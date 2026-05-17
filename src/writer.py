"""
LLM-based content writer.
Generates tweets in @pepperfr1ends voice using persona + voice rules + templates.
LLM writes; guardrails.py validates; loop until clean or max retries.
"""

import logging
from pathlib import Path

from llm import call_claude, call_claude_json
from guardrails import run_all_guardrails, has_kill_violation, SlopSeverity
from config import (
    VOICE_PROFILE_PATH,
    VOICE_RULES_PATH,
    AVOID_SLOP_PATH,
    HOOKS_PATH,
    TEMPLATE_AI_PATH,
    PERSONA_PATH,
    MAX_TWEET_LENGTH,
)

logger = logging.getLogger(__name__)

MAX_REWRITE_ATTEMPTS = 3
HUMAN_TEXT_PRIOR_ROOT = Path(__file__).resolve().parent.parent / "skills" / "human-text-prior" / "references"


def _load_file(path: Path) -> str:
    """Load a markdown file as string."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("File not found: %s", path)
    return ""


def _build_writer_system_prompt(
    content_type: str,
    reaction_pack: dict | None = None,
) -> str:
    """Build the full system prompt for the writer LLM call."""
    persona = _load_file(PERSONA_PATH)
    voice_profile = _load_file(VOICE_PROFILE_PATH)
    voice_rules = _load_file(VOICE_RULES_PATH)
    hooks = _load_file(HOOKS_PATH)
    template = _load_file(TEMPLATE_AI_PATH)

    reaction_block = ""
    if reaction_pack and reaction_pack.get("status") == "ok":
        reaction_block = f"""

## reaction pack（只学反应结构 不学原句）
- 大家都在注意：{", ".join(reaction_pack.get("what_everyone_noticed", [])[:4])}
- 常见切角：{", ".join(reaction_pack.get("angle_patterns", [])[:4])}
- 常见钩子：{", ".join(reaction_pack.get("hook_patterns", [])[:4])}
- 可用惊讶手法：{", ".join(reaction_pack.get("surprise_patterns", [])[:4])}
- 不能学的写法：{", ".join(reaction_pack.get("avoid_patterns", [])[:4])}
- 还没被写透的角度：{reaction_pack.get("underused_angle", "")}
- 适合本账号的立场：{reaction_pack.get("suggested_stance", "")}
- 时效提醒：{reaction_pack.get("freshness_note", "")}
- 给 writer 的提醒：{", ".join(reaction_pack.get("writer_notes", [])[:4])}
"""

    human_prior_block = _build_human_prior_block()

    return f"""你是 @pepperfr1ends（花椒），一个 AI/OPC 创业者的 Twitter 账号。

## 人设核心
{persona[:1500]}

## 声音档案
{voice_profile[:2000]}

## 句式规则
{voice_rules[:1500]}

## 钩子库
{hooks[:800]}

## 内容模板（{content_type}）
{template[:1000]}
{reaction_block}

## human-text-prior 结构校准
{human_prior_block}

## 硬性排版规则（违反任何一条 = 重写）
1. 一句话一行。每个完整意思独占一行
2. 每行之间必须空一行。两行文字不允许紧贴
3. 行尾不加句号。整条推文不出现任何句号
4. 逗号用空格代替。「A，B」→「A B」
5. 不用结构标签。「对的部分：」「问题在于：」这种标签删掉 直接写内容

## 硬性内容规则
6. 每条推文 ≤ {MAX_TWEET_LENGTH} 字
7. 第一行 ≤ 20 字
8. 必须有明确取向，但不要每条都写成暴论模板
9. 不用破折号 ——
10. 不用排比句
11. 不用「赋能/格局/综上所述/建议大家/你怎么看」
12. 不出现源帖元词（原帖/原话/这帖/文章里/据XX报道）
13. emoji ≤ 2个，🔥🚀📈📉 不用
14. 主语用「我」不用「我们」
15. 收尾要落地，可以收住，不必强行喊口号或暴论
16. 不强行把每个话题都拉到 OPC/一人公司叙事。话题本身够硬就直接说
17. 不写元评论（「这条消息的重点不是X而是Y」）直接说内容
18. 必须包含配图建议

输出JSON格式：
{{
  "tweet": "<推文正文>",
  "image_prompt": "<配图描述/建议>",
  "hook_used": "<使用了哪种钩子>",
  "self_eval": "<自我评价，一句话>"
}}
"""


def _build_human_prior_block() -> str:
    """Load a compact human-text-prior handoff for structural calibration."""
    integration = _load_file(HUMAN_TEXT_PRIOR_ROOT / "integration-contract.md")
    human_core = _load_file(HUMAN_TEXT_PRIOR_ROOT / "human-core.md")
    news_rewrite = _load_file(HUMAN_TEXT_PRIOR_ROOT / "news-rewrite.md")

    keep = [
        "Lead with the take, not the full background",
        "Keep one sentence visibly plainer than the others",
        "Preserve technical accuracy and all source facts",
        "Use reaction to sharpen the post, not to replace the facts",
    ]
    avoid = [
        "Thesis-essay scaffolding",
        "Over-symmetry",
        "Fake all-sides neutrality",
        "Forced slang or mandatory hot-take endings",
    ]
    cadence = [
        "Short opening, medium explanation, short landing",
        "Let one sentence carry the reaction instead of making every sentence perform",
        "Assume the audience already knows the broad AI topic category",
    ]

    return "\n".join(
        [
            "human_prior_level: natural-human",
            "keep:",
            *[f"- {item}" for item in keep],
            "avoid:",
            *[f"- {item}" for item in avoid],
            "cadence_notes:",
            *[f"- {item}" for item in cadence],
            "fact_rule: humanize the delivery, not the facts",
            f"references: integration={bool(integration)}, core={bool(human_core)}, news={bool(news_rewrite)}",
        ]
    )


async def write_tweet(
    content_type: str,
    source_material: str = "",
    extra_context: str = "",
    reaction_pack: dict | None = None,
) -> dict | None:
    """
    Generate a single tweet.
    Runs guardrail loop: write → check → rewrite if needed.
    Returns dict with tweet, image_prompt, hook_used, self_eval.
    Returns None if all attempts fail.
    """
    system_prompt = _build_writer_system_prompt(content_type, reaction_pack)

    if source_material:
        user_prompt = f"""你收到了一条 {content_type} 类型的AI资讯素材，请把它改写成花椒的推文。

