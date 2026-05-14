"""
Main orchestrator — deterministic state machine.
Zero LLM tokens in routing/scheduling. LLM only called inside worker modules.

Schedule:
  07:00 → morning_batch (5-6 posts + 5 KOL comments + likes + follows)
  13:00 → noon_batch (2-3 posts + 5 KOL comments)
  19:00 → evening_batch (2-3 posts, controversy-heavy)
  23:00 → nightly_review (metrics scrape + self-learning + daily log)
"""

import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    DEFAULT_WEIGHTS,
    MAX_POSTS_PER_DAY,
    MIN_POSTS_PER_DAY,
    SCHEDULE_TIMEZONE,
    MORNING_HOUR,
    NOON_HOUR,
    EVENING_HOUR,
    REVIEW_HOUR,
    REVIEW_WINDOWS_HOURS,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
)
from database import (
    init_database,
    get_connection,
    insert_post,
    mark_post_published,
    is_duplicate,
    get_today_post_count,
    get_recent_posts,
    get_posts_needing_metrics,
    update_post_metrics,
    get_latest_weights,
    upsert_daily_stats,
    get_today_comment_count,
    get_today_engagement_count,
)
from guardrails import run_all_guardrails, has_kill_violation
from scraper import scrape_all_news, ScrapedItem, dict_to_kol_post, fetch_image_for_item
from scorer import score_content, decide_publish
from writer import write_tweet
from twitter_bot import TwitterBot
from engagement import (
    parse_kol_list,
    select_kols_for_session,
    run_comment_session,
    run_like_session,
    run_follow_session,
    get_viral_kol_posts,
)
from learner import (
    analyze_own_posts,
    learn_from_kol_viral,
    check_circuit_breaker,
    get_learned_techniques,
)
from obsidian_logger import (
    log_post,
    log_kol_comment,
    log_engagement_stats,
    log_daily_summary,
    log_strategy_change,
    log_learning,
    log_system_event,
)

# Configure logging
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


def _pick_content_type(weights: dict[str, float]) -> str:
    """Weighted random selection of content type."""
    types = list(weights.keys())
    probs = list(weights.values())
    return random.choices(types, weights=probs, k=1)[0]


async def _generate_and_publish_posts(
    bot: TwitterBot,
    target_count: int,
    news_items: list[ScrapedItem],
    techniques: list[dict],
    weights: dict[str, float],
    session_name: str,
) -> int:
    """
    Generate and publish a batch of posts.
    Deterministic loop: generate → score → guardrail → publish or discard.
    Returns number of posts published.
    """
    conn = get_connection()
    published = 0
    today_total = get_today_post_count(conn)

    for i in range(target_count):
        if today_total + published >= MAX_POSTS_PER_DAY:
            logger.warning("Daily post cap reached: %d", MAX_POSTS_PER_DAY)
            break

        # 1. Pick content type
        content_type = _pick_content_type(weights)

        # 2. Pick source material (if news-based)
        source_material = ""
        matched_item = None
        if news_items and content_type in ("ai_hot_take", "ai_tool_review"):
            # Try to find a matching item by content_type first
            matched_item = None
            for idx, item in enumerate(news_items):
                if item.content_type == content_type:
                    matched_item = news_items.pop(idx)
                    break
            if not matched_item and news_items:
                matched_item = news_items.pop(0)

            if matched_item:
                parts = [f"标题: {matched_item.title}"]
                if matched_item.summary:
                    parts.append(f"摘要: {matched_item.summary}")
                elif matched_item.snippet:
                    parts.append(f"简介: {matched_item.snippet}")
                if matched_item.url:
                    parts.append(f"来源URL: {matched_item.url}")
                if matched_item.source:
                    parts.append(f"来源: {matched_item.source}")
                source_material = "\n".join(parts)

        # 3. Generate tweet (LLM call inside writer)
        result = await write_tweet(
            content_type=content_type,
            source_material=source_material,
            techniques=techniques,
        )

        if not result:
            logger.warning("Tweet generation failed for type %s", content_type)
            continue

        tweet_text = result["tweet"]

        # 4. Dedup check (deterministic)
        if is_duplicate(conn, tweet_text):
            logger.info("Duplicate detected, skipping")
            continue

        # 5. Score (LLM call inside scorer)
        scores = await score_content(tweet_text, content_type, source_material)
        decision = decide_publish(scores["total"])

        if decision == "drop":
            logger.info("Score too low (%d), dropping", scores["total"])
            continue

        if decision == "needs_review":
            # In fully autonomous mode, try one more rewrite
            logger.info("Score %d needs_review, attempting rewrite", scores["total"])
            result = await write_tweet(
                content_type=content_type,
                source_material=source_material,
                extra_context=f"上一版评分{scores['total']}/85，需要提高。弱项：{scores.get('reasoning', '')}",
                techniques=techniques,
            )
            if not result:
                continue
            tweet_text = result["tweet"]
            scores = await score_content(tweet_text, content_type, source_material)
            if decide_publish(scores["total"]) == "drop":
                continue

        # 6. Final guardrail pass (deterministic)
        if has_kill_violation(tweet_text):
            logger.error("Kill violation in final check, discarding")
            continue

        # 7. Try to get image from source article
        image_path = None
        if matched_item:
            image_path = await fetch_image_for_item(matched_item)
            if image_path:
                logger.info("Image acquired for post: %s", image_path)

        # 8. Insert to database
        post_id = insert_post(
            conn=conn,
            content=tweet_text,
            content_type=content_type,
            image_prompt=result.get("image_prompt", ""),
            scores=scores,
            source_url=source_material[:200] if source_material else "",
        )

        # 9. Publish via Chrome with image (returns tweet URL or None)
        tweet_url = await bot.post_tweet(tweet_text, image_path=image_path)
        if tweet_url:
            mark_post_published(conn, post_id, tweet_url=tweet_url)
            published += 1
            post_number = today_total + published
            log_post(tweet_text, content_type, scores["total"], post_number)
            logger.info(
                "[%s] Post #%d published (score=%d, type=%s, url=%s)",
                session_name, post_number, scores["total"], content_type, tweet_url,
            )

            # Rate limit protection: wait between posts
            await asyncio.sleep(random.uniform(60, 180))

        # Clean up downloaded image
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        # Check rate limit
        if await bot.check_rate_limit():
            logger.warning("Rate limit detected, pausing batch")
            log_system_event("Rate limit detected, batch paused", "WARN")
            break

    conn.close()
    return published


