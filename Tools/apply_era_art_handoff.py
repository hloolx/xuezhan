"""Root-owned merge of actual imported era handoffs into default game mapping."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def asset_paths(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from asset_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from asset_paths(child)
    elif isinstance(value, str) and value.startswith("/Game/ArtPilot/") and "." in value:
        yield value


def merge(paths, execute):
    mapping_path = ROOT / "Content/Data/EraArt.json"
    cook_path = ROOT / "Config/DefaultGame.ini"
    mapping, cook = read(mapping_path), cook_path.read_text(encoding="utf-8-sig")
    expected = {
        row["VisualKey"]
        for name in ("Ages", "Units", "Turrets", "Champions")
        for row in read(ROOT / f"Content/Data/{name}.json")
        if row.get("Age", row.get("Index", 0)) > 0
    }
    changed, checked = [], set()
    directories = []
    for path in paths:
        handoff = read(path)
        entry = handoff.get("entry", handoff.get("runtime_entry"))
        if not entry or entry["asset_id"] not in expected:
            raise ValueError("Handoff is not an actual non-stone gameplay entry: " + str(path))
        if entry["kind"] not in {"skeletal_unit", "static_base", "mechanical_turret"}:
            raise ValueError("Unsupported runtime kind")
        for asset in asset_paths(entry):
            package = ROOT / "Content" / (asset.split(".", 1)[0][6:] + ".uasset")
            if not package.is_file() or package.stat().st_size == 0:
                raise ValueError("Native package missing: " + asset)
            checked.add(str(package))
        own_directories = handoff.get("cook_directories") or [handoff.get("cook_directory")]
        if not all(isinstance(folder, str) and re.fullmatch(r"/Game/ArtPilot/[A-Za-z0-9_/]+", folder)
                   for folder in own_directories):
            raise ValueError("Explicit actual Cook directories required")
        for folder in own_directories:
            if not (ROOT / "Content" / folder[6:]).is_dir():
                raise ValueError("Cook directory missing: " + folder)
            directories.append(folder)
        entry.update(enabled=True, default_runtime_enabled=True, preview_enabled=True)
        mapping["assets"][entry["asset_id"]] = entry
        changed.append(entry["asset_id"])
    marker = "[/Script/UnrealEd.ProjectPackagingSettings]\n"
    if marker not in cook:
        raise ValueError("Packaging section missing")
    additions = []
    for folder in sorted(set(directories)):
        line = f'+DirectoriesToAlwaysCook=(Path="{folder}")'
        if line not in cook:
            additions.append(line)
    if additions:
        cook = cook.replace(marker, marker + "\n".join(additions) + "\n", 1)
    if execute:
        temporary = mapping_path.with_suffix(".merge.tmp")
        temporary.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(mapping_path)
        cook_path.write_text(cook, encoding="utf-8")
    print(json.dumps({"applied": execute, "assets": changed, "existing_native_packages_checked": len(checked),
                      "cook_added": additions}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("handoff", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    merge([path.resolve() for path in args.handoff], args.apply)
