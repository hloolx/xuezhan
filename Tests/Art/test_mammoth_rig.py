import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_rig_under_test", ROOT / "Tools/Blender/inspect_mammoth_rig.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    arrays = {"POSITION": np.array(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0), (0, 0, 1), (1, 1, 1)), dtype=float),
              "NORMAL": np.array(((0, 0, 1),) * 6, dtype=float), "TEXCOORD_0": np.zeros((6, 2)),
              "indices": np.array(((0, 1, 2), (3, 4, 5)))}
    snapshot = MODULE.source_snapshot(arrays)
    fit = {"rotation": np.eye(3), "uniform_scale": 1.0, "translation_m": np.zeros(3)}
    return arrays, snapshot, fit


class MammothRigTests(unittest.TestCase):
    def test_source_snapshot_explicit_uv_and_axis_convention(self):
        arrays, source, _ = fixture()
        np.testing.assert_array_equal(source["positions"][4], (0, -1, 0))
        np.testing.assert_array_equal(source["normals"][0], (0, -1, 0))
        np.testing.assert_array_equal(source["uv"][0], (0, 1))
        np.testing.assert_array_equal(arrays["TEXCOORD_0"], np.zeros((6, 2)))

    def test_full_corner_mapping_retains_separate_coincident_identity(self):
        _, source, fit = fixture()
        mapping, triangles = MODULE.triangle_mapping(source, source, fit)
        self.assertEqual(mapping[0], {0})
        self.assertEqual(mapping[3], {3})
        self.assertEqual(len(triangles), 2)

    def test_cloud_weld_is_visible_in_mapping(self):
        _, source, fit = fixture()
        returned = {key: value.copy() for key, value in source.items()}
        returned["triangles"][1, 0] = 0
        mapping, _ = MODULE.triangle_mapping(source, returned, fit)
        self.assertEqual(mapping[0] & mapping[3], {0})
        result = MODULE.texture.split_identity(dict(enumerate(range(6))), [(0, 3)], mapping)
        self.assertFalse(result["all_native_identities_preserved"])

    def test_reversed_winding_rejected(self):
        _, source, fit = fixture()
        returned = {key: value.copy() for key, value in source.items()}
        returned["triangles"][0] = returned["triangles"][0][::-1]
        with self.assertRaisesRegex(ValueError, "winding"):
            MODULE.triangle_mapping(source, returned, fit)

    def test_missing_face_rejected(self):
        _, source, fit = fixture()
        returned = {key: value.copy() for key, value in source.items()}
        returned["triangles"] = returned["triangles"][:1]
        with self.assertRaisesRegex(ValueError, "omitted"):
            MODULE.triangle_mapping(source, returned, fit)

    def test_duplicate_face_rejected(self):
        _, source, fit = fixture()
        returned = {key: value.copy() for key, value in source.items()}
        returned["triangles"] = np.array((source["triangles"][0], source["triangles"][0]))
        with self.assertRaisesRegex(ValueError, "duplicated"):
            MODULE.triangle_mapping(source, returned, fit)

    def test_weight_validation_rejects_unknown_and_unweighted(self):
        rows = [{"vertex": 0, "weights": {}}, {"vertex": 1, "weights": {"missing": 1.0}}]
        result = MODULE.weight_metrics(rows, {"root"})
        self.assertFalse(result["weights_numerically_valid"])
        self.assertEqual(result["unweighted_vertices"], [0])
        self.assertEqual(len(result["errors"]), 2)

    def test_weight_sums_not_silently_normalized(self):
        rows = [{"vertex": 0, "weights": {"root": .3, "spine": .3}}]
        result = MODULE.weight_metrics(rows, {"root", "spine"})
        self.assertFalse(result["weights_numerically_valid"])
        self.assertAlmostEqual(result["errors"][0]["sum"], .6)
        self.assertEqual(rows[0]["weights"], {"root": .3, "spine": .3})

    def test_region_is_summary_not_anatomical_approval(self):
        rows = [{"vertex": 0, "weights": {"spine": 1.0}}, {"vertex": 1, "weights": {"spine": .5, "leg": .5}}]
        result = MODULE.region_weights(rows, [0, 1])
        self.assertAlmostEqual(result["mean_weight_by_bone"]["spine"], .75)
        self.assertFalse(result["rigid_or_deformation_approved"])

    def test_readonly_audit_has_no_export_or_repair_calls(self):
        source = inspect.getsource(MODULE.inspect)
        for forbidden in ("export_scene", "save_as_mainfile", "normals_split_custom_set", "vertex_groups.new", "modifier_apply"):
            self.assertNotIn(forbidden, source)

    def test_gltf_display_mesh_is_disabled_without_relaxing_skin_count(self):
        source = inspect.getsource(MODULE.inspect)
        self.assertIn("disable_bone_shape=True", source)
        self.assertIn("if len(meshes) != 1 or len(armatures) != 1:", source)
        self.assertLess(source.index('"import_inventory.json"'), source.index("if len(meshes) != 1"))

    def test_output_cannot_modify_cleanup_or_slinger(self):
        for path in (MODULE.BRANCH / "cleanup_v01", MODULE.BRANCH.parent / "stone_slinger_v01/rig_audit_01"):
            with self.assertRaises(ValueError):
                MODULE.fresh_output(path)


if __name__ == "__main__":
    unittest.main()
