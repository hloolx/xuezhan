"""Hash-isolated RockTower import and independent read-only UE reopen validation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tools"))
from import_art_pilot import inspect_asset, sha256
from inspect_art_materials import audit_meshes, source_materials

BASE = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/rock_tower_v01"
DELIVERY = BASE / "delivery_v02"
MANIFEST_SHA = "2b803ea029cd33e22979b59e7a1871ab3ad7b3a31007a3e6ab5f172a5144c081"
VERSION = "rock_tower_native_glb_v1"
EXPECTED_TRIANGLES = {"RT_Frame": 7944, "RT_Arm": 3012, "RT_Stone": 80, "RT_Cloth": 20,
                      "RT_Adapter_front_negative_y": 96, "RT_Adapter_front_positive_y": 88,
                      "RT_Adapter_rear": 120}
POSITION_TOLERANCE_CM = 0.001
UV_TOLERANCE = 0.000001
NORMAL_TOLERANCE = 0.002
BUILD_SETTINGS = {"bRemoveDegenerates": False, "bRecomputeNormals": False,
                  "bRecomputeTangents": True, "bUseMikkTSpace": True,
                  "bUseFullPrecisionUVs": True, "bUseHighPrecisionTangentBasis": True}
IMPORT_SETTINGS = {"pipeline": VERSION, "format": "glb", "native_pbr": True,
                   "build_settings": BUILD_SETTINGS, "build_nanite": False,
                   "collision": False, "lod_group": "None", "combine": "ALL",
                   "material_overrides": {}, "material_repairs": False,
                   "material_reuse": False, "automatic_mesh_alignment": False}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def resolve_record(record):
    path = Path(record["file"])
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def file_record(path):
    path = Path(path).resolve()
    return {"file": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def check_records(records):
    for record in records:
        path = resolve_record(record)
        if not path.is_file() or path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError("Frozen evidence changed or missing: " + str(path))


def write_new(path, document):
    path = Path(path).resolve()
    if not path.is_relative_to(BASE.resolve()):
        raise ValueError("Report must remain inside the owned RockTower evidence directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def gltf_point_to_ue(point):
    return (100 * point[0], 100 * point[2], 100 * point[1])


def blender_point_to_ue(point):
    return (100 * point[0], -100 * point[1], 100 * point[2])


def read_glb(path):
    data = Path(path).read_bytes()
    if struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
        raise ValueError("Invalid embedded GLB header")
    document, binary, cursor = None, None, 12
    while cursor < len(data):
        length, kind = struct.unpack_from("<II", data, cursor)
        if length > len(data) - cursor - 8:
            raise ValueError("Truncated GLB chunk")
        chunk = data[cursor + 8:cursor + 8 + length]
        cursor += 8 + length
        if kind == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif kind == 0x004E4942:
            binary = chunk
    if document is None or binary is None or len(document["meshes"]) != 1:
        raise ValueError("Expected one embedded static mesh")
    if document.get("animations") or document.get("skins") or document.get("images"):
        raise ValueError("This constant-PBR rigid delivery must not contain animation, skin or images")
    if len(document["nodes"]) != 1 or document["nodes"][0].get("mesh") != 0:
        raise ValueError("Expected exactly one identity mesh node")
    if set(document["nodes"][0]) & {"matrix", "translation", "rotation", "scale", "skin"}:
        raise ValueError("Nonidentity node: do not ignore or apply an additional pivot transform")

    def accessor(index):
        entry = document["accessors"][index]
        if entry.get("sparse") or entry.get("normalized"):
            raise ValueError("Unsupported sparse/normalized accessor")
        view = document["bufferViews"][entry["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError("External buffer not permitted")
        component = {5126: "f", 5123: "H", 5125: "I"}[entry["componentType"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[entry["type"]]
        unpacker = struct.Struct("<" + component * width)
        start = view.get("byteOffset", 0) + entry.get("byteOffset", 0)
        stride = view.get("byteStride", unpacker.size)
        return [unpacker.unpack_from(binary, start + offset * stride) for offset in range(entry["count"])]

    rows, primitives = [], []
    for primitive in document["meshes"][0]["primitives"]:
        if primitive.get("mode", 4) != 4 or primitive.get("targets"):
            raise ValueError("Only rigid indexed triangles are allowed")
        attributes = primitive["attributes"]
        positions = accessor(attributes["POSITION"])
        normals = accessor(attributes["NORMAL"])
        uvs = accessor(attributes["TEXCOORD_0"])
        indices = [entry[0] for entry in accessor(primitive["indices"])]
        if len(indices) % 3 or not len(positions) == len(normals) == len(uvs):
            raise ValueError("Mismatched indexed geometry attributes")
        material = document["materials"][primitive["material"]]["name"]
        corners = [(*gltf_point_to_ue(position), *uv, normal[0], normal[2], normal[1])
                   for position, uv, normal in zip(positions, uvs, normals)]
        if any(not math.isfinite(value) for corner in corners for value in corner):
            raise ValueError("Nonfinite source surface")
        rows.extend({"material": material, "corners": [corners[index] for index in indices[offset:offset + 3]]}
                    for offset in range(0, len(indices), 3))
        primitives.append({"material": material, "triangles": len(indices) // 3, "vertices": len(positions)})
    if len({row["material"] for row in primitives}) != len(primitives):
        raise ValueError("Unexpected duplicate source material primitives")
    return rows, primitives


def expected_bounds(rows):
    points = [corner[:3] for row in rows for corner in row["corners"]]
    return {"min": [min(point[axis] for point in points) for axis in range(3)],
            "max": [max(point[axis] for point in points) for axis in range(3)]}


def compare_surface(expected, observed):
    if len(expected) != len(observed):
        raise ValueError("Source/render triangle counts differ")
    cell = POSITION_TOLERANCE_CM
    buckets = defaultdict(list)

    def key(row):
        return tuple(math.floor(sum(corner[axis] for corner in row["corners"]) / (3 * cell)) for axis in range(3))

    for index, row in enumerate(expected):
        buckets[(row["material"], key(row))].append(index)
    offsets = tuple(itertools.product((-1, 0, 1), repeat=3))
    permutations = tuple(itertools.permutations(range(3)))
    consumed, maxima = set(), [0.0, 0.0, 0.0]
    for actual in observed:
        if len(actual["corners"]) != 3 or any(len(corner) != 8 or any(not math.isfinite(value) for value in corner) for corner in actual["corners"]):
            raise ValueError("Nonfinite or malformed UE surface")
        bucket = key(actual)
        candidates = []
        for offset in offsets:
            nearby = tuple(value + delta for value, delta in zip(bucket, offset))
            for index in buckets.get((actual["material"], nearby), ()):
                if index in consumed:
                    continue
                wanted = expected[index]
                for order in permutations:
                    errors = (max(math.dist(actual["corners"][corner][:3], wanted["corners"][order[corner]][:3]) for corner in range(3)),
                              max(abs(actual["corners"][corner][axis] - wanted["corners"][order[corner]][axis]) for corner in range(3) for axis in (3, 4)),
                              max(math.dist(actual["corners"][corner][5:], wanted["corners"][order[corner]][5:]) for corner in range(3)))
                    if all(error <= limit for error, limit in zip(errors, (POSITION_TOLERANCE_CM, UV_TOLERANCE, NORMAL_TOLERANCE))):
                        candidates.append((*errors, index))
        if not candidates:
            raise ValueError("No unique source triangle with matching material/position/UV/normal: " + str(actual))
        *errors, index = min(candidates)
        consumed.add(index)
        maxima = [max(previous, error) for previous, error in zip(maxima, errors)]
    if len(consumed) != len(expected):
        raise ValueError("Not all source triangles were consumed exactly once")
    return {"status": "passed", "triangles": len(expected), "source_material_triangle_counts": dict(Counter(row["material"] for row in expected)),
            "max_position_error_cm": maxima[0], "max_uv_error": maxima[1], "max_normal_vector_error": maxima[2],
            "position_tolerance_cm": POSITION_TOLERANCE_CM, "uv_tolerance": UV_TOLERANCE, "normal_tolerance": NORMAL_TOLERANCE,
            "scope": "Every actual render triangle with material, UV0 and normal; corner order is unordered, winding/tangent parity still needs rendered review."}


def dry_plan():
    manifest_path, index_path = DELIVERY / "delivery_manifest.json", DELIVERY / "ue_delivery_index.json"
    if sha256(manifest_path) != MANIFEST_SHA:
        raise ValueError("Only the frozen passed delivery_v02 is eligible")
    manifest, index = read_json(manifest_path), read_json(index_path)
    review_path = BASE / "assembly_v03/visual_review.json"
    if not read_json(review_path)["root_review"]["dcc_controlled_assembly_approved"]:
        raise ValueError("Missing actual root DCC assembly review")
    if manifest.get("blender_fbx_glb_roundtrip_passed") is not True or manifest.get("source_geometry_unchanged") is not True:
        raise ValueError("DCC surface/roundtrip gate is not passed")
    if index["delivery_manifest"]["sha256"] != MANIFEST_SHA or not index.get("dcc_delivery_numeric_pass"):
        raise ValueError("Delivery index is not bound to the passed manifest")
    parts = index["parts"] + [platform["adapter"] for platform in index["platforms"]]
    if {part["name"]: part["triangles"] for part in parts} != EXPECTED_TRIANGLES or len(parts) != 7:
        raise ValueError("Unexpected seven-part delivery")
    evidence = [file_record(path) for path in (manifest_path, index_path, review_path, Path(__file__),
                ROOT / "Tools/import_art_pilot.py", ROOT / "Tools/inspect_art_materials.py")]
    entries = []
    for part in parts:
        check_records([part["glb"], part["fbx"], part["surface_reference"]])
        source = resolve_record(part["glb"])
        rows, primitives = read_glb(source)
        if len(rows) != part["triangles"] or len(primitives) != part["material_sections"]:
            raise ValueError("Actual GLB geometry differs from grouped delivery")
        material_names = {primitive["material"]: re.sub(r"\.\d{3}$", "", primitive["material"]) for primitive in primitives}
        if set(part["materials"]) != set(material_names.values()) or len(set(material_names.values())) != len(material_names):
            raise ValueError("GLB material primitives differ from approved groups")
        bounds = expected_bounds(rows)
        old_bounds = part["local_bounds_blender_m"]
        converted_min = blender_point_to_ue((old_bounds["min"][0], old_bounds["max"][1], old_bounds["min"][2]))
        converted_max = blender_point_to_ue((old_bounds["max"][0], old_bounds["min"][1], old_bounds["max"][2]))
        if any(abs(actual - wanted) > POSITION_TOLERANCE_CM for key_name, wanted_values in (("min", converted_min), ("max", converted_max)) for actual, wanted in zip(bounds[key_name], wanted_values)):
            raise ValueError("GLB no longer preserves its pivot-local Blender dimensions")
        source_info = source_materials(source)
        if source_info["image_count"] != 0 or source_info["extensions_required"]:
            raise ValueError("Unexpected texture/extension payload")
        for material in source_info["materials"]:
            expected = part["materials"][material_names[material["name"]]]
            values = material["channels"]
            for channel, wanted in (("base_color", expected["base_color_linear"]), ("metallic", expected["metallic"]), ("roughness", expected["roughness"])):
                actual = values[channel]["factor"]
                actual, wanted = (actual, wanted) if isinstance(actual, list) else ([actual], [wanted])
                if len(actual) != len(wanted) or any(abs(left - right) > 0.00001 for left, right in zip(actual, wanted)):
                    raise ValueError("GLB PBR factors differ from grouped source")
        evidence.extend(file_record(resolve_record(part[kind])) for kind in ("glb", "fbx", "surface_reference"))
        entries.append({"name": part["name"], "config_key": part["name"].removeprefix("RT_"),
                        "source": file_record(source), "triangles": len(rows), "primitives": primitives,
                        "material_slots": len(primitives), "bounds_ue_cm": bounds,
                        "materials": part["materials"], "source_to_dcc_material_names": material_names,
                        "local_pivot_preserved": "Identity GLB node; every vertex is checked in the unchanged local basis."})
    fingerprint = hashlib.sha256(json.dumps({"evidence": evidence, "settings": IMPORT_SETTINGS}, sort_keys=True).encode()).hexdigest()[:16]
    destination = "/Game/ArtPilot/RockTower/h" + fingerprint
    for entry in entries:
        entry["destination"] = destination + "/" + entry["name"]
        entry["predicted_mesh_path"] = entry["destination"] + "/" + entry["name"] + "." + entry["name"]
    return {"schema_version": 1, "version": VERSION, "asset_id": "Turret_RockTower", "dry_run": True,
            "status": "ready_for_root_controlled_import_not_executed", "destination": destination,
            "settings": IMPORT_SETTINGS, "source_evidence": evidence, "entries": entries,
            "basis": index["basis"], "anchors": index["anchors"], "platforms": [{key: value for key, value in platform.items() if key != "adapter"} for platform in index["platforms"]],
            "timing": index["timing"], "component_transforms": {part["name"]: part["component_transform_ue"] for part in index["parts"]},
            "source_choice": "GLB: all seven actual DCC position/UV/normal/PBR roundtrips passed; native PBR avoids reconstructing FBX factors.",
            "material_policy": "No repair, override, graph replacement or usage mutation. Preserve actual iron/steel metallic and cloth roughness. ISM-only usage warning is recorded but not applicable to StaticMeshComponent pilot.",
            "api_contract": {"section_material": "StaticMeshEditorSubsystem.GetLODMaterialSlot reads actual SectionInfoMap; CDO fallback only for stateless read methods when no editor subsystem exists in commandlet.",
                             "native_properties": "get/set_editor_property accepts original reflected names; bUseFullPrecisionUVs and bUseHighPrecisionTangentBasis are set before import.",
                             "render_data": "ProceduralMeshLibrary.get_section_from_static_mesh reads real LOD0 render positions/normals/UV0; no allow_cpu_access mutation, editor-only scope."},
            "expected_owned_packages": {"StaticMesh": 7, "Material": 14},
            "remaining_gates": ["Actual initial UE import and all surface/PBR/build checks", "All saved package hashes and independent fresh-process reopen", "Both-team physical assembly, release path, FireSeq timing and in-game views/performance"],
            "production_approved": False, "runtime_integrated": False, "ue_structural_approved": False}


def package_file(asset_path, destination, content):
    if not re.fullmatch(r"/Game/ArtPilot/RockTower/h[0-9a-f]{16}", destination):
        raise ValueError("Invalid isolated destination")
    if not asset_path.startswith(destination + "/") or any(piece in {"", ".", ".."} for piece in asset_path.split("/")[1:]) or "\\" in asset_path:
        raise ValueError("Package escaped the exact isolated hash directory")
    package = asset_path.split(".")[0]
    result = (Path(content) / (package[len("/Game/"):] + ".uasset")).resolve()
    if not result.is_relative_to(Path(content).resolve()):
        raise ValueError("Package file escaped project Content")
    return result


def check_package_set(plan, records, actual_paths, content):
    expected_paths = {record["asset_path"] for record in records}
    if len(expected_paths) != len(records) or set(actual_paths) != expected_paths:
        raise ValueError("Registry set differs from exact saved package set")
    if Counter(record["class_name"] for record in records) != Counter(plan["expected_owned_packages"]):
        raise ValueError("Expected seven StaticMeshes and fourteen independent native materials")
    folder = Path(content) / plan["destination"][len("/Game/"):]
    expected_files = {package_file(record["asset_path"], plan["destination"], content) for record in records}
    if {path.resolve() for path in folder.rglob("*.uasset")} != expected_files:
        raise ValueError("Disk .uasset set differs from exact package manifest")
    check_records(records)
    for record in records:
        if sha256(package_file(record["asset_path"], plan["destination"], content)) != record["sha256"]:
            raise ValueError("Actual UE project resolves different package bytes")


def static_reader(unreal):
    reader = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    return reader if reader else unreal.get_default_object(unreal.StaticMeshEditorSubsystem)


def import_entry(unreal, entry):
    task = unreal.AssetImportTask()
    for key, value in {"filename": entry["source"]["file"], "destination_path": entry["destination"],
                       "destination_name": entry["name"], "replace_existing": False,
                       "automated": True, "save": True, "async_": False}.items():
        task.set_editor_property(key, value)
    pipeline = unreal.InterchangeGenericAssetsPipeline()
    for key, value in {"asset_name": entry["name"], "scene_name_sub_folder": False, "asset_type_sub_folders": False}.items():
        pipeline.set_editor_property(key, value)
    materials = pipeline.get_editor_property("material_pipeline")
    for key, value in {"import_materials": True, "create_new_materials": True, "reuse_existing_materials": False,
                       "material_import": unreal.InterchangeMaterialImportOption.IMPORT_AS_MATERIALS}.items():
        materials.set_editor_property(key, value)
    materials.get_editor_property("texture_pipeline").set_editor_property("import_textures", False)
    meshes = pipeline.get_editor_property("mesh_pipeline")
    for key, value in {"import_static_meshes": True, "import_skeletal_meshes": False, "create_physics_asset": False,
                       "collision": False, "build_nanite": False, "lod_group": "None",
                       "combine_static_meshes_behavior": unreal.InterchangeCombineStaticMeshesBehavior.ALL}.items():
        meshes.set_editor_property(key, value)
    common = pipeline.get_editor_property("common_meshes_properties")
    for key, value in BUILD_SETTINGS.items():
        common.set_editor_property(key, value)
        if common.get_editor_property(key) != value:
            raise ValueError("Import pipeline did not retain " + key)
    pipeline.get_editor_property("animation_pipeline").set_editor_property("import_animations", False)
    stack = unreal.InterchangePipelineStackOverride()
    stack.add_pipeline(pipeline)
    task.set_editor_property("options", stack)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    objects = list(task.get_objects())
    if not objects:
        objects = [unreal.EditorAssetLibrary.load_asset(path) for path in task.get_editor_property("imported_object_paths")]
    if len([obj for obj in objects if isinstance(obj, unreal.StaticMesh)]) != 1:
        raise ValueError("Import did not return exactly one StaticMesh")


def audit_materials(unreal, mesh, entry):
    audit = audit_meshes(unreal, [mesh], entry["source"]["file"], repair=False)
    ignored = [warning for warning in audit["warnings"] if warning.endswith(":ism_usage_not_persisted_on_entire_parent_chain")]
    blocking = [warning for warning in audit["warnings"] if warning not in ignored]
    if blocking or len(audit["materials"]) != entry["material_slots"]:
        raise ValueError("Native PBR audit failed: " + str(blocking))
    mapping = {}
    for material in audit["materials"]:
        if not material.get("source_material") or material.get("textures") or not material["path"].startswith(entry["destination"] + "/"):
            raise ValueError("Material is missing its local source mapping or unexpectedly uses textures")
        for channel in ("base_color", "roughness", "metallic", "normal"):
            evidence = material["channels"][channel]
            if not evidence["connected"] or evidence["method"] != "ue58_native_gltf_function_binding" or evidence["issues"]:
                raise ValueError("Native PBR channel has no verified effective binding: " + channel)
        mapping[material["path"]] = material["source_material"]["name"]
    audit["pilot_scope_ignored_warnings"] = ignored
    audit["pilot_scope_warning_reason"] = "StaticMeshComponent only, not instanced rendering; no usage flag modified. All warnings remain in the raw audit."
    audit["pilot_pbr_passed"] = True
    return audit, mapping


def inspect_mesh(unreal, entry, mesh):
    inspection = inspect_asset(unreal, mesh)
    if inspection["triangles_lod0"] != entry["triangles"] or inspection["source_mesh_triangles_lod0"] != entry["triangles"] or inspection["lod_count"] != 1 or inspection["nanite_enabled"] or len(inspection["material_slots"]) != entry["material_slots"]:
        raise ValueError("Actual mesh counts/LOD/material slots changed: " + entry["name"])
    bounds = mesh.get_bounds()
    observed_bounds = {"min": [float(getattr(bounds.origin, axis) - getattr(bounds.box_extent, axis)) for axis in ("x", "y", "z")],
                       "max": [float(getattr(bounds.origin, axis) + getattr(bounds.box_extent, axis)) for axis in ("x", "y", "z")]}
    if any(abs(actual - wanted) > POSITION_TOLERANCE_CM for side in ("min", "max") for actual, wanted in zip(observed_bounds[side], entry["bounds_ue_cm"][side])):
        raise ValueError("Local origin/scale/basis bounds changed: " + entry["name"])
    reader = static_reader(unreal)
    settings = reader.get_lod_build_settings(mesh, 0)
    actual_settings = {key: bool(settings.get_editor_property(key)) for key in BUILD_SETTINGS}
    if actual_settings != BUILD_SETTINGS:
        raise ValueError("Actual persisted LOD build settings differ: " + str(actual_settings))
    audit, material_names = audit_materials(unreal, mesh, entry)
    section_count = mesh.get_num_sections(0)
    if section_count != entry["material_slots"]:
        raise ValueError("Render section count changed")
    rows, sections = [], []
    for section_index in range(section_count):
        slot_index = reader.get_lod_material_slot(mesh, 0, section_index)
        if slot_index < 0 or slot_index >= entry["material_slots"]:
            raise ValueError("Actual section-to-material mapping is unavailable")
        material = mesh.get_material(slot_index)
        material_name = material_names.get(material.get_path_name()) if material else None
        if not material_name:
            raise ValueError("Render section is assigned an unverified source material")
        vertices, triangles, normals, uvs, tangents = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(mesh, 0, section_index)
        if not vertices or len(triangles) % 3 or not len(vertices) == len(normals) == len(uvs) == len(tangents):
            raise ValueError("Actual render section buffers are missing or inconsistent")
        corners = [(float(vertex.x), float(vertex.y), float(vertex.z), float(uv.x), float(uv.y), float(normal.x), float(normal.y), float(normal.z))
                   for vertex, uv, normal in zip(vertices, uvs, normals)]
        rows.extend({"material": material_name, "corners": [corners[index] for index in triangles[offset:offset + 3]]}
                    for offset in range(0, len(triangles), 3))
        sections.append({"section": section_index, "actual_material_slot": slot_index, "material_path": material.get_path_name(),
                         "source_material": material_name, "actual_render_vertices": len(vertices), "actual_render_triangles": len(triangles) // 3})
    source_rows, _ = read_glb(entry["source"]["file"])
    surface = compare_surface(source_rows, rows)
    return {"name": entry["name"], "config_key": entry["config_key"], "mesh": inspection, "bounds_ue_cm": observed_bounds,
            "build_settings": actual_settings, "render_sections": sections, "source_surface_correspondence": surface,
            "material_audit": audit, "local_origin_verified": True,
            "origin_evidence": "All render triangles agree in the unshifted local source basis, not a recentered bounding box."}


def load_entry_assets(unreal, entry):
    paths = list(unreal.EditorAssetLibrary.list_assets(entry["destination"], recursive=True, include_folder=False))
    objects = [unreal.EditorAssetLibrary.load_asset(path) for path in paths]
    if not all(objects) or Counter(obj.get_class().get_name() for obj in objects) != Counter({"StaticMesh": 1, "Material": entry["material_slots"]}):
        raise ValueError("Actual per-group package set is not one mesh plus its independent source materials")
    return objects, next(obj for obj in objects if isinstance(obj, unreal.StaticMesh))


def fresh_gate(plan, prior, current_pid):
    if prior.get("status") != "rock_tower_initial_saved_requires_fresh_reopen" or prior.get("dry_run") is not False or prior.get("structural_checks_passed") is not True:
        raise ValueError("Only a successful real saved initial import is eligible for reopen")
    if not prior.get("execution_process_id") or prior["execution_process_id"] == current_pid:
        raise ValueError("Independent fresh UE process is required")
    if prior.get("destination") != plan["destination"] or prior.get("source_evidence") != plan["source_evidence"]:
        raise ValueError("Initial source/settings/tool fingerprint differs from current frozen plan")
    if prior.get("disk_dependency_validation", {}).get("status") != "saved_pending_fresh_reopen":
        raise ValueError("Initial report has no complete saved-package baseline")


def execute(unreal, plan, mode, prior_path=None, progress=None):
    progress = progress if progress is not None else {}
    progress.update(destination=plan["destination"], results=[], imported_groups=[])
    library = unreal.EditorAssetLibrary
    content = Path(unreal.Paths.project_content_dir()).resolve()
    if content != (ROOT / "Content").resolve():
        raise ValueError("Refuse to import into another UE project's Content")
    check_records(plan["source_evidence"])
    prior = read_json(prior_path) if mode == "reopen" else None
    if prior is not None:
        fresh_gate(plan, prior, os.getpid())
        files = prior["disk_dependency_validation"]["files"]
        check_package_set(plan, files, library.list_assets(plan["destination"], recursive=True, include_folder=False), content)
    else:
        folder = content / plan["destination"][len("/Game/"):]
        if folder.exists() or library.does_directory_exist(plan["destination"]):
            raise FileExistsError("Never overwrite/reimport an existing isolated attempt; inspect prior evidence first")
        for entry in plan["entries"]:
            import_entry(unreal, entry)
            progress["imported_groups"].append(entry["name"])
    results, objects = [], []
    for entry in plan["entries"]:
        entry_objects, mesh = load_entry_assets(unreal, entry)
        objects.extend(entry_objects)
        results.append(inspect_mesh(unreal, entry, mesh))
        progress["results"] = results
    if prior is None:
        for obj in objects:
            if not library.save_loaded_asset(obj, only_if_is_dirty=False):
                raise ValueError("Explicit owned package save failed: " + obj.get_path_name())
        files = [dict(file_record(package_file(obj.get_path_name(), plan["destination"], content)),
                      asset_path=obj.get_path_name(), class_name=obj.get_class().get_name()) for obj in objects]
    check_package_set(plan, files, library.list_assets(plan["destination"], recursive=True, include_folder=False), content)
    check_records(plan["source_evidence"])
    mapping = {result["config_key"]: result["mesh"]["path"] for result in results}
    fresh = prior is not None
    return {"schema_version": 1, "version": VERSION, "asset_id": "Turret_RockTower", "dry_run": False,
            "status": "rock_tower_fresh_reopen_structural_checks_passed" if fresh else "rock_tower_initial_saved_requires_fresh_reopen",
            "execution_process_id": os.getpid(), "initial_process_id": prior["execution_process_id"] if fresh else os.getpid(),
            "destination": plan["destination"], "source_evidence": plan["source_evidence"], "settings": plan["settings"],
            "results": results, "structural_checks_passed": True, "validated_in_fresh_process": fresh,
            "read_only": fresh, "material_changes": [], "mesh_mapping": mapping,
            "meshes": mapping, "package_files": files, "source_files": plan["source_evidence"],
            "validation_process_id": os.getpid() if fresh else None,
            "disk_dependency_validation": {"status": "passed" if fresh else "saved_pending_fresh_reopen",
                                           "validated_in_fresh_process": fresh, "files": files,
                                           "prior_import_report": file_record(prior_path) if fresh else None,
                                           "initial_process_id": prior["execution_process_id"] if fresh else os.getpid(),
                                           "validation_process_id": os.getpid() if fresh else None},
            "config_candidate_not_written_to_content": {"asset_id": "Turret_RockTower", "enabled": False,
                "ue_structural_approved": fresh, "assembly_approved_for_pilot": False, "production_approved": False, "meshes": mapping},
            "anchors": plan["anchors"], "platforms": plan["platforms"], "component_transforms": plan["component_transforms"],
            "remaining_gates": ["Root approval and actual UE/game-camera assembly", "Both-team yaw/attachment/release and FireSeq phase", "Runtime performance; no production approval"],
            "production_approved": False, "runtime_integrated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "import", "reopen"), default=os.environ.get("CIVWAR_ROCK_TOWER_UE_MODE", "dry-run"))
    parser.add_argument("--report", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_UE_REPORT"))
    parser.add_argument("--prior-report", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_UE_PRIOR"))
    parser.add_argument("--spec", type=Path, default=os.environ.get("CIVWAR_ROCK_TOWER_UE_SPEC"))
    args, _ = parser.parse_known_args()
    if args.report and args.report.exists():
        raise FileExistsError("Never overwrite an execution report")
    if args.mode != "dry-run" and not args.report:
        raise ValueError("Actual execution requires a new report path")
    if args.mode == "reopen" and not args.prior_report:
        raise ValueError("Read-only reopen requires the successful initial report")
    progress = {}
    try:
        plan = dry_plan()
        if args.spec and read_json(args.spec) != plan:
            raise ValueError("Frozen execution spec no longer agrees with current inputs/settings/tool")
        if args.mode == "dry-run":
            document = plan
        else:
            import unreal
            document = execute(unreal, plan, args.mode, args.prior_report, progress)
            document["created_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        if args.report:
            write_new(args.report, {"status": "failed", "mode": args.mode, "error": str(exc),
                                    "execution_process_id": os.getpid(), "structural_checks_passed": False,
                                    "validated_in_fresh_process": False, "production_approved": False,
                                    "progress": progress,
                                    "instruction": "Preserve failed packages/report; do not silently overwrite or relax tolerances."})
        raise
    if args.report:
        write_new(args.report, document)
    print(json.dumps({"status": document["status"], "destination": document["destination"], "report": str(args.report), "production_approved": False}))


if __name__ == "__main__":
    main()
