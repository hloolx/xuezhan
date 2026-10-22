"""Prove only explicit cloth-edge length contradictions, without changing weights."""
from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optimize_mammoth_buckle_weights as optimizer


def shortest_upper_bound_paths(count, edge_pairs, upper_bounds, start):
    adjacency = [[] for _ in range(count)]
    for (first, second), maximum in zip(edge_pairs, upper_bounds):
        adjacency[first].append((second, float(maximum)))
        adjacency[second].append((first, float(maximum)))
    distances, previous = {start: 0.0}, {}
    queue = [(0.0, start)]
    while queue:
        distance, index = heapq.heappop(queue)
        if distance != distances[index]:
            continue
        for other, length in adjacency[index]:
            proposed = distance + length
            if proposed < distances.get(other, float("inf")):
                distances[other] = proposed
                previous[other] = index
                heapq.heappush(queue, (proposed, other))
    return distances, previous


def analyze(output):
    transfer = optimizer.transfer
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_weight_bounds_"):
        raise ValueError("Use a new owned bounds-proof directory")
    model = optimizer.accessory.MODEL
    if transfer.audit_tool.texture.core.record(model)["sha256"] != optimizer.accessory.MODEL_SHA:
        raise ValueError("Frozen parent-only source changed")
    document, binary = transfer.read_container(model)
    arrays = transfer.source_arrays(document, binary)
    native_map, _, _ = transfer.audit_tool.texture.native_identity(arrays)
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    matrices = np.array([optimizer.accessory.pose_matrices(document, command) @ inverse for command in transfer.POSES])
    masks = json.loads(optimizer.MASK_PLAN.read_text(encoding="utf-8-sig"))
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    output.mkdir(parents=True, exist_ok=False)
    reports = []
    for region in masks["regions"]:
        data = optimizer.build_region(region, arrays, document, native_map, matrices)
        pairs = list(zip(data["first"].tolist(), data["second"].tolist()))
        anchors = [region["actual_pose"]["bone"], "tripo::Spine_1", "tripo::Spine_2", "tripo::Spine_3"]
        homogeneous = np.column_stack((data["positions"], np.ones(len(data["positions"]))))
        seeds = [data["lookup"][index] for index in sorted(data["seeds"])]
        boundaries = [index for index, value in data["fixed"].items() if value == 0]
        findings = []
        for name in anchors:
            joint = joint_names.index(name)
            anchored = np.einsum("pij,nj->pni", matrices[:, joint], homogeneous)[:, :, :3]
            contradictions = []
            for pose_index, command in enumerate(transfer.POSES):
                maximum_lengths = data["lengths"] * (1 + abs(data["baseline"][pose_index]) + optimizer.STRAIN_NUMERIC_TOLERANCE)
                for seed in seeds:
                    distances, previous = shortest_upper_bound_paths(len(data["native_ids"]), pairs, maximum_lengths, seed)
                    for boundary in boundaries:
                        if boundary not in distances:
                            continue
                        euclidean = float(np.linalg.norm(anchored[pose_index, seed] - data["current"][pose_index, boundary]))
                        excess = euclidean - distances[boundary]
                        if excess > transfer.TOLERANCE_M:
                            path = [boundary]
                            while path[-1] != seed:
                                path.append(previous[path[-1]])
                            path.reverse()
                            contradictions.append({"pose": command["name"], "contact_native_vertex": data["native_ids"][seed],
                                                   "fixed_boundary_native_vertex": data["native_ids"][boundary],
                                                   "path_native_vertices": [data["native_ids"][index] for index in path],
                                                   "required_endpoint_distance_m": euclidean, "sum_allowed_edge_upper_bounds_m": distances[boundary],
                                                   "positive_triangle_inequality_violation_m": excess,
                                                   "contact_world_position_gltf_m": anchored[pose_index, seed].tolist(),
                                                   "boundary_world_position_gltf_m": data["current"][pose_index, boundary].tolist()})
            contradictions.sort(key=lambda row: -row["positive_triangle_inequality_violation_m"])
            findings.append({"anchor": name, "contradiction_count": len(contradictions), "has_rigorous_fixed_boundary_contradiction": bool(contradictions),
                             "maximum_violation_m": contradictions[0]["positive_triangle_inequality_violation_m"] if contradictions else 0,
                             "top_contradictions": contradictions[:12],
                             "interpretation": "A positive excess proves these fixed endpoint positions cannot be connected by this real edge path without at least one edge exceeding its original strain cap. A missing contradiction does not prove feasibility."})
        reports.append({"patch": region["native_patch"], "contact_seed_count": len(seeds), "fixed_outer_boundary_count": len(boundaries), "anchors": findings})
    report = {"status": "pure_data_cloth_path_bounds_complete_no_model_or_weights_modified", "model": transfer.audit_tool.texture.core.record(model),
              "mask_plan": transfer.audit_tool.texture.core.record(optimizer.MASK_PLAN), "script": transfer.audit_tool.texture.core.record(Path(__file__)),
              "proof": "Triangle inequality: distance of two fixed endpoint positions must be at most the sum of permitted lengths along every connecting mesh-edge path. This test uses original rest lengths times1+original absolute edge strain+1e-5numeric tolerance and requires excess>3micrometres.",
              "regions": reports, "Blender_runs": 0, "tail_changes": 0, "model_writes": 0, "weight_changes": 0, "production_approved": False}
    transfer.audit_tool.texture.core.save(output / "constraint_bounds.json", report)
    print(json.dumps({"file": transfer.audit_tool.texture.core.record(output / "constraint_bounds.json"), "regions": [{"patch": row["patch"], "anchors": [{"anchor": anchor["anchor"], "contradictions": anchor["contradiction_count"], "maximum_violation_mm": anchor["maximum_violation_m"] * 1000} for anchor in row["anchors"]]} for row in reports]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output.resolve())


if __name__ == "__main__":
    main()
