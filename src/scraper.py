"""
News content scraper.
Primary source: AI HOT API (aihot.virxact.com) — curated AI news, free, no auth.
Supplementary: GitHub Trending.
KOL scraping handled by TwitterBot.scrape_kol_posts().
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from urllib.parse import urlencode

from config import (
    AIHOT_ITEMS_URL,
    AIHOT_DAILY_URL,
    AIHOT_USER_AGENT,
    AIHOT_MAX_ITEMS,
    AIHOT_LOOKBACK_HOURS,
    AIHOT_CATEGORY_MAP,
    GITHUB_TRENDING_URL,
    CHROME_CDP_URL,
    IMAGE_CACHE_DIR,
    MAX_IMAGE_SIZE_MB,
)

logger = logging.getLogger(__name__)


@dataclass
class ScrapedItem:
    title: str
    url: str
    source: str
    snippet: str = ""
    summary: str = ""           # LLM-generated summary from AI HOT
    category: str = ""          # ai-models / ai-products / industry / paper / tip
    content_type: str = ""      # mapped to our types: ai_hot_take / ai_tool_review / ...
    image_url: str = ""         # original article image if available
    published_at: str = ""
    engagement: dict = field(default_factory=dict)
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class KOLPost:
    handle: str
    tier: str
    post_url: str
    content: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    posted_at: str = ""
    is_viral: bool = False


# ── AI HOT API ──

async def _http_get_json(url: str, headers: dict | None = None) -> dict | list | None:
    """
    Async HTTP GET via subprocess curl.
    We use curl instead of aiohttp to avoid adding dependencies.
    """
    cmd = [
        "curl", "-s", "-f",
        "-H", f"User-Agent: {AIHOT_USER_AGENT}",
        "-H", "Accept: application/json",
    ]
    if headers:
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30
        )

        if process.returncode != 0:
            logger.error("HTTP GET failed (%d): %s — %s", process.returncode, url, stderr.decode()[:200])
            return None

        return json.loads(stdout.decode("utf-8"))

    except asyncio.TimeoutError:
        logger.error("HTTP GET timed out: %s", url)
        return None
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error from %s: %s", url, exc)
        return None
    except Exception as exc:
        logger.error("HTTP GET error: %s — %s", url, exc)
        return None


async def _http_get_text(url: str) -> str | None:
    """Async HTTP GET returning raw text (for HTML pages)."""
    cmd = [
        "curl", "-s", "-f", "-L",
        "--max-time", "15",
        "-H", f"User-Agent: {AIHOT_USER_AGENT}",
    ]
    cmd.append(url)
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        if process.returncode != 0:
            return None
        return stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


async def fetch_og_image(source_url: str) -> str | None:
    """
    Fetch the og:image from a source article URL.
    Returns the image URL string, or None.
    """
    if not source_url:
        return None

    html = await _http_get_text(source_url)
    if not html:
        return None

    # Look for og:image meta tag
    patterns = [
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']twitter:image["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            image_url = match.group(1)
            if image_url.startswith("http"):
                return image_url

    return None


async def download_image(image_url: str, filename: str = "") -> str | None:
    """
    Download an image to IMAGE_CACHE_DIR.
    Returns local file path on success, None on failure.
    Auto-deletes after posting (caller's responsibility).
    """
    if not image_url:
        return None

    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not filename:
        # Generate filename from URL hash
        import hashlib
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        # Guess extension
        ext = ".jpg"
        if ".png" in image_url.lower():
            ext = ".png"
        elif ".webp" in image_url.lower():
            ext = ".webp"
        elif ".gif" in image_url.lower():
            ext = ".gif"
        filename = f"img_{url_hash}{ext}"

    output_path = IMAGE_CACHE_DIR / filename

    cmd = [
        "curl", "-s", "-f", "-L",
        "--max-time", "30",
        "--max-filesize", str(MAX_IMAGE_SIZE_MB * 1024 * 1024),
        "-o", str(output_path),
        image_url,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=35)

        if process.returncode == 0 and output_path.exists():
            file_size = output_path.stat().st_size
            if file_size > 1024:  # at least 1KB (skip broken images)
                logger.info("Image downloaded: %s (%d KB)", filename, file_size // 1024)
                return str(output_path)
            else:
                output_path.unlink(missing_ok=True)
                return None
        return None

    except Exception as exc:
        logger.warning("Image download failed: %s — %s", image_url[:80], exc)
        output_path.unlink(missing_ok=True)
        return None


async def fetch_image_for_item(item: "ScrapedItem") -> str | None:
    """
    Try to get an image for a scraped news item:
    1. If item already has image_url, download it directly
    2. Otherwise, fetch og:image from the source article
    Returns local file path or None.
    """
    image_url = item.image_url

    if not image_url and item.url:
        image_url = await fetch_og_image(item.url)
        if image_url:
            item.image_url = image_url

    if image_url:
        return await download_image(image_url)

    return None


async def scrape_aihot_items(
    since_hours: int = AIHOT_LOOKBACK_HOURS,
    take: int = AIHOT_MAX_ITEMS,
    category: str = "",
    keyword: str = "",
) -> list[ScrapedItem]:
    """
    Fetch curated AI news from AI HOT REST API.
    GET /api/public/items?mode=selected&since=<ISO>&take=50
    Returns ScrapedItem list with title, summary, url, category, content_type.
    """
    since_time = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    params = {
        "mode": "selected",
        "since": since_time,
        "take": str(take),
    }
    if category:
        params["category"] = category
    if keyword:
        params["q"] = keyword

    url = f"{AIHOT_ITEMS_URL}?{urlencode(params)}"
    data = await _http_get_json(url)

    if not data:
        logger.error("AI HOT items API returned nothing")
        return []

    raw_items = data.get("items", [])
    items = []

    for raw in raw_items:
        cat = raw.get("category", "")
        mapped_type = AIHOT_CATEGORY_MAP.get(cat, "ai_hot_take")

        item = ScrapedItem(
            title=raw.get("title", "") or raw.get("title_en", ""),
            url=raw.get("url", "") or raw.get("sourceUrl", ""),
            source=raw.get("source", "aihot"),
            snippet=raw.get("title_en", ""),
            summary=raw.get("summary", ""),
            category=cat,
            content_type=mapped_type,
            published_at=raw.get("publishedAt", ""),
        )
        items.append(item)

    logger.info("AI HOT: fetched %d curated items (since %dh ago)", len(items), since_hours)
    return items


async def scrape_aihot_daily() -> dict | None:
    """
    Fetch today's AI daily digest.
    GET /api/public/daily
    Returns the structured daily report with sections and flashes.
    """
    data = await _http_get_json(AIHOT_DAILY_URL)
    if not data:
        logger.warning("AI HOT daily digest unavailable")
        return None

    logger.info("AI HOT daily digest fetched for %s", data.get("date", "unknown"))
    return data


async def scrape_aihot_by_keyword(keyword: str, take: int = 20) -> list[ScrapedItem]:
    """
    Search AI HOT by keyword (server-side trigram search).
    GET /api/public/items?q=<keyword>&take=20
    """
    params = {"q": keyword, "take": str(take)}
    url = f"{AIHOT_ITEMS_URL}?{urlencode(params)}"
    data = await _http_get_json(url)

    if not data:
        return []

    items = []
    for raw in data.get("items", []):
        cat = raw.get("category", "")
        items.append(ScrapedItem(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            source=raw.get("source", "aihot"),
            summary=raw.get("summary", ""),
            category=cat,
            content_type=AIHOT_CATEGORY_MAP.get(cat, "ai_hot_take"),
        ))

    logger.info("AI HOT keyword search '%s': %d results", keyword, len(items))
    return items


# ── GitHub Trending (supplementary) ──

async def scrape_github_trending() -> list[ScrapedItem]:
    """Scrape GitHub trending repos via connected Chrome CDP."""
    items = []
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(CHROME_CDP_URL)
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            await pw.stop()
            return []

        page = await context.new_page()
        await page.goto(GITHUB_TRENDING_URL, wait_until="networkidle", timeout=15000)

        repos = await page.query_selector_all("article.Box-row")
        for repo in repos[:20]:
            name_el = await repo.query_selector("h2 a")
            desc_el = await repo.query_selector("p")
            lang_el = await repo.query_selector('[itemprop="programmingLanguage"]')
            stars_el = await repo.query_selector('a[href*="/stargazers"]')

            if name_el:
                name = (await name_el.inner_text()).strip().replace("\n", "").replace(" ", "")
                href = await name_el.get_attribute("href") or ""
                desc = (await desc_el.inner_text()).strip() if desc_el else ""
                lang = (await lang_el.inner_text()).strip() if lang_el else ""

                # Filter for AI-related repos
                ai_keywords = [
                    "ai", "llm", "gpt", "claude", "agent", "model",
                    "neural", "transformer", "machine-learning", "ml",
                    "anthropic", "openai", "inference", "fine-tun",
                    "rag", "embedding", "diffusion", "lora",
                ]
                combined = f"{name} {desc}".lower()
                if any(kw in combined for kw in ai_keywords):
                    items.append(ScrapedItem(
                        title=name,
                        url=f"https://github.com{href}",
                        source="github_trending",
                        snippet=desc,
                        content_type="ai_tool_review",
                    ))

        await page.close()
        await browser.close()
        await pw.stop()

    except Exception as exc:
        logger.error("GitHub trending scrape failed: %s", exc)

    logger.info("GitHub Trending: %d AI-related repos", len(items))
    return items


# ── Aggregator ──

async def scrape_all_news() -> list[ScrapedItem]:
    """
    Aggregate news from all sources.
    Primary: AI HOT API (curated, structured, with summaries).
    Supplementary: GitHub Trending (AI-filtered).
    """
    all_items: list[ScrapedItem] = []

    # Primary: AI HOT curated items (last 24h)
    aihot_items = await scrape_aihot_items()
    all_items.extend(aihot_items)

    # Supplementary: GitHub Trending
    gh_items = await scrape_github_trending()
    all_items.extend(gh_items)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_items: list[ScrapedItem] = []
    for item in all_items:
        if item.url and item.url not in seen_urls:
            seen_urls.add(item.url)
            unique_items.append(item)
        elif not item.url:
            unique_items.append(item)

    logger.info(
        "Total scraped: %d items (%d AI HOT + %d GitHub, %d after dedup)",
        len(all_items), len(aihot_items), len(gh_items), len(unique_items),
    )
    return unique_items


def dict_to_kol_post(d: dict) -> KOLPost:
    """Convert a dict (from TwitterBot.scrape_kol_posts) to KOLPost dataclass."""
    return KOLPost(
        handle=d.get("handle", ""),
        tier=d.get("tier", "tier3"),
        post_url=d.get("post_url", ""),
        content=d.get("content", ""),
        likes=d.get("likes", 0),
        retweets=d.get("retweets", 0),
        replies=d.get("replies", 0),
        is_viral=d.get("is_viral", False),
    )
