from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_team_footprint_ue as team
from base_stone_team_footprint import triangle_texel_support


OUTPUT = team.TEAM / "side_emblem_protection_v04"
INSPECTION_RECTANGLE = (195, 135, 292, 224)
RING_OUTER = [(240, 149), (249, 150), (257, 155), (264, 164), (268, 176), (272, 193),
              (270, 202), (265, 211), (258, 214), (249, 211), (239, 204), (231, 195),
              (226, 185), (224, 174), (226, 163), (231, 155)]
RING_INNER = [(241, 158), (247, 159), (253, 163), (258, 172), (261, 183), (261, 191),
              (256, 196), (250, 197), (243, 193), (237, 188), (233, 180), (232, 172),
              (234, 165), (237, 160)]
STROKES = {
    "central_divider": {"points": [(230, 186), (237, 182), (243, 179), (248, 176), (254, 173), (259, 169)], "width": 3},
    "left_upper_bar": {"points": [(215, 184), (220, 181)], "width": 3},
    "left_middle_bar": {"points": [(216, 191), (224, 186)], "width": 4},
    "left_lower_bar": {"points": [(219, 199), (227, 194)], "width": 4},
    "right_upper_bar": {"points": [(268, 158), (276, 153)], "width": 3},
    "right_middle_bar": {"points": [(271, 166), (281, 161)], "width": 3},
    "right_lower_bar": {"points": [(273, 176), (283, 170)], "width": 3},
}


def inputs():
    spec = team.read(OUTPUT / "spec.json")
    context = team.source_inputs()
    atlas = team.ROOT / spec["source_atlas"]["file"]
    if team.sha(atlas) != spec["source_atlas"]["sha256"] or context["mask_source"]["sha256"] != spec["current_mask"]["sha256"]:
        raise ValueError("Frozen atlas or exact footprint mask changed")
    return spec, context, atlas


def inspect():
    spec, context, atlas = inputs()
    path = OUTPUT / "atlas_source_crop_x6.png"
    if path.exists():
        raise FileExistsError("Preserve prior diagnostic")
    crop = Image.open(atlas).convert("RGB").crop(INSPECTION_RECTANGLE)
    crop.resize((crop.width * 6, crop.height * 6), Image.Resampling.NEAREST).save(path)
    print(json.dumps({"source": spec["source_atlas"], "crop": team.file_record(path),
                      "rectangle": INSPECTION_RECTANGLE, "method": "Diagnostic-only source crop nearest6; source pixels unchanged"}))


