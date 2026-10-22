import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("art_import", ROOT / "Tools/import_art_pilot.py")
art_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(art_import)


class RuntimeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "Content/Data").mkdir(parents=True)
        (self.root / "Config").mkdir()
        self.mapping = self.root / "Content/Data/EnvironmentArt.json"
        self.config = self.root / "Config/DefaultGame.ini"
        self.mapping.write_bytes(b'{"status":"previous"}\r\n')
        self.config.write_bytes(b'[/Script/UnrealEd.ProjectPackagingSettings]\r\nbUnrelatedSetting=True\r\n')
        self.results = []
        for asset_id in ("Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf", "Env_GrassClump"):
            destination = "/Game/ArtPilot/test/" + asset_id
            self.results.append({"id": asset_id, "status": "imported", "warnings": [],
                "expected_dimensions_cm": [100, 100, 100], "source": "processed/source.glb",
                "source_sha256": "fixture", "destination": destination,
                "runtime_material_overrides": {"Metallic": 0},
                "assets": [{"type": "static_mesh", "path": destination + "/mesh.mesh",
                    "dimensions_cm": [100, 100, 100], "origin_cm": [0, 0, 50], "triangles_lod0": 12}]})

    def test_registration_preserves_backups_and_non_art_config(self):
        originals = {path: path.read_bytes() for path in (self.mapping, self.config)}
        report = art_import.write_environment_runtime_map({"batch_id": "test"}, self.results, self.root)
        self.assertEqual(2, len(report["backups"]))
        for row in report["backups"]:
            self.assertEqual(originals[Path(row["original"])], Path(row["backup"]).read_bytes())
        self.assertIn("bUnrelatedSetting=True", self.config.read_text())
        document = json.loads(self.mapping.read_text())
        self.assertFalse(document["production_approved"])
        self.assertEqual(7, len(document["assets"]))
        self.assertEqual({"Metallic": 0}, document["assets"]["Env_Shrub"]["runtime_material_overrides"])

    def test_warning_prevents_all_runtime_writes(self):
        self.results[-1]["warnings"] = ["material_audit_requires_review"]
        before = self.mapping.read_bytes(), self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, "clean single"):
            art_import.write_environment_runtime_map({"batch_id": "test"}, self.results, self.root)
        self.assertEqual(before, (self.mapping.read_bytes(), self.config.read_bytes()))

    def test_incomplete_batch_prevents_runtime_writes(self):
        before = self.mapping.read_bytes(), self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, "all seven"):
            art_import.write_environment_runtime_map({"batch_id": "test"}, self.results[:-1], self.root)
        self.assertEqual(before, (self.mapping.read_bytes(), self.config.read_bytes()))


if __name__ == "__main__":
    unittest.main()
