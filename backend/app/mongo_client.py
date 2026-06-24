import re
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

# Setup module logger
logger = logging.getLogger(__name__)

# Single global motor client instance
_mongo_client = None

def get_mongo_client() -> AsyncIOMotorClient:
    global _mongo_client
    if _mongo_client is None:
        logger.info(f"Establishing non-blocking MongoDB connection using Motor to URI: {settings.MONGO_URI}")
        try:
            _mongo_client = AsyncIOMotorClient(settings.MONGO_URI)
            logger.info("Successfully established connection to MongoDB.")
        except Exception as e:
            logger.critical(f"Failed to initialize non-blocking MongoDB client: {e}", exc_info=True)
            raise e
    return _mongo_client

def get_db():
    client = get_mongo_client()
    return client[settings.MONGO_DB]

def generate_chat_title(first_message: str) -> str:
    """Helper to generate a clean, friendly chat title from the first message."""
    # Remove URLs for title
    cleaned = re.sub(r'https?://\S+', '', first_message).strip()
    if not cleaned:
        # Fallback to the original URL if that's all there was
        urls = re.findall(r'https?://(?:www\.)?([a-zA-Z0-9-]+)\.[a-z]+', first_message)
        if urls:
            return f"Video for {urls[0].capitalize()}"
        return "New Chat"
    
    # Take first 5-6 words
    words = cleaned.split()
    if len(words) > 5:
        return " ".join(words[:5]) + "..."
    return cleaned[:35]

