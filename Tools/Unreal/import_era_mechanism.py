"""Import real articulated parts and emit an EraArt entry with actual UE paths.

Run only in a root-leased UE Python process:
    run(unreal, mechanism_manifest_path, report_path)
or set CIVWAR_MECHANISM_IMPORT_PLAN to {entries:[{manifest,report}]}.

This reuses the corrected static importer for FBX units, PBR and measurements.
It never modifies EraArt/default flags/Cook directories. Archer platforms use
import_era_assets.run; crew uses the character importer and is assembled after
both actual import reports exist.
"""
from __future__ import annotations

import copy
import importlib.util
import math
import os
from pathlib import Path
import traceback

_spec = importlib.util.spec_from_file_location("mechanism_static_import", Path(__file__).with_name("import_era_assets.py"))
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)


def mechanical_measurements(u, mesh, row):
    evidence = row.get("ue_triangle_filter_evidence")
    if not evidence:
        return static.mesh_measurements(u, mesh, row)
    if static.sha(evidence["source_blend"]["path"]) != evidence["source_blend"]["sha256"]:
        raise ValueError("Measured triangle source changed")
    rejected = evidence["faces"]
    if len({face["id"] for face in rejected}) != len(rejected):
        raise ValueError("Duplicate triangle filter evidence")
    for face in rejected:
        # UE5.8 FbxStaticMeshImport::GetTriangleAreaThreshold uses SMALL_NUMBER
        # on squared cross-product magnitude in cm. These are positive-area
        # source micro-faces, not arbitrary missing geometry.
        a, b, c = [[float(value)*100 for value in point] for point in face["vertices"]]
        ab, ac = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        cross = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
        squared = sum(value*value for value in cross)
        if not 0 <= face["id"] < row["triangles"] or not 0 < squared < 1e-8:
            raise ValueError("Triangle loss is not explained by UE's actual area threshold")
        if abs(math.sqrt(squared)/20000-face["area_m2"]) > 1e-12:
            raise ValueError("Triangle filter evidence does not match measured geometry")
    measured = static.mesh_measurements(u, mesh, {**row, "triangles": row["triangles"]-len(rejected)})
    measured.update(triangles_removed_by_import=len(rejected), source_triangles=row["triangles"],
                    ue_small_area_triangles=len(rejected), ue_squared_cross_threshold_cm4=1e-8)
    return measured


def mechanical_material(u, row, destination, red=False):
    material = static.material(u, row, destination, red)
    recipe = row.get("dynamic_emissive")
    if not recipe:
        return material
    lib = u.MaterialEditingLibrary
    parameter_name = recipe["parameter"]
    existing_names = [str(name) for name in lib.get_scalar_parameter_names(material)]
    if parameter_name not in existing_names:
        parameter = lib.create_material_expression(material, u.MaterialExpressionScalarParameter)
        parameter.set_editor_property("parameter_name", parameter_name)
        parameter.set_editor_property("default_value", float(recipe["default"]))
        color = lib.create_material_expression(material, u.MaterialExpressionConstant3Vector)
        color.set_editor_property("constant", u.LinearColor(*recipe["color"], 1))
        multiply = lib.create_material_expression(material, u.MaterialExpressionMultiply)
        if (not lib.connect_material_expressions(color, "", multiply, "A")
                or not lib.connect_material_expressions(parameter, "", multiply, "B")
                or not lib.connect_material_property(multiply, "", u.MaterialProperty.MP_EMISSIVE_COLOR)):
            raise RuntimeError("Emitter parameter graph connection failed")
        lib.layout_material_expressions(material)
        lib.recompile_material(material)
        u.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
    if parameter_name not in [str(name) for name in lib.get_scalar_parameter_names(material)]:
        raise RuntimeError("Actual emitter scalar parameter missing")
    return material


