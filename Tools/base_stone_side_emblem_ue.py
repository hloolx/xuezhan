from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_footprint_ue as previous


ROOT, PILOT, TEAM = previous.ROOT, previous.PILOT, previous.TEAM
read, sha, file_record = previous.read, previous.sha, previous.file_record
shared, audit, check_records = previous.shared, previous.audit, previous.check_records
FOLDER = TEAM / "side_emblem_protection_v04"
MASK_SHA = "d9758180f8712c5de9f803a8509781901c601dc4df529a80bd402472dc0bce97"
REPORT_SHA = "89a83e0958350fc5c28529b07fddc154cbe249230cd37aaa27f2a26159e5bc4f"
PREVIOUS_TOOL_SHA = "7906ddd346543e384c4e73fcf4112599f2ec4c21afa3233c9294de8c9aebd723"
VERSION = "base_stone_cluster0_emblem_protection_team_candidate_v1"


def validate_candidate(report):
    expected = {"original_selected_faces": 714, "held_faces": 6, "old_mask_pixels": 74045,
                "new_mask_pixels": 72828, "removed_pixels": 1217, "added_pixels": 0,
                "changes_outside_target_cluster": 0, "changes_on_other_source_support": 0,
                "previous30_uv_sampling_gap_points_still_on": True, "noncloth_direct_and1px_overlap_remain_zero": True,
                "source_atlas_mesh_uv_unchanged": True, "global_pigment_predicate_modified": False,
                "material_or_content_modified": False, "actual_ue_visual_approved": False,
                "all_emblems_preserved": False, "all_cloth_coverage_approved": False, "production_approved": False}
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("Frozen side-emblem candidate contract changed")
    if report["semantic_selection"].get("source_cluster") != 0 or report["semantic_selection"].get("cluster_faces") != 195:
        raise ValueError("Only actual game-visible cluster0 stroke protection is authorized")
    if report["new_mask"]["sha256"] != MASK_SHA or report["source_glb"]["sha256"] != previous.base.SOURCE_SHA:
        raise ValueError("Frozen source or mask changed")
    probes = report.get("front45_probes_unchanged", [])
    if len(probes) != 45 or not all(item.get("unchanged") is True for item in probes):
        raise ValueError("Original45 front-flag probes must stay unchanged")
    if len(report.get("affected_source_faces", [])) != 19:
        raise ValueError("Exact19 source faces are expected")
    return expected


def source_inputs():
    if sha(previous.__file__) != PREVIOUS_TOOL_SHA:
        raise ValueError("Frozen footprint adapter changed")
    context = previous.source_inputs()
    candidate_path = FOLDER / "candidate_v02/candidate_report.json"
    approval_path = FOLDER / "controlled_ue_approval_v01.json"
    review_path = FOLDER / "candidate_v02/agent_review.json"
    prior_path = TEAM / "ue_fresh_03.json"
    if sha(candidate_path) != REPORT_SHA:
        raise ValueError("Frozen candidate report changed")
    candidate, approval, review, prior = map(read, (candidate_path, approval_path, review_path, prior_path))
    contract = validate_candidate(candidate)
    if not approval.get("root_semantic_selection_approved") or not approval.get("controlled_ue_derivative_authorized"):
        raise ValueError("Root source-atlas semantic approval is required")
    if approval.get("mask_sha256") != MASK_SHA or approval.get("numeric_report_sha256") != REPORT_SHA or approval.get("actual_ue_visual_approved") is not False:
        raise ValueError("Approval must bind exact candidate without claiming final visual acceptance")
    if not review.get("root_semantic_selection_approved") or not review.get("controlled_ue_derivative_authorized"):
        raise ValueError("Reviewed3preview evidence must be recorded")
    if prior.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or prior.get("destination") != context["destination"]:
        raise ValueError("Prior actual footprint lineage changed")
    if len(prior["result"]["files"]) != 4 or not prior["result"].get("validated_in_fresh_process"):
        raise ValueError("Four prior footprint packages must be frozen")
    additional = [previous.base.resolved_record(record) for record in prior["result"]["files"]]
    additional.extend(previous.base.resolved_record(candidate[name]) for name in ("new_mask", "selection", "removed_pixels_image", "tool"))
    additional.extend(previous.base.resolved_record(record) for record in candidate["previews"].values())
    check_records(additional)
    context["source_evidence"].extend(additional)
    packages = {record["path"] for record in context["frozen_packages"] + context["source_evidence"] if Path(record["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 34:
        raise ValueError("All34 existing packages must be frozen before this branch")
    context["sources"].update(emblem_candidate=file_record(candidate_path), emblem_root_approval=file_record(approval_path),
                              emblem_review=file_record(review_path), prior_footprint_fresh=file_record(prior_path),
                              frozen_footprint_implementation=file_record(previous.__file__))
    context["settings"].update(version=VERSION, tool_sha256=sha(__file__), semantic_emblem_protection=contract,
                               formula="Unchanged nativePBR masked lerp; only1217 verified cluster0 source-emblem pixels removed from prior exact-footprint mask",
                               prior_safe1_and_footprint_packages_preserved=8)
    context["mask_source"] = previous.base.resolved_record(candidate["new_mask"])
    fingerprint = hashlib.sha256(json.dumps({"settings": context["settings"], "sources": context["sources"]}, sort_keys=True).encode()).hexdigest()[:16]
    context["destination"] = previous.base.PREFIX + "h" + fingerprint
    context["additional_previous_derived_packages_frozen"] = 8
    context["existing_package_count"] = 34
    return context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_REPORT"))
    parser.add_argument("--prior-report", type=Path, default=os.environ.get("CIVWAR_BASE_TEAM_PRIOR_REPORT"))
    parser.add_argument("--reopen-only", action="store_true", default=os.environ.get("CIVWAR_BASE_TEAM_REOPEN_ONLY") == "1")
    parser.add_argument("--dry-run", action="store_true")
    args, unknown = parser.parse_known_args()
    if not args.report or args.report.exists():
        raise ValueError("Explicit new report path required")
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
                raise ValueError("Independent fresh reopen requires matching initial report")
            report["result"] = previous.base.execute(unreal, context, read(args.prior_report) if args.reopen_only else None)
            report["status"] = "base_team_material_fresh_reopen_passed_pending_actual_render" if args.reopen_only else "base_team_material_persisted_requires_fresh_reopen"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if "frozen_packages" in report:
            try:
                check_records(report["frozen_packages"] + report["source_evidence"])
                report["all34_existing_packages_and_sources_unchanged"] = True
            except Exception as error:
                report.update(status="failed", preservation_error=str(error))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
