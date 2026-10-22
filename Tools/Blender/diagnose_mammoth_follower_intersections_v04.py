"""Repeat the frozen read-only pair probe with JSON-safe scalar output only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose_mammoth_follower_intersections as original


visual = original.visual
FOLDER = original.FOLDER


def json_safe(value):
    def scalar(item):
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError("Unsupported report value: " + type(item).__name__)
    return json.loads(json.dumps(value, default=scalar, allow_nan=False))


def prepare():
    prior = visual.read_json(FOLDER / "intersection_probe_03_spec.json")
    for record in prior["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    path = FOLDER / "intersection_probe_04_spec.json"
    if path.exists() or (FOLDER / "intersection_probe_04").exists():
        raise FileExistsError("Preserve prior evidence")
    spec = dict(prior)
    spec["status"] = "frozen_json_scalar_conversion_only"
    spec["root_authorization"] = "Root authorized fresh04 after PID71876 serialization failure. Convert NumPy scalars to equivalent JSON scalar types only; same exact nineteen triangle pairs, geometric predicates, thresholds, saved actions and source."
    spec["frozen_inputs"] = prior["frozen_inputs"] + [visual.core.record(Path(__file__)), visual.core.record(FOLDER / "intersection_probe_03_spec.json")]
    spec["command"] = {"executable": prior["command"]["executable"], "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(path)]}
    visual.core.save(path, spec)
    print(json.dumps(visual.core.record(path)))


def run(spec_path):
    import bpy
    spec = visual.read_json(spec_path)
    for record in spec["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    output = FOLDER / "intersection_probe_04"
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
    report = {"status": "started_actual_pairs", "process_id": __import__("os").getpid(), "pair_count": len(spec["pairs"]), "pairs": [], "poses": [], "renders": 0, "edits": 0, "historical_safety_gate": "FAIL", "only_change_from_probe03": "Equivalent JSON-safe NumPy scalar conversion"}
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
                                   "actual_materials": [material.name for material in candidate_body.data.materials], "raw_source_rest": original.triangle_details(*source_points[arrays["indices"][pair]])})
        for command in [{"name": "rest"}] + visual.transfer.POSES:
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
            flagged = prior["rest_new_intersections"] if command["name"] == "rest" else next(row["new_intersection_pairs"] for row in prior["poses"] if row["pose"] == command["name"])
            rows = [{"triangles": pair, "flagged_in_prior_same_pose": pair in flagged, "actual_baseline": original.triangle_details(*baseline_points[arrays["indices"][pair]]),
                     "actual_candidate": original.triangle_details(*candidate_points[arrays["indices"][pair]])} for pair in spec["pairs"]]
            report["poses"].append({"pose": command["name"], "pairs": rows})
            visual.core.save(output / "actual_intersections.json", json_safe(report))
        report["status"] = "actual_signed_depth_and_segment_evidence_complete_no_changes"
        report["depth_definition"] = "Signed vertex distances to opposing triangle planes follow retained winding, not closed-solid volume penetration depth. Strict edge-plane witnesses record signed endpoint distances, barycentric location and intersection-segment length."
        report["unchanged_tolerances"] = {"intersection_m": visual.INTERSECTION_TOLERANCE_M, "coplanar_area_m2": visual.AREA_TOLERANCE_M2}
        for record in spec["frozen_inputs"]:
            visual.transfer.audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
    except Exception as error:
        report["status"], report["error"] = "failed_preserved", str(error)
        visual.core.save(output / "actual_intersections.json", json_safe(report))
        raise
    visual.core.save(output / "actual_intersections.json", json_safe(report))
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
