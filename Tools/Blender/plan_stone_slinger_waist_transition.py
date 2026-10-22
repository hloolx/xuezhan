"""One fixed-boundary harmonic waist candidate; no Blender or search."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_stone_slinger_waist_weights as previous


grip, geometry = previous.grip, previous.geometry


def proper_rotation(matrix):
    first, _, second = np.linalg.svd(matrix)
    rotation = first @ second
    if np.linalg.det(rotation) < 0:
        first[:, -1] *= -1
        rotation = first @ second
    return rotation


def complete_pose_matrices(bones, commands, frame, name):
    commands = list(commands)
    if name.startswith("move_"):
        sign = 1 if name == "move_A" else -1
        commands += [["thigh_l", [0, 1, 0], sign * 7], ["thigh_r", [0, 1, 0], -sign * 7],
                     ["calf_l", [0, 1, 0], 6 if sign > 0 else 0], ["calf_r", [0, 1, 0], 0 if sign > 0 else 6]]
    rest, posed = grip.skin.pose_matrices(bones, commands)
    parents = {bone["name"]: bone["parent"] for bone in bones}
    basis = {}
    for bone in bones:
        current, parent = bone["name"], bone["parent"]
        inherited = (posed[parent] @ np.linalg.inv(rest[parent]) if parent else np.eye(4)) @ rest[current]
        basis[current] = np.linalg.solve(inherited, posed[current])

    def recompute():
        evaluated = {}

        def resolve(current):
            if current not in evaluated:
                parent = parents[current]
                evaluated[current] = (resolve(parent) @ np.linalg.inv(rest[parent]) if parent else np.eye(4)) @ rest[current] @ basis[current]
            return evaluated[current]

        for current in rest:
            resolve(current)
        return evaluated

    def set_world_rotation(current, target):
        parent = parents[current]
        inherited = (posed[parent] @ np.linalg.inv(rest[parent]) if parent else np.eye(4)) @ rest[current]
        basis[current] = np.eye(4)
        basis[current][:3, :3] = proper_rotation(inherited[:3, :3]).T @ target
        return recompute()

    def aim(current, child, target):
        direction = posed[child][:3, 3] - posed[current][:3, 3]
        rotation = previous.rotation_between(direction, np.asarray(target) - posed[current][:3, 3])
        return set_world_rotation(current, rotation @ proper_rotation(posed[current][:3, :3]))

    phase = .015 if name == "move_A" else -.015 if name == "move_B" else 0.
    arm_evidence = []
    for side, target, pole in (("r", [.23 + phase, -.43, .98], [-.05, -.55, 1.02]),
                               ("l", [.10 - phase, .33, .82], [-.12, .54, .91])):
        upper, lower, hand = [prefix + "_" + side for prefix in ("upperarm", "lowerarm", "hand")]
        shoulder = posed[upper][:3, 3].copy()
        first = np.linalg.norm(posed[lower][:3, 3] - shoulder)
        second = np.linalg.norm(posed[hand][:3, 3] - posed[lower][:3, 3])
        delta = np.asarray(target) - shoulder
        distance = min(np.linalg.norm(delta), (first + second) * .995)
        axis = grip.normalize(delta)
        pole_delta = np.asarray(pole) - shoulder
        elbow_axis = grip.normalize(pole_delta - axis * np.dot(pole_delta, axis))
        along = (first ** 2 - second ** 2 + distance ** 2) / (2 * distance)
        desired_elbow = shoulder + axis * along + elbow_axis * np.sqrt(max(0., first ** 2 - along ** 2))
        posed = aim(upper, lower, desired_elbow)
        posed = aim(lower, hand, shoulder + axis * distance)
        arm_evidence.append({"side": side, "wrist_target_m": target, "actual_pure_wrist_m": posed[hand][:3, 3].tolist(),
                             "wrist_error_m": float(np.linalg.norm(posed[hand][:3, 3] - target))})
    source_frame = np.column_stack((frame["across"], frame["longitudinal"], frame["palm"]))
    target_frame = np.column_stack(((0, 1, 0), (0, 0, -1), (-1, 0, 0)))
    rotation = proper_rotation(target_frame @ np.linalg.inv(source_frame)) @ proper_rotation(rest["hand_r"][:3, :3])
    posed = set_world_rotation("hand_r", rotation)
    matrices = {current: posed[current] @ np.linalg.inv(matrix) for current, matrix in rest.items()}
    return matrices, arm_evidence


def harmonic_fraction(native_positions, adjacency, region, seeds):
    region, seeds = set(region), set(seeds)
    boundary = {identifier for identifier in region if adjacency[identifier] - region}
    if not seeds <= region or seeds & boundary or not boundary:
        raise ValueError("Invalid fixed topology boundary")
    unknown = sorted(region - boundary - seeds)
    indices = {identifier: index for index, identifier in enumerate(unknown)}
    coefficients, right = np.zeros((len(unknown), len(unknown))), np.zeros(len(unknown))
    for identifier in unknown:
        for neighbour in sorted(adjacency[identifier] & region):
            conductance = 1 / np.linalg.norm(native_positions[identifier] - native_positions[neighbour])
            coefficients[indices[identifier], indices[identifier]] += conductance
            if neighbour in indices:
                coefficients[indices[identifier], indices[neighbour]] -= conductance
            elif neighbour in seeds:
                right[indices[identifier]] += conductance
    solution = np.linalg.solve(coefficients, right) if unknown else []
    amounts = {identifier: 1. if identifier in seeds else 0. for identifier in region}
    amounts.update({identifier: float(value) for identifier, value in zip(unknown, solution)})
    if any(value < -1e-12 or value > 1 + 1e-12 for value in amounts.values()):
        raise ValueError("Harmonic maximum principle violated")
    return amounts, sorted(boundary)


def partial_transfer(weights, amount):
    removed = weights.get("upperarm_r", 0.) * amount
    if not 0 <= amount <= 1 or not set(weights) <= previous.ALLOWED_RECIPIENTS | {"upperarm_r"}:
        raise ValueError("Unexpected candidate scope")
    recipients = {name: value for name, value in weights.items() if name != "upperarm_r"}
    mass = sum(recipients.values())
    if mass <= 0:
        raise ValueError("No existing torso/leg mass")
    result = {name: value + removed * value / mass for name, value in recipients.items()}
    remaining = weights.get("upperarm_r", 0.) - removed
    if remaining > 0:
        result["upperarm_r"] = remaining
    return result


def changed_face_crossings(points, triangles, native, changed_faces):
    surface = points[triangles]
    minimum, maximum = surface.min(axis=1), surface.max(axis=1)
    result, visited = [], set()
    for first in changed_faces:
        possible = np.flatnonzero(np.all((minimum <= maximum[first] + 1e-9) & (maximum + 1e-9 >= minimum[first]), axis=1))
        for second in possible:
            pair = tuple(sorted((int(first), int(second))))
            if first == second or pair in visited:
                continue
            visited.add(pair)
            if len(set(native[triangles[first]]) & set(native[triangles[second]])) >= 2:
                continue
            kind = geometry.triangle_contact_kind(surface[first], surface[second])
            if kind in {"proper_crossing", "coplanar_area_overlap"}:
                result.append([*pair, kind])
    return sorted(result)


def strain_report(rest, before, after, triangles, face_ids, native):
    edge_rows = geometry.native_edges(triangles[face_ids], native)
    result = []
    for pair, (first, second) in edge_rows.items():
        lengths = [float(np.linalg.norm(points[first] - points[second])) for points in (rest, before, after)]
        result.append({"native_edge": pair, "rest_m": lengths[0], "before_m": lengths[1], "after_m": lengths[2],
                       "before_rest_ratio": lengths[1] / lengths[0], "after_rest_ratio": lengths[2] / lengths[0],
                       "after_before_ratio": lengths[2] / lengths[1], "length_change_mm": (lengths[2] - lengths[1]) * 1000})
    return {"all_local_edges": result, "maximum_length_change_mm": max(abs(row["length_change_mm"]) for row in result),
            "before_rest_ratio_range": [min(row["before_rest_ratio"] for row in result), max(row["before_rest_ratio"] for row in result)],
            "after_rest_ratio_range": [min(row["after_rest_ratio"] for row in result), max(row["after_rest_ratio"] for row in result)]}


def analyze(output):
    previous_path = grip.BRANCH / "waist_weight_plan_01/waist_weight_plan.json"
    prior = json.loads(previous_path.read_text(encoding="utf-8"))
    for field in ("source", "source_mesh", "mapping", "transfer_report", "accepted_foot_weights", "local_grip_review"):
        if grip.rig.record(Path(prior[field]["path"])) != prior[field]:
            raise ValueError("Immutable input changed: " + field)
    mapping = json.loads(Path(prior["mapping"]["path"]).read_text(encoding="utf-8"))
    transfer = json.loads(Path(prior["transfer_report"]["path"]).read_text(encoding="utf-8"))
    foot = json.loads(Path(prior["accepted_foot_weights"]["path"]).read_text(encoding="utf-8"))
    foot_changes_path = Path(foot["actual_weight_changes"]["path"])
    if grip.rig.record(foot_changes_path) != foot["actual_weight_changes"]:
        raise ValueError("Foot evidence changed")
    foot_changes = json.loads(foot_changes_path.read_text(encoding="utf-8"))["changes"]
    arrays = grip.texture.read_glb(grip.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    native = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(positions))])
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    for row in foot_changes:
        weights[row["source_vertex"]] = row["after_actual_float32"]
    native_positions = {int(identifier): positions[int(np.flatnonzero(native == identifier)[0])] for identifier in np.unique(native)}
    adjacency = defaultdict(set)
    for face in native[triangles]:
        for identifier in face:
            adjacency[int(identifier)].update(int(other) for other in face if other != identifier)
    region = [row["native_vertex"] for row in prior["read_only_two_ring_neighbourhood"]]
    face_ids = np.array(prior["diagnostic_face_ids"])
    if len(region) != 26 or len(face_ids) != 35 or len(np.unique(triangles[face_ids])) != 49:
        raise ValueError("Exact authorized region drift")
    fractions, boundary = harmonic_fraction(native_positions, adjacency, region, previous.TARGET_NATIVE)
    proposed = [dict(row) for row in weights]
    changes = []
    for identifier in sorted(region):
        render_ids = np.flatnonzero(native == identifier).tolist()
        original = weights[render_ids[0]]
        if any(weights[index] != original for index in render_ids):
            raise ValueError("UV identity has inconsistent weights")
        amount = fractions[identifier]
        if amount == 0 or not original.get("upperarm_r", 0):
            continue
        after = partial_transfer(original, amount)
        for vertex in render_ids:
            proposed[vertex] = after
            changes.append({"vertex": vertex, "native_vertex": identifier, "fraction_removed": amount,
                            "before": original, "after": after,
                            "delta": {name: after.get(name, 0.) - original.get(name, 0.) for name in original}})
    changed_vertices = np.array([row["vertex"] for row in changes])
    changed_faces = np.flatnonzero(np.any(np.isin(triangles, changed_vertices), axis=1))
    if not set(changed_faces) <= set(face_ids):
        raise ValueError("Changed face crosses authorized fixed boundary")
    loop_path = grip.BRANCH / "loop_anchor_plan_04/loop_anchor_plan.json"
    loop = json.loads(loop_path.read_text(encoding="utf-8"))
    prep_path = grip.BRANCH / "preparation_05/grip_preparation.json"
    prep = json.loads(prep_path.read_text(encoding="utf-8"))
    bones = transfer["actual_final_skeleton"]["armatures"][0]["bones"]
    poses = []
    for name in ("idle", "move_A", "move_B"):
        matrices, arm_evidence = complete_pose_matrices(bones, loop["commands"], prep["hand_frame"], name)
        before, before_linear = previous.local_skin(positions, weights, matrices)
        after, after_linear = previous.local_skin(positions, proposed, matrices)
        before_check = geometry.triangle_orientation(positions, before, triangles, before_linear)
        after_check = geometry.triangle_orientation(positions, after, triangles, after_linear)
        before_crossings = changed_face_crossings(before, triangles, native, changed_faces)
        after_crossings = changed_face_crossings(after, triangles, native, changed_faces)
        new_crossings = sorted(set(map(tuple, after_crossings)) - set(map(tuple, before_crossings)))
        changed_native = sorted({row["native_vertex"] for row in changes})
        seam_gap = max(float(np.max(np.linalg.norm(after[native == identifier] - after[np.flatnonzero(native == identifier)[0]], axis=1))) for identifier in changed_native)
        unchanged = np.ones(len(positions), dtype=bool)
        unchanged[changed_vertices] = False
        poses.append({"pose": name, "arm_IK": arm_evidence, "whole_model_before": before_check, "whole_model_after": after_check,
                      "new_negative_triangles": sorted(set(after_check["negative_triangles"]) - set(before_check["negative_triangles"])),
                      "changed_faces_against_entire_model_before": before_crossings, "changed_faces_against_entire_model_after": after_crossings,
                      "new_intersection_pairs": new_crossings,
                      "intersection_completeness": "Every triangle incident to any changed vertex tested against all10770 bodytriangles, including outside the authorized patch. All other vertices are exactly unchanged, so no new pair can occur entirely outside this set.",
                      "maximum_body_displacement_mm": float(np.linalg.norm(after - before, axis=1).max() * 1000),
                      "unchanged_vertices_max_error_m": float(np.linalg.norm(after[unchanged] - before[unchanged], axis=1).max()),
                      "native_UV_duplicate_seam_gap_m": seam_gap,
                      "local_edge_strain": strain_report(positions, before, after, triangles, face_ids, native)})
    result = {"asset_id": "Unit_StoneSlinger", "status": "single_fixed_boundary_harmonic_candidate_not_applied",
              "script": grip.rig.record(Path(__file__)), "previous_failed_candidate": grip.rig.record(previous_path),
              "source": prior["source"], "source_mesh": prior["source_mesh"], "mapping": prior["mapping"],
              "accepted_foot_changes": foot["actual_weight_changes"], "loop_plan": grip.rig.record(loop_path), "pose_preparation": grip.rig.record(prep_path),
              "region_native_vertices": sorted(region), "unchanged_boundary_native_vertices": boundary,
              "region_face_ids": face_ids.tolist(), "harmonic_fraction_by_native": fractions,
              "method": "Exactly one inverse-rest-edge-length weighted discrete harmonic attenuation field. Seed908/2331=1, every patch vertex touching an outside neighbour=0. No parameter sweep, support growth or geometry weld. Removed arm mass goes to already present torso/thigh influences in original proportions.",
              "exact_weight_changes": changes, "changed_native_count": len({row["native_vertex"] for row in changes}),
              "changed_render_count": len(changes), "changed_face_ids": changed_faces.tolist(), "whole_model_pose_comparisons": poses,
              "checks": {"fixed_outer_boundary": all(weights[index] == proposed[index] for index in range(len(positions)) if native[index] in boundary),
                         "all_weights_outside_region_exact": all(weights[index] == proposed[index] for index in range(len(positions)) if native[index] not in region),
                         "all_accepted_foot_weights_exact": all(proposed[row["source_vertex"]] == row["after_actual_float32"] for row in foot_changes),
                         "mass_preserved": all(abs(sum(row["before"].values()) - sum(row["after"].values())) < 1e-12 for row in changes),
                         "no_new_negative_triangles": all(not row["new_negative_triangles"] for row in poses),
                         "no_negative_triangles_remaining": all(not row["whole_model_after"]["negative_triangles"] for row in poses),
                         "no_new_full_model_intersections": all(not row["new_intersection_pairs"] for row in poses),
                         "native_UV_seams_closed": all(row["native_UV_duplicate_seam_gap_m"] <= 1e-7 for row in poses)},
              "candidate_count": 1, "actual_weights_mesh_PBR_modified": False, "Blender_started": False,
              "scope": "Pure complete-model skin under original Idle/MoveA/MoveB. Not an actual Blender candidate, gait acceptance, waist artwork approval or weapon motion test.", "approved": False}
    result["pure_checks_passed"] = all(result["checks"].values())
    if not result["pure_checks_passed"]:
        result["status"] = "fixed_boundary_candidate_rejected_before_Blender_stop_no_followup_search"
    output.mkdir(parents=True, exist_ok=False)
    previous.projection(output / "waist_transition_projection.png", positions, triangles, face_ids, native, {row["native_vertex"] for row in changes})
    result["projection"] = grip.rig.record(output / "waist_transition_projection.png")
    grip.rig.save(output / "waist_transition_plan.json", result)
    print(json.dumps({"path": str(output), "changed_native": result["changed_native_count"], "changed_render": len(changes),
                      "boundary": boundary, "checks": result["checks"], "poses": [{"name": row["pose"], "before_negative": row["whole_model_before"]["negative_triangles"],
                      "after_negative": row["whole_model_after"]["negative_triangles"], "new_crossings": row["new_intersection_pairs"],
                      "displacement_mm": row["maximum_body_displacement_mm"], "edge_ratios_before": row["local_edge_strain"]["before_rest_ratio_range"],
                      "edge_ratios_after": row["local_edge_strain"]["after_rest_ratio_range"]} for row in poses]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    analyze(Path(arguments.output).resolve())
