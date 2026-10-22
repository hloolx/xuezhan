from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
DIGIT_ANGLES = {"index": (30, 30, 0), "middle": (30, 30, 0), "ring": (30, 30, 10), "pinky": (10, 30, 0)}
module_spec = importlib.util.spec_from_file_location("stoneaxe_inspection", Path(__file__).with_name("prepare_stoneaxe_rig_pilot.py"))
inspection = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(inspection)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def world_head(armature, bone):
    return armature.matrix_world @ bone.head


def world_tail(armature, bone):
    return armature.matrix_world @ bone.tail


def reset_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


def set_world_rotation(armature, bone, rotation):
    position = world_head(armature, bone)
    world_matrix = Matrix.LocRotScale(position, rotation, armature.matrix_world.to_scale())
    bone.matrix = armature.matrix_world.inverted() @ world_matrix
    bpy.context.view_layer.update()


def translate_bone_world(armature, bone, translation):
    matrix = bone.matrix.copy()
    matrix.translation += armature.matrix_world.inverted().to_3x3() @ Vector(translation)
    bone.matrix = matrix
    bpy.context.view_layer.update()


def aim_bone(armature, bone, target):
    before = (world_tail(armature, bone) - world_head(armature, bone)).normalized()
    after = (Vector(target) - world_head(armature, bone)).normalized()
    rotation = before.rotation_difference(after) @ (armature.matrix_world @ bone.matrix).to_quaternion()
    set_world_rotation(armature, bone, rotation)


def solve_arm(armature, upper, lower, wrist, target, pole):
    shoulder = world_head(armature, upper)
    distance_upper = (world_head(armature, lower) - shoulder).length
    distance_lower = (world_head(armature, wrist) - world_head(armature, lower)).length
    delta = Vector(target) - shoulder
    distance = min(delta.length, (distance_upper + distance_lower) * .995)
    axis = delta.normalized()
    pole_delta = Vector(pole) - shoulder
    elbow_axis = (pole_delta - axis * pole_delta.dot(axis)).normalized()
    along = (distance_upper * distance_upper - distance_lower * distance_lower + distance * distance) / (2 * distance)
    height = math.sqrt(max(0, distance_upper * distance_upper - along * along))
    elbow = shoulder + axis * along + elbow_axis * height
    aim_bone(armature, upper, elbow)
    aim_bone(armature, lower, shoulder + axis * distance)
    return {"wrist_error_m": (world_head(armature, wrist) - Vector(target)).length,
            "elbow_m": list(elbow), "target_m": list(target)}


def rotate_rest_axis(bone, axis, angle):
    rest = bone.bone.matrix_local.to_quaternion()
    bone.rotation_quaternion = rest.inverted() @ Quaternion(Vector(axis), angle) @ rest


def keyed_pose(armature, frame):
    for bone in armature.pose.bones:
        bone.keyframe_insert(data_path="location", frame=frame)
        bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        bone.keyframe_insert(data_path="scale", frame=frame)


def evaluated_world_vertices(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    result = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return result


def hand_frame(armature):
    hand = armature.pose.bones["hand_r"]
    index = world_head(armature, armature.pose.bones["index_01_r"])
    pinky = world_head(armature, armature.pose.bones["pinky_01_r"])
    middle = world_head(armature, armature.pose.bones["middle_01_r"])
    across = (index - pinky).normalized()
    longitudinal = middle - world_head(armature, hand)
    longitudinal = (longitudinal - across * longitudinal.dot(across)).normalized()
    palm = across.cross(longitudinal).normalized()
    return across, longitudinal, palm, (index + pinky) / 2


def close_grip(armature, angles=(30, 0, 0), thumb_angles=(0, 0, 0)):
    across, longitudinal, palm, center = hand_frame(armature)
    armature_rotation = armature.matrix_world.to_quaternion()
    local_axis = armature_rotation.inverted() @ across
    for finger in ("index", "middle", "ring", "pinky"):
        for joint, angle in enumerate(DIGIT_ANGLES[finger], 1):
            rotate_rest_axis(armature.pose.bones[f"{finger}_{joint:02d}_r"], local_axis, math.radians(angle))
    thumb_axis = armature_rotation.inverted() @ longitudinal
    for joint, angle in enumerate(thumb_angles, 1):
        rotate_rest_axis(armature.pose.bones[f"thumb_{joint:02d}_r"], thumb_axis, math.radians(angle))
    first = armature.pose.bones["thumb_01_r"]
    rest = first.bone.matrix_local.to_quaternion()
    palm_axis = armature_rotation.inverted() @ palm
    first.rotation_quaternion = rest.inverted() @ Quaternion(local_axis, math.radians(20)) @ Quaternion(thumb_axis, math.radians(-15)) @ Quaternion(palm_axis, math.radians(10)) @ rest
    rotate_rest_axis(armature.pose.bones["thumb_02_r"], palm_axis, math.radians(45))
    rotate_rest_axis(armature.pose.bones["thumb_03_r"], palm_axis, 0)
    bpy.context.view_layer.update()
    return {"across": across, "longitudinal": longitudinal, "palm": palm, "center": center}


def append_weapon():
    source = ART / "weapons/Weapon_StoneAxe/Weapon_StoneAxe.blend"
    with bpy.data.libraries.load(str(source), link=False) as (library_source, library_target):
        library_target.objects = list(library_source.objects)
    objects = [obj for obj in library_target.objects if obj and obj.type not in ("LIGHT", "CAMERA") and not obj.name.startswith("DISPLAY_")]
    for obj in objects:
        bpy.context.scene.collection.objects.link(obj)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    root = next(obj for obj in objects if obj.name == "Weapon_StoneAxe")
    return root, meshes, objects


def bind_weapon(armature, frame, diameter=.036):
    root, meshes, objects = append_weapon()
    center = frame["center"] - frame["longitudinal"] * .005228 + frame["palm"] * .041
    across = frame["across"]
    weapon_forward = frame["longitudinal"]
    weapon_right = across.cross(weapon_forward).normalized()
    rotation = Matrix((weapon_forward, weapon_right, across)).transposed().to_quaternion()
    root.matrix_world = Matrix.LocRotScale(center, rotation, Vector((.82, .82, .82)))
    for obj in meshes:
        if obj.name.startswith(("shaft", "grip_wrap")):
            obj.scale.x *= diameter / (.05 * .82)
            obj.scale.y *= diameter / (.05 * .82)
    socket = bpy.data.objects.new("weapon_r", None)
    bpy.context.scene.collection.objects.link(socket)
    socket.empty_display_type = "ARROWS"
    socket.empty_display_size = .08
    socket.parent = armature
    socket.parent_type = "BONE"
    socket.parent_bone = "hand_r"
    socket.matrix_world = root.matrix_world.copy()
    root.parent = socket
    root.matrix_parent_inverse = Matrix.Identity(4)
    root.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    return socket, root, meshes, objects


def pose_idle(armature, rest_hand_frame, phase=0, carry_correction=False):
    reset_pose(armature)
    close_grip(armature)
    solve_arm(armature, armature.pose.bones["upperarm_r"], armature.pose.bones["lowerarm_r"], armature.pose.bones["hand_r"],
              (.20, -.36, (.90 if carry_correction else .95) + .008 * math.sin(phase)), (-.15, -.55, .9))
    across, longitudinal, palm, center = rest_hand_frame
    source_frame = Matrix((across, longitudinal, palm)).transposed()
    target_frame = Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0))).transposed()
    desired = (target_frame @ source_frame.inverted()).to_quaternion() @ (armature.matrix_world @ armature.data.bones["hand_r"].matrix_local).to_quaternion()
    if carry_correction:
        desired = Quaternion(Vector((0, 1, 0)), math.radians(20)) @ desired
    set_world_rotation(armature, armature.pose.bones["hand_r"], desired)
    solve_arm(armature, armature.pose.bones["upperarm_l"], armature.pose.bones["lowerarm_l"], armature.pose.bones["hand_l"],
              (.11, .34, .81), (-.12, .55, .92))


