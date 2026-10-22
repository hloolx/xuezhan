"""Read actual mount rest geometry and joints without a DCC process."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "Blender"))
import prepare_era_asset


def inspect(source):
    doc, binary = prepare_era_asset.glb(source)
    nodes = doc["nodes"]
    parents = {child: i for i, n in enumerate(nodes) for child in n.get("children", [])}
    worlds = {}

    def world(i):
        if i in worlds:
            return worlds[i]
        n = nodes[i]
        if "matrix" in n:
            matrix = np.array(n["matrix"]).reshape(4, 4).T
        else:
            x, y, z, w = n.get("rotation", [0, 0, 0, 1])
            matrix = np.eye(4)
            matrix[:3, :3] = np.array([
                [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
            ]) @ np.diag(n.get("scale", [1, 1, 1]))
            matrix[:3, 3] = n.get("translation", [0, 0, 0])
        worlds[i] = world(parents[i]) @ matrix if i in parents else matrix
        return worlds[i]

    meshes = []
    for i, n in enumerate(nodes):
        if "mesh" not in n:
            continue
        vertices = []
        for p in doc["meshes"][n["mesh"]]["primitives"]:
            a = doc["accessors"][p["attributes"]["POSITION"]]
            v = doc["bufferViews"][a["bufferView"]]
            array = np.ndarray((a["count"], 3), dtype="<f4", buffer=binary,
                               offset=v.get("byteOffset", 0)+a.get("byteOffset", 0),
                               strides=(v.get("byteStride", 12), 4))
            vertices.append(np.c_[array, np.ones(len(array))] @ world(i).T)
        points = np.concatenate(vertices)[:, :3]
        meshes.append({"node": n.get("name"), "minimum": points.min(axis=0).tolist(),
                       "maximum": points.max(axis=0).tolist(), "vertex_count": len(points)})
    joints = []
    for skin in doc.get("skins", []):
        accessor = doc["accessors"][skin["inverseBindMatrices"]]
        view = doc["bufferViews"][accessor["bufferView"]]
        binds = np.ndarray((accessor["count"], 16), dtype="<f4", buffer=binary,
                           offset=view.get("byteOffset", 0)+accessor.get("byteOffset", 0),
                           strides=(view.get("byteStride", 64), 4))
        for j, i in enumerate(skin["joints"]):
            bind = np.linalg.inv(binds[j].reshape(4, 4).T)
            joints.append({"name": nodes[i].get("name"), "position": world(i)[:3, 3].tolist(),
                           "bind_position": bind[:3, 3].tolist(),
                           "bind_world_matrix": bind.tolist(),
                           "parent": nodes[parents[i]].get("name") if i in parents else None})
    return {"source": str(source), "coordinate_system": "original glTF Y-up",
            "meshes": meshes, "joints": joints}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = inspect(args.source)
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+"\n", encoding="utf-8")
    print(text)
