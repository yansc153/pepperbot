import unittest
import sys
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
