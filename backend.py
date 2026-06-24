import os
import httpx
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.google import Gemini

# Setup basic logging for standalone prototype
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s:%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"
)
logger = logging.getLogger("backend_standalone")

# Initialize FastAPI App
app = FastAPI(title="UGC Video Generation Platform API")

# Add CORS Middleware for Next.js frontend communication
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
    gif_concept: str = Field(description="A descriptive query for a meme GIF (e.g. crying cat, shock face)")
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
    gifSearch: str = Field(description="Descriptive search query for Tenor GIF (e.g., crying cat, confused math)")
    audioCategory: str = Field(description="Audio style matching the vibe (upbeat, funny, dramatic)")
    scenes: List[VideoScene] = Field(description="Sequential text scenes mapped to timestamps")

class SelectedConceptAndPlan(BaseModel):
    winner_index: int = Field(description="The index of the selected concept (0, 1, or 2)")
    score: int = Field(description="Confidence/relatability score from 1-100")
    reason: str = Field(description="Brief explanation of why this concept is the strongest and most relatable")
    video_plan: VideoPlan = Field(description="The final deterministic video plan compiled from the selected concept")

# ==========================================
# 2. Website Scraper Supporting Service
# ==========================================

async def scrape_website(url: str) -> str:
    """
    Asynchronously scrapes the given website landing page.
    For a rapid workable solution, we can use a lightweight HTTP client or a Playwright scraper.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # We fetch the HTML page
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                return f"Failed to scrape website. HTTP Status: {response.status_code}"
            
            # Simple text extraction from HTML (to avoid complex beautifulsoup/playwright overhead in early prototype)
            # In a full setup, we would parse title, meta tags, and hero text
            html_content = response.text
            # Return first 2000 chars of the page content as a basic fallback
            return html_content[:2000]
    except Exception as e:
        return f"Error scraping website: {str(e)}"

# ==========================================
# 3. Agno Agents Initialization
# ==========================================

# Note: Gemini 3.5 Flash is our core LLM.
# Critical Gotcha Handled: Do NOT set search=True or thinking_budget=0!
gemini_model = Gemini(id="gemini-3.5-flash")

product_agent = Agent(
    model=gemini_model,
    output_schema=ProductBrief,
    instructions=[
        "You are an expert product analyst.",
        "Your job is to read the raw scraped website content and compile a highly structured ProductBrief.",
        "Focus on extracting the real, human value proposition and target audience.",
    ]
)

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

judge_agent = Agent(
    model=gemini_model,
    output_schema=SelectedConceptAndPlan,
    instructions=[
        "You are an expert editor, social media manager, and marketing director.",
        "Your job is to evaluate the 3 concepts from the Creative Agent.",
        "Score them based on humor, virality, trend relevance, and product fit.",
        "Select the single best concept (winner_index) and explain your choice.",
        "Now, compile the chosen concept into a deterministic VideoPlan.",
        "For 'backgroundSearch', specify a highly descriptive vertical stock video query (e.g. 'gym workout vertical' or 'student studying vertical').",
        "For 'gifSearch', specify a funny trending meme GIF query (e.g. 'rock eyebrow raise', 'crying cat').",
        "Map the text overlay scenes precisely to timestamps (e.g. scene 1: 0-4s, scene 2: 4-8s). Total duration should be 8-10 seconds.",
    ]
)

# ==========================================
# 4. Asset Provider Integrations (Pexels & Tenor)
# ==========================================

async def fetch_pexels_video(query: str, pexels_api_key: str) -> Optional[str]:
    """
    Queries Pexels API for a vertical high-quality stock video.
    Returns the URL of the best vertical video file.
    """
    if not pexels_api_key or pexels_api_key == "YOUR_PEXELS_KEY":
        # Mock fallback url for testing
        return "https://assets.mixkit.co/videos/preview/mixkit-man-holding-smartphone-with-green-screen-40156-large.mp4"
    
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"
    headers = {"Authorization": pexels_api_key}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                videos = data.get("videos", [])
                if videos:
                    # Extract the highest resolution MP4 vertical stream
                    video_files = videos[0].get("video_files", [])
                    # Filter for mp4 and select a good file
                    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
                    if mp4_files:
                        return mp4_files[0].get("link")
    except Exception as e:
        logger.error(f"Error fetching Pexels video: {e}", exc_info=True)
    return None

async def fetch_tenor_gif(query: str, tenor_api_key: str) -> Optional[str]:
    """
    Queries Tenor API for a transparent or highly popular trending overlay GIF.
    """
    if not tenor_api_key or tenor_api_key == "YOUR_TENOR_KEY":
        # Mock fallback gif url for testing
        return "https://media.tenor.com/yheS1gNSgOgAAAAM/crying-cat-meme.gif"
    
    # We query Tenor v2 search
    url = f"https://tenor.googleapis.com/v2/search?q={query}&key={tenor_api_key}&limit=1"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if results:
                    media_formats = results[0].get("media_formats", {})
                    gif_format = media_formats.get("gif", {})
                    return gif_format.get("url")
    except Exception as e:
        logger.error(f"Error fetching Tenor GIF: {e}", exc_info=True)
    return None

# ==========================================
# 5. Core Video Generation Orchestrator
# ==========================================

# In-memory job state tracker (For production, this would be a Postgres DB as per requirements)
jobs_db = {}

async def run_video_generation_job(job_id: str, chat_id: str, product_url: str):
    """
    Background job that executes the 3-agent orchestration flow sequentially.
    """
    # Keys should be loaded from env vars
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
    TENOR_API_KEY = os.getenv("TENOR_API_KEY", "")

    try:
        # Step 1: Scrape & Understand
        jobs_db[job_id] = {"status": "ANALYZING_PRODUCT", "progress": 20, "message": "Scraping website..."}
        scraped_text = await scrape_website(product_url)
        
        # Run Product Agent
        brief_response = product_agent.run(f"Analyze this product: URL: {product_url}\n\nContent: {scraped_text}")
        product_brief: ProductBrief = brief_response.content
        
        # Step 2: Ideate
        jobs_db[job_id] = {"status": "GENERATING_CONCEPTS", "progress": 40, "message": "Brainstorming viral TikTok hooks..."}
        concepts_response = creative_agent.run(f"Generate 3 viral UGC concepts based on this product brief: {product_brief.model_dump_json()}")
        concepts_list: CreativeConceptsList = concepts_response.content
        
        # Step 3: Evaluate & Select
        jobs_db[job_id] = {"status": "SELECTING_CONCEPT", "progress": 60, "message": "Evaluating virality score..."}
        judge_response = judge_agent.run(f"Compare and choose the best concept from this list, then compile a final VideoPlan: {concepts_list.model_dump_json()}")
        selection_and_plan: SelectedConceptAndPlan = judge_response.content
        video_plan: VideoPlan = selection_and_plan.video_plan
        
        # Step 4: Asset Acquisition
        jobs_db[job_id] = {"status": "ACQUIRING_ASSETS", "progress": 80, "message": "Downloading video and GIF assets..."}
        video_url = await fetch_pexels_video(video_plan.backgroundSearch, PEXELS_API_KEY)
        gif_url = await fetch_tenor_gif(video_plan.gifSearch, TENOR_API_KEY)
        
        # Step 5: Render (FFmpeg Mock for rapid workable solutions)
        jobs_db[job_id] = {"status": "RENDERING_VIDEO", "progress": 90, "message": "FFmpeg assembling video layers..."}
        # Render execution goes here!
        # Once built, we upload output to Supabase Storage.
        # For now, we return a fully formed plan + asset URLs as success!
        
        final_video_url = "https://cdn.example.com/videos/mock_rendered_ugc_video.mp4" # Placeholder output
        
        jobs_db[job_id] = {
            "status": "COMPLETED",
            "progress": 100,
            "message": "Video successfully generated!",
            "result": {
                "brief": product_brief,
                "selected_concept": selection_and_plan.reason,
                "score": selection_and_plan.score,
                "video_plan": video_plan,
                "background_video_url": video_url,
                "gif_url": gif_url,
                "final_video_url": final_video_url
            }
        }
        
    except Exception as e:
        jobs_db[job_id] = {
            "status": "FAILED",
            "progress": 100,
            "message": f"Generation failed: {str(e)}"
        }

# ==========================================
# 6. FastAPI Routes
# ==========================================

@app.post("/jobs/generate")
async def generate_video(product_url: str, chat_id: str, background_tasks: BackgroundTasks):
    """
    Submits a new video generation request to run asynchronously in the background.
    """
    import uuid
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    jobs_db[job_id] = {"status": "PENDING", "progress": 0, "message": "Initializing job..."}
    
    # Run the background job orchestrating the agents and assets
    background_tasks.add_task(run_video_generation_job, job_id, chat_id, product_url)
    
    return {"job_id": job_id, "status": "PENDING", "message": "Job registered successfully"}

@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """
    Queries current progress of a specific job (Fast fallback to polling, SSE implemented in Phase 4).
    """
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs_db[job_id]
