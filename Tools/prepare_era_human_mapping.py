"""Write a reviewable mapping handoff from actual successful imported assets."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare(manifest_path, report_path, output):
    manifest, report = read(manifest_path), read(report_path)
    if report["status"] != "imported_preview_pending_gameplay" or report["failures"]:
        raise ValueError("Actual successful UE import required")
    if record(manifest_path)["sha256"] != report["source_manifest_sha256"]:
        raise ValueError("Actual report source changed")
    for row in report["packages"]:
        if record(row["file"])["sha256"] != row["sha256"]:
            raise ValueError("Persisted package changed: "+row["file"])
    if set(report["clips"]) != {"Idle", "Move", "Attack", "Hit", "Death"}:
        raise ValueError("Missing actual animation")
    entry = {"kind": "skeletal_unit", "asset_id": manifest["asset_id"],
        "enabled": True, "default_runtime_enabled": True, "preview_enabled": True,
        "production_approved": False, "height_cm": manifest["normalization"]["reference_height_cm"],
        "reference_move_speed": manifest["reference_move_speed_cm_s"],
        "contact_time": manifest["attack_contact_seconds"],
        "attack_style": "Thrust" if manifest["profile"] == "mounted_lance" else
                        "Shoot" if manifest["profile"] in {"crossbow", "rifle", "laser_rifle"} else
                        "Burst" if manifest["profile"] == "launcher" else "Chop",
        "parts": [{"id": "body", "skeletal_mesh": report["mesh"],
                   "animations": {key: value["asset"] for key, value in report["clips"].items()},
                   "translation_cm": [0, 0, 0], "rotation_degrees": [0, 0, 0], "uniform_scale": 1.,
                   "team_materials": report["materials"]["team_materials"]}],
        "attachments": [row["runtime"] for row in report["attachments"]],
        "import_evidence": {"manifest": record(manifest_path), "initial_report": record(report_path)},
        "runtime_visual_review": "pending_root_gameplay"}
    if manifest.get("muzzle_bone"):
        entry.update(muzzle_part="body", muzzle_socket=manifest["muzzle_bone"])
    if manifest.get("rig_provenance"):
        entry["rig_provenance"] = manifest["rig_provenance"]
    handoff = {"asset_id": manifest["asset_id"], "entry": entry, "cook_directory": report["destination"],
               "actual_package_count": len(report["packages"]), "runtime_config_written": False,
               "scope": "Proposed default entry from actual saved asset evidence; root owns shared mapping and gameplay review"}
    Path(output).write_text(json.dumps(handoff, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"asset": manifest["asset_id"], "handoff": str(output), "packages": len(report["packages"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.manifest, args.report, args.output)
