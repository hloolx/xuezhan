"""Derive explicit-preview mappings from actual imports and a fresh UE readback.

This does not grant default-runtime, gameplay-visual or production approval.
Without --execute it validates the reports and prints the proposed mapping.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from stone_era_art import ASSETS, CLIPS, ROOT, package, read, validate_asset

ART = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed"
REQUIRED = {"Unit_StoneSlinger", "Mount_Mammoth", "Unit_BeastRider", "Champion_Stone"}
EXPECTED_LENGTHS = {
    "Unit_StoneSlinger": dict(Idle=2., Move=.6, Attack=1.4, Hit=.5, Death=1.2),
    "Champion_Stone": dict(Idle=2., Move=.6, Attack=.9, Hit=.5, Death=1.2),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path):
    return {"path": str(path.resolve()), "sha256": digest(path)}


def actual_path(root, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def validate_single_result(asset_id, imported, fresh):
    if imported["status"] != "imported_preview_requires_fresh_reopen":
        raise ValueError(asset_id + ": initial import did not pass")
    if fresh["status"] != "fresh_reopen_verified_preview":
        raise ValueError(asset_id + ": independent readback did not pass")
    if fresh["execution_process_id"] == imported["execution_process_id"]:
        raise ValueError(asset_id + ": readback reused the initial process")
    if fresh["destination"] != imported["destination"] or fresh["manifest"] != imported["manifest"]:
        raise ValueError(asset_id + ": readback lineage differs")
    result = fresh["result"]
    if result["structural_checks_passed"] is not True:
        raise ValueError(asset_id + ": actual structure failed")
    reference = result["reference_pose"]
    if not reference["bone_names_match_source"] or reference["maximum_reference_bone_basis_error_cm"] >= .1:
        raise ValueError(asset_id + ": actual skeleton differs")
    clips = {clip["clip"]: clip for clip in result["clips"]}
    if set(clips) != set(CLIPS):
        raise ValueError(asset_id + ": missing actual animation")
    for name, clip in clips.items():
        if (not clip["same_skeleton"] or clip["enable_root_motion"] or
                clip["absolute_motion_validation"]["status"] != "passed" or
                abs(clip["duration_seconds"] - EXPECTED_LENGTHS[asset_id][name]) > .001 or
                clip["root_translation_delta_cm"] >= .01):
            raise ValueError(asset_id + ": actual clip contract differs: " + name)
    disk = result["disk_dependency_validation"]
    if disk["status"] != "passed" or not disk["validated_in_fresh_process"]:
        raise ValueError(asset_id + ": disk dependencies were not independently reopened")
    return result, {name: clip["path"] for name, clip in clips.items()}


def prepare(root, plan_path, fresh_path, mapping_path, rider_contract_path):
    plan, fresh = read(plan_path), read(fresh_path)
    entries = {entry["asset"]: entry for entry in plan["entries"]}
    rows = {row["asset"]: row for row in fresh["results"]}
    if set(entries) != REQUIRED or set(rows) != REQUIRED or fresh.get("stage") != "fresh":
        raise ValueError("A complete four-part fresh UE batch is required")
    if any(row["status"] != "passed" for row in rows.values()):
        raise ValueError("Fresh UE batch contains failed or unfinished parts")
    initial, reports, snapshots = {}, {}, {}
    for key in sorted(REQUIRED):
        report_path = actual_path(root, entries[key]["report"])
        if actual_path(root, rows[key]["report"]) != report_path:
            raise ValueError("Fresh batch refers to another report: " + key)
        imported = read(report_path)
        imported_manifest = imported.get("manifest", imported.get("source_manifest", ""))
        if not imported_manifest or actual_path(root, imported_manifest) != actual_path(root, entries[key]["manifest"]):
            raise ValueError("Initial import used another source manifest: " + key)
        initial_pid = imported.get("execution_process_id", imported.get("process_id"))
        if not initial_pid or initial_pid == fresh["process_id"]:
            raise ValueError("Fresh process must differ from the actual import: " + key)
        if imported["status"] not in ("imported_preview_requires_fresh_reopen", "imported_preview_pending_gameplay"):
            raise ValueError("Initial import failed: " + key)
        snapshot_path = report_path.with_name("persisted_package_snapshot.json")
        snapshot = read(snapshot_path)
        if not snapshot or rows[key]["packages"] != len(snapshot):
            raise ValueError("Fresh package count differs: " + key)
        for item in snapshot:
            filename = package(root, item["asset"])
            if filename.resolve() != actual_path(root, item["file"]) or digest(filename) != item["sha256"]:
                raise ValueError("A verified package changed: " + item["asset"])
        initial[key], reports[key], snapshots[key] = imported, report_path, record(snapshot_path)
    mapping = copy.deepcopy(read(mapping_path))
    if set(mapping["assets"]) != set(ASSETS):
        raise ValueError("Existing stone-era mapping has unexpected assets")
    definitions = {row["VisualKey"]: row for name in ("Units", "Champions") for row in read(root / f"Content/Data/{name}.json")}
    for key in ("Unit_StoneSlinger", "Champion_Stone"):
        reopened_path = reports[key].with_name("unreal_fresh.json")
        reopened = read(reopened_path)
        if reopened["execution_process_id"] != fresh["process_id"]:
            raise ValueError(key + ": individual readback is not from this fresh batch")
        result, clips = validate_single_result(key, initial[key], reopened)
        entry = mapping["assets"][key]
        team = (result["materials"]["team_materials"] if key == "Unit_StoneSlinger" else
                [{"slot": slot, "path": result["team_materials"]["Blue"],
                  "red_path": result["team_materials"]["Red"]} for slot in result["body_material_slots"]])
        if not team:
            raise ValueError(key + ": no verified faction material")
        entry.update(
            parts=[{"id": "body", "skeletal_mesh": result["body"], "animations": clips,
                    "translation_cm": [0, 0, 0], "rotation_degrees": [0, 0, 0], "uniform_scale": 1,
                    "team_materials": team}],
            attachments=[],
            import_evidence={"initial": record(reports[key]), "fresh": record(reopened_path),
                             "persisted_packages": snapshots[key]},
        )
        if key == "Unit_StoneSlinger":
            bone = result["muzzle_bone"]
            if bone not in result["reference_pose"]["bones"]:
                raise ValueError("Actual slinger muzzle bone is absent")
            entry.update(muzzle_part="body", muzzle_socket=bone)
        else:
            weapon = result["weapon"]
            if not weapon["separate_from_body"] or not weapon["socket_fit"]["numeric_fit_passed"]:
                raise ValueError("Chief club actual socket fit failed")
            entry["attachments"] = [{"static_mesh": weapon["path"], "parent_part": "body",
                                     "socket": weapon["socket_fit"]["socket"],
                                     "translation_cm": [0, 0, 0], "rotation_degrees": [0, 0, 0], "uniform_scale": 1}]
    rider = read(rider_contract_path)
    if rider["visual_key"] != "Unit_BeastRider" or rider["status"] != "imported_preview_pending_gameplay":
        raise ValueError("Actual rider assembly contract is absent")
    expected_reports = {str(reports[key]): digest(reports[key]) for key in ("Mount_Mammoth", "Unit_BeastRider")}
    source_reports = {str(actual_path(root, item["path"])): item["sha256"] for item in rider["source_reports"]}
    if source_reports != expected_reports:
        raise ValueError("Rider assembly uses another pair of UE reports")
    mapping["assets"]["Unit_BeastRider"].update(
        parts=rider["parts"], attachments=rider["attachments"], height_cm=rider["height_cm"],
        height_evidence=rider["height_evidence"],
        import_evidence={"contract": record(rider_contract_path),
                         "mount": record(reports["Mount_Mammoth"]), "rider": record(reports["Unit_BeastRider"]),
                         "persisted_packages": {key: snapshots[key] for key in ("Mount_Mammoth", "Unit_BeastRider")}},
    )
    for key, entry in mapping["assets"].items():
        entry.update(enabled=True, preview_enabled=True, default_runtime_enabled=False,
                     ue_structural_approved=True, animation_contract_verified=True,
                     team_material_structural_verified=True, gameplay_visual_review_approved=False,
                     production_approved=False)
        validate_asset(root, key, entry, definitions[key])
    mapping["production_approved"] = False
    mapping["fresh_batch_evidence"] = record(fresh_path)
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fresh-report", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, default=ROOT / "Content/Data/StoneEraArt.json")
    parser.add_argument("--rider-contract", type=Path, default=ART / "beast_rider_v01/preview_delivery_02/runtime_contract.json")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = prepare(ROOT, args.plan.resolve(), args.fresh_report.resolve(), args.mapping.resolve(), args.rider_contract.resolve())
    if args.execute:
        args.mapping.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"executed": args.execute, "mapping": str(args.mapping), "assets": result["assets"],
                      "production_approved": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
