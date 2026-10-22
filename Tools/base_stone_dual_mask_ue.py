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
import base_stone_side_emblem_ue as previous


ROOT, PILOT, TEAM = previous.ROOT, previous.PILOT, previous.TEAM
FOLDER = previous.FOLDER / "dual_mask_v01"
base = previous.previous.base
shared, read, sha, file_record, check_records = previous.shared, previous.read, previous.sha, previous.file_record, previous.check_records
VERSION = "base_stone_strict_nearest_guard_local_bilinear_protection_v1"
REPORT_SHA = "55ba85074a3f45930f535c7d0f954aeb19e8c7c923d4f8f85173174406ab73b9"
PROTECTION_SHA = "6411979429239b3da5dc93f666874795ac47391a3c43c093bfef9a22f3d56030"
GUARD_SHA = "b5dc4ff963f70ffea7164ed0e04b5b65e46b2f87a1aeabc6be98152cc01b880d"
EXTRA_CLASSES = {"emblem_protection": "MaterialExpressionTextureSample", "emblem_complement": "MaterialExpressionSubtract", "protected_mask": "MaterialExpressionMultiply"}
ORIGINAL_LINK = ("cloth_mask", "R", "masked_strength", "A")
EXTRA_LINKS = [("cloth_mask", "R", "protected_mask", "A"), ("emblem_protection", "R", "emblem_complement", "B"),
               ("emblem_complement", "", "protected_mask", "B"), ("protected_mask", "", "masked_strength", "A")]


