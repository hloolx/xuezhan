import itertools
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASE_SOURCE = (ROOT / "Source/CivWar/View/CWStaticBasePilot.cpp").read_text(encoding="utf-8-sig")
TURRET_SOURCE = (ROOT / "Source/CivWar/View/CWStaticTurretPilot.cpp").read_text(encoding="utf-8-sig")
BASE_CONFIG = json.loads((ROOT / "Content/Data/BaseArtPilot.json").read_text(encoding="utf-8-sig"))
TURRET_CONFIG = json.loads((ROOT / "Content/Data/TurretArtPilot.json").read_text(encoding="utf-8-sig"))


def activation_expression(source):
    expression = re.search(r"if \((!DefaultRuntimeEnabled && !bExplicitPilot)\) return false;", source)
    if not expression:
        raise ValueError("Actual default-or-explicit guard is absent or changed")
    return expression.group(1).replace("!", "not ").replace("&&", "and")


class BaseTurretDefaultRuntimeTests(unittest.TestCase):
    def test_exact_cpp_activation_guard_truth_table(self):
        for source in (BASE_SOURCE, TURRET_SOURCE):
            expression = activation_expression(source)
            for default, explicit in itertools.product((False, True), repeat=2):
                rejected = eval(expression, {"__builtins__": {}}, {"DefaultRuntimeEnabled": default, "bExplicitPilot": explicit})
                self.assertEqual(not rejected, default or explicit)

    def test_legacy_precedes_config_and_cannot_be_overridden_by_explicit_flag(self):
        for source in (BASE_SOURCE, TURRET_SOURCE):
            build = source.split("::TryBuild", 1)[1]
            early_guard = build.split("return false;", 1)[0]
            self.assertIn('FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))', early_guard)
            self.assertNotIn('!FParse::Param', early_guard)
            self.assertLess(build.index('TEXT("cwlegacyart")'), build.index('LoadFileToString'))
            self.assertLess(build.index('TEXT("cwlegacyart")'), build.index('const bool bExplicitPilot'))

    def test_missing_default_field_is_false_and_old_explicit_flags_remain(self):
        for source in (BASE_SOURCE, TURRET_SOURCE):
            self.assertIn('bool DefaultRuntimeEnabled = false;', source)
            self.assertIn('Config->TryGetBoolField(TEXT("default_runtime_enabled"), DefaultRuntimeEnabled);', source)
        self.assertIn('const bool bExplicitPilot = FParse::Param(FCommandLine::Get(), TEXT("cwbasestonepilot"));', BASE_SOURCE)
        self.assertRegex(TURRET_SOURCE, r'const bool bExplicitPilot = FParse::Param\(FCommandLine::Get\(\), TEXT\("cwbasestonepilot"\)\) &&\s*FParse::Param\(FCommandLine::Get\(\), TEXT\("cwrocktowerpilot"\)\);')

    def test_all_prior_approval_gates_remain_mandatory(self):
        for field in ("enabled", "ue_structural_approved", "placement_approved_for_pilot", "team_material_approved_for_pilot"):
            self.assertIn(f'TryGetBoolField(TEXT("{field}")', BASE_SOURCE)
        for field in ("enabled", "ue_structural_approved", "assembly_approved_for_pilot"):
            self.assertIn(f'TEXT("{field}")', TURRET_SOURCE)
        self.assertIn('if (!Config->TryGetBoolField(Gate, Approved) || !Approved) return false;', TURRET_SOURCE)
        self.assertIn('!Owner || !Mount || !bBasePilot', TURRET_SOURCE)
        self.assertIn('!TeamMaterialApproved', BASE_SOURCE)

    def test_config_default_is_user_authorized_not_a_production_claim(self):
        for config in (BASE_CONFIG, TURRET_CONFIG):
            self.assertIs(config["default_runtime_enabled"], True)
            self.assertIs(config["enabled"], True)
            self.assertIs(config["production_approved"], False)
            self.assertIs(config["runtime_approved"], False)
            self.assertEqual(config["force_legacy_command_line"], "-cwlegacyart")
            self.assertIn("Explicit user request", config["default_runtime_authorization"])
            self.assertTrue(config["remaining_gates"])
            self.assertNotIn("activation_requires_command_line", config)

    def test_approved_base_mesh_and_actual_team_material_are_unchanged(self):
        self.assertEqual(BASE_CONFIG["static_mesh"], "/Game/ArtPilot/tripo_base_stone_pbr_v01/Base_Stone/h96b57839189a/Base_Stone.Base_Stone")
        self.assertEqual(BASE_CONFIG["team_material"], "/Game/ArtPilot/BaseStoneTeam/h8fcec9bb7998327c/M_Base_Stone_MainCloth.M_Base_Stone_MainCloth")
        self.assertIs(BASE_CONFIG["team_material_approved_for_pilot"], True)
        self.assertEqual(BASE_CONFIG["turret_mounts_cm"], [[148.40097, 191.79658, 157.49995], [147.91031, -195.37494, 157.55195], [-158.95849, .11456, 317.55337]])

    def test_tower_original_seven_meshes_no_new_wood_material_override(self):
        self.assertEqual(len(TURRET_CONFIG["meshes"]), 7)
        for path in TURRET_CONFIG["meshes"].values():
            self.assertTrue(path.startswith("/Game/ArtPilot/RockTower/hef0edf145a136087/"))
        self.assertNotIn("material_overrides", TURRET_CONFIG)
        self.assertNotIn("wood_tone", TURRET_CONFIG)
        self.assertEqual(TURRET_SOURCE.count('->SetMaterial('), 1)
        self.assertIn('ClothComponent->SetMaterial(0, TeamCloth)', TURRET_SOURCE)
        self.assertIn('CWVisual::TeamColor(Team), 0.66f, 0.f', TURRET_SOURCE)

    def test_logs_distinguish_default_activation_without_changing_old_prefixes(self):
        for source, prefix in ((BASE_SOURCE, "CIVWAR_BASE_STONE_PILOT"), (TURRET_SOURCE, "CIVWAR_ROCK_TOWER_PILOT")):
            self.assertIn(prefix, source)
            self.assertIn('activation=%s production_approved=false', source)
            self.assertIn('bExplicitPilot ? TEXT("explicit_pilot") : TEXT("default_runtime")', source)


if __name__ == "__main__":
    unittest.main()
