"""Read-only comparison of actual FBX binding against missing-TRS GLB exports.

Uses four received FBXs as evidence. Never emits repaired GLBs or runtime data.
"""
import argparse
import itertools
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from prepare_era_asset import glb, record

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ("Unit_Knight", "Unit_Crossbowman", "Crew_Archer", "Unit_Engineer")


def accessor(document, binary, index):
    acc = document["accessors"][index]
    view = document["bufferViews"][acc["bufferView"]]
    if acc.get("sparse"):
        raise ValueError("Sparse data requires another reader")
    kind = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    offset = view.get("byteOffset", 0)+acc.get("byteOffset", 0)
    stride = view.get("byteStride", np.dtype(kind).itemsize*width)
    values = np.ndarray((acc["count"], width), dtype=kind, buffer=binary,
                        offset=offset, strides=(stride, np.dtype(kind).itemsize)).copy()
    if acc.get("normalized") and acc["componentType"] != 5126:
        values = values.astype(float)/np.iinfo(kind).max
    return values


def fit_affine(source, target):
    matrix = np.linalg.lstsq(np.column_stack([source, np.ones(len(source))]), target, rcond=None)[0].T
    errors = np.linalg.norm(np.column_stack([source, np.ones(len(source))]) @ matrix.T-target, axis=1)
    result = np.eye(4)
    result[:3] = matrix
    return result, errors


