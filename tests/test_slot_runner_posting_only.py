import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import slot_runner


class SlotRunnerPostingOnlyTests(unittest.TestCase):
    def test_slot_mapping_has_observe_and_review(self) -> None:
        self.assertEqual(slot_runner.SLOT_TO_SESSION["periodic2h"], "periodic2h")
        self.assertEqual(slot_runner.SLOT_TO_SESSION["slot1"], "slot1")
        self.assertEqual(slot_runner.SLOT_TO_SESSION["slot5"], "slot5")
        self.assertEqual(slot_runner.SLOT_TO_SESSION["observe"], "observe")
        self.assertEqual(slot_runner.SLOT_TO_SESSION["review"], "review")

    def test_legacy_session_names_are_not_used(self) -> None:
        self.assertNotIn("morning", slot_runner.SLOT_TO_SESSION.values())
        self.assertNotIn("noon", slot_runner.SLOT_TO_SESSION.values())
        self.assertNotIn("evening", slot_runner.SLOT_TO_SESSION.values())


if __name__ == "__main__":
    unittest.main()
