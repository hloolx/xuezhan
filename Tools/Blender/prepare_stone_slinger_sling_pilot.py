"""Fit the existing independent sling to the actual rig for limited pose review."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_stone_slinger_rig_transfer as transfer
import apply_stone_slinger_foot_weights as foot
import inspect_stone_slinger_rig as rig
import plan_stone_slinger_sling_grip as plan_math
import render_stone_slinger_foot_completion as framing_math
import stone_slinger_foot_math as geometry


def tube_vertices(points, radius=.008, sides=8):
    points = [Vector(point) for point in points]
    result = []
    for index, point in enumerate(points):
        tangent = (points[min(index + 1, len(points) - 1)] - points[max(index - 1, 0)]).normalized()
        reference = Vector((0, 1, 0)) if abs(tangent.y) < .9 else Vector((0, 0, 1))
        first = tangent.cross(reference).normalized()
        second = tangent.cross(first).normalized()
        result.extend(point + radius * (math.cos(angle * math.tau / sides) * first + math.sin(angle * math.tau / sides) * second) for angle in range(sides))
    return result


def append_existing_weapon(plan):
    required = {"Weapon_Sling", "grip_r", "sling_pouch", "release_point", "cord_N1", "cord_P1", "leather_pouch", "loaded_stone"}
    with bpy.data.libraries.load(plan["weapon"]["path"], link=False) as (source, target):
        if not required.issubset(source.objects):
            raise ValueError("Existing weapon lacks documented independent parts")
        target.objects = sorted(required)
    objects = list(target.objects)
    for obj in objects:
        bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    by_name = {obj.name: obj for obj in objects}
    baseline = {name: local_weapon_data(obj) for name, obj in by_name.items() if obj.type == "MESH"}
    control_rows = []
    for name in ("cord_N1", "cord_P1"):
        obj = by_name[name]
        if len(obj.data.vertices) != 88 or not obj.data.shape_keys:
            raise ValueError("Existing11ring/8side cord topology no longer matches")
        if max(abs(obj.matrix_world[row][column] - (1 if row == column else 0)) for row in range(4) for column in range(4)) > 1e-6:
            raise ValueError("Cord object transform must be explicitly accounted for")
        path = np.array(plan["terminal_path_proposal_local_m"][name])
        vertices = tube_vertices(path)
        ready = obj.shape_key_add(name="GripReady")
        for vertex, point in zip(ready.data, vertices):
            vertex.co = point
        for key in obj.data.shape_keys.key_blocks:
            key.value = 0
        ready.value = 1
        if name == "cord_P1":
            released = path.copy()
            for index in range(len(path)):
                released[index] += np.array([.07, .10, -.05]) * (1 - index / (len(path) - 1)) ** 2
            free = obj.shape_key_add(name="ReleaseTerminal")
            free.relative_key = ready
            for vertex, point in zip(free.data, tube_vertices(released)):
                vertex.co = point
            free.value = 0
            released_path = released.tolist()
        else:
            released_path = path.tolist()
        control_rows.append({"object": name, "vertices": len(vertices), "retained": name == "cord_N1",
                             "ready_path_local_m": path.tolist(), "released_path_local_m": released_path,
                             "pouch_end_unchanged": path[-1].tolist() == released_path[-1],
                             "source_Basis_Draw_retained": True})
    anchors = {}
    for name, location in (("retained_terminal", plan["terminal_path_proposal_local_m"]["cord_N1"][0]),
                           ("release_terminal", plan["terminal_path_proposal_local_m"]["cord_P1"][0])):
        anchor = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(anchor)
        anchor.parent = by_name["Weapon_Sling"]
        anchor.location = location
        anchor.empty_display_type = "SPHERE"
        anchor.empty_display_size = .009
        anchors[name] = anchor
    by_name.update(anchors)
    return by_name, baseline, control_rows


def local_weapon_data(obj):
    return {"vertices": [list(vertex.co) for vertex in obj.data.vertices],
            "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
            "uv": [[list(corner.uv) for corner in layer.data] for layer in obj.data.uv_layers],
            "materials": [material.name if material else None for material in obj.data.materials],
            "original_keys": {key.name: [list(vertex.co) for vertex in key.data]
                              for key in (obj.data.shape_keys.key_blocks if obj.data.shape_keys else [])
                              if key.name in {"Basis", "Draw"}}}


def bone_world(armature, name):
    return armature.matrix_world @ armature.pose.bones[name].matrix


def set_bone_world_rotation(armature, name, rotation):
    bone = armature.pose.bones[name]
    location = bone_world(armature, name).translation
    bone.matrix = armature.matrix_world.inverted() @ Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
    bpy.context.view_layer.update()


def aim_joint(armature, name, child_name, target):
    matrix = bone_world(armature, name)
    old_direction = (bone_world(armature, child_name).translation - matrix.translation).normalized()
    direction = (Vector(target) - matrix.translation).normalized()
    set_bone_world_rotation(armature, name, old_direction.rotation_difference(direction) @ matrix.to_quaternion())


def solve_arm(armature, side, target, pole):
    upper, lower, hand = [name + "_" + side for name in ("upperarm", "lowerarm", "hand")]
    shoulder = bone_world(armature, upper).translation
    first_length = (bone_world(armature, lower).translation - shoulder).length
    second_length = (bone_world(armature, hand).translation - bone_world(armature, lower).translation).length
    delta = Vector(target) - shoulder
    distance = min(delta.length, (first_length + second_length) * .995)
    axis = delta.normalized()
    pole_delta = Vector(pole) - shoulder
    elbow_axis = (pole_delta - axis * pole_delta.dot(axis)).normalized()
    along = (first_length ** 2 - second_length ** 2 + distance ** 2) / (2 * distance)
    elbow = shoulder + axis * along + elbow_axis * math.sqrt(max(0, first_length ** 2 - along ** 2))
    aim_joint(armature, upper, lower, elbow)
    aim_joint(armature, lower, hand, shoulder + axis * distance)
    return {"side": side, "target_m": list(target), "actual_wrist_m": list(bone_world(armature, hand).translation),
            "wrist_error_m": (bone_world(armature, hand).translation - Vector(target)).length}


def pose(armature, plan, name):
    commands = list(plan["initial_grip_commands"])
    if name == "release_terminal":
        commands = [row for row in commands if not row[0].startswith(("index_", "thumb_"))]
    if name.startswith("move_"):
        sign = 1 if name == "move_A" else -1
        commands += [["thigh_l", [0, 1, 0], sign * 7], ["thigh_r", [0, 1, 0], -sign * 7],
                     ["calf_l", [0, 1, 0], 6 if sign > 0 else 0], ["calf_r", [0, 1, 0], 0 if sign > 0 else 6]]
    transfer.set_pose([armature], commands)
    phase_offset = .015 if name == "move_A" else -.015 if name == "move_B" else 0
    errors = [solve_arm(armature, "r", (.23 + phase_offset, -.43, .98), (-.05, -.55, 1.02)),
              solve_arm(armature, "l", (.10 - phase_offset, .33, .82), (-.12, .54, .91))]
    frame = plan["hand_frame"]
    source = Matrix((frame["across"], frame["longitudinal"], frame["palm"])).transposed()
    target = Matrix(((0, 1, 0), (0, 0, -1), (-1, 0, 0))).transposed()
    rotation = (target @ source.inverted()).to_quaternion() @ armature.data.bones["hand_r"].matrix_local.to_quaternion()
    if name in ("wrist_in", "wrist_out"):
        rotation = Quaternion(Vector((1, 0, 0)), math.radians(12 if name == "wrist_in" else -12)) @ rotation
    set_bone_world_rotation(armature, "hand_r", rotation)
    return errors


def evaluated_snapshot(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices])
    triangles = np.array([list(triangle.vertices) for triangle in mesh.loop_triangles])
    evaluated.to_mesh_clear()
    return points, triangles


def ray_inside(tree, point):
    votes = []
    for direction in ((1, .317, .213), (.193, 1, .273), (.217, .137, 1)):
        direction = Vector(direction).normalized()
        origin = Vector(point)
        count = 0
        for _ in range(64):
            location, _, _, distance = tree.ray_cast(origin, direction)
            if location is None:
                break
            count += 1
            origin = location + direction * 1e-7
        else:
            raise ValueError("Unexpected ray-parity traversal length")
        votes.append(count % 2 == 1)
    return sum(votes) >= 2, votes


def actual_grip(body_points, body_triangles, weights, weapon, plan):
    hand_ids = [index for index, row in enumerate(weights) if sum(value for name, value in row.items() if name.endswith("_r") and name.startswith(("hand_", "thumb_", "index_", "middle_", "ring_", "pinky_"))) > .5]
    hand_set = set(hand_ids)
    body_tree = BVHTree.FromPolygons(body_points.tolist(), body_triangles.tolist(), all_triangles=True)
    records = []
    for name in ("cord_N1", "cord_P1", "leather_pouch", "loaded_stone"):
        points, triangles = evaluated_snapshot(weapon[name])
        tree = BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True)
        signed_rows = []
        if name.startswith("cord_"):
            for index in hand_ids:
                nearest = tree.find_nearest(Vector(body_points[index]))
                if nearest[0] is None or nearest[3] > .06:
                    continue
                inside, votes = ray_inside(tree, body_points[index])
                signed_rows.append({"body_vertex": index, "group": max(weights[index], key=weights[index].get),
                                    "signed_distance_m": float(nearest[3]) * (-1 if inside else 1),
                                    "parity_votes": votes, "actual_world_m": body_points[index].tolist()})
        crossing_hand, crossing_other = [], []
        for body_index, prop_index in body_tree.overlap(tree):
            kind = geometry.triangle_contact_kind(body_points[body_triangles[body_index]], points[triangles[prop_index]])
            if kind not in {"proper_crossing", "coplanar_area_overlap"}:
                continue
            target = crossing_hand if any(int(index) in hand_set for index in body_triangles[body_index]) else crossing_other
            target.append([int(body_index), int(prop_index), kind])
        contacts = {}
        for finger in ("index", "middle", "ring", "pinky", "thumb", "hand"):
            rows = [row for row in signed_rows if row["group"].startswith(finger + "_")]
            if rows:
                nearest = min(rows, key=lambda row: abs(row["signed_distance_m"]))
                contacts[finger] = nearest
        records.append({"object": name, "actual_triangles": len(triangles), "hand_surface_samples": signed_rows,
                        "minimum_signed_distance_m": min((row["signed_distance_m"] for row in signed_rows), default=None),
                        "hand_vertices_inside_over2mm": [row["body_vertex"] for row in signed_rows if row["signed_distance_m"] < -.002],
                        "nearest_group_contacts": contacts, "actual_hand_triangle_intersections": crossing_hand,
                        "actual_nonhand_triangle_intersections": crossing_other,
                        "minimum_world_Z_m": float(points[:, 2].min())})
    return records, hand_ids


def fingertip_contacts(actual, rest, weights, armature, weapon):
    points, triangles = evaluated_snapshot(weapon["cord_P1"])
    tree = BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True)
    start = points[:8].mean(axis=0)
    axis = plan_math.normalize(points[8:16].mean(axis=0) - start)
    result = {}
    for finger in ("index", "thumb"):
        name = finger + "_03_r"
        bone = armature.data.bones[name]
        head, tail = np.array(bone.head_local), np.array(bone.tail_local)
        direction = tail - head
        fraction = (rest - head) @ direction / np.dot(direction, direction)
        ids = [index for index, row in enumerate(weights) if row.get(name, 0) > .4 and fraction[index] > .35]
        rows = []
        for index in ids:
            location, normal, triangle, distance = tree.find_nearest(Vector(actual[index]))
            inside, votes = ray_inside(tree, actual[index])
            delta = np.array(location) - start
            radial = plan_math.normalize(delta - axis * np.dot(delta, axis))
            rows.append({"body_vertex": index, "signed_distance_m": float(distance) * (-1 if inside else 1),
                         "radial": radial.tolist(), "actual_world_m": actual[index].tolist(), "parity_votes": votes})
        if not rows:
            raise ValueError("No actual distal fingertip surface: " + finger)
        result[finger] = min(rows, key=lambda row: abs(row["signed_distance_m"]))
        result[finger]["qualified_tip_samples"] = len(rows)
    result["contact_radial_dot"] = float(np.dot(result["index"]["radial"], result["thumb"]["radial"]))
    result["opposition_target_dot"] = -.5
    result["both_actual_tip_surfaces_within2mm"] = all(abs(result[finger]["signed_distance_m"]) <= .002 for finger in ("index", "thumb"))
    result["opposition_target_met"] = result["contact_radial_dot"] <= -.5
    return result


def terminal_geometry_checks(weapon, controls, released):
    results = []
    for row in controls:
        obj = weapon[row["object"]]
        points, _ = evaluated_snapshot(obj)
        centers = points.reshape(11, 8, 3).mean(axis=1)
        path = row["released_path_local_m"] if released else row["ready_path_local_m"]
        expected = np.array([list(obj.matrix_world @ Vector(point)) for point in path])
        results.append({"object": obj.name, "retained": row["retained"],
                        "ring_center_max_error_m": float(np.linalg.norm(centers - expected, axis=1).max()),
                        "actual_pouch_end_world_m": centers[-1].tolist(),
                        "pouch_end_local_unchanged": row["pouch_end_unchanged"]})
    return results


def create(plan_path, output):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    frozen = [plan[key] for key in ("source", "weapon", "root_review", "weapon_interface", "actual_rig_transfer_report")]
    for item in frozen:
        if rig.record(Path(item["path"])) != item:
            raise ValueError("Frozen preparation input changed: " + item["path"])
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=plan["source"]["path"])
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(bodies) != 1 or len(armatures) != 1:
        raise ValueError("Expected the approved single body and actual armature")
    body, armature = bodies[0], armatures[0]
    transfer.set_pose([armature], [])
    baseline = rig.mesh_snapshot(body)
    baseline_weights = foot.weights_of(body)
    baseline_materials = rig.materials_report([body])
    baseline_encoded = foot.encoded_normals(body.data)
    baseline_bones = foot.rest_bones(armature)
    weapon, weapon_source, controls = append_existing_weapon(plan)
    weapon_root = weapon["Weapon_Sling"]
    source_weapon_world = Matrix(np.array(plan["weapon_basis_columns"]).tolist()).to_4x4()
    source_weapon_world.translation = Vector(plan["terminal_root_rest_m"])
    hand_mount = bone_world(armature, "hand_r").inverted() @ source_weapon_world
    socket = bpy.data.objects.new("weapon_r", None)
    bpy.context.scene.collection.objects.link(socket)
    socket.parent = armature
    socket.parent_type = "BONE"
    socket.parent_bone = "hand_r"
    bpy.context.view_layer.update()
    socket.matrix_world = source_weapon_world
    bpy.context.view_layer.update()
    weapon_root.parent = socket
    weapon_root.matrix_parent_inverse = Matrix.Identity(4)
    weapon_root.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    prior_report = json.loads(Path(plan["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(prior_report["mapping"]["path"]).read_text(encoding="utf-8"))
    native_ids = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(baseline_weights))])
    report = {"asset_id": "Unit_StoneSlinger", "status": "limited_grip_pose_diagnostic_in_progress", "plan": rig.record(plan_path),
              "source": plan["source"], "weapon_source": plan["weapon"], "script": rig.record(Path(__file__)),
              "weapon_derivative_controls": controls, "hand_mount_matrix": [list(row) for row in hand_mount],
              "timing_contract": plan["timing"], "poses": [], "images": [], "body_weights_modified": False,
              "actual_attack_clip_created": False, "move_loop_created": False, "grip_approved": False,
              "gait_approved": False, "animation_approved": False, "ue_approved": False, "production_approved": False}
    report_path = output / "sling_pilot_report.json"
    helper = rig.module("slinger_pilot_review", "prepare_tripo_character.py")
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    helper.render_setup(samples=8)
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    saved_pose_points = {}
    for name in ("idle", "wrist_in", "wrist_out", "move_A", "move_B", "release_terminal"):
        arms = pose(armature, plan, name)
        released = name == "release_terminal"
        weapon["cord_P1"].data.shape_keys.key_blocks["ReleaseTerminal"].value = 1 if released else 0
        weapon["loaded_stone"].hide_render = released
        weapon["release_terminal"].location = controls[1]["released_path_local_m"][0] if released else controls[1]["ready_path_local_m"][0]
        bpy.context.view_layer.update()
        actual, triangles = evaluated_snapshot(body)
        grip, hand_ids = actual_grip(actual, triangles, baseline_weights, weapon, plan)
        tips = fingertip_contacts(actual, baseline["positions"], baseline_weights, armature, weapon)
        terminal_geometry = terminal_geometry_checks(weapon, controls, released)
        matrices = {bone.name: np.array(bone_world(armature, bone.name) @ armature.data.bones[bone.name].matrix_local.inverted()) for bone in armature.pose.bones}
        predicted = np.zeros_like(actual)
        homogeneous = np.column_stack((baseline["positions"], np.ones(len(actual))))
        for index, row in enumerate(baseline_weights):
            predicted[index] = sum((matrices[bone] @ homogeneous[index])[:3] * value for bone, value in row.items())
        scope = np.flatnonzero(np.any(np.isin(triangles, hand_ids), axis=1))
        intersections = foot.exact_intersections(actual, triangles, native_ids, scope)
        intersections["scope"] = "Every triangle touching actual right hand/digit weighted vertices against every body triangle; native-edge-adjacent pairs excluded, single-common-vertex pairs tested; no positional weld."
        orientation = geometry.triangle_orientation(baseline["positions"], actual, triangles, foot.weight_linear(baseline_weights, matrices))
        mount_error = max(abs(value) for row in (weapon_root.matrix_world - bone_world(armature, "hand_r") @ hand_mount) for value in row)
        checks = {"unchanged_source_skin_actual_LBS_within3micrometers": float(np.linalg.norm(actual - predicted, axis=1).max()) < 3e-6,
                  "hand_attachment_matrix_within3micrometers": mount_error < 3e-6,
                  "arm_wrist_targets_within1mm": max(row["wrist_error_m"] for row in arms) < .001,
                  "no_nonhand_weapon_triangle_intersection": not any(row["actual_nonhand_triangle_intersections"] for row in grip),
                  "no_hand_surface_vertex_inside_cords_over2mm": not any(row["hand_vertices_inside_over2mm"] for row in grip),
                  "actual_terminal_path_centers_within3micrometers": max(row["ring_center_max_error_m"] for row in terminal_geometry) < 3e-6,
                  "actual_distal_pinching_contact_within2mm": released or tips["both_actual_tip_surfaces_within2mm"],
                  "actual_opposing_tip_target_met": released or tips["opposition_target_met"],
                  "no_body_negative_triangles": not orientation["negative_triangles"],
                  "no_hand_body_proper_crossings": not intersections["proper_crossing_pairs"]}
        pose_row = {"name": name, "arms": arms, "checks": checks, "maximum_actual_skin_prediction_error_m": float(np.linalg.norm(actual - predicted, axis=1).max()),
                    "actual_hand_attachment_matrix_max_error": mount_error, "weapon_body_triangle_and_hand_parity": grip,
                    "actual_distal_fingertip_contact": tips, "actual_terminal_geometry": terminal_geometry,
                    "actual_hand_self_intersection": intersections, "body_orientation": orientation,
                    "body_scale_channels": foot.scale_diagnostic(armature), "body_minimum_Z_m": float(actual[:, 2].min()),
                    "retained_terminal_world_m": list(weapon["retained_terminal"].matrix_world.translation),
                    "release_terminal_world_m": list(weapon["release_terminal"].matrix_world.translation),
                    "pouch_world_m": list(weapon["sling_pouch"].matrix_world.translation),
                    "independent_stone_visible": not weapon["loaded_stone"].hide_render,
                    "scope": "Static finite diagnostic pose, not a grounded gait, physics sling, attack clip or server event."}
        report["poses"].append(pose_row)
        rig.save(report_path, report)
        if not checks["unchanged_source_skin_actual_LBS_within3micrometers"] or not checks["hand_attachment_matrix_within3micrometers"]:
            raise ValueError("Actual rig evaluation/attachment contract failed; stop before images")
        saved_pose_points[name] = actual[hand_ids]
        if name == "idle":
            views = [("grip_palm", (-1, -1, .3), True), ("grip_dorsal", (1, -1, .3), True),
                     ("grip_terminal", (-1, 1, .2), True), ("idle_full", (1, -1.3, .4), False), ("idle_reverse", (-1, 1.3, .4), False)]
        else:
            views = [(name, (-1, -1, .3) if name == "release_terminal" else (1, -1.3, .4), name.startswith("wrist_") or released)]
        for image_name, direction, close in views:
            path = output / (image_name + ".png")
            target, size = None, None
            if close:
                target, size, _ = framing_math.orthographic_frame(saved_pose_points[name], direction, padding=1.4)
                target = target.tolist()
            helper.render_view(path, [body] + [obj for obj in weapon.values() if obj.type == "MESH"], direction,
                               size=512, target=target, framing=size)
            report["images"].append(rig.record(path))
            rig.save(report_path, report)
    pose(armature, plan, "idle")
    weapon["cord_P1"].data.shape_keys.key_blocks["ReleaseTerminal"].value = 0
    weapon["loaded_stone"].hide_render = False
    weapon["release_terminal"].location = controls[1]["ready_path_local_m"][0]
    bpy.context.view_layer.update()
    report["preservation"] = transfer.check_rest_normals_uv(baseline, rig.mesh_snapshot(body))
    report["preservation"].update({"all_body_weights_exact": foot.weights_of(body) == baseline_weights,
                                    "body_encoded_normals_exact": foot.encoded_normals(body.data) == baseline_encoded,
                                    "body_PBR_exact": rig.materials_report([body]) == baseline_materials,
                                    "all_rest_bones_exact": foot.rest_bones(armature) == baseline_bones,
                                    "weapon_original_geometry_UV_Basis_Draw_exact": all(local_weapon_data(weapon[name]) == snapshot for name, snapshot in weapon_source.items()),
                                    "all_frozen_files_unchanged": all(rig.record(Path(item["path"])) == item for item in frozen)})
    if not all(report["preservation"].values()):
        rig.save(report_path, report)
        raise ValueError("Frozen body surface, PBR, weights or source preservation failed")
    report["status"] = "limited_pose_candidate_pending_visual_review" if all(all(row["checks"].values()) for row in report["poses"]) else "limited_pose_diagnostic_failures_not_approved"
    blend = output / "Unit_StoneSlinger_IndependentSling_Diagnostic.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"] = rig.record(blend)
    rig.save(report_path, report)
    print(json.dumps({"status": report["status"], "poses": len(report["poses"]), "images": len(report["images"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    create(Path(args.plan).resolve(), Path(args.output).resolve())
