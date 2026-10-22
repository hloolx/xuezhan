"""Prepare measured geometry-only inputs for explicitly NEW local bindings."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from assess_chief_local_rig import geometry
from prepare_era_character_plan import build
from prepare_era_human_queue import target_folder
from prepare_chief_local_regions import distances

ROOT = Path(__file__).resolve().parents[1]


def prepare(output, assets, candidate=1):
    output.mkdir(parents=True, exist_ok=False)
    template = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw/Unit_Rifleman/web_v01_canonical/rigged.fbx"
    measurement = ROOT/"RawAssets/Art/Tripo_v01/tripo_processed/rifleman_v01/fbx_candidate_01/actual_source_bind.json"
    actual = json.loads(measurement.read_text(encoding="utf-8-sig"))
    from assess_chief_local_rig import record
    if actual["source_fbx"]["sha256"] != record(template)["sha256"]:
        raise ValueError("Actual measured FBX template changed")
    template_geometry = template.with_name("pbr.glb")
    _, template_points, _, _ = geometry(template_geometry)
    template_height = float(np.ptp(template_points[:, 1]))
    # Parent names come from the actual source GLB's hierarchy only; its
    # transforms and skin weights never supply the proposed local binding.
    rig_doc, _, _, _ = geometry(template.with_name("rigged.glb"))
    nodes = rig_doc["nodes"]
    edges = [(nodes[parent]["name"], nodes[child]["name"])
             for parent in rig_doc["skins"][0]["joints"]
             for child in nodes[parent].get("children", [])
             if nodes[child].get("name") in actual["actual_named_bones"]]
    plans, tasks = [], []
    for asset in assets:
        plan = build(asset)
        source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/asset/"web_v01_canonical/pbr.glb"
        doc, points, faces, colors = geometry(source)
        if sum("mesh" in node for node in doc["nodes"]) != 1 or any(
                any(k in node for k in ("matrix", "rotation", "scale", "translation")) for node in doc["nodes"]):
            raise ValueError("Explicit node transform handling required for target geometry")
        unique, aliases = np.unique(np.round(points, 5), axis=0, return_inverse=True)
        adjacency = [set() for _ in unique]
        for a, b, c in aliases[faces]:
            adjacency[a].update((int(b), int(c)))
            adjacency[b].update((int(a), int(c)))
            adjacency[c].update((int(a), int(b)))
        world = unique[:, [0, 2, 1]].copy()
        world[:, 1] *= -1
        region_path = output/(asset+"_regions.json")
        regions = {
            "schema": "actual_connected_local_human_regions_v1", "source": record(source),
            "unique_vertices": len(unique), "points_world_m": world.tolist(),
            "welded_adjacency": [sorted(row) for row in adjacency],
            "cape_strength": [0.] * len(unique), "tabard_strength": [0.] * len(unique),
            "cloth_helpers": False,
            "method": "Actual welded mesh adjacency; hand/sole and same-side limb constraints fitted in DCC. No imported target weights used.",
            "binding_authored": False, "deformation_verified": False,
        }
        if asset == "Champion_Future":
            # Actual front/back projections show short blue rigid hip plates,
            # not a free cape. Keep their connected white trim with the pelvis.
            height = float(np.ptp(points[:, 1]))
            face_centre = points[faces].mean(axis=1)/height
            blue = (colors[:, 2] > colors[:, 0]*1.17) & (colors[:, 2] > colors[:, 1]*1.035)
            selected = blue & (face_centre[:, 1] > .405) & (face_centre[:, 1] < .54) & (abs(face_centre[:, 0]) < .23)
            seeds = np.zeros(len(unique), dtype=bool)
            seeds[aliases[faces[selected]].reshape(-1)] = True
            domain = (unique[:, 1]/height > .395) & (unique[:, 1]/height < .55) & (abs(unique[:, 0])/height < .23)
            distance = distances(unique, adjacency, seeds, domain, .045*height)
            q = np.clip((distance/height-.025)/.02, 0, 1)
            regions["pelvis_plate_strength"] = (1-q*q*(3-2*q)).tolist()
            regions["pelvis_plate_method"] = "Actual blue hip plate seeds plus connected trim; rigid pelvis influence, no new skirt bones"
            regions["hand_lateral_min_height"] = .235
            regions["rigid_hands"] = True
        region_path.write_text(json.dumps(regions, separators=(",", ":"))+"\n", encoding="utf-8")
        height = float(np.ptp(points[:, 1]))
        bones = {name: np.array([p[0], p[2], -p[1]])*height/template_height
                 for name, p in actual["actual_named_bones"].items()}
        image = Image.new("RGB", (1320, 700), (29, 32, 38))
        draw = ImageDraw.Draw(image)
        for panel, (horizontal, depth, direction) in enumerate(((0, 2, 1), (2, 0, 1), (0, 2, -1))):
            project = lambda p: (220+panel*440+float(p[horizontal])*565/height, 640-float(p[1])*565/height)
            for i in np.argsort(points[faces, depth].mean(axis=1)*direction):
                draw.polygon([project(p) for p in points[faces[i]]], fill=tuple(int(v) for v in colors[i]))
            if panel < 2:
                for a, b in edges:
                    draw.line([project(bones[a]), project(bones[b])], fill=(255, 218, 62), width=2)
            draw.text((panel*440+12, 18), asset+" / "+("front", "side", "back")[panel], fill="white")
        draw.text((12, 675), "Actual geometry + measured template only; no accepted binding or deformation yet.", fill="white")
        image.save(output/(asset+"_geometry.png"))
        plan["local_binding_preparation"] = {
            "source_geometry": record(source), "template_actual_fbx": record(template),
            "regions": record(region_path), "cloth_helpers": False,
            "scope": "Explicit new local authorship; original broken target skin is not recovered",
        }
        plans.append(plan)
        tasks.append({
            "asset": asset, "source_geometry": record(source),
            "template_actual_fbx": record(template), "regions": str(region_path),
            "output": str(target_folder(asset)/("local_candidate_%02d" % candidate)),
            "binding_output": str(ROOT/"RawAssets/Art/Tripo_v01/tripo_processed/local_authored_rigs"/asset/("candidate_%02d" % candidate)),
            "status": "geometry_prepared_pending_actual_dcc_and_visual",
        })
    plan_path = output/"input_plan.json"
    plan_path.write_text(json.dumps({"entries": plans}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (output/"queue.json").write_text(json.dumps({
        "schema": "explicit_local_human_binding_queue_v1", "input_plan": record(plan_path),
        "tasks": tasks, "heavy_process_started": False, "runtime_config_written": False,
    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "assets": assets, "binding_authored": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset", action="append", required=True)
    parser.add_argument("--candidate", type=int, default=1)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.asset, args.candidate)