def source_inputs():
    context = previous.source_inputs()
    candidate_path = FOLDER / "candidate_report.json"
    if sha(candidate_path) != REPORT_SHA:
        raise ValueError("Frozen dual-mask numeric proof changed")
    candidate = read(candidate_path)
    required = {"local_protection_texels": 1217, "fully_protected_entire_texel_cells": 613, "partial_boundary_texel_cells": 604,
                "effective_possible_support_on_other_source_triangles": 0, "new_noncloth_or_held_dye_support": 0,
                "noncloth_direct_and1px_overlap": 0, "original_selected_faces": 714, "held_faces": 6,
                "previous30_uv_gap_points_still_on": True, "source_atlas_mesh_uv_unchanged": True, "global_blue_threshold_changed": False}
    if any(candidate.get(key) != value for key, value in required.items()):
        raise ValueError("Restricted dual-mask support proof differs")
    if candidate["protection_mask"]["sha256"] != PROTECTION_SHA or candidate["guard_mask"]["sha256"] != GUARD_SHA:
        raise ValueError("Exact guard/protection bytes differ")
    if len(candidate["front45_entire_cells_unchanged"]) != 45 or not all(item["protection_zero_across_entire_cell"] and item["final_guard_unchanged"] for item in candidate["front45_entire_cells_unchanged"]):
        raise ValueError("All45 front probes must be unchanged over entire cells")
    if not all(probe["dual_sample"]["final_tint_weight"] == 0 for probe in candidate["actual_game_uv_probes"]):
        raise ValueError("Both actual game emblem rays must remain fully protected")
    prior_path = previous.FOLDER / "ue_fresh_01.json"
    prior = read(prior_path)
    if prior.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or prior.get("destination") != context["destination"] or len(prior["result"]["files"]) != 4:
        raise ValueError("Previous binary branch must be immutable and independently reopened")
    additions = [base.resolved_record(item) for item in prior["result"]["files"]]
    additions.extend(base.resolved_record(candidate[key]) for key in ("guard_mask", "protection_mask", "tool"))
    additions.extend(base.resolved_record(item) for item in candidate["previews"].values())
    check_records(additions)
    context["source_evidence"].extend(additions)
    context["sources"].update(dual_mask_numeric_proof=file_record(candidate_path), previous_binary_fresh=file_record(prior_path),
                              frozen_previous_adapter=file_record(previous.__file__))
    context["settings"].update(version=VERSION, tool_sha256=sha(__file__), dual_mask_contract=required,
                               mask_policy="Unchanged exact-footprintNearest guard multiplied by1-minus independent localBilinear protection; both2048 NonColor NoMipmaps Clamp.",
                               formula=candidate["formula"], semantic_emblem_protection=None, new_package_count=5,
                               new_required_resident_textures=5, previous_derived_packages_preserved=12)
    context["mask_source"] = base.resolved_record(candidate["guard_mask"])
    context["protection_source"] = base.resolved_record(candidate["protection_mask"])
    packages = {item["path"] for item in context["frozen_packages"] + context["source_evidence"] if Path(item["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 38:
        raise ValueError("Expected original26 plus12 existing derived packages")
    context["existing_package_count"] = 38
    context["destination"] = base.PREFIX + "h" + hashlib.sha256(json.dumps({"settings": context["settings"], "sources": context["sources"]}, sort_keys=True).encode()).hexdigest()[:16]
    return context


def protection_settings(unreal):
    return {**shared.mask_settings(unreal), "filter": unreal.TextureFilter.TF_BILINEAR}


@contextmanager
def graph_contract():
    original_classes, original_links = base.WRAPPER_CLASSES, shared.LINKS
    if ORIGINAL_LINK not in original_links or any(name in original_classes for name in EXTRA_CLASSES):
        raise ValueError("Frozen baseline graph contract differs")
    base.WRAPPER_CLASSES = {**original_classes, **EXTRA_CLASSES}
    shared.LINKS = [link for link in original_links if link != ORIGINAL_LINK] + EXTRA_LINKS
    try:
        yield
    finally:
        base.WRAPPER_CLASSES, shared.LINKS = original_classes, original_links


def audit(unreal, context, mask, material, instances):
    protection = unreal.EditorAssetLibrary.load_asset(context["destination"] + "/T_Base_Stone_SideEmblemProtection")
    if not isinstance(protection, unreal.Texture2D):
        raise TypeError("Protection texture is missing")
    with graph_contract():
        result = base.audit(unreal, context, mask, material, instances)
    nodes = {str(node.get_editor_property("desc"))[len(base.NODE_PREFIX):]: node for node in unreal.MaterialEditingLibrary.get_material_expressions(material)
             if str(node.get_editor_property("desc")).startswith(base.NODE_PREFIX)}
    for key, expected in protection_settings(unreal).items():
        if protection.get_editor_property(key) != expected:
            raise ValueError("Independent bilinear protection property differs: " + key)
    if [protection.blueprint_get_size_x(), protection.blueprint_get_size_y()] != [2048, 2048]:
        raise ValueError("Protection must remain actual2048x2048")
    if nodes["emblem_protection"].get_editor_property("texture") != protection or nodes["emblem_protection"].get_editor_property("sampler_source") != unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET or nodes["emblem_protection"].get_editor_property("sampler_type") != unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE:
        raise ValueError("Protection node must honor the independent noncolor asset sampler")
    if float(nodes["emblem_complement"].get_editor_property("const_a")) != 1:
        raise ValueError("Protection complement must be exactly1-minus")
    result.update(dual_mask_guard_nearest_verified=True, local_protection_bilinear_verified=True,
                  exact_multiplicative_graph_verified=True, protection_settings={key: str(protection.get_editor_property(key)) for key in protection_settings(unreal)},
                  added_texture_count=1, required_resident_textures=5)
    return result


def create_assets(unreal, context):
    mask, material, instances = base.create_assets(unreal, context)
    library, editing = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
    path = context["destination"] + "/T_Base_Stone_SideEmblemProtection"
    if library.does_asset_exist(path):
        raise FileExistsError("Protection output already exists")
    task = unreal.AssetImportTask()
    shared.properties(task, {"filename": context["protection_source"]["path"], "destination_path": context["destination"],
                             "destination_name": "T_Base_Stone_SideEmblemProtection", "automated": True,
                             "replace_existing": False, "save": False, "async_": False, "factory": unreal.TextureFactory()})
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    protection = library.load_asset(path)
    if not isinstance(protection, unreal.Texture2D):
        raise TypeError("Protection import failed")
    shared.properties(protection, protection_settings(unreal))
    nodes = {str(node.get_editor_property("desc"))[len(base.NODE_PREFIX):]: node for node in editing.get_material_expressions(material)
             if str(node.get_editor_property("desc")).startswith(base.NODE_PREFIX)}
    for index, (name, class_name) in enumerate(EXTRA_CLASSES.items()):
        node = editing.create_material_expression(material, getattr(unreal, class_name), 1500, 1200 + index * 220)
        node.set_editor_property("desc", base.NODE_PREFIX + name)
        nodes[name] = node
    shared.properties(nodes["emblem_protection"], {"texture": protection, "sampler_type": unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE,
                                                  "sampler_source": unreal.SamplerSourceMode.SSM_FROM_TEXTURE_ASSET})
    nodes["emblem_complement"].set_editor_property("const_a", 1.0)
    for source, output, target, pin in EXTRA_LINKS:
        if not editing.connect_material_expressions(nodes[source], output, nodes[target], pin):
            raise ValueError("Dual-mask connection failed: " + target + "." + pin)
    errors = list(editing.recompile_material(material))
    if errors:
        raise ValueError("Dual-mask compile failed: " + str(errors))
    return mask, protection, material, instances


def execute(unreal, context, prior=None):
    destination = context["destination"]
    if prior:
        if prior.get("status") != "base_team_material_persisted_requires_fresh_reopen" or prior.get("execution_process_id") == os.getpid():
            raise ValueError("Independent successful initial report required")
        for key in ("destination", "settings", "sources", "frozen_packages", "source_evidence"):
            if prior.get(key) != context[key]:
                raise ValueError("Fresh dual-mask context changed: " + key)
        if len(prior["result"]["files"]) != 5:
            raise ValueError("Five persisted packages required")
        check_records(prior["result"]["files"])
        library = unreal.EditorAssetLibrary
        mask = library.load_asset(destination + "/T_Base_Stone_MainClothMask")
        protection = library.load_asset(destination + "/T_Base_Stone_SideEmblemProtection")
        material = library.load_asset(destination + "/M_Base_Stone_MainCloth")
        instances = {name: library.load_asset(destination + "/MI_Base_Stone_" + name) for name in shared.TEAM_COLORS}
    else:
        mask, protection, material, instances = create_assets(unreal, context)
    verified = audit(unreal, context, mask, material, instances)
    records = []
    for asset in [mask, protection, material] + list(instances.values()):
        path = base.package_file(unreal.Paths.project_content_dir(), asset.get_path_name(), destination)
        if not prior and not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not persist new dual-mask package")
        records.append({**file_record(path), "asset_path": asset.get_path_name(), "class_name": asset.get_class().get_name()})
    if prior and {item["asset_path"]: item["sha256"] for item in records} != {item["asset_path"]: item["sha256"] for item in prior["result"]["files"]}:
        raise ValueError("Five packages changed across independent fresh reopen")
    check_records(context["frozen_packages"] + context["source_evidence"])
    return {"mask": mask.get_path_name(), "protection": protection.get_path_name(), "material": material.get_path_name(),
            "instances": {name: asset.get_path_name() for name, asset in instances.items()}, "files": records, "audit": verified,
            "frozen26_unchanged": True, "all38_existing_packages_unchanged": True, "validated_in_fresh_process": prior is not None,
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
            if os.environ.get("CIVWAR_BASE_DUAL_EXECUTE_TOKEN") != context["destination"].split("/")[-1]:
                raise ValueError("Root must explicitly confirm this exact branch after candidate preview review")
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
                report["all38_existing_packages_and_sources_unchanged"] = True
            except Exception as error:
                report.update(status="failed", preservation_error=str(error))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
