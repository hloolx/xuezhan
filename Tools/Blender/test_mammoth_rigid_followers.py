"""One pure-data feasibility test for two baked rigid buckle follower joints."""
from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimize_mammoth_buckle_weights as optimizer
import analyze_mammoth_buckle_constraints as bounds_tool


def proper_rigid_fit(source, target, weights):
    weights = np.array(weights, dtype=float)
    weights /= weights.sum()
    source_center = weights @ source
    target_center = weights @ target
    covariance = (source - source_center).T @ ((target - target_center) * weights[:, None])
    left, singular, right = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[2, 2] = 1. if np.linalg.det(right.T @ left.T) >= 0 else -1.
    rotation = right.T @ correction @ left.T
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = target_center - rotation @ source_center
    if abs(np.linalg.det(rotation) - 1) > 1e-10 or np.max(abs(rotation.T @ rotation - np.eye(3))) > 1e-10:
        raise ValueError("Rigid fit introduced scale or reflection")
    if singular[1] < 1e-12:
        raise ValueError("Attachment samples are collinear; twist is unobservable")
    return matrix, singular


def fit_sparse_original(original_joint_positions, target_positions, original_weights):
    joints = list(original_weights)
    best = None
    for size in range(1, min(3, len(joints)) + 1):
        for selected in combinations(joints, size):
            columns = np.column_stack([original_joint_positions[joint].reshape(-1) for joint in selected])
            target = target_positions.reshape(-1)
            gram = columns.T @ columns
            system = np.block([[gram, np.ones((size, 1))], [np.ones((1, size)), np.zeros((1, 1))]])
            rhs = np.r_[columns.T @ target, 1.]
            solution = np.linalg.lstsq(system, rhs, rcond=1e-12)[0][:size]
            if min(solution) < -1e-9:
                continue
            solution = np.maximum(solution, 0)
            solution /= solution.sum()
            predicted = (columns @ solution).reshape(target_positions.shape)
            error = float(np.max(np.linalg.norm(predicted - target_positions, axis=1)))
            retained_mass = sum(original_weights[joint] for joint in selected)
            candidate = (round(error, 9), -retained_mass, len(selected), selected, solution, error, predicted)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
    if best is None:
        raise ValueError("No nonnegative normalized sparse original-bone fit")
    return {joint: float(weight) for joint, weight in zip(best[3], best[4]) if weight > 1e-12}, best[5], best[6]


