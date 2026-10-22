"""Plan or submit ONE reviewed canonical multiview geometry job.

Dry-run by default. Each paid submission creates an exclusive intent first;
uncertain outcomes must be reconciled instead of automatically retried.
"""
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
VIEWS = ("front", "left", "back", "right")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def plan(asset, version, preset, single_front_review=None):
    for value in (asset, version, preset):
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("Asset, version and preset must be single names")
    folder = ART / "prepared_tripo_canonical" / asset
    upload = read(folder / "upload_manifest.json")
    metadata = read(folder / "canonical_metadata.json")
    if upload.get("view_convention") != "tripo_api_canonical_probe_e175fe52":
        raise ValueError("Only canonical Tripo view files are accepted")
    files = {}
    hashes = {}
    for view in VIEWS:
        if view not in upload["files"]:
            continue
        path = folder / upload["files"][view]
        if path.resolve().parent != folder.resolve() or path.stem != view:
            raise ValueError("CLI direction detection requires exact canonical filenames")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != metadata["files"][view]["canonical_sha256"]:
            raise ValueError("Canonical input has changed: " + str(path))
        files[view] = str(path)
        hashes[view] = digest
    if "front" not in files or not 2 <= len(files) <= 4:
        raise ValueError("Need front and one to three other views")
    if not set(upload["project_required_views"]).issubset(files):
        raise ValueError("Project-required views are missing")
    approval = read(ART / "reviews/geometry_pilot_approvals.json")["assets"].get(asset, {})
    if not approval.get("approved_for_geometry_pilot") or approval.get("sha256") != hashes:
        raise ValueError("A visual geometry-pilot approval matching these exact images is required")
    allowed = approval.get("allowed_presets", [])
    if preset not in allowed:
        raise ValueError("This preset was not included in the pilot review")
    generation_type = "multiview-to-model"
    variant_review = None
    if single_front_review:
        review_path = (ROOT / single_front_review).resolve()
        if not review_path.is_relative_to((ART / "reviews").resolve()):
            raise ValueError("Single-front review must be in the project review directory")
        variant_review = read(review_path)
        expected_identity = {"asset_id": asset, "version": version, "preset": preset}
        if any(variant_review.get(key) != value for key, value in expected_identity.items()):
            raise ValueError("Single-front review identity does not match this exact task")
        if variant_review.get("approved_for_single_front_geometry") is not True or not variant_review.get("reason"):
            raise ValueError("Explicit single-front visual review and reason required")
        if variant_review.get("sha256") != {"front": hashes["front"]}:
            raise ValueError("Single-front review image hash mismatch")
        files = {"front": files["front"]}
        hashes = {"front": hashes["front"]}
        single_front_review = str(review_path)
        generation_type = "image-to-model"
    parameters = read(ART / "generation_presets.json")["presets"][preset]["parameters"]
    model = parameters["model"]
    if parameters.get("texture") is not False or parameters.get("pbr") is not False:
        raise ValueError("This runner only accepts geometry-only presets")
    if model == "P2-20260801":
        model_alias, cost = "tripo-p2", 100
    elif model == "v3.1-20260211":
        model_alias, cost = "tripo-v3.1", 20
    else:
        raise ValueError("Unverified model/cost: " + model)
    if variant_review and variant_review.get("maximum_credits") != cost:
        raise ValueError("Single-front review cost does not match the selected model")
    output = ART / "tripo_raw" / asset / version
    if any((output / name).exists() for name in ("submission.intent.json", "submission.json", "task.json", "task_status.json")):
        raise ValueError("Existing submission/intent: reconcile it; do not resubmit")
    return {"asset_id": asset, "version": version, "preset": preset,
            "model_alias": model_alias, "parameters": parameters,
            "expected_geometry_credits": cost, "input_files": files, "sha256": hashes,
            "output_directory": str(output), "review": approval,
            "generation_type": generation_type, "single_front_review": single_front_review,
            "variant_review": variant_review, "created_at": datetime.now(timezone.utc).isoformat()}


def submit(item):
    node_dir = Path(os.environ.get("TRIPO_NODE_DIR", str(Path.home() / "devtools/node-v24.16.0-win-x64")))
    cli = [str(node_dir / "node.exe"), str(node_dir / "node_modules/tripo-cli/dist/cli.js")]
    balance_result = subprocess.run(cli + ["balance", "--json"], capture_output=True,
                                    text=True, encoding="utf-8", timeout=60, check=True)
    balance = json.loads(balance_result.stdout)
    if balance["balance"] < item["expected_geometry_credits"]:
        raise ValueError("Insufficient CLI balance. User policy: switch to browser membership; never purchase credits.")
    # Recheck after the network wait; another agent may have changed/revoked
    # an approval or written a receipt since the original plan was created.
    fresh = plan(item["asset_id"], item["version"], item["preset"], item.get("single_front_review"))
    if any(fresh.get(key) != item.get(key) for key in ("sha256", "parameters", "generation_type", "variant_review")):
        raise ValueError("Inputs or parameters changed after planning; review a new plan")
    item["balance_before"] = balance
    output = Path(item["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    canonical_files = dict(item["input_files"])
    item["canonical_input_files"] = canonical_files
    item["input_files"] = {view: str(output / "inputs" / Path(path).name)
                           for view, path in canonical_files.items()}
    write(output / "submission.intent.json", item, exclusive=True)
    if any((output / name).exists() for name in ("submission.json", "task.json", "task_status.json")):
        raise ValueError("A receipt appeared after planning; reconcile the existing job")
    (output / "inputs").mkdir(exist_ok=False)
    # Upload these exact bytes, never a mutable source path. Hash each byte
    # buffer immediately before saving its exclusive per-submission snapshot.
    for view, path in canonical_files.items():
        contents = Path(path).read_bytes()
        if hashlib.sha256(contents).hexdigest() != item["sha256"][view]:
            raise ValueError("Canonical input changed while freezing submission: " + view)
        with Path(item["input_files"][view]).open("xb") as stream:
            stream.write(contents)
    command = cli + ["generate", item["generation_type"], *item["input_files"].values(), "--model", item["model_alias"]]
    for key, value in item["parameters"].items():
        if key == "model":
            continue
        command += ["-p", key + "=" + json.dumps(value, separators=(",", ":"))]
    command += ["--name", "civwar-" + item["asset_id"].lower() + "-" + item["version"],
                "--out", str(output), "--no-wait", "--no-open", "--yes", "--json"]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=240)
    except subprocess.TimeoutExpired:
        write(output / "submission.uncertain.json", {"status": "timeout_unknown_outcome", "automatic_retry": False})
        raise
    (output / "submission.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output / "submission.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("CLI returned an error; inspect saved intent and response, never automatically retry")
    receipt = json.loads(result.stdout)
    if not receipt.get("task_id"):
        raise ValueError("No task ID; outcome requires reconciliation")
    write(output / "submission.json", receipt)
    print(json.dumps({"asset": item["asset_id"], **{key: receipt.get(key) for key in ("task_id", "status", "type")}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset")
    parser.add_argument("--version", required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--single-front-review")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    item = plan(args.asset, args.version, args.preset, args.single_front_review)
    if args.submit:
        submit(item)
    else:
        print(json.dumps(item, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
