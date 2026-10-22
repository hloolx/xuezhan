from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_emblem as candidate
import base_stone_team_footprint_ue as team


class SemanticEmblemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = candidate.OUTPUT / "candidate_v02"
        cls.report = team.read(cls.folder / "candidate_report.json")
        cls.old = np.asarray(Image.open(cls.report["prior_mask"]["path"])) > 0
        cls.new = np.asarray(Image.open(cls.report["new_mask"]["path"])) > 0

    def test_exact_new_mask_record(self):
        team.shared.check_record(self.report["new_mask"])
        team.shared.check_record(self.report["tool"])
        self.assertEqual(int(self.new.sum()), 72828)

    def test_current_material_sources_still_frozen(self):
        context = team.source_inputs()
        team.check_records(context["frozen_packages"] + context["source_evidence"])

    def test_no_added_pixels_or_blanket_rectangle(self):
        self.assertFalse((self.new & ~self.old).any())
        self.assertEqual(int((self.old & ~self.new).sum()), 1217)
        self.assertTrue(self.new[185, 247])
        self.assertTrue(self.new[190, 249])

    def test_only_hand_traced_strokes_change(self):
        spec, context, path = candidate.inputs()
        proposal = candidate.stroke_selection(np.asarray(Image.open(path).convert("RGB")))
        self.assertFalse(((self.old ^ self.new) & ~proposal).any())

    def test_shared_other_face_pixels_remain_original(self):
        old = np.ones((3, 3), dtype=bool)
        proposed = old.copy()
        target = old.copy()
        other = np.eye(3, dtype=bool)
        new, excluded = candidate.protect_strokes(old, proposed, target, other)
        np.testing.assert_array_equal(new, other)
        self.assertFalse((excluded & other).any())

    def test_outside_target_cluster_never_removed(self):
        old = np.ones((3, 3), dtype=bool)
        target = np.eye(3, dtype=bool)
        new, excluded = candidate.protect_strokes(old, old, target, np.zeros_like(old))
        np.testing.assert_array_equal(old ^ new, target)

    def test_two_actual_side_emblem_probes_protected(self):
        for column, row in [(235, 156), (256, 197)]:
            self.assertTrue(self.old[row, column])
            self.assertFalse(self.new[row, column])

    def test_front45_probes_keep_previous_results(self):
        report = team.read(team.TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json")
        self.assertEqual(len(report["probes"]), 45)
        for probe in report["probes"]:
            column, row = probe["atlas_pixel"]
            self.assertEqual(bool(self.new[row, column]), probe["new_mask_on"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
