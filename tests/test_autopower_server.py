import json
import tempfile
import unittest
from pathlib import Path

from src.autopower_server import AppState, create_schedule, update_schedule


class AutoPowerServerTests(unittest.TestCase):
    def test_state_loads_default_schedules_when_file_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))

            data = state.load()

            self.assertEqual(len(data["schedules"]), 2)
            self.assertEqual(data["schedules"][0]["operation"], "wake")
            self.assertEqual(data["schedules"][0]["hour"], 15)
            self.assertEqual(data["schedules"][1]["operation"], "shutdown")
            self.assertEqual(data["schedules"][1]["hour"], 20)

    def test_create_schedule_persists_valid_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))

            created = create_schedule(
                state,
                {"enabled": True, "operation": "shutdown", "days": "custom", "weekdays": [4], "hour": 14, "minute": 30},
            )
            data = json.loads((Path(temp_dir) / "schedules.json").read_text())

            self.assertEqual(created["operation"], "shutdown")
            self.assertEqual(data["schedules"][-1]["hour"], 14)
            self.assertTrue(data["schedules"][-1]["id"])

    def test_update_schedule_replaces_existing_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))
            existing = create_schedule(state, {"enabled": True, "operation": "wake", "days": "daily", "hour": 9, "minute": 0})

            updated = update_schedule(state, existing["id"], {"enabled": False, "operation": "wake", "days": "daily", "hour": 10, "minute": 15})

            self.assertFalse(updated["enabled"])
            self.assertEqual(updated["hour"], 10)
            self.assertEqual(updated["minute"], 15)


if __name__ == "__main__":
    unittest.main()
