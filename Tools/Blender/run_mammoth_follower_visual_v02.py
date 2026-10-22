"""Run the same frozen follower diagnostic with separately audited import-normal checks."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mammoth_follower_visual as visual
import diagnose_mammoth_follower_normals as probe


FOLDER = probe.FOLDER
LIMITS = {"bind_skin_vector": 4e-7, "static_angle_degrees": .01, "evaluated_rest_angle_degrees": .015}


def enforce_normal_gate(summary):
    if not all(summary["authored_exact"].values()) or not summary["original_binary_prefix_exact"] or not summary["PBR_metadata_exact"]:
        raise ValueError("Authored source attributes or PBR bytes changed")
    if summary["existing33_bind_matrix_difference"] != 0:
        raise ValueError("Existing bind matrices changed in actual importer")
    if summary["bind_skin"]["maximum_vector_difference"] > LIMITS["bind_skin_vector"]:
        raise ValueError("Importer bind-skin normal difference exceeds frozen limit")
    if summary["static"]["maximum_angle_degrees"] > LIMITS["static_angle_degrees"]:
        raise ValueError("Static decoded corner normal exceeds frozen angle limit")
    if summary["evaluated_rest"]["maximum_angle_degrees"] > LIMITS["evaluated_rest_angle_degrees"]:
        raise ValueError("Evaluated rest normal exceeds frozen angle limit")
    if summary["bind_skin_changes_outside_weight_rows"] or summary["static_changes_outside_one_ring"] or summary["evaluated_changes_outside_one_ring"]:
        raise ValueError("Normal change exceeds reviewed local and one-ring scope")


def import_pair(spec):
    importer = importlib.import_module("io_scene_gltf2.blender.imp.mesh")
    original = importer.skin_into_bind_pose
    captures = []

    def observe(*arguments, **keywords):
        bound = inspect.signature(original).bind(*arguments, **keywords).arguments
        gltf, skin_index = bound["gltf"], bound["skin_idx"]
        skin = gltf.data.skins[skin_index]
        inverse = importer.BinaryData.get_data_from_accessor(gltf, skin.inverse_bind_matrices)
        matrices = np.array([gltf.vnodes[joint].bind_arma_mat @ gltf.matrix_gltf_to_blender(row) for joint, row in zip(skin.joints, inverse)], dtype=np.float32)
        result = original(*arguments, **keywords)
        captures.append({"normals": bound["vert_normals"].copy(), "matrices": matrices})
        return result

    try:
        importer.skin_into_bind_pose = observe
        baseline = visual.import_rig(spec["baseline"]["path"], 33)
        candidate = visual.import_rig(spec["candidate"]["path"], 35)
    finally:
        importer.skin_into_bind_pose = original
    if len(captures) != 2:
        raise ValueError("Expected one actual bind-skin call per model")
    return baseline, candidate, captures


def evaluated_normals(body):
    import bpy
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
    values = np.array([list((matrix @ corner.vector).normalized()) for corner in mesh.corner_normals])
    evaluated.to_mesh_clear()
    return values


def normal_audit(before_body, body, captures, spec, preparation):
    import bpy
    bpy.context.view_layer.update()
    before_doc, before_bin = visual.transfer.read_container(spec["baseline"]["path"])
    after_doc, after_bin = visual.transfer.read_container(spec["candidate"]["path"])
    before = visual.transfer.source_arrays(before_doc, before_bin)
    after = visual.transfer.source_arrays(after_doc, after_bin)
    authored = {key: np.array_equal(before[key], after[key]) for key in ("POSITION", "NORMAL", "TEXCOORD_0", "indices")}
    raw_before = np.array([list(corner.vector) for corner in before_body.data.corner_normals])
    raw_after = np.array([list(corner.vector) for corner in body.data.corner_normals])
    static, static_delta = probe.vector_difference(raw_before, raw_after)
    evaluated, evaluated_delta = probe.vector_difference(evaluated_normals(before_body), evaluated_normals(body))
    bind, bind_delta = probe.vector_difference(captures[0]["normals"], captures[1]["normals"])
    changed = set(preparation["changed_render_vertices"])
    one_ring = {int(vertex) for triangle in after["indices"] if any(int(vertex) in changed for vertex in triangle) for vertex in triangle}
    loop_vertices = np.array([loop.vertex_index for loop in body.data.loops])
    encoded_before, encoded_after = probe.encoded_normals(before_body.data), probe.encoded_normals(body.data)
    for layer in (static, evaluated):
        for row in layer["top_rows"]:
            row["render_vertex"] = int(loop_vertices[row["index"]])
            row["encoded_before"] = encoded_before[row["index"]].tolist()
            row["encoded_after"] = encoded_after[row["index"]].tolist()
    summary = {"limits": LIMITS, "authored_exact": authored, "original_binary_prefix_exact": before_bin == after_bin[:len(before_bin)],
               "PBR_metadata_exact": all(before_doc.get(key) == after_doc.get(key) for key in ("images", "textures", "materials")),
               "existing33_bind_matrix_difference": float(np.max(abs(captures[0]["matrices"] - captures[1]["matrices"][:33]))),
               "bind_skin": bind, "static": static, "evaluated_rest": evaluated,
               "bind_skin_changes_outside_weight_rows": [int(index) for index in np.flatnonzero(bind_delta) if int(index) not in changed],
               "static_changes_outside_one_ring": [int(index) for index in np.flatnonzero(static_delta) if int(loop_vertices[index]) not in one_ring],
               "evaluated_changes_outside_one_ring": [int(index) for index in np.flatnonzero(evaluated_delta) if int(loop_vertices[index]) not in one_ring],
               "changed_weight_rows": len(changed), "allowed_one_ring_vertices": len(one_ring), "encoded_changed_pairs": int(np.count_nonzero(np.any(encoded_before != encoded_after, axis=1))),
               "maximum_encoded_integer_delta": int(np.max(abs(encoded_before - encoded_after)))}
    enforce_normal_gate(summary)
    summary["passed_separate_import_layer_gate"] = True
    return summary


def actual_weight_rows(body):
    return [{body.vertex_groups[item.group].name: item.weight for item in vertex.groups if item.weight > 0} for vertex in body.data.vertices]


def prepare():
    original = visual.read_json(probe.ORIGINAL_SPEC)
    if visual.core.record(probe.ORIGINAL_SPEC)["sha256"] != probe.ORIGINAL_SPEC_SHA:
        raise ValueError("Original failed spec changed")
    for record in original["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    path = FOLDER / "execution_spec_v02.json"
    if path.exists() or (FOLDER / "actual_visual_02").exists():
        raise FileExistsError("Preserve earlier attempts")
    spec = dict(original)
    spec["status"] = "frozen_same_candidate_import_layer_gate_revision_only"
    spec["root_authorization"] = "Root explicitly approved distinct import-layer detection: exact authored bytes; bind-skin delta <=4e-7; static decoded <=0.01degree; evaluated rest <=0.015degree; changes only original local587rows and one-ring. Preserve original failures. Execute same eight poses/four images without optimization."
    spec["normal_gate_revision"] = {"limits": LIMITS, "cause_report": visual.core.record(FOLDER / "normal_probe_02/normal_diagnostic.json"), "historical_failed_spec": visual.core.record(probe.ORIGINAL_SPEC), "old_gate_failure_unchanged": True}
    extra = [Path(__file__), Path(probe.__file__), probe.ORIGINAL_SPEC, FOLDER / "normal_probe_02/normal_diagnostic.json", probe.IMPORTER, probe.IMPORTER.with_name("vnode.py")]
    spec["frozen_inputs"] = original["frozen_inputs"] + [visual.core.record(path) for path in extra]
    spec["command"] = {"executable": original["command"]["executable"], "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(path)]}
    visual.core.save(path, spec)
    print(json.dumps(visual.core.record(path)))


def run(spec_path):
    import bpy
    import prepare_tripo_character as renderer
    spec = visual.read_json(spec_path)
    for record in spec["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    output = FOLDER / "actual_visual_02"
    output.mkdir(exist_ok=False)
    report = {"status": "started_unapproved_diagnostic", "process_id": __import__("os").getpid(), "poses": [], "images": [], "historical_per_edge_strain_gate": "FAIL", "production_approved": False, "runtime_approved": False}
    try:
        preparation, feasibility, masks, exact = (visual.read_json(spec[name]["path"]) for name in ("preparation", "feasibility", "mask_plan", "exact_regions"))
        document, binary = visual.transfer.read_container(spec["candidate"]["path"])
        arrays = visual.transfer.source_arrays(document, binary)
        native_map, _, _ = visual.transfer.audit_tool.texture.native_identity(arrays)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        (baseline_body, baseline_rig), (body, rig), captures = import_pair(spec)
        baseline_body.hide_render = True
        report["separate_import_normal_gate"] = normal_audit(baseline_body, body, captures, spec, preparation)
        before = visual.transfer.audit_tool.rig_core.mesh_snapshot(baseline_body)
        actual = visual.transfer.audit_tool.rig_core.mesh_snapshot(body)
        if any(not np.array_equal(before[attribute], actual[attribute]) for attribute in ("triangles", "uv")):
            raise ValueError("Actual candidate changes decoded UV or triangle indices")
        baseline_rest, rest = visual.evaluate(baseline_body), visual.evaluate(body)
        source = arrays["POSITION"] @ visual.transfer.BASIS.T
        rest_error = max(float(np.linalg.norm(rest - baseline_rest, axis=1).max()), float(np.linalg.norm(rest - source, axis=1).max()))
        if rest_error > visual.transfer.TOLERANCE_M:
            raise ValueError("Actual retained surface/rest exceeds three micrometres")
        bases = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
        baseline_bases = {bone.name: bone.matrix_basis.copy() for bone in baseline_rig.pose.bones}
        rest_world = {bone.name: (rig.matrix_world @ bone.matrix).copy() for bone in rig.pose.bones}
        original_bone_error = max(float(np.max(abs(np.array(baseline_rig.matrix_world @ bone.matrix) - np.array(rest_world[bone.name])))) for bone in baseline_rig.pose.bones)
        if original_bone_error > visual.transfer.TOLERANCE_M:
            raise ValueError("An existing bone's actual rest changed")
        old_weights, new_weights = actual_weight_rows(baseline_body), actual_weight_rows(body)
        changed = set(preparation["changed_render_vertices"])
        outside_weight_changes = [index for index in range(len(rest)) if index not in changed and old_weights[index] != new_weights[index]]
        if outside_weight_changes:
            raise ValueError("Actual weight changes outside approved support")
        report["rest"] = {"surface_error_m": rest_error, "existing_bone_matrix_error": original_bone_error, "bones": 35, "surface_vertices": len(rest), "triangles": len(arrays["indices"]), "actual_UV_indices_exact": True, "outside_support_weight_changes": outside_weight_changes}
        rest_pairs = visual.intersection_pairs(rest, arrays["indices"], preparation["affected_triangles"])
        before_pairs = visual.intersection_pairs(baseline_rest, arrays["indices"], preparation["affected_triangles"])
        report["rest_new_intersections"] = sorted(rest_pairs - before_pairs)
        actions = {}
        original_doc, _ = visual.transfer.read_container(spec["baseline"]["path"])
        inverse = visual.transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
        for pose_index, command in enumerate(spec["diagnostic_poses"]):
            visual.reset_pose(baseline_rig, baseline_bases)
            visual.apply_command(baseline_rig, command)
            baseline_points = visual.evaluate(baseline_body)
            action, slot, action_record = visual.bake_action(rig, command, feasibility, bases, rest_world)
            direct = visual.evaluate(body)
            visual.reset_pose(rig, bases)
            rig.animation_data.action, rig.animation_data.action_slot = action, slot
            bpy.context.scene.frame_set(1)
            keyed_rest_error = float(np.linalg.norm(visual.evaluate(body) - rest, axis=1).max())
            bpy.context.scene.frame_set(2)
            points = visual.evaluate(body)
            replay_error = float(np.linalg.norm(points - direct, axis=1).max())
            if max(keyed_rest_error, replay_error) > visual.transfer.TOLERANCE_M:
                raise ValueError("Actual keyed replay diverges from direct target or rest")
            target_worlds = list(visual.optimizer.accessory.pose_matrices(original_doc, command))
            target_worlds.extend(np.array(region["pose_fits"][pose_index]["follower_world_matrix_gltf_m"]) for region in feasibility["regions"])
            predicted = visual.transfer.skin_positions(arrays["POSITION"], arrays["JOINTS_0"], arrays["WEIGHTS_0"], np.array(target_worlds) @ inverse) @ visual.transfer.BASIS.T
            prediction_error = float(np.linalg.norm(points - predicted, axis=1).max())
            if prediction_error > visual.transfer.TOLERANCE_M:
                raise ValueError("Actual keyed deformation differs from frozen prediction")
            before_pairs = visual.intersection_pairs(baseline_points, arrays["indices"], preparation["affected_triangles"])
            after_pairs = visual.intersection_pairs(points, arrays["indices"], preparation["affected_triangles"])
            row = {"pose": command["name"], "baked_action": action_record, "keyed_rest_max_error_m": keyed_rest_error, "keyed_replay_max_error_m": replay_error,
                   "actual_to_frozen_prediction_max_error_m": prediction_error, "face_changes": visual.face_changes(baseline_points, points, arrays["indices"], preparation["affected_triangles"]),
                   "baseline_intersection_count": len(before_pairs), "candidate_intersection_count": len(after_pairs), "new_intersection_pairs": sorted(after_pairs - before_pairs), "buckles": []}
            for region in masks["regions"]:
                patch = next(item for item in exact["patches"] if item["native_patch"] == region["native_patch"])
                pairs = np.array(patch["coincident_patch_to_surrounding_pairs"])
                seam = float(np.linalg.norm(points[pairs[:, 0]] - points[pairs[:, 1]], axis=1).max())
                metal = region["metal_render_vertices"]
                name = "derived_buckle_" + str(region["native_patch"])
                delta = np.array(rig.matrix_world @ rig.pose.bones[name].matrix @ rest_world[name].inverted())
                determinant = float(np.linalg.det(delta[:3, :3]))
                scales = np.linalg.svd(delta[:3, :3], compute_uv=False)
                rigid_transform = {"actual_world_delta_matrix": delta.tolist(), "determinant": determinant, "singular_scales": scales.tolist(), "positive_proper_unit_scale": determinant > 0 and float(max(abs(scales - 1))) <= 3e-6}
                row["buckles"].append({"patch": region["native_patch"], "metal": visual.transfer.rigid_residual(rest[metal], points[metal]), "actual_follower_transform": rigid_transform, "maximum_coincident_seam_gap_m": seam,
                                       "actual_edge_strain": visual.actual_strain_rows(baseline_points, points, rest, arrays["indices"], native_map, region)})
            report["poses"].append(row)
            actions[command["name"]] = (action, slot)
            visual.core.save(output / "diagnostic.json", report)
        visual.reset_pose(baseline_rig, baseline_bases)
        visual.reset_pose(rig, bases)
        bpy.context.scene.world = bpy.data.worlds.new("MammothFollowerDiagnosticWorld")
        renderer.render_setup(samples=8)
        if bpy.context.scene.cycles.device != "GPU":
            raise ValueError("HIP required; no CPU render fallback")
        for region in masks["regions"]:
            for mode in ("rest", "shoulder8"):
                visual.reset_pose(rig, bases)
                if mode != "rest":
                    action, slot = actions[region["actual_pose"]["name"]]
                    rig.animation_data.action, rig.animation_data.action_slot = action, slot
                    bpy.context.scene.frame_set(2)
                bpy.context.view_layer.update()
                path = output / ("buckle_" + str(region["native_patch"]) + "_" + mode + ".png")
                renderer.render_view(path, [body], region["camera"]["direction"], size=512, framing=region["camera"]["framing_m"], target=region["camera"]["target"])
                report["images"].append({"patch": region["native_patch"], "pose": mode, "file": visual.core.record(path)})
        visual.reset_pose(rig, bases)
        scene_path = output / "Mount_Mammoth_follower_diagnostic.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
        report["saved_real_actions_scene"] = visual.core.record(scene_path)
        report["safety_numeric_passed"] = not report["rest_new_intersections"] and all(not row["new_intersection_pairs"] and not row["face_changes"]["normal_reversed_triangles"] and not row["face_changes"]["new_degenerate_triangles"] and all(item["maximum_coincident_seam_gap_m"] <= visual.transfer.TOLERANCE_M and item["metal"]["max_pair_distance_change_m"] <= visual.transfer.TOLERANCE_M and item["actual_follower_transform"]["positive_proper_unit_scale"] for item in row["buckles"]) for row in report["poses"])
        report["status"] = "actual_diagnostic_complete_requires_root_visual_review_not_approval"
        report["limitations"] = ["Historical individual-edge gate remains FAIL", "Real keyed two-frame diagnostic actions are not gameplay clips or intermediate motion validation", "No source change, normal reset, GLB/FBX re-export, UE, gait or rider approval"]
        for record in spec["frozen_inputs"]:
            visual.transfer.audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
    except Exception as error:
        report["status"], report["error"] = "failed_preserved_no_automatic_retry", str(error)
        visual.core.save(output / "diagnostic.json", report)
        raise
    visual.core.save(output / "diagnostic.json", report)
    print(json.dumps({"status": report["status"], "poses": len(report["poses"]), "images": len(report["images"]), "safety_numeric_passed": report["safety_numeric_passed"], "historical_per_edge_strain_gate": "FAIL"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "run"), required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare()
    elif args.spec:
        run(args.spec)
    else:
        parser.error("Frozen spec required")


if __name__ == "__main__":
    main()
