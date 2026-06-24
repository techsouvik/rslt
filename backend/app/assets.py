import httpx
import logging
import asyncio
import hashlib
from typing import Optional
from .config import settings
from .redis_client import get_redis_connection

# Setup module logger
logger = logging.getLogger(__name__)

def _get_cache_key(prefix: str, query: str) -> str:
    """
    Generates a secure, normalized cache key for Redis.
    """
    normalized = query.strip().lower()
    query_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
    return f"cache:asset:{prefix}:{query_hash}"

async def _fetch_with_retry_and_cache(
    prefix: str,
    query: str,
    fetch_func,  # async callable that takes no arguments and returns the raw URL
    fallback_url: str,
    ttl: int = 86400  # Default to 24 hours TTL
) -> Optional[str]:
    """
    Universal asset fetcher wrapper that implements:
    1. Redis Caching to completely prevent external network requests for identical queries.
    2. Exponential backoff and auto-retry on 429 rate limits or transient connection issues.
    3. Seamless and resilient fallback mechanisms on structural failures.
    """
    cache_key = _get_cache_key(prefix, query)
    
    # 1. Try to read from Redis cache
    try:
        r = get_redis_connection()
        cached_url = r.get(cache_key)
        if cached_url:
            logger.info(f"Cache HIT for asset cache. prefix='{prefix}', query='{query}'. Key: '{cache_key}'")
            return cached_url
    except Exception as e:
        logger.warning(f"Transient Redis read error while checking cache for prefix='{prefix}': {e}")

    # 2. Execute fetch with exponential backoff on transient errors or 429 rate limits
    max_retries = 3
    delay = 1.0  # Starts at 1 second
    result_url = None
    
    logger.info(f"Cache MISS for prefix='{prefix}', query='{query}'. Initiating API query with rate-limit backoff handler.")
    
    # Increment API calls counter in Redis on cache miss if job is active
    try:
        from .agents import current_job_id
        from .redis_client import RedisManager
        job_id = current_job_id.get()
        if job_id:
            RedisManager().increment_job_api_calls(job_id)
    except Exception as metric_err:
        logger.warning(f"Failed to increment API call counter on cache miss for '{prefix}': {metric_err}")
    
    for attempt in range(1, max_retries + 1):
        try:
            result_url = await fetch_func()
            if result_url:
                break
        except httpx.HTTPStatusError as hse:
            status_code = hse.response.status_code
            if status_code == 429:
                logger.warning(f"Rate limited (HTTP 429) on '{prefix}' search for query='{query}' [Attempt {attempt}/{max_retries}]. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2.0
            else:
                logger.error(f"HTTP error {status_code} occurred while querying '{prefix}' API for query='{query}': {hse.response.text}")
                break
        except (httpx.RequestError, asyncio.TimeoutError) as transient_err:
            logger.warning(f"Transient connection error on '{prefix}' API [Attempt {attempt}/{max_retries}]: {transient_err}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay *= 2.0
        except Exception as e:
            logger.error(f"Unrecoverable error during '{prefix}' API execution for query='{query}': {e}", exc_info=True)
            break

    # 3. Write successful results to Redis cache with TTL
    if result_url:
        try:
            r = get_redis_connection()
            r.setex(cache_key, ttl, result_url)
            logger.info(f"Successfully cached retrieved asset. prefix='{prefix}', query='{query}' -> TTL={ttl}s")
            return result_url
        except Exception as e:
            logger.warning(f"Transient Redis write error while saving cache key '{cache_key}': {e}")
            return result_url

    # 4. Ultimate fallback in case the API request failed completely
    logger.warning(f"All retries failed or no asset was found for '{prefix}' query='{query}'. Activating ultimate fallback.")
    return fallback_url

def sanitize_background_query(query: str) -> str:
    """
    Sanitizes the stock video query to ensure no human subjects, faces, or people are requested,
    forcing pure ambient, flatlay, background, nature, or abstract aesthetic terms.
    """
    forbidden_words = {
        "man", "woman", "person", "people", "guy", "girl", "boy", "speaker", 
        "interview", "face", "talking", "human", "model", "actor", "actress", 
        "worker", "developer", "programmer", "gym bro", "user", "client", 
        "patient", "doctor", "coach", "trainer", "audience", "crowd"
    }
    
    # Split query into words
    words = query.lower().replace(",", " ").replace("-", " ").split()
    
    # Filter out forbidden words
    clean_words = []
    for w in words:
        # Check if the word or its singular/plural form is forbidden
        # Simple plural check: stripping 's'
        normalized_w = w.rstrip('s')
        if normalized_w in forbidden_words or w in forbidden_words:
            continue
        clean_words.append(w)
        
    # If the clean_words became empty, fallback to a safe general background search query
    if not clean_words:
        return "aesthetic vertical background ambient"
        
    # Append helpful ambient/flatlay/aesthetic vertical stock video terms to reinforce clean backgrounds
    # and prevent Pexels from matching human subjects.
    clean_query = " ".join(clean_words)
    
    # Ensure background indicators are present
    vibe_words = ["background", "ambient", "aesthetic", "flatlay", "scenery", "texture", "loop"]
    if not any(v in clean_query for v in vibe_words):
        clean_query += " aesthetic vertical background ambient"
        
    return clean_query

async def fetch_pexels_video(query: str) -> Optional[str]:
    """
    Queries Pexels API for a vertical high-quality stock video matching the query.
    Returns the URL of the vertical video stream file.
    """
    # Sanitize query to force clean background-type videos without humans
    sanitized_query = sanitize_background_query(query)
    logger.info(f"Pexels search query sanitized: '{query}' -> '{sanitized_query}'")
    
    fallback_url = "https://assets.mixkit.co/videos/preview/mixkit-clouds-and-blue-sky-background-2410-large.mp4"
    
    async def _fetch_pexels() -> Optional[str]:
        api_key = settings.PEXELS_API_KEY
        if not api_key or api_key == "YOUR_PEXELS_KEY":
            logger.warning("Pexels API Key is missing or default placeholder value is found. Activating fallback instantly.")
            return fallback_url
            
        url = f"https://api.pexels.com/videos/search?query={sanitized_query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()  # Triggers HTTPStatusError for non-2xx status codes (including 429)
            
            data = response.json()
            videos = data.get("videos", [])
            if videos:
                # Select the highest resolution MP4 vertical stream
                video_files = videos[0].get("video_files", [])
                mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
                if mp4_files:
                    # Sort by width descending
                    mp4_files.sort(key=lambda x: x.get("width", 0), reverse=True)
                    selected_url = mp4_files[0].get("link")
                    logger.info(f"Retrieved vertical MP4 video link from Pexels API: {selected_url}")
                    return selected_url
                else:
                    logger.warning(f"No suitable mp4 file format found in Pexels results for query '{sanitized_query}'")
            else:
                logger.warning(f"Zero video results returned by Pexels for query '{sanitized_query}'")
            return None

    return await _fetch_with_retry_and_cache(
        prefix="pexels",
        query=sanitized_query,
        fetch_func=_fetch_pexels,
        fallback_url=fallback_url
    )

async def fetch_giphy_gif(query: str) -> Optional[str]:
    """
    Queries Giphy API v1 Stickers Search endpoint for a high-quality transparent overlay sticker matching the query.
    Retrieves up to 20 candidates, randomly shuffles them, and lets an Agno Multimodal agent select from 5 shuffled choices.
    """
    fallback_pool = [
        "https://media.giphy.com/media/uhLADEafPVzRA0nWEb/giphy.gif",  # Confused Math Lady
        "https://media.giphy.com/media/3kzJvEcifI9ACKIFi9/giphy.gif",  # Shocked Pikachu
        "https://media.giphy.com/media/OPU6wUKdXaoVy/giphy.gif",      # Crying Cat
        "https://media.giphy.com/media/t3mzO2mK7fRCw/giphy.gif",      # Success Kid
        "https://media.giphy.com/media/COYGe9rQbsiLC/giphy.gif",      # Homer Simpson backing into bush
        "https://media.giphy.com/media/3o72F8tGP5fUe0U8bC/giphy.gif",  # This is Fine Dog
        "https://media.giphy.com/media/d3mlE7uhX8KFgEmY/giphy.gif",    # Roll Safe smart guy tapping head
        "https://media.giphy.com/media/l0HlIDueXMCWRNSec/giphy.gif",  # Mocking Spongebob
        "https://media.giphy.com/media/138K6MAsYWNKKI/giphy.gif",      # Minion Celebrating
        "https://media.giphy.com/media/3o85xGocUH8TCQDDry/giphy.gif",  # Kermit sipping tea
        "https://media.giphy.com/media/oD3l3n06ceuk8/giphy.gif",      # Doge Confused
        "https://media.giphy.com/media/12A3hKKsewxtGE/giphy.gif"       # Barney Stinson Challenge Accepted
    ]
    import random
    fallback_url = random.choice(fallback_pool)
    
    async def _fetch_giphy() -> Optional[str]:
        api_key = settings.GIPHY_API_KEY
        if not api_key or api_key in ["YOUR_GIPHY_KEY", "your_giphy_api_key_here", ""]:
            logger.warning("Giphy API Key is missing or default placeholder value is found. Activating fallback instantly.")
            return fallback_url
            
        # Use Giphy Stickers search API with a limit of 20 to allow rich candidate variety
        url = f"https://api.giphy.com/v1/stickers/search?api_key={api_key}&q={query}&limit=20"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("data", [])
            if not results:
                logger.warning(f"Zero sticker results returned by Giphy for query '{query}'")
                return None
                
            # Randomize/shuffle results so different candidates are analyzed on each run
            random.shuffle(results)
            results = results[:5] # Keep at most 5 candidates for AI multimodal review
            
            # If only 1 result remains, bypass review to save time and API costs
            if len(results) == 1:
                gif_url = results[0].get("images", {}).get("original", {}).get("url")
                if gif_url:
                    clean_url = gif_url.split("?")[0] if "?" in gif_url else gif_url
                    logger.info(f"Retrieved single transparent sticker link from Giphy API: {clean_url}")
                    return clean_url
                else:
                    logger.warning(f"No valid sticker URL found in single Giphy result for query '{query}'")
                    return None
            
            # Extract GIF URLs for candidate sticker assets
            candidate_gifs = []
            for r in results:
                gif_url = r.get("images", {}).get("original", {}).get("url")
                if gif_url:
                    clean_url = gif_url.split("?")[0] if "?" in gif_url else gif_url
                    candidate_gifs.append(clean_url)
                    
            if not candidate_gifs:
                return None
                
            logger.info(f"Giphy returned {len(candidate_gifs)} sticker candidates. Processing first-frame extraction in parallel...")
            
            # Helper to download GIF and extract its first frame as PNG bytes
            async def download_and_extract_frame(url_candidate: str) -> Optional[bytes]:
                try:
                    # Increment API calls counter for candidate download if job is active
                    try:
                        from .agents import current_job_id
                        from .redis_client import RedisManager
                        job_id = current_job_id.get()
                        if job_id:
                            RedisManager().increment_job_api_calls(job_id)
                    except Exception as metric_err:
                        logger.warning(f"Failed to increment API call counter for frame download: {metric_err}")

                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as d_client:
                        resp = await d_client.get(url_candidate)
                        if resp.status_code == 200:
                            from PIL import Image as PILImage
                            import io
                            img = PILImage.open(io.BytesIO(resp.content))
                            img.seek(0)
                            out_buf = io.BytesIO()
                            img.save(out_buf, format="PNG")
                            return out_buf.getvalue()
                except Exception as ex:
                    logger.warning(f"Failed to download/extract frame for {url_candidate}: {ex}")
                return None

            tasks = [download_and_extract_frame(u) for u in candidate_gifs]
            frames = await asyncio.gather(*tasks)
            
            # Compile valid candidates with frame bytes
            valid_candidates = []
            for idx, frame_bytes in enumerate(frames):
                if frame_bytes:
                    valid_candidates.append({
                        "url": candidate_gifs[idx],
                        "frame_bytes": frame_bytes
                    })
                    
            if not valid_candidates:
                logger.warning("All frame processing attempts failed. Defaulting to first candidate.")
                return candidate_gifs[0]
                
            if len(valid_candidates) == 1:
                logger.info("Only 1 valid candidate processed successfully. Returning it.")
                return valid_candidates[0]["url"]
                
            # Run Agno Multimodal Giphy Review Agent!
            try:
                from .agents import giphy_review_agent, Image
                
                logger.info(f"Invoking Agno Multimodal Giphy Review Agent on {len(valid_candidates)} candidates...")
                agent_images = [Image(content=c["frame_bytes"]) for c in valid_candidates]
                
                review_resp = giphy_review_agent.run(
                    f"Review these {len(valid_candidates)} candidate sticker first frames for search query '{query}' and select the single best one that features a clear central subject (human, character, animal, puppet, or object).",
                    images=agent_images
                )
                
                # Increment tokens in Redis if job is active
                try:
                    from .agents import current_job_id
                    from .redis_client import RedisManager
                    job_id = current_job_id.get()
                    if job_id and review_resp and hasattr(review_resp, "metrics") and review_resp.metrics:
                        in_t = review_resp.metrics.input_tokens or 0
                        out_t = review_resp.metrics.output_tokens or 0
                        RedisManager().increment_job_tokens(job_id, in_t, out_t)
                except Exception as metric_err:
                    logger.warning(f"Failed to increment token metrics for Giphy Review Agent: {metric_err}")

                selected_idx = int(review_resp.content.selected_index) - 1 # 1-based to 0-based index
                reason = review_resp.content.reason
                
                if 0 <= selected_idx < len(valid_candidates):
                    chosen_url = valid_candidates[selected_idx]["url"]
                    logger.info(f"Agno Giphy Agent selected candidate #{selected_idx + 1}: {chosen_url}. Reason: {reason}")
                    return chosen_url
                else:
                    logger.warning(f"Agno Giphy Agent returned out-of-bounds selected_index={selected_idx + 1}. Defaulting to first candidate.")
                    return valid_candidates[0]["url"]
            except Exception as review_err:
                logger.error(f"Error occurred during Agno multimodal Giphy sticker review: {review_err}. Defaulting to first candidate.")
                return valid_candidates[0]["url"]

    return await _fetch_with_retry_and_cache(
        prefix="giphy_sticker",
        query=query,
        fetch_func=_fetch_giphy,
        fallback_url=fallback_url
    )

async def fetch_tenor_gif(query: str) -> Optional[str]:
    """
    Queries GIF search endpoint. Automatically routes to Giphy Stickers Search if GIPHY_API_KEY is configured,
    otherwise falls back to Tenor refined with 'transparent sticker' queries.
    Retrieves up to 20 candidates, randomly shuffles them, and lets an Agno Multimodal agent select from 5 shuffled choices.
    """
    if settings.GIPHY_API_KEY and settings.GIPHY_API_KEY not in ["", "your_giphy_api_key_here", "YOUR_GIPHY_KEY"]:
        logger.info("Routing GIF search request to Giphy Stickers search API.")
        return await fetch_giphy_gif(query)
        
    fallback_pool = [
        "https://media.giphy.com/media/uhLADEafPVzRA0nWEb/giphy.gif",  # Confused Math Lady
        "https://media.giphy.com/media/3kzJvEcifI9ACKIFi9/giphy.gif",  # Shocked Pikachu
        "https://media.giphy.com/media/OPU6wUKdXaoVy/giphy.gif",      # Crying Cat
        "https://media.giphy.com/media/t3mzO2mK7fRCw/giphy.gif",      # Success Kid
        "https://media.giphy.com/media/COYGe9rQbsiLC/giphy.gif",      # Homer Simpson backing into bush
        "https://media.giphy.com/media/3o72F8tGP5fUe0U8bC/giphy.gif",  # This is Fine Dog
        "https://media.giphy.com/media/d3mlE7uhX8KFgEmY/giphy.gif",    # Roll Safe smart guy tapping head
        "https://media.giphy.com/media/l0HlIDueXMCWRNSec/giphy.gif",  # Mocking Spongebob
        "https://media.giphy.com/media/138K6MAsYWNKKI/giphy.gif",      # Minion Celebrating
        "https://media.giphy.com/media/3o85xGocUH8TCQDDry/giphy.gif",  # Kermit sipping tea
        "https://media.giphy.com/media/oD3l3n06ceuk8/giphy.gif",      # Doge Confused
        "https://media.giphy.com/media/12A3hKKsewxtGE/giphy.gif"       # Barney Stinson Challenge Accepted
    ]
    import random
    fallback_url = random.choice(fallback_pool)
    
    async def _fetch_tenor() -> Optional[str]:
        api_key = settings.TENOR_API_KEY
        if not api_key or api_key in ["YOUR_TENOR_KEY", "your_tenor_api_key_here", ""]:
            logger.warning("Tenor API Key is missing or default placeholder value is found. Activating fallback instantly.")
            return fallback_url
            
        # Refine query for Tenor to ensure transparent background stickers are prioritized
        tenor_query = query
        if "sticker" not in tenor_query.lower() and "transparent" not in tenor_query.lower():
            tenor_query = f"{tenor_query} transparent sticker"
            
        # Use searchfilter=sticker,-static to guarantee Tenor only returns animated transparent cutout stickers
        # Retrieve up to 20 sticker candidates for rich candidate variety
        url = f"https://tenor.googleapis.com/v2/search?q={tenor_query}&key={api_key}&limit=20&searchfilter=sticker,-static"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            if not results:
                logger.warning(f"Zero sticker results returned by Tenor for query '{tenor_query}'")
                return None
                
            # Randomize/shuffle results so different candidates are analyzed on each run
            random.shuffle(results)
            results = results[:5] # Keep at most 5 candidates for AI multimodal review
            
            # If only 1 result remains, bypass review to save time and API costs
            if len(results) == 1:
                media_formats = results[0].get("media_formats", {})
                gif_format = media_formats.get("gif", {})
                gif_url = gif_format.get("url")
                if gif_url:
                    logger.info(f"Retrieved single transparent sticker link from Tenor API: {gif_url}")
                    return gif_url
                else:
                    logger.warning(f"No valid sticker format found in Tenor result for query '{tenor_query}'")
                    return None
            
            # Extract GIF URLs for candidate Tenor assets
            candidate_gifs = []
            for r in results:
                media_formats = r.get("media_formats", {})
                gif_format = media_formats.get("gif", {})
                gif_url = gif_format.get("url")
                if gif_url:
                    candidate_gifs.append(gif_url)
                    
            if not candidate_gifs:
                return None
                
            logger.info(f"Tenor returned {len(candidate_gifs)} sticker candidates. Processing first-frame extraction in parallel...")
            
            # Helper to download GIF and extract its first frame as PNG bytes
            async def download_and_extract_frame(url_candidate: str) -> Optional[bytes]:
                try:
                    # Increment API calls counter for candidate download if job is active
                    try:
                        from .agents import current_job_id
                        from .redis_client import RedisManager
                        job_id = current_job_id.get()
                        if job_id:
                            RedisManager().increment_job_api_calls(job_id)
                    except Exception as metric_err:
                        logger.warning(f"Failed to increment API call counter for frame download: {metric_err}")

                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as d_client:
                        resp = await d_client.get(url_candidate)
                        if resp.status_code == 200:
                            from PIL import Image as PILImage
                            import io
                            img = PILImage.open(io.BytesIO(resp.content))
                            img.seek(0)
                            out_buf = io.BytesIO()
                            img.save(out_buf, format="PNG")
                            return out_buf.getvalue()
                except Exception as ex:
                    logger.warning(f"Failed to download/extract frame for {url_candidate}: {ex}")
                return None

            tasks = [download_and_extract_frame(u) for u in candidate_gifs]
            frames = await asyncio.gather(*tasks)
            
            # Compile valid candidates with frame bytes
            valid_candidates = []
            for idx, frame_bytes in enumerate(frames):
                if frame_bytes:
                    valid_candidates.append({
                        "url": candidate_gifs[idx],
                        "frame_bytes": frame_bytes
                    })
                    
            if not valid_candidates:
                logger.warning("All frame processing attempts failed. Defaulting to first candidate.")
                return candidate_gifs[0]
                
            if len(valid_candidates) == 1:
                logger.info("Only 1 valid candidate processed successfully. Returning it.")
                return valid_candidates[0]["url"]
                
            # Run Agno Multimodal Giphy Review Agent!
            try:
                from .agents import giphy_review_agent, Image
                
                logger.info(f"Invoking Agno Multimodal Giphy Review Agent on {len(valid_candidates)} Tenor candidates...")
                agent_images = [Image(content=c["frame_bytes"]) for c in valid_candidates]
                
                review_resp = giphy_review_agent.run(
                    f"Review these {len(valid_candidates)} candidate Tenor sticker first frames for query '{query}' and select the single best one that features a clear central subject (human, character, animal, puppet, or object).",
                    images=agent_images
                )
                
                # Increment tokens in Redis if job is active
                try:
                    from .agents import current_job_id
                    from .redis_client import RedisManager
                    job_id = current_job_id.get()
                    if job_id and review_resp and hasattr(review_resp, "metrics") and review_resp.metrics:
                        in_t = review_resp.metrics.input_tokens or 0
                        out_t = review_resp.metrics.output_tokens or 0
                        RedisManager().increment_job_tokens(job_id, in_t, out_t)
                except Exception as metric_err:
                    logger.warning(f"Failed to increment token metrics for Giphy Review Agent: {metric_err}")

                selected_idx = int(review_resp.content.selected_index) - 1 # 1-based to 0-based index
                reason = review_resp.content.reason
                
                if 0 <= selected_idx < len(valid_candidates):
                    chosen_url = valid_candidates[selected_idx]["url"]
                    logger.info(f"Agno Giphy Agent selected Tenor candidate #{selected_idx + 1}: {chosen_url}. Reason: {reason}")
                    return chosen_url
                else:
                    logger.warning(f"Agno Giphy Agent returned out-of-bounds selected_index={selected_idx + 1}. Defaulting to first candidate.")
                    return valid_candidates[0]["url"]
            except Exception as review_err:
                logger.error(f"Error occurred during Agno multimodal Tenor sticker review: {review_err}. Defaulting to first candidate.")
                return valid_candidates[0]["url"]

    return await _fetch_with_retry_and_cache(
        prefix="tenor_sticker",
        query=query,
        fetch_func=_fetch_tenor,
        fallback_url=fallback_url
    )

