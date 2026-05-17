"""
Learning module for the posting-only system.

Two loops:
  1. observe KOL reactions as read-only external signal
  2. review our own published posts and extract writing hypotheses

This module does not auto-like, auto-comment, auto-follow, or auto-adjust
strategy weights in the default runtime path.
"""

import json
import logging
from datetime import datetime, timezone

from llm import call_claude_json
from database import (
    get_connection,
    get_recent_posts,
    insert_learning_log,
    insert_reaction_observation,
    get_recent_reaction_observations,
    update_circuit_breaker,
    get_circuit_breaker,
)
from config import (
    CIRCUIT_BREAKER_THRESHOLD,
    KOL_LIST_URL,
)

logger = logging.getLogger(__name__)

REACTION_PACK_PROMPT = """你是一个 reaction-learning 蒸馏器。

目标不是复述 KOL 的内容，而是提取他们如何反应一条 AI 新闻：
- 从什么角度切
- 开头是怎么让人停下来的
- 哪种惊讶/质疑/判断方式最有效
- 哪些表达已经同质化，不能再学

严格要求：
1. 只提炼“反应结构”，不要复制原句
2. 如果样本和新闻不相关，要明确排除
3. 输出能直接给写作者使用的 reaction pack
4. 不要把账号写成 KOL 摘要号

输出 JSON：
{
  "status": "ok" | "no_recent_reactions" | "low_signal",
  "relevant_count": <int>,
  "what_everyone_noticed": ["<事实或变化点>"],
  "angle_patterns": ["<大家常见的切入角度>"],
  "hook_patterns": ["<适合第一行的钩子方式>"],
  "surprise_patterns": ["<惊讶/反常识/质疑手法>"],
  "avoid_patterns": ["<已经同质化或不该学的写法>"],
  "underused_angle": "<可写但大家没写透的角度>",
  "suggested_stance": "<适合花椒账号的明确立场>",
  "freshness_note": "<现在适合快评/跟进/复盘哪一种>",
  "writer_notes": ["<给 writer 的直接建议>"]
}
"""

POST_REVIEW_PROMPT = """你是 @pepperfr1ends 的发帖复盘分析师。

你只能根据本账号已经发布帖子的真实表现做复盘，不要编造 KOL 信号，
也不要自动修改任何策略权重。

输出 JSON：
{
  "status": "ok" | "insufficient_data",
  "best_post_id": <int|null>,
  "worst_post_id": <int|null>,
  "winning_patterns": ["<表现好的结构或切法>"],
  "losing_patterns": ["<表现差的结构或切法>"],
  "next_writing_hypotheses": ["<下一轮可验证假设>"],
  "human_calibration_notes": ["<去模板感建议>"],
  "review_summary": "<一句话总结>"
}
"""


async def observe_kol_reactions(bot, max_posts: int = 30) -> int:
    """
    Continuously collect KOL list reactions as raw read-only observations.
    Returns the number of newly inserted observations.
    """
    raw_posts = await bot.scrape_list_by_url(KOL_LIST_URL, max_posts=max_posts)
    if not raw_posts:
        logger.info("No KOL reactions scraped from list")
        return 0

    conn = get_connection()
    inserted = 0
    try:
        for post in raw_posts:
            post_url = post.get("post_url", "")
            post_text = post.get("content", "").strip()
            if not post_url or not post_text:
                continue

            row_id = insert_reaction_observation(
                conn=conn,
                kol_handle=post.get("handle", ""),
                post_url=post_url,
                post_text=post_text,
                posted_at=post.get("posted_at", ""),
                likes=post.get("likes", 0),
                retweets=post.get("retweets", 0),
                replies=post.get("replies", 0),
            )
            if row_id:
                inserted += 1
    finally:
        conn.close()

    logger.info("Observed %d new KOL reactions", inserted)
    return inserted


def _format_reaction_samples(samples: list[dict], limit: int = 12) -> str:
    lines = []
    for sample in samples[:limit]:
        lines.append(
            f"- {sample.get('kol_handle', '')} | "
            f"{sample.get('likes', 0)} likes / {sample.get('retweets', 0)} RT / "
            f"{sample.get('replies', 0)} replies | "
            f"{sample.get('post_text', '')[:240]}"
        )
    return "\n".join(lines)


async def build_reaction_pack(
    source_material: str,
    source_url: str = "",
    source_title: str = "",
    since_hours: int = 8,
) -> dict:
    """
    Distill recent raw reactions into a writer-friendly reaction pack.
    The model decides which samples are relevant to the current source.
    """
    conn = get_connection()
    samples = get_recent_reaction_observations(conn, since_hours=since_hours, limit=60)
    conn.close()

    if not samples:
        return {
            "status": "no_recent_reactions",
            "relevant_count": 0,
            "what_everyone_noticed": [],
            "angle_patterns": [],
            "hook_patterns": [],
            "surprise_patterns": [],
            "avoid_patterns": [],
            "underused_angle": "",
            "suggested_stance": "",
            "freshness_note": "",
            "writer_notes": [],
        }

    user_prompt = f"""请围绕这条 AI 新闻蒸馏最近 KOL 反应。

## 新闻素材
标题: {source_title}
来源: {source_url}
{source_material[:1600]}

## 最近 KOL 反应样本
{_format_reaction_samples(samples)}

注意：
- 只保留和这条新闻相关的反应
- 学“怎么反应”，不是学“具体怎么写”
- 要指出哪些写法已经太像 KOL 了，不能再学
"""

    try:
        result = await call_claude_json(
            system_prompt=REACTION_PACK_PROMPT,
            user_prompt=user_prompt,
            max_tokens=900,
            temperature=0.3,
        )
        result.setdefault("status", "ok")
        result.setdefault("relevant_count", 0)
        result.setdefault("what_everyone_noticed", [])
        result.setdefault("angle_patterns", [])
        result.setdefault("hook_patterns", [])
        result.setdefault("surprise_patterns", [])
        result.setdefault("avoid_patterns", [])
        result.setdefault("underused_angle", "")
        result.setdefault("suggested_stance", "")
        result.setdefault("freshness_note", "")
        result.setdefault("writer_notes", [])
        return result
    except Exception as exc:
        logger.warning("Reaction pack distillation failed: %s", exc)
        return {
            "status": "low_signal",
            "relevant_count": 0,
            "what_everyone_noticed": [],
            "angle_patterns": [],
            "hook_patterns": [],
            "surprise_patterns": [],
            "avoid_patterns": ["reaction_pack_error"],
            "underused_angle": "",
            "suggested_stance": "",
            "freshness_note": "",
            "writer_notes": [],
        }


