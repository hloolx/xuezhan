"""Lightweight actual-mesh projections for a proposed, explicitly new local rig.

No Blender, binding, new skeleton or corrected Tripo data is created here.
"""
import io
import json
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Tools/Blender"))
from prepare_era_asset import glb, record


def array(document, binary, index):
    acc = document["accessors"][index]
    view = document["bufferViews"][acc["bufferView"]]
    if acc.get("sparse") or view.get("extensions"):
        raise ValueError("Special accessor requires explicit handling")
    dtype = {5126: "<f4", 5123: "<u2", 5125: "<u4"}[acc["componentType"]]
    width = {"VEC3": 3, "VEC2": 2, "SCALAR": 1}[acc["type"]]
    size = np.dtype(dtype).itemsize
    return np.ndarray((acc["count"], width), dtype=dtype, buffer=binary,
                      offset=view.get("byteOffset", 0)+acc.get("byteOffset", 0),
                      strides=(view.get("byteStride", width*size), size)).copy()


def geometry(path):
    doc, binary = glb(path)
    primitive, = doc["meshes"][0]["primitives"]
    points = array(doc, binary, primitive["attributes"]["POSITION"])
    uv = array(doc, binary, primitive["attributes"]["TEXCOORD_0"])
    triangles = array(doc, binary, primitive["indices"]).reshape(-1, 3)
    mat = doc["materials"][primitive["material"]]
    texture = doc["textures"][mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    image = doc["images"][texture["source"]]
    view = doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    pixels = np.asarray(Image.open(io.BytesIO(binary[start:start+view["byteLength"]])).convert("RGB"))
    samples = np.clip(uv[triangles].mean(axis=1), 0, 1)
    colors = pixels[(samples[:, 1]*(pixels.shape[0]-1)).astype(int),
                    (samples[:, 0]*(pixels.shape[1]-1)).astype(int)]
    return doc, points, triangles, colors


def main():
    source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw/Champion_Medieval/web_v01_canonical/pbr.glb"
    template = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw/Unit_Knight/web_v01_canonical/rigged.glb"
    inspection = ROOT/"RawAssets/Art/Tripo_v01/reviews/TripoBindFrameCompare_01/Unit_Knight.json"
    doc, points, triangles, colors = geometry(source)
    template_doc, template_points, _, _ = geometry(template)
    actual = json.loads(inspection.read_text(encoding="utf-8"))
    height = float(np.ptp(points, axis=0)[1])
    template_height = float(np.ptp(template_points, axis=0)[1])
    ratio = height/template_height
    bones = {}
    for name, row in actual["per_bone"].items():
        x, y, z = row["actual_fbx_head"]
        bones[name] = np.array([x, z, -y])*ratio
    nodes = template_doc["nodes"]
    edges = [(nodes[parent]["name"], nodes[child]["name"])
             for parent in template_doc["skins"][0]["joints"] for child in nodes[parent].get("children", [])
             if nodes[child].get("name") in bones]
    image = Image.new("RGB", (1350, 710), (29, 32, 38))
    draw = ImageDraw.Draw(image)
    views = (("Chief actual base-color mesh / front", points, triangles, colors, 0, 2, False),
             ("Chief + measured Knight bones / front", points, triangles, colors, 0, 2, True),
             ("Chief + measured Knight bones / side", points, triangles, colors, 2, 0, True))
    scale = 570/height
    for panel, (label, data, faces, paint, horizontal, depth, overlay) in enumerate(views):
        origin = panel*450+225
        project = lambda point: (origin+float(point[horizontal])*scale, 650-float(point[1])*scale)
        for index in np.argsort(data[faces, depth].mean(axis=1)):
            draw.polygon([project(point) for point in data[faces[index]]], fill=tuple(int(x) for x in paint[index]))
        if overlay:
            for parent, child in edges:
                draw.line([project(bones[parent]), project(bones[child])], fill=(255, 218, 62), width=2)
            for name in ("pelvis", "spine_02", "head", "upperarm_l", "upperarm_r", "lowerarm_l",
                         "lowerarm_r", "hand_l", "hand_r", "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r"):
                x, y = project(bones[name])
                draw.ellipse((x-3, y-3, x+3, y+3), fill=(255, 83, 74))
        draw.text((panel*450+12, 22), label, fill=(235, 235, 235))
    draw.text((12, 680), "Geometry-only diagnostic. Template bones are a measured starting point, not an accepted target binding.", fill=(210, 210, 210))
    output = ROOT/"RawAssets/Art/Tripo_v01/reviews/ChiefLocalRigFeasibility_01"
    output.mkdir(parents=True, exist_ok=False)
    image.save(output/"actual_mesh_template_projection.png")
    report = {
        "source_geometry": record(source), "template_actual_fbx": actual["fbx"],
        "template_measurement": record(inspection),
        "source_dimensions_m_gltf": np.ptp(points, axis=0).tolist(),
        "template_dimensions_m_gltf": np.ptp(template_points, axis=0).tolist(),
        "height_ratio": ratio, "initial_measured_template_bone_heads_gltf": {k: v.tolist() for k, v in bones.items()},
        "scope": "Read-only source geometry and actual FBX template comparison; original broken GLB weights ignored",
        "binding_authored": False, "deformation_verified": False, "production_approved": False,
    }
    (output/"assessment_input.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "source_dimensions": report["source_dimensions_m_gltf"],
                      "template_dimensions": report["template_dimensions_m_gltf"], "height_ratio": ratio}))


if __name__ == "__main__":
    main()