# ── Session handlers ──

async def morning_batch(bot: TwitterBot) -> None:
    """07:00 morning session."""
    logger.info("=== MORNING BATCH START ===")
    log_system_event("Morning batch started")

    # Check circuit breaker
    if await check_circuit_breaker():
        log_system_event("Circuit breaker active, skipping morning batch", "ERROR")
        return

    # Load current strategy weights
    conn = get_connection()
    weights = get_latest_weights(conn) or DEFAULT_WEIGHTS.as_dict()
    conn.close()

    # Get learned techniques
    techniques = get_learned_techniques()

    # Scrape news
    news_items = await scrape_all_news()
    logger.info("Scraped %d news items", len(news_items))

    # Scrape KOL posts via List timeline (much faster than visiting each profile)
    all_kols = parse_kol_list()
    raw_kol_posts = await bot.scrape_list_timeline(max_posts=30)

    # Enrich tier info from our KOL list
    kol_tier_map = {k["handle"]: k["tier"] for k in all_kols}
    for post in raw_kol_posts:
        handle = post.get("handle", "")
        post["tier"] = kol_tier_map.get(handle, "tier3")

    kol_posts = [dict_to_kol_post(p) for p in raw_kol_posts]

    # Learn from viral KOL posts (Loop 3B)
    viral_kol_posts = get_viral_kol_posts(kol_posts)
    if viral_kol_posts:
        new_techniques = await learn_from_kol_viral(viral_kol_posts)
        if new_techniques:
            techniques.extend(new_techniques)
            log_learning([t["technique_name"] for t in new_techniques])

    # Generate and publish 5-6 posts
    posts_published = await _generate_and_publish_posts(
        bot=bot,
        target_count=6,
        news_items=news_items,
        techniques=techniques,
        weights=weights,
        session_name="morning",
    )

    # KOL comments (5)
    comments_posted = await run_comment_session(bot, session="morning")
    logger.info("Morning comments: %d", comments_posted)

    # Likes (10-15)
    likes = await run_like_session(bot, kol_posts, target_likes=15)

    # Follows (3-5)
    tier3_handles = [k["handle"] for k in all_kols if k["tier"] == "tier3"]
    random.shuffle(tier3_handles)
    follows = await run_follow_session(bot, tier3_handles[:5])

    log_engagement_stats(likes, follows)
    logger.info(
        "=== MORNING BATCH DONE: %d posts, %d comments, %d likes, %d follows ===",
        posts_published, comments_posted, likes, follows,
    )


async def noon_batch(bot: TwitterBot) -> None:
    """13:00 noon session."""
    logger.info("=== NOON BATCH START ===")
    log_system_event("Noon batch started")

    if await check_circuit_breaker():
        return

    conn = get_connection()
    weights = get_latest_weights(conn) or DEFAULT_WEIGHTS.as_dict()
    conn.close()

    techniques = get_learned_techniques()
    news_items = await scrape_all_news()

    posts_published = await _generate_and_publish_posts(
        bot=bot,
        target_count=3,
        news_items=news_items,
        techniques=techniques,
        weights=weights,
        session_name="noon",
    )

    comments_posted = await run_comment_session(bot, session="noon")

    logger.info(
        "=== NOON BATCH DONE: %d posts, %d comments ===",
        posts_published, comments_posted,
    )


