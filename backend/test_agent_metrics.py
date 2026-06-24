import asyncio
import logging
import sys
import os

sys.path.insert(0, "/Users/souvikojha/Desktop/Result/backend")

from app.agents import product_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_agent_metrics():
    print("Running product_agent...")
    brief_resp = product_agent.run("Extract info from: https://example.com/ - This is a gym app called GymBuddy.")
    
    print("\nResponse details:")
    print("type(brief_resp):", type(brief_resp))
    print("hasattr(brief_resp, 'metrics'):", hasattr(brief_resp, "metrics"))
    if hasattr(brief_resp, "metrics") and brief_resp.metrics:
        print("metrics:", brief_resp.metrics)
        print("input_tokens:", getattr(brief_resp.metrics, "input_tokens", None))
        print("output_tokens:", getattr(brief_resp.metrics, "output_tokens", None))
        print("total_tokens:", getattr(brief_resp.metrics, "total_tokens", None))
    else:
        print("Metrics attribute is missing or None!")
        
    print("\nContent details:")
    print("content:", brief_resp.content)

if __name__ == "__main__":
    test_agent_metrics()
