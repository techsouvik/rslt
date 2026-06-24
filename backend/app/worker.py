import os
import shutil
import asyncio
import traceback
import logging
from typing import Dict, Any, Optional
from .config import settings
from .redis_client import RedisManager
from .mongo_client import MongoManager
from .scraper import scrape_website
from .agents import product_agent, creative_agent, judge_agent, ProductBrief, CreativeConceptsList, SelectedConceptAndPlan
from .assets import fetch_pexels_video, fetch_tenor_gif
from .renderer import FFmpegRenderer

# Setup module logger
logger = logging.getLogger(__name__)

# Create a static dir served by FastAPI for locally rendered output videos
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
logger.info(f"Background worker static directory established at: {STATIC_DIR}")

class BackgroundWorker:
    def __init__(self):
        self.redis = RedisManager()
        self.mongo = MongoManager()
        logger.info("BackgroundWorker class initialized with Redis and MongoDB managers.")

    async def upload_to_uploadthing(self, file_path: str, api_key: str) -> Optional[str]:
        """
        Uploads a file to uploadthing.com using the REST API v6 presigned URL mechanism.
        Returns the public CDN URL of the uploaded file on success, or None on failure.
        """
        import os
        import httpx
        import base64
        import json
        
        # Detect if the provided key is a base64-encoded token wrapper (typically starting with eyJ)
        if api_key.startswith("eyJ"):
            logger.info("Detected base64-encoded UploadThing token. Decoding to extract API key...")
            try:
                # Add padding if needed
                padded_key = api_key + "=" * (-len(api_key) % 4)
                decoded_bytes = base64.b64decode(padded_key)
                decoded_str = decoded_bytes.decode("utf-8")
                token_data = json.loads(decoded_str)
                if isinstance(token_data, dict) and "apiKey" in token_data:
                    api_key = token_data["apiKey"]
                    logger.info("Successfully extracted apiKey from the base64 UploadThing token.")
                else:
                    logger.warning("Decoded token JSON does not contain 'apiKey' key.")
            except Exception as e:
                logger.error(f"Failed to decode base64 UploadThing token: {e}. Will attempt using the token as-is.")

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # 1. Request presigned upload URL via v7 prepareUpload
        headers = {
            "x-uploadthing-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "fileName": file_name,
            "fileSize": file_size,
            "fileType": "video/mp4"
        }
        
        api_url = "https://api.uploadthing.com/v7/prepareUpload"
        
        logger.info(f"Requesting presigned upload URL from UploadThing (v7) for '{file_name}'...")
        try:
            # Increment API calls count for UploadThing prepareUpload
            try:
                from .agents import current_job_id
                job_id = current_job_id.get()
                if job_id:
                    self.redis.increment_job_api_calls(job_id)
            except Exception as e:
                logger.warning(f"Failed to increment API call count for prepareUpload: {e}")

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(api_url, json=payload, headers=headers)
                if response.status_code != 200:
                    logger.error(f"Failed to request presigned upload URL: {response.status_code} - {response.text}")
                    return None
                    
                data = response.json()
                logger.debug(f"UploadThing v7 response: {data}")
                
                upload_url = data.get("url")
                file_key = data.get("key")
                
                if not upload_url or not file_key:
                    logger.error(f"Invalid upload presigned info returned from UploadThing: {data}")
                    return None
                    
                # 2. Upload file bytes to the presigned URL via PUT (as multipart/form-data for the v7 Ingest Server)
                logger.info(f"Uploading file bytes ({file_size} bytes) to presigned URL via multipart PUT...")
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                    
                files = {
                    "file": (file_name, file_bytes, "video/mp4")
                }
                
                # Increment API calls count for UploadThing PUT upload
                try:
                    from .agents import current_job_id
                    job_id = current_job_id.get()
                    if job_id:
                        self.redis.increment_job_api_calls(job_id)
                except Exception as e:
                    logger.warning(f"Failed to increment API call count for PUT upload: {e}")

                put_response = await client.put(upload_url, files=files)
                if put_response.status_code not in [200, 201, 204]:
                    logger.error(f"Failed to upload bytes to presigned URL: {put_response.status_code} - {put_response.text}")
                    return None
                    
                # Dynamically retrieve CDN url from UploadThing response or fall back to standard format
                try:
                    res_json = put_response.json()
                    public_url = res_json.get("url") or f"https://utfs.io/f/{file_key}"
                except Exception:
                    public_url = f"https://utfs.io/f/{file_key}"
                    
                logger.info(f"Upload to UploadThing successful! Public CDN URL: {public_url}")
                return public_url
        except Exception as e:
            logger.error(f"Exception during UploadThing uploading: {e}", exc_info=True)
            return None


    async def update_status(self, job_id: str, status: str, progress: int, message: str, video_url: str = "", details: Optional[Dict[str, Any]] = None):
        """
        Unified status updater.
        Synchronizes Redis (for fast PubSub SSE) and MongoDB (for robust non-blocking storage) simultaneously.
        """
        logger.info(f"[{job_id}] Synchronized status update -> {status} ({progress}%) - '{message}'")
        try:
            # 1. Update Redis (Triggers PubSub to SSE)
            self.redis.update_job_status(
                job_id=job_id,
                status=status,
                progress=progress,
                message=message,
                video_url=video_url,
                details=details
            )
        except Exception as e:
            logger.error(f"[{job_id}] Redis status sync failed: {e}", exc_info=True)

        # Retrieve latest metrics from Redis to sync with MongoDB
        extra_data = {}
        try:
            redis_job = self.redis.get_job(job_id)
            if redis_job:
                extra_data = {
                    "api_calls_count": redis_job.get("api_calls_count", 0),
                    "input_tokens_burned": redis_job.get("input_tokens_burned", 0),
                    "output_tokens_burned": redis_job.get("output_tokens_burned", 0),
                    "total_tokens_burned": redis_job.get("total_tokens_burned", 0)
                }
        except Exception as e:
            logger.warning(f"Failed to retrieve Redis metrics to sync with MongoDB for job {job_id}: {e}")

        try:
            # 2. Update MongoDB asynchronously
            await self.mongo.update_job_status(
                job_id=job_id,
                status=status,
                progress=progress,
                message=message,
                video_url=video_url,
                details=details,
                extra_data=extra_data
            )
        except Exception as e:
            logger.error(f"[{job_id}] MongoDB status sync failed: {e}", exc_info=True)

    async def process_job(self, job_id: str):
        """Sequential 3-agent and rendering workflow execution."""
        logger.info(f"[{job_id}] Received job. Commencing UGC video processing sequence.")
        
        # Set the current job context variable so that it's accessible globally in this task
        from .agents import current_job_id
        current_job_id.set(job_id)
        
        # Initialize cumulative details dictionary for rich UI monitoring
        details = {
            "scraped_stats": None,
            "product_brief": None,
            "brainstormed_concepts": None,
            "winner_selection": None,
            "video_plan": None,
            "assets": None,
            "rendering_stats": None
        }

        try:
            logger.debug(f"[{job_id}] Pulling job details from Redis.")
            job = self.redis.get_job(job_id)
            if not job:
                logger.error(f"[{job_id}] Job data not found in Redis. Attempting to fall back to MongoDB.")
                job = await self.mongo.get_job(job_id)
                
            if not job:
                logger.error(f"[{job_id}] Job data not found in either Redis or MongoDB. Aborting job processing.")
                return

            product_url = job.get("product_url", "")
            custom_instructions = job.get("custom_instructions", "")
            chat_id = job.get("chat_id", "default_chat")
            
            logger.info(f"[{job_id}] Processing details: url='{product_url}', custom_instructions='{custom_instructions}', chat_id='{chat_id}'")

            # 1. Initialize Job record inside MongoDB
            await self.mongo.create_job(
                job_id=job_id,
                product_url=product_url,
                custom_instructions=custom_instructions,
                chat_id=chat_id
            )

            # ----------------------------------------------------
            # Step 1: Scrape landing page
            # ----------------------------------------------------
            msg = f"Extracting website landing page text from {product_url}..."
            await self.update_status(
                job_id=job_id,
                status="ANALYZING_PRODUCT",
                progress=10,
                message=msg,
                details=details
            )
            scraped_text = await scrape_website(product_url)
            logger.debug(f"[{job_id}] Scraped text sample: {scraped_text[:150]}...")

            scraped_char_count = len(scraped_text)
            scraped_word_count = len(scraped_text.split())
            details["scraped_stats"] = {
                "url": product_url,
                "character_count": scraped_char_count,
                "word_count": scraped_word_count,
                "status": "success" if scraped_char_count > 0 else "empty_or_failed"
            }

            await self.update_status(
                job_id=job_id,
                status="ANALYZING_PRODUCT",
                progress=20,
                message=f"Landing page scraped successfully. Analyzed {scraped_word_count} words.",
                details=details
            )

            # ----------------------------------------------------
            # Step 2: Product Agent brief extraction
            # ----------------------------------------------------
            msg = "Product Agent compiling structured brief..."
            await self.update_status(
                job_id=job_id,
                status="ANALYZING_PRODUCT",
                progress=30,
                message=msg,
                details=details
            )
            
            logger.debug(f"[{job_id}] Invoking ProductAgent...")
            brief_resp = product_agent.run(
                f"Extract product metrics from URL: {product_url}\n\nContent:\n{scraped_text}"
            )
            
            # Increment tokens in Redis if successful
            try:
                if brief_resp and hasattr(brief_resp, "metrics") and brief_resp.metrics:
                    in_t = brief_resp.metrics.input_tokens or 0
                    out_t = brief_resp.metrics.output_tokens or 0
                    self.redis.increment_job_tokens(job_id, in_t, out_t)
            except Exception as e:
                logger.warning(f"Failed to increment job tokens for product_agent: {e}")

            product_brief: ProductBrief = brief_resp.content
            logger.info(f"[{job_id}] Product Brief compiled successfully. Product Name: {product_brief.product}, Category: {product_brief.category}")
            logger.debug(f"[{job_id}] Brief details: {product_brief.model_dump_json()}")

            # Sync intermediate product brief metadata
            details["product_brief"] = product_brief.model_dump()
            await self.update_status(
                job_id=job_id,
                status="ANALYZING_PRODUCT",
                progress=40,
                message=f"Product Agent compiled structured brief for {product_brief.product}.",
                details=details
            )

            # ----------------------------------------------------
            # Step 3: Creative Agent concepts brainstorming
            # ----------------------------------------------------
            msg = "Creative Agent brainstorming viral short-form structures..."
            await self.update_status(
                job_id=job_id,
                status="GENERATING_CONCEPTS",
                progress=45,
                message=msg,
                details=details
            )
            
            prompt = f"Product Brief:\n{product_brief.model_dump_json()}"
            if custom_instructions:
                prompt += f"\n\nUser Custom Vibe/Angle Requested: {custom_instructions}"
                
            logger.debug(f"[{job_id}] Invoking CreativeAgent...")
            concepts_resp = creative_agent.run(prompt)
            
            # Increment tokens in Redis if successful
            try:
                if concepts_resp and hasattr(concepts_resp, "metrics") and concepts_resp.metrics:
                    in_t = concepts_resp.metrics.input_tokens or 0
                    out_t = concepts_resp.metrics.output_tokens or 0
                    self.redis.increment_job_tokens(job_id, in_t, out_t)
            except Exception as e:
                logger.warning(f"Failed to increment job tokens for creative_agent: {e}")

            concepts_list: CreativeConceptsList = concepts_resp.content
            logger.info(f"[{job_id}] Brainstormed {len(concepts_list.concepts)} viral concepts successfully.")
            logger.debug(f"[{job_id}] Brainstormed concepts: {concepts_list.model_dump_json()}")

            # Sync brainstormed creative concepts
            details["brainstormed_concepts"] = concepts_list.model_dump()
            await self.update_status(
                job_id=job_id,
                status="GENERATING_CONCEPTS",
                progress=55,
                message=f"Creative Agent brainstormed {len(concepts_list.concepts)} viral layouts.",
                details=details
            )

            # ----------------------------------------------------
            # Step 4: Judge Agent winner selection & Video Plan contract compilation
            # ----------------------------------------------------
            msg = "Judge Agent scoring and compiling final video plan..."
            await self.update_status(
                job_id=job_id,
                status="SELECTING_CONCEPT",
                progress=65,
                message=msg,
                details=details
            )
            judge_prompt = (
                f"Evaluate these concepts:\n{concepts_list.model_dump_json()}\n\n"
                f"Choose the single most funny and relatable one, score it, and compile the final VideoPlan contract.\n\n"
                f"USER CUSTOM VIBE/PLACEMENT OPTIONS: {custom_instructions if custom_instructions else 'None specified.'}\n"
                f"Strictly respect any specific fonts, positions, sizes, or Giphy preferences requested by the user."
            )
            
            logger.debug(f"[{job_id}] Invoking JudgeAgent...")
            judge_resp = judge_agent.run(judge_prompt)
            
            # Increment tokens in Redis if successful
            try:
                if judge_resp and hasattr(judge_resp, "metrics") and judge_resp.metrics:
                    in_t = judge_resp.metrics.input_tokens or 0
                    out_t = judge_resp.metrics.output_tokens or 0
                    self.redis.increment_job_tokens(job_id, in_t, out_t)
            except Exception as e:
                logger.warning(f"Failed to increment job tokens for judge_agent: {e}")

            selection_and_plan: SelectedConceptAndPlan = judge_resp.content
            video_plan = selection_and_plan.video_plan
            logger.info(f"[{job_id}] Selected winner concept index={selection_and_plan.winner_index} (Score: {selection_and_plan.score}/100)")
            logger.info(f"[{job_id}] Choice reason: '{selection_and_plan.reason}'")
            logger.debug(f"[{job_id}] Final Video Plan compiled: {video_plan.model_dump_json()}")

            # Sync selected concept evaluation metadata
            details["winner_selection"] = {
                "index": selection_and_plan.winner_index,
                "score": selection_and_plan.score,
                "reason": selection_and_plan.reason
            }
            details["video_plan"] = video_plan.model_dump()
            
            await self.update_status(
                job_id=job_id,
                status="SELECTING_CONCEPT",
                progress=75,
                message=f"Concept #{selection_and_plan.winner_index + 1} selected as winner with score {selection_and_plan.score}/100.",
                details=details
            )

            # ----------------------------------------------------
            # Step 5: Asset Service acquisition
            # ----------------------------------------------------
            msg = f"Retrieving stock video for query '{video_plan.backgroundSearch}'..."
            await self.update_status(
                job_id=job_id,
                status="ACQUIRING_ASSETS",
                progress=80,
                message=msg,
                details=details
            )
            
            logger.debug(f"[{job_id}] Dispatching asset API queries...")
            video_url = await fetch_pexels_video(video_plan.backgroundSearch)
            gif_url = await fetch_tenor_gif(video_plan.gifSearch)
            logger.info(f"[{job_id}] Asset urls successfully retrieved. Video URL: {video_url}, GIF URL: {gif_url}")

            # Sync assets details
            details["assets"] = {
                "video_url": video_url,
                "gif_url": gif_url,
                "background_search": video_plan.backgroundSearch,
                "gif_search": video_plan.gifSearch
            }

            await self.update_status(
                job_id=job_id,
                status="ACQUIRING_ASSETS",
                progress=85,
                message="Stock video and meme GIF successfully loaded from APIs.",
                details=details
            )

            # ----------------------------------------------------
            # Step 6: FFmpeg Rendering Composition
            # ----------------------------------------------------
            msg = "FFmpeg stitching layers, text overlays, and audio track..."
            await self.update_status(
                job_id=job_id,
                status="RENDERING_VIDEO",
                progress=90,
                message=msg,
                details=details
            )
            
            logger.debug(f"[{job_id}] Invoking FFmpegRenderer pipeline...")
            renderer = FFmpegRenderer(job_id)
            rendered_local_path = await renderer.render(
                video_plan=video_plan.model_dump(),
                bg_video_url=video_url,
                gif_url=gif_url
            )
            logger.info(f"[{job_id}] Render completed. Output path: {rendered_local_path}")

            # Calculate rendering stats
            try:
                file_size_bytes = os.path.getsize(rendered_local_path)
                file_size_mb = file_size_bytes / (1024 * 1024)
            except Exception:
                file_size_mb = 0.0

            details["rendering_stats"] = {
                "duration_seconds": video_plan.duration,
                "resolution": "1080x1920 (Vertical)",
                "codec": "libx264",
                "audio_codec": "aac",
                "file_size_mb": round(file_size_mb, 2),
                "scenes_count": len(video_plan.scenes)
            }

            # Define served URL path on FastAPI
            video_served_url = ""
            
            # Check if UploadThing configuration is available
            api_key = settings.UPLOADTHING_API_KEY
            if api_key and api_key not in ["YOUR_UPLOADTHING_KEY", "your_uploadthing_api_key_here", ""]:
                logger.info(f"[{job_id}] UPLOADTHING_API_KEY detected. Starting direct upload to uploadthing.com...")
                try:
                    uploaded_url = await self.upload_to_uploadthing(rendered_local_path, api_key)
                    if uploaded_url:
                        video_served_url = uploaded_url
                        logger.info(f"[{job_id}] UploadThing storage successful. Public URL: {video_served_url}")
                        
                        # Clean up temporary and local static files to remove server storage dependency
                        logger.info(f"[{job_id}] Cleaning up all local temporary folders and compiled assets...")
                        try:
                            # 1. Clean up renderer temp dir (contains stock video, audio loop, overlay GIF, output MP4)
                            if hasattr(renderer, "temp_dir") and os.path.exists(renderer.temp_dir):
                                logger.info(f"[{job_id}] Removing renderer temp directory: {renderer.temp_dir}")
                                shutil.rmtree(renderer.temp_dir)
                            # 2. Force delete any other temporary file in /tmp/ugc_platform
                            if os.path.exists(rendered_local_path):
                                logger.info(f"[{job_id}] Removing local rendered file: {rendered_local_path}")
                                os.remove(rendered_local_path)
                            logger.info(f"[{job_id}] Local disk space cleanup completed successfully.")
                        except Exception as cleanup_err:
                            logger.warning(f"[{job_id}] Minor warning during file cleanup: {cleanup_err}")
                    else:
                        logger.warning(f"[{job_id}] UploadThing upload failed. Falling back to local static serving...")
                except Exception as upload_err:
                    logger.error(f"[{job_id}] Error uploading to UploadThing: {upload_err}. Falling back to local static serving...")
            
            # If upload was skipped or failed, fall back to local serving
            if not video_served_url:
                static_filename = f"ugc_video_{job_id}.mp4"
                final_served_path = os.path.join(STATIC_DIR, static_filename)
                logger.info(f"[{job_id}] Copying processed file to local served folder: {final_served_path}")
                shutil.copy(rendered_local_path, final_served_path)
                video_served_url = f"http://localhost:8000/static/{static_filename}"

            # ----------------------------------------------------
            # Step 7: Completed
            # ----------------------------------------------------
            logger.info(f"[{job_id}] Stage 7/7 (COMPLETED): UGC Video generated successfully! Serving on {video_served_url}")
            await self.update_status(
                job_id=job_id,
                status="COMPLETED",
                progress=100,
                message="Premium UGC Video compiled and served successfully!",
                video_url=video_served_url,
                details=details
            )
            logger.info(f"[{job_id}] Workflow run succeeded.")

        except Exception as e:
            err_msg = f"Worker exception occurred during job execution: {str(e)}"
            logger.error(f"[{job_id}] {err_msg}", exc_info=True)
            await self.update_status(
                job_id=job_id,
                status="FAILED",
                progress=100,
                message=err_msg,
                details=details
            )

    async def run_forever(self):
        """Infinite blocking pop loop that retrieves and processes jobs."""
        logger.info("UGC Video Generation Background Worker started. Listening on Redis queue...")
        while True:
            try:
                # Wait for a job ID to become available on the Redis list
                # Since Redis BRPOP is blocking, it utilizes zero CPU when idle
                logger.debug("Worker entering BRPOP listen block...")
                job_id = self.redis.dequeue_job(timeout=10)
                if job_id:
                    logger.info(f"Worker picked up job_id={job_id} from queue. Beginning task execution...")
                    await self.process_job(job_id)
                else:
                    logger.debug("Worker poll cycle: queue empty. Continuing listen block...")
                    # Heartbeat
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.critical(f"Fatal exception inside main Worker Queue Loop: {e}", exc_info=True)
                await asyncio.sleep(5)

def start_worker():
    """Entrypoint to run the async worker loop."""
    logger.info("Invoking start_worker() loop initializer...")
    worker = BackgroundWorker()
    asyncio.run(worker.run_forever())

if __name__ == "__main__":
    start_worker()