async def analyze_own_posts() -> dict:
    """
    Review published post performance and extract the next writing hypotheses.
    This does not mutate strategy weights in the default runtime path.
    """
    conn = get_connection()
    posts = get_recent_posts(conn, limit=30)
    published = [p for p in posts if p.get("published_at")]

    if len(published) < 3:
        conn.close()
        return {
            "status": "insufficient_data",
            "best_post_id": None,
            "worst_post_id": None,
            "winning_patterns": [],
            "losing_patterns": [],
            "next_writing_hypotheses": [],
            "human_calibration_notes": [],
            "review_summary": "insufficient_data",
        }

    posts_summary = []
    for post in published[:20]:
        posts_summary.append({
            "id": post["id"],
            "type": post["content_type"],
            "content": post["content"][:160],
            "likes": post.get("likes", 0),
            "retweets": post.get("retweets", 0),
            "replies": post.get("replies", 0),
            "impressions": post.get("impressions", 0),
            "score_total": post.get("score_total", 0),
        })

    user_prompt = f"""请复盘以下本账号帖子表现，只输出下一轮可执行的写作建议。

帖子数据：
{json.dumps(posts_summary, ensure_ascii=False, indent=2)}
"""

    try:
        analysis = await call_claude_json(
            system_prompt=POST_REVIEW_PROMPT,
            user_prompt=user_prompt,
            max_tokens=1000,
            temperature=0.3,
        )
    except Exception as exc:
        logger.error("Own post review failed: %s", exc)
        conn.close()
        return {
            "status": "insufficient_data",
            "best_post_id": None,
            "worst_post_id": None,
            "winning_patterns": [],
            "losing_patterns": [],
            "next_writing_hypotheses": [],
            "human_calibration_notes": [],
            "review_summary": f"review_error: {exc}",
        }

    analysis.setdefault("status", "ok")
    analysis.setdefault("best_post_id", None)
    analysis.setdefault("worst_post_id", None)
    analysis.setdefault("winning_patterns", [])
    analysis.setdefault("losing_patterns", [])
    analysis.setdefault("next_writing_hypotheses", [])
    analysis.setdefault("human_calibration_notes", [])
    analysis.setdefault("review_summary", "")

    insert_learning_log(
        conn=conn,
        learning_type="post_review_summary",
        techniques_extracted=json.dumps(analysis.get("winning_patterns", []), ensure_ascii=False),
        strategy_adjustment=json.dumps(
            {
                "losing_patterns": analysis.get("losing_patterns", []),
                "next_writing_hypotheses": analysis.get("next_writing_hypotheses", []),
                "human_calibration_notes": analysis.get("human_calibration_notes", []),
                "review_summary": analysis.get("review_summary", ""),
            },
            ensure_ascii=False,
        ),
    )
    conn.close()
    return analysis


async def check_circuit_breaker() -> bool:
    """
    Check if system should pause.
    Returns True if paused (should not post).
    Triggers:
    - consecutive posts with 0 interactions
    """
    conn = get_connection()
    cb = get_circuit_breaker(conn)

    if cb.get("is_paused"):
        logger.warning("Circuit breaker is PAUSED. Skipping this cycle.")
        conn.close()
        return True

    posts = get_recent_posts(conn, limit=CIRCUIT_BREAKER_THRESHOLD)
    consecutive_zeros = 0

    for post in posts:
        if post.get("published_at"):
            total_interaction = (
                post.get("likes", 0)
                + post.get("retweets", 0)
                + post.get("replies", 0)
            )
            if total_interaction == 0:
                consecutive_zeros += 1
            else:
                break

    if consecutive_zeros >= CIRCUIT_BREAKER_THRESHOLD:
        logger.error(
            "CIRCUIT BREAKER TRIGGERED: %d consecutive 0-interaction posts",
            consecutive_zeros,
        )
        update_circuit_breaker(conn, consecutive_zeros, is_paused=True)
        conn.close()
        return True

    update_circuit_breaker(conn, consecutive_zeros, is_paused=False)
    conn.close()
    return False


async def reset_circuit_breaker() -> None:
    """Manually reset the circuit breaker."""
    conn = get_connection()
    update_circuit_breaker(conn, 0, is_paused=False)
    conn.close()
    logger.info("Circuit breaker reset")


def get_learned_techniques() -> list[dict]:
    """
    Legacy compatibility shim.
    The posting-only runtime no longer feeds KOL viral techniques into writer.
    """
    return []
