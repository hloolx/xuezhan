"""Build the environment-first production queue. This never submits a paid job.

Run: python Tools/build_tripo_queue.py
Execution evidence lives in jobs/execution.json and is preserved across rebuilds.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path, root):
    return path.relative_to(root).as_posix()


def validate_dependencies(jobs):
    by_id = {j["asset_id"]: j for j in jobs}
    if len(by_id) != len(jobs):
        raise ValueError("Duplicate asset IDs")
    visiting, visited = set(), set()

    def walk(asset_id):
        if asset_id in visiting:
            raise ValueError("Cyclic dependency at " + asset_id)
        if asset_id in visited:
            return
        visiting.add(asset_id)
        for dependency in by_id[asset_id]["assembly_dependencies"]:
            if dependency not in by_id:
                raise ValueError(asset_id + " has unknown dependency " + dependency)
            walk(dependency)
        visiting.remove(asset_id)
        visited.add(asset_id)

    for asset_id in by_id:
        walk(asset_id)


def build(root=ROOT):
    art = root / "RawAssets/Art/Tripo_v01"
    catalog = read(art / "catalog.json")
    supplement_path = art / "catalog_champions.json"
    supplement = read(supplement_path, {})
    supplemental_assets = supplement.get("core", []) + supplement.get("support", [])
    supplemental_ids = {a["id"] for a in supplemental_assets}
    supplement_hash = hashlib.sha256(supplement_path.read_bytes()).hexdigest() if supplement_path.exists() else None
    pipeline = read(art / "pipeline.json")
    presets = read(art / "generation_presets.json")
    contracts = read(art / "animation_contracts.json")
    profiles = dict(contracts["profiles"])
    if profiles.keys() & supplement.get("animation_profiles", {}).keys():
        raise ValueError("Duplicate supplemental animation profiles")
    profiles.update(supplement.get("animation_profiles", {}))
    character_preparation = read(art / "prepared_characters_v02/preparation_report.json", {"results": []})
    prepared_character_ids = {r["asset_id"] for r in character_preparation["results"] if r["status"] == "prepared_needs_visual_review"}
    execution = read(art / "jobs/execution.json", {"assets": {}, "tripo_access": "unverified"})
    records = execution.get("assets", {})
    jobs = []
    env_extras = [dict(a, kind="environment", modules=[]) for a in catalog["non_tripo"][:2]]
    assets = env_extras + catalog["core"] + catalog["support"] + supplemental_assets
    source_unit_rows = read(root / "Content/Data/Units.json")
    source_turret_rows = read(root / "Content/Data/Turrets.json")
    source_age_rows = read(root / "Content/Data/Ages.json")
    champion_source = root / "Content/Data/Champions.json"
    source_champion_rows = read(champion_source)
    champion_source_hash = hashlib.sha256(champion_source.read_bytes()).hexdigest()
    champion_ids = {a["VisualKey"] for a in source_champion_rows}
    if champion_ids != {a["id"] for a in supplement.get("core", [])} or champion_ids != set(supplement.get("animation_profiles", {})):
        raise ValueError("Champion catalog and profiles must match gameplay VisualKeys")
    era_by_id = {a["VisualKey"]: a["Age"] for a in source_unit_rows + source_turret_rows + source_champion_rows}
    era_by_id.update({a["VisualKey"]: i for i, a in enumerate(source_age_rows)})
    owners = {}
    for a in assets:
        for dependency in a.get("modules", []):
            owners.setdefault(dependency, []).append(a["id"])
    for dependency in ["Crew_Archer", "Weapon_Bow"]:
        owners.setdefault(dependency, []).append("Turret_ArrowTower")
    for index, asset in enumerate(assets):
        aid = asset["id"]
        kind = asset["kind"]
        route_id = pipeline["asset_overrides"].get(aid, pipeline["kind_routes"][kind])
        route = pipeline["routes"][route_id]
        preset_id = route["request_preset"]
        brief_path = art / "prompts" / aid / "brief.json"
        brief = read(brief_path, {})
        character_prepared = art / "prepared_characters_v02" / aid
        environment_prepared = art / "prepared_environment_tripo" / aid
        architecture_prepared = art / "prepared_architecture_tripo" / aid
        canonical_prepared = art / "prepared_tripo_canonical" / aid
        if (canonical_prepared / "upload_manifest.json").is_file():
            prepared = canonical_prepared
        elif route_id == "environment_h" and (environment_prepared / "upload_manifest.json").is_file():
            prepared = environment_prepared
        elif kind == "base" and route_id == "architecture_h" and (architecture_prepared / "upload_manifest.json").is_file():
            prepared = architecture_prepared
        elif aid in prepared_character_ids and (character_prepared / "upload_manifest.json").is_file():
            prepared = character_prepared
        else:
            prepared = art / "prepared" / aid
        upload = read(prepared / "upload_manifest.json", {})
        views = {v: rel(prepared / filename, root) for v, filename in upload.get("files", {}).items()
                 if (prepared / filename).is_file()}
        canonical = upload.get("view_convention") == "tripo_api_canonical_probe_e175fe52"
        required = (upload["project_required_views"] if canonical else route["review_views"]) if preset_id else []
        missing = [view for view in required if view not in views]
        dependencies = list(asset.get("modules", []))
        if aid == "Turret_ArrowTower":
            dependencies = sorted(set(dependencies + ["Crew_Archer", "Weapon_Bow"]))
        era = era_by_id.get(aid, min((era_by_id.get(owner, 0) for owner in owners.get(aid, [])), default=0))
        if not isinstance(era, int):
            era = 0
        # Scene first, then base and unit sets in era order. Modules precede assembly.
        stage = 0 if kind == "environment" else 90 if route_id == "deferred" else 10 + era * 10
        rank = {"environment": 0, "base": 1, "weapon": 2, "prop": 2, "mount": 3,
                "human": 4, "rider": 5, "vehicle": 5, "mech": 5, "turret": 6}[kind]
        blocks = []
        if aid in supplemental_ids:
            if not brief:
                blocks.append("design_brief_missing")
            elif brief.get("design_catalog_sha256") != supplement_hash:
                blocks.append("design_contract_stale")
            if aid in champion_ids and brief and brief.get("source", {}).get("sha256") != champion_source_hash:
                blocks.append("gameplay_contract_stale")
        if preset_id:
            if execution.get("tripo_access") != "verified":
                blocks.append("needs_tripo_access")
            if missing:
                blocks.append("missing_reference_views")
            if not upload.get("production_approved", False):
                blocks.append("reference_review_pending")
            if canonical and not upload.get("canonical_mapping_validation", {}).get("approved", False):
                blocks.append("canonical_mapping_model_pilot_pending")
        if route_id == "deferred":
            blocks.append("gameplay_visual_mapping_required")
        status = blocks[0] if blocks else "ready_for_dcc" if not preset_id else "ready_for_generation"
        evidence = records.get(aid, {})
        for output in evidence.get("output_files", []):
            if not (root / output).is_file():
                raise ValueError(aid + " execution output missing: " + output)
        if evidence.get("status") in {"downloaded", "dcc_ready", "validated"} and not evidence.get("output_files"):
            raise ValueError(aid + " cannot claim generated geometry without output_files")
        profile = profiles.get(aid)
        clips = ["idle", "move", "attack", "hit", "death"] if aid.startswith(("Unit_", "Champion_")) else []
        if kind == "mount":
            clips = ["idle", "walk", "run", "hit", "death"]
        elif kind == "turret":
            clips = ["idle", "aim", "fire", "disabled"]
        elif aid == "Crew_Archer":
            clips = ["idle", "aim", "fire", "reload", "death"]
        clips = list(dict.fromkeys(clips + (profile or {}).get("extra_clips", [])))
        jobs.append({
            "asset_id": aid, "kind": kind, "display_name": brief.get("display_name", asset.get("name", aid)),
            "order_key": [stage, rank, index], "route": route_id,
            "provider": "Tripo" if preset_id else "Blender" if route_id != "deferred" else "unassigned",
            "status": evidence.get("status", status), "blockers": blocks,
            "inputs": {"brief": rel(brief_path, root) if brief_path.exists() else None,
                       "production_prompt": rel(brief_path.with_name("production.txt"), root) if brief_path.exists() else None,
                       "images": views, "required_views": required, "missing_views": missing,
                       "reference_approved": upload.get("production_approved", False),
                       "reference_approval_scope": upload.get("approval_scope"),
                       "view_convention": upload.get("view_convention", "design_subject_views"),
                       "canonical_metadata": rel(prepared / "canonical_metadata.json", root) if canonical else None,
                       "canonical_mapping_validation": upload.get("canonical_mapping_validation")},
            "request_preset": preset_id,
            "request_parameters": presets["presets"][preset_id]["parameters"] if preset_id else None,
            "submission_endpoint": presets["endpoint"] if preset_id else None,
            "submission_note": "Local image paths must be uploaded first; this queue is not an API request.",
            "assembly_dependencies": dependencies, "used_by": owners.get(aid, []),
            "body_or_rig_target": brief.get("production_target", asset.get("route", route["rig"])),
            "animation_contract": profile,
            "required_clips": clips,
            "clip_status": "not_validated" if clips else "not_applicable",
            "timing": (brief.get("animation_contract") or {}).get("timing"),
            "acceptance": route["acceptance"],
            "execution": {"task_id": evidence.get("task_id"), "credits_charged": evidence.get("credits_charged"),
                          "cost_currency": evidence.get("cost_currency"), "cost_amount": evidence.get("cost_amount"),
                          "output_files": evidence.get("output_files", []), "evidence_file": evidence.get("evidence_file"),
                          "note": evidence.get("note"),
                          **{key: value for key, value in evidence.items() if key != "status"}},
            "production_approved": False,
        })
    jobs.sort(key=lambda j: j["order_key"])
    validate_dependencies(jobs)
    source_units = {a["VisualKey"] for a in source_unit_rows}
    source_turrets = {a["VisualKey"] for a in source_turret_rows}
    source_bases = {a["VisualKey"] for a in source_age_rows}
    for label, expected in [("units", source_units), ("turrets", source_turrets), ("bases", source_bases), ("champions", champion_ids)]:
        if not expected.issubset({j["asset_id"] for j in jobs}):
            raise ValueError("Queue missing source " + label)
    return {"schema_version": 1, "built_at": datetime.now(timezone.utc).isoformat(),
            "priority": "environment_first_then_era_sets", "submitted_by_this_script": False,
            "tripo_access": execution.get("tripo_access", "unverified"),
            "counts": {"total": len(jobs), "units": len(source_units), "bases": len(source_bases),
                       "turrets": len(source_turrets), "champions": len(champion_ids),
                       "by_provider": dict(Counter(j["provider"] for j in jobs)),
                       "by_status": dict(Counter(j["status"] for j in jobs))}, "jobs": jobs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    queue = build(root)
    out = root / "RawAssets/Art/Tripo_v01/jobs"
    write(out / "queue.json", queue)
    for job in queue["jobs"]:
        write(out / "cards" / (job["asset_id"] + ".json"), job)
    lines = ["# 资产制作执行队列", "", "场地先行；此文件由 Tools/build_tripo_queue.py 生成。",
             "所有 Tripo 提交须由实际账户入口执行并记录任务号、实际扣费和下载文件；本脚本不联网或扣费。",
             "execution.json 是人工/自动化写入的事实记录，重建队列不会覆盖它。下载完成仍须独立通过绑定、动作和 UE 验收。", "",
             "| 顺序 | 资产 | 路线 | 当前状态 | 装配依赖 |", "|---:|---|---|---|---|"]
    for i, job in enumerate(queue["jobs"], 1):
        lines.append(f"| {i} | {job['asset_id']} | {job['route']} | {job['status']} | {', '.join(job['assembly_dependencies']) or '—'} |")
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(queue["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
