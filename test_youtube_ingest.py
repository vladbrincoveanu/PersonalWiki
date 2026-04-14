import asyncio
import sys
import logging

from pipeline import run_pipeline

# Configure a low-level logger just to see what's happening under the hood
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def main():
    url = "https://www.youtube.com/watch?v=aircAruvnKk"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    print(f"Starting ingestion test for: {url}")
    print("-" * 40)
    
    try:
        async for msg in run_pipeline(url=url):
            print(f"[pipeline] {msg}")
    except Exception as e:
        print(f"\n[error] Pipeline failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
