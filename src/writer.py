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
    HOOKS_PATH,
    TEMPLATE_AI_PATH,
    PERSONA_PATH,
    MAX_TWEET_LENGTH,
)

logger = logging.getLogger(__name__)

MAX_REWRITE_ATTEMPTS = 3
HUMAN_TEXT_PRIOR_ROOT = Path(__file__).resolve().parent.parent / "skills" / "human-text-prior" / "references"

FACT_SPINE_PROMPT = """你是新闻事实提炼器。

任务：把输入新闻压成硬事实骨架，不写观点，不下判断，不做意义拔高。

输出 JSON：
{
  "fact_spine": ["<事实1>", "<事实2>", "<事实3>"],
  "most_telling_fact": "<最值得盯的一条事实>",
  "image_anchor": "<最适合作为配图依据的对象或画面>",
  "uncertainty": "<还不确定的部分，没有就写none>"
}
"""

ANGLE_CARD_PROMPT = """你是社交写作者的角度编辑。

你要根据事实骨架和 reaction pack，先决定这条推文怎么反应，再交给写手去写。
不要直接写完整推文。

输出 JSON：
{
  "posture": "<quick_judgment|follow_up|reverse_angle|measured_take>",
  "stance": "<明确取向>",
  "hook_style": "<开头怎么切>",
  "surprise_move": "<反差/惊讶/质疑点>",
  "supporting_move": "<正文怎么承接>",
  "ending_style": "<怎么落地收住>",
  "avoid": ["<不要写成什么样>"],
  "writer_brief": "<给写手的一句话 brief>"
}
"""

ANTI_TEMPLATE_AUDIT_PROMPT = """你是中文社交文案审稿人。

检查这条推文是不是太像 AI 总结腔、KOL 模板腔、或者“为了发帖而发帖”。
不要改事实，只找最需要改的 1-3 处。

输出 JSON：
{
  "verdict": "pass" | "needs_rewrite",
  "why_it_reads_ai": ["<问题1>", "<问题2>"],
  "surgical_fixes": ["<局部改法1>", "<局部改法2>"],
  "rewrite_focus": "<优先改第一行/最后一行/最模板的那句>"
}
"""


def _load_file(path: Path) -> str:
    """Load a markdown file as string."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("File not found: %s", path)
    return ""


def _join_brief(items: list[str], limit: int = 4) -> str:
    return "；".join(item for item in items[:limit] if item)


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
- 大家都在注意：{_join_brief(reaction_pack.get("what_everyone_noticed", []))}
- 常见切角：{_join_brief(reaction_pack.get("angle_patterns", []))}
- 常见钩子：{_join_brief(reaction_pack.get("hook_patterns", []))}
- 可用惊讶手法：{_join_brief(reaction_pack.get("surprise_patterns", []))}
- 不能学的写法：{_join_brief(reaction_pack.get("avoid_patterns", []))}
- 还没被写透的角度：{reaction_pack.get("underused_angle", "")}
- 适合本账号的立场：{reaction_pack.get("suggested_stance", "")}
- 时效提醒：{reaction_pack.get("freshness_note", "")}
- 给 writer 的提醒：{_join_brief(reaction_pack.get("writer_notes", []))}
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


async def _build_fact_spine(source_material: str) -> dict:
    if not source_material.strip():
        return {
            "fact_spine": [],
            "most_telling_fact": "",
            "image_anchor": "",
            "uncertainty": "none",
        }

    result = await call_claude_json(
        system_prompt=FACT_SPINE_PROMPT,
        user_prompt=f"请提炼这条新闻素材：\n\n{source_material[:1800]}",
        max_tokens=500,
        temperature=0.2,
    )
    result.setdefault("fact_spine", [])
    result.setdefault("most_telling_fact", "")
    result.setdefault("image_anchor", "")
    result.setdefault("uncertainty", "none")
    return result


async def _build_angle_card(
    content_type: str,
    fact_spine: dict,
    reaction_pack: dict | None = None,
    extra_context: str = "",
) -> dict:
    reaction_summary = "无 recent reaction pack"
    if reaction_pack:
        reaction_summary = (
            f"大家都在注意: {_join_brief(reaction_pack.get('what_everyone_noticed', []))}\n"
            f"常见切角: {_join_brief(reaction_pack.get('angle_patterns', []))}\n"
            f"常见钩子: {_join_brief(reaction_pack.get('hook_patterns', []))}\n"
            f"惊讶手法: {_join_brief(reaction_pack.get('surprise_patterns', []))}\n"
            f"不要学: {_join_brief(reaction_pack.get('avoid_patterns', []))}\n"
            f"时效提醒: {reaction_pack.get('freshness_note', '')}\n"
            f"建议立场: {reaction_pack.get('suggested_stance', '')}"
        )

    result = await call_claude_json(
        system_prompt=ANGLE_CARD_PROMPT,
        user_prompt=(
            f"内容类型: {content_type}\n\n"
            f"事实骨架:\n{_join_brief(fact_spine.get('fact_spine', []), limit=6)}\n"
            f"最值得看的事实: {fact_spine.get('most_telling_fact', '')}\n"
            f"反应摘要:\n{reaction_summary}\n"
            f"{'额外上下文: ' + extra_context if extra_context else ''}"
        ),
        max_tokens=500,
        temperature=0.4,
    )
    result.setdefault("posture", "quick_judgment")
    result.setdefault("stance", "")
    result.setdefault("hook_style", "")
    result.setdefault("surprise_move", "")
    result.setdefault("supporting_move", "")
    result.setdefault("ending_style", "")
    result.setdefault("avoid", [])
    result.setdefault("writer_brief", "")
    return result


async def _audit_draft(
    tweet_text: str,
    fact_spine: dict,
    angle_card: dict,
) -> dict:
    result = await call_claude_json(
        system_prompt=ANTI_TEMPLATE_AUDIT_PROMPT,
        user_prompt=(
            f"事实骨架: {_join_brief(fact_spine.get('fact_spine', []), limit=6)}\n"
            f"角度卡: stance={angle_card.get('stance', '')}; hook={angle_card.get('hook_style', '')}; "
            f"surprise={angle_card.get('surprise_move', '')}\n\n"
            f"待审推文:\n{tweet_text}"
        ),
        max_tokens=400,
        temperature=0.2,
    )
    result.setdefault("verdict", "pass")
    result.setdefault("why_it_reads_ai", [])
    result.setdefault("surgical_fixes", [])
    result.setdefault("rewrite_focus", "")
    return result


async def write_tweet(
    content_type: str,
    source_material: str = "",
    extra_context: str = "",
    reaction_pack: dict | None = None,
) -> dict | None:
    """
    Generate a single tweet.
    Runs a structured loop:
    facts -> angle -> draft -> anti-template audit -> guardrails.
    Returns dict with tweet, image_prompt, hook_used, self_eval.
    Returns None if all attempts fail.
    """
    system_prompt = _build_writer_system_prompt(content_type, reaction_pack)
    try:
        fact_spine = await _build_fact_spine(source_material)
    except Exception as exc:
        logger.warning("Fact spine build failed, falling back to source material: %s", exc)
        fact_spine = {
            "fact_spine": [],
            "most_telling_fact": "",
            "image_anchor": "",
            "uncertainty": "none",
        }

    try:
        angle_card = await _build_angle_card(content_type, fact_spine, reaction_pack, extra_context)
    except Exception as exc:
        logger.warning("Angle card build failed, falling back to direct draft: %s", exc)
        angle_card = {
            "posture": "quick_judgment",
            "stance": "",
            "hook_style": "",
            "surprise_move": "",
            "supporting_move": "",
            "ending_style": "",
            "avoid": [],
            "writer_brief": "",
        }

    if source_material:
        user_prompt = f"""你收到了一条 {content_type} 类型的AI资讯素材，请把它改写成花椒的推文。