## 原始素材
{source_material[:1200]}

## 要求
1. 不是翻译/搬运，是用花椒的第一人称视角改写
2. 加入自己的立场判断（看好/看衰/矛盾点在哪）
3. 如果有数据就用数据说话
4. 每条推文必须配图建议（描述图片内容，方便后续使用原文配图或生成图）
5. 可以学习别人的反应结构，但不要复用他们的原句或固定话术
{f"5. 额外上下文：{extra_context}" if extra_context else ""}"""
    else:
        user_prompt = f"""自由发挥，写一条 {content_type} 类型的AI/创业观点推文。

要有取向、有数字、有态度，但不要像模板化暴论机器。
{f"额外上下文：{extra_context}" if extra_context else ""}"""

    for attempt in range(MAX_REWRITE_ATTEMPTS):
        try:
            result = await call_claude_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=800,
                temperature=0.8 - (attempt * 0.1),  # lower temp on retries
            )

            tweet_text = result.get("tweet", "")
            if not tweet_text:
                logger.warning("Empty tweet from LLM, attempt %d", attempt + 1)
                continue

            # Deterministic formatting fixes — Moonshot ignores these prompt rules reliably
            tweet_text = "\n".join(line.rstrip("。") for line in tweet_text.split("\n"))
            tweet_text = tweet_text.replace("，", " ")
            result["tweet"] = tweet_text

            # Run guardrails
            failures = run_all_guardrails(tweet_text)

            if not failures:
                logger.info("Tweet passed all guardrails on attempt %d", attempt + 1)
                return result

            # Check if any A-class (kill) violations
            kill_failures = [f for f in failures if f.severity == SlopSeverity.A]
            rewrite_failures = [f for f in failures if f.severity in (SlopSeverity.B, SlopSeverity.C)]

            if kill_failures:
                logger.warning(
                    "A-class violation attempt %d: %s",
                    attempt + 1,
                    [f.matched_patterns for f in kill_failures],
                )
                # Full rewrite with explicit feedback
                user_prompt = f"""上一版推文被拒绝，存在以下问题：
{chr(10).join(f"- {f.reason}: {f.matched_patterns}" for f in failures)}

原推文：
{tweet_text}

请完全重写，避免上述所有问题。记住：不要用破折号、不要用排比、第一行≤20字、总长≤{MAX_TWEET_LENGTH}字。"""
                continue

            if rewrite_failures:
                logger.info(
                    "B/C violations attempt %d, requesting rewrite: %s",
                    attempt + 1,
                    [f.matched_patterns for f in rewrite_failures],
                )
                user_prompt = f"""推文需要微调，以下表达需要改写：
{chr(10).join(f"- {f.reason}: {f.matched_patterns}" for f in rewrite_failures)}

原推文：
{tweet_text}

请改写有问题的表达，保持整体意思不变。"""
                continue

        except Exception as exc:
            logger.error("Writer attempt %d failed: %s", attempt + 1, exc)
            continue

    logger.error("Failed to generate clean tweet after %d attempts", MAX_REWRITE_ATTEMPTS)
    return None


async def write_kol_comment(
    kol_handle: str,
    kol_post_content: str,
    kol_tier: str,
) -> str | None:
    """
    Generate a comment for a KOL's post.
    Must have information increment, 2-4 sentences.
    """
    system_prompt = f"""你是 @pepperfr1ends（花椒），要在KOL的帖子下写一条有信息增量的评论。

规则：
- 2-4句话
- 必须有信息增量（补充数据、反面案例、亲身经历、具体工具推荐）
- 不说「学到了」「写得好」「收藏了」「感谢分享」
- 不用破折号 ——
- 不用「赋能/格局/综上所述」
- 语气坚定但不攻击
- 可以补充、可以质疑、可以加自己的实操经验
- 像一个同行在讨论，不像粉丝在追捧

输出纯文本评论，不要JSON。"""

    user_prompt = f"""KOL: {kol_handle} (Tier: {kol_tier})

KOL帖子内容：
{kol_post_content[:500]}

请写一条有信息增量的评论。"""

    try:
        comment = await call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=300,
            temperature=0.7,
        )
        comment = comment.strip().strip('"').strip("'")

        # Guardrail check on comment too
        if has_kill_violation(comment):
            logger.warning("KOL comment has kill violation, discarding")
            return None

        # Length check (comments should be shorter)
        if len(comment) > 280:
            comment = comment[:277] + "..."

        return comment

    except Exception as exc:
        logger.error("KOL comment generation failed: %s", exc)
        return None
