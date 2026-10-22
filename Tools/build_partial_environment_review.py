from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sync_tripo_quality_reviews import merge_isolated_import

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"Env_BoulderA", "Env_BoulderB", "Env_RockSlab", "Env_Shrub", "Env_Pine", "Env_Broadleaf"}


def build_review_map(report, root=ROOT):
    if {result["id"] for result in report["results"]} != EXPECTED or len(report["results"]) != 6:
        raise ValueError("Partial review requires exactly six mothers, with Grass explicitly deferred")
    ledger = {"assets": {asset_id: {} for asset_id in EXPECTED}}
    merge_isolated_import(ledger, report, "temporary_validation_only", root)
    assets = {}
    for result in report["results"]:
        source = (root / result["source"]).resolve()
        if not source.is_relative_to((root / "RawAssets/Art/Tripo_v01/tripo_processed").resolve()):
            raise ValueError("Partial review cannot include prototype sources")
        mesh = next(item for item in result["assets"] if item.get("type") == "static_mesh")
        if not mesh["path"].startswith("/Game/ArtPilot/tripo_environment_v03/"):
            raise ValueError("Unexpected isolated Tripo environment package")
        assets[result["id"]] = {"object_path": mesh["path"], "source": result["source"],
                               "source_sha256": result["source_sha256"], "dimensions_cm": mesh["dimensions_cm"],
                               "triangles_lod0": mesh["triangles_lod0"],
                               "runtime_material_overrides": result["runtime_material_overrides"]}
    runtime = root / "Content/Data/EnvironmentArt.json"
    return {"schema_version": 1, "partial_review_only": True, "production_approved": False,
            "status": "six_asset_temporary_game_camera_review_not_full_environment_delivery",
            "deferred_assets": ["Env_GrassClump"], "hide_deferred_grass": True,
            "permanent_runtime_mapping_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
            "assets": assets}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / "RawAssets/Art/Tripo_v01/reviews").resolve()):
        raise ValueError("Review mapping must stay outside Content in the art review directory")
    report = json.loads((ROOT / args.report).read_text(encoding="utf-8-sig"))
    document = build_review_map(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"review_map": str(output), "assets": 6, "runtime_mapping_modified": False}))


if __name__ == "__main__":
    main()
