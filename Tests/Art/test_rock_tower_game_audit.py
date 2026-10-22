import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("rock_game_audit", Path(__file__).resolve().parents[2] / "Tools/check_rock_tower_game.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    lines = []
    for team in (0, 1):
        lines.append(f"CIVWAR_ROCK_TOWER_FIXTURE_GOLD team={team} before=100.000 after=100.000")
        for slot in (0, 1, 2):
            lines += [f"CIVWAR_ROCK_TOWER_PILOT team={team} slot={slot} components=5",
                      f"CIVWAR_ROCK_TOWER_FIXTURE team={team} slot={slot} result=0"]
    return "\n".join(lines) + "\n"


RELEASE = "CIVWAR_ROCK_TOWER_RELEASE team=0 slot=0 seq=1 pitch=35.00000 stone_visible=0\n"
POSE = "CIVWAR_ROCK_TOWER_POSE team=0 slot=0 seq=1 elapsed=0.160000 pitch=-40.00000 stone_visible=0 muzzle=X=0.000 Y=0.000 Z=0.000 scale=X=1.000 Y=1.000 Z=1.000\n"
NATURAL_BUILD = "CIVWAR_ROCK_TOWER_PILOT team=0 slot=0 components=5 lift_cm=1.500 scale=positive_one approval=controlled_pilot activation=default_runtime production_approved=false\n"
AUTHORITY = "CIVWAR_ROCK_TOWER_AUTHORITY team=0 slot=0 seq=1 sim_time=30.000000 target=9 target_x=600.000000\n"


class RockTowerGameAuditTests(unittest.TestCase):
    def test_no_fire_is_not_cycle_approval(self):
        report = MODULE.audit(fixture())
        self.assertEqual("assembly_only_no_fire_samples", report["status"])
        self.assertFalse(report["local_sample_validation_passed"])

    def test_actual_sample_pass_does_not_claim_authority_or_network(self):
        report = MODULE.audit(fixture() + RELEASE + POSE)
        self.assertTrue(report["local_sample_validation_passed"])
        self.assertEqual(1, report["sample_count"])
        self.assertFalse(report["authority_event_correlation_verified"])
        self.assertFalse(report["network_timing_approved"])
        self.assertFalse(report["both_team_cycles_observed"])

    def test_bad_pitch_scale_visibility_and_gold_fail(self):
        for bad in (POSE.replace("pitch=-40", "pitch=40"), POSE.replace("scale=X=1", "scale=X=-1"),
                    POSE.replace("stone_visible=0", "stone_visible=1")):
            self.assertEqual("failed", MODULE.audit(fixture() + RELEASE + bad)["status"])
        self.assertEqual("failed", MODULE.audit(fixture().replace("after=100", "after=101"))["status"])

    def test_missing_release_and_malformed_telemetry_fail(self):
        self.assertEqual("failed", MODULE.audit(fixture() + POSE)["status"])
        self.assertEqual("failed", MODULE.audit(fixture() + "CIVWAR_ROCK_TOWER_POSE broken\n")["status"])

    def test_incomplete_fixture_fails(self):
        self.assertEqual("failed", MODULE.audit("")["status"])

    def test_actual_authority_order_and_multiplicity(self):
        event = "CIVWAR_ROCK_TOWER_AUTHORITY team=0 slot=0 seq=1 sim_time=30.000000 target=9 target_x=600.000000\n"
        report = MODULE.audit(fixture() + event + RELEASE + POSE)
        self.assertTrue(report["authority_event_correlation_verified"])
        self.assertFalse(report["network_timing_approved"])
        for body in (event + POSE, RELEASE + event + POSE, event + RELEASE + RELEASE + POSE,
                     event.replace("seq=1", "seq=2") + RELEASE + POSE, event + "CIVWAR_ROCK_TOWER_AUTHORITY malformed\n" + RELEASE + POSE):
            self.assertEqual("failed", MODULE.audit(fixture() + body)["status"])

    def test_image_request_requires_actual_pose_and_correct_unique_phase(self):
        shot = "CIVWAR_ROCK_TOWER_IMAGE shot=test.png team=0 slot=0 seq=1 phase=1 elapsed=0.160000 pitch=-40.00000 stone_visible=0\n"
        valid = fixture() + RELEASE + POSE
        self.assertEqual(1, len(MODULE.audit(valid + shot)["image_component_records"]))
        for content in (valid + shot + shot, valid + shot.replace("phase=1", "phase=3"),
                        valid + shot.replace("pitch=-40", "pitch=35"), fixture() + RELEASE + shot):
            self.assertEqual("failed", MODULE.audit(content)["status"])

    def test_natural_build_is_explicit_and_does_not_weaken_default_fixture(self):
        self.assertEqual("failed", MODULE.audit(NATURAL_BUILD)["status"])
        report = MODULE.audit(NATURAL_BUILD, require_fixture=False)
        self.assertEqual("assembly_only_no_fire_samples", report["status"])
        self.assertEqual("natural_build", report["audit_mode"])
        self.assertFalse(report["require_fixture"])
        self.assertEqual(0, report["fixture_line_count"])
        self.assertEqual(0, report["fixture_record_count"])
        self.assertFalse(report["local_sample_validation_passed"])
        self.assertFalse(report["authority_event_correlation_verified"])
        self.assertEqual({}, report["gold_before_after"])

    def test_natural_single_tower_can_correlate_real_samples_without_six_towers(self):
        report = MODULE.audit(NATURAL_BUILD + AUTHORITY + RELEASE + POSE, require_fixture=False)
        self.assertEqual([], report["failures"])
        self.assertEqual([(0, 0)], report["built_team_slots"])
        self.assertTrue(report["local_sample_validation_passed"])
        self.assertTrue(report["authority_event_correlation_verified"])
        self.assertFalse(report["both_team_cycles_observed"])
        self.assertFalse(report["network_timing_approved"])
        self.assertFalse(report["production_approved"])

    def test_natural_rejects_any_fixture_line_even_malformed_or_gold_only(self):
        for extra in (fixture(), "CIVWAR_ROCK_TOWER_FIXTURE broken\n",
                      "CIVWAR_ROCK_TOWER_FIXTURE_GOLD team=0 before=100 after=100\n",
                      "CIVWAR_ROCK_TOWER_FIXTURE_GOLD malformed\n"):
            report = MODULE.audit(NATURAL_BUILD + extra, require_fixture=False)
            self.assertEqual("failed", report["status"])
            self.assertGreater(report["fixture_line_count"], 0)

    def test_natural_requires_actual_valid_built_components(self):
        for content in ("", NATURAL_BUILD.replace("components=5", "components=4"),
                        NATURAL_BUILD.replace("team=0", "team=2"), NATURAL_BUILD.replace("slot=0", "slot=3"),
                        NATURAL_BUILD + "CIVWAR_ROCK_TOWER_PILOT broken\n"):
            self.assertEqual("failed", MODULE.audit(content, require_fixture=False)["status"])

    def test_each_natural_release_pose_and_authority_belongs_to_built_tower(self):
        for content in (NATURAL_BUILD + AUTHORITY.replace("slot=0", "slot=1") + RELEASE + POSE,
                        NATURAL_BUILD + AUTHORITY + RELEASE.replace("slot=0", "slot=1") + POSE,
                        NATURAL_BUILD + AUTHORITY + RELEASE + POSE.replace("slot=0", "slot=1"),
                        AUTHORITY + RELEASE + POSE + NATURAL_BUILD):
            self.assertEqual("failed", MODULE.audit(content, require_fixture=False)["status"])

    def test_natural_authority_is_required_and_order_multiplicity_stay_strict(self):
        for events in (RELEASE + POSE, RELEASE + AUTHORITY + POSE,
                       AUTHORITY + RELEASE + RELEASE + POSE, AUTHORITY + AUTHORITY + RELEASE + POSE,
                       AUTHORITY + POSE, AUTHORITY.replace("seq=1", "seq=2") + RELEASE + POSE):
            report = MODULE.audit(NATURAL_BUILD + events, require_fixture=False)
            self.assertEqual("failed", report["status"])
            self.assertFalse(report["authority_event_correlation_verified"])

    def test_natural_preserves_scale_pitch_visibility_and_elapsed_safety(self):
        for bad in (POSE.replace("pitch=-40", "pitch=40"), POSE.replace("scale=X=1", "scale=X=-1"),
                    POSE.replace("stone_visible=0", "stone_visible=1"), POSE.replace("elapsed=0.160000", "elapsed=3.000000"),
                    POSE + POSE.replace("elapsed=0.160000", "elapsed=0.100000")):
            self.assertEqual("failed", MODULE.audit(NATURAL_BUILD + AUTHORITY + RELEASE + bad, require_fixture=False)["status"])

    def test_natural_release_without_pose_is_not_attack_sample_approval(self):
        report = MODULE.audit(NATURAL_BUILD + AUTHORITY + RELEASE, require_fixture=False)
        self.assertEqual("assembly_only_no_fire_samples", report["status"])
        self.assertFalse(report["local_sample_validation_passed"])
        self.assertEqual(0, report["sample_count"])

    def test_cli_natural_build_switch_writes_explicit_scope_and_zero_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "actual.log"
            output = Path(directory) / "audit.json"
            log.write_text(NATURAL_BUILD, encoding="utf-8")
            with patch("sys.argv", ["check_rock_tower_game.py", "--natural-build", "--log", str(log), "--output", str(output)]), redirect_stdout(io.StringIO()):
                MODULE.main()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("natural_build", report["audit_mode"])
            self.assertEqual(0, report["fixture_line_count"])
            self.assertIn("Naturally built", report["scope"])


if __name__ == "__main__":
    unittest.main()
