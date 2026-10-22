from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_ue as previous


ROOT, PILOT, TEAM = previous.ROOT, previous.PILOT, previous.TEAM
FOLDER = previous.FOLDER / "unmix_research_v01/candidate_02/ue_rgb_contribution_v01"
base, shared = previous.base, previous.shared
read, sha, file_record, check_records = previous.read, previous.sha, previous.file_record, previous.check_records
VERSION = "base_stone_candidate02_source_ink_linear_rgb_v1"
ENCODING_SHA = "a655b39bbae0dc579cb3a698d229f56f43e0873e31cf7570f04a7e80ce57b715"
TEXTURE_SHA = "0efc1c1b9141a9b2e8dbbae9fe54d198e7a1bc7dcfce0599fc7301fd4ff20c73"
TEXTURE_NAME = "T_Base_Stone_SideInkContribution"
DECODE_SCALE = .5
EXTRA_CLASSES = {"ink_texture": "MaterialExpressionTextureSample", "ink_decode": "MaterialExpressionMultiply",
                 "ink_bounded": "MaterialExpressionMin", "substrate": "MaterialExpressionSubtract", "ink_composite": "MaterialExpressionAdd"}
REPLACED_LINKS = [("base_color", "RGB", "base_luminance", "A"), ("recolored_cloth", "", "cloth_blend", "B")]
EXTRA_LINKS = [("ink_texture", "RGB", "ink_decode", "A"), ("ink_decode", "", "ink_bounded", "A"),
               ("base_color", "RGB", "ink_bounded", "B"), ("base_color", "RGB", "substrate", "A"),
               ("ink_bounded", "", "substrate", "B"), ("substrate", "", "base_luminance", "A"),
               ("ink_bounded", "", "ink_composite", "A"), ("recolored_cloth", "", "ink_composite", "B"),
               ("ink_composite", "", "cloth_blend", "B")]


