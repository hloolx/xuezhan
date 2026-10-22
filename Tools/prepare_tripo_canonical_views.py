"""Copy design-view pixels into the experimentally verified Tripo API convention.

API left <- design right; API right <- design left. Front/back unchanged.
No mirroring, image processing, network requests, or paid generation occurs.
Existing canonical pixels are immutable; a changed source needs a new output root.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "RawAssets/Art/Tripo_v01"
VIEW_MAP = {"front": "front", "right": "left", "back": "back", "left": "right"}
API_ORDER = ["front", "left", "back", "right"]
SOURCE_GROUPS = ["prepared_characters_v02", "prepared_environment_tripo", "prepared_architecture_tripo", "prepared_turrets_tripo", "prepared_support_tripo"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path, root):
    return path.relative_to(root).as_posix()


def probe_evidence(root):
    folder = root / "RawAssets/Art/Tripo_v01/reviews/tripo_view_convention_probe"
    task = read(folder / "task.json")
    if task["task_id"] != "e175fe52-8f3b-4808-8d54-0f6fad6684b5" or task["status"] != "success":
        raise ValueError("Expected successful official image-to-multiview convention probe")
    return {"task_id": task["task_id"], "task_type": task["type"], "task_file": rel(folder / "task.json", root),
            "task_file_sha256": sha(folder / "task.json"), "observed_api_convention": {
                "left": "Subject nose points toward image LEFT", "right": "Subject nose points toward image RIGHT"},
            "files": {name: {"path": rel(folder / f"generate_multiview_image.{name}_view.jpeg", root),
                              "sha256": sha(folder / f"generate_multiview_image.{name}_view.jpeg")}
                      for name in ("left", "right")},
            "validation_limit": "Image-to-multiview directional semantics verified visually; corrected multiview-to-model pilot still required."}


def prepare(source, destination, root, probe):
    original = read(source / "upload_manifest.json")
    aid = original["asset"]
    if source.name != aid or destination.name != aid:
        raise ValueError("Asset ID/folder mismatch")
    rows = {}
    for design_view, filename in original["files"].items():
        api_view = VIEW_MAP[design_view]
        path = source / filename
        if path.resolve().parent != source.resolve():
            raise ValueError("Input image must be a direct file in its asset folder")
        with Image.open(path) as image:
            if image.size != (1024, 1024) or image.mode != "RGB":
                raise ValueError(f"{aid}/{filename}: expected 1024 RGB")
        rows[api_view] = {"source_design_view": design_view, "source_path": rel(path, root), "source_sha256": sha(path),
                          "canonical_file": api_view + path.suffix.lower(), "pixel_operation": "byte_identical_copy"}
    required = [VIEW_MAP[view] for view in original["project_required_views"]]
    missing = [view for view in required if view not in rows]
    if missing:
        raise ValueError(aid + " is missing required API views: " + ",".join(missing))
    lock = {name: {"source_sha256": row["source_sha256"], "source_design_view": row["source_design_view"]} for name, row in rows.items()}
    metadata_path = destination / "canonical_metadata.json"
    previous = read(metadata_path) if metadata_path.exists() else None
    if previous and (previous["input_lock"] != lock or previous["project_required_views"] != required):
        raise ValueError(aid + ": existing canonical input is frozen; use a new output root for revised source pixels")
    for api_view, row in rows.items():
        output = destination / row["canonical_file"]
        if output.exists() and sha(output) != row["source_sha256"]:
            raise ValueError(aid + ": existing canonical file differs, refusing overwrite: " + output.name)
    destination.mkdir(parents=True, exist_ok=True)
    for row in rows.values():
        output = destination / row["canonical_file"]
        if not output.exists():
            shutil.copyfile(root / row["source_path"], output)
        if sha(output) != row["source_sha256"]:
            raise ValueError("Canonical byte-copy hash mismatch")
        row["canonical_sha256"] = sha(output)
    manifest_path = destination / "upload_manifest.json"
    prior_manifest = read(manifest_path) if manifest_path.exists() else {}
    validation = prior_manifest.get("canonical_mapping_validation", (previous or {}).get("canonical_mapping_validation", {"status": "pending_minimal_model_pilot", "approved": False, "evidence": []}))
    metadata = {"schema_version": 1, "asset_id": aid, "source_group": source.parent.name,
                "source_manifest": rel(source / "upload_manifest.json", root), "source_manifest_sha256": sha(source / "upload_manifest.json"),
                "created_at": (previous or {}).get("created_at", datetime.now(timezone.utc).isoformat()),
                "design_to_api_view_map": VIEW_MAP, "api_to_design_view_map": VIEW_MAP,
                "files": rows, "input_lock": lock, "project_required_views": required,
                "probe_evidence": probe, "canonical_mapping_validation": validation,
                "source_reference_approval": {"approved": original.get("production_approved", False), "scope": original.get("approval_scope"),
                                              "approved_source_sha256": original.get("approved_source_sha256"),
                                              "approved_design_view_sha256": original.get("approved_view_sha256")},
                "production_model_approved": False, "submitted_by_this_script": False}
    files = {name: rows[name]["canonical_file"] for name in API_ORDER if name in rows}
    # Preserve original reference approval and its limited scope; it never grants
    # approval to the new mapping, model, rig, textures or runtime integration.
    manifest = {**original, **prior_manifest, "files": files, "missing_views": [v for v in API_ORDER if v not in rows],
                "project_required_views": required, "project_missing_views": missing,
                "view_convention": "tripo_api_canonical_probe_e175fe52", "canonical_mapping_validation": validation,
                "reference_approved": original.get("production_approved", False),
                "reference_approval_scope": original.get("approval_scope"),
                "canonical_metadata": "canonical_metadata.json",
                "legacy_positional_order": API_ORDER,
                "legacy_local_file_map_not_api_request": [files.get(v, "") for v in API_ORDER],
                "note": "API-direction files only. API left is design right; API right is design left. Byte-identical copied pixels, never mirrored. Original approval scope retained; corrected model pilot pending."}
    if original.get("approved_view_sha256"):
        manifest["approved_view_sha256"] = {VIEW_MAP[k]: value for k, value in original["approved_view_sha256"].items()}
    template = read(source / "tripo_request.template.json")
    preset = original.get("generation_preset")
    if template.get("disabled") and preset:
        presets = read(root / "RawAssets/Art/Tripo_v01/generation_presets.json")
        template = dict(presets["presets"][preset]["parameters"])
    if preset is None and template.get("disabled"):
        # Mechanical design-only references must not become paid requests merely
        # because their view filenames have been canonicalized.
        template.pop("inputs", None)
        template.update({"disabled": True, "contains_api_inputs": False,
                         "reason": "Design-only/deferred asset without generation preset; canonical images do not authorize Tripo generation"})
    else:
        template["inputs"] = [{view: "REPLACE_WITH_" + view.upper() + "_FILE_TOKEN_OR_PUBLIC_URL"} for view in API_ORDER if view in files]
    write(metadata_path, metadata)
    write(destination / "upload_manifest.json", manifest)
    write(destination / "tripo_request.template.json", template)
    return {"asset_id": aid, "source_group": source.parent.name, "output": rel(destination, root), "views": list(files),
            "project_required_views": required, "reference_approved": original.get("production_approved", False),
            "canonical_mapping_validation": validation["status"], "status": "copied_verified_no_mirroring"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--asset", action="append", help="Limit to asset ID; repeat for multiple pilot assets")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    art = root / "RawAssets/Art/Tripo_v01"
    output = args.output_root.resolve() if args.output_root else art / "prepared_tripo_canonical"
    probe = probe_evidence(root)
    sources = {}
    for group in SOURCE_GROUPS:
        for manifest in sorted((art / group).glob("*/upload_manifest.json")):
            aid = manifest.parent.name
            if aid in sources:
                raise ValueError("Ambiguous prepared asset: " + aid)
            sources[aid] = manifest.parent
    ids = args.asset or sorted(sources)
    results = []
    for aid in ids:
        if aid not in sources:
            raise ValueError("No prepared source for " + aid)
        results.append(prepare(sources[aid], output / aid, root, probe))
    report_path = output / "preparation_report.json"
    prior = read(report_path).get("results", []) if report_path.exists() else []
    combined = {row["asset_id"]: row for row in prior + results}
    report = {"schema_version": 1, "prepared_at": datetime.now(timezone.utc).isoformat(), "asset_count": len(combined),
              "submitted_by_this_script": False, "results": sorted(combined.values(), key=lambda row: row["asset_id"])}
    write(report_path, report)
    print(json.dumps({"processed_count": len(results), "total_count": len(combined), "assets": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
