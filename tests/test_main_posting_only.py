import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main
from scraper import ScrapedItem


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


class PostingPublishRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_slot_retries_when_first_publish_fails(self) -> None:
        bot = MagicMock()
        bot.post_tweet = AsyncMock(side_effect=[None, "https://x.com/pepperfr1ends/status/1"])
        bot.check_rate_limit = AsyncMock(return_value=False)
        conn = MagicMock()
        news_items = [
            ScrapedItem(
                title="First",
                url="https://example.com/1",
                source="AIHOT",
                content_type="ai_hot_take",
            ),
            ScrapedItem(
                title="Second",
                url="https://example.com/2",
                source="AIHOT",
                content_type="ai_hot_take",
            ),
        ]

        with (
            patch.object(main, "get_connection", return_value=conn),
            patch.object(main, "get_today_post_count", return_value=0),
            patch.object(main, "_pick_content_type", return_value="ai_hot_take"),
            patch.object(
                main,
                "build_reaction_pack",
                AsyncMock(return_value={"status": "no_recent_reactions"}),
            ),
            patch.object(
                main,
                "write_tweet",
                AsyncMock(return_value={"tweet": "短判断\n\n补一句", "image_prompt": "image"}),
            ),
            patch.object(main, "is_duplicate", return_value=False),
            patch.object(main, "score_content", AsyncMock(return_value={"total": 60})),
            patch.object(main, "decide_publish", return_value="publish"),
            patch.object(main, "fetch_image_for_item", AsyncMock(return_value="/tmp/fake.jpg")),
            patch.object(main, "insert_post", side_effect=[101, 102]),
            patch.object(main, "mark_post_published") as mark_published,
            patch.object(main, "log_post"),
            patch.object(main.os.path, "exists", return_value=False),
            patch.object(main.asyncio, "sleep", AsyncMock()),
        ):
            published = await main._generate_and_publish_posts(  # noqa: SLF001
                bot=bot,
                slot_name="periodic2h",
                target_count=1,
                news_items=news_items,
                weights={
                    "ai_hot_take": 1.0,
                    "ai_tool_review": 0.0,
                    "startup_cognition": 0.0,
                    "controversy": 0.0,
                    "kol_interaction": 0.0,
                },
            )

        self.assertEqual(published, 1)
        self.assertEqual(bot.post_tweet.await_count, 2)
        mark_published.assert_called_once_with(conn, 102, tweet_url="https://x.com/pepperfr1ends/status/1")


if __name__ == "__main__":
    unittest.main()
