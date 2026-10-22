import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stone_era_art", ROOT / "Tools/stone_era_art.py")
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)


def asset():
    return {
        "asset_id": "Unit_StoneSlinger", "enabled": True, "preview_enabled": True,
        "ue_structural_approved": True, "animation_contract_verified": True,
        "attack_style": "Throw", "height_cm": 142.5, "contact_time": 0.45,
        "reference_move_speed": 160, "muzzle_part": "body", "muzzle_socket": "sling_release",
        "parts": [{"id": "body", "skeletal_mesh": "/Game/ArtPilot/Test/SK.SK",
                   "animations": {key: f"/Game/ArtPilot/Test/AN_{key}.AN_{key}" for key in ART.CLIPS}}],
        "attachments": [],
    }


class StoneEraContractTests(unittest.TestCase):
    def validate(self, config):
        return ART.validate_asset(ROOT, "Unit_StoneSlinger", config, {"AttackWindup": .45, "MoveSpeed": 160}, lambda _, path: path)

    def test_imported_flexible_sling_can_share_the_body_skeleton(self):
        self.assertEqual(6, len(self.validate(asset())))

    def test_contact_cannot_change_gameplay_timing(self):
        item = asset()
        item["contact_time"] = .35
        with self.assertRaisesRegex(ValueError, "AttackWindup"):
            self.validate(item)

    def test_ranged_unit_needs_a_real_release_location(self):
        item = asset()
        del item["muzzle_socket"]
        with self.assertRaisesRegex(ValueError, "muzzle"):
            self.validate(item)

    def test_missing_death_animation_is_not_an_animated_delivery(self):
        item = asset()
        del item["parts"][0]["animations"]["Death"]
        with self.assertRaisesRegex(ValueError, "five"):
            self.validate(item)

    def test_preview_does_not_bypass_import_verification(self):
        item = asset()
        item["ue_structural_approved"] = False
        with self.assertRaisesRegex(ValueError, "verified"):
            self.validate(item)

    def test_unreviewed_visual_can_be_previewed_without_fake_approval(self):
        item = asset()
        item.update(gameplay_visual_review_approved=False, default_runtime_enabled=False, production_approved=False)
        self.validate(item)

    def test_mount_parents_must_precede_children(self):
        item = asset()
        rider = copy.deepcopy(item["parts"][0])
        rider.update(id="rider", parent_part="missing_mount", parent_socket="saddle_seat")
        item["parts"].append(rider)
        with self.assertRaisesRegex(ValueError, "earlier parent"):
            self.validate(item)

    def test_mounted_child_can_use_an_independent_skeleton(self):
        item = asset()
        rider = copy.deepcopy(item["parts"][0])
        rider.update(id="rider", parent_part="body", parent_socket="saddle_seat", skeletal_mesh="/Game/ArtPilot/Rider/SK.SK")
        item["parts"].append(rider)
        self.assertEqual(12, len(self.validate(item)))

    def test_rejects_negative_scale_and_nonfinite_transforms(self):
        for transform in ({"uniform_scale": -1}, {"translation_cm": [0, 0, float("nan")]}, {"rotation_degrees": [0, 0]},
                          {"transform": {"translation_cm": [0, 0, 20]}}):
            item = asset()
            item["parts"][0].update(transform)
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                self.validate(item)

    def test_static_spear_requires_a_known_parent(self):
        item = asset()
        item["attachments"] = [{"static_mesh": "/Game/ArtPilot/Spear/SM.SM", "parent_part": "missing", "socket": "weapon_r"}]
        with self.assertRaisesRegex(ValueError, "weapon"):
            self.validate(item)

    def test_paths_do_not_escape_isolated_imports(self):
        for path in ("/Engine/BasicShapes/Cube.Cube", "/Game/ArtPilot/../Existing.Asset", "/Game/ArtPilot/X.X"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ART.package(ROOT, path)

    def test_cpp_keeps_legacy_and_default_review_gates(self):
        source = (ROOT / "Source/CivWar/View/CWSkeletalUnitConfigured.cpp").read_text(encoding="utf-8")
        self.assertLess(source.index('TEXT("cwlegacyart")'), source.index("LoadObject<USkeletalMesh>"))
        self.assertIn('Approved(Config, TEXT("gameplay_visual_review_approved"))', source)
        self.assertIn("Clip->GetSkeleton() != Part.Mesh->GetSkeleton()", source)
        self.assertIn("Clip->bEnableRootMotion", source)
        self.assertIn("Component->bSuppressNotifyEventDispatch = true;", source)
        self.assertIn("HasSocketOrBone", source)


if __name__ == "__main__":
    unittest.main()
