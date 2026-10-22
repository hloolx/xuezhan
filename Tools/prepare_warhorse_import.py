"""Prepare a completed horse animation bundle for the shared native importer."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "Blender"))
import prepare_beast_rider_team_masks as masks


def prepare(directory: Path):
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    destination = directory / "manifest_team01.json"
    if destination.exists():
        raise FileExistsError("Keep the existing import input immutable")
    plan_path = directory / "input_plan.json"
    plan_path.write_text(json.dumps({
        "asset_id": "Mount_Warhorse",
        "source_bind": manifest["source_bind"],
        "source_pbr": manifest["source_pbr"],
        "body_height_cm": manifest["source_height_cm"],
        "reference_move_speed_cm_s": manifest["reference_move_speed_cm_s"],
        "saddle_bone": manifest["saddle_bone"],
        "mount_profile": "Four real FBX hip/knee/ankle/hoof chains; disjoint sole weights; diagonal trot",
        "clips": {row["clip"]: row["duration"] for row in manifest["clips"]},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest.update({
        "plan": masks.rec(plan_path),
        "body_material_name": "Warhorse_OriginalPBR",
        "attachments": [],
        "embedded_equipment_materials": {},
        "mechanism_runtime_ready": True,
        "muzzle_bone": None,
    })
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    masks.prepare(destination)
    actual = json.loads(destination.read_text(encoding="utf-8"))
    if not 0 < actual["team_cloth"]["fraction_selected"] < .5:
        raise ValueError("Inspect the horse cloth selection before import")
    print(json.dumps({"manifest": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    prepare(parser.parse_args().directory.resolve())