async def evening_batch(bot: TwitterBot) -> None:
    """19:00 evening session — controversy heavy."""
    logger.info("=== EVENING BATCH START ===")
    log_system_event("Evening batch started")

    if await check_circuit_breaker():
        return

    conn = get_connection()
    weights = get_latest_weights(conn) or DEFAULT_WEIGHTS.as_dict()
    conn.close()

    # Boost controversy weight for evening
    evening_weights = weights.copy()
    evening_weights["controversy"] = max(0.30, evening_weights.get("controversy", 0.15))
    # Re-normalize
    total = sum(evening_weights.values())
    evening_weights = {k: v / total for k, v in evening_weights.items()}

    techniques = get_learned_techniques()

    posts_published = await _generate_and_publish_posts(
        bot=bot,
        target_count=3,
        news_items=[],
        techniques=techniques,
        weights=evening_weights,
        session_name="evening",
    )

    logger.info("=== EVENING BATCH DONE: %d posts ===", posts_published)


async def nightly_review(bot: TwitterBot) -> None:
    """23:00 nightly review — metrics scraping + self-learning."""
    logger.info("=== NIGHTLY REVIEW START ===")
    log_system_event("Nightly review started")

    conn = get_connection()

    # 1. Scrape metrics for today's published posts (using stored tweet URLs)
    posts_with_urls = get_posts_needing_metrics(conn, limit=20)
    total_impressions = 0
    total_likes = 0
    total_retweets = 0

    for post in posts_with_urls:
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
            logger.info(
                "Metrics updated for post #%d: %d likes, %d RT, %d impressions",
                post["id"], metrics.get("likes", 0),
                metrics.get("retweets", 0), metrics.get("impressions", 0),
            )

        # Rate limit protection between scrapes
        await asyncio.sleep(random.uniform(2, 5))

    # 2. Get follower count
    follower_count = await bot.get_follower_count()

    # 3. Run 24h/72h backtest on historical posts
    await backtest_posts(bot)

    # 4. Self-learning analysis (Loop 3A)
    analysis = await analyze_own_posts()
    if analysis:
        log_strategy_change(analysis.get("weight_reasoning", ""))
        if analysis.get("topic_suggestions"):
            log_learning(analysis["topic_suggestions"])

    # 5. Daily stats
    stats = {
        "posts_count": get_today_post_count(conn),
        "comments_count": get_today_comment_count(conn),
        "likes_given": get_today_engagement_count(conn, "like"),
        "follows_given": get_today_engagement_count(conn, "follow"),
        "total_impressions": total_impressions,
        "total_likes_received": total_likes,
        "total_retweets_received": total_retweets,
        "follower_count": follower_count,
        "best_post_id": analysis.get("best_post_id") if analysis else None,
        "worst_post_id": analysis.get("worst_post_id") if analysis else None,
    }
    upsert_daily_stats(conn, stats)
    log_daily_summary(stats)

    conn.close()
    logger.info("=== NIGHTLY REVIEW DONE ===")


async def backtest_posts(bot: TwitterBot) -> None:
    """
    Run 24h/72h performance backtest on historical posts.
    Called during nightly_review or as standalone.
    Checks posts published 24h and 72h ago, scrapes their current metrics,
    and logs performance attribution.
    """
    logger.info("=== BACKTEST START ===")
    conn = get_connection()

    now = datetime.now()

    for window_hours in REVIEW_WINDOWS_HOURS:
        target_time = now - timedelta(hours=window_hours)
        target_date = target_time.strftime("%Y-%m-%d")

        # Find posts published around that time
        posts = conn.execute(
            """SELECT * FROM posts
               WHERE published_at IS NOT NULL
                 AND tweet_url IS NOT NULL AND tweet_url != ''
                 AND published_at LIKE ?
               ORDER BY published_at DESC""",
            (f"{target_date}%",),
        ).fetchall()

        if not posts:
            logger.info("No posts found for %dh backtest (%s)", window_hours, target_date)
            continue

        logger.info("Backtesting %d posts from %dh ago (%s)", len(posts), window_hours, target_date)

        for post in posts:
            post_dict = dict(post)
            tweet_url = post_dict.get("tweet_url", "")
            if not tweet_url or "status" not in tweet_url:
                continue

            metrics = await bot.get_post_metrics(tweet_url)
            if metrics:
                update_post_metrics(
                    conn=conn,
                    post_id=post_dict["id"],
                    likes=metrics.get("likes", 0),
                    retweets=metrics.get("retweets", 0),
                    replies=metrics.get("replies", 0),
                    impressions=metrics.get("impressions", 0),
                )
                total_engagement = metrics.get("likes", 0) + metrics.get("retweets", 0) + metrics.get("replies", 0)
                logger.info(
                    "[%dh backtest] Post #%d: %d likes, %d RT, %d replies, %d views (type=%s)",
                    window_hours, post_dict["id"],
                    metrics.get("likes", 0), metrics.get("retweets", 0),
                    metrics.get("replies", 0), metrics.get("impressions", 0),
                    post_dict.get("content_type", ""),
                )

            await asyncio.sleep(random.uniform(2, 4))

    conn.close()
    logger.info("=== BACKTEST DONE ===")


