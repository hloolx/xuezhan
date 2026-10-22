import copy
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower_wood_style", ROOT / "Tools/Unreal/rock_tower_wood_style.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fake_spec():
    protected = [{"file": "F:/fake/" + str(index) + ".uasset", "sha256": "a" * 64, "bytes": 1} for index in range(69)]
    result = {"version": MODULE.VERSION, "shots": MODULE.SHOTS, "slot_overrides": MODULE.slot_contract(),
              "new_package_count": 3, "new_texture_count": 0, "protected_package_count": 69,
              "protected_packages": protected, "source_files": copy.deepcopy(protected),
              "reference": {"median_linear_rgb": [.15, .08, .04], "median_linear_roughness": .75,
                            "families": MODULE.bounded_proposal([.15, .08, .04], .75)}}
    return sign(result)


def sign(spec):
    unsigned = {key: value for key, value in spec.items() if key not in {"fingerprint", "destination"}}
    spec["fingerprint"] = MODULE.digest(unsigned)
    spec["destination"] = "/Game/ArtPilot/RockTowerWood/h" + spec["fingerprint"][:16]
    return spec


class WoodStyleTests(unittest.TestCase):
    def test_import_does_not_load_unreal_or_process_runner(self):
        self.assertNotIn("unreal", MODULE.__dict__)
        self.assertNotIn("subprocess", MODULE.__dict__)

    def test_srgb_middle_is_not_linear_middle(self):
        self.assertAlmostEqual(MODULE.srgb_linear(.5), .21404114048223255)

    def test_srgb_endpoints(self):
        self.assertEqual(MODULE.srgb_linear(0), 0)
        self.assertEqual(MODULE.srgb_linear(1), 1)

    def test_fingerprint_survives_equivalent_json_number_types(self):
        self.assertEqual(MODULE.digest({"value": [0, 1, .5]}), MODULE.digest({"value": [0.0, 1.0, .5]}))
        self.assertNotEqual(MODULE.digest({"value": False}), MODULE.digest({"value": 0}))

    def test_srgb_rejects_invalid(self):
        for value in (math.nan, math.inf, -1, 1.01):
            with self.assertRaises(ValueError):
                MODULE.srgb_linear(value)

    def test_proposal_is_bounded_per_channel(self):
        for reference in ([.0001, 1, .0001], [1, .0001, 1], [.12, .07, .04]):
            proposal = MODULE.bounded_proposal(reference, .9)
            for family, original in MODULE.ORIGINAL.items():
                for actual, source in zip(proposal[family]["base_color_linear"], original):
                    self.assertGreaterEqual(actual, source * .70)
                    self.assertLessEqual(actual, source * 1.35)
                self.assertEqual(proposal[family]["roughness"], .78)
                self.assertEqual(proposal[family]["metallic"], 0)

    def test_roughness_lower_bound(self):
        self.assertEqual(MODULE.bounded_proposal([.12, .08, .04], .1)["Dark"]["roughness"], .66)

    def test_reject_nonfinite_reference(self):
        for reference in ([0, .1, .2], [math.nan, .1, .2], [.1, .2]):
            with self.assertRaises(ValueError):
                MODULE.bounded_proposal(reference, .7)
        with self.assertRaises(ValueError):
            MODULE.bounded_proposal([.1, .2, .3], math.nan)

    def test_exact_seven_semantic_wood_slots(self):
        self.assertEqual(sum(map(len, MODULE.SLOTS.values())), 7)
        for mapping in MODULE.SLOTS.values():
            self.assertTrue(all(name.startswith("CW_wood") for name, family in mapping.values()))
        self.assertNotIn("Cloth", MODULE.SLOTS)
        self.assertNotIn("Stone", MODULE.SLOTS)

    def test_six_control_views_paired_cameras(self):
        self.assertEqual(len(MODULE.SHOTS), 6)
        for old, new in zip(MODULE.SHOTS[::2], MODULE.SHOTS[1::2]):
            self.assertFalse(old["new"])
            self.assertTrue(new["new"])
            self.assertEqual({key: value for key, value in old.items() if key not in {"label", "new"}},
                             {key: value for key, value in new.items() if key not in {"label", "new"}})
        self.assertEqual({shot["team"] for shot in MODULE.SHOTS if shot["crop"] == "wide"}, {0, 1})

    def test_exact_three_new_asset_names(self):
        self.assertEqual(len(MODULE.asset_names()), 3)
        self.assertTrue(all(name.startswith(("M_", "MI_")) for name in MODULE.asset_names().values()))

    def test_valid_spec_hashes_sources(self):
        with patch.object(MODULE.rock, "check_records") as check:
            MODULE.validate_spec(fake_spec())
            self.assertEqual(check.call_count, 1)

    def test_tampered_fingerprint_rejected(self):
        spec = fake_spec()
        spec["new_package_count"] = 4
        with self.assertRaises(ValueError):
            MODULE.validate_spec(spec)

    def test_rehashed_semantic_expansion_rejected(self):
        spec = fake_spec()
        spec["slot_overrides"]["Frame"]["4"] = ["CW_hide", "Dark"]
        with self.assertRaises(ValueError):
            MODULE.validate_spec(sign(spec))

    def test_rehashed_added_texture_rejected(self):
        spec = fake_spec()
        spec["new_texture_count"] = 1
        with self.assertRaises(ValueError):
            MODULE.validate_spec(sign(spec))

    def test_missing_or_duplicate_protected_package_rejected(self):
        for action in ("drop", "duplicate"):
            spec = fake_spec()
            if action == "drop":
                spec["protected_packages"].pop()
            else:
                spec["protected_packages"][-1] = spec["protected_packages"][0]
            with self.assertRaises(ValueError):
                MODULE.validate_spec(sign(spec))

    def test_unbounded_candidate_cannot_be_rehashed(self):
        spec = fake_spec()
        spec["reference"]["families"]["Dark"]["base_color_linear"][0] = .9
        with self.assertRaises(ValueError):
            MODULE.validate_spec(sign(spec))

    def test_fresh_rejects_same_process(self):
        spec = fake_spec()
        report = {"status": "wood_style_fresh_passed_pending_actual6", "validated_in_fresh_process": True,
                  "initial_process_id": 123, "execution_process_id": 123}
        with self.assertRaises(ValueError):
            MODULE.check_fresh(spec, report)

    def test_report_cannot_escape_owned_folder(self):
        with self.assertRaises(ValueError):
            MODULE.write_report(ROOT / "Content/Data/forbidden.json", {})

    def test_per_shot_timeout_finishes_instead_of_polling_forever(self):
        session = object.__new__(MODULE.WoodReview)
        session.stage = "wood_resources"
        session.started = session.wood_resource_started = 0
        session.args = SimpleNamespace(timeout=160)
        session.report = {}
        session.finish = Mock()
        with patch.object(MODULE.time, "monotonic", return_value=200):
            session.advance(0)
        session.finish.assert_called_once_with("failed")
        self.assertIn("timed out", session.report["error"])

    def test_source_does_not_save_mesh_or_import_texture(self):
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        for forbidden in ("TextureFactory", "AssetImportTask", "save_directory"):
            self.assertNotIn(forbidden, source)
        self.assertIn("component.set_material(index, self.wood", source)

    def test_frozen_spec_if_present(self):
        path = MODULE.DEFAULT_SPEC
        if not path.exists():
            self.skipTest("Freeze spec after preparing tested source")
        MODULE.validate_spec(MODULE.rock.read_json(path))


if __name__ == "__main__":
    unittest.main()
