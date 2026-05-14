#!/usr/bin/env python3
"""
Post a tweet via Playwright connected to an existing Chrome via CDP.
Chrome must be running with: --remote-debugging-port=9222

Usage:
  echo "tweet text" | python3 post_tweet.py --image_url https://...
  python3 post_tweet.py --text-file /tmp/tweet.txt --image_url https://...
"""

import argparse
import asyncio
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright
from tweet_utils import tweet_weight, MAX_TWEET_WEIGHT

CHROME_CDP = "http://localhost:9222"
COMPOSE_URL = "https://x.com/compose/post"


async def download_image(url: str, dest_path: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        max_bytes = 5 * 1024 * 1024
        total = 0
        with urllib.request.urlopen(req, timeout=20) as response:
            with open(dest_path, "wb") as f:
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Image exceeds {max_bytes} bytes")
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"[WARN] Image download failed: {e}", file=sys.stderr)
        return False


async def post_tweet(text: str, image_url: str | None) -> bool:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CHROME_CDP)
        except Exception as e:
            print(f"[ERROR] Cannot connect to Chrome at {CHROME_CDP}: {e}", file=sys.stderr)
            print("[ERROR] Start Chrome with: open -a 'Google Chrome' --args --remote-debugging-port=9222", file=sys.stderr)
            return False

        context = browser.contexts[0]
        page = await context.new_page()

        try:
            await page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=30000)

            # x.com/compose/post opens a modal inside #layers; the home feed textarea
            # sits behind the modal mask and cannot receive clicks — scope to #layers.
            layers = page.locator("#layers")
            tweet_box = layers.get_by_test_id("tweetTextarea_0").first
            await tweet_box.wait_for(state="visible", timeout=15000)
            await tweet_box.click()
            await page.keyboard.type(text, delay=20)

            # Upload image
            image_path = None
            try:
                if image_url:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                        image_path = f.name
                    if await download_image(image_url, image_path):
                        file_input = layers.locator('input[type="file"][accept*="image"]').first
                        await file_input.set_input_files(image_path)
                        # Wait for upload preview to appear
                        await page.wait_for_selector('[data-testid="attachments"]', timeout=20000)
                        print("[OK] Image uploaded", file=sys.stderr)
                    else:
                        print("[WARN] Posting without image", file=sys.stderr)
            finally:
                if image_path and os.path.exists(image_path):
                    os.remove(image_path)

            # Click Post button inside the modal
            post_button = layers.get_by_test_id("tweetButtonInline").first
            await post_button.wait_for(state="visible", timeout=10000)
            # Poll until enabled (Twitter disables the button until text/image loaded)
            for _ in range(20):
                if await post_button.is_enabled():
                    break
                await page.wait_for_timeout(500)
            await post_button.click()

            # Confirm posted — modal closes (tweetTextarea disappears from #layers)
            await layers.get_by_test_id("tweetTextarea_0").first.wait_for(
                state="hidden", timeout=15000
            )
            print("[OK] Tweet posted successfully")
            return True

        except Exception as e:
            print(f"[ERROR] Post failed: {e}", file=sys.stderr)
            screenshot = f"/tmp/tweet_error_{os.getpid()}.png"
            await page.screenshot(path=screenshot)
            print(f"[DEBUG] Screenshot: {screenshot}", file=sys.stderr)
            return False

        finally:
            await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="Tweet text (up to 280 chars)")
    parser.add_argument("--text-file", help="File containing tweet text")
    parser.add_argument("--image_url", help="Image URL to attach")
    args = parser.parse_args()

    if args.text:
        text = args.text
    elif args.text_file:
        text = Path(args.text_file).read_text().strip()
    else:
        text = sys.stdin.read().strip()

    if not text:
        print("[ERROR] No tweet text provided", file=sys.stderr)
        sys.exit(1)

    if tweet_weight(text) > MAX_TWEET_WEIGHT:
        print(f"[ERROR] Text too long ({tweet_weight(text)} weighted chars, max {MAX_TWEET_WEIGHT})", file=sys.stderr)
        sys.exit(1)

    success = await post_tweet(text, args.image_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
