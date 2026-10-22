"""Produce an inactive runtime base entry from a real successful UE import."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def prepare(report_path, measurement_path, output_path):
    report_path, measurement_path, output_path = map(resolve, (report_path, measurement_path, output_path))
    report, measurement = read(report_path), read(measurement_path)
    if (report["kind"] != "base" or report["status"] != "imported_static_pending_gameplay"
            or report["failures"] or not report["full_pbr"]):
        raise ValueError("Expected successful full-PBR static base import")
    manifest = read(report["source_manifest"])
    if sha(report["source_manifest"]) != report["source_manifest_sha256"]:
        raise ValueError("Imported manifest changed")
    if (manifest["source"]["sha256"] != measurement["source"]["sha256"]
            or report["anchors_cm"] != measurement["anchors_cm"]
            or set(measurement["anchors_cm"]) != {"turret_0", "turret_1", "turret_2"}):
        raise ValueError("Platform measurements do not match imported source")
    if len(report["packages"]) == 0:
        raise ValueError("No saved packages")
    for package in report["packages"]:
        if sha(package["path"]) != package["sha256"]:
            raise ValueError("Saved package changed: " + package["path"])
    entry = {"asset_id": report["asset_id"], "kind": "static_base",
             "enabled": False, "default_runtime_enabled": False, "preview_enabled": False,
             "parts": [{"id": "body", "static_mesh": report["static_mesh"],
                        "team_materials": report["team_materials"]}],
             "anchors_cm": report["anchors_cm"],
             "source_import_report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
             "anchor_measurement": str(measurement_path.relative_to(ROOT)).replace("\\", "/"),
             "gameplay_status": "pending_root_gameplay",
             "production_approved": False}
    result = {"schema_version": 1, "runtime_entry": entry,
              "cook_directories": [report["destination"]],
              "source": manifest["source"],
              "import_report": {"path": str(report_path), "sha256": sha(report_path)},
              "dimensions_cm": report["dimensions_cm"],
              "verified_saved_packages": len(report["packages"]),
              "actual_triangle_count": report["bounds_cm"]["triangles"],
              "bounds_error_cm": report["bounds_cm"]["max_error_cm"],
              "dcc_views": [str(Path(report["source_manifest"]).parent / name)
                            for name in ("preview_front.png", "preview_back.png")]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--measurements", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = prepare(args.report, args.measurements, args.output)
    print(json.dumps({"asset_id": result["runtime_entry"]["asset_id"],
                      "packages": result["verified_saved_packages"],
                      "bounds_error_cm": result["bounds_error_cm"]}))


if __name__ == "__main__":
    main()
