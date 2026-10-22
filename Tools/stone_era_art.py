"""Check the imported stone-era runtime contract without launching Unreal.

The checker never enables an asset or grants a visual approval. A preview can
use structurally verified art that has not yet passed visual review. Default
activation additionally requires a real gameplay visual review.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("Unit_StoneSlinger", "Unit_BeastRider", "Champion_Stone")
CLIPS = ("Idle", "Move", "Attack", "Hit", "Death")
STYLES = {"Unit_StoneSlinger": "Throw", "Unit_BeastRider": "Thrust", "Champion_Stone": "Chop"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite(value, positive=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (not positive or value > 0)


def package(root, object_path):
    if not isinstance(object_path, str) or not re.fullmatch(r"/Game/ArtPilot/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+", object_path):
        raise ValueError(f"Asset path is outside the isolated import directory: {object_path!r}")
    filename = root / "Content" / (object_path.split(".")[0][len("/Game/"):] + ".uasset")
    if not filename.is_file():
        raise ValueError(f"Imported package does not exist: {filename}")
    return filename


def transform(item):
    if "transform" in item:
        raise ValueError("Expand transform fields onto the part or attachment; nested transforms are not a runtime contract")
    for key in ("translation_cm", "rotation_degrees"):
        if key in item and (not isinstance(item[key], list) or len(item[key]) != 3 or not all(finite(v) for v in item[key])):
            raise ValueError(f"{key} must contain three finite numbers")
    scale = item.get("uniform_scale", 1)
    if not finite(scale, True) or scale > 10:
        raise ValueError("uniform_scale must be positive and no greater than 10; do not mirror mounted actors")


def validate_asset(root, asset_id, config, definition, package_check=package):
    if config.get("asset_id") != asset_id:
        raise ValueError("VisualKey and asset_id differ")
    if any(config.get(key) is not True for key in ("enabled", "ue_structural_approved", "animation_contract_verified")):
        raise ValueError("Imported structure or animation contract has not been verified")
    if config.get("attack_style") != STYLES[asset_id]:
        raise ValueError("Attack style differs from the stone-era gameplay role")
    if not finite(config.get("height_cm"), True):
        raise ValueError("height_cm must be a measured positive height")
    for field, source in (("contact_time", "AttackWindup"), ("reference_move_speed", "MoveSpeed")):
        if not finite(config.get(field), True) or abs(config[field] - definition[source]) > 0.001:
            raise ValueError(f"{field} differs from authoritative {source}")
    parts = config.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
        raise ValueError("One to eight skeletal parts are required")
    ids = set()
    packages = []
    for part in parts:
        part_id = part.get("id")
        if not isinstance(part_id, str) or not part_id or part_id in ids:
            raise ValueError("Part ids must be unique nonempty strings")
        transform(part)
        parent = part.get("parent_part")
        if parent and (parent not in ids or not part.get("parent_socket")):
            raise ValueError("A mounted part must reference an earlier parent and a real socket or bone")
        packages.append(package_check(root, part.get("skeletal_mesh")))
        clips = part.get("animations", {})
        if set(clips) != set(CLIPS):
            raise ValueError(f"{part_id} must provide exactly the five animation clips")
        packages.extend(package_check(root, clips[name]) for name in CLIPS)
        team_materials = part.get("team_materials", [])
        if team_materials and config.get("team_material_structural_verified") is not True:
            raise ValueError("Faction material needs a structural verification")
        slots = set()
        for material in team_materials:
            slot = material.get("slot")
            if type(slot) is not int or slot < 0 or slot in slots:
                raise ValueError("Material slots must be unique nonnegative integers")
            slots.add(slot)
            packages.append(package_check(root, material.get("path")))
            if "red_path" in material:
                packages.append(package_check(root, material["red_path"]))
        ids.add(part_id)
    for attachment in config.get("attachments", []):
        transform(attachment)
        if attachment.get("parent_part") not in ids or not attachment.get("socket"):
            raise ValueError("A weapon must attach to a skeletal part socket or bone")
        packages.append(package_check(root, attachment.get("static_mesh")))
    if asset_id == "Unit_StoneSlinger" or "muzzle_part" in config:
        if config.get("muzzle_part") not in ids or not config.get("muzzle_socket"):
            raise ValueError("A projectile needs a real muzzle part and socket or bone")
    return packages


def preflight(root=ROOT, mode="preview", require_complete=False):
    config = read(root / "Content/Data/StoneEraArt.json")
    definitions = {row["VisualKey"]: row for name in ("Units", "Champions") for row in read(root / f"Content/Data/{name}.json")}
    if set(config.get("assets", {})) != set(ASSETS):
        raise ValueError("Stone-era extension must contain exactly Slinger, BeastRider and Champion_Stone")
    included, deferred, failures, packages = [], [], [], []
    for asset_id in ASSETS:
        asset = config["assets"][asset_id]
        activation = (asset.get("preview_enabled") is True if mode == "preview" else
                      asset.get("default_runtime_enabled") is True and asset.get("gameplay_visual_review_approved") is True)
        if asset.get("enabled") is not True or not activation:
            deferred.append(asset_id)
            continue
        try:
            packages.extend(validate_asset(root, asset_id, asset, definitions[asset_id]))
            included.append(asset_id)
        except ValueError as exc:
            failures.append(f"{asset_id}: {exc}")
    if require_complete and deferred:
        failures.append("Stone-era extension is incomplete: " + ", ".join(deferred))
    return {
        "mode": mode,
        "included": included,
        "deferred": deferred,
        "failures": failures,
        "package_count": len(set(packages)),
        "packages": sorted(str(path) for path in set(packages)),
        "flags": ["-cwstoneerapreview"] if mode == "preview" else [],
        "complete_extension_ready": not failures and not deferred,
        "production_approved": False,
        "runtime_validation_required": "Unreal validates classes, skeletons, root-motion flags, attack lengths and actual parent/muzzle sockets. This filesystem preflight does not replace those checks or actual gameplay screenshots.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preview", "default"), default="preview")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = preflight(mode=args.mode, require_complete=args.require_complete)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