def grip_clearance(meshes, weapon, radius=.018):
    center = weapon.matrix_world @ Vector((-.0046, 0, 0))
    axis = (weapon.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    grouped = {}
    samples = []
    for obj in meshes:
        vertices = evaluated_world_vertices(obj)
        for vertex, world in zip(obj.data.vertices, vertices):
            named = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
            hand = [(name, weight) for name, weight in named if name.endswith("_r") and name.startswith(("hand", "index", "middle", "ring", "pinky", "thumb"))]
            if sum(weight for _, weight in hand) < .5:
                continue
            along = (world - center).dot(axis)
            if abs(along) > .075:
                continue
            radial = (world - center - axis * along).length
            part = max(hand, key=lambda pair: pair[1])[0].split("_")[0]
            grouped.setdefault(part, []).append(radial - radius)
            samples.append({"group": part, "world": list(world), "axial": along})
    return {"method": "Evaluated weighted hand surface vertices against nominal straight 36mm handle cylinder inside +/-75mm of grip. Negative distance is vertex penetration; triangle crossings and wrapping still require visual review.",
            "radius_m": radius, "center_world": list(center), "axis_world": list(axis), "samples": samples,
            "groups": {name: {"vertices": len(values), "min_clearance_mm": min(values) * 1000, "max_clearance_mm": max(values) * 1000,
                               "vertices_penetrating_over_2mm": sum(value < -.002 for value in values)} for name, values in grouped.items()}}


def actual_handle_clearance(meshes, weapon_meshes):
    trees = []
    for obj in weapon_meshes:
        if not obj.name.startswith(("shaft", "grip_wrap")):
            continue
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        vertices = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        polygons = [list(polygon.vertices) for polygon in mesh.polygons]
        center = sum(vertices, Vector()) / len(vertices)
        planes = []
        for polygon in polygons:
            origin = vertices[polygon[0]]
            normal = (vertices[polygon[1]] - origin).cross(vertices[polygon[2]] - origin)
            if normal.length < 1e-10:
                continue
            normal.normalize()
            if normal.dot(origin - center) < 0:
                normal.negate()
            planes.append((normal, normal.dot(origin)))
        if not planes or max(normal.dot(point) - offset for normal, offset in planes for point in vertices) > 1e-5:
            raise ValueError("Actual handle part is not convex; use closed-mesh ray containment instead: " + obj.name)
        trees.append((obj.name, BVHTree.FromPolygons(vertices, polygons), planes))
        evaluated.to_mesh_clear()
    grouped = {}
    for obj in meshes:
        vertices = evaluated_world_vertices(obj)
        for vertex, point in zip(obj.data.vertices, vertices):
            influences = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
            hand = [(name, weight) for name, weight in influences if name.endswith("_r") and name.startswith(("hand", "index", "middle", "ring", "pinky", "thumb"))]
            if sum(weight for _, weight in hand) < .5:
                continue
            signed = []
            for name, tree, planes in trees:
                nearest, normal, polygon, distance = tree.find_nearest(point)
                inside = all(plane_normal.dot(point) - offset <= 1e-7 for plane_normal, offset in planes)
                signed.append(-distance if inside else distance)
            part = max(hand, key=lambda pair: pair[1])[0].split("_")[0]
            grouped.setdefault(part, []).append(min(signed))
    return {"method": "Evaluated hand surface vertices to actual evaluated shaft and grip-wrap BVHs. Sign uses all outward convex-face halfspaces, with convexity checked against actual vertices; nearest-face dot alone is not a valid containment test. Does not exclude triangle-edge crossings without vertex penetration.",
            "handle_parts": [name for name, tree, planes in trees],
            "groups": {name: {"vertices": len(values), "min_clearance_mm": min(values) * 1000,
                               "vertices_penetrating_over_2mm": sum(value < -.002 for value in values)} for name, values in grouped.items()}}


def create_grip(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    reset_pose(armature)
    frame_tuple = hand_frame(armature)
    frame = close_grip(armature)
    socket, weapon, weapon_meshes, weapon_objects = bind_weapon(armature, frame)
    pose_idle(armature, frame_tuple)
    bpy.context.view_layer.update()
    inspection.helper.write(args.output / "grip_draft.json", {
        "status": "actual_bones_posed_pending_visual_review", "hand": "hand_r", "source": str(args.source),
        "four_finger_curl_deg": DIGIT_ANGLES, "thumb_deg": {"opposition": 20, "roll": -15, "palm_flex": [10, 45, 0]}, "handle_diameter_m": .036,
        "weapon_source": str(ART / "weapons/Weapon_StoneAxe/Weapon_StoneAxe.blend"),
        "weapon_scale": .82, "armature": inspection.skeleton_report(armature, meshes),
        "clearance": grip_clearance(meshes, weapon),
        "actual_handle_clearance": actual_handle_clearance(meshes, weapon_meshes),
        "socket_world": [list(row) for row in socket.matrix_world], "grip_approved": False,
        "handedness": "Uses returned Unreal hand_r bone chain without mirroring; Blender raw hand_r is on -Y side. UE FBX handedness requires integration review."})
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / "grip_draft.blend"))
    if args.render:
        inspection.render_setup(args.device, 12)
        hand_target = world_head(armature, armature.pose.bones["hand_r"]) + Vector((.045, 0, .015))
        for name, direction in [("grip_front", (1, -1, .3)), ("grip_rear", (-1, -1, .3)), ("grip_palm", (1, 1, .2))]:
            inspection.helper.render_view(args.output / (name + ".png"), meshes + weapon_meshes, direction, size=768, framing=.38, target=hand_target)
        if not args.closeup_only:
            for name, direction in [("idle_front", (1, 0, .1)), ("idle_right", (0, -1, .3)), ("idle_back", (-1, 0, .1))]:
                inspection.helper.render_view(args.output / (name + ".png"), meshes + weapon_meshes, direction, size=768, framing=1.9, target=(.08, 0, .83))
    print("STONEAXE_GRIP_DRAFT " + str(args.output))


