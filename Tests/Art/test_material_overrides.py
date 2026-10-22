import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("material_audit", ROOT / "Tools/inspect_art_materials.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class MaterialOverrideTests(unittest.TestCase):
    def test_nonmetallic_is_explicit_and_copied(self):
        source = {"Metallic": 0.0}
        result = audit.validate_material_overrides(source)
        self.assertEqual(source, result)
        self.assertIsNot(source, result)

    def test_unsupported_channels_rejected(self):
        with self.assertRaises(ValueError):
            audit.validate_material_overrides({"BaseColor": 0})

    def test_invalid_factors_rejected(self):
        for value in (True, -0.1, 1.1, float("nan"), float("inf"), "0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.validate_material_overrides({"Metallic": value})

    def test_no_override_is_noop_without_unreal(self):
        self.assertEqual([], audit.apply_material_overrides(None, [], {}, "/Game/ArtPilot/test"))


if __name__ == "__main__":
    unittest.main()
