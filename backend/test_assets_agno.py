import asyncio
import os
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_assets_agno")

# Load environment variables
load_dotenv(dotenv_path="/Users/souvikojha/Desktop/Result/backend/.env")

async def test_giphy_selection():
    from app.assets import fetch_giphy_gif, fetch_tenor_gif
    
    query = "crying cat"
    logger.info(f"Triggering fetch_giphy_gif with query: '{query}'")
    
    # We will temporarily mock the Redis cache to force a cache miss
    import app.assets as assets
    original_fetch = assets._fetch_with_retry_and_cache
    
    async def bypass_cache(prefix, query, fetch_func, fallback_url, ttl=86400):
        # Directly execute the fetch function bypassing cache read/write
        return await fetch_func()
        
    assets._fetch_with_retry_and_cache = bypass_cache
    
    # Execute the Giphy GIF fetch which should trigger the Agno review agent
    selected_gif_url = await fetch_giphy_gif(query)
    logger.info(f"Selected GIF URL: {selected_gif_url}")
    
    # Restore original function
    assets._fetch_with_retry_and_cache = original_fetch

if __name__ == "__main__":
    asyncio.run(test_giphy_selection())
