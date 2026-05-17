import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import learner


class _DummyConn:
    def __init__(self, execute_result=None):
        self.execute_result = execute_result

    def close(self) -> None:
        return None

    def execute(self, _query: str, _params=None):  # pragma: no cover - simple DB shim
        class _Cursor:
            def fetchone(self_inner):
                return self.execute_result

        return _Cursor()


class _FakePostRow(dict):
    @property
    def __getitem__(self, key):
        return super().__getitem__(key)


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

    async def test_analyze_own_posts_persists_learning_and_weights(self) -> None:
        call_count = {"insert_learning_log": 0, "save_strategy_weights": 0, "weights": {}}
        posts = [
            {
                "id": 1,
                "content_type": "ai_hot_take",
                "content": "A",
                "likes": 30,
                "retweets": 6,
                "replies": 5,
                "impressions": 140,
                "score_total": 82,
                "published_at": "2026-05-17T07:00:00",
            },
            {
                "id": 2,
                "content_type": "startup_cognition",
                "content": "B",
                "likes": 2,
                "retweets": 1,
                "replies": 0,
                "impressions": 30,
                "score_total": 51,
                "published_at": "2026-05-17T08:00:00",
            },
            {
                "id": 3,
                "content_type": "ai_tool_review",
                "content": "C",
                "likes": 9,
                "retweets": 0,
                "replies": 2,
                "impressions": 60,
                "score_total": 67,
                "published_at": "2026-05-17T09:00:00",
            },
            {
                "id": 4,
                "content_type": "ai_hot_take",
                "content": "D",
                "likes": 14,
                "retweets": 2,
                "replies": 1,
                "impressions": 70,
                "score_total": 73,
                "published_at": "2026-05-17T10:00:00",
            },
        ]

        fake_analysis = {
            "status": "ok",
            "best_post_id": 1,
            "worst_post_id": 2,
            "winning_patterns": ["先给判断"],
            "losing_patterns": ["过分模板化"],
            "next_writing_hypotheses": ["增加反例对照"],
            "human_calibration_notes": ["少用“妥妥的”"],
            "review_summary": "立场+细节更容易拉住停留",
        }

        with (
            patch.object(learner, "get_connection", return_value=_DummyConn()),
            patch.object(learner, "get_recent_posts", return_value=posts),
            patch.object(learner, "call_claude_json", return_value=fake_analysis),
            patch.object(
                learner,
                "insert_learning_log",
                side_effect=lambda **kwargs: call_count.__setitem__(
                    "insert_learning_log",
                    call_count["insert_learning_log"] + 1,
                ) or 1,
            ),
            patch.object(
                learner,
                "save_strategy_weights",
                side_effect=lambda _conn, weights, reason="": (
                    call_count.__setitem__("save_strategy_weights", call_count["save_strategy_weights"] + 1),
                    call_count.__setitem__("weights", dict(weights)),
                    None,
                )[-1],
            ),
        ):
            result = await learner.analyze_own_posts()

        self.assertEqual(call_count["insert_learning_log"], 1)
        self.assertEqual(call_count["save_strategy_weights"], 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["best_post_id"], 1)
        self.assertEqual(result["worst_post_id"], 2)
        self.assertIn("立场+细节", result["review_summary"])

    def test_get_latest_review_learning_returns_default_without_rows(self) -> None:
        with patch.object(
            learner,
            "get_connection",
            return_value=_DummyConn(execute_result=None),
        ):
            result = learner.get_latest_review_learning()

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["winning_patterns"], [])
        self.assertEqual(result["source_post_id"], None)
        self.assertEqual(result["applied_at"], None)

    def test_get_latest_review_learning_parses_strategy_context(self) -> None:
        conn = _DummyConn(
            execute_result={
                "strategy_adjustment": "{\"losing_patterns\": [\"过于口语化\"], \"next_writing_hypotheses\": [\"增加证据\"], \"human_calibration_notes\": [\"更省句号\"], \"review_summary\": \"更短的结尾更好\", \"weights\": {\"ai_hot_take\": 0.3, \"ai_tool_review\": 0.2, \"startup_cognition\": 0.3, \"controversy\": 0.2, \"kol_interaction\": 0.0}}",
                "techniques_extracted": "[\"先给观点\", \"留数字\" ]",
                "applied_at": "2026-05-17 07:00:00",
                "source_post_id": 11,
            }
        )
        with patch.object(learner, "get_connection", return_value=conn):
            result = learner.get_latest_review_learning()

        self.assertEqual(result["status"], "ok")
        self.assertIn("先给观点", result["winning_patterns"])
        self.assertEqual(result["losing_patterns"], ["过于口语化"])
        self.assertEqual(result["strategy_adjustment"]["review_summary"], "更短的结尾更好")
        self.assertEqual(result["source_post_id"], 11)


if __name__ == "__main__":
    unittest.main()
