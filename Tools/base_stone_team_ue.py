from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"
TEAM = PILOT / "team_color_v01"
sys.path.insert(0, str(ROOT / "Tools"))
sys.path.insert(0, str(ROOT / "Tools/Unreal"))
import import_stoneaxe_teamcolor as shared
import inspect_art_materials as material_audit

VERSION = "base_stone_native_pbr_main714_team_candidate_v1"
PREFIX = "/Game/ArtPilot/BaseStoneTeam/"
MASK_SHA = "657853f761746162b6e9123a5fc852266e1e3658d399d753b40d6e3a96888a04"
SOURCE_SHA = "23f0701d13e0edd1d4d788ff8725482ad8e0d9b1e129d14c2e523ab128ff31c4"
WRAPPER_CLASSES = {name: value for name, value in shared.NODE_CLASSES.items() if name not in {"base_color", "normal", "roughness", "metallic"}}
NODE_PREFIX = "BaseStoneTeam_"
read = shared.read
sha = shared.sha
file_record = shared.file_record


def resolved_record(record):
    path = Path(record.get("file", record.get("package_file", record.get("path", ""))))
    if not path.is_absolute():
        path = ROOT / path
    return {**record, "path": str(path.resolve())}


def check_records(records):
    for record in records:
        shared.check_record(resolved_record(record))


def validate_mask(report):
    required = {"selected_triangle_count": 714, "mask_pixels": 70868, "protected_uv_overlap_pixels": 0,
                "one_pixel_filter_footprint_protected_overlap_pixels": 0, "protected_gutter_pixels": 1,
                "selected_edge_pixels_retained_original_color_for_safety": 608,
                "nonblue_selected_region_pixels_preserved": 12227,
                "padding_added": False, "blur_applied": False, "mask_expanded": False,
                "all_cloth_coverage_approved": False}
    if any(report.get(name) != value for name, value in required.items()):
        raise ValueError("Approved safe1 semantic or UV protection contract differs")
    if report.get("selected_clusters") != [0, 1, 3, 4, 7] or report.get("held_clusters") != [2, 5, 6, 8]:
        raise ValueError("Main cloth selection expanded or held fragments changed")
    if report["mask"]["sha256"] != MASK_SHA or report["source"]["sha256"] != SOURCE_SHA:
        raise ValueError("Exact root-reviewed mask or source differs")
    return required


