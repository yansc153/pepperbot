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

    def test_all_posting_slots_target_count(self) -> None:
        self.assertEqual(main.POSTING_SLOT_PROFILES["periodic2h"]["target_count"], 1)
        for slot_name, profile in main.POSTING_SLOT_PROFILES.items():
            if slot_name == "periodic2h":
                continue
            self.assertEqual(profile["target_count"], 2)

    def test_periodic_cadence_targets_twelve_posts_per_day(self) -> None:
        posts_per_run = main.POSTING_SLOT_PROFILES["periodic2h"]["target_count"]

        self.assertEqual((24 // 2) * posts_per_run, 12)

    def test_scheduler_hours_match_documented_slots(self) -> None:
        self.assertEqual(main.SCHEDULER_HOURS["slot1"], 7)
        self.assertEqual(main.SCHEDULER_HOURS["slot2"], 11)
        self.assertEqual(main.SCHEDULER_HOURS["slot5"], 23)
        self.assertEqual(main.SCHEDULER_HOURS["review"], 0)

    def test_scheduler_runs_review_and_periodic_post_at_midnight(self) -> None:
        due_sessions = main._scheduler_due_sessions(0, "2026-05-17", set())  # noqa: SLF001

        self.assertEqual(
            due_sessions,
            [
                ("review", "2026-05-17_review"),
                ("periodic2h", "2026-05-17_periodic2h_0"),
            ],
        )

    def test_scheduler_keeps_periodic_two_hour_cadence(self) -> None:
        due_sessions = main._scheduler_due_sessions(2, "2026-05-17", set())  # noqa: SLF001

        self.assertEqual(due_sessions, [("periodic2h", "2026-05-17_periodic2h_2")])


if __name__ == "__main__":
    unittest.main()
