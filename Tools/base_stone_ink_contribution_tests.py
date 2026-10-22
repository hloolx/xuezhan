from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_ink_contribution_encode as encoding
import base_stone_ink_contribution_ue as adapter
import base_stone_ink_contribution_render as render


def evaluate_graph(source, texture, guard, color, strength):
    values = {"base_color": source, "ink_texture": texture, "cloth_mask": guard, "team_color": color,
              "luminance_weights": np.asarray(adapter.shared.LUMINANCE), "team_strength": strength}
    with adapter.graph_contract():
        pending = {name: kind for name, kind in adapter.base.WRAPPER_CLASSES.items() if name not in values}
        links = list(adapter.shared.LINKS)
        while pending:
            processed = False
            for name, kind in list(pending.items()):
                incoming = {pin: values[source_name] for source_name, output, target, pin in links if target == name and source_name in values}
                wanted = [link for link in links if link[2] == name]
                if len(incoming) != len(wanted):
                    continue
                first = incoming.get("A")
                second = incoming.get("B", .5 if name == "ink_decode" else .01)
                operations = {"MaterialExpressionMultiply": lambda: first * second,
                              "MaterialExpressionDotProduct": lambda: np.sum(first * second),
                              "MaterialExpressionSubtract": lambda: first - second,
                              "MaterialExpressionAdd": lambda: first + second,
                              "MaterialExpressionMin": lambda: np.minimum(first, second),
                              "MaterialExpressionMax": lambda: np.maximum(first, second),
                              "MaterialExpressionDivide": lambda: first / second,
                              "MaterialExpressionSaturate": lambda: np.clip(incoming[""], 0, 1),
                              "MaterialExpressionLinearInterpolate": lambda: first * (1 - incoming["Alpha"]) + second * incoming["Alpha"]}
                values[name] = operations[kind]()
                pending.pop(name)
                processed = True
            if not processed:
                raise ValueError("Frozen graph is cyclic or disconnected")
    return values["cloth_blend"]


class InkContributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = adapter.read(encoding.FOLDER / "encoding_report.json")
        cls.fields = dict(np.load(encoding.CANDIDATE / "decomposition_fields.npz"))
        cls.context = adapter.source_inputs()

    def test_exact43_previous_packages_preserved(self):
        self.assertEqual(self.context["existing_package_count"], 43)
        self.assertNotEqual(self.context["destination"], adapter.previous.source_inputs()["destination"])

    def test_png_linear_quantization_bounds(self):
        ink = self.fields["protected_ink_contribution_linear"]
        decoded = encoding.decode(encoding.encode(ink))
        self.assertLessEqual(np.abs(decoded - ink).max(), .5 / 510)

    def test_png_roundtrip_and1240_semantic1239_nonzero(self):
        full = np.asarray(Image.open(self.report["contribution_texture"]["path"]).convert("RGB"))
        self.assertEqual(full.shape, (2048, 2048, 3))
        self.assertEqual(int(np.any(full != 0, axis=-1).sum()), 1239)
        self.assertEqual(self.report["semantic_support_texels_after"], 1240)
        self.assertEqual(self.report["quantized_to_zero"][0]["atlas_pixel"], [243, 197])

    def test_no_semantic_expansion(self):
        encoded = encoding.encode(self.fields["protected_ink_contribution_linear"])
        self.assertFalse(encoded[~self.fields["semantic_support"]].any())

    def test_color_encoding_difference_within_one_rgb8(self):
        for mode in ("blue", "red"):
            self.assertLessEqual(self.report["final_color_encoding_error_x6"][mode]["rgb8_max"], 1)

    def test_disabled_exactly_original(self):
        source = self.fields["source_linear"]
        for color in adapter.shared.TEAM_COLORS.values():
            np.testing.assert_array_equal(encoding.shader(source, np.ones_like(source), self.fields["guard"], color, 0), source)

    def test_noncloth_guard_zero_exactly_original(self):
        source = self.fields["source_linear"]
        np.testing.assert_array_equal(encoding.shader(source, np.ones_like(source), np.zeros(source.shape[:2]), [1, 0, 0]), source)

    def test_native_source_clamp_keeps_substrate_nonnegative(self):
        source = np.asarray([.05, .1, .08])
        ink = np.asarray([.4, .09, .6])
        self.assertTrue(np.all(source - np.minimum(source, ink) >= 0))

    def test_graph_numerically_matches_linear_formula(self):
        generator = np.random.default_rng(8246)
        for index in range(250):
            source, texture, color = generator.random((3, 3))
            guard, strength = float(index % 2), float(generator.uniform(-.25, 1.25))
            np.testing.assert_allclose(evaluate_graph(source, texture, guard, color, strength),
                                       encoding.shader(source, .5 * texture, guard, color, strength), atol=1e-14)

    def test_outside_ink_reduces_to_footprint_formula(self):
        source, color = np.array([.2, .3, .4]), np.array([.92, .16, .1])
        expected = color * np.dot(source, adapter.shared.LUMINANCE) / np.dot(color, adapter.shared.LUMINANCE)
        np.testing.assert_allclose(evaluate_graph(source, np.zeros(3), 1, color, 1), expected)

    def test_graph_unchanged_nearest_guard_and_single_root_lerp(self):
        with adapter.graph_contract():
            self.assertIn(("cloth_mask", "R", "masked_strength", "A"), adapter.shared.LINKS)
            self.assertIn(("base_color", "RGB", "cloth_blend", "A"), adapter.shared.LINKS)
            self.assertTrue(all(link not in adapter.shared.LINKS for link in adapter.REPLACED_LINKS))
            self.assertEqual(len(adapter.shared.LINKS), 22)
            pins = [(link[2], link[3]) for link in adapter.shared.LINKS]
            self.assertEqual(len(pins), len(set(pins)))

    def test_graph_contract_restores_after_failure(self):
        classes, links = adapter.base.WRAPPER_CLASSES, adapter.shared.LINKS
        with self.assertRaises(RuntimeError):
            with adapter.graph_contract():
                raise RuntimeError("test")
        self.assertIs(adapter.base.WRAPPER_CLASSES, classes)
        self.assertIs(adapter.shared.LINKS, links)

    def test_texture_noncolor_uncompressed_bilinear(self):
        unreal = SimpleNamespace(TextureCompressionSettings=SimpleNamespace(TC_GRAYSCALE="gray", TC_VECTOR_DISPLACEMENTMAP="rgba8"),
                                 TextureMipGenSettings=SimpleNamespace(TMGS_NO_MIPMAPS="none"),
                                 TextureFilter=SimpleNamespace(TF_NEAREST="nearest", TF_BILINEAR="bilinear"),
                                 TextureAddress=SimpleNamespace(TA_CLAMP="clamp"))
        values = adapter.contribution_settings(unreal)
        self.assertEqual(values["compression_settings"], "rgba8")
        self.assertFalse(values["srgb"])
        self.assertEqual(values["filter"], "bilinear")
        self.assertEqual(values["mip_gen_settings"], "none")

    def test_exact12_controls_same_calibrated_cameras(self):
        self.assertEqual(len(render.SHOTS), 12)
        for crop in ("wide", "flag", "side_flag"):
            self.assertEqual({item[1] for item in render.SHOTS if item[2] == crop}, {"original", "disabled", "blue", "red"})

    def test_initial_dump_adds_exactly_fifth_texture(self):
        instance = render.InkContributionReview.__new__(render.InkContributionReview)
        instance.required_paths = {"one", "two", "three", "four"}
        instance.context = {"result": {"contribution": "five"}}
        with patch.object(render.renderer.BaseReview, "request_dump", return_value="dump"):
            self.assertEqual(instance.request_dump("initial"), "dump")
            self.assertEqual(instance.required_paths, {"one", "two", "three", "four", "five"})

    def test_allfive_resident2048_or_reject(self):
        records = {str(index): {"maximum_allowed_size": [2048, 2048], "actual_resident_size": [2048, 2048]} for index in range(5)}
        self.assertTrue(render.renderer.textures_resident(records, set(records)))
        records["4"]["actual_resident_size"] = [1024, 1024]
        self.assertFalse(render.renderer.textures_resident(records, set(records)))

    def test_compressed_contribution_is_rejected(self):
        for invalid in ("PF_DXT1", "PF_BC7", "PF_G8"):
            with self.assertRaises(ValueError):
                render.validate_contribution_format({"ink": {"format": invalid}}, "ink")
        self.assertEqual(render.validate_contribution_format({"ink": {"format": "PF_B8G8R8A8"}}, "ink"), "PF_B8G8R8A8")

    def test_old_mixed_rgb_probe_requirement_explicitly_revised(self):
        self.assertEqual(len(self.report["actual_game_two_uv_predictions"]), 2)
        self.assertTrue(all("withdrawn explicitly" in item["former_all_four_neighbors_protection1_gate"] for item in self.report["actual_game_two_uv_predictions"]))

    def test_not_runtime_or_fullcloth_approval(self):
        self.assertFalse(self.report["actual_ue_execution_completed"])
        self.assertFalse(self.report["runtime_approved"])
        self.assertFalse(self.context["settings"]["all_cloth_coverage_approved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
