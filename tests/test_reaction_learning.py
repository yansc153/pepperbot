import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import learner


class _DummyConn:
    def close(self) -> None:
        return None


class ReactionLearningTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_reaction_pack_returns_empty_shape_without_samples(self) -> None:
        with (
            patch.object(learner, "get_connection", return_value=_DummyConn()),
            patch.object(learner, "get_recent_reaction_observations", return_value=[]),
        ):
            result = await learner.build_reaction_pack(
                source_material="标题: Anthropic 发布新模型",
                source_url="https://example.com/news",
                source_title="Anthropic 发布新模型",
            )

        self.assertEqual(result["status"], "no_recent_reactions")
        self.assertEqual(result["relevant_count"], 0)
        self.assertEqual(result["writer_notes"], [])

    async def test_build_reaction_pack_distills_samples(self) -> None:
        samples = [
            {
                "kol_handle": "@foo",
                "likes": 12,
                "retweets": 4,
                "replies": 1,
                "post_text": "这次真正该看的不是模型参数 是价格和延迟",
            }
        ]
        fake_result = {
            "status": "ok",
            "relevant_count": 1,
            "what_everyone_noticed": ["价格变化"],
            "angle_patterns": ["先看成本"],
            "hook_patterns": ["真正该看的不是X 是Y"],
            "surprise_patterns": ["反常识先切成本"],
            "avoid_patterns": ["纯复述发布会"],
            "underused_angle": "谁会被替代",
            "suggested_stance": "别先吹能力 先看成本",
            "freshness_note": "适合快评",
            "writer_notes": ["先亮观点 再补数字"],
        }
        with (
            patch.object(learner, "get_connection", return_value=_DummyConn()),
            patch.object(learner, "get_recent_reaction_observations", return_value=samples),
            patch.object(learner, "call_claude_json", return_value=fake_result),
        ):
            result = await learner.build_reaction_pack(
                source_material="标题: Anthropic 发布新模型",
                source_url="https://example.com/news",
                source_title="Anthropic 发布新模型",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["relevant_count"], 1)
        self.assertIn("价格变化", result["what_everyone_noticed"])


if __name__ == "__main__":
    unittest.main()
