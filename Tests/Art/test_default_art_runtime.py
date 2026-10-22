import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


def read_config(name):
    return json.loads((ROOT / "Content/Data" / name).read_text(encoding="utf-8-sig"))


def object_paths(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.startswith("rejected_") or key == "evidence":
                continue
            yield from object_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from object_paths(item)
    elif isinstance(value, str) and re.fullmatch(r"/Game/ArtPilot/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+", value):
        yield value.split(".")[0]


class DefaultArtRuntimeTests(unittest.TestCase):
    def test_all_default_mesh_material_and_clip_packages_exist_and_are_cooked(self):
        config = (ROOT / "Config/DefaultGame.ini").read_text(encoding="utf-8-sig")
        directories = re.findall(r'\+DirectoriesToAlwaysCook=\(Path="([^"]+)"\)', config)
        packages = set()
        for name in ("EnvironmentArt.json", "EnvironmentArtLegacy.json", "UnitArtPilot.json", "BaseArtPilot.json", "TurretArtPilot.json"):
            packages.update(object_paths(read_config(name)))
        self.assertGreaterEqual(len(packages), 30)
        for package in packages:
            with self.subTest(package=package):
                path = ROOT / "Content" / (package.removeprefix("/Game/") + ".uasset")
                self.assertTrue(path.is_file(), str(path))
                self.assertTrue(any(package.startswith(directory.rstrip("/") + "/") for directory in directories), package)

    def test_default_enablement_does_not_claim_complete_production(self):
        for name in ("EnvironmentArt.json", "UnitArtPilot.json", "BaseArtPilot.json", "TurretArtPilot.json"):
            with self.subTest(config=name):
                config = read_config(name)
                self.assertTrue(config["default_runtime_enabled"])
                self.assertFalse(config["production_approved"])

    def test_experimental_wood_material_is_not_in_default_configs(self):
        for name in ("EnvironmentArt.json", "UnitArtPilot.json", "BaseArtPilot.json", "TurretArtPilot.json"):
            self.assertNotIn("/Game/ArtPilot/RockTowerWood/", json.dumps(read_config(name)))

    def test_character_and_turret_default_scope_stays_exact(self):
        self.assertEqual("Unit_StoneAxe", read_config("UnitArtPilot.json")["asset_id"])
        self.assertEqual("Base_Stone", read_config("BaseArtPilot.json")["asset_id"])
        self.assertEqual("Turret_RockTower", read_config("TurretArtPilot.json")["asset_id"])


if __name__ == "__main__":
    unittest.main()
