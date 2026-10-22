"""Preserve the failed numeric candidate and prepare an unapproved actual visual diagnostic."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimize_mammoth_buckle_weights as optimizer


transfer = optimizer.transfer
core = transfer.audit_tool.texture.core
MODEL = optimizer.accessory.MODEL
FEASIBILITY = transfer.BRANCH / "rig_follower_feasibility_01/feasibility.json"
FEASIBILITY_SHA = "9b5b7c2bc451c8de313f59429a0397386c812529797ce36c285374145646cd55"
EXACT_REGIONS = transfer.BRANCH / "rig_weight_plan_01/exact_regions.json"
INTERSECTION_TOLERANCE_M = 1e-7
AREA_TOLERANCE_M2 = 1e-12


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def pack_weight_row(row, names):
    if not row or len(row) > 4 or any(not np.isfinite(value) or value <= 0 for value in row.values()):
        raise ValueError("Expected one to four finite positive influences")
    if abs(sum(row.values()) - 1) > 1e-7:
        raise ValueError("Frozen proposed weights are not normalized")
    selected = sorted(row, key=lambda name: names.index(name))
    joints = np.zeros(4, dtype=np.uint8)
    weights = np.zeros(4, dtype=np.float32)
    for column, name in enumerate(selected):
        joints[column], weights[column] = names.index(name), row[name]
    if abs(float(weights.sum()) - 1) > 2e-7:
        raise ValueError("Float32 conversion loses weight normalization")
    return joints, weights


def build_candidate():
    if core.record(MODEL)["sha256"] != optimizer.accessory.MODEL_SHA or core.record(FEASIBILITY)["sha256"] != FEASIBILITY_SHA:
        raise ValueError("Frozen parent-only model or failed feasibility changed")
    feasibility = read_json(FEASIBILITY)
    if feasibility["both_regions_strict_numeric_feasible"] or feasibility["fit_policies_tried"] != 1:
        raise ValueError("Expected the exact single failed follower policy")
    original, original_binary = transfer.read_container(MODEL)
    document, binary = deepcopy(original), bytearray(original_binary)
    arrays = transfer.source_arrays(original, original_binary)
    native_map, _, _ = transfer.audit_tool.texture.native_identity(arrays)
    masks = read_json(optimizer.MASK_PLAN)
    worlds, _ = transfer.world_matrices(original)
    skin = document["skins"][0]
    old_joints = list(skin["joints"])
    if len(old_joints) != 33 or original.get("animations"):
        raise ValueError("Expected exact existing thirty-three bones without clips")
    names = [document["nodes"][index]["name"] for index in old_joints]
    parent = old_joints[names.index("tripo::Spine_3")]
    original_inverse = transfer.accessor(original, original_binary, skin["inverseBindMatrices"])
    inverse = list(original_inverse)
    proposed_joints, proposed_weights = arrays["JOINTS_0"].copy(), arrays["WEIGHTS_0"].copy()
    changes = {}
    for region in feasibility["regions"]:
        name = "derived_buckle_" + str(region["patch"])
        rest = np.array(region["derived_bone_rest_matrix_gltf_m"])
        local = np.linalg.inv(worlds[parent]) @ rest
        node = len(document["nodes"])
        document["nodes"].append({"name": name, "matrix": local.T.reshape(-1).tolist()})
        document["nodes"][parent].setdefault("children", []).append(node)
        skin["joints"].append(node)
        inverse.append(np.linalg.inv(rest))
        names.append(name)
        mask = next(item for item in masks["regions"] if item["native_patch"] == region["patch"])
        approved_native = {int(index) for index in mask["outer12cm_native_geodesic_distances_m"]}
        proposed_native = {}
        for row in region["sparse_native_weights_not_applied"]:
            if row["native_vertex"] not in approved_native:
                raise ValueError("Proposed weight exceeds the reviewed cloth support")
            proposed_native[row["native_vertex"]] = row["proposed_weights_not_applied"]
        metal = set(mask["metal_render_vertices"])
        for render, native in native_map.items():
            row = {name: 1.} if render in metal else proposed_native.get(native)
            if row is None:
                continue
            if render in changes:
                raise ValueError("The two local buckle regions overlap")
            proposed_joints[render], proposed_weights[render] = pack_weight_row(row, names)
            changes[render] = {"patch": region["patch"], "native": native, "metal": render in metal}
    primitive = document["meshes"][0]["primitives"][0]
    primitive["attributes"]["JOINTS_0"] = transfer.append_accessor(document, binary, proposed_joints, "VEC4", 5121)
    primitive["attributes"]["WEIGHTS_0"] = transfer.append_accessor(document, binary, proposed_weights, "VEC4", 5126)
    skin["inverseBindMatrices"] = transfer.append_accessor(document, binary, np.array(inverse), "MAT4", 5126)
    skin["name"] = "Mammoth35_UnapprovedFollowerVisualDiagnostic"
    document.setdefault("extras", {})["diagnostic_approval"] = {"production": False, "rig": False, "historical_per_edge_strain_gate": "FAIL", "source_policy_sha256": FEASIBILITY_SHA}
    after_worlds, _ = transfer.world_matrices(document)
    world_error = max(float(np.max(abs(after_worlds[index] - worlds[index]))) for index in old_joints)
    rest_points = transfer.skin_positions(arrays["POSITION"], proposed_joints, proposed_weights, np.array([after_worlds[index] for index in skin["joints"]]) @ np.array(inverse))
    rest_error = float(np.linalg.norm(rest_points - arrays["POSITION"], axis=1).max())
    if world_error > 1e-12 or rest_error > transfer.TOLERANCE_M or not np.array_equal(np.array(inverse)[:33], original_inverse):
        raise ValueError("Existing rest, inverse binds, or retained surface changed")
    changed = sorted(changes)
    affected = np.flatnonzero(np.any(np.isin(arrays["indices"], changed), axis=1)).tolist()
    report = {"status": "unapproved_visual_diagnostic_candidate_only", "source": core.record(MODEL), "frozen_failed_policy": core.record(FEASIBILITY),
              "existing_bones": 33, "added_bones": 2, "candidate_bones": 35, "original_binary_prefix_bytes_retained": len(original_binary),
              "existing_world_rest_max_matrix_error": world_error, "numeric_skin_rest_max_error_m": rest_error, "existing_inversebind_rows_exact": True,
              "changed_render_vertices": changed, "change_regions": changes, "affected_triangles": affected, "new_animation_clips": 0,
              "historical_per_edge_strain_gate": "FAIL", "production_approved": False, "weight_application_approved": False}
    return transfer.encode(document, binary), report


def prepare(output):
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_follower_visual_"):
        raise ValueError("Use a fresh owned visual-diagnostic directory")
    payload, report = build_candidate()
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "Mount_Mammoth_follower_diagnostic.glb"
    candidate.write_bytes(payload)
    before_doc, before_bin = transfer.read_container(MODEL)
    after_doc, after_bin = transfer.read_container(candidate)
    before, after = transfer.source_arrays(before_doc, before_bin), transfer.source_arrays(after_doc, after_bin)
    exact = {key: np.array_equal(before[key], after[key]) for key in ("POSITION", "NORMAL", "TEXCOORD_0", "indices")}
    if not all(exact.values()) or before_bin != after_bin[:len(before_bin)] or any(before_doc.get(key) != after_doc.get(key) for key in ("images", "textures", "materials")):
        raise ValueError("Retained source surface or original PBR bytes changed")
    native_map, pairs, _ = transfer.audit_tool.texture.native_identity(after)
    if len(pairs) != 23:
        raise ValueError("Expected all twenty-three cleaned splits")
    report.update({"candidate": core.record(candidate), "retained_surface_accessors_exact": exact, "retained_native_splits": len(pairs), "original_PBR_bytes_exact": True})
    core.save(output / "preparation.json", report)
    dependencies = [MODEL, FEASIBILITY, EXACT_REGIONS, optimizer.MASK_PLAN, optimizer.MASK_REVIEW, transfer.MAPPING, candidate, output / "preparation.json",
                    Path(__file__), Path(optimizer.__file__), Path(optimizer.accessory.__file__), Path(transfer.__file__), Path(transfer.audit_tool.__file__),
                    Path(transfer.audit_tool.texture.__file__), Path(transfer.audit_tool.texture.native_reader.__file__), Path(transfer.audit_tool.rig_core.__file__), Path(core.__file__),
                    transfer.audit_tool.texture.CLEANUP, transfer.audit_tool.texture.APPROVAL, transfer.audit_tool.texture.NORMALIZATION, Path(__file__).parent / "prepare_tripo_character.py"]
    spec = {"status": "frozen_waiting_root_exclusive_lease_not_approved", "candidate": core.record(candidate), "preparation": core.record(output / "preparation.json"),
            "baseline": core.record(MODEL), "feasibility": core.record(FEASIBILITY), "exact_regions": core.record(EXACT_REGIONS), "mask_plan": core.record(optimizer.MASK_PLAN),
            "frozen_inputs": [core.record(path) for path in dependencies], "root_authorization": "One actual visual diagnostic of the exact existing failed follower candidate. Preserve the historical per-edge FAIL. No further weight search. Four views maximum. No UE, production or full-clip approval.",
            "restrictions": {"threads": 2, "priority": "BelowNormal", "renders": 4, "size": 512, "samples": 8, "paid_calls": 0, "UE_calls": 0, "source_edits": 0, "Blender_model_reexports": 0},
            "diagnostic_poses": transfer.POSES, "animation": {"actions": 8, "frames_each": [1, 2], "interpolation": "CONSTANT", "frame1": "rest", "frame2": "one existing limited target pose", "new_bones_keyed": True, "constraint_count": 0, "full_gameplay_clips": False},
            "gates": {"retained_rest_source_and_actual_prediction_tolerance_m": transfer.TOLERANCE_M, "metal_rigidity_and_seam_tolerance_m": transfer.TOLERANCE_M,
                      "historical_per_edge_strain": "Always report unchanged old FAIL; not rewritten as PASS by this visual-stage authorization",
                      "new_face_normal_reversals": 0, "new_degenerate_faces": 0, "new_proper_triangle_intersections": 0, "intersection_tolerance_m": INTERSECTION_TOLERANCE_M,
                      "coplanar_overlap_area_tolerance_m2": AREA_TOLERANCE_M2, "intersection_scope": "All changed-vertex triangles against the complete retained mesh, compared with the same actual baseline pose; intended edge/point touching is not a proper intersection"},
            "command": {"executable": "C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe",
                        "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(output / "execution_spec.json"), "--output", str(output / "actual_visual_01")]}}
    core.save(output / "execution_spec.json", spec)
    print(json.dumps({"candidate": report["candidate"], "spec": core.record(output / "execution_spec.json"), "changed_vertices": len(report["changed_render_vertices"]), "affected_triangles": len(report["affected_triangles"])}))


def clipped_triangle_area(first, second):
    normal = np.cross(first[1] - first[0], first[2] - first[0])
    keep = [axis for axis in range(3) if axis != int(np.argmax(abs(normal)))]
    polygon, clip = first[:, keep].copy().tolist(), second[:, keep]
    cross2 = lambda first_vector, second_vector: first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0]
    sign = 1 if cross2(clip[1] - clip[0], clip[2] - clip[0]) >= 0 else -1
    for edge in range(3):
        start, end = clip[edge], clip[(edge + 1) % 3]
        remaining = []
        for index in range(len(polygon)):
            previous, current = np.array(polygon[index - 1]), np.array(polygon[index])
            distance_previous = sign * cross2(end - start, previous - start)
            distance_current = sign * cross2(end - start, current - start)
            if (distance_previous >= 0) != (distance_current >= 0):
                remaining.append((previous + (current - previous) * distance_previous / (distance_previous - distance_current)).tolist())
            if distance_current >= 0:
                remaining.append(current.tolist())
        polygon = remaining
    if len(polygon) < 3:
        return 0.
    points = np.array(polygon)
    projected = abs(sum(cross2(points[index], points[(index + 1) % len(points)]) for index in range(len(points)))) / 2
    return float(projected * np.linalg.norm(normal) / max(abs(normal[int(np.argmax(abs(normal)))]), 1e-30))


def proper_triangle_intersection(first, second, tolerance=INTERSECTION_TOLERANCE_M):
    first_normal = np.cross(first[1] - first[0], first[2] - first[0])
    second_normal = np.cross(second[1] - second[0], second[2] - second[0])
    first_size, second_size = np.linalg.norm(first_normal), np.linalg.norm(second_normal)
    if min(first_size, second_size) <= AREA_TOLERANCE_M2:
        return False
    first_unit, second_unit = first_normal / first_size, second_normal / second_size
    first_distances = (second - first[0]) @ first_unit
    second_distances = (first - second[0]) @ second_unit
    if (np.all(first_distances > tolerance) or np.all(first_distances < -tolerance) or np.all(second_distances > tolerance) or np.all(second_distances < -tolerance)):
        return False
    if max(abs(first_distances)) <= tolerance and max(abs(second_distances)) <= tolerance:
        return clipped_triangle_area(first, second) > AREA_TOLERANCE_M2
    for edges, triangle, unit in ((first, second, second_unit), (second, first, first_unit)):
        for index in range(3):
            start, end = edges[index], edges[(index + 1) % 3]
            start_distance, end_distance = (start - triangle[0]) @ unit, (end - triangle[0]) @ unit
            if start_distance * end_distance >= 0 or min(abs(start_distance), abs(end_distance)) <= tolerance:
                continue
            fraction = start_distance / (start_distance - end_distance)
            point = start + fraction * (end - start)
            edge_first, edge_second, relative = triangle[1] - triangle[0], triangle[2] - triangle[0], point - triangle[0]
            gram = np.array([[edge_first @ edge_first, edge_first @ edge_second], [edge_first @ edge_second, edge_second @ edge_second]])
            barycentric = np.linalg.solve(gram, [relative @ edge_first, relative @ edge_second])
            if min(barycentric[0], barycentric[1], 1 - sum(barycentric)) > tolerance / max(np.linalg.norm(edge_first), np.linalg.norm(edge_second)):
                return True
    return False


def face_changes(before, after, triangles, affected):
    baseline = before[triangles[affected]]
    candidate = after[triangles[affected]]
    normal_before = np.cross(baseline[:, 1] - baseline[:, 0], baseline[:, 2] - baseline[:, 0])
    normal_after = np.cross(candidate[:, 1] - candidate[:, 0], candidate[:, 2] - candidate[:, 0])
    size_before, size_after = np.linalg.norm(normal_before, axis=1), np.linalg.norm(normal_after, axis=1)
    stable = size_before > AREA_TOLERANCE_M2
    reversed_mask = stable & (np.sum(normal_before * normal_after, axis=1) < 0)
    collapsed = stable & (size_after <= AREA_TOLERANCE_M2)
    return {"normal_reversed_triangles": np.asarray(affected)[reversed_mask].tolist(), "new_degenerate_triangles": np.asarray(affected)[collapsed].tolist(),
            "minimum_area_ratio_on_nondegenerate_baseline": float(min(size_after[stable] / size_before[stable]))}


def intersection_pairs(points, triangles, affected):
    from mathutils.bvhtree import BVHTree
    whole = BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True, epsilon=INTERSECTION_TOLERANCE_M)
    local = BVHTree.FromPolygons(points.tolist(), triangles[affected].tolist(), all_triangles=True, epsilon=INTERSECTION_TOLERANCE_M)
    broad = {tuple(sorted((affected[local_index], global_index))) for local_index, global_index in local.overlap(whole) if affected[local_index] != global_index}
    return {pair for pair in broad if proper_triangle_intersection(points[triangles[pair[0]]], points[triangles[pair[1]]])}


def import_rig(path, expected_bones):
    import bpy
    previous = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=False, disable_bone_shape=True, bone_heuristic="BLENDER")
    added = set(bpy.data.objects) - previous
    bodies, rigs = [item for item in added if item.type == "MESH"], [item for item in added if item.type == "ARMATURE"]
    if len(bodies) != 1 or len(rigs) != 1 or len(rigs[0].data.bones) != expected_bones:
        raise ValueError("Actual skin, armature or bone-count mismatch")
    return bodies[0], rigs[0]


def evaluate(body):
    import bpy
    bpy.context.view_layer.update()
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices])
    evaluated.to_mesh_clear()
    return points


def reset_pose(rig, bases):
    import bpy
    if rig.animation_data:
        rig.animation_data.action = None
    for bone in rig.pose.bones:
        bone.matrix_basis = bases[bone.name].copy()
        bone.rotation_mode = "QUATERNION"
    bpy.context.view_layer.update()


def apply_command(rig, command):
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    bone = rig.pose.bones[command["bone"]]
    world = rig.matrix_world @ bone.matrix
    turn = Quaternion(Vector(command["axis_world"]), math.radians(command["degrees"])).to_matrix().to_4x4()
    bone.matrix = rig.matrix_world.inverted() @ Matrix.Translation(world.translation) @ turn @ Matrix.Translation(-world.translation) @ world
    bpy.context.view_layer.update()


def bake_action(rig, command, feasibility, bases, rest_world):
    import bpy
    from mathutils import Matrix
    reset_pose(rig, bases)
    rig.animation_data_create()
    action = bpy.data.actions.new("Mammoth_Diagnostic_" + command["name"])
    action.use_fake_user = True
    rig.animation_data.action = action
    for frame in (1, 2):
        bpy.context.scene.frame_set(frame)
        if frame == 2:
            apply_command(rig, command)
            for region in feasibility["regions"]:
                fitted = next(pose for pose in region["pose_fits"] if pose["pose"] == command["name"])
                delta = np.array(fitted["follower_world_matrix_gltf_m"]) @ np.linalg.inv(region["derived_bone_rest_matrix_gltf_m"])
                basis = np.eye(4)
                basis[:3, :3] = transfer.BASIS
                blender_delta = Matrix((basis @ delta @ basis.T).tolist())
                name = "derived_buckle_" + str(region["patch"])
                rig.pose.bones[name].matrix = rig.matrix_world.inverted() @ blender_delta @ rest_world[name]
                bpy.context.view_layer.update()
        for bone in rig.pose.bones:
            for data_path in ("location", "rotation_quaternion", "scale"):
                bone.keyframe_insert(data_path=data_path, frame=frame)
    slot = rig.animation_data.action_slot
    if slot is None:
        raise ValueError("Real diagnostic animation slot was not created")
    curves = [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves]
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT"
    if len(curves) != 350 or sum(len(curve.keyframe_points) for curve in curves) != 700:
        raise ValueError("Expected thirty-five bones with real two-frame TRS animation channels")
    if any(bone.constraints for bone in rig.pose.bones):
        raise ValueError("Constraints may not substitute for real keyed follower motion")
    return action, slot, {"name": action.name, "slot": slot.identifier, "fcurves": len(curves), "keyframes": 700, "constraint_count": 0, "frames": [1, 2], "interpolation": "CONSTANT"}


def actual_strain_rows(before, after, rest, triangles, native_map, region):
    metal = set(region["metal_render_vertices"])
    support_native = {int(index) for index in region["outer12cm_native_geodesic_distances_m"]}
    selected = [triangle for triangle in triangles if any(native_map[int(index)] in support_native for index in triangle) and not any(int(index) in metal for index in triangle)]
    native_pairs = sorted({tuple(sorted((native_map[int(first)], native_map[int(second)]))) for triangle in selected for first, second in zip(triangle, np.roll(triangle, -1)) if native_map[int(first)] != native_map[int(second)]})
    representatives = {}
    for render, native in native_map.items():
        representatives.setdefault(native, render)
    first = np.array([representatives[pair[0]] for pair in native_pairs])
    second = np.array([representatives[pair[1]] for pair in native_pairs])
    lengths = np.linalg.norm(rest[second] - rest[first], axis=1)
    valid = lengths > 1e-6
    baseline = np.linalg.norm(before[second] - before[first], axis=1)[valid] / lengths[valid] - 1
    candidate = np.linalg.norm(after[second] - after[first], axis=1)[valid] / lengths[valid] - 1
    metric = optimizer.metric_rows(candidate[None, :], baseline[None, :], lengths[valid])[0]
    metric.pop("pose")
    metric["all_edges"] = [{"native_vertices": pair, "rest_length_m": float(length), "baseline_strain": float(original), "candidate_strain": float(actual), "old_gate_failed": bool(abs(actual) > abs(original) + optimizer.STRAIN_NUMERIC_TOLERANCE)}
                           for pair, length, original, actual in zip(np.array(native_pairs)[valid].tolist(), lengths[valid], baseline, candidate)]
    return metric


def run(output, spec_path):
    import bpy
    import prepare_tripo_character as renderer
    spec = read_json(spec_path)
    for record in spec["frozen_inputs"]:
        transfer.audit_tool.texture.checked_record(record)
    if output.exists() or output.resolve() != spec_path.parent.resolve() / "actual_visual_01":
        raise ValueError("Expected fresh frozen actual diagnostic output")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "started_unapproved_diagnostic", "process_id": __import__("os").getpid(), "poses": [], "images": [], "historical_per_edge_strain_gate": "FAIL", "production_approved": False, "runtime_approved": False}
    try:
        preparation, feasibility, masks, exact = (read_json(spec[name]["path"]) for name in ("preparation", "feasibility", "mask_plan", "exact_regions"))
        document, binary = transfer.read_container(spec["candidate"]["path"])
        arrays = transfer.source_arrays(document, binary)
        native_map, _, _ = transfer.audit_tool.texture.native_identity(arrays)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        baseline_body, baseline_rig = import_rig(spec["baseline"]["path"], 33)
        body, rig = import_rig(spec["candidate"]["path"], 35)
        baseline_body.hide_render = True
        before = transfer.audit_tool.rig_core.mesh_snapshot(baseline_body)
        actual = transfer.audit_tool.rig_core.mesh_snapshot(body)
        for attribute in ("triangles", "uv", "normals"):
            if not np.array_equal(before[attribute], actual[attribute]):
                raise ValueError("Actual candidate changes decoded " + attribute)
        baseline_rest, rest = evaluate(baseline_body), evaluate(body)
        source = arrays["POSITION"] @ transfer.BASIS.T
        rest_error = max(float(np.linalg.norm(rest - baseline_rest, axis=1).max()), float(np.linalg.norm(rest - source, axis=1).max()))
        if rest_error > transfer.TOLERANCE_M:
            raise ValueError("Actual retained surface/rest exceeds three micrometres")
        bases = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
        baseline_bases = {bone.name: bone.matrix_basis.copy() for bone in baseline_rig.pose.bones}
        rest_world = {bone.name: (rig.matrix_world @ bone.matrix).copy() for bone in rig.pose.bones}
        original_bone_error = max(float(np.max(abs(np.array(baseline_rig.matrix_world @ bone.matrix) - np.array(rest_world[bone.name])))) for bone in baseline_rig.pose.bones)
        if original_bone_error > transfer.TOLERANCE_M:
            raise ValueError("An existing bone's actual rest changed")
        report["rest"] = {"surface_error_m": rest_error, "existing_bone_matrix_error": original_bone_error, "bones": 35, "surface_vertices": len(rest), "triangles": len(arrays["indices"]), "UV_corner_normals_indices_exact_against_same_import": True}
        rest_intersections = intersection_pairs(rest, arrays["indices"], preparation["affected_triangles"])
        baseline_intersections = intersection_pairs(baseline_rest, arrays["indices"], preparation["affected_triangles"])
        report["rest_new_intersections"] = sorted(rest_intersections - baseline_intersections)
        actions = {}
        for pose_index, command in enumerate(spec["diagnostic_poses"]):
            reset_pose(baseline_rig, baseline_bases)
            apply_command(baseline_rig, command)
            baseline_points = evaluate(baseline_body)
            action, slot, action_record = bake_action(rig, command, feasibility, bases, rest_world)
            direct = evaluate(body)
            reset_pose(rig, bases)
            rig.animation_data.action, rig.animation_data.action_slot = action, slot
            bpy.context.scene.frame_set(1)
            keyed_rest_error = float(np.linalg.norm(evaluate(body) - rest, axis=1).max())
            bpy.context.scene.frame_set(2)
            points = evaluate(body)
            replay_error = float(np.linalg.norm(points - direct, axis=1).max())
            if max(keyed_rest_error, replay_error) > transfer.TOLERANCE_M:
                raise ValueError("Real keyed animation replay diverges from assigned target or rest")
            original_doc, original_binary = transfer.read_container(spec["baseline"]["path"])
            target_worlds = list(optimizer.accessory.pose_matrices(original_doc, command))
            target_worlds.extend(np.array(region["pose_fits"][pose_index]["follower_world_matrix_gltf_m"]) for region in feasibility["regions"])
            inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
            predicted = transfer.skin_positions(arrays["POSITION"], arrays["JOINTS_0"], arrays["WEIGHTS_0"], np.array(target_worlds) @ inverse) @ transfer.BASIS.T
            prediction_error = float(np.linalg.norm(points - predicted, axis=1).max())
            if prediction_error > transfer.TOLERANCE_M:
                raise ValueError("Actual keyed deformation differs from frozen follower prediction")
            before_pairs = intersection_pairs(baseline_points, arrays["indices"], preparation["affected_triangles"])
            after_pairs = intersection_pairs(points, arrays["indices"], preparation["affected_triangles"])
            row = {"pose": command["name"], "baked_action": action_record, "keyed_rest_max_error_m": keyed_rest_error, "keyed_replay_max_error_m": replay_error,
                   "actual_to_frozen_prediction_max_error_m": prediction_error, "face_changes": face_changes(baseline_points, points, arrays["indices"], preparation["affected_triangles"]),
                   "baseline_intersection_count": len(before_pairs), "candidate_intersection_count": len(after_pairs), "new_intersection_pairs": sorted(after_pairs - before_pairs), "buckles": []}
            for region in masks["regions"]:
                patch = next(item for item in exact["patches"] if item["native_patch"] == region["native_patch"])
                pairs = np.array(patch["coincident_patch_to_surrounding_pairs"])
                seam = float(np.linalg.norm(points[pairs[:, 0]] - points[pairs[:, 1]], axis=1).max())
                metal = region["metal_render_vertices"]
                rigidity = transfer.rigid_residual(rest[metal], points[metal])
                row["buckles"].append({"patch": region["native_patch"], "metal": rigidity, "maximum_coincident_seam_gap_m": seam,
                                       "actual_edge_strain": actual_strain_rows(baseline_points, points, rest, arrays["indices"], native_map, region)})
            report["poses"].append(row)
            actions[command["name"]] = (action, slot)
            core.save(output / "diagnostic.json", report)
        reset_pose(baseline_rig, baseline_bases)
        reset_pose(rig, bases)
        bpy.context.scene.world = bpy.data.worlds.new("MammothFollowerDiagnosticWorld")
        renderer.render_setup(samples=8)
        if bpy.context.scene.cycles.device != "GPU":
            raise ValueError("HIP required; no silent CPU rendering")
        for region in masks["regions"]:
            for mode in ("rest", "shoulder8"):
                reset_pose(rig, bases)
                if mode != "rest":
                    action, slot = actions[region["actual_pose"]["name"]]
                    rig.animation_data.action, rig.animation_data.action_slot = action, slot
                    bpy.context.scene.frame_set(2)
                bpy.context.view_layer.update()
                path = output / ("buckle_" + str(region["native_patch"]) + "_" + mode + ".png")
                renderer.render_view(path, [body], region["camera"]["direction"], size=512, framing=region["camera"]["framing_m"], target=region["camera"]["target"])
                report["images"].append({"patch": region["native_patch"], "pose": mode, "file": core.record(path)})
        reset_pose(rig, bases)
        scene_path = output / "Mount_Mammoth_follower_diagnostic.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
        report["saved_real_actions_scene"] = core.record(scene_path)
        report["safety_numeric_passed"] = not report["rest_new_intersections"] and all(not row["new_intersection_pairs"] and not row["face_changes"]["normal_reversed_triangles"] and not row["face_changes"]["new_degenerate_triangles"] and all(item["maximum_coincident_seam_gap_m"] <= transfer.TOLERANCE_M and item["metal"]["max_pair_distance_change_m"] <= transfer.TOLERANCE_M for item in row["buckles"]) for row in report["poses"])
        report["status"] = "actual_diagnostic_complete_requires_root_visual_review_not_approval"
        report["limitations"] = ["Historical individual-edge strain gate remains FAIL", "Eight two-frame constant diagnostic actions are real keyed bone channels, not gameplay clips or validated motion between poses", "Proper crossings and positive-area coplanar overlaps are checked locally against all triangles; contact at points or edges is intentionally excluded", "No GLB/FBX re-export, new paid task, UE import, gait or rider validation"]
        for record in spec["frozen_inputs"]:
            transfer.audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
    except Exception as error:
        report["status"], report["error"] = "failed_preserved_no_automatic_retry", str(error)
        core.save(output / "diagnostic.json", report)
        raise
    core.save(output / "diagnostic.json", report)
    print(json.dumps({"status": report["status"], "poses": len(report["poses"]), "images": len(report["images"]), "safety_numeric_passed": report["safety_numeric_passed"], "historical_per_edge_strain_gate": "FAIL"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "run"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare(args.output.resolve())
    elif args.spec:
        run(args.output.resolve(), args.spec.resolve())
    else:
        parser.error("--spec is required for a real diagnostic run")


if __name__ == "__main__":
    main()