def interpolate_attack(time):
    keys = [
        (0.00, (.20, -.36, .95), 0, 0),
        (0.12, (.03, -.36, 1.20), -25, -2),
        (0.22, (-.02, -.35, 1.30), -45, -4),
        (0.30, (.18, -.36, 1.18), 35, 2),
        (0.35, (.37, -.34, 1.02), 95, 6),
        (0.45, (.34, -.35, .85), 115, 7),
        (0.65, (.20, -.36, .86), 50, 3),
        (1.00, (.20, -.36, .95), 0, 0),
    ]
    for previous, following in zip(keys, keys[1:]):
        if previous[0] <= time <= following[0]:
            factor = (time - previous[0]) / (following[0] - previous[0])
            factor = factor * factor * (3 - 2 * factor)
            wrist = Vector(previous[1]).lerp(Vector(following[1]), factor)
            tilt = previous[2] * (1 - factor) + following[2] * factor
            lean = previous[3] * (1 - factor) + following[3] * factor
            return wrist, tilt, lean
    return Vector(keys[-1][1]), keys[-1][2], keys[-1][3]


def foot_surface_groups(armature, meshes):
    groups = {side: [] for side in ("r", "l")}
    for obj in meshes:
        points = evaluated_world_vertices(obj)
        for side in groups:
            ankle_x = world_head(armature, armature.pose.bones["foot_" + side]).x
            toe_x = world_head(armature, armature.pose.bones["ball_" + side]).x
            indices = []
            for vertex in obj.data.vertices:
                weight = sum(group.weight for group in vertex.groups if obj.vertex_groups[group.group].name.endswith("_" + side) and obj.vertex_groups[group.group].name.startswith(("foot", "ball", "calf")))
                ankle = world_head(armature, armature.pose.bones["foot_" + side])
                if weight > .5 and points[vertex.index].z < ankle.z + .07:
                    indices.append(vertex.index)
            if not indices:
                continue
            floor = min(points[index].z for index in indices)
            sole = [index for index in indices if points[index].z < floor + .015]
            heel = [index for index in indices if points[index].x < ankle_x]
            toe = [index for index in indices if points[index].x > toe_x]
            if not sole or not heel or not toe:
                raise ValueError("Cannot identify actual weighted sole/heel/toe on " + side)
            groups[side].append({"object": obj, "all": indices, "sole": sole, "heel": heel, "toe": toe})
    return groups


def repair_shoe_weights(armature, meshes):
    records = []
    for obj in meshes:
        points = evaluated_world_vertices(obj)
        adjacency = [set() for vertex in obj.data.vertices]
        for edge in obj.data.edges:
            first, second = edge.vertices
            adjacency[first].add(second)
            adjacency[second].add(first)
        for side in ("r", "l"):
            ankle = world_head(armature, armature.pose.bones["foot_" + side])
            foot_name = "foot_" + side
            ball_name = "ball_" + side
            candidates = set()
            seeds = set()
            for vertex in obj.data.vertices:
                weights = {obj.vertex_groups[group.group].name: group.weight for group in vertex.groups}
                leg_weight = sum(weight for name, weight in weights.items() if name.endswith("_" + side) and name.startswith(("foot", "ball", "calf")))
                if points[vertex.index].z < ankle.z + .07 and leg_weight > .5:
                    candidates.add(vertex.index)
                    if weights.get(foot_name, 0) + weights.get(ball_name, 0) > .9:
                        seeds.add(vertex.index)
            selected = set(seeds)
            pending = list(seeds)
            while pending:
                index = pending.pop()
                for neighbor in adjacency[index] & candidates - selected:
                    selected.add(neighbor)
                    pending.append(neighbor)
            for index in sorted(selected):
                vertex = obj.data.vertices[index]
                before = {obj.vertex_groups[group.group].name: group.weight for group in vertex.groups}
                fraction = min(1.0, max(0.0, (ankle.z + .07 - points[index].z) / .09))
                blend = fraction * fraction * (3 - 2 * fraction)
                after = dict(before)
                transferred = 0.0
                for name, weight in before.items():
                    if name not in {foot_name, ball_name}:
                        transferred += weight * blend
                        after[name] = weight * (1 - blend)
                if transferred < 1e-7:
                    continue
                after[foot_name] = after.get(foot_name, 0) + transferred
                after = {name: weight for name, weight in after.items() if weight > 1e-8}
                total = sum(after.values())
                after = {name: weight / total for name, weight in after.items()}
                for name in before:
                    obj.vertex_groups[name].remove([index])
                for name, weight in after.items():
                    obj.vertex_groups[name].add([index], weight, "REPLACE")
                records.append({"object": obj.name, "vertex": index, "side": side, "rest_world_m": list(points[index]),
                                "before": before, "after": after, "foot_transfer_weight": transferred})
    return {"method": "Topology flood from existing foot/ball-dominant seeds within geometric lower-boot region; full lower-sole transfer to foot below ankle-20mm, smooth transition to unchanged cuff at ankle+70mm; existing ball weights retained. Hands and original rig files untouched.",
            "modified_vertices": len(records), "vertices": records}


