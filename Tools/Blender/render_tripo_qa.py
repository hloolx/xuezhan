"""Render existing manifest GLBs without rewriting models or previous evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tripo_environment as environment

ROOT = Path(__file__).resolve().parents[2]
DIRECTIONS = {"front": (1, 0, 0), "left": (0, -1, 0), "back": (-1, 0, 0), "right": (0, 1, 0), "preview": (2, -3, 1.6)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--views", nargs="+", choices=list(DIRECTIONS), default=list(DIRECTIONS))
    parser.add_argument("--asset", action="append")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--device", choices=("CPU", "HIP"), default="HIP")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8-sig"))
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / "RawAssets/Art/Tripo_v01").resolve()):
        raise ValueError("Review output must stay under project art")
    if args.size < 256 or args.size > 1024:
        raise ValueError("Use 256-1024 pixel review images")
    selected = [item for item in manifest["assets"] if not args.asset or item["id"] in args.asset]
    for item in selected:
        if any((output / item["id"] / (view + ".png")).exists() for view in args.views):
            raise ValueError("Review exists; use a new review directory")
    report = {"source_manifest": args.manifest, "renderer": "Cycles", "size": args.size, "samples": 12, "assets": []}
    for item in selected:
        source = ROOT / item["file"]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
        objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        lower, upper = environment.bounds(objects)
        centre, span = (lower + upper) * 0.5, max(upper - lower)
        camera, centre, span = environment.setup_render(objects[0], args.device, (centre, span))
        scene = bpy.context.scene
        scene.render.resolution_x = scene.render.resolution_y = args.size
        scene.render.threads_mode = "FIXED"
        scene.render.threads = 2
        scene.cycles.samples = 12
        folder = output / item["id"]
        folder.mkdir(parents=True, exist_ok=True)
        row = {"asset_id": item["id"], "source": item["file"], "model_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "views": {}}
        for view in args.views:
            camera.location = centre + Vector(DIRECTIONS[view]) * span * 2
            camera.rotation_euler = (centre - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.ortho_scale = span * (1.55 if view == "preview" else 1.25)
            destination = folder / (view + ".png")
            scene.render.filepath = str(destination)
            bpy.ops.render.render(write_still=True)
            row["views"][view] = {"file": destination.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
        report["assets"].append(row)
        (output / "render_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
