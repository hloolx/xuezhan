"""Read exact saved diagnostic Actions and measure the already flagged triangle pairs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mammoth_follower_visual as visual


FOLDER = visual.transfer.BRANCH / "rig_follower_visual_01"
REPORT = FOLDER / "actual_visual_02/diagnostic.json"
REPORT_SHA = "4e81fcdde923b57b701ee0ff483d5b4bae7354a39ca42f81cdb42f2b74c8bfda"


def triangle_details(first, second):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    normals = [np.cross(points[1] - points[0], points[2] - points[0]) for points in (first, second)]
    lengths = [float(np.linalg.norm(normal)) for normal in normals]
    if min(lengths) <= visual.AREA_TOLERANCE_M2:
        return {"kind": "degenerate", "positions_m": [first.tolist(), second.tolist()]}
    units = [normal / length for normal, length in zip(normals, lengths)]
    second_to_first = (second - first[0]) @ units[0]
    first_to_second = (first - second[0]) @ units[1]
    coplanar = max(abs(second_to_first)) <= visual.INTERSECTION_TOLERANCE_M and max(abs(first_to_second)) <= visual.INTERSECTION_TOLERANCE_M
    witnesses = []
    for owner, edges, triangle, unit in ((0, first, second, units[1]), (1, second, first, units[0])):
        for edge_index in range(3):
            start, end = edges[edge_index], edges[(edge_index + 1) % 3]
            start_depth, end_depth = float((start - triangle[0]) @ unit), float((end - triangle[0]) @ unit)
            denominator = start_depth - end_depth
            if abs(denominator) < 1e-20:
                continue
            fraction = start_depth / denominator
            if not 0 <= fraction <= 1:
                continue
            point = start + fraction * (end - start)
            first_edge, second_edge = triangle[1] - triangle[0], triangle[2] - triangle[0]
            relative = point - triangle[0]
            gram = np.array([[first_edge @ first_edge, first_edge @ second_edge], [first_edge @ second_edge, second_edge @ second_edge]])
            coordinates = np.linalg.solve(gram, [relative @ first_edge, relative @ second_edge])
            barycentric = np.array([1 - sum(coordinates), coordinates[0], coordinates[1]])
            if min(barycentric) < -1e-8:
                continue
            witnesses.append({"edge_triangle": owner, "edge_index": edge_index, "intersection_world_m": point.tolist(), "edge_fraction": float(fraction),
                              "other_triangle_barycentric": barycentric.tolist(), "signed_endpoint_depths_m": [start_depth, end_depth],
                              "two_sided_endpoint_depth_margin_m": min(abs(start_depth), abs(end_depth)),
                              "strict_original_crossing_witness": start_depth * end_depth < 0 and min(abs(start_depth), abs(end_depth)) > visual.INTERSECTION_TOLERANCE_M and min(barycentric) > visual.INTERSECTION_TOLERANCE_M / max(np.linalg.norm(first_edge), np.linalg.norm(second_edge))})
    intersection_points = np.array([row["intersection_world_m"] for row in witnesses])
    intersection_length = float(np.max(np.linalg.norm(intersection_points[:, None] - intersection_points[None], axis=2))) if len(intersection_points) >= 2 else 0.
    area = visual.clipped_triangle_area(first, second) if coplanar else 0.
    proper = visual.proper_triangle_intersection(first, second)
    kind = "coplanar_area_overlap" if coplanar and proper else "proper_crossing" if proper else "coplanar_touch_or_disjoint" if coplanar else "no_proper_crossing"
    return {"kind": kind, "original_detector_true": proper, "positions_m": [first.tolist(), second.tolist()], "normals_from_original_winding": [unit.tolist() for unit in units],
            "first_vertices_signed_distance_to_second_plane_m": first_to_second.tolist(), "second_vertices_signed_distance_to_first_plane_m": second_to_first.tolist(),
            "maximum_absolute_plane_depth_m": float(max(max(abs(first_to_second)), max(abs(second_to_first)))),
            "normal_angle_degrees": float(np.degrees(np.arctan2(np.linalg.norm(np.cross(units[0], units[1])), units[0] @ units[1]))),
            "coplanar_overlap_area_m2": area, "intersection_segment_length_m": intersection_length, "edge_plane_witnesses": witnesses,
            "maximum_strict_crossing_endpoint_margin_m": max((row["two_sided_endpoint_depth_margin_m"] for row in witnesses if row["strict_original_crossing_witness"]), default=0.)}


def prepare():
    if visual.core.record(REPORT)["sha256"] != REPORT_SHA:
        raise ValueError("Frozen actual diagnostic report changed")
    report = visual.read_json(REPORT)
    spec = visual.read_json(FOLDER / "execution_spec_v02.json")
    for record in spec["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    visual.transfer.audit_tool.texture.checked_record(report["saved_real_actions_scene"])
    path = FOLDER / "intersection_probe_03_spec.json"
    if path.exists() or (FOLDER / "intersection_probe_03").exists():
        raise FileExistsError("Preserve earlier probe evidence")
    pairs = sorted({tuple(pair) for pose in report["poses"] for pair in pose["new_intersection_pairs"]} | {tuple(pair) for pair in report["rest_new_intersections"]})
    if len(pairs) != 19:
        raise ValueError("Do not expand the nineteen flagged pairs")
    output = {"status": "frozen_readonly_actual_pair_probe", "root_authorization": "One zero-render read-only reopening of the saved blend, replaying the same actions and measuring the nineteen flagged pairs; no modification of models, actions or thresholds",
              "prior_report": visual.core.record(REPORT), "scene": report["saved_real_actions_scene"], "candidate": spec["candidate"], "mask_plan": spec["mask_plan"], "pairs": pairs,
              "frozen_inputs": spec["frozen_inputs"] + [visual.core.record(REPORT), report["saved_real_actions_scene"], visual.core.record(Path(__file__))],
              "restrictions": {"threads": 2, "priority": "BelowNormal", "renders": 0, "model_exports": 0, "saves": 0, "weight_search": 0},
              "command": {"executable": spec["command"]["executable"], "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(path)]}}
    visual.core.save(path, output)
    print(json.dumps(visual.core.record(path)))


def run(spec_path):
    import bpy
    spec = visual.read_json(spec_path)
    for record in spec["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    output = FOLDER / "intersection_probe_03"
    output.mkdir(exist_ok=False)
    prior = visual.read_json(spec["prior_report"]["path"])
    bpy.ops.wm.open_mainfile(filepath=spec["scene"]["path"])
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    baseline_rig = next(obj for obj in rigs if len(obj.data.bones) == 33)
    candidate_rig = next(obj for obj in rigs if len(obj.data.bones) == 35)
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    body_for = lambda rig: next(body for body in bodies if any(modifier.type == "ARMATURE" and modifier.object == rig for modifier in body.modifiers))
    baseline_body, candidate_body = body_for(baseline_rig), body_for(candidate_rig)
    bases = [{bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones} for rig in (baseline_rig, candidate_rig)]
    for rig, rest in zip((baseline_rig, candidate_rig), bases):
        visual.reset_pose(rig, rest)
    arrays = visual.transfer.source_arrays(*visual.transfer.read_container(spec["candidate"]["path"]))
    native_map, _, analysis = visual.transfer.audit_tool.texture.native_identity(arrays)
    masks = visual.read_json(spec["mask_plan"]["path"])["regions"]
    source_points = arrays["POSITION"] @ visual.transfer.BASIS.T
    report = {"status": "started_actual_pairs", "process_id": __import__("os").getpid(), "pair_count": len(spec["pairs"]), "pairs": [], "poses": [], "renders": 0, "edits": 0, "historical_safety_gate": "FAIL"}
    try:
        for pair in spec["pairs"]:
            parts = []
            for face in pair:
                vertices = arrays["indices"][face]
                part = next(("metal_" + str(region["native_patch"]) for region in masks if set(int(index) for index in vertices).issubset(region["metal_render_vertices"])), None)
                if part is None:
                    part = next(("reviewed_cloth_" + str(region["native_patch"]) for region in masks if any(str(native_map[int(index)]) in region["outer12cm_native_geodesic_distances_m"] for index in vertices)), "outside_reviewed_region")
                parts.append(part)
            report["pairs"].append({"triangles": pair, "source_native_polygons": [analysis["source_triangle_native_polygons"][face] for face in pair], "parts": parts,
                                   "actual_materials": [material.name for material in candidate_body.data.materials], "raw_source_rest": triangle_details(*source_points[arrays["indices"][pair]])})
        commands = [{"name": "rest"}] + visual.transfer.POSES
        for command in commands:
            visual.reset_pose(baseline_rig, bases[0])
            visual.reset_pose(candidate_rig, bases[1])
            if command["name"] != "rest":
                visual.apply_command(baseline_rig, command)
                pose = next(row for row in prior["poses"] if row["pose"] == command["name"])
                action = bpy.data.actions[pose["baked_action"]["name"]]
                candidate_rig.animation_data.action = action
                candidate_rig.animation_data.action_slot = next(slot for slot in action.slots if slot.identifier == pose["baked_action"]["slot"])
                bpy.context.scene.frame_set(2)
            baseline_points, candidate_points = visual.evaluate(baseline_body), visual.evaluate(candidate_body)
            pair_rows = []
            originally_flagged = prior["rest_new_intersections"] if command["name"] == "rest" else next(row["new_intersection_pairs"] for row in prior["poses"] if row["pose"] == command["name"])
            for pair in spec["pairs"]:
                faces = arrays["indices"][pair]
                pair_rows.append({"triangles": pair, "flagged_in_prior_same_pose": pair in originally_flagged,
                                  "actual_baseline": triangle_details(*baseline_points[faces]), "actual_candidate": triangle_details(*candidate_points[faces])})
            report["poses"].append({"pose": command["name"], "pairs": pair_rows})
            visual.core.save(output / "actual_intersections.json", report)
        report["status"] = "actual_signed_depth_and_segment_evidence_complete_no_changes"
        report["depth_definition"] = "Signed vertex distances to the opposing triangle plane use each retained triangle's original winding. They are not a closed-solid volume penetration depth. Strict edge-plane witnesses include endpoint distances, barycentric location and intersection-segment extent, distinguishing transverse crossings from near-coplanar contact."
        report["unchanged_tolerances"] = {"intersection_m": visual.INTERSECTION_TOLERANCE_M, "coplanar_area_m2": visual.AREA_TOLERANCE_M2}
        for record in spec["frozen_inputs"]:
            visual.transfer.audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
    except Exception as error:
        report["status"], report["error"] = "failed_preserved", str(error)
        visual.core.save(output / "actual_intersections.json", report)
        raise
    visual.core.save(output / "actual_intersections.json", report)
    print(json.dumps({"report": visual.core.record(output / "actual_intersections.json"), "poses": len(report["poses"]), "pairs": len(report["pairs"])}))


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
