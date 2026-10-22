"""Render bounded true-pad sling diagnostics without approving failed candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_stone_slinger_sling_pilot as base
import refine_stone_slinger_sling_diameter as diameter


def set_rotation_channels(armature, name, rotation):
    bone = armature.pose.bones[name]
    rest = armature.data.bones[name]
    parent = armature.pose.bones.get(rest.parent.name) if rest.parent else None
    inherited = armature.matrix_world @ (parent.matrix @ rest.parent.matrix_local.inverted() if parent else Matrix.Identity(4)) @ rest.matrix_local
    quaternion = inherited.to_quaternion().inverted() @ rotation
    quaternion.normalize()
    bone.rotation_mode = "QUATERNION"
    bone.location = (0, 0, 0)
    bone.rotation_quaternion = quaternion
    bone.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def pad_diagnostics(actual, triangles, pad_ids, weapon):
    cord_points, cord_triangles = base.evaluated_snapshot(weapon["cord_P1"])
    centers = cord_points.reshape(11, 8, 3).mean(axis=1)
    center = centers[:2].mean(axis=0)
    axis = base.plan_math.normalize(centers[0] - centers[1])
    result, radials = {}, []
    for finger, ids in pad_ids.items():
        samples, normals = diameter.joint.face_samples(actual, triangles[ids])
        distances, closest = diameter.joint.nearest_surface(samples, cord_points[cord_triangles])
        chosen = int(np.argmin(distances))
        delta = closest[chosen] - center
        radial = base.plan_math.normalize(delta - axis * np.dot(delta, axis))
        radials.append(radial)
        result[finger] = {"triangle": int(ids[chosen]), "barycentric": [1 / 3] * 3, "distance_m": float(distances[chosen]),
                          "world_m": samples[chosen].tolist(), "normal_dot_outward_radial": float(np.dot(normals[chosen], radial))}
    result["opposed_radial_dot"] = float(np.dot(*radials))
    result["checks"] = {"true03_pad_faces_contact_within2mm": max(result[finger]["distance_m"] for finger in pad_ids) <= .002,
                        "opposed_radial_dot_at_most_minus0p5": result["opposed_radial_dot"] <= -.5,
                        "pad_normals_face_cord": all(result[finger]["normal_dot_outward_radial"] <= -.3 for finger in pad_ids)}
    return result


def camera_candidates(actual, triangles, armature, plan, hand_ids, pad_ids):
    tree = BVHTree.FromPolygons(actual.tolist(), triangles.tolist(), all_triangles=True)
    hand_delta = (base.bone_world(armature, "hand_r") @ armature.data.bones["hand_r"].matrix_local.inverted()).to_3x3()
    across = hand_delta @ Vector(plan["hand_frame"]["across"])
    longitudinal = hand_delta @ Vector(plan["hand_frame"]["longitudinal"])
    palm = hand_delta @ Vector(plan["hand_frame"]["palm"])
    target = actual[hand_ids].mean(axis=0)
    pad_points = {finger: actual[triangles[ids]].mean(axis=1) for finger, ids in pad_ids.items()}
    selected = []
    for side in (-1, 1):
        choices = []
        for around in (.45, .9, 1.4):
            for below in (.3, .8, 1.3):
                direction = (palm + across * around * side + longitudinal * below).normalized()
                camera = Vector(target) + direction * 3
                visible = {}
                for finger, points in pad_points.items():
                    count = 0
                    for point in points:
                        delta = Vector(point) - camera
                        hit, _, _, distance = tree.ray_cast(camera, delta.normalized(), delta.length + .001)
                        if hit is None or distance >= delta.length - .0005:
                            count += 1
                    visible[finger] = {"visible_face_centers": count, "tested": len(points)}
                score = sum(row["visible_face_centers"] for row in visible.values())
                choices.append({"direction": list(direction), "visible_actual03_faces": visible, "score": score})
        selected.append(max(choices, key=lambda row: row["score"]))
    return selected


def execute(comparison_path, output):
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    for key in ("source", "weapon"):
        if base.rig.record(Path(comparison[key]["path"])) != comparison[key]:
            raise ValueError("Immutable input mismatch: " + key)
    plan_path = base.plan_math.BRANCH / "preparation_05/grip_preparation.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["source"] != comparison["source"] or plan["weapon"] != comparison["weapon"]:
        raise ValueError("Comparison lineage does not match the original preparation")
    if len(comparison["best_candidates"]) != 3:
        raise ValueError("This final diagnostic batch requires exactly three frozen candidates")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=plan["source"]["path"])
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(bodies) != 1 or len(armatures) != 1:
        raise ValueError("Expected approved single body/armature")
    body, armature = bodies[0], armatures[0]
    base.transfer.set_pose([armature], [])
    baseline = base.rig.mesh_snapshot(body)
    weights = base.foot.weights_of(body)
    normals = base.foot.encoded_normals(body.data)
    materials = base.rig.materials_report([body])
    bones_before = base.foot.rest_bones(armature)
    weapon, weapon_baseline, _ = base.append_existing_weapon(plan)
    source_world = Matrix(np.array(plan["weapon_basis_columns"]).tolist()).to_4x4()
    source_world.translation = Vector(plan["terminal_root_rest_m"])
    mount = base.bone_world(armature, "hand_r").inverted() @ source_world
    socket = bpy.data.objects.new("weapon_r", None)
    bpy.context.scene.collection.objects.link(socket)
    socket.parent, socket.parent_type, socket.parent_bone = armature, "BONE", "hand_r"
    bpy.context.view_layer.update()
    socket.matrix_world = source_world
    bpy.context.view_layer.update()
    weapon["Weapon_Sling"].parent = socket
    weapon["Weapon_Sling"].matrix_parent_inverse = Matrix.Identity(4)
    weapon["Weapon_Sling"].matrix_basis = Matrix.Identity(4)
    prior = json.loads(Path(plan["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    bones = prior["actual_final_skeleton"]["armatures"][0]["bones"]
    mapping = json.loads(Path(prior["mapping"]["path"]).read_text(encoding="utf-8"))
    native_ids = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(weights))])
    pads = {finger: diameter.joint.pad_faces(finger, baseline["positions"], baseline["triangles"], weights, bones, np.array(plan["hand_frame"]["palm"])) for finger in ("index", "thumb")}
    source_triangles = base.plan_math.texture.read_glb(base.rig.SOURCE)[2]["indices"]
    if not np.array_equal(source_triangles, baseline["triangles"]):
        raise ValueError("Local pad-face IDs require explicit new mapping; no array assumption")
    base.set_bone_world_rotation = set_rotation_channels
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    renderer = base.rig.module("slinger_joint_review_render", "prepare_tripo_character.py")
    renderer.render_setup(samples=8)
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    report = {"asset_id": "Unit_StoneSlinger", "status": "actual_joint_pinch_diagnostics_not_approved", "script": base.rig.record(Path(__file__)),
              "comparison": base.rig.record(comparison_path), "source": plan["source"], "weapon_source": plan["weapon"], "candidates": [], "images": [],
              "scope": "Three bounded8mm derivative terminal comparisons at the same limited idle pose. No new gait, attack, weights, garment repair, UV or PBR change.",
              "grip_approved": False, "gait_approved": False, "production_approved": False}
    report_path = output / "joint_pinch_report.json"
    for index, candidate in enumerate(comparison["best_candidates"]):
        for name, field in (("cord_N1", "retained"), ("cord_P1", "released")):
            path = candidate[field]["path"]
            vertices, _ = diameter.transported_tube(path, candidate["diameter_mm"] / 2000)
            for vertex, point in zip(weapon[name].data.shape_keys.key_blocks["GripReady"].data, vertices):
                vertex.co = point
            if name == "cord_P1":
                weapon[name].data.shape_keys.key_blocks["ReleaseTerminal"].value = 0
            terminal = "retained_terminal" if name == "cord_N1" else "release_terminal"
            weapon[terminal].location = path[0]
        modified_plan = dict(plan, initial_grip_commands=candidate["commands"])
        arms = base.pose(armature, modified_plan, "idle")
        actual, triangles = base.evaluated_snapshot(body)
        grip, hand_ids = base.actual_grip(actual, triangles, weights, weapon, modified_plan)
        full_hand_ids = np.array([vertex for vertex, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "thumb_", "index_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
        hand_faces = np.flatnonzero(np.all(np.isin(triangles, full_hand_ids), axis=1))
        certifications = {}
        for name in ("cord_N1", "cord_P1"):
            points, cord_faces = base.evaluated_snapshot(weapon[name])
            certifications[name] = diameter.certify_triangle_interiors(actual, triangles, hand_faces, points, cord_faces)
            certifications[name]["actual_triangle_intersections"] = diameter.mesh_crossings(actual, triangles, hand_faces, points, cord_faces)
            certifications[name]["actual_self_crossings"] = diameter.joint.pair_crossings(points, cord_faces, np.arange(len(cord_faces)), np.arange(len(cord_faces)), np.arange(len(points)))
        pad = pad_diagnostics(actual, triangles, pads, weapon)
        whole_hand = base.foot.exact_intersections(actual, triangles, native_ids, np.flatnonzero(np.any(np.isin(triangles, hand_ids), axis=1)))
        digit_faces = {}
        for finger in pads:
            weighted = np.array([sum(value for name, value in row.items() if name.startswith(finger + "_") and name.endswith("_r")) > .4 for row in weights])
            digit_faces[finger] = np.flatnonzero(np.any(weighted[triangles], axis=1))
        interdigit = diameter.joint.pair_crossings(actual, triangles, digit_faces["index"], digit_faces["thumb"], native_ids)
        matrices = {bone.name: np.array(base.bone_world(armature, bone.name) @ armature.data.bones[bone.name].matrix_local.inverted()) for bone in armature.pose.bones}
        homogeneous = np.column_stack((baseline["positions"], np.ones(len(actual))))
        predicted = np.array([sum((matrices[bone] @ point)[:3] * value for bone, value in row.items()) for point, row in zip(homogeneous, weights)])
        channel_exact = all(tuple(bone.scale) == (1, 1, 1) for bone in armature.pose.bones)
        cameras = camera_candidates(actual, triangles, armature, modified_plan, hand_ids, pads)
        cuff_pairs, other_hand_pairs = [], []
        interdigit_pairs = {tuple(sorted(value[:2])) for value in interdigit}
        for pair in whole_hand["proper_crossing_pairs"]:
            if tuple(sorted(pair)) in interdigit_pairs:
                continue
            lowerarm_influence = max(sum(value for name, value in weights[int(vertex)].items() if name.startswith("lowerarm") and name.endswith("_r")) for triangle in pair for vertex in triangles[triangle])
            (cuff_pairs if lowerarm_influence > .15 else other_hand_pairs).append(pair)
        orientation = base.geometry.triangle_orientation(baseline["positions"], actual, triangles, base.foot.weight_linear(weights, matrices))
        garment_negative = [{"triangle": triangle, "rest_center_m": baseline["positions"][triangles[triangle]].mean(axis=0).tolist(),
                             "actual_world_vertices_m": actual[triangles[triangle]].tolist(), "original_unchanged_weights": [weights[int(vertex)] for vertex in triangles[triangle]]}
                            for triangle in orientation["negative_triangles"] if .78 < baseline["positions"][triangles[triangle], 2].mean() < .92]
        entry = {"index": index, "candidate_name": "candidate_" + str(index + 1), "diameter_mm": candidate["diameter_mm"], "true_pad_faces": pad, "actual_closed_cord_interiors": certifications,
                 "preserved_pure_diagnostic_failures": {field: {"checks": candidate[field]["checks"], "full_interior_certification": candidate[field]["full_interior_certification"]} for field in ("retained", "released")},
                 "actual_index_thumb_crossings": interdigit, "actual_wrist_cuff_crossing_pairs": cuff_pairs, "other_hand_crossing_pairs": other_hand_pairs,
                 "crossing_classification_rule": "Record all actual pairs; after explicit index-thumb separation, pairs touching lowerarm_r/lowerarm_twist weights>0.15 classified as wrist/cuff. Classification never waives intersection failures.",
                 "garment_negative_orientation_diagnosis_only": garment_negative,
                 "actual_skin_prediction_max_m": float(np.linalg.norm(actual - predicted, axis=1).max()),
                 "explicit_pose_scale_channels_exactly_one": channel_exact, "scale_diagnostic": base.foot.scale_diagnostic(armature), "arms": arms,
                 "body_orientation": orientation,
                 "actual_weapon_mount_matrix_error": max(abs(value) for row in (weapon["Weapon_Sling"].matrix_world - base.bone_world(armature, "hand_r") @ mount) for value in row),
                 "camera_visibility": cameras, "actual_grip_vertex_and_triangle_diagnostics": grip, "approved": False}
        report["candidates"].append(entry)
        base.rig.save(report_path, report)
        if not channel_exact or entry["actual_skin_prediction_max_m"] > 3e-6 or entry["actual_weapon_mount_matrix_error"] > 3e-6:
            raise ValueError("Exact scale channels/physical evaluation contract failed before rendering")
        if any(camera["score"] == 0 for camera in cameras):
            raise ValueError("No nonoccluded actual distal-pad camera among the bounded camera directions")
        if any(not any(camera["visible_actual03_faces"][finger]["visible_face_centers"] for camera in cameras) for finger in pads):
            raise ValueError("The paired cameras must show both true distal pads rather than a forearm proxy")
        for view_index, camera in enumerate(cameras):
            target, framing, _ = base.framing_math.orthographic_frame(actual[hand_ids], camera["direction"], padding=1.4)
            image = output / ("candidate_" + str(index + 1) + "_pad_" + str(view_index + 1) + ".png")
            renderer.render_view(image, [body] + [obj for obj in weapon.values() if obj.type == "MESH"], camera["direction"], size=512, framing=framing, target=target.tolist())
            report["images"].append(base.rig.record(image))
        blend = output / ("Unit_StoneSlinger_SlingDiagnostic_" + str(index + 1) + ".blend")
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        entry["blend"] = base.rig.record(blend)
        base.rig.save(report_path, report)
    report["preservation"] = base.transfer.check_rest_normals_uv(baseline, base.rig.mesh_snapshot(body))
    report["preservation"].update({"all_body_weights_exact": weights == base.foot.weights_of(body), "encoded_normals_exact": normals == base.foot.encoded_normals(body.data),
                                    "body_PBR_exact": materials == base.rig.materials_report([body]), "rest_bones_exact": bones_before == base.foot.rest_bones(armature),
                                    "original_weapon_Basis_Draw_UV_geometry_exact": all(base.local_weapon_data(weapon[name]) == value for name, value in weapon_baseline.items()),
                                    "frozen_body_file_unchanged": base.rig.record(Path(plan["source"]["path"])) == plan["source"],
                                    "frozen_weapon_file_unchanged": base.rig.record(Path(plan["weapon"]["path"])) == plan["weapon"]})
    if not all(report["preservation"].values()):
        raise ValueError("Immutable source preservation failed")
    base.rig.save(report_path, report)
    print(json.dumps({"status": report["status"], "images": len(report["images"]), "candidates": len(report["candidates"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    execute(Path(args.comparison).resolve(), Path(args.output).resolve())
