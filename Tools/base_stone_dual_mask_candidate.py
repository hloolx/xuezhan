from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_side_emblem_ue as previous
from base_stone_team_emblem import INSPECTION_RECTANGLE
from base_stone_team_footprint import triangle_texel_support
from base_stone_side_emblem_diagnostic import inputs, continuous_mask, save_json


FOLDER = previous.FOLDER / "dual_mask_v01"


def bilinear_sample(image, uv):
    height, width = image.shape
    position = np.asarray(uv, dtype=float) * (width, height) - .5
    lower = np.floor(position).astype(int)
    fraction = position - lower
    samples = []
    total = 0.0
    for delta_y in (0, 1):
        for delta_x in (0, 1):
            column, row = np.clip(lower + (delta_x, delta_y), (0, 0), (width - 1, height - 1)).tolist()
            weight = (fraction[0] if delta_x else 1 - fraction[0]) * (fraction[1] if delta_y else 1 - fraction[1])
            value = float(image[row, column]) / 255
            total += weight * value
            samples.append({"pixel": [column, row], "weight": float(weight), "value": value})
    return float(total), samples


def sample_dual(guard, protection, uv):
    column, row = np.clip(np.floor(np.asarray(uv) * (guard.shape[1], guard.shape[0])).astype(int), (0, 0), (guard.shape[1] - 1, guard.shape[0] - 1)).tolist()
    nearest = float(guard[row, column]) / 255
    value, samples = bilinear_sample(protection, uv)
    return {"uv": list(uv), "guard_nearest_texel": [column, row], "guard": nearest,
            "protection_bilinear": value, "final_tint_weight": nearest * (1 - value), "four_samples": samples}


