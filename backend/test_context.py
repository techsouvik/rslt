import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.agents import current_job_id
from app.scraper import scrape_website

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_flow():
    job_id = "test_job_123"
    print(f"Setting current_job_id to '{job_id}'")
    current_job_id.set(job_id)
    
    print(f"Checking current_job_id inside test_flow: '{current_job_id.get()}'")
    
    # Let's call scrape_website (which imports current_job_id and gets its value)
    res = await scrape_website("https://example.com")
    print(f"Finished scraping. Job ID in contextvar is still: '{current_job_id.get()}'")

if __name__ == "__main__":
    asyncio.run(test_flow())
