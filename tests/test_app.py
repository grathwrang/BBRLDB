import os
import tempfile
import unittest
from unittest import mock

from flask import url_for

from judging import create_judge_record

import app as bot_app
import storage


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        bot_app.app.config["TESTING"] = True
        self.client = bot_app.app.test_client()

        # Create an isolated temp directory for all storage files.
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)

        # Build patched file paths inside the temp directory.
        patched_judging_fp = os.path.join(self._tempdir.name, "judging.json")
        patched_lock_fp = os.path.join(self._tempdir.name, "judging.lock")
        patched_schedule_fp = os.path.join(self._tempdir.name, "schedule.json")
        patched_tournaments_fp = os.path.join(self._tempdir.name, "tournaments.json")
        patched_db_files = {
            wc: os.path.join(self._tempdir.name, f"{wc.lower()}_elo.json")
            for wc in storage.DB_FILES
        }

        # Patch storage module constants so all I/O is sandboxed.
        self._patches = [
            mock.patch.object(storage, "DATA_DIR", self._tempdir.name),
            mock.patch.object(storage, "SCHEDULE_FP", patched_schedule_fp),
            mock.patch.object(storage, "JUDGING_FP", patched_judging_fp),
            mock.patch.object(storage, "JUDGING_LOCK_FP", patched_lock_fp),
            mock.patch.object(storage, "TOURNAMENTS_FP", patched_tournaments_fp),
            mock.patch.object(storage, "DB_FILES", patched_db_files),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        storage.ensure_dirs()

    def test_robot_display_handles_invalid_weight_class(self):
        result = bot_app.robot_display("Unknown", "TestBot")
        self.assertEqual(result["name"], "TestBot")
        self.assertIsNone(result["rating"])
        self.assertEqual(result["wins"], 0)
        self.assertEqual(result["losses"], 0)
        self.assertEqual(result["draws"], 0)
        self.assertEqual(result["ko_wins"], 0)
        self.assertEqual(result["ko_losses"], 0)

    def test_robot_presence_invalid_weight_class_redirects(self):
        response = self.client.post(
            "/robot/presence",
            data={"wc": "Unknown", "name": "TestBot", "present": "1"},
        )
        self.assertEqual(response.status_code, 302)
        with bot_app.app.test_request_context():
            expected = url_for("index", wc=bot_app.WEIGHT_CLASSES[0], _external=False)
        self.assertEqual(response.headers.get("Location"), expected)

    def test_judge_state_api_includes_meta_version(self):
        response = self.client.get("/api/judge/state")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertIn("meta", payload)
        self.assertIn("version", payload["meta"])
        self.assertIsInstance(payload["meta"]["version"], int)

    def test_judge_state_version_only_changes_when_mutated(self):
        first = self.client.get("/api/judge/state").get_json()
        base_version = first["meta"]["version"]

        second = self.client.get("/api/judge/state").get_json()
        self.assertEqual(second["meta"]["version"], base_version)

        def mutate(state):
            counter = int(state.get("_test_counter", 0))
            state["_test_counter"] = counter + 1
            return state

        storage.update_judging_state(mutate)

        third = self.client.get("/api/judge/state").get_json()
        self.assertGreater(third["meta"]["version"], base_version)

    def test_update_judging_state_noop_does_not_bump_version(self):
        original = self.client.get("/api/judge/state").get_json()
        original_version = original["meta"]["version"]

        storage.update_judging_state(lambda s: s)

        after = self.client.get("/api/judge/state").get_json()
        self.assertEqual(after["meta"]["version"], original_version)

    def test_public_schedule_empty(self):
        # Ensure schedule file is empty
        storage.save_schedule({"list": []})
        resp = self.client.get("/SchedulePublic")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No fights are scheduled yet", resp.data)

    def test_finalize_current_match_updates_elo_from_judges(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        red = "Alpha"
        white = "Beta"

        db = storage.load_db(wc)
        db["robots"][red] = {"rating": 1000, "matches": []}
        db["robots"][white] = {"rating": 1000, "matches": []}
        storage.save_db(wc, db)

        schedule_card = {"weight_class": wc, "red": red, "white": white}
        schedule_data = {"list": [dict(schedule_card)]}
        storage.save_schedule(schedule_data)

        judges = {
            "1": create_judge_record(
                1,
                {"damage": 7, "aggression": 4, "control": 5},
                judge_name="Judge 1",
            ),
            "2": create_judge_record(
                2,
                {"damage": 6, "aggression": 3, "control": 4},
                judge_name="Judge 2",
            ),
            "3": create_judge_record(
                3,
                {"damage": 1, "aggression": 1, "control": 1},
                judge_name="Judge 3",
            ),
        }

        match_state = {
            "match_id": "test-match",
            "weight_class": wc,
            "red": red,
            "white": white,
            "judges": judges,
        }

        state = {"current": match_state, "history": [], "_meta": {"version": 1, "updated_at": 0}}

        updated_state, updated_schedule = bot_app.finalize_current_match(state, schedule_data)

        self.assertIsNone(updated_state.get("current"))
        self.assertEqual(updated_schedule.get("list"), [])

        db_after = storage.load_db(wc)
        history = db_after.get("history", [])
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertTrue(entry["result"].startswith("Red wins JD"))
        self.assertEqual(db_after["robots"][red]["rating"], 1016)
        self.assertEqual(db_after["robots"][white]["rating"], 984)
        self.assertEqual(db_after["robots"][red]["matches"][0]["match_id"], entry["match_id"])
        self.assertEqual(entry["change_red"], 16)
        self.assertEqual(entry["change_white"], -16)

    def test_submit_match_recovers_missing_next_match_id(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        red = "Gamma"
        white = "Delta"

        db = storage.load_db(wc)
        db["robots"][red] = {"rating": 1000, "matches": []}
        db["robots"][white] = {"rating": 1000, "matches": []}
        db["history"] = [
            {"match_id": 2},
            {"match_id": "not-a-number"},
            {"match_id": 7},
        ]
        numeric_existing = []
        for entry in db["history"]:
            try:
                numeric_existing.append(int(entry.get("match_id")))
            except (TypeError, ValueError):
                continue
        existing_max = max(numeric_existing)
        db.pop("next_match_id", None)
        storage.save_db(wc, db)

        response = self.client.post(
            "/submit_match",
            data={"wc": wc, "red": red, "white": white, "result": "Red wins JD"},
        )
        self.assertEqual(response.status_code, 302)

        updated_db = storage.load_db(wc)
        history = updated_db.get("history", [])
        self.assertEqual(len(history), 4)
        new_entry = history[-1]
        new_id = new_entry.get("match_id")
        self.assertIsInstance(new_id, int)
        self.assertGreater(new_id, existing_max)
        self.assertEqual(updated_db.get("next_match_id"), new_id + 1)
        self.assertEqual(updated_db["robots"][red]["matches"][0]["match_id"], new_id)

    def test_tournament_creation_and_progression(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        db = storage.load_db(wc)
        db["robots"] = {
            "Atlas": {"present": True},
            "Blazer": {"present": True},
            "Cyclone": {"present": True},
            "Dynamo": {"present": True},
        }
        storage.save_db(wc, db)

        create_resp = self.client.post(
            "/tournaments/summer-showdown",
            json={
                "name": "Summer Showdown",
                "weight_class": wc,
                "elimination": "single",
                "max_robots": 4,
                "use_present": True,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        payload = create_resp.get_json()
        self.assertEqual(payload["metadata"]["name"], "Summer Showdown")
        self.assertEqual(set(payload["metadata"]["robots"]), {"Atlas", "Blazer", "Cyclone", "Dynamo"})

        listing = self.client.get("/tournaments").get_json()
        self.assertEqual(len(listing), 1)
        first_match_id = payload["bracket"]["order"]["winners"][0][0]
        first_match = payload["bracket"]["matches"][first_match_id]
        chosen_winner = first_match["red"]

        advance_resp = self.client.post(
            f"/tournaments/summer-showdown/matches/{first_match_id}",
            json={"winner": chosen_winner},
        )
        self.assertEqual(advance_resp.status_code, 200)
        updated = advance_resp.get_json()
        self.assertEqual(
            updated["bracket"]["matches"][first_match_id]["winner"],
            chosen_winner,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
