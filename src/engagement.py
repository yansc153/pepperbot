"""
KOL engagement logic.
Manages tier rotation, comment generation, like/follow quotas.
Deterministic scheduling; LLM only for comment writing.
"""

import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from config import (
    KOL_LIST_PATH,
    KOL_LIST_URL,
    MAX_KOL_COMMENTS_PER_DAY,
    MIN_KOL_COMMENTS_PER_DAY,
    MAX_LIKES_PER_DAY,
    MAX_FOLLOWS_PER_DAY,
    KOL_VIRAL_THRESHOLD_LIKES,
)
from database import (
    get_connection,
    insert_kol_comment,
    get_today_comment_count,
    log_engagement,
    get_today_engagement_count,
)
from scraper import KOLPost, dict_to_kol_post
from writer import write_kol_comment
from twitter_bot import TwitterBot

logger = logging.getLogger(__name__)


def parse_kol_list(kol_path: Path = KOL_LIST_PATH) -> list[dict]:
    """
    Parse kol_list.md into structured list.
    Returns [{"handle": "@xxx", "name": "...", "tier": "tier1", "niche": "..."}]
    """
    if not kol_path.exists():
        logger.error("KOL list not found: %s", kol_path)
        return []

    content = kol_path.read_text(encoding="utf-8")
    kols = []
    current_tier = "tier3"

    for line in content.split("\n"):
        line = line.strip()
        if "第一梯队" in line:
            current_tier = "tier1"
        elif "第二梯队" in line:
            current_tier = "tier2"
        elif "第三梯队" in line:
            current_tier = "tier3"
        elif re.match(r"^\d+\.", line):
            # Parse "1. 宝玉 @dotey — 大模型解读"
            match = re.search(r"@(\w+)", line)
            if match:
                handle = f"@{match.group(1)}"
                # Extract name and niche
                parts = line.split("@")
                name = parts[0].strip().lstrip("0123456789. ")
                niche = ""
                if "—" in line:
                    niche = line.split("—")[-1].strip()
                elif "—" in line:
                    niche = line.split("—")[-1].strip()

                kols.append({
                    "handle": handle,
                    "name": name,
                    "tier": current_tier,
                    "niche": niche,
                })

    logger.info("Parsed %d KOLs from list", len(kols))
    return kols


def select_kols_for_session(
    all_kols: list[dict],
    session: str = "morning",
) -> list[dict]:
    """
    Select KOLs to engage with for this session.
    Morning: tier1 priority (5 comments)
    Noon: tier2 rotation (5 comments)
    Evening: organic (whoever has hot posts)
    """
    tier1 = [k for k in all_kols if k["tier"] == "tier1"]
    tier2 = [k for k in all_kols if k["tier"] == "tier2"]
    tier3 = [k for k in all_kols if k["tier"] == "tier3"]

    if session == "morning":
        selected = random.sample(tier1, min(5, len(tier1)))
    elif session == "noon":
        selected = random.sample(tier2, min(5, len(tier2)))
    else:
        # Evening: mix
        pool = tier1 + tier2
        selected = random.sample(pool, min(5, len(pool)))

    return selected


async def run_comment_session(
    bot: TwitterBot,
    session: str = "morning",
) -> int:
    """
    Run a KOL comment session.
    1. Parse KOL list
    2. Select KOLs for this session
    3. Scrape their latest posts
    4. Generate and post comments
    Returns number of comments posted.
    """
    conn = get_connection()

    # Check daily quota
    today_comments = get_today_comment_count(conn)
    if today_comments >= MAX_KOL_COMMENTS_PER_DAY:
        logger.info("Comment quota reached: %d/%d", today_comments, MAX_KOL_COMMENTS_PER_DAY)
        conn.close()
        return 0

    remaining_quota = MAX_KOL_COMMENTS_PER_DAY - today_comments
    target_comments = min(5, remaining_quota)

    # Parse KOL list for tier enrichment
    all_kols = parse_kol_list()
    kol_tier_map = {k["handle"].lower(): k["tier"] for k in all_kols}

    # Primary: scrape from Twitter List URL (much faster than per-profile)
    raw_posts = await bot.scrape_list_by_url(KOL_LIST_URL, max_posts=30)

    # Fallback: if list URL fails, scrape individual profiles
    if not raw_posts:
        selected_kols = select_kols_for_session(all_kols, session)
        raw_posts = await bot.scrape_kol_posts(
            [{"handle": k["handle"], "tier": k["tier"]} for k in selected_kols],
            max_per_kol=3,
        )

    # Enrich tier info from kol_list.md
    for post in raw_posts:
        handle_lower = post.get("handle", "").lower()
        if handle_lower in kol_tier_map:
            post["tier"] = kol_tier_map[handle_lower]

    kol_posts = [dict_to_kol_post(p) for p in raw_posts]

    if not kol_posts:
        logger.warning("No KOL posts found for this session")
        conn.close()
        return 0

    # Sort by engagement (high = more visibility for our comment)
    kol_posts.sort(key=lambda p: p.likes, reverse=True)

    comments_posted = 0

    for post in kol_posts:
        if comments_posted >= target_comments:
            break

        # Generate comment
        comment = await write_kol_comment(
            kol_handle=post.handle,
            kol_post_content=post.content,
            kol_tier=post.tier,
        )

        if not comment:
            continue

        # Post via Playwright
        success = await bot.post_comment(post.post_url, comment)
        if success:
            insert_kol_comment(
                conn=conn,
                kol_handle=post.handle,
                kol_tier=post.tier,
                original_post_url=post.post_url,
                original_post_snippet=post.content[:200],
                comment_text=comment,
            )
            comments_posted += 1
            logger.info(
                "Comment #%d posted on %s's post",
                comments_posted, post.handle,
            )

    conn.close()
    return comments_posted


async def run_like_session(
    bot: TwitterBot,
    kol_posts: list[KOLPost],
    target_likes: int = 10,
) -> int:
    """Like KOL posts. Returns number of likes given."""
    conn = get_connection()
    today_likes = get_today_engagement_count(conn, "like")
    if today_likes >= MAX_LIKES_PER_DAY:
        logger.info("Like quota reached")
        conn.close()
        return 0

    remaining = min(target_likes, MAX_LIKES_PER_DAY - today_likes)
    liked = 0

    for post in kol_posts[:remaining]:
        success = await bot.like_tweet(post.post_url)
        if success:
            log_engagement(conn, "like", post.handle, post.post_url)
            liked += 1

    conn.close()
    return liked


async def run_follow_session(
    bot: TwitterBot,
    handles: list[str],
) -> int:
    """Follow new accounts. Returns number of follows."""
    conn = get_connection()
    today_follows = get_today_engagement_count(conn, "follow")
    if today_follows >= MAX_FOLLOWS_PER_DAY:
        logger.info("Follow quota reached")
        conn.close()
        return 0

    remaining = min(len(handles), MAX_FOLLOWS_PER_DAY - today_follows)
    followed = 0

    for handle in handles[:remaining]:
        success = await bot.follow_user(handle)
        if success:
            log_engagement(conn, "follow", handle)
            followed += 1

    conn.close()
    return followed


def get_viral_kol_posts(kol_posts: list[KOLPost]) -> list[KOLPost]:
    """Filter KOL posts that qualify as viral (for learning)."""
    return [
        p for p in kol_posts
        if p.likes >= KOL_VIRAL_THRESHOLD_LIKES or p.retweets >= 50
    ]
