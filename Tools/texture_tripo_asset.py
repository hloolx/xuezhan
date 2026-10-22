"""Submit one reviewed model for Tripo texture using its original multiview refs.

This command spends Tripo credits. It never retries submissions automatically.
Existing intent/receipt blocks duplicates, including an uncertain API outcome.
"""
import argparse
import json
from pathlib import Path
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("asset")
    p.add_argument("--source-version", default="v01")
    p.add_argument("--output-version", default="textured_v01")
    p.add_argument("--submit", action="store_true", help="Actually submit and spend credits; default prints plan only")
    args = p.parse_args()
    for part in (args.asset, args.source_version, args.output_version):
        if not part or Path(part).name != part or part in {".", ".."}:
            raise ValueError("Expected a single directory name")
    source = ART / "tripo_raw" / args.asset / args.source_version / "task.json"
    task = json.loads(source.read_text(encoding="utf-8-sig"))
    if task["status"] != "success":
        raise ValueError("Source task must have succeeded")
    files = task["input"].get("files", [])
    if len(files) != 4 or not files[0] or sum(bool(f) for f in files) < 2:
        raise ValueError("Need source task's original four-slot multiview upload receipts")
    images = [{view: value} for view, value in zip(("front", "left", "back", "right"), files) if value]
    output = source.parent.parent / args.output_version
    intent = output / "submission.intent.json"
    receipt = output / "submission.json"
    if intent.exists() or receipt.exists():
        raise ValueError("Submission intent or receipt already exists; reconcile it instead of resubmitting")
    config = {"asset_id": args.asset, "source_task_id": task["task_id"],
              "source_receipt": source.relative_to(ROOT).as_posix(),
              "texture_quality": "standard", "texture_alignment": "original_image",
              "pbr": True, "texture_prompt": {"images": images}}
    print(json.dumps({k: v for k, v in config.items() if k != "texture_prompt"}))
    if not args.submit:
        return
    node_dir = Path(os.environ.get("TRIPO_NODE_DIR", str(Path.home() / "devtools/node-v24.16.0-win-x64")))
    command = [str(node_dir / "node.exe"), str(node_dir / "node_modules/tripo-cli/dist/cli.js"),
        "model", "texture", task["task_id"], "--texture-quality", "standard", "--texture-alignment", "original_image",
        "-p", "pbr=true", "-p", "texture_prompt=" + json.dumps(config["texture_prompt"], separators=(",", ":")),
        "--name", "civwar-" + args.asset.lower() + "-" + args.output_version,
        "--out", str(output), "--no-wait", "--no-open", "--yes", "--json"]
    if not Path(command[0]).is_file() or not Path(command[1]).is_file():
        raise ValueError("Set TRIPO_NODE_DIR to the installed CLI's Node directory")
    output.mkdir(parents=True, exist_ok=True)
    intent.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=180)
    receipt.write_text(result.stdout, encoding="utf-8")
    (output / "submission.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("CLI failed; saved intent/response must be reconciled before any retry")
    response = json.loads(result.stdout)
    print(json.dumps({k: response.get(k) for k in ("task_id", "type", "status")}))


if __name__ == "__main__":
    main()
