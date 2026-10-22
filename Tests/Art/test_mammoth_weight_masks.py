import importlib.util
import inspect
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_masks_test", ROOT / "Tools/Blender/prepare_mammoth_weight_masks.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothMaskTests(unittest.TestCase):
    def test_geodesic_does_not_jump_disconnected_nearby_vertices(self):
        graph = {0: {1: .04}, 1: {0: .04, 2: .06}, 2: {1: .06}, 3: {}}
        self.assertEqual(MODULE.geodesic_distances(graph, [0], .08), {0: 0., 1: .04})

    def test_transition_exact_endpoints_and_smooth_middle(self):
        self.assertEqual(MODULE.transition_alpha(0, .08), 1)
        self.assertEqual(MODULE.transition_alpha(.08, .08), 0)
        self.assertEqual(MODULE.transition_alpha(.12, .08), 0)
        self.assertAlmostEqual(MODULE.transition_alpha(.04, .08), .5)

    def test_contact_rows_identical_without_cross_vertex_average(self):
        self.assertEqual(MODULE.blend_with_anchor({1: .7, 2: .3}, 3, 1), {3: 1})
        self.assertEqual(MODULE.blend_with_anchor({5: .2, 6: .8}, 3, 1), {3: 1})
        self.assertEqual(MODULE.blend_with_anchor({1: .7, 2: .3}, 3, 0), {1: .7, 2: .3})

    def test_blend_does_not_truncate_fifth_influence(self):
        row = MODULE.blend_with_anchor({0: .25, 1: .25, 2: .25, 3: .25}, 4, .5)
        self.assertEqual(len(row), 5)
        self.assertAlmostEqual(sum(row.values()), 1)

    def test_render_is_mask_only_not_weight_or_model_writer(self):
        source = inspect.getsource(MODULE.render)
        for forbidden in ("vertex_groups.new", '"REPLACE"', "export_scene", "save_as_mainfile", "normals_split_custom_set"):
            self.assertNotIn(forbidden, source)
        self.assertIn('"weights_exact"', source)
        self.assertIn('for mode in ("rest", "current_shoulder8")', source)


if __name__ == "__main__":
    unittest.main()
