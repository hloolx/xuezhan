import copy
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("socket_fit", ROOT / "Tools/Unreal/fit_stoneaxe_socket.py")
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


def identity():
    return FIT.compose([0, 0, 0], [0, 0, 0, 1], [1, 1, 1])


def rotation(axis, degrees):
    radians = math.radians(degrees) / 2
    length = math.sqrt(sum(value * value for value in axis))
    return [value / length * math.sin(radians) for value in axis] + [math.cos(radians)]


def calibration_fixture():
    points = [[.01, .02, -.2], [0, .01, .4], [.02, -.01, .1], [.2, .03, .35]]
    names = ["handle_tail", "handle_top", "grip_center", "axe_edge_end"]
    calibration = {"schema_version": 1, "units": "metres", "coordinate_system": "Blender right-handed +X forward +Z up",
                   "matrix_convention": "4x4 row arrays representing column-vector transforms; translation in last column",
                   "local_vertices_m": points, "parts": [{"object": "axe", "vertex_start": 0, "vertex_count": len(points)}],
                   "markers": {name: {"local_position_m": point, "source_evaluated_vertices": [{"object": "axe", "vertex": index}]} for index, (name, point) in enumerate(zip(names, points))}, "poses": {}}
    for index, (name, (clip, sample_time)) in enumerate(FIT.POSES.items()):
        transform = FIT.compose([.2 * index, -.1, .8], rotation([1, 2, 3], 30 * index), [1, 1, 1])
        calibration["poses"][name] = {"clip": clip, "time_seconds": sample_time, "weapon_rigid_world_matrix": transform, "weapon_world_scale": [.82, .82, .82],
                                      "world_positions_m": {marker_name: FIT.transform_point(transform, point) for marker_name, point in zip(names, points)}}
    return calibration


def report_fixture(manifest_path):
    destination = "/Game/ArtPilot/StoneAxeRig/h0123456789abcdef"
    settings = {"force_front_x_axis": False, "scale": 1.0}
    report = {"manifest": str(manifest_path), "destination": destination, "settings": settings, "dry_run": False,
              "status": "isolated_import_fresh_reopen_structural_review_only", "result": {
                  "structural_checks_passed": True, "warnings": [], "body": destination + "/SK_StoneAxe_Pilot.SK_StoneAxe_Pilot",
                  "absolute_motion_validation": {"status": "passed", "frames": 323, "reference_and_each_clip_checked": True,
                                                   "source": {"path": "physical_motion_reference.json", "sha256": "fixture"}},
                  "disk_dependency_validation": {"status": "passed", "validated_in_fresh_process": True, "initial_process_id": 123,
                                                 "validation_process_id": 456, "prior_import_report": "initial_import.json", "files": [{"class_name": "Skeleton"}]},
                  "weapon": {"path": destination + "/Weapon/SM_StoneAxe_Fitted.SM_StoneAxe_Fitted"},
                  "clips": [{"clip": clip, "path": destination + "/Animations/AN_StoneAxe_" + clip, "same_skeleton": True} for clip in ("Idle", "Move", "Attack", "Hit", "Death")]}}
    return report, settings, destination


