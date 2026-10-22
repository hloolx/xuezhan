"""Prepare locked 2x2 character sheets using the existing multiview splitter.

Layout: front / right on the first row, back / left on the second row.
This validates crop geometry only. Shape/style/pose consistency remains unapproved.
Run again as versioned source sheets arrive; existing matching outputs regenerate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
CONFIG = ART / "split_layouts_characters_v02.json"
OUTPUT = ART / "prepared_characters_v02"

spec = importlib.util.spec_from_file_location("civwar_split_multiview", ROOT / "Tools/split_multiview.py")
split = importlib.util.module_from_spec(spec)
spec.loader.exec_module(split)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative(path):
    return path.relative_to(ROOT).as_posix()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_source(asset_id):
    candidates = []
    for path in (ART / "samples" / asset_id).glob("review_turnaround_v*.png"):
        match = re.fullmatch(r"review_turnaround_v(\d+)\.png", path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    return max(candidates, default=(0, None), key=lambda p: p[0])[1]


def blank_separator(sheet, axis):
    """Use a real empty gutter near the center, not a mechanical 50% cut."""
    _, background = split.foreground_box(sheet, 32)
    delta = ImageChops.difference(sheet, Image.new("RGB", sheet.size, background))
    r, g, b = delta.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda p: 255 if p > 32 else 0)
    occupied = mask.getprojection()[axis]
    length = sheet.width if axis == 0 else sheet.height
    # Generated side views of long quadrupeds/vehicles may occupy a wider column.
    # Find the real empty gutter within the central band; output squares remain equal.
    lo, hi = round(length * 0.30), round(length * 0.70)
    runs, start = [], None
    for i in range(lo, hi + 1):
        empty = i < hi and not occupied[i]
        if empty and start is None:
            start = i
        if not empty and start is not None:
            if i - start >= 6 and any(occupied[:start]) and any(occupied[i:]):
                runs.append((start, i))
            start = None
    if not runs:
        raise ValueError("No safe empty " + ("vertical" if axis == 0 else "horizontal") + " gutter; object overlaps the proposed quadrants")
    gap = min(runs, key=lambda ab: abs((ab[0] + ab[1]) / 2 - length / 2))
    return (gap[0] + gap[1]) // 2, list(gap)


def configure_asset(aid, source, preset, previous):
    sha = digest(source)
    if previous and previous["source"] == relative(source) and previous.get("source_sha256") != sha:
        raise ValueError("A locked source changed in place; save a new versioned sheet before preparing it")
    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (250, 249, 246, 255))
        background.alpha_composite(rgba)
        sheet = background.convert("RGB")
    w, h = sheet.size
    if not 0.85 <= w / h <= 1.18:
        raise ValueError("Latest source is not a square 2x2 sheet; an older three-view strip is not a four-view source")
    if previous and previous["source"] == relative(source) and previous["expected_source_size"] != [w, h]:
        raise ValueError("Locked source dimensions changed")
    x, x_gap = blank_separator(sheet, 0)
    y, y_gap = blank_separator(sheet, 1)
    regions = [("front", [0, 0, x, y]), ("right", [x, 0, w, y]),
               ("back", [0, y, x, h]), ("left", [x, y, w, h])]
    views = []
    for name, region in regions:
        panel = sheet.crop(region)
        box, _ = split.foreground_box(panel, 32)
        # Keep a real empty strip on both sides of each crop edge. A crossing body,
        # weapon, shadow or label is rejected rather than silently clipped out.
        distances = [box[0], box[1], panel.width - box[2], panel.height - box[3]]
        if min(distances) < 3:
            raise ValueError(f"{name}: foreground crosses/touches the fixed quadrant ROI (clearances={distances})")
        bounds = [box[0] + region[0], box[1] + region[1], box[2] + region[0], box[3] + region[1]]
        views.append({"view": name, "region": region, "height_reference_y": [bounds[1], bounds[3]],
                      "detected_foreground_box": bounds, "roi_clearances_px": distances})
    # The original splitter performs the full normalization preflight before any
    # output write; no second resize implementation is introduced here.
    return {"id": aid, "source": relative(source), "source_sha256": sha, "expected_source_size": [w, h],
            "generation_preset": preset, "required_project_views": ["front", "right", "back", "left"],
            "layout": "2x2: front,right / back,left", "blank_gutters": {"x": x_gap, "y": y_gap}, "notes": [
                "Automatic crop validation only; visual identity, anatomy, view direction, equipment absence and style still require human review.",
                "Height landmarks use detected silhouette top and ground contact; uniform physical-height assumption requires visual review, especially shadows and non-upright subjects.",
                "All views use isotropic resize, shared fitted height and common ground baseline; no mirroring or invented missing view."],
            "views": views}


def verify_outputs(asset):
    folder = OUTPUT / asset["id"]
    report = read(folder / "split_report.json")
    upload = read(folder / "upload_manifest.json")
    if report["source_sha256"] != asset["source_sha256"]:
        raise ValueError("Prepared output references a different source version")
    rows = []
    for view in ["front", "right", "back", "left"]:
        path = folder / (view + ".png")
        with Image.open(path) as image:
            if image.size != (1024, 1024) or image.mode != "RGB":
                raise ValueError("Unexpected output dimensions/mode: " + str(path))
        item = next(v for v in report["views"] if v["view"] == view)
        rows.append({"view": view, "file": relative(path), "sha256": digest(path),
                     "baseline_px": item["baseline_px"], "reference_height_px": item["normalized_reference_height_px"],
                     "scale_uniform_xy": item["scale_uniform_xy"], "upsampled": item["upsampled"]})
    if len({r["baseline_px"] for r in rows}) != 1 or len({r["reference_height_px"] for r in rows}) != 1:
        raise ValueError("Views do not share a fitted height and baseline")
    if upload["project_missing_views"]:
        raise ValueError("Unexpected missing-view status")
    approved = upload.get("production_approved") is True
    if approved:
        # Approval belongs to exact pixels already submitted by the operator.
        # Keep its scope and other operator metadata, and bind it to source/output
        # hashes. A later source revision must never silently replace these files.
        if upload.get("approved_source_sha256", asset["source_sha256"]) != asset["source_sha256"]:
            raise ValueError("Approved source hash changed; approved inputs are frozen")
        hashes = {r["view"]: r["sha256"] for r in rows}
        if upload.get("approved_view_sha256", hashes) != hashes:
            raise ValueError("Approved output pixels changed; approved inputs are frozen")
        upload["approved_source_sha256"] = asset["source_sha256"]
        upload["approved_view_sha256"] = hashes
        write(folder / "upload_manifest.json", upload)
    triple = Image.new("RGB", (3072, 1024), (250, 249, 246))
    for i, name in enumerate(["front", "right", "back"]):
        with Image.open(folder / (name + ".png")) as image:
            triple.paste(image, (i * 1024, 0))
    triple.save(folder / "review_three_views.png")
    return {"asset_id": asset["id"], "status": "prepared_needs_visual_review", "source": asset["source"],
            "source_sha256": asset["source_sha256"], "source_size": asset["expected_source_size"],
            "output": relative(folder), "review_three_views": relative(folder / "review_three_views.png"),
            "views": rows, "production_approved": approved,
            "approval_scope": upload.get("approval_scope")}


def reusable_output(asset, prior):
    if not prior or prior.get("status") != "prepared_needs_visual_review" or prior.get("source_sha256") != asset["source_sha256"]:
        return False
    folder = OUTPUT / asset["id"]
    try:
        required = ["front.png", "right.png", "back.png", "left.png", "contact_sheet.jpg", "split_report.json", "upload_manifest.json", "tripo_request.template.json"]
        if not all((folder / name).is_file() for name in required):
            return False
        report = read(folder / "split_report.json")
        request = read(folder / "tripo_request.template.json")
        if request != split.request_template([v["view"] for v in asset["views"]], asset["generation_preset"]):
            return False
        for expected, actual in zip(asset["views"], report["views"]):
            if any(expected[key] != actual[key] for key in ["view", "region", "height_reference_y"]):
                return False
        if len(report["views"]) != 4:
            return False
        return all(digest(ROOT / row["file"]) == row["sha256"] for row in prior["views"])
    except (OSError, ValueError, KeyError):
        return False


def reuse_or_protect_approval(asset, prior, force=False):
    manifest_path = OUTPUT / asset["id"] / "upload_manifest.json"
    approved = manifest_path.exists() and read(manifest_path).get("production_approved") is True
    reusable = reusable_output(asset, prior)
    if approved and not reusable:
        raise ValueError("Approved/submitted inputs are frozen: source, crop, request or output hash changed. Use a separate revision output directory.")
    return reusable and (approved or not force)


def write_overview(results):
    ready = [r for r in results if r["status"] == "prepared_needs_visual_review"]
    width, tile = 1200, 100
    image = Image.new("RGB", (width, max(1, len(ready)) * (tile + 22)), "white")
    draw = ImageDraw.Draw(image)
    for index, row in enumerate(ready):
        y = index * (tile + 22)
        status = "REFERENCE APPROVED (see scope)" if row.get("production_approved") else "NOT APPROVED"
        draw.text((4, y + 3), row["asset_id"] + " | front / right / back / left | " + status, fill="#222222")
        for i, view in enumerate(["front", "right", "back", "left"]):
            with Image.open(ROOT / row["output"] / (view + ".png")) as opened:
                thumb = opened.resize((tile, tile), Image.Resampling.LANCZOS)
                image.paste(thumb, (i * 300 + 95, y + 22))
    image.save(OUTPUT / "inspection_overview.jpg", quality=94)


def character_catalog(root=ROOT):
    art = root / "RawAssets/Art/Tripo_v01"
    catalog = read(art / "catalog.json")
    supplement = read(art / "catalog_champions.json")
    champions = [row["VisualKey"] for row in read(root / "Content/Data/Champions.json")]
    if set(champions) != {asset["id"] for asset in supplement["core"]}:
        raise ValueError("Champion reference catalog does not match gameplay data")
    assets = catalog["core"] + catalog["support"] + supplement["core"] + supplement["support"]
    by_id = {asset["id"]: asset for asset in assets}
    if len(by_id) != len(assets):
        raise ValueError("Duplicate reference asset IDs")
    ids = [row["VisualKey"] for row in read(root / "Content/Data/Units.json")]
    ids += ["Mount_Mammoth", "Mount_Warhorse", "Crew_Archer"] + champions
    return ids, by_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", help="Only prepare one planned unit, mount, crew or champion")
    parser.add_argument("--force", action="store_true", help="Regenerate even when source, crop and output hashes match")
    args = parser.parse_args()
    ids, by_id = character_catalog(ROOT)
    if args.asset and args.asset not in ids:
        raise ValueError("Unknown character asset " + args.asset)
    pipeline = read(ART / "pipeline.json")
    old_config = read(CONFIG) if CONFIG.exists() else {"assets": []}
    old = {a["id"]: a for a in old_config["assets"]}
    old_report = read(OUTPUT / "preparation_report.json") if (OUTPUT / "preparation_report.json").exists() else {"results": []}
    prior_results = {r["asset_id"]: r for r in old_report["results"]}
    configured = dict(old)
    prepare_ids, results = [], []
    for aid in ids:
        if args.asset and aid != args.asset:
            continue
        source = latest_source(aid)
        if source is None:
            results.append({"asset_id": aid, "status": "waiting_for_four_view_source", "production_approved": False})
            continue
        route = pipeline["asset_overrides"].get(aid, pipeline["kind_routes"][by_id[aid]["kind"]])
        try:
            configured[aid] = configure_asset(aid, source, pipeline["routes"][route]["request_preset"], old.get(aid))
            prepare_ids.append(aid)
        except Exception as exc:
            results.append({"asset_id": aid, "status": "crop_preflight_failed", "source": relative(source), "error": str(exc), "production_approved": False})
    config = {"version": 2, "size": 1024, "background": [250, 249, 246], "threshold": 32, "padding": 4,
              "output_root": relative(OUTPUT), "source_lock": "Exact dimensions and SHA256; save a new version rather than replacing locked pixels",
              "assets": [configured[aid] for aid in ids if aid in configured]}
    write(CONFIG, config)
    for aid in prepare_ids:
        asset = configured[aid]
        try:
            if digest(ROOT / asset["source"]) != asset["source_sha256"]:
                raise ValueError("Source changed after preflight")
            cached = reuse_or_protect_approval(asset, prior_results.get(asset["id"]), force=args.force)
            if not cached:
                split.run(CONFIG, size_override=1024, asset_filter=asset["id"], force=True)
            row = verify_outputs(asset)
            row["processing"] = "reused_hash_verified_outputs" if cached else "split_with_original_tool"
            results.append(row)
        except Exception as exc:
            results.append({"asset_id": asset["id"], "status": "preparation_failed", "error": str(exc), "production_approved": False})
    if args.asset and (OUTPUT / "preparation_report.json").exists():
        results.extend(r for r in old_report["results"] if r["asset_id"] != args.asset)
    results.sort(key=lambda r: ids.index(r["asset_id"]))
    summary = {"schema_version": 1, "prepared_at": datetime.now(timezone.utc).isoformat(), "planned_character_count": len(ids),
               "prepared_count": sum(r["status"] == "prepared_needs_visual_review" for r in results),
               "waiting_or_failed_count": sum(r["status"] != "prepared_needs_visual_review" for r in results),
               "visual_consistency_approved": False, "review_owner": "root agent / human visual review", "results": results}
    write(OUTPUT / "preparation_report.json", summary)
    write_overview(results)
    (OUTPUT / "README.md").write_text(f"# 角色四视图拆分\n\n运行 `python Tools/prepare_character_views.py` 更新已到齐的{len(ids)}项角色。"
        "每项的 front/right/back/left.png 都是1024×1024 RGB PNG；review_three_views.png 为正、右、背三联人工审阅图。"
        "三联和contact_sheet不能作为单张多视图上传。\n\n裁切配置锁定原图尺寸与SHA256、四格ROI、轮廓高度参考。"
        "触边或跨格会失败；图片不拉伸，所有视图共享归一化物理高度与基线。归一化高度依赖同姿态轮廓假设，"
        "裁切通过不代表造型、左右视方向、解剖或绑定通过。新输入默认production_approved=false；"
        "已有明确批准保持原approval_scope，并锁定approved_source_sha256及四张图片SHA。批准输入不会被--force重写。\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))
    for row in results:
        print(row["asset_id"] + ": " + row["status"] + (" - " + row["error"] if row.get("error") else ""))


if __name__ == "__main__":
    main()
