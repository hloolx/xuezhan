from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_images(report_path):
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    images = {}
    records = {}
    for record in report["images"]:
        if record["label"].startswith(("original_", "disabled_")):
            if sha(record["path"]) != record["sha256"]:
                raise ValueError("Actual capture image changed: " + record["label"])
            with Image.open(record["path"]) as image:
                if image.size != (512, 512):
                    raise ValueError("Unexpected comparison image dimensions")
                images[record["label"]] = np.asarray(image.convert("RGB"), dtype=np.int16)
            records[record["label"]] = {name: record[name] for name in ("path", "sha256")}
    return report, images, records


def stats(first, second, mask):
    signed = second[mask].astype(np.float64) - first[mask]
    absolute = np.abs(signed)
    pixel_maximum = absolute.max(axis=1)
    return {"pixels": int(mask.sum()), "mean_absolute_channel_error_8bit": float(absolute.mean()),
            "root_mean_square_channel_error_8bit": float(np.sqrt(np.mean(signed ** 2))),
            "maximum_channel_error_8bit": int(absolute.max()),
            "absolute_channel_error_percentiles": {str(percent): float(np.percentile(absolute, percent)) for percent in (50, 95, 99)},
            "changed_pixel_percent": float(np.mean(pixel_maximum > 0) * 100),
            "pixel_percent_above_channel_error": {str(limit): float(np.mean(pixel_maximum > limit) * 100) for limit in (2, 5, 10, 20)},
            "mean_signed_rgb_error_8bit": signed.mean(axis=0).tolist(), "bit_exact": bool(not np.any(absolute))}


def compare(first, second, crop):
    all_pixels = np.ones(first.shape[:2], dtype=bool)
    foreground = np.maximum(first.max(axis=2), second.max(axis=2)) > 6
    result = {"whole_frame": stats(first, second, all_pixels), "nonblack_union": stats(first, second, foreground)}
    if crop == "face":
        face_roi = np.zeros(first.shape[:2], dtype=bool)
        face_roi[230:375, 180:330] = True
        result["fixed_face_interior_roi"] = stats(first, second, face_roi)
        result["fixed_face_interior_roi_xyxy"] = [180, 230, 330, 375]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Do not overwrite previous control analysis")
    report, images, records = read_images(args.report)
    required = [f"{prefix}_{crop}" for prefix in ("original", "disabled", "original_repeat") for crop in ("front", "face")]
    if not all(label in images for label in required):
        raise ValueError("Original->disabled->original six actual control captures required")
    comparison = {}
    for crop in ("front", "face"):
        comparison[crop] = {}
        for label, first, second in (("original_vs_disabled", "original", "disabled"),
                                      ("original_vs_original_repeat", "original", "original_repeat"),
                                      ("disabled_vs_original_repeat", "disabled", "original_repeat")):
            comparison[crop][label] = compare(images[f"{first}_{crop}"], images[f"{second}_{crop}"], crop)
    native = [record["actual_pose_check"]["actual_texture_residency"] for record in report["images"]]
    resident_pass = all(len(records) == 5 and all(record["actual_resident_size"] == [2048, 2048] and record["maximum_allowed_size"] == [2048, 2048]
                                                 for record in records.values()) for records in native)
    if not resident_pass or not all(record["equal"] for record in report["original_vs_derived_sampler_audit"].values()):
        raise ValueError("Native per-shot residency or original/derived sampler equality did not pass")
    output = {"schema_version": 1, "status": "actual_control_pixel_and_native_resource_diagnostic_complete_not_bitexact_approval",
              "created_at": datetime.now(timezone.utc).isoformat(), "source_report": {"path": str(args.report.resolve()), "sha256": sha(args.report)},
              "source_images": records, "comparisons": comparison, "images_modified": False,
              "metric_space": "Decoded8bit PNG RGB channel errors; not linear-light shader radiance or perceptual error threshold",
              "native_resource_evidence": {"initial_before_force": report["initial_residency_before_force"],
                                           "all14_shots_all5_textures_actual2048": resident_pass,
                                           "sampler_uv_attributes_equal": True, "frozen21package_bytes_unchanged": report["original_and_derived_asset_bytes_unchanged"]},
              "interpretation": [
                  "Before compilation flush/residency preparation, all five native texture records were32x32/PF_B8G8R8A8; after preparation every actual captured shot used2048x2048 final resources.",
                  "Installed Texture2D.cpp:344-409 explicitly returns placeholder dimensions and format while texture platform data compiles. This confirms transient unready resources in the measured02 process, not a UV or original material edit.",
                  "Review01 has no per-shot native resource samples, so its exact capture-time resource states cannot be retroactively proven. The observed control mismatch disappears after explicit preparation and actual residency gates in02.",
                  "Original-versus-original-repeat is the same-material temporal baseline. Compare derivative Strength0 error against that baseline; temporal AA, shadow sampling and quantization can produce nonzero image differences even without a material change.",
                  "No bitexact equivalence is asserted. Image differences are measured in final PNG space and cannot isolate each renderer noise source. Root visual control review and exact material graph identity at Strength0 are separate evidence.",
                  "14 controlled editor captures do not establish live gameplay visibility or performance."
              ], "runtime_approved": False, "production_approved": False}
    if args.previous_report:
        old_report, old_images, old_records = read_images(args.previous_report)
        output["previous_failed_control"] = {"report": str(args.previous_report.resolve()), "sha256": sha(args.previous_report),
                                              "comparisons": {crop: compare(old_images[f"original_{crop}"], old_images[f"disabled_{crop}"], crop) for crop in ("front", "face")}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {crop: {name: record["whole_frame"]["mean_absolute_channel_error_8bit"] for name, record in values.items()} for crop, values in comparison.items()}
    print(json.dumps({"output": str(args.output), "comparison_wholeframe_mae": summary}))


if __name__ == "__main__":
    main()
