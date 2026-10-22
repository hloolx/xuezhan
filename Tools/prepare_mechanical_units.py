"""Build measured plans for the three arrived mechanical units.

File-only stage `plan` records real source partitions and dimensions. Stage
`specs` requires actual prepared part manifests; it does not start Blender/UE.
Measurements below are in normalized Blender centimetres from the source
orthographic projections. No runtime mapping is activated by this tool.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Tools/Blender"))
import prepare_era_parts as parts
from era_vehicle_motion import Motion, capsule_frame, capsule_length

RUN = ROOT/"RawAssets/Art/Tripo_v01/reviews/MechanicalUnitsPrepare_01"


def inverse_point(point, basis):
    rotation, scale, centre = basis
    return ((np.asarray(point)/100/scale+centre)@rotation).tolist()


def region(basis, low, high, segment=None, radius=None):
    corners = [inverse_point([x, y, z], basis)
               for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    result = {"minimum": np.min(corners, axis=0).tolist(), "maximum": np.max(corners, axis=0).tolist()}
    if segment:
        result.update(segment=[inverse_point(point, basis) for point in segment], radius=radius/100/basis[1])
    return result


def make_entry(entry):
    geometry = parts.common.source_geometry(entry)
    basis = parts.common.normalized_basis(entry, geometry["vertices"])
    entry = deepcopy(entry)
    entry.update(revision="measured_rigid_parts_02", remainder_part="hull", parts=[], selections=[])
    profile = {"part_bones": {}, "joint_origins_cm": {"root": [0, 0, 0]},
               "bone_parents": {}, "ground_bones": []}

    def part(name, pivot, low=None, high=None, segment=None, radius=None, exclude=None, parent="hull"):
        row = {"id": name, "pivot_gltf": inverse_point(pivot, basis)}
        if name != "hull":
            row["parent_part"] = parent
            profile["bone_parents"][name] = parent
        entry["parts"].append(row)
        profile["part_bones"][name] = name
        profile["joint_origins_cm"][name] = pivot
        if low:
            selection = {"part": name, "regions": [region(basis, low, high, segment, radius)]}
            if exclude:
                selection["exclude_regions"] = exclude
            entry["selections"].append(selection)

    part("hull", [0, 0, 0])
    if entry["asset_id"] == "Unit_ArmoredCar":
        profile.update(profile="wheeled_unit", attack_style="Burst", wheels=[])
        for axle, x in (("F", 90.5), ("R", -90.)):
            for side, y in (("L", 71.), ("R", -71.)):
                name = "wheel_"+axle+side
                lo, hi = sorted((np.sign(y)*58, np.sign(y)*90))
                part(name, [x, y, 40.5], [x-43, lo, -1], [x+43, hi, 82],
                     [[x, lo, 40.5], [x, hi, 40.5]], 41.2)
                profile["wheels"].append({"bone": name, "radius_cm": 40.5, "axis": [0, 1, 0]})
                profile["ground_bones"].append(name)
        part("turret", [-25, 0, 145])
        part("gun", [20, 0, 166], [20, -10, 157], [90, 10, 177], parent="turret")
        entry["selections"].append({"part": "turret", "regions": [region(basis, [-90, -65, 145], [90, 65, 200])]})
        profile["recoil"] = [{"bone": "gun", "dependent_bones": ["muzzle"], "distance_cm": 2, "recovery": .18}]
        entry["slice_planes"] = [[1, 0, 0, inverse_point([0, y, 0], basis)[0]] for y in (-58, 58)]
    elif entry["asset_id"] == "Unit_MainTank":
        profile.update(profile="tracked_unit", attack_style="Cannon", tracks=[], track_objects={},
                       rigid_tread_objects=[])
        entry["authored_treads"] = []
        # Original wheels and fused side skirts stay intact. New closed links
        # provide actual drive motion without shearing the source armour.
        for side, y in (("L", 87.), ("R", -87.)):
            track_name = "track_"+side
            track = {"half_straight_cm": 126.5, "radius_cm": 35, "lateral_cm": y,
                     "centre_height_cm": 37, "forward_cm": -9.5, "bones": []}
            length = capsule_length(1.265, .35)
            for index in range(40):
                name = f"tread_{side}_{index:02}"
                profile["joint_origins_cm"][name] = (capsule_frame(
                    length*index/40, 1.265, .35, y/100, .37, -.095)[:3, 3]*100).tolist()
                profile["bone_parents"][name] = "hull"
                track["bones"].append(name)
            profile["track_objects"][track_name] = len(profile["tracks"])
            profile["rigid_tread_objects"].append(track_name)
            profile["tracks"].append(track)
            entry["authored_treads"].append({**deepcopy(track), "id": track_name, "parent_part": "hull",
                "width_cm": 41, "thickness_cm": 4, "link_fraction": .90,
                "reason": "Closed moving links over actual fused Tripo track/side-skirt surface; original source retained"})
        part("turret", [-42, 0, 102])
        part("gun", [52, 0, 123], [52, -15, 109], [185, 15, 138], parent="turret")
        entry["selections"].append({"part": "turret", "regions": [region(basis, [-150, -90, 101], [185, 90, 180])]})
        profile["recoil"] = [{"bone": "gun", "dependent_bones": ["muzzle"], "distance_cm": 10, "recovery": .38}]
    else:
        profile.update(profile="biped_mech", attack_style="Cannon", legs=[], move_cycle=.9,
                       stance_fraction=.6, foot_clearance_cm=18)
        for side, y in (("L", 64.), ("R", -64.)):
            lo, hi = (20, 130) if y > 0 else (-130, -20)
            upper, lower, foot = "upper_"+side, "lower_"+side, "foot_"+side
            part(upper, [-22, y, 157], [-100, lo, 115], [70, hi, 174])
            part(lower, [4, y, 115], [-100, lo, 40], [70, hi, 115], parent=upper)
            part(foot, [-34, y, 40], [-110, lo, -1], [80, hi, 40], parent=lower)
            profile["legs"].append({"upper": upper, "lower": lower, "foot": foot})
            weapon = "weapon_"+side
            low_y, high_y = (80, 130) if y > 0 else (-130, -80)
            part(weapon, [5, np.sign(y)*105, 210], [-40, low_y, 175], [85, high_y, 246])
        profile["recoil"] = [
            {"bone": "weapon_L", "dependent_bones": ["muzzle"], "distance_cm": 5, "recovery": .3},
            {"bone": "weapon_R", "dependent_bones": ["muzzle_R"], "distance_cm": 5, "recovery": .3}]
        # Exact planes through measured joints avoid jagged whole-face hinges.
        entry["slice_planes"] = [[0, 1, 0, inverse_point([0, 0, z], basis)[1]] for z in (40, 115, 174)]
    partitioned, labels = parts.inspect(entry)
    points = parts.common.normalized_point(partitioned["vertices"], basis)*100
    triangle = points[partitioned["faces"]]
    # Muzzles are the centre of actual forward-most source vertices belonging
    # to each independent gun. Their names survive as true skeleton bones.
    for gun, muzzle in (("weapon_L", "muzzle"), ("weapon_R", "muzzle_R")) if entry["asset_id"] == "Unit_Mech" else (("gun", "muzzle"),):
        selected = triangle[labels == gun].reshape(-1, 3)
        end = selected[selected[:, 0] > selected[:, 0].max()-1]
        profile["joint_origins_cm"][muzzle] = end.mean(0).tolist()
        profile["bone_parents"][muzzle] = gun
    definition = next(row for row in parts.static.read(ROOT/"Content/Data/Units.json") if row["VisualKey"] == entry["asset_id"])
    profile.update(asset_id=entry["asset_id"], reference_move_speed_cm_s=definition["MoveSpeed"],
                   contact_time=definition["AttackWindup"], attack_interval=definition["AttackInterval"],
                   muzzle_bone="muzzle", measurement_source=geometry["inspection"]["source"],
                   planned_part_triangles={str(name): int(np.count_nonzero(labels == name)) for name in set(labels)})
    motion = Motion(profile)
    for clip, duration in motion.durations.items():
        for time in np.linspace(0, duration, 121):
            motion.pose(clip, time)
    profile["offline_kinematics"] = {"sampled_poses": 605, "unreachable_ik_targets": 0,
                                     "note": "Numerical feasibility only; actual skinned geometry pending leased Blender"}
    return entry, profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "specs"), default="plan")
    parser.add_argument("--candidate", default="candidate_01")
    args = parser.parse_args()
    plan = parts.static.read(RUN/"source_plan.json")
    if args.stage == "plan":
        entries = []
        for entry in plan["entries"]:
            actual, profile = make_entry(entry)
            entries.append(actual)
            parts.static.write(RUN/entry["asset_id"]/"motion_measurements.json", profile)
        parts.static.write(RUN/"parts_plan.json", {**plan, "entries": entries})
    else:
        plan = parts.static.read(RUN/"parts_plan.json")
        dispatch = []
        for entry in plan["entries"]:
            folder = parts.destination(plan, entry)
            actual = parts.static.read(folder/"parts_manifest.json")
            profile = parts.static.read(RUN/entry["asset_id"]/"motion_measurements.json")
            if actual["asset_id"] != profile["asset_id"]:
                raise ValueError("Prepared vehicle identity mismatch")
            output = parts.static.ROOT/plan["output_root"]/entry["asset_id"]/args.candidate
            profile.update(scene=actual["blend"]["path"], scene_sha256=actual["blend"]["sha256"],
                           materials=actual["materials"], output=str(output))
            path = RUN/entry["asset_id"]/(args.candidate+"_spec.json")
            parts.static.write(path, profile)
            dispatch.append({"asset_id": entry["asset_id"], "spec": str(path), "output": str(output)})
        parts.static.write(RUN/(args.candidate+"_dispatch.json"), {"entries": dispatch})


if __name__ == "__main__":
    main()