def compare(asset, directory):
    source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/asset/"web_v01_canonical"
    document, binary = glb(source/"rigged.glb")
    skin, = document["skins"]
    nodes = document["nodes"]
    names = [nodes[i]["name"] for i in skin["joints"]]
    inverse = accessor(document, binary, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    bind = np.linalg.inv(inverse.astype(float))
    raw_points, raw_weights = [], []
    for node in nodes:
        if node.get("skin") != 0:
            continue
        if any(key in node for key in ("matrix", "translation", "rotation", "scale")):
            raise ValueError("Expected exactly the missing-node-transform defect")
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            attrs = primitive["attributes"]
            positions = accessor(document, binary, attrs["POSITION"])
            joints = accessor(document, binary, attrs["JOINTS_0"]).astype(int)
            weights = accessor(document, binary, attrs["WEIGHTS_0"])
            dense = np.zeros((len(positions), len(names)))
            for i in range(4):
                np.add.at(dense, (np.arange(len(positions)), joints[:, i]), weights[:, i])
            raw_points.extend(positions)
            raw_weights.extend(dense)
    raw_points, raw_weights = np.array(raw_points), np.array(raw_weights)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.threads_mode, bpy.context.scene.render.threads = "FIXED", 2
    bpy.ops.import_scene.fbx(filepath=str(source/"rigged.fbx"), use_anim=False,
                            automatic_bone_orientation=False)
    rig, = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    rig.animation_data_clear()
    for bone in rig.pose.bones:
        bone.matrix_basis.identity()
    bpy.context.view_layer.update()
    fbx_points, fbx_weights = [], []
    for mesh in bpy.context.scene.objects:
        if mesh.type != "MESH" or not any(m.type == "ARMATURE" and m.object == rig for m in mesh.modifiers):
            continue
        groups = {group.index: names.index(group.name) for group in mesh.vertex_groups if group.name in names}
        for vertex in mesh.data.vertices:
            fbx_points.append(list(mesh.matrix_world @ vertex.co))
            weight = np.zeros(len(names))
            for group in vertex.groups:
                if group.group in groups:
                    weight[groups[group.group]] = group.weight
            fbx_weights.append(weight)
    fbx_points, fbx_weights = np.array(fbx_points), np.array(fbx_weights)
    fbx_bones = np.array([list((rig.matrix_world @ rig.pose.bones[name].matrix).translation) for name in names])
    if not len(fbx_points):
        raise ValueError("Actual FBX has no skinned vertices")
    tree = KDTree(len(fbx_points))
    for index, point in enumerate(fbx_points):
        tree.insert(Vector(point), index)
    tree.balance()
    # Search only fixed axis bases, not arbitrary geometry warps.
    source_center = (raw_points.min(axis=0)+raw_points.max(axis=0))/2
    target_center = (fbx_points.min(axis=0)+fbx_points.max(axis=0))/2
    source_size = np.ptp(raw_points, axis=0)
    target_size = np.ptp(fbx_points, axis=0)
    sample = raw_points[np.linspace(0, len(raw_points)-1, 384).astype(int)]
    candidates = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1., 1.), repeat=3):
            rotation = np.eye(3)[list(permutation)]*np.array(signs)[:, None]
            scale = np.max(target_size)/np.max(source_size)
            translation = target_center-rotation @ source_center*scale
            points = sample @ rotation.T*scale+translation
            error = np.mean([tree.find(Vector(point))[2] for point in points])
            candidates.append((error, rotation, scale, translation))
    _, rotation, scale, translation = min(candidates, key=lambda row: row[0])
    mesh_transform = np.eye(4)
    mesh_transform[:3, :3], mesh_transform[:3, 3] = rotation*scale, translation
    aligned = raw_points @ rotation.T*scale+translation
    nearest = [tree.find(Vector(point)) for point in aligned]
    indices = np.array([row[1] for row in nearest])
    distances = np.array([row[2] for row in nearest])
    weights_error = np.abs(raw_weights-fbx_weights[indices]).sum(axis=1)
    bone_transform, bone_error = fit_affine(bind[:, :3, 3], fbx_bones)
    # Express the needed correction directly in original GLB vertex coordinates.
    correction = np.linalg.inv(mesh_transform) @ bone_transform
    singular = np.linalg.svd(correction[:3, :3], compute_uv=False)
    result = {
        "asset": asset, "fbx": record(source/"rigged.fbx"), "glb": record(source/"rigged.glb"),
        "bones": len(names), "raw_vertices": len(raw_points), "fbx_vertices": len(fbx_points),
        "glb_mesh_to_fbx_world": mesh_transform.tolist(),
        "mesh_nearest_max_m": float(distances.max()), "mesh_nearest_mean_m": float(distances.mean()),
        "matched_weight_L1_max": float(weights_error.max()),
        "matched_weight_L1_mean": float(weights_error.mean()),
        "weight_matches_within_1e_5_fraction": float((weights_error < 1e-5).mean()),
        "inverse_bind_heads_to_actual_fbx": bone_transform.tolist(),
        "bone_affine_max_m": float(bone_error.max()), "bone_affine_mean_m": float(bone_error.mean()),
        "required_bind_correction_in_glb_mesh_frame": correction.tolist(),
        "correction_linear_singular_values": singular.tolist(),
        "per_bone": {name: {"inverse_bind_head": bind[i, :3, 3].tolist(),
                            "actual_fbx_head": fbx_bones[i].tolist(), "affine_error_m": float(bone_error[i])}
                     for i, name in enumerate(names)},
        "repaired_asset_written": False, "production_approved": False,
    }
    path = directory/(asset+".json")
    path.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("asset", "mesh_nearest_max_m", "matched_weight_L1_max",
        "bone_affine_max_m", "required_bind_correction_in_glb_mesh_frame")}))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = [compare(asset, output) for asset in ASSETS]
    matrices = np.array([row["required_bind_correction_in_glb_mesh_frame"] for row in results])
    summary = {
        "scope": "Four real FBXs, exact mesh nearest correspondences and actual vertex-group weights",
        "assets": list(ASSETS), "maximum_correction_matrix_difference": float(np.abs(matrices-matrices[0]).max()),
        "maximum_linear_correction_difference": float(np.abs(matrices[:, :3, :3]-matrices[0, :3, :3]).max()),
        "translation_by_asset": {row["asset"]: row["required_bind_correction_in_glb_mesh_frame"] for row in results},
        "can_claim_universal_recovery": False, "repaired_asset_written": False,
        "conclusion": "Numeric evidence requires review; no automatic fallback adoption",
    }
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
