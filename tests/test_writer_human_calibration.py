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


if __name__ == "__main__":
    unittest.main()
