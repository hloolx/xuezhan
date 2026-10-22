from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


module_spec = importlib.util.spec_from_file_location("stoneaxe_pose", Path(__file__).with_name("prepare_stoneaxe_pose_pilot.py"))
pose = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(pose)
REVIEW_FRAMES = [
    ("Idle", 1, "idle"),
    ("Idle", 1, "idle_reverse"),
    ("Move", 7, "move_right"),
    ("Move", 25, "move_left"),
    ("Move", 1, "move_phase0"),
    ("Move", 7, "move_phase1"),
    ("Move", 13, "move_phase2"),
    ("Move", 19, "move_phase3"),
    ("Move", 25, "move_phase4"),
    ("Move", 31, "move_phase5"),
    ("Move", 37, "move_loop_end"),
    ("Attack", 14, "windup"),
    ("Attack", 1, "attack_start"),
    ("Attack", 61, "attack_ready"),
    ("Attack", 19, "swing"),
    ("Attack", 22, "contact"),
    ("Attack", 28, "recovery"),
    ("Hit", 10, "hit"),
    ("Hit", 25, "hit_recovery"),
    ("Hit", 31, "hit_ready"),
    ("Death", 37, "death_mid"),
    ("Death", 55, "death_contact"),
    ("Death", 73, "death_end"),
    ("Death", 73, "death_reverse"),
]


def surface(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    vertices = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    evaluated.to_mesh_clear()
    return vertices, triangles


def edge_regions(obj):
    labels = []
    for edge in obj.data.edges:
        names = []
        for index in edge.vertices:
            vertex = obj.data.vertices[index]
            names.append(max(((obj.vertex_groups[group.group].name, group.weight) for group in vertex.groups), key=lambda item: item[1])[0])
        if any(name.startswith(("hand_r", "lowerarm_r")) for name in names):
            labels.append("right_wrist_forearm")
        elif any(name.startswith("upperarm_r") for name in names):
            labels.append("right_elbow_upperarm")
        elif any(name.startswith(("thumb", "index", "middle", "ring", "pinky")) and name.endswith("_r") for name in names):
            labels.append("right_fingers")
        else:
            labels.append("other")
    return labels


def numeric_review(args, armature, body, weapon_meshes):
    armature.animation_data.action = None
    pose.reset_pose(armature)
    baseline = {}
    for obj in body:
        vertices = np.array([list(point) for point in pose.evaluated_world_vertices(obj)])
        edges = np.array([list(edge.vertices) for edge in obj.data.edges])
        lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
        baseline[obj.name] = (edges, lengths, np.array(edge_regions(obj)))
    result = {"source": str(args.source), "status": "numeric_diagnostic_not_visual_approval", "samples": []}
    for clip, frame, label in REVIEW_FRAMES:
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        intersections = {}
        weapon_floor = {}
        body_trees = []
        stretching = {}
        all_vertices = []
        for obj in body:
            vertices, triangles = surface(obj)
            all_vertices.extend(vertices)
            body_trees.append((obj.name, BVHTree.FromPolygons(vertices, triangles, all_triangles=True)))
            points = np.array([list(point) for point in vertices])
            edges, reference_lengths, regions = baseline[obj.name]
            lengths = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
            for region in sorted(set(regions)):
                selected = (regions == region) & (reference_lengths > .001)
                ratios = lengths[selected] / reference_lengths[selected]
                stretching[region] = {"edge_count": int(selected.sum()), "minimum_ratio": float(ratios.min()),
                                      "maximum_ratio": float(ratios.max()), "p95_ratio": float(np.percentile(ratios, 95)),
                                      "over_1_8x": int((ratios > 1.8).sum()), "under_0_3x": int((ratios < .3).sum())}
        for obj in weapon_meshes:
            vertices, triangles = surface(obj)
            weapon_floor[obj.name] = min(point.z for point in vertices)
            tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
            pairs = [(body_name, tree.overlap(body_tree)) for body_name, body_tree in body_trees]
            intersections[obj.name] = sum(len(overlaps) for body_name, overlaps in pairs)
        hand_world = armature.matrix_world @ armature.pose.bones["hand_r"].matrix
        socket_world = bpy.context.scene.objects["weapon_r"].matrix_world
        relative = hand_world.inverted() @ socket_world
        result["samples"].append({"clip": clip, "frame": frame, "time_seconds": (frame - 1) / 60, "label": label,
                                  "body_minimum_z_m": min(point.z for point in all_vertices),
                                  "weapon_body_surface_triangle_pairs": intersections,
                                  "weapon_minimum_z_m": weapon_floor,
                                  "edge_length_change": stretching,
                                  "socket_from_hand_head_matrix": [list(row) for row in relative]})
    result["limits"] = ["Triangle overlap counts identify contacts needing review; grip intersections can be sub-2mm intentional tolerance, not automatic approval.",
                        "Edge strain is a diagnostic of actual skinned deformation, not an anatomical or animation quality score.",
                        "Socket matrix is Blender bone-head relative and still contains 0.82 weapon scale; do not copy directly into UE handedness or a scale-baked static mesh."]
    pose.inspection.helper.write(args.output / "motion_numeric_review.json", result)
    print("MOTION_NUMERIC_REVIEW " + str(args.output / "motion_numeric_review.json"))


def render_review(args, armature, meshes, configure=True):
    if configure:
        pose.inspection.render_setup(args.device, args.samples)
    requested = set(args.labels.split(",")) if args.labels else set()
    for clip, frame, label in REVIEW_FRAMES:
        if requested and label not in requested:
            continue
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        vertices = [point for obj in meshes for point in pose.evaluated_world_vertices(obj)]
        minimum = Vector(tuple(min(point[axis] for point in vertices) for axis in range(3)))
        maximum = Vector(tuple(max(point[axis] for point in vertices) for axis in range(3)))
        target = (minimum + maximum) / 2
        framing = max(maximum - minimum) * 1.18
        suffix = ""
        if args.crop == "right-arm":
            joints = [pose.world_head(armature, armature.pose.bones[name]) for name in ("upperarm_r", "lowerarm_r", "hand_r")]
            minimum = Vector(tuple(min(point[axis] for point in joints) for axis in range(3)))
            maximum = Vector(tuple(max(point[axis] for point in joints) for axis in range(3)))
            target = (minimum + maximum) / 2
            framing = max(maximum - minimum) + .28
            suffix = "_arm"
        if args.crop == "feet":
            joints = [pose.world_head(armature, armature.pose.bones[name]) for name in ("foot_r", "foot_l", "ball_r", "ball_l")]
            minimum = Vector(tuple(min(point[axis] for point in joints) for axis in range(3)))
            maximum = Vector(tuple(max(point[axis] for point in joints) for axis in range(3)))
            target = (minimum + maximum) / 2
            framing = max(maximum - minimum) + .32
            suffix = "_feet"
        direction = (1.2, 2.3, .55) if label.endswith("_reverse") else (1.2, -2.3, .55)
        pose.inspection.helper.render_view(args.output / (label + suffix + ".png"), meshes, direction, size=args.size, framing=framing, target=target)
    print("MOTION_REVIEW_RENDERS " + str(args.output))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["numeric", "render"], default="numeric")
    parser.add_argument("--device", choices=["CPU", "HIP"], default="CPU")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--labels", default="")
    parser.add_argument("--crop", choices=["body", "right-arm", "feet"], default="body")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    weapon_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj not in body]
    if args.mode == "numeric":
        numeric_review(args, armature, body, weapon_meshes)
    else:
        render_review(args, armature, body + weapon_meshes)


if __name__ == "__main__":
    main()
