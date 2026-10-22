import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stone_slinger_cleanup", ROOT / "Tools/Blender/cleanup_stone_slinger.py")
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


class StoneSlingerCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vertices, cls.polygons, cls.uv_layers, cls.version = CLEANUP.read_fbx(CLEANUP.SOURCE)
        cls.plan = CLEANUP.split_plan(cls.vertices, cls.polygons)

    def test_frozen_original_source_and_normalized_hash(self):
        CLEANUP.require_hash(CLEANUP.SOURCE, CLEANUP.SOURCE_SHA)
        CLEANUP.require_hash(CLEANUP.NORMALIZED, CLEANUP.NORMALIZED_SHA)

    def test_exact_source_counts_and_uv_loop_correspondence(self):
        self.assertEqual(5539, len(self.vertices))
        self.assertEqual(6173, len(self.polygons))
        self.assertEqual(1, len(self.uv_layers))
        self.assertEqual(sum(map(len, self.polygons)), len(self.uv_layers[0]["loops"]))

    def test_four_faces_are_two_preexisting_manifold_sheets(self):
        self.assertEqual([3921, 5318], self.plan["edge_vertex_indices"])
        self.assertEqual([1270, 4981, 5007, 5008], self.plan["adjacent_faces"])
        self.assertEqual([517, 3447], sorted(sheet["face_count"] for sheet in self.plan["sheets"]))
        self.assertEqual([1280, 5002, 5003, 5007, 5008, 6054], self.plan["modified_face_indices"])

    def test_no_deleted_faces_moved_vertices_or_new_boundary(self):
        proof = self.plan["proof"]
        self.assertEqual(0, proof["faces_deleted"])
        self.assertEqual(0, proof["vertices_moved"])
        self.assertEqual(2, proof["vertices_duplicated"])
        self.assertEqual(290, proof["boundary_edges_after"])
        self.assertTrue(proof["boundary_edge_coordinate_multiset_identical"])
        self.assertTrue(proof["polygon_order_and_each_corner_position_identical"])
        self.assertEqual(0, proof["nonmanifold_index_edges_after"])

    def test_simulation_does_not_mutate_input(self):
        before = json.dumps([self.vertices, self.polygons])
        CLEANUP.split_plan(self.vertices, self.polygons)
        self.assertEqual(before, json.dumps([self.vertices, self.polygons]))

    def test_already_manifold_mesh_is_not_blindly_changed(self):
        with self.assertRaisesRegex(ValueError, "exactly one four-face"):
            CLEANUP.split_plan([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])

    def test_frozen_json_plan_rehydrates_without_false_mismatch(self):
        restored = json.loads(json.dumps(self.plan))
        self.assertEqual(restored, json.loads(json.dumps(CLEANUP.split_plan(self.vertices, self.polygons))))

    def test_remaining_four_points_are_genuine_disconnected_face_fans(self):
        plan = CLEANUP.split_plan(self.vertices, self.polygons, split_point_joins=True)
        rows = plan["point_only_join_diagnostic"]["before"]
        self.assertEqual([2494, 2499, 3888, 5320], [row["vertex"] for row in rows])
        self.assertTrue(all(row["fan_count"] == 2 for row in rows))
        self.assertTrue(all(len(set(root for fan in row["sheet_roots_by_fan"] for root in fan)) == 2 for row in rows))

    def test_point_split_preserves_surface_and_fixes_all_affected_fans(self):
        plan = CLEANUP.split_plan(self.vertices, self.polygons, split_point_joins=True)
        self.assertEqual(6, plan["proof"]["vertices_duplicated"])
        self.assertEqual(0, plan["proof"]["vertices_moved"])
        self.assertEqual(0, plan["proof"]["faces_deleted"])
        self.assertTrue(plan["proof"]["boundary_edge_coordinate_multiset_identical"])
        affected = plan["point_only_join_diagnostic"]["all_affected_source_and_duplicate_vertices_after"]
        self.assertEqual(12, len(affected))
        self.assertTrue(all(row["fan_count"] == 1 for row in affected))


if __name__ == "__main__":
    unittest.main()
