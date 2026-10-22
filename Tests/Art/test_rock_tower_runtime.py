import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "Source/CivWar/View/CWStaticTurretPilot.cpp").read_text(encoding="utf-8-sig")
BASE = (ROOT / "Source/CivWar/View/CWBaseVisual.cpp").read_text(encoding="utf-8-sig")
GAME = (ROOT / "Source/CivWar/Game/CWGameMode.cpp").read_text(encoding="utf-8-sig")
RUNNER = (ROOT / "Tools/review_base_stone.ps1").read_text(encoding="utf-8-sig")
CAMERA = (ROOT / "Source/CivWar/View/CWCameraRig.cpp").read_text(encoding="utf-8-sig")
SPEC = importlib.util.spec_from_file_location("rock_tower_contract_runtime", ROOT / "Tools/Blender/build_rock_tower.py")
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class RockTowerRuntimeContractTests(unittest.TestCase):
    def test_default_or_explicit_activation_and_actual_base_gates_precede_asset_loading(self):
        for guard in ('!bBasePilot', 'TEXT("cwlegacyart")', 'TEXT("cwbasestonepilot")', 'TEXT("cwrocktowerpilot")', 'Slot < 0 || Slot >= 3'):
            self.assertIn(guard, SOURCE)
            self.assertLess(SOURCE.index(guard), SOURCE.index('LoadMesh(*Meshes'))
        self.assertIn('Rig.bTripoBasePilot, TurretRigs[Slot]', BASE)
        self.assertIn('if (!DefaultRuntimeEnabled && !bExplicitPilot) return false;', SOURCE)

    def test_three_approval_gates_and_isolated_prefix(self):
        for field in ('enabled', 'ue_structural_approved', 'assembly_approved_for_pilot'):
            self.assertIn('TEXT("' + field + '")', SOURCE)
        self.assertIn('/Game/ArtPilot/RockTower/', SOURCE)
        self.assertIn('if (!Frame || !Arm || !Stone || !Cloth || !Adapter', SOURCE)

    def test_unmodified_fallback_and_no_gameplay_authority(self):
        self.assertIn('CWModels::BuildTurret(this, SlotRoots[Slot], VisualKey, Team, TurretRigs[Slot]);', BASE)
        for forbidden in ('ApplyDamage', 'ServerCommand', 'SetReplicates', 'NetNotify', 'AnimNotify', 'SimState'):
            self.assertNotIn(forbidden, SOURCE)
        self.assertIn('SetCollisionEnabled(ECollisionEnabled::NoCollision)', SOURCE)
        self.assertIn('SetMobility(EComponentMobility::Movable)', SOURCE)

    def test_release_pose_applied_before_projectile_broadcast(self):
        self.assertLess(BASE.index('CWStaticTurretPilot::BeginFire(TurretRigs[I])'), BASE.index('OnTurretFired.Broadcast'))
        self.assertIn('Rig.PilotFireElapsed = 0.f;', SOURCE)
        self.assertIn('ApplyPose(Rig, SamplePose(0.f));', SOURCE)
        self.assertFalse(CONTRACT.sample_cycle(0)["stone_visible"])
        self.assertEqual(-35, CONTRACT.sample_cycle(0)["angle_degrees"])

    def test_initial_snapshot_does_not_replay_release(self):
        initial = BASE.split('if (Slot.Def != TurretDefs[I] || bUnlockChanged)', 1)[1].split('else if (Slot.FireSeq', 1)[0]
        self.assertIn('TurretFireSeqs[I] = Slot.FireSeq;', initial)
        self.assertNotIn('BeginFire', initial)
        self.assertIn('Rig.PilotFireElapsed = -1.f;', SOURCE)

    def test_exact_ue_axis_sign_and_cycle_contract(self):
        for expression in ('Transition(35.f, -40.f, Elapsed / 0.16f)',
                           'Transition(-40.f, 65.f, (Elapsed - 0.30f) / 0.65f)',
                           'Transition(65.f, 35.f, (Elapsed - 1.30f) / 0.80f)',
                           'Elapsed >= 1.20f', 'FMath::Min(2.10f, Rig.PilotFireElapsed + DeltaSeconds)'):
            self.assertIn(expression, SOURCE)
        self.assertEqual(-40, -CONTRACT.sample_cycle(0.2)["angle_degrees"])
        self.assertEqual(65, -CONTRACT.sample_cycle(1.2)["angle_degrees"])
        self.assertEqual(35, -CONTRACT.sample_cycle(2.1)["angle_degrees"])

    def test_slot_lifts_not_applied_to_adapter(self):
        self.assertIn('UpperLiftCm[] = {1.5f, 0.8f, 1.f}', SOURCE)
        self.assertIn('AddMesh(Owner, Mount, Adapter, FVector::ZeroVector)', SOURCE)
        self.assertIn('FVector(-4.f, 0.f, 51.f)', SOURCE)
        self.assertIn('FVector(3.5f, 0.f, 57.f)', SOURCE)
        self.assertNotIn('SetRelativeScale3D', SOURCE)

    def test_custom_arm_cycle_bypasses_legacy_translation_recoil(self):
        update = BASE.split('void ACWBaseVisual::UpdateVisual', 1)[1]
        self.assertLess(update.index('CWStaticTurretPilot::Update(TurretRigs[I], Dt)'), update.index('Aim->SetRelativeLocation'))
        self.assertNotIn('SetRelativeLocation', SOURCE.split('bool CWStaticTurretPilot::Update', 1)[1])

    def test_only_independent_cloth_recolored_with_source_pbr_factors(self):
        self.assertIn('CWVisual::TeamColor(Team), 0.66f, 0.f', SOURCE)
        self.assertIn('ClothComponent->SetMaterial(0, TeamCloth)', SOURCE)
        self.assertEqual(1, SOURCE.count('->SetMaterial('))

    def test_bad_delta_cannot_reverse_or_nan_the_cycle(self):
        self.assertIn('FMath::IsFinite(DeltaSeconds) && DeltaSeconds > 0.f', SOURCE)
        self.assertIn('!FMath::IsFinite(Elapsed) || Elapsed < 0.f', SOURCE)

    def test_fixture_is_editor_standalone_and_has_explicit_default_diagnostic(self):
        fixture = GAME.split('#if WITH_EDITOR', 1)[1].split('#endif', 1)[0]
        for guard in ('GetNetMode() == NM_Standalone', 'SessionMode == ECWSessionMode::Single',
                      'TEXT("cwrocktowerfixture")', 'TEXT("cwrocktowerpilot")', 'TEXT("cwbasestonepilot")'):
            self.assertIn(guard, fixture)
            self.assertLess(fixture.index(guard), fixture.index('Sim->DebugGrantGold'))
        self.assertIn('FixtureData.Rules.MaxTurretSlots == 3', fixture)
        self.assertIn('TEXT("cwdefaultartfixture")) ||', fixture)
        self.assertLess(fixture.index('TEXT("cwdefaultartfixture")'), fixture.index('Sim->DebugGrantGold'))
        self.assertIn('Sim->Apply(FixtureTeam, Unlock)', fixture)
        self.assertIn('Sim->Apply(FixtureTeam, Build)', fixture)
        for forbidden in ('FireSeq', 'Damage', 'AddUnit', 'const_cast', 'DebugGrantXp'):
            self.assertNotIn(forbidden, fixture)

    def test_game_capture_requires_all_six_real_towers_and_fixture_results(self):
        self.assertIn('[switch]$RockTower', RUNNER)
        self.assertIn('PILOT team=$team slot=$slot components=5', RUNNER)
        self.assertIn('FIXTURE team=$team slot=$slot result=0', RUNNER)
        self.assertIn("$arguments += ' -cwrocktowerpilot -cwrocktowerfixture'", RUNNER)
        self.assertIn('Turret mapping changed during capture', RUNNER)

    def test_live_pose_log_samples_components_not_expected_values(self):
        self.assertIn('TurretRigs[I].Aim->GetRelativeRotation().Pitch', BASE)
        self.assertIn('TurretRigs[I].LoadedStone->IsVisible() ? 1 : 0', BASE)
        self.assertIn('TurretRigs[I].Aim->GetComponentScale().ToString()', BASE)
        self.assertNotIn('seq=%u pitch=35 stone_visible=false', BASE)
        self.assertIn('PreviousPilotElapsed < 2.10f', BASE)

    def test_defender_test_changes_only_ai_and_keeps_authority_read_only(self):
        scenario = GAME.split('int32 RockTowerDefender = -1;', 1)[1].split('#endif', 1)[0]
        for guard in ('GetNetMode() == NM_Standalone', 'SessionMode == ECWSessionMode::Single',
                      'TEXT("cwrocktowerfixture")', 'TEXT("cwrocktowerpilot")', 'TEXT("cwbasestonepilot")'):
            self.assertIn(guard, scenario)
        self.assertIn('if (RockTowerDefender == 1) Ai.Reset();', scenario)
        self.assertIn('TEXT("cwdefaultartfixture")) ||', scenario)
        event = GAME.split('case cw::EventType::TurretFired:', 1)[1].split('case cw::EventType::SkillCast:', 1)[0]
        self.assertIn('CIVWAR_ROCK_TOWER_AUTHORITY', event)
        for forbidden in ('Sim->Apply', 'DebugGrant', 'FireSeq =', 'Damage'):
            self.assertNotIn(forbidden, event)
        self.assertIn("if ($Defender -eq 0) { $arguments = $arguments.Replace(' -cwautoplay', '') }", RUNNER)

    def test_cycle_images_sample_actual_state_without_driving_pose(self):
        capture = CAMERA.split('void ACWCameraRig::CaptureRockTowerReview', 1)[1].split('#endif', 1)[0]
        for guard in ('Slot != 0', 'GetNetMode() != NM_Standalone', 'State->GetMatchTime() < 60.f',
                      'TEXT("cwrocktowerfixture")', 'TEXT("cwrocktowercyclecapture")', 'Defender != Team'):
            self.assertIn(guard, capture)
        for forbidden in ('ApplyPose', 'BeginFire', 'Sim->', 'SetRelativeRotation'):
            self.assertNotIn(forbidden, capture)
        self.assertIn('Sequence != RockTowerReviewSequence', capture)
        self.assertIn('RockTowerReviewMask & (1 << Phase)', capture)
        self.assertIn('FScreenshotRequest::RequestScreenshot(Name, false, false)', capture)
        self.assertIn('TurretRigs[I].Aim->GetRelativeRotation().Pitch, TurretRigs[I].LoadedStone->IsVisible()', BASE)
        self.assertIn('foreach ($phase in 0..5)', RUNNER)


if __name__ == '__main__':
    unittest.main()
