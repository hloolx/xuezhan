from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_footprint_ue as team
import base_stone_team_render as renderer
from base_stone_team_pixel_diagnostic import pair_metrics


REGIONS = {
    "wide": {"roof": [170, 245, 265, 275], "platform_top": [263, 297, 296, 308],
             "gate_wood": [171, 339, 192, 361], "ground": [50, 450, 180, 480]},
    "flag": {"left_wood_and_rope": [70, 160, 128, 370], "right_wood_and_rope": [388, 166, 465, 365],
             "top_wood": [200, 20, 280, 65], "pale_emblem_left_ring_core": [197, 243, 202, 265],
             "cloth_interior": [154, 136, 357, 375]},
}


def residual_blue(original, tinted):
    original, tinted = original.astype(float), tinted.astype(float)
    residual = (tinted[:, :, 2] > tinted[:, :, 0] * 1.1) & (tinted[:, :, 2] > tinted[:, :, 1] * 1.01)
    residual &= (tinted[:, :, 2] - tinted[:, :, 0] > 5)
    scope = np.zeros((512, 512), dtype=bool)
    scope[108:420, 135:383] = True
    return int((residual & scope & (np.max(np.abs(original - tinted), axis=2) < 12)).sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", type=Path, default=team.TEAM / "ue_fresh_03.json")
    parser.add_argument("--folder", type=Path, default=team.TEAM / "ue_color_review_05")
    args = parser.parse_args()
    output = args.folder / "control_pixel_diagnostic.json"
    if output.exists():
        raise FileExistsError("Preserve prior control evidence; choose a new actual render folder")
    renderer.team = team
    context = renderer.check_team_report(args.fresh)
    report_path = args.folder / "ue_render_report.json"
    report = team.read(report_path)
    if report.get("status") != "actual8images_captured_pending_visual_and_pixel_control_review" or report.get("actual_images") != 8:
        raise ValueError("A completed actual eight-image capture is required")
    expected = {mode + "_" + view for mode in ("original", "disabled", "blue", "red") for view in ("wide", "flag")}
    if len(report["images"]) != 8 or {item["label"] for item in report["images"]} != expected:
        raise ValueError("Matched controls are incomplete")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    team.check_records(records)
    packages = {item["path"]: item for item in records if Path(item["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 34:
        raise ValueError("Expected original26, previous4 and current4 immutable packages")
    textures = set(context["original_textures"] + [context["result"]["mask"]])
    images, image_evidence = {}, []
    for item in report["images"]:
        team.shared.check_record(item)
        image = np.asarray(Image.open(item["path"]).convert("RGB"))
        if image.shape != (512, 512, 3):
            raise ValueError("Actual image dimensions changed")
        resident = item["actual_check"]["actual_texture_residency"]
        if not renderer.textures_resident(resident, textures):
            raise ValueError("All four textures must actually be resident at2048 per shot")
        images[item["label"]] = image
        image_evidence.append({"label": item["label"], **team.file_record(item["path"]),
                               "all4textures_resident2048": True, "actual_check": item["actual_check"]})
    comparisons = {}
    for view in ("wide", "flag"):
        original = images["original_" + view]
        comparisons[view] = {
            mode: {"whole_image": pair_metrics(original, images[mode + "_" + view]),
                   "manual_roi": {name: {"rectangle": rectangle, **pair_metrics(original, images[mode + "_" + view], rectangle)}
                                  for name, rectangle in REGIONS[view].items()}}
            for mode in ("disabled", "blue", "red")}
    residual = residual_blue(images["original_flag"], images["red_flag"])
    result = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "actual_eight_controls_and34package_hashes_verified_requires_separate_visual_review",
        "tool": team.file_record(__file__), "fresh_report": team.file_record(args.fresh),
        "render_report": team.file_record(report_path), "actual_render_process_id": report["execution_process_id"],
        "images": image_evidence, "comparisons": comparisons,
        "residual_blue_pixels_in_same_front_flag_scope": residual,
        "residual_test_limit": "Same finite screen-space heuristic as rejected04; nonzero fringe is not automatically a defect and zero is not a whole-surface semantic proof.",
        "native4textures_resident2048_all8shots": True, "package_count": len(packages),
        "verified_package_records": list(packages.values()), "all34packages_unchanged": True,
        "source_records_verified": context["source_evidence"], "all_source_records_unchanged": True,
        "source_glb": context["source_glb"], "mask_source": context["mask_source"],
        "root_only_runtime_execution": True, "runtime_approved": False, "production_approved": False,
        "limitations": "ROIs are finite negative controls, not exhaustive hidden-surface coverage. Image differences include temporal/shadow noise; source semantic mask protection is independently audited. No image, package, source texture or geometry modified.",
    }
    team.check_records(records)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "packages": len(packages), "residual_blue_pixels": residual,
                      "controls": {view: comparisons[view]["disabled"]["whole_image"] for view in comparisons},
                      "regions": {view: {mode: comparisons[view][mode]["manual_roi"] for mode in ("blue", "red")} for view in comparisons}}, indent=2))


if __name__ == "__main__":
    main()