def analyze(output):
    transfer = optimizer.transfer
    started = time.monotonic()
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_follower_feasibility_"):
        raise ValueError("Use a fresh owned follower-feasibility directory")
    model = optimizer.accessory.MODEL
    if transfer.audit_tool.texture.core.record(model)["sha256"] != optimizer.accessory.MODEL_SHA:
        raise ValueError("Frozen real33bone model changed")
    document, binary = transfer.read_container(model)
    arrays = transfer.source_arrays(document, binary)
    native_map, _, analysis = transfer.audit_tool.texture.native_identity(arrays)
    representatives = {}
    for render, native in native_map.items():
        representatives.setdefault(native, render)
    joints = document["skins"][0]["joints"]
    names = [document["nodes"][index]["name"] for index in joints]
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    worlds = np.array([optimizer.accessory.pose_matrices(document, command) for command in transfer.POSES])
    matrices = worlds @ inverse
    original_positions = np.array([transfer.skin_positions(arrays["POSITION"], arrays["JOINTS_0"], arrays["WEIGHTS_0"], matrix) for matrix in matrices])
    masks = json.loads(optimizer.MASK_PLAN.read_text(encoding="utf-8-sig"))
    excluded = {face for patch in analysis["plan"]["accessory_patches"] for face in patch["face_indices"]}
    reports = []
    output.mkdir(parents=True, exist_ok=False)
    for region in masks["regions"]:
        metal_native = sorted({native_map[index] for index in region["metal_render_vertices"]})
        metal = [representatives[index] for index in metal_native]
        contacts = [representatives[index] for index in region["contact_native_vertices"]]
        samples = metal + contacts
        weights = np.r_[np.full(len(metal), .5 / len(metal)), np.full(len(contacts), .5 / len(contacts))]
        sample_source = arrays["POSITION"][samples].astype(float)
        rest_center = weights @ sample_source
        follower_rest = np.eye(4)
        follower_rest[:3, 3] = rest_center
        fits, fit_reports = [], []
        for pose_index, command in enumerate(transfer.POSES):
            target = original_positions[pose_index, samples]
            fitted, singular = proper_rigid_fit(sample_source, target, weights)
            predicted = (np.column_stack((sample_source, np.ones(len(samples)))) @ fitted.T)[:, :3]
            error = np.linalg.norm(predicted - target, axis=1)
            follower_world = fitted @ follower_rest
            local = np.linalg.inv(worlds[pose_index, names.index("tripo::Spine_3")]) @ follower_world
            fits.append(fitted)
            fit_reports.append({"pose": command["name"], "determinant": float(np.linalg.det(fitted[:3, :3])), "singular_values": singular.tolist(),
                                "metal_max_residual_m": float(max(error[:len(metal)])), "metal_rms_residual_m": float(np.sqrt(np.mean(error[:len(metal)] ** 2))),
                                "contact_max_residual_m": float(max(error[len(metal):])), "contact_rms_residual_m": float(np.sqrt(np.mean(error[len(metal):] ** 2))),
                                "follower_world_matrix_gltf_m": follower_world.tolist(), "proposed_parent": "tripo::Spine_3", "follower_local_matrix_gltf_m": local.tolist()})
        expanded = dict(region)
        expanded["transition_native_geodesic_distances_m"] = dict(region["outer12cm_native_geodesic_distances_m"])
        inside = {int(index) for index in expanded["transition_native_geodesic_distances_m"]}
        render_support = {index for index, native in native_map.items() if native in inside and index not in set(region["metal_render_vertices"])}
        expanded["transition_affected_triangles"] = [face for face, triangle in enumerate(arrays["indices"])
            if analysis["source_triangle_native_polygons"][face] not in excluded and any(int(index) in render_support for index in triangle)]
        data = optimizer.build_region(expanded, arrays, document, native_map, matrices)
        data["fixed"] = {data["lookup"][native]: 1. if native in data["seeds"] else 0. for native in data["native_ids"]
                         if native in data["seeds"] or native not in data["distances"] or data["distances"].get(native, .12) >= .12}
        anchored = np.einsum("pij,nj->pni", np.array(fits), np.column_stack((data["positions"], np.ones(len(data["positions"])))))[:, :, :3]
        delta = anchored - data["current"]
        problem = {"edge_arguments": {"current_edges": data["current_edges"], "first_delta": delta[:, data["first"]], "second_delta": delta[:, data["second"]],
                   "first_indices": data["first"], "second_indices": data["second"], "lengths": data["lengths"]}, "baseline_strain": data["baseline"]}
        fraction = np.array([min(1., data["distances"].get(native, .12) / .12) for native in data["native_ids"]])
        initial = 1 - fraction * fraction * (3 - 2 * fraction)
        alpha, objective, strain, iterations = optimizer.optimize(initial, problem, data["fixed"], iterations=160)
        sparse_positions = data["current"].copy()
        sparse_rows = []
        for native, local in data["lookup"].items():
            blend = float(alpha[local])
            if native not in inside or blend <= 1e-12:
                continue
            render = representatives[native]
            original = {int(joint): float(weight) for joint, weight in zip(arrays["JOINTS_0"][render], arrays["WEIGHTS_0"][render]) if weight > 0}
            if blend >= 1 - 1e-12:
                row, error, predicted_original = {}, 0., data["current"][:, local]
                blend = 1.
            else:
                homogeneous = np.r_[arrays["POSITION"][render], 1.]
                joint_positions = {joint: np.einsum("pij,j->pi", matrices[:, joint], homogeneous)[:, :3] for joint in original}
                row, error, predicted_original = fit_sparse_original(joint_positions, data["current"][:, local], original)
            proposed = {names[joint]: weight * (1 - blend) for joint, weight in row.items() if weight * (1 - blend) > 1e-12}
            proposed["derived_buckle_" + str(region["native_patch"])] = blend
            sparse_positions[:, local] = predicted_original * (1 - blend) + anchored[:, local] * blend
            sparse_rows.append({"native_vertex": native, "alpha": blend, "proposed_weights_not_applied": proposed,
                                "original_bone_subset_fit_max_error_m_across8poses": error, "explicit_dropped_original_bones": [names[joint] for joint in original if names[joint] not in proposed]})
        sparse_edges = sparse_positions[:, data["second"]] - sparse_positions[:, data["first"]]
        sparse_strain = np.linalg.norm(sparse_edges, axis=2) / data["lengths"][None, :] - 1
        metrics = optimizer.metric_rows(sparse_strain, data["baseline"], data["lengths"])
        contradictions = []
        pairs = list(zip(data["first"].tolist(), data["second"].tolist()))
        for pose_index, command in enumerate(transfer.POSES):
            upper = data["lengths"] * (1 + abs(data["baseline"][pose_index]) + optimizer.STRAIN_NUMERIC_TOLERANCE)
            for seed_native in data["seeds"]:
                seed = data["lookup"][seed_native]
                distances, previous = bounds_tool.shortest_upper_bound_paths(len(data["native_ids"]), pairs, upper, seed)
                for boundary, value in data["fixed"].items():
                    if value != 0 or boundary not in distances:
                        continue
                    required = float(np.linalg.norm(anchored[pose_index, seed] - data["current"][pose_index, boundary]))
                    if required > distances[boundary] + transfer.TOLERANCE_M:
                        path = [boundary]
                        while path[-1] != seed:
                            path.append(previous[path[-1]])
                        contradictions.append({"pose": command["name"], "native_path": [data["native_ids"][index] for index in reversed(path)],
                                               "required_distance_m": required, "allowed_path_total_m": distances[boundary], "excess_m": required - distances[boundary]})
        contradictions.sort(key=lambda row: -row["excess_m"])
        maximum_influences = max(len(row["proposed_weights_not_applied"]) for row in sparse_rows)
        maximum_weight_sum_error = max(abs(sum(row["proposed_weights_not_applied"].values()) - 1) for row in sparse_rows)
        passed = not contradictions and all(row["edges_worse_than_original_by_tolerance"] == 0 for row in metrics) and maximum_influences <= 4 and maximum_weight_sum_error < 1e-5
        reports.append({"patch": region["native_patch"], "metal_unique_native_samples": len(metal), "contact_unique_native_samples": len(contacts),
                        "sample_weight_policy": "Fixed50percenttotalmetal/50percenttotalcontacts; no parameter search", "derived_bone_rest_matrix_gltf_m": follower_rest.tolist(),
                        "pose_fits": fit_reports, "12cm_cloth_native_count": len(inside), "one_transition_trial_iterations": iterations, "transition_objective": objective,
                        "pose_metrics_after_explicit_max4_sparse_fit": metrics, "sparse_native_weights_not_applied": sparse_rows,
                        "maximum_influences": maximum_influences, "weight_sum_max_error": maximum_weight_sum_error,
                        "maximum_sparse_original_motion_fit_error_m": max(row["original_bone_subset_fit_max_error_m_across8poses"] for row in sparse_rows),
                        "coincident_contact_rows_identical_follower1": True, "rigid_metal_single_follower1": True,
                        "path_bound_contradiction_count": len(contradictions), "top_path_bound_contradictions": contradictions[:8], "strict_numeric_feasible": passed})
    report = {"asset_id": "Mount_Mammoth", "status": "single_rigid_follower_feasibility_complete_no_model_or_bone_changes",
              "elapsed_seconds": time.monotonic() - started, "source_model": transfer.audit_tool.texture.core.record(model), "source_mask_plan": transfer.audit_tool.texture.core.record(optimizer.MASK_PLAN),
              "script": transfer.audit_tool.texture.core.record(Path(__file__)), "existing_bones": 33, "proposed_derived_bones": 2, "actual_bones_added": 0,
              "existing_diagnostic_poses": 8, "fit_policies_tried": 1, "transition_initializations_each": 1, "regions": reports,
              "both_regions_strict_numeric_feasible": all(region["strict_numeric_feasible"] for region in reports),
              "runtime_requirement": "These are sampled proposed transforms, not UE-ready constraints. Every future Idle/Walk/Attack/Hit/Death clip needs continuous follower transforms baked into real bone animation or an implemented validated runtime controller; eight Blender poses or constraints alone cannot establish UE usability.",
              "limitations": ["Sparseoriginalbonefits may exploit equivalent motion in these8poses; they do not prove future spinal motion preservation", "No sourcegeometry/PBR/UV/normal/inversebind or real weights changed", "No heavyprocess, animation export or UE validation occurred", "No more binding strategies or parameter iteration in this round"],
              "Blender_UE_runs": 0, "tail_changes": 0, "production_approved": False}
    transfer.audit_tool.texture.core.save(output / "feasibility.json", report)
    spec = {"status": "numeric_failure_no_asset_application_authorized" if not report["both_regions_strict_numeric_feasible"] else "numeric_feasibility_requires_actual_validation",
            "report": transfer.audit_tool.texture.core.record(output / "feasibility.json"), "source_model": report["source_model"], "actual_asset_mutations": 0,
            "next_evidence_gates": ["Root reviews exact contact residuals and pathbound/edge failures before any scope change", "Allsource/rest/inversebind3micrometres plus exact23split/PBR/UV/normal checks on any future derivative", "Actual8pose skin/cloth seams/strain and metal rigidity, then complete real animation bake", "UEfreshimport validates newbone channels and full clips before runtime or rider claims"],
            "automatic_heavy_command": None, "weight_application_approved": False}
    transfer.audit_tool.texture.core.save(output / "next_stage_spec.json", spec)
    print(json.dumps({"report": transfer.audit_tool.texture.core.record(output / "feasibility.json"), "elapsed_seconds": report["elapsed_seconds"],
                      "all_feasible": report["both_regions_strict_numeric_feasible"], "regions": [{"patch": row["patch"], "contact_max_residual_mm": max(pose["contact_max_residual_m"] for pose in row["pose_fits"]) * 1000,
                      "bounds_contradictions": row["path_bound_contradiction_count"], "max_influences": row["maximum_influences"], "strict_feasible": row["strict_numeric_feasible"]} for row in reports]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output.resolve())


if __name__ == "__main__":
    main()
