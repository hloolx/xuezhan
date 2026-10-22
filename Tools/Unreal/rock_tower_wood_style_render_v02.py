"""Render-only retry with seven explicitly evidenced imported slot names."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/Unreal"))
import rock_tower_wood_style as wood

rock, renderer = wood.rock, wood.renderer
FOLDER = wood.FOLDER
DEFAULT_SPEC = FOLDER / "render_02_spec.json"
VERSION = "rock_tower_wood_render_exact_imported_slots_v2"
ALIASES = {
    "Adapter_front_negative_y": ("CW_wood.005", "CW_wood_005"),
    "Adapter_front_positive_y": ("CW_wood.008", "CW_wood_008"),
    "Adapter_rear": ("CW_wood.011", "CW_wood_011"),
}
SESSION = None


def slot_evidence(report):
    if not report.get("validated_in_fresh_process"):
        raise ValueError("Original independent tower fresh evidence required")
    results = {entry["config_key"]: entry for entry in report["results"]}
    evidence = []
    for component, slots in wood.SLOTS.items():
        entry = results[component]
        mesh = entry["mesh"]
        correspondence = entry["source_surface_correspondence"]
        if correspondence["status"] != "passed":
            raise ValueError("Source/render surface correspondence did not pass")
        for name, limit in (("max_position_error_cm", .001), ("max_uv_error", 1e-6), ("max_normal_vector_error", .002)):
            value = correspondence[name]
            if not math.isfinite(value) or not 0 <= value <= limit:
                raise ValueError("Source/render surface error exceeded the original gate")
        source_path = Path(entry["material_audit"]["source_materials"]["source"])
        source_record = rock.file_record(source_path)
        declared = [item for item in report["source_files"] if Path(item["file"]).resolve() == source_path.resolve()]
        if len(declared) != 1 or declared[0]["sha256"] != source_record["sha256"]:
            raise ValueError("Actual source GLB differs from original fresh receipt")
        payload = source_path.read_bytes()
        document = json.loads(payload[20:20 + struct.unpack_from("<I", payload, 12)[0]])
        source_names = {material["name"] for material in document["materials"]}
        for index, (source_name, family) in slots.items():
            expected_name = source_name
            if component in ALIASES:
                expected_source, expected_name = ALIASES[component]
                if index != 0 or source_name != expected_source:
                    raise ValueError("Alias is only authorized for this exact source slot")
            observed = mesh["material_slots"][index]
            expected_material = mesh["path"].rsplit("/", 1)[0] + "/" + expected_name + "." + expected_name
            sections = [section for section in entry["render_sections"] if section["actual_material_slot"] == index]
            if source_name not in source_names or observed["slot"] != expected_name or observed["material"] != expected_material:
                raise ValueError("Frozen source/imported slot identity differs")
            if len(sections) != 1 or sections[0]["source_material"] != source_name or sections[0]["material_path"] != expected_material:
                raise ValueError("Original render section does not establish the exact mapping")
            triangles = correspondence["source_material_triangle_counts"][source_name]
            if triangles <= 0 or triangles != sections[0]["actual_render_triangles"]:
                raise ValueError("Original section triangle correspondence differs")
            actual_material = [item for item in entry["material_audit"]["materials"] if item["path"] == expected_material]
            if len(actual_material) != 1 or actual_material[0]["class"] != "Material":
                raise ValueError("Original material class/path proof differs")
            evidence.append({"component": component, "slot": index, "family": family,
                             "source_name": source_name, "ue_slot_name": expected_name,
                             "original_mesh_path": mesh["path"], "original_material_path": expected_material,
                             "source_glb": source_record, "section_triangles": triangles,
                             "source_surface_correspondence": correspondence})
    if len(evidence) != 7:
        raise ValueError("Exactly seven original wood slots required")
    return evidence


def plan():
    original_spec = rock.read_json(wood.DEFAULT_SPEC)
    wood.validate_spec(original_spec)
    fresh = rock.read_json(FOLDER / "fresh_01.json")
    wood.check_fresh(original_spec, fresh)
    original_fresh = rock.read_json(rock.DELIVERY / "ue_fresh_01.json")
    failed = rock.read_json(FOLDER / "render_01/ue_render_report.json")
    if failed.get("status") != "failed" or failed.get("actual_images") != 0 or failed.get("error") != "Wood slot semantic name differs":
        raise ValueError("Repair must bind the actual zero-image slot-name failure")
    paths = [wood.DEFAULT_SPEC, FOLDER / "initial_01.json", FOLDER / "fresh_01.json",
             FOLDER / "render_01/ue_render_report.json", rock.DELIVERY / "ue_fresh_01.json",
             Path(wood.__file__), Path(__file__), ROOT / "Tests/Art/test_rock_tower_wood_style_render_v02.py"]
    result = {"version": VERSION, "original_spec": rock.file_record(wood.DEFAULT_SPEC),
              "material_fingerprint": original_spec["fingerprint"], "destination": original_spec["destination"],
              "slot_evidence": slot_evidence(original_fresh), "shots": wood.SHOTS,
              "source_files": [rock.file_record(path) for path in paths], "new_package_count": 0,
              "new_texture_count": 0, "protected_existing_packages": 72,
              "saved_material_package_files": fresh["package_files"], "output_name": "render_02",
              "scope": "Only proven source-name to UE-slot-name checks; same existing three materials and six cameras.",
              "initial_or_fresh_execution_allowed": False, "runtime_approved": False, "production_approved": False}
    result["fingerprint"] = wood.digest(result)
    return result


def validate_repair(spec):
    unsigned = {key: value for key, value in spec.items() if key != "fingerprint"}
    if spec.get("version") != VERSION or spec.get("fingerprint") != wood.digest(unsigned):
        raise ValueError("Repair fingerprint differs")
    if spec["new_package_count"] != 0 or spec["new_texture_count"] != 0 or spec["protected_existing_packages"] != 72:
        raise ValueError("Render-only repair cannot create or omit packages")
    if spec["shots"] != wood.SHOTS or spec["output_name"] != "render_02" or spec["initial_or_fresh_execution_allowed"]:
        raise ValueError("Exact six-shot render-only scope required")
    rock.check_records(spec["source_files"] + spec["saved_material_package_files"] + [spec["original_spec"]])
    if spec != plan():
        raise ValueError("Repair differs from actual preserved evidence or material candidate")
    return rock.read_json(Path(spec["original_spec"]["file"]))


@contextmanager
def proven_names_only(evidence):
    original = wood.SLOTS
    expected = {(name, index): (source, family) for name, slots in original.items() for index, (source, family) in slots.items()}
    observed = {(row["component"], row["slot"]): (row["source_name"], row["family"]) for row in evidence}
    if observed != expected or len(evidence) != 7:
        raise ValueError("The temporary audit mapping cannot add, remove or change semantic slots")
    mapped = {}
    for row in evidence:
        allowed = ALIASES.get(row["component"], (row["source_name"], row["source_name"]))
        if (row["source_name"], row["ue_slot_name"]) != allowed:
            raise ValueError("No unproven identifier normalization is permitted")
        mapped.setdefault(row["component"], {})[row["slot"]] = (row["ue_slot_name"], row["family"])
    try:
        wood.SLOTS = mapped
        yield
    finally:
        wood.SLOTS = original


def audit_loaded_slots(meshes, evidence):
    for row in evidence:
        mesh = meshes[row["component"]]
        slot = list(mesh.get_editor_property("static_materials"))[row["slot"]]
        material = mesh.get_material(row["slot"])
        if mesh.get_path_name() != row["original_mesh_path"] or str(slot.get_editor_property("material_slot_name")) != row["ue_slot_name"]:
            raise ValueError("Actual loaded mesh or UE slot differs from frozen original fresh proof")
        if material.get_path_name() != row["original_material_path"] or material.get_class().get_name() != "Material":
            raise ValueError("Actual original material differs from frozen original fresh proof")


class ExactSlotReview(wood.WoodReview):
    def __init__(self, unreal, args, context, spec, fresh, repair):
        self.repair = repair
        super().__init__(unreal, args, context, spec, fresh)
        self.report.update(repair_version=VERSION, repair_fingerprint=repair["fingerprint"],
                           repair_tool=rock.file_record(__file__), exact_slot_mapping=repair["slot_evidence"],
                           material_parameters_changed_by_repair=False, additional_packages_created=0)

    def audit_components(self):
        audit_loaded_slots(self.meshes, self.repair["slot_evidence"])
        with proven_names_only(self.repair["slot_evidence"]):
            actual = super().audit_components()
        actual["seven_exact_imported_names_and_original_material_objects_verified"] = True
        return actual

    def finish(self, status):
        global SESSION
        if self.finished:
            return
        try:
            validate_repair(self.repair)
            self.report["repair_evidence_unchanged"] = True
        except Exception as error:
            self.report["repair_preservation_error"], status = str(error), "failed"
        try:
            super().finish(status)
        finally:
            SESSION = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--phase", choices=("validate", "render"), default=os.environ.get("CIVWAR_ROCK_WOOD_REPAIR_PHASE", "validate"))
    parser.add_argument("--spec", type=Path, default=os.environ.get("CIVWAR_ROCK_WOOD_REPAIR_SPEC", str(DEFAULT_SPEC)))
    parser.add_argument("--log-file", type=Path, default=os.environ.get("CIVWAR_ROCK_WOOD_REPAIR_LOG"))
    args, _ = parser.parse_known_args()
    if args.plan:
        print(json.dumps(plan(), ensure_ascii=True))
        return
    repair = rock.read_json(args.spec)
    spec = validate_repair(repair)
    if args.phase == "validate":
        print(json.dumps({"status": "render_only_repair_validated_without_unreal", "fingerprint": repair["fingerprint"], "new_packages": 0}, ensure_ascii=True))
        return
    if os.environ.get("CIVWAR_ROCK_WOOD_REPAIR_TOKEN") != repair["fingerprint"]:
        raise ValueError("Root authorization token for this exact repair required")
    output = FOLDER / repair["output_name"]
    if output.exists():
        raise FileExistsError("Never overwrite a previous or partial render")
    fresh = rock.read_json(FOLDER / "fresh_01.json")
    wood.check_fresh(spec, fresh)
    context = renderer.input_context(rock.DELIVERY / "ue_fresh_01.json")
    context["dependencies"].extend(spec["source_files"] + fresh["package_files"] + repair["source_files"] + [rock.file_record(args.spec)])
    import unreal
    output.mkdir()
    renderer.SHOTS = wood.SHOTS
    render_args = SimpleNamespace(fresh_report=rock.DELIVERY / "ue_fresh_01.json", output=output,
                                  log_file=args.log_file, size=512, timeout=160)
    global SESSION
    SESSION = ExactSlotReview(unreal, render_args, context, spec, fresh, repair)
    try:
        SESSION.setup()
    except Exception as error:
        SESSION.report["error"] = str(error)
        SESSION.finish("failed_before_capture")
        raise


if __name__ == "__main__":
    main()
