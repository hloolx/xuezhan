"""Reconcile local Tripo receipts and downloaded artifacts; never submit jobs.

Run after CLI submission/download. Only actual downloaded model files and actual
credits_consumed values count. Failed or pending jobs are retained in history.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def relative(path):
    return path.relative_to(ROOT).as_posix()


def collect_auxiliary_tasks(art, recorded_model_ids):
    records = {}
    for receipt in sorted((art / "reviews").rglob("task.json")):
        task = read(receipt, {})
        if task.get("type") not in {"image_to_multiview", "animate_prerigcheck"}:
            continue
        task_id = task.get("task_id")
        if not task_id or task_id in recorded_model_ids:
            continue
        final = task.get("status") in {"success", "failed", "cancelled"}
        record = {"task_id": task_id, "type": task["type"], "status": task.get("status"),
                  "credits_charged": task.get("credits_consumed") if final else None,
                  "evidence_file": receipt.relative_to(art).as_posix()}
        previous = records.get(task_id)
        if previous and previous["credits_charged"] is not None:
            if record["credits_charged"] not in {None, previous["credits_charged"]}:
                raise ValueError("Conflicting auxiliary credit receipts: " + task_id)
            continue
        records[task_id] = record
    return records


def main():
    path = ART / "jobs/execution.json"
    ledger = read(path, {"schema_version": 1, "assets": {}})
    all_tasks = {}
    for asset_dir in sorted((ART / "tripo_raw").iterdir()):
        if not asset_dir.is_dir():
            continue
        previous = ledger["assets"].get(asset_dir.name, {})
        history = {r["task_id"]: r for r in previous.get("task_history", [])}
        for folder in sorted(asset_dir.iterdir()):
            if not folder.is_dir():
                continue
            submission = read(folder / "submission.json", {})
            task = read(folder / "task.json", {})
            latest = read(folder / "task_status.json", {})
            task_id = task.get("task_id") or latest.get("task_id") or submission.get("task_id")
            if not task_id:
                continue
            models = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in {".glb", ".fbx", ".obj"} and p.stat().st_size > 0]
            receipt = {**history.get(task_id, {}), "task_id": task_id,
                       "version": folder.name,
                       "type": task.get("type", latest.get("type", submission.get("type", "unknown"))),
                       "provider_status": task.get("status", latest.get("status", submission.get("status", "submitted"))),
                       "created_at": task.get("created_at", latest.get("created_at")),
                       "credits_charged": task.get("credits_consumed", latest.get("credits_consumed")),
                       "output_files": [relative(p) for p in models],
                       "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models},
                       "evidence_file": relative(folder / ("task.json" if task else "task_status.json" if latest else "submission.json"))}
            if receipt["provider_status"] not in {"success", "failed", "cancelled"}:
                receipt["reported_pending_credits"] = receipt["credits_charged"]
                receipt["credits_charged"] = None
            receipt["status"] = "downloaded" if models and receipt["provider_status"] == "success" else receipt["provider_status"]
            history[task_id] = receipt
        if not history:
            continue
        ordered = sorted(history.values(), key=lambda r: (r.get("created_at") or "9999", r["version"]))
        latest = ordered[-1]
        ledger["assets"][asset_dir.name] = {**previous, **latest, "task_history": ordered,
            "note": "真实 Tripo 任务记录；下载不代表模型、绑定、动画或 UE 验收完成。"}
        all_tasks.update(history)
    if all_tasks:
        ledger["tripo_access"] = "verified"
    # Diagnostic/image tasks also spend credits, even though they produce no mesh.
    auxiliary = collect_auxiliary_tasks(ART, all_tasks)
    for record in auxiliary.values():
        record["evidence_file"] = relative(ART / record["evidence_file"])
    ledger["auxiliary_tasks"] = list(auxiliary.values())
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    ledger["note"] = "通过已登录的 Tripo CLI 执行。账本仅从本地任务回执及实际文件重建，不联网、不扣费。"
    accounted = {**all_tasks, **auxiliary}
    ledger["totals"] = {"task_count": len(accounted), "model_task_count": len(all_tasks),
        "downloaded_task_count": sum(r["status"] == "downloaded" for r in all_tasks.values()),
        "confirmed_credits_charged": sum(r["credits_charged"] or 0 for r in accounted.values()),
        "tasks_without_final_credit_receipt": sum(r["credits_charged"] is None for r in accounted.values())}
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ledger["totals"]))


if __name__ == "__main__":
    main()
