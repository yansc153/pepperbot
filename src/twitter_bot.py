"""
Twitter/X browser automation via Chrome CDP.
Connects to your already-logged-in Chrome browser.
No separate browser launch, no login needed.

Prerequisites:
  Start Chrome with: open -a "Google Chrome" --args --remote-debugging-port=9222
  Or add --remote-debugging-port=9222 to Chrome shortcut.

Uses Playwright's connect_over_cdp to attach to existing Chrome session.
All screenshots deleted after use. Known selectors cached.
"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from config import (
    TWITTER_HOME,
    TWITTER_URL,
    CHROME_CDP_URL,
    SCREENSHOT_DIR,
    PLAYWRIGHT_RULES_PATH,
    KOL_LIST_NAME,
)

# VPS headless mode: set HEADLESS=true to launch Chromium without CDP
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"
_COOKIE_FILE = Path(os.environ.get(
    "TWITTER_COOKIE_FILE",
    str(Path(__file__).resolve().parent.parent / "secrets" / "twitter_cookies.json"),
))

logger = logging.getLogger(__name__)


class TwitterBot:
    """Chrome CDP-based Twitter automation. Connects to existing browser."""

    def __init__(self) -> None:
        self._playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._selectors = self._load_known_selectors()

    def _load_known_selectors(self) -> dict:
        """Known Twitter/X DOM selectors."""
        return {
            "tweet_input": '[data-testid="tweetTextarea_0"]',
            "tweet_button": '[data-testid="tweetButtonInline"]',
            "reply_input": '[data-testid="tweetTextarea_0"]',
            "reply_button": '[data-testid="tweetButton"]',
            "like_button": '[data-testid="like"]',
            "unlike_button": '[data-testid="unlike"]',
            "retweet_button": '[data-testid="retweet"]',
            "image_input": 'input[data-testid="fileInput"]',
            "tweet_text": '[data-testid="tweetText"]',
            "tweet_element": '[data-testid="tweet"]',
            "search_input": '[data-testid="SearchBox_Search_Input"]',
        }

    async def start(self) -> None:
        """
        Start browser connection. Two modes:
          HEADLESS=false (default): connect to existing Chrome via CDP (Mac, Chrome must be running)
          HEADLESS=true: launch headless Chromium with twitter_cookies.json (VPS)
        """
        self._playwright = await async_playwright().start()
        try:
            if HEADLESS:
                await self._start_headless()
            else:
                await self._start_cdp()
        except Exception as exc:
            logger.error("Browser start failed: %s", exc)
            raise

    async def _start_headless(self) -> None:
        """VPS path: launch headless Chromium + load Twitter cookie file."""
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            logger.warning("playwright-stealth not installed — bot detection risk higher")
            stealth_async = None

        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        if _COOKIE_FILE.exists():
            cookies = json.loads(_COOKIE_FILE.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
            logger.info("Loaded %d cookies from %s", len(cookies), _COOKIE_FILE)
        else:
            logger.warning("Cookie file not found: %s — will likely fail login check", _COOKIE_FILE)

        self.page = await context.new_page()
        if stealth_async:
            await stealth_async(self.page)

        logger.info("Headless Chromium started")

    async def _start_cdp(self) -> None:
        """Mac path: connect to existing Chrome via CDP."""
        self.browser = await self._playwright.chromium.connect_over_cdp(CHROME_CDP_URL)
        logger.info("Connected to Chrome via CDP at %s", CHROME_CDP_URL)

        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("No browser contexts found. Is Chrome running?")

        pages = contexts[0].pages
        twitter_page = None
        for p in pages:
            if "x.com" in p.url or "twitter.com" in p.url:
                twitter_page = p
                break

        if twitter_page:
            self.page = twitter_page
            logger.info("Found existing X tab: %s", self.page.url)
        else:
            self.page = await contexts[0].new_page()
            await self.page.goto(TWITTER_HOME, wait_until="networkidle", timeout=15000)
            logger.info("Opened new X tab")

    async def stop(self) -> None:
        """Disconnect from Chrome (doesn't close the browser)."""
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Disconnected from Chrome")

    async def _screenshot(self, name: str = "action") -> str | None:
        """Take screenshot, return path. Must be deleted after use."""
        if not self.page:
            return None
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
        try:
            await self.page.screenshot(path=str(path))
            return str(path)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    def _cleanup(self, path: str | None) -> None:
        """Delete screenshot immediately."""
        if path and os.path.exists(path):
            os.remove(path)

    async def _save_selector(self, name: str, selector: str) -> None:
        """Update known selectors and persist."""
        self._selectors[name] = selector
        try:
            with open(PLAYWRIGHT_RULES_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n- [{datetime.now().strftime('%Y-%m-%d')}] {name}: `{selector}`")
        except Exception:
            pass

    async def is_logged_in(self) -> bool:
        """Check if the connected Chrome is logged into X."""
        if not self.page:
            return False
        try:
            url = self.page.url
            if "x.com" not in url and "twitter.com" not in url:
                await self.page.goto(TWITTER_HOME, wait_until="networkidle", timeout=15000)

            if "/login" in self.page.url or "/i/flow/login" in self.page.url:
                return False

            el = await self.page.query_selector(self._selectors["tweet_input"])
            return el is not None
        except Exception:
            return False

    async def navigate_to_home(self) -> bool:
        """Go to Twitter home timeline."""
        if not self.page:
            return False
        try:
            await self.page.goto(TWITTER_HOME, wait_until="networkidle", timeout=15000)
            return True
        except Exception as exc:
            logger.error("Failed to navigate home: %s", exc)
            return False

    async def post_tweet(self, text: str, image_path: str | None = None) -> str | None:
        """
        Post a tweet in the connected Chrome.
        Returns the tweet URL on success, None on failure.
        """
        if not self.page:
            return None

        try:
            await self.navigate_to_home()
            await self.page.wait_for_timeout(2000)

            # Click compose area
            compose = await self.page.wait_for_selector(
                self._selectors["tweet_input"], timeout=10000
            )
            if not compose:
                shot = await self._screenshot("compose_not_found")
                logger.error("Compose box not found")
                self._cleanup(shot)
                return None

            await compose.click()
            await self.page.keyboard.type(text, delay=30)

            # Upload image if provided
            if image_path and os.path.exists(image_path):
                file_input = await self.page.query_selector(self._selectors["image_input"])
                if file_input:
                    await file_input.set_input_files(image_path)
                    await self.page.wait_for_timeout(2000)

            # Click post button
            post_btn = await self.page.wait_for_selector(
                self._selectors["tweet_button"], timeout=5000
            )
            if not post_btn:
                logger.error("Post button not found")
                return None

            await post_btn.click()
            await self.page.wait_for_timeout(3000)
            logger.info("Tweet posted: %s...", text[:50])

            # Extract tweet URL from the page after posting
            tweet_url = await self._extract_latest_tweet_url()
            if tweet_url:
                logger.info("Tweet URL: %s", tweet_url)
            else:
                logger.warning("Could not extract tweet URL, using profile fallback")
                tweet_url = f"{TWITTER_URL}/pepperfr1ends"

            return tweet_url

        except Exception as exc:
            logger.error("Tweet posting failed: %s", exc)
            shot = await self._screenshot("post_error")
            self._cleanup(shot)
            return None

    async def _extract_latest_tweet_url(self) -> str | None:
        """
        After posting, navigate to profile and grab the latest tweet's URL.
        Twitter redirects or shows a toast, but the most reliable method is
        checking our own profile for the newest tweet.
        """
        try:
            await self.page.goto(
                f"{TWITTER_URL}/pepperfr1ends",
                wait_until="networkidle", timeout=15000,
            )
            await self.page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

            # Get the first (newest) tweet
            first_tweet = await self.page.query_selector('[data-testid="tweet"]')
            if not first_tweet:
                return None

            time_el = await first_tweet.query_selector("time")
            if time_el:
                parent_a = await time_el.evaluate("el => el.closest('a')?.href")
                if parent_a and "status" in str(parent_a):
                    return str(parent_a)

            return None
        except Exception as exc:
            logger.warning("Failed to extract tweet URL: %s", exc)
            return None

    async def post_comment(self, post_url: str, comment_text: str) -> bool:
        """Comment on a specific tweet."""
        if not self.page:
            return False

        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=15000)
            await self.page.wait_for_timeout(1500)

            # On tweet detail page, reply box is below the tweet.
            # Try the reply-specific textarea first, then fall back to generic.
            reply_input = await self.page.query_selector(
                '[data-testid="tweetTextarea_0RichTextInputContainer"]'
            )
            if not reply_input:
                # Fallback: click the reply area text
                reply_input = await self.page.wait_for_selector(
                    self._selectors["reply_input"], timeout=10000
                )
            if not reply_input:
                logger.error("Reply input not found at %s", post_url)
                return False

            await reply_input.click()
            await self.page.wait_for_timeout(500)
            await self.page.keyboard.type(comment_text, delay=30)

            # Reply button on detail page has testid="tweetButton" (not tweetButtonInline)
            reply_btn = await self.page.wait_for_selector(
                self._selectors["reply_button"], timeout=5000
            )
            if reply_btn:
                await reply_btn.click()
                await self.page.wait_for_timeout(2000)
                logger.info("Comment posted on %s", post_url)
                return True

            return False

        except Exception as exc:
            logger.error("Commenting failed on %s: %s", post_url, exc)
            return False

    async def like_tweet(self, post_url: str) -> bool:
        """Like a tweet. Skips if already liked."""
        if not self.page:
            return False
        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=15000)

            # Check if already liked (unlike button present = already liked)
            unlike_btn = await self.page.query_selector(self._selectors["unlike_button"])
            if unlike_btn:
                logger.info("Already liked: %s", post_url)
                return False

            like_btn = await self.page.wait_for_selector(
                self._selectors["like_button"], timeout=5000
            )
            if like_btn:
                await like_btn.click()
                await self.page.wait_for_timeout(1000)
                return True
            return False
        except Exception as exc:
            logger.error("Like failed: %s", exc)
            return False

    async def follow_user(self, handle: str) -> bool:
        """Follow a user by visiting their profile. Skips if already following."""
        if not self.page:
            return False
        try:
            profile_url = f"{TWITTER_URL}/{handle.lstrip('@')}"
            await self.page.goto(profile_url, wait_until="networkidle", timeout=15000)

            # Check if already following (button text = "Following" / "正在关注")
            follow_btns = await self.page.query_selector_all('[role="button"]')
            for btn in follow_btns:
                text = (await btn.inner_text()).strip().lower()
                if text in ("following", "正在关注"):
                    logger.info("Already following %s", handle)
                    return False
                if text in ("follow", "关注"):
                    await btn.click()
                    await self.page.wait_for_timeout(1000)
                    logger.info("Followed %s", handle)
                    return True
            return False
        except Exception as exc:
            logger.error("Follow failed for %s: %s", handle, exc)
            return False

    async def get_post_metrics(self, post_url: str) -> dict:
        """Scrape engagement metrics for a specific post."""
        if not self.page:
            return {}
        try:
            await self.page.goto(post_url, wait_until="networkidle", timeout=15000)

            metrics = {"likes": 0, "retweets": 0, "replies": 0, "impressions": 0}

            groups = await self.page.query_selector_all('[role="group"] button')
            for group in groups:
                aria = await group.get_attribute("aria-label") or ""
                aria_lower = aria.lower()
                if "like" in aria_lower or "赞" in aria_lower:
                    metrics["likes"] = _extract_number(aria)
                elif "repost" in aria_lower or "retweet" in aria_lower:
                    metrics["retweets"] = _extract_number(aria)
                elif "repl" in aria_lower or "回复" in aria_lower:
                    metrics["replies"] = _extract_number(aria)
                elif "view" in aria_lower or "浏览" in aria_lower:
                    metrics["impressions"] = _extract_number(aria)

            return metrics

        except Exception as exc:
            logger.error("Metrics scrape failed for %s: %s", post_url, exc)
            return {}

    async def get_follower_count(self) -> int:
        """Get current follower count."""
        if not self.page:
            return 0
        try:
            await self.page.goto(
                f"{TWITTER_URL}/pepperfr1ends",
                wait_until="networkidle", timeout=15000,
            )
            followers_link = await self.page.query_selector('a[href$="/verified_followers"]')
            if not followers_link:
                followers_link = await self.page.query_selector('a[href$="/followers"]')
            if followers_link:
                text = await followers_link.inner_text()
                return _extract_number(text)
            return 0
        except Exception as exc:
            logger.error("Follower count scrape failed: %s", exc)
            return 0

    async def check_rate_limit(self) -> bool:
        """Check if Twitter is rate limiting us."""
        if not self.page:
            return False
        try:
            content = await self.page.content()
            rate_limit_signals = [
                "Rate limit exceeded",
                "Try again later",
                "你的请求太多了",
                "Something went wrong",
            ]
            for signal in rate_limit_signals:
                if signal.lower() in content.lower():
                    logger.warning("Rate limit detected: %s", signal)
                    return True
            return False
        except Exception:
            return False

    async def scrape_kol_posts(
        self,
        kol_handles: list[dict],
        max_per_kol: int = 3,
    ) -> list[dict]:
        """
        Scrape KOL posts directly in the connected Chrome.
        Returns list of dicts with handle, tier, post_url, content, likes, etc.
        """
        if not self.page:
            return []

        posts = []
        for kol in kol_handles:
            handle = kol["handle"].lstrip("@")
            tier = kol.get("tier", "tier3")
            profile_url = f"{TWITTER_URL}/{handle}"

            try:
                await self.page.goto(profile_url, wait_until="networkidle", timeout=20000)
                await self.page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

                tweet_elements = await self.page.query_selector_all('[data-testid="tweet"]')
                for tweet_el in tweet_elements[:max_per_kol]:
                    text_el = await tweet_el.query_selector('[data-testid="tweetText"]')
                    if not text_el:
                        continue
                    text = await text_el.inner_text()

                    likes = 0
                    retweets = 0
                    replies = 0

                    groups = await tweet_el.query_selector_all('[role="group"] button')
                    for group in groups:
                        aria = await group.get_attribute("aria-label") or ""
                        aria_lower = aria.lower()
                        if "like" in aria_lower or "赞" in aria_lower:
                            likes = _extract_number(aria)
                        elif "repost" in aria_lower or "retweet" in aria_lower:
                            retweets = _extract_number(aria)
                        elif "repl" in aria_lower or "回复" in aria_lower:
                            replies = _extract_number(aria)

                    time_el = await tweet_el.query_selector("time")
                    post_url = profile_url
                    if time_el:
                        parent_a = await time_el.evaluate("el => el.closest('a')?.href")
                        if parent_a:
                            post_url = parent_a

                    posts.append({
                        "handle": f"@{handle}",
                        "tier": tier,
                        "post_url": post_url,
                        "content": text,
                        "likes": likes,
                        "retweets": retweets,
                        "replies": replies,
                        "is_viral": likes >= 200 or retweets >= 50,
                    })

            except Exception as exc:
                logger.warning("Failed to scrape @%s: %s", handle, exc)
                continue

        return posts

    # ── Twitter List management ──

    async def create_kol_list(self, list_name: str = KOL_LIST_NAME) -> bool:
        """
        Create a private Twitter List for monitoring KOLs.
        Navigates to Lists page and creates if not exists.
        """
        if not self.page:
            return False
        try:
            await self.page.goto(f"{TWITTER_URL}/i/lists", wait_until="networkidle", timeout=15000)
            await self.page.wait_for_timeout(1500)

            # Check if list already exists
            page_content = await self.page.content()
            if list_name in page_content:
                logger.info("List '%s' already exists", list_name)
                return True

            # Click "Create a new List" button
            create_btn = await self.page.query_selector('[data-testid="createList"]')
            if not create_btn:
                # Try alternate: the + icon or "New List" button
                new_list_links = await self.page.query_selector_all('a[href="/i/lists/create"]')
                if new_list_links:
                    await new_list_links[0].click()
                else:
                    logger.error("Cannot find create list button")
                    return False
            else:
                await create_btn.click()

            await self.page.wait_for_timeout(1500)

            # Type list name
            name_input = await self.page.wait_for_selector(
                'input[name="name"], input[placeholder*="Name"], input[data-testid="listNameInput"]',
                timeout=5000,
            )
            if name_input:
                await name_input.fill(list_name)

            # Make it private
            private_toggle = await self.page.query_selector(
                'input[type="checkbox"], [role="checkbox"]'
            )
            if private_toggle:
                is_checked = await private_toggle.is_checked() if hasattr(private_toggle, 'is_checked') else False
                if not is_checked:
                    await private_toggle.click()

            # Click save/next
            save_btn = await self.page.query_selector('[data-testid="listCreationSaveButton"]')
            if not save_btn:
                save_btn = await self.page.query_selector('div[role="button"][data-testid="createListSaveButton"]')
            if save_btn:
                await save_btn.click()
                await self.page.wait_for_timeout(2000)
                logger.info("Created list '%s'", list_name)
                return True

            return False

        except Exception as exc:
            logger.error("Create list failed: %s", exc)
            return False

    async def add_to_list(self, handle: str, list_name: str = KOL_LIST_NAME) -> bool:
        """Add a user to our KOL monitoring list."""
        if not self.page:
            return False
        try:
            clean_handle = handle.lstrip("@")
            profile_url = f"{TWITTER_URL}/{clean_handle}"
            await self.page.goto(profile_url, wait_until="networkidle", timeout=15000)
            await self.page.wait_for_timeout(1000)

            # Click the "..." more button on profile
            more_btn = await self.page.query_selector('[data-testid="userActions"]')
            if not more_btn:
                logger.warning("More button not found for @%s", clean_handle)
                return False

            await more_btn.click()
            await self.page.wait_for_timeout(800)

            # Click "Add/remove from Lists"
            menu_items = await self.page.query_selector_all('[role="menuitem"]')
            for item in menu_items:
                text = await item.inner_text()
                if "list" in text.lower() or "列表" in text:
                    await item.click()
                    await self.page.wait_for_timeout(1500)

                    # Find our list and check it
                    list_items = await self.page.query_selector_all('[role="listbox"] [role="option"], [role="checkbox"]')
                    for li in list_items:
                        li_text = await li.inner_text()
                        if list_name in li_text:
                            await li.click()
                            await self.page.wait_for_timeout(500)
                            logger.info("Added @%s to list '%s'", clean_handle, list_name)

                            # Close the modal
                            done_btn = await self.page.query_selector('[data-testid="listCellDoneButton"]')
                            if done_btn:
                                await done_btn.click()
                            return True

                    # Close modal if list not found
                    await self.page.keyboard.press("Escape")
                    return False

            return False

        except Exception as exc:
            logger.error("Add to list failed for @%s: %s", handle, exc)
            return False

    async def scrape_list_timeline(
        self,
        list_name: str = KOL_LIST_NAME,
        max_posts: int = 30,
    ) -> list[dict]:
        """
        Scrape posts from our KOL monitoring list's timeline.
        Much more efficient than visiting each KOL's profile individually.
        Returns list of dicts same format as scrape_kol_posts.
        """
        if not self.page:
            return []

        posts = []
        try:
            # Navigate to Lists page to find our list
            await self.page.goto(f"{TWITTER_URL}/i/lists", wait_until="networkidle", timeout=15000)
            await self.page.wait_for_timeout(1500)

            # Find and click our list
            list_links = await self.page.query_selector_all('a[href*="/i/lists/"]')
            target_list = None
            for link in list_links:
                text = await link.inner_text()
                if list_name in text:
                    target_list = link
                    break

            if not target_list:
                logger.warning("List '%s' not found", list_name)
                return []

            await target_list.click()
            await self.page.wait_for_timeout(2000)
            await self.page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

            # Scrape tweets from the list timeline
            tweet_elements = await self.page.query_selector_all('[data-testid="tweet"]')

            for tweet_el in tweet_elements[:max_posts]:
                text_el = await tweet_el.query_selector('[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = await text_el.inner_text()

                # Get author handle
                handle = ""
                author_links = await tweet_el.query_selector_all('a[role="link"]')
                for a_link in author_links:
                    href = await a_link.get_attribute("href") or ""
                    if href.startswith("/") and "/" not in href[1:] and len(href) > 2:
                        handle = f"@{href[1:]}"
                        break

                # Get metrics
                likes = 0
                retweets = 0
                replies = 0
                groups = await tweet_el.query_selector_all('[role="group"] button')
                for group in groups:
                    aria = await group.get_attribute("aria-label") or ""
                    aria_lower = aria.lower()
                    if "like" in aria_lower or "赞" in aria_lower:
                        likes = _extract_number(aria)
                    elif "repost" in aria_lower or "retweet" in aria_lower:
                        retweets = _extract_number(aria)
                    elif "repl" in aria_lower or "回复" in aria_lower:
                        replies = _extract_number(aria)

                # Get post URL
                time_el = await tweet_el.query_selector("time")
                post_url = ""
                if time_el:
                    parent_a = await time_el.evaluate("el => el.closest('a')?.href")
                    if parent_a:
                        post_url = str(parent_a)

                posts.append({
                    "handle": handle,
                    "tier": "unknown",  # will be enriched by engagement.py
                    "post_url": post_url,
                    "content": text,
                    "likes": likes,
                    "retweets": retweets,
                    "replies": replies,
                    "is_viral": likes >= 200 or retweets >= 50,
                })

        except Exception as exc:
            logger.error("List timeline scrape failed: %s", exc)

        logger.info("Scraped %d posts from list '%s'", len(posts), list_name)
        return posts

    async def scrape_list_by_url(
        self,
        list_url: str,
        max_posts: int = 30,
    ) -> list[dict]:
        """
        Scrape posts directly from a Twitter List URL.
        More reliable than searching by name — just navigate to the URL.
        Returns list of dicts same format as scrape_kol_posts.
        """
        if not self.page:
            return []

        posts = []
        try:
            await self.page.goto(list_url, wait_until="networkidle", timeout=20000)
            await self.page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

            tweet_elements = await self.page.query_selector_all('[data-testid="tweet"]')

            for tweet_el in tweet_elements[:max_posts]:
                text_el = await tweet_el.query_selector('[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = await text_el.inner_text()

                # Get author handle
                handle = ""
                author_links = await tweet_el.query_selector_all('a[role="link"]')
                for a_link in author_links:
                    href = await a_link.get_attribute("href") or ""
                    if href.startswith("/") and "/" not in href[1:] and len(href) > 2:
                        handle = f"@{href[1:]}"
                        break

                # Get metrics
                likes = 0
                retweets = 0
                replies = 0
                groups = await tweet_el.query_selector_all('[role="group"] button')
                for group in groups:
                    aria = await group.get_attribute("aria-label") or ""
                    aria_lower = aria.lower()
                    if "like" in aria_lower or "赞" in aria_lower:
                        likes = _extract_number(aria)
                    elif "repost" in aria_lower or "retweet" in aria_lower:
                        retweets = _extract_number(aria)
                    elif "repl" in aria_lower or "回复" in aria_lower:
                        replies = _extract_number(aria)

                # Get post URL
                time_el = await tweet_el.query_selector("time")
                post_url = ""
                if time_el:
                    parent_a = await time_el.evaluate("el => el.closest('a')?.href")
                    if parent_a:
                        post_url = str(parent_a)

                posts.append({
                    "handle": handle,
                    "tier": "unknown",
                    "post_url": post_url,
                    "content": text,
                    "likes": likes,
                    "retweets": retweets,
                    "replies": replies,
                    "is_viral": likes >= 200 or retweets >= 50,
                })

        except Exception as exc:
            logger.error("List URL scrape failed: %s", exc)

        logger.info("Scraped %d posts from list URL", len(posts))
        return posts

    async def batch_follow_kols(self, handles: list[str]) -> int:
        """Follow a batch of KOL handles. Returns count of new follows."""
        followed = 0
        for handle in handles:
            success = await self.follow_user(handle)
            if success:
                followed += 1
            await asyncio.sleep(random.uniform(3, 8))
        logger.info("Batch follow: %d/%d succeeded", followed, len(handles))
        return followed


def _extract_number(text: str) -> int:
    """Extract number from aria-label like '42 Likes' or '1.2K Reposts'."""
    match = re.search(r"([\d,.]+)\s*([KkMm])?", text)
    if not match:
        return 0
    num_str = match.group(1).replace(",", "")
    try:
        num = float(num_str)
    except ValueError:
        return 0
    suffix = match.group(2)
    if suffix and suffix.upper() == "K":
        num *= 1000
    elif suffix and suffix.upper() == "M":
        num *= 1_000_000
    return int(num)