def blend_pose_to_idle(armature, idle_basis, amount):
    for bone in armature.pose.bones:
        current_location, current_rotation, current_scale = bone.matrix_basis.decompose()
        idle_location, idle_rotation, idle_scale = idle_basis[bone.name].decompose()
        bone.matrix_basis = Matrix.LocRotScale(current_location.lerp(idle_location, amount),
                                             current_rotation.slerp(idle_rotation, amount), current_scale.lerp(idle_scale, amount))
    bpy.context.view_layer.update()


def measured_feet(groups):
    result = {}
    for side, entries in groups.items():
        selected = {name: [] for name in ("all", "sole", "heel", "toe")}
        for entry in entries:
            vertices = evaluated_world_vertices(entry["object"])
            for name in selected:
                selected[name].extend(vertices[index] for index in entry[name])
        result[side] = {"minimum_z_m": min(point.z for point in selected["all"]),
                        "heel_minimum_z_m": min(point.z for point in selected["heel"]),
                        "toe_minimum_z_m": min(point.z for point in selected["toe"]),
                        "sole_centroid_m": list(sum(selected["sole"], Vector()) / len(selected["sole"]))}
    return result


def pose_move_legs(armature, rest_feet, foot_groups, fraction, duration, speed):
    phase = fraction * 2 * math.pi
    translate_bone_world(armature, armature.pose.bones["pelvis"], (0, 0, -.065 + .006 * (1 - math.cos(phase * 2))))
    amplitude = speed * duration / 4
    targets = {}
    for side, phase_offset in (("r", 0), ("l", .5)):
        cycle = (fraction + phase_offset) % 1.0
        stance = cycle < .5
        position, rotation = rest_feet[side]
        if stance:
            offset = amplitude - speed * duration * cycle
            lift = 0.0
        else:
            progress = (cycle - .5) * 2
            offset = -amplitude + 2 * amplitude * progress * progress * (3 - 2 * progress)
            lift = .075 * math.sin(math.pi * progress)
        hip_rest = armature.matrix_world @ armature.data.bones["thigh_" + side].head_local
        target = Vector((hip_rest.x + offset, position.y, position.z + lift))
        targets[side] = {"target": target, "rotation": rotation, "stance": stance, "desired_sole_z_m": lift}
    for iteration in range(4):
        for side, values in targets.items():
            target = values["target"]
            solve_arm(armature, armature.pose.bones["thigh_" + side], armature.pose.bones["calf_" + side], armature.pose.bones["foot_" + side], target,
                      (.45, target.y, .4))
            set_world_rotation(armature, armature.pose.bones["foot_" + side], values["rotation"])
        measurements = measured_feet(foot_groups)
        for side, values in targets.items():
            values["target"].z += values["desired_sole_z_m"] - measurements[side]["minimum_z_m"]
    result = measured_feet(foot_groups)
    for side, values in targets.items():
        result[side].update({"stance": values["stance"], "desired_sole_z_m": values["desired_sole_z_m"],
                             "ankle_target_error_m": (world_head(armature, armature.pose.bones["foot_" + side]) - values["target"]).length,
                             "world_compensated_sole_x_m": result[side]["sole_centroid_m"][0] + speed * duration * fraction})
    return result


def relax_death_arms(armature, reference_frame, fraction):
    relaxation = min(1.0, max(0.0, (fraction - .35) / .65))
    relaxation = relaxation * relaxation * (3 - 2 * relaxation)
    if relaxation == 0:
        return
    pelvis = world_head(armature, armature.pose.bones["pelvis"])
    across, longitudinal, palm, center = reference_frame
    source_frame = Matrix((across, longitudinal, palm)).transposed()
    target_frame = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1))).transposed()
    right_rotation = (target_frame @ source_frame.inverted()).to_quaternion() @ (armature.matrix_world @ armature.data.bones["hand_r"].matrix_local).to_quaternion()
    for side, offset, elbow_offset in (("r", (0, -.43, -.11), (-.25, -.65, .02)), ("l", (.03, .39, -.09), (-.25, .62, .01))):
        hand = armature.pose.bones["hand_" + side]
        current_rotation = (armature.matrix_world @ hand.matrix).to_quaternion()
        target = world_head(armature, hand).lerp(pelvis + Vector(offset), relaxation)
        solve_arm(armature, armature.pose.bones["upperarm_" + side], armature.pose.bones["lowerarm_" + side], hand, target, pelvis + Vector(elbow_offset))
        rotation = current_rotation.slerp(right_rotation, relaxation) if side == "r" else current_rotation
        set_world_rotation(armature, hand, rotation)


