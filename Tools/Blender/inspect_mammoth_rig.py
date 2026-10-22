"""Read-only audit of a real quadruped rig against the frozen23-split PBR source."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspect_mammoth_texture as texture
import inspect_stone_slinger_rig as rig_core


ROOT = Path(__file__).resolve().parents[2]
BRANCH = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/mammoth_v01"
SOURCE = BRANCH / "textured_v01/pbr_review_01/Mount_Mammoth_PBR.glb"
SOURCE_SHA = "d0208f1a64a96c72c640b179314bbff3b44e5d96a6ef96d50f620ae78bfc9473"
APPROVAL = BRANCH / "textured_v01/pbr_render_diagnostic_02/visual_review.json"
TASK_ID = "ed978df0-5950-4960-9e30-79581cb4b1c8"
RAW_FOLDER = ROOT / "RawAssets/Art/Tripo_v01/tripo_raw/Mount_Mammoth/rigged_v01_split23"


def fresh_output(path):
    path = path.resolve()
    if path.parent != BRANCH.resolve() or not path.name.startswith("rig_audit_"):
        raise ValueError("Output must be a fresh owned mammoth rig_audit_* directory")
    if path.exists():
        raise FileExistsError("Preserve previous rig evidence")
    return path


def source_snapshot(arrays):
    triangles = arrays["indices"].astype(int)
    positions = arrays["POSITION"].astype(float)[:, (0, 2, 1)] * (1, -1, 1)
    normals = arrays["NORMAL"].astype(float)[:, (0, 2, 1)] * (1, -1, 1)
    uv = arrays["TEXCOORD_0"].astype(float).copy()
    uv[:, 1] = 1 - uv[:, 1]
    return {"positions": positions, "normals": normals[triangles.reshape(-1)], "uv": uv[triangles.reshape(-1)],
            "triangles": triangles, "triangle_loops": np.arange(triangles.size).reshape(-1, 3)}


def triangle_mapping(source, returned, fit):
    rotation = np.array(fit["rotation"])
    restored = returned["positions"] @ rotation.T * fit["uniform_scale"] + fit["translation_m"]
    source_ids, returned_ids = texture.core.position_correspondence(source["positions"], restored)
    by_positions = defaultdict(list)
    for face, triangle in enumerate(source["triangles"]):
        by_positions[tuple(sorted(int(source_ids[index]) for index in triangle))].append(face)
    vertex_mapping = defaultdict(set)
    triangle_rows = []
    used = set()
    for face, triangle in enumerate(returned["triangles"]):
        candidates = by_positions[tuple(sorted(int(returned_ids[index]) for index in triangle))]
        if len(candidates) != 1 or candidates[0] in used:
            raise ValueError("Triangle correspondence is missing, duplicated or ambiguous")
        source_face = candidates[0]
        used.add(source_face)
        expected = source["triangles"][source_face]
        positions = {int(source_ids[index]): int(index) for index in expected}
        ordered = [positions[int(returned_ids[index])] for index in triangle]
        if not any(ordered == list(expected[offset:]) + list(expected[:offset]) for offset in range(3)):
            raise ValueError("Rig reversed triangle winding")
        for old, new in zip(ordered, triangle):
            vertex_mapping[old].add(int(new))
        triangle_rows.append({"source_triangle": source_face, "returned_triangle": face, "source_vertices_in_returned_corner_order": ordered})
    if len(used) != len(source["triangles"]) or len(vertex_mapping) != len(source["positions"]):
        raise ValueError("Rig omitted source faces or surface vertices")
    return vertex_mapping, triangle_rows


def weight_metrics(rows, deform_names):
    errors, missing, totals, histogram = [], [], defaultdict(float), defaultdict(int)
    for row in rows:
        weights = row["weights"]
        if not weights:
            missing.append(row["vertex"])
        histogram[len(weights)] += 1
        for name, weight in weights.items():
            totals[name] += weight
            if name not in deform_names or not np.isfinite(weight) or not 0 <= weight <= 1:
                errors.append({"vertex": row["vertex"], "bone": name, "weight": weight, "kind": "invalid_or_non_deform_influence"})
        weight_sum = sum(weights.values())
        if not np.isfinite(weight_sum) or abs(weight_sum - 1) > 1e-5:
            errors.append({"vertex": row["vertex"], "sum": weight_sum, "kind": "weight_sum"})
    return {"vertices": len(rows), "unweighted_vertices": missing, "errors": errors,
            "maximum_influences": max(histogram, default=0), "influence_histogram": dict(histogram),
            "total_weight_by_bone": dict(totals), "weights_numerically_valid": not errors and not missing}


def region_weights(rows, vertex_indices):
    selected = [rows[index] for index in sorted(set(vertex_indices))]
    totals = defaultdict(float)
    for row in selected:
        for bone, weight in row["weights"].items():
            totals[bone] += weight
    return {"vertices": len(selected), "vertex_indices": [row["vertex"] for row in selected],
            "mean_weight_by_bone": {bone: total / len(selected) for bone, total in sorted(totals.items(), key=lambda item: -item[1])} if selected else {},
            "dominant_bone_counts": {bone: sum(max(row["weights"], key=row["weights"].get, default=None) == bone for row in selected) for bone in totals},
            "rigid_or_deformation_approved": False}


def lineage(returned):
    if returned.resolve().parent != RAW_FOLDER.resolve() or returned.suffix.lower() not in {".glb", ".fbx"}:
        raise ValueError("Rig must be the actual file in its unique paid-task folder")
    task = json.loads((RAW_FOLDER / "task.json").read_text(encoding="utf-8-sig"))
    submission = json.loads((RAW_FOLDER / "submission.json").read_text(encoding="utf-8-sig"))
    intent = json.loads((RAW_FOLDER / "submission.intent.json").read_text(encoding="utf-8-sig"))
    if task["task_id"] != TASK_ID or task["status"] != "success" or task["type"] != "animate_rig" or submission["task_id"] != TASK_ID:
        raise ValueError("Not a successful receipt for the unique paid rig")
    if intent["source_sha256"] != SOURCE_SHA or texture.core.record(SOURCE)["sha256"] != SOURCE_SHA:
        raise ValueError("Paid rig source does not match frozen23-split candidate")
    approved = json.loads(APPROVAL.read_text(encoding="utf-8-sig"))
    if not approved["root_stage_approval"] or approved["root_review"]["approved_exact_candidate_sha256"] != SOURCE_SHA:
        raise ValueError("Exact root stage approval missing")
    return task


def plan(output, returned):
    task = lineage(returned)
    if not output.name.startswith("rig_audit_plan_"):
        raise ValueError("Plan output must use a distinct rig_audit_plan_* name")
    inspection_output = BRANCH / output.name.replace("rig_audit_plan_", "rig_audit_", 1)
    files = [SOURCE, APPROVAL, returned, RAW_FOLDER / "task.json", RAW_FOLDER / "submission.json", RAW_FOLDER / "submission.intent.json",
             Path(__file__), Path(texture.__file__), Path(rig_core.__file__), Path(texture.core.__file__)]
    result = {"asset_id": "Mount_Mammoth", "status": "rig_readonly_audit_prepared_waiting_root_exclusive_lease",
              "task_id": TASK_ID, "actual_credits_consumed": task["credits_consumed"], "returned_format": returned.suffix.lower(),
              "source": texture.core.record(SOURCE), "returned": texture.core.record(returned),
              "frozen_inputs": [texture.core.record(path) for path in files],
              "stages": ["24proper signed-axis rotations and positive uniform-scale hypotheses; prove complete triangle/UV/winding correspondence, not just matching bounds",
                         "Compare23 cleaned native split pairs and report any returned index re-weld; never position-weld or repair during audit",
                         "Record received bone hierarchy, physical rest heads/tails/matrices, object/root scales, actual weights and Armature modifier targets",
                         "Compare actual evaluated rest-pose geometry to raw received vertices; list all unweighted/invalid/unnormalized influences",
                         "Record three original texture payload matches and actual received shader node links/color spaces without automatically repairing PBR",
                         "Exact four approved saddle-buckle patches receive weight statistics; four near-ground quadrants are spatial foot probes, not semantic bone approval",
                         "Trunk/ears/tail/spine identity and test poses are selected only after actual bone coordinates and weight regions have been reviewed"],
              "restrictions": {"paid_calls": 0, "ue_calls": 0, "source_mutations": 0, "weight_edits": 0, "normal_edits": 0,
                               "material_edits": 0, "renders": 0, "model_exports": 0, "blender_threads": 2, "priority": "BelowNormal"},
              "future_command": {"executable": "C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe",
                                 "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "inspect", "--spec", str(output / "execution_spec.json"), "--output", str(inspection_output)]},
              "rig_approved": False, "gait_approved": False, "rider_fit_approved": False, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    texture.core.save(output / "execution_spec.json", result)
    print(json.dumps({"status": result["status"], "actual_format": result["returned_format"], "task_id": TASK_ID}))


def inspect(output, spec_path):
    import bpy
    from mathutils import Vector
    from mathutils.kdtree import KDTree

    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    for item in spec["frozen_inputs"]:
        texture.checked_record(item)
    returned_path = Path(spec["returned"]["path"])
    task = lineage(returned_path)
    source_document, source_binary, source_arrays = texture.core.read_glb(SOURCE)
    source = source_snapshot(source_arrays)
    source_native, split_pairs, native_analysis = texture.native_identity(source_arrays)
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if returned_path.suffix.lower() == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(returned_path), merge_vertices=False, disable_bone_shape=True)
    else:
        bpy.ops.import_scene.fbx(filepath=str(returned_path), use_anim=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    texture.core.save(output / "import_inventory.json", {"received": texture.core.record(returned_path),
                      "gltf_display_only_custom_bone_shapes_disabled": returned_path.suffix.lower() == ".glb",
                      "mesh_count": len(meshes), "armature_count": len(armatures),
                      "objects": [{"name": obj.name, "type": obj.type, "parent": obj.parent.name if obj.parent else None,
                                   "collections": [collection.name for collection in obj.users_collection]} for obj in bpy.context.scene.objects]})
    if len(meshes) != 1 or len(armatures) != 1:
        raise ValueError("Expected one actual mesh/armature; refuse implicit merge or armature guessing")
    bpy.context.view_layer.update()
    returned = rig_core.mesh_snapshot(meshes[0])
    tree = KDTree(len(source["positions"]))
    for index, point in enumerate(source["positions"]):
        tree.insert(Vector(point), index)
    tree.balance()
    candidates = rig_core.fit_axis_candidates(source["positions"], returned["positions"])
    for candidate in candidates:
        points = returned["positions"] @ np.array(candidate["rotation"]).T * candidate["uniform_scale"] + candidate["translation_m"]
        distances = [tree.find(Vector(point))[2] for point in points]
        candidate["maximum_nearest_surface_distance_m"] = max(distances)
    candidates.sort(key=lambda item: item["maximum_nearest_surface_distance_m"])
    report = {"schema_version": 1, "asset_id": "Mount_Mammoth", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "actual_readonly_rig_audit_not_rig_or_animation_approval", "process_id": __import__("os").getpid(),
              "task_id": TASK_ID, "actual_credits_consumed": task["credits_consumed"], "source": texture.core.record(SOURCE),
              "returned": texture.core.record(returned_path), "execution_spec": texture.core.record(spec_path), "blender_version": bpy.app.version_string,
              "frame_candidates": candidates, "source_baseline": "Exact GLB arrays, not Blender-decoded source normals",
              "actions": [{"name": action.name, "frame_range": list(action.frame_range)} for action in bpy.data.actions],
              "received_materials": rig_core.materials_report(meshes), "objects": [{"name": obj.name, "type": obj.type,
                  "parent": obj.parent.name if obj.parent else None, "matrix_world": [list(row) for row in obj.matrix_world]} for obj in bpy.context.scene.objects],
              "sources_modified": False, "weights_modified": False, "PBR_repaired": False, "normal_replaced": False,
              "rig_approved": False, "gait_approved": False, "rider_fit_approved": False, "production_approved": False}
    fit = None
    for candidate in candidates:
        if candidate["maximum_nearest_surface_distance_m"] >= 1e-6:
            continue
        try:
            comparison = rig_core.triangle_correspondence(source, returned, candidate)
            mapping, triangle_rows = triangle_mapping(source, returned, candidate)
            if comparison["maximum_errors"]["uv"] >= 1e-6 or comparison["winding_reversals"]:
                continue
            fit = candidate
            break
        except ValueError:
            continue
    report["physical_frame_proven_by_full_triangles_and_uv"] = fit is not None
    report["skeleton"] = rig_core.skeleton_report(armatures, meshes, fit)
    report["skeleton"].pop("hand_grip_and_foot_deformation_approved", None)
    report["skeleton"]["anatomy_and_deformation_approved"] = False
    original_images = texture.image_audit(source_document, source_binary, decode=False)
    actual_images = {node["image"]["sha256"]: node["image"] for material in report["received_materials"] for node in material["nodes"] if node.get("image", {}).get("sha256")}
    report["texture_payloads"] = {"expected": original_images, "matching_roles": [item["role"] for item in original_images if item["sha256"] in actual_images],
                                   "all_three_original_payloads_present": all(item["sha256"] in actual_images for item in original_images), "graph_compatibility_approved": False}
    evaluated = meshes[0].evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in evaluated_mesh.vertices])
    report["actual_rest_evaluation"] = {"vertices": len(points), "count_matches": len(points) == len(returned["positions"]),
                                        "maximum_received_world_difference_m": float(np.linalg.norm(points - returned["positions"], axis=1).max()) if len(points) == len(returned["positions"]) else None}
    evaluated.to_mesh_clear()
    if fit:
        report["frame_fit"] = fit
        report["surface_correspondence"] = comparison
        report["split_identity"] = texture.split_identity(source_native, split_pairs, mapping)
        rows = report["skeleton"]["weights"][0]["all_vertex_weights"]
        deform_names = {bone.name for bone in armatures[0].data.bones if bone.use_deform}
        report["weight_metrics"] = weight_metrics(rows, deform_names)
        report["saddle_buckle_regions"] = []
        source_triangle_by_native = native_analysis["source_triangle_native_polygons"]
        for patch in native_analysis["plan"]["accessory_patches"]:
            polygons = set(patch["face_indices"])
            source_vertices = {int(vertex) for face, triangle in enumerate(source_arrays["indices"]) if source_triangle_by_native[face] in polygons for vertex in triangle}
            cloud_vertices = {index for source_index in source_vertices for index in mapping[source_index]}
            report["saddle_buckle_regions"].append({"native_patch_root": patch["patch_root"], "source_native_faces": patch["face_count"],
                                                     "weight_summary": region_weights(rows, cloud_vertices)})
        foot_probes = []
        for fore_sign in (-1, 1):
            for side_sign in (-1, 1):
                selected = [row["vertex"] for row in rows if row["world_review_m"][2] < .12 and row["world_review_m"][0] * fore_sign > 0 and row["world_review_m"][1] * side_sign > .10]
                foot_probes.append({"x_sign": fore_sign, "y_sign": side_sign, "max_height_m": .12, "scope": "Spatial ground quadrant only, not a semantic foot-bone assignment", "weights": region_weights(rows, selected)})
        report["ground_quadrant_probes"] = foot_probes
        texture.core.save(output / "full_triangle_correspondence.json", {"source_vertex_to_returned_vertices": {str(index): sorted(values) for index, values in mapping.items()},
                         "source_render_vertex_to_native_vertex": source_native, "triangles": triangle_rows})
        report["correspondence_file"] = texture.core.record(output / "full_triangle_correspondence.json")
    else:
        report["status"] = "physical_frame_or_surface_correspondence_failed_received_rig_preserved"
    for item in spec["frozen_inputs"]:
        texture.checked_record(item)
    report["all_frozen_inputs_unchanged_after_inspection"] = True
    texture.core.save(output / "inspection.json", report)
    print(json.dumps({"status": report["status"], "physical_frame": fit is not None,
                      "bones": len(armatures[0].data.bones), "split_pairs": report.get("split_identity", {}).get("retained_split_pairs"),
                      "texture_payloads": report["texture_payloads"]["matching_roles"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "inspect"), required=True)
    parser.add_argument("--returned", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = fresh_output(args.output)
    if args.mode == "plan" and args.returned:
        plan(output, args.returned.resolve())
    elif args.mode == "inspect" and args.spec:
        inspect(output, args.spec.resolve())
    else:
        raise ValueError("Plan requires actual returned file; inspect requires frozen spec")


if __name__ == "__main__":
    main()
