"""Freeze a truthful serial DCC queue from actual received human source files.

Missing downloads remain waiting. Existing matching prepared bundles are reused.
This command never launches Blender/UE or edits runtime configuration.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from prepare_era_character_plan import build, read

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT/"RawAssets/Art/Tripo_v01/tripo_processed"
REMAINING = (
    "Champion_Medieval", "Unit_Rifleman", "Champion_Industrial",
    "Unit_RiotTrooper", "Unit_RocketTrooper", "Champion_Modern",
    "Unit_PlasmaBlade", "Unit_LaserTrooper", "Champion_Future",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_signature(plan):
    records = [plan[key] for key in ("source_rig", "source_fbx", "source_usd",
                                    "source_brief", "gameplay_table") if plan.get(key)]
    for module in plan["modules"]:
        records.extend(module[key] for key in ("source", "interface", "blend") if module.get(key))
        for material in (module.get("pbr_materials") or {}).values():
            records.extend(material["textures"].values())
    return sorted((Path(row["path"]).name, row["sha256"]) for row in records)


def target_folder(asset):
    return PROCESSED/(re.sub(r"^Unit_", "", asset).lower()+"_v01")


def existing_bundle(plan, folder):
    matches = []
    candidates = [*folder.glob("candidate_*/manifest.json"), *folder.glob("fbx_candidate_*/manifest.json")]
    for manifest in candidates:
        try:
            delivery = read(manifest)
            prior_plan = read(delivery["plan"]["path"])
            records = [delivery["body"], *delivery["clips"], *delivery["textures"].values()]
            if (source_signature(prior_plan) == source_signature(plan) and
                    all(digest(row["path"]) == row["sha256"] for row in records) and
                    set(row["clip"] for row in delivery["clips"]) == {"Idle", "Move", "Attack", "Hit", "Death"}):
                matches.append(manifest)
        except (OSError, KeyError, ValueError):
            continue
    return sorted(matches)[-1] if matches else None


def prepare(directory, assets, candidate_prefix="candidate"):
    if candidate_prefix not in {"candidate", "fbx_candidate"}:
        raise ValueError("Use an explicit supported candidate namespace")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plans, tasks = [], []
    for asset in assets:
        plan = build(asset)
        plans.append(plan)
        row = {"asset": asset, "status": "waiting_for_inputs", "missing_inputs": plan["missing_inputs"]}
        if plan["status"] == "ready_for_leased_blender_preparation":
            folder = target_folder(asset)
            existing = existing_bundle(plan, folder)
            if existing:
                row.update(status="reuse_prepared_dcc", manifest=str(existing), manifest_sha256=digest(existing),
                           visual_and_unreal_approval_not_inferred=True)
            else:
                numbers = [int(path.name.rsplit("_", 1)[-1]) for path in folder.glob(candidate_prefix+"_*")
                           if path.is_dir() and re.fullmatch(candidate_prefix+r"_\d+", path.name)]
                target = folder/(candidate_prefix+"_%02d" % (max(numbers, default=0)+1))
                row.update(status="ready_for_leased_dcc", output=str(target),
                           source_format="FBX" if plan.get("source_fbx") else "USD" if plan.get("source_usd") else "GLB")
        tasks.append(row)
    plan_path = directory/"input_plan.json"
    plan_path.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                                    "entries": plans, "animations_authored": False}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    queue = {"schema": "actual_human_dcc_queue_v1", "input_plan": str(plan_path),
             "input_plan_sha256": digest(plan_path), "tasks": tasks,
             "heavy_process_started": False, "runtime_config_written": False,
             "execution_policy": "Only under root's current heavy-slot lease, serial Blender at 2 threads/BelowNormal; inspect real images before UE import"}
    (directory/"queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({row["asset"]: row["status"] for row in tasks}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset", action="append")
    parser.add_argument("--candidate-prefix", choices=("candidate", "fbx_candidate"), default="candidate")
    args = parser.parse_args()
    prepare(args.output, args.asset or REMAINING, args.candidate_prefix)
