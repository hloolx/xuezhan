"""Read actual hand weights and plan a distinct two-terminal sling grip."""
from __future__ import annotations

import argparse
from itertools import product
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspect_stone_slinger_rig as rig
import plan_stone_slinger_foot_weights as skin
import review_stone_slinger_texture as texture


ROOT = Path(__file__).resolve().parents[2]
BRANCH = rig.BRANCH / "sling_pilot_v01"
SOURCE = rig.BRANCH / "foot_weight_candidate_02/Unit_StoneSlinger_LocalFootWeights.blend"
SOURCE_SHA = "960ce41300b9dd6323f451458865cde6770ffe835547c3d2f27b4ad1faa92225"
WEAPON = rig.ART / "weapons/Weapon_Sling/Weapon_Sling.blend"
WEAPON_SHA = "c6bd89d23ed3bed6b664fdd8cbba08f2d2495d161a874bb377982721fb920f90"
RELEASE_LONGITUDINAL = -.005
RELEASE_PALM = .025


def normalize(value):
    value = np.asarray(value, dtype=float)
    return value / np.linalg.norm(value)


def hand_frame(bones):
    by_name = {bone["name"]: bone for bone in bones}
    head = lambda name: np.array(by_name[name]["head_world_review_m"])
    across = normalize(head("index_01_r") - head("pinky_01_r"))
    longitudinal = head("middle_01_r") - head("hand_r")
    longitudinal = normalize(longitudinal - across * np.dot(longitudinal, across))
    palm = normalize(np.cross(across, longitudinal))
    center = (head("index_01_r") + head("pinky_01_r")) * .5
    return across, longitudinal, palm, center


def terminal_paths():
    paths = {}
    for name, side in (("cord_N1", -1), ("cord_P1", 1)):
        if side == -1:
            start, departure = np.array([0., -.058, 0.]), np.array([0., .023, 0.])
        else:
            start = np.array([.035 - RELEASE_PALM, .060, .008 - RELEASE_LONGITUDINAL])
            departure = np.array([.035 - RELEASE_PALM, .032, .008 - RELEASE_LONGITUDINAL])
        endpoint = np.array([.025 + side * .075, 0., -.52])
        control = departure + np.array([side * .07, 0, -.11])
        points = [start, departure]
        for index in range(1, 10):
            amount = index / 9
            points.append((1 - amount) ** 2 * departure + 2 * amount * (1 - amount) * control + amount ** 2 * endpoint)
        paths[name] = np.array(points)
    return paths


def cylinder_distances(points, center, axis, radius, interval):
    delta = points - center
    along = delta @ axis
    radial = np.linalg.norm(delta - along[:, None] * axis, axis=1) - radius
    axial = np.maximum(interval[0] - along, along - interval[1])
    return np.minimum(np.maximum(radial, axial), 0) + np.linalg.norm(np.maximum(np.column_stack((radial, axial)), 0), axis=1)


def fit_finger(name, positions, weights, bones, across, longitudinal, palm, center):
    retained = name in {"middle", "ring", "pinky"}
    terminal_center = center + longitudinal * (.008 if retained else RELEASE_LONGITUDINAL) + palm * (.035 if retained else RELEASE_PALM)
    interval = (-.058, .023) if retained else (.032, .060)
    indices = [index for index, row in enumerate(weights) if sum(value for bone, value in row.items() if bone.startswith(name + "_") and bone.endswith("_r")) > .5]
    distal = np.array([index for index, original in enumerate(indices) if sum(weights[original].get(name + "_" + joint + "_r", 0) for joint in ("02", "03")) > .6], dtype=int)
    if not indices or not len(distal):
        raise ValueError("Missing real weighted digit surface: " + name)
    candidates = []
    if name == "thumb":
        configurations = [(opposition, base, middle) for opposition in (-20, 0, 20, 40) for base in (15, 35, 55) for middle in (15, 35, 55)]
    else:
        configurations = [(first, second, third) for first in (25, 35, 45, 55, 65, 75) for second in (20, 30, 40, 50, 60, 70) for third in (0, 10, 20)]
    local_positions, local_weights = positions[indices], [weights[index] for index in indices]
    for angles in configurations:
        if name == "thumb":
            first_axis = normalize(across * np.cos(np.radians(angles[0])) + longitudinal * np.sin(np.radians(angles[0])))
            commands = [["thumb_01_r", first_axis.tolist(), angles[1]], ["thumb_02_r", across.tolist(), angles[2]], ["thumb_03_r", across.tolist(), 10]]
        else:
            commands = [[name + "_" + str(joint).zfill(2) + "_r", across.tolist(), angle] for joint, angle in enumerate(angles, 1)]
        actual, _ = skin.deform(local_positions, local_weights, bones, commands)
        distances = cylinder_distances(actual, terminal_center, across, .008, interval)
        contact = float(np.min(distances[distal]))
        penetration = float(np.sum(np.minimum(0, distances + .001) ** 2))
        score = penetration * 80 + max(0, contact - .002) ** 2
        candidates.append({"parameters": list(angles), "commands": commands, "score": score,
                           "maximum_surface_vertex_penetration_mm": max(0., -float(distances.min())) * 1000,
                           "distal_contact_distance_mm": contact * 1000,
                           "vertices_inside_over2mm": int(np.count_nonzero(distances < -.002))})
    candidates.sort(key=lambda row: row["score"])
    return {"finger": name, "weighted_render_vertices": len(indices), "distal_render_vertices": len(distal),
            "assigned_terminal": "retained" if retained else "released_by_index_thumb",
            "diagnostic_cylinder_center_rest_m": terminal_center.tolist(), "radius_m": .008,
            "axis_rest": across.tolist(), "finite_axis_interval_m": list(interval),
            "best": candidates[0], "alternatives": candidates[1:5],
            "method": "Pure LBS surface vertices versus a finite16mm terminal cylinder. No triangle, hand wrap or actual Blender grip approval."}


