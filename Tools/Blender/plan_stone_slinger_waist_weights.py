"""Bounded two-native-vertex waist diagnosis without opening Blender."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_stone_slinger_sling_grip as grip
import stone_slinger_foot_math as geometry


TARGET_NATIVE = (908, 2331)
ALLOWED_RECIPIENTS = {"pelvis", "spine_01", "spine_02", "thigh_r"}


def remove_arm_influence(weights):
    removed = weights.get("upperarm_r", 0.)
    if not 0 < removed < .1 or not set(weights).issubset(ALLOWED_RECIPIENTS | {"upperarm_r"}):
        raise ValueError("Unexpected local waist influence; no broad redistribution")
    recipients = {name: value for name, value in weights.items() if name != "upperarm_r"}
    mass = sum(recipients.values())
    if mass <= 0:
        raise ValueError("No existing torso/leg recipients")
    return {name: value + removed * value / mass for name, value in recipients.items()}


def rotation_between(first, second):
    first, second = grip.normalize(first), grip.normalize(second)
    axis = np.cross(first, second)
    sine, cosine = np.linalg.norm(axis), float(np.dot(first, second))
    if sine < 1e-12:
        if cosine < 0:
            raise ValueError("Ambiguous opposite-direction arm solution")
        return np.eye(3)
    return grip.skin.axis_rotation(axis / sine, np.degrees(np.arctan2(sine, cosine)))[:3, :3]


def local_pose_matrices(bones, name):
    commands = []
    if name.startswith("move_"):
        sign = 1 if name == "move_A" else -1
        commands = [["thigh_l", [0, 1, 0], sign * 7], ["thigh_r", [0, 1, 0], -sign * 7],
                    ["calf_l", [0, 1, 0], 6 if sign > 0 else 0], ["calf_r", [0, 1, 0], 0 if sign > 0 else 6]]
    rest, posed = grip.skin.pose_matrices(bones, commands)
    if name != "rest":
        shoulder = posed["upperarm_r"][:3, 3]
        elbow = posed["lowerarm_r"][:3, 3]
        wrist = posed["hand_r"][:3, 3]
        first_length, second_length = np.linalg.norm(elbow - shoulder), np.linalg.norm(wrist - elbow)
        phase = .015 if name == "move_A" else -.015 if name == "move_B" else 0.
        target, pole = np.array([.23 + phase, -.43, .98]), np.array([-.05, -.55, 1.02])
        delta = target - shoulder
        distance = min(np.linalg.norm(delta), (first_length + second_length) * .995)
        axis = grip.normalize(delta)
        pole_delta = pole - shoulder
        elbow_axis = grip.normalize(pole_delta - axis * np.dot(pole_delta, axis))
        along = (first_length ** 2 - second_length ** 2 + distance ** 2) / (2 * distance)
        desired_elbow = shoulder + axis * along + elbow_axis * np.sqrt(max(0., first_length ** 2 - along ** 2))
        rotation = rotation_between(elbow - shoulder, desired_elbow - shoulder)
        posed["upperarm_r"] = posed["upperarm_r"].copy()
        posed["upperarm_r"][:3, :3] = rotation @ posed["upperarm_r"][:3, :3]
    return {name: posed[name] @ np.linalg.inv(matrix) for name, matrix in rest.items()}


def local_skin(positions, weights, matrices):
    homogeneous = np.column_stack((positions, np.ones(len(positions))))
    actual = np.array([sum((matrices[name] @ point)[:3] * value for name, value in row.items()) for point, row in zip(homogeneous, weights)])
    linear = np.array([sum(matrices[name][:3, :3] * value for name, value in row.items()) for row in weights])
    return actual, linear


def native_neighborhood(triangles, native, seeds, rings=1):
    chosen = set(seeds)
    for _ in range(rings):
        face_ids = np.flatnonzero(np.any(np.isin(native[triangles], list(chosen)), axis=1))
        chosen.update(int(value) for value in native[triangles[face_ids]].ravel())
    face_ids = np.flatnonzero(np.all(np.isin(native[triangles], list(chosen)), axis=1))
    return sorted(chosen), face_ids


def projection(path, positions, triangles, face_ids, native, target_ids):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (1280, 640), "#161b22")
    draw = ImageDraw.Draw(canvas)
    vertices = np.unique(triangles[face_ids])
    for panel, (axes, label) in enumerate((((0, 2), "X/Z side of waist"), ((1, 2), "Y/Z end of waist"))):
        points = positions[vertices][:, axes]
        low, high = points.min(axis=0), points.max(axis=0)
        scale = min(510 / max(high[0] - low[0], .01), 480 / max(high[1] - low[1], .01))
        center = (low + high) * .5
        projected = {int(vertex): (float((positions[vertex, axes[0]] - center[0]) * scale + panel * 640 + 320),
                                  float(340 - (positions[vertex, axes[1]] - center[1]) * scale)) for vertex in vertices}
        draw.text((panel * 640 + 20, 20), label + " | two native vertices only", fill="white")
        for face in face_ids:
            polygon = [projected[int(vertex)] for vertex in triangles[face]]
            color = "#7192a2" if face not in (3355, 5610) else "#f1a24a"
            draw.line(polygon + [polygon[0]], fill=color, width=2)
        for native_id in sorted(set(native[vertices])):
            vertex = int(next(value for value in vertices if native[value] == native_id))
            horizontal, vertical = projected[vertex]
            selected = native_id in target_ids
            draw.ellipse((horizontal - 4, vertical - 4, horizontal + 4, vertical + 4), fill="#ff659c" if selected else "#9bb3bf")
            draw.text((horizontal + 5, vertical - 12), str(native_id), fill="#ff91b5" if selected else "#b3c5ce")
    draw.text((20, 611), "DATA projection, not a rendered or applied mesh. Pink: 908/2331; orange: original failing3355/5610. UV duplicates remain distinct.", fill="white")
    canvas.save(path)


def analyze(output):
    if grip.rig.record(grip.SOURCE)["sha256"] != grip.SOURCE_SHA:
        raise ValueError("Frozen accepted foot-weight source changed")
    transfer_path = grip.rig.BRANCH / "rig_transfer_candidate_03/transfer_report.json"
    transfer = json.loads(transfer_path.read_text(encoding="utf-8"))
    mapping_path = Path(transfer["mapping"]["path"])
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    arrays = grip.texture.read_glb(grip.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    native = np.array([mapping["source_render_vertex_to_cleaned_native_vertex"][str(index)] for index in range(len(positions))])
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    bones = transfer["actual_final_skeleton"]["armatures"][0]["bones"]
    neighbourhood, face_ids = native_neighborhood(triangles, native, TARGET_NATIVE, 2)
    vertices = np.unique(triangles[face_ids])
    if positions[vertices, 2].min() < .75 or any(not set(weights[int(index)]).issubset(ALLOWED_RECIPIENTS | {"upperarm_r"}) for index in vertices):
        raise ValueError("Local region expanded outside proven torso/waist influences")
    foot_report_path = grip.rig.BRANCH / "foot_weight_candidate_02/foot_weight_report.json"
    foot_report = json.loads(foot_report_path.read_text(encoding="utf-8"))
    foot_changes_path = Path(foot_report["actual_weight_changes"]["path"])
    if grip.rig.record(foot_changes_path) != foot_report["actual_weight_changes"]:
        raise ValueError("Accepted foot-weight evidence changed")
    foot_changes = json.loads(foot_changes_path.read_text(encoding="utf-8"))
    foot_changed = {int(row["source_vertex"]) for row in foot_changes["changes"]}
    if set(vertices) & foot_changed:
        raise ValueError("Waist diagnostic overlaps frozen foot-weight edits")
    proposed = [dict(row) for row in weights]
    changes, neighbours = [], []
    for native_id in neighbourhood:
        render_ids = np.flatnonzero(native == native_id).tolist()
        original = weights[render_ids[0]]
        if any(weights[index] != original for index in render_ids):
            raise ValueError("UV-duplicate weights conflict; do not average")
        record = {"native_vertex": native_id, "render_vertices": render_ids, "rest_m": positions[render_ids[0]].tolist(),
                  "UVs": arrays["TEXCOORD_0"][render_ids].tolist(), "weights": original,
                  "incident_faces": np.flatnonzero(np.any(native[triangles] == native_id, axis=1)).tolist()}
        neighbours.append(record)
        if native_id in TARGET_NATIVE:
            after = remove_arm_influence(original)
            for vertex in render_ids:
                proposed[vertex] = dict(after)
                changes.append({"vertex": vertex, "native_vertex": native_id, "before": original, "after": after,
                                "delta": {name: after.get(name, 0.) - original.get(name, 0.) for name in original}})
    local_index = {int(vertex): index for index, vertex in enumerate(vertices)}
    local_triangles = np.array([[local_index[int(vertex)] for vertex in face] for face in triangles[face_ids]])
    before_weights = [weights[int(vertex)] for vertex in vertices]
    after_weights = [proposed[int(vertex)] for vertex in vertices]
    pose_reports = []
    for name in ("rest", "idle", "move_A", "move_B"):
        matrices = local_pose_matrices(bones, name)
        before, before_linear = local_skin(positions[vertices], before_weights, matrices)
        after, after_linear = local_skin(positions[vertices], after_weights, matrices)
        before_check = geometry.triangle_orientation(positions[vertices], before, local_triangles, before_linear)
        after_check = geometry.triangle_orientation(positions[vertices], after, local_triangles, after_linear)
        for check in (before_check, after_check):
            for field in ("negative_triangles", "degenerate_triangles"):
                check[field] = [int(face_ids[index]) for index in check[field]]
        displacements = np.linalg.norm(after - before, axis=1)
        pose_reports.append({"pose": name, "before": before_check, "after": after_check,
                             "maximum_changed_surface_displacement_mm": float(displacements.max() * 1000),
                             "new_negative_triangles": sorted(set(after_check["negative_triangles"]) - set(before_check["negative_triangles"])),
                             "local_vertex_count": len(vertices), "local_triangle_count": len(face_ids)})
    result = {"asset_id": "Unit_StoneSlinger", "status": "pure_two_native_waist_weight_candidate_not_applied",
              "script": grip.rig.record(Path(__file__)), "source": grip.rig.record(grip.SOURCE),
              "source_mesh": grip.rig.record(grip.rig.SOURCE), "mapping": grip.rig.record(mapping_path),
              "transfer_report": grip.rig.record(transfer_path), "accepted_foot_weights": grip.rig.record(foot_report_path),
              "local_grip_review": grip.rig.record(grip.BRANCH / "loop_anchor_candidate_01/root_stage_review.json"),
              "source_of_arm_weights": "Actual Tripo rig source_vertex_weights mapped by complete triangle/corner correspondence, then unchanged by accepted foot-only repair. Not introduced by current sling pose or interpolation.",
              "candidate_rule": "Only native908/2331 and every existing UV render duplicate: remove upperarm_r and distribute its mass proportionally among that vertex's already present spine01/spine02/thigh_r influences. No new bone recipient, neighbour smoothing or expanded selection.",
              "candidate_count": 1, "changed_native_vertices": list(TARGET_NATIVE), "exact_weight_changes": changes,
              "read_only_two_ring_neighbourhood": neighbours, "diagnostic_face_ids": face_ids.tolist(),
              "pure_pose_comparisons": pose_reports,
              "checks": {"only_four_render_vertices_changed": len(changes) == 4,
                         "no_change_outside_target_native": all(before == after for index, (before, after) in enumerate(zip(weights, proposed)) if native[index] not in TARGET_NATIVE),
                         "accepted_foot_region_disjoint": not set(vertices) & foot_changed,
                         "mass_preserved": all(abs(sum(row["before"].values()) - sum(row["after"].values())) < 1e-12 for row in changes),
                         "no_new_negative_faces_in_four_local_poses": all(not row["new_negative_triangles"] for row in pose_reports),
                         "no_negative_faces_remaining_in_local_poses": all(not row["after"]["negative_triangles"] for row in pose_reports)},
              "scope": "Pure local skin prediction, not actual Blender geometry or approval. Only waist influences are evaluated; hand pose, cuff crossings and complete gait remain outside this diagnosis. Actual original Idle/MoveA/MoveB require identical pose evaluation, local before-after images, seam-gradient and intersection gates under a new lease.",
              "actual_weights_modified": False, "actual_mesh_PBR_modified": False, "heavy_process_started": False,
              "approved": False}
    output.mkdir(parents=True, exist_ok=False)
    projection(output / "waist_region_projection.png", positions, triangles, face_ids, native, TARGET_NATIVE)
    result["projection"] = grip.rig.record(output / "waist_region_projection.png")
    grip.rig.save(output / "waist_weight_plan.json", result)
    print(json.dumps({"output": str(output), "changes": changes, "checks": result["checks"], "poses": pose_reports}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    analyze(Path(arguments.output).resolve())
