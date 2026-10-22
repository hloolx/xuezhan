"""Measure connected cloth regions on the actual Chief mesh; no DCC process."""
import heapq
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Tools"))
from assess_chief_local_rig import array, geometry
sys.path.insert(0, str(ROOT/"Tools/Blender"))
from prepare_era_asset import glb, record


def distances(points, adjacency, seeds, allowed, maximum):
    result = np.full(len(points), np.inf)
    queue = []
    for i in np.flatnonzero(seeds & allowed):
        result[i] = 0
        heapq.heappush(queue, (0., int(i)))
    while queue:
        distance, vertex = heapq.heappop(queue)
        if distance > result[vertex]:
            continue
        for other in adjacency[vertex]:
            candidate = distance+float(np.linalg.norm(points[vertex]-points[other]))
            if allowed[other] and candidate <= maximum and candidate < result[other]:
                result[other] = candidate
                heapq.heappush(queue, (candidate, other))
    return result


def main():
    source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw/Champion_Medieval/web_v01_canonical/pbr.glb"
    output = ROOT/"RawAssets/Art/Tripo_v01/reviews/ChiefLocalRigRegions_02"
    output.mkdir(parents=True, exist_ok=False)
    doc, binary = glb(source)
    primitive, = doc["meshes"][0]["primitives"]
    positions = array(doc, binary, primitive["attributes"]["POSITION"])
    uv = array(doc, binary, primitive["attributes"]["TEXCOORD_0"])
    triangles = array(doc, binary, primitive["indices"]).reshape(-1, 3)
    texture = doc["materials"][primitive["material"]]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    image = doc["images"][doc["textures"][texture]["source"]]
    view = doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    pixels = np.asarray(Image.open(io.BytesIO(binary[start:start+view["byteLength"]])).convert("RGB"))/255.
    uv = np.clip(uv, 0, 1)
    color = pixels[(uv[:, 1]*(pixels.shape[0]-1)).astype(int), (uv[:, 0]*(pixels.shape[1]-1)).astype(int)]
    points, inverse = np.unique(np.round(positions, 5), axis=0, return_inverse=True)
    colors, count = np.zeros((len(points), 3)), np.zeros(len(points))
    np.add.at(colors, inverse, color)
    np.add.at(count, inverse, 1)
    colors /= count[:, None]
    adjacency = [set() for _ in points]
    for a, b, c in inverse[triangles]:
        adjacency[a].update((int(b), int(c)))
        adjacency[b].update((int(a), int(c)))
        adjacency[c].update((int(a), int(b)))
    height = float(np.ptp(points[:, 1]))
    x, z, forward = (points/height).T
    blue = (colors[:, 2] > colors[:, 0]*1.17) & (colors[:, 2] > colors[:, 1]*1.035)
    cape_domain = (abs(x) < .245) & (z > .28) & (z < .83) & (forward < .035)
    front_domain = (abs(x) < .16) & (z > .245) & (z < .545) & (forward > .035)
    cape_distance = distances(points, adjacency, blue & (forward < -.035), cape_domain, .065*height)
    front_distance = distances(points, adjacency, blue & (forward > .07), front_domain, .065*height)
    strengths = []
    for distance in (cape_distance, front_distance):
        q = np.clip((distance/height-.04)/.025, 0, 1)
        strengths.append(1-q*q*(3-2*q))
    cape, tabard = strengths
    # Points are original glTF Y-up; the DCC consumes actual FBX/Blender Z-up.
    world = points[:, [0, 2, 1]].copy()
    world[:, 1] *= -1
    report = {
        "schema": "actual_connected_cloth_regions_v1", "source": record(source),
        "method": "Original blue-cloth seeds expanded along welded actual mesh edges, including white trim; no straight-line transfer across an air gap",
        "vertex_alias_tolerance_m": 1e-5,
        "unique_vertices": len(points), "cape_full_vertices": int((cape > .99).sum()),
        "tabard_full_vertices": int((tabard > .99).sum()),
        "points_world_m": world.tolist(), "cape_strength": cape.tolist(), "tabard_strength": tabard.tolist(),
        "welded_adjacency": [sorted(row) for row in adjacency],
        "binding_authored": False, "deformation_verified": False,
    }
    (output/"regions.json").write_text(json.dumps(report, separators=(",", ":"))+"\n", encoding="utf-8")
    _, actual, faces, paint = geometry(source)
    canvas = Image.new("RGB", (1320, 700), (29, 32, 38))
    draw = ImageDraw.Draw(canvas)
    labels = cape[inverse[faces]].mean(axis=1), tabard[inverse[faces]].mean(axis=1)
    for panel, direction in enumerate((1, -1, 1)):
        horizontal, depth = (0, 2) if panel < 2 else (2, 0)
        scale = 565/height
        origin = 220+panel*440
        for i in np.argsort(actual[faces, depth].mean(axis=1)*direction):
            base = paint[i].astype(float)*.62
            base = base*(1-labels[0][i])+np.array([20, 230, 130])*labels[0][i]
            base = base*(1-labels[1][i])+np.array([255, 100, 50])*labels[1][i]
            draw.polygon([(origin+float(v[horizontal])*scale, 640-float(v[1])*scale) for v in actual[faces[i]]],
                         fill=tuple(base.astype(int)))
        draw.text((panel*440+12, 18), ("Front", "Back", "Side")[panel]+" / green=cape, orange=tabard", fill="white")
    draw.text((12, 675), "Connected actual mesh diagnostic only. Original positions, topology and UV are not changed.", fill="white")
    canvas.save(output/"connected_regions.png")
    print(json.dumps({k: report[k] for k in ("unique_vertices", "cape_full_vertices", "tabard_full_vertices")}))


if __name__ == "__main__":
    main()
