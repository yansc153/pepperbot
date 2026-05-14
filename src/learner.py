"""
Self-learning module.
Two sub-loops:
  3A: Own post analysis → attribute performance to techniques → adjust weights
  3B: KOL viral post extraction → learn narrative techniques → feed to writer

No learning boundaries. AI makes ALL strategy decisions.
"""

import json
import logging
from datetime import datetime, timezone

from llm import call_claude_json
from database import (
    get_connection,
    get_recent_posts,
    update_post_metrics,
    save_strategy_weights,
    get_latest_weights,
    insert_technique,
    get_all_techniques,
    update_circuit_breaker,
    get_circuit_breaker,
)
from config import (
    DEFAULT_WEIGHTS,
    VIRAL_THRESHOLD_LIKES,
    VIRAL_THRESHOLD_RETWEETS,
    CIRCUIT_BREAKER_THRESHOLD,
    MEMORY_PATH,
)
from scraper import KOLPost

logger = logging.getLogger(__name__)


# ── 3A: Own Post Analysis ──

ANALYSIS_SYSTEM_PROMPT = """你是 @pepperfr1ends 的数据分析师，负责分析帖子表现并归因。

输入：一组帖子及其互动数据。
任务：
1. 识别表现最好和最差的帖子
2. 归因分析：哪些写作技法/话题/钩子带来了高互动
3. 提出策略调整建议（内容比例、话题方向、语气调整）

当前内容比例权重：
- ai_hot_take: AI热点快评
- ai_tool_review: AI工具实测
- startup_cognition: 创业认知
- controversy: 争议观点
- kol_interaction: KOL互动

你可以自由调整任何权重。没有调整幅度限制。
如果某类内容完全不行，可以把权重压到0.05。
如果某类内容爆了，可以把权重拉到0.50。
大胆决策，用数据说话。

输出JSON：
{
  "best_post_id": <int>,
  "worst_post_id": <int>,
  "best_post_analysis": "<为什么好>",
  "worst_post_analysis": "<为什么差>",
  "techniques_identified": ["<技法1>", "<技法2>"],
  "new_weights": {
    "ai_hot_take": <float>,
    "ai_tool_review": <float>,
    "startup_cognition": <float>,
    "controversy": <float>,
    "kol_interaction": <float>
  },
  "weight_reasoning": "<为什么这样调>",
  "topic_suggestions": ["<明天应该多写什么>"],
  "tone_adjustment": "<语气方向建议>"
}
"""


async def analyze_own_posts() -> dict | None:
    """
    Loop 3A: Analyze recent posts, attribute performance, adjust strategy.
    Returns analysis dict or None on failure.
    """
    conn = get_connection()
    posts = get_recent_posts(conn, limit=30)
    current_weights = get_latest_weights(conn)
    if not current_weights:
        current_weights = DEFAULT_WEIGHTS.as_dict()

    if not posts:
        logger.info("No posts to analyze")
        conn.close()
        return None

    # Filter to posts that have been published and have metrics
    published = [p for p in posts if p.get("published_at")]
    if len(published) < 3:
        logger.info("Too few published posts for analysis: %d", len(published))
        conn.close()
        return None

    # Build analysis input
    posts_summary = []
    for p in published[:20]:
        posts_summary.append({
            "id": p["id"],
            "type": p["content_type"],
            "content": p["content"][:150],
            "likes": p.get("likes", 0),
            "retweets": p.get("retweets", 0),
            "replies": p.get("replies", 0),
            "impressions": p.get("impressions", 0),
            "score_total": p.get("score_total", 0),
        })

    user_prompt = f"""请分析以下帖子数据并提出策略调整：

当前权重：{json.dumps(current_weights, ensure_ascii=False)}

帖子数据（最近20条）：
{json.dumps(posts_summary, ensure_ascii=False, indent=2)}

基于数据表现，给出归因分析和新的权重建议。大胆调整，不要保守。"""

    try:
        analysis = await call_claude_json(
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=1200,
            temperature=0.3,
        )

        # Validate and apply new weights
        new_weights = analysis.get("new_weights", {})
        if new_weights:
            # Ensure all keys present
            for key in ["ai_hot_take", "ai_tool_review", "startup_cognition",
                        "controversy", "kol_interaction"]:
                if key not in new_weights:
                    new_weights[key] = current_weights.get(key, 0.2)

            # Normalize to sum to 1.0
            total = sum(new_weights.values())
            if total > 0:
                new_weights = {k: v / total for k, v in new_weights.items()}

            # Clamp: no weight below 0.05 (so nothing is truly killed)
            for key in new_weights:
                new_weights[key] = max(0.05, new_weights[key])
            # Re-normalize
            total = sum(new_weights.values())
            new_weights = {k: v / total for k, v in new_weights.items()}

            # Save to database
            save_strategy_weights(
                conn, new_weights,
                reason=analysis.get("weight_reasoning", "auto_analysis"),
            )
            logger.info("Weights updated: %s", new_weights)

        # Update MEMORY.md
        _append_to_memory(
            f"策略调整：{analysis.get('weight_reasoning', 'N/A')}",
            section="策略权重变更记录",
        )

        conn.close()
        return analysis

    except Exception as exc:
        logger.error("Own post analysis failed: %s", exc)
        conn.close()
        return None


