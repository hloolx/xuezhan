from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


VERSION = "stoneaxe_exact_cloth_derivative_material_v2"
ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/stoneaxe_rig_pilot"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_stoneaxe_review import validate_inputs


TEAM_COLORS = {"Blue": [.10, .32, .95], "Red": [.92, .16, .10]}
LUMINANCE = [.2126, .7152, .0722]
NODE_CLASSES = {
    "base_color": "MaterialExpressionTextureSample", "normal": "MaterialExpressionTextureSample",
    "roughness": "MaterialExpressionTextureSample", "metallic": "MaterialExpressionTextureSample",
    "cloth_mask": "MaterialExpressionTextureSample", "luminance_weights": "MaterialExpressionConstant3Vector",
    "base_luminance": "MaterialExpressionDotProduct", "team_color": "MaterialExpressionVectorParameter",
    "team_luminance": "MaterialExpressionDotProduct", "safe_team_luminance": "MaterialExpressionMax",
    "normalized_team_color": "MaterialExpressionDivide", "recolored_cloth": "MaterialExpressionMultiply",
    "team_strength": "MaterialExpressionScalarParameter", "clamped_strength": "MaterialExpressionSaturate",
    "masked_strength": "MaterialExpressionMultiply", "cloth_blend": "MaterialExpressionLinearInterpolate",
}
LINKS = [
    ("base_color", "RGB", "base_luminance", "A"), ("luminance_weights", "", "base_luminance", "B"),
    ("team_color", "RGB", "team_luminance", "A"), ("luminance_weights", "", "team_luminance", "B"),
    ("team_luminance", "", "safe_team_luminance", "A"),
    ("team_color", "RGB", "normalized_team_color", "A"), ("safe_team_luminance", "", "normalized_team_color", "B"),
    ("normalized_team_color", "", "recolored_cloth", "A"), ("base_luminance", "", "recolored_cloth", "B"),
    ("team_strength", "", "clamped_strength", ""),
    ("cloth_mask", "R", "masked_strength", "A"), ("clamped_strength", "", "masked_strength", "B"),
    ("base_color", "RGB", "cloth_blend", "A"), ("recolored_cloth", "", "cloth_blend", "B"),
    ("masked_strength", "", "cloth_blend", "Alpha"),
]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def check_record(record, key="path"):
    path = Path(record[key])
    if not path.is_file() or sha(path) != record["sha256"]:
        raise ValueError("Required frozen source changed: " + str(path))


def shade_reference(base, team, mask, strength):
    original_luminance = sum(value * weight for value, weight in zip(base, LUMINANCE))
    team_luminance = max(.01, sum(value * weight for value, weight in zip(team, LUMINANCE)))
    alpha = mask * max(0.0, min(1.0, strength))
    return [original * (1 - alpha) + color * original_luminance / team_luminance * alpha
            for original, color in zip(base, team)]


def source_inputs(args):
    imported, fitted, calibration = validate_inputs(args)
    approval = read(args.approval)
    if not approval.get("semantic_selection_approved") or not approval.get("derived_material_pilot_authorized"):
        raise ValueError("Explicit approval of exact cloth selection is required")
    if approval.get("root_opened_actual_original_images") != 4 or len(approval.get("images", [])) != 4:
        raise ValueError("Four actual root-reviewed semantic diagnostic views are required")
    if approval.get("nonselected_triangle_uv_overlap_pixels") != 0:
        raise ValueError("Mask overlaps nonselected geometry UVs")
    for record in [approval[name] for name in ("source_blend", "base_color", "analysis", "mask")] + approval["images"]:
        check_record(record)
    manifest = read(imported["manifest"])
    if approval["base_color"]["sha256"] != manifest["textures"]["base_color"]["sha256"]:
        raise ValueError("Mask approval and frozen PBR base color differ")
    reviewed = read(args.assembly_review)
    if not all(reviewed.get(key) for key in ("visual_approved", "assembled_render_grip_approved", "socket_alignment_approved")):
        raise ValueError("Actual assembled UE body and socket visual approval is required")
    if sha(reviewed["source_report"]) != reviewed["source_report_sha256"]:
        raise ValueError("Actual assembly render report changed after visual review")
    render_report = read(reviewed["source_report"])
    if Path(render_report["import_report"]).resolve() != args.import_report or Path(render_report["socket_report"]).resolve() != args.socket_report:
        raise ValueError("Visual approval refers to different frozen body or socket evidence")
    frozen = [fitted["result"]["body_package_record"] if record["asset_path"] == imported["result"]["body"] else record
              for record in imported["result"]["disk_dependency_validation"]["files"]]
    settings = {"version": VERSION, "tool_sha256": sha(__file__), "mask_srgb": False,
                "mask_compression": "TC_GRAYSCALE", "mask_mips": "TMGS_NO_MIPMAPS",
                "mask_filter": "TF_NEAREST", "mask_address": "TA_CLAMP", "mask_never_stream": True,
                "luminance_weights": LUMINANCE, "team_colors_linear": TEAM_COLORS,
                "parameters": {"TeamColor": TEAM_COLORS["Blue"], "TeamColorStrength": 0.0},
                "formula": "lerp(original_rgb, TeamColor * dot(original_rgb,Luma) / max(dot(TeamColor,Luma),0.01), mask_r * saturate(TeamColorStrength))"}
    sources = {name: file_record(getattr(args, name)) for name in ("approval", "import_report", "socket_report", "assembly_review")}
    fingerprint = hashlib.sha256(json.dumps({"settings": settings, "sources": sources}, sort_keys=True).encode()).hexdigest()[:16]
    return imported, approval, frozen, settings, sources, "/Game/ArtPilot/StoneAxeTeam/h" + fingerprint