def fit_thumb_opposition(positions, weights, bones, frame, index_fit):
    across, longitudinal, palm, _ = frame
    center = np.array(index_fit["diagnostic_cylinder_center_rest_m"])
    interval = index_fit["finite_axis_interval_m"]
    by_name = {bone["name"]: bone for bone in bones}

    def fingertip_ids(finger):
        tip = by_name[finger + "_03_r"]
        head = np.array(tip["head_world_review_m"])
        direction = np.array(tip["tail_world_review_m"]) - head
        fractions = (positions - head) @ direction / np.dot(direction, direction)
        return [index for index, row in enumerate(weights) if row.get(finger + "_03_r", 0) > .4 and fractions[index] > .35]

    index_ids = fingertip_ids("index")
    index_points, _ = skin.deform(positions[index_ids], [weights[index] for index in index_ids], bones, index_fit["best"]["commands"])
    index_distances = cylinder_distances(index_points, center, across, .008, interval)
    index_contact = index_points[int(np.argmin(np.abs(index_distances)))]
    index_radial = index_contact - center
    index_radial = normalize(index_radial - across * np.dot(index_radial, across))
    ids = [index for index, row in enumerate(weights) if sum(row.get("thumb_" + joint + "_r", 0) for joint in ("01", "02", "03")) > .5]
    thumb_tips = set(fingertip_ids("thumb"))
    distal = np.array([local for local, index in enumerate(ids) if index in thumb_tips])
    if not len(distal) or not index_ids:
        raise ValueError("Actual tip-pad geometry/weights selection is empty")
    candidates = []
    for axis_components in product((-1, 0, 1), repeat=3):
        if axis_components == (0, 0, 0):
            continue
        first_axis = normalize(across * axis_components[0] + longitudinal * axis_components[1] + palm * axis_components[2])
        for base in (15, 30, 45, 60):
            for second_axis_name, second_axis in (("across", across), ("longitudinal", longitudinal), ("palm", palm)):
                for middle in (-45, -30, -15, 0, 15, 30, 45, 60):
                    commands = [["thumb_01_r", first_axis.tolist(), base], ["thumb_02_r", second_axis.tolist(), middle], ["thumb_03_r", second_axis.tolist(), middle * .3]]
                    actual, _ = skin.deform(positions[ids], [weights[index] for index in ids], bones, commands)
                    distances = cylinder_distances(actual, center, across, .008, interval)
                    selected = int(distal[np.argmin(np.abs(distances[distal]))])
                    contact = float(distances[selected])
                    radial = actual[selected] - center
                    radial = normalize(radial - across * np.dot(radial, across))
                    opposite = float(np.dot(radial, index_radial))
                    penetration = float(np.sum(np.minimum(0, distances + .001) ** 2))
                    score = penetration * 80 + max(0, abs(contact) - .001) ** 2 + max(0, opposite + .5) ** 2 * .0001
                    score += (base * base + middle * middle) * 1e-11
                    candidates.append({"parameters": {"base_axis_components_in_anatomical_frame": axis_components, "base_deg": base, "second_axis": second_axis_name, "second_deg": middle},
                                       "commands": commands, "score": score, "distal_contact_distance_mm": contact * 1000,
                                       "maximum_surface_vertex_penetration_mm": max(0, -float(distances.min())) * 1000,
                                       "vertices_inside_over2mm": int(np.count_nonzero(distances < -.002)),
                                       "index_thumb_contact_radial_dot": opposite, "distal_contact_m": actual[selected].tolist()})
    candidates.sort(key=lambda row: row["score"])
    return {"finger": "thumb", "weighted_render_vertices": len(ids), "distal_render_vertices": len(distal),
            "assigned_terminal": "released_by_index_thumb", "diagnostic_cylinder_center_rest_m": center.tolist(),
            "radius_m": .008, "axis_rest": across.tolist(), "finite_axis_interval_m": interval,
            "index_contact_m": index_contact.tolist(), "best": candidates[0], "alternatives": candidates[1:8],
            "method": "Expanded anatomical-frame thumb opposition search. Pads require actual03bone weight>0.4 and tip segment fraction>0.35, not thumb02side contact. Finite terminal cylinder/opposite index-thumb radial contacts are preliminary only; actual triangle/pad enclosure remains required."}


