"""Run the reviewed stone-era importers in one UE process, then verify a fresh one."""
from pathlib import Path
import hashlib
import importlib
import json
import os
import sys
import traceback

import unreal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
plan_path = Path(os.environ["CIVWAR_STONE_ERA_IMPORT_PLAN"])
plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
stage = os.environ.get("CIVWAR_STONE_ERA_IMPORT_STAGE", "initial")
out = plan_path.parent / (stage + "_batch_report.json")
results = []


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def persisted_snapshot(destination):
    records = []
    for asset_path in unreal.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False):
        package = ROOT / "Content" / (asset_path.split(".")[0][len("/Game/"):] + ".uasset")
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if asset is None or not package.is_file():
            raise ValueError("Missing persisted asset: " + asset_path)
        records.append({"asset": asset_path, "file": str(package), "sha256": digest(package)})
    if not records:
        raise ValueError("Empty asset destination: " + destination)
    return records


try:
    for entry in plan["entries"]:
        row = {"asset": entry["asset"], "status": "running"}
        results.append(row)
        try:
            manifest = ROOT / entry["manifest"]
            report = ROOT / entry["report"]
            snapshot = report.with_name("persisted_package_snapshot.json")
            report.parent.mkdir(parents=True, exist_ok=True)
            module = importlib.import_module(entry["module"])
            if stage == "initial":
                if entry["module"] == "import_beast_rider_preview":
                    result = module.run(unreal, manifest, report)
                else:
                    module.execute(manifest, report)
                    result = json.loads(report.read_text(encoding="utf-8-sig"))
                if result.get("status") == "failed":
                    raise ValueError(result.get("error", str(result.get("failures"))))
                records = persisted_snapshot(result["destination"])
                snapshot.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                row["packages"] = len(records)
            elif stage == "fresh":
                initial = json.loads(report.read_text(encoding="utf-8-sig"))
                previous = json.loads(snapshot.read_text(encoding="utf-8-sig"))
                for record in previous:
                    if digest(record["file"]) != record["sha256"]:
                        raise ValueError("Saved asset changed before reopen: " + record["file"])
                    if unreal.EditorAssetLibrary.load_asset(record["asset"]) is None:
                        raise ValueError("Fresh process could not load: " + record["asset"])
                if entry["module"] != "import_beast_rider_preview":
                    module.execute(manifest, report.with_name("unreal_fresh.json"), report)
                # Reading validation must leave the immutable saved bundle intact.
                for record in previous:
                    if digest(record["file"]) != record["sha256"]:
                        raise ValueError("Fresh validation changed saved package: " + record["file"])
                row["packages"] = len(previous)
            else:
                raise ValueError("Unknown stage: " + stage)
            row["status"] = "passed"
            row["report"] = str(report)
        except Exception as error:
            row.update(status="failed", error=str(error), traceback=traceback.format_exc())
            print(row["traceback"])
        finally:
            out.write_text(json.dumps({"stage": stage, "process_id": os.getpid(), "results": results,
                                       "production_approved": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(row["status"] != "passed" for row in results):
        raise RuntimeError("Stone-era batch has failed entries; inspect " + str(out))
finally:
    print("STONE_ERA_BATCH_REPORT " + str(out))
