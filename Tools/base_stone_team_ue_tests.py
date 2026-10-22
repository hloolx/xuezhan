import copy
import inspect
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import base_stone_team_ue as candidate
import base_stone_team_render as render


class BaseTeamUEContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mask = candidate.read(candidate.TEAM / "main_cloth_candidate_v02_safe1/candidate_mask_report.json")

    def test_all26_frozen_packages_and_sources(self):
        context = candidate.source_inputs()
        self.assertEqual(len(context["frozen_packages"]), 26)
        self.assertEqual(len(context["original_textures"]), 3)
        self.assertFalse(context["settings"]["all_cloth_coverage_approved"])

    def test_exact_safe_mask(self):
        self.assertEqual(candidate.validate_mask(self.mask)["mask_pixels"], 70868)

    def test_uv_spill_rejected(self):
        changed = copy.deepcopy(self.mask)
        changed["one_pixel_filter_footprint_protected_overlap_pixels"] = 1
        with self.assertRaises(ValueError):
            candidate.validate_mask(changed)

    def test_semantic_expansion_rejected(self):
        changed = copy.deepcopy(self.mask)
        changed["selected_clusters"].append(2)
        with self.assertRaises(ValueError):
            candidate.validate_mask(changed)

    def test_unsafe_mask_hash_rejected(self):
        changed = copy.deepcopy(self.mask)
        changed["mask"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            candidate.validate_mask(changed)

    def test_whole_cloth_claim_rejected(self):
        changed = copy.deepcopy(self.mask)
        changed["all_cloth_coverage_approved"] = True
        with self.assertRaises(ValueError):
            candidate.validate_mask(changed)

    def test_hash_isolated_write_path(self):
        destination = candidate.PREFIX + "h" + "a" * 16
        result = candidate.package_file(candidate.ROOT / "Content", destination + "/M_Base.M_Base", destination)
        self.assertEqual(result.name, "M_Base.uasset")

    def test_frozen_base_write_path_rejected(self):
        with self.assertRaises(ValueError):
            candidate.package_file(candidate.ROOT / "Content", "/Game/ArtPilot/Base/Base.Base", "/Game/ArtPilot/Base")

    def test_traversal_rejected(self):
        destination = candidate.PREFIX + "h" + "a" * 16
        with self.assertRaises(ValueError):
            candidate.package_file(candidate.ROOT / "Content", destination + "/../M.M", destination)

    def test_no_reconstructed_noncolor_nodes(self):
        self.assertFalse(set(candidate.WRAPPER_CLASSES) & {"base_color", "normal", "roughness", "metallic"})
        self.assertEqual(len(candidate.shared.LINKS), 15)

    def test_native_output_query_shapes(self):
        self.assertEqual(candidate.output_name((True, "BaseColor")), "BaseColor")
        self.assertEqual(candidate.output_name(""), "")
        with self.assertRaises(ValueError):
            candidate.output_name((False, ""))

    def test_actual_vector_parameter_named_rgb_is_exact(self):
        candidate.require_output("RGB", "RGB")
        candidate.require_output("", "")
        candidate.require_output("BaseColor", "BaseColor")
        for actual, requested in (("", "RGB"), ("R", "RGB"), ("Roughness", "BaseColor"), ("RGB", "")):
            with self.assertRaises(ValueError):
                candidate.require_output(actual, requested)

    def test_strength0_exact_original(self):
        original = [.15, .3, .55]
        self.assertEqual(candidate.shared.shade_reference(original, candidate.shared.TEAM_COLORS["Red"], 1, 0), original)

    def test_mask0_keeps_white_and_noncloth(self):
        original = [.9, .85, .8]
        self.assertEqual(candidate.shared.shade_reference(original, candidate.shared.TEAM_COLORS["Red"], 0, 1), original)

    def test_luminance_preserved(self):
        original = [.1, .2, .4]
        result = candidate.shared.shade_reference(original, candidate.shared.TEAM_COLORS["Red"], 1, 1)
        weights = candidate.shared.LUMINANCE
        self.assertAlmostEqual(sum(value * weight for value, weight in zip(original, weights)), sum(value * weight for value, weight in zip(result, weights)))

    def test_eight_matched_camera_controls(self):
        self.assertEqual(len(render.SHOTS), 8)
        for crop in ("wide", "flag"):
            self.assertEqual({mode for label, mode, shot_crop in render.SHOTS if shot_crop == crop}, {"original", "disabled", "blue", "red"})
            self.assertIn(crop, render.CAMERAS)

    def test_residency_missing_mask_rejected(self):
        paths = {"/Game/Base", "/Game/Normal", "/Game/Packed", "/Game/Mask"}
        records = {path: {"maximum_allowed_size": [2048, 2048], "actual_resident_size": [2048, 2048]} for path in paths - {"/Game/Mask"}}
        self.assertFalse(render.textures_resident(records, paths))

    def test_rhi_compilation_flush_precedes_strict_dimension_audit(self):
        source = inspect.getsource(render.BaseReview.setup)
        self.assertLess(source.index('"Editor.AsyncAssetCompilationFinishAll"'), source.index("team.audit("))
        self.assertIn("mask_dimensions_before_compilation_flush", source)
        self.assertIn("mask_dimensions_after_compilation_flush", source)

    def test_source2048_does_not_imply_resident2048(self):
        text = "BEGIN\n2048,2048,1,PF,1024,1024,1,PF_DXT1,World,/Game/Base,\nEND"
        records = render.parse_texture_dump(text, "BEGIN", "END", {"/Game/Base"})
        self.assertFalse(render.textures_resident(records, {"/Game/Base"}))
        self.assertEqual(records["/Game/Base"]["actual_resident_size"], [1024, 1024])

    def test_incomplete_dump_rejected(self):
        self.assertIsNone(render.parse_texture_dump("BEGIN\n2048", "BEGIN", "END", {"/Game/Base"}))

    def test_actual_logged_complete_resident_block(self):
        log_path = candidate.TEAM / "ue_color_review_03.log"
        if not log_path.is_file():
            self.skipTest("Historical actual UE log not present")
        context = candidate.read(candidate.TEAM / "ue_fresh_02.json")
        paths = set(context["original_textures"] + [context["result"]["mask"]])
        prefix = "BASE_TEAM_RESIDENCY_49584_4_original_wide"
        records = render.parse_texture_dump(log_path.read_text(encoding="utf-8-sig", errors="replace"), prefix + "_BEGIN", prefix + "_END", paths)
        self.assertTrue(render.textures_resident(records, paths))

    def test_pending_end_does_not_queue_new_dump(self):
        session = render.BaseReview.__new__(render.BaseReview)
        session.finished = False
        session.started = session.phase_started = time.monotonic()
        session.args = Mock(timeout=150)
        session.stage = "resources"
        session.current_dump = ("BEGIN", "END")
        session.last_request = time.monotonic() - 1
        session.read_dump = Mock(return_value=None)
        session.request_dump = Mock()
        session.tick(0.1)
        session.request_dump.assert_not_called()

    def test_terminal_tick_is_inert(self):
        session = render.BaseReview.__new__(render.BaseReview)
        session.finished = True
        session.request_dump = Mock()
        session.tick(0.1)
        session.request_dump.assert_not_called()

    def test_terminal_request_cannot_queue(self):
        session = render.BaseReview.__new__(render.BaseReview)
        session.finished = True
        with self.assertRaises(RuntimeError):
            session.request_dump("forbidden")

    def test_fake_or_wrong_size_screenshot_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preview.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 256, 256) + b"\x00" * 1200)
            with self.assertRaises(ValueError):
                render.validate_png(path, 512)


if __name__ == "__main__":
    unittest.main(verbosity=2)
