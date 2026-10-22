"""Reconcile gameplay VisualKeys with the art catalog, without submitting jobs."""
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(root=ROOT):
    art = root / "RawAssets/Art/Tripo_v01"
    catalog = read(art / "catalog.json")
    ids = {item["id"] for group in ("core", "support", "non_tripo") for item in catalog.get(group, [])}
    supplement = art / "catalog_champions.json"
    if supplement.exists():
        additional = read(supplement)
        for group in ("core", "support"):
            for asset in additional.get(group, []):
                if asset["id"] in ids:
                    raise ValueError("Duplicate supplemental asset: " + asset["id"])
                ids.add(asset["id"])
    execution = read(art / "jobs/execution.json").get("assets", {})
    rows = []
    for table in ("Units", "Ages", "Turrets", "Champions"):
        for index, item in enumerate(read(root / "Content/Data" / (table + ".json"))):
            key = item["VisualKey"]
            record = execution.get(key, {})
            geometry = [root / path for path in record.get("output_files", []) if Path(path).suffix.lower() in {".glb", ".gltf", ".fbx", ".obj", ".blend"}]
            has_model = bool(geometry) and all(path.is_file() for path in geometry)
            brief_exists = (art / "prompts" / key / "brief.json").is_file()
            entry = {"asset_id": key, "name": item.get("DisplayName", item["Name"]),
                     "source_table": table, "source_row": item["Name"], "age": item.get("Age", index),
                     "in_production_catalog": key in ids,
                     "has_design_brief": brief_exists,
                     "has_downloaded_model": record.get("status") in {"downloaded", "dcc_ready", "validated"} and has_model,
                     "state": record.get("status", "brief_ready_reference_required" if brief_exists else "design_required"),
                     "production_approved": record.get("production_approved", False)}
            if key not in ids:
                entry.update({"next_action": "Create a style-matched body/equipment brief, review reference views, then schedule generation",
                              "state": "design_required", "automatic_submission_allowed": False,
                              "description": item.get("Description", ""),
                              "attack_interval": item.get("AttackInterval"), "attack_windup": item.get("AttackWindup"),
                              "priority": "stone_era_completion" if item.get("Age") == 0 else "later_era_set"})
            rows.append(entry)
    return {"schema_version": 1, "verified_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Gameplay VisualKey coverage, not model/animation quality approval",
            "counts": {"gameplay_visuals": len(rows), "catalogued": sum(r["in_production_catalog"] for r in rows),
                       "with_design_brief": sum(r["has_design_brief"] for r in rows),
                       "with_downloaded_model": sum(r["has_downloaded_model"] for r in rows),
                       "missing_from_catalog": sum(not r["in_production_catalog"] for r in rows)},
            "missing_assets": [r for r in rows if not r["in_production_catalog"]], "assets": rows,
            "paid_jobs_submitted": 0}


if __name__ == "__main__":
    report = audit()
    output = ART / "jobs/gameplay_coverage.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "missing": [r["asset_id"] for r in report["missing_assets"]],
                      "output": str(output)}, ensure_ascii=False))
