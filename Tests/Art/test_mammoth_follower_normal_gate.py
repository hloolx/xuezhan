from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_visual_v02_test", ROOT / "Tools/Blender/run_mammoth_follower_visual_v02.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_summary():
    return {"authored_exact": {"POSITION": True, "NORMAL": True, "TEXCOORD_0": True, "indices": True},
            "original_binary_prefix_exact": True, "PBR_metadata_exact": True, "existing33_bind_matrix_difference": 0,
            "bind_skin": {"maximum_vector_difference": 2.23e-7}, "static": {"maximum_angle_degrees": .007146},
            "evaluated_rest": {"maximum_angle_degrees": .011051}, "bind_skin_changes_outside_weight_rows": [],
            "static_changes_outside_one_ring": [], "evaluated_changes_outside_one_ring": []}


class MammothFollowerNormalGateTests(unittest.TestCase):
    def test_audited_import_roundoff_passes(self):
        MODULE.enforce_normal_gate(valid_summary())

    def test_real_authored_normal_change_cannot_hide_under_angle_limits(self):
        summary = valid_summary()
        summary["authored_exact"]["NORMAL"] = False
        with self.assertRaisesRegex(ValueError, "Authored"):
            MODULE.enforce_normal_gate(summary)

    def test_any_original_payload_change_fails(self):
        for name in ("original_binary_prefix_exact", "PBR_metadata_exact"):
            summary = valid_summary()
            summary[name] = False
            with self.assertRaises(ValueError):
                MODULE.enforce_normal_gate(summary)

    def test_each_layer_limit_is_enforced(self):
        for layer, field, value in (("bind_skin", "maximum_vector_difference", 4.01e-7), ("static", "maximum_angle_degrees", .01001), ("evaluated_rest", "maximum_angle_degrees", .01501)):
            summary = valid_summary()
            summary[layer][field] = value
            with self.assertRaises(ValueError):
                MODULE.enforce_normal_gate(summary)

    def test_locality_and_existing_bone_identity_are_required(self):
        for field in ("bind_skin_changes_outside_weight_rows", "static_changes_outside_one_ring", "evaluated_changes_outside_one_ring"):
            summary = deepcopy(valid_summary())
            summary[field] = [123]
            with self.assertRaises(ValueError):
                MODULE.enforce_normal_gate(summary)
        summary = valid_summary()
        summary["existing33_bind_matrix_difference"] = 1e-8
        with self.assertRaises(ValueError):
            MODULE.enforce_normal_gate(summary)


if __name__ == "__main__":
    unittest.main()
