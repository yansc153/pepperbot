"""
Main orchestrator for the posting-only pepperbot.

Runtime contract:
  - periodic2h: posting every 2 hours
  - slot1-slot5: posting only
  - observe: KOL list observation only
  - review: metrics + post review only
"""

import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    DEFAULT_WEIGHTS,
    MAX_POSTS_PER_DAY,
    REVIEW_WINDOWS_HOURS,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
)
from database import (
    init_database,
    get_connection,
    insert_post,
    get_latest_weights,
    mark_post_published,
    is_duplicate,
    get_today_post_count,
    get_posts_needing_metrics,
    update_post_metrics,
    upsert_daily_stats,
)
from guardrails import has_kill_violation
from scraper import scrape_all_news, ScrapedItem, fetch_image_for_item
from scorer import score_content, decide_publish
from writer import write_tweet
from twitter_bot import TwitterBot
from learner import (
    analyze_own_posts,
    build_reaction_pack,
    check_circuit_breaker,
    observe_kol_reactions,
    get_latest_review_learning,
)
from obsidian_logger import (
    log_post,
    log_daily_summary,
    log_learning,
    log_system_event,
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pepperbot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

POSTING_SLOT_PROFILES: dict[str, dict] = {
    "periodic2h": {
        "label": "Every 2h feedback-driven post",
        "target_count": 1,
        "weights": {
            "ai_hot_take": 0.30,
            "ai_tool_review": 0.25,
            "startup_cognition": 0.25,
            "controversy": 0.20,
            "kol_interaction": 0.00,
        },
    },
    "slot1": {
        "label": "07:00 fast AI read",
        "target_count": 2,
        "weights": {
            "ai_hot_take": 0.50,
            "ai_tool_review": 0.35,
            "startup_cognition": 0.10,
            "controversy": 0.05,
            "kol_interaction": 0.00,
        },
    },
    "slot2": {
        "label": "11:00 tool + founder angle",
        "target_count": 2,
        "weights": {
            "ai_hot_take": 0.15,
            "ai_tool_review": 0.45,
            "startup_cognition": 0.35,
            "controversy": 0.05,
            "kol_interaction": 0.00,
        },
    },
    "slot3": {
        "label": "16:00 follow-up reaction",
        "target_count": 2,
        "weights": {
            "ai_hot_take": 0.45,
            "ai_tool_review": 0.15,
            "startup_cognition": 0.35,
            "controversy": 0.05,
            "kol_interaction": 0.00,
        },
    },
    "slot4": {
        "label": "20:00 sharp angle",
        "target_count": 2,
        "weights": {
            "ai_hot_take": 0.35,
            "ai_tool_review": 0.20,
            "startup_cognition": 0.15,
            "controversy": 0.30,
            "kol_interaction": 0.00,
        },
    },
    "slot5": {
        "label": "23:00 deep judgment",
        "target_count": 2,
        "weights": {
            "ai_hot_take": 0.20,
            "ai_tool_review": 0.15,
            "startup_cognition": 0.40,
            "controversy": 0.25,
            "kol_interaction": 0.00,
        },
    },
}

SCHEDULER_HOURS = {
    "slot1": 7,
    "slot2": 11,
    "slot3": 16,
    "slot4": 20,
    "slot5": 23,
    "review": 0,
}


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def _pick_content_type(weights: dict[str, float]) -> str:
    types = list(weights.keys())
    probs = list(weights.values())
    return random.choices(types, weights=probs, k=1)[0]


def _scheduler_due_sessions(hour: int, today_key: str, executed: set[str]) -> list[tuple[str, str]]:
    """Return scheduler sessions due for this hour, with review before posting."""
    due_sessions: list[tuple[str, str]] = []

    review_key = f"{today_key}_review"
    if hour == SCHEDULER_HOURS["review"] and review_key not in executed:
        due_sessions.append(("review", review_key))

    periodic_key = f"{today_key}_periodic2h_{hour}"
    if hour % 2 == 0 and periodic_key not in executed:
        due_sessions.append(("periodic2h", periodic_key))

    return due_sessions


def _blend_weights(
    base: dict[str, float],
    learned: dict[str, float],
    alpha: float = 0.6,
) -> dict[str, float]:
    """
    Blend base profile weights with learned weights.
    Higher alpha means more weight is given to learnings.
    """
    if not learned:
        return base

    blended = {
        content_type: (1 - alpha) * base.get(content_type, 0.0)
        + alpha * learned.get(content_type, 0.0)
        for content_type in base
    }
    return _normalize_weights(blended)


def _build_source_material(item: ScrapedItem | None) -> str:
    if not item:
        return ""
    parts = [f"标题: {item.title}"]
    if item.summary:
        parts.append(f"摘要: {item.summary}")
    elif item.snippet:
        parts.append(f"简介: {item.snippet}")
    if item.url:
        parts.append(f"来源URL: {item.url}")
    if item.source:
        parts.append(f"来源: {item.source}")
    if item.published_at:
        parts.append(f"发布时间: {item.published_at}")
    return "\n".join(parts)


def _pick_news_item(
    content_type: str,
    news_items: list[ScrapedItem],
) -> ScrapedItem | None:
    if not news_items:
        return None

    for index, item in enumerate(news_items):
        if item.content_type == content_type:
            return news_items.pop(index)
    return news_items.pop(0)


async def _generate_and_publish_posts(
    bot: TwitterBot,
    slot_name: str,
    target_count: int,
    news_items: list[ScrapedItem],
    weights: dict[str, float],
    learning_context: dict[str, object] | None = None,
) -> int:
    """
    Deterministic posting-only loop:
    source -> reaction pack -> draft -> score -> image -> post -> write tweet_url
    """
    conn = get_connection()
    published = 0
    today_total = get_today_post_count(conn)

    try:
        max_attempts = max(target_count * 3, target_count)
        attempts = 0
        while published < target_count and attempts < max_attempts:
            attempts += 1
            if today_total + published >= MAX_POSTS_PER_DAY:
                logger.warning("Daily post cap reached: %d", MAX_POSTS_PER_DAY)
                break
            if not news_items:
                logger.warning("[%s] No source-backed news items left, stopping", slot_name)
                break

            content_type = _pick_content_type(weights)
            matched_item = _pick_news_item(content_type, news_items)
            source_material = _build_source_material(matched_item)
            source_url = matched_item.url if matched_item else ""
            source_title = matched_item.title if matched_item else ""

            reaction_pack = await build_reaction_pack(
                source_material=source_material,
                source_url=source_url,
                source_title=source_title,
            )

            result = await write_tweet(
                content_type=content_type,
                source_material=source_material,
                reaction_pack=reaction_pack,
                learning_context=learning_context,
            )
            if not result:
                logger.warning("[%s] Tweet generation failed for %s", slot_name, content_type)
                continue

            tweet_text = result["tweet"]
            if is_duplicate(conn, tweet_text):
                logger.info("[%s] Duplicate detected, skipping", slot_name)
                continue

            scores = await score_content(tweet_text, content_type, source_material)
            decision = decide_publish(scores["total"])
            if decision == "drop":
                logger.info("[%s] Score too low (%d), dropping", slot_name, scores["total"])
                continue

            if decision == "needs_review":
                result = await write_tweet(
                    content_type=content_type,
                    source_material=source_material,
                    extra_context=f"上一版评分{scores['total']}/85，需要更具体、更自然",
                    reaction_pack=reaction_pack,
                    learning_context=learning_context,
                )
                if not result:
                    continue
                tweet_text = result["tweet"]
                scores = await score_content(tweet_text, content_type, source_material)
                if decide_publish(scores["total"]) == "drop":
                    continue

            if has_kill_violation(tweet_text):
                logger.error("[%s] Kill violation in final check", slot_name)
                continue

            image_path = None
            if matched_item:
                image_path = await fetch_image_for_item(matched_item, bot=bot)

            if not image_path:
                logger.warning("[%s] Missing image for '%s' — skipping post", slot_name, source_title[:80])
                continue

            post_id = insert_post(
                conn=conn,
                content=tweet_text,
                content_type=content_type,
                image_prompt=result.get("image_prompt", ""),
                scores=scores,
                source_url=source_url,
                source_title=source_title,
            )

            tweet_url = await bot.post_tweet(tweet_text, image_path=image_path)
            if tweet_url:
                mark_post_published(conn, post_id, tweet_url=tweet_url)
                published += 1
                post_number = today_total + published
                log_post(tweet_text, content_type, scores["total"], post_number)
                logger.info(
                    "[%s] Post #%d published (score=%d, type=%s, url=%s)",
                    slot_name, post_number, scores["total"], content_type, tweet_url,
                )
                await asyncio.sleep(random.uniform(20, 45))
            else:
                logger.error("[%s] Post failed after DB insert, post_id=%d", slot_name, post_id)

            if image_path and os.path.exists(image_path):
                os.remove(image_path)

            if await bot.check_rate_limit():
                logger.warning("[%s] Rate limit detected, pausing batch", slot_name)
                log_system_event(f"{slot_name} rate limit detected, batch paused", "WARN")
                break
    finally:
        conn.close()

    return published


async def run_observe_session(bot: TwitterBot) -> int:
    """Read-only observation cycle for the KOL list."""
    logger.info("=== OBSERVE SESSION START ===")
    observed = await observe_kol_reactions(bot, max_posts=30)
    log_system_event(f"Observe session captured {observed} new reactions")
    logger.info("=== OBSERVE SESSION DONE: %d new reactions ===", observed)
    return observed


async def run_posting_slot(bot: TwitterBot, slot_name: str) -> int:
    """Run one posting-only slot."""
    logger.info("=== %s START ===", slot_name.upper())
    log_system_event(f"{slot_name} started")

    if await check_circuit_breaker():
        log_system_event(f"{slot_name} skipped by circuit breaker", "ERROR")
        return 0

    profile = POSTING_SLOT_PROFILES[slot_name]
    base_weights = _normalize_weights(profile["weights"])
    weight_conn = get_connection()
    try:
        latest_weights = get_latest_weights(weight_conn)
    finally:
        weight_conn.close()
    weights = _blend_weights(base_weights, latest_weights or {})
    learning_context = get_latest_review_learning()
    await observe_kol_reactions(bot, max_posts=20)
    news_items = await scrape_all_news()
    logger.info("[%s] scraped %d AIHOT items", slot_name, len(news_items))

    published = await _generate_and_publish_posts(
        bot=bot,
        slot_name=slot_name,
        target_count=profile["target_count"],
        news_items=news_items,
        weights=weights,
        learning_context=learning_context,
    )
    logger.info("=== %s DONE: %d posts ===", slot_name.upper(), published)
    return published


async def nightly_review(bot: TwitterBot) -> None:
    """Metrics scrape + post-review learning. No posting, no interactions."""
    logger.info("=== NIGHTLY REVIEW START ===")
    log_system_event("Nightly review started")

    conn = get_connection()
    total_impressions = 0
    total_likes = 0
    total_retweets = 0

    for post in get_posts_needing_metrics(conn, limit=20):
        tweet_url = post.get("tweet_url", "")
        if not tweet_url or "status" not in tweet_url:
            continue

        metrics = await bot.get_post_metrics(tweet_url)
        if metrics:
            update_post_metrics(
                conn=conn,
                post_id=post["id"],
                likes=metrics.get("likes", 0),
                retweets=metrics.get("retweets", 0),
                replies=metrics.get("replies", 0),
                impressions=metrics.get("impressions", 0),
            )
            total_impressions += metrics.get("impressions", 0)
            total_likes += metrics.get("likes", 0)
            total_retweets += metrics.get("retweets", 0)
        await asyncio.sleep(random.uniform(2, 4))

    follower_count = await bot.get_follower_count()
    await backtest_posts(bot)
    analysis = await analyze_own_posts()
    if analysis.get("winning_patterns"):
        log_learning(analysis["winning_patterns"][:5])
    if analysis.get("human_calibration_notes"):
        log_learning(analysis["human_calibration_notes"][:5])

    stats = {
        "posts_count": get_today_post_count(conn),
        "comments_count": 0,
        "likes_given": 0,
        "follows_given": 0,
        "total_impressions": total_impressions,
        "total_likes_received": total_likes,
        "total_retweets_received": total_retweets,
        "follower_count": follower_count,
        "best_post_id": analysis.get("best_post_id"),
        "worst_post_id": analysis.get("worst_post_id"),
        "notes": analysis.get("review_summary", ""),
    }
    upsert_daily_stats(conn, stats)
    log_daily_summary(stats)
    conn.close()
    logger.info("=== NIGHTLY REVIEW DONE ===")


async def backtest_posts(bot: TwitterBot) -> None:
    """Refresh metrics for posts published 24h and 72h ago."""
    logger.info("=== BACKTEST START ===")
    conn = get_connection()
    now = datetime.now()

    for window_hours in REVIEW_WINDOWS_HOURS:
        target_date = (now - timedelta(hours=window_hours)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE published_at IS NOT NULL
                 AND tweet_url IS NOT NULL
                 AND tweet_url != ''
                 AND published_at LIKE ?
               ORDER BY published_at DESC""",
            (f"{target_date}%",),
        ).fetchall()

        for row in rows:
            post = dict(row)
            metrics = await bot.get_post_metrics(post["tweet_url"])
            if metrics:
                update_post_metrics(
                    conn=conn,
                    post_id=post["id"],
                    likes=metrics.get("likes", 0),
                    retweets=metrics.get("retweets", 0),
                    replies=metrics.get("replies", 0),
                    impressions=metrics.get("impressions", 0),
                )
            await asyncio.sleep(random.uniform(2, 4))

    conn.close()
    logger.info("=== BACKTEST DONE ===")


async def run_scheduler() -> None:
    """
    Compatibility scheduler.
    Production should prefer cron + slot_runner, but this keeps a self-contained mode.
    """
    logger.info("PepperBot scheduler starting...")
    init_database()
    log_system_event("PepperBot scheduler started")

    bot = TwitterBot()
    await bot.start()
    if not await bot.is_logged_in():
        logger.error("Not logged into Twitter")
        log_system_event("Not logged in — manual login required", "ERROR")
        await bot.stop()
        return

    executed: set[str] = set()

    try:
        while True:
            now = datetime.now()
            hour = now.hour
            today_key = now.strftime("%Y-%m-%d")
            if not any(today_key in key for key in executed):
                executed.clear()

            for session, executed_key in _scheduler_due_sessions(hour, today_key, executed):
                if session == "review":
                    await nightly_review(bot)
                elif session == "periodic2h":
                    await run_posting_slot(bot, "periodic2h")
                executed.add(executed_key)

            await asyncio.sleep(300)
    finally:
        await bot.stop()


async def run_single_session(session: str) -> None:
    """Run one explicit session."""
    init_database()
    bot = TwitterBot()
    await bot.start()
    if not await bot.is_logged_in():
        logger.error("Not logged in!")
        await bot.stop()
        return

    try:
        if session in POSTING_SLOT_PROFILES:
            await run_posting_slot(bot, session)
        elif session == "observe":
            await run_observe_session(bot)
        elif session == "review":
            await nightly_review(bot)
        elif session == "backtest":
            await backtest_posts(bot)
        elif session == "scheduler":
            await run_scheduler()
        else:
            logger.error("Unknown session: %s", session)
    finally:
        await bot.stop()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="PepperBot — posting-only automation")
    parser.add_argument(
        "--session",
        choices=[
            "periodic2h",
            "slot1",
            "slot2",
            "slot3",
            "slot4",
            "slot5",
            "observe",
            "review",
            "backtest",
            "scheduler",
        ],
        default="scheduler",
        help="Run a specific session or start the compatibility scheduler",
    )
    args = parser.parse_args()

    asyncio.run(run_single_session(args.session))


if __name__ == "__main__":
    main()
