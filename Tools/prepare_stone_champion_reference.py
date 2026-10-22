"""Prepare the reviewed new chieftain with the existing measured splitter."""
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
SPEC = importlib.util.spec_from_file_location("character_views", ROOT / "Tools/prepare_character_views.py")
views = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(views)
source = ART / "samples/Champion_Stone/review_turnaround_v01.png"
generated = Path("C:/Users/12153/.codex/generated_images/01a157ba-0ca2-7aa0-9b6b-06d3a6ef39bf/exec-200ae2d0-2453-4e9b-ad81-3b2339e22684.png")
source.parent.mkdir(parents=True, exist_ok=True)
if source.exists():
    assert source.read_bytes() == generated.read_bytes(), "Do not overwrite a different source"
else:
    shutil.copy2(generated, source)
pipeline = views.read(ART / "pipeline.json")
route = pipeline["kind_routes"]["human"]
asset = views.configure_asset("Champion_Stone", source, pipeline["routes"][route]["request_preset"], None)
# The generated sheet's top-right profile faces image-right. The existing
# project design-right convention faces image-left, so use the bottom-right
# panel for design-right. This changes file roles, never mirrors pixels.
for row in asset["views"]:
    if row["view"] in ("left", "right"):
        row["view"] = "right" if row["view"] == "left" else "left"
asset["layout"] = "front,left / back,right; observed profile direction, no mirroring"
asset["notes"].append("Root visually checked the four views: one consistent unarmed chieftain, short cloak, distinct bone crown; model generation-stage approval only.")
config = {
    "version": 2, "size": 1024, "background": [250, 249, 246], "threshold": 32, "padding": 4,
    "output_root": "RawAssets/Art/Tripo_v01/prepared_characters_v02",
    "assets": [asset],
}
path = source.parent / "split_config_reviewed.json"
views.write(path, config)
destination = ART / "prepared_characters_v02/Champion_Stone"
if not (destination / "upload_manifest.json").exists():
    views.split.run(path, asset_filter="Champion_Stone")
views.verify_outputs(asset)
canonical = ART / "prepared_tripo_canonical/Champion_Stone"
if (canonical / "canonical_metadata.json").exists():
    manifest_path = ART / "reviews/web_batch_20261020/manifest.json"
    manifest = views.read(manifest_path)
    if not any(j["asset_id"] == "Champion_Stone" for j in manifest["jobs"]):
        manifest["jobs"].append({
            "asset_id": "Champion_Stone", "display_name": "部落酋长",
            "route": route, "requested_parameters": views.read(canonical / "tripo_request.template.json"),
            "images": {name: {"path": str(canonical / (name + ".png")), "sha256": views.digest(canonical / (name + ".png"))}
                       for name in ("front", "left", "right", "back")},
            "source_review": "Root reviewed generated four views and explicit profile orientation; geometry-stage approval only",
            "raw_directory": str(ART / "tripo_raw/Champion_Stone/web_v01_canonical"),
            "submitted": False, "production_approved": False,
        })
        manifest["active_scope"] = "Stone era completion: preserve submitted medieval work, no further medieval generation in this batch"
        manifest["scope"] = "Geometry, texture/PBR and rigging, followed by separately verified game integration"
        views.write(manifest_path, manifest)
print(json.dumps({"source": str(source), "split_config": str(path), "prepared": str(destination)}, ensure_ascii=False))
