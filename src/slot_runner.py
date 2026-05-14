#!/usr/bin/env python3
"""
Slot entry point for cron scheduling. Maps slot names to main.py sessions.

Usage:
  python src/slot_runner.py --slot slot1               # run morning session
  python src/slot_runner.py --slot slot1 --dry-run     # scrape + generate only, no post

Slot → session mapping (CST):
  slot1  → morning  (07:00)
  slot2  → noon     (11:00)
  slot3  → evening  (16:00)
  slot4  → evening  (20:00)
  slot5  → evening  (23:00)
  review → review   (00:00)

Set env vars before running:
  HEADLESS=true             use headless Chromium (VPS)
  LLM_BACKEND=moonshot      use Moonshot API for LLM calls
  MOONSHOT_API_KEY=...
  TWITTER_COOKIE_FILE=...   path to twitter_cookies.json
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure src/ is on path when called from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import LOG_FORMAT, LOG_DATE_FORMAT

SLOT_TO_SESSION = {
    "slot1": "morning",
    "slot2": "noon",
    "slot3": "evening",
    "slot4": "evening",
    "slot5": "evening",
    "review": "review",
}

COOKIE_WARN_DAYS = 25
_COOKIE_FILE = Path(os.environ.get(
    "TWITTER_COOKIE_FILE",
    str(Path(__file__).resolve().parent.parent / "secrets" / "twitter_cookies.json"),
))

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)
logger = logging.getLogger("slot_runner")


def _check_cookie_age() -> None:
    """Warn if cookie file is older than COOKIE_WARN_DAYS days."""
    if not _COOKIE_FILE.exists():
        logger.warning("Cookie file not found: %s", _COOKIE_FILE)
        return
    mtime = _COOKIE_FILE.stat().st_mtime
    age_days = (datetime.now().timestamp() - mtime) / 86400
    if age_days > COOKIE_WARN_DAYS:
        logger.warning(
            "Cookie file is %.0f days old (warn threshold: %d days). "
            "Re-run cookie_exporter.py on Mac and scp to VPS.",
            age_days, COOKIE_WARN_DAYS,
        )
    else:
        logger.info("Cookie file age: %.1f days (ok)", age_days)


async def _dry_run(session: str) -> None:
    """Print what would be scraped and generated without posting."""
    from database import init_database
    from scraper import scrape_all_news
    from learner import get_learned_techniques
    from writer import write_tweet
    from guardrails import run_all_guardrails

    init_database()
    logger.info("[DRY RUN] session=%s — scraping news...", session)
    news_items = await scrape_all_news()
    logger.info("[DRY RUN] scraped %d items", len(news_items))

    techniques = get_learned_techniques()

    content_type_map = {
        "morning": "ai_hot_take",
        "noon": "ai_tool_review",
        "evening": "startup_cognition",
        "review": None,
    }
    content_type = content_type_map.get(session, "ai_hot_take")

    if content_type is None:
        logger.info("[DRY RUN] review session — no content generation, dry run complete")
        return

    source_material = ""
    if news_items:
        item = news_items[0]
        parts = [f"标题: {item.title}"]
        if item.summary:
            parts.append(f"摘要: {item.summary}")
        source_material = "\n".join(parts)

    logger.info("[DRY RUN] generating tweet (type=%s)...", content_type)
    result = await write_tweet(
        content_type=content_type,
        source_material=source_material,
        techniques=techniques,
    )

    if result:
        tweet = result.get("tweet", "")
        print("\n" + "=" * 60)
        print("[DRY RUN] Generated tweet:")
        print(tweet)
        print("=" * 60 + "\n")

        violations = run_all_guardrails(tweet)
        if violations:
            logger.warning("[DRY RUN] Guardrail violations: %s", violations)
        else:
            logger.info("[DRY RUN] Guardrails passed")
    else:
        logger.warning("[DRY RUN] Tweet generation returned None")


async def _run_session(session: str) -> None:
    """Run a full session via main.py's run_single_session."""
    from database import init_database
    from main import run_single_session

    init_database()
    await run_single_session(session)


def main() -> None:
    parser = argparse.ArgumentParser(description="PepperBot slot runner")
    parser.add_argument(
        "--slot",
        required=True,
        choices=list(SLOT_TO_SESSION.keys()),
        help="Slot name: slot1-slot5 or review",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and generate but do not post",
    )
    args = parser.parse_args()

    session = SLOT_TO_SESSION[args.slot]
    headless = os.environ.get("HEADLESS", "false").lower() == "true"

    logger.info("slot=%s → session=%s | HEADLESS=%s | LLM_BACKEND=%s",
                args.slot, session, headless, os.environ.get("LLM_BACKEND", "claude"))

    if headless:
        _check_cookie_age()

    if args.dry_run:
        asyncio.run(_dry_run(session))
    else:
        asyncio.run(_run_session(session))


if __name__ == "__main__":
    main()
