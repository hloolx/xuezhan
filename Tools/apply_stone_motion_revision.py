"""Apply two verified motion imports while preserving existing activation flags.

Dry-run by default. This narrowly updates Slinger/Chief package references,
their import evidence, and exactly their two existing cook directories.
It does not assign new visual/default approvals or touch mounted-unit mappings.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from stone_era_art import ROOT, CLIPS, package, read, validate_asset

EXPECTED = {
    "Unit_StoneSlinger": (80, dict(Idle=2., Move=.6, Attack=1.4, Hit=.5, Death=1.2)),
    "Champion_Stone": (61, dict(Idle=2., Move=.6, Attack=.9, Hit=.5, Death=1.2)),
}
FLAGS = ("enabled", "preview_enabled", "default_runtime_enabled",
         "gameplay_visual_review_approved", "ue_structural_approved",
         "animation_contract_verified", "team_material_structural_verified",
         "production_approved")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path):
    return {"path": str(path.resolve()), "sha256": digest(path)}


def resolved(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT/path).resolve()


def verified_result(entry, batch_row, batch_pid):
    manifest_path, report_path = resolved(entry["manifest"]), resolved(entry["report"])
    if digest(manifest_path) != entry["manifest_sha256"]:
        raise ValueError("Frozen motion manifest changed: " + entry["asset"])
    if resolved(batch_row["report"]) != report_path or batch_row["status"] != "passed":
        raise ValueError("Initial batch did not validate this exact report")
    report = read(report_path)
    if (report["status"] != "imported_preview_requires_fresh_reopen"
            or report["execution_process_id"] != batch_pid
            or resolved(report["manifest"]) != manifest_path):
        raise ValueError("Unexpected actual import lineage")
    result = report["result"]
    bone_count, durations = EXPECTED[entry["asset"]]
    reference = result["reference_pose"]
    if (not result["structural_checks_passed"] or reference["bone_count"] != bone_count
            or not reference["bone_names_match_source"]
            or reference["maximum_reference_bone_basis_error_cm"] >= .1):
        raise ValueError("Actual skeleton validation failed")
    clips = {item["clip"]: item for item in result["clips"]}
    if set(clips) != set(CLIPS):
        raise ValueError("Missing animation clips")
    for name, item in clips.items():
        if (not item["same_skeleton"] or item["enable_root_motion"]
                or item["root_translation_delta_cm"] >= .01
                or abs(item["duration_seconds"] - durations[name]) > .001
                or item["absolute_motion_validation"]["status"] != "passed"):
            raise ValueError("Actual animation validation failed: " + name)
    disk = result["disk_dependency_validation"]
    if disk["status"] != "passed":
        raise ValueError("Saved dependency validation failed")
    snapshot_path = report_path.with_name("persisted_package_snapshot.json")
    snapshot = read(snapshot_path)
    if not snapshot or len(snapshot) != batch_row["packages"]:
        raise ValueError("Persisted package count differs")
    for saved in snapshot:
        path = package(ROOT, saved["asset"])
        if path.resolve() != resolved(saved["file"]) or digest(path) != saved["sha256"]:
            raise ValueError("Verified saved package changed: " + saved["asset"])
    return report, result, {name: item["path"] for name, item in clips.items()}, snapshot_path


def prepare(plan_path):
    plan = read(plan_path)
    entries = {item["asset"]: item for item in plan["entries"]}
    batch_path = plan_path.with_name("initial_batch_report.json")
    batch = read(batch_path)
    rows = {item["asset"]: item for item in batch["results"]}
    if set(entries) != set(EXPECTED) or set(rows) != set(EXPECTED) or batch["stage"] != "initial":
        raise ValueError("This tool requires exactly the two motion imports")
    mapping_path, cook_path = ROOT/"Content/Data/StoneEraArt.json", ROOT/"Config/DefaultGame.ini"
    original_mapping, original_cook = mapping_path.read_bytes(), cook_path.read_bytes()
    mapping = json.loads(original_mapping.decode("utf-8-sig"))
    previous = copy.deepcopy(mapping)
    cook = original_cook.decode("utf-8-sig")
    replacements = []
    definitions = {row["VisualKey"]: row for name in ("Units", "Champions")
                   for row in read(ROOT/f"Content/Data/{name}.json")}
    for asset_id, source in entries.items():
        imported, result, clips, snapshot = verified_result(source, rows[asset_id], batch["process_id"])
        asset = mapping["assets"][asset_id]
        if any(asset.get(key) is not True for key in ("enabled", "default_runtime_enabled", "gameplay_visual_review_approved")):
            raise ValueError("Do not infer or grant default/visual approval")
        if len(asset["parts"]) != 1 or asset["parts"][0]["id"] != "body":
            raise ValueError("Expected one existing body part")
        part = asset["parts"][0]
        old_directory = part["skeletal_mesh"].split(".")[0].rsplit("/", 1)[0]
        part.update(skeletal_mesh=result["body"], animations=clips)
        if asset_id == "Unit_StoneSlinger":
            part["team_materials"] = result["materials"]["team_materials"]
            if not part["team_materials"] or result["muzzle_bone"] not in result["reference_pose"]["bones"]:
                raise ValueError("Slinger faction material or release bone missing")
            asset.update(muzzle_part="body", muzzle_socket=result["muzzle_bone"])
        else:
            part["team_materials"] = [{"slot": slot, "path": result["team_materials"]["Blue"],
                                      "red_path": result["team_materials"]["Red"]}
                                     for slot in result["body_material_slots"]]
            weapon = result["weapon"]
            if (not weapon["separate_from_body"] or not weapon["socket_fit"]["numeric_fit_passed"]
                    or len(asset["attachments"]) != 1):
                raise ValueError("Chief club socket/attachment contract failed")
            asset["attachments"][0].update(static_mesh=weapon["path"], socket=weapon["socket_fit"]["socket"])
        asset["import_evidence"] = {
            "initial": record(resolved(source["report"])), "persisted_packages": record(snapshot),
            "validation_scope": "Saved packages and actual poses validated in the import process; no repeated fresh pass was run.",
        }
        asset["motion_revision_evidence"] = {
            "plan": record(plan_path), "manifest": record(resolved(source["manifest"])),
            "prior_import_evidence": previous["assets"][asset_id]["import_evidence"],
            "runtime_motion_review": "pending_root_gameplay_run",
        }
        new_directory = imported["destination"]
        old_line = f'+DirectoriesToAlwaysCook=(Path="{old_directory}")'
        new_line = f'+DirectoriesToAlwaysCook=(Path="{new_directory}")'
        if cook.count(old_line) != 1:
            raise ValueError("Expected exactly one current cook directory: " + old_directory)
        cook = cook.replace(old_line, new_line)
        replacements.append({"asset": asset_id, "old": old_directory, "new": new_directory})
        if any(asset.get(key) != previous["assets"][asset_id].get(key) for key in FLAGS):
            raise ValueError("An existing approval or activation flag changed")
        validate_asset(ROOT, asset_id, asset, definitions[asset_id])
    for asset_id in set(previous["assets"]) - set(EXPECTED):
        if previous["assets"][asset_id] != mapping["assets"][asset_id]:
            raise ValueError("Unrelated mapping was modified")
    mapping["motion_import_batch_evidence"] = record(batch_path)
    mapping_bytes = (json.dumps(mapping, ensure_ascii=False, indent=2)+"\n").encode("utf-8")
    cook_bytes = cook.encode("utf-8")
    if original_cook.startswith(b"\xef\xbb\xbf"):
        cook_bytes = b"\xef\xbb\xbf" + cook_bytes
    return mapping_path, cook_path, original_mapping, original_cook, mapping_bytes, cook_bytes, replacements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    mapping_path, cook_path, old_mapping, old_cook, mapping, cook, replacements = prepare(plan_path)
    output = plan_path.parent
    if args.execute:
        if (output/"mapping_apply_report.json").exists():
            raise ValueError("This motion mapping update was already recorded")
        # Detect concurrent writers immediately before the two small replacements.
        if mapping_path.read_bytes() != old_mapping or cook_path.read_bytes() != old_cook:
            raise ValueError("Configuration changed during preparation; rerun from current contents")
        (output/"StoneEraArt.before.json").write_bytes(old_mapping)
        (output/"DefaultGame.before.ini").write_bytes(old_cook)
        mapping_path.write_bytes(mapping)
        cook_path.write_bytes(cook)
    else:
        (output/"StoneEraArt.proposed.json").write_bytes(mapping)
        (output/"DefaultGame.proposed.ini").write_bytes(cook)
    result = {"executed": args.execute, "replacements": replacements, "existing_flags_preserved": True,
              "other_assets_preserved": True, "validation_scope": "initial_saved_package_and_pose_validation",
              "configuration_hashes": {"mapping": hashlib.sha256(mapping).hexdigest(),
                                       "cook": hashlib.sha256(cook).hexdigest()},
              "production_approved": False}
    (output/("mapping_apply_report.json" if args.execute else "mapping_proposal_report.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
