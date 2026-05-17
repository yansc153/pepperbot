import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VpsRuntimeScriptTests(unittest.TestCase):
    def test_run_slot_vps_sets_cron_safe_python_path(self) -> None:
        script = (ROOT / "scripts" / "run_slot_vps.sh").read_text(encoding="utf-8")

        self.assertIn('export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"', script)
        self.assertIn("command -v python3", script)
        self.assertIn('"$PYTHON_BIN" src/slot_runner.py --slot "$SLOT"', script)

    def test_run_slot_vps_loads_env_without_shell_evaluating_secrets(self) -> None:
        script = (ROOT / "scripts" / "run_slot_vps.sh").read_text(encoding="utf-8")

        self.assertIn("while IFS='=' read -r name value", script)
        self.assertIn("HEADLESS|LLM_BACKEND|MOONSHOT_API_KEY|TWITTER_COOKIE_FILE", script)
        self.assertNotIn(". /etc/environment", script)


if __name__ == "__main__":
    unittest.main()