def source_inputs():
    context = previous.source_inputs()
    old_destination = context["destination"]
    prior_path = previous.FOLDER / "ue_fresh_01.json"
    prior = read(prior_path)
    if prior.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or prior["destination"] != old_destination or len(prior["result"]["files"]) != 5:
        raise ValueError("Historical dual-mask five packages must be independently reopened and preserved")
    encoding_path, approval_path = FOLDER / "encoding_report.json", FOLDER / "root_trial_preparation_approval.json"
    if sha(encoding_path) != ENCODING_SHA:
        raise ValueError("Frozen final-candidate encoding proof changed")
    encoding, approval = read(encoding_path), read(approval_path)
    if not approval.get("one_ue_control_trial_preparation_authorized") or not approval.get("root_candidate02_preview_reviewed") or approval.get("candidate03_authorized"):
        raise ValueError("Explicit final-candidate single-trial authorization required")
    if approval["candidate_report_sha256"] != encoding["candidate_report"]["sha256"]:
        raise ValueError("Root preview authorization refers to another candidate")
    if encoding["contribution_texture"]["sha256"] != TEXTURE_SHA or encoding["encoding"]["linear_decode_scale"] != DECODE_SCALE:
        raise ValueError("Exact RGB contribution encoding differs")
    required = {"semantic_support_texels_after": 1240, "nonzero_encoded_texels": 1239, "source714_and_held6_unchanged": True,
                "noncloth_direct_and1px_overlap": 0, "new_other_triangle_support": 0, "front45_and_prior30gaps_unchanged": True}
    if any(encoding.get(key) != value for key, value in required.items()):
        raise ValueError("Final1240 limited semantic/footprint proof differs")
    additions = [base.resolved_record(item) for item in prior["result"]["files"]]
    additions.extend(base.resolved_record(encoding[key]) for key in ("candidate_report", "decomposition_fields", "encoder", "contribution_texture"))
    additions.extend(base.resolved_record(item) for item in encoding["preview_images"].values())
    check_records(additions)
    context["source_evidence"].extend(additions)
    context["sources"].update(previous_dual_fresh=file_record(prior_path), encoding_proof=file_record(encoding_path),
                              root_trial_approval=file_record(approval_path), frozen_dual_adapter=file_record(previous.__file__))
    context["settings"] = {"version": VERSION, "tool_sha256": sha(__file__), "formula": encoding["formula"],
                           "mask_policy": "Unchanged strict714 footprint NonColorNearest guard; independent side ink RGB NonColorBilinear only changes tint result inside guard.",
                           "semantic_contract": required, "decode_scale": DECODE_SCALE, "ink_texture_policy": "RGBA8 uncompressed; linearRGB; NoMipmaps; Bilinear; Clamp; UV0; asset sampler",
                           "team_colors_linear": shared.TEAM_COLORS, "luminance_weights": shared.LUMINANCE, "parent_default_strength": 0.0,
                           "root_gate_revision": encoding["root_gate_revision"], "new_package_count": 5, "new_required_resident_textures": 5,
                           "existing_package_count": 43, "all_cloth_coverage_approved": False,
                           "quantized_to_zero": encoding["quantized_to_zero"], "encoding_errors": encoding["final_color_encoding_error_x6"],
                           "native_source_clamp_approximation": encoding["native_source_clamp_approximation_x6"]}
    context.pop("protection_source", None)
    context["contribution_source"] = base.resolved_record(encoding["contribution_texture"])
    packages = {item["path"] for item in context["frozen_packages"] + context["source_evidence"] if Path(item["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 43:
        raise ValueError("Expected original26 plus17 existing derived packages")
    context["existing_package_count"] = 43
    context["destination"] = base.PREFIX + "h" + hashlib.sha256(json.dumps({"settings": context["settings"], "sources": context["sources"]}, sort_keys=True).encode()).hexdigest()[:16]
    return context


def contribution_settings(unreal):
    return {**shared.mask_settings(unreal), "compression_settings": unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP,
            "compression_no_alpha": False, "filter": unreal.TextureFilter.TF_BILINEAR}


@contextmanager
def graph_contract():
    original_classes, original_links = base.WRAPPER_CLASSES, shared.LINKS
    if any(link not in original_links for link in REPLACED_LINKS) or any(name in original_classes for name in EXTRA_CLASSES):
        raise ValueError("Frozen baseline graph contract differs")
    base.WRAPPER_CLASSES = {**original_classes, **EXTRA_CLASSES}
    shared.LINKS = [link for link in original_links if link not in REPLACED_LINKS] + EXTRA_LINKS
    try:
        yield
    finally:
        base.WRAPPER_CLASSES, shared.LINKS = original_classes, original_links


def audit(unreal, context, mask, material, instances):
    contribution = unreal.EditorAssetLibrary.load_asset(context["destination"] + "/" + TEXTURE_NAME)
    if not isinstance(contribution, unreal.Texture2D):
        raise TypeError("Source ink contribution texture is missing")
    with graph_contract():
        result = base.audit(unreal, context, mask, material, instances)
    nodes = {str(node.get_editor_property("desc"))[len(base.NODE_PREFIX):]: node for node in unreal.MaterialEditingLibrary.get_material_expressions(material)
             if str(node.get_editor_property("desc")).startswith(base.NODE_PREFIX)}
    for key, expected in contribution_settings(unreal).items():
        if contribution.get_editor_property(key) != expected:
            raise ValueError("Linear contribution texture property differs: " + key)
    if [contribution.blueprint_get_size_x(), contribution.blueprint_get_size_y()] != [2048, 2048]:
        raise ValueError("Contribution must remain actual2048x2048")
    texture = nodes["ink_texture"]
    if texture.get_editor_property("texture") != contribution or texture.get_editor_property("sampler_source") != unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET or texture.get_editor_property("sampler_type") != unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR or texture.get_editor_property("const_coordinate") != 0:
        raise ValueError("Contribution requires linearRGB UV0 and asset bilinear sampler")
    if float(nodes["ink_decode"].get_editor_property("const_b")) != DECODE_SCALE:
        raise ValueError("Linear RGB decode scale must remain exactly0.5")
    result.update(strict_nearest_guard_verified=True, linear_rgb_ink_bilinear_verified=True,
                  exact_source_contribution_graph_verified=True, native_basecolor_channelwise_ink_bound_verified=True,
                  contribution_settings={key: str(contribution.get_editor_property(key)) for key in contribution_settings(unreal)},
                  formula=context["settings"]["formula"], added_texture_count=1, required_resident_textures=5)
    return result


def create_assets(unreal, context):
    mask, material, instances = base.create_assets(unreal, context)
    library, editing = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
    path = context["destination"] + "/" + TEXTURE_NAME
    if library.does_asset_exist(path):
        raise FileExistsError("Contribution output already exists")
    task = unreal.AssetImportTask()
    shared.properties(task, {"filename": context["contribution_source"]["path"], "destination_path": context["destination"],
                             "destination_name": TEXTURE_NAME, "automated": True, "replace_existing": False, "save": False,
                             "async_": False, "factory": unreal.TextureFactory()})
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    contribution = library.load_asset(path)
    if not isinstance(contribution, unreal.Texture2D):
        raise TypeError("Contribution import failed")
    shared.properties(contribution, contribution_settings(unreal))
    nodes = {str(node.get_editor_property("desc"))[len(base.NODE_PREFIX):]: node for node in editing.get_material_expressions(material)
             if str(node.get_editor_property("desc")).startswith(base.NODE_PREFIX)}
    original = library.load_asset(context["original_material"])
    native_name = base.native_roots(unreal, original)["base_color"]["node"]
    nodes["base_color"] = next(node for node in editing.get_material_expressions(material) if node.get_name() == native_name)
    for index, (name, class_name) in enumerate(EXTRA_CLASSES.items()):
        node = editing.create_material_expression(material, getattr(unreal, class_name), 1500, 1200 + index * 220)
        node.set_editor_property("desc", base.NODE_PREFIX + name)
        nodes[name] = node
    shared.properties(nodes["ink_texture"], {"texture": contribution, "sampler_type": unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR,
                                            "sampler_source": unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET, "const_coordinate": 0})
    nodes["ink_decode"].set_editor_property("const_b", DECODE_SCALE)
    for source, output, target, pin in EXTRA_LINKS:
        if not editing.connect_material_expressions(nodes[source], "BaseColor" if source == "base_color" else output, nodes[target], pin):
            raise ValueError("Source contribution connection failed: " + target + "." + pin)
    errors = list(editing.recompile_material(material))
    if errors:
        raise ValueError("Contribution shader compile failed: " + str(errors))
    return mask, contribution, material, instances


def execute(unreal, context, prior=None):
    destination = context["destination"]
    if prior:
        if prior.get("status") != "base_team_material_persisted_requires_fresh_reopen" or prior.get("execution_process_id") == os.getpid():
            raise ValueError("Independent successful initial process required")
        for key in ("destination", "settings", "sources", "frozen_packages", "source_evidence", "contribution_source"):
            if prior.get(key) != context[key]:
                raise ValueError("Fresh contribution context changed: " + key)
        if len(prior["result"]["files"]) != 5:
            raise ValueError("Five persisted packages required")
        check_records(prior["result"]["files"])
        library = unreal.EditorAssetLibrary
        mask = library.load_asset(destination + "/T_Base_Stone_MainClothMask")
        contribution = library.load_asset(destination + "/" + TEXTURE_NAME)
        material = library.load_asset(destination + "/M_Base_Stone_MainCloth")
        instances = {name: library.load_asset(destination + "/MI_Base_Stone_" + name) for name in shared.TEAM_COLORS}
    else:
        mask, contribution, material, instances = create_assets(unreal, context)
    verified = audit(unreal, context, mask, material, instances)
    records = []
    for asset in [mask, contribution, material] + list(instances.values()):
        path = base.package_file(unreal.Paths.project_content_dir(), asset.get_path_name(), destination)
        if not prior and not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not persist isolated contribution package")
        records.append({**file_record(path), "asset_path": asset.get_path_name(), "class_name": asset.get_class().get_name()})
    if prior and {item["asset_path"]: item["sha256"] for item in records} != {item["asset_path"]: item["sha256"] for item in prior["result"]["files"]}:
        raise ValueError("Five packages changed across independent fresh reopen")
    check_records(context["frozen_packages"] + context["source_evidence"])
    return {"mask": mask.get_path_name(), "contribution": contribution.get_path_name(), "material": material.get_path_name(),
            "instances": {name: asset.get_path_name() for name, asset in instances.items()}, "files": records, "audit": verified,
            "frozen26_unchanged": True, "all43_existing_packages_unchanged": True, "validated_in_fresh_process": prior is not None,
            "initial_process_id": prior["execution_process_id"] if prior else os.getpid(), "validation_process_id": os.getpid(),
            "all_cloth_coverage_approved": False, "production_approved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_REPORT"))
    parser.add_argument("--prior-report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_PRIOR_REPORT"))
    parser.add_argument("--reopen-only", action="store_true", default=os.environ.get("CIVWAR_BASE_TEAM_REOPEN_ONLY") == "1")
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.report or args.report.exists():
        raise ValueError("Explicit new report required")
    report = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "execution_process_id": os.getpid(),
              "dry_run": args.dry_run, "runtime_approved": False, "production_approved": False}
    try:
        context = source_inputs()
        report.update(context)
        if args.dry_run:
            report["status"] = "inputs_validated_no_ue_execution"
        else:
            if os.environ.get("CIVWAR_BASE_INK_EXECUTE_TOKEN") != context["destination"].split("/")[-1]:
                raise ValueError("Root must explicitly authorize this exact isolated branch")
            import unreal
            if args.reopen_only and not args.prior_report:
                raise ValueError("Fresh phase requires initial report")
            report["result"] = execute(unreal, context, read(args.prior_report) if args.reopen_only else None)
            report["status"] = "base_team_material_fresh_reopen_passed_pending_actual_render" if args.reopen_only else "base_team_material_persisted_requires_fresh_reopen"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if "frozen_packages" in report:
            try:
                check_records(report["frozen_packages"] + report["source_evidence"])
                report["all43_existing_packages_and_sources_unchanged"] = True
            except Exception as error:
                report.update(status="failed", preservation_error=str(error))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
