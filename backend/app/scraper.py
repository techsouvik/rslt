import httpx
import re
import logging

# Setup module logger
logger = logging.getLogger(__name__)

async def scrape_website(url: str) -> str:
    """
    Asynchronously scrapes the given website landing page.
    Attempts to fetch raw text content using httpx and extracts readable information.
    """
    logger.info(f"Initiating website scrape for URL: {url}")
    
    # Increment API calls counter in Redis if job is active
    try:
        from .agents import current_job_id
        from .redis_client import RedisManager
        job_id = current_job_id.get()
        if job_id:
            RedisManager().increment_job_api_calls(job_id)
    except Exception as metric_err:
        logger.warning(f"Failed to increment API call counter for scraping: {metric_err}")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            logger.debug(f"Sending HTTP GET request to {url}")
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Scrape request failed for {url}. HTTP Status Code: {response.status_code}")
                return f"Error: Scrape request failed with status code {response.status_code}"
            
            logger.info(f"Successfully fetched URL {url}. Content size: {len(response.text)} bytes.")
            
            # Simple, deterministic HTML-to-text cleaner
            html = response.text
            
            # Remove scripts and styles
            logger.debug("Cleaning HTML: stripping out script and style tags")
            html = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
            
            # Extract basic body content
            body_match = re.search(r"<body.*?>(.*?)</body>", html, flags=re.DOTALL | re.IGNORECASE)
            content = body_match.group(1) if body_match else html
            
            # Remove all tags to keep only inner text
            logger.debug("Cleaning HTML: stripping tags and normalizing whitespace")
            clean_text = re.sub(r"<.*?>", " ", content)
            
            # Collapse whitespace
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            
            logger.info(f"Finished parsing HTML. Clean text length: {len(clean_text)} characters.")
            
            # Slice first 4000 characters to keep context size clean for Gemini 3.5 Flash
            truncated_text = clean_text[:4000]
            if len(clean_text) > 4000:
                logger.debug("Scraped text length exceeds 4000 characters, truncating to prevent context bloat.")
                
            return truncated_text
            
    except httpx.RequestError as exc:
        logger.error(f"Network error occurred while scraping {url}: {exc}", exc_info=True)
        return f"Scraper error occurred: Network request failed: {str(exc)}"
    except Exception as e:
        logger.error(f"Unexpected error while scraping {url}: {e}", exc_info=True)
        return f"Scraper error occurred: {str(e)}"
