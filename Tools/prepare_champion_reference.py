"""Prepare one reviewed champion sheet; never writes shared queues or reports.

python Tools/prepare_champion_reference.py --asset Champion_Medieval \
  --generated <imagegen-file.png> --top-right-faces left --review-note "..."

The profile direction is an observed input, not guessed from the prompt.
Existing source/prepared pixels are immutable. Only the named asset's new
directories are written. The current character splitter and verified Tripo
view mapping are reused without modifying their historical files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "Tools" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--top-right-faces", choices=("left", "right"), required=True)
    parser.add_argument("--review-note", required=True)
    args = parser.parse_args()
    views = module("champion_views", "prepare_character_views.py")
    canonical = module("champion_canonical", "prepare_tripo_canonical_views.py")
    catalog = views.read(ART / "catalog_champions.json")
    if args.asset not in {a["id"] for a in catalog["core"]}:
        raise ValueError("Expected a catalog champion")
    directory = ART / "samples" / args.asset
    source = directory / "review_turnaround_v01.png"
    directory.mkdir(parents=True, exist_ok=True)
    if source.exists():
        if source.read_bytes() != args.generated.read_bytes():
            raise ValueError("Do not overwrite a different source sheet")
    else:
        shutil.copy2(args.generated, source)
    prompt = directory / "generation_prompt.txt"
    if not prompt.is_file():
        raise ValueError("Save the actual generation prompt before preparing")
    brief = views.read(ART / "prompts" / args.asset / "brief.json")
    preset = brief["production_route"]["request_preset"]
    asset = views.configure_asset(args.asset, source, preset, None)
    if args.top_right_faces == "right":
        for row in asset["views"]:
            if row["view"] in {"left", "right"}:
                row["view"] = "left" if row["view"] == "right" else "right"
    asset["layout"] = ("front,right / back,left" if args.top_right_faces == "left"
                       else "front,left / back,right")
    asset["notes"].append(args.review_note)
    config = {"version": 2, "size": 1024, "background": [250, 249, 246],
              "threshold": 32, "padding": 4,
              "output_root": "RawAssets/Art/Tripo_v01/prepared_characters_v02",
              "assets": [asset]}
    config_path = directory / "split_config_reviewed.json"
    if config_path.exists() and views.read(config_path) != config:
        raise ValueError("Existing split configuration differs")
    views.write(config_path, config)
    prepared = ART / "prepared_characters_v02" / args.asset
    if not (prepared / "upload_manifest.json").exists():
        views.split.run(config_path, asset_filter=args.asset)
    checked = views.verify_outputs(asset)
    visual_review = {
        "asset_id": args.asset, "source": str(source), "source_sha256": views.digest(source),
        "generated_source": str(args.generated.resolve()), "tool": "built_in_image_gen",
        "prompt": str(prompt), "prompt_sha256": views.digest(prompt),
        "review_note": args.review_note, "reference_generation_ready": True,
        "observed_top_right_nose_direction": args.top_right_faces,
        "observed_bottom_right_nose_direction": "right" if args.top_right_faces == "left" else "left",
        "pixel_mirroring_used": False, "scope": "Reference sheet suitable for the next Tripo geometry stage",
        "production_model_approved": False,
    }
    views.write(directory / "reference_review.json", visual_review)
    upload = views.read(prepared / "upload_manifest.json")
    upload.update(reference_generation_ready=True, reference_review=str(directory / "reference_review.json"))
    views.write(prepared / "upload_manifest.json", upload)
    result = canonical.prepare(prepared, ART / "prepared_tripo_canonical" / args.asset,
                               ROOT, canonical.probe_evidence(ROOT))
    result.update(reference_generation_ready=True, source=str(source), split_config=str(config_path),
                  prepared=checked["output"], prompt=str(prompt), production_model_approved=False)
    views.write(directory / "prepared_reference_receipt.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