def package_file(unreal, path, destination):
    package = path.split(".")[0]
    if not package.startswith(destination + "/") or not destination.startswith("/Game/ArtPilot/StoneAxeTeam/h"):
        raise ValueError("Refuse writes outside the new team-color branch")
    return Path(unreal.Paths.project_content_dir()).resolve() / (package[len("/Game/"):] + ".uasset")


def properties(obj, values):
    for name, value in values.items():
        obj.set_editor_property(name, value)


def color(unreal, values):
    return unreal.LinearColor(r=values[0], g=values[1], b=values[2], a=1.0)


def values(linear_color):
    return [float(linear_color.r), float(linear_color.g), float(linear_color.b)]


def set_instance_parameters(unreal, instance, team_color):
    editing = unreal.MaterialEditingLibrary
    editing.set_material_instance_vector_parameter_value(instance, "TeamColor", color(unreal, team_color))
    editing.set_material_instance_scalar_parameter_value(instance, "TeamColorStrength", 1.0)
    editing.update_material_instance(instance)
    actual_color = values(editing.get_material_instance_vector_parameter_value(instance, "TeamColor"))
    actual_strength = float(editing.get_material_instance_scalar_parameter_value(instance, "TeamColorStrength"))
    if max(abs(actual - expected) for actual, expected in zip(actual_color, team_color)) > 1e-6 or actual_strength != 1.0:
        raise ValueError("Actual team instance parameter readback differs after public setter")


def mask_settings(unreal):
    return {"srgb": False, "compression_settings": unreal.TextureCompressionSettings.TC_GRAYSCALE,
            "compression_no_alpha": True, "mip_gen_settings": unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS,
            "filter": unreal.TextureFilter.TF_NEAREST, "address_x": unreal.TextureAddress.TA_CLAMP,
            "address_y": unreal.TextureAddress.TA_CLAMP, "never_stream": True,
            "virtual_texture_streaming": False}


