"""Refresh preparation tasks from real gameplay rows and arrived canonical GLBs.

This is a file-only inventory/dispatch step. Missing assets have no invented
source/import paths, and this never writes runtime or Cook configuration.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mechanical_static_inspect", ROOT/"Tools/Blender/prepare_era_asset.py")
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)
PROFILES = {
    "Turret_ArrowTower": ("archer_platform", ["platform", "Crew_Archer", "bow_limbs", "bow_string", "loaded_arrow", "muzzle"]),
    "Turret_Ballista": ("ballista", ["frame", "arm_left", "arm_right", "string", "bolt", "muzzle"]),
    "Turret_MachineGun": ("machinegun", ["fixed_base", "gun_mount", "bolt", "muzzle"]),
    "Turret_Cannon": ("cannon", ["fixed_base", "gun_cradle", "barrel_recoil", "muzzle"]),
    "Turret_Autocannon": ("autocannon", ["fixed_base", "gun_mount", "barrel_left", "barrel_right", "muzzle"]),
    "Turret_MissileBattery": ("missile_battery", ["fixed_base", "launcher", "loaded_missile", "muzzle"]),
    "Turret_LaserTower": ("laser_emitter", ["fixed_base", "emitter", "emission_pulse_material", "muzzle"]),
    "Turret_IonCannon": ("ion_emitter", ["fixed_base", "gun_cradle", "emitter", "emission_pulse_material", "muzzle"]),
    "Unit_ArmoredCar": ("wheeled_unit", ["hull", "wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR", "turret", "gun", "muzzle"]),
    "Unit_MainTank": ("tracked_unit", ["hull", "track_L", "track_R", "road_wheels", "turret", "gun_recoil", "muzzle"]),
    "Unit_Mech": ("biped_mech", ["torso", "hip_L", "knee_L", "ankle_L", "foot_L",
                                "hip_R", "knee_R", "ankle_R", "foot_R", "weapon_L", "weapon_R", "muzzle_L", "muzzle_R"]),
}


def generate():
    rows = []
    for definition in static.read(ROOT/"Content/Data/Ages.json"):
        if definition["Index"] > 0:
            rows.append(("base", definition))
    for definition in static.read(ROOT/"Content/Data/Turrets.json"):
        if definition["Age"] > 0:
            rows.append(("turret", definition))
    for definition in static.read(ROOT/"Content/Data/Units.json"):
        if definition["VisualKey"] in PROFILES:
            rows.append(("mech" if definition["Name"] == "Mech" else "vehicle", definition))
    result = []
    for kind, definition in rows:
        key = definition["VisualKey"]
        source = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"/key/"web_v01_canonical/pbr.glb"
        brief_path = ROOT/"RawAssets/Art/Tripo_v01/prompts"/key/"brief.json"
        brief = static.read(brief_path) if brief_path.exists() else {}
        profile, parts = ("static_base", ["body", "turret_0", "turret_1", "turret_2", "gate"]) if kind == "base" else PROFILES[key]
        row = {"asset_id": key, "kind": kind, "age": definition.get("Age", definition.get("Index")),
               "profile": profile, "required_real_parts_or_anchors": parts,
               "status": "awaiting_canonical_pbr", "source": None,
               "design_subject": brief.get("subject"), "runtime_entry_written": False}
        if source.is_file():
            inspection = static.inspect({"asset_id": key, "kind": kind, "source": str(source)})
            row.update(source=inspection["source"], source_inspection=inspection,
                       status="source_ready_needs_measured_parts" if inspection["full_pbr"] and not inspection["errors"] else "source_incomplete")
        if kind == "base":
            row["normalization_intent"] = {"measure": "horizontal_max", "target_cm": 640,
                                            "yaw_degrees": "measure_from_actual_front"}
            row["anchor_method"] = "actual surface ray intersections across each of three usable platforms"
        else:
            row["authority"] = {"attack_interval": definition["AttackInterval"],
                                 "contact_time": definition.get("AttackWindup", 0),
                                 "projectile_speed": definition["ProjectileSpeed"],
                                 "client_damage_events": 0}
            if kind in {"vehicle", "mech"}:
                row["reference_move_speed"] = definition["MoveSpeed"]
                row["runtime_kind"] = "skeletal_unit"
                row["required_clips"] = ["Idle", "Move", "Attack", "Hit", "Death"]
                row["motion_contract"] = {
                    "root_motion": False, "rigid_parts_weighted_to_actual_bones": True,
                    "wheel_rotation": "v/r from measured wheel radius",
                    "tracks": "closed tread phase from actual distance; fixed hull is not a Move animation",
                    "legs": "measured hip/knee/ankle chain, foot support speed cancels actor velocity",
                    "attack": "actual gun recoil at AttackWindup, real muzzle bone; no damage from animation",
                    "death": "collapse or wreck pose, final hold >=0.35s, root translation remains zero"}
            else:
                row["runtime_kind"] = "mechanical_turret"
                row["motion_contract"] = "FireSeq samples t=0 release immediately, mechanism resets within AttackInterval"
        result.append(row)
    return {"scope": "all four later eras: four bases, eight turrets, three mechanical units",
            "tasks": result, "counts": {"total": len(result),
            "source_ready": sum(r["status"] == "source_ready_needs_measured_parts" for r in result),
            "awaiting_source": sum(r["source"] is None for r in result)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"RawAssets/Art/Tripo_v01/reviews/mechanical_prepare_20261020/all_eras_plan.json")
    args = parser.parse_args()
    result = generate()
    static.write(args.output, result)
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    main()
