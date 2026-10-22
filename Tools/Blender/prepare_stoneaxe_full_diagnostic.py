from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


module_spec = importlib.util.spec_from_file_location("stoneaxe_review", Path(__file__).with_name("prepare_stoneaxe_motion_review.py"))
review = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(review)
pose = review.pose
CLIPS = {"Idle": 121, "Move": 37, "Attack": 61, "Hit": 31, "Death": 73}


def snapshot(armature):
    return {bone.name: (armature.matrix_world @ bone.matrix).copy() for bone in armature.pose.bones} | {"weapon_r": bpy.context.scene.objects["weapon_r"].matrix_world.copy()}


def differences(actual, expected):
    result = {}
    for name, matrix in actual.items():
        reference = expected[name]
        result[name] = {"position_m": (matrix.translation - reference.translation).length,
                        "rotation_deg": math.degrees(matrix.to_quaternion().rotation_difference(reference.to_quaternion()).angle)}
    return result


def inspect(args):
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    comparison = {}
    if getattr(args, "comparison_source", None):
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.comparison_source).resolve()))
        previous_armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
        previous_armature.animation_data.action = bpy.data.actions["CW_StoneAxe_Attack"]
        for frame in (14, 19, 22, 28, 40):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            comparison[frame] = snapshot(previous_armature)
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    weapons = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj not in body]
    armature.animation_data.action = bpy.data.actions["CW_StoneAxe_Idle"]
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    idle = snapshot(armature)
    result = {"source": str(args.source), "source_sha256": pose.inspection.helper.sha(args.source), "fps": 60,
              "status": "full_frame_numeric_diagnostic_not_runtime_approval", "clips": [], "seams_to_idle": {},
              "comparison_source": str(getattr(args, "comparison_source", "")), "preserved_attack_frames": {}}
    for clip, end_frame in CLIPS.items():
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        samples = []
        worst_body_vertices = []
        for frame in range(1, end_frame + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            if clip == "Attack" and frame in comparison:
                result["preserved_attack_frames"][str(frame)] = differences(snapshot(armature), comparison[frame])
            hand = pose.world_head(armature, armature.pose.bones["hand_r"])
            body_trees = []
            lowest = []
            for obj in body:
                vertices, triangles = review.surface(obj)
                hand_weights = [sum(group.weight for group in vertex.groups if obj.vertex_groups[group.group].name.endswith("_r") and obj.vertex_groups[group.group].name.startswith(("hand", "index", "middle", "ring", "pinky", "thumb"))) for vertex in obj.data.vertices]
                body_trees.append((BVHTree.FromPolygons(vertices, triangles, all_triangles=True), vertices, triangles, hand_weights))
                minimum_index = min(range(len(vertices)), key=lambda index: vertices[index].z)
                lowest.append(vertices[minimum_index].z)
                if vertices[minimum_index].z < -.001:
                    source_vertex = obj.data.vertices[minimum_index]
                    worst_body_vertices.append({"frame": frame, "object": obj.name, "index": minimum_index,
                                                "world_m": list(vertices[minimum_index]), "rest_local": list(source_vertex.co),
                                                "weights": {obj.vertex_groups[group.group].name: group.weight for group in source_vertex.groups}})
            collisions = {}
            weapon_floor = {}
            for obj in weapons:
                vertices, triangles = review.surface(obj)
                weapon_floor[obj.name] = min(point.z for point in vertices)
                tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
                far_pairs = 0
                non_hand_pairs = 0
                all_pairs = 0
                contact_evidence = []
                for body_tree, body_vertices, body_triangles, hand_weights in body_trees:
                    pairs = tree.overlap(body_tree)
                    all_pairs += len(pairs)
                    for weapon_triangle, body_triangle in pairs:
                        center = sum((body_vertices[index] for index in body_triangles[body_triangle]), Vector()) / 3
                        if (center - hand).length > .13:
                            far_pairs += 1
                        triangle_hand_weight = sum(hand_weights[index] for index in body_triangles[body_triangle]) / 3
                        if triangle_hand_weight < .5:
                            non_hand_pairs += 1
                        if frame == 1 and (center - hand).length > .13:
                            contact_evidence.append({"body_triangle": body_triangle, "body_vertices": list(body_triangles[body_triangle]),
                                                     "centroid_distance_from_wrist_m": (center - hand).length,
                                                     "mean_right_hand_finger_weight": triangle_hand_weight})
                collisions[obj.name] = {"all_pairs": all_pairs, "outside_hand_130mm_pairs": far_pairs,
                                        "non_hand_weighted_triangle_pairs": non_hand_pairs, "first_frame_far_contact_evidence": contact_evidence}
            clearance = pose.actual_handle_clearance(body, weapons)["groups"]
            root = armature.pose.bones["root"].matrix_basis
            samples.append({"frame": frame, "time_seconds": (frame - 1) / 60,
                            "body_minimum_z_m": min(lowest), "weapon_minimum_z_m": weapon_floor,
                            "weapon_body_surface_intersections": collisions,
                            "hand_minimum_handle_clearance_mm": min(group["min_clearance_mm"] for group in clearance.values()),
                            "hand_points_penetrating_handle_over_2mm": sum(group["vertices_penetrating_over_2mm"] for group in clearance.values()),
                            "root_matrix_basis_maximum_identity_error": max(abs(root[row][column] - Matrix.Identity(4)[row][column]) for row in range(4) for column in range(4))})
            if frame in {1, end_frame}:
                result["seams_to_idle"][clip + "_" + str(frame)] = differences(snapshot(armature), idle)
        result["clips"].append({"name": clip, "sample_count": len(samples), "samples": samples,
                                 "body_floor_minimum_m": min(sample["body_minimum_z_m"] for sample in samples),
                                 "weapon_floor_minimum_m": min(min(sample["weapon_minimum_z_m"].values()) for sample in samples),
                                 "maximum_outside_hand_triangle_pairs": max(sum(part["outside_hand_130mm_pairs"] for part in sample["weapon_body_surface_intersections"].values()) for sample in samples),
                                 "maximum_non_hand_weighted_triangle_pairs": max(sum(part["non_hand_weighted_triangle_pairs"] for part in sample["weapon_body_surface_intersections"].values()) for sample in samples),
                                 "maximum_head_triangle_pairs": max(sum(part["all_pairs"] for name, part in sample["weapon_body_surface_intersections"].items() if not name.startswith(("shaft", "grip_wrap"))) for sample in samples),
                                 "maximum_hand_points_penetrating_over_2mm": max(sample["hand_points_penetrating_handle_over_2mm"] for sample in samples),
                                 "worst_below_floor_vertices": sorted(worst_body_vertices, key=lambda item: item["world_m"][2])[:12]})
        print("FULL_DIAGNOSTIC " + clip + " " + str(len(samples)), flush=True)
    result["limitations"] = ["All integer animation frames sampled; sub-frame interpolation and engine retarget/import require separate validation.",
                              "Intentional grip triangle intersections are reported, not automatically waived by full-mesh zero-intersection assumptions.",
                              "Outside-hand mask is a 130mm sphere around the actual right wrist, while head/edge/lashing intersections are always counted."]
    pose.inspection.helper.write(args.output / "full_frame_diagnostic.json", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-source", type=Path)
    inspect(parser.parse_args(sys.argv[sys.argv.index("--") + 1:]))


if __name__ == "__main__":
    main()
