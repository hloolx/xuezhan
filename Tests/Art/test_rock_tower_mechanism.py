import importlib.util
import math
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower", ROOT / "Tools/Blender/build_rock_tower.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RockTowerMechanismTests(unittest.TestCase):
    def test_import_is_blender_free(self):
        self.assertNotIn("bpy", MODULE.__dict__)

    def test_y_axis_rotation_preserves_transverse_axis(self):
        for angle in (-65, -35, 0, 40):
            self.assertEqual(MODULE.rotate_y((0, 1, 0), angle), (0, 1, 0))

    def test_rotation_keeps_lengths_and_handedness(self):
        for angle in range(-65, 41, 5):
            transformed = MODULE.rotate_y((.1, .2, .3), angle)
            self.assertAlmostEqual(math.dist((0, 0, 0), transformed), math.sqrt(.14))
            first = MODULE.rotate_y((1, 0, 0), angle)
            third = MODULE.rotate_y((0, 0, 1), angle)
            self.assertAlmostEqual(first[0] * third[2] - first[2] * third[0], 1)

    def test_release_direction_points_forward_and_up(self):
        direction = MODULE.rotate_y((1, 0, 0), MODULE.READY_ANGLE)
        self.assertGreater(direction[0], .8)
        self.assertGreater(direction[2], .5)

    def test_axle_has_positive_radial_clearance_and_closed_post_above(self):
        self.assertGreater(MODULE.BORE_RADIUS, MODULE.AXLE_RADIUS)
        top = MODULE.POST_CENTRE_Z + MODULE.POST_DIMENSIONS[2] / 2
        self.assertGreater(top - MODULE.PIVOT[2] - MODULE.BORE_RADIUS, .03)

    def test_fire_sequence_is_immediate_release_not_windup(self):
        before = MODULE.sample_cycle(-.001)
        release = MODULE.sample_cycle(0)
        self.assertTrue(before["stone_visible"])
        self.assertFalse(release["stone_visible"])
        self.assertEqual(before["angle_degrees"], release["angle_degrees"])
        self.assertEqual(release["phase"], "released_follow_through")

    def test_reload_and_ready_fit_existing_cooldown(self):
        self.assertFalse(MODULE.sample_cycle(1.199)["stone_visible"])
        self.assertTrue(MODULE.sample_cycle(1.2)["stone_visible"])
        self.assertEqual(MODULE.sample_cycle(2.1)["phase"], "ready")
        self.assertEqual(MODULE.sample_cycle(2.4)["angle_degrees"], MODULE.READY_ANGLE)
        self.assertEqual(MODULE.CYCLE_SECONDS, 2.4)

    def test_disabled_is_not_a_release(self):
        state = MODULE.sample_cycle(0, enabled=False)
        self.assertEqual(state["phase"], "disabled")
        self.assertFalse(state["stone_visible"])

    def test_all_samples_stay_in_mechanical_range(self):
        for frame in range(145):
            angle = MODULE.sample_cycle(frame / 60)["angle_degrees"]
            self.assertGreaterEqual(angle, MODULE.RELOAD_ANGLE)
            self.assertLessEqual(angle, MODULE.FOLLOW_ANGLE)

    def test_cycle_angles_continuous_at_boundaries(self):
        for boundary in (0, .16, .30, .95, 1.3, 2.1, 2.4):
            left = MODULE.sample_cycle(boundary - 1e-8)["angle_degrees"]
            right = MODULE.sample_cycle(boundary + 1e-8)["angle_degrees"]
            self.assertLess(abs(left - right), 1e-4)

    def test_nonfinite_time_rejected(self):
        for value in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                MODULE.sample_cycle(value)

    def test_swept_extrema_enclose_dense_samples(self):
        points = [(-.1, -.15, -.1), (.15, .2, .7), MODULE.RELEASE_LOCAL]
        bounds = MODULE.swept_point_bounds(points)
        for index in range(1001):
            angle = -65 + 105 * index / 1000
            for point in points:
                actual = MODULE.arm_point(point, angle)
                for axis in range(3):
                    self.assertGreaterEqual(actual[axis] + 1e-12, bounds["min"][axis])
                    self.assertLessEqual(actual[axis] - 1e-12, bounds["max"][axis])

    def test_swept_extrema_include_interior_peak(self):
        bounds = MODULE.swept_point_bounds([(0, 0, 1)])
        self.assertAlmostEqual(bounds["max"][2], MODULE.PIVOT[2] + 1)

    def test_cup_is_closed_thick_shell_not_two_concave_fronts(self):
        vertices, faces, sectors = MODULE.cup_geometry()
        edges = Counter()
        directions = Counter()
        for face in faces:
            for current, following in zip(face, face[1:] + face[:1]):
                edges[tuple(sorted((current, following)))] += 1
                directions[(current, following)] += 1
        self.assertTrue(all(count == 2 for count in edges.values()))
        self.assertTrue(all(directions[(first, second)] == directions[(second, first)] for first, second in edges))
        self.assertEqual(len(sectors), len(faces))
        self.assertLess(min(vertex[0] for vertex in vertices), -.08)
        self.assertAlmostEqual(max(vertex[0] for vertex in vertices), .06)

    def test_independent_stone_and_release_anchor(self):
        self.assertEqual(MODULE.HIERARCHY["loaded_stone"], "cup")
        self.assertEqual(MODULE.HIERARCHY["release_point"], "cup")
        self.assertNotEqual("loaded_stone", "throwing_arm")

    def test_new_cup_bindings_are_closed_loops_not_free_ends(self):
        for axial in (-.025, .02):
            vertices, faces = MODULE.cup_binding_geometry(axial)
            edges = Counter()
            for face in faces:
                for current, following in zip(face, face[1:] + face[:1]):
                    edges[tuple(sorted((current, following)))] += 1
            self.assertTrue(all(count == 2 for count in edges.values()))
            self.assertEqual(len(vertices), 32 * 6)
        with self.assertRaises(ValueError):
            MODULE.cup_binding_geometry(.5)

    def test_support_requires_every_sample_not_an_average(self):
        result = MODULE.support_result([-.010, .010, 0], 0, 0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["penetrating_samples"], 1)
        self.assertEqual(result["floating_samples"], 1)

    def test_support_tolerance_cannot_hide_missing_or_sloping_surfaces(self):
        self.assertTrue(MODULE.support_result([0, .001, -.001], 0, 0)["passed"])
        self.assertFalse(MODULE.support_result([0], 1, 0)["passed"])
        self.assertFalse(MODULE.support_result([0], 0, 1)["passed"])
        self.assertFalse(MODULE.support_result([], 0, 0)["passed"])
        self.assertFalse(MODULE.support_result([.00200001], 0, 0)["passed"])

    def test_platforms_use_normalized_ground_not_old_runtime_coordinates(self):
        self.assertAlmostEqual(MODULE.PLATFORMS_CM["front_negative_y"][2], 157.49995)
        self.assertAlmostEqual(MODULE.PLATFORMS_CM["front_positive_y"][2], 157.55195)
        self.assertAlmostEqual(MODULE.PLATFORMS_CM["rear"][2], 317.55337)

    def test_surface_clip_preserves_actual_plane_heights(self):
        polygon = [(-1, -1, -2), (2, -1, 1), (-1, 2, 1)]
        clipped = MODULE.clipped_surface_polygon(polygon, (0, .5, 0, .5))
        self.assertAlmostEqual(MODULE.projected_area(clipped), .25)
        for horizontal, across, height in clipped:
            self.assertAlmostEqual(height, horizontal + across)

    def test_pad_mesh_is_closed_consistently_wound_and_minimal(self):
        patches = [(1, [(0, 0, 0), (.1, 0, .001), (.1, .1, .002)]),
                   (2, [(0, 0, 0), (.1, .1, .002), (0, .1, .001)])]
        vertices, faces, report = MODULE.matched_pad_geometry(patches, (0, .1, 0, .1), .008)
        edges, directions = Counter(), Counter()
        for face in faces:
            for first, second in zip(face, face[1:] + face[:1]):
                edges[tuple(sorted((first, second)))] += 1
                directions[(first, second)] += 1
        self.assertTrue(all(count == 2 for count in edges.values()))
        self.assertTrue(all(directions[(first, second)] == directions[(second, first)] for first, second in edges))
        self.assertEqual(len(vertices), 8)
        self.assertEqual(sum(len(face) - 2 for face in faces), 12)
        self.assertEqual(report["source_base_faces"], [1, 2])
        self.assertAlmostEqual(report["minimum_thickness_mm"], 6)

    def test_pad_rejects_missing_overlap_or_thin_underlay(self):
        patches = [(1, [(0, 0, 0), (.1, 0, 0), (0, .1, 0)])]
        with self.assertRaises(ValueError):
            MODULE.matched_pad_geometry(patches, (0, .1, 0, .1), .01)
        patches += [(2, [(.1, 0, 0), (.1, .1, 0), (0, .1, 0)])]
        with self.assertRaises(ValueError):
            MODULE.matched_pad_geometry(patches * 2, (0, .1, 0, .1), .01)
        with self.assertRaises(ValueError):
            MODULE.matched_pad_geometry(patches, (0, .1, 0, .1), .004)

    def test_lift_is_explicit_minimum_and_never_silently_clamped(self):
        self.assertEqual(MODULE.mount_lift([.009355], [.0131]), .015)
        self.assertEqual(MODULE.mount_lift([.0024], [.0101]), .011)
        with self.assertRaises(ValueError):
            MODULE.mount_lift([.018], [])
        with self.assertRaises(ValueError):
            MODULE.mount_lift([], [])
        with self.assertRaises(ValueError):
            MODULE.mount_lift([float("nan")], [])

    def test_frozen_v02_contract_requires_real_inspection_hash(self):
        contract = MODULE.frozen_upper_contract(MODULE.OUTPUT_ROOT / "candidate_v02/Turret_RockTower.blend")
        self.assertEqual(contract["mesh_count"], 71)
        self.assertEqual(contract["triangles"], 11056)
        self.assertEqual(contract["model"]["sha256"], "be39857c4dbb12f9380dd60577e4b98213953e2e0518c54fca9dcd71288bac70")
        self.assertTrue(contract["reuse_axis_and_cycle_unmodified"])
        with self.assertRaises(ValueError):
            MODULE.frozen_upper_contract(MODULE.ROOT / "outside.blend")

    def test_pad_clip_does_not_accept_degenerate_or_outside_surface(self):
        self.assertEqual(MODULE.clipped_surface_polygon([(2, 2, 0), (3, 2, 0), (2, 3, 0)], (0, 1, 0, 1)), [])
        with self.assertRaises(ValueError):
            MODULE.matched_pad_geometry([], (0, 1, 0, 1), .01)

    def test_no_cycles_or_missing_parents(self):
        for name in MODULE.HIERARCHY:
            visited = set()
            current = name
            while current is not None:
                self.assertNotIn(current, visited)
                visited.add(current)
                self.assertIn(current, MODULE.HIERARCHY)
                current = MODULE.HIERARCHY[current]

    def test_path_guard(self):
        self.assertEqual(MODULE.safe_output(MODULE.OUTPUT_ROOT / "candidate_v01"), (MODULE.OUTPUT_ROOT / "candidate_v01").resolve())
        for path in (MODULE.ROOT, MODULE.OUTPUT_ROOT, MODULE.OUTPUT_ROOT / "../elsewhere"):
            with self.assertRaises(ValueError):
                MODULE.safe_output(path)

    def test_writer_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            MODULE.write_new(path, {"kept": True})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                MODULE.write_new(path, {"kept": False})
            self.assertEqual(path.read_bytes(), original)

    def test_frozen_canonical_hashes_and_unapproved_plan(self):
        plan = MODULE.mechanism_plan()
        self.assertEqual(len(plan["references"]), 3)
        self.assertFalse(plan["production_approved"])
        self.assertFalse(plan["approved_for_ue_import"])
        self.assertFalse(plan["timing"]["client_notify_causes_damage"])
        self.assertEqual(plan["references"][1]["design_role"], "right")


if __name__ == "__main__":
    unittest.main()
