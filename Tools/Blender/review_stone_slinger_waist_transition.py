"""One controlled actual waist comparison; preserve all unrelated body data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_stone_slinger_joint_pinch as prior
import plan_stone_slinger_waist_transition as candidate_math


base = prior.base


def assign_rows(body, rows):
    for vertex, weights in rows.items():
        names = [body.vertex_groups[membership.group].name for membership in body.data.vertices[vertex].groups]
        for name in names:
            body.vertex_groups[name].remove([vertex])
        for name, value in weights.items():
            body.vertex_groups[name].add([vertex], value, "REPLACE")
    body.data.update()
    bpy.context.view_layer.update()


def source_checks(body, armature, baseline, normals, materials, bones, weights, changed_vertices):
    actual = base.foot.weights_of(body)
    checks = base.transfer.check_rest_normals_uv(baseline, base.rig.mesh_snapshot(body))
    checks.update({"encoded_normals_exact": normals == base.foot.encoded_normals(body.data),
                   "body_PBR_exact": materials == base.rig.materials_report([body]),
                   "rest_bones_exact": bones == base.foot.rest_bones(armature),
                   "all_other_weights_exact": all(row == actual[index] for index, row in enumerate(weights) if index not in changed_vertices)})
    return checks


def actual_diagnostic(body, armature, positions, triangles, before, after, original, modified, native, changed_faces, face_ids):
    matrices = {bone.name: np.array(base.bone_world(armature, bone.name) @ armature.data.bones[bone.name].matrix_local.inverted()) for bone in armature.pose.bones}
    predicted_before, before_linear = candidate_math.previous.local_skin(positions, original, matrices)
    predicted_after, after_linear = candidate_math.previous.local_skin(positions, modified, matrices)
    before_orientation = base.geometry.triangle_orientation(positions, before, triangles, before_linear)
    after_orientation = base.geometry.triangle_orientation(positions, after, triangles, after_linear)
    first_crossings = candidate_math.changed_face_crossings(before, triangles, native, changed_faces)
    second_crossings = candidate_math.changed_face_crossings(after, triangles, native, changed_faces)
    changes = {index for index, row in enumerate(original) if row != modified[index]}
    unchanged = [index for index in range(len(original)) if index not in changes]
    changed_native = {int(native[index]) for index in changes}
    seam_error = max(float(np.max(np.linalg.norm(after[native == identifier] - after[np.flatnonzero(native == identifier)[0]], axis=1))) for identifier in changed_native)
    result = {"whole_model_before": before_orientation, "whole_model_after": after_orientation,
              "new_negative_triangles": sorted(set(after_orientation["negative_triangles"]) - set(before_orientation["negative_triangles"])),
              "waist_negative_triangles_after": sorted(set(after_orientation["negative_triangles"]) & set(face_ids)),
              "unchanged_outside_negative_triangles": sorted((set(before_orientation["negative_triangles"]) & set(after_orientation["negative_triangles"])) - set(face_ids)),
              "changed_faces_against_all_body_before": first_crossings, "changed_faces_against_all_body_after": second_crossings,
              "new_intersection_pairs": sorted(set(map(tuple, second_crossings)) - set(map(tuple, first_crossings))),
              "intersection_scope": "All actual triangles incident to changed vertices versus every10770 actual bodytriangle. Unchanged outside triangles cannot create a new outside/outside intersection.",
              "maximum_body_displacement_mm": float(np.linalg.norm(after - before, axis=1).max() * 1000),
              "unchanged_vertices_max_error_m": float(np.linalg.norm(after[unchanged] - before[unchanged], axis=1).max()),
              "actual_LBS_error_before_m": float(np.linalg.norm(predicted_before - before, axis=1).max()),
              "actual_LBS_error_after_m": float(np.linalg.norm(predicted_after - after, axis=1).max()),
              "UV_duplicate_seam_gap_m": seam_error,
              "scale_channels_exactly_one": all(tuple(bone.scale) == (1, 1, 1) for bone in armature.pose.bones),
              "local_edge_strain": candidate_math.strain_report(positions, before, after, triangles, face_ids, native)}
    result["local_safety_checks"] = {"no_new_full_model_negative_triangles": not result["new_negative_triangles"],
                                     "no_remaining_waist_negative_triangles": not result["waist_negative_triangles_after"],
                                     "no_new_full_model_intersections": not result["new_intersection_pairs"],
                                     "unchanged_other_surface_within3micrometers": result["unchanged_vertices_max_error_m"] <= 3e-6,
                                     "actual_LBS_within3micrometers": max(result["actual_LBS_error_before_m"], result["actual_LBS_error_after_m"]) <= 3e-6,
                                     "UV_duplicates_within0p1micrometer": seam_error <= 1e-7,
                                     "pose_scale_channels_exactly_one": result["scale_channels_exactly_one"]}
    result["whole_model_zero_negative_triangles"] = not after_orientation["negative_triangles"]
    return result


def execute(spec_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for record in [spec["script"], spec["plan"], spec["source"]] + spec["dependencies"]:
        if base.rig.record(Path(record["path"])) != record:
            raise ValueError("Frozen dependency mismatch: " + record["path"])
    plan = json.loads(Path(spec["plan"]["path"]).read_text(encoding="utf-8"))
    output = Path(spec["output"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if plan["source"] != spec["source"] or plan["changed_native_count"] != 9 or plan["changed_render_count"] != 20:
        raise ValueError("This diagnostic is only the one fixed9native/20render candidate")
    if len(plan["region_native_vertices"]) != 26 or len(plan["region_face_ids"]) != 35:
        raise ValueError("Authorized region changed")
    bpy.ops.wm.open_mainfile(filepath=spec["source"]["path"])
    body, = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armature, = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    base.transfer.set_pose([armature], [])
    baseline = base.rig.mesh_snapshot(body)
    original = base.foot.weights_of(body)
    normals = base.foot.encoded_normals(body.data)
    materials = base.rig.materials_report([body])
    bones = base.foot.rest_bones(armature)
    mapping = json.loads(Path(plan["mapping"]["path"]).read_text(encoding="utf-8"))
    native = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(original))])
    triangles = base.plan_math.texture.read_glb(base.rig.SOURCE)[2]["indices"].astype(int)
    original_rows, modified_rows = {}, {}
    for change in plan["exact_weight_changes"]:
        vertex = change["vertex"]
        if original[vertex] != change["before"] or int(native[vertex]) != change["native_vertex"]:
            raise ValueError("Actual original weight/native identity mismatch")
        original_rows[vertex], modified_rows[vertex] = original[vertex], change["after"]
    changed_vertices = set(original_rows)
    changed_faces = np.array(plan["changed_face_ids"])
    face_ids = np.array(plan["region_face_ids"])
    loop = json.loads(Path(plan["loop_plan"]["path"]).read_text(encoding="utf-8"))
    prep = json.loads(Path(plan["pose_preparation"]["path"]).read_text(encoding="utf-8"))
    pose_plan = dict(prep, initial_grip_commands=loop["commands"])
    base.set_bone_world_rotation = prior.set_rotation_channels
    assign_rows(body, modified_rows)
    modified = base.foot.weights_of(body)
    actual_changes = [{"vertex": index, "native_vertex": int(native[index]), "before": original[index], "requested_after": modified_rows[index],
                       "actual_after_float32": modified[index], "actual_delta": {name: modified[index].get(name, 0.) - original[index].get(name, 0.) for name in original[index]}} for index in sorted(changed_vertices)]
    rounding_error = max(abs(modified[index].get(name, 0.) - value) for index, row in modified_rows.items() for name, value in row.items())
    mass_error = max(abs(sum(original[index].values()) - sum(modified[index].values())) for index in changed_vertices)
    report = {"asset_id": "Unit_StoneSlinger", "status": "actual_fixed_candidate_pending_local_visual_review", "spec": base.rig.record(spec_path),
              "source": spec["source"], "plan": spec["plan"], "actual_weight_changes": actual_changes,
              "maximum_weight_rounding_error": rounding_error, "maximum_weight_mass_error": mass_error,
              "original_full_zero_gate_result_preserved": plan["checks"]["no_negative_triangles_remaining"],
              "poses": [], "images": [], "local_waist_approved": False, "whole_body_approved": False,
              "grip_motion_approved": False, "gait_approved": False, "production_approved": False,
              "scope": "One existing fixed harmonic field, no new candidate search. Frozen foot weights/PBR/mesh/rig preserved; only20render/9native torso/leg weights changed. Existing wrist/cuff failures remain separately reported."}
    report_path = output / "waist_transition_report.json"
    report["source_preservation_before_poses"] = source_checks(body, armature, baseline, normals, materials, bones, original, changed_vertices)
    base.rig.save(report_path, report)
    if not all(report["source_preservation_before_poses"].values()) or max(rounding_error, mass_error) > 1e-7:
        raise ValueError("Preservation or exact planned weight conversion failed")
    captures = {}
    for name in ("idle", "move_A", "move_B"):
        assign_rows(body, original_rows)
        arms = base.pose(armature, pose_plan, name)
        before, actual_triangles = base.evaluated_snapshot(body)
        if not np.array_equal(actual_triangles, triangles):
            raise ValueError("Actual triangle identities changed")
        assign_rows(body, modified_rows)
        after, actual_triangles = base.evaluated_snapshot(body)
        if not np.array_equal(actual_triangles, triangles):
            raise ValueError("Candidate triangle identities changed")
        row = actual_diagnostic(body, armature, baseline["positions"], triangles, before, after, original, modified, native, changed_faces, face_ids)
        row.update({"pose": name, "arms": arms})
        report["poses"].append(row)
        base.rig.save(report_path, report)
        if not row["scale_channels_exactly_one"] or max(row["actual_LBS_error_before_m"], row["actual_LBS_error_after_m"]) > 3e-6:
            raise ValueError("Actual source/transform model failed; preserve diagnostic and stop before rendering")
        captures[name] = (before, after)
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    renderer = base.rig.module("slinger_waist_renderer", "prepare_tripo_character.py")
    renderer.render_setup(samples=8)
    bpy.context.scene.render.threads_mode, bpy.context.scene.render.threads = "FIXED", 2
    direction = [-.35, -1., .12]
    frame_ids = np.unique(triangles[face_ids])
    for name in ("idle", "move_A"):
        before, after = captures[name]
        frame_points = np.concatenate((before[frame_ids], after[frame_ids]))
        target, framing, _ = base.framing_math.orthographic_frame(frame_points, direction, padding=1.55)
        framing = max(framing, .14)
        for stage, rows in (("before", original_rows), ("after", modified_rows)):
            assign_rows(body, rows)
            base.pose(armature, pose_plan, name)
            path = output / (name + "_" + stage + ".png")
            renderer.render_view(path, [body], direction, size=512, framing=framing, target=target.tolist())
            report["images"].append({**base.rig.record(path), "pose": name, "stage": stage, "target_m": target.tolist(), "framing_m": framing})
            base.rig.save(report_path, report)
    assign_rows(body, modified_rows)
    base.transfer.set_pose([armature], [])
    report["final_preservation"] = source_checks(body, armature, baseline, normals, materials, bones, original, changed_vertices)
    report["final_preservation"]["frozen_source_file_exact"] = base.rig.record(Path(spec["source"]["path"])) == spec["source"]
    report["final_preservation"]["only_requested_twenty_rows_changed"] = base.foot.weights_of(body) == modified
    report["all_local_numeric_safety_checks_passed"] = all(all(row["local_safety_checks"].values()) for row in report["poses"])
    report["whole_model_zero_negative_triangles"] = all(row["whole_model_zero_negative_triangles"] for row in report["poses"])
    report["edge_strain_visual_review_required"] = True
    base.rig.save(report_path, report)
    if not all(report["final_preservation"].values()):
        raise ValueError("Final preservation failed")
    path = output / "Unit_StoneSlinger_LocalWaistWeights.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    report["blend"] = base.rig.record(path)
    base.rig.save(report_path, report)
    print(json.dumps({"status": report["status"], "images": len(report["images"]), "local_numeric": report["all_local_numeric_safety_checks_passed"],
                      "whole_model_zero_negative": report["whole_model_zero_negative_triangles"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    execute(Path(arguments.spec).resolve())
