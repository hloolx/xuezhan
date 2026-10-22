import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/Blender"))
SPEC = importlib.util.spec_from_file_location("mammoth_cleanup", ROOT / "Tools/Blender/cleanup_mammoth.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vertices, cls.polygons, cls.uv_layers, cls.version = MODULE.helpers.read_fbx(MODULE.SOURCE)
        cls.plan = MODULE.classify(cls.vertices, cls.polygons)

    def test_source_lineage_is_frozen(self):
        MODULE.helpers.require_hash(MODULE.SOURCE, MODULE.SOURCE_SHA)
        MODULE.helpers.require_hash(MODULE.NORMALIZED, MODULE.NORMALIZED_SHA)

    def test_eighteen_three_face_edges_belong_to_four_small_sheets(self):
        self.assertEqual(18, len(self.plan["nonmanifold_edges"]))
        self.assertEqual([61, 62, 63, 63], sorted(row["face_count"] for row in self.plan["accessory_patches"]))
        self.assertTrue(all(len(row["main_sheet_faces"]) == 2 for row in self.plan["nonmanifold_edges"]))

    def test_all_surface_corners_retained_by_twenty_three_index_splits(self):
        proof = self.plan["simulation"]
        self.assertEqual(23, proof["vertices_duplicated"])
        self.assertEqual(0, proof["faces_deleted"])
        self.assertEqual(0, proof["vertices_moved"])
        self.assertEqual(10078, proof["polygons_after"])
        self.assertTrue(proof["surface_corner_positions_and_order_identical"])

    def test_new_boundaries_are_only_proven_t_junction_positions(self):
        proof = self.plan["simulation"]
        self.assertEqual(137, proof["boundary_edges_before"])
        self.assertEqual(155, proof["boundary_edges_after"])
        self.assertTrue(proof["original_boundary_coordinate_multiset_retained"])
        self.assertTrue(proof["new_boundary_coordinate_multiset_equals18original_T_junctions"])

    def test_candidate_has_no_targeted_edge_or_vertex_nonmanifold_join(self):
        proof = self.plan["simulation"]
        self.assertEqual(0, proof["nonmanifold_edges_after"])
        self.assertEqual([], proof["affected_vertices_with_multiple_face_fans_after"])

    def test_readonly_simulation_does_not_mutate_source(self):
        before = json.dumps([self.vertices, self.polygons, self.uv_layers])
        MODULE.classify(self.vertices, self.polygons)
        self.assertEqual(before, json.dumps([self.vertices, self.polygons, self.uv_layers]))


if __name__ == "__main__":
    unittest.main()
