import os
import uuid
import logging
import contextvars
from typing import List, Optional
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.google import Gemini
from agno.media import Image
from .redis_client import RedisManager

# Setup module logger
logger = logging.getLogger(__name__)

current_chat_id = contextvars.ContextVar("current_chat_id", default="default_chat")
current_job_id = contextvars.ContextVar("current_job_id", default="")

# ==========================================
# 1. Pydantic Models for Structured Outputs
# ==========================================

class ProductBrief(BaseModel):
    product: str = Field(description="Name of the product/app")
    category: str = Field(description="Industry or market category")
    targetAudience: str = Field(description="Primary target demographic")
    painPoint: str = Field(description="The core customer pain point solved")
    valueProposition: str = Field(description="The unique value proposition or solution")

class CreativeConcept(BaseModel):
    hook: str = Field(description="The viral hook / opening text (e.g. POV, Bro said, etc.)")
    gif_concept: str = Field(description="A highly creative and specific search query for a transparent meme sticker overlay. Avoid generic terms like 'funny', 'excited', 'meme', 'sticker'. Instead, specify extremely clear reaction memes, specific pop-culture characters, animals, or actions (e.g., 'shocked pikachu', 'roll safe tapping head', 'confused john travolta', 'crying cat', 'homer Simpson backing into bush', 'drake hotline bling no', 'doge side eye').")
    ending: str = Field(description="The final text resolving the hook and showing the app value")

class CreativeConceptsList(BaseModel):
    concepts: List[CreativeConcept] = Field(description="Exactly 3 creative concept ideas")

class VideoScene(BaseModel):
    start: int = Field(description="Start time of the scene in seconds")
    end: int = Field(description="End time of the scene in seconds")
    text: str = Field(description="The overlay text displayed during this scene")

class VideoPlan(BaseModel):
    duration: int = Field(default=8, description="Total video duration in seconds (usually 8-10)")
    backgroundSearch: str = Field(description="Descriptive vertical video search query for Pexels (e.g., gym workout, coding vertical)")
    isLightBackground: bool = Field(default=False, description="Set to True if the requested backgroundSearch stock video is expected to have a primarily white, light, or bright aesthetic (e.g. minimalist white desk, clean white walls, light gray surface, sunny bright backdrop), otherwise False")
    gifSearch: str = Field(description="Descriptive search query for Tenor GIF (e.g., crying cat, confused math)")
    audioCategory: str = Field(description="Audio style matching the vibe (upbeat, funny, dramatic)")
    fontFamily: str = Field(
        default="Arial Bold", 
        description="Font family to use for captions. Choose from standard system fonts like: 'Arial Bold', 'Impact', 'Courier New Bold', 'Trebuchet MS Bold', 'Georgia Bold'."
    )
    fontSize: int = Field(
        default=78, 
        description="The font size for captions. Default is 78."
    )
    fontColor: str = Field(
        default="white", 
        description="Primary text color (e.g. 'white', 'black'). If isLightBackground is True, must use 'black', otherwise 'white'."
    )
    strokeColor: str = Field(
        default="black", 
        description="Text outline/border color (e.g. 'black', 'white'). If isLightBackground is True, must use 'white', otherwise 'black'."
    )
    strokeWidth: int = Field(
        default=5, 
        description="Outline stroke thickness. Default is 5."
    )
    textXPosition: str = Field(
        default="(w-text_w)/2", 
        description="Horizontal position expression for drawtext filter (e.g., '(w-text_w)/2' for center alignment). Default is '(w-text_w)/2'."
    )
    textYPosition: str = Field(
        default="h*0.12", 
        description="Vertical position expression for drawtext filter (e.g., 'h*0.12' for upper third, 'h*0.75' for lower third). Default is 'h*0.12'."
    )
    gifPosition: str = Field(
        default="bottom-center", 
        description="Position of the overlay GIF. Choose from: 'top-right', 'top-left', 'top-center', 'bottom-right', 'bottom-left', 'center', 'bottom-center', 'above-caption', 'below-caption'."
    )
    gifScaleWidthPercent: int = Field(
        default=65, 
        description="Scale width of overlay GIF as a percentage of background video width. Default is 65 for a very prominent, large sticker presentation (usually 60-70%)."
    )
    gifVisibleSceneIndices: List[int] = Field(
        default=[0, 1, 2],
        description="List of 0-indexed scene indices where the meme GIF should be visible (e.g. [0, 1, 2]). By default, show the GIF throughout all scenes of the video so it persists for the entire duration."
    )
    scenes: List[VideoScene] = Field(description="Sequential text scenes mapped to timestamps")

