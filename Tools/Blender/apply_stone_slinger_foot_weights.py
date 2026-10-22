"""Apply one audited local sole-weight candidate without editing its surface."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import bpy
from mathutils.bvhtree import BVHTree
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_stone_slinger_rig_transfer as transfer
import inspect_stone_slinger_rig as rig
import plan_stone_slinger_foot_weights as plan_math
import stone_slinger_foot_math as geometry


PLAN_SHA = "c50d9fe602efebb83a94793c68f34deade007fb99df560b3398b08ec71bdb86c"


def weights_of(body):
    names = {group.index: group.name for group in body.vertex_groups}
    return [{names[group.group]: group.weight for group in vertex.groups} for vertex in body.data.vertices]


def rest_bones(armature):
    return [{"name": bone.name, "parent": bone.parent.name if bone.parent else None,
             "matrix": [list(row) for row in bone.matrix_local], "head": list(bone.head_local),
             "tail": list(bone.tail_local), "deform": bone.use_deform} for bone in armature.data.bones]


def encoded_normals(mesh):
    attribute = mesh.attributes.get("custom_normal")
    if attribute is None or not attribute.data:
        raise ValueError("Expected source encoded corner-normal attribute is missing")
    properties = [prop.identifier for prop in attribute.data[0].bl_rna.properties
                  if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
    if len(properties) != 1:
        raise ValueError("Cannot identify actual encoded custom-normal property")
    values = [list(getattr(item, properties[0])) for item in attribute.data]
    return {"type": attribute.data_type, "domain": attribute.domain, "property": properties[0], "values": values}


def scale_diagnostic(armature):
    rows = [{"bone": bone.name, "parent": bone.parent.name if bone.parent else None,
             "channel": list(bone.scale), "basis": list(bone.matrix_basis.to_scale()),
             "world": list((armature.matrix_world @ bone.matrix).to_scale())} for bone in armature.pose.bones]
    checks = {"armature_object_unit_scale": max(abs(value - 1) for value in armature.scale) < 1e-7,
              "pose_channels_unit_scale": max(abs(value - 1) for row in rows for value in row["channel"]) < 1e-7,
              "pose_basis_unit_scale": max(abs(value - 1) for row in rows for value in row["basis"]) < 1e-7,
              "root_world_unit_scale": max(abs(value - 1) for row in rows if row["parent"] is None for value in row["world"]) < 1e-6}
    return {"checks": checks, "all_bones": rows,
            "maximum_hierarchical_world_scale_roundoff": max(abs(value - 1) for row in rows for value in row["world"])}


def weight_linear(weights, matrices):
    result = np.zeros((len(weights), 3, 3))
    for index, row in enumerate(weights):
        for name, weight in row.items():
            result[index] += matrices[name][:3, :3] * weight
    return result


def exact_intersections(points, triangles, native_ids, scope_triangles):
    all_tree = BVHTree.FromPolygons(points.tolist(), triangles.tolist(), all_triangles=True, epsilon=0.)
    local_tree = BVHTree.FromPolygons(points.tolist(), triangles[scope_triangles].tolist(), all_triangles=True, epsilon=0.)
    pairs = {tuple(sorted((int(scope_triangles[local]), int(other)))) for local, other in local_tree.overlap(all_tree)}
    crossings, coplanar = [], []
    tested = 0
    for first, second in sorted(pairs):
        if first == second or len(set(native_ids[triangles[first]]) & set(native_ids[triangles[second]])) >= 2:
            continue
        tested += 1
        contact = geometry.triangle_contact_kind(points[triangles[first]], points[triangles[second]])
        if contact == "proper_crossing":
            crossings.append([first, second])
        elif contact == "coplanar_area_overlap":
            coplanar.append([first, second])
    return {"proper_crossing_pairs": crossings, "coplanar_area_overlap_pairs": coplanar,
            "narrowphase_pairs_tested": tested, "broadphase_pairs": len(pairs),
            "scope": "Every rest triangle touching Z<0.40m against every body triangle; native-edge-adjacent pairs excluded, single-common-vertex pairs still tested, no position weld. BVH candidates narrowed by segment/triangle interior tests and coplanar clipped area. Touch-only excluded; adjacent folds covered by orientation test."}


def seam_diagnostic(points, native_groups):
    maximum, worst = 0., None
    for native, indices in native_groups.items():
        if len(indices) < 2:
            continue
        distance = float(np.linalg.norm(points[indices] - points[indices[0]], axis=1).max())
        if distance > maximum:
            maximum, worst = distance, native
    return {"maximum_native_duplicate_position_gap_m": maximum, "worst_native_vertex": worst,
            "identity": "Frozen source render-to-native map, including six cleaned split identities, not position welding."}


def edge_diagnostic(points, rest, edges, weight_rows, bands):
    values = []
    for native_pair, render_pair in edges.items():
        start, end = render_pair
        if min(rest[start, 2], rest[end, 2]) > .4:
            continue
        length = float(np.linalg.norm(rest[start] - rest[end]))
        if length <= 1e-10:
            continue
        ratio = float(np.linalg.norm(points[start] - points[end]) / length)
        names = weight_rows[start].keys() | weight_rows[end].keys()
        gradient = sum(abs(weight_rows[start].get(name, 0) - weight_rows[end].get(name, 0)) for name in names)
        side = "l" if (rest[start, 1] + rest[end, 1]) > 0 else "r"
        band = bands[side]
        in_band = geometry.edge_touches_band(rest[start, 2], rest[end, 2], band["full_transfer_below_m"], band["zero_transfer_above_m"])
        values.append({"native_edge": list(native_pair), "render_edge": list(render_pair), "rest_length_m": length,
                       "length_ratio": ratio, "weight_L1_difference": gradient, "touches_transition_band": in_band})
    ratios = [row["length_ratio"] for row in values]
    transitions = [row for row in values if row["touches_transition_band"]]
    return {"edge_count": len(values), "length_ratio_min_p50_p95_p99_max": np.percentile(ratios, [0, 50, 95, 99, 100]).tolist(),
            "transition_edge_count": len(transitions),
            "transition_max_weight_L1_difference": max(row["weight_L1_difference"] for row in transitions),
            "transition_max_length_ratio": max(row["length_ratio"] for row in transitions),
            "severe_edges_ratio_over2_or_underhalf": [row for row in values if row["length_ratio"] > 2 or row["length_ratio"] < .5],
            "all_local_edges": values}


def foot_points_diagnostic(points, rest, native_groups, matrices):
    result = {}
    for side, sign in (("l", 1), ("r", -1)):
        indices = [values[0] for values in native_groups.values() if sign * rest[values[0], 1] > 0 and rest[values[0], 2] < .35]
        sole = [index for index in indices if rest[index, 2] < .025]
        toe = [index for index in sole if rest[index, 0] > .06]
        heel = [index for index in sole if rest[index, 0] < -.06]
        rows = []
        for index in indices:
            ideal = (matrices["foot_" + side] @ np.append(rest[index], 1))[:3]
            rows.append({"render_vertex": index, "rest_m": rest[index].tolist(), "actual_m": points[index].tolist(),
                         "foot_rigid_reference_m": ideal.tolist(), "foot_rigid_distance_m": float(np.linalg.norm(points[index] - ideal))})
        def region(selected):
            if not selected:
                raise ValueError("Geometric sole/toe/heel selection unexpectedly empty")
            errors = [row["foot_rigid_distance_m"] for row in rows if row["render_vertex"] in selected]
            return {"unique_native_vertices": len(selected), "minimum_Z_m": float(points[selected, 2].min()),
                    "maximum_Z_m": float(points[selected, 2].max()), "maximum_foot_rigid_distance_m": max(errors)}
        result[side] = {"low_boot": region(indices), "sole": region(sole), "toe": region(toe), "heel": region(heel), "points": rows}
    return result


def apply(plan_path, output):
    if rig.record(plan_path)["sha256"] != PLAN_SHA:
        raise ValueError("Frozen semantic plan changed")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    frozen = [plan[key] for key in ("source_blend", "source_report", "source_mesh", "planned_changes", "projection", "script")]
    for item in frozen:
        if rig.record(Path(item["path"])) != item:
            raise ValueError("Frozen source file changed: " + item["path"])
    original = json.loads(Path(plan["source_report"]["path"]).read_text(encoding="utf-8"))
    mapping_record = original["mapping"]
    if rig.record(Path(mapping_record["path"])) != mapping_record:
        raise ValueError("Frozen native/weight correspondence changed")
    mapping = json.loads(Path(mapping_record["path"]).read_text(encoding="utf-8"))
    changes = json.loads(Path(plan["planned_changes"]["path"]).read_text(encoding="utf-8"))["changes"]
    if len(changes) != 1458 or len({row["native_vertex"] for row in changes}) != 657:
        raise ValueError("Approved local selection changed")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=plan["source_blend"]["path"])
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(meshes) != 1 or len(armatures) != 1:
        raise ValueError("Unexpected actual saved rig layout")
    body, armature = meshes[0], armatures[0]
    if len(armature.data.bones) != 61:
        raise ValueError("Actual skeleton changed")
    modifiers = list(body.modifiers)
    if len(modifiers) != 1 or modifiers[0].type != "ARMATURE" or modifiers[0].object != armature or modifiers[0].use_deform_preserve_volume:
        raise ValueError("Actual modifier no longer matches the audited linear skin model")
    transfer.set_pose([armature], [])
    baseline = rig.mesh_snapshot(body)
    original_normals = encoded_normals(body.data)
    original_materials = rig.materials_report([body])
    original_rest_bones = rest_bones(armature)
    before_weights = weights_of(body)
    native_ids = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(before_weights))])
    native_groups = defaultdict(list)
    for index, native in enumerate(native_ids):
        native_groups[int(native)].append(index)
    control = body.copy()
    control.data = body.data.copy()
    control.name = "FootWeight_Before_Control"
    bpy.context.scene.collection.objects.link(control)
    control.hide_render = True
    actual_changes = []
    selected = {row["source_vertex"] for row in changes}
    for row in changes:
        index = row["source_vertex"]
        if before_weights[index] != row["before"] or native_ids[index] != row["native_vertex"]:
            raise ValueError("Exact before weight/native identity differs from approved plan")
        for name in row["before"]:
            body.vertex_groups[name].remove([index])
        for name, value in row["after"].items():
            if name not in body.vertex_groups:
                raise ValueError("Plan refers to a missing actual bone group")
            body.vertex_groups[name].add([index], value, "REPLACE")
    after_weights = weights_of(body)
    checks = transfer.check_rest_normals_uv(baseline, rig.mesh_snapshot(body))
    checks["encoded_custom_normal_attribute_exact"] = encoded_normals(body.data) == original_normals
    checks["materials_and_three_image_payloads_exact"] = rig.materials_report([body]) == original_materials
    checks["all61_rest_bones_exact"] = rest_bones(armature) == original_rest_bones
    checks["all_unselected_weight_rows_exact"] = all(before_weights[index] == after_weights[index] for index in range(len(before_weights)) if index not in selected)
    checks["ball_weights_exact_all_vertices"] = all(before.get("ball_l", 0) == after.get("ball_l", 0) and before.get("ball_r", 0) == after.get("ball_r", 0) for before, after in zip(before_weights, after_weights))
    checks["native_UV_duplicate_weight_rows_exact"] = all(all(after_weights[index] == after_weights[indices[0]] for index in indices) for indices in native_groups.values())
    checks["planned_after_float32_exact"] = all(after_weights[row["source_vertex"]] == {name: float(np.float32(value)) for name, value in row["after"].items()} for row in changes)
    for row in changes:
        index = row["source_vertex"]
        names = before_weights[index].keys() | after_weights[index].keys()
        actual_changes.append({**row, "after_actual_float32": after_weights[index],
                               "actual_delta": {name: after_weights[index].get(name, 0) - before_weights[index].get(name, 0) for name in names}})
    difference_path = output / "actual_vertex_weight_changes.json"
    rig.save(difference_path, {"source": plan["source_blend"], "changes": actual_changes, "all_other_rows_exact": checks["all_unselected_weight_rows_exact"]})
    maximum_sum_error = max(abs(sum(row.values()) - 1) for row in after_weights)
    checks["normalized_at_most4_weights"] = maximum_sum_error < 1e-6 and max(map(len, after_weights)) <= 4
    scale = scale_diagnostic(armature)
    checks.update(scale["checks"])
    report_path = output / "foot_weight_report.json"
    report = {"asset_id": "Unit_StoneSlinger", "status": "actual_candidate_diagnostics_in_progress",
              "source": plan["source_blend"], "plan": rig.record(plan_path), "script": rig.record(Path(__file__)),
              "geometry_math": rig.record(Path(geometry.__file__)), "mapping": mapping_record,
              "actual_weight_changes": rig.record(difference_path), "changed_render_vertices": len(changes),
              "changed_native_vertices": len({row["native_vertex"] for row in changes}), "maximum_weight_sum_error": maximum_sum_error,
              "checks": checks, "rest_scale_diagnostic": scale, "source_materials": original_materials,
              "pose_checks": [], "images": [], "production_approved": False, "gait_approved": False,
              "scope": "Local boot weight experiment only. No root translation, floor compensation, mesh/UV/normal/map change, upperbody change, animation export, UE or paid work."}
    rig.save(report_path, report)
    if not all(checks.values()):
        raise ValueError("Strict source-preservation or weight-scope gate failed")
    triangles = baseline["triangles"]
    rest = baseline["positions"]
    edges = geometry.native_edges(triangles, native_ids)
    scope = np.flatnonzero(np.min(rest[triangles, 2], axis=1) < .4)
    bones = original["actual_final_skeleton"]["armatures"][0]["bones"]
    poses = {"rest": []}
    poses.update({row["pose"]: row["commands"] for row in plan["predictions"]})
    for label, commands in poses.items():
        transfer.set_pose([armature], commands)
        actual_before, actual_after = transfer.evaluated_positions(control), transfer.evaluated_positions(body)
        predicted_before, matrices = plan_math.deform(rest, before_weights, bones, commands)
        predicted_after, _ = plan_math.deform(rest, after_weights, bones, commands)
        pose = {"pose": label, "commands": commands, "actual_vertices_per_side": len(rest),
                "prediction_max_error_before_m": float(np.linalg.norm(predicted_before - actual_before, axis=1).max()),
                "prediction_max_error_after_m": float(np.linalg.norm(predicted_after - actual_after, axis=1).max()),
                "maximum_before_after_displacement_m": float(np.linalg.norm(actual_before - actual_after, axis=1).max()),
                "scale": scale_diagnostic(armature)}
        for stage, points, weights in (("before", actual_before, before_weights), ("after", actual_after, after_weights)):
            pose[stage] = {"minimum_world_Z_m": float(points[:, 2].min()), "native_seams": seam_diagnostic(points, native_groups),
                           "gradient_and_edge_stretch": edge_diagnostic(points, rest, edges, weights, plan["anatomical_bands"]),
                           "orientation": geometry.triangle_orientation(rest, points, triangles, weight_linear(weights, matrices)),
                           "intersection": exact_intersections(points, triangles, native_ids, scope),
                           "geometric_feet": foot_points_diagnostic(points, rest, native_groups, matrices)}
        for key in ("proper_crossing_pairs", "coplanar_area_overlap_pairs"):
            before_pairs = {tuple(pair) for pair in pose["before"]["intersection"][key]}
            after_pairs = {tuple(pair) for pair in pose["after"]["intersection"][key]}
            pose["new_" + key] = sorted(after_pairs - before_pairs)
            pose["removed_" + key] = sorted(before_pairs - after_pairs)
        for key in ("negative_triangles", "degenerate_triangles"):
            pose["new_" + key] = sorted(set(pose["after"]["orientation"][key]) - set(pose["before"]["orientation"][key]))
        before_severe = {tuple(row["native_edge"]) for row in pose["before"]["gradient_and_edge_stretch"]["severe_edges_ratio_over2_or_underhalf"]}
        after_severe = {tuple(row["native_edge"]) for row in pose["after"]["gradient_and_edge_stretch"]["severe_edges_ratio_over2_or_underhalf"]}
        pose["new_severe_native_edges"] = sorted(after_severe - before_severe)
        pose["checks"] = {"actual_LBS_prediction_within3micrometers": max(pose["prediction_max_error_before_m"], pose["prediction_max_error_after_m"]) < 3e-6,
                          "actual_native_seams_within3micrometers": pose["after"]["native_seams"]["maximum_native_duplicate_position_gap_m"] < 3e-6,
                          "no_new_negative_triangles": not pose["new_negative_triangles"],
                          "no_new_degenerate_triangles": not pose["new_degenerate_triangles"],
                          "no_new_proper_crossings": not pose["new_proper_crossing_pairs"],
                          "no_new_coplanar_area_overlap": not pose["new_coplanar_area_overlap_pairs"],
                          "no_new_severe_native_edges": not pose["new_severe_native_edges"],
                          "unit_explicit_scale_channels_and_root": all(pose["scale"]["checks"].values())}
        if label.startswith("ankle_"):
            pose["checks"]["geometric_sole_follows_foot_within3micrometers"] = max(pose["after"]["geometric_feet"][side]["sole"]["maximum_foot_rigid_distance_m"] for side in ("l", "r")) < 3e-6
        if label == "toe_lift":
            pose["checks"]["ball_articulation_unchanged_within3micrometers"] = pose["maximum_before_after_displacement_m"] < 3e-6
        report["pose_checks"].append(pose)
        rig.save(report_path, report)
        if not pose["checks"]["actual_LBS_prediction_within3micrometers"]:
            raise ValueError("Actual deformation differs from proven skin math; do not render misleading comparisons")
    report["all_actual_diagnostic_checks_passed"] = all(all(row["checks"].values()) for row in report["pose_checks"])
    report["status"] = "numeric_pass_pending_visual_review" if report["all_actual_diagnostic_checks_passed"] else "diagnostic_failures_preserved_not_approved"
    rig.save(report_path, report)
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    helper = rig.module("slinger_foot_render", "prepare_tripo_character.py")
    if bpy.context.scene.world is None:
        bpy.context.scene.world = bpy.data.worlds.new("ReviewWorld")
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    helper.render_setup(samples=8)
    views = [("rest", "both", (1, -1.3, .6), (-.015, 0, .18), .85),
             ("ankle_minus20", "left", (1, 1.8, .5), (-.02, .23, .17), .48),
             ("ankle_minus20", "right", (1, -1.8, .5), (-.02, -.23, .17), .48),
             ("ankle_plus20", "left", (1, 1.8, .5), (-.02, .23, .17), .48),
             ("ankle_plus20", "right", (1, -1.8, .5), (-.02, -.23, .17), .48),
             ("toe_lift", "both", (1, -1.3, .6), (-.015, 0, .18), .85),
             ("knee_plus15", "both", (1, -1.3, .6), (-.015, 0, .18), .85),
             ("heel_lift", "both", (1, -1.3, .6), (-.015, 0, .18), .85)]
    for pose, view, direction, target, framing in views:
        transfer.set_pose([armature], poses[pose])
        for stage, shown, hidden in (("before", control, body), ("after", body, control)):
            shown.hide_render, hidden.hide_render = False, True
            path = output / (pose + "_" + view + "_" + stage + ".png")
            helper.render_view(path, [shown], direction, size=512, framing=framing, target=target)
            report["images"].append(rig.record(path))
            rig.save(report_path, report)
    transfer.set_pose([armature], [])
    bpy.data.objects.remove(control, do_unlink=True)
    body.hide_render = False
    final_checks = transfer.check_rest_normals_uv(baseline, rig.mesh_snapshot(body))
    final_checks["encoded_custom_normal_attribute_exact"] = encoded_normals(body.data) == original_normals
    final_checks["PBR_exact"] = rig.materials_report([body]) == original_materials
    final_checks["rest_bones_exact"] = rest_bones(armature) == original_rest_bones
    final_checks["all_frozen_source_files_unchanged"] = all(rig.record(Path(item["path"])) == item for item in frozen)
    report["final_preservation_checks"] = final_checks
    if not all(final_checks.values()):
        rig.save(report_path, report)
        raise ValueError("Post-diagnostic source preservation failed")
    blend = output / "Unit_StoneSlinger_LocalFootWeights.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"] = rig.record(blend)
    report["actual_images"] = len(report["images"])
    rig.save(report_path, report)
    print(json.dumps({"status": report["status"], "numeric_checks_passed": report["all_actual_diagnostic_checks_passed"], "images": len(report["images"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    apply(Path(args.plan).resolve(), Path(args.output).resolve())