## 原始素材
{source_material[:1200]}

## 事实骨架
{chr(10).join(f"- {item}" for item in fact_spine.get("fact_spine", [])[:6])}

## angle card
- posture: {angle_card.get("posture", "")}
- stance: {angle_card.get("stance", "")}
- hook_style: {angle_card.get("hook_style", "")}
- surprise_move: {angle_card.get("surprise_move", "")}
- supporting_move: {angle_card.get("supporting_move", "")}
- ending_style: {angle_card.get("ending_style", "")}
- avoid: {_join_brief(angle_card.get("avoid", []))}
- writer_brief: {angle_card.get("writer_brief", "")}

## 要求
1. 不是翻译/搬运，是用花椒的第一人称视角改写
2. 加入自己的立场判断（看好/看衰/矛盾点在哪）
3. 如果有数据就用数据说话
4. 每条推文必须配图建议（描述图片内容，方便后续使用原文配图或生成图）
5. 开头像真人刚看到这条消息 不是像写总结
6. 可以学习别人的反应结构，但不要复用他们的原句或固定话术
{f"7. 额外上下文：{extra_context}" if extra_context else ""}"""
    else:
        user_prompt = f"""自由发挥，写一条 {content_type} 类型的AI/创业观点推文。

## angle card
- posture: {angle_card.get("posture", "")}
- stance: {angle_card.get("stance", "")}
- hook_style: {angle_card.get("hook_style", "")}
- surprise_move: {angle_card.get("surprise_move", "")}
- supporting_move: {angle_card.get("supporting_move", "")}
- ending_style: {angle_card.get("ending_style", "")}
- avoid: {_join_brief(angle_card.get("avoid", []))}
- writer_brief: {angle_card.get("writer_brief", "")}

要有取向、有数字、有态度，但不要像模板化暴论机器，也不要像行业周报。
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

            try:
                audit = await _audit_draft(tweet_text, fact_spine, angle_card)
            except Exception as exc:
                logger.warning("Anti-template audit failed: %s", exc)
                audit = {"verdict": "pass", "why_it_reads_ai": [], "surgical_fixes": [], "rewrite_focus": ""}

            if audit.get("verdict") == "needs_rewrite":
                user_prompt = f"""上一版推文太像模板/AI 总结腔，需要局部重写。

问题：
{chr(10).join(f"- {item}" for item in audit.get("why_it_reads_ai", []))}

优先改：
{audit.get("rewrite_focus", "")}

具体改法：
{chr(10).join(f"- {item}" for item in audit.get("surgical_fixes", []))}

原推文：
{tweet_text}

要求：保留事实骨架和立场，不要整条推倒重来，只把最像模板的地方改掉。"""
                continue

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