# ── Scheduler ──

async def run_scheduler() -> None:
    """
    Main loop. Runs continuously, executing batches at scheduled times.
    Uses simple polling — checks every 5 minutes.
    """
    logger.info("PepperBot scheduler starting...")
    init_database()
    log_system_event("PepperBot started")

    bot = TwitterBot()
    await bot.start()

    # Check login
    if not await bot.is_logged_in():
        logger.error("Not logged into Twitter! Please log in manually first.")
        log_system_event("Not logged in — manual login required", "ERROR")
        await bot.stop()
        return

    logger.info("Logged into Twitter, scheduler running")

    # One-time setup: create KOL list and batch follow
    all_kols = parse_kol_list()
    if all_kols:
        await bot.create_kol_list()
        kol_handles_to_add = [k["handle"] for k in all_kols]
        for handle in kol_handles_to_add:
            await bot.add_to_list(handle)
            await asyncio.sleep(random.uniform(1, 3))
        logger.info("KOL list setup complete: %d KOLs added", len(kol_handles_to_add))
        log_system_event(f"KOL list setup: {len(kol_handles_to_add)} accounts added")

    executed_today: set[str] = set()

    try:
        while True:
            now = datetime.now()
            hour = now.hour
            today_key = now.strftime("%Y-%m-%d")

            # Reset executed set at midnight
            if not any(today_key in k for k in executed_today):
                executed_today.clear()

            # Morning batch
            if hour >= MORNING_HOUR and f"{today_key}_morning" not in executed_today:
                await morning_batch(bot)
                executed_today.add(f"{today_key}_morning")

            # Noon batch
            elif hour >= NOON_HOUR and f"{today_key}_noon" not in executed_today:
                await noon_batch(bot)
                executed_today.add(f"{today_key}_noon")

            # Evening batch
            elif hour >= EVENING_HOUR and f"{today_key}_evening" not in executed_today:
                await evening_batch(bot)
                executed_today.add(f"{today_key}_evening")

            # Nightly review
            elif hour >= REVIEW_HOUR and f"{today_key}_review" not in executed_today:
                await nightly_review(bot)
                executed_today.add(f"{today_key}_review")

            # Sleep 5 minutes between checks
            await asyncio.sleep(300)

    except KeyboardInterrupt:
        logger.info("Scheduler interrupted by user")
    except Exception as exc:
        logger.error("Scheduler error: %s", exc)
        log_system_event(f"Scheduler error: {exc}", "ERROR")
    finally:
        await bot.stop()
        log_system_event("PepperBot stopped")


# ── CLI entry points ──

async def run_single_session(session: str) -> None:
    """Run a single session for testing."""
    init_database()
    bot = TwitterBot()
    await bot.start()

    if not await bot.is_logged_in():
        logger.error("Not logged in!")
        await bot.stop()
        return

    try:
        if session == "morning":
            await morning_batch(bot)
        elif session == "noon":
            await noon_batch(bot)
        elif session == "evening":
            await evening_batch(bot)
        elif session == "review":
            await nightly_review(bot)
        elif session == "backtest":
            await backtest_posts(bot)
        elif session == "setup_list":
            # One-time: create list and add all KOLs
            all_kols = parse_kol_list()
            await bot.create_kol_list()
            for k in all_kols:
                await bot.add_to_list(k["handle"])
                await asyncio.sleep(random.uniform(1, 3))
            logger.info("KOL list setup complete")
        elif session == "batch_follow":
            # One-time: follow all KOLs
            all_kols = parse_kol_list()
            handles = [k["handle"] for k in all_kols]
            await bot.batch_follow_kols(handles)
        else:
            logger.error("Unknown session: %s", session)
    finally:
        await bot.stop()


def main() -> None:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="PepperBot — @pepperfr1ends automation")
    parser.add_argument(
        "--session",
        choices=["morning", "noon", "evening", "review", "backtest", "setup_list", "batch_follow", "scheduler"],
        default="scheduler",
        help="Run a specific session or start the scheduler",
    )
    args = parser.parse_args()

    if args.session == "scheduler":
        asyncio.run(run_scheduler())
    else:
        asyncio.run(run_single_session(args.session))


if __name__ == "__main__":
    main()
