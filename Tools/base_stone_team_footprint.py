from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import base_stone_team_ue as team


def triangle_texel_support(uv, width, height):
    triangle = np.asarray(uv, dtype=np.float64) * (width, height)
    if triangle.shape != (3, 2) or not np.isfinite(triangle).all():
        raise ValueError("Expected finite triangle UVs")
    minimum = np.maximum(np.floor(triangle.min(axis=0)).astype(int), 0)
    maximum = np.minimum(np.ceil(triangle.max(axis=0)).astype(int), (width - 1, height - 1))
    if np.any(maximum < minimum):
        return None
    horizontal, vertical = np.meshgrid(np.arange(minimum[0], maximum[0] + 1) + .5, np.arange(minimum[1], maximum[1] + 1) + .5)
    support = np.ones(horizontal.shape, dtype=bool)
    edges = np.roll(triangle, -1, axis=0) - triangle
    axes = [(1., 0.), (0., 1.)] + [(-edge[1], edge[0]) for edge in edges]
    for axis_x, axis_y in axes:
        projection = triangle[:, 0] * axis_x + triangle[:, 1] * axis_y
        centers = horizontal * axis_x + vertical * axis_y
        radius = .5 * (abs(axis_x) + abs(axis_y))
        support &= (centers + radius >= projection.min() - 1e-8) & (centers - radius <= projection.max() + 1e-8)
    return (slice(minimum[1], maximum[1] + 1), slice(minimum[0], maximum[0] + 1)), support


def dilate(mask, radius=1):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(1 + radius * 2))) > 0


def derive_mask(selected_support, protected_support, blue):
    return selected_support & blue & ~dilate(protected_support, 1)


