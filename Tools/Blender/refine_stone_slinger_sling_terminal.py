"""One bounded micro-adjustment of the authorized8mm independent sling."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refine_stone_slinger_sling_diameter as diameter


def analyze(output):
    joint, old = diameter.joint, diameter.joint.old
    prior_path = old.BRANCH / "diameter_plan_02/diameter_comparison.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    chosen = prior["best_candidates"][0]
    if chosen["diameter_mm"] != 8:
        raise ValueError("This bounded adjustment is frozen to8mm")
    prep = json.loads((old.BRANCH / "preparation_05/grip_preparation.json").read_text(encoding="utf-8"))
    for key in ("source", "weapon", "root_review"):
        if old.rig.record(Path(prep[key]["path"])) != prep[key]:
            raise ValueError("Frozen source changed")
    original = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(original["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = original["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = old.texture.read_glb(old.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    across, longitudinal, palm, _ = old.hand_frame(bones)
    basis, root = np.array(prep["weapon_basis_columns"]), np.array(prep["terminal_root_rest_m"])
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    hand_faces = np.flatnonzero(np.all(np.isin(triangles, hand_ids), axis=1))
    actual = positions.copy()
    actual[hand_ids] = old.skin.deform(positions[hand_ids], [weights[index] for index in hand_ids], bones, chosen["commands"])[0]
    interior = np.einsum("sk,tki->tsi", np.array([[1 / 3] * 3, [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]]), actual[triangles[hand_faces]]).reshape(-1, 3)
    samples = np.vstack((actual[hand_ids], interior))
    pads = {finger: joint.pad_faces(finger, positions, triangles, weights, bones, palm) for finger in ("index", "thumb")}
    release_path = np.array(chosen["path_proposal_local_m"]["cord_P1"])
    release_center = release_path[:2].mean(axis=0) @ basis.T + root
    release_axis = old.normalize((release_path[0] - release_path[1]) @ basis.T)
    finger_centers = [actual[triangles[chosen["contacts"][finger]["triangle"]]].mean(axis=0) for finger in ("index", "thumb")]
    span = old.normalize(finger_centers[1] - finger_centers[0])
    options = {"cord_N1": [], "cord_P1": []}
    retained_path = np.array(chosen["path_proposal_local_m"]["cord_N1"])
    for angle in (-20, 0, 20):
        for shift in (-.001, 0, .001):
            axis = old.skin.axis_rotation(span.copy(), angle)[:3, :3] @ release_axis
            center = release_center + span * shift
            local_center, local_axis = (center - root) @ basis, axis @ basis
            path = diameter.straight_neck_path(local_center + local_axis * .02, local_center - local_axis * .02, release_path[-1])
            options["cord_P1"].append({"path": path, "center": center, "axis": axis, "angle_deg": angle, "pinch_center_shift_m": shift})
    for shift_palm in (-.012, -.006, 0):
        for shift_longitudinal in (-.006, 0, .006):
            shift = (palm * shift_palm + longitudinal * shift_longitudinal) @ basis
            path = diameter.offset_retained(retained_path, shift)
            options["cord_N1"].append({"path": path, "extra_shift_m": shift.tolist()})
    for name, rows in options.items():
        for row in rows:
            points, faces = diameter.transported_tube(row["path"], .004)
            points = points @ basis.T + root
            signed = diameter.signed_surface(samples, points, faces)
            contact, radials = {}, []
            for finger in (("index", "thumb") if name == "cord_P1" else ("middle", "ring", "pinky")):
                if name == "cord_P1":
                    selected = pads[finger]
                else:
                    qualified = np.array([sum(value for bone, value in weight.items() if bone.startswith(finger + "_") and bone.endswith("_r")) > .5 for weight in weights])
                    selected = np.flatnonzero(np.all(qualified[triangles], axis=1))
                centers, normals = joint.face_samples(actual, triangles[selected])
                distances, nearest = joint.nearest_surface(centers, points[faces])
                closest = int(np.argmin(distances))
                contact[finger] = {"triangle": int(selected[closest]), "barycentric": [1 / 3] * 3, "distance_m": float(distances[closest])}
                if name == "cord_P1":
                    delta = nearest[closest] - row["center"]
                    radial = old.normalize(delta - row["axis"] * np.dot(delta, row["axis"]))
                    radials.append(radial)
                    contact[finger]["normal_dot_outward_radial"] = float(np.dot(normals[closest], radial))
            checks = {"contact_surfaces_within2mm": max(value["distance_m"] for value in contact.values()) <= .002,
                      "vertex_and_face_samples_penetration_within2mm": float(signed.min()) >= -.002}
            if name == "cord_P1":
                row["opposed_radial_dot"] = float(np.dot(*radials))
                checks["opposed_radial_dot_at_most_minus0p5"] = row["opposed_radial_dot"] <= -.5
                checks["pad_normals_face_cord"] = all(value["normal_dot_outward_radial"] <= -.3 for value in contact.values())
            row.update({"checks": checks, "contacts": contact, "maximum_sample_depth_m": max(0, -float(signed.min())),
                        "predicted_hand_triangle_intersections": diameter.mesh_crossings(actual, triangles, hand_faces, points, faces)})
        rows.sort(key=lambda row: (sum(not value for value in row["checks"].values()), row["maximum_sample_depth_m"], max(value["distance_m"] for value in row["contacts"].values())))
        for row in rows[:3]:
            points, faces = diameter.transported_tube(row["path"], .004)
            points = points @ basis.T + root
            row["full_interior_certification"] = diameter.certify_triangle_interiors(actual, triangles, hand_faces, points, faces)
            row["checks"]["full_hand_face_interior_2mm_bound_certified"] = row["full_interior_certification"]["passed"]
            self_crossings = joint.pair_crossings(points, faces, np.arange(len(faces)), np.arange(len(faces)), np.arange(len(points)))
            row["checks"]["no_cord_self_crossings"] = not self_crossings
            row["predicted_cord_self_crossings"] = self_crossings
        options[name] = sorted(rows[:3], key=lambda row: (sum(not value for value in row["checks"].values()), row["maximum_sample_depth_m"]))
    results = []
    for retained_index, released_index in ((0, 0), (1, 0), (0, 1)):
        retained, released = options["cord_N1"][retained_index], options["cord_P1"][released_index]
        results.append({"diameter_mm": 8, "commands": chosen["commands"], "retained": retained, "released": released,
                        "pure_checks_passed": all(retained["checks"].values()) and all(released["checks"].values()),
                        "inherited_index_thumb_and_other_hand_crossings": 0})
    def serializable(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, dict):
            return {key: serializable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [serializable(item) for item in value]
        return value
    result = {"asset_id": "Unit_StoneSlinger", "status": "final_bounded_terminal_micro_comparison_pending_root", "script": old.rig.record(Path(__file__)),
              "geometry_math": old.rig.record(Path(diameter.__file__)), "source": prep["source"], "weapon": prep["weapon"], "prior_diameter_comparison": old.rig.record(prior_path),
              "budget": {"bone_pose_pairs": 1, "diameter_mm": 8, "release_options": 9, "retained_options": 9, "full_certified_options_each": 3, "returned_best_pairs": 3},
              "best_candidates": results, "pure_pass_count": sum(row["pure_checks_passed"] for row in results),
              "original_geometry_UV_Draw_human_weights_modified": False, "actual_blender_executed": False, "grip_approved": False,
              "next_action": "No further unbounded search; present this bounded comparison and pending actual diagnostic specification to root."}
    output.mkdir(parents=True, exist_ok=False)
    old.rig.save(output / "terminal_comparison.json", serializable(result))
    print(json.dumps({"pure_pass_count": result["pure_pass_count"], "path": str(output / "terminal_comparison.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.output).resolve())