def build():
    if FOLDER.exists():
        raise FileExistsError("Preserve prior candidate")
    context, records, packages = inputs()
    original = previous.read(previous.FOLDER / "candidate_v02/candidate_report.json")
    guard = np.asarray(Image.open(original["prior_mask"]["path"]))
    binary = np.asarray(Image.open(original["new_mask"]["path"]))
    unused, excluded, occupancy = continuous_mask(guard, binary)
    protection = excluded.astype(np.uint8) * 255
    core = excluded & (occupancy == 16)
    support = np.asarray(Image.fromarray(protection).filter(ImageFilter.MaxFilter(3))) > 0
    if int(excluded.sum()) != 1217 or int(core.sum()) != 613:
        raise ValueError("Semantic scope/core changed")
    analysis = previous.read(previous.TEAM / "region_diagnostic_v01/region_analysis.json")
    target = set(next(item for item in analysis["clusters"] if item["cluster_id"] == 0)["source_glb_triangles"])
    other_support = np.zeros_like(excluded)
    target_support = np.zeros_like(excluded)
    for triangle in analysis["triangles"]:
        raster = triangle_texel_support(triangle["uv_gltf_top_left"], 2048, 2048)
        if raster is not None:
            region, triangle_support = raster
            collection = target_support if triangle["source_glb_triangle"] in target else other_support
            collection[region] |= triangle_support
    effective_support = support & (guard > 0)
    other_affected = int((effective_support & other_support).sum())
    if other_affected:
        raise ValueError("Bilinear protection would affect another source triangle: " + str(other_affected))
    footprint = previous.read(previous.TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json")
    front_probes = []
    for probe in footprint["probes"]:
        column, row = probe["atlas_pixel"]
        if support[row, column]:
            raise ValueError("Front-probe texel cell can sample protection")
        front_probes.append({"atlas_pixel": probe["atlas_pixel"], "protection_zero_across_entire_cell": True,
                             "final_guard_unchanged": bool(guard[row, column]) == probe["new_mask_on"]})
    spec = previous.read(previous.FOLDER / "spec.json")
    game_probes = [dict(probe, dual_sample=sample_dual(guard, protection, probe["source_uv"])) for probe in spec["verified_atlas_ring_samples"]]
    edge_report = previous.read(previous.FOLDER / "ue_control_review_01/pixel_diagnostic.json")
    edge_texels = []
    for pair in edge_report["finite_edge_ray_samples"]:
        samples = []
        for sample in pair["samples"]:
            column, row = sample["atlas_pixel"]
            samples.append({"pixel": [column, row], "binary_protection": int(protection[row, column]),
                            "bilinear_at_texel_center": sample_dual(guard, protection, [(column + .5) / 2048, (row + .5) / 2048])})
        edge_texels.append({"region": pair["region"], "samples": samples})
    atlas_path = previous.ROOT / original["source_atlas"]["file"]
    atlas = Image.open(atlas_path).convert("RGB")
    FOLDER.mkdir()
    protection_path = FOLDER / "T_Base_Stone_SideEmblemProtection.png"
    Image.fromarray(protection).save(protection_path)
    tool_snapshot = FOLDER / "generator_snapshot.py"
    tool_snapshot.write_bytes(Path(__file__).read_bytes())
    crop = Image.fromarray(protection).crop(INSPECTION_RECTANGLE)
    weight_preview = np.asarray(crop.resize((crop.width * 6, crop.height * 6), Image.Resampling.BILINEAR))
    source_crop = atlas.crop(INSPECTION_RECTANGLE).resize((crop.width * 6, crop.height * 6), Image.Resampling.NEAREST)
    strength = weight_preview.astype(float) / 255 * .65
    overlay = np.rint(np.asarray(source_crop) * (1 - strength[:, :, None]) + np.asarray((255, 225, 20)) * strength[:, :, None]).astype(np.uint8)
    previews = {}
    for name, image in {"atlas_source_crop_x6": source_crop, "bilinear_protection_preview_x6": Image.fromarray(weight_preview),
                        "atlas_bilinear_weight_overlay_x6": Image.fromarray(overlay)}.items():
        path = FOLDER / (name + ".png")
        image.save(path)
        previews[name] = previous.file_record(path)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "dual_mask_sampling_support_verified_pending_root_candidate_review_and_ue",
              "tool": previous.file_record(tool_snapshot), "source_glb": context["source_glb"], "source_atlas": original["source_atlas"],
              "guard_mask": original["prior_mask"], "protection_mask": previous.file_record(protection_path),
              "binary_candidate_report": previous.file_record(previous.FOLDER / "candidate_v02/candidate_report.json"),
              "actual_failure_review": previous.file_record(previous.FOLDER / "ue_control_review_01/visual_review.json"),
              "previews": previews, "formula": "FinalTint = FootprintNearest * (1 - LocalProtectionBilinear) * saturate(TeamColorStrength)",
              "guard_sampling": "Frozen exact-footprint2048/NonColor/NoMipmaps/Nearest/Clamp; unchanged714faces, held6, pigment and noncloth1px guard.",
              "protection_sampling": "Independent2048/NonColor/NoMipmaps/Bilinear/Clamp texture: exactly1217 semantic texels1, everything else0. Not the preweighted candidate; do not double-erode.",
              "local_protection_texels": 1217, "fully_protected_entire_texel_cells": 613, "partial_boundary_texel_cells": 604,
              "bilinear_possible_support_texel_cells": int(support.sum()),
              "effective_protection_possible_texel_cells_after_guard": int(effective_support.sum()),
              "possible_fringe_cells_outside_binary1217": int((effective_support & ~excluded).sum()),
              "effective_possible_support_on_other_source_triangles": other_affected,
              "guard_maximum_dye_weight_unchanged": True, "new_noncloth_or_held_dye_support": 0,
              "noncloth_direct_and1px_overlap": 0,
              "support_proof": "For any continuous UV, guard is0or1 and bilinearProtection is a convex combination of0/1 texels. Hence0<=FinalTint<=guard pointwise. No guard-zero region can gain dye regardless of protection footprint. Additional source-triangle footprint intersection confirms effective protection fringe touches only cluster0; no other source face is affected.",
              "core_proof": "Each of613core texels has all3x3protection neighbors1. Across its entire nearest-texel cell, every possible bilinear2x2support is within those neighbors; therefore protection=1 and final tint=0 for every fractional UV in that cell.",
              "boundary_limit": "604boundary cells have fractional protection. Also the half-texel bilinear footprint can reduce dye in adjacent already-selected cloth cells. This cannot add noncloth dye, but must be visually checked for residual halos and stroke thinning.",
              "actual_game_uv_probes": game_probes, "previous_actual_edge_texel_probes": edge_texels,
              "front45_entire_cells_unchanged": front_probes, "previous30_uv_gap_points_still_on": True,
              "all38_existing_packages_unchanged": True, "source_atlas_mesh_uv_unchanged": True,
              "original_selected_faces": 714, "held_faces": 6,
              "preview_limit": "Bilinear zoom is a mathematical texture-sampling preview, not actual UE shading or a modified capture. Exact GPU filtering and TAA must be checked on a new branch.",
              "global_blue_threshold_changed": False, "content_modified": False, "heavy_process_started": False,
              "root_candidate_preview_approved": False, "new_ue_branch_created": False,
              "runtime_approved": False, "production_approved": False}
    previous.check_records(records)
    save_json(FOLDER / "candidate_report.json", report)
    print(json.dumps({"report": str(FOLDER / "candidate_report.json"), "mask": report["protection_mask"],
                      "support": report["bilinear_possible_support_texel_cells"], "effective": report["effective_protection_possible_texel_cells_after_guard"],
                      "fringe": report["possible_fringe_cells_outside_binary1217"], "other": other_affected,
                      "game_probes": [probe["dual_sample"] for probe in game_probes]}, indent=2))


if __name__ == "__main__":
    build()