def build_animations(args):
    grip_acceptance = None
    if args.grip_review_reference:
        grip_acceptance = read_json(Path(args.grip_review_reference).resolve())
        if grip_acceptance.get("status") != "static_grip_approved_only" or grip_acceptance["source_sha256"] != inspection.helper.sha(args.source):
            raise ValueError("Animation input does not match the actually reviewed static grip")
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    weapon = bpy.context.scene.objects["Weapon_StoneAxe"]
    weapon_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj not in body_meshes]
    reset_pose(armature)
    shoe_repair = repair_shoe_weights(armature, body_meshes)
    inspection.helper.write(args.output / "shoe_weight_repair.json", shoe_repair)
    reference_frame = hand_frame(armature)
    rest_feet = {side: (world_head(armature, armature.pose.bones["foot_" + side]),
                         (armature.matrix_world @ armature.pose.bones["foot_" + side].matrix).to_quaternion()) for side in ("l", "r")}
    foot_groups = foot_surface_groups(armature, body_meshes)
    pose_idle(armature, reference_frame, carry_correction=True)
    idle_basis = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
    scene = bpy.context.scene
    scene.render.fps = 60
    scene.render.fps_base = 1
    unit = next(unit for unit in read_json(ROOT / "Content/Data/Units.json") if unit["VisualKey"] == "Unit_StoneAxe")
    if unit["AttackWindup"] != .35 or unit["AttackInterval"] != 1.0:
        raise ValueError("Current authored attack keys must be re-timed to changed server data")
    armature.animation_data_create()
    if grip_acceptance:
        armature["reviewed_static_grip_source_sha256"] = grip_acceptance["source_sha256"]
    clips = [("CW_StoneAxe_Idle", 120), ("CW_StoneAxe_Move", 36), ("CW_StoneAxe_Attack", 60), ("CW_StoneAxe_Hit", 30), ("CW_StoneAxe_Death", 72)]
    report = {"source": str(args.source), "fps": 60, "source_timing": {"AttackInterval": unit["AttackInterval"], "AttackWindup": unit["AttackWindup"]},
              "client_animation_causes_damage": False, "root_motion": False, "clips": [], "grip_approved": bool(args.grip_review_reference),
              "grip_review_reference": args.grip_review_reference, "animation_approved": False, "runtime_approved": False,
              "shoe_weight_repair": {"report": str(args.output / "shoe_weight_repair.json"), "modified_vertices": shoe_repair["modified_vertices"]}}
    report["movement_contract"] = {"server_move_speed_cm_per_second": unit["MoveSpeed"], "authored_move_cycle_seconds": .6,
                                    "stance_fraction": .5, "stance_backwards_speed_m_per_second": unit["MoveSpeed"] / 100,
                                    "root_motion": False, "runtime_no_sliding_approved": False,
                                    "note": "In-place stance motion offsets server translation analytically; actual component interpolation and animation rate still require game testing."}
    for name, duration_frames in clips:
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        armature.animation_data.action = action
        samples = []
        foot_samples = []
        for frame in range(1, duration_frames + 2):
            scene.frame_set(frame)
            fraction = (frame - 1) / duration_frames
            pose_idle(armature, reference_frame, phase=fraction * 2 * math.pi if name.endswith("Idle") else 0,
                      carry_correction=not name.endswith("Attack"))
            hand_rotation = (armature.matrix_world @ armature.pose.bones["hand_r"].matrix).to_quaternion()
            if name.endswith("Attack"):
                wrist, tilt, lean = interpolate_attack(fraction)
                rotate_rest_axis(armature.pose.bones["spine_02"], Vector((0, 1, 0)), math.radians(lean))
                bpy.context.view_layer.update()
                solve_arm(armature, armature.pose.bones["upperarm_r"], armature.pose.bones["lowerarm_r"], armature.pose.bones["hand_r"], wrist, (-.18, -.60, 1.0))
                set_world_rotation(armature, armature.pose.bones["hand_r"], Quaternion(Vector((0, 1, 0)), math.radians(tilt)) @ hand_rotation)
                solve_arm(armature, armature.pose.bones["upperarm_l"], armature.pose.bones["lowerarm_l"], armature.pose.bones["hand_l"], (.10, .36, .85), (-.10, .6, .9))
                seam = max(0.0, 1 - fraction / .12) if fraction < .12 else max(0.0, (fraction - .65) / .35)
                if seam > 0:
                    blend_pose_to_idle(armature, idle_basis, seam * seam * (3 - 2 * seam))
            elif name.endswith("Move"):
                feet = pose_move_legs(armature, rest_feet, foot_groups, fraction, duration_frames / 60, unit["MoveSpeed"] / 100)
                foot_samples.append({"frame": frame, "time_seconds": (frame - 1) / 60, "feet": feet})
            elif name.endswith("Hit"):
                reaction = math.sin(math.pi * fraction) * (1 - fraction)
                rotate_rest_axis(armature.pose.bones["spine_02"], Vector((0, 1, 0)), math.radians(-16 * reaction))
                rotate_rest_axis(armature.pose.bones["neck_01"], Vector((0, 1, 0)), math.radians(-8 * reaction))
            elif name.endswith("Death"):
                fall = fraction * fraction * (3 - 2 * fraction)
                pelvis = armature.pose.bones["pelvis"]
                rotate_rest_axis(pelvis, Vector((0, 1, 0)), math.radians(-86 * fall))
                bpy.context.view_layer.update()
                translate_bone_world(armature, pelvis, (-.10 * fall, 0, -.58 * fall))
                relax_death_arms(armature, reference_frame, fraction)
            if name.endswith("Death"):
                for correction in range(3):
                    minimum_z = min(point.z for obj in body_meshes for point in evaluated_world_vertices(obj))
                    if minimum_z >= -.00001:
                        break
                    translate_bone_world(armature, armature.pose.bones["pelvis"], (0, 0, -minimum_z))
            bpy.context.view_layer.update()
            keyed_pose(armature, frame)
            if frame in {1, duration_frames + 1, 8, 14, 19, 22, 28, 40}:
                vertices = [point for obj in body_meshes for point in evaluated_world_vertices(obj)]
                samples.append({"frame": frame, "time_seconds": (frame - 1) / 60,
                                "body_minimum_z_m": min(point.z for point in vertices),
                                "body_maximum_z_m": max(point.z for point in vertices),
                                "hand_r_world": list(world_head(armature, armature.pose.bones["hand_r"])),
                                "actual_handle_clearance": actual_handle_clearance(body_meshes, weapon_meshes),
                                "root_matrix_basis": [list(row) for row in armature.pose.bones["root"].matrix_basis]})
        if name.endswith("Attack"):
            for marker_name, marker_frame in (("windup", 1), ("swing", 14), ("contact_visual_only", 22), ("recovery", 28), ("ready", 61)):
                action.pose_markers.new(marker_name).frame = marker_frame
        clip_report = {"name": name, "start_frame": 1, "end_frame": duration_frames + 1, "duration_seconds": duration_frames / 60, "samples": samples}
        if foot_samples:
            slips = []
            for previous, following in zip(foot_samples, foot_samples[1:]):
                for side in ("r", "l"):
                    before, after = previous["feet"][side], following["feet"][side]
                    if before["stance"] and after["stance"]:
                        slips.append(abs(after["world_compensated_sole_x_m"] - before["world_compensated_sole_x_m"]))
            clip_report["all_frame_feet"] = foot_samples
            clip_report["maximum_stance_sole_ground_error_m"] = max(abs(feet["minimum_z_m"]) for sample in foot_samples for feet in sample["feet"].values() if feet["stance"])
            clip_report["maximum_stance_compensated_sole_x_step_m"] = max(slips, default=0)
            clip_report["stance_compensated_sole_x_span_m"] = {side: max(sample["feet"][side]["world_compensated_sole_x_m"] for sample in foot_samples[:-1] if sample["feet"][side]["stance"])
                                                              - min(sample["feet"][side]["world_compensated_sole_x_m"] for sample in foot_samples[:-1] if sample["feet"][side]["stance"]) for side in ("r", "l")}
            clip_report["actual_runtime_foot_sliding_approved"] = False
        report["clips"].append(clip_report)
    armature.animation_data.action = bpy.data.actions["CW_StoneAxe_Idle"]
    scene.frame_start = 1
    scene.frame_end = 121
    scene.frame_set(1)
    inspection.helper.write(args.output / "animation_draft_report.json", report)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / "StoneAxe_animation_draft.blend"))
    if args.render:
        review_spec = importlib.util.spec_from_file_location("stoneaxe_motion_review", Path(__file__).with_name("prepare_stoneaxe_motion_review.py"))
        review = importlib.util.module_from_spec(review_spec)
        review_spec.loader.exec_module(review)
        review_args = argparse.Namespace(source=args.output / "StoneAxe_animation_draft.blend", output=args.output / "review",
                                         device=args.device, samples=args.samples, size=args.size, labels=args.labels, crop="body")
        review_args.output.mkdir(parents=True, exist_ok=True)
        review.numeric_review(review_args, armature, body_meshes, weapon_meshes)
        review.render_review(review_args, armature, body_meshes + weapon_meshes)
        if args.arm_labels:
            review_args.labels = args.arm_labels
            review_args.crop = "right-arm"
            review.render_review(review_args, armature, body_meshes + weapon_meshes, configure=False)
        if args.foot_labels:
            review_args.labels = args.foot_labels
            review_args.crop = "feet"
            review.render_review(review_args, armature, body_meshes + weapon_meshes, configure=False)
    if args.full_diagnostic:
        diagnostic_spec = importlib.util.spec_from_file_location("stoneaxe_full_diagnostic", Path(__file__).with_name("prepare_stoneaxe_full_diagnostic.py"))
        diagnostic = importlib.util.module_from_spec(diagnostic_spec)
        diagnostic_spec.loader.exec_module(diagnostic)
        diagnostic.inspect(argparse.Namespace(source=args.output / "StoneAxe_animation_draft.blend", output=args.output / "full_diagnostic", comparison_source=args.comparison_source))
    print("ANIMATION_DRAFT " + json.dumps({"path": str(args.output), "clips": [name for name, frames in clips]}))


