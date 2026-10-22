"""Retain the exact Mammoth PBR surface while transferring proven real rig weights."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspect_mammoth_rig as audit_tool


BRANCH = audit_tool.BRANCH
SOURCE = audit_tool.SOURCE
RECEIVED = audit_tool.RAW_FOLDER / "model.glb"
AUDIT = BRANCH / "rig_audit_02/inspection.json"
MAPPING = BRANCH / "rig_audit_02/full_triangle_correspondence.json"
FROZEN = {SOURCE: audit_tool.SOURCE_SHA,
          RECEIVED: "0367adcb349945ae38c1d1cec591a2a7fd2e1c062a27e5970a50ff77c0529fbf",
          AUDIT: "4ecc3e88ef12664466d766eb23b8f7b770d88480ec739fa9462c4edd895caff4",
          MAPPING: "fa28e8d539b5061ff475ec9dcd13f605cb55d4401d945625d6b9ae960de04752"}
BASIS = np.array(((1, 0, 0), (0, 0, -1), (0, 1, 0)), dtype=float)
TOLERANCE_M = 3e-6
POSES = [
    {"name": "front_positive_y", "bone": "tripo::0_Left_Limb_0", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x1_y1"},
    {"name": "front_negative_y", "bone": "tripo::1_Right_Limb_0", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x1_y-1"},
    {"name": "hind_positive_y", "bone": "tripo::1_Left_Limb_0", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x-1_y1"},
    {"name": "hind_negative_y", "bone": "tripo::1_Left_Limb_1", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x-1_y-1"},
    {"name": "trunk", "bone": "tripo::0_Right_Limb_0", "axis_world": [0, 1, 0], "degrees": 10, "target_probe": "trunk_tip"},
    {"name": "tail", "bone": "bone_32", "axis_world": [0, 0, 1], "degrees": 10, "target_probe": "tail_tip"},
    {"name": "shoulder_positive_y", "bone": "bone_11", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x1_y1"},
    {"name": "shoulder_negative_y", "bone": "tripo::Spine_4", "axis_world": [0, 1, 0], "degrees": 8, "target_probe": "x1_y-1"},
]


def read_container(path):
    data = Path(path).read_bytes()
    magic, version, size = struct.unpack_from("<III", data)
    if magic != 0x46546C67 or version != 2 or size != len(data):
        raise ValueError("Invalid GLB container")
    chunks, offset = {}, 12
    while offset < size:
        length, kind = struct.unpack_from("<II", data, offset)
        if kind in chunks or offset + 8 + length > size:
            raise ValueError("Duplicate or truncated GLB chunk")
        chunks[kind] = data[offset + 8:offset + 8 + length]
        offset += 8 + length
    return json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]


def accessor(document, binary, index):
    item = document["accessors"][index]
    if "sparse" in item or item.get("normalized"):
        raise ValueError("Do not silently decode normalized or sparse skin attributes")
    view = document["bufferViews"][item["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise ValueError("External buffer unsupported")
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[item["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[item["type"]]
    stride = view.get("byteStride", dtype.itemsize * width)
    offset = view.get("byteOffset", 0) + item.get("byteOffset", 0)
    values = np.ndarray((item["count"], width), dtype=dtype, buffer=binary, offset=offset,
                        strides=(stride, dtype.itemsize)).copy()
    if item["type"] == "MAT4":
        return values.reshape(-1, 4, 4).transpose(0, 2, 1)
    return values[:, 0] if item["type"] == "SCALAR" else values


def local_matrix(node):
    if "matrix" in node:
        if any(key in node for key in ("translation", "rotation", "scale")):
            raise ValueError("GLTF node mixes matrix and TRS")
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    quat = np.array(node.get("rotation", (0, 0, 0, 1)), dtype=float)
    if abs(float(np.linalg.norm(quat)) - 1) > 1e-5:
        raise ValueError("Unexpected non-unit bone quaternion")
    quat /= np.linalg.norm(quat)
    qx, qy, qz, qw = quat
    rotation = np.array(((1 - 2 * (qy*qy + qz*qz), 2 * (qx*qy - qz*qw), 2 * (qx*qz + qy*qw)),
                         (2 * (qx*qy + qz*qw), 1 - 2 * (qx*qx + qz*qz), 2 * (qy*qz - qx*qw)),
                         (2 * (qx*qz - qy*qw), 2 * (qy*qz + qx*qw), 1 - 2 * (qx*qx + qy*qy))))
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag(node.get("scale", (1, 1, 1)))
    matrix[:3, 3] = node.get("translation", (0, 0, 0))
    return matrix


def world_matrices(document):
    nodes = document["nodes"]
    parents = {}
    for parent, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parents:
                raise ValueError("Node has multiple parents")
            parents[child] = parent
    worlds, active = {}, set()

    def visit(index):
        if index in active:
            raise ValueError("Bone parent cycle")
        if index not in worlds:
            active.add(index)
            worlds[index] = (visit(parents[index]) if index in parents else np.eye(4)) @ local_matrix(nodes[index])
            active.remove(index)
        return worlds[index]

    for index in range(len(nodes)):
        visit(index)
    return worlds, parents


def append_accessor(document, binary, values, kind, component_type):
    while len(binary) % 4:
        binary.append(0)
    values = np.asarray(values, dtype={5121: "u1", 5123: "<u2", 5126: "<f4"}[component_type])
    count = len(values)
    if kind == "MAT4":
        values = values.transpose(0, 2, 1).copy()
    payload = values.tobytes()
    view = len(document["bufferViews"])
    document["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(payload)})
    binary.extend(payload)
    index = len(document["accessors"])
    document["accessors"].append({"bufferView": view, "componentType": component_type, "count": count, "type": kind})
    return index


def encode(document, binary):
    document["buffers"][0]["byteLength"] = len(binary)
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    return struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary)) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + struct.pack("<II", len(binary), 0x004E4942) + binary


def resolve_weights(mapping, joints, weights, source_count):
    chosen = []
    for source_index in range(source_count):
        candidates = mapping.get(str(source_index))
        if not candidates:
            raise ValueError("Incomplete source vertex correspondence")
        first = candidates[0]
        expected = {int(joint): float(weight) for joint, weight in zip(joints[first], weights[first]) if weight > 0}
        for candidate in candidates[1:]:
            actual = {int(joint): float(weight) for joint, weight in zip(joints[candidate], weights[candidate]) if weight > 0}
            if actual != expected:
                raise ValueError("Inconsistent coincident-corner weights; averaging is forbidden")
        chosen.append(first)
    return joints[chosen].copy(), weights[chosen].copy(), np.array(chosen)


def skin_positions(positions, joints, weights, matrices):
    homogeneous = np.column_stack((positions, np.ones(len(positions))))
    result = np.zeros_like(homogeneous)
    for column in range(joints.shape[1]):
        result += np.einsum("nij,nj->ni", matrices[joints[:, column]], homogeneous) * weights[:, column, None]
    return result[:, :3]


def source_arrays(document, binary):
    if len(document["meshes"]) != 1 or len(document["meshes"][0]["primitives"]) != 1:
        raise ValueError("Expected one mesh primitive")
    primitive = document["meshes"][0]["primitives"][0]
    arrays = {name: accessor(document, binary, index) for name, index in primitive["attributes"].items()}
    arrays["indices"] = accessor(document, binary, primitive["indices"]).reshape(-1, 3)
    return arrays


def make_candidate():
    for path, expected in FROZEN.items():
        if audit_tool.texture.core.record(path)["sha256"] != expected:
            raise ValueError("Frozen audited input changed: " + str(path))
    audit_tool.lineage(RECEIVED)
    source_doc, source_binary = read_container(SOURCE)
    raw_doc, raw_binary = read_container(RECEIVED)
    source, raw = source_arrays(source_doc, source_binary), source_arrays(raw_doc, raw_binary)
    audit = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8-sig"))
    if len(raw_doc.get("skins", [])) != 1 or raw_doc.get("animations"):
        raise ValueError("Expected audited single skin without clips")
    joints = raw_doc["skins"][0]["joints"]
    if len(joints) != 33 or source_doc["nodes"] != [{"mesh": 0, "name": "tripo_node_37ec2f0d"}]:
        raise ValueError("Frozen mesh/root structure changed")
    raw_worlds, parents = world_matrices(raw_doc)
    raw_inverse = accessor(raw_doc, raw_binary, raw_doc["skins"][0]["inverseBindMatrices"])
    raw_matrices = np.array([raw_worlds[index] @ inverse for index, inverse in zip(joints, raw_inverse)])
    raw_rest = skin_positions(raw["POSITION"], raw["JOINTS_0"], raw["WEIGHTS_0"], raw_matrices)
    fit = audit["frame_fit"]
    scale = fit["uniform_scale"]
    rotation = np.array(fit["rotation"])
    translation = np.array(fit["translation_m"])
    raw_physical = raw["POSITION"].astype(float) @ BASIS.T @ rotation.T * scale + translation
    rows = audit["skeleton"]["weights"][0]["all_vertex_weights"]
    audit_index_error = float(np.linalg.norm(raw_physical - np.array([row["world_review_m"] for row in rows]), axis=1).max())
    if audit_index_error > TOLERANCE_M:
        raise ValueError("GLB indexed vertices do not match actual Blender evidence")
    for row in rows:
        weights = {raw_doc["nodes"][joints[int(joint)]]["name"]: float(weight)
                   for joint, weight in zip(raw["JOINTS_0"][row["vertex"]], raw["WEIGHTS_0"][row["vertex"]]) if weight > 0}
        if weights != row["weights"]:
            raise ValueError("GLB indexed weights differ from actual Blender evidence")
    selected_joints, selected_weights, selected = resolve_weights(mapping["source_vertex_to_returned_vertices"], raw["JOINTS_0"], raw["WEIGHTS_0"], len(source["POSITION"]))
    snapshot = audit_tool.source_snapshot(source)
    raw_snapshot = audit_tool.source_snapshot(raw)
    raw_snapshot["positions"] = raw_physical
    identity_fit = {"rotation": np.eye(3), "uniform_scale": 1, "translation_m": np.zeros(3)}
    recomputed, triangles = audit_tool.triangle_mapping(snapshot, raw_snapshot, identity_fit)
    if {str(index): sorted(values) for index, values in recomputed.items()} != mapping["source_vertex_to_returned_vertices"]:
        raise ValueError("Complete triangle correspondence changed")
    source_error = float(np.linalg.norm(snapshot["positions"] - raw_physical[selected], axis=1).max())
    if source_error > TOLERANCE_M:
        raise ValueError("Source-to-actual-rig physical surface exceeds3micrometres")
    gltf_frame = np.eye(4)
    gltf_frame[:3, :3] = BASIS.T @ rotation @ BASIS * scale
    gltf_frame[:3, 3] = BASIS.T @ translation
    unscale = np.diag((1 / scale, 1 / scale, 1 / scale, 1))
    physical_worlds = {index: gltf_frame @ raw_worlds[index] @ unscale for index in joints}
    document, binary = deepcopy(source_doc), bytearray(source_binary)
    node_map = {old: position + 1 for position, old in enumerate(joints)}
    roots = []
    for index in joints:
        parent = parents.get(index)
        matrix = np.linalg.inv(physical_worlds[parent]) @ physical_worlds[index] if parent in physical_worlds else physical_worlds[index]
        node = {"name": raw_doc["nodes"][index]["name"], "matrix": matrix.T.reshape(-1).tolist()}
        children = [node_map[child] for child in raw_doc["nodes"][index].get("children", []) if child in node_map]
        if children:
            node["children"] = children
        if parent not in physical_worlds:
            roots.append(node_map[index])
        document["nodes"].append(node)
    if len(roots) != 1:
        raise ValueError("Expected one actual joint root")
    inverse = np.array([np.linalg.inv(physical_worlds[index]) for index in joints], dtype="<f4")
    attrs = document["meshes"][0]["primitives"][0]["attributes"]
    attrs["JOINTS_0"] = append_accessor(document, binary, selected_joints, "VEC4", 5121)
    attrs["WEIGHTS_0"] = append_accessor(document, binary, selected_weights, "VEC4", 5126)
    inverse_accessor = append_accessor(document, binary, inverse, "MAT4", 5126)
    document["skins"] = [{"name": "Mammoth_Actual33Bone_UnchangedHierarchy", "joints": [node_map[index] for index in joints], "skeleton": roots[0], "inverseBindMatrices": inverse_accessor}]
    document["nodes"][0]["skin"] = 0
    document["scenes"][0]["nodes"] = [0] + roots
    bind_matrices = np.array([physical_worlds[index] @ inv for index, inv in zip(joints, inverse)])
    rest = skin_positions(source["POSITION"], selected_joints, selected_weights, bind_matrices)
    rest_error = float(np.linalg.norm(rest - source["POSITION"], axis=1).max())
    if rest_error > TOLERANCE_M or not np.all(selected_weights.sum(axis=1) > .99999):
        raise ValueError("Physical inversebind/rest skin gate failed")
    source_native, split_pairs, native = audit_tool.texture.native_identity(source)
    split = audit_tool.texture.split_identity(source_native, split_pairs, {index: {index} for index in source_native})
    if not split["all_native_identities_preserved"]:
        raise ValueError("Source23split evidence failed")
    regions = spatial_regions(snapshot["positions"])
    buckle_regions = {}
    for patch in native["plan"]["accessory_patches"]:
        polygons = set(patch["face_indices"])
        indices = sorted({int(vertex) for face, triangle in enumerate(source["indices"]) if native["source_triangle_native_polygons"][face] in polygons for vertex in triangle})
        buckle_regions[str(patch["patch_root"])] = indices
    report = {"status": "retained_surface_skin_candidate_prepared_actual_motion_not_run", "source": audit_tool.texture.core.record(SOURCE),
              "received": audit_tool.texture.core.record(RECEIVED), "raw_index_to_actual_blender_max_error_m": audit_index_error,
              "raw_skin_rest_max_error_m": float(np.linalg.norm(raw_rest - raw["POSITION"], axis=1).max()),
              "source_to_actual_rig_max_error_m": source_error, "candidate_inversebind_rest_max_error_m": rest_error,
              "complete_triangles": len(triangles), "render_vertices": len(source["POSITION"]), "bones": len(joints),
              "parent_changes": 0, "weight_averaging": False, "weights_changed": False, "split_identity": split,
              "source_geometry_accessors_unchanged": True, "original_binary_prefix_retained_bytes": len(source_binary),
              "original_materials_images_unchanged": document["materials"] == source_doc["materials"] and document["images"] == source_doc["images"],
              "original_texture_payloads": audit_tool.texture.image_audit(source_doc, source_binary, decode=False),
              "joint_world_matrices_gltf_m": {raw_doc["nodes"][index]["name"]: physical_worlds[index].tolist() for index in joints},
              "regions": regions, "buckle_regions": buckle_regions, "poses": POSES,
              "rig_approved": False, "gait_approved": False, "production_approved": False}
    return encode(document, binary), report


def spatial_regions(points):
    regions = {}
    for xsign in (-1, 1):
        for ysign in (-1, 1):
            regions[f"x{xsign}_y{ysign}"] = np.flatnonzero((points[:, 2] < .12) & (points[:, 0] * xsign > 0) & (points[:, 1] * ysign > .1)).tolist()
    regions["trunk_tip"] = np.flatnonzero((points[:, 0] > .85) & (abs(points[:, 1]) < .13) & (points[:, 2] < .30)).tolist()
    regions["tail_tip"] = np.flatnonzero((points[:, 0] < -1.02) & (abs(points[:, 1]) < .16) & (points[:, 2] > .6)).tolist()
    if any(not indices for indices in regions.values()):
        raise ValueError("An anatomical spatial probe is empty")
    return regions


def rigid_residual(before, after):
    before_center, after_center = before.mean(axis=0), after.mean(axis=0)
    left, _, right = np.linalg.svd((before - before_center).T @ (after - after_center))
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(left @ right)
    rotation = left @ correction @ right
    errors = np.linalg.norm((before - before_center) @ rotation + after_center - after, axis=1)
    before_distance = np.linalg.norm(before[:, None] - before[None], axis=2)
    after_distance = np.linalg.norm(after[:, None] - after[None], axis=2)
    selected = before_distance > 1e-5
    return {"vertices": len(before), "best_rigid_fit_max_residual_m": float(errors.max()), "best_rigid_fit_rms_m": float(np.sqrt(np.mean(errors ** 2))),
            "max_pair_distance_change_m": float(np.max(abs(after_distance - before_distance))),
            "max_pair_relative_strain": float(np.max(abs(after_distance[selected] / before_distance[selected] - 1)))}


def fresh_output(path):
    path = path.resolve()
    if path.parent != BRANCH.resolve() or not path.name.startswith("rig_transfer_"):
        raise ValueError("Output must be a new owned rig_transfer_* directory")
    if path.exists():
        raise FileExistsError("Preserve earlier transfer evidence")
    return path


def prepare(output):
    payload, report = make_candidate()
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "Mount_Mammoth_skin_candidate.glb"
    candidate.write_bytes(payload)
    document, binary = read_container(candidate)
    source_doc, source_binary = read_container(SOURCE)
    source = source_arrays(source_doc, source_binary)
    actual = source_arrays(document, binary)
    if any(not np.array_equal(source[name], actual[name]) for name in source):
        raise ValueError("Candidate changed retained source attributes")
    if binary[:len(source_binary)] != source_binary:
        raise ValueError("Original binary prefix changed")
    report["candidate"] = audit_tool.texture.core.record(candidate)
    audit_tool.texture.core.save(output / "preparation.json", report)
    dependencies = list(FROZEN) + [candidate, output / "preparation.json", Path(__file__), Path(audit_tool.__file__),
                                  Path(audit_tool.texture.__file__), Path(audit_tool.rig_core.__file__), Path(audit_tool.texture.core.__file__)]
    future = output / "actual_diagnostic_01"
    spec = {"status": "frozen_waiting_root_exclusive_blender_lease", "candidate": report["candidate"], "preparation": audit_tool.texture.core.record(output / "preparation.json"),
            "frozen_inputs": [audit_tool.texture.core.record(path) for path in dependencies],
            "restrictions": {"blender_threads": 2, "priority": "BelowNormal", "renders": 0, "paid_calls": 0, "ue_calls": 0, "model_reexports": 0, "reparent": 0, "weight_edits": 0},
            "gates": {"rest_and_full_surface_tolerance_m": TOLERANCE_M, "source_normals_uv_indices_position_payloads": "exact", "native_split_pairs": 23, "unique_actual_bones": 33},
            "diagnostic_poses": POSES, "scope": "Actual independent8limited poses; measure all four spatial feet and four rigid-buckle residuals. Not gait/rig approval. No fixes in this first batch.",
            "command": {"executable": "C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe",
                        "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "diagnose", "--spec", str(output / "execution_spec.json"), "--output", str(future)]}}
    audit_tool.texture.core.save(output / "execution_spec.json", spec)
    print(json.dumps({"candidate": report["candidate"], "spec": str(output / "execution_spec.json"), "rest_error_m": report["candidate_inversebind_rest_max_error_m"], "split_pairs": report["split_identity"]["retained_split_pairs"]}))


def diagnose(output, spec_path):
    import bpy
    from mathutils import Matrix, Quaternion, Vector

    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    for record in spec["frozen_inputs"]:
        audit_tool.texture.checked_record(record)
    if output.exists() or output.resolve() != spec_path.parent.resolve() / "actual_diagnostic_01":
        raise ValueError("Expected fresh frozen diagnostic output")
    preparation = json.loads(Path(spec["preparation"]["path"]).read_text(encoding="utf-8-sig"))
    candidate = Path(spec["candidate"]["path"])
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "started_not_approved", "process_id": __import__("os").getpid(), "candidate": spec["candidate"], "poses": [],
              "source_modified": False, "reparented": False, "weights_edited": False, "model_reexported": False, "rig_approved": False, "production_approved": False}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(candidate), merge_vertices=False, disable_bone_shape=True)
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
        if len(meshes) != 1 or len(rigs) != 1 or len(rigs[0].data.bones) != 33:
            raise ValueError("Actual skin/armature/bone count mismatch")
        body, armature = meshes[0], rigs[0]
        bpy.context.view_layer.update()
        snapshot = audit_tool.rig_core.mesh_snapshot(body)
        expected = audit_tool.source_snapshot(source_arrays(*read_container(SOURCE)))
        if not np.array_equal(snapshot["triangles"], expected["triangles"]):
            raise ValueError("Actual import reordered surface triangle indices")
        source_error = float(np.linalg.norm(snapshot["positions"] - expected["positions"], axis=1).max())

        def evaluate():
            bpy.context.view_layer.update()
            evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices])
            evaluated.to_mesh_clear()
            return points

        baseline = evaluate()
        rest_error = float(np.linalg.norm(baseline - expected["positions"], axis=1).max())
        joint_errors = []
        for name, matrix in preparation["joint_world_matrices_gltf_m"].items():
            head = np.array(armature.matrix_world @ armature.data.bones[name].head_local)
            joint_errors.append(float(np.linalg.norm(head - BASIS @ np.array(matrix)[:3, 3])))
        report["actual_rest"] = {"vertices": len(baseline), "triangles": len(snapshot["triangles"]), "bones": len(armature.data.bones),
                                 "source_surface_max_error_m": source_error, "skin_rest_max_error_m": rest_error, "joint_head_max_error_m": max(joint_errors),
                                 "max_blender_decoded_normal_difference": float(np.linalg.norm(snapshot["normals"] - expected["normals"], axis=1).max()),
                                 "max_uv_difference": float(np.linalg.norm(snapshot["uv"] - expected["uv"], axis=1).max()),
                                 "armature_matrix_world": [list(row) for row in armature.matrix_world], "armature_scale": list(armature.scale)}
        if max(source_error, rest_error, max(joint_errors)) > TOLERANCE_M:
            raise ValueError("Actual source/rest/inversebind joint gate exceeds3micrometres")
        report["materials"] = audit_tool.rig_core.materials_report(meshes)
        original_basis = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
        for command in spec["diagnostic_poses"]:
            for bone in armature.pose.bones:
                bone.matrix_basis = original_basis[bone.name].copy()
            bpy.context.view_layer.update()
            if float(np.linalg.norm(evaluate() - baseline, axis=1).max()) > TOLERANCE_M:
                raise ValueError("Independent pose baseline did not restore")
            pose_bone = armature.pose.bones[command["bone"]]
            world = armature.matrix_world @ pose_bone.matrix
            head = world.translation.copy()
            turn = Quaternion(Vector(command["axis_world"]), math.radians(command["degrees"])).to_matrix().to_4x4()
            target = Matrix.Translation(head) @ turn @ Matrix.Translation(-head) @ world
            pose_bone.matrix = armature.matrix_world.inverted() @ target
            points = evaluate()
            delta = np.linalg.norm(points - baseline, axis=1)
            regions = {name: {"vertices": len(indices), "mean_displacement_m": float(delta[indices].mean()), "max_displacement_m": float(delta[indices].max()),
                              "centroid_displacement_m": (points[indices].mean(axis=0) - baseline[indices].mean(axis=0)).tolist(), "minimum_world_z_m": float(points[indices, 2].min())}
                       for name, indices in preparation["regions"].items()}
            buckles = {name: rigid_residual(baseline[indices], points[indices]) for name, indices in preparation["buckle_regions"].items()}
            report["poses"].append({"command": command, "actual_bone_world_matrix": [list(row) for row in armature.matrix_world @ pose_bone.matrix],
                                    "maximum_surface_displacement_m": float(delta.max()), "spatial_regions": regions, "buckle_nonrigidity": buckles})
            audit_tool.texture.core.save(output / "diagnostic.json", report)
        for bone in armature.pose.bones:
            bone.matrix_basis = original_basis[bone.name].copy()
        restored = evaluate()
        report["final_rest_max_error_m"] = float(np.linalg.norm(restored - baseline, axis=1).max())
        if report["final_rest_max_error_m"] > TOLERANCE_M:
            raise ValueError("Final rest restore failed")
        for record in spec["frozen_inputs"]:
            audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
        report["status"] = "actual_independent_pose_diagnostics_complete_not_deformation_approval"
    except Exception as error:
        report["status"] = "failed_preserved_no_automatic_retry"
        report["error"] = str(error)
        audit_tool.texture.core.save(output / "diagnostic.json", report)
        raise
    audit_tool.texture.core.save(output / "diagnostic.json", report)
    print(json.dumps({"status": report["status"], "poses": len(report["poses"]), "rest": report["actual_rest"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "diagnose"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare(fresh_output(args.output))
    elif args.spec:
        diagnose(args.output.resolve(), args.spec.resolve())
    else:
        raise ValueError("Actual diagnosis requires frozen spec")


if __name__ == "__main__":
    main()
