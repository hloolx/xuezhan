"""Assemble the two actually imported skeletons at the sampled saddle frame."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checked_report(path, expected_asset):
    report = read(path)
    if report.get("asset_id") != expected_asset or report.get("failures") or not report.get("status", "").startswith("imported_"):
        raise ValueError("Actual completed import required: " + str(path))
    if set(report["clips"]) != {"Idle", "Move", "Attack", "Hit", "Death"}:
        raise ValueError("Five real animations required")
    for package in report["packages"]:
        file = Path(package["file"])
        if not file.is_file() or record(file)["sha256"] != package["sha256"]:
            raise ValueError("Saved package changed or missing: " + str(file))
    return report


def part(report, identity):
    return {
        "id": identity, "skeletal_mesh": report["mesh"],
        "animations": {key: value["asset"] for key, value in report["clips"].items()},
        "translation_cm": [0, 0, 0], "rotation_degrees": [0, 0, 0], "uniform_scale": 1.,
        "team_materials": report["materials"]["team_materials"],
    }


def prepare(horse_path, rider_path, output):
    horse = checked_report(horse_path, "Mount_Warhorse")
    rider = checked_report(rider_path, "Unit_Knight")
    for name in horse["clips"]:
        if abs(horse["clips"][name]["duration"] - rider["clips"][name]["duration"]) > .005:
            raise ValueError("Mounted clips do not share a time base: " + name)
    mount_part, rider_part = part(horse, "mount"), part(rider, "rider")
    rider_part.update({
        "parent_part": "mount", "parent_socket": horse["saddle"]["bone"],
        "rotation_degrees": horse["saddle"]["rider_rotation_degrees"],
        "translation_cm": horse["saddle"]["rider_translation_cm"],
    })
    attachments = []
    for row in rider["attachments"]:
        runtime = dict(row["runtime"])
        runtime["parent_part"] = "rider"
        attachments.append(runtime)
    if {row["id"] for row in attachments} != {"Weapon_Lance", "Weapon_RoundShield"}:
        raise ValueError("Actual knight lance and shield are required")
    entry = {
        "kind": "skeletal_unit", "asset_id": "Unit_Knight",
        "enabled": True, "default_runtime_enabled": True, "preview_enabled": True,
        "production_approved": False,
        "height_cm": 205., "reference_move_speed": 230., "contact_time": .4,
        "attack_style": "Thrust", "quadruped": True,
        "parts": [mount_part, rider_part], "attachments": attachments,
        "import_evidence": {"horse": record(horse_path), "rider": record(rider_path)},
        "mounting": {
            "frame": "Actual imported saddle_seat reference orientation",
            "rider_origin": "Measured saddle surface; seat and horse move together",
            "height_cm_usage": "Nameplate and effect placement; does not scale either mesh",
        },
        "runtime_visual_review": "pending_root_gameplay",
    }
    result = {"asset_id": "Unit_Knight", "entry": entry,
              "cook_directories": [horse["destination"], rider["destination"]],
              "actual_package_count": len(horse["packages"]) + len(rider["packages"])}
    if output.exists():
        raise FileExistsError("Preserve prior mounted handoff")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"handoff": str(output), "parts": 2, "attachments": len(attachments)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--horse", required=True, type=Path)
    parser.add_argument("--rider", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.horse.resolve(), args.rider.resolve(), args.output.resolve())