class MongoManager:
    def __init__(self):
        self.db = get_db()
        self.jobs_col = self.db["jobs"]
        self.chats_col = self.db["chats"]
        logger.debug("MongoManager initialized successfully with 'jobs' and 'chats' collections.")

    # ==========================================
    # 1. Job Management (Async Non-Blocking)
    # ==========================================

    async def create_job(self, job_id: str, product_url: str, custom_instructions: str = "", chat_id: str = "default_chat") -> Dict[str, Any]:
        logger.info(f"MongoDB - Creating persistent job record for job_id={job_id}, url={product_url}, chat_id={chat_id}")
        job_data = {
            "job_id": job_id,
            "chat_id": chat_id,
            "status": "PENDING",
            "progress": 0,
            "message": "Job registered. Waiting for worker...",
            "product_url": product_url,
            "custom_instructions": custom_instructions,
            "video_url": "",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        try:
            # Idempotent upsert logic
            await self.jobs_col.update_one(
                {"job_id": job_id},
                {"$set": job_data},
                upsert=True
            )
            logger.debug(f"MongoDB - Job {job_id} successfully saved.")
        except Exception as e:
            logger.error(f"MongoDB - Error writing job {job_id}: {e}", exc_info=True)
            raise e
        return job_data

    async def update_job_status(self, job_id: str, status: str, progress: int, message: str, video_url: str = "", details: Optional[Dict[str, Any]] = None, extra_data: Optional[Dict[str, Any]] = None) -> None:
        logger.info(f"MongoDB - Updating job_id={job_id} -> status={status}, progress={progress}%, message='{message}'")
        updates = {
            "status": status,
            "progress": progress,
            "message": message,
            "video_url": video_url,
            "updated_at": datetime.utcnow()
        }
        if details is not None:
            updates["details"] = details
        if extra_data:
            updates.update(extra_data)
            
        try:
            result = await self.jobs_col.update_one(
                {"job_id": job_id},
                {"$set": updates}
            )
            if result.matched_count == 0:
                logger.warning(f"MongoDB - No matching job record found for job_id={job_id}. Registering as fallback upsert...")
                updates["job_id"] = job_id
                updates["created_at"] = datetime.utcnow()
                await self.jobs_col.update_one({"job_id": job_id}, {"$set": updates}, upsert=True)
            else:
                logger.debug(f"MongoDB - Job {job_id} updated successfully.")
        except Exception as e:
            logger.error(f"MongoDB - Error updating job {job_id}: {e}", exc_info=True)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        logger.debug(f"MongoDB - Querying job record for job_id={job_id}")
        try:
            job = await self.jobs_col.find_one({"job_id": job_id})
            if job:
                # Remove default ObjectID for easier json serialization
                job.pop("_id", None)
                # Formatter for datetimes
                if "created_at" in job and isinstance(job["created_at"], datetime):
                    job["created_at"] = job["created_at"].isoformat()
                if "updated_at" in job and isinstance(job["updated_at"], datetime):
                    job["updated_at"] = job["updated_at"].isoformat()
                return job
            logger.warning(f"MongoDB - Job record {job_id} not found.")
            return None
        except Exception as e:
            logger.error(f"MongoDB - Error fetching job {job_id}: {e}", exc_info=True)
            return None

    # ==========================================
    # 2. Conversational Chat History (Async)
    # ==========================================

    async def append_chat_message(self, chat_id: str, role: str, content: str) -> None:
        logger.info(f"MongoDB - Appending message for chat_id={chat_id}, role={role}")
        message_data = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow()
        }
        try:
            existing = await self.chats_col.find_one({"chat_id": chat_id})
            updates = {
                "$push": {"messages": message_data},
                "$set": {"updated_at": datetime.utcnow()}
            }
            if not existing and role == "user":
                # Set dynamic chat title on first user message
                title = generate_chat_title(content)
                updates["$set"]["title"] = title
                logger.info(f"MongoDB - Generated friendly title '{title}' for new chat_id={chat_id}")
                
            await self.chats_col.update_one(
                {"chat_id": chat_id},
                updates,
                upsert=True
            )
            logger.debug(f"MongoDB - Message successfully appended in chat {chat_id}.")
        except Exception as e:
            logger.error(f"MongoDB - Error writing chat message for {chat_id}: {e}", exc_info=True)

    async def get_chat_history(self, chat_id: str) -> List[Dict[str, Any]]:
        logger.debug(f"MongoDB - Querying chat logs for chat_id={chat_id}")
        try:
            doc = await self.chats_col.find_one({"chat_id": chat_id})
            if doc and "messages" in doc:
                messages = doc["messages"]
                for msg in messages:
                    if "timestamp" in msg and isinstance(msg["timestamp"], datetime):
                        msg["timestamp"] = msg["timestamp"].isoformat()
                logger.info(f"MongoDB - Successfully loaded {len(messages)} messages for chat {chat_id}.")
                return messages
            logger.info(f"MongoDB - Chat log for {chat_id} not found. Returning empty list.")
            return []
        except Exception as e:
            logger.error(f"MongoDB - Error reading chat history for {chat_id}: {e}", exc_info=True)
            return []

    # ==========================================
    # 3. Conversations Grouping and Deletion (Async)
    # ==========================================

    async def get_conversations(self) -> List[Dict[str, Any]]:
        """Retrieves all past conversations sorted by updated_at desc, with linked video jobs."""
        logger.info("MongoDB - Fetching all conversation groups with associated video jobs")
        try:
            cursor = self.chats_col.find({}).sort("updated_at", -1)
            conversations = []
            async for chat in cursor:
                chat_id = chat.get("chat_id")
                title = chat.get("title", "New Chat")
                updated_at = chat.get("updated_at")
                messages = chat.get("messages", [])
                
                # Format timestamps
                if isinstance(updated_at, datetime):
                    updated_at_str = updated_at.isoformat()
                else:
                    updated_at_str = datetime.utcnow().isoformat()
                    
                for msg in messages:
                    if "timestamp" in msg and isinstance(msg["timestamp"], datetime):
                        msg["timestamp"] = msg["timestamp"].isoformat()
                        
                # Query associated jobs from jobs collection
                jobs_cursor = self.jobs_col.find({"chat_id": chat_id}).sort("created_at", -1)
                videos = []
                async for job in jobs_cursor:
                    job.pop("_id", None)
                    if "created_at" in job and isinstance(job["created_at"], datetime):
                        job["created_at"] = job["created_at"].isoformat()
                    if "updated_at" in job and isinstance(job["updated_at"], datetime):
                        job["updated_at"] = job["updated_at"].isoformat()
                    videos.append(job)
                    
                conversations.append({
                    "chat_id": chat_id,
                    "title": title,
                    "updated_at": updated_at_str,
                    "messages": messages,
                    "videos": videos
                })
            return conversations
        except Exception as e:
            logger.error(f"MongoDB - Error loading conversations grouping list: {e}", exc_info=True)
            return []

    async def delete_conversation(self, chat_id: str) -> bool:
        """Deletes chat message history and all associated video jobs in MongoDB."""
        logger.info(f"MongoDB - Deleting chat log and video jobs for chat_id={chat_id}")
        try:
            chat_res = await self.chats_col.delete_one({"chat_id": chat_id})
            jobs_res = await self.jobs_col.delete_many({"chat_id": chat_id})
            logger.info(f"MongoDB - Deletion success. Deleted {chat_res.deleted_count} chat session, and {jobs_res.deleted_count} video jobs.")
            return True
        except Exception as e:
            logger.error(f"MongoDB - Deletion failure for chat_id={chat_id}: {e}", exc_info=True)
            return False
