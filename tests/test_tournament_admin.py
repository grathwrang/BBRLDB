import os
import tempfile
import unittest
from unittest import mock

import app as bot_app
import storage


class TournamentAdminTestCase(unittest.TestCase):
    def setUp(self):
        bot_app.app.config["TESTING"] = True
        self.client = bot_app.app.test_client()

        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)

        patched_judging_fp = os.path.join(self._tempdir.name, "judging.json")
        patched_lock_fp = os.path.join(self._tempdir.name, "judging.lock")
        patched_schedule_fp = os.path.join(self._tempdir.name, "schedule.json")
        patched_tournaments_fp = os.path.join(self._tempdir.name, "tournaments.json")
        patched_db_files = {
            wc: os.path.join(self._tempdir.name, f"{wc.lower()}_elo.json")
            for wc in storage.DB_FILES
        }

        self._patches = [
            mock.patch.object(storage, "DATA_DIR", self._tempdir.name),
            mock.patch.object(storage, "SCHEDULE_FP", patched_schedule_fp),
            mock.patch.object(storage, "JUDGING_FP", patched_judging_fp),
            mock.patch.object(storage, "JUDGING_LOCK_FP", patched_lock_fp),
            mock.patch.object(storage, "TOURNAMENTS_FP", patched_tournaments_fp),
            mock.patch.object(storage, "DB_FILES", patched_db_files),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        storage.ensure_dirs()

    def _create_robot(self, wc, name, *, present=False):
        db = storage.load_db(wc)
        robots = db.setdefault("robots", {})
        robots[name] = {"rating": 1000, "matches": [], "present": present}
        storage.save_db(wc, db)

    def test_admin_page_lists_tournaments(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        self._create_robot(wc, "Alpha", present=True)
        self._create_robot(wc, "Beta", present=True)

        storage.save_tournaments(
            {
                "tournaments": [
                    {
                        "id": "test",
                        "name": "Spring Invitational",
                        "weight_classes": [wc],
                        "elimination": "single",
                        "robot_cap": 16,
                        "entrants": ["Alpha", "Beta"],
                        "matches": [
                            {
                                "id": "m1",
                                "round": "1",
                                "red": "Alpha",
                                "white": "Beta",
                                "winner": None,
                            }
                        ],
                    }
                ]
            }
        )

        response = self.client.get("/tournaments/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Spring Invitational", response.data)
        self.assertIn(b"Alpha", response.data)
        self.assertIn(b"Beta", response.data)

    def test_create_tournament_persists(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        self._create_robot(wc, "Gamma", present=True)

        response = self.client.post(
            "/tournaments/admin/create",
            data={
                "name": "Autumn Open",
                "weight_classes": [wc],
                "elimination": "double",
                "robot_cap": "24",
                "entrants": ["Gamma"],
            },
        )

        self.assertEqual(response.status_code, 302)
        tournaments = storage.load_tournaments().get("tournaments", [])
        self.assertEqual(len(tournaments), 1)
        created = tournaments[0]
        self.assertEqual(created["name"], "Autumn Open")
        self.assertEqual(created["elimination"], "double")
        self.assertEqual(created["weight_classes"], [wc])
        self.assertEqual(created["robot_cap"], 24)
        self.assertEqual(created["entrants"], ["Gamma"])

    def test_update_tournament_sets_winner(self):
        wc = bot_app.WEIGHT_CLASSES[0]
        storage.save_tournaments(
            {
                "tournaments": [
                    {
                        "id": "bracket-1",
                        "name": "Winter Finals",
                        "weight_classes": [wc],
                        "elimination": "single",
                        "robot_cap": None,
                        "entrants": ["Alpha", "Beta"],
                        "matches": [
                            {
                                "id": "match-1",
                                "round": "1",
                                "red": "Alpha",
                                "white": "Beta",
                                "winner": None,
                            }
                        ],
                    }
                ]
            }
        )

        response = self.client.post(
            "/tournaments/admin/update",
            data={
                "tournament_id": "bracket-1",
                "action": "set_winner",
                "match_id": "match-1",
                "winner": "Alpha",
            },
        )

        self.assertEqual(response.status_code, 302)
        tournaments = storage.load_tournaments().get("tournaments", [])
        self.assertEqual(tournaments[0]["matches"][0]["winner"], "Alpha")

