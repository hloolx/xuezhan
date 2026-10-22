"""Assemble exactly seven reviewed Tripo models without changing the runtime map."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Broadleaf", "Env_Pine", "Env_Shrub", "Env_GrassClump"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(selection, root=ROOT, partial_review=False):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", selection["batch_id"]):
        raise ValueError("Unsafe batch name")
    chosen = selection["assets"]
    if len(chosen) != 7 or {item["id"] for item in chosen} != REQUIRED:
        raise ValueError("Exactly seven distinct environment mothers are required")
    if partial_review:
        chosen = [item for item in chosen if item["id"] != "Env_GrassClump"]
    assets = []
    for selected in chosen:
        asset_id = selected["id"]
        manifest = read(root / selected["manifest"])
        candidates = [item for item in manifest["assets"] if item["id"] == asset_id]
        if len(candidates) != 1:
            raise ValueError("Manifest identity mismatch: " + asset_id)
        item = dict(candidates[0])
        model = (root / item["file"]).resolve()
        if not model.is_relative_to((root / "RawAssets/Art/Tripo_v01/tripo_processed").resolve()):
            raise ValueError("Formal source must be processed Tripo geometry")
        if item.get("source") != "tripo_generated_processed_in_blender" or item.get("source_stage") != "textured":
            raise ValueError("Untextured or prototype model: " + asset_id)
        approval = read(root / selected["approval"])
        if approval.get("asset_id") != asset_id or approval.get("approved_for_ue_import") is not True:
            raise ValueError("Missing input-stage visual approval: " + asset_id)
        if approval.get("model_sha256") != digest(model):
            raise ValueError("Reviewed mesh changed: " + asset_id)
        if approval.get("runtime_material_overrides", {}) != item.get("runtime_material_overrides", {}):
            raise ValueError("Reviewed material overrides changed: " + asset_id)
        views = approval.get("reviewed_views")
        if views is None:
            records = approval.get("views", [])
            views = {record["view"]: record for record in records}
            if len(views) != len(records):
                raise ValueError("Duplicate reviewed direction: " + asset_id)
        if not {"front", "left", "back", "right"}.issubset(views):
            raise ValueError("Four reviewed directions required: " + asset_id)
        for view in views.values():
            if digest(root / view["file"]) != view["sha256"]:
                raise ValueError("Reviewed image changed: " + asset_id)
        inspection = read(root / item["inspection"])
        if inspection.get("glb_roundtrip", {}).get("pass") is not True:
            raise ValueError("GLB roundtrip not verified: " + asset_id)
        textures = item.get("textures", [])
        if not textures:
            raise ValueError("Texture evidence missing: " + asset_id)
        for texture in textures:
            if digest(root / texture["file"]) != texture["sha256"]:
                raise ValueError("Texture changed: " + asset_id)
        item.update({"production_approved": False, "input_review": selected["approval"],
                     "reviewed_model_sha256": approval["model_sha256"]})
        assets.append(item)
    return {"schema_version": 1, "batch_id": selection["batch_id"], "units": "cm", "source": "Tripo",
            "status": "six_asset_partial_review_grass_deferred" if partial_review else "input_approved_pending_ue_and_gameplay_acceptance",
            "partial_review_only": partial_review, "deferred_assets": ["Env_GrassClump"] if partial_review else [], "assets": assets,
            "updated_at": datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--partial-review", action="store_true")
    args = parser.parse_args()
    result = assemble(read(ROOT / args.selection), partial_review=args.partial_review)
    destination = ROOT / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(destination), "assets": len(result["assets"]), "runtime_changed": False}))


if __name__ == "__main__":
    main()
