"""Offline source-correspondence and read-only persistence guards; never launches UE."""
import json
from pathlib import Path
import tempfile
import unittest

import base_stone_validate_ue as validator


class BaseStoneFreshValidationTests(unittest.TestCase):
    def setUp(self):
        self.corners = [(10.0, 20.0, -31.0, 0.1, 0.2), (20.0, 21.0, 0.0, 0.3, 0.4), (30.0, -10.0, 12.0, 0.5, 0.6)]
        self.triangles = [(0, 1, 2)]
        self.observed = [list(self.corners)]

    def test_exact_triangle_and_uv(self):
        result = validator.match_triangles(self.corners, self.triangles, self.observed)
        self.assertEqual(result["triangle_count"], 1)
        self.assertEqual(result["maximum_position_error_cm"], 0)

    def test_corner_reorder_permitted(self):
        self.observed[0].reverse()
        self.assertEqual(validator.match_triangles(self.corners, self.triangles, self.observed)["status"], "passed")

    def test_float32_rounding_tolerance(self):
        self.observed[0][0] = (10.00001, 20.0, -31.0, 0.1, 0.2)
        self.assertLess(validator.match_triangles(self.corners, self.triangles, self.observed)["maximum_position_error_cm"], 0.001)

    def test_reject_y_mirror(self):
        self.observed = [[(corner[0], -corner[1], *corner[2:]) for corner in self.corners]]
        with self.assertRaises(ValueError):
            validator.match_triangles(self.corners, self.triangles, self.observed)

    def test_reject_second_ground_translation(self):
        self.observed = [[(corner[0], corner[1], corner[2] - 31, *corner[3:]) for corner in self.corners]]
        with self.assertRaises(ValueError):
            validator.match_triangles(self.corners, self.triangles, self.observed)

    def test_reject_uv_change(self):
        self.observed[0][0] = (*self.corners[0][:3], 0.15, 0.2)
        with self.assertRaises(ValueError):
            validator.match_triangles(self.corners, self.triangles, self.observed)

    def test_reject_removed_triangle(self):
        with self.assertRaises(ValueError):
            validator.match_triangles(self.corners, self.triangles, [])

    def test_reject_duplicate_triangle(self):
        with self.assertRaises(ValueError):
            validator.match_triangles(self.corners, self.triangles, self.observed * 2)

    def test_source_duplicate_multiplicity_preserved(self):
        self.assertEqual(validator.match_triangles(self.corners, self.triangles * 2, self.observed * 2)["triangle_count"], 2)

    def test_other_asset_package_rejected(self):
        with self.assertRaises(ValueError):
            validator.package_file("/Game/ArtPilot/StoneAxeRig/SK_StoneAxe.SK_StoneAxe")

    def test_directory_traversal_rejected(self):
        with self.assertRaises(ValueError):
            validator.package_file(validator.DESTINATION + "/../Other.Other")

    def test_changed_disk_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence"
            path.write_bytes(b"original")
            record = validator.file_record(path)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                validator.check_records([record])

    def test_never_overwrites_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.json"
            validator.write_new(path, {"before": True})
            with self.assertRaises(FileExistsError):
                validator.write_new(path, {"after": True})
            self.assertEqual(json.loads(path.read_text()), {"before": True})

    def test_actual_immutable_source_self_correspondence(self):
        path = validator.BASE / "pbr_v01/hf150ba0cde05/Base_Stone_PBR.glb"
        self.assertEqual(validator.sha256(path), validator.SOURCE_SHA)
        corners, triangles = validator.read_glb_geometry(path)
        result = validator.match_triangles(corners, triangles, [[corners[index] for index in triangle] for triangle in triangles])
        self.assertEqual(result["triangle_count"], 18681)


if __name__ == "__main__":
    unittest.main()
