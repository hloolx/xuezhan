"""Derive red cloth maps while preserving source PBR and all unmasked pixels."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def rec(path):
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def linear(rgb):
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def srgb(rgb):
    return np.where(rgb <= .0031308, rgb * 12.92, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - .055)


def prepare(path):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    source = Path(manifest["textures"]["base_color"]["path"])
    raw = np.asarray(Image.open(source).convert("RGB")).copy()
    rgb = raw.astype(np.float32) / 255.
    r, g, b = (rgb[:, :, i] for i in range(3))
    alpha = np.clip((b - r - 8 / 255.) / (15 / 255.), 0, 1) * np.clip((b - g - 3 / 255.) / (6 / 255.), 0, 1)
    pixels = np.rint(alpha * 255).astype(np.uint8)
    alpha = pixels.astype(np.float32) / 255.
    source_linear = linear(rgb)
    weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    team = np.array([.92, .16, .10], dtype=np.float32)
    recolored = source_linear @ weights
    recolored = recolored[:, :, None] * (team / np.dot(team, weights))
    mixed = source_linear * (1 - alpha[:, :, None]) + recolored * alpha[:, :, None]
    red = np.rint(np.clip(srgb(mixed), 0, 1) * 255).astype(np.uint8)
    red[alpha == 0] = raw[alpha == 0]
    directory = path.parent / "team_cloth"
    directory.mkdir(exist_ok=True)
    mask_path, red_path = directory / "cloth_mask.png", directory / "base_color_red.png"
    Image.fromarray(pixels).save(mask_path)
    Image.fromarray(red).save(red_path)
    report = {"selection": "Only blue-dominant cloth pixels, smooth threshold; original PBR unchanged.",
              "source": rec(source), "mask": rec(mask_path), "red_base_color": rec(red_path),
              "dimensions": list(Image.open(source).size), "nonzero_pixels": int((pixels > 0).sum()),
              "fraction_selected": float((pixels > 0).mean()),
              "unmasked_pixels_changed": int(np.any(raw[pixels == 0] != red[pixels == 0], axis=1).sum()),
              "semantic_visual_review": "pending assembly red/blue images"}
    (directory / "selection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest["team_cloth"] = report
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(path), "selected": report["fraction_selected"],
                      "unmasked_changed": report["unmasked_pixels_changed"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.manifest:
        prepare(path.resolve())
