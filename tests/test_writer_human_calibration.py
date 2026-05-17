import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import writer


class WriterHumanCalibrationTests(unittest.TestCase):
    def test_human_prior_block_is_present(self) -> None:
        system_prompt = writer._build_writer_system_prompt(  # noqa: SLF001
            "ai_hot_take",
            reaction_pack={
                "status": "ok",
                "what_everyone_noticed": ["价格变化"],
                "angle_patterns": ["先看成本"],
                "hook_patterns": ["真正该看的不是X 是Y"],
                "surprise_patterns": ["先讲反常识"],
                "avoid_patterns": ["复述官宣"],
                "underused_angle": "分发成本",
                "suggested_stance": "别急着吹能力",
                "freshness_note": "适合快评",
                "writer_notes": ["一开始先亮判断"],
            },
        )

        self.assertIn("human_prior_level: natural-human", system_prompt)
        self.assertIn("reaction pack", system_prompt)
        self.assertNotIn("每条推文至少用 1-2 个", system_prompt)
        self.assertIn("不必强行喊口号或暴论", system_prompt)

    def test_learning_context_is_in_prompt(self) -> None:
        system_prompt = writer._build_writer_system_prompt(  # noqa: SLF001
            "ai_hot_take",
            reaction_pack={
                "status": "ok",
                "what_everyone_noticed": ["价格变化"],
                "angle_patterns": ["先看成本"],
                "hook_patterns": ["真正该看的不是X 是Y"],
                "surprise_patterns": ["先讲反常识"],
                "avoid_patterns": ["复述官宣"],
                "underused_angle": "分发成本",
                "suggested_stance": "别急着吹能力",
                "freshness_note": "适合快评",
                "writer_notes": ["一开始先亮判断"],
            },
            learning_context={
                "winning_patterns": ["开头要给结论后再给判断"],
                "losing_patterns": ["第一句口语化"],
                "human_calibration_notes": ["少用夸张词"],
                "next_writing_hypotheses": ["增加反常识例子"],
                "review_summary": "用户更喜欢有立场并带例证的版本",
                "strategy_adjustment": {
                    "weights": {
                        "ai_hot_take": 0.42,
                        "ai_tool_review": 0.18,
                        "startup_cognition": 0.22,
                        "controversy": 0.18,
                        "kol_interaction": 0.0,
                    },
                },
            },
        )
        self.assertIn("复盘学习上下文（review -> 下一轮）", system_prompt)
        self.assertIn("赢在形式", system_prompt)
        self.assertIn("失误点", system_prompt)
        self.assertIn("学习后权重建议", system_prompt)

    def test_human_prior_block_preserves_fact_rule(self) -> None:
        human_prior = writer._build_human_prior_block()  # noqa: SLF001
        self.assertIn("fact_rule: humanize the delivery, not the facts", human_prior)
        self.assertIn("Lead with the take", human_prior)

    def test_fact_spine_prompt_and_angle_card_prompt_exist(self) -> None:
        self.assertIn("硬事实骨架", writer.FACT_SPINE_PROMPT)
        self.assertIn("先决定这条推文怎么反应", writer.ANGLE_CARD_PROMPT)
        self.assertIn("AI 总结腔", writer.ANTI_TEMPLATE_AUDIT_PROMPT)

    def test_join_brief_uses_compact_separator(self) -> None:
        result = writer._join_brief(["a", "b", "c"])  # noqa: SLF001
        self.assertEqual(result, "a；b；c")


class WriterPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_tweet_uses_fact_spine_angle_and_audit(self) -> None:
        calls = []

        async def fake_call_claude_json(*, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float):
            calls.append(system_prompt)
            if system_prompt == writer.FACT_SPINE_PROMPT:
                return {
                    "fact_spine": ["OpenAI 把 ChatGPT 和 Codex 放到手机端"],
                    "most_telling_fact": "手机端入口扩张",
                    "image_anchor": "产品界面截图",
                    "uncertainty": "none",
                }
            if system_prompt == writer.ANGLE_CARD_PROMPT:
                return {
                    "posture": "quick_judgment",
                    "stance": "入口扩张是真的 但主力开发场景没变",
                    "hook_style": "先讲反差",
                    "surprise_move": "功能很强 但使用强度会被高估",
                    "supporting_move": "解释为什么大多数只是轻任务",
                    "ending_style": "落回使用场景",
                    "avoid": ["官宣复述"],
                    "writer_brief": "像真人第一反应",
                }
            if system_prompt == writer.ANTI_TEMPLATE_AUDIT_PROMPT:
                return {
                    "verdict": "pass",
                    "why_it_reads_ai": [],
                    "surgical_fixes": [],
                    "rewrite_focus": "",
                }
            return {
                "tweet": "手机端接了ChatGPT和Codex\n\n功能更完整了\n\n但离主力开发机还远",
                "image_prompt": "产品界面截图",
                "hook_used": "反差开头",
                "self_eval": "像第一反应",
            }

        with patch.object(writer, "call_claude_json", side_effect=fake_call_claude_json):
            result = await writer.write_tweet(
                content_type="ai_hot_take",
                source_material="标题: OpenAI 把 ChatGPT 和 Codex 放到手机端",
                reaction_pack={
                    "status": "ok",
                    "what_everyone_noticed": ["手机端入口"],
                    "angle_patterns": ["先看使用场景"],
                    "hook_patterns": ["真正变的不是功能 是入口"],
                    "surprise_patterns": ["功能强 但主场景没变"],
                    "avoid_patterns": ["纯复述官宣"],
                    "underused_angle": "主力开发机替代率",
                    "suggested_stance": "别高估移动端开发",
                    "freshness_note": "适合快评",
                    "writer_notes": ["第一句先亮判断"],
                },
            )

        self.assertIsNotNone(result)
        self.assertIn(writer.FACT_SPINE_PROMPT, calls)
        self.assertIn(writer.ANGLE_CARD_PROMPT, calls)
        self.assertIn(writer.ANTI_TEMPLATE_AUDIT_PROMPT, calls)

    async def test_write_tweet_falls_back_on_final_audit_attempt(self) -> None:
        audit_calls = 0

        async def fake_call_claude_json(*, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float):
            nonlocal audit_calls
            if system_prompt == writer.FACT_SPINE_PROMPT:
                return {
                    "fact_spine": ["产品上了手机端"],
                    "most_telling_fact": "入口扩张",
                    "image_anchor": "产品界面截图",
                    "uncertainty": "none",
                }
            if system_prompt == writer.ANGLE_CARD_PROMPT:
                return {
                    "posture": "quick_judgment",
                    "stance": "入口变大了 但主场景没变",
                    "hook_style": "先讲反差",
                    "surprise_move": "功能很强 但多数人只会轻用",
                    "supporting_move": "解释使用强度",
                    "ending_style": "收回到场景",
                    "avoid": ["官宣复述"],
                    "writer_brief": "像真人第一反应",
                }
            if system_prompt == writer.ANTI_TEMPLATE_AUDIT_PROMPT:
                audit_calls += 1
                return {
                    "verdict": "needs_rewrite",
                    "why_it_reads_ai": ["句子太平均"],
                    "surgical_fixes": ["把第一句改得更像第一反应"],
                    "rewrite_focus": "第一行",
                }
            return {
                "tweet": "手机端也能直接开了\n\n功能当然更全了\n\n但大多数人还是先拿来做轻任务",
                "image_prompt": "产品界面截图",
                "hook_used": "反差开头",
                "self_eval": "像第一反应",
            }

        with patch.object(writer, "call_claude_json", side_effect=fake_call_claude_json):
            result = await writer.write_tweet(
                content_type="ai_hot_take",
                source_material="标题: 产品上了手机端",
            )

        self.assertIsNotNone(result)
        self.assertGreaterEqual(audit_calls, 1)


if __name__ == "__main__":
    unittest.main()
