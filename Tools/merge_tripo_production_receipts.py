"""Merge per-asset browser receipts; only the root agent writes the shared ledger."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
path = ART / "jobs/web_execution_20261020.json"
ledger = json.loads(path.read_text(encoding="utf-8-sig"))
merged = []
for source in sorted((ART / "tripo_raw").glob("*/web_v01_canonical/production_receipt.json")):
    try:
        receipt = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        continue  # Another agent may currently be completing this independent file.
    if not receipt.get("task_id"):
        continue
    asset = receipt["asset_id"]
    old = ledger["assets"].setdefault(asset, {})
    if old.get("task_id") and old["task_id"] != receipt["task_id"]:
        raise ValueError("Conflicting paid task for " + asset)
    old.update({
        "task_id": receipt["task_id"], "status": receipt["status"],
        "web_credits_confirmed": receipt.get("web_credits_confirmed"),
        "evidence_file": str(source.relative_to(ROOT)),
        "export_stages": list(receipt.get("exports", {})),
        "production_approved": False,
    })
    merged.append(asset)
ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
temporary = path.with_suffix(".merge.tmp")
temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(path)
print(json.dumps({"merged": merged}, ensure_ascii=False))