def source_inputs():
    paths = {"mask_report": TEAM / "main_cloth_candidate_v02_safe1/candidate_mask_report.json",
             "selection": TEAM / "root_main_cloth_candidate_selection.json", "held_review": TEAM / "held_review_v01.json",
             "controlled_ue_approval": TEAM / "controlled_ue_approval_v01.json",
             "base_fresh": PILOT / "ue_fresh_preflight/fresh_01.json",
             "stoneaxe_fresh": ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/stoneaxe_rig_pilot/team_color_v01/ue_fresh_02.json",
             "shared_shader_tool": Path(shared.__file__), "material_audit_tool": Path(material_audit.__file__)}
    mask_report, base, stone = (read(paths[name]) for name in ("mask_report", "base_fresh", "stoneaxe_fresh"))
    contract = validate_mask(mask_report)
    approval = read(paths["controlled_ue_approval"])
    if not approval.get("controlled_ue_derivative_authorized") or approval.get("mask_sha256") != MASK_SHA or approval.get("all_cloth_coverage_approved") is not False:
        raise ValueError("Exact limited root authorization for controlled UE derivative required")
    selection = read(paths["selection"])
    if not selection.get("root_semantic_candidate_approved") or selection.get("primary_cloth_candidate_clusters") != [0, 1, 3, 4, 7]:
        raise ValueError("Root semantic selection is missing")
    if read(paths["held_review"]).get("held_clusters_unchanged") != [2, 5, 6, 8]:
        raise ValueError("Held-fragment review changed")
    if base.get("status") != "base_stone_fresh_reopen_structural_and_coordinate_checks_passed" or not base.get("source_and_all_five_packages_unchanged"):
        raise ValueError("Base original fresh reopen did not pass")
    if not base.get("validated_in_fresh_process") or base["execution_process_id"] == base["initial_process_id"]:
        raise ValueError("Base fresh process identity was not verified")
    if stone.get("status") != "team_material_fresh_reopen_passed_pending_actual_color_review":
        raise ValueError("Frozen StoneAxe21 provenance unavailable")
    base_files = base["disk_dependency_validation"]["files"]
    stone_files = stone["frozen_packages"] + stone["result"]["disk_dependency_validation"]["files"]
    if len(base_files) != 5 or len(stone_files) != 21:
        raise ValueError("Expected exactly Base5 and StoneAxe21 frozen packages")
    frozen = [resolved_record(record) for record in base_files + stone_files]
    if len({record["path"] for record in frozen}) != 26:
        raise ValueError("Frozen package set is not26 unique dependencies")
    evidence = [resolved_record(mask_report[name]) for name in ("source", "base_color", "mask", "selection", "selected_geometry_coverage")]
    evidence.extend(resolved_record(record) for record in base["source_evidence"])
    check_records(frozen + evidence)
    sources = {name: file_record(path) for name, path in paths.items()}
    settings = {"version": VERSION, "tool_sha256": sha(__file__), "semantic_mask": contract,
                "held_clusters": [2, 5, 6, 8], "all_cloth_coverage_approved": False,
                "mask_policy": "NonColor/Grayscale/NoMipmaps/Nearest/Clamp/asset sampler",
                "formula": "original native BaseColor -> luminance-preserving masked lerp; other native outputs unchanged",
                "team_colors_linear": shared.TEAM_COLORS, "luminance_weights": shared.LUMINANCE,
                "parent_default_strength": 0.0}
    fingerprint = hashlib.sha256(json.dumps({"settings": settings, "sources": sources}, sort_keys=True).encode()).hexdigest()[:16]
    return {"sources": sources, "source_evidence": evidence, "frozen_packages": frozen, "settings": settings,
            "destination": PREFIX + "h" + fingerprint,
            "mesh": next(record["asset_path"] for record in base_files if record["class_name"] == "StaticMesh"),
            "original_material": next(record["asset_path"] for record in base_files if record["class_name"] == "Material"),
            "original_textures": sorted(record["asset_path"] for record in base_files if record["class_name"] == "Texture2D"),
            "mask_source": resolved_record(mask_report["mask"]), "source_glb": resolved_record(mask_report["source"])}


def package_file(content_dir, asset_path, destination):
    if not re.fullmatch(re.escape(PREFIX) + r"h[0-9a-f]{16}", destination):
        raise ValueError("Only new hash-isolated BaseStoneTeam branches may be written")
    package = asset_path.split(".")[0]
    if not package.startswith(destination + "/") or not re.fullmatch(r"[A-Za-z0-9_]+", package[len(destination) + 1:]):
        raise ValueError("Refuse writes outside isolated single-package team branch")
    return Path(content_dir).resolve() / (package[len("/Game/"):] + ".uasset")


def output_name(value):
    if isinstance(value, tuple) and len(value) == 2 and value[0] is True:
        return str(value[1])
    if isinstance(value, str):
        return value
    raise ValueError("Public graph output query failed: " + str(value))


def require_output(actual, requested):
    if actual != requested:
        raise ValueError("Exact expression output mismatch: " + str((actual, requested)))


def inputs(unreal, material, node):
    editing = unreal.MaterialEditingLibrary
    names = list(editing.get_material_expression_input_names(node))
    children = list(editing.get_inputs_for_material_expression(material, node))
    if len(names) != len(children):
        raise ValueError("Graph input names and sources have different counts")
    return [("" if str(name) == "None" else str(name), child) for name, child in zip(names, children)]


def graph_snapshot(unreal, material):
    editing = unreal.MaterialEditingLibrary
    records = {}
    for node in editing.get_material_expressions(material):
        if str(node.get_editor_property("desc")).startswith(NODE_PREFIX):
            continue
        record = {"class": node.get_class().get_name(), "inputs": [], "properties": {}}
        for name, child in inputs(unreal, material, node):
            record["inputs"].append({"pin": name, "node": child.get_name() if child else None,
                                     "output": output_name(editing.get_input_node_output_name_for_material_expression(node, child)) if child else None})
        for key in ("material_function", "texture", "parameter_name", "constant", "r", "g", "b", "a", "value", "default_value",
                    "sampler_type", "sampler_source", "mip_value_mode", "const_coordinate", "automatic_view_mip_bias"):
            value = material_audit.prop(node, key)
            if value is not None:
                record["properties"][key] = material_audit.value_json(value)
        records[node.get_name()] = record
    return records


