import copy
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower_render", ROOT / "Tools/rock_tower_render.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def context():
    return {"platforms": [{"mount_ue_cm": [100, 200, 150], "upper_local_translation_cm": [0, 0, 1.5]}],
            "anchors": {"ArmPivot": {"translation_cm": [-4, 0, 51]}, "release_point": {"translation_cm": [3.5, 0, 57]}}}


class RockTowerRenderTests(unittest.TestCase):
    def test_import_has_no_unreal_or_process_execution_dependency(self):
        self.assertNotIn("unreal", MODULE.__dict__)
        self.assertNotIn("subprocess", MODULE.__dict__)

    def test_twelve_shots_cover_both_real_yaws_and_original_cloth_control(self):
        shots = MODULE.SHOTS
        self.assertEqual(len(shots), 12)
        self.assertEqual(len({shot["label"] for shot in shots}), 12)
        self.assertEqual({shot["team"] for shot in shots}, {0, 1})
        self.assertEqual({shot["slot"] for shot in shots if shot["crop"] == "fit"}, {0, 1, 2})
        self.assertEqual(len([shot for shot in shots if shot["crop"] == "mechanism"]), 4)
        self.assertTrue(any(shot.get("original_cloth") for shot in shots))

    def test_yaw_180_rotates_not_mirrors(self):
        first = MODULE.rotate((1, 2, 3), yaw=180)
        self.assertAlmostEqual(first[0], -1)
        self.assertAlmostEqual(first[1], -2)
        self.assertAlmostEqual(first[2], 3)
        forward = MODULE.rotate((1, 0, 0), yaw=180)
        right = MODULE.rotate((0, 1, 0), yaw=180)
        self.assertAlmostEqual(forward[0] * right[1] - forward[1] * right[0], 1)

    def test_positive_pitch_raises_forward_per_installed_unreal_formula(self):
        actual = MODULE.rotate((1, 0, 0), pitch=35)
        self.assertAlmostEqual(actual[0], math.cos(math.radians(35)))
        self.assertAlmostEqual(actual[2], math.sin(math.radians(35)))

    def test_adapter_does_not_receive_upper_lift(self):
        source = context()
        self.assertEqual(MODULE.component_point(source, 0, "Adapter_front_negative_y", (0, 0, 0), 0, 35), [100, 200, 150])
        self.assertEqual(MODULE.component_point(source, 0, "Frame", (0, 0, 0), 0, 35), [100, 200, 151.5])
        self.assertEqual(MODULE.component_point(source, 0, "Arm", (0, 0, 0), 0, 35), [96, 200, 202.5])

    def test_stone_origin_tracks_actual_arm_release_basis(self):
        source = context()
        for yaw in (0, 180):
            for pitch in (-40, 12.5, 35, 65):
                origin = MODULE.component_point(source, 0, "Stone", (0, 0, 0), yaw, pitch)
                release = MODULE.component_point(source, 0, "Arm", (3.5, 0, 57), yaw, pitch)
                self.assertLess(math.dist(origin, release), 1e-10)

    def test_unknown_component_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.component_point(context(), 0, "invented", (0, 0, 0), 0, 0)

    def test_camera_sphere_fits_all_bounds_without_clipping(self):
        bounds = {"min": [-400, -300, -31], "max": [400, 300, 430]}
        result = MODULE.fit_camera(bounds, (1.2, -1.5, .85))
        angle = math.asin(result["fit_sphere_radius_cm"] / result["distance_cm"])
        self.assertLess(angle, math.radians(result["fov"] / 2))
        for corner in MODULE.bounds_corners(bounds):
            self.assertLessEqual(math.dist(corner, result["target"]), result["fit_sphere_radius_cm"] + 1e-9)
        with self.assertRaises(ValueError):
            MODULE.fit_camera(bounds, (0, 0, 0))
        with self.assertRaises(ValueError):
            MODULE.fit_camera({"min": [0, 0, 0], "max": [0, 0, 0]}, (1, 0, 0))

    def test_fresh_gate_rejects_initial_and_forged_mesh_mapping(self):
        plan = {"destination": "isolated", "source_evidence": [], "entries": [{"config_key": str(index)} for index in range(7)]}
        files = [{"asset_path": "mesh" + str(index), "class_name": "StaticMesh"} for index in range(7)]
        report = {"status": "rock_tower_fresh_reopen_structural_checks_passed", "dry_run": False,
                  "structural_checks_passed": True, "validated_in_fresh_process": True,
                  "initial_process_id": 1, "validation_process_id": 2,
                  "destination": "isolated", "source_files": [], "package_files": files,
                  "disk_dependency_validation": {"status": "passed", "files": files},
                  "meshes": {str(index): "mesh" + str(index) for index in range(7)}}
        MODULE.check_fresh(report, plan)
        for key, value in (("status", "rock_tower_initial_saved_requires_fresh_reopen"), ("validation_process_id", 1),
                           ("validated_in_fresh_process", False), ("dry_run", True), ("source_files", ["changed"])):
            with self.assertRaises(ValueError):
                MODULE.check_fresh(dict(report, **{key: value}), plan)
        changed = copy.deepcopy(report)
        changed["meshes"]["0"] = "/Game/Other/Wrong.Wrong"
        with self.assertRaises(ValueError):
            MODULE.check_fresh(changed, plan)

    def test_tick_after_terminal_state_cannot_queue_more_work(self):
        review = object.__new__(MODULE.RockReview)
        review.finished = True
        review.tick(.1)
        with self.assertRaises(ValueError):
            review.request_dump()

    def test_tick_cannot_reenter_dispatch(self):
        review = object.__new__(MODULE.RockReview)
        review.finished, review.in_tick = False, False
        calls = []

        def advance(delta):
            calls.append(delta)
            review.tick(delta)

        review.advance = advance
        review.tick(.1)
        self.assertEqual(calls, [.1])
        self.assertFalse(review.in_tick)

    def test_dispatch_deadline_starts_after_blocking_api_and_checks_are_recorded_first(self):
        review = object.__new__(MODULE.RockReview)
        review.args = SimpleNamespace(output=Path("not_created"), size=512)
        review.shot = {"label": "test"}
        review.actual = {"actual_basis_passed": True}
        review.camera, review.report = object(), {}
        task = SimpleNamespace(is_valid_task=lambda: True)

        def take(*args, **kwargs):
            self.assertEqual(review.stage, "screenshot_dispatch")
            self.assertEqual(review.report["capture_attempts"][0]["actual_check"], review.actual)
            self.assertEqual(kwargs["delay"], 0.0)
            return task

        review.level_editor = SimpleNamespace(editor_invalidate_viewports=Mock())
        review.unreal = SimpleNamespace(SystemLibrary=SimpleNamespace(get_frame_count=lambda: 100),
                                        AutomationLibrary=SimpleNamespace(take_high_res_screenshot=take), log=lambda value: None)
        with patch.object(MODULE.time, "monotonic", side_effect=[10.0, 45.0]):
            review.dispatch_capture()
        self.assertEqual(review.phase_started, 45.0)
        self.assertEqual(review.stage, "screenshot")
        self.assertEqual(review.report["capture_attempts"][0]["synchronous_dispatch_seconds"], 35.0)
        self.assertEqual(review.report["capture_attempts"][0]["post_dispatch_timeout_seconds"], 20)
        review.level_editor.editor_invalidate_viewports.assert_called_once()

    def test_actual_saved_fresh_inputs_remain_frozen(self):
        fresh = MODULE.rock.DELIVERY / "ue_fresh_01.json"
        if not fresh.is_file():
            self.skipTest("Actual UE fresh report not available on this machine")
        data = MODULE.input_context(fresh)
        self.assertEqual(len(data["rock"]["meshes"]), 7)
        self.assertEqual(len(data["base_textures"]), 3)
        self.assertEqual(len(data["platforms"]), 3)


if __name__ == "__main__":
    unittest.main()
