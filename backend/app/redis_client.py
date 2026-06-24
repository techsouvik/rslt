import json
import redis
import logging
from typing import Dict, Any, Optional, List
from .config import settings

# Setup module logger
logger = logging.getLogger(__name__)

# Active Redis connections
_redis_conn = None

def get_redis_connection() -> redis.Redis:
    global _redis_conn
    if _redis_conn is None:
        logger.info(f"Establishing new Redis connection to {settings.REDIS_HOST}:{settings.REDIS_PORT} (db={settings.REDIS_DB})")
        try:
            _redis_conn = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True  # decodes keys/values to strings automatically
            )
            # Test connection
            _redis_conn.ping()
            logger.info("Successfully connected to Redis server.")
        except Exception as e:
            logger.critical(f"Failed to connect to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}. Error: {e}", exc_info=True)
            raise e
    return _redis_conn

class RedisManager:
    def __init__(self):
        self.r = get_redis_connection()
        self.queue_key = "ugc_video_jobs"

    # ==========================================
    # 1. Job Management (HSET/HGET)
    # ==========================================

    def create_job(self, job_id: str, product_url: str, custom_instructions: str = "", chat_id: str = "default_chat") -> Dict[str, Any]:
        logger.info(f"Creating job record for job_id={job_id}, url={product_url}, chat_id={chat_id}")
        job_data = {
            "job_id": job_id,
            "chat_id": chat_id,
            "status": "PENDING",
            "progress": "0",
            "message": "Job registered. Waiting for worker...",
            "product_url": product_url,
            "custom_instructions": custom_instructions,
            "video_url": "",
            "details": "{}"
        }
        try:
            self.r.hset(f"job:{job_id}", mapping=job_data)
            logger.debug(f"Job {job_id} successfully saved to Redis.")
            
            # Since details is a dict inside the return, parse it
            job_data["details"] = {}
            # Notify any active listeners via PubSub
            self.publish_update(job_id, job_data)
        except Exception as e:
            logger.error(f"Error creating job {job_id} in Redis: {e}", exc_info=True)
            raise e
        return job_data

    def update_job_status(self, job_id: str, status: str, progress: int, message: str, video_url: str = "", details: Optional[Dict[str, Any]] = None) -> None:
        logger.info(f"Updating job {job_id} -> status={status}, progress={progress}%, message='{message}'")
        updates = {
            "status": status,
            "progress": str(progress),
            "message": message,
            "video_url": video_url
        }
        if details is not None:
            updates["details"] = json.dumps(details)
            
        try:
            self.r.hset(f"job:{job_id}", mapping=updates)
            
            # Get full updated job info
            full_job = self.get_job(job_id)
            if full_job:
                self.publish_update(job_id, full_job)
            else:
                logger.warning(f"Failed to fetch updated job details for {job_id} after writing status.")
        except Exception as e:
            logger.error(f"Error updating job {job_id} status in Redis: {e}", exc_info=True)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        logger.debug(f"Fetching job record for {job_id}")
        try:
            job_data = self.r.hgetall(f"job:{job_id}")
            if not job_data:
                logger.warning(f"Job record {job_id} not found in Redis.")
                return None
                
            # If details is present, decode it
            if "details" in job_data and job_data["details"]:
                try:
                    job_data["details"] = json.loads(job_data["details"])
                except Exception:
                    logger.warning(f"Failed to parse details JSON string: {job_data['details']}")
                    job_data["details"] = {}
            else:
                job_data["details"] = {}
                
            # Parse numeric metrics if present
            for key in ["api_calls_count", "input_tokens_burned", "output_tokens_burned", "total_tokens_burned"]:
                if key in job_data:
                    try:
                        job_data[key] = int(job_data[key])
                    except (ValueError, TypeError):
                        job_data[key] = 0
                else:
                    job_data[key] = 0
                    
            return job_data
        except Exception as e:
            logger.error(f"Error reading job {job_id} from Redis: {e}", exc_info=True)
            return None

    def increment_job_api_calls(self, job_id: str, amount: int = 1) -> int:
        """Atomically increments the outside API calls counter for a job in Redis."""
        logger.info(f"Incrementing outside API calls count for job_id={job_id} by {amount}")
        try:
            val = self.r.hincrby(f"job:{job_id}", "api_calls_count", amount)
            # Fetch and publish the updated state so that SSE updates are triggered
            full_job = self.get_job(job_id)
            if full_job:
                self.publish_update(job_id, full_job)
            return val
        except Exception as e:
            logger.error(f"Error incrementing API calls for job {job_id} in Redis: {e}", exc_info=True)
            return 0

    def increment_job_tokens(self, job_id: str, input_tokens: int, output_tokens: int) -> Dict[str, int]:
        """Atomically increments input, output, and total tokens burned for a job in Redis."""
        logger.info(f"Incrementing tokens for job_id={job_id}: input={input_tokens}, output={output_tokens}")
        try:
            in_val = self.r.hincrby(f"job:{job_id}", "input_tokens_burned", input_tokens)
            out_val = self.r.hincrby(f"job:{job_id}", "output_tokens_burned", output_tokens)
            tot_val = self.r.hincrby(f"job:{job_id}", "total_tokens_burned", input_tokens + output_tokens)
            
            full_job = self.get_job(job_id)
            if full_job:
                self.publish_update(job_id, full_job)
            return {
                "input_tokens_burned": in_val,
                "output_tokens_burned": out_val,
                "total_tokens_burned": tot_val
            }
        except Exception as e:
            logger.error(f"Error incrementing tokens for job {job_id} in Redis: {e}", exc_info=True)
            return {"input_tokens_burned": 0, "output_tokens_burned": 0, "total_tokens_burned": 0}

    # ==========================================
    # 2. Asynchronous Queue Management (LPUSH/BRPOP)
    # ==========================================

    def enqueue_job(self, job_id: str) -> None:
        """Pushes a job ID onto the queue."""
        logger.info(f"Enqueueing job_id={job_id} into queue '{self.queue_key}'")
        try:
            self.r.lpush(self.queue_key, job_id)
            logger.debug(f"Job {job_id} successfully enqueued.")
        except Exception as e:
            logger.error(f"Error enqueueing job {job_id}: {e}", exc_info=True)
            raise e

    def dequeue_job(self, timeout: int = 0) -> Optional[str]:
        """Blocking pop of a job ID from the queue."""
        logger.debug(f"Listening on queue '{self.queue_key}' with timeout={timeout}...")
        try:
            result = self.r.brpop(self.queue_key, timeout=timeout)
            if result:
                # brpop returns a tuple of (key, value)
                job_id = result[1]
                logger.info(f"Dequeued job_id={job_id} from '{self.queue_key}'")
                return job_id
            return None
        except redis.exceptions.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Error dequeueing job from Redis: {e}", exc_info=True)
            return None

    # ==========================================
    # 3. Real-time Event PubSub
    # ==========================================

    def publish_update(self, job_id: str, data: Dict[str, Any]) -> None:
        """Publishes progress data to a Redis Channel for SSE streaming."""
        channel = f"job:{job_id}:updates"
        logger.debug(f"Publishing update to channel {channel}: {data}")
        try:
            subscribers = self.r.publish(channel, json.dumps(data))
            logger.debug(f"Update published. Channel {channel} has {subscribers} active subscriber(s).")
        except Exception as e:
            logger.error(f"Failed to publish update on channel {channel}: {e}", exc_info=True)

    def subscribe_updates(self, job_id: str):
        """Subscribes to a job channel and returns the PubSub connection."""
        channel = f"job:{job_id}:updates"
        logger.info(f"Subscribing to updates channel: {channel}")
        try:
            pubsub = self.r.pubsub()
            pubsub.subscribe(channel)
            return pubsub
        except Exception as e:
            logger.error(f"Failed to subscribe to channel {channel}: {e}", exc_info=True)
            raise e

    # ==========================================
    # 4. Chat History Management (List)
    # ==========================================

    def append_chat_message(self, chat_id: str, role: str, content: str) -> None:
        logger.info(f"Appending chat message for chat_id={chat_id}, role={role}")
        message_data = {
            "role": role,
            "content": content
        }
        try:
            self.r.rpush(f"chat:{chat_id}:messages", json.dumps(message_data))
            logger.debug(f"Chat message successfully appended for {chat_id}.")
        except Exception as e:
            logger.error(f"Error appending chat message for {chat_id}: {e}", exc_info=True)

    def get_chat_history(self, chat_id: str) -> List[Dict[str, str]]:
        logger.debug(f"Retrieving chat history for chat_id={chat_id}")
        try:
            messages = self.r.lrange(f"chat:{chat_id}:messages", 0, -1)
            history = [json.loads(msg) for msg in messages]
            logger.debug(f"Successfully retrieved {len(history)} messages for chat_id={chat_id}")
            return history
        except Exception as e:
            logger.error(f"Error retrieving chat history for {chat_id}: {e}", exc_info=True)
            return []

    def delete_chat_history(self, chat_id: str) -> None:
        """Deletes chat message logs from Redis."""
        logger.info(f"Deleting chat log from Redis for chat_id={chat_id}")
        try:
            self.r.delete(f"chat:{chat_id}:messages")
            logger.debug(f"Chat message log successfully deleted for {chat_id}.")
        except Exception as e:
            logger.error(f"Error deleting chat message log for {chat_id}: {e}", exc_info=True)

    def delete_job(self, job_id: str) -> None:
        """Deletes job record from Redis."""
        logger.info(f"Deleting job record from Redis for job_id={job_id}")
        try:
            self.r.delete(f"job:{job_id}")
            logger.debug(f"Job record successfully deleted for {job_id}.")
        except Exception as e:
            logger.error(f"Error deleting job {job_id} from Redis: {e}", exc_info=True)

