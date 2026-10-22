import copy
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower_ue", ROOT / "Tools/rock_tower_ue.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def triangle(material="CW_wood", offset=0):
    return {"material": material, "corners": [(offset, 0, 0, 0, 0, 0, 0, 1),
            (offset + 1, 0, 0, 1, 0, 0, 0, 1), (offset, 1, 0, 0, 1, 0, 0, 1)]}


class RockTowerUETests(unittest.TestCase):
    def test_import_does_not_import_unreal_or_launch_process(self):
        self.assertNotIn("unreal", MODULE.__dict__)
        self.assertNotIn("subprocess", MODULE.__dict__)

    def test_bases_agree_without_double_scale_or_mirror_weapon(self):
        self.assertEqual(MODULE.blender_point_to_ue((1, 2, 3)), (100, -200, 300))
        self.assertEqual(MODULE.gltf_point_to_ue((1, 3, -2)), (100, -200, 300))

    def test_surface_allows_vertex_reordering_with_same_attributes(self):
        expected = [triangle()]
        actual = copy.deepcopy(expected)
        actual[0]["corners"] = list(reversed(actual[0]["corners"]))
        result = MODULE.compare_surface(expected, actual)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["max_position_error_cm"], 0)
        self.assertIn("winding", result["scope"])

    def test_material_swap_between_real_surfaces_fails(self):
        expected = [triangle("CW_wood"), triangle("CW_iron", 3)]
        actual = copy.deepcopy(expected)
        actual[0]["material"], actual[1]["material"] = actual[1]["material"], actual[0]["material"]
        with self.assertRaisesRegex(ValueError, "matching material"):
            MODULE.compare_surface(expected, actual)

    def test_uv_or_normal_tamper_fails(self):
        for component, value in ((3, .01), (5, .1)):
            actual = [triangle()]
            corner = list(actual[0]["corners"][0])
            corner[component] = value
            actual[0]["corners"][0] = corner
            with self.assertRaises(ValueError):
                MODULE.compare_surface([triangle()], actual)

    def test_nonfinite_and_out_of_tolerance_position_fail(self):
        for value in (math.nan, math.inf, .01):
            actual = [triangle()]
            corner = list(actual[0]["corners"][0])
            corner[0] = value
            actual[0]["corners"][0] = corner
            with self.assertRaises(ValueError):
                MODULE.compare_surface([triangle()], actual)

    def test_nearby_float_error_is_bounded_and_reported(self):
        actual = [triangle(offset=.0001)]
        result = MODULE.compare_surface([triangle()], actual)
        self.assertGreater(result["max_position_error_cm"], 0)
        self.assertLess(result["max_position_error_cm"], MODULE.POSITION_TOLERANCE_CM)

    def test_duplicate_and_missing_triangles_do_not_match(self):
        expected = [triangle(), triangle(offset=3)]
        with self.assertRaises(ValueError):
            MODULE.compare_surface(expected, [triangle(), triangle()])
        with self.assertRaises(ValueError):
            MODULE.compare_surface(expected, [triangle()])

    def test_actual_glb_seven_groups_and_identity_pivots(self):
        plan = MODULE.dry_plan()
        self.assertEqual(len(plan["entries"]), 7)
        self.assertEqual(sum(entry["triangles"] for entry in plan["entries"]), 11360)
        self.assertEqual(sum(entry["material_slots"] for entry in plan["entries"]), 14)
        self.assertFalse(plan["runtime_integrated"])
        self.assertFalse(plan["ue_structural_approved"])
        self.assertFalse(plan["production_approved"])
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["settings"]["material_overrides"], {})
        self.assertFalse(plan["settings"]["material_repairs"])
        self.assertEqual(plan["anchors"]["ArmPivot"]["translation_cm"], [-4, 0, 51])
        self.assertEqual([entry["upper_local_translation_cm"][2] for entry in plan["platforms"]], [1.5, .8, 1])
        cloth = next(entry for entry in plan["entries"] if entry["config_key"] == "Cloth")
        self.assertAlmostEqual(cloth["materials"]["CW_cobalt"]["roughness"], .66)
        self.assertEqual(cloth["materials"]["CW_cobalt"]["metallic"], 0)

    def test_real_small_glb_surface_self_comparison(self):
        rows, primitives = MODULE.read_glb(MODULE.DELIVERY / "RT_Cloth.glb")
        self.assertEqual(len(rows), 20)
        self.assertEqual(primitives[0]["material"], "CW_cobalt")
        self.assertEqual(MODULE.compare_surface(rows, rows)["status"], "passed")

    def test_fresh_requires_different_process_and_real_saved_pass(self):
        plan = {"destination": "/Game/ArtPilot/RockTower/h0123456789abcdef", "source_evidence": []}
        prior = {"status": "rock_tower_initial_saved_requires_fresh_reopen", "dry_run": False,
                 "structural_checks_passed": True, "execution_process_id": 100,
                 "destination": plan["destination"], "source_evidence": [],
                 "disk_dependency_validation": {"status": "saved_pending_fresh_reopen"}}
        MODULE.fresh_gate(plan, prior, 101)
        with self.assertRaisesRegex(ValueError, "fresh UE process"):
            MODULE.fresh_gate(plan, prior, 100)
        for field, value in (("dry_run", True), ("structural_checks_passed", False), ("status", "failed"), ("execution_process_id", None)):
            changed = dict(prior, **{field: value})
            with self.assertRaises(ValueError):
                MODULE.fresh_gate(plan, changed, 101)
        changed = dict(prior, source_evidence=[{"changed": True}])
        with self.assertRaises(ValueError):
            MODULE.fresh_gate(plan, changed, 101)

    def test_package_path_cannot_escape_exact_hash(self):
        destination = "/Game/ArtPilot/RockTower/h0123456789abcdef"
        for path in ("/Game/Other/A.A", destination + "/../Other/A.A", destination + "/A\\B.B", destination + "bad/A.A"):
            with self.assertRaises(ValueError):
                MODULE.package_file(path, destination, ROOT / "Content")

    def test_disk_package_tamper_missing_and_extra_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            content = Path(temporary)
            destination = "/Game/ArtPilot/RockTower/h0123456789abcdef"
            asset = destination + "/Frame/Frame.Frame"
            package = MODULE.package_file(asset, destination, content)
            package.parent.mkdir(parents=True)
            package.write_bytes(b"original")
            records = [dict(MODULE.file_record(package), asset_path=asset, class_name="StaticMesh")]
            plan = {"destination": destination, "expected_owned_packages": {"StaticMesh": 1}}
            MODULE.check_package_set(plan, records, [asset], content)
            with self.assertRaises(ValueError):
                MODULE.check_package_set(plan, records, [], content)
            extra = package.with_name("unexpected.uasset")
            extra.write_bytes(b"untracked")
            with self.assertRaises(ValueError):
                MODULE.check_package_set(plan, records, [asset], content)
            extra.unlink()
            package.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "changed"):
                MODULE.check_package_set(plan, records, [asset], content)


if __name__ == "__main__":
    unittest.main()