def run(u, manifest_path, report_path):
    manifest_path, report_path = static.resolve(manifest_path), static.resolve(report_path)
    source = static.read(manifest_path)
    if source["status"] != "mechanism_prepared_pending_unreal" or source["kind"] != "mechanical_turret":
        raise ValueError("Expected an actually prepared articulated mechanism")
    if static.sha(source["source"]["path"]) != source["source"]["sha256"]:
        raise ValueError("Original source changed")
    for row in source["meshes"]:
        for record in static.records(row):
            if static.sha(record["path"]) != record["sha256"]:
                raise ValueError("Prepared mechanism input changed: "+record["path"])
    destination = "/Game/ArtPilot/EraMechanisms/" + source["asset_id"] + "/h" + static.sha(manifest_path)[:16]
    imported = {}
    for row in source["meshes"]:
        name = "SM_" + source["asset_id"] + "_" + row["id"]
        mesh = static.import_asset(u, row["exports"]["fbx"]["path"], destination + "/Meshes",
                                   name, static.static_options(u), u.FbxFactory())
        material_rows = {r["slot_name"]: r for r in row["materials"]}
        teams = []
        for index, slot in enumerate(mesh.get_editor_property("static_materials")):
            slot_name = str(slot.get_editor_property("material_slot_name"))
            if slot_name not in material_rows:
                slot_name = str(slot.get_editor_property("imported_material_slot_name"))
            if slot_name not in material_rows:
                raise ValueError("Unknown real material slot: "+slot_name)
            material = material_rows[slot_name]
            blue = mechanical_material(u, material, destination+"/Materials")
            red = mechanical_material(u, material, destination+"/Materials", True) if material.get("team_cloth") else blue
            mesh.set_material(index, blue)
            teams.append({"slot": index, "path": blue.get_path_name(), "red_path": red.get_path_name()})
        bounds = mechanical_measurements(u, mesh, row)
        u.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
        imported[row["id"]] = {"static_mesh": mesh.get_path_name(), "team_materials": teams, "bounds_cm": bounds}
    parts = []
    for row in source["parts"]:
        part = copy.deepcopy(row)
        real = imported[part.pop("mesh_id")]
        part.update(static_mesh=real["static_mesh"], team_materials=real["team_materials"])
        parts.append(part)
    # Deliberately inactive until root inspects actual DCC/UE/game output.
    runtime = {"asset_id": source["asset_id"], "kind": "mechanical_turret",
               "enabled": False, "default_runtime_enabled": False, "preview_enabled": False,
               "parts": parts, "muzzle": source["muzzle"], "fire_animation": source["fire_animation"],
               "production_approved": False}
    u.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    result = {"asset_id": source["asset_id"], "status": "imported_mechanism_pending_gameplay",
              "source_manifest": str(manifest_path), "source_manifest_sha256": static.sha(manifest_path),
              "process_id": os.getpid(), "destination": destination, "meshes": imported,
              "runtime_entry": runtime, "packages": static.snapshot(u, destination), "failures": [],
              "remaining": ["actual_gameplay"], "production_approved": False}
    static.write(report_path, result)
    return result


def fresh(u, report_path):
    previous = static.read(report_path)
    if static.sha(previous["source_manifest"]) != previous["source_manifest_sha256"]:
        raise ValueError("Prepared manifest changed")
    source = static.read(previous["source_manifest"])
    for record in previous["packages"]:
        if static.sha(record["path"]) != record["sha256"] or not u.EditorAssetLibrary.load_asset(record["asset"]):
            raise ValueError("Saved package missing/changed: "+record["asset"])
    for mesh in source["meshes"]:
        actual = u.EditorAssetLibrary.load_asset(previous["meshes"][mesh["id"]]["static_mesh"])
        mechanical_measurements(u, actual, mesh)
    for record in previous["packages"]:
        if static.sha(record["path"]) != record["sha256"]:
            raise ValueError("Read-only load changed a package")
    return {"asset_id": source["asset_id"], "status": "fresh_passed", "packages": len(previous["packages"])}


def main():
    import unreal
    plan_path = static.resolve(os.environ["CIVWAR_MECHANISM_IMPORT_PLAN"])
    stage = os.environ.get("CIVWAR_MECHANISM_IMPORT_STAGE", "initial")
    if stage not in {"initial", "fresh"}:
        raise ValueError("Unknown import stage")
    results = []
    for entry in static.read(plan_path)["entries"]:
        try:
            initial_fn, fresh_fn = (static.run, static.fresh) if entry.get("kind") == "static" else (run, fresh)
            result = initial_fn(unreal, entry["manifest"], entry["report"]) if stage == "initial" else fresh_fn(unreal, static.resolve(entry["report"]))
        except Exception as error:
            result = {"manifest": entry["manifest"], "status": "failed",
                      "error": str(error), "traceback": traceback.format_exc()}
        results.append(result)
        static.write(plan_path.with_name(stage+"_mechanism_import.json"), {"results": results})
    if any(result["status"] == "failed" for result in results):
        raise RuntimeError("Mechanism import failed; see the batch report")


if __name__ == "__main__":
    main()
