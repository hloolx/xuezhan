"""The diagnostic camera must not weaken the ordinary preview's checks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Tools"))
import play_stone_era_preview as preview


class UnitCameraReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = {"camera_review": "units", "run": "TestRun", "included": [], "complete_era": True}
        lines = ["CIVWAR_STONE_ERA_FIXTURE", "CIVWAR_ROCK_TOWER_PILOT team=0", "CIVWAR_ROCK_TOWER_PILOT team=1"]
        self.shots = []
        for team in (0, 1):
            for distance in (1300, 2300, 3400):
                name = f"TestRun_team{team}_distance{distance}.png"
                path = Path(self.temp.name) / name
                path.write_bytes(b"synthetic file fixture")
                self.shots.append({"path": str(path), "sha256": preview.base.sha(path)})
                lines.extend([f"CIVWAR_ART_REVIEW shot={name} team={team} distance={distance}",
                              f"CIVWAR_UNIT_ART_REVIEW shot={name} id=1 unit_team={team}"])
        self.log = "\n".join(lines)

    def summarize(self):
        base_report = {"failures": ["Automated art-review camera unexpectedly activated"]}
        with patch.object(preview.base, "summarize", return_value=base_report):
            return preview.summarize(self.log, self.state, self.shots, 0, False)

    def test_six_expected_tracked_shots_are_accepted_without_visual_approval(self):
        result = self.summarize()
        self.assertEqual(result["failures"], [])
        self.assertFalse(result["visual_reviewed"])

    def test_normal_mode_still_rejects_review_camera(self):
        self.state["camera_review"] = None
        self.assertIn("Automated art-review camera unexpectedly activated", self.summarize()["failures"])

    def test_missing_actual_shot_is_rejected(self):
        Path(self.shots[0]["path"]).unlink()
        self.assertTrue(any("missing or changed" in item for item in self.summarize()["failures"]))

    def test_unexpected_camera_is_not_whitelisted(self):
        self.log += "\nCIVWAR_ART_REVIEW shot=Other.png team=0 distance=1700"
        self.assertTrue(any("incomplete or unexpected" in item for item in self.summarize()["failures"]))

    def test_wrong_team_tracking_is_rejected(self):
        self.log = self.log.replace("id=1 unit_team=1", "id=1 unit_team=0")
        self.assertTrue(any("stated team" in item for item in self.summarize()["failures"]))


if __name__ == "__main__":
    unittest.main()
