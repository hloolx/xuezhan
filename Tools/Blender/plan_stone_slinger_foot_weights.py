"""Plan local sole weights using retained topology and verify an LBS prediction."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np

import inspect_stone_slinger_rig as rig
import review_stone_slinger_texture as texture


CANDIDATE = rig.BRANCH / "rig_transfer_candidate_03"
BLEND_SHA = "5a80dc87866c2947fb1bd55af3fd1a6d8ee85bff9512b07a2b96026930f27ff1"


def fade_height(height, full_height, zero_height):
    amount = min(1., max(0., (height - full_height) / (zero_height - full_height)))
    return 1 - amount * amount * (3 - 2 * amount)


def transfer_proximal(weights, side, amount):
    result = dict(weights)
    allowed = {"calf_" + side, "calf_twist_01_" + side, "thigh_" + side, "thigh_twist_01_" + side}
    moved = 0.
    for name in allowed & weights.keys():
        value = weights[name] * amount
        result[name] -= value
        moved += value
    result["foot_" + side] = result.get("foot_" + side, 0) + moved
    result = {name: value for name, value in result.items() if value > 1e-12}
    return result, moved


def axis_rotation(axis, degrees):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    cosine, sine = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    cross = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    result = np.eye(4)
    result[:3, :3] = cosine * np.eye(3) + (1 - cosine) * np.outer(axis, axis) + sine * cross
    return result


def pose_matrices(bones, commands):
    rest = {bone["name"]: np.array(bone["rest_matrix_armature_local"]) for bone in bones}
    parents = {bone["name"]: bone["parent"] for bone in bones}
    basis = {name: np.eye(4) for name in rest}
    for name, world_axis, degrees in commands:
        local_axis = np.linalg.solve(rest[name][:3, :3], world_axis)
        basis[name] = axis_rotation(local_axis, degrees)
    posed = {}

    def resolve(name):
        if name not in posed:
            parent = parents[name]
            posed[name] = (resolve(parent) @ np.linalg.inv(rest[parent]) if parent else np.eye(4)) @ rest[name] @ basis[name]
        return posed[name]

    for name in rest:
        resolve(name)
    return rest, posed


def deform(positions, weights, bones, commands):
    rest, posed = pose_matrices(bones, commands)
    skin = {name: posed[name] @ np.linalg.inv(matrix) for name, matrix in rest.items()}
    homogeneous = np.column_stack((positions, np.ones(len(positions))))
    output = np.zeros((len(positions), 3))
    for index, row in enumerate(weights):
        for name, weight in row.items():
            output[index] += (skin[name] @ homogeneous[index])[:3] * weight
    return output, skin


def connected_regions(adjacency, vertices):
    remaining = set(vertices)
    components = []
    while remaining:
        start = min(remaining)
        pending, found = [start], set()
        while pending:
            current = pending.pop()
            if current in found or current not in remaining:
                continue
            found.add(current)
            pending.extend(adjacency[current] & remaining)
        remaining -= found
        components.append(sorted(found))
    return sorted(components, key=len, reverse=True)


def projection(path, native_positions, native_weights, native_moved, native_after, bands, regions):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (800, 1260), "#161b22")
    draw = ImageDraw.Draw(canvas)
    draw.text((16, 10), "StoneSlinger sole-weight PLAN | source topology, no mesh/weight applied", fill="white")
    draw.text((16, 30), "Blue=0 proximal influence, orange/magenta=1 | cyan dashed=blend band", fill="#d5dce7")
    for column, side in enumerate(("l", "r")):
        sign = 1 if side == "l" else -1
        points = {index: point for index, point in native_positions.items() if sign * point[1] > 0 and point[2] < .4}
        minimum_x = min(point[0] for point in points.values()) - .025
        maximum_x = max(point[0] for point in points.values()) + .025
        for row, label in enumerate(("BEFORE proximal weight", "PROPOSED proximal weight", "TRANSFER to foot (ball retained)")):
            left, top = column * 400 + 28, row * 400 + 80
            width, height = 344, 340
            draw.text((left, top - 20), side.upper() + " foot: " + label, fill="white")

            def project(point):
                return (left + (point[0] - minimum_x) / (maximum_x - minimum_x) * width,
                        top + height - point[2] / .4 * height)

            for index, point in points.items():
                for neighbor in regions["adjacency"][index]:
                    if neighbor in points and neighbor > index:
                        draw.line((*project(point), *project(points[neighbor])), fill="#344251", width=1)
            for height_value in bands[side].values():
                ordinate = top + height - height_value / .4 * height
                for start in range(int(left), int(left + width), 12):
                    draw.line((start, ordinate, start + 6, ordinate), fill="#6be5e2", width=1)
            allowed = {"calf_" + side, "calf_twist_01_" + side, "thigh_" + side, "thigh_twist_01_" + side}
            for index, point in points.items():
                weights = native_after[index] if row == 1 else native_weights[index]
                amount = native_moved.get(index, 0.) if row == 2 else sum(weight for name, weight in weights.items() if name in allowed)
                amount = min(1., max(0., amount))
                color = (int(45 + amount * 210), int(150 - amount * 90), int(235 - amount * 90))
                position = project(point)
                radius = 2.1 if native_moved.get(index, 0) > 1e-8 else 1.2
                draw.ellipse((position[0] - radius, position[1] - radius, position[0] + radius, position[1] + radius), fill=color)
            draw.text((left, top + height + 6), "heel  -X <----> +X toe; height 0..40cm", fill="#aebdcc")
    canvas.save(path)


def analyze(output):
    blend = CANDIDATE / "Unit_StoneSlinger_ReviewedSurface_RealRig.blend"
    if rig.record(blend)["sha256"] != BLEND_SHA:
        raise ValueError("Approved source-mesh real-rig candidate changed")
    report_path = CANDIDATE / "transfer_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mapping_path = Path(report["mapping"]["path"])
    if rig.record(mapping_path) != report["mapping"]:
        raise ValueError("Frozen full-triangle correspondence changed")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    arrays = texture.read_glb(rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    bones = report["actual_final_skeleton"]["armatures"][0]["bones"]
    native_ids = [mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(positions))]
    native_positions, native_weights = {}, {}
    for index, native in enumerate(native_ids):
        native_positions[native] = positions[index]
        if native in native_weights and native_weights[native] != weights[index]:
            raise ValueError("One native surface vertex has differing seam weights; do not silently average")
        native_weights[native] = weights[index]
    adjacency = defaultdict(set)
    for triangle in arrays["indices"]:
        native_triangle = [native_ids[index] for index in triangle]
        for start, end in zip(native_triangle, native_triangle[1:] + native_triangle[:1]):
            adjacency[start].add(end)
            adjacency[end].add(start)
    bands, selections = {}, {}
    for side, sign in (("l", 1), ("r", -1)):
        ankle = next(bone for bone in bones if bone["name"] == "foot_" + side)["head_world_review_m"][2]
        bands[side] = {"full_transfer_below_m": ankle - .025, "zero_transfer_above_m": ankle + .10}
        domain = {index for index, point in native_positions.items() if sign * point[1] > 0 and point[2] < bands[side]["zero_transfer_above_m"]}
        components = connected_regions(adjacency, domain)
        seeded = [component for component in components if min(native_positions[index][2] for index in component) < .025]
        if not seeded:
            raise ValueError("No topologically connected sole seed on side " + side)
        selections[side] = {"native_vertices": sorted({index for component in seeded for index in component}),
                            "component_counts": [len(component) for component in seeded],
                            "excluded_nonsole_components": [len(component) for component in components if component not in seeded]}
    after = [dict(row) for row in weights]
    rows = []
    native_after = {index: dict(value) for index, value in native_weights.items()}
    native_moved = {}
    for index, (point, native) in enumerate(zip(positions, native_ids)):
        side = "l" if point[1] > 0 else "r"
        if native not in selections[side]["native_vertices"]:
            continue
        allowed_names = {stem + "_" + side for stem in ("foot", "ball", "calf", "calf_twist_01", "thigh", "thigh_twist_01")}
        if set(weights[index]) - allowed_names:
            raise ValueError("Selected boot point has nonlocal/cross-leg influence; requires explicit separate review")
        amount = fade_height(point[2], bands[side]["full_transfer_below_m"], bands[side]["zero_transfer_above_m"])
        updated, moved = transfer_proximal(weights[index], side, amount)
        if moved <= 1e-8:
            continue
        after[index] = updated
        native_after[native], native_moved[native] = updated, moved
        rows.append({"source_vertex": index, "native_vertex": native, "side": side, "rest_world_m": point.tolist(),
                     "height_fade": amount, "transferred_proximal_weight": moved,
                     "before": weights[index], "after": updated})
    output.mkdir(parents=True, exist_ok=False)
    record_path = output / "planned_vertex_weight_changes.json"
    rig.save(record_path, {"changes": rows, "source_vertex_count": len(positions), "apply_permitted": False})
    validated_before = []
    for actual in report["pose_checks"]:
        predicted, _ = deform(positions, weights, bones, actual["commands"])
        error = max(float(np.linalg.norm(predicted[row["source_vertex"]] - row["actual_world_m"]))
                    for row in actual["lowest154_cloud_vertex_diagnostic"])
        validated_before.append({"pose": actual["pose"], "actual_Blender_lowfoot_points": 154,
                                 "maximum_predicted_vs_actual_error_m": error, "passed3micrometer_gate": error < 3e-6})
    if not all(row["passed3micrometer_gate"] for row in validated_before):
        rig.save(output / "prediction_failure.json", validated_before)
        raise ValueError("Offline skin math is not validated against actual existing Blender poses")
    pose_defs = {"ankle_minus10": [("foot_l", (0, 1, 0), -10), ("foot_r", (0, 1, 0), -10)],
                 "ankle_plus10": [("foot_l", (0, 1, 0), 10), ("foot_r", (0, 1, 0), 10)],
                 "ankle_minus20": [("foot_l", (0, 1, 0), -20), ("foot_r", (0, 1, 0), -20)],
                 "ankle_plus20": [("foot_l", (0, 1, 0), 20), ("foot_r", (0, 1, 0), 20)],
                 "knee_plus15": [("calf_l", (0, 1, 0), 15), ("calf_r", (0, 1, 0), 15)],
                 "toe_lift": [("ball_l", (0, 1, 0), -20), ("ball_r", (0, 1, 0), -20)],
                 "heel_lift": [("foot_l", (0, 1, 0), 15), ("foot_r", (0, 1, 0), 15),
                               ("ball_l", (0, 1, 0), -15), ("ball_r", (0, 1, 0), -15)]}
    sole_indices = np.flatnonzero(positions[:, 2] < .025)
    predictions = []
    for label, commands in pose_defs.items():
        original, matrices = deform(positions, weights, bones, commands)
        changed, _ = deform(positions, after, bones, commands)
        before_errors, after_errors = [], []
        for index in sole_indices:
            side = "l" if positions[index, 1] > 0 else "r"
            ideal = (matrices["foot_" + side] @ np.append(positions[index], 1))[:3]
            before_errors.append(float(np.linalg.norm(original[index] - ideal)))
            after_errors.append(float(np.linalg.norm(changed[index] - ideal)))
        predictions.append({"pose": label, "commands": commands,
                            "lowfoot_maximum_rigid_foot_error_before_m": max(before_errors),
                            "lowfoot_maximum_rigid_foot_error_after_m": max(after_errors),
                            "maximum_changed_vertex_displacement_m": float(np.linalg.norm(changed - original, axis=1).max()),
                            "interpretation": "Offline LBS prediction only; toe/heel ball articulation deliberately differs from a rigid wholefoot and is not a failure by that metric."})
    graph_path = output / "foot_region_projection.png"
    projection(graph_path, native_positions, native_weights, native_moved, native_after, bands, {"adjacency": adjacency})
    changed_indices = {row["source_vertex"] for row in rows}
    changed_native = {row["native_vertex"] for row in rows}
    result = {"asset_id": "Unit_StoneSlinger", "status": "semantic_local_sole_weight_plan_only_not_applied",
              "source_blend": rig.record(blend), "source_report": rig.record(report_path), "source_mesh": rig.record(rig.SOURCE),
              "script": rig.record(Path(__file__)), "planned_changes": rig.record(record_path), "projection": rig.record(graph_path),
              "actual_reviewed_source_bounds_m": {"min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
              "anatomical_bands": bands, "topological_selection": selections,
              "affected_render_vertices": len(rows), "affected_native_vertices": len(changed_native),
              "affected_bounds_m": {"min": positions[sorted(changed_indices)].min(axis=0).tolist(), "max": positions[sorted(changed_indices)].max(axis=0).tolist()},
              "candidate_policy": "Retain every existing ball/toe weight. Transfer only local proximal leg influences into foot using C1smoothstep by ankle-derived height. Full belowankle-2.5cm, zero aboveankle+10cm; preserve cuff/upperboot/leg/upperbody. Select only native face-connected components reaching actual sole<2.5cm. No sourcevertex welding, no wholeboot rigid binding, no weight averaging.",
              "unaffected_weight_rows_exact": all(after[index] == weights[index] for index in range(len(weights)) if index not in changed_indices),
              "maximum_weight_sum_error": max(abs(sum(row.values()) - 1) for row in after),
              "maximum_influences_after": max(len(row) for row in after),
              "ball_weights_exact": all(after[index].get("ball_" + side, 0) == weights[index].get("ball_" + side, 0) for index in range(len(weights)) for side in ("l", "r")),
              "offline_skin_prediction_validation": validated_before, "predictions": predictions,
              "required_actual_batch": ["Render exact affected-source point/region overlay to confirm anatomical scope", "Apply only listed weight rows to newcandidate and audit original mesh/PBR/all other weights unchanged", "Actual ankle±10/20degrees, knee15, toe lift and heel lift comparisons with no ground compensation", "Report every sole heel/toe point and transition-edge stretch, not just globalminimumZ", "Return to originalrest and preserve reference source"],
              "Blender_started": False, "weight_correction_applied": False, "production_approved": False}
    rig.save(output / "foot_weight_plan.json", result)
    print(json.dumps({"status": result["status"], "affected_render_vertices": len(rows), "affected_native_vertices": len(changed_native),
                      "bands": bands, "components": {side: row["component_counts"] for side, row in selections.items()},
                      "max_prediction_error_m": max(row["maximum_predicted_vs_actual_error_m"] for row in validated_before),
                      "ankle_minus10_after_m": predictions[0]["lowfoot_maximum_rigid_foot_error_after_m"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Use a fresh plan directory")
    analyze(output)


if __name__ == "__main__":
    main()
