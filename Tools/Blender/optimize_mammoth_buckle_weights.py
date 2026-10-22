"""Bounded single-thread numeric buckle-anchor trials; never modify a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_mammoth_accessory_weights as accessory
import prepare_mammoth_rig_transfer as transfer


MASK_PLAN = transfer.BRANCH / "rig_weight_masks_plan_02/region_plan.json"
MASK_REVIEW = transfer.BRANCH / "rig_weight_masks_plan_02/actual_masks_01/mask_review.json"
MASK_REVIEW_SHA = "ac6fe341934bb57dda4e973c1f4cd12c91472418dd3d5903a05b5d0519a48b54"
STRAIN_NUMERIC_TOLERANCE = 1e-5
MAX_ITERATIONS = 160


def edge_state(alpha, current_edges, first_delta, second_delta, first_indices, second_indices, lengths):
    edges = current_edges + alpha[second_indices][None, :, None] * second_delta - alpha[first_indices][None, :, None] * first_delta
    size = np.linalg.norm(edges, axis=2)
    return edges, size, size / lengths[None, :] - 1


def objective_gradient(alpha, data):
    edges, size, strain = edge_state(alpha, **data["edge_arguments"])
    violation = np.maximum(abs(strain) - abs(data["baseline_strain"]) - STRAIN_NUMERIC_TOLERANCE, 0)
    worst = np.unravel_index(int(np.argmax(violation)), violation.shape)
    objective = float(np.mean(violation ** 2) + .25 * violation[worst] ** 2)
    coefficient = 2 * violation / violation.size
    coefficient[worst] += .5 * violation[worst]
    coefficient *= np.sign(strain)
    direction = edges / np.maximum(size[:, :, None], 1e-15)
    args = data["edge_arguments"]
    first = -np.sum(direction * args["first_delta"], axis=2) / args["lengths"][None, :]
    second = np.sum(direction * args["second_delta"], axis=2) / args["lengths"][None, :]
    gradient = np.zeros_like(alpha)
    np.add.at(gradient, args["first_indices"], np.sum(coefficient * first, axis=0))
    np.add.at(gradient, args["second_indices"], np.sum(coefficient * second, axis=0))
    return objective, gradient, strain


def optimize(initial, data, fixed, iterations=MAX_ITERATIONS):
    alpha = initial.copy()
    for index, value in fixed.items():
        alpha[index] = value
    objective, gradient, strain = objective_gradient(alpha, data)
    completed = 0
    for iteration in range(iterations):
        for index in fixed:
            gradient[index] = 0
        maximum = float(np.max(abs(gradient)))
        if maximum < 1e-14 or objective < 1e-16:
            break
        step = .15 / maximum
        accepted = False
        for _ in range(14):
            trial = np.clip(alpha - step * gradient, 0, 1)
            for index, value in fixed.items():
                trial[index] = value
            value, new_gradient, new_strain = objective_gradient(trial, data)
            if value < objective - 1e-16:
                alpha, objective, gradient, strain = trial, value, new_gradient, new_strain
                accepted = True
                break
            step *= .5
        completed = iteration + 1
        if not accepted:
            break
    return alpha, objective, strain, completed


def metric_rows(strain, baseline, lengths):
    records = []
    for command, actual, reference in zip(transfer.POSES, strain, baseline):
        current, original = abs(actual), abs(reference)
        records.append({"pose": command["name"], "maximum_strain": float(max(current)), "baseline_maximum_strain": float(max(original)),
                        "p95_strain": float(np.quantile(current, .95)), "baseline_p95_strain": float(np.quantile(original, .95)),
                        "length_weighted_rms_strain": float(np.sqrt(np.average(current ** 2, weights=lengths))),
                        "baseline_length_weighted_rms_strain": float(np.sqrt(np.average(original ** 2, weights=lengths))),
                        "edges_worse_than_original_by_tolerance": int(np.count_nonzero(current > original + STRAIN_NUMERIC_TOLERANCE)),
                        "maximum_per_edge_worsening": float(np.max(current - original))})
    return records


def build_region(region, arrays, document, native_map, skin_matrices):
    native_representatives = {}
    for render, native in native_map.items():
        native_representatives.setdefault(native, render)
    triangles = arrays["indices"][region["transition_affected_triangles"]]
    native_triangles = [[native_map[int(index)] for index in triangle] for triangle in triangles]
    edge_ids = sorted({tuple(sorted((first, second))) for triangle in native_triangles for first, second in zip(triangle, triangle[1:] + triangle[:1]) if first != second})
    native_ids = sorted({index for edge in edge_ids for index in edge})
    lookup = {native: index for index, native in enumerate(native_ids)}
    source_indices = np.array([native_representatives[native] for native in native_ids])
    positions = arrays["POSITION"][source_indices].astype(float)
    current = np.array([transfer.skin_positions(positions, arrays["JOINTS_0"][source_indices], arrays["WEIGHTS_0"][source_indices], matrices) for matrices in skin_matrices])
    first = np.array([lookup[pair[0]] for pair in edge_ids])
    second = np.array([lookup[pair[1]] for pair in edge_ids])
    lengths = np.linalg.norm(positions[second] - positions[first], axis=1)
    if min(lengths) < 1e-6:
        raise ValueError("Degenerate cloth edge cannot be hidden in strain metrics")
    current_edges = current[:, second] - current[:, first]
    baseline = np.linalg.norm(current_edges, axis=2) / lengths[None, :] - 1
    distances = {int(key): value for key, value in region["transition_native_geodesic_distances_m"].items()}
    seeds = set(region["contact_native_vertices"])
    fixed = {lookup[native]: 1. if native in seeds else 0. for native in native_ids if native in seeds or native not in distances or distances.get(native, 1) >= .08}
    return {"native_ids": native_ids, "lookup": lookup, "render_representatives": source_indices, "positions": positions,
            "current": current, "edge_native_pairs": edge_ids, "first": first, "second": second, "lengths": lengths,
            "current_edges": current_edges, "baseline": baseline, "distances": distances, "fixed": fixed, "seeds": seeds}


def analyze(output):
    started = time.monotonic()
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_weight_opt_"):
        raise ValueError("Use a fresh owned numeric optimization directory")
    for path, expected in ((accessory.MODEL, accessory.MODEL_SHA), (MASK_REVIEW, MASK_REVIEW_SHA)):
        if transfer.audit_tool.texture.core.record(path)["sha256"] != expected:
            raise ValueError("Approved mask/model input changed")
    mask = json.loads(MASK_PLAN.read_text(encoding="utf-8-sig"))
    document, binary = transfer.read_container(accessory.MODEL)
    arrays = transfer.source_arrays(document, binary)
    native_map, _, _ = transfer.audit_tool.texture.native_identity(arrays)
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    skin_matrices = np.array([accessory.pose_matrices(document, command) @ inverse for command in transfer.POSES])
    source_weights = [{int(joint): float(weight) for joint, weight in zip(joints, weights) if weight > 0}
                      for joints, weights in zip(arrays["JOINTS_0"], arrays["WEIGHTS_0"])]
    joint_worlds, _ = transfer.world_matrices(document)
    results = []
    output.mkdir(parents=True, exist_ok=False)
    for region in mask["regions"]:
        data = build_region(region, arrays, document, native_map, skin_matrices)
        names = [region["actual_pose"]["bone"], "tripo::Spine_1", "tripo::Spine_2", "tripo::Spine_3"]
        rankings, movements = [], {}
        seed_indices = np.array([data["lookup"][native] for native in sorted(data["seeds"])])
        homogeneous = np.column_stack((data["positions"], np.ones(len(data["positions"]))))
        for name in names:
            joint = joint_names.index(name)
            anchored = np.einsum("pij,nj->pni", skin_matrices[:, joint], homogeneous)[:, :, :3]
            delta = anchored - data["current"]
            error = np.linalg.norm(delta[:, seed_indices], axis=2)
            rest_head = joint_worlds[document["skins"][0]["joints"][joint]][:3, 3]
            rankings.append({"anchor": name, "all8pose_contact_rms_m": float(np.sqrt(np.mean(error ** 2))), "maximum_contact_error_m": float(error.max()),
                             "rest_head_to_contact_centroid_m": float(np.linalg.norm(rest_head - data["positions"][seed_indices].mean(axis=0)))})
            movements[name] = delta
        rankings.sort(key=lambda row: (round(row["all8pose_contact_rms_m"], 6), row["rest_head_to_contact_centroid_m"]))
        selected = []
        for row in rankings:
            if not any(float(np.max(np.linalg.norm(movements[row["anchor"]] - movements[name], axis=2))) < transfer.TOLERANCE_M for name in selected):
                selected.append(row["anchor"])
        selected = selected[:2]
        trials = []
        for name in selected:
            anchor = joint_names.index(name)
            delta = movements[name]
            arguments = {"current_edges": data["current_edges"], "first_delta": delta[:, data["first"]], "second_delta": delta[:, data["second"]],
                         "first_indices": data["first"], "second_indices": data["second"], "lengths": data["lengths"]}
            problem = {"edge_arguments": arguments, "baseline_strain": data["baseline"]}
            for profile in ("linear", "smoothstep", "slowfall"):
                fractions = np.array([min(1., data["distances"].get(native, .08) / .08) for native in data["native_ids"]])
                initial = 1 - fractions if profile == "linear" else 1 - fractions * fractions * (3 - 2 * fractions) if profile == "smoothstep" else np.sqrt(1 - fractions)
                alpha, loss, strain, iterations = optimize(initial, problem, data["fixed"])
                proposed = {}
                changed_native = {native: float(alpha[index]) for native, index in data["lookup"].items() if native in data["distances"]}
                for index in region["metal_render_vertices"]:
                    proposed[str(index)] = {joint_names[anchor]: 1.0}
                for index in region["transition_render_alpha"]:
                    render = int(index)
                    blend = changed_native[native_map[render]]
                    row = {joint: weight * (1 - blend) for joint, weight in source_weights[render].items()}
                    row[anchor] = row.get(anchor, 0) + blend
                    proposed[index] = {joint_names[joint]: weight for joint, weight in row.items() if weight > 0}
                metrics = metric_rows(strain, data["baseline"], data["lengths"])
                influence_count = max(len(weights) for weights in proposed.values())
                sum_error = max(abs(sum(weights.values()) - 1) for weights in proposed.values())
                accepted = all(row["edges_worse_than_original_by_tolerance"] == 0 for row in metrics) and influence_count <= 4 and sum_error < 1e-5
                entry = {"anchor": name, "initial_profile": profile, "iterations": iterations, "objective": loss, "passed_all_strict_numeric_gates": accepted,
                         "cloth_native_alpha": changed_native, "proposed_render_weights_not_applied": proposed, "pose_metrics": metrics,
                         "maximum_influences": influence_count, "weight_sum_max_error": sum_error, "fixed_contacts_alpha1": True, "outside_alpha0": True,
                         "source_topology_UV_normals_PBR_rest_untouched": True, "metal_single_rigid_anchor": True}
                trials.append(entry)
        trials.sort(key=lambda row: (not row["passed_all_strict_numeric_gates"], row["objective"]))
        best = trials[0]
        worst_pose = max(best["pose_metrics"], key=lambda row: row["maximum_per_edge_worsening"])["pose"]
        command_index = next(index for index, command in enumerate(transfer.POSES) if command["name"] == worst_pose)
        best_alpha = np.array([best["cloth_native_alpha"].get(native, 0) for native in data["native_ids"]])
        for index, value in data["fixed"].items():
            best_alpha[index] = value
        delta = movements[best["anchor"]]
        _, _, best_strain = edge_state(best_alpha, data["current_edges"], delta[:, data["first"]], delta[:, data["second"]], data["first"], data["second"], data["lengths"])
        worsening = abs(best_strain[command_index]) - abs(data["baseline"][command_index])
        worst_edges = np.argsort(worsening)[-8:][::-1]
        result = {"patch": region["native_patch"], "anchor_ranking": rankings, "motion_distinct_anchors_tried": selected,
                  "candidate_count": len(trials), "cloth_native_count": len(data["distances"]), "free_variables": len(data["native_ids"]) - len(data["fixed"]),
                  "cloth_edge_count": len(data["lengths"]), "best_trial_index": 0, "passed": best["passed_all_strict_numeric_gates"],
                  "worst_edges": [{"native_vertices": data["edge_native_pairs"][int(edge)], "pose": worst_pose, "baseline_abs_strain": float(abs(data["baseline"][command_index, edge])),
                                   "candidate_abs_strain": float(abs(best_strain[command_index, edge])), "worsening": float(worsening[edge])} for edge in worst_edges], "trials": trials}
        results.append(result)
        transfer.audit_tool.texture.core.save(output / ("patch_" + str(region["native_patch"]) + ".json"), result)
    summary = {"asset_id": "Mount_Mammoth", "status": "bounded_numeric_trials_complete_no_model_modified", "elapsed_seconds": time.monotonic() - started,
               "numeric_scope": "PureGLTFlinearblend8pose calculations, not actual Blender deformation or visual approval.", "model": transfer.audit_tool.texture.core.record(accessory.MODEL),
               "iteration_limit_per_trial": MAX_ITERATIONS, "strain_numeric_tolerance": STRAIN_NUMERIC_TOLERANCE,
               "gate": "Every affected cloth edge in every8pose may not worsen its absolute strain beyond1e-5 dimensionless numerical allowance; no max-only substitution.",
               "regions": [{"patch": result["patch"], "passed": result["passed"], "anchor_ranking": result["anchor_ranking"], "distinct_anchors_tried": result["motion_distinct_anchors_tried"],
                            "trial_count": result["candidate_count"], "free_variables": result["free_variables"], "cloth_edges": result["cloth_edge_count"],
                            "best_anchor": result["trials"][0]["anchor"], "best_profile": result["trials"][0]["initial_profile"], "best_objective": result["trials"][0]["objective"],
                            "best_pose_metrics": result["trials"][0]["pose_metrics"], "worst_edges": result["worst_edges"],
                            "full_trial_file": transfer.audit_tool.texture.core.record(output / ("patch_" + str(result["patch"]) + ".json"))} for result in results],
               "all_regions_passed": all(result["passed"] for result in results), "weight_or_model_writes": 0, "tail_changes": 0, "Blender_runs": 0, "production_approved": False}
    transfer.audit_tool.texture.core.save(output / "summary.json", summary)
    spec = {"status": "numeric_candidates_only_requires_root_review_no_heavy_command_authorized", "source_model": summary["model"],
            "summary": transfer.audit_tool.texture.core.record(output / "summary.json"), "source_mask_plan": transfer.audit_tool.texture.core.record(MASK_PLAN),
            "actual_mask_review": transfer.audit_tool.texture.core.record(MASK_REVIEW), "script": transfer.audit_tool.texture.core.record(Path(__file__)),
            "all_strict_numeric_gates_passed": summary["all_regions_passed"], "allowed_scope": "Retain failure data and review precise topology/constraint bottlenecks; no automatic Blender run or application.",
            "next_actual_candidate_requires": ["Root selects a numerically passing local candidate or explicitly authorizes diagnostic review of a failure", "Append onlyskinweightaccessors while preserving originalsurface/PBR/IB and verify coincidentcontacts", "Fresh Blender lease for actual8pose/rest3micrometre and4influences checks"], "tail_included": False}
    transfer.audit_tool.texture.core.save(output / "candidate_spec.json", spec)
    print(json.dumps({"status": summary["status"], "elapsed_seconds": summary["elapsed_seconds"], "all_passed": summary["all_regions_passed"],
                      "best": [{"patch": row["patch"], "anchor": row["best_anchor"], "loss": row["best_objective"], "passed": row["passed"]} for row in summary["regions"]]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output.resolve())


if __name__ == "__main__":
    main()
