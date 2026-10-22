"""Submit one reviewed processing step with an exclusive intent and a credit gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def cli():
    folder = Path(os.environ.get("TRIPO_NODE_DIR", str(Path.home() / "devtools/node-v24.16.0-win-x64")))
    return [str(folder / "node.exe"), str(folder / "node_modules/tripo-cli/dist/cli.js")]


def plan(spec_path):
    spec = read(spec_path)
    for key in ("asset_id", "version"):
        value = spec[key]
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("Asset and version must be single directory names")
    if spec.get("approved_for_processing") is not True:
        raise ValueError("Processing-stage review is required")
    operation = spec["operation"]
    if operation not in {"texture", "rig", "retarget"}:
        raise ValueError("Unsupported processing step")
    expected = {"texture": 10, "rig": 25, "retarget": 10}[operation]
    if spec["expected_credits"] != expected:
        raise ValueError("Unverified processing cost")
    if operation == "retarget" and len(spec.get("animations", [])) != 1:
        raise ValueError("One retarget clip per reviewed task")
    source = (ROOT / spec["source_file"]).resolve()
    if not source.is_relative_to(ART.resolve()) or source.suffix.lower() not in {".glb", ".fbx"}:
        raise ValueError("Source must be a project art model")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != spec["source_sha256"]:
        raise ValueError("Reviewed source hash changed")
    evidence = (ROOT / spec["review_file"]).resolve()
    if not evidence.is_relative_to(ART.resolve()) or not evidence.is_file():
        raise ValueError("Missing stage review evidence")
    output = ART / "tripo_raw" / spec["asset_id"] / spec["version"]
    for name in ("submission.intent.json", "submission.json", "task.json", "task_status.json"):
        if (output / name).exists():
            raise ValueError("Existing task/intent; reconcile instead of resubmitting")
    arguments = spec["arguments"]
    if any(flag in arguments for flag in ("--then", "--no-wait", "--out", "--yes", "--json")):
        raise ValueError("Managed flags or task chains are not allowed")
    return {**spec, "spec_file": str(spec_path.resolve()), "source_file": str(source),
            "output_directory": str(output), "created_at": datetime.now(timezone.utc).isoformat()}


def submit(item):
    executable = cli()
    balance_result = subprocess.run(executable + ["balance", "--json"], capture_output=True,
                                    text=True, encoding="utf-8", timeout=60, check=True)
    balance = json.loads(balance_result.stdout)
    if balance["balance"] < item["expected_credits"]:
        raise ValueError("Insufficient CLI balance; use authorized browser membership, never purchase credits")
    fresh = plan(Path(item["spec_file"]))
    for key in ("source_sha256", "operation", "arguments", "source_task_id", "expected_credits"):
        if fresh.get(key) != item.get(key):
            raise ValueError("Reviewed processing plan changed")
    output = Path(item["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    write(output / "submission.intent.json", {**item, "balance_before": balance}, exclusive=True)
    if any((output / name).exists() for name in ("submission.json", "task.json", "task_status.json")):
        raise ValueError("Receipt appeared after locking; reconcile it")
    source = item.get("source_task_id")
    if not source:
        (output / "inputs").mkdir(exist_ok=False)
        snapshot = output / "inputs" / ("input" + Path(item["source_file"]).suffix)
        contents = Path(item["source_file"]).read_bytes()
        if hashlib.sha256(contents).hexdigest() != item["source_sha256"]:
            raise ValueError("Source changed while freezing input")
        with snapshot.open("xb") as stream:
            stream.write(contents)
        source = str(snapshot)
    group = "model" if item["operation"] == "texture" else "anim"
    command = executable + [group, item["operation"], source, *item["arguments"],
        "--name", "civwar-" + item["asset_id"].lower() + "-" + item["version"],
        "--out", str(output), "--no-wait", "--no-open", "--yes", "--json"]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=240)
    except subprocess.TimeoutExpired:
        write(output / "submission.uncertain.json", {"status": "timeout_unknown_outcome", "automatic_retry": False})
        raise
    (output / "submission.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output / "submission.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("CLI error; reconcile saved intent/output before retrying")
    receipt = json.loads(result.stdout)
    if not receipt.get("task_id"):
        raise ValueError("Missing task ID; reconcile the outcome")
    write(output / "submission.json", receipt, exclusive=True)
    print(json.dumps({"asset_id": item["asset_id"], **{key: receipt.get(key) for key in ("task_id", "status", "type")}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    item = plan((ROOT / args.spec).resolve())
    if args.submit:
        submit(item)
    else:
        print(json.dumps(item, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
