import argparse
import ast
from contextlib import redirect_stderr
import io
import json
import math
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Tools/Blender/prepare_tripo_character.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
PURE_NAMES = {"parse_options", "validate_io", "height_contract", "overview_views"}
PURE = ast.Module(body=[node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in PURE_NAMES], type_ignores=[])
ART = ROOT / "RawAssets/Art/Tripo_v01"
NAMESPACE = {"__doc__": "Offline character argument validation", "argparse": argparse, "Path": Path,
             "re": re, "math": math, "json": json, "ART": ART,
             "DEFAULT_SOURCE": ART / "tripo_raw/Unit_StoneAxe/v01/model.fbx",
             "DEFAULT_OUTPUT": ART / "tripo_processed/characters_geometry_v01/Unit_StoneAxe",
             "AXES": dict.fromkeys(["+X", "-X", "+Y", "-Y"])}
exec(compile(PURE, str(SOURCE), "exec"), NAMESPACE)
parse_options = NAMESPACE["parse_options"]
validate_io = NAMESPACE["validate_io"]
height_contract = NAMESPACE["height_contract"]


class CharacterPrepareOptionsTests(unittest.TestCase):
    def test_stoneaxe_legacy_inspection_defaults(self):
        args = parse_options([])
        self.assertEqual("Unit_StoneAxe", args.asset_id)
        self.assertEqual(150.0, args.height_cm)
        self.assertEqual(512, args.render_size)
        self.assertEqual(24, args.samples)
        self.assertEqual("legacy", args.render_profile)
        self.assertEqual(NAMESPACE["DEFAULT_SOURCE"].resolve(), args.source)
        self.assertEqual(NAMESPACE["DEFAULT_OUTPUT"].resolve(), args.output)
        self.assertIn("1.0f", height_contract(args)["formula"])

    def test_stoneaxe_legacy_prepare_size(self):
        args = parse_options(["--mode", "prepare", "--source-front-axis", "+Y", "--orientation-evidence", "Actual four views reviewed"])
        self.assertEqual(1024, args.render_size)
        self.assertEqual(24, args.samples)

    def test_slinger_explicit_height_and_low_resource_settings(self):
        evidence = "CWModels.cpp:335,605,611;150cm *0.95 =142.5cm"
        args = parse_options(["--asset-id", "Unit_StoneSlinger", "--height-cm", "142.5", "--height-evidence", evidence,
                              "--render-size", "512", "--samples", "8"])
        self.assertEqual(142.5, args.height_cm)
        self.assertEqual(8, args.samples)
        self.assertIn("Unit_StoneSlinger", args.source.parts)
        self.assertEqual("Unit_StoneSlinger", args.output.name)
        self.assertEqual(evidence, height_contract(args)["evidence"])
        self.assertNotIn("formula", height_contract(args))

    def test_nonstoneaxe_requires_height_evidence(self):
        for evidence in ([], ["--height-evidence", "   "]):
            with self.assertRaisesRegex(ValueError, "height-evidence"):
                parse_options(["--asset-id", "Unit_StoneSlinger"] + evidence)

    def test_mount_requires_explicit_height_and_evidence(self):
        with self.assertRaisesRegex(ValueError, "explicit height-cm"):
            parse_options(["--asset-id", "Mount_Mammoth", "--height-evidence", "Pending exact source dimensions"])
        with self.assertRaisesRegex(ValueError, "height-evidence"):
            parse_options(["--asset-id", "Mount_Mammoth", "--height-cm", "300"])

    def test_mount_defaults_to_overview_and_mount_specific_directory(self):
        args = parse_options(["--asset-id", "Mount_Mammoth", "--height-cm", "300", "--height-evidence", "Unit test fixture only, not production size approval"])
        self.assertTrue(args.is_mount)
        self.assertEqual("overview", args.render_profile)
        self.assertIn("mounts_geometry_v01", args.output.parts)
        self.assertEqual(300.0, height_contract(args)["height_cm"])
        self.assertNotIn("formula", height_contract(args))
        with self.assertRaisesRegex(ValueError, "biped hand/foot"):
            parse_options(["--asset-id", "Mount_Mammoth", "--height-cm", "300", "--height-evidence", "Fixture", "--render-profile", "legacy"])

    def test_mount_path_injection_rejected(self):
        for asset in ("Mount_../Mammoth", "Mount_A\\B", "Mount_", "Mount_A:C", "Mount_A\n"):
            with self.subTest(asset=asset), self.assertRaisesRegex(ValueError, "safe Unit_"):
                parse_options(["--asset-id", asset, "--height-cm", "300", "--height-evidence", "Fixture"])

    def test_nondefault_stoneaxe_height_cannot_reuse_default_evidence(self):
        with self.assertRaisesRegex(ValueError, "height-evidence"):
            parse_options(["--height-cm", "142.5"])

    def test_asset_path_injection_is_rejected(self):
        for asset in ("../Unit_StoneAxe", "Unit_A/../../B", "Unit_A\\B", "Unit_A:C", "Unit_A.", "Unit_A B", "Unit_", "Unit_石斧", "Unit_A\n", "Unit_" + "A" * 65):
            with self.subTest(asset=asset), self.assertRaisesRegex(ValueError, "safe Unit_"):
                parse_options(["--asset-id", asset])

    def test_nonfinite_or_unreasonable_height_rejected(self):
        for height in ("nan", "inf", "-1", "0", "1001"):
            with self.subTest(height=height), self.assertRaisesRegex(ValueError, "finite"):
                parse_options(["--height-cm", height, "--height-evidence", "Explicit but invalid"])

    def test_resource_caps(self):
        for samples in ("0", "-1", "33", "4096"):
            with self.subTest(samples=samples), self.assertRaisesRegex(ValueError, "samples"):
                parse_options(["--samples", samples])
        for size in ("128", "2048", "4096"):
            with self.subTest(size=size), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_options(["--render-size", size])

    def test_overview_profile_has_all_four_sides_and_one_preview(self):
        args = parse_options(["--render-profile", "overview"])
        self.assertEqual("overview", args.render_profile)
        views = NAMESPACE["overview_views"]()
        self.assertEqual(["front", "right", "back", "left", "preview"], [name for name, direction in views])
        self.assertEqual({(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)}, {direction for name, direction in views[:4]})
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_options(["--render-profile", "all_200"])

    def test_prepare_requires_actual_axis_review(self):
        for arguments in (["--mode", "prepare"], ["--mode", "prepare", "--source-front-axis", "+X", "--orientation-evidence", " "]):
            with self.assertRaisesRegex(ValueError, "Inspect axis renders"):
                parse_options(arguments)

    def test_existing_output_is_not_reused_even_if_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.glb"
            source.write_bytes(b"original")
            (root / "task.json").write_text('{"task_id":"existing-task"}')
            output = root / "inspection"
            output.mkdir()
            args = parse_options(["--source", str(source), "--output", str(output)])
            with self.assertRaisesRegex(FileExistsError, "new output directory"):
                validate_io(args)
            self.assertEqual(b"original", source.read_bytes())
            self.assertEqual([], list(output.iterdir()))

    def test_new_output_and_receipt_validation_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.fbx"
            source.write_bytes(b"original")
            output = root / "new"
            args = parse_options(["--source", str(source), "--output", str(output)])
            with self.assertRaises(FileNotFoundError):
                validate_io(args)
            self.assertFalse(output.exists())
            (root / "task.json").write_text('{"task_id":"existing-task"}', encoding="utf-8-sig")
            self.assertEqual("existing-task", validate_io(args)["task_id"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
