"""Build truthful character-production plans from live gameplay tables and GLBs.

This lightweight command never launches Blender/UE, edits gameplay tables or
claims that planned actions exist. Re-run after real rigged downloads arrive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
PROFILES = {
    "humanoid_sword_shield": "sword_shield",
    "humanoid_two_hand_crossbow": "crossbow",
    "humanoid_tool_demolition": "shovel",
    "humanoid_two_hand_rifle": "rifle",
    "humanoid_baton_shield": "baton_shield",
    "humanoid_shoulder_launcher": "launcher",
    "humanoid_one_hand_energy": "energy_blade",
    "humanoid_two_hand_energy_rifle": "laser_rifle",
    "humanoid_one_hand": "one_hand",
    "humanoid_two_hand": "two_hand_hammer",
    "humanoid_left_hand_bow": "bow_crew",
    "rider_horse_lance_shield": "mounted_lance",
}
REQUIRED_BONES = {
    "root", "pelvis", "spine_01", "spine_02", "head",
    *[part+"_"+side for side in ("r", "l") for part in
      ("upperarm", "lowerarm", "hand", "thigh", "calf", "foot", "ball")],
    *[f"{digit}_{joint:02d}_{side}" for side in ("r", "l")
      for digit in ("thumb", "index", "middle", "ring", "pinky") for joint in (1, 2, 3)],
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def load_glb(path):
    spec = importlib.util.spec_from_file_location("era_asset_inspection", ROOT / "Tools/Blender/prepare_era_asset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.glb(path)[0]


def rig_evidence(path):
    if not path.is_file():
        return {"path": str(path), "exists": False, "status": "waiting_for_actual_rigged_glb"}
    document = load_glb(path)
    skins = document.get("skins", [])
    joints = sorted({document["nodes"][i].get("name", "") for skin in skins for i in skin["joints"]})
    missing = sorted(REQUIRED_BONES - set(joints))
    joint_nodes = [document["nodes"][i] for skin in skins for i in skin["joints"]]
    explicit_transforms = sum(any(key in node for key in ("matrix", "translation", "rotation", "scale")) for node in joint_nodes)
    return {**record(path), "exists": True, "skins": len(skins), "joint_names": joints,
            "missing_required_bones": missing,
            "joint_nodes_with_explicit_transform": explicit_transforms,
            "source_animations": [a.get("name", str(i)) for i, a in enumerate(document.get("animations", []))],
            "status": "actual_ue5_rig_present" if len(skins) == 1 and not missing and explicit_transforms else
                      "missing_node_transforms_requires_bind_frame_adapter" if len(skins) == 1 and not missing else "rig_requires_explicit_adapter"}


def module_evidence(asset_id):
    directory = ART / "weapons" / asset_id
    interface = directory / "interface.json"
    source = directory / (asset_id + ".glb")
    if not interface.is_file() or not source.is_file():
        return {"asset_id": asset_id, "status": "waiting_for_real_module",
                "expected_glb": str(source), "expected_interface": str(interface)}
    data = read(interface)
    return {"asset_id": asset_id, "status": "source_module_present",
            "source": record(source), "interface": record(interface),
            "blend": record(directory / (asset_id+".blend")) if (directory/(asset_id+".blend")).is_file() else None,
            "pbr_materials": data.get("pbr_materials"),
            "family": data["family"], "anchors": data["anchors"],
            "deformation_controls": data.get("deformation_controls", []),
            "source_validated_on_character": False}


def build(asset_id):
    brief_path = ART / "prompts" / asset_id / "brief.json"
    brief = read(brief_path)
    if brief["kind"] != "human" and asset_id != "Unit_Knight":
        raise ValueError("Use separate rider/mount or mechanical pipeline: " + asset_id)
    crew = asset_id == "Crew_Archer"
    table_path = ROOT / "Content/Data" / ("Turrets.json" if crew else
                                        "Champions.json" if asset_id.startswith("Champion_") else "Units.json")
    authority_key = "Turret_ArrowTower" if crew else asset_id
    row = next(r for r in read(table_path) if r["VisualKey"] == authority_key)
    family = "humanoid_left_hand_bow" if crew else brief["animation_contract"]["family"]
    if family not in PROFILES:
        raise ValueError("No authored family profile yet: " + family)
    source = ART / "tripo_raw" / asset_id / "web_v01_canonical/rigged.glb"
    repair_path = ART / "tripo_processed/rig_bind_repairs" / asset_id / "repair.json"
    repair = read(repair_path) if repair_path.is_file() else None
    if repair and repair.get("blender_validation") == "passed":
        if (repair["source"]["sha256"] != record(source)["sha256"] or
                not repair["binary_mesh_skin_pbr_unchanged"] or
                record(repair["derived"]["path"])["sha256"] != repair["derived"]["sha256"]):
            raise ValueError("Bind reconstruction lineage changed")
        source = Path(repair["derived"]["path"])
    evidence = rig_evidence(source)
    fbx_path = ART / "tripo_raw" / asset_id / "web_v01_canonical/rigged.fbx"
    fbx = record(fbx_path) if fbx_path.is_file() else None
    usd_receipt = fbx_path.parent/"rigged_usd_receipt.json"
    usd = None
    if usd_receipt.is_file():
        received = read(usd_receipt)
        usd = received["usd"]
        if record(usd["path"]) != usd or not Path(usd["path"]).resolve().is_relative_to(fbx_path.parent.resolve()):
            raise ValueError("Actual USD receipt differs from its canonical source")
    modules = [module_evidence(m) for m in (["Weapon_Bow"] if crew else brief["modules"])
               if not m.startswith("Mount_")]
    missing = []
    if evidence["status"] != "actual_ue5_rig_present" and not fbx and not usd:
        missing.append(evidence["status"])
    missing += [m["asset_id"] + ": " + m["status"] for m in modules if m["status"] != "source_module_present"]
    cycle, contact = float(row["AttackInterval"]), float(row.get("AttackWindup", 0))
    if not (0 <= contact < cycle if crew else 0 < contact < cycle):
        raise ValueError("Invalid authoritative attack timing")
    if abs(contact*60-round(contact*60)) > 1e-6 or abs(cycle*60-round(cycle*60)) > 1e-6:
        raise ValueError("Attack timing requires a higher exact sampling rate")
    primary = next((m for m in modules if "Shield" not in m["asset_id"] and m["asset_id"].startswith("Weapon_")), None)
    shield = next((m for m in modules if "Shield" in m["asset_id"]), None)
    height = 198 if asset_id.startswith("Champion_") else 150
    # This target is only a production scale, not an assertion about a missing model.
    plan = {
        "schema_version": 1, "asset_id": asset_id, "profile": PROFILES[family],
        "family": family, "status": "ready_for_leased_blender_preparation" if not missing else "waiting_for_inputs",
        "missing_inputs": missing, "source_rig": evidence, "source_brief": record(brief_path),
        "gameplay_table": record(table_path), "gameplay_values": {
            key: row[key] for key in ("VisualKey", "AttackInterval", "AttackWindup", "MoveSpeed", "Range") if key in row},
        "reference_height_cm": height, "fps": 60, "root_motion": False,
        "clips": {"Idle": 2.0, "Move": .6, "Attack": cycle, "Hit": .5, "Death": 1.4},
        "attack_contact_seconds": contact, "attack_contact_frame": round(contact*60)+1,
        "reference_move_speed_cm_s": float(row.get("MoveSpeed", 0)),
        "attack_recovery_returns_to_idle": True, "death_hold_last_fraction": .2,
        "modules": modules, "primary_weapon": primary["asset_id"] if primary else None,
        "shield": shield["asset_id"] if shield else None,
        "requested_anchors": brief["assembly_usage"][0]["anchors"] if crew else brief["animation_contract"]["anchors"],
        "grip_policy": "Measure real metacarpal frame; align module named grip; no assumed mesh-origin grip",
        "mechanism_policy": "Crossbow source string Draw, limbs and bolt have separate authored visual tracks; UE mechanism delivery is a separate explicit stage",
        "charge_policy": "Engineer pack persists; charge/ability variants are presentation only and do not alter authority",
        "source_reference_pose_claim": "Expected A-pose; must inspect actual rig import before accepting",
        "animations_authored": False, "production_approved": False,
    }
    if repair:
        plan["source_bind_reconstruction"] = record(repair_path)
        plan["source_bind_reconstruction_applied"] = repair.get("blender_validation") == "passed"
    if fbx:
        plan["source_fbx"] = fbx
        plan["render_source_motion_checks"] = True
        plan["source_reference_pose_claim"] = "Actual FBX bone frames and weights require Blender import and pose inspection; original GLB supplies PBR"
    elif usd:
        plan["source_usd"] = usd
        plan["source_usd_receipt"] = record(usd_receipt)
        plan["source_reference_pose_claim"] = "Actual USD Skel must import as a weighted Blender armature and pass mesh/weight checks; original GLB supplies PBR"
    if crew:
        plan.update(authority_source="Turret_ArrowTower.FireSeq",
                    attack_timing_semantics="FireSeq is already released; Attack starts at zero, no invented windup",
                    crew_clips_consumed={"Ready": "Idle", "Fire": "Attack"},
                    attack_recovery_returns_to_idle=True,
                    source_reference_pose_claim="Actual empty-hand rig; bow must attach to left hand with a deforming string",
                    execution_adapter="bow_crew_adapter_required")
    elif family.startswith("rider_"):
        plan["execution_adapter"] = "mounted_lance_rider"
        plan["mount_source"] = rig_evidence(ART/"tripo_raw/Mount_Warhorse/web_v01_canonical/rigged.glb")
        plan["mounted_contract"] = {
            "assembly_owner": "root", "origin": "actual saddle seat; parent owns global horse motion",
            "pelvis_above_origin_m": .12, "body_height_cm": 150,
            "foot_goals_m": {"r": [.10, -.42, -.54], "l": [.10, .42, -.54]},
            "death_policy": "slump and relax limbs only; do not apply the horse death rotation again"}
    else:
        plan["execution_adapter"] = "generic_human"
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ids = args.asset or ["Unit_ShieldSword", "Unit_Crossbowman", "Champion_Medieval"]
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "entries": [build(a) for a in ids],
              "blender_started": False, "animations_authored": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({r["asset_id"]: {"status": r["status"], "missing": r["missing_inputs"],
                                     "attack": [r["attack_contact_seconds"], r["clips"]["Attack"]]}
                      for r in result["entries"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