class SelectedConceptAndPlan(BaseModel):
    winner_index: int = Field(description="The index of the selected concept (0, 1, or 2)")
    score: int = Field(description="Confidence/relatability score from 1-100")
    reason: str = Field(description="Brief explanation of why this concept is the strongest and most relatable")
    video_plan: VideoPlan = Field(description="The final deterministic video plan compiled from the selected concept")

# ==========================================
# 2. Tool Definition for Chat Agent
# ==========================================

def trigger_video_generation(product_url: str, custom_instructions: str = "") -> str:
    """
    Triggers the automated short-form UGC video generation pipeline for a product URL.
    Call this whenever the user gives you a website link or URL and requests to make a video.
    
    Args:
        product_url: The absolute web link to scrape (e.g., 'https://calai.app')
        custom_instructions: Any specific angle or custom style requested by the user (e.g. 'gym bro angle')
    """
    logger.info(f"Tool trigger_video_generation called with url='{product_url}', instructions='{custom_instructions}'")
    try:
        import pymongo
        from datetime import datetime
        from .config import settings
        
        # Pull chat_id from task-local context variable
        chat_id = current_chat_id.get()
        logger.info(f"Using ContextVar for chat_id: {chat_id}")
            
        redis_mgr = RedisManager()
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        
        logger.debug(f"Generated job_id={job_id} for url='{product_url}'")
        
        # Set the current job_id ContextVar so it's programmatically retrievable
        current_job_id.set(job_id)
        
        # 1. Register the job in Redis
        redis_mgr.create_job(job_id, product_url, custom_instructions, chat_id=chat_id)
        
        # 2. Enqueue the job for the background worker process
        redis_mgr.enqueue_job(job_id)
        
        # 3. Synchronously register the job in MongoDB for initial state matching
        try:
            logger.info(f"MongoDB - Synchronously registering job_id={job_id}")
            with pymongo.MongoClient(settings.MONGO_URI) as client:
                db = client[settings.MONGO_DB]
                jobs_col = db["jobs"]
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
                jobs_col.update_one({"job_id": job_id}, {"$set": job_data}, upsert=True)
                logger.debug(f"MongoDB - Successfully created sync record for job_id={job_id}")
        except Exception as mongo_err:
            logger.error(f"MongoDB - Sync initialization failed for job_id={job_id}: {mongo_err}", exc_info=True)
        
        logger.info(f"Successfully initialized and queued job_id={job_id} for background processing.")
        return "SUCCESS: Video generation initiated! Status is PENDING."
    except Exception as e:
        logger.error(f"Error inside trigger_video_generation tool: {e}", exc_info=True)
        return f"ERROR: Failed to initiate video generation. Details: {str(e)}"

