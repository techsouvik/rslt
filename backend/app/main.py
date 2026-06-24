import os
import re
import json
import asyncio
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .config import settings
from .redis_client import RedisManager
from .mongo_client import MongoManager
from .agents import chat_agent, current_chat_id, current_job_id

# Setup module logger
logger = logging.getLogger(__name__)

# Initialize FastAPI app
logger.info("Initializing FastAPI Application instance...")
app = FastAPI(title="UGC Video Generation Backend", version="1.0.0")

# CORS Setup
logger.info("Configuring CORS middleware with explicit origins for local development.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves rendered outputs (and asset directory) locally via HTTP
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
logger.info(f"Mounting static directory path: {STATIC_DIR} to URL route path: /static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ==========================================
# FastAPI Request Schemas
# ==========================================

class ChatRequest(BaseModel):
    chat_id: Optional[str] = None
    message: str

# ==========================================
# REST API Endpoints
# ==========================================

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Direct endpoint for conversational Chat UI.
    Passes requests to the Agno Chat Coordinator Agent.
    If the agent triggers video generation, it extracts the job_id and returns it to the client.
    """
    chat_id = request.chat_id or "default_chat"
    user_message = request.message
    
    logger.info(f"POST /api/chat - chat_id={chat_id}, message_len={len(user_message)} chars")
    
    redis_mgr = RedisManager()
    mongo_mgr = MongoManager()
    
    # ── Instant Greeting & Info Bypass ─────────────────────────────────────
    clean_msg = user_message.strip().lower().rstrip("?.!")
    greetings = {"hello", "hi", "hey", "yo", "sup", "greetings", "hello there", "hi there", "hey there", "hola"}
    info_queries = {"who are you", "what are you", "who is this", "what is this app", "what can you do", "what do you do", "how do you work", "help"}
    
    if clean_msg in greetings or clean_msg in info_queries:
        if clean_msg in greetings:
            reply_content = (
                "Hey there! 👋 Welcome to UGC Studio AI. I'm your Gen-Z viral video specialist.\n\n"
                "Just drop a product URL/website link or describe your startup/app, and I'll analyze the product, "
                "generate highly relatable video concepts, fetch the perfect stock background clips, and stitch "
                "together a high-converting 9:16 vertical video with funny trending meme stickers and captions!\n\n"
                "What are we building today? 🚀"
            )
        else:
            reply_content = (
                "I'm **UGC Studio AI**—a highly automated, creative agentic workspace designed to turn product web links "
                "and descriptions into viral vertical marketing videos for TikTok, Reels, and YouTube Shorts! 🎥✨\n\n"
                "### How I Work:\n"
                "1. **Scrape & Analyze**: Pass a link (e.g., `https://calai.app`), and I'll analyze its core value propositions and target demographics.\n"
                "2. **Creative Brainstorming**: I generate 3 trending Gen-Z video concepts using viral meme formats.\n"
                "3. **Smart Asset Gathering**: I search for minimalist background videos and top-reviewed transparent meme stickers from Giphy/Tenor.\n"
                "4. **Full Render**: I render a professional 9:16 vertical video with dynamic captions and custom placement in seconds.\n\n"
                "Just paste a product link below and let's get viral! 🚀"
            )
            
        logger.info(f"Instant fast-path bypass triggered for message: '{user_message}'. Returning response in under 5ms.")
        
        # Append user message and assistant reply to Redis and MongoDB so they persist
        redis_mgr.append_chat_message(chat_id, "user", user_message)
        await mongo_mgr.append_chat_message(chat_id, "user", user_message)
        redis_mgr.append_chat_message(chat_id, "assistant", reply_content)
        await mongo_mgr.append_chat_message(chat_id, "assistant", reply_content)
        
        return {"reply": reply_content, "job_id": None}

    # 1. Append user message to Redis (fast-cache) and MongoDB (persistent)
    logger.debug(f"Appending user message to Redis and MongoDB conversation logs: {chat_id}")
    redis_mgr.append_chat_message(chat_id, "user", user_message)
    await mongo_mgr.append_chat_message(chat_id, "user", user_message)
    
    # 2. Retrieve history context from MongoDB (primary) or Redis (fallback) to pass to Agno
    logger.debug(f"Fetching chat history messages from MongoDB for chat_id: {chat_id}")
    history_list = await mongo_mgr.get_chat_history(chat_id)
    if not history_list:
        logger.debug("MongoDB history blank, pulling fallback from Redis cache...")
        history_list = redis_mgr.get_chat_history(chat_id)
    
    # Simple history formatter for Agno instructions context
    # Strip any Job ID or job_xxxx text from content so the LLM NEVER sees it
    history_context = ""
    for msg in history_list[:-1]:  # Exclude current message
        role = msg['role']
        content = msg['content']
        clean_content = re.sub(r"Job ID is 'job_[a-fA-F0-9]{8}'\.?", "", content)
        clean_content = re.sub(r"job_[a-fA-F0-9]{8}", "", clean_content)
        history_context += f"{role.upper()}: {clean_content.strip()}\n"
    
    prompt = f"Chat History Context:\n{history_context}\n\nUser Current Message: {user_message}"
    
    # Use contextvar to safely propagate chat_id and job_id down to any tools called synchronously by the Agent
    token = current_chat_id.set(chat_id)
    job_token = current_job_id.set("")
    try:
        logger.info(f"Invoking Agno Chat Coordinator Agent for chat_id: {chat_id}")
        # Run Chat Agent synchronously (very fast, <1s response)
        agent_response = chat_agent.run(prompt)
        reply_content = agent_response.content
        logger.info(f"Received Agent reply. Reply length: {len(reply_content)} chars")
        logger.debug(f"Agent reply: '{reply_content}'")
        
        # Check if a video generation job was triggered (via the ContextVar)
        job_id = current_job_id.get()
        if job_id:
            logger.info(f"Programmatic video generation job detected. Job ID: {job_id}")
            # Programmatically append the Job ID pattern to the assistant's reply
            reply_content += f"\n\nJob ID is '{job_id}'."
        
        # Append assistant reply to Redis and MongoDB
        logger.debug(f"Appending Assistant reply to Redis and MongoDB conversation logs: {chat_id}")
        redis_mgr.append_chat_message(chat_id, "assistant", reply_content)
        await mongo_mgr.append_chat_message(chat_id, "assistant", reply_content)
        
        return {
            "chat_id": chat_id,
            "reply": reply_content,
            "job_id": job_id if job_id else None
        }
        
    except Exception as e:
        logger.error(f"Error occurred during /api/chat execution for chat_id {chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat Agent error: {str(e)}")
    finally:
        current_chat_id.reset(token)
        current_job_id.reset(job_token)

@app.get("/api/chat/history")
async def get_history(chat_id: str = Query(default="default_chat")):
    """Retrieves chat message history for the UI."""
    logger.info(f"GET /api/chat/history - chat_id={chat_id}")
    mongo_mgr = MongoManager()
    history = await mongo_mgr.get_chat_history(chat_id)
    if not history:
        logger.debug("MongoDB history blank, pulling fallback from Redis...")
        redis_mgr = RedisManager()
        history = redis_mgr.get_chat_history(chat_id)
    return {"messages": history}

@app.get("/api/conversations")
async def get_all_conversations():
    """Retrieves all past conversations, grouped with their associated video jobs."""
    logger.info("GET /api/conversations")
    mongo_mgr = MongoManager()
    conversations = await mongo_mgr.get_conversations()
    return conversations

@app.get("/api/conversations/{chat_id}")
async def get_single_conversation(chat_id: str):
    """Retrieves a single conversation with its associated video jobs."""
    logger.info(f"GET /api/conversations/{chat_id}")
    mongo_mgr = MongoManager()
    
    # Fetch history
    history = await mongo_mgr.get_chat_history(chat_id)
    
    # Fetch associated jobs
    from datetime import datetime
    jobs_cursor = mongo_mgr.jobs_col.find({"chat_id": chat_id}).sort("created_at", -1)
    videos = []
    async for job in jobs_cursor:
        job.pop("_id", None)
        if "created_at" in job and isinstance(job["created_at"], datetime):
            job["created_at"] = job["created_at"].isoformat()
        if "updated_at" in job and isinstance(job["updated_at"], datetime):
            job["updated_at"] = job["updated_at"].isoformat()
        videos.append(job)
        
    # Get title
    chat_doc = await mongo_mgr.chats_col.find_one({"chat_id": chat_id})
    title = chat_doc.get("title", "New Chat") if chat_doc else "New Chat"
    
    return {
        "chat_id": chat_id,
        "title": title,
        "messages": history,
        "videos": videos
    }

@app.delete("/api/conversations/{chat_id}")
async def delete_conversation(chat_id: str):
    """Deletes a conversation history and all associated video jobs from database and cache."""
    logger.info(f"DELETE /api/conversations/{chat_id}")
    mongo_mgr = MongoManager()
    redis_mgr = RedisManager()
    
    # 1. Fetch associated jobs to delete from Redis too
    try:
        jobs_cursor = mongo_mgr.jobs_col.find({"chat_id": chat_id})
        async for job in jobs_cursor:
            job_id = job.get("job_id")
            if job_id:
                redis_mgr.delete_job(job_id)
    except Exception as redis_err:
        logger.warning(f"Failed to fetch and clean job cache from Redis for chat_id {chat_id}: {redis_err}")
        
    # 2. Delete Redis chat history
    try:
        redis_mgr.delete_chat_history(chat_id)
    except Exception as redis_err:
        logger.warning(f"Failed to clear chat cache from Redis for chat_id {chat_id}: {redis_err}")

    # 3. Delete from MongoDB (both jobs and chat)
    success = await mongo_mgr.delete_conversation(chat_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete conversation")
    return {"status": "success", "message": f"Conversation {chat_id} and all related jobs/cache deleted successfully."}

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """REST endpoint to fetch the current status of a video generation job."""
    logger.info(f"GET /api/jobs/{job_id}")
    redis_mgr = RedisManager()
    
    # Try fetching from Redis first (fast operational state)
    job_data = redis_mgr.get_job(job_id)
    if not job_data:
        # Fallback to MongoDB (primary persistent store)
        logger.debug(f"Job {job_id} not found in Redis cache. Querying MongoDB...")
        mongo_mgr = MongoManager()
        job_data = await mongo_mgr.get_job(job_id)
        
    if not job_data:
        logger.warning(f"GET /api/jobs/{job_id} failed: Job ID not found in either Redis or MongoDB.")
        raise HTTPException(status_code=404, detail="Job not found")
        
    logger.debug(f"GET /api/jobs/{job_id} response: {job_data}")
    return job_data

# ==========================================
# Server-Sent Events (SSE) Real-Time Stream
# ==========================================

@app.get("/api/jobs/{job_id}/sse")
async def stream_job_updates(job_id: str):
    """
    Premium real-time progress update stream via Server-Sent Events (SSE).
    Subscribes to Redis PubSub and streams state changes down to the Chat UI.
    """
    logger.info(f"GET /api/jobs/{job_id}/sse - Client requested SSE updates subscription channel.")
    
    async def sse_event_generator():
        redis_mgr = RedisManager()
        mongo_mgr = MongoManager()
        logger.info(f"[{job_id}] Opening SSE PubSub listener connection for client stream.")
        pubsub = redis_mgr.subscribe_updates(job_id)
        
        # Send current cached job state instantly upon connection
        current_job = redis_mgr.get_job(job_id)
        if not current_job:
            # Fallback to MongoDB
            logger.debug(f"[{job_id}] Job state not found in Redis during initial SSE load. Querying MongoDB...")
            current_job = await mongo_mgr.get_job(job_id)
            
        if current_job:
            logger.info(f"[{job_id}] Sending initial job state to client: {current_job.get('status')}")
            yield f"event: progress\ndata: {json.dumps(current_job)}\n\n"
            if current_job.get("status") in ["COMPLETED", "FAILED"]:
                logger.info(f"[{job_id}] Initial job status is already in terminal state '{current_job.get('status')}'. Closing stream.")
                pubsub.unsubscribe()
                return

        # Keep connection open, yielding real-time PubSub updates from worker
        while True:
            try:
                # get_message is non-blocking, we check channel with low timeout
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if msg and msg.get("data"):
                    data_str = msg["data"]
                    logger.info(f"[{job_id}] PubSub message received: {data_str}")
                    yield f"event: progress\ndata: {data_str}\n\n"
                    
                    # Stop stream if terminal status reached
                    data = json.loads(data_str)
                    if data.get("status") in ["COMPLETED", "FAILED"]:
                        logger.info(f"[{job_id}] Job reached terminal status '{data.get('status')}'. Unsubscribing and terminating SSE connection stream.")
                        break
            except Exception as e:
                logger.error(f"[{job_id}] Exception inside SSE event loop generator: {e}", exc_info=True)
                break
            
            # Prevent spinning CPU
            await asyncio.sleep(0.1)
            
        # Cleanup
        logger.info(f"[{job_id}] Cleaning up SSE pubsub handlers. Unsubscribing channel.")
        pubsub.unsubscribe()

    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

# Mount the static frontend directory to serve the index.html from root "/"
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
    "app",
    "dist"
)
if not os.path.exists(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend"
    )

if os.path.exists(FRONTEND_DIR):
    logger.info(f"Mounting static frontend directory: {FRONTEND_DIR} to URL root '/'")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

