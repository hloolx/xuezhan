"""Measure the frozen parent-only Mammoth and record a non-executable gait contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tools/Blender"))
import prepare_mammoth_rig_transfer as transfer


BRANCH = transfer.BRANCH
MODEL = BRANCH / "rig_transfer_parent_02/Mount_Mammoth_parent_only.glb"
MODEL_SHA = "65c1f2291b1917cafa97ec3b9be3181c7ca9f51a8360330f66e1762ca867effb"
PREPARATION = MODEL.parent / "preparation.json"
PARENT_REVIEW = MODEL.parent / "actual_diagnostic_01/visual_review.json"
FOLLOWER_REVIEW = BRANCH / "rig_follower_visual_01/actual_visual_02/stage_review.json"
LIMBS = {
    "front_positive_y": {"region": "x1_y1", "signs": [1, 1], "support_parent": "bone_11",
                         "chain": ["tripo::0_Left_Limb_0", "tripo::0_Left_Limb_1", "tripo::0_Left_Limb_2"]},
    "front_negative_y": {"region": "x1_y-1", "signs": [1, -1], "support_parent": "tripo::Spine_4",
                         "chain": ["tripo::1_Right_Limb_0", "tripo::1_Right_Limb_1", "tripo::1_Right_Limb_2"]},
    "hind_positive_y": {"region": "x-1_y1", "signs": [-1, 1], "support_parent": "bone_21",
                        "chain": ["tripo::1_Left_Limb_0", "bone_23", "bone_24", "bone_25"]},
    "hind_negative_y": {"region": "x-1_y-1", "signs": [-1, -1], "support_parent": "bone_21",
                        "chain": ["tripo::1_Left_Limb_1", "tripo::1_Left_Limb_2", "tripo::1_Left_Limb_3"]},
}
CODE_INPUTS = [
    "Content/Data/Units.json", "Content/Data/Rules.json",
    "Source/CivWar/Sim/Simulation.cpp", "Source/CivWar/Sim/SimState.h",
    "Source/CivWar/Sim/SimTypes.h", "Source/CivWar/Net/CWNetTypes.h",
    "Source/CivWar/Net/CWBattleReplicator.cpp", "Source/CivWar/Game/CWGameMode.h",
    "Source/CivWar/Game/CWGameMode.cpp", "Source/CivWar/View/CWModels.cpp",
    "Source/CivWar/View/CWUnitVisual.cpp", "Source/CivWar/View/CWSkeletalUnitPresentation.cpp",
    "RawAssets/Art/Tripo_v01/prompts/Mount_Mammoth/brief.json",
    "RawAssets/Art/Tripo_v01/prompts/Unit_BeastRider/brief.json",
]


def record(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def checked_output(path):
    path = Path(path).resolve()
    if path.parent != BRANCH.resolve() or path.name != "gait_plan_01" or path.exists():
        raise ValueError("Only the fresh owned gait_plan_01 directory may be created")
    return path


def select_unit(units):
    matches = [(index, unit) for index, unit in enumerate(units) if unit.get("Name") == "BeastRider"]
    if len(matches) != 1 or matches[0][1].get("VisualKey") != "Unit_BeastRider":
        raise ValueError("Require exactly one actual BeastRider with its matching visual key")
    index, unit = matches[0]
    if unit["MoveSpeed"] <= 0 or not 0 <= unit["AttackWindup"] <= unit["AttackInterval"]:
        raise ValueError("Invalid actual gameplay timing or speed")
    return index, unit


def measure_foot(physical, indices, signs, sole_band_m=0.008):
    selected = physical[np.asarray(indices, dtype=int)]
    if not len(selected) or not np.all(selected[:, 0] * signs[0] > 0) or not np.all(selected[:, 1] * signs[1] > 0.1):
        raise ValueError("Frozen foot region disagrees with physical X/Y anatomy")
    if not np.all(selected[:, 2] < 0.12):
        raise ValueError("Frozen foot region contains non-foot-height samples")
    minimum = float(selected[:, 2].min())
    mask = selected[:, 2] <= minimum + sole_band_m
    sole = np.unique(selected[mask], axis=0)
    return {"source_render_indices": list(map(int, indices)), "render_count": len(selected),
            "unique_position_count": len(np.unique(selected, axis=0)),
            "bounds_m": {"min": selected.min(axis=0).tolist(), "max": selected.max(axis=0).tolist()},
            "sole_band_above_own_minimum_m": sole_band_m,
            "sole_render_indices": np.asarray(indices, dtype=int)[mask].tolist(),
            "sole_unique_position_count": len(sole), "sole_minimum_world_z_m": minimum,
            "sole_centroid_m": sole.mean(axis=0).tolist(),
            "sole_xy_extents_m": np.ptp(sole[:, :2], axis=0).tolist(),
            "not_semantic_or_dynamic_contact_approved": True}


def local_axis(world_matrix):
    basis = transfer.BASIS @ np.asarray(world_matrix)[:3, :3]
    lengths = np.linalg.norm(basis, axis=0)
    if np.any(lengths <= 0):
        raise ValueError("Invalid bone basis")
    rotation = basis / lengths
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5) or np.linalg.det(rotation) <= 0:
        raise ValueError("Do not infer local bend axes through shear or mirrored scale")
    axis = rotation.T @ np.array([0.0, 1.0, 0.0])
    return {"world_sagittal_bend_axis_blender": [0, 1, 0], "corresponding_local_axis": axis.tolist(),
            "world_local_axes_columns_blender": rotation.tolist(), "world_scale": lengths.tolist(),
            "axis_is_geometric_proposal_not_anatomical_limit_approval": True}


def stride_contract(speed_cm_s, hip, sole, cycle_s=0.6, duty=0.65, measured_angle_deg=8.0):
    if speed_cm_s <= 0 or cycle_s <= 0 or not 0 < duty < 1:
        raise ValueError("Invalid speed/cycle/duty")
    height = float(np.asarray(hip)[2] - np.asarray(sole)[2])
    if height <= 0:
        raise ValueError("Leg pivot must be above its foot")
    speed = speed_cm_s / 100.0
    travel = speed * cycle_s
    stance = travel * duty
    span = 2 * height * math.sin(math.radians(measured_angle_deg))
    ratio = stance / (2 * height)
    angle = math.degrees(math.asin(ratio)) if ratio <= 1 else None
    return {"reference_speed_cm_s": speed_cm_s, "proposed_cycle_seconds": cycle_s,
            "proposed_stance_fraction": duty, "virtual_world_travel_per_cycle_cm": travel * 100,
            "required_local_foot_stance_sweep_cm": stance * 100,
            "pivot_to_measured_sole_vertical_m": height,
            "illustrative_rigid_leg_plus_minus_8_degree_sweep_cm": span * 100,
            "matching_cycle_if_only_that_rigid_sweep_seconds": span / (speed * duty),
            "corresponding_cycles_per_second": speed * duty / span,
            "illustrative_angle_for_proposed_stance_sweep_degrees": angle,
            "not_a_solved_ground_contact_or_multijoint_reach_test": True,
            "negative_8_degree_or_full_cycle_not_previously_tested": True}


def source_location(relative, needle):
    lines = (ROOT / relative).read_text(encoding="utf-8-sig").splitlines()
    matches = [index + 1 for index, line in enumerate(lines) if needle in line]
    if not matches:
        raise ValueError("Required source semantics missing: " + needle)
    return {"path": str(ROOT / relative), "lines": matches, "needle": needle}


def gameplay_contract():
    index, unit = select_unit(read_json(ROOT / "Content/Data/Units.json"))
    rules = read_json(ROOT / "Content/Data/Rules.json")[0]
    mode = (ROOT / "Source/CivWar/Game/CWGameMode.h").read_text(encoding="utf-8-sig")
    fixed = re.search(r"FixedStep\s*=\s*([0-9.]+)f", mode)
    if not fixed:
        raise ValueError("Actual fixed simulation step not found")
    net = (ROOT / "Source/CivWar/Net/CWNetTypes.h").read_text(encoding="utf-8-sig")
    net_unit = net.split("struct FCWUnitNetItem", 1)[1].split("struct FCWUnitNetArray", 1)[0]
    return {"actual_data_index": index, "actual_unit": unit, "simulation_step_seconds": float(fixed.group(1)),
            "speed_semantics": "MoveSpeed * actual Unit.SpeedMul; ally/enemy/base/hold constraints can reduce real displacement to zero",
            "nominal_recovery_budget_seconds": unit["AttackInterval"] - unit["AttackWindup"],
            "attack_interval_semantics": "AttackInterval / max(AttackSpeedMul * active BuffAttackSpeed factor, 0.1); windup remains actual data AttackWindup",
            "nominal_contact_not_rounded_to_keyframe_damage": True,
            "release_semantics": "Authority decrements windup on fixed simulation steps, validates target, marks Released then queues melee; both teams act before pending hits are applied",
            "charge": {"multiplier": unit["ChargeMultiplier"], "recharge_continuous_walk_seconds": rules["ChargeRechargeTime"],
                       "charge_variant_replicated": "ChargeReady" in net_unit or "ChargeVariant" in net_unit,
                       "blocker": "Do not infer charge versus normal strike from AttackSeq or client distance. ChargeReady is consumed at authoritative release."},
            "retreat_nominal_cm_s": unit["MoveSpeed"] * rules["RetreatSpeedFactor"],
            "logical_radius_cm": unit["Radius"], "lane_spacing_cm": rules["RowSpacing"],
            "time_base": "AttackStartServerTime/AttackEndServerTime use snapshot ServerWorldTime minus Accumulator, with stable same-attack timestamps. Presentation samples ServerWorldTime, not stale MatchTime.",
            "cancel_late_initial": "Use replicated Outcome; Cancelled stops attack/contact. Initial or late observations seek elapsed phase and never replay contact. Requires BeastRider-specific actual verification, not inherited StoneAxe approval.",
            "client_notify_causes_damage": False,
            "source_locations": [
                source_location("Source/CivWar/Sim/Simulation.cpp", "const float Speed = D.MoveSpeed * U.SpeedMul"),
                source_location("Source/CivWar/Sim/Simulation.cpp", "U.AttackStartSimTime = SimTime"),
                source_location("Source/CivWar/Sim/Simulation.cpp", "U.Windup = D.AttackWindup"),
                source_location("Source/CivWar/Sim/Simulation.cpp", "RecordAttackEnd(U, AttackOutcome::Released"),
                source_location("Source/CivWar/Sim/Simulation.cpp", "if (U.ChargeReady && D.ChargeMultiplier > 1.f)"),
                source_location("Source/CivWar/Game/CWGameMode.cpp", "ServerTime - Accumulator"),
                source_location("Source/CivWar/Net/CWBattleReplicator.cpp", "const float QAttackStartServerTime"),
                source_location("Source/CivWar/View/CWUnitVisual.cpp", "const float Speed = FMath::Abs(VisualX - PrevX)"),
                source_location("Source/CivWar/View/CWSkeletalUnitPresentation.cpp", "Dt * Speed / ReferenceMoveSpeed"),
            ]}


def analyze(output):
    output = checked_output(output)
    if record(MODEL)["sha256"] != MODEL_SHA:
        raise ValueError("Reject changed or follower source; require exact parent-only model")
    document, binary = transfer.read_container(MODEL)
    if len(document["skins"]) != 1 or len(document["skins"][0]["joints"]) != 33 or document.get("animations"):
        raise ValueError("Require frozen 33-bone parent-only rig without authored actions")
    worlds, parents = transfer.world_matrices(document)
    named = {node.get("name"): index for index, node in enumerate(document["nodes"])}
    if parents[named["tripo::1_Left_Limb_1"]] != named["bone_21"]:
        raise ValueError("Parent-only hind-leg correction is absent")
    arrays = transfer.source_arrays(document, binary)
    physical = arrays["POSITION"] @ transfer.BASIS.T
    prep = read_json(PREPARATION)
    gameplay = gameplay_contract()
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    legs = {}
    for label, definition in LIMBS.items():
        foot = measure_foot(physical, prep["regions"][definition["region"]], definition["signs"])
        chain = []
        previous = named[definition["support_parent"]]
        for name in definition["chain"]:
            node = named[name]
            if parents[node] != previous:
                raise ValueError("Unexpected actual leg chain: " + label)
            head = transfer.BASIS @ worlds[node][:3, 3]
            if head[0] * definition["signs"][0] <= 0 or head[1] * definition["signs"][1] <= 0.1:
                raise ValueError("Bone names disagree with measured physical leg quadrant")
            chain.append({"bone": name, "parent": document["nodes"][parents[node]]["name"],
                          "head_blender_m": head.tolist(), "axis": local_axis(worlds[node]),
                          "children": [document["nodes"][child]["name"] for child in document["nodes"][node].get("children", [])]})
            previous = node
        heads = np.array([row["head_blender_m"] for row in chain])
        influence = np.zeros(len(joint_names))
        for render in foot["source_render_indices"]:
            np.add.at(influence, arrays["JOINTS_0"][render], arrays["WEIGHTS_0"][render])
        influence /= foot["render_count"]
        legs[label] = {"anatomy_source": "Actual spatial quadrant, descending chain heads and preserved foot region; not Left/Right names",
                       "support_parent": definition["support_parent"], "chain": chain,
                       "head_to_head_segment_lengths_m": np.linalg.norm(np.diff(heads, axis=0), axis=1).tolist(),
                       "terminal_head_to_sole_centroid_m": float(np.linalg.norm(heads[-1] - foot["sole_centroid_m"])),
                       "foot": foot,
                       "mean_foot_weights": {joint_names[index]: float(weight) for index, weight in enumerate(influence) if weight > 0},
                       "stride_planning": stride_contract(gameplay["actual_unit"]["MoveSpeed"], heads[0], foot["sole_centroid_m"])}
    rider = read_json(ROOT / "RawAssets/Art/Tripo_v01/prompts/Unit_BeastRider/brief.json")
    anchors = rider["animation_contract"]["anchors"]
    existing_anchors = [name for name in anchors if name in named]
    source_files = [MODEL, PREPARATION, PARENT_REVIEW, FOLLOWER_REVIEW, Path(__file__),
                    ROOT / "Tools/Blender/prepare_mammoth_rig_transfer.py"] + [ROOT / path for path in CODE_INPUTS]
    frozen = [record(path) for path in source_files]
    contract = {
        "asset_id": "Mount_Mammoth", "status": "planning_only_parent33_body_idle_move_not_authored_or_approved",
        "source": frozen[0], "frozen_inputs": frozen, "coordinate_basis": {"model": "glTF metres", "measurement": "Blender +X forward +Z up metres", "gltf_to_blender": transfer.BASIS.tolist(), "future_UE_mapping": "Blender (x,-y,z)*100; must verify actual import; both teams rotate, never negative scale"},
        "counts": {"joints": len(joint_names), "render_vertices": len(physical), "triangles": len(arrays["indices"]), "new_bones": 0, "new_actions": 0},
        "bounds_cm": {"min": (physical.min(axis=0)*100).tolist(), "max": (physical.max(axis=0)*100).tolist(), "size": (np.ptp(physical, axis=0)*100).tolist()},
        "gameplay": gameplay, "legs": legs,
        "saddle_and_rider": {"required_anchors": anchors, "existing_named_anchors_in_mount": existing_anchors,
                             "mount_only_anchors_to_measure": ["saddle_seat", "seat_hand_l", "rider_foot_l", "rider_foot_r"],
                             "spine_reference_heads_m": {name: (transfer.BASIS @ worlds[named[name]][:3, 3]).tolist() for name in ("tripo::Spine_1", "tripo::Spine_2", "tripo::Spine_3")},
                             "no_spine_head_is_an_approved_seat": True,
                             "rider_generated_or_rigged": False, "attachment_transform_approved": False,
                             "contract": ["Measure rigid seat and hand/foot support from actual saddle surface after semantic review; do not guess at body bounds centre", "Rider pelvis follows one seat parent; world actor travel is applied once only; independent human and quadruped skeletons", "Right-hand spear has one hand_r weapon_r parent and aligns grip_r; left hand targets seat_hand_l; no attachment cycle", "Legs must clear shoulders/blanket, spear must clear head/trunk/tusks in both yaw directions; no mirrored weapon", "Actual rider mass pose and seat angular/vertical acceleration require finite motion inspection; body-only diagnostic is not mounted approval"]},
        "limited_clip_proposal_not_authored": {
            "Idle": {"duration_seconds": 1.6, "first_gate": "Rest hold and four actual sole contacts; optional <=1degree head/spine breathing is a later unapproved finite test, not an applied edit", "root_motion": False},
            "Move": {"duration_seconds": 0.6, "fps_proposal": 60, "reference_speed_cm_s": gameplay["actual_unit"]["MoveSpeed"], "stance_fraction_proposal": 0.65,
                     "phase_offsets_proposal": {"hind_positive_y": 0.0, "front_positive_y": 0.25, "hind_negative_y": 0.5, "front_negative_y": 0.75},
                     "phase_order_not_anatomical_validation": True, "nominal_virtual_travel_cm": gameplay["actual_unit"]["MoveSpeed"] * 0.6,
                     "foot_lift_cap_cm_proposal": 5, "swing_and_stance_trajectory": "Solve separate actual chains and preserve bone lengths. Stance local X counter-travels the actual actor; do not rigidly rotate whole legs and assume grounding.",
                     "root_motion": False, "bone_angles_not_authored": True,
                     "runtime_clock": "Phase increment follows measured actor displacement/reference travel, freezes when blocked, seeks/reset explicitly on teleport; not nominal speed or UnitState alone"},
            "excluded": ["Attack/charge", "Hit", "Death", "rider animation", "buckle repair", "tail weight edit", "new paid action"]},
        "future_validation_gates_not_executed": [
            {"gate": "source_rest", "requirement": "Exact POSITION/NORMAL/UV/index/23split/3PBR/33rest/IB/source weights; source and evaluated full rest <=3micrometres; no follower payload"},
            {"gate": "actual_contact", "requirement": "Record all four immutable sole sample sets before motion; global model minimum Z=0 is not four-foot grounding. No runtime per-foot height hacks."},
            {"gate": "stance_sliding", "requirement": "At each <=1/120s diagnostic sample, apply explicit virtual actor trajectory and measure each stance sole centroid world drift and penetration; report max/p95, transitions separately. Proposed <=5mm stance centroid drift and <=2mm new penetration require root acceptance, not existing passed evidence."},
            {"gate": "support_and_swing", "requirement": "Actual skin contact probes, not bone heads: no new non-foot floor penetration, no lifted foot declared supporting, body COM proxy inside measured support polygon where intended; proxy is not physical mass simulation."},
            {"gate": "whole_surface", "requirement": "Full surface temporal comparison, no new flips/degenerate faces; explicitly compare frame/cloth crossings to source baseline. Preserve unresolved baseline violations and distinguish every new intersection."},
            {"gate": "locomotion_clock", "requirement": "Check base220cm/s and retreat176cm/s, variable actual SpeedMul/displacement, stop/start, blocking, no teleport-distance pumping; root displacement zero in clip, both teams positive scale."},
            {"gate": "delivery", "requirement": "Only after finite DCC approval: preserve exact authored normals, bake actual actions, GLB/FBX world-pose and skin roundtrip, fresh UE every-frame position/scale/skin, then actual gameplay and rider assembly. Not executed by this planning tool."},
        ],
        "blockers": [
            "Front buckles on current33bone source still deform non-rigidly; shoulder8degree actual rigid-fit residuals6.242mm/4.963mm. Gait planning is not accessory acceptance.",
            "Rejected35bone follower created12 real new frame-cloth crossings;7 source-existing pairs remain distinct. Never apply that candidate.",
            "12 existing-anchor8cm candidates,4 bounded12cm comparisons and one follower policy have closed failure evidence. This exhausts authorized trials, not every conceivable method; no further buckle search authorized.",
            "Actual source hind chains have unequal joint counts/heights; do not mirror transforms or force symmetric knees.",
            "Tail bone32 weakly influences240 negative-Y hind-foot render vertices; tail10degree moved those probes up to0.2367mm. Tail stays at rest for first body proposal, weights unchanged.",
            "No generated rider, validated seat/hand/foot socket, full gait, actual UE mount import or mounted battle timing evidence exists.",
            "Model width114.13cm exceeds85cm lane centre spacing and model length232.47cm exceeds120cm logical diameter; neighbouring occupancy and spear/tusk apparent reach require actual game camera review, not authority radius edits.",
            "Original normal-map914 negative samples and7 source frame-cloth contacts remain provenance risks, not waived by this plan.",
        ],
        "execution": {"pure_python_numeric_only": True, "Blender_runs": 0, "UE_runs": 0, "paid_calls": 0, "model_writes": 0, "actions_authored": 0, "heavy_lease_requested": False},
        "body_gait_approved": False, "buckle_approved": False, "rider_approved": False, "production_approved": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    save(output / "contract.json", contract)
    summary = {"status": contract["status"], "contract": record(output / "contract.json"), "source": record(MODEL),
               "base_speed_cm_s": gameplay["actual_unit"]["MoveSpeed"], "attack_contact_seconds": gameplay["actual_unit"]["AttackWindup"],
               "base_attack_interval_seconds": gameplay["actual_unit"]["AttackInterval"], "charge_variant_replicated": gameplay["charge"]["charge_variant_replicated"],
               "actual_feet": {label: {"sole_minimum_z_cm": value["foot"]["sole_minimum_world_z_m"]*100, "chain_joints": len(value["chain"]), "rigid8degree_sweep_cm": value["stride_planning"]["illustrative_rigid_leg_plus_minus_8_degree_sweep_cm"], "target_stance_sweep_cm": value["stride_planning"]["required_local_foot_stance_sweep_cm"]} for label, value in legs.items()},
               "models_or_actions_written": 0, "approved": False, "next": "Root reviews only this measured contract. Any actual finite DCC motion requires a separate frozen spec and heavy lease. Buckle/rider blockers remain; no more rejected-follower iterations."}
    save(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output)


if __name__ == "__main__":
    main()
