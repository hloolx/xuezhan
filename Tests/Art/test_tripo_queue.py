"""Coverage, provenance and import-boundary checks; no Unreal or Tripo requests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "Tools" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


queue = module("build_tripo_queue")
importer = module("import_art_pilot")
character_views = module("prepare_character_views")
canonical_views = module("prepare_tripo_canonical_views")


class ProductionQueueTests(unittest.TestCase):
    def test_reference_preparation_recognizes_champions_without_touching_images(self):
        ids, catalog = character_views.character_catalog(ROOT)
        self.assertEqual(23, len(ids))
        for row in queue.read(ROOT / "Content/Data/Champions.json"):
            self.assertIn(row["VisualKey"], ids)
            self.assertEqual("human", catalog[row["VisualKey"]]["kind"])

    def test_tripo_canonical_side_mapping_copies_bytes_without_mirroring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "design/Tree"
            destination = root / "canonical/Tree"
            source.mkdir(parents=True)
            for name, color in [("front", "white"), ("right", "red"), ("back", "blue")]:
                image = Image.new("RGB", (1024, 1024), color)
                ImageDraw.Draw(image).rectangle([20, 30, 80, 190], fill="black")
                image.save(source / (name + ".png"))
            original = {"asset": "Tree", "files": {view: view + ".png" for view in ["front", "right", "back"]},
                        "project_required_views": ["front", "right", "back"], "production_approved": True,
                        "approval_scope": "reference pilot only"}
            canonical_views.write(source / "upload_manifest.json", original)
            canonical_views.write(source / "tripo_request.template.json", {"model": "test", "inputs": [{"right": "old"}]})
            source_hash = canonical_views.sha(source / "upload_manifest.json")
            canonical_views.prepare(source, destination, root, {"task_id": "test_probe"})
            self.assertEqual((source / "right.png").read_bytes(), (destination / "left.png").read_bytes())
            self.assertFalse((destination / "right.png").exists())
            output = canonical_views.read(destination / "upload_manifest.json")
            self.assertEqual(["front", "left", "back"], output["project_required_views"])
            self.assertEqual([], output["project_missing_views"])
            self.assertEqual("reference pilot only", output["approval_scope"])
            self.assertTrue(output["production_approved"])
            self.assertFalse(output["canonical_mapping_validation"]["approved"])
            request = canonical_views.read(destination / "tripo_request.template.json")
            self.assertEqual(["front", "left", "back"], [next(iter(item)) for item in request["inputs"]])
            self.assertEqual(source_hash, canonical_views.sha(source / "upload_manifest.json"))
            output["canonical_mapping_validation"] = {"status": "pilot_verified", "approved": True, "evidence": ["test"]}
            canonical_views.write(destination / "upload_manifest.json", output)
            canonical_views.prepare(source, destination, root, {"task_id": "test_probe"})
            self.assertTrue(canonical_views.read(destination / "upload_manifest.json")["canonical_mapping_validation"]["approved"])
            Image.new("RGB", (1024, 1024), "green").save(destination / "left.png")
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                canonical_views.prepare(source, destination, root, {"task_id": "test_probe"})

    def test_queue_uses_canonical_api_requirements_not_internal_card_directions(self):
        jobs = {job["asset_id"]: job for job in queue.build(ROOT)["jobs"]}
        tree = jobs["Env_Broadleaf"]
        self.assertEqual(["front", "left", "back"], tree["inputs"]["required_views"])
        self.assertEqual([], tree["inputs"]["missing_views"])
        self.assertTrue(all("prepared_tripo_canonical" in path for path in tree["inputs"]["images"].values()))
        self.assertEqual("tripo_api_canonical_probe_e175fe52", tree["inputs"]["view_convention"])

    def test_canonical_dcc_and_deferred_templates_never_gain_api_inputs(self):
        folder = ROOT / "RawAssets/Art/Tripo_v01/prepared_tripo_canonical"
        jobs = {job["asset_id"]: job for job in queue.build(ROOT)["jobs"]}
        for aid in ["Turret_RockTower", "Turret_ArrowTower", "Turret_Ballista", "Prop_EconomyMine"]:
            template = canonical_views.read(folder / aid / "tripo_request.template.json")
            self.assertTrue(template["disabled"])
            self.assertNotIn("inputs", template)
            self.assertIsNone(jobs[aid]["request_preset"])
        self.assertEqual("deferred", jobs["Prop_EconomyMine"]["route"])
        for aid in ["Turret_Cannon", "Turret_Autocannon", "Prop_DemolitionPack"]:
            template = canonical_views.read(folder / aid / "tripo_request.template.json")
            self.assertEqual(["front", "left", "back"], [next(iter(item)) for item in template["inputs"]])
            self.assertIn("model", template)
            self.assertFalse(jobs[aid]["inputs"]["reference_approved"])

    def test_approved_character_pixels_are_frozen_even_with_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "prepared"
            folder = output / "ApprovedCharacter"
            folder.mkdir(parents=True)
            names = ["front", "right", "back", "left"]
            views = [{"view": name, "region": [0, 0, 10, 10], "height_reference_y": [1, 9],
                      "baseline_px": 942, "normalized_reference_height_px": 840,
                      "scale_uniform_xy": 1.0, "upsampled": False} for name in names]
            asset = {"id": "ApprovedCharacter", "source": "source.png", "source_sha256": "source_hash",
                     "expected_source_size": [20, 20], "generation_preset": "p2_character_geometry", "views": views}
            prior = {"status": "prepared_needs_visual_review", "source_sha256": "source_hash", "views": []}
            for name in names:
                path = folder / (name + ".png")
                Image.new("RGB", (1024, 1024), "white").save(path)
                prior["views"].append({"file": path.relative_to(root).as_posix(), "sha256": character_views.digest(path)})
            Image.new("RGB", (10, 10), "white").save(folder / "contact_sheet.jpg")
            character_views.write(folder / "split_report.json", {"source_sha256": "source_hash", "views": views})
            character_views.write(folder / "tripo_request.template.json", character_views.split.request_template(names, "p2_character_geometry"))
            character_views.write(folder / "upload_manifest.json", {"production_approved": True, "approval_scope": "first pilot only", "project_missing_views": []})
            with patch.object(character_views, "ROOT", root), patch.object(character_views, "OUTPUT", output):
                self.assertTrue(character_views.reuse_or_protect_approval(asset, prior, force=True))
                character_views.verify_outputs(asset)
                manifest = character_views.read(folder / "upload_manifest.json")
                self.assertTrue(manifest["production_approved"])
                self.assertEqual("first pilot only", manifest["approval_scope"])
                self.assertEqual("source_hash", manifest["approved_source_sha256"])
                Image.new("RGB", (1024, 1024), "red").save(folder / "front.png")
                with self.assertRaisesRegex(ValueError, "Approved/submitted inputs are frozen"):
                    character_views.reuse_or_protect_approval(asset, prior, force=True)
                with self.assertRaisesRegex(ValueError, "Approved output pixels changed"):
                    character_views.verify_outputs(asset)

    def test_character_split_uses_real_off_center_gutter(self):
        sheet = Image.new("RGB", (1200, 1200), "white")
        draw = ImageDraw.Draw(sheet)
        for x in [120, 800]:
            draw.rectangle([x, 20, x + 160, 570], fill="brown")
            draw.rectangle([x, 610, x + 160, 1170], fill="brown")
        separator, gap = character_views.blank_separator(sheet, 1)
        self.assertGreater(separator, 570)
        self.assertLess(separator, 610)
        self.assertNotEqual(separator, 600)
        self.assertGreaterEqual(gap[1] - gap[0], 6)

    def test_character_split_rejects_crossing_content(self):
        sheet = Image.new("RGB", (1200, 1200), "white")
        ImageDraw.Draw(sheet).rectangle([250, 440, 950, 760], fill="brown")
        with self.assertRaisesRegex(ValueError, "No safe empty horizontal gutter"):
            character_views.blank_separator(sheet, 1)

    def test_source_coverage_and_environment_priority(self):
        result = queue.build(ROOT)
        self.assertEqual((15, 5, 9), tuple(result["counts"][k] for k in ("units", "bases", "turrets")))
        self.assertEqual(5, result["counts"]["champions"])
        self.assertEqual(68, result["counts"]["total"])
        self.assertTrue(all(j["kind"] == "environment" for j in result["jobs"][:9]))

    def test_rider_and_arrow_assembly_dependencies(self):
        jobs = {j["asset_id"]: j for j in queue.build(ROOT)["jobs"]}
        self.assertEqual({"Mount_Warhorse", "Weapon_Lance", "Weapon_RoundShield"}, set(jobs["Unit_Knight"]["assembly_dependencies"]))
        self.assertTrue({"Crew_Archer", "Weapon_Bow"}.issubset(jobs["Turret_ArrowTower"]["assembly_dependencies"]))
        self.assertFalse(jobs["Mount_Mammoth"]["assembly_dependencies"])
        self.assertEqual("p2_mount_geometry", jobs["Mount_Mammoth"]["request_preset"])

    def test_champions_keep_source_timing_era_and_independent_equipment(self):
        result = queue.build(ROOT)
        jobs = {job["asset_id"]: job for job in result["jobs"]}
        positions = {job["asset_id"]: i for i, job in enumerate(result["jobs"])}
        for row in queue.read(ROOT / "Content/Data/Champions.json"):
            job = jobs[row["VisualKey"]]
            self.assertEqual(10 + row["Age"] * 10, job["order_key"][0])
            self.assertEqual(["idle", "move", "attack", "hit", "death"], job["required_clips"])
            self.assertEqual(row["AttackWindup"], job["timing"]["release_seconds"])
            self.assertEqual(row["AttackInterval"], job["timing"]["cycle_seconds"])
            self.assertFalse(job["timing"]["client_notify_causes_damage"])
            self.assertIn("missing_reference_views", job["blockers"])
            self.assertIn("reference_review_pending", job["blockers"])
            self.assertNotIn("gameplay_contract_stale", job["blockers"])
            self.assertNotIn("design_contract_stale", job["blockers"])
            self.assertFalse(job["production_approved"])
            for dependency in job["assembly_dependencies"]:
                self.assertLess(positions[dependency], positions[job["asset_id"]])
        self.assertEqual(["Weapon_ChampionLongsword", "Weapon_KiteShield"], jobs["Champion_Medieval"]["assembly_dependencies"])
        self.assertEqual(["Weapon_EnergyBlade"], jobs["Champion_Future"]["assembly_dependencies"])

    def test_stale_champion_source_blocks_generation(self):
        original_read = queue.read

        def stale_read(path, default=None):
            value = original_read(path, default)
            if path.name == "brief.json" and path.parent.name == "Champion_Stone":
                value["source"]["sha256"] = "old_gameplay_data"
            return value

        with patch.object(queue, "read", side_effect=stale_read):
            job = next(job for job in queue.build(ROOT)["jobs"] if job["asset_id"] == "Champion_Stone")
        self.assertEqual("gameplay_contract_stale", job["status"])
        self.assertIn("gameplay_contract_stale", job["blockers"])

    def test_geometry_first_and_no_fabricated_submissions(self):
        result = queue.build(ROOT)
        self.assertFalse(result["submitted_by_this_script"])
        for job in result["jobs"]:
            if job["provider"] == "Tripo":
                self.assertFalse(job["request_parameters"]["pbr"])
                self.assertFalse(job["request_parameters"]["texture"])
            self.assertFalse(job["production_approved"])

    def test_invalid_dependency_graph_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown dependency"):
            queue.validate_dependencies([{"asset_id": "A", "assembly_dependencies": ["B"]}])
        with self.assertRaisesRegex(ValueError, "Cyclic dependency"):
            queue.validate_dependencies([{"asset_id": "A", "assembly_dependencies": ["B"]},
                                         {"asset_id": "B", "assembly_dependencies": ["A"]}])

    def test_import_destination_is_isolated_and_changes_with_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "asset.fbx").write_bytes(b"test source")
            path = root / "manifest.json"
            manifest = {"batch_id": "environment_v01", "assets": [{"id": "Env_Pine", "file": "asset.fbx"}]}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            _, first = importer.load_manifest(path, root)
            self.assertTrue(first[0]["destination"].startswith("/Game/ArtPilot/environment_v01/Env_Pine/"))
            manifest["assets"][0]["import_scale"] = 2
            path.write_text(json.dumps(manifest), encoding="utf-8")
            _, second = importer.load_manifest(path, root)
            self.assertNotEqual(first[0]["destination"], second[0]["destination"])
            manifest["batch_id"] = "../../Art"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                importer.load_manifest(path, root)

    def test_import_preflight_rejects_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "manifest.json"
            path.write_text(json.dumps({"batch_id": "environment_v01", "assets": [{"id": "Env_Pine", "file": "missing.fbx"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing or unsupported"):
                importer.load_manifest(path, root)

    def test_runtime_map_cooks_only_verified_mothers_and_preserves_settings(self):
        ids = ["Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf", "Env_GrassClump"]
        results = []
        for aid in ids:
            folder = "/Game/ArtPilot/environment_v01/" + aid + "/habc"
            results.append({"id": aid, "status": "imported", "warnings": [], "expected_dimensions_cm": [10, 20, 30],
                            "source": "source.fbx", "source_sha256": "abc", "destination": folder,
                            "assets": [{"type": "static_mesh", "path": folder + "/" + aid + "." + aid,
                                        "dimensions_cm": [10, 20, 30], "origin_cm": [0, 0, 15], "triangles_lod0": 100}]})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Config").mkdir()
            config = root / "Config/DefaultGame.ini"
            config.write_text('[/Script/UnrealEd.ProjectPackagingSettings]\nUsePakFile=True\n[OtherSettings]\nValue=Retain\n', encoding="utf-8")
            importer.write_environment_runtime_map({"batch_id": "environment_v01"}, results, root)
            first = config.read_text(encoding="utf-8")
            importer.write_environment_runtime_map({"batch_id": "environment_v01"}, results, root)
            self.assertEqual(first, config.read_text(encoding="utf-8"))
            self.assertEqual(7, first.count("+DirectoriesToAlwaysCook="))
            self.assertNotIn("Preview_", first)
            self.assertIn("[OtherSettings]\nValue=Retain", first)
            self.assertLess(first.index("END CIVWAR ENVIRONMENT ART COOK"), first.index("[OtherSettings]"))
            results[0]["warnings"] = ["dimensions_differ_over_5_percent_check_scale_and_axis"]
            with self.assertRaisesRegex(ValueError, "clean single static mesh"):
                importer.write_environment_runtime_map({"batch_id": "environment_v01"}, results, root)


if __name__ == "__main__":
    unittest.main()
