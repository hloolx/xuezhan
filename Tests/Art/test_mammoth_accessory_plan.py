import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_accessory_plan_test", ROOT / "Tools/Blender/plan_mammoth_accessory_weights.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothAccessoryPlanTests(unittest.TestCase):
    def test_world_rotation_moves_only_real_descendants(self):
        document = {"nodes": [{"name": "pelvis", "children": [1, 3]},
                              {"name": "leg", "translation": [0, 1, 0], "children": [2]},
                              {"name": "foot", "translation": [1, 0, 0]},
                              {"name": "other", "translation": [0, 0, 1]}],
                    "skins": [{"joints": [0, 1, 2, 3]}]}
        actual = MODULE.pose_matrices(document, {"bone": "leg", "axis_world": [0, 0, 1], "degrees": 90})
        before, _ = MODULE.transfer.world_matrices(document)
        np.testing.assert_allclose(actual[0], before[0], atol=1e-12)
        np.testing.assert_allclose(actual[3], before[3], atol=1e-12)
        np.testing.assert_allclose(actual[1][:3, 3], before[1][:3, 3], atol=1e-12)
        self.assertGreater(np.linalg.norm(actual[2][:3, 3] - before[2][:3, 3]), 1)

    def test_plan_has_no_blender_or_mesh_mutation(self):
        source = inspect.getsource(MODULE.analyze)
        for forbidden in ("import bpy", "export_scene", "vertex_groups", "MODEL.write", "encode("):
            self.assertNotIn(forbidden, source)
        self.assertIn("pure_GLTF_skin_simulation_not_Blender_actual", source)
        self.assertIn('"weight_changes": 0', source)

    def test_model_is_frozen_parent_only_not_raw_reweld(self):
        self.assertEqual(MODULE.MODEL_SHA, "65c1f2291b1917cafa97ec3b9be3181c7ca9f51a8360330f66e1762ca867effb")
        self.assertIn("rig_transfer_parent_02", str(MODULE.MODEL))


if __name__ == "__main__":
    unittest.main()
