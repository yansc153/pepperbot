"""
LLM-based content writer.
Generates tweets in @pepperfr1ends voice using persona + voice rules + templates.
LLM writes; guardrails.py validates; loop until clean or max retries.
"""

import logging
import json
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


def _load_file(path: Path) -> str:
    """Load a markdown file as string."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("File not found: %s", path)
    return ""


def _build_writer_system_prompt(
    content_type: str,
    techniques: list[dict] | None = None,
) -> str:
    """Build the full system prompt for the writer LLM call."""
    persona = _load_file(PERSONA_PATH)
    voice_profile = _load_file(VOICE_PROFILE_PATH)
    voice_rules = _load_file(VOICE_RULES_PATH)
    hooks = _load_file(HOOKS_PATH)
    template = _load_file(TEMPLATE_AI_PATH)

    technique_block = ""
    if techniques:
        technique_block = "\n\n## 从爆款帖子中学到的写作技法\n"
        for tech in techniques[:5]:
            technique_block += f"- {tech['technique_name']}: {tech['description']}\n"

    return f"""你是 @pepperfr1ends（花椒），一个 AI/OPC 创业者的 Twitter 账号。

## 必须使用的俚语/口语词（每条推文至少用 1-2 个）
从这些词里自然地挑：
玩出花来了、玩明白了、折腾、不用折腾了、闷声发大财、拼凑、糊了一个、
一口气放出来了、纯纯的、属于是、脑子瓦特了、上头了、整活、搞事情、
离谱、炸了、跑通了、跑废了、真香、GG了、凉了、直接起飞、直接拉满、
没跑了、妥妥的、嘎嘎好、草、严重的、卖课的、卖流量的、
tokenmaxxing、vibe coding、卷起来了、打起来了

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
{technique_block}

## 硬性排版规则（违反任何一条 = 重写）
1. 一句话一行。每个完整意思独占一行
2. 每行之间必须空一行。两行文字不允许紧贴
3. 行尾不加句号。整条推文不出现任何句号
4. 逗号用空格代替。「A，B」→「A B」
5. 不用结构标签。「对的部分：」「问题在于：」这种标签删掉 直接写内容

## 硬性内容规则
6. 每条推文 ≤ {MAX_TWEET_LENGTH} 字
7. 第一行 ≤ 20 字
8. 必须有坚定立场
9. 不用破折号 ——
10. 不用排比句
11. 不用「赋能/格局/综上所述/建议大家/你怎么看」
12. 不出现源帖元词（原帖/原话/这帖/文章里/据XX报道）
13. emoji ≤ 2个，🔥🚀📈📉 不用
14. 主语用「我」不用「我们」
15. 收尾用暴论/定心丸/悬念 不用设问。收尾要有力量 例：「买就对了 你怕啥」「差距在拉大」
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


async def write_tweet(
    content_type: str,
    source_material: str = "",
    extra_context: str = "",
    techniques: list[dict] | None = None,
) -> dict | None:
    """
    Generate a single tweet.
    Runs guardrail loop: write → check → rewrite if needed.
    Returns dict with tweet, image_prompt, hook_used, self_eval.
    Returns None if all attempts fail.
    """
    system_prompt = _build_writer_system_prompt(content_type, techniques)

    if source_material:
        user_prompt = f"""你收到了一条 {content_type} 类型的AI资讯素材，请把它改写成花椒的推文。

## 原始素材
{source_material[:1200]}

## 要求
1. 不是翻译/搬运，是用花椒的第一人称视角改写
2. 加入自己的立场判断（看好/看衰/矛盾点在哪）
3. 如果有数据就用数据说话
4. 每条推文必须配图建议（描述图片内容，方便后续使用原文配图或生成图）
{f"5. 额外上下文：{extra_context}" if extra_context else ""}"""
    else:
        user_prompt = f"""自由发挥，写一条 {content_type} 类型的AI/创业观点推文。

要有立场、有数字、有态度。不要温吞水。
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

            # Strip trailing 。 from each line — Moonshot habitually adds them
            tweet_text = "\n".join(line.rstrip("。") for line in tweet_text.split("\n"))
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
