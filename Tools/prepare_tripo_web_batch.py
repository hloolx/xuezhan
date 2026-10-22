"""Prepare an auditable browser batch and visual reference sheets; never submits."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
OUT = ART / "reviews/web_batch_20261020"
OUT.mkdir(parents=True, exist_ok=True)
queue = json.loads((ART / "jobs/queue.json").read_text(encoding="utf-8-sig"))
jobs = [j for j in queue["jobs"] if j["provider"] == "Tripo"
        and j["status"] == "reference_review_pending"]
records = []
for job in jobs:
    asset = job["asset_id"]
    canonical = ART / "prepared_tripo_canonical" / asset
    meta = json.loads((canonical / "canonical_metadata.json").read_text(encoding="utf-8-sig"))
    images = {}
    for view, relative in job["inputs"]["images"].items():
        source = ROOT / relative
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        assert digest == meta["files"][view]["canonical_sha256"], (asset, view)
        with Image.open(source) as im:
            assert im.size == (1024, 1024), (asset, view, im.size)
        images[view] = {"path": str(source), "sha256": digest}
    records.append({
        "asset_id": asset, "display_name": job["display_name"],
        "route": job["route"], "requested_parameters": job["request_parameters"],
        "images": images, "source_review": "pending_visual_review",
        "raw_directory": str(ART / "tripo_raw" / asset / "web_v01_canonical"),
        "submitted": False, "production_approved": False,
    })
for offset in range(0, len(records), 5):
    batch = records[offset:offset + 5]
    sheet = Image.new("RGB", (1200, 330 * len(batch)), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for row, record in enumerate(batch):
        draw.text((10, row * 330 + 3), record["asset_id"], fill="black")
        for col, view in enumerate(["front", "left", "right", "back"]):
            draw.text((col * 300 + 10, row * 330 + 20), view, fill="black")
            if view in record["images"]:
                with Image.open(record["images"][view]["path"]) as im:
                    im.thumbnail((290, 290))
                    sheet.paste(im, (col * 300 + 5, row * 330 + 40))
    sheet.save(OUT / f"references_{offset // 5 + 1:02d}.png")
(OUT / "manifest.json").write_text(
    json.dumps({"schema_version": 1, "source": "jobs/queue.json",
                "scope": "Remaining prepared reference sets; geometry generation only",
                "purchase_authorized": False, "jobs": records}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print(json.dumps({"assets": len(records), "directory": str(OUT)}, ensure_ascii=False))
