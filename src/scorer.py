"""
LLM-based content scoring.
Uses the 4-dimension rubric from config/filter_rules.md.
LLM evaluates; Python enforces thresholds.
"""

import logging
from typing import Any

from llm import call_claude_json
from config import (
    FILTER_PASS_THRESHOLD,
    FILTER_REVIEW_THRESHOLD,
    PERSONA_PATH,
    VOICE_PROFILE_PATH,
)

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """你是一个内容质量评分员，为 Twitter 账号 @pepperfr1ends 评估推文质量。

评分维度（4维度，总分0-85）：

Dim1 — 立场可承接度（0-20）
这条内容是否有"花椒立场可以套上去"的角度？
花椒核心立场：AI是杠杆不是替代品、OPC一人公司信仰、Build in Public、怀疑论默认值、数据实证主义、执行力>认知
0 = 无法挂钩任何立场
12 = 有1-2个明显立场切入点
20 = 同时切多个立场

Dim2 — receipts可验证度（0-20）
是否有具体数字/可验证source/可截图内容？
0 = 全是定性描述
15 = 有数字+链向官方/产品页
20 = 多个receipts，截图素材丰富

Dim3 — 反共识/故事性（0-25）
0 = 完全合规共识叙事，无张力
18 = 反共识+有具体案例
25 = 反共识+故事+反转可拆

Dim4 — 受众相关度（0-20）
受众：男25-40，AI/科技从业，创业者，独立开发者
0 = 完全不关心
15 = 主受众痛点
20 = 主受众痛点+强情绪共鸣

输出JSON格式：
{
  "stance": <int>,
  "receipts": <int>,
  "counter": <int>,
  "audience": <int>,
  "total": <int>,
  "reasoning": "<一句话解释>"
}
"""


async def score_content(
    content: str,
    content_type: str,
    source_context: str = "",
) -> dict[str, Any]:
    """
    Score a piece of content using LLM.
    Returns dict with stance, receipts, counter, audience, total, reasoning.
    """
    user_prompt = f"""请评分以下推文草稿：

---
内容类型: {content_type}
草稿内容:
{content}
---
{f"素材背景: {source_context}" if source_context else ""}

按4个维度打分并输出JSON。"""

    try:
        result = await call_claude_json(
            system_prompt=SCORING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        # Validate and clamp scores
        result["stance"] = max(0, min(20, int(result.get("stance", 0))))
        result["receipts"] = max(0, min(20, int(result.get("receipts", 0))))
        result["counter"] = max(0, min(25, int(result.get("counter", 0))))
        result["audience"] = max(0, min(20, int(result.get("audience", 0))))
        result["total"] = (
            result["stance"] + result["receipts"]
            + result["counter"] + result["audience"]
        )
        return result
    except Exception as exc:
        logger.error("Scoring failed: %s", exc)
        return {
            "stance": 0, "receipts": 0, "counter": 0,
            "audience": 0, "total": 0, "reasoning": f"scoring_error: {exc}",
        }


def decide_publish(score_total: int) -> str:
    """
    Deterministic decision based on score.
    Returns: 'pass' / 'needs_review' / 'drop'
    """
    if score_total >= FILTER_PASS_THRESHOLD:
        return "pass"
    elif score_total >= FILTER_REVIEW_THRESHOLD:
        return "needs_review"
    else:
        return "drop"