class SocketMathTests(unittest.TestCase):
    def test_axis_conversion_uses_y_reflection_and_metres_to_cm_once(self):
        self.assertEqual([100, -200, 300], FIT.blender_point_to_ue([1, 2, 3]))
        source = FIT.compose([.5, .2, 1.3], rotation([1, 2, 3], 37), [1, 1, 1])
        point = [.2, -.3, .4]
        actual = FIT.transform_point(FIT.blender_transform_to_ue(source), FIT.blender_point_to_ue(point))
        expected = FIT.blender_point_to_ue(FIT.transform_point(source, point))
        self.assertLess(FIT.distance(actual, expected), 1e-10)
        self.assertAlmostEqual(1, FIT.decompose(FIT.blender_transform_to_ue(source))["scale"][0])

    def test_scale_baked_weapon_is_not_multiplied_by_point82_again(self):
        reference = FIT.compose([.5, -.2, .9], rotation([0, 1, 0], 50), [1, 1, 1])
        for inherited_scale in (1.5, 150):
            hand = FIT.compose([50, 20, 90], rotation([1, 1, 0], 20), [inherited_scale] * 3)
            fitted = FIT.fit_socket(hand, reference)
            for value in fitted["scale"]:
                self.assertAlmostEqual(1 / inherited_scale, value)
            local = FIT.compose(fitted["translation_cm"], fitted["rotation_xyzw"], fitted["scale"])
            self.assertLess(FIT.matrix_error(FIT.multiply(hand, local), FIT.blender_transform_to_ue(reference)), 1e-10)

    def test_random_positive_trs_roundtrips_and_inverts(self):
        generator = random.Random(73)
        for index in range(40):
            source = FIT.compose([generator.uniform(-100, 100) for axis in range(3)], rotation([generator.random() for axis in range(3)], generator.uniform(-360, 360)), [generator.uniform(.1, 3) for axis in range(3)])
            decomposed = FIT.decompose(source)
            rebuilt = FIT.compose(decomposed["translation_cm"], decomposed["rotation_xyzw"], decomposed["scale"])
            self.assertLess(FIT.matrix_error(source, rebuilt), 1e-10)
            self.assertLess(FIT.matrix_error(FIT.multiply(source, FIT.inverse(source)), identity()), 1e-10)

    def test_half_turn_each_axis_quaternion_branch(self):
        for axis in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
            source = FIT.compose([0, 0, 0], rotation(axis, 180), [1, 1, 1])
            parts = FIT.decompose(source)
            self.assertLess(FIT.matrix_error(source, FIT.compose(parts["translation_cm"], parts["rotation_xyzw"], parts["scale"])), 1e-10)

    def test_reject_negative_reflection_shear_singular_and_nonfinite(self):
        reflected, sheared, singular = identity(), identity(), identity()
        reflected[0][0] = -1
        sheared[0][1] = .1
        singular[0][0] = 0
        for transform in (reflected, sheared, singular):
            with self.assertRaises(ValueError):
                FIT.decompose(transform)
        with self.assertRaises(ValueError):
            FIT.compose([0, 0, 0], [0, 0, 0, 1], [1, -1, 1])
        with self.assertRaises(ValueError):
            FIT.blender_point_to_ue([float("nan"), 0, 0])
        with self.assertRaises(ValueError):
            FIT.inverse(singular)

    def test_vertex_matching_allows_seams_and_reordering_not_wrong_axis_or_scale(self):
        expected = [[0, 1, 0], [2, 0, 3], [-1, .5, .3]]
        actual = [expected[2], expected[0], expected[1], expected[2]]
        check, mapping = FIT.compare_vertices(actual, expected)
        self.assertTrue(check["passed"])
        self.assertEqual([expected[index] for index in range(3)], [actual[index] for index in mapping])
        for incorrect in ([[point[0], -point[1], point[2]] for point in actual], [[value * .82 for value in point] for point in actual], actual[:2]):
            self.assertFalse(FIT.compare_vertices(incorrect, expected)[0]["passed"])

    def test_calibration_independent_markers_reference_idle_contact_death(self):
        calibration = calibration_fixture()
        check = FIT.calibration_check(calibration)
        self.assertTrue(check["passed"])
        self.assertEqual(4, len(check["marker_vertex_indices"]))
        self.assertLess(check["maximum_source_marker_error_cm"], 1e-10)
        for name in FIT.POSES:
            corrupted = copy.deepcopy(calibration)
            corrupted["poses"][name]["world_positions_m"]["grip_center"][0] += .001
            with self.assertRaises(ValueError):
                FIT.calibration_check(corrupted)

    def test_calibration_rejects_contact_offset_double_scale_and_unbaked_matrix(self):
        calibration = calibration_fixture()
        modified = copy.deepcopy(calibration)
        modified["poses"]["attack_contact"]["time_seconds"] = 22 / 60
        with self.assertRaises(ValueError):
            FIT.calibration_check(modified)
        modified = copy.deepcopy(calibration)
        for point in modified["local_vertices_m"]:
            point[:] = [value * .82 for value in point]
        with self.assertRaises(ValueError):
            FIT.calibration_check(modified)
        modified = copy.deepcopy(calibration)
        modified["poses"]["reference"]["weapon_rigid_world_matrix"][0][0] *= .82
        with self.assertRaises(ValueError):
            FIT.calibration_check(modified)

    def test_one_socket_reproduces_multiple_hand_poses(self):
        local = FIT.compose([2, -3, 4], rotation([1, 2, 3], 20), [2 / 3] * 3)
        markers = {"tail": [1, 2, -30], "edge": [10, -2, 40]}
        for degrees in (0, 15, 75, 170):
            hand = FIT.compose([10, -15, 100], rotation([1, 0, 1], degrees), [1.5] * 3)
            world = FIT.multiply(hand, local)
            expected = {name: FIT.transform_point(world, point) for name, point in markers.items()}
            sample = {"world_positions_m": {name: [point[0] / 100, -point[1] / 100, point[2] / 100] for name, point in expected.items()}}
            self.assertLess(max(FIT.marker_errors(markers, world, sample).values()), 1e-10)

    def test_report_requires_real_structural_pass_and_exact_isolated_lineage(self):
        path = ROOT / "example/delivery_manifest.json"
        report, settings, destination = report_fixture(path)
        FIT.validate_import_report(report, path, settings, destination)
        variants = []
        for key, value in (("dry_run", True), ("status", "failed"), ("destination", "/Game/Units"), ("manifest", str(path.with_name("other.json")))):
            changed = copy.deepcopy(report)
            changed[key] = value
            variants.append(changed)
        changed = copy.deepcopy(report)
        changed["result"]["structural_checks_passed"] = False
        variants.append(changed)
        changed = copy.deepcopy(report)
        changed["result"]["weapon"]["path"] = "/Game/Production/Weapon"
        variants.append(changed)
        changed = copy.deepcopy(report)
        changed["result"]["clips"][0]["same_skeleton"] = False
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(ValueError):
                FIT.validate_import_report(changed, path, settings, destination)

    def test_failed_blender_roundtrip_is_rejected_before_ue_or_report_read(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "delivery_manifest.json"
            manifest.write_text(json.dumps({"blender_fbx_roundtrip_passed": False}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "round trip must pass"):
                FIT.read_inputs(manifest, Path(directory) / "not_created.json")

    def test_in_memory_import_success_is_not_a_persistence_pass(self):
        path = ROOT / "example/delivery_manifest.json"
        report, settings, destination = report_fixture(path)
        variants = [{}, {"status": "passed", "validated_in_fresh_process": False}]
        for key, value in (("status", "failed"), ("initial_process_id", 456), ("validation_process_id", None), ("files", []), ("prior_import_report", "")):
            dependency = copy.deepcopy(report["result"]["disk_dependency_validation"])
            dependency[key] = value
            variants.append(dependency)
        for dependency in variants:
            changed = copy.deepcopy(report)
            changed["result"]["disk_dependency_validation"] = dependency
            with self.assertRaises(ValueError):
                FIT.validate_import_report(changed, path, settings, destination)

    def test_changed_file_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text("original", encoding="utf-8")
            record = {"path": str(path), "sha256": FIT.digest(path)}
            self.assertEqual(path.resolve(), FIT.verified_record(record))
            path.write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                FIT.verified_record(record)

    def test_reference_only_or_incomplete_animation_scale_validation_is_rejected(self):
        path = ROOT / "example/delivery_manifest.json"
        report, settings, destination = report_fixture(path)
        variants = [{}]
        for key, value in (("status", "failed"), ("frames", 322), ("reference_and_each_clip_checked", False), ("source", {})):
            motion = copy.deepcopy(report["result"]["absolute_motion_validation"])
            motion[key] = value
            variants.append(motion)
        for motion in variants:
            changed = copy.deepcopy(report)
            changed["result"]["absolute_motion_validation"] = motion
            with self.assertRaisesRegex(ValueError, "all 323 animation frames"):
                FIT.validate_import_report(changed, path, settings, destination)

    def test_report_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text("existing evidence", encoding="utf-8")
            with patch.object(sys, "argv", ["fit", "--manifest", "unused.json", "--import-report", "unused-report.json", "--report", str(output), "--apply"]):
                with self.assertRaises(FileExistsError):
                    FIT.main()
            self.assertEqual("existing evidence", output.read_text(encoding="utf-8"))

    def test_default_dry_run_never_imports_unreal_or_approves_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            manifest, imported, output = path / "manifest.json", path / "import.json", path / "report.json"
            manifest.write_text("{}", encoding="utf-8")
            imported.write_text("{}", encoding="utf-8")
            records = {"weapon": {"calibration": {"path": "fixture", "sha256": "fixture"}}}
            with patch.object(sys, "argv", ["fit", "--manifest", str(manifest), "--import-report", str(imported), "--report", str(output)]), patch.object(FIT, "read_inputs", return_value=(records, {"destination": "fixture", "result": {"disk_dependency_validation": {}}}, {}, {})), patch.object(FIT, "execute") as execution:
                FIT.main()
                execution.assert_not_called()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["numeric_socket_pass"])
            self.assertFalse(report["socket_alignment_approved"])
            self.assertFalse(report["runtime_approved"])
            self.assertEqual("validated_frozen_input_only_no_ue_executed", report["status"])


if __name__ == "__main__":
    unittest.main()