# ── 3B: KOL Viral Learning ──

KOL_LEARNING_PROMPT = """你是写作技法分析师。分析一条爆款帖子的叙事和写作手法。

提取：
1. 使用了哪些写作技法（钩子、节奏、收尾、情绪调动）
2. 为什么这个技法在这个话题上有效
3. 如何将这个技法迁移到 AI/创业 话题

输出JSON：
{
  "techniques": [
    {
      "name": "<技法名>",
      "description": "<怎么用>",
      "why_effective": "<为什么有效>",
      "migration_tip": "<如何迁移到AI/创业话题>"
    }
  ],
  "overall_pattern": "<整体模式总结>",
  "transferable_score": <1-10, 越高越容易迁移到AI/OPC内容>
}
"""


async def learn_from_kol_viral(viral_posts: list[KOLPost]) -> list[dict]:
    """
    Loop 3B: Extract writing techniques from viral KOL posts.
    Stores learned techniques in technique_library.
    Returns list of newly learned techniques.
    """
    if not viral_posts:
        return []

    conn = get_connection()
    new_techniques = []

    for post in viral_posts[:5]:  # analyze top 5 viral posts max
        user_prompt = f"""分析这条爆款帖子的写作技法：

KOL: {post.handle}
互动数据: {post.likes} likes / {post.retweets} retweets / {post.replies} replies

帖子内容：
{post.content}

提取可复用的写作技法。"""

        try:
            result = await call_claude_json(
                system_prompt=KOL_LEARNING_PROMPT,
                user_prompt=user_prompt,
                max_tokens=800,
                temperature=0.3,
            )

            techniques = result.get("techniques", [])
            transferable = result.get("transferable_score", 5)

            # Only save techniques with high transferability
            if transferable >= 6:
                for tech in techniques:
                    tech_id = insert_technique(
                        conn=conn,
                        technique_name=tech.get("name", "unknown"),
                        description=tech.get("description", ""),
                        example_text=post.content[:200],
                        source_kol=post.handle,
                        source_url=post.post_url,
                    )
                    new_techniques.append({
                        "id": tech_id,
                        "technique_name": tech.get("name", ""),
                        "description": tech.get("description", ""),
                        "source_kol": post.handle,
                    })
                    logger.info(
                        "Learned technique '%s' from %s",
                        tech.get("name", ""), post.handle,
                    )

        except Exception as exc:
            logger.warning("KOL learning failed for %s: %s", post.handle, exc)
            continue

    # Update MEMORY.md
    if new_techniques:
        tech_names = [t["technique_name"] for t in new_techniques]
        _append_to_memory(
            f"从KOL爆款学到新技法：{', '.join(tech_names)}",
            section="最佳实践",
        )

    conn.close()
    return new_techniques


# ── Circuit Breaker ──

async def check_circuit_breaker() -> bool:
    """
    Check if system should pause.
    Returns True if paused (should not post).
    Triggers:
    - 5 consecutive posts with 0 interactions
    - Twitter rate limit / ban detected
    """
    conn = get_connection()
    cb = get_circuit_breaker(conn)

    if cb.get("is_paused"):
        logger.warning("Circuit breaker is PAUSED. Skipping this cycle.")
        conn.close()
        return True

    # Check recent posts for consecutive 0-interaction
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
        _append_to_memory(
            f"CIRCUIT BREAKER触发：连续{consecutive_zeros}条0互动帖子，系统暂停",
            section="已知坑",
        )
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


# ── Memory management ──

def _append_to_memory(entry: str, section: str = "最佳实践") -> None:
    """Append a dated entry to MEMORY.md under the given section."""
    today = datetime.now().strftime("%Y-%m-%d")
    entry_line = f"\n- [{today}] {entry}"

    try:
        content = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else ""
        if section in content:
            # Insert after section header
            parts = content.split(f"## {section}")
            if len(parts) == 2:
                content = f"{parts[0]}## {section}{entry_line}{parts[1]}"
            else:
                content += f"\n\n## {section}{entry_line}"
        else:
            content += f"\n\n## {section}{entry_line}"

        MEMORY_PATH.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to update MEMORY.md: %s", exc)


def get_learned_techniques() -> list[dict]:
    """Get all learned techniques for feeding into writer."""
    conn = get_connection()
    techniques = get_all_techniques(conn)
    conn.close()
    return techniques
