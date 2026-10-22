import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_parent_test", ROOT / "Tools/Blender/correct_mammoth_hind_parent.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothParentTests(unittest.TestCase):
    def test_reparent_keeps_world_rest_and_other_nodes(self):
        document = {"nodes": [{"name": "pelvis", "translation": [1, 2, 3], "children": [1]},
                              {"name": "left", "translation": [0, 1, 0], "children": [2]},
                              {"name": "right", "translation": [0, -2, 0], "children": [3]},
                              {"name": "ankle", "translation": [0, 0, -1]}], "skins": [{"inverseBindMatrices": 7}], "meshes": [{"primitives": []}]}
        before, _ = MODULE.transfer.world_matrices(document)
        changed, report = MODULE.reparent_preserving_world(document, "right", "pelvis")
        after, parents = MODULE.transfer.world_matrices(changed)
        for index in before:
            np.testing.assert_allclose(before[index], after[index], atol=1e-14)
        self.assertEqual(parents[2], 0)
        self.assertEqual(document["nodes"][1]["children"], [2])
        self.assertEqual(changed["skins"], document["skins"])
        self.assertEqual(changed["meshes"], document["meshes"])
        self.assertEqual(report["old_parent"], "left")

    def test_descendant_parent_rejected(self):
        document = {"nodes": [{"name": "root", "children": [1]}, {"name": "child", "children": [2]}, {"name": "tip"}]}
        with self.assertRaisesRegex(ValueError, "descendant|cycle"):
            MODULE.reparent_preserving_world(document, "child", "tip")

    def test_scope_only_parent_not_weights_or_export(self):
        for function in (MODULE.reparent_preserving_world, MODULE.run, MODULE.compare_actual_rest):
            source = inspect.getsource(function)
            for forbidden in ("vertex_groups.new", "export_scene", "normals_split_custom_set", "remove_doubles"):
                self.assertNotIn(forbidden, source)
        self.assertEqual(MODULE.CHILD, "tripo::1_Left_Limb_1")
        self.assertEqual(MODULE.NEW_PARENT, "bone_21")

    def test_render_requires_actual_endpoints_and_gpu(self):
        source = inspect.getsource(MODULE.render_comparisons)
        self.assertIn("rig.matrix_world @ bone.head", source)
        self.assertIn("rig.matrix_world @ bone.tail", source)
        self.assertIn('scene.cycles.device != "GPU"', source)
        self.assertIn("size=512", source)
        self.assertIn("samples=8", source)


if __name__ == "__main__":
    unittest.main()
