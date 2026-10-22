from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_side_emblem_diagnostic as diagnostic


class WeightedEmblemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = diagnostic.team.read(diagnostic.WEIGHTED / "candidate_report.json")
        cls.footprint = np.asarray(Image.open(cls.report["previous_footprint"]["path"]))
        cls.binary = np.asarray(Image.open(cls.report["previous_binary_mask"]["path"]))
        cls.actual = np.asarray(Image.open(cls.report["new_mask"]["path"]))

    def test_exact_mask_record(self):
        diagnostic.team.shared.check_record(self.report["new_mask"])
        diagnostic.team.shared.check_record(self.report["tool"])

    def test_deterministic_regeneration(self):
        result, excluded, occupancy = diagnostic.continuous_mask(self.footprint, self.binary)
        np.testing.assert_array_equal(result, self.actual)
        self.assertEqual(int(excluded.sum()), 1217)

    def test_no_addition_to_footprint_or_noncloth_margin(self):
        self.assertTrue(np.all(self.actual <= self.footprint))
        self.assertFalse(((self.actual > 0) & (self.footprint == 0)).any())

    def test_only_radius1_inside_semantic_boundary_changes(self):
        result, excluded, occupancy = diagnostic.continuous_mask(self.footprint, self.binary)
        changed = result != self.binary
        self.assertFalse((changed & ~excluded).any())
        self.assertFalse((changed & (occupancy == 16)).any())
        self.assertEqual(int(changed.sum()), 604)

    def test_fully_protected_core_remains_zero(self):
        result, excluded, occupancy = diagnostic.continuous_mask(self.footprint, self.binary)
        core = excluded & (occupancy == 16)
        self.assertEqual(int(core.sum()), 613)
        self.assertTrue((result[core] == 0).all())

    def test_actual_game_probes_report_risk_honestly(self):
        self.assertEqual(int(self.actual[156, 235]), 0)
        self.assertEqual(int(self.actual[197, 256]), 48)
        self.assertFalse(self.report["verified_old_game_probes"][1]["is_core"])

    def test_front45_probes_identical(self):
        previous = diagnostic.team.read(diagnostic.team.FOLDER / "candidate_v02/candidate_report.json")
        self.assertEqual(len(previous["front45_probes_unchanged"]), 45)
        for probe in previous["front45_probes_unchanged"]:
            column, row = probe["atlas_pixel"]
            self.assertEqual(int(self.actual[row, column]), int(self.footprint[row, column]))

    def test_straight_edge_partial_and_core(self):
        footprint = np.full((7, 7), 255, dtype=np.uint8)
        binary = footprint.copy()
        binary[:, 3:] = 0
        result, excluded, occupancy = diagnostic.continuous_mask(footprint, binary)
        self.assertEqual(int(result[3, 2]), 255)
        self.assertEqual(int(result[3, 3]), 64)
        self.assertEqual(int(result[3, 4]), 0)

    def test_no_wraparound_at_image_edge(self):
        footprint = np.full((5, 5), 255, dtype=np.uint8)
        binary = footprint.copy()
        binary[0, 0] = 0
        result, excluded, occupancy = diagnostic.continuous_mask(footprint, binary)
        self.assertEqual(int(result[0, 0]), 191)
        self.assertEqual(int(result[-1, -1]), 255)

    def test_malformed_inputs_rejected(self):
        with self.assertRaises(ValueError):
            diagnostic.continuous_mask(np.zeros((2, 2), dtype=np.uint8), np.full((2, 2), 255, dtype=np.uint8))
        with self.assertRaises(ValueError):
            diagnostic.continuous_mask(np.full((2, 2), 128, dtype=np.uint8), np.zeros((2, 2), dtype=np.uint8))

    def test_source_and38_packages_still_frozen(self):
        context, records, packages = diagnostic.inputs()
        self.assertEqual(len(packages), 38)

    def test_candidate_is_not_visual_or_runtime_approval(self):
        for key in ("root_preview_review_passed", "actual_ue_visual_approved", "runtime_approved", "production_approved", "content_modified", "new_ue_branch_created"):
            self.assertFalse(self.report[key])


if __name__ == "__main__":
    unittest.main(verbosity=2)
