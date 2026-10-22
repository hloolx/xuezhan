from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_ue as base


ROOT, PILOT, TEAM = base.ROOT, base.PILOT, base.TEAM
read, sha, file_record = base.read, base.sha, base.file_record
shared, audit, check_records = base.shared, base.audit, base.check_records
MASK_SHA = "b5dc4ff963f70ffea7164ed0e04b5b65e46b2f87a1aeabc6be98152cc01b880d"
REPORT_SHA = "761ab00ad31c9eb771c4b5128109aff611cac7b3842abb5c089ff1c5dd0090ce"
BASE_TOOL_SHA = "857e690b6f1e2d195a2ff1845faf2d60382d2ee6a2cebe5c8f35f97fbd201cc4"
VERSION = "base_stone_main714_exact_nearest_footprint_team_candidate_v1"


def validate_footprint(report):
    expected = {"selected_triangle_count": 714, "mask_pixels": 74045, "added_pixels": 3719,
                "removed_pixels_for_stricter_protected_sampler_support": 542,
                "protected_sampler_overlap_pixels": 0, "one_pixel_filter_footprint_protected_overlap_pixels": 0,
                "pale_or_nonblue_pixels_recolored": 0, "outside_selected_sampler_support_pixels": 0,
                "all_cloth_coverage_approved": False, "mesh_edited": False}
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("Exact approved nearest-footprint contract changed")
    if report.get("selected_clusters") != [0, 1, 3, 4, 7] or report.get("held_clusters") != [2, 5, 6, 8]:
        raise ValueError("Footprint changes must not expand semantic faces")
    if report["mask"]["sha256"] != MASK_SHA or report["source"]["sha256"] != base.SOURCE_SHA:
        raise ValueError("Exact approved footprint source/mask changed")
    group = report["probe_groups"]["nearest_texel_center_outside_selected714_uv_coverage"]
    if group["points"] != 30 or group["new_mask_on"] != 30:
        raise ValueError("All30 diagnosed primary sampling gaps must be numerically resolved")
    for group_name in ("selected_coverage_but_original_pigment_classifier_excluded", "safe1_removed_original_selected_pigment"):
        if report["probe_groups"][group_name]["new_mask_on"] != 0:
            raise ValueError("White pigment and true protected adjacency must remain unchanged")
    return expected


def source_inputs():
    if sha(base.__file__) != BASE_TOOL_SHA:
        raise ValueError("Frozen validated native material implementation changed")
    context = base.source_inputs()
    report_path = TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json"
    approval_path = TEAM / "controlled_ue_footprint_approval_v01.json"
    prior_path = TEAM / "ue_fresh_02.json"
    if sha(report_path) != REPORT_SHA:
        raise ValueError("Frozen numerical footprint report changed")
    report, approval, prior = read(report_path), read(approval_path), read(prior_path)
    contract = validate_footprint(report)
    if not approval.get("controlled_ue_derivative_authorized") or approval.get("mask_sha256") != MASK_SHA or approval.get("actual_visual_approved") is not False:
        raise ValueError("Explicit root candidate-only authorization required")
    if prior.get("status") != "base_team_material_fresh_reopen_passed_pending_actual_render" or prior.get("destination") != context["destination"]:
        raise ValueError("Prior actual safe1 material lineage changed")
    if len(prior["result"]["files"]) != 4 or not prior["result"].get("validated_in_fresh_process"):
        raise ValueError("Four original safe1 derivative packages must be frozen")
    additional = [base.resolved_record(record) for record in prior["result"]["files"]]
    additional.extend(base.resolved_record(report[name]) for name in ("mask", "analysis", "actual_ray_probe_evidence", "tool"))
    check_records(additional)
    context["source_evidence"].extend(additional)
    context["sources"].update(footprint_report=file_record(report_path), footprint_approval=file_record(approval_path),
                              prior_safe1_fresh=file_record(prior_path), frozen_native_implementation=file_record(base.__file__))
    context["settings"].update(version=VERSION, tool_sha256=sha(__file__), semantic_mask=contract,
                               formula="Original native BaseColor masked lerp; exact nearest footprint replaces center-only mask; native noncolor unchanged",
                               prior_safe1_packages_preserved=4)
    context["mask_source"] = base.resolved_record(report["mask"])
    fingerprint = hashlib.sha256(json.dumps({"settings": context["settings"], "sources": context["sources"]}, sort_keys=True).encode()).hexdigest()[:16]
    context["destination"] = base.PREFIX + "h" + fingerprint
    context["additional_previous_derived_packages_frozen"] = 4
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
                raise ValueError("Independent fresh reopen requires matching prior report")
            report["result"] = base.execute(unreal, context, read(args.prior_report) if args.reopen_only else None)
            report["status"] = "base_team_material_fresh_reopen_passed_pending_actual_render" if args.reopen_only else "base_team_material_persisted_requires_fresh_reopen"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if "frozen_packages" in report:
            try:
                check_records(report["frozen_packages"] + report["source_evidence"])
                report["base5_stoneaxe21_previous_team4_and_sources_unchanged"] = True
            except Exception as error:
                report.update(status="failed", preservation_error=str(error))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
