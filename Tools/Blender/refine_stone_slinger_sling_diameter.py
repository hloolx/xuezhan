"""Compare three authorized independent sling diameters using actual local faces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_stone_slinger_joint_pinch as joint


def signed_surface(points, cord_points, cord_triangles):
    distances, _ = joint.nearest_surface(points, cord_points[cord_triangles])
    return np.where(joint.parity_inside(points, cord_points[cord_triangles]), -distances, distances)


def transported_tube(path, radius):
    path = np.array(path)
    points = []
    previous_tangent = None
    first = None
    for index, center in enumerate(path):
        tangent = joint.old.normalize(path[min(index + 1, len(path) - 1)] - path[max(0, index - 1)])
        if previous_tangent is None:
            reference = np.array([0, 1, 0]) if abs(tangent[1]) < .9 else np.array([0, 0, 1])
            first = joint.old.normalize(np.cross(tangent, reference))
        else:
            rotation_axis = np.cross(previous_tangent, tangent)
            sine = np.linalg.norm(rotation_axis)
            cosine = float(np.dot(previous_tangent, tangent))
            if sine > 1e-12:
                rotation_axis /= sine
                first = first * cosine + np.cross(rotation_axis, first) * sine + rotation_axis * np.dot(rotation_axis, first) * (1 - cosine)
            elif cosine < 0:
                raise ValueError("Tube path reverses180degrees")
            first = joint.old.normalize(first - tangent * np.dot(first, tangent))
        second = np.cross(tangent, first)
        points.extend(center + radius * (np.cos(side * np.pi / 4) * first + np.sin(side * np.pi / 4) * second) for side in range(8))
        previous_tangent = tangent
    return np.array(points), joint.tube_mesh(path, radius)[1]


def straight_neck_path(start, departure, endpoint):
    axis = joint.old.normalize(departure - start)
    third = departure + axis * .006
    control = third + axis * .03 + np.array([0, 0, -.11])
    points = [start, departure, third]
    for index in range(1, 9):
        amount = index / 8
        points.append((1 - amount) ** 2 * third + 2 * amount * (1 - amount) * control + amount ** 2 * endpoint)
    return np.array(points)


def offset_retained(path, shift):
    path = np.array(path, dtype=float)
    return straight_neck_path(path[0] + shift, path[1] + shift, path[-1])


def mesh_crossings(hand_points, hand_triangles, face_ids, cord_points, cord_triangles):
    hand = hand_points[hand_triangles[face_ids]]
    cord = cord_points[cord_triangles]
    overlap = np.all((hand.min(axis=1)[:, None] <= cord.max(axis=1)[None] + 1e-9)
                     & (hand.max(axis=1)[:, None] + 1e-9 >= cord.min(axis=1)[None]), axis=2)
    rows = []
    for hand_index, cord_index in np.argwhere(overlap):
        kind = joint.geometry.triangle_contact_kind(hand[hand_index], cord[cord_index])
        if kind in {"proper_crossing", "coplanar_area_overlap"}:
            rows.append([int(face_ids[hand_index]), int(cord_index), kind])
    return rows


def certify_triangle_interiors(hand_points, hand_triangles, face_ids, cord_points, cord_triangles, max_depth=6, budget=18000):
    cord = cord_points[cord_triangles]
    surface = hand_points[hand_triangles[face_ids]]
    nearby = np.all((surface.min(axis=1) <= cord_points.max(axis=0) + .003)
                    & (surface.max(axis=1) + .003 >= cord_points.min(axis=0)), axis=1)
    active = [(int(face), triangle, 0) for face, triangle in zip(face_ids[nearby], surface[nearby])]
    certified, failures, unresolved = [], [], []
    maximum_depth = 0.
    samples = 0
    while active:
        batch, active = active[:64], active[64:]
        if samples + 3 * len(batch) > budget:
            unresolved.extend(int(row[0]) for row in batch + active)
            break
        points = np.array([row[1] for row in batch])
        distances = signed_surface(points.reshape(-1, 3), cord_points, cord_triangles).reshape(-1, 3)
        samples += points.shape[0] * 3
        maximum_depth = max(maximum_depth, max(0, -float(distances.min())))
        for (face, triangle, depth), signed in zip(batch, distances):
            if signed.min() < -.002:
                failures.append({"triangle": face, "sample_maximum_depth_m": max(0, -float(signed.min())), "depth": depth})
                continue
            longest = max(np.linalg.norm(triangle[(index + 1) % 3] - triangle[index]) for index in range(3))
            lower_bound = float(signed.min()) - longest
            if lower_bound >= -.002:
                certified.append({"triangle": face, "signed_distance_lower_bound_m": lower_bound, "depth": depth})
            elif depth >= max_depth:
                unresolved.append(face)
            else:
                first, second, third = triangle
                first_mid, second_mid, third_mid = (first + second) / 2, (second + third) / 2, (third + first) / 2
                active.extend((face, np.array(child), depth + 1) for child in ((first, first_mid, third_mid), (first_mid, second, second_mid), (third_mid, second_mid, third), (first_mid, second_mid, third_mid)))
    return {"passed": not failures and not unresolved, "face_count_near_cord": int(nearby.sum()), "samples": samples,
            "maximum_sample_penetration_m": maximum_depth, "failures": failures, "unresolved_face_ids": sorted(set(unresolved)),
            "certified_subtriangles": len(certified), "method": "Adaptive exact-closed-mesh signed-distance sampling; one-Lipschitz lower bound minus full subtriangle longest edge conservatively covers every interior point. Any bound unresolved at depth6/budget18000 is rejected, never accepted by sample-only maximum.",
            "maximum_depth": max_depth, "sample_budget": budget}


def analyze(output):
    old = joint.old
    prep_path = old.BRANCH / "preparation_05/grip_preparation.json"
    comparison_path = old.BRANCH / "joint_pinch_plan_02/joint_pinch_candidates.json"
    prep = json.loads(prep_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    for key in ("source", "weapon", "root_review"):
        if old.rig.record(Path(prep[key]["path"])) != prep[key]:
            raise ValueError("Frozen source mismatch: " + key)
    prior = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(prior["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = prior["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = old.texture.read_glb(old.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    across, longitudinal, palm, _ = old.hand_frame(bones)
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    hand_faces = np.flatnonzero(np.all(np.isin(triangles, hand_ids), axis=1))
    pads = {finger: joint.pad_faces(finger, positions, triangles, weights, bones, palm) for finger in ("index", "thumb")}
    basis, root = np.array(prep["weapon_basis_columns"]), np.array(prep["terminal_root_rest_m"])
    source_candidates = comparison["comparison"][:3]
    results = []
    for source_index, source in enumerate(source_candidates):
        actual = positions.copy()
        actual[hand_ids] = old.skin.deform(positions[hand_ids], [weights[index] for index in hand_ids], bones, source["commands"])[0]
        interior = np.einsum("sk,tki->tsi", np.array([[1 / 3] * 3, [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]]), actual[triangles[hand_faces]]).reshape(-1, 3)
        samples = np.vstack((actual[hand_ids], interior))
        index_points, index_normals = joint.face_samples(actual, triangles[pads["index"]])
        thumb_points, thumb_normals = joint.face_samples(actual, triangles[pads["thumb"]])
        delta = thumb_points[None] - index_points[:, None]
        distance = np.linalg.norm(delta, axis=2)
        direction = joint.normalized_rows(delta)
        index_facing = np.einsum("ijt,it->ij", direction, index_normals)
        thumb_facing = -np.einsum("ijt,jt->ij", direction, thumb_normals)
        for diameter_mm in (8, 10, 12):
            radius = diameter_mm / 2000
            scores = np.abs(distance - radius * 2) + .05 * np.maximum(.3 - index_facing, 0) + .05 * np.maximum(.3 - thumb_facing, 0)
            selected = np.unravel_index(np.argmin(scores), scores.shape)
            center = (index_points[selected[0]] + thumb_points[selected[1]]) / 2
            span = old.normalize(thumb_points[selected[1]] - index_points[selected[0]])
            axis = old.normalize(across - span * np.dot(across, span))
            local_center, local_axis = (center - root) @ basis, axis @ basis
            release_path = straight_neck_path(local_center + local_axis * .020, local_center - local_axis * .020, np.array([.1, 0, -.52]))
            release_points, release_triangles = transported_tube(release_path, radius)
            release_points = release_points @ basis.T + root
            release_signed = signed_surface(samples, release_points, release_triangles)
            contacts, radials = {}, []
            for finger in pads:
                pad_points, normals = joint.face_samples(actual, triangles[pads[finger]])
                distances, nearest = joint.nearest_surface(pad_points, release_points[release_triangles])
                chosen = int(np.argmin(distances))
                vector = nearest[chosen] - center
                radial = old.normalize(vector - axis * np.dot(axis, vector))
                radials.append(radial)
                contacts[finger] = {"triangle": int(pads[finger][chosen]), "barycentric": [1 / 3] * 3, "distance_m": float(distances[chosen]), "normal_dot_outward_radial": float(np.dot(normals[chosen], radial))}
            retained_options = []
            for shift_longitudinal in (-.006, 0, .006):
                for shift_palm in (-.012, -.008, -.004):
                    shift = (longitudinal * shift_longitudinal + palm * shift_palm) @ basis
                    path = offset_retained(prep["terminal_path_proposal_local_m"]["cord_N1"], shift)
                    center_retained = np.mean(path[:2], axis=0) @ basis.T + root
                    approximate = old.cylinder_distances(samples, center_retained, across, radius, (-.0405, .0405))
                    retained_options.append({"shift_m": shift.tolist(), "path": path, "approx_penetration": max(0, -float(approximate.min()))})
            retained_options.sort(key=lambda row: row["approx_penetration"])
            retained_results = []
            for option in retained_options[:3]:
                points, faces = transported_tube(option["path"], radius)
                points = points @ basis.T + root
                signed = signed_surface(samples, points, faces)
                retained_results.append({"path": option["path"], "shift_m": option["shift_m"], "points": points, "triangles": faces,
                                         "maximum_sample_depth_m": max(0, -float(signed.min()))})
            retained = min(retained_results, key=lambda row: row["maximum_sample_depth_m"])
            checks = {"both_actual03pad_face_contacts_within2mm": max(row["distance_m"] for row in contacts.values()) <= .002,
                      "opposed_pad_radials_at_most_minus0p5": float(np.dot(*radials)) <= -.5,
                      "pad_normals_point_into_contact": all(row["normal_dot_outward_radial"] <= -.3 for row in contacts.values()),
                      "release_cord_hand_vertex_and_interior_samples_under2mm": float(release_signed.min()) >= -.002,
                      "retained_cord_hand_vertex_and_interior_samples_under2mm": retained["maximum_sample_depth_m"] <= .002,
                      "inherited_two_digit_and_other_hand_no_crossings": not source["index_thumb_crossings"] and not source["index_thumb_other_hand_crossings"]}
            row = {"pose_candidate_index": source_index, "diameter_mm": diameter_mm, "original_diameter_mm": 16,
                   "commands": source["commands"], "checks": checks, "contacts": contacts, "opposed_radial_dot": float(np.dot(*radials)),
                   "release_maximum_sample_depth_m": max(0, -float(release_signed.min())), "retained_maximum_sample_depth_m": retained["maximum_sample_depth_m"],
                   "retained_local_shift_m": retained["shift_m"], "path_proposal_local_m": {"cord_N1": retained["path"].tolist(), "cord_P1": release_path.tolist()},
                   "hand_sample_count": len(samples), "release_predicted_triangle_intersections": mesh_crossings(actual, triangles, hand_faces, release_points, release_triangles),
                   "retained_predicted_triangle_intersections": mesh_crossings(actual, triangles, hand_faces, retained["points"], retained["triangles"])}
            row["retained_digit_contacts"] = {}
            for finger in ("middle", "ring", "pinky"):
                qualified = np.array([sum(value for name, value in weights[index].items() if name.startswith(finger + "_") and name.endswith("_r")) > .5 for index in range(len(weights))])
                selected_faces = np.flatnonzero(np.all(qualified[triangles], axis=1))
                centers, _ = joint.face_samples(actual, triangles[selected_faces])
                distances, _ = joint.nearest_surface(centers, retained["points"][retained["triangles"]])
                nearest = int(np.argmin(distances))
                row["retained_digit_contacts"][finger] = {"triangle": int(selected_faces[nearest]), "distance_m": float(distances[nearest])}
            row["checks"]["retained_three_digit_surface_contacts_within2mm"] = all(value["distance_m"] <= .002 for value in row["retained_digit_contacts"].values())
            results.append(row)
    results.sort(key=lambda row: (sum(not value for value in row["checks"].values()), max(row["release_maximum_sample_depth_m"], row["retained_maximum_sample_depth_m"]), max(value["distance_m"] for value in row["contacts"].values())))
    for row in results[:3]:
        actual = positions.copy()
        actual[hand_ids] = old.skin.deform(positions[hand_ids], [weights[index] for index in hand_ids], bones, row["commands"])[0]
        row["full_interior_certification"] = {}
        for name, path in row["path_proposal_local_m"].items():
            points, faces = transported_tube(path, row["diameter_mm"] / 2000)
            points = points @ basis.T + root
            crossings = joint.pair_crossings(points, faces, np.arange(len(faces)), np.arange(len(faces)), np.arange(len(points)))
            result = certify_triangle_interiors(actual, triangles, hand_faces, points, faces)
            row["full_interior_certification"][name] = result
            row["checks"][name + "_all_interior_2mm_bound_certified"] = result["passed"]
            row["checks"][name + "_no_cord_self_crossings"] = not crossings
            result["predicted_cord_self_crossings"] = crossings
    summary = [{"pose_candidate_index": row["pose_candidate_index"], "diameter_mm": row["diameter_mm"], "checks": row["checks"]} for row in results]
    result = {"asset_id": "Unit_StoneSlinger", "status": "three_authorized_diameter_comparison_pending_actual_DCC", "source": prep["source"], "weapon": prep["weapon"],
              "script": old.rig.record(Path(__file__)), "joint_math": old.rig.record(Path(joint.__file__)), "prior_candidates": old.rig.record(comparison_path),
              "bounded_search": {"existing_pose_pairs": 3, "diameters_mm": [8, 10, 12], "retained_offsets_per_case": 9, "retained_mesh_audits_per_case": 3,
                                 "joint_cases": len(results), "returned_best": 3, "interior_adaptive_maxdepth": 6, "interior_sample_budget_per_cord": 18000},
              "best_candidates": results[:3], "case_check_summary": summary,
              "all_current_pure_gates_pass_count": sum(all(row["checks"].values()) for row in results[:3]),
              "source_geometry_UV_Draw_weights_modified": False, "blender_executed": False, "grip_approved": False,
              "scope": "Authorized derivative cord diameter/terminal position only. Actual Blender tessellation and final posed pad/interior checks remain mandatory. Wrist/cuff, garment weights and gait remain separate unresolved diagnostic work."}
    result["derivative_tube_method"] = "Parallel-transported radial frames and a straight3ring contact neck; same88vertices/172fixed triangles, original source Basis/UV/Draw unchanged. Avoid per-ring reference-axis jumps that flatten or twist an arbitrary terminal direction."
    output.mkdir(parents=True, exist_ok=False)
    old.rig.save(output / "diameter_comparison.json", result)
    print(json.dumps({"path": str(output / "diameter_comparison.json"), "pure_passed": result["all_current_pure_gates_pass_count"], "best": results[0]["checks"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.output).resolve())
