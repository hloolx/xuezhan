"""Offline source-drift, preservation and truthful coverage tests."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ART = Path("RawAssets/Art/Tripo_v01")


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "Tools" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


briefs = module("build_champion_briefs")
coverage = module("audit_art_coverage")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root):
    for relative in [ART / "catalog.json", ART / "catalog_champions.json", ART / "pipeline.json",
                     Path("Content/Data/Champions.json"), Path("Source/CivWar/View/CWModels.cpp")]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


class ChampionBriefTests(unittest.TestCase):
    def test_generated_cards_preserve_existing_designs_and_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            protected = [root / ART / "catalog.json", root / ART / "jobs/execution.json",
                         root / ART / "prompts/Unit_StoneAxe/brief.json"]
            write(protected[1], {"assets": {"Unit_StoneAxe": {"task_id": "preserve_receipt"}}})
            write(protected[2], {"approved": "preserve original design"})
            original = {path: path.read_bytes() for path in protected}
            briefs.generate(root)
            self.assertEqual(0, briefs.generate(root, check=True)["changed"])
            for path, content in original.items():
                self.assertEqual(content, path.read_bytes())
            stone = briefs.read(root / ART / "prompts/Champion_Stone/brief.json")
            self.assertEqual(198, stone["dimensions"]["nominal_height_cm"])
            self.assertEqual("design_only_reference_required", stone["status"])
            self.assertFalse(stone["production_approved"])
            self.assertIsNone(stone["animation_contract"]["ability"]["cast_clip_seconds"])

    def test_gameplay_change_is_detected_and_regeneration_uses_new_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            briefs.generate(root)
            source = root / "Content/Data/Champions.json"
            rows = briefs.read(source)
            rows[0]["AttackWindup"] = 0.2
            write(source, rows)
            with self.assertRaisesRegex(ValueError, "Stale or missing"):
                briefs.generate(root, check=True)
            briefs.generate(root)
            card = briefs.read(root / ART / "prompts/Champion_Stone/brief.json")
            self.assertEqual(0.2, card["animation_contract"]["timing"]["release_seconds"])
            self.assertEqual(0.7, card["animation_contract"]["timing"]["recovery_budget_seconds"])
            self.assertEqual(briefs.digest(source), card["source"]["sha256"])

    def test_invalid_timing_or_projectile_change_requires_review(self):
        row = briefs.read(ROOT / "Content/Data/Champions.json")[0]
        for changes in [{"AttackWindup": row["AttackInterval"]}, {"AttackInterval": 0}, {"ProjectileSpeed": 100}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                briefs.timing({**row, **changes})

    def test_scale_follows_runtime_baseline_without_changing_collision_radius(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            source = root / "Source/CivWar/View/CWModels.cpp"
            source.write_text(source.read_text(encoding="utf-8").replace("const float Scale = 1.32f;", "const float Scale = 1.25f;"), encoding="utf-8")
            briefs.generate(root)
            card = briefs.read(root / ART / "prompts/Champion_Stone/brief.json")
            self.assertEqual(187.5, card["dimensions"]["nominal_height_cm"])
            self.assertEqual(45, card["dimensions"]["gameplay_radius_unchanged_cm"])

    def test_missing_champion_and_unknown_weapon_fail_before_writing(self):
        for change in ["missing", "dependency"]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture(root)
                path = root / ART / "catalog_champions.json"
                data = briefs.read(path)
                if change == "missing":
                    data["core"].pop()
                else:
                    data["core"][0]["modules"].append("Weapon_Unknown")
                write(path, data)
                with self.assertRaises(ValueError):
                    briefs.generate(root)
                self.assertFalse((root / ART / "prompts").exists())

    def test_catalog_coverage_does_not_claim_model_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            briefs.generate(root)
            for table in ("Units", "Turrets", "Ages"):
                write(root / "Content/Data" / (table + ".json"), [])
            write(root / ART / "jobs/execution.json", {"assets": {"Champion_Stone": {
                "status": "downloaded", "output_files": ["missing.glb"]}}})
            report = coverage.audit(root)
            self.assertEqual(5, report["counts"]["catalogued"])
            self.assertEqual(5, report["counts"]["with_design_brief"])
            self.assertEqual(0, report["counts"]["with_downloaded_model"])
            self.assertFalse(any(row["production_approved"] for row in report["assets"]))


if __name__ == "__main__":
    unittest.main()