def native_roots(unreal, material):
    editing = unreal.MaterialEditingLibrary
    return {channel: {"node": editing.get_material_property_input_node(material, getattr(unreal.MaterialProperty, enum_name)).get_name(),
                      "output": str(editing.get_material_property_input_node_output_name(material, getattr(unreal.MaterialProperty, enum_name)))}
            for channel, (enum_name, _, _, _) in material_audit.CHANNELS.items()}


def create_assets(unreal, context):
    library, editing = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
    destination = context["destination"]
    folder = Path(unreal.Paths.project_content_dir()).resolve() / destination[len("/Game/"):]
    if library.does_directory_exist(destination) or folder.exists():
        raise FileExistsError("Never overwrite or reuse partial derived assets: " + destination)
    task = unreal.AssetImportTask()
    shared.properties(task, {"filename": context["mask_source"]["path"], "destination_path": destination,
                            "destination_name": "T_Base_Stone_MainClothMask", "automated": True, "replace_existing": False,
                            "save": False, "async_": False, "factory": unreal.TextureFactory()})
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tools.import_asset_tasks([task])
    mask = library.load_asset(destination + "/T_Base_Stone_MainClothMask")
    if not isinstance(mask, unreal.Texture2D):
        raise TypeError("Mask did not import as Texture2D")
    shared.properties(mask, shared.mask_settings(unreal))
    material = library.duplicate_asset(context["original_material"], destination + "/M_Base_Stone_MainCloth")
    if not isinstance(material, unreal.Material):
        raise TypeError("Native PBR material duplication failed")
    original = library.load_asset(context["original_material"])
    if graph_snapshot(unreal, material) != graph_snapshot(unreal, original) or native_roots(unreal, material) != native_roots(unreal, original):
        raise ValueError("Duplicated native PBR is not structurally identical before wrapping")
    base_node = editing.get_material_property_input_node(material, unreal.MaterialProperty.MP_BASE_COLOR)
    base_output = str(editing.get_material_property_input_node_output_name(material, unreal.MaterialProperty.MP_BASE_COLOR))
    if base_output != "BaseColor":
        raise ValueError("Expected native BaseColor output, not raw texture")
    nodes = {"base_color": base_node}
    for index, (name, class_name) in enumerate(WRAPPER_CLASSES.items()):
        node = editing.create_material_expression(material, getattr(unreal, class_name), 400 + index % 4 * 260, index // 4 * 220)
        node.set_editor_property("desc", NODE_PREFIX + name)
        nodes[name] = node
    shared.properties(nodes["cloth_mask"], {"texture": mask, "sampler_type": unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE,
                                          "sampler_source": unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET})
    nodes["luminance_weights"].set_editor_property("constant", shared.color(unreal, shared.LUMINANCE))
    nodes["safe_team_luminance"].set_editor_property("const_b", .01)
    shared.properties(nodes["team_color"], {"parameter_name": "TeamColor", "default_value": shared.color(unreal, shared.TEAM_COLORS["Blue"])})
    shared.properties(nodes["team_strength"], {"parameter_name": "TeamColorStrength", "default_value": 0.0, "slider_min": 0.0, "slider_max": 1.0})
    for source, output, target, pin in shared.LINKS:
        if not editing.connect_material_expressions(nodes[source], base_output if source == "base_color" else output, nodes[target], pin):
            raise ValueError("Could not connect team wrapper: " + target + "." + pin)
    if not editing.connect_material_property(nodes["cloth_blend"], "", unreal.MaterialProperty.MP_BASE_COLOR):
        raise ValueError("Could not wrap only the BaseColor output")
    errors = list(editing.recompile_material(material))
    if errors:
        raise ValueError("Derived shader compile errors: " + str(errors))
    instances = {}
    for team, team_color in shared.TEAM_COLORS.items():
        instance = tools.create_asset("MI_Base_Stone_" + team, destination, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        if not instance:
            raise RuntimeError("Could not create isolated preview instance")
        editing.set_material_instance_parent(instance, material)
        shared.set_instance_parameters(unreal, instance, team_color)
        instances[team] = instance
    return mask, material, instances


def audit(unreal, context, mask, material, instances):
    editing, library = unreal.MaterialEditingLibrary, unreal.EditorAssetLibrary
    original = library.load_asset(context["original_material"])
    mesh = library.load_asset(context["mesh"])
    source = material_audit.source_materials(context["source_glb"]["path"])["materials"][0]
    source["channels"]["metallic"]["factor"] = 0
    original_audit = material_audit.inspect_material(unreal, original, source, repair=False)
    if original_audit["warnings"]:
        raise ValueError("Original native PBR audit failed: " + str(original_audit["warnings"]))
    original_graph, derived_graph = graph_snapshot(unreal, original), graph_snapshot(unreal, material)
    if original_graph != derived_graph:
        raise ValueError("Native PBR graph changed inside derived material")
    original_roots, derived_roots = native_roots(unreal, original), native_roots(unreal, material)
    for channel in ("normal", "roughness", "metallic"):
        if original_roots[channel] != derived_roots[channel]:
            raise ValueError("Native noncolor output changed: " + channel)
    for name in ("two_sided", "blend_mode", "shading_model", "dithered_lod_transition"):
        if material_audit.prop(original, name) != material_audit.prop(material, name):
            raise ValueError("Native material surface property changed: " + name)
    if not editing.has_material_usage(material, unreal.MaterialUsage.MATUSAGE_INSTANCED_STATIC_MESHES):
        raise ValueError("Derived material lost original ISM usage")
    if [slot.material_interface.get_path_name() for slot in mesh.get_editor_property("static_materials")] != [context["original_material"]]:
        raise ValueError("Frozen mesh material assignment changed")
    nodes = {str(node.get_editor_property("desc"))[len(NODE_PREFIX):]: node for node in editing.get_material_expressions(material)
             if str(node.get_editor_property("desc")).startswith(NODE_PREFIX)}
    if set(nodes) != set(WRAPPER_CLASSES):
        raise ValueError("Derived wrapper node set differs")
    for name, class_name in WRAPPER_CLASSES.items():
        if not isinstance(nodes[name], getattr(unreal, class_name)):
            raise ValueError("Wrapper node class differs: " + name)
    base_name = original_roots["base_color"]["node"]
    nodes["base_color"] = next(node for node in editing.get_material_expressions(material) if node.get_name() == base_name)
    links = {(target, pin): (source, "BaseColor" if source == "base_color" else output) for source, output, target, pin in shared.LINKS}
    audited_links = []
    for name in WRAPPER_CLASSES:
        for pin, child in inputs(unreal, material, nodes[name]):
            expected = links.get((name, pin))
            if child is None:
                if expected:
                    raise ValueError("Missing team wrapper input")
                continue
            if not expected or child != nodes[expected[0]]:
                raise ValueError("Unexpected team wrapper connection: " + name + "." + pin)
            actual_output = output_name(editing.get_input_node_output_name_for_material_expression(nodes[name], child))
            require_output(actual_output, expected[1])
            audited_links.append([expected[0], actual_output, name, pin])
    if len(audited_links) != len(shared.LINKS) or editing.get_material_property_input_node(material, unreal.MaterialProperty.MP_BASE_COLOR) != nodes["cloth_blend"]:
        raise ValueError("Team wrapper is not complete masked interpolation")
    for name, expected in shared.mask_settings(unreal).items():
        if mask.get_editor_property(name) != expected:
            raise ValueError("Mask sampler safety property differs: " + name)
    if [mask.blueprint_get_size_x(), mask.blueprint_get_size_y()] != [2048, 2048]:
        raise ValueError("Mask dimensions differ")
    if nodes["cloth_mask"].get_editor_property("texture") != mask or nodes["cloth_mask"].get_editor_property("sampler_type") != unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE or nodes["cloth_mask"].get_editor_property("sampler_source") != unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET:
        raise ValueError("Mask expression ignores exact noncolor asset sampler")
    if max(abs(actual - expected) for actual, expected in zip(shared.values(nodes["luminance_weights"].get_editor_property("constant")), shared.LUMINANCE)) > 1e-6:
        raise ValueError("Luminance weights differ")
    if abs(float(nodes["safe_team_luminance"].get_editor_property("const_b")) - .01) > 1e-6:
        raise ValueError("Luminance floor differs")
    if editing.get_material_default_scalar_parameter_value(material, "TeamColorStrength") != 0:
        raise ValueError("Default must retain unchanged original color")
    for team, instance in instances.items():
        if instance.get_editor_property("parent") != material or editing.get_material_instance_scalar_parameter_value(instance, "TeamColorStrength") != 1:
            raise ValueError("Persisted preview parent/strength differs")
        actual = shared.values(editing.get_material_instance_vector_parameter_value(instance, "TeamColor"))
        if max(abs(value - expected) for value, expected in zip(actual, shared.TEAM_COLORS[team])) > 1e-6:
            raise ValueError("Persisted preview color differs")
    return {"status": "passed", "original_native_material_audit": original_audit,
            "unchanged_native_graph": original_graph, "original_roots": original_roots, "derived_roots": derived_roots,
            "wrapper_links": audited_links, "native_graph_preserved": True, "original_mesh_assignment_unchanged": True,
            "mask_settings": {name: str(mask.get_editor_property(name)) for name in shared.mask_settings(unreal)},
            "all_cloth_coverage_approved": False, "runtime_approved": False}


def execute(unreal, context, prior=None):
    destination = context["destination"]
    if prior:
        if prior.get("status") != "base_team_material_persisted_requires_fresh_reopen" or prior.get("execution_process_id") == os.getpid():
            raise ValueError("Actual independent successful first-save report required")
        if prior.get("destination") != destination or prior.get("settings") != context["settings"] or prior.get("sources") != context["sources"]:
            raise ValueError("Prior report lineage differs")
        check_records(prior["result"]["files"])
        library = unreal.EditorAssetLibrary
        mask = library.load_asset(destination + "/T_Base_Stone_MainClothMask")
        material = library.load_asset(destination + "/M_Base_Stone_MainCloth")
        instances = {team: library.load_asset(destination + "/MI_Base_Stone_" + team) for team in shared.TEAM_COLORS}
    else:
        mask, material, instances = create_assets(unreal, context)
    verified = audit(unreal, context, mask, material, instances)
    records = []
    for asset in [mask, material] + list(instances.values()):
        path = package_file(unreal.Paths.project_content_dir(), asset.get_path_name(), destination)
        if not prior and not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save isolated team candidate")
        records.append({**file_record(path), "asset_path": asset.get_path_name(), "class_name": asset.get_class().get_name()})
    if prior and {record["asset_path"]: record["sha256"] for record in records} != {record["asset_path"]: record["sha256"] for record in prior["result"]["files"]}:
        raise ValueError("Derived four packages changed across actual fresh reopen")
    check_records(context["frozen_packages"] + context["source_evidence"])
    return {"mask": mask.get_path_name(), "material": material.get_path_name(), "instances": {team: obj.get_path_name() for team, obj in instances.items()},
            "files": records, "audit": verified, "frozen26_unchanged": True,
            "validated_in_fresh_process": prior is not None, "initial_process_id": prior["execution_process_id"] if prior else os.getpid(),
            "validation_process_id": os.getpid(), "all_cloth_coverage_approved": False, "production_approved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_REPORT"))
    parser.add_argument("--prior-report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_PRIOR_REPORT"))
    parser.add_argument("--reopen-only", action="store_true", default=os.environ.get("CIVWAR_BASE_TEAM_REOPEN_ONLY") == "1")
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.report or args.report.exists():
        raise ValueError("Explicit new report path required; no overwrite")
    report = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "execution_process_id": os.getpid(),
              "dry_run": args.dry_run, "runtime_approved": False, "production_approved": False}
    try:
        context = source_inputs()
        report.update(context)
        if args.dry_run:
            report["status"] = "inputs_validated_no_ue_execution"
        else:
            import unreal
            if args.reopen_only and not args.prior_report:
                raise ValueError("Fresh reopen requires prior report")
            report["result"] = execute(unreal, context, read(args.prior_report) if args.reopen_only else None)
            report["status"] = "base_team_material_fresh_reopen_passed_pending_actual_render" if args.reopen_only else "base_team_material_persisted_requires_fresh_reopen"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if "frozen_packages" in report:
            try:
                check_records(report["frozen_packages"] + report["source_evidence"])
                report["frozen26_and_source_unchanged_after_execution"] = True
            except Exception as error:
                report.update(status="failed", preservation_error=str(error))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
