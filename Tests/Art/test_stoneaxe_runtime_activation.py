import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "Source/CivWar/View/CWSkeletalUnitPresentation.cpp").read_text(encoding="utf-8-sig")
CREATE = SOURCE.split("UCWSkeletalUnitPresentation::TryCreate(", 1)[1].split("\nvoid UCWSkeletalUnitPresentation::ApplyState", 1)[0]
CONFIG = json.loads((ROOT / "Content/Data/UnitArtPilot.json").read_text(encoding="utf-8-sig"))


class StoneAxeRuntimeActivationTests(unittest.TestCase):
    def test_default_activation_is_explicit_without_claiming_production_acceptance(self):
        self.assertTrue(CONFIG["enabled"])
        self.assertTrue(CONFIG["default_runtime_enabled"])
        self.assertEqual(CONFIG["asset_id"], "Unit_StoneAxe")
        self.assertFalse(CONFIG["runtime_approved"])
        self.assertFalse(CONFIG["production_approved"])
        self.assertNotIn("activation_requires_command_line", CONFIG)
        self.assertEqual(CONFIG["force_legacy_command_line"], "-cwlegacyart")
        self.assertEqual(CONFIG["explicit_pilot_command_line"], "-cwstoneaxepilot")

    def test_actual_cpp_gates_default_pilot_legacy_and_other_characters(self):
        guard = re.search(r'if \((VisualKey[^\n]+)\) return nullptr;', CREATE).group(1)
        requested = re.search(r'if \((!bDefaultRuntimeEnabled[^\n]+)\) return nullptr;', CREATE).group(1)
        guard = guard.replace('FName(TEXT("Unit_StoneAxe"))', '"Unit_StoneAxe"')
        guard = guard.replace('FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))', 'legacy')
        guard = guard.replace('VisualKey', 'visual_key').replace('||', ' or ')
        requested = requested.replace('bDefaultRuntimeEnabled', 'default').replace('bExplicitPilot', 'pilot')
        requested = requested.replace('&&', ' and ').replace('!', 'not ')
        self.assertRegex(guard, r'^[A-Za-z_" !=]+$')
        self.assertRegex(requested, r'^[a-z ]+$')
        for visual_key in ("Unit_StoneAxe", "Unit_StoneSlinger", "Unit_BeastRider"):
            for default in (False, True):
                for pilot in (False, True):
                    for legacy in (False, True):
                        values = {"visual_key": visual_key, "default": default, "pilot": pilot, "legacy": legacy}
                        rejected = eval(guard, {"__builtins__": {}}, values) or eval(requested, {"__builtins__": {}}, values)
                        expected = visual_key == "Unit_StoneAxe" and not legacy and (default or pilot)
                        with self.subTest(**values):
                            self.assertEqual(not rejected, expected)

    def test_legacy_precedes_loading_and_missing_default_does_not_opt_in(self):
        legacy = CREATE.index('TEXT("cwlegacyart")')
        self.assertLess(legacy, CREATE.index('TEXT("cwstoneaxepilot")'))
        self.assertLess(legacy, CREATE.index('FFileHelper::LoadFileToString'))
        self.assertLess(legacy, CREATE.index('LoadObject<USkeletalMesh>'))
        self.assertIn('bool bDefaultRuntimeEnabled = false;', CREATE)
        self.assertIn('Config->TryGetBoolField(TEXT("default_runtime_enabled"), bDefaultRuntimeEnabled);', CREATE)
        self.assertIn('if (!bDefaultRuntimeEnabled && !bExplicitPilot) return nullptr;', CREATE)

    def test_pilot_never_bypasses_existing_asset_and_animation_safety(self):
        for requirement in (
            '!Config->TryGetBoolField(TEXT("enabled"), bEnabled) || !bEnabled',
            '!Config->TryGetBoolField(TEXT("ue_structural_approved"), bImported) || !bImported',
            '!Config->TryGetBoolField(TEXT("socket_alignment_approved"), bSocketApproved) || !bSocketApproved',
            'AssetId != TEXT("Unit_StoneAxe")',
            'Socket->BoneName != FName(TEXT("hand_r"))',
            'Clip->GetSkeleton() != Mesh->GetSkeleton()',
            'Clip->GetPlayLength() <= 0.f || Clip->bEnableRootMotion',
            'Presentation->Body->bSuppressNotifyEventDispatch = true;',
            'TEXT("/Game/ArtPilot/StoneAxeTeam/")',
        ):
            self.assertIn(requirement, CREATE)
        self.assertNotIn('Unit_StoneSlinger', CREATE)

    def test_rejection_preserves_existing_legacy_unit_builder(self):
        view = (ROOT / "Source/CivWar/View/CWUnitVisual.cpp").read_text(encoding="utf-8-sig")
        self.assertIn('UCWSkeletalUnitPresentation::TryCreate(this, Model, VisualKey, Team)', view)
        self.assertRegex(view, r'if \(SkeletalPresentation\)[\s\S]*?else\s*\{\s*CWModels::BuildUnit\(this, Model, VisualKey, Team, Rig\);')
        self.assertIn('damage_authority=server_only activation=%s', CREATE)


if __name__ == "__main__":
    unittest.main()
