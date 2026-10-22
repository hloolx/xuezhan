import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower_wood_style_render_v02", ROOT / "Tools/Unreal/rock_tower_wood_style_render_v02.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExactImportedSlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = MODULE.rock.read_json(MODULE.rock.DELIVERY / "ue_fresh_01.json")
        cls.evidence = MODULE.slot_evidence(cls.report)

    def test_import_is_lightweight_and_render_only(self):
        self.assertNotIn("unreal", MODULE.__dict__)
        self.assertNotIn("subprocess", MODULE.__dict__)
        self.assertFalse(hasattr(MODULE, "create_materials"))

    def test_seven_exact_slots_only_three_aliases(self):
        self.assertEqual(len(self.evidence), 7)
        changed = [row for row in self.evidence if row["source_name"] != row["ue_slot_name"]]
        self.assertEqual({row["component"] for row in changed}, set(MODULE.ALIASES))

    def test_actual_geometry_and_material_proof(self):
        self.assertEqual(sum(row["section_triangles"] for row in self.evidence if row["component"].startswith("Adapter")), 304)
        self.assertTrue(all(row["source_surface_correspondence"]["max_uv_error"] == 0 for row in self.evidence))
        self.assertTrue(all(row["original_material_path"].endswith(row["ue_slot_name"] + "." + row["ue_slot_name"]) for row in self.evidence))

    def test_report_requires_actual_independent_fresh(self):
        report = copy.deepcopy(self.report)
        report["validated_in_fresh_process"] = False
        with self.assertRaisesRegex(ValueError, "independent"):
            MODULE.slot_evidence(report)

    def test_mapped_slot_name_is_case_sensitive(self):
        report = copy.deepcopy(self.report)
        report["results"][0]["mesh"]["material_slots"][0]["slot"] = "cw_wood"
        with self.assertRaisesRegex(ValueError, "identity"):
            MODULE.slot_evidence(report)

    def test_no_generic_normalization(self):
        evidence = copy.deepcopy(self.evidence)
        evidence[0]["ue_slot_name"] = "CW_WOOD"
        with self.assertRaisesRegex(ValueError, "unproven"):
            with MODULE.proven_names_only(evidence):
                self.fail("Unexpected mapping accepted")

    def test_material_path_mismatch_rejected(self):
        report = copy.deepcopy(self.report)
        report["results"][0]["mesh"]["material_slots"][0]["material"] += "wrong"
        with self.assertRaisesRegex(ValueError, "identity"):
            MODULE.slot_evidence(report)

    def test_source_section_mismatch_rejected(self):
        report = copy.deepcopy(self.report)
        report["results"][0]["render_sections"][0]["source_material"] = "CW_hide"
        with self.assertRaisesRegex(ValueError, "section"):
            MODULE.slot_evidence(report)

    def test_triangle_count_mismatch_rejected(self):
        report = copy.deepcopy(self.report)
        report["results"][0]["render_sections"][0]["actual_render_triangles"] += 1
        with self.assertRaisesRegex(ValueError, "triangle"):
            MODULE.slot_evidence(report)

    def test_bad_uv_gate_rejected(self):
        report = copy.deepcopy(self.report)
        report["results"][0]["source_surface_correspondence"]["max_uv_error"] = .01
        with self.assertRaisesRegex(ValueError, "error"):
            MODULE.slot_evidence(report)

    def test_names_restored_even_on_failure(self):
        original = MODULE.wood.SLOTS
        with self.assertRaisesRegex(RuntimeError, "expected"):
            with MODULE.proven_names_only(self.evidence):
                self.assertEqual(MODULE.wood.SLOTS["Adapter_rear"][0], ("CW_wood_011", "Dark"))
                raise RuntimeError("expected")
        self.assertIs(MODULE.wood.SLOTS, original)
        self.assertEqual(MODULE.wood.SLOTS["Adapter_rear"][0][0], "CW_wood.011")

    def test_cannot_add_slot_or_change_family(self):
        for mutation in ("add", "family"):
            evidence = copy.deepcopy(self.evidence)
            if mutation == "add":
                evidence.append(copy.deepcopy(evidence[0]))
            else:
                evidence[0]["family"] = "Light"
            with self.assertRaisesRegex(ValueError, "semantic slots"):
                with MODULE.proven_names_only(evidence):
                    self.fail("Unexpected semantic scope accepted")

    def fake_meshes(self):
        meshes = {}
        for row in self.evidence:
            if row["component"] not in meshes:
                mesh = Mock()
                mesh.get_path_name.return_value = row["original_mesh_path"]
                mesh.slots, mesh.materials = {}, {}
                mesh.get_editor_property.side_effect = lambda name, mesh=mesh: [mesh.slots[index] for index in sorted(mesh.slots)]
                mesh.get_material.side_effect = lambda index, mesh=mesh: mesh.materials[index]
                meshes[row["component"]] = mesh
            mesh = meshes[row["component"]]
            slot, material = Mock(), Mock()
            slot.get_editor_property.return_value = row["ue_slot_name"]
            material.get_path_name.return_value = row["original_material_path"]
            material.get_class.return_value.get_name.return_value = "Material"
            mesh.slots[row["slot"]], mesh.materials[row["slot"]] = slot, material
        return meshes

    def test_live_mesh_material_and_name_verified(self):
        MODULE.audit_loaded_slots(self.fake_meshes(), self.evidence)

    def test_live_original_material_cannot_be_new_override(self):
        meshes = self.fake_meshes()
        meshes["Frame"].materials[0].get_path_name.return_value = "/Game/Fake.NewWood"
        with self.assertRaisesRegex(ValueError, "original material"):
            MODULE.audit_loaded_slots(meshes, self.evidence)

    def test_live_slot_name_cannot_be_source_spelling(self):
        meshes = self.fake_meshes()
        meshes["Adapter_rear"].slots[0].get_editor_property.return_value = "CW_wood.011"
        with self.assertRaisesRegex(ValueError, "UE slot"):
            MODULE.audit_loaded_slots(meshes, self.evidence)

    def test_existing_candidate_unchanged_and_no_new_assets(self):
        plan = MODULE.plan()
        self.assertEqual(plan["new_package_count"], 0)
        self.assertEqual(plan["new_texture_count"], 0)
        self.assertEqual(plan["protected_existing_packages"], 72)
        self.assertEqual(len(plan["shots"]), 6)
        self.assertEqual(plan["material_fingerprint"], "e5a67c69f6c4e7cd5b0830fc345348248addbb38500a8b0322bf7995811c7bae")
        MODULE.validate_repair(plan)

    def test_repair_fingerprint_tamper_rejected(self):
        plan = MODULE.plan()
        plan["shots"] = []
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            MODULE.validate_repair(plan)


if __name__ == "__main__":
    unittest.main()
