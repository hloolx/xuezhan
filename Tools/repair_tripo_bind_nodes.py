"""Restore omitted GLB joint transforms from the file's real inverse bind data.

Only accepts the specific all-identity-node export defect. Binary mesh, UV,
skin weights and embedded PBR bytes remain identical. Never edits a source.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Tools/Blender"))
from prepare_era_asset import glb


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    if any(key in node for key in ("translation", "rotation", "scale")):
        raise ValueError("TRS-bearing source must be diagnosed separately")
    return np.eye(4)


def repair(asset):
    source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/asset/"web_v01_canonical/rigged.glb"
    document, binary = glb(source)
    skin, = document["skins"]
    nodes = document["nodes"]
    joints = skin["joints"]
    if any(not np.allclose(matrix(nodes[j]), np.eye(4), atol=1e-8) for j in joints):
        return {"asset": asset, "status": "source_has_explicit_transforms_no_repair"}
    mesh_nodes = [i for i, node in enumerate(nodes) if node.get("skin") == 0]
    if len(mesh_nodes) != 1 or any("matrix" in n or any(k in n for k in ("translation", "rotation", "scale")) for n in nodes):
        raise ValueError("Only the exact identity-node defect is supported")
    accessor = document["accessors"][skin["inverseBindMatrices"]]
    if accessor["componentType"] != 5126 or accessor["type"] != "MAT4" or accessor["count"] != len(joints):
        raise ValueError("Invalid actual inverse bind accessor")
    view = document["bufferViews"][accessor["bufferView"]]
    if view.get("byteStride", 64) != 64:
        raise ValueError("Interleaved inverse binds require explicit adapter")
    offset = view.get("byteOffset", 0)+accessor.get("byteOffset", 0)
    inverse_binds = np.frombuffer(binary, dtype="<f4", count=len(joints)*16, offset=offset).reshape(-1, 4, 4).transpose(0, 2, 1).astype(float)
    if not np.isfinite(inverse_binds).all():
        raise ValueError("Nonfinite inverse bind matrix")
    worlds = {joint: np.linalg.inv(inverse_binds[i]) for i, joint in enumerate(joints)}
    parents = {child: parent for parent, node in enumerate(nodes) for child in node.get("children", [])}
    if max(np.linalg.norm(world[:3, 3]) for world in worlds.values()) < .1:
        raise ValueError("Inverse bind data does not establish a usable physical rig")
    for joint in joints:
        parent = worlds.get(parents.get(joint), np.eye(4))
        local = np.linalg.inv(parent) @ worlds[joint]
        nodes[joint]["matrix"] = local.T.reshape(-1).tolist()
    recomputed = {}
    def world(index):
        if index not in recomputed:
            recomputed[index] = (world(parents[index]) if index in parents else np.eye(4)) @ matrix(nodes[index])
        return recomputed[index]
    residual = max(float(np.abs(world(joint) @ inverse_binds[i] - np.eye(4)).max()) for i, joint in enumerate(joints))
    if residual > 1e-6:
        raise ValueError("Actual inverse-bind reconstruction failed")
    folder = ROOT/"RawAssets/Art/Tripo_v01/tripo_processed/rig_bind_repairs"/asset
    folder.mkdir(parents=True, exist_ok=False)
    output = folder/"rigged_bind_pose.glb"
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" "*((-len(encoded)) % 4)
    size = 12+8+len(encoded)+8+len(binary)
    output.write_bytes(struct.pack("<III", 0x46546c67, 2, size)+struct.pack("<II", len(encoded), 0x4e4f534a)+encoded+
                       struct.pack("<II", len(binary), 0x004e4942)+binary)
    _, actual_binary = glb(output)
    if actual_binary != binary:
        raise ValueError("Binary source preservation failed")
    report = {"asset": asset, "status": "exact_inverse_bind_node_reconstruction",
        "source": {"path": str(source), "sha256": sha(source)}, "derived": {"path": str(output), "sha256": sha(output)},
        "binary_mesh_skin_pbr_unchanged": True, "joint_count": len(joints),
        "maximum_bind_identity_residual": residual, "blender_validation": "pending",
        "reason": "All original node transforms were omitted; actual inverseBindMatrices define the original bind pose"}
    (folder/"repair.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", action="append", required=True)
    args = parser.parse_args()
    for asset in args.asset:
        try:
            print(json.dumps(repair(asset), ensure_ascii=False))
        except ValueError as error:
            print(json.dumps({"asset": asset, "requires_separate_review": str(error)}, ensure_ascii=False))