def main():
    output = team.TEAM / "main_cloth_candidate_v03_nearest_footprint"
    if output.exists():
        raise FileExistsError("Never overwrite candidate evidence")
    context = team.source_inputs()
    analysis_path = team.TEAM / "region_diagnostic_v01/region_analysis.json"
    analysis = team.read(analysis_path)
    selected_report = team.read(team.TEAM / "main_cloth_candidate_v02_safe1/candidate_mask_report.json")
    probe_path = team.TEAM / "ue_color_review_04/pixel_geometry_diagnostic.json"
    probes = team.read(probe_path)
    selected = set(selected_report["selected_source_triangles"])
    if len(selected) != 714 or analysis["source"]["sha256"] != team.SOURCE_SHA:
        raise ValueError("Original714 selected source faces are mandatory")
    rgb = np.asarray(Image.open(team.ROOT / selected_report["base_color"]["file"]).convert("RGB"), dtype=float) / 255
    blue = (rgb[:, :, 2] > rgb[:, :, 0] * 1.12) & (rgb[:, :, 2] > rgb[:, :, 1] * 1.03) & (rgb[:, :, 2] - rgb[:, :, 0] > .018)
    selected_support = np.zeros((2048, 2048), dtype=bool)
    protected_support = np.zeros_like(selected_support)
    for item in analysis["triangles"]:
        raster = triangle_texel_support(item["uv_gltf_top_left"], 2048, 2048)
        if raster is not None:
            region, support = raster
            destination = selected_support if item["source_glb_triangle"] in selected else protected_support
            destination[region] |= support
    mask = derive_mask(selected_support, protected_support, blue)
    protected_neighborhood = dilate(protected_support, 1)
    old_mask = np.asarray(Image.open(team.ROOT / selected_report["mask"]["file"])) > 0
    protected_overlap = int((mask & protected_support).sum())
    protected_filter_overlap = int((dilate(mask, 1) & protected_support).sum())
    if protected_overlap or protected_filter_overlap or (mask & ~blue).any() or (mask & ~selected_support).any():
        raise ValueError("Conservative sampler support or pigment gate failed")
    grouped = {}
    probe_rows = []
    for row in probes["source_uv_probes"]:
        horizontal, vertical = row["atlas_pixel"]
        region = (slice(max(0, vertical - 1), min(2048, vertical + 2)), slice(max(0, horizontal - 1), min(2048, horizontal + 2)))
        category = row["classification"]
        summary = grouped.setdefault(category, Counter())
        summary["points"] += 1
        summary["old_mask_on"] += int(old_mask[vertical, horizontal])
        summary["new_mask_on"] += int(mask[vertical, horizontal])
        summary["new3x3_mask_on_total"] += int(mask[region].sum())
        probe_rows.append({"screen_pixel": row["pixel"], "source_triangle": row["source_triangle"], "prior_classification": category,
                           "atlas_pixel": row["atlas_pixel"], "old_mask_on": bool(old_mask[vertical, horizontal]), "new_mask_on": bool(mask[vertical, horizontal]),
                           "selected_sampler_support": bool(selected_support[vertical, horizontal]), "blue_pigment": bool(blue[vertical, horizontal]),
                           "protected_sampler_support": bool(protected_support[vertical, horizontal]),
                           "protected_one_pixel_neighbor": bool(protected_neighborhood[vertical, horizontal]),
                           "old3x3_on": int(old_mask[region].sum()), "new3x3_on": int(mask[region].sum())})
    main_group = grouped["nearest_texel_center_outside_selected714_uv_coverage"]
    if main_group["points"] != 30 or main_group["new_mask_on"] != 30:
        raise ValueError("Exact30diagnosed nearest-texel UV holes were not all resolved numerically")
    output.mkdir(parents=True)
    mask_path = output / "T_Base_Stone_MainClothMask_FOOTPRINT_CANDIDATE.png"
    Image.fromarray(mask.astype(np.uint8) * 255).save(mask_path)
    report = {"status": "nearest_sampler_footprint_candidate_numeric_only_pending_actual_ue_controls",
              "tool": team.file_record(__file__), "source": context["source_glb"], "base_color": selected_report["base_color"],
              "prior_safe1_mask": selected_report["mask"], "analysis": team.file_record(analysis_path), "actual_ray_probe_evidence": team.file_record(probe_path),
              "mask": team.file_record(mask_path), "selected_clusters": [0, 1, 3, 4, 7], "held_clusters": [2, 5, 6, 8],
              "selected_source_triangles": sorted(selected), "selected_triangle_count": len(selected),
              "method": "Separating-axis intersection of approved source UV triangle with each texel square, including degenerate point/line support. Nonselected triangles use identical conservative support. Remove its1pixel neighborhood. Intersect unchanged original blue-pigment predicate; no blur, no arbitrary atlas dilation, no new semantic triangles.",
              "selected_sampler_support_pixels": int(selected_support.sum()), "protected_sampler_support_pixels": int(protected_support.sum()),
              "old_mask_pixels": int(old_mask.sum()), "mask_pixels": int(mask.sum()), "added_pixels": int((mask & ~old_mask).sum()),
              "removed_pixels_for_stricter_protected_sampler_support": int((old_mask & ~mask).sum()),
              "protected_sampler_overlap_pixels": protected_overlap, "one_pixel_filter_footprint_protected_overlap_pixels": protected_filter_overlap,
              "pale_or_nonblue_pixels_recolored": int((mask & ~blue).sum()), "outside_selected_sampler_support_pixels": int((mask & ~selected_support).sum()),
              "probe_groups": grouped, "probes": probe_rows,
              "white_emblem_policy": "Preserve original nonblue predicate exactly; do not recolor pale antialias edge merely to erase halo.",
              "required_sampler_policy": "Unchanged NonColor/Grayscale/NoMipmaps/Nearest/Clamp with asset sampler; actual mip/alias acceptance not implied.",
              "mesh_edited": False, "source_modified": False, "original_or_derived_ue_packages_modified": False,
              "all_cloth_coverage_approved": False, "actual_ue_color_approved": False, "production_approved": False}
    team.check_records(context["frozen_packages"] + context["source_evidence"])
    (output / "candidate_mask_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mask_pixels", "added_pixels", "removed_pixels_for_stricter_protected_sampler_support", "protected_sampler_overlap_pixels", "one_pixel_filter_footprint_protected_overlap_pixels", "probe_groups")}, indent=2))


if __name__ == "__main__":
    main()
