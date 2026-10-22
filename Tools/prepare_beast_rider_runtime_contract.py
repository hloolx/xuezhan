"""Build the mounted-unit runtime contract only from successful UE reports."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare(mount_path, rider_path, output):
    mount, rider = read(mount_path), read(rider_path)
    expected = {"Idle": 2., "Move": .5, "Attack": 1.6, "Hit": .5, "Death": 1.2}
    for result in (mount, rider):
        if result["status"] != "imported_preview_pending_gameplay" or result.get("failures"):
            raise ValueError("UE import failed for " + result["asset_id"])
        if set(result["clips"]) != set(expected):
            raise ValueError("Five actual animation clips required")
        if result["reference_scale_max_error"] > .01:
            raise ValueError("UE reference scale inconsistent")
        for name, clip in result["clips"].items():
            if abs(clip["duration"] - expected[name]) > .005:
                raise ValueError("Unexpected actual animation duration: " + name)
            error = clip.get("physical_max_bone_error_cm")
            if error is not None and error > .1:
                raise ValueError("Actual UE/DCC physical motion mismatch")
        if set(result["team_materials"]) != {"Blue", "Red"}:
            raise ValueError("Both team materials required")
        if not all(item["exists"] and Path(item["file"]).is_file() for item in result["packages"]):
            raise ValueError("Actual package missing on disk")
    if "saddle_seat" not in mount["bone_names"] or "weapon_r" not in rider["bone_names"]:
        raise ValueError("Attachment bones absent")
    if not rider["weapon_attachment"] or rider["weapon_attachment"]["actual_ue_pose_samples"] != 3:
        raise ValueError("Three-pose actual UE weapon frame correction missing")
    rider_top = rider["bounds_origin_cm"][2] + rider["dimensions_cm"][2] * .5
    mount_reference_top = mount["bounds_origin_cm"][2] + mount["dimensions_cm"][2] * .5
    saddle_idle_z = mount["attachment_idle"]["translation_cm"][2]
    if rider.get("head_idle") is None:
        raise ValueError("Rider actual UE Idle head comparison missing")
    head_delta = rider["head_idle"]["translation_delta_cm"]
    if max(abs(v) for v in head_delta) > .1:
        raise ValueError("Idle head is displaced from reference; need a new posed-head bounds measurement")
    combined_top = max(mount_reference_top, saddle_idle_z + rider_top + head_delta[2])
    parts = []
    for name, result in (("mount", mount), ("rider", rider)):
        part = {"id": name, "skeletal_mesh": result["mesh"],
                "animations": {k: v["asset"] for k, v in result["clips"].items()},
                "translation_cm": [0, 0, 0], "rotation_degrees": [0, 0, 0], "uniform_scale": 1,
                "team_materials": [{"slot": 0, "path": result["team_materials"]["Blue"],
                                    "red_path": result["team_materials"]["Red"]}]}
        if name == "rider":
            part.update(parent_part="mount", parent_socket="saddle_seat",
                        rotation_degrees=mount["attachment_reference"]["inverse_rotation_degrees"])
        parts.append(part)
    result = {"visual_key": "Unit_BeastRider", "status": "imported_preview_pending_gameplay",
              "reference_move_speed_cm_s": 220, "attack_contact_seconds": .4,
              "height_cm": math.ceil(combined_top),
              "height_evidence": {
                  "method": "Actual UE rider mesh reference upper bound plus actual UE Idle saddle height; Idle head translation checked against reference. Mount reference upper bound is also retained. Weapon excluded.",
                  "ground_cm": 0., "rider_reference_top_cm": rider_top,
                  "mount_reference_top_cm": mount_reference_top, "saddle_idle_z_cm": saddle_idle_z,
                  "head_idle_delta_cm": head_delta, "combined_body_top_cm": combined_top,
                  "not_a_gpu_skinned_triangle_bounds_readback": True},
              "parts": parts,
              "attachments": [{"static_mesh": rider["weapon"], "parent_part": "rider",
                               "socket": "weapon_r", "translation_cm": [0, 0, 0], "uniform_scale": 1,
                               "rotation_degrees": rider["weapon_attachment"]["rotation_degrees"]}],
              "source_reports": [record(mount_path), record(rider_path)],
              "actual_ue_frames": {"mount_anchor": mount["attachment_reference"],
                                   "weapon_correction": rider["weapon_attachment"]},
              "preview_limitations": ["Close hand grip remains loose; not final production approval.",
                                      "Game-camera and attack-timing review pending."],
              "production_approved": False}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "mount": mount["dimensions_cm"],
                      "rider": rider["dimensions_cm"],
                      "rider_rotation": parts[1]["rotation_degrees"],
                      "weapon_rotation": result["attachments"][0]["rotation_degrees"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mount", type=Path, default=ART / "mammoth_v01/preview_delivery_02/unreal_import.json")
    parser.add_argument("--rider", type=Path, default=ART / "beast_rider_v01/preview_delivery_02/unreal_import.json")
    parser.add_argument("--output", type=Path, default=ART / "beast_rider_v01/preview_delivery_02/runtime_contract.json")
    args = parser.parse_args()
    prepare(args.mount.resolve(), args.rider.resolve(), args.output.resolve())