def get_video_generation_metrics() -> str:
    """
    Retrieves the execution and performance metrics for the latest completed or active video generation job in this chat.
    This includes the number of outside API calls made, input tokens burned, output tokens burned, and total tokens burned.
    Call this tool whenever the user asks for details like:
    - How many outside API calls were made?
    - How much LLM token was burned / how many tokens were used?
    - What are the costs or performance metrics for the video generation?
    """
    logger.info("Tool get_video_generation_metrics called")
    try:
        import pymongo
        from .config import settings
        
        chat_id = current_chat_id.get()
        logger.info(f"Using ContextVar for chat_id: {chat_id}")
            
        with pymongo.MongoClient(settings.MONGO_URI) as client:
            db = client[settings.MONGO_DB]
            jobs_col = db["jobs"]
            
            # Find the latest job associated with this chat_id
            job = jobs_col.find_one({"chat_id": chat_id}, sort=[("created_at", pymongo.DESCENDING)])
            
            if not job:
                logger.warning(f"No video jobs found in MongoDB for chat_id='{chat_id}'")
                return "No video generation jobs were found for this chat session. Let me know if you would like me to generate a video first!"
                
            job_id = job.get("job_id")
            
            # Try fetching from Redis first for the absolute latest live counters
            try:
                redis_mgr = RedisManager()
                redis_job = redis_mgr.get_job(job_id)
                if redis_job:
                    # Merge Redis live counters into the job doc
                    for key in ["api_calls_count", "input_tokens_burned", "output_tokens_burned", "total_tokens_burned", "status", "video_url"]:
                        if key in redis_job and redis_job[key]:
                            job[key] = redis_job[key]
            except Exception as redis_err:
                logger.warning(f"Failed to fetch live metrics from Redis for job {job_id}: {redis_err}")
                
            status = job.get("status", "UNKNOWN")
            product_url = job.get("product_url", "N/A")
            api_calls = job.get("api_calls_count", 0)
            in_tokens = job.get("input_tokens_burned", 0)
            out_tokens = job.get("output_tokens_burned", 0)
            tot_tokens = job.get("total_tokens_burned", 0)
            video_url = job.get("video_url", "")
            
            summary = (
                "Here are the performance and resource metrics for your latest video generation:\n\n"
                f"- **Product URL**: {product_url}\n"
                f"- **Generation Status**: {status}\n"
                f"- **Outside API Calls**: {api_calls} calls (Includes Scraping, stock video search/misses, Giphy/Tenor stickers search, asset downloads, and cloud CDN uploading)\n"
                f"- **LLM Tokens Burned (Gemini 3.5)**:\n"
                f"  - **Input Tokens**: {in_tokens:,}\n"
                f"  - **Output Tokens**: {out_tokens:,}\n"
                f"  - **Total Tokens**: {tot_tokens:,}\n"
            )
            if video_url:
                summary += f"- **Video Link**: {video_url}\n"
                
            return summary
            
    except Exception as e:
        logger.error(f"Error inside get_video_generation_metrics: {e}", exc_info=True)
        return f"Sorry, I encountered an error while retrieving the video generation metrics: {str(e)}"

# ==========================================
# 3. Agent Framework Setup (Gemini 3.5 Flash)
# ==========================================

logger.info("Initializing Agno Agents with Gemini 3.5 Flash backend...")

# Handler for model configuration: ensuring we don't block thoughts
gemini_model = Gemini(id="gemini-3.5-flash")

# The Chat Coordinator Agent
chat_agent = Agent(
    model=gemini_model,
    tools=[trigger_video_generation, get_video_generation_metrics],
    instructions=[
        "You are the premium, friendly UGC Video Generation Assistant.",
        "Your role is to chat with the user, answer questions, and help them create highly viral marketing videos.",
        "If a user provides a product URL/website link or asks you to make a video for a URL, call the 'trigger_video_generation' tool immediately.",
        "If the user asks about the performance metrics, costs, token burn, or outside API calls of their video generation, call 'get_video_generation_metrics' tool immediately to retrieve the details of the latest video and report them.",
        "Your replies MUST be extremely small, concise, and direct (1-2 sentences maximum) unless the user explicitly asks you to explain, list, or describe something in detail.",
        "Keep your replies friendly, conversational, modern, and engaging. Avoid dry corporate jargon.",
        "NEVER output, invent, or expose any raw machine IDs, hex hashes, or tokens like 'job_xxxxxxx' or 'chat_xxxxxxx' in your replies. Simply explain your actions in friendly natural language.",
    ]
)
logger.debug("Chat Coordinator Agent successfully initialized.")