def stroke_selection(atlas=None):
    selection = Image.new("L", (2048, 2048), 0)
    draw = ImageDraw.Draw(selection)
    draw.polygon(RING_OUTER, fill=255)
    draw.polygon(RING_INNER, fill=0)
    parts = {"ring": np.asarray(selection) > 0}
    for name, stroke in STROKES.items():
        part = Image.new("L", (2048, 2048), 0)
        ImageDraw.Draw(part).line(stroke["points"], fill=255, width=stroke["width"], joint="curve")
        parts[name] = np.asarray(part) > 0
    result = np.zeros((2048, 2048), dtype=bool)
    for name, support in parts.items():
        if atlas is not None:
            ratio_minimum = .67 if name == "right_lower_bar" else .70
            seeds = support & (atlas[:, :, 0].astype(float) >= atlas[:, :, 2].astype(float) * ratio_minimum)
            fringe = np.asarray(Image.fromarray(seeds.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
            support &= fringe
        result |= support
    return result


def protect_strokes(old_mask, proposed, cluster_support, other_support):
    exclusion = proposed & cluster_support & ~other_support
    result = old_mask & ~exclusion
    if (result & ~old_mask).any() or ((old_mask ^ result) & other_support).any():
        raise ValueError("Only target-cluster strokes may change")
    return result, exclusion


def candidate(tight_strokes=False):
    spec, context, atlas_path = inputs()
    destination = OUTPUT / ("candidate_v02" if tight_strokes else "candidate_v01")
    if destination.exists():
        raise FileExistsError("Preserve prior candidate")
    analysis_path = team.TEAM / "region_diagnostic_v01/region_analysis.json"
    analysis = team.read(analysis_path)
    footprint_path = team.TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json"
    footprint = team.read(footprint_path)
    cluster = next(item for item in analysis["clusters"] if item["cluster_id"] == 0)
    source_faces = set(cluster["source_glb_triangles"])
    if len(source_faces) != 195 or not source_faces.issubset(footprint["selected_source_triangles"]):
        raise ValueError("Only verified cluster0 within original714 may change")
    target_support, other_support = np.zeros((2048, 2048), dtype=bool), np.zeros((2048, 2048), dtype=bool)
    for triangle in analysis["triangles"]:
        raster = triangle_texel_support(triangle["uv_gltf_top_left"], 2048, 2048)
        if raster is not None:
            region, support = raster
            selected_support = target_support if triangle["source_glb_triangle"] in source_faces else other_support
            selected_support[region] |= support
    old_mask = np.asarray(Image.open(context["mask_source"]["path"])) > 0
    atlas = np.asarray(Image.open(atlas_path).convert("RGB"))
    proposed = stroke_selection(atlas if tight_strokes else None)
    new_mask, exclusion = protect_strokes(old_mask, proposed, target_support, other_support)
    removed = old_mask & ~new_mask
    if not removed.any() or (removed & ~proposed).any() or (removed & ~target_support).any():
        raise ValueError("Expected only target semantic stroke removals")
    probes = []
    for probe in footprint["probes"]:
        horizontal, vertical = probe["atlas_pixel"]
        new_on = bool(new_mask[vertical, horizontal])
        if new_on != probe["new_mask_on"]:
            raise ValueError("Previously audited45 front-camera probes must remain identical")
        probes.append({"atlas_pixel": probe["atlas_pixel"], "source_triangle": probe["source_triangle"], "unchanged": True, "new_mask_on": new_on})
    for horizontal, vertical in [(235, 156), (256, 197)]:
        if not old_mask[vertical, horizontal] or new_mask[vertical, horizontal]:
            raise ValueError("Verified side-emblem bright probes must be protected")
    destination.mkdir()
    tool_snapshot = destination / "generator_snapshot.py"
    tool_snapshot.write_bytes(Path(__file__).read_bytes())
    mask_path = destination / "T_Base_Stone_MainClothMask_EMBLEM_CANDIDATE.png"
    Image.fromarray(new_mask.astype(np.uint8) * 255).save(mask_path)
    selection_path = destination / "semantic_stroke_selection.png"
    Image.fromarray(proposed.astype(np.uint8) * 255).save(selection_path)
    removed_path = destination / "removed_emblem_pixels.png"
    Image.fromarray(removed.astype(np.uint8) * 255).save(removed_path)
    overlay = atlas.copy()
    overlay[removed] = np.rint(atlas[removed] * .4 + np.asarray((255, 225, 20)) * .6).astype(np.uint8)
    preview_paths = {}
    for name, image in {"atlas_source": Image.fromarray(atlas), "atlas_stroke_overlay": Image.fromarray(overlay),
                        "mask_protected": Image.fromarray(new_mask.astype(np.uint8) * 255),
                        "removed_strokes": Image.fromarray(removed.astype(np.uint8) * 255)}.items():
        crop = image.crop(INSPECTION_RECTANGLE)
        path = destination / (name + "_crop_x6.png")
        crop.resize((crop.width * 6, crop.height * 6), Image.Resampling.NEAREST).save(path)
        preview_paths[name] = team.file_record(path)
    affected_faces = []
    for triangle in analysis["triangles"]:
        if triangle["source_glb_triangle"] not in source_faces:
            continue
        raster = triangle_texel_support(triangle["uv_gltf_top_left"], 2048, 2048)
        if raster is not None:
            region, support = raster
            count = int((removed[region] & support).sum())
            if count:
                affected_faces.append({"source_triangle": triangle["source_glb_triangle"], "removed_sample_support_pixels": count})
    report = {
        "schema_version": 1, "status": "local_semantic_stroke_candidate_numeric_pass_pending_root_atlas_review",
        "tool": team.file_record(tool_snapshot), "spec": team.file_record(OUTPUT / "spec.json"),
        "analysis": team.file_record(analysis_path), "prior_footprint": team.file_record(footprint_path),
        "source_glb": context["source_glb"], "source_atlas": spec["source_atlas"], "prior_mask": context["mask_source"],
        "new_mask": team.file_record(mask_path), "selection": team.file_record(selection_path),
        "removed_pixels_image": team.file_record(removed_path), "previews": preview_paths,
        "semantic_selection": {"source_cluster": 0, "cluster_faces": 195, "ring_outer_atlas_pixels": RING_OUTER,
                               "ring_inner_atlas_pixels": RING_INNER, "strokes": STROKES,
                               "policy": "Manually traced actual source atlas ring band, central divider and6 side strokes. Inner/background is not blanket-erased; intersect exclusive cluster0 exact sampler support.",
                               "local_source_pigment_snap": tight_strokes,
                               "local_source_pigment_snap_method": "Inside each hand-traced stroke envelope only: seed sourceR/sourceB>=0.70, or0.67 for independently visible faded right-lower stroke, and include its1texel antialias neighborhood clipped to that same stroke envelope. No global pigment predicate or other island changes." if tight_strokes else None},
        "original_selected_faces": 714, "held_faces": 6, "old_mask_pixels": int(old_mask.sum()),
        "new_mask_pixels": int(new_mask.sum()), "removed_pixels": int(removed.sum()), "added_pixels": int((new_mask & ~old_mask).sum()),
        "proposed_semantic_pixels": int(proposed.sum()), "excluded_shared_or_noncluster_semantic_pixels": int((proposed & (~target_support | other_support)).sum()),
        "changes_outside_target_cluster": int((removed & ~target_support).sum()), "changes_on_other_source_support": int((removed & other_support).sum()),
        "front45_probes_unchanged": probes, "previous30_uv_sampling_gap_points_still_on": True,
        "noncloth_direct_and1px_overlap_remain_zero": True,
        "noncloth_proof": "New mask is an exact subset of prior approved footprint mask. It adds no pixels, so prior direct and dilated1px protected-overlap zero invariants are monotone-preserved.",
        "affected_source_faces": affected_faces, "source_atlas_mesh_uv_unchanged": True,
        "global_pigment_predicate_modified": False, "material_or_content_modified": False,
        "actual_ue_visual_approved": False, "root_semantic_selection_approved": False,
        "all_emblems_preserved": False, "all_cloth_coverage_approved": False, "production_approved": False,
    }
    team.check_records(context["frozen_packages"] + context["source_evidence"])
    report_path = destination / "candidate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": team.file_record(report_path), "removed_pixels": report["removed_pixels"],
                      "new_mask_pixels": report["new_mask_pixels"], "affected_source_faces": len(affected_faces), "previews": preview_paths}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--candidate", action="store_true")
    parser.add_argument("--tight-strokes", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.candidate:
        raise ValueError("Choose exactly one explicit operation")
    inspect() if args.inspect else candidate(args.tight_strokes)


if __name__ == "__main__":
    main()
