import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'Source/CivWar/View/CWStaticBasePilot.cpp').read_text(encoding='utf-8-sig')
BASE = (ROOT / 'Source/CivWar/View/CWBaseVisual.cpp').read_text(encoding='utf-8-sig')
CAMERA = (ROOT / 'Source/CivWar/View/CWCameraRig.cpp').read_text(encoding='utf-8-sig')
RUNNER = (ROOT / 'Tools/review_base_stone.ps1').read_text(encoding='utf-8-sig')


class BaseStonePilotContractTests(unittest.TestCase):
    def test_default_or_explicit_flag_age_and_three_approval_gates(self):
        self.assertIn('Age != 0', SOURCE)
        self.assertIn('TEXT("cwbasestonepilot")', SOURCE)
        self.assertIn('TEXT("cwlegacyart")', SOURCE)
        self.assertIn('if (!DefaultRuntimeEnabled && !bExplicitPilot) return false;', SOURCE)
        for field in ('enabled', 'ue_structural_approved', 'placement_approved_for_pilot'):
            self.assertIn('TryGetBoolField(TEXT("' + field + '")', SOURCE)
        self.assertLess(SOURCE.index('!Enabled'), SOURCE.index('LoadObject<UStaticMesh>'))

    def test_unavailable_or_legacy_procedural_fallback_retained(self):
        self.assertRegex(BASE, r'if \(!CWStaticBasePilot::TryBuild\(this, Structure, Age, Team, Rig\)\)\s*\{\s*CWModels::BuildBase\(this, Structure, Age, Team, Rig\);')

    def test_finite_vectors_exact_count_and_bounds_before_allocation(self):
        for guard in ('Numbers->Num() != 3', 'FMath::IsFinite(Number)', 'MountValues->Num() != 3', 'ExpectedMinimum[Axis] >= ExpectedMaximum[Axis]', '.Equals(ExpectedMinimum, 0.05)', '.Equals(ExpectedMaximum, 0.05)'):
            self.assertIn(guard, SOURCE)
            self.assertLess(SOURCE.index(guard), SOURCE.index('NewObject<UStaticMeshComponent>'))

    def test_identity_baked_placement_no_negative_scale(self):
        self.assertIn('SetRelativeTransform(FTransform::Identity)', SOURCE)
        self.assertNotIn('SetRelativeScale3D', SOURCE)
        self.assertNotIn('SetRelativeLocation', SOURCE)
        self.assertIn('Team == 0 ? 0.f : 180.f', BASE)

    def test_no_gameplay_authority_or_collision(self):
        self.assertIn('SetCollisionEnabled(ECollisionEnabled::NoCollision)', SOURCE)
        self.assertIn('SetGenerateOverlapEvents(false)', SOURCE)
        for forbidden in ('SimState', 'ServerCommand', 'ApplyDamage', 'SetReplicates', 'FireSeq', 'HitSeq', 'SetActorLocation'):
            self.assertNotIn(forbidden, SOURCE)

    def test_mesh_material_and_isolated_path_are_required(self):
        self.assertIn('/Game/ArtPilot/tripo_base_stone_pbr_v01/Base_Stone/', SOURCE)
        self.assertIn('Mesh->GetStaticMaterials().Num() != 1', SOURCE)
        self.assertIn('!Mesh->GetMaterial(0)', SOURCE)

    def test_camera_is_opt_in_and_keeps_six_distance_views(self):
        self.assertIn('TEXT("cwbaseartreview")', CAMERA)
        self.assertIn('!bReviewBase && FParse::Param', CAMERA)
        self.assertIn('1300.f, 2300.f, 3400.f', CAMERA)
        self.assertIn('if (bReviewBase) CurrentX = TargetX', CAMERA)
        self.assertIn('GetMatchTime() < 12.f', CAMERA)

    def test_ui_exclusion_requires_base_review_and_its_separate_flag(self):
        self.assertIn('!bReviewBase || !FParse::Param(FCommandLine::Get(), TEXT("cwbasearthideui"))', CAMERA)
        self.assertIn('RequestScreenshot(Name, bShowReviewUI, false)', CAMERA)

    def test_team_material_is_optional_isolated_and_explicitly_approved(self):
        self.assertIn('TryGetStringField(TEXT("team_material")', SOURCE)
        self.assertIn('TryGetBoolField(TEXT("team_material_approved_for_pilot")', SOURCE)
        self.assertIn('/Game/ArtPilot/BaseStoneTeam/', SOURCE)
        self.assertLess(SOURCE.index('!TeamMaterialApproved'), SOURCE.index('NewObject<UStaticMeshComponent>'))
        self.assertIn('CWVisual::TeamColor(Team)', SOURCE)
        self.assertIn('TEXT("TeamColorStrength"), 1.f', SOURCE)
        self.assertIn('Owner->RemoveInstanceComponent(Body)', SOURCE)

    def test_capture_requires_actual_both_team_material_logs_when_configured(self):
        self.assertIn('if ($config.team_material)', RUNNER)
        self.assertIn('team=$team material=$($config.team_material) cloth_mask_only=true', RUNNER)
        self.assertIn('Actual team material absent or differs', RUNNER)
        self.assertIn('team_material_evidence=$teamMaterialEvidence', RUNNER)


if __name__ == '__main__':
    unittest.main()
