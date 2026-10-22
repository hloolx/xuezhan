"""Split reviewed turnarounds into equal square, proportion-preserving Tripo inputs.

Requires Pillow. No network, background removal, mirroring or AI generation.
ROIs are explicit because generated sheets rarely have equal panel widths.
All views of an asset share a physical-height scale and ground baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

ROOT = Path(__file__).resolve().parents[1]
PRESETS_PATH = ROOT / "RawAssets/Art/Tripo_v01/generation_presets.json"
VIEWS = ("front", "left", "back", "right")


def workspace_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Path must stay in workspace: {value}")
    return path


def box_checked(value, size, label):
    if len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError(f"{label}: expected four integer coordinates")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise ValueError(f"{label}: box outside image: {value}")
    return tuple(value)


def foreground_box(image: Image.Image, threshold: int):
    """Find bounds only; retain all original RGB pixels, including light surfaces.

    The input must have a plain light background. Explicit content_box is the
    preferred override for white armor, shadows, text or low-contrast objects.
    """
    w, h = image.size
    edge = min(8, w, h)
    corners = Image.new("RGB", (edge * 4, edge))
    for i, xy in enumerate(((0, 0), (w-edge, 0), (0, h-edge), (w-edge, h-edge))):
        corners.paste(image.crop((xy[0], xy[1], xy[0]+edge, xy[1]+edge)), (i*edge, 0))
    background = tuple(int(v) for v in ImageStat.Stat(corners).median)
    difference = ImageChops.difference(image, Image.new("RGB", image.size, background))
    channels = difference.split()
    delta = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = delta.point(lambda p: 255 if p > threshold else 0)
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError("No visible object found; supply a reviewed content_box")
    if sum(mask.histogram()[1:]) < 100:
        raise ValueError("Foreground too small/noisy; supply a reviewed content_box")
    return bounds, background


def flatten_edge_background(image, sampled_background, target_background, tolerance=12):
    """Replace only near-background pixels connected to the outer boundary.

    This removes rectangular off-white padding without globally keying out
    light-colored details enclosed by the object. It is not semantic masking;
    use a manual mask/transparent source for very low-contrast white assets.
    """
    if sampled_background is None:
        _, sampled_background = foreground_box(image, 32)
    diff = ImageChops.difference(image, Image.new("RGB", image.size, sampled_background))
    r, g, b = diff.split()
    delta = ImageChops.lighter(ImageChops.lighter(r, g), b)
    eligible = delta.point(lambda p: 255 if p <= tolerance else 0)
    bordered = Image.new("L", (image.width+2, image.height+2), 255)
    bordered.paste(eligible, (1, 1))
    ImageDraw.floodfill(bordered, (0, 0), 128)
    outside = bordered.crop((1, 1, image.width+1, image.height+1)).point(lambda p: 255 if p == 128 else 0)
    return Image.composite(Image.new("RGB", image.size, target_background), image, outside)


def normalize_views(sheet, views, size=1024, background=(250, 249, 246),
                    threshold=32, padding=4, height_fraction=0.82,
                    baseline_fraction=0.92, margin_fraction=0.05):
    names = [view["view"] for view in views]
    if len(names) != len(set(names)) or not set(names).issubset(VIEWS):
        raise ValueError("Views must have unique front/left/back/right keys")
    if "front" not in names or not 2 <= len(names) <= 4:
        raise ValueError("Tripo requires front and at least one other view")
    if type(size) is not int or size < 256:
        raise ValueError("Output size must be an integer >= 256")
    if not (0 < height_fraction <= 1 and 0 < margin_fraction < baseline_fraction < 1-margin_fraction):
        raise ValueError("Invalid scale/margin/baseline fractions")
    if type(padding) is not int or padding < 0 or not 0 <= threshold <= 255:
        raise ValueError("Invalid padding or threshold")
    source = sheet.convert("RGB")
    prepared = []
    for view in views:
        roi = box_checked(view["region"], source.size, view["view"])
        panel = source.crop(roi)
        if "content_box" in view:
            bounds = box_checked(view["content_box"], source.size, "content_box")
            if not (roi[0] <= bounds[0] < bounds[2] <= roi[2] and roi[1] <= bounds[1] < bounds[3] <= roi[3]):
                raise ValueError("content_box must be inside region")
            sampled_bg = None
        else:
            local, sampled_bg = foreground_box(panel, threshold)
            # A non-empty mask at a crop boundary usually indicates a cut body.
            if local[0] <= 1 or local[1] <= 1 or local[2] >= panel.width-1 or local[3] >= panel.height-1:
                raise ValueError(f"{view['view']}: foreground touches ROI edge; expand/review region")
            bounds = (local[0]+roi[0], local[1]+roi[1], local[2]+roi[0], local[3]+roi[1])
        crop = (max(roi[0], bounds[0]-padding), max(roi[1], bounds[1]-padding),
                min(roi[2], bounds[2]+padding), min(roi[3], bounds[3]+padding))
        # These two source-Y landmarks represent the SAME physical span in each
        # view. Defaults assume an upright subject with the same overall height.
        ref_top, ref_bottom = view.get("height_reference_y", [bounds[1], bounds[3]])
        if not (crop[1] <= ref_top < ref_bottom <= crop[3]):
            raise ValueError("Height references must be inside the crop")
        ref_height = ref_bottom-ref_top
        cleaned_panel = flatten_edge_background(panel, sampled_bg, tuple(background))
        local_crop = (crop[0]-roi[0], crop[1]-roi[1], crop[2]-roi[0], crop[3]-roi[1])
        prepared.append({"view": view["view"], "region": roi, "content_box": bounds,
                         "crop_box": crop, "height_reference_y": [ref_top, ref_bottom],
                         "reference_height": ref_height, "sampled_background": sampled_bg,
                         "tile": cleaned_panel.crop(local_crop)})

    baseline = round(size*baseline_fraction)
    margin = round(size*margin_fraction)
    # Fit the widest view FIRST, then apply the resulting height to every view.
    # This prevents a long vehicle's side from being clipped or front enlarged.
    target_height = size*height_fraction
    for item in prepared:
        crop, span = item["crop_box"], item["reference_height"]
        target_height = min(target_height, (size-2*margin)*span/(crop[2]-crop[0]))
        above = item["height_reference_y"][1]-crop[1]
        below = crop[3]-item["height_reference_y"][1]
        target_height = min(target_height, (baseline-margin)*span/above)
        if below > 0:
            target_height = min(target_height, (size-margin-baseline)*span/below)

    result, reports = {}, []
    for item in prepared:
        tile = item.pop("tile")
        scale = target_height/item["reference_height"]
        tile_size = (round(tile.width*scale), round(tile.height*scale))
        if min(tile_size) < 1:
            raise ValueError("Invalid normalized object dimensions")
        resized = tile.resize(tile_size, Image.Resampling.LANCZOS)
        x = (size-resized.width)//2
        y = baseline-round((item["height_reference_y"][1]-item["crop_box"][1])*scale)
        if x < 0 or y < 0 or x+resized.width > size or y+resized.height > size:
            raise ValueError("Internal fit error: output would clip object")
        canvas = Image.new("RGB", (size, size), tuple(background))
        canvas.paste(resized, (x, y))
        result[item["view"]] = canvas
        item.update({"scale_uniform_xy": scale, "paste_xy": [x, y], "resized_crop_size": tile_size,
                     "normalized_reference_height_px": target_height, "baseline_px": baseline,
                     "upsampled": scale > 1.0})
        reports.append(item)
    return result, reports


def generation_preset(name):
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]
    if name not in presets:
        raise ValueError(f"Unknown generation preset: {name}")
    preset = presets[name]
    if preset["parameters"].get("texture") is not False or preset["parameters"].get("pbr") is not False:
        raise ValueError("Geometry-first presets must disable both texture and pbr")
    return preset


def request_template(names, preset="h_mechanical_geometry"):
    names = list(names)
    if len(names) != len(set(names)) or set(names) - set(VIEWS) or "front" not in names or not 2 <= len(names) <= 4:
        raise ValueError("Request requires front and 2-4 unique named views")
    return {"inputs": [{name: f"REPLACE_WITH_{name.upper()}_FILE_TOKEN_OR_PUBLIC_URL"}
                       for name in VIEWS if name in names],
            **generation_preset(preset)["parameters"]}


def run(config_path, size_override=None, asset_filter=None, force=False):
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    size = size_override or config.get("size", 1024)
    output_root = workspace_path(config["output_root"])
    selected = [a for a in config["assets"] if not asset_filter or a["id"] == asset_filter]
    if not selected:
        raise ValueError(f"No configured asset: {asset_filter}")
    ids = [a["id"] for a in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate asset ID")
    jobs = []
    for asset in selected:
        asset_id = asset["id"]
        if not asset_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in asset_id):
            raise ValueError("Asset ID must contain only letters, digits, underscore or hyphen")
        source = workspace_path(asset["source"])
        with Image.open(source) as opened:
            opened.load()
            if list(opened.size) != asset["expected_source_size"]:
                raise ValueError(f"{asset_id}: source size changed; re-review crop regions")
            # Flatten existing alpha without turning transparent areas black.
            rgba = opened.convert("RGBA")
            flattened = Image.new("RGBA", rgba.size, tuple(config.get("background", [250, 249, 246]))+(255,))
            flattened.alpha_composite(rgba)
            images, report = normalize_views(flattened.convert("RGB"), asset["views"], size=size,
                background=config.get("background", [250, 249, 246]),
                threshold=config.get("threshold", 32), padding=config.get("padding", 4))
        destination = output_root / asset_id
        preset_name = asset.get("generation_preset", "h_mechanical_geometry")
        preset = generation_preset(preset_name)
        request = request_template(images, preset_name)
        required = asset.get("required_project_views", ["front", "right", "back"])
        if set(required) - set(VIEWS):
            raise ValueError(f"{asset_id}: invalid required_project_views")
        filenames = [f"{v}.png" for v in images] + ["contact_sheet.jpg", "split_report.json", "upload_manifest.json", "tripo_request.template.json"]
        if not force and any((destination/f).exists() for f in filenames):
            raise FileExistsError(f"{asset_id}: output exists; pass --force to regenerate prepared outputs")
        jobs.append((asset, source, destination, images, report, preset_name, preset, request, required))

    # Preflight every asset before writing any file.
    summary = []
    for asset, source, destination, images, report, preset_name, preset, request, required in jobs:
        destination.mkdir(parents=True, exist_ok=True)
        for name, image in images.items():
            image.save(destination/f"{name}.png")
        thumb = 360
        contact = Image.new("RGB", (len(images)*thumb, thumb+36), "white")
        draw = ImageDraw.Draw(contact)
        for i, (name, image) in enumerate(images.items()):
            contact.paste(image.resize((thumb, thumb), Image.Resampling.LANCZOS), (i*thumb, 0))
            draw.text((i*thumb+12, thumb+10), f"{asset['id']} / {name}", fill="#333333")
        contact.save(destination/"contact_sheet.jpg", quality=95)
        report_data = {"asset": asset["id"], "source": asset["source"],
                       "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "size": [size, size], "mode": "RGB", "format": "PNG",
                       "status": "prepared_needs_visual_review", "asset_notes": asset.get("notes", []),
                       "normalization": "Same physical-height span and baseline; isotropic scaling; shared fit for all views",
                       "views": report}
        upload = {"asset": asset["id"], "files": {v: f"{v}.png" for v in VIEWS if v in images},
                  "missing_views": [v for v in VIEWS if v not in images],
                  "api_documentation": preset["documentation"],
                  "generation_preset": preset_name,
                  "stage": "geometry_first_no_texture",
                  "project_required_views": required,
                  "project_missing_views": [v for v in required if v not in images],
                  "production_approved": False,
                  "legacy_positional_order": list(VIEWS),
                  "legacy_local_file_map_not_api_request": [f"{v}.png" if v in images else "" for v in VIEWS],
                  "note": "Upload individual files first. Local filenames are not API URLs/tokens. Do not upload contact_sheet. Never mirror right to invent left."}
        for filename, data in (("split_report.json", report_data), ("upload_manifest.json", upload),
                               ("tripo_request.template.json", request)):
            (destination/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        summary.append({"asset": asset["id"], "views": list(images), "size": size,
                        "reference_height_px": round(report[0]["normalized_reference_height_px"], 2),
                        "output": destination.relative_to(ROOT).as_posix()})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--size", type=int, help="Square output size; default comes from config")
    parser.add_argument("--asset", help="Export one configured asset")
    parser.add_argument("--force", action="store_true", help="Replace prepared outputs, never original images")
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.size, args.asset, args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
