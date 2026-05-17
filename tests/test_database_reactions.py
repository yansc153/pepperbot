import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import database


class DatabaseReactionTests(unittest.TestCase):
    def test_reaction_observations_insert_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "pepperbot.db"
            database.init_database(db_path)
            conn = database.get_connection(db_path)
            database.insert_reaction_observation(
                conn=conn,
                kol_handle="@foo",
                post_url="https://x.com/foo/status/1",
                post_text="这次真正该看的不是参数 是成本",
                posted_at="2099-01-01T00:00:00+00:00",
                likes=10,
                retweets=2,
                replies=1,
            )

            rows = database.get_recent_reaction_observations(conn, since_hours=999999, limit=10)
            conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kol_handle"], "@foo")
        self.assertEqual(rows[0]["likes"], 10)


if __name__ == "__main__":
    unittest.main()
