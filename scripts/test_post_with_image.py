"""
One-shot test: post a single tweet with image, then exit.
Usage:
  HEADLESS=true TWITTER_COOKIE_FILE=... python3 scripts/test_post_with_image.py
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_post")

TWEET_TEXT = """测试发帖 — 带图版

Moonshot K2.6 登顶金融智能体榜

Finance Agent Benchmark V2 数据：
把分析师换成 AI 不是趋势
是已经在发生的事"""


async def main() -> None:
    from twitter_bot import TwitterBot
    from scraper import scrape_aihot_items, fetch_image_for_item

    bot = TwitterBot()
    await bot.start()

    try:
        # Get a real news item for image (pass bot so x.com URLs use authenticated screenshot)
        logger.info("Fetching news item for image...")
        items = await scrape_aihot_items(since_hours=24, take=5)
        image_path = None
        for item in items:
            logger.info("Trying image for: %s (%s)", item.title[:60], item.url[:60])
            image_path = await fetch_image_for_item(item, bot=bot)
            if image_path:
                logger.info("Got image: %s", image_path)
                break

        if not image_path:
            logger.warning("No image found — will post text-only")

        logger.info("Posting tweet (image=%s)...", image_path)
        url = await bot.post_tweet(TWEET_TEXT, image_path=image_path)
        logger.info("Done. Tweet URL: %s", url or "(not captured)")

        if image_path and os.path.exists(image_path):
            os.remove(image_path)
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
