"""Regression checks for asset loss, distortion and Tripo view association."""
import unittest

from PIL import Image, ImageDraw
from Tools.split_multiview import normalize_views, request_template, flatten_edge_background


class SplitMultiviewTests(unittest.TestCase):
    def sheet(self):
        sheet = Image.new("RGB", (1100, 400), "white")
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((40, 100, 139, 299), fill="#554433")
        draw.rectangle((250, 100, 749, 299), fill="#554433")
        draw.rectangle((920, 100, 1019, 299), fill="#554433")
        views = [{"view": "front", "region": [0, 0, 200, 400]},
                 {"view": "right", "region": [200, 0, 850, 400]},
                 {"view": "back", "region": [850, 0, 1100, 400]}]
        return sheet, views

    def test_wide_side_sets_scale_for_all_views_without_clipping_or_stretch(self):
        sheet, views = self.sheet()
        images, report = normalize_views(sheet, views)
        self.assertEqual({im.size for im in images.values()}, {(1024, 1024)})
        self.assertEqual(len({r["normalized_reference_height_px"] for r in report}), 1)
        self.assertEqual(len({r["baseline_px"] for r in report}), 1)
        self.assertLess(report[0]["normalized_reference_height_px"], 500)
        for r in report:
            x, y = r["paste_xy"]
            w, h = r["resized_crop_size"]
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x+w, 1024)
            self.assertLessEqual(y+h, 1024)
            b = r["crop_box"]
            self.assertAlmostEqual(w/h, (b[2]-b[0])/(b[3]-b[1]), delta=0.02)

    def test_cut_object_is_rejected(self):
        sheet, views = self.sheet()
        views[1]["region"][0] = 300
        with self.assertRaisesRegex(ValueError, "touches ROI edge"):
            normalize_views(sheet, views)

    def test_blank_sheet_is_rejected(self):
        _, views = self.sheet()
        with self.assertRaisesRegex(ValueError, "No visible object"):
            normalize_views(Image.new("RGB", (1100, 400), "white"), views)

    def test_named_right_is_not_assigned_to_left(self):
        request = request_template(["front", "right", "back"])
        self.assertEqual([next(iter(v)) for v in request["inputs"]], ["front", "back", "right"])
        self.assertNotIn("left", {k for v in request["inputs"] for k in v})

    def test_character_route_uses_p2_and_disables_pbr_texture_override(self):
        request = request_template(["front", "right", "back", "left"], "p2_character_geometry")
        self.assertEqual(request["model"], "P2-20260801")
        self.assertTrue(request["quad"])
        self.assertFalse(request["texture"])
        self.assertFalse(request["pbr"])
        self.assertEqual([next(iter(v)) for v in request["inputs"]], ["front", "left", "back", "right"])

    def test_unknown_preset_cannot_silently_fall_back_to_h(self):
        with self.assertRaisesRegex(ValueError, "Unknown generation preset"):
            request_template(["front", "right"], "typo_p2")

    def test_request_rejects_missing_front_and_duplicate_views(self):
        for views in (["left", "back"], ["front", "front"], ["front", "top"]):
            with self.subTest(views=views), self.assertRaises(ValueError):
                request_template(views)

    def test_background_flatten_retains_enclosed_light_detail(self):
        image = Image.new("RGB", (80, 80), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 60, 60), outline="black", width=6)
        cleaned = flatten_edge_background(image, (255, 255, 255), (250, 249, 246))
        self.assertEqual(cleaned.getpixel((0, 0)), (250, 249, 246))
        self.assertEqual(cleaned.getpixel((40, 40)), (255, 255, 255))
        self.assertEqual(cleaned.getpixel((22, 22)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
