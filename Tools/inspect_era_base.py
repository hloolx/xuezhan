"""Inspect source base geometry and measure explicit turret platform footprints.

Ordinary Python only. Projection pixels come from actual GLB triangles and their
base-colour texture. Anchors are only emitted for explicitly supplied centres.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("base_mechanism", ROOT / "Tools/Blender/prepare_era_mechanism.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def inspect(entry, output, centres=None, radius=20):
    geometry = common.source_geometry(entry)
    basis = common.normalized_basis(entry, geometry["vertices"])
    points = common.normalized_point(geometry["vertices"], basis) * np.array([100, -100, 100])
    faces = geometry["faces"]
    document, binary = common.static.glb(common.static.absolute(entry["source"]))
    colours = np.zeros((len(faces), 3))
    for index, material in enumerate(document["materials"]):
        info = material["pbrMetallicRoughness"]["baseColorTexture"]
        payload, _ = common.static.extract_image(document, binary, info, common.static.absolute(entry["source"]))
        texture = np.array(Image.open(io.BytesIO(payload)).convert("RGB"))
        mask = geometry["materials"] == index
        uv = geometry["uvs"][faces[mask]].mean(1) % 1
        pixel = np.minimum((uv * [texture.shape[1], texture.shape[0]]).astype(int),
                           [texture.shape[1] - 1, texture.shape[0] - 1])
        colours[mask] = texture[pixel[:, 1], pixel[:, 0]]
    triangle = points[faces]
    norms = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    norms /= np.maximum(np.linalg.norm(norms, axis=1)[:, None], 1e-12)
    light = np.array([.3, -.5, .8])
    light /= np.linalg.norm(light)
    colours *= (.65 + .35 * np.abs(norms @ light))[:, None]
    sheet = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(sheet)
    for view_index, (name, horizontal, vertical, depth, sign) in enumerate([
            ("Front -Y", 0, 2, 1, -1), ("Back +Y", 0, 2, 1, 1),
            ("Top +Z: X right, Y up", 0, 1, 2, 1), ("Side +X", 1, 2, 0, 1)]):
        origin = np.array([(view_index % 2) * 900 + 450, (view_index // 2) * 600 + 545])
        xy = points[:, [horizontal, vertical]]
        lower, upper = xy.min(0), xy.max(0)
        scale = min(800 / (upper[0] - lower[0]), 470 / (upper[1] - lower[1]))
        screen = (xy - [(lower[0] + upper[0]) / 2, lower[1]]) * [scale, -scale] + origin
        for face_index in np.argsort(triangle[:, :, depth].mean(1) * sign):
            draw.polygon([tuple(p) for p in screen[faces[face_index]]],
                         fill=tuple(np.clip(colours[face_index], 0, 255).astype(int)))
        draw.text((origin[0] - 420, origin[1] - 525), name, fill="black")
        tick = 100 if max(upper-lower) > 200 else 20
        for coordinate in range(int(np.ceil(lower[0]/tick))*tick, int(upper[0])+1, tick):
            sx = origin[0] + (coordinate - (lower[0]+upper[0])/2)*scale
            draw.line((sx, origin[1]+4, sx, origin[1]+12), fill="black")
            draw.text((sx-12, origin[1]+15), str(coordinate), fill="black")
        for coordinate in range(int(np.ceil(lower[1]/tick))*tick, int(upper[1])+1, tick):
            sy = origin[1] - (coordinate-lower[1])*scale
            draw.text((origin[0]-440, sy), str(coordinate), fill="black")
        if view_index == 2:
            for label, centre in (centres or {}).items():
                sx, sy = (np.array(centre) - [(lower[0]+upper[0])/2, lower[1]]) * [scale, -scale] + origin
                draw.ellipse((sx-5, sy-5, sx+5, sy+5), outline="magenta", width=2)
                draw.text((sx+6, sy), label, fill="magenta")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    sheet.save(output / "source_projection.png")
    evidence = {"source": geometry["inspection"]["source"], "entry": entry,
                "dimensions_cm": (points.max(0)-points.min(0)).tolist(),
                "bounds_cm": {"minimum": points.min(0).tolist(), "maximum": points.max(0).tolist()},
                "method": "Highest actual source triangle vertical intersection on each explicit 3x3 footprint; anchor 0.5 cm above maximum.",
                "anchors_cm": {}, "samples": {}}
    for label, centre in (centres or {}).items():
        samples = []
        for dx in (-radius, 0, radius):
            for dy in (-radius, 0, radius):
                x, y = centre[0]+dx, centre[1]+dy
                height = common.top_surface(geometry, [x/100, -y/100], basis)*100
                samples.append([x, y, height])
        evidence["samples"][label] = samples
        evidence["anchors_cm"][label] = [*centre, max(row[2] for row in samples)+.5]
    common.static.write(output / "platform_measurement.json", evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--centres", type=Path)
    parser.add_argument("--radius", type=float, default=20)
    args = parser.parse_args()
    plan = common.static.read(args.plan)
    centres = common.static.read(args.centres) if args.centres else {}
    for entry in plan["entries"]:
        result = inspect(entry, args.output / entry["asset_id"], centres.get(entry["asset_id"]), args.radius)
        print(json.dumps({"asset_id": entry["asset_id"], "dimensions_cm": result["dimensions_cm"],
                          "anchors_cm": result["anchors_cm"]}))


if __name__ == "__main__":
    main()