def analyze(output):
    if rig.record(SOURCE)["sha256"] != SOURCE_SHA or rig.record(WEAPON)["sha256"] != WEAPON_SHA:
        raise ValueError("Approved body or existing independent weapon changed")
    approval = SOURCE.with_name("root_stage_review.json")
    reviewed = json.loads(approval.read_text(encoding="utf-8"))
    if not reviewed.get("local_deformation_diagnostic_approved") or reviewed["candidate_blend_sha256"] != SOURCE_SHA:
        raise ValueError("Missing actual root local-foot stage review")
    report_path = rig.BRANCH / "rig_transfer_candidate_03/transfer_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mapping = json.loads(Path(report["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = report["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = texture.read_glb(rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    across, longitudinal, palm, center = hand_frame(bones)
    fingers = [fit_finger(name, positions, weights, bones, across, longitudinal, palm, center) for name in ("index", "middle", "ring", "pinky", "thumb")]
    fingers[-1] = fit_thumb_opposition(positions, weights, bones, (across, longitudinal, palm, center), fingers[0])
    units_path = ROOT / "Content/Data/Units.json"
    units = json.loads(units_path.read_text(encoding="utf-8-sig"))
    unit = next(row for row in units if row["VisualKey"] == "Unit_StoneSlinger")
    terminal_root = center + longitudinal * .008 + palm * .035
    basis = np.column_stack((-palm, across, -longitudinal))
    paths = terminal_paths()
    all_digit_bones = [bone for bone in bones if bone["name"].endswith("_r") and bone["name"].startswith(("thumb", "index", "middle", "ring", "pinky"))]
    result = {"asset_id": "Unit_StoneSlinger", "status": "pure_hand_weight_and_terminal_fit_diagnostic_not_actual_grip",
              "source": rig.record(SOURCE), "root_review": rig.record(approval), "weapon": rig.record(WEAPON),
              "weapon_interface": rig.record(WEAPON.with_name("interface.json")), "actual_rig_transfer_report": rig.record(report_path),
              "script": rig.record(Path(__file__)), "body_height_cm": 142.5,
              "hand_r_actual_Blender_side": "negativeY; retain actual chain, UE physical conversion later is(X,-Y,Z), no name swapping",
              "actual_bone_count": len(bones), "right_digit_bones": all_digit_bones,
              "hand_frame": {"across": across.tolist(), "longitudinal": longitudinal.tolist(), "palm": palm.tolist(), "center_m": center.tolist()},
              "independent_digit_candidates": fingers,
              "initial_grip_commands": [command for row in fingers for command in row["best"]["commands"]],
              "terminal_root_rest_m": terminal_root.tolist(), "weapon_basis_columns": basis.tolist(),
              "terminal_path_proposal_local_m": {name: points.tolist() for name, points in paths.items()},
              "terminal_path_lengths_m": {name: float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()) for name, points in paths.items()},
              "actual_control_changes_required": ["Reuse four existing weapon meshes and three materials, keep independent stone and pouch", "Retained terminal under middle/ring/pinky stays attached; release terminal is pinched by index/thumb and must be freed independently", "Reuse each88vertex11ring cord topology; create explicit separate retention/release controls in a new derivative only", "Existing Draw does not release a terminal; no claim original static or Draw-only weapon is attack-ready"],
              "timing": {"data_source": rig.record(units_path), "AttackInterval_seconds": unit["AttackInterval"], "AttackWindup_seconds": unit["AttackWindup"],
                         "ProjectileSpeed_cm_per_second": unit["ProjectileSpeed"], "fps": 60,
                         "release_frame_one_based": int(round(unit["AttackWindup"] * 60)) + 1,
                         "cycle_end_frame_one_based": int(round(unit["AttackInterval"] * 60)) + 1,
                         "server_source": "Source/CivWar/Sim/Simulation.cpp:578,727,827,854,874",
                         "authority": "Windup expiry records Released and creates the projectile. Damage occurs later in StepProjectiles, not at release or in animation notifies.",
                         "speed_modifier": "UnitAttackInterval scales cycle by AttackSpeedMul/buff; AttackWindup remains0.45s. Do not globally time-scale the release marker.",
                         "first_batch_attack_clip": False},
              "first_batch_scope": "Actual grip candidate, retained/free terminal diagnostic, wrist/elbow, idle and two conservative move phases only. Numeric/visual failure remains diagnostic, no full gait or attack approval.",
              "blender_started": False, "body_or_weapon_modified": False, "grip_approved": False, "animation_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    rig.save(output / "grip_preparation.json", result)
    print(json.dumps({"fingers": [{"name": row["finger"], **row["best"]} for row in fingers], "timing": result["timing"], "path_lengths": result["terminal_path_lengths_m"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.output).resolve())
