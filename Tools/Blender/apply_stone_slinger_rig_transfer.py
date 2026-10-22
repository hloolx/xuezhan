"""Keep the reviewed PBR surface and transfer only the proven cloud rig weights."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspect_stone_slinger_rig as rig
import review_stone_slinger_texture as texture


def evaluated_positions(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices])
    evaluated.to_mesh_clear()
    return points


def set_pose(armatures, commands):
    for armature in armatures:
        for pose_bone in armature.pose.bones:
            pose_bone.matrix_basis = Matrix.Identity(4)
        for name, axis, degrees in commands:
            bone = armature.data.bones.get(name)
            if bone is None:
                raise ValueError("Actual rig lacks requested diagnostic bone: " + name)
            world_axis = Vector(axis)
            local_axis = (armature.matrix_world @ bone.matrix_local).to_3x3().inverted() @ world_axis
            pose_bone = armature.pose.bones[name]
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees))
    bpy.context.view_layer.update()


def check_rest_normals_uv(before, after):
    checks = {"vertex_positions_exact": np.array_equal(before["positions"], after["positions"]),
              "triangle_indices_exact": np.array_equal(before["triangles"], after["triangles"]),
              "triangle_loops_exact": np.array_equal(before["triangle_loops"], after["triangle_loops"]),
              "UVs_exact": np.array_equal(before["uv"], after["uv"]),
              "custom_corner_normals_exact": np.array_equal(before["normals"], after["normals"])}
    if not all(checks.values()):
        raise ValueError("Source surface changed during rig transfer: " + json.dumps(checks))
    return checks


def apply(plan_path, output, diagnose_only=False):
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if plan["status"] != "transfer_correspondence_proven_candidate_not_applied" or plan["source_vertex_corner_weights_inconsistent"]:
        raise ValueError("Unproven or ambiguous transfer plan")
    for label in ("source", "returned", "audit", "mapping"):
        item = plan[label]
        if rig.record(Path(item["path"])) != item:
            raise ValueError("Frozen transfer input changed: " + label)
    mapping = json.loads(Path(plan["mapping"]["path"]).read_text(encoding="utf-8"))
    audit = json.loads(Path(plan["audit"]["path"]).read_text(encoding="utf-8"))
    source_document, _, source_arrays = texture.read_glb(rig.SOURCE)
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.ops.import_scene.fbx(filepath=str(rig.RETURNED), use_anim=True)
    cloud_objects = list(bpy.context.scene.objects)
    cloud_meshes = [obj for obj in cloud_objects if obj.type == "MESH"]
    cloud_armatures = [obj for obj in cloud_objects if obj.type == "ARMATURE"]
    if len(cloud_meshes) != 1 or len(cloud_armatures) != 1:
        raise ValueError("Actual rig object layout changed")
    cloud_body, cloud_rig = cloud_meshes[0], cloud_armatures[0]
    if cloud_rig.animation_data and cloud_rig.animation_data.action:
        raise ValueError("Unexpected received action cannot be discarded silently")
    original_pose_channels = []
    for bone in cloud_rig.pose.bones:
        basis_error = max(abs(bone.matrix_basis[row][column] - (1 if row == column else 0)) for row in range(4) for column in range(4))
        original_pose_channels.append({"bone": bone.name, "scale": list(bone.scale),
                                       "matrix_basis": [list(row) for row in bone.matrix_basis],
                                       "maximum_identity_error": basis_error})
        if basis_error > 1e-6:
            raise ValueError("Received pose is not its rest pose")
    before_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(rig.SOURCE))
    source_objects = [obj for obj in bpy.data.objects if obj not in before_objects]
    source_meshes = [obj for obj in source_objects if obj.type == "MESH"]
    if len(source_meshes) != 1:
        raise ValueError("Reviewed source object layout changed")
    body = source_meshes[0]
    body.name = "StoneSlinger_ReviewedSourceSurface"
    baseline = rig.mesh_snapshot(body)
    gltf_positions = source_arrays["POSITION"][:, (0, 2, 1)] * (1, -1, 1)
    if len(body.data.vertices) != mapping["source_vertex_count"] or np.max(np.linalg.norm(baseline["positions"] - gltf_positions, axis=1)) > 1e-7:
        raise ValueError("GLB-to-Blender source vertex index contract failed")
    if not np.array_equal(baseline["triangles"], source_arrays["indices"]):
        raise ValueError("GLB-to-Blender source triangle index contract failed")
    if max(abs(body.matrix_world[row][column] - (1 if row == column else 0)) for row in range(4) for column in range(4)) > 1e-7:
        raise ValueError("Reviewed source mesh has an unexpected object transform")
    baseline_materials = rig.materials_report([body])
    fit = audit["frame_fit"]
    frame = Matrix.Translation(Vector(fit["translation_m"])) @ Matrix(fit["rotation"]).to_4x4() @ Matrix.Scale(fit["uniform_scale"], 4)
    expected_bones = {bone.name: (frame @ cloud_rig.matrix_world @ bone.head_local,
                                  frame @ cloud_rig.matrix_world @ bone.tail_local) for bone in cloud_rig.data.bones}
    armature = cloud_rig.copy()
    armature.data = cloud_rig.data.copy()
    armature.name = "StoneSlinger_UnitScaleRig"
    bpy.context.scene.collection.objects.link(armature)
    armature.parent = None
    armature.data.transform(frame @ cloud_rig.matrix_world)
    armature.matrix_world = Matrix.Identity(4)
    armature.animation_data_clear()
    for bone in armature.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    armature.show_in_front = True
    cloud_rig.matrix_world = frame @ cloud_rig.matrix_world
    for obj in cloud_objects:
        obj.hide_render = True
    group_names = {name for weights in mapping["source_vertex_weights"].values() for name in weights}
    if group_names - set(armature.data.bones.keys()):
        raise ValueError("A real cloud weight refers to a missing actual bone")
    for name in sorted(group_names):
        body.vertex_groups.new(name=name)
    for index, weights in mapping["source_vertex_weights"].items():
        if abs(sum(weights.values()) - 1) > 1e-5 or len(weights) > 4:
            raise ValueError("Invalid exact transferred weight row")
        for name, weight in weights.items():
            body.vertex_groups[name].add([int(index)], weight, "REPLACE")
    body.parent = armature
    body.matrix_parent_inverse = Matrix.Identity(4)
    body.matrix_basis = Matrix.Identity(4)
    modifier = body.modifiers.new("ActualTripoWeightsOnReviewedSurface", "ARMATURE")
    modifier.object = armature
    modifier.use_vertex_groups = True
    modifier.use_bone_envelopes = False
    bpy.context.view_layer.update()
    after = rig.mesh_snapshot(body)
    checks = check_rest_normals_uv(baseline, after)
    after_materials = rig.materials_report([body])
    checks["material_nodes_and_payload_hashes_exact"] = after_materials == baseline_materials
    bone_errors = {name: {"head_error_m": (armature.matrix_world @ armature.data.bones[name].head_local - expected[0]).length,
                          "tail_error_m": (armature.matrix_world @ armature.data.bones[name].tail_local - expected[1]).length}
                   for name, expected in expected_bones.items()}
    maximum_bone_error = max(error for row in bone_errors.values() for error in row.values())
    rest_positions = evaluated_positions(body)
    rest_error = float(np.linalg.norm(rest_positions - baseline["positions"], axis=1).max())
    source_to_cloud = np.array([mapping["source_render_vertex_to_cloud_vertices"][str(index)][0] for index in range(len(body.data.vertices))])
    actual_received_rest = evaluated_positions(cloud_body)
    original_rest_comparison_error = float(np.linalg.norm(rest_positions - actual_received_rest[source_to_cloud], axis=1).max())
    scales = {bone.name: list(bone.matrix.to_scale()) for bone in armature.pose.bones}
    scale_error = max(abs(value - 1) for scale in scales.values() for value in scale)
    scale_details = [{"bone": bone.name, "parent": bone.parent.name if bone.parent else None,
                      "pose_scale_channels": list(bone.scale), "pose_basis_scale": list(bone.matrix_basis.to_scale()),
                      "pose_world_matrix_scale": scales[bone.name],
                      "rest_matrix_scale": list(armature.data.bones[bone.name].matrix_local.to_scale()),
                      "pose_vs_rest_matrix_maximum_error": max(abs(bone.matrix[row][column] - armature.data.bones[bone.name].matrix_local[row][column]) for row in range(4) for column in range(4))}
                     for bone in armature.pose.bones]
    checks.update({"unit_armature_object_scale": max(abs(value - 1) for value in armature.scale) < 1e-7,
                   "all_pose_scale_channels_unit": max(abs(value - 1) for row in scale_details for value in row["pose_scale_channels"]) < 1e-7,
                   "all_pose_basis_scales_unit": max(abs(value - 1) for row in scale_details for value in row["pose_basis_scale"]) < 1e-7,
                   "root_world_matrix_scale_unit": max(abs(value - 1) for row in scale_details if row["parent"] is None for value in row["pose_world_matrix_scale"]) < 1e-6,
                   "physical_rest_bone_locations_preserved": maximum_bone_error < 1e-6,
                   "actual_skin_rest_surface_preserved": rest_error < 2e-6,
                   "source_vs_original_received_rest_skin_within3micrometers": original_rest_comparison_error < 3e-6})
    report = {"asset_id": "Unit_StoneSlinger", "status": "candidate_numeric_review_in_progress", "source": rig.record(rig.SOURCE),
              "cloud_rig": rig.record(rig.RETURNED), "plan": rig.record(plan_path), "mapping": plan["mapping"],
              "script": rig.record(Path(__file__)), "checks": checks, "bone_errors": bone_errors,
              "maximum_rest_bone_location_error_m": maximum_bone_error, "maximum_rest_skin_error_m": rest_error,
              "maximum_source_vs_original_received_rest_skin_error_m": original_rest_comparison_error,
              "maximum_rest_bone_scale_error": scale_error, "actual_bone_count": len(armature.data.bones),
              "bone_scale_diagnostic": scale_details,
              "received_rest_pose_channels_before_canonicalization": original_pose_channels,
              "rest_pose_canonicalization_scope": "Only the new candidate copy: verified near-identity FBX pose bases (maximum1e-6) set exactlyIdentity. Received rig, bone rest geometry, weights and source surface remain untouched. Original evaluated surface comparison retains3micrometer gate.",
              "source_materials": baseline_materials, "source_native_split_pairs": plan["six_cleaned_split_pairs"],
              "cloud_remerged_bowtie_not_reused": plan["cloud_vertices_merging_distinct_native_vertices"],
              "weight_averaging_performed": False, "weights_corrected": False, "source_geometry_modified": False,
              "normal_or_texture_repair_performed": False, "production_approved": False}
    rig.save(output / "transfer_report.json", report)
    if diagnose_only:
        print(json.dumps({"status": "scale_diagnostic_only_no_export_or_render", "root": [row for row in scale_details if row["parent"] is None],
                          "maximum_world_matrix_scale_error": scale_error,
                          "maximum_channel_scale_error": max(abs(value - 1) for row in scale_details for value in row["pose_scale_channels"])}))
        return
    if not all(checks.values()):
        raise ValueError("Candidate rest preservation gates failed")
    poses = {"rest": [],
             "upper_limb": [("upperarm_l", (1, 0, 0), 12), ("upperarm_r", (1, 0, 0), -12),
                            ("lowerarm_l", (0, 1, 0), 18), ("lowerarm_r", (0, 1, 0), 18)],
             "ankle_both": [("foot_l", (0, 1, 0), -10), ("foot_r", (0, 1, 0), -10)],
             "knee_both": [("calf_l", (0, 1, 0), 15), ("calf_r", (0, 1, 0), 15)]}
    pose_checks = []
    cloud_low = [row for row in audit["skeleton"]["weights"][0]["all_vertex_weights"] if row["world_review_m"][2] < .025]
    for label, commands in poses.items():
        set_pose([armature, cloud_rig], commands)
        actual = evaluated_positions(body)
        control = evaluated_positions(cloud_body)
        errors = np.linalg.norm(actual - control[source_to_cloud], axis=1)
        low_rows = []
        for row in cloud_low:
            index = int(np.flatnonzero(source_to_cloud == row["vertex"])[0])
            rest_point = Vector(baseline["positions"][index])
            foot_name = "foot_l" if rest_point.y > 0 else "foot_r"
            ideal = armature.pose.bones[foot_name].matrix @ armature.data.bones[foot_name].matrix_local.inverted() @ rest_point
            low_rows.append({"cloud_vertex": row["vertex"], "source_vertex": index, "weights": row["weights"],
                             "dominant_bone": max(row["weights"], key=row["weights"].get),
                             "actual_world_m": actual[index].tolist(), "ideal_single_foot_rigid_world_m": list(ideal),
                             "distance_from_rigid_foot_m": float(np.linalg.norm(actual[index] - np.array(ideal)))})
        check = {"pose": label, "commands": commands, "actual_source_vertices_compared": len(actual),
                 "maximum_source_vs_cloud_evaluated_surface_error_m": float(errors.max()),
                 "mean_source_vs_cloud_error_m": float(errors.mean()), "candidate_minimum_z_m": float(actual[:, 2].min()),
                 "lowest154_cloud_vertex_diagnostic": low_rows,
                 "passed_surface_transfer": bool(errors.max() < 3e-6)}
        pose_checks.append(check)
        if not check["passed_surface_transfer"]:
            report["pose_checks"] = pose_checks
            rig.save(output / "transfer_report.json", report)
            raise ValueError("Transferred weights diverge from actual cloud rig under diagnostic pose")
    report["pose_checks"] = pose_checks
    set_pose([armature, cloud_rig], [])
    for obj in cloud_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    prep = rig.module("slinger_transfer_prep", "prepare_tripo_character.py")
    bpy.context.scene.world = bpy.data.worlds.new("SlingerTransferredPBRReviewWorld")
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    prep.render_setup(samples=8)
    images = []
    for name, direction in prep.overview_views()[:4]:
        path = output / ("rest_" + name + ".png")
        prep.render_view(path, [body], direction, size=512)
        images.append(rig.record(path))
    for name, direction in (("neck_front", (.8, 1, .15)), ("neck_back", (-.8, 1, .1))):
        path = output / (name + ".png")
        prep.render_view(path, [body], direction, size=512, target=(.005, .085, 1.188), framing=.24)
        images.append(rig.record(path))
    for label in ("ankle_both", "knee_both"):
        set_pose([armature], poses[label])
        for side, name in ((1, "left"), (-1, "right")):
            path = output / (label + "_" + name + ".png")
            prep.render_view(path, [body], (1, side, .3), size=512, target=(-.02, side * .23, .14), framing=.46)
            images.append(rig.record(path))
    set_pose([armature], [])
    check_rest_normals_uv(baseline, rig.mesh_snapshot(body))
    report.update({"status": "source_PBR_rig_transfer_numeric_passed_pending_visual_and_weight_correction_review",
                   "images": images, "final_bounds_m": {"min": list(prep.bounds([body])[0]), "max": list(prep.bounds([body])[1])},
                   "actual_final_statistics": prep.mesh_stats([body]),
                   "actual_final_skeleton": rig.skeleton_report([armature], [body], None),
                   "diagnostic_control_removed_from_saved_candidate": True,
                   "heel_weight_or_grip_or_animation_approved": False})
    blend = output / "Unit_StoneSlinger_ReviewedSurface_RealRig.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"] = rig.record(blend)
    for label in ("source", "returned", "audit", "mapping"):
        item = plan[label]
        if rig.record(Path(item["path"])) != item:
            raise ValueError("Frozen input was modified")
    rig.save(output / "transfer_report.json", report)
    print(json.dumps({"status": report["status"], "images": len(images), "max_rest_error_m": rest_error,
                      "pose_max_errors_m": {row["pose"]: row["maximum_source_vs_cloud_evaluated_surface_error_m"] for row in pose_checks}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnose-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output, plan = args.output.resolve(), args.plan.resolve()
    if output.exists():
        raise FileExistsError("Use a fresh candidate directory")
    apply(plan, output, args.diagnose_only)


if __name__ == "__main__":
    main()
