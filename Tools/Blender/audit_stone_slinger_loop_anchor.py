"""Bounded certificate refinement for unchanged loop-route geometry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refine_stone_slinger_sling_diameter as geometry


def fixed_contact_samples(points, triangles, weights, bone_name, mesh_points, mesh_triangles):
    qualified = np.array([row.get(bone_name, 0) > .4 for row in weights])
    face_ids = np.flatnonzero(np.all(qualified[triangles], axis=1))
    barycentric = np.array([[first / 12, second / 12, (12 - first - second) / 12]
                            for first in range(1, 11) for second in range(1, 12 - first)])
    samples = np.einsum("sk,tki->tsi", barycentric, points[triangles[face_ids]]).reshape(-1, 3)
    distances, locations = [], []
    for start in range(0, len(samples), 32):
        batch_distances, batch_locations = geometry.joint.nearest_surface(samples[start:start + 32], mesh_points[mesh_triangles])
        distances.extend(batch_distances)
        locations.extend(batch_locations)
    distances = np.array(distances)
    best = int(np.argmin(distances))
    face_index, sample_index = divmod(best, len(barycentric))
    return {"bone": bone_name, "selection": "All three face corners have the stated03boneweight>0.4; interior barycentric lattice has every coordinate>=1/12. No02proxy/vertex-onlycontact.",
            "face_count": len(face_ids), "samples_per_face": len(barycentric), "samples": len(samples), "triangle": int(face_ids[face_index]),
            "barycentric": barycentric[sample_index].tolist(), "gap_m": float(distances[best]), "surface_world_m": samples[best].tolist(), "cord_surface_world_m": np.array(locations[best]).tolist()}


def analyze(plan_path, output):
    old = geometry.joint.old
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    prep = json.loads((old.BRANCH / "preparation_05/grip_preparation.json").read_text(encoding="utf-8"))
    for key in ("source", "weapon", "root_review"):
        if old.rig.record(Path(prep[key]["path"])) != prep[key]:
            raise ValueError("Frozen input changed")
    source = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(source["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = source["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = old.texture.read_glb(old.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    actual = positions.copy()
    actual[hand_ids] = old.skin.deform(positions[hand_ids], [weights[index] for index in hand_ids], bones, plan["commands"])[0]
    basis, root = np.array(plan["basis_columns"]), np.array(plan["root_rest_m"])
    result = {"status": "fixed_geometry_certificate_audit_not_DCC_approval", "source_plan": old.rig.record(plan_path), "script": old.rig.record(Path(__file__)),
              "new_candidates": 0, "geometry_changed": False, "pose_changed": False, "penetration_limit_m": .002,
              "fixed_refinement": {"maximum_depth": 8, "sample_budget_per_cord": 12000, "only_previously_unresolved_faces": True}, "cords": {}, "grip_approved": False}
    for name, mesh in plan["meshes"].items():
        points = np.array(mesh["positions_local_m"]) @ basis.T + root
        faces = np.array(mesh["triangles"])
        initial = plan["diagnostics"][name]["full_face_interior"]
        unresolved = np.array(initial["unresolved_face_ids"], dtype=int)
        refined = geometry.certify_triangle_interiors(actual, triangles, unresolved, points, faces, max_depth=8, budget=12000) if len(unresolved) else None
        passed = not initial["failures"] and (refined is None or refined["passed"])
        result["cords"][name] = {"original_certificate_passed": initial["passed"], "original_unresolved_faces": unresolved.tolist(), "original_failure_count": len(initial["failures"]),
                                  "refined_certificate": refined, "complete_face_interior_passed": bool(passed)}
        if name == "retained_loop_cord":
            result["actual_local03_contact"] = fixed_contact_samples(actual, triangles, weights, "pinky_03_r", points, faces)
    result["checks"] = {key: value for key, value in plan["checks"].items() if key not in {"retained_finger_contact_within2mm", "full_face_interiors_within2mm_certified"}}
    result["checks"]["retained_true03_face_interior_contact_within2mm"] = result["actual_local03_contact"]["gap_m"] <= .002
    result["checks"]["full_face_interiors_within2mm_certified"] = all(row["complete_face_interior_passed"] for row in result["cords"].values())
    result["prior_centroid_only_contact_m"] = plan["retention_surface_contact"]["gap_m"]
    result["explanation"] = "The original centroid-only result remains preserved. The new contact is an explicit interior point on a genuine03weighted triangle, not a different hand region. Certificate depth increases only proof resolution on the exact three previously unresolved faces; geometric2mm limit never changes."
    output.mkdir(parents=True, exist_ok=False)
    old.rig.save(output / "fixed_geometry_audit.json", result)
    print(json.dumps({"checks": result["checks"], "contact_gap_mm": result["actual_local03_contact"]["gap_m"] * 1000,
                      "certificates": {name: row["complete_face_interior_passed"] for name, row in result["cords"].items()}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.plan).resolve(), Path(args.output).resolve())