def optimize_grip(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    reset_pose(armature)
    across, longitudinal, palm, center = hand_frame(armature)
    groups = {}
    for vertex in obj.data.vertices:
        named = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
        hand = [(name, weight) for name, weight in named if name.endswith("_r") and name.startswith(("hand", "index", "middle", "ring", "pinky"))]
        if sum(weight for _, weight in hand) >= .5:
            part = max(hand, key=lambda pair: pair[1])[0].split("_")[0]
            groups.setdefault(part, []).append(vertex.index)
            if part != "hand" and sum(weight for name, weight in hand if "_02_" in name or "_03_" in name) > .6:
                groups.setdefault(part + "_distal", []).append(vertex.index)
    indices = [index for values in groups.values() for index in values]
    labels = [name for name, values in groups.items() for index in values]
    candidates = np.array([(along / 1000, inward / 1000) for along in range(-15, 66, 3) for inward in range(5, 76, 3)])
    best = []
    axis = armature.matrix_world.to_quaternion().inverted() @ across
    for proximal in (0, 10, 20, 30, 40):
        for middle in (0, 12, 24, 36):
            for distal in (0, 12):
                for finger in ("index", "middle", "ring", "pinky"):
                    for joint, angle in enumerate((proximal, middle, distal), 1):
                        rotate_rest_axis(armature.pose.bones[f"{finger}_{joint:02d}_r"], axis, math.radians(angle))
                bpy.context.view_layer.update()
                vertices = evaluated_world_vertices(obj)
                points = np.array([[(vertices[index] - center).dot(longitudinal), (vertices[index] - center).dot(palm)] for index in indices])
                distances = np.linalg.norm(points[None, :, :] - candidates[:, None, :], axis=2)
                for radius in (.016, .018, .020):
                    signed = distances - radius
                    penetration = (np.minimum(0, signed + .001) ** 2).sum(axis=1)
                    contacts = {name: signed[:, [index for index, label in enumerate(labels) if label == name]].min(axis=1) for name in groups}
                    contact_loss = sum(np.maximum(0, values - .002) ** 2 for values in contacts.values())
                    scores = penetration * 60 + contact_loss
                    selected = np.argsort(scores)[:2]
                    for selected_index in selected:
                        best.append({"score": float(scores[selected_index]), "angles_deg": [proximal, middle, distal],
                                     "radius_m": radius, "center_offset_longitudinal_palm_m": candidates[selected_index].tolist(),
                                     "contacts_mm": {name: float(values[selected_index] * 1000) for name, values in contacts.items()},
                                     "penetrating_over_2mm": int((signed[selected_index] < -.002).sum())})
    best.sort(key=lambda item: item["score"])
    inspection.helper.write(args.output / "finger_fit_candidates.json", best[:30])
    print("FINGER_FIT " + json.dumps(best[:4]))


def optimize_thumb(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    reset_pose(armature)
    across, longitudinal, palm, center = hand_frame(armature)
    close_grip(armature)
    center = center - longitudinal * .009 + palm * .041
    indices = []
    distal_indices = []
    for vertex in obj.data.vertices:
        weights = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
        if sum(weight for name, weight in weights if name.startswith("thumb") and name.endswith("_r")) > .5:
            indices.append(vertex.index)
            if sum(weight for name, weight in weights if name in ("thumb_02_r", "thumb_03_r")) > .5:
                distal_indices.append(vertex.index)
    local_across = armature.matrix_world.to_quaternion().inverted() @ across
    local_long = armature.matrix_world.to_quaternion().inverted() @ longitudinal
    best = []
    for opposition in range(-40, 61, 20):
        for base in range(-40, 61, 20):
            for middle in range(-40, 61, 20):
                first = armature.pose.bones["thumb_01_r"]
                rest = first.bone.matrix_local.to_quaternion()
                first.rotation_quaternion = rest.inverted() @ Quaternion(local_across, math.radians(opposition)) @ Quaternion(local_long, math.radians(base)) @ rest
                rotate_rest_axis(armature.pose.bones["thumb_02_r"], local_long, math.radians(middle))
                rotate_rest_axis(armature.pose.bones["thumb_03_r"], local_long, math.radians(middle * .3))
                bpy.context.view_layer.update()
                vertices = evaluated_world_vertices(obj)
                distances = []
                distal = []
                for index in indices:
                    delta = vertices[index] - center
                    along = delta.dot(across)
                    radial = (delta - across * along).length - .018
                    distances.append(radial)
                    if index in distal_indices:
                        distal.append(radial)
                penetration = sum(min(0, distance + .001) ** 2 for distance in distances)
                contact = max(0, min(distal, default=.1) - .002) ** 2
                regularization = (opposition * opposition + base * base + middle * middle) * 1e-10
                best.append({"score": penetration * 70 + contact + regularization, "opposition": opposition, "base": base, "middle": middle,
                             "distal": middle * .3, "minimum_mm": min(distances, default=.1) * 1000,
                             "distal_contact_mm": min(distal, default=.1) * 1000, "penetrating_over_2mm": sum(distance < -.002 for distance in distances)})
    best.sort(key=lambda item: item["score"])
    inspection.helper.write(args.output / "thumb_fit_candidates.json", best[:30])
    print("THUMB_FIT " + json.dumps(best[:5]))


def optimize_digits(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    reset_pose(armature)
    across, longitudinal, palm, center = hand_frame(armature)
    close_grip(armature)
    center = center - longitudinal * .009 + palm * .041
    groups = {}
    distal = {}
    for vertex in obj.data.vertices:
        weights = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
        for finger in ("index", "middle", "ring", "pinky"):
            if sum(weight for name, weight in weights if name.startswith(finger) and name.endswith("_r")) > .5:
                groups.setdefault(finger, []).append(vertex.index)
                if sum(weight for name, weight in weights if name in (finger + "_02_r", finger + "_03_r")) > .6:
                    distal.setdefault(finger, []).append(vertex.index)
    axis = armature.matrix_world.to_quaternion().inverted() @ across
    selected = {finger: [30, 0, 0] for finger in groups}
    results = {}
    for iteration in range(2):
        for finger in groups:
            choices = []
            for proximal in (0, 10, 20, 30, 40):
                for middle in (-10, 0, 10, 20, 30):
                    for last in (0, 10):
                        for joint, angle in enumerate((proximal, middle, last), 1):
                            rotate_rest_axis(armature.pose.bones[f"{finger}_{joint:02d}_r"], axis, math.radians(angle))
                        bpy.context.view_layer.update()
                        vertices = evaluated_world_vertices(obj)
                        signed = {}
                        for group, indices in groups.items():
                            for index in indices:
                                delta = vertices[index] - center
                                signed[index] = (delta - across * delta.dot(across)).length - .018
                        penetration = sum(min(0, distance + .001) ** 2 for distance in signed.values())
                        distal_contact = min(signed[index] for index in distal[finger])
                        score = penetration * 80 + max(0, distal_contact - .001) ** 2
                        choices.append({"score": score, "angles": [proximal, middle, last], "distal_contact_mm": distal_contact * 1000,
                                        "minimum_mm": min(signed[index] for index in groups[finger]) * 1000,
                                        "penetrating_over_2mm": sum(distance < -.002 for distance in signed.values())})
            choices.sort(key=lambda item: item["score"])
            selected[finger] = choices[0]["angles"]
            results[finger] = choices[0]
            for joint, angle in enumerate(selected[finger], 1):
                rotate_rest_axis(armature.pose.bones[f"{finger}_{joint:02d}_r"], axis, math.radians(angle))
    inspection.helper.write(args.output / "per_digit_fit.json", {"selected_angles": selected, "results": results})
    print("DIGIT_FIT " + json.dumps({"selected_angles": selected, "results": results}))


def optimize_thumb_wrap(args):
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    reset_pose(armature)
    across, longitudinal, palm, center = hand_frame(armature)
    close_grip(armature)
    center = center - longitudinal * .009 + palm * .041
    indices = []
    tips = []
    for vertex in obj.data.vertices:
        weights = [(obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups]
        if sum(weight for name, weight in weights if name.startswith("thumb") and name.endswith("_r")) > .5:
            indices.append(vertex.index)
            if sum(weight for name, weight in weights if name == "thumb_03_r") > .5:
                tips.append(vertex.index)
    rotation = armature.matrix_world.to_quaternion().inverted()
    axes = [rotation @ across, rotation @ longitudinal, rotation @ palm]
    first = armature.pose.bones["thumb_01_r"]
    rest = first.bone.matrix_local.to_quaternion()
    choices = []
    for opposition in (10, 15, 20, 25, 30):
        for roll in (-15, -10, -5, 0, 5, 10, 15):
            for base in (10, 20, 30):
                for middle in (45, 55, 65, 75):
                    for last in (0, 10):
                        first.rotation_quaternion = rest.inverted() @ Quaternion(axes[0], math.radians(opposition)) @ Quaternion(axes[1], math.radians(roll)) @ Quaternion(axes[2], math.radians(base)) @ rest
                        rotate_rest_axis(armature.pose.bones["thumb_02_r"], axes[2], math.radians(middle))
                        rotate_rest_axis(armature.pose.bones["thumb_03_r"], axes[2], math.radians(last))
                        bpy.context.view_layer.update()
                        vertices = evaluated_world_vertices(obj)
                        signed = []
                        for index in indices:
                            delta = vertices[index] - center
                            signed.append((delta - across * delta.dot(across)).length - .018)
                        tip = sum((vertices[index] for index in tips), Vector()) / len(tips)
                        relative_tip = tip - center
                        tip_axial = relative_tip.dot(across)
                        tip_radial = (relative_tip - across * tip_axial).length
                        thumb_end_direction = (world_tail(armature, armature.pose.bones["thumb_03_r"]) - world_head(armature, armature.pose.bones["thumb_03_r"])).normalized()
                        end_axial = thumb_end_direction.dot(across)
                        penetration = sum(min(0, distance + .0007) ** 2 for distance in signed)
                        contact = max(0, min(signed) - .002) ** 2
                        wrap = max(0, abs(tip_axial - .032) - .012) ** 2 + max(0, tip_radial - .050) ** 2 + max(0, end_axial + .2) ** 2 * .001
                        score = penetration * 80 + contact + wrap * 4
                        choices.append({"score": score, "opposition": opposition, "roll": roll, "palm_flex_deg": [base, middle, last],
                                        "minimum_mm": min(signed) * 1000, "tip_axial_mm": tip_axial * 1000, "tip_radius_mm": tip_radial * 1000,
                                        "tip_direction_along_shaft": end_axial, "penetrating_over_2mm": sum(distance < -.002 for distance in signed)})
    choices.sort(key=lambda item: item["score"])
    inspection.helper.write(args.output / "thumb_wrap_fit.json", choices[:30])
    print("THUMB_WRAP_FIT " + json.dumps(choices[:5]))


def inspect_rig(args):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    imported = inspection.import_model(args.source)
    meshes = [obj for obj in imported if obj.type == "MESH"]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError("Expected exactly one real Tripo armature")
    armature = armatures[0]
    inspection.normalize(meshes, armatures)
    bones = inspection.skeleton_report(armature, meshes)
    bones["armature_matrix"] = [list(row) for row in armature.matrix_world]
    bones["pose_matrices"] = {bone.name: [list(row) for row in bone.matrix] for bone in armature.pose.bones}
    bones["meshes"] = [{"name": obj.name, "matrix": [list(row) for row in obj.matrix_world], "vertices": len(obj.data.vertices)} for obj in meshes]
    bones["source"] = str(args.source)
    bones["source_sha256"] = inspection.helper.sha(args.source)
    bones["materials"] = inspection.material_report(meshes)
    bones["material_repair"] = restore_source_pbr(meshes)
    inspection.helper.write(args.output / "skeleton_inspection.json", bones)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / "rig_inspected.blend"))
    print("RIG_INSPECTED " + json.dumps({"bone_count": bones["bone_count"], "bones": [bone["name"] for bone in bones["bones"]], "weights": bones["weights"]}))


def restore_source_pbr(meshes):
    reference_path = ART / "tripo_processed/stoneaxe_rig_pilot/textured_inspection/Unit_StoneAxe_textured_normalized.blend"
    with bpy.data.libraries.load(str(reference_path), link=False) as (library_source, library_target):
        library_target.objects = list(library_source.objects)
    references = [obj for obj in library_target.objects if obj and obj.type == "MESH"]
    for obj in references:
        bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    reference = references[0]
    tree = KDTree(len(reference.data.vertices))
    uv_by_vertex = {}
    for vertex in reference.data.vertices:
        tree.insert(reference.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    for loop in reference.data.loops:
        uv_by_vertex.setdefault(loop.vertex_index, []).append(reference.data.uv_layers.active.data[loop.index].uv.copy())
    maximum_position = 0.0
    maximum_uv = 0.0
    for obj in meshes:
        for loop in obj.data.loops:
            world = obj.matrix_world @ obj.data.vertices[loop.vertex_index].co
            position, nearest, distance = tree.find(world)
            maximum_position = max(maximum_position, distance)
            uv = obj.data.uv_layers.active.data[loop.index].uv
            maximum_uv = max(maximum_uv, min((uv - other).length for other in uv_by_vertex[nearest]))
    result = {"reference": str(reference_path), "maximum_surface_corner_position_difference_m": maximum_position,
              "maximum_matching_vertex_uv_difference": maximum_uv, "applied": False}
    if maximum_position < .00001 and maximum_uv < .00001:
        for obj in meshes:
            obj.data.materials.clear()
            obj.data.materials.append(reference.data.materials[0])
        result["applied"] = True
        result["reason"] = "Rig FBX material image bindings were defective. Proven matching surface vertices and UV corners allow the original full four-channel PBR material to be reused."
    for obj in library_target.objects:
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ART / "tripo_processed/stoneaxe_rig_pilot/rig_inspection")
    parser.add_argument("--mode", choices=["inspect", "grip", "fit", "fit-thumb", "fit-digits", "fit-thumb-wrap", "animate"], default="inspect")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--closeup-only", action="store_true")
    parser.add_argument("--device", choices=["CPU", "HIP"], default="CPU")
    parser.add_argument("--grip-review-reference")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--labels", default="idle,move_right,move_left,windup,swing,contact,recovery")
    parser.add_argument("--arm-labels", default="")
    parser.add_argument("--foot-labels", default="")
    parser.add_argument("--full-diagnostic", action="store_true")
    parser.add_argument("--comparison-source", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "animate":
        build_animations(args)
    elif args.mode == "fit-thumb-wrap":
        optimize_thumb_wrap(args)
    elif args.mode == "fit-digits":
        optimize_digits(args)
    elif args.mode == "fit-thumb":
        optimize_thumb(args)
    elif args.mode == "fit":
        optimize_grip(args)
    elif args.mode == "grip":
        create_grip(args)
    else:
        inspect_rig(args)


if __name__ == "__main__":
    main()