# Product Analysis Specialist
product_agent = Agent(
    model=gemini_model,
    output_schema=ProductBrief,
    instructions=[
        "You are an expert product analyst.",
        "Your job is to read raw scraped website content and compile a highly structured ProductBrief.",
        "Focus on extracting the real, human value proposition, customer pain points, and target audience.",
    ]
)
logger.debug("Product Analysis Agent successfully initialized.")

# Gen-Z Social Media Specialist
creative_agent = Agent(
    model=gemini_model,
    output_schema=CreativeConceptsList,
    instructions=[
        "You are a highly creative Gen-Z social media marketer and viral content creator.",
        "Your task is to take a ProductBrief and generate exactly 3 highly relatable and funny short-form video concepts.",
        "Ensure concepts adopt viral meme formats popular on TikTok/Reels today (e.g. POV, Bro said, Gym Math, etc.).",
        "Keep text overlays extremely short, snappy, and readable on screen.",
    ]
)
logger.debug("Gen-Z Social Media Specialist Agent successfully initialized.")

# Chief Editor / Selector Specialist
judge_agent = Agent(
    model=gemini_model,
    output_schema=SelectedConceptAndPlan,
    instructions=[
        "You are an expert editor, social media manager, and marketing director.",
        "Your job is to evaluate the 3 concepts from the Creative Agent.",
        "Score them based on humor, virality, trend relevance, and product fit.",
        "Select the single best concept (winner_index) and explain your choice.",
        "Now, compile the chosen concept into a deterministic VideoPlan.",
        "CRITICAL REQUIREMENT for 'backgroundSearch': Search queries MUST target ONLY clean, subject-free, quiet, slow-motion, extremely calm, minimalist, or mostly static vertical stock videos (e.g. 'minimalist slow-motion loop vertical', 'ambient static wall texture vertical', 'aesthetic flatlay subtle movement vertical'). The background must feel nearly static and completely unobtrusive, serving only as a quiet backing canvas.",
        "For 'isLightBackground', set it to True if the backgroundSearch query is expected to yield light, bright, or white aesthetics (e.g. minimalist white space, bright sunny desk, light gray theme), otherwise False.",
        "For 'gifSearch', specify a highly creative, specific, and funny trending transparent meme sticker search query matching the exact vibe of the scene. Avoid generic terms like 'meme', 'gif', 'sticker', 'excited', 'funny', 'happy', 'sad'. Instead, generate highly descriptive, specific pop culture references, reaction memes, characters, animals, or expressive actions (e.g. 'rock eyebrow raise', 'crying cat', 'confused john travolta', 'homer bush back away', 'drake hotline blink no', 'shocked pikachu', 'doge side eye', 'minions cheer', 'sponge mock', 'dancing elmo', 'crying kim kardashian'). Be unique and generate a different meme request for every video plan!",
        "For 'audioCategory', select the audio style matching the theme and vibe of the winner concept. Use 'funny' for quirky/humorous/meme concepts, 'dramatic' for tense/serious/emotional concepts, and 'upbeat' for positive/energetic/motivational/educational branding concepts.",
        "For 'fontFamily', select the font style matching the video vibe. Choose 'Impact' for highly energetic/funny meme formats, 'Arial Bold' for high-quality clean branding layouts, 'Courier New Bold' for technical/coding themes, 'Trebuchet MS Bold' for athletic or casual themes.",
        "For 'fontSize', default to 78.",
        "For 'fontColor' and 'strokeColor': If 'isLightBackground' is True, use 'black' for 'fontColor' and 'white' for 'strokeColor'. Otherwise, use 'white' for 'fontColor' and 'black' for 'strokeColor'.",
        "For 'strokeWidth', default to 5.",
        "For 'textXPosition' and 'textYPosition', default to '(w-text_w)/2' and 'h*0.12' (upper third). If needed for creative framing, you can adjust these (e.g., 'h*0.75' for lower third).",
        "For 'gifPosition', specify the optimal Giphy placement intelligently: Choose from 'top-left', 'top-right', 'top-center', 'bottom-left', 'bottom-right', 'center', 'bottom-center', 'above-caption', or 'below-caption'.",
        "  - PRIORITIZE placing the meme GIF in the lower side of the screen (defaulting to 'bottom-center' or 'below-caption') so that it sits beautifully in the bottom half of the vertical layout.",
        "  - COORDINATE POSITIONING TO GUARANTEE ZERO OVERLAP with the text captions.",
        "  - Use 'above-caption' to place the meme GIF centered horizontally exactly above the subtitle lines.",
        "  - Use 'below-caption' to place the meme GIF centered horizontally exactly below the subtitle lines.",
        "  - If text is placed in the upper-third ('h*0.12'), prioritize 'bottom-center', 'below-caption', 'bottom-left', or 'bottom-right' for Giphy position.",
        "  - If text is placed in the lower-third ('h*0.75'), prioritize 'top-center', 'above-caption', 'top-left', or 'top-right' for Giphy position.",
        "  - If text is placed in the center ('h*0.5'), prioritize 'bottom-center', 'below-caption', 'bottom-left', or 'bottom-right' for Giphy position.",
        "  - If both captions and Giphy are requested to be in the center, prioritize placing the captions in the center ('h*0.5') and use 'below-caption' or 'bottom-center' to automatically stack them in the bottom half with zero overlap.",
        "  - Choose Giphy positions matching any explicit user-specified vibes or placement instructions if provided in custom instructions.",
        "For 'gifScaleWidthPercent', default to a highly prominent, large, and focused 60 to 75% (never less than 55%), making the overlay sticker/GIF much larger and more central on screen so it grabs maximum focus over the static background.",
        "For 'gifVisibleSceneIndices', specify exactly which scene indices should display the meme Giphy. By default, you MUST include ALL scene indices of the video (e.g., [0, 1, 2]) so that the GIF/sticker persists throughout the entire video and does not get prematurely removed in the second part or final scene of the video.",
        "Map the text overlay scenes precisely to timestamps (e.g. scene 1: 0-4s, scene 2: 4-8s). Total duration should be 8-10 seconds.",
        "USER CUSTOM OVERRIDES: If the user specified a custom font, font size, text colors, text position, Giphy search query, Giphy position, Giphy scale, or Giphy visible scenes in the custom instructions, you MUST strictly override your standard guidelines and use their specified values exactly in the compiled VideoPlan contract."
    ]
)
logger.debug("Chief Editor / Selector Specialist Agent successfully initialized.")

class GiphyReviewResult(BaseModel):
    selected_index: int = Field(description="The 1-based index of the chosen candidate image (1-5). If none are suitable or all fail, return 1.")
    reason: str = Field(description="A brief explanation of why this candidate was selected as having the best clear central subject.")

# Multimodal Giphy Review Agent
giphy_review_agent = Agent(
    model=gemini_model,
    output_schema=GiphyReviewResult,
    instructions=[
        "You are an expert design director and social media asset editor.",
        "Your task is to review the candidate transparent sticker images and select the single best one that features a clear, recognizable, and appealing central subject (such as a person, character, animal, puppet, or object) that is perfect for a social media overlay.",
        "Avoid selecting stickers that are purely text overlays, abstract lines, icons, or blank backgrounds.",
        "Strictly return the selected_index (1-based, 1 to 5) of the chosen candidate, and the reason."
    ]
)
logger.debug("Multimodal Giphy Review Agent successfully initialized.")

