"""One authorized12cm cloth-only comparison, two starts per best real anchor."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimize_mammoth_buckle_weights as optimizer
import analyze_mammoth_buckle_constraints as bounds_tool


RADIUS_M = .12


def analyze(output):
    transfer = optimizer.transfer
    started = time.monotonic()
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_weight_support12_"):
        raise ValueError("Use a fresh owned12cmcomparison directory")
    model = optimizer.accessory.MODEL
    if transfer.audit_tool.texture.core.record(model)["sha256"] != optimizer.accessory.MODEL_SHA:
        raise ValueError("Frozen parent-only model changed")
    document, binary = transfer.read_container(model)
    arrays = transfer.source_arrays(document, binary)
    native_map, _, native_analysis = transfer.audit_tool.texture.native_identity(arrays)
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    matrices = np.array([optimizer.accessory.pose_matrices(document, command) @ inverse for command in transfer.POSES])
    mask = json.loads(optimizer.MASK_PLAN.read_text(encoding="utf-8-sig"))
    prior_path = transfer.BRANCH / "rig_weight_opt_01/summary.json"
    previous = json.loads(prior_path.read_text(encoding="utf-8-sig"))
    excluded = {face for patch in native_analysis["plan"]["accessory_patches"] for face in patch["face_indices"]}
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    reports = []
    output.mkdir(parents=True, exist_ok=False)
    for original in mask["regions"]:
        expanded = deepcopy(original)
        expanded["transition_native_geodesic_distances_m"] = dict(original["outer12cm_native_geodesic_distances_m"])
        inside = {int(index) for index in expanded["transition_native_geodesic_distances_m"]}
        metal = set(original["metal_render_vertices"])
        render_indices = [index for index, native in native_map.items() if native in inside and index not in metal]
        expanded["transition_affected_triangles"] = [face for face, triangle in enumerate(arrays["indices"])
            if native_analysis["source_triangle_native_polygons"][face] not in excluded and any(int(index) in set(render_indices) for index in triangle)]
        expanded["transition_render_alpha"] = {str(index): 0 for index in render_indices}
        data = optimizer.build_region(expanded, arrays, document, native_map, matrices)
        data["fixed"] = {data["lookup"][native]: 1. if native in data["seeds"] else 0. for native in data["native_ids"]
                         if native in data["seeds"] or native not in data["distances"] or data["distances"].get(native, RADIUS_M) >= RADIUS_M}
        anchor_name = next(region["best_anchor"] for region in previous["regions"] if region["patch"] == original["native_patch"])
        anchor = joint_names.index(anchor_name)
        homogeneous = np.column_stack((data["positions"], np.ones(len(data["positions"]))))
        anchored = np.einsum("pij,nj->pni", matrices[:, anchor], homogeneous)[:, :, :3]
        delta = anchored - data["current"]
        problem = {"edge_arguments": {"current_edges": data["current_edges"], "first_delta": delta[:, data["first"]], "second_delta": delta[:, data["second"]],
                                       "first_indices": data["first"], "second_indices": data["second"], "lengths": data["lengths"]}, "baseline_strain": data["baseline"]}
        trials = []
        for profile in ("slowfall", "smoothstep"):
            fractions = np.array([min(1., data["distances"].get(native, RADIUS_M) / RADIUS_M) for native in data["native_ids"]])
            initial = np.sqrt(1 - fractions) if profile == "slowfall" else 1 - fractions * fractions * (3 - 2 * fractions)
            alpha, objective, strain, iterations = optimizer.optimize(initial, problem, data["fixed"])
            metrics = optimizer.metric_rows(strain, data["baseline"], data["lengths"])
            trials.append({"initial_profile": profile, "iterations": iterations, "objective": objective, "pose_metrics": metrics,
                           "native_alpha_not_applied": {native: float(alpha[index]) for native, index in data["lookup"].items() if native in inside},
                           "passed_individual_edge_caps": all(row["edges_worse_than_original_by_tolerance"] == 0 for row in metrics),
                           "passed_max_p95_rms": all(row["maximum_strain"] <= row["baseline_maximum_strain"] + optimizer.STRAIN_NUMERIC_TOLERANCE and
                                row["p95_strain"] <= row["baseline_p95_strain"] + optimizer.STRAIN_NUMERIC_TOLERANCE and
                                row["length_weighted_rms_strain"] <= row["baseline_length_weighted_rms_strain"] + optimizer.STRAIN_NUMERIC_TOLERANCE for row in metrics)})
        contradictions = []
        pairs = list(zip(data["first"].tolist(), data["second"].tolist()))
        for pose_index, command in enumerate(transfer.POSES):
            upper = data["lengths"] * (1 + abs(data["baseline"][pose_index]) + optimizer.STRAIN_NUMERIC_TOLERANCE)
            for seed_native in data["seeds"]:
                seed = data["lookup"][seed_native]
                distances, path_previous = bounds_tool.shortest_upper_bound_paths(len(data["native_ids"]), pairs, upper, seed)
                for boundary, value in data["fixed"].items():
                    if value != 0 or boundary not in distances:
                        continue
                    euclidean = float(np.linalg.norm(anchored[pose_index, seed] - data["current"][pose_index, boundary]))
                    if euclidean > distances[boundary] + transfer.TOLERANCE_M:
                        path = [boundary]
                        while path[-1] != seed:
                            path.append(path_previous[path[-1]])
                        contradictions.append({"pose": command["name"], "path_native_vertices": [data["native_ids"][index] for index in reversed(path)],
                                               "required_distance_m": euclidean, "allowed_path_total_m": distances[boundary], "violation_m": euclidean - distances[boundary]})
        contradictions.sort(key=lambda row: -row["violation_m"])
        added_native = sorted(inside - {int(index) for index in original["transition_native_geodesic_distances_m"]})
        added_render = sorted(set(render_indices) - {int(index) for index in original["transition_render_alpha"]})
        trials.sort(key=lambda trial: trial["objective"])
        reports.append({"patch": original["native_patch"], "anchor": anchor_name, "old_radius_m": .08, "comparison_radius_m": RADIUS_M,
                        "native_vertices_before": len(original["transition_native_geodesic_distances_m"]), "native_vertices_after": len(inside),
                        "added_native_vertices": added_native, "added_render_vertices": added_render,
                        "added_positions_blender_m": {index: (arrays["POSITION"][index] @ transfer.BASIS.T).tolist() for index in added_render},
                        "support_equals_previously_reviewed_blue_ring": True, "outside_reviewed_native_set_added": 0,
                        "cloth_edges": len(data["lengths"]), "free_variables": len(data["native_ids"]) - len(data["fixed"]), "trials": trials,
                        "rigorous_path_bound_contradiction_count": len(contradictions), "top_path_contradictions": contradictions[:8],
                        "passed": any(trial["passed_individual_edge_caps"] and trial["passed_max_p95_rms"] for trial in trials)})
    report = {"status": "single_authorized12cm_comparison_complete_stop_same_strategy_if_failed", "model": transfer.audit_tool.texture.core.record(model),
              "prior8cm_summary": transfer.audit_tool.texture.core.record(prior_path), "mask_plan": transfer.audit_tool.texture.core.record(optimizer.MASK_PLAN),
              "script": transfer.audit_tool.texture.core.record(Path(__file__)), "elapsed_seconds": time.monotonic() - started,
              "candidate_count": 4, "iterations_cap_each": optimizer.MAX_ITERATIONS, "regions": reports,
              "all_passed": all(row["passed"] for row in reports), "tail_changes": 0, "model_or_weight_writes": 0, "Blender_runs": 0, "production_approved": False}
    transfer.audit_tool.texture.core.save(output / "comparison.json", report)
    spec = {"status": "failed_numeric_strategy_stopped_no_heavy_command" if not report["all_passed"] else "numeric_pass_requires_actual_review",
            "comparison": transfer.audit_tool.texture.core.record(output / "comparison.json"), "source_model": report["model"],
            "allowed_support": "Exactly the already-reviewed blue8to12cmcloth ring, additional native/render indices enumerated in comparison; no gray fur or full saddle expansion.",
            "all_numeric_gates_passed": report["all_passed"], "model_candidate_created": False, "weight_changes": 0, "tail_included": False}
    transfer.audit_tool.texture.core.save(output / "candidate_spec.json", spec)
    print(json.dumps({"comparison": transfer.audit_tool.texture.core.record(output / "comparison.json"), "elapsed_seconds": report["elapsed_seconds"],
                      "all_passed": report["all_passed"], "regions": [{"patch": row["patch"], "added_native": len(row["added_native_vertices"]),
                      "added_render": len(row["added_render_vertices"]), "bound_contradictions": row["rigorous_path_bound_contradiction_count"],
                      "maximum_bound_violation_mm": row["top_path_contradictions"][0]["violation_m"] * 1000 if row["top_path_contradictions"] else 0} for row in reports]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output.resolve())


if __name__ == "__main__":
    main()
