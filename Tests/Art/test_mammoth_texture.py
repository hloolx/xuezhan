import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_texture_under_test", ROOT / "Tools/Blender/inspect_mammoth_texture.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def seam_fixture():
    source = {"POSITION": np.array(((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0), (0, 0, 1), (1, 1, 1)), dtype=np.float32),
              "NORMAL": np.array(((0, 0, 1),) * 6, dtype=np.float32),
              "TEXCOORD_0": np.zeros((6, 2), dtype=np.float32), "indices": np.array(((0, 1, 2), (3, 4, 5)), dtype=np.uint32)}
    returned = {name: np.delete(value, 3, axis=0) for name, value in source.items() if name != "indices"}
    returned["indices"] = np.array(((0, 1, 2), (0, 3, 4)), dtype=np.uint32)
    return source, returned


class MammothTextureTests(unittest.TestCase):
    def test_full_surface_does_not_hide_split_identity_loss(self):
        source, returned = seam_fixture()
        comparison, _, mapping, _ = MODULE.triangle_mapping(source, returned)
        result = MODULE.split_identity(dict(enumerate(range(6))), [(0, 3)], mapping)
        self.assertTrue(comparison["surface_and_uv_passed"])
        self.assertFalse(comparison["render_vertex_bijection_preserved"])
        self.assertFalse(result["all_native_identities_preserved"])
        self.assertEqual(result["retained_split_pairs"], 0)

    def test_split_restoration_keeps_every_cloud_corner_attribute(self):
        source, returned = seam_fixture()
        _, corners, _, _ = MODULE.triangle_mapping(source, returned)
        repaired, record = MODULE.restore_split_arrays(returned, corners)
        self.assertEqual(record["added_vertices"], 1)
        for name in ("POSITION", "NORMAL", "TEXCOORD_0"):
            np.testing.assert_array_equal(repaired[name][repaired["indices"]], returned[name][returned["indices"]])
        comparison, _, mapping, _ = MODULE.triangle_mapping(source, repaired)
        self.assertTrue(comparison["render_vertex_bijection_preserved"])
        self.assertTrue(MODULE.split_identity(dict(enumerate(range(6))), [(0, 3)], mapping)["all_native_identities_preserved"])

    def test_reordered_vertices_and_triangles_pass(self):
        source, _ = seam_fixture()
        order = np.array((5, 3, 1, 0, 2, 4))
        inverse = np.argsort(order)
        returned = {name: values[order].copy() for name, values in source.items() if name != "indices"}
        returned["indices"] = inverse[source["indices"]][::-1]
        comparison, _, _, _ = MODULE.triangle_mapping(source, returned)
        self.assertTrue(comparison["render_vertex_bijection_preserved"])
        self.assertTrue(comparison["surface_and_uv_passed"])

    def test_winding_reversal_rejected(self):
        source, returned = seam_fixture()
        returned["indices"][1] = returned["indices"][1][::-1]
        comparison, _, _, _ = MODULE.triangle_mapping(source, returned)
        self.assertFalse(comparison["surface_and_uv_passed"])
        self.assertEqual(comparison["winding_reversed_faces"], [1])

    def test_missing_surface_rejected(self):
        source, returned = seam_fixture()
        returned["indices"] = returned["indices"][:1]
        with self.assertRaisesRegex(ValueError, "triangle correspondence"):
            MODULE.triangle_mapping(source, returned)

    def test_uv_change_cannot_pass(self):
        source, returned = seam_fixture()
        returned["TEXCOORD_0"][1, 0] = .001
        comparison, _, _, _ = MODULE.triangle_mapping(source, returned)
        self.assertFalse(comparison["surface_and_uv_passed"])

    def test_cloud_uniform_normalization_recovered(self):
        source, returned = seam_fixture()
        returned["POSITION"] = returned["POSITION"] / 2.5 - np.array((.1, .2, .3))
        comparison, _, _, _ = MODULE.triangle_mapping(source, returned)
        self.assertAlmostEqual(comparison["restore_uniform_scale"], 2.5)
        np.testing.assert_allclose(comparison["restore_gltf_y_up_translation_m"], (.25, .5, .75))
        self.assertTrue(comparison["surface_and_uv_passed"])

    def test_nonuniform_scale_cannot_be_silently_restored(self):
        source, returned = seam_fixture()
        returned["POSITION"][:, 0] *= 1.01
        with self.assertRaises(ValueError):
            MODULE.triangle_mapping(source, returned)

    def test_changed_normals_are_diagnostic_not_surface_failure(self):
        source, returned = seam_fixture()
        returned["NORMAL"][1] = (0, .01, np.sqrt(1 - .01 ** 2))
        comparison, _, _, rows = MODULE.triangle_mapping(source, returned)
        normals = MODULE.normal_diagnostic(source, returned, rows)
        self.assertTrue(comparison["surface_and_uv_passed"])
        self.assertGreater(normals["maximum_angular_change_degrees"], .5)
        self.assertEqual(normals["tested_triangle_corners"], 6)

    def test_degenerate_surface_normal_rejected(self):
        source, returned = seam_fixture()
        _, _, _, rows = MODULE.triangle_mapping(source, returned)
        returned["POSITION"][2] = returned["POSITION"][1]
        with self.assertRaisesRegex(ValueError, "Degenerate"):
            MODULE.normal_diagnostic(source, returned, rows)

    def test_encoded_glb_retains_existing_binary_bytes(self):
        source, _ = seam_fixture()
        original = b"frozen texture payload\x00\x00"
        document = {"asset": {"version": "2.0"}, "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {}}]}],
                    "buffers": [{"byteLength": len(original)}], "bufferViews": [], "accessors": []}
        encoded = MODULE.encode_glb(document, original, source)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.glb"
            path.write_bytes(encoded)
            actual_document, binary, actual = MODULE.core.read_glb(path)
            self.assertEqual(binary[:len(original)], original)
            for name in source:
                np.testing.assert_array_equal(actual[name], source[name])
            self.assertEqual(document["accessors"], [])
            self.assertEqual(actual_document["asset"]["version"], "2.0")

    def test_output_outside_owned_directory_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.fresh_output(MODULE.SOURCE.parent / "forbidden")

    def test_existing_evidence_cannot_be_overwritten(self):
        original = MODULE.OWNED
        with tempfile.TemporaryDirectory() as folder:
            MODULE.OWNED = Path(folder)
            evidence = Path(folder) / "existing"
            evidence.mkdir()
            try:
                with self.assertRaises(FileExistsError):
                    MODULE.fresh_output(evidence)
            finally:
                MODULE.OWNED = original

    def test_diagnostic_renderer_never_exports_or_modifies_normals(self):
        source = inspect.getsource(MODULE.render_diagnostic)
        for prohibited in ("export_scene", "write_bytes", "save_as_mainfile", "normals_split_custom_set", "restore_split_arrays"):
            self.assertNotIn(prohibited, source)
        self.assertIn("diagnostic_inputs()", source)
        self.assertIn('"model_exports_performed": 0', source)

    def test_failed_roundtrip_threshold_is_not_relaxed_for_diagnostics(self):
        source = inspect.getsource(MODULE.prepare_render)
        self.assertIn('roundtrip_comparison["maximum_normal_vector_change"] > 1e-4', source)
        self.assertIn('raise ValueError("Actual Blender roundtrip geometry/UV/index/normal gate failed")', source)


if __name__ == "__main__":
    unittest.main()
