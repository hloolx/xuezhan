import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("assembly", ROOT / "Tools/assemble_tripo_environment.py")
assembly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assembly)


class EnvironmentAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.selection = {"batch_id": "test_environment", "assets": []}
        for asset_id in sorted(assembly.REQUIRED):
            folder = self.root / "RawAssets/Art/Tripo_v01/tripo_processed" / asset_id
            folder.mkdir(parents=True)
            model = folder / "model.glb"
            model.write_bytes(b"fixture mesh")
            image = folder / "image.png"
            image.write_bytes(b"fixture image")
            inspection = folder / "inspection.json"
            inspection.write_text(json.dumps({"glb_roundtrip": {"pass": True}}))
            approval = folder / "approval.json"
            approval.write_text(json.dumps({"asset_id": asset_id, "approved_for_ue_import": True,
                "model_sha256": assembly.digest(model), "reviewed_views": {
                    view: {"file": image.relative_to(self.root).as_posix(), "sha256": assembly.digest(image)}
                    for view in ("front", "left", "back", "right")}}))
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps({"assets": [{"id": asset_id, "file": model.relative_to(self.root).as_posix(),
                "source": "tripo_generated_processed_in_blender", "source_stage": "textured",
                "inspection": inspection.relative_to(self.root).as_posix(), "production_approved": True,
                "textures": [{"file": image.relative_to(self.root).as_posix(), "sha256": assembly.digest(image)}]}]}))
            self.selection["assets"].append({"id": asset_id, "manifest": manifest.relative_to(self.root).as_posix(),
                "approval": approval.relative_to(self.root).as_posix()})

    def test_complete_selection_never_claims_gameplay_approval(self):
        result = assembly.assemble(self.selection, self.root)
        self.assertEqual(7, len(result["assets"]))
        self.assertTrue(all(item["production_approved"] is False for item in result["assets"]))
        self.assertFalse((self.root / "Content/Data/EnvironmentArt.json").exists())

    def test_missing_mother_rejected(self):
        self.selection["assets"].pop()
        with self.assertRaisesRegex(ValueError, "Exactly seven"):
            assembly.assemble(self.selection, self.root)

    def test_partial_review_explicitly_defers_grass_without_approving_it(self):
        grass = next(item for item in self.selection["assets"] if item["id"] == "Env_GrassClump")
        (self.root / grass["approval"]).unlink()
        with self.assertRaises(FileNotFoundError):
            assembly.assemble(self.selection, self.root)
        result = assembly.assemble(self.selection, self.root, partial_review=True)
        self.assertTrue(result["partial_review_only"])
        self.assertEqual(["Env_GrassClump"], result["deferred_assets"])
        self.assertEqual(6, len(result["assets"]))
        self.assertNotIn("Env_GrassClump", {item["id"] for item in result["assets"]})
        self.assertFalse((self.root / "Content/Data/EnvironmentArt.json").exists())

    def test_partial_review_does_not_relax_other_asset_approval(self):
        selected = next(item for item in self.selection["assets"] if item["id"] == "Env_Pine")
        path = self.root / selected["approval"]
        approval = assembly.read(path)
        approval["approved_for_ue_import"] = False
        path.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "visual approval"):
            assembly.assemble(self.selection, self.root, partial_review=True)

    def test_unreviewed_rejected(self):
        path = self.root / self.selection["assets"][0]["approval"]
        value = assembly.read(path)
        value["approved_for_ue_import"] = False
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "visual approval"):
            assembly.assemble(self.selection, self.root)

    def test_mesh_changed_after_review_rejected(self):
        manifest = assembly.read(self.root / self.selection["assets"][0]["manifest"])
        (self.root / manifest["assets"][0]["file"]).write_bytes(b"modified mesh")
        with self.assertRaisesRegex(ValueError, "Reviewed mesh changed"):
            assembly.assemble(self.selection, self.root)

    def test_image_changed_after_review_rejected(self):
        approval = assembly.read(self.root / self.selection["assets"][0]["approval"])
        (self.root / approval["reviewed_views"]["front"]["file"]).write_bytes(b"modified render")
        with self.assertRaisesRegex(ValueError, "Reviewed image changed"):
            assembly.assemble(self.selection, self.root)

    def test_material_override_changed_after_review_rejected(self):
        path = self.root / self.selection["assets"][0]["approval"]
        approval = assembly.read(path)
        approval["runtime_material_overrides"] = {"Metallic": 0}
        path.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "material overrides changed"):
            assembly.assemble(self.selection, self.root)

    def test_additional_preview_is_validated_without_replacing_four_directions(self):
        path = self.root / self.selection["assets"][0]["approval"]
        approval = assembly.read(path)
        approval["reviewed_views"]["preview"] = dict(approval["reviewed_views"]["front"])
        path.write_text(json.dumps(approval))
        self.assertEqual(7, len(assembly.assemble(self.selection, self.root)["assets"]))
        del approval["reviewed_views"]["back"]
        path.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "Four reviewed"):
            assembly.assemble(self.selection, self.root)

    def test_legacy_view_records_require_all_directions_and_unique_names(self):
        path = self.root / self.selection["assets"][0]["approval"]
        approval = assembly.read(path)
        approval["views"] = [dict(record, view=name) for name, record in approval.pop("reviewed_views").items()]
        path.write_text(json.dumps(approval))
        self.assertEqual(7, len(assembly.assemble(self.selection, self.root)["assets"]))
        approval["views"].append(dict(approval["views"][0]))
        path.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "Duplicate reviewed"):
            assembly.assemble(self.selection, self.root)


if __name__ == "__main__":
    unittest.main()
