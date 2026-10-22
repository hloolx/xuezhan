"""Bounded pure-data true-pad pinch search; never opens Blender or edits assets."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_stone_slinger_sling_grip as old
import stone_slinger_foot_math as geometry


def normalized_rows(values):
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-30)


def pad_faces(finger, positions, triangles, weights, bones, palm):
    bone = next(row for row in bones if row["name"] == finger + "_03_r")
    head = np.array(bone["head_world_review_m"])
    direction = np.array(bone["tail_world_review_m"]) - head
    fraction = (positions - head) @ direction / np.dot(direction, direction)
    qualified = np.array([row.get(finger + "_03_r", 0) > .4 for row in weights]) & (fraction > .35)
    faces = positions[triangles]
    normals = normalized_rows(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]))
    selected = np.flatnonzero(np.all(qualified[triangles], axis=1) & (normals @ palm > .2))
    if not len(selected):
        raise ValueError("Missing actual distal03 palm-facing local triangle pad: " + finger)
    return selected


def face_samples(positions, triangles):
    faces = positions[triangles]
    centers = faces.mean(axis=1)
    normals = normalized_rows(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]))
    return centers, normals


def pair_crossings(points, triangles, first_ids, second_ids, native_ids):
    first = points[triangles[first_ids]]
    second = points[triangles[second_ids]]
    overlap = np.all((first.min(axis=1)[:, None] <= second.max(axis=1)[None] + 1e-9)
                     & (first.max(axis=1)[:, None] + 1e-9 >= second.min(axis=1)[None]), axis=2)
    result = []
    for first_local, second_local in np.argwhere(overlap):
        first_index, second_index = int(first_ids[first_local]), int(second_ids[second_local])
        if first_index == second_index or len(set(native_ids[triangles[first_index]]) & set(native_ids[triangles[second_index]])) >= 2:
            continue
        kind = geometry.triangle_contact_kind(first[first_local], second[second_local])
        if kind in {"proper_crossing", "coplanar_area_overlap"}:
            result.append([first_index, second_index, kind])
    return result


def tube_mesh(path, radius=.008):
    path = np.array(path)
    points = []
    for index, point in enumerate(path):
        tangent = old.normalize(path[min(index + 1, len(path) - 1)] - path[max(index - 1, 0)])
        reference = np.array([0, 1, 0]) if abs(tangent[1]) < .9 else np.array([0, 0, 1])
        first = old.normalize(np.cross(tangent, reference))
        second = np.cross(tangent, first)
        for side in range(8):
            angle = np.pi * side / 4
            points.append(point + radius * (np.cos(angle) * first + np.sin(angle) * second))
    triangles = [[0, side + 1, side] for side in range(1, 7)]
    for ring in range(10):
        for side in range(8):
            first, second = ring * 8 + side, ring * 8 + (side + 1) % 8
            triangles += [[first, second, second + 8], [first, second + 8, first + 8]]
    triangles += [[80, 80 + side, 80 + side + 1] for side in range(1, 7)]
    return np.array(points), np.array(triangles)


def nearest_surface(points, triangle_points):
    first = triangle_points[:, 0]
    edge_first = triangle_points[:, 1] - first
    edge_second = triangle_points[:, 2] - first
    normal = normalized_rows(np.cross(edge_first, edge_second))
    relative = points[:, None] - first[None]
    distance_plane = np.einsum("pti,ti->pt", relative, normal)
    projected = points[:, None] - distance_plane[:, :, None] * normal[None]
    relative_projected = projected - first
    first_squared = np.einsum("ti,ti->t", edge_first, edge_first)
    second_squared = np.einsum("ti,ti->t", edge_second, edge_second)
    mixed = np.einsum("ti,ti->t", edge_first, edge_second)
    first_dot = np.einsum("pti,ti->pt", relative_projected, edge_first)
    second_dot = np.einsum("pti,ti->pt", relative_projected, edge_second)
    denominator = first_squared * second_squared - mixed ** 2
    first_bary = (second_squared * first_dot - mixed * second_dot) / denominator
    second_bary = (first_squared * second_dot - mixed * first_dot) / denominator
    inside = (first_bary >= 0) & (second_bary >= 0) & (first_bary + second_bary <= 1)
    distances = np.where(inside, distance_plane ** 2, np.inf)
    locations = projected.copy()
    for edge_index in range(3):
        start = triangle_points[:, edge_index]
        delta = triangle_points[:, (edge_index + 1) % 3] - start
        fraction = np.clip(np.einsum("pti,ti->pt", points[:, None] - start, delta) / np.einsum("ti,ti->t", delta, delta), 0, 1)
        closest = start + fraction[:, :, None] * delta
        squared = np.sum((closest - points[:, None]) ** 2, axis=2)
        changed = squared < distances
        locations[changed] = closest[changed]
        distances[changed] = squared[changed]
    selected = np.argmin(distances, axis=1)
    return np.sqrt(distances[np.arange(len(points)), selected]), locations[np.arange(len(points)), selected]


def parity_inside(points, triangle_points):
    votes = []
    first = triangle_points[:, 0]
    first_edge = triangle_points[:, 1] - first
    second_edge = triangle_points[:, 2] - first
    for direction in ((1, .317, .213), (.193, 1, .273), (.217, .137, 1)):
        direction = old.normalize(direction)
        cross = np.cross(direction, second_edge)
        determinant = np.einsum("ti,ti->t", first_edge, cross)
        valid = np.abs(determinant) > 1e-13
        inverse = np.divide(1, determinant, out=np.zeros_like(determinant), where=valid)
        relative = points[:, None] - first
        first_bary = np.einsum("pti,ti->pt", relative, cross) * inverse
        other_cross = np.cross(relative, first_edge)
        second_bary = np.einsum("pti,i->pt", other_cross, direction) * inverse
        along = np.einsum("pti,ti->pt", other_cross, second_edge) * inverse
        intersections = valid & (first_bary >= 0) & (second_bary >= 0) & (first_bary + second_bary <= 1) & (along > 1e-8)
        votes.append(np.count_nonzero(intersections, axis=1) % 2 == 1)
    return np.count_nonzero(votes, axis=0) >= 2


def release_path(center, axis, basis, root, length=.040):
    center = (center - root) @ basis
    axis = axis @ basis
    start, departure = center + axis * length * .5, center - axis * length * .5
    endpoint = np.array([.10, 0, -.52])
    control = departure + np.array([.07, 0, -.11])
    points = [start, departure]
    for index in range(1, 10):
        amount = index / 9
        points.append((1 - amount) ** 2 * departure + 2 * amount * (1 - amount) * control + amount ** 2 * endpoint)
    return np.array(points)


def analyze(output):
    if output.exists():
        raise FileExistsError("New analysis output required")
    prep_path = old.BRANCH / "preparation_05/grip_preparation.json"
    prep = json.loads(prep_path.read_text(encoding="utf-8"))
    for key in ("source", "weapon", "root_review"):
        if old.rig.record(Path(prep[key]["path"])) != prep[key]:
            raise ValueError("Frozen input drift: " + key)
    prior = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(prior["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = prior["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = old.texture.read_glb(old.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    native_ids = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(positions))])
    across, longitudinal, palm, _ = old.hand_frame(bones)
    pads = {finger: pad_faces(finger, positions, triangles, weights, bones, palm) for finger in ("index", "thumb")}
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    local_lookup = {int(vertex): index for index, vertex in enumerate(hand_ids)}
    local_triangles = {}
    digit_faces = {}
    for finger in pads:
        local_triangles[finger] = np.array([[local_lookup[int(vertex)] for vertex in triangle] for triangle in triangles[pads[finger]]])
        weighted = np.array([sum(value for name, value in row.items() if name.startswith(finger + "_") and name.endswith("_r")) > .4 for row in weights])
        digit_faces[finger] = np.flatnonzero(np.any(weighted[triangles], axis=1))
    local_positions, local_weights = positions[hand_ids], [weights[index] for index in hand_ids]
    hand_face_ids = np.flatnonzero(np.all(np.isin(triangles, hand_ids), axis=1))
    active_digit_ids = np.union1d(digit_faces["index"], digit_faces["thumb"])
    other_hand_face_ids = np.setdiff1d(hand_face_ids, active_digit_ids)
    fixed = [command for command in prep["initial_grip_commands"] if not command[0].startswith(("index_", "thumb_"))]
    base, _ = old.skin.deform(local_positions, local_weights, bones, fixed)
    candidates = {"index": [], "thumb": []}
    for first, second, third in product((15, 25, 35, 45), (0, 20, 40, 60), (0, 15)):
        commands = [["index_" + str(joint).zfill(2) + "_r", across.tolist(), angle] for joint, angle in enumerate((first, second, third), 1)]
        actual, _ = old.skin.deform(local_positions, local_weights, bones, fixed + commands)
        samples, normals = face_samples(actual, local_triangles["index"])
        candidates["index"].append({"commands": commands, "delta": actual - base, "samples": samples, "normals": normals})
    for components, first, second, third in product(((-1, 0, 0), (-1, 0, -1), (-1, -.5, -1), (0, -1, -1)), (15, 30, 45), (-30, 0, 30, 60), (0, 15)):
        axis = old.normalize(across * components[0] + longitudinal * components[1] + palm * components[2])
        commands = [["thumb_01_r", axis.tolist(), first], ["thumb_02_r", palm.tolist(), second], ["thumb_03_r", palm.tolist(), third]]
        actual, _ = old.skin.deform(local_positions, local_weights, bones, fixed + commands)
        samples, normals = face_samples(actual, local_triangles["thumb"])
        candidates["thumb"].append({"commands": commands, "delta": actual - base, "samples": samples, "normals": normals})
    proposals = []
    for index_id, index in enumerate(candidates["index"]):
        for thumb_id, thumb in enumerate(candidates["thumb"]):
            delta = thumb["samples"][None] - index["samples"][:, None]
            length = np.linalg.norm(delta, axis=2)
            direction = normalized_rows(delta)
            index_facing = np.einsum("ijt,it->ij", direction, index["normals"])
            thumb_facing = -np.einsum("ijt,jt->ij", direction, thumb["normals"])
            score = np.abs(length - .016) + .05 * np.maximum(.3 - index_facing, 0) + .05 * np.maximum(.3 - thumb_facing, 0)
            selected = np.unravel_index(np.argmin(score), score.shape)
            first_sample, second_sample = index["samples"][selected[0]], thumb["samples"][selected[1]]
            span = old.normalize(second_sample - first_sample)
            axis = old.normalize(across - span * np.dot(across, span))
            proposals.append({"index_id": index_id, "thumb_id": thumb_id, "score": float(score[selected]), "center": (first_sample + second_sample) * .5,
                              "axis": axis, "pad_faces": {"index": int(pads["index"][selected[0]]), "thumb": int(pads["thumb"][selected[1]])},
                              "pad_separation_m": float(length[selected]), "index_normal_facing": float(index_facing[selected]), "thumb_normal_facing": float(thumb_facing[selected])})
    proposals.sort(key=lambda row: row["score"])
    basis, root = np.array(prep["weapon_basis_columns"]), np.array(prep["terminal_root_rest_m"])
    evaluated = []
    for proposal in proposals[:40]:
        index, thumb = candidates["index"][proposal["index_id"]], candidates["thumb"][proposal["thumb_id"]]
        actual = positions.copy()
        actual[hand_ids] = base + index["delta"] + thumb["delta"]
        crossings = pair_crossings(actual, triangles, digit_faces["index"], digit_faces["thumb"], native_ids)
        other_hand_crossings = pair_crossings(actual, triangles, active_digit_ids, other_hand_face_ids, native_ids)
        path = release_path(proposal["center"], proposal["axis"], basis, root)
        cord_points, cord_triangles = tube_mesh(path)
        cord_points = cord_points @ basis.T + root
        distances, _ = nearest_surface(actual[hand_ids], cord_points[cord_triangles])
        signed = np.where(parity_inside(actual[hand_ids], cord_points[cord_triangles]), -distances, distances)
        barycentric_samples = np.array([[1 / 3] * 3, [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]])
        interior = np.einsum("sk,tki->tsi", barycentric_samples, actual[triangles[hand_face_ids]]).reshape(-1, 3)
        interior_distances, _ = nearest_surface(interior, cord_points[cord_triangles])
        signed_interior = np.where(parity_inside(interior, cord_points[cord_triangles]), -interior_distances, interior_distances)
        retained_points, retained_triangles = tube_mesh(prep["terminal_path_proposal_local_m"]["cord_N1"])
        retained_points = retained_points @ basis.T + root
        retained_samples = np.vstack((actual[hand_ids], interior))
        retained_distances, _ = nearest_surface(retained_samples, retained_points[retained_triangles])
        retained_signed = np.where(parity_inside(retained_samples, retained_points[retained_triangles]), -retained_distances, retained_distances)
        release_self_crossings = pair_crossings(cord_points, cord_triangles, np.arange(len(cord_triangles)), np.arange(len(cord_triangles)), np.arange(len(cord_points)))
        contact = {}
        contact_radials = []
        for finger in pads:
            pad_points, pad_normals = face_samples(actual, triangles[pads[finger]])
            pad_distances, nearest = nearest_surface(pad_points, cord_points[cord_triangles])
            chosen = int(np.argmin(pad_distances))
            delta = nearest[chosen] - proposal["center"]
            radial = old.normalize(delta - proposal["axis"] * np.dot(delta, proposal["axis"]))
            contact_radials.append(radial)
            contact[finger] = {"triangle": int(pads[finger][chosen]), "barycentric": [1 / 3] * 3,
                               "distance_m": float(pad_distances[chosen]), "point_m": pad_points[chosen].tolist(), "normal": pad_normals[chosen].tolist(),
                               "pad_outward_normal_dot_cord_outward_radial": float(np.dot(pad_normals[chosen], radial))}
        opposing = float(np.dot(*contact_radials))
        checks = {"true03_pad_faces_both_within2mm": max(row["distance_m"] for row in contact.values()) <= .002,
                  "no_index_thumb_triangle_crossings": not crossings, "no_hand_vertex_cord_penetration_over2mm": float(signed.min()) >= -.002,
                  "opposed_radial_dot_at_most_minus0p5": opposing <= -.5,
                  "both_pad_normals_face_cord": all(value["pad_outward_normal_dot_cord_outward_radial"] <= -.3 for value in contact.values()),
                  "no_index_thumb_other_hand_triangle_crossings": not other_hand_crossings,
                  "no_release_cord_hand_face_samples_inside_over2mm": float(signed_interior.min()) >= -.002,
                  "no_retained_cord_hand_samples_inside_over2mm": float(retained_signed.min()) >= -.002,
                  "no_release_cord_self_crossings": not release_self_crossings}
        row = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in proposal.items()}
        row.update({"commands": fixed + index["commands"] + thumb["commands"], "checks": checks, "index_thumb_crossings": crossings,
                    "true_pad_contacts": contact, "opposed_radial_dot": opposing, "maximum_cord_penetration_m": max(0, -float(signed.min())),
                    "hand_vertices_inside_over2mm": hand_ids[signed < -.002].tolist(), "release_path_local_m": path.tolist(),
                    "index_thumb_other_hand_crossings": other_hand_crossings, "release_cord_self_crossings": release_self_crossings,
                    "hand_face_interior_samples": len(interior), "release_cord_interior_sample_maximum_penetration_m": max(0, -float(signed_interior.min())),
                    "retained_cord_all_sample_maximum_penetration_m": max(0, -float(retained_signed.min()))})
        evaluated.append(row)
    evaluated.sort(key=lambda row: (sum(not value for value in row["checks"].values()), len(row["index_thumb_crossings"]), max(value["distance_m"] for value in row["true_pad_contacts"].values()), row["maximum_cord_penetration_m"]))
    result = {"asset_id": "Unit_StoneSlinger", "status": "pure_joint_pad_candidates_pending_actual_mesh_validation", "script": old.rig.record(Path(__file__)),
              "source": prep["source"], "prior_preparation": old.rig.record(prep_path), "prior_actual_failure": old.rig.record(old.BRANCH / "candidate_01/sling_pilot_report.json"),
              "selection": {"rule": "All three triangle corners have actual03weight>0.4 and distal03fraction>0.35, plus rest outward normal dot anatomical palm>0.2. Triangle-interior barycentric samples, no02proxy.", "pad_triangle_ids": {key: value.tolist() for key, value in pads.items()}},
              "finite_budget": {"index_poses": len(candidates["index"]), "thumb_poses": len(candidates["thumb"]), "pairs": len(proposals), "full_mesh_pairs_audited": len(evaluated)},
              "comparison": evaluated, "pure_candidate_checks_all_pass_count": sum(all(row["checks"].values()) for row in evaluated),
              "scope": "Pure LBS with original weights. Closed88vertex/172triangle derivative cord. Fixed quad triangulation is provisional: Blender actual evaluated tessellation/parity/face contacts must be repeated. No actual mesh or pose acceptance.",
              "body_or_weight_modified": False, "blender_started": False, "grip_approved": False, "gait_expanded": False}
    output.mkdir(parents=True, exist_ok=False)
    old.rig.save(output / "joint_pinch_candidates.json", result)
    print(json.dumps({"status": result["status"], "count": result["pure_candidate_checks_all_pass_count"], "best": evaluated[0]["checks"], "path": str(output / "joint_pinch_candidates.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.output).resolve())
