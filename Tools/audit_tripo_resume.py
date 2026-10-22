"""Check saved hashes and submission receipts before refreshing the production ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(root, ledger):
    root = root.resolve()
    art = root / "RawAssets/Art/Tripo_v01"
    failures, models, intents, task_ids = [], [], [], set()
    for asset_id, asset in ledger.get("assets", {}).items():
        for task in asset.get("task_history", []):
            task_id = task.get("task_id")
            if task_id:
                task_ids.add(task_id)
            for filename in task.get("output_files", []):
                path = (root / filename).resolve()
                expected = task.get("sha256", {}).get(path.name)
                record = {"asset_id": asset_id, "task_id": task_id, "file": filename,
                          "expected_sha256": expected, "matches": False}
                if not path.is_relative_to(art.resolve()):
                    failures.append("Recorded model escapes art directory: " + filename)
                elif not path.is_file():
                    failures.append("Recorded model missing: " + filename)
                elif not expected:
                    failures.append("Recorded model lacks frozen hash: " + filename)
                else:
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    record.update(actual_sha256=actual, bytes=path.stat().st_size,
                                  matches=actual == expected)
                    if actual != expected:
                        failures.append("Recorded model hash changed: " + filename)
                models.append(record)
    for path in sorted((art / "tripo_raw").glob("*/*/submission.intent.json")):
        identifiers, receipts = set(), []
        for name in ("submission.json", "task.json", "task_status.json"):
            receipt_path = path.parent / name
            if not receipt_path.exists():
                continue
            receipt = read_json(receipt_path)
            task_id = receipt.get("task_id")
            if task_id:
                identifiers.add(task_id)
            receipts.append({"file": name, "task_id": task_id, "status": receipt.get("status")})
        relative = path.relative_to(root).as_posix()
        if len(identifiers) != 1:
            failures.append("Intent has missing or conflicting task IDs; reconcile, never resubmit: " + relative)
        elif not identifiers.issubset(task_ids):
            failures.append("Intent receipt is absent from the saved ledger: " + relative)
        intents.append({"file": relative, "task_ids": sorted(identifiers), "receipts": receipts})
    return {"schema_version": 1, "verified_at": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if not failures else "failed", "model_files_checked": len(models),
            "intent_folders_checked": len(intents), "failures": failures,
            "models": models, "intents": intents, "network_calls": 0, "paid_submissions": 0,
            "scope": "Saved local identity and receipt consistency only; not live provider status, balances, model quality or production acceptance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.root, read_json(args.root / "RawAssets/Art/Tripo_v01/jobs/execution.json"))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "model_files_checked", "intent_folders_checked", "failures")}))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