def create_assets(unreal, imported, approval, destination):
    library = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    editing = unreal.MaterialEditingLibrary
    if library.does_directory_exist(destination) or (Path(unreal.Paths.project_content_dir()).resolve() / destination[len("/Game/"):]).exists():
        raise ValueError("Destination already exists; refuse overwrite or partial import reuse")
    task = unreal.AssetImportTask()
    properties(task, {"filename": approval["mask"]["path"], "destination_path": destination,
                      "destination_name": "T_StoneAxe_ClothMask", "automated": True, "replace_existing": False,
                      "save": False, "async_": False, "factory": unreal.TextureFactory()})
    tools.import_asset_tasks([task])
    mask = library.load_asset(destination + "/T_StoneAxe_ClothMask")
    if not isinstance(mask, unreal.Texture2D):
        raise TypeError("Exact cloth mask did not import as Texture2D")
    properties(mask, mask_settings(unreal))
    material = tools.create_asset("M_StoneAxe_TeamCloth", destination, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError("Cannot create isolated derived material")
    nodes = {}
    for index, (name, class_name) in enumerate(NODE_CLASSES.items()):
        node = editing.create_material_expression(material, getattr(unreal, class_name), -1400 + (index % 4) * 320, (index // 4) * 240)
        node.set_editor_property("desc", name)
        nodes[name] = node
    samplers = {"base_color": unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
                "normal": unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
                "roughness": unreal.MaterialSamplerType.SAMPLERTYPE_MASKS,
                "metallic": unreal.MaterialSamplerType.SAMPLERTYPE_MASKS}
    for channel, sampler in samplers.items():
        texture = library.load_asset(imported["result"]["materials"]["channels"][channel]["texture"])
        properties(nodes[channel], {"texture": texture, "sampler_type": sampler})
    properties(nodes["cloth_mask"], {"texture": mask, "sampler_type": unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE,
                                     "sampler_source": unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET})
    nodes["luminance_weights"].set_editor_property("constant", color(unreal, LUMINANCE))
    nodes["safe_team_luminance"].set_editor_property("const_b", .01)
    properties(nodes["team_color"], {"parameter_name": "TeamColor", "default_value": color(unreal, TEAM_COLORS["Blue"])})
    properties(nodes["team_strength"], {"parameter_name": "TeamColorStrength", "default_value": 0.0,
                                       "slider_min": 0.0, "slider_max": 1.0})
    for source, output, target, pin in LINKS:
        if not editing.connect_material_expressions(nodes[source], output, nodes[target], pin):
            raise RuntimeError("Failed material connection: " + source + "->" + target + "." + pin)
    for name, output, prop in (("cloth_blend", "", unreal.MaterialProperty.MP_BASE_COLOR),
                               ("normal", "RGB", unreal.MaterialProperty.MP_NORMAL),
                               ("roughness", "R", unreal.MaterialProperty.MP_ROUGHNESS),
                               ("metallic", "R", unreal.MaterialProperty.MP_METALLIC)):
        if not editing.connect_material_property(nodes[name], output, prop):
            raise RuntimeError("Failed material property connection: " + name)
    editing.set_base_material_usage(material, unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    errors = list(editing.recompile_material(material))
    if errors:
        raise RuntimeError("Derived material compile errors: " + str(errors))
    instances = {}
    for team, team_color in TEAM_COLORS.items():
        instance = tools.create_asset("MI_StoneAxe_" + team, destination, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        if instance is None:
            raise RuntimeError("Cannot create isolated team preview instance")
        editing.set_material_instance_parent(instance, material)
        set_instance_parameters(unreal, instance, team_color)
        instances[team] = instance
    return mask, material, instances


def audit_material(unreal, imported, mask, material, instances):
    editing = unreal.MaterialEditingLibrary
    for name, expected in mask_settings(unreal).items():
        if mask.get_editor_property(name) != expected:
            raise ValueError("Actual mask setting differs: " + name)
    dimensions = [mask.blueprint_get_size_x(), mask.blueprint_get_size_y()]
    if dimensions != [2048, 2048]:
        raise ValueError("Actual mask resolution differs from approved source")
    nodes = {str(node.get_editor_property("desc")): node for node in editing.get_material_expressions(material)}
    if set(nodes) != set(NODE_CLASSES):
        raise ValueError("Persisted material graph node set differs")
    for name, class_name in NODE_CLASSES.items():
        if not isinstance(nodes[name], getattr(unreal, class_name)):
            raise TypeError("Persisted graph node class differs: " + name)
    expected_inputs = {(target, pin): source for source, output, target, pin in LINKS}
    actual_links = []
    for name, node in nodes.items():
        pin_names = ["" if str(pin) in {"", "None"} else str(pin) for pin in editing.get_material_expression_input_names(node)]
        inputs = list(editing.get_inputs_for_material_expression(material, node))
        if len(pin_names) != len(inputs):
            raise ValueError("Public graph input names and connections have inconsistent counts: " + name)
        for pin, source in zip(pin_names, inputs):
            connected = str(source.get_editor_property("desc")) if source else None
            if connected != expected_inputs.get((name, pin)):
                raise ValueError("Actual graph input differs: " + name + "." + pin)
            if connected:
                actual_links.append({"source": connected, "target": name, "input": pin})
    if len(actual_links) != len(LINKS):
        raise ValueError("Incomplete material graph")
    for channel, prop in (("normal", unreal.MaterialProperty.MP_NORMAL), ("roughness", unreal.MaterialProperty.MP_ROUGHNESS),
                           ("metallic", unreal.MaterialProperty.MP_METALLIC)):
        if editing.get_material_property_input_node(material, prop) != nodes[channel]:
            raise ValueError("Noncolor PBR no longer directly uses original texture: " + channel)
    if editing.get_material_property_input_node(material, unreal.MaterialProperty.MP_BASE_COLOR) != nodes["cloth_blend"]:
        raise ValueError("Base color is not exact masked interpolation")
    textures = {}
    for channel in ("base_color", "normal", "roughness", "metallic"):
        texture = nodes[channel].get_editor_property("texture")
        textures[channel] = texture.get_path_name()
        if textures[channel] != imported["result"]["materials"]["channels"][channel]["texture"]:
            raise ValueError("Original PBR reference changed: " + channel)
    if nodes["cloth_mask"].get_editor_property("texture") != mask or nodes["cloth_mask"].get_editor_property("sampler_type") != unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE:
        raise ValueError("Mask sampler is not exact linear grayscale texture")
    if nodes["cloth_mask"].get_editor_property("sampler_source") != unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET:
        raise ValueError("Mask sampler ignores its no-bleed texture settings")
    if max(abs(actual - expected) for actual, expected in zip(values(nodes["luminance_weights"].get_editor_property("constant")), LUMINANCE)) > 1e-6:
        raise ValueError("Linear luminance weights changed")
    if abs(float(nodes["safe_team_luminance"].get_editor_property("const_b")) - .01) > 1e-6:
        raise ValueError("Team luminance floor changed")
    if not editing.has_material_usage(material, unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH):
        raise ValueError("Derived material lacks skeletal mesh usage")
    if float(editing.get_material_default_scalar_parameter_value(material, "TeamColorStrength")) != 0.0:
        raise ValueError("Parent must default to unchanged original color")
    if max(abs(actual - expected) for actual, expected in zip(values(editing.get_material_default_vector_parameter_value(material, "TeamColor")), TEAM_COLORS["Blue"])) > 1e-6:
        raise ValueError("Parent team color default differs")
    for team, instance in instances.items():
        if instance.get_editor_property("parent") != material:
            raise ValueError("Team instance references wrong parent")
        if float(editing.get_material_instance_scalar_parameter_value(instance, "TeamColorStrength")) != 1.0:
            raise ValueError("Team preview strength differs")
        if max(abs(actual - expected) for actual, expected in zip(values(editing.get_material_instance_vector_parameter_value(instance, "TeamColor")), TEAM_COLORS[team])) > 1e-6:
            raise ValueError("Team preview color differs")
    body = unreal.EditorAssetLibrary.load_asset(imported["result"]["body"])
    if any(slot.get_editor_property("material_interface").get_path_name() != imported["result"]["materials"]["material"] for slot in body.get_editor_property("materials")):
        raise ValueError("Frozen body material assignment changed")
    return {"status": "passed", "actual_graph_connections": actual_links, "original_pbr_references": textures,
            "mask_settings": {name: str(mask.get_editor_property(name)) for name in mask_settings(unreal)},
            "mask_dimensions": dimensions, "original_body_material_assignment_unchanged": True,
            "preview_instance_parameters_verified": True, "nominal_uncompressed_mask_bytes": 2048 * 2048,
            "limitations": ["NoMipmaps/nearest prevents mask mip or bilinear UV spill, but far-view aliasing and GPU cost require actual game review.",
                            "Graph and persistence checks do not prove rendered color correctness; runtime colors and filtering remain unapproved."]}


def execute(unreal, imported, approval, frozen, destination, prior):
    if prior:
        if prior["execution_process_id"] == os.getpid():
            raise ValueError("Reopen-only must run in a different UE process")
        for record in prior["result"]["disk_dependency_validation"]["files"]:
            check_record(record, "package_file")
        library = unreal.EditorAssetLibrary
        mask = library.load_asset(destination + "/T_StoneAxe_ClothMask")
        material = library.load_asset(destination + "/M_StoneAxe_TeamCloth")
        instances = {team: library.load_asset(destination + "/MI_StoneAxe_" + team) for team in TEAM_COLORS}
    else:
        mask, material, instances = create_assets(unreal, imported, approval, destination)
    graph = audit_material(unreal, imported, mask, material, instances)
    assets = [mask, material] + list(instances.values())
    if not prior:
        for asset in assets:
            package_file(unreal, asset.get_path_name(), destination)
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                raise RuntimeError("Cannot save derived asset: " + asset.get_path_name())
    files = []
    for asset in assets:
        path = package_file(unreal, asset.get_path_name(), destination)
        record = file_record(path)
        files.append({"asset_path": asset.get_path_name(), "package_file": record["path"], "bytes": record["bytes"],
                      "sha256": record["sha256"], "class_name": asset.get_class().get_name()})
    if prior:
        old = {record["asset_path"]: record["sha256"] for record in prior["result"]["disk_dependency_validation"]["files"]}
        if old != {record["asset_path"]: record["sha256"] for record in files}:
            raise ValueError("Derived packages changed between initial save and actual fresh reopen")
    for record in frozen:
        check_record(record, "package_file")
    return {"team_material": material.get_path_name(), "mask": mask.get_path_name(),
            "preview_instances": {team: instance.get_path_name() for team, instance in instances.items()},
            "material_audit": graph, "frozen_asset_bytes_unchanged": True, "frozen_packages_checked": len(frozen),
            "disk_dependency_validation": {"status": "passed", "validated_in_fresh_process": prior is not None,
                                           "initial_process_id": prior["execution_process_id"] if prior else os.getpid(),
                                           "validation_process_id": os.getpid(), "files": files},
            "runtime_interface": {"component_slot": 0, "new_mid_only": True, "color_parameter": "TeamColor",
                                  "strength_parameter": "TeamColorStrength", "strength": 1.0, "team_colors_linear": TEAM_COLORS},
            "final_team_colors_approved": False, "runtime_approved": False, "production_approved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval", default=os.environ.get("CIVWAR_STONEAXE_TEAM_APPROVAL", str(PILOT / "team_color_v01/semantic_approval.json")))
    parser.add_argument("--import-report", default=os.environ.get("CIVWAR_STONEAXE_TEAM_IMPORT_REPORT", str(PILOT / "delivery_v05c/unreal_fresh_reopen_v5.json")))
    parser.add_argument("--socket-report", default=os.environ.get("CIVWAR_STONEAXE_TEAM_SOCKET_REPORT", str(PILOT / "delivery_v05c/socket_apply_05.json")))
    parser.add_argument("--assembly-review", default=os.environ.get("CIVWAR_STONEAXE_TEAM_ASSEMBLY_REVIEW", str(PILOT / "delivery_v05c/ue_review_15_02/visual_review.json")))
    parser.add_argument("--report", default=os.environ.get("CIVWAR_STONEAXE_TEAM_REPORT"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reopen-only", action="store_true", default=os.environ.get("CIVWAR_STONEAXE_TEAM_REOPEN_ONLY") == "1")
    parser.add_argument("--prior-report", default=os.environ.get("CIVWAR_STONEAXE_TEAM_PRIOR_REPORT"))
    args, unknown = parser.parse_known_args()
    if not args.report:
        raise ValueError("Explicit new --report / CIVWAR_STONEAXE_TEAM_REPORT required")
    report_path = Path(args.report).resolve()
    if report_path.exists():
        raise FileExistsError("Refuse to overwrite existing execution evidence: " + str(report_path))
    for name in ("approval", "import_report", "socket_report", "assembly_review"):
        setattr(args, name, Path(getattr(args, name)).resolve())
    report = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "execution_process_id": os.getpid(),
              "dry_run": args.dry_run, "reopen_only": args.reopen_only, "runtime_approved": False, "production_approved": False}
    try:
        imported, approval, frozen, settings, sources, destination = source_inputs(args)
        report.update({"settings": settings, "sources": sources, "destination": destination, "frozen_packages": frozen})
        if args.dry_run:
            report["status"] = "validated_inputs_only_no_ue_executed"
        else:
            import unreal
            prior = None
            if args.reopen_only:
                if not args.prior_report:
                    raise ValueError("Actual fresh reopen requires prior initial save report")
                prior = read(args.prior_report)
                if prior.get("status") != "team_material_persisted_requires_fresh_reopen" or prior.get("destination") != destination or prior.get("settings") != settings or prior.get("dry_run"):
                    raise ValueError("Prior report does not match this exact successful initial save")
            report["result"] = execute(unreal, imported, approval, frozen, destination, prior)
            if prior:
                report["result"]["disk_dependency_validation"]["prior_import_report"] = file_record(args.prior_report)
            report["status"] = "team_material_fresh_reopen_passed_pending_actual_color_review" if prior else "team_material_persisted_requires_fresh_reopen"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("STONEAXE_TEAMCOLOR_REPORT " + str(report_path))


if __name__ == "__main__":
    main()
