import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main


class MainPostingOnlyTests(unittest.TestCase):
    def test_all_posting_slots_disable_kol_interaction_weight(self) -> None:
        for profile in main.POSTING_SLOT_PROFILES.values():
            self.assertEqual(profile["weights"]["kol_interaction"], 0.0)

    def test_all_posting_slots_publish_two_posts(self) -> None:
        for profile in main.POSTING_SLOT_PROFILES.values():
            self.assertEqual(profile["target_count"], 2)

    def test_scheduler_hours_match_documented_slots(self) -> None:
        self.assertEqual(main.SCHEDULER_HOURS["slot1"], 7)
        self.assertEqual(main.SCHEDULER_HOURS["slot2"], 11)
        self.assertEqual(main.SCHEDULER_HOURS["slot5"], 23)
        self.assertEqual(main.SCHEDULER_HOURS["review"], 0)


if __name__ == "__main__":
    unittest.main()
