from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_side_emblem_ue as team
import base_stone_team_render as renderer
from base_stone_side_emblem_render import CAMERAS
from base_stone_team_emblem import INSPECTION_RECTANGLE
from base_stone_team_pixel_diagnostic import pair_metrics, ray_hit
from base_stone_team_review_controls import REGIONS
from base_stone_validate_ue import read_glb_geometry


FOLDER = team.FOLDER / "ue_control_review_01"
WEIGHTED = team.FOLDER / "candidate_v03_weighted1"
SIDE_REGIONS = {
    "left_wood": [92, 114, 132, 306], "right_wood": [445, 205, 490, 417],
    "ground": [20, 410, 125, 485], "ring_right_core": [316, 261, 320, 284],
    "ring_bottom_core": [261, 323, 279, 327], "upper_bar_core": [260, 164, 263, 182],
    "left_detached_patch_failure": [171, 216, 195, 284], "full_emblem_and_fringe": [170, 151, 335, 389],
}


def save_json(path, value):
    if path.exists():
        raise FileExistsError("Preserve existing evidence: " + str(path))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inputs():
    renderer.team = team
    context = renderer.check_team_report(team.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    team.check_records(records)
    packages = {record["path"]: record for record in records if Path(record["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 38:
        raise ValueError("Expected original26 plus three immutable4-package branches")
    return context, records, packages


def continuous_mask(footprint, binary):
    if footprint.shape != binary.shape or footprint.ndim != 2:
        raise ValueError("Two matching grayscale masks required")
    if not np.isin(footprint, (0, 255)).all() or not np.isin(binary, (0, 255)).all():
        raise ValueError("Frozen input masks must be binary")
    if np.any(binary > footprint):
        raise ValueError("Binary candidate cannot expand footprint")
    excluded = (footprint > 0) & (binary == 0)
    padded = np.pad(excluded.astype(np.uint16), 1)
    occupancy = np.zeros_like(footprint, dtype=np.uint16)
    height, width = footprint.shape
    kernel = (1, 2, 1)
    for row, row_weight in enumerate(kernel):
        for column, column_weight in enumerate(kernel):
            occupancy += padded[row:row + height, column:column + width] * row_weight * column_weight
    result = binary.copy()
    result[excluded] = np.rint(255 * (1 - occupancy[excluded].astype(float) / 16)).astype(np.uint8)
    if np.any(result > footprint) or np.any((result != binary) & ~excluded):
        raise ValueError("Only original protected semantic pixels can change")
    return result, excluded, occupancy


def edge_samples(images, context, binary):
    original, red = images["original_side_flag"].astype(np.int16), images["red_side_flag"].astype(np.int16)
    first_gradient = np.abs(original[:, 1:] - original[:, :-1]).max(axis=2)
    red_gradient = np.abs(red[:, 1:] - red[:, :-1]).max(axis=2)
    candidates = []
    for label, rectangle in {"ring_right": [305, 218, 335, 320], "ring_left": [177, 205, 214, 306],
                             "left_detached": [171, 216, 195, 284], "upper_bars": [230, 152, 289, 190]}.items():
        left, top, right, bottom = rectangle
        ranking = []
        for row in range(top, bottom):
            for column in range(left, right):
                gain = int(red_gradient[row, column] - first_gradient[row, column])
                if gain >= 20 and first_gradient[row, column] <= 12:
                    ranking.append((gain, column, row))
        chosen = []
        for gain, column, row in sorted(ranking, reverse=True):
            if all((column - prior[0]) ** 2 + (row - prior[1]) ** 2 >= 8 ** 2 for prior in chosen):
                chosen.append((column, row))
                candidates.append((label, gain, column, row))
                if len(chosen) == 4:
                    break
    corners, triangles = read_glb_geometry(Path(context["source_glb"]["path"]))
    corners, indices = np.asarray(corners), np.asarray(triangles)
    vertices = corners[indices, :3]
    candidate = team.read(team.FOLDER / "candidate_v02/candidate_report.json")
    atlas = np.asarray(Image.open(team.ROOT / candidate["source_atlas"]["file"]).convert("RGB"))
    rows = []
    for label, gain, column, row in candidates:
        samples = []
        for pixel in ((column, row), (column + 1, row)):
            hit = ray_hit(pixel, CAMERAS["side_flag"], vertices, corners, indices)
            if hit is None:
                samples.append({"pixel": pixel, "hit": False})
                continue
            face, uv, bary, position = hit
            horizontal, vertical = np.clip(np.floor(uv * 2048).astype(int), 0, 2047).tolist()
            samples.append({"pixel": pixel, "source_triangle": face, "atlas_pixel": [horizontal, vertical],
                            "original_rgb": images["original_side_flag"][pixel[1], pixel[0]].tolist(),
                            "red_rgb": images["red_side_flag"][pixel[1], pixel[0]].tolist(),
                            "source_atlas_rgb": atlas[vertical, horizontal].tolist(),
                            "mask": int(binary[vertical, horizontal])})
        rows.append({"region": label, "original_horizontal_max_rgb_gradient": int(first_gradient[row, column]),
                     "red_horizontal_max_rgb_gradient": int(red_gradient[row, column]),
                     "gradient_increase": gain, "samples": samples})
    return rows


def review():
    context, records, packages = inputs()
    report_path = FOLDER / "ue_render_report.json"
    report = team.read(report_path)
    expected = {mode + "_" + view for mode in ("original", "disabled", "blue", "red") for view in ("wide", "flag", "side_flag")}
    if report.get("actual_images") != 12 or len(report["images"]) != 12 or {item["label"] for item in report["images"]} != expected:
        raise ValueError("Twelve actual matched controls required")
    if report.get("status") != "actual12images_captured_pending_visual_and_pixel_control_review":
        raise ValueError("Actual render did not finish")
    textures = set(context["original_textures"] + [context["result"]["mask"]])
    images, image_records = {}, []
    for item in report["images"]:
        team.shared.check_record(item)
        image = np.asarray(Image.open(item["path"]).convert("RGB"))
        if image.shape != (512, 512, 3) or not renderer.textures_resident(item["actual_check"]["actual_texture_residency"], textures):
            raise ValueError("Actual512 image and four native2048 textures required for every shot")
        images[item["label"]] = image
        image_records.append({"label": item["label"], **team.file_record(item["path"]), "native4resident2048": True})
    comparisons = {}
    for view in ("wide", "flag", "side_flag"):
        regions = SIDE_REGIONS if view == "side_flag" else REGIONS[view]
        comparisons[view] = {mode: {"whole_image": pair_metrics(images["original_" + view], images[mode + "_" + view]),
                                    "manual_roi": {name: {"rectangle": rectangle, **pair_metrics(images["original_" + view], images[mode + "_" + view], rectangle)}
                                                   for name, rectangle in regions.items()}}
                             for mode in ("disabled", "blue", "red")}
    binary = np.asarray(Image.open(context["mask_source"]["path"]))
    samples = edge_samples(images, context, binary)
    diagnostic = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                  "status": "numeric_controls_pass_visual_side_emblem_hard_edge_failure",
                  "tool": team.file_record(__file__), "render_report": team.file_record(report_path),
                  "fresh_report": team.file_record(team.FOLDER / "ue_fresh_01.json"),
                  "images": image_records, "comparisons": comparisons, "finite_edge_ray_samples": samples,
                  "native4resident2048_all12shots": True, "all38packages_unchanged": True,
                  "package_count": 38, "verified_package_records": list(packages.values()),
                  "source_records_verified": context["source_evidence"], "all_source_records_unchanged": True,
                  "source_atlas_glb_uv_unchanged": True, "actual_render_process_id": report["execution_process_id"],
                  "source_glb": context["source_glb"], "mask_source": context["mask_source"],
                  "limits": "Finite ROIs and exact camera rays do not reconstruct temporal jitter, bilinear source texture filtering or all hidden surfaces. Core preservation is not edge-quality acceptance. Actual images remain unmodified.",
                  "runtime_approved": False, "production_approved": False}
    save_json(FOLDER / "pixel_diagnostic.json", diagnostic)
    visual = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "rejected_for_runtime_side_emblem_hard_binary_boundary",
              "reviewers": ["agent_A_personally_viewed_all12_original512_images", "root_personally_viewed_all12_original512_images"],
              "images": image_records, "pixel_diagnostic": team.file_record(FOLDER / "pixel_diagnostic.json"),
              "passes": ["Original and strength0 controls remain visually equivalent at wide, front and side cameras.",
                         "Main714 team cloth remains readable; front white emblem and prior internal triangle-gap correction hold.",
                         "Wood, ropes, stone and ground negative controls show no visible team tint; all38packages and all12x4native2048 residency verified.",
                         "Side emblem core no longer shifts wholly orange/cyan."],
              "failures": ["Red side closeup exposes a coarse blue-gray ring border and obvious pixel stairs, absent from the softer original source appearance.",
                           "Detached blue-gray patches left of the circle and hard short-bar edges become high-contrast against red cloth; blue also retains stair steps.",
                           "1217 binary-protected texels include antialias/faded source fringe. Nearest sampling of a0/255 tint mask abruptly separates that original fringe from tinted cloth; valid semantic location alone is insufficient."],
              "next_minimum_candidate": "Within the same1217 protected texels only, keep eroded1texel core at0 and weight boundary protection continuously with a3x3 radius1 binomial occupancy. Preserve original atlas, global blue predicate, outside strokes,714selection/held6 and footprint/noncloth margins. Preview before any new UE branch.",
              "controlled_front_and_wide_regression_passed": True, "side_emblem_edge_quality_passed": False,
              "all_emblems_preserved": False, "all_cloth_approved": False,
              "runtime_approved": False, "production_approved": False, "content_modified": False,
              "performance_scope": "37.14s controlled editor capture, not gameplay or full-load/network performance acceptance."}
    save_json(FOLDER / "visual_review.json", visual)
    suggestion = {"status": "blocked_do_not_switch_current_runtime_material", "rejected_branch": context["destination"],
                  "reason": "Side emblem core is protected but actual closeup has new hard binary edges and detached high-contrast patches.",
                  "keep_current_runtime_branch": "/Game/ArtPilot/BaseStoneTeam/h209a2a8ebd7b9dca",
                  "current_branch_limit": "Retain historical partial-game status: original side blue-gray emblem still tints under oldbranch; retaining configuration is not final approval.",
                  "proposed_runtime_fields": None, "content_modified": False, "next_ue_requires_root_candidate_preview_review": True,
                  "visual_review": team.file_record(FOLDER / "visual_review.json")}
    save_json(FOLDER / "runtime_field_suggestion.json", suggestion)
    team.check_records(records)
    print(json.dumps({"review": str(FOLDER / "visual_review.json"), "packages": len(packages), "edge_pairs": len(samples),
                      "disabled": {view: comparisons[view]["disabled"]["whole_image"] for view in comparisons}}, indent=2))


def candidate():
    if WEIGHTED.exists():
        raise FileExistsError("Preserve all prior candidates")
    context, records, packages = inputs()
    previous = team.read(team.FOLDER / "candidate_v02/candidate_report.json")
    footprint = np.asarray(Image.open(previous["prior_mask"]["path"]))
    binary = np.asarray(Image.open(previous["new_mask"]["path"]))
    result, excluded, occupancy = continuous_mask(footprint, binary)
    if int(excluded.sum()) != 1217:
        raise ValueError("Only frozen1217 semantic stroke texels may change")
    for probe in previous["front45_probes_unchanged"]:
        column, row = probe["atlas_pixel"]
        if int(result[row, column]) != int(footprint[row, column]):
            raise ValueError("Previous front45 probes must remain byte-identical")
    if not np.array_equal(result[~excluded], footprint[~excluded]):
        raise ValueError("Nonstroke pixels must remain exact")
    atlas_path = team.ROOT / previous["source_atlas"]["file"]
    if team.sha(atlas_path) != previous["source_atlas"]["sha256"]:
        raise ValueError("Original source atlas changed")
    atlas = np.asarray(Image.open(atlas_path).convert("RGB"))
    WEIGHTED.mkdir()
    snapshot = WEIGHTED / "generator_snapshot.py"
    snapshot.write_bytes(Path(__file__).read_bytes())
    mask_path = WEIGHTED / "T_Base_Stone_MainClothMask_WEIGHTED1_CANDIDATE.png"
    Image.fromarray(result).save(mask_path)
    protection = np.zeros_like(result)
    protection[excluded] = 255 - result[excluded]
    strength = protection.astype(float) / 255 * .65
    overlay = np.rint(atlas * (1 - strength[:, :, None]) + np.asarray((255, 225, 20)) * strength[:, :, None]).astype(np.uint8)
    previews = {}
    for name, image in {"atlas_source": Image.fromarray(atlas), "atlas_weight_overlay": Image.fromarray(overlay),
                        "continuous_mask": Image.fromarray(result), "protection_weight": Image.fromarray(protection)}.items():
        crop = image.crop(INSPECTION_RECTANGLE)
        path = WEIGHTED / (name + "_crop_x6.png")
        crop.resize((crop.width * 6, crop.height * 6), Image.Resampling.NEAREST).save(path)
        previews[name] = team.file_record(path)
    core = excluded & (occupancy == 16)
    boundary = excluded & (occupancy < 16)
    levels, counts = np.unique(result[excluded], return_counts=True)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "continuous1texel_candidate_numeric_pass_pending_actual_preview_review",
              "tool": team.file_record(snapshot), "source_glb": context["source_glb"], "source_atlas": previous["source_atlas"],
              "previous_binary_candidate": team.file_record(team.FOLDER / "candidate_v02/candidate_report.json"),
              "actual_failure_review": team.file_record(FOLDER / "visual_review.json"),
              "previous_footprint": previous["prior_mask"], "previous_binary_mask": previous["new_mask"],
              "new_mask": team.file_record(mask_path), "previews": previews,
              "algorithm": {"selection": "Exact previously approved1217 source-semantic cluster0 stroke texels; no semantic expansion.",
                            "kernel": [[1, 2, 1], [2, 4, 2], [1, 2, 1]], "divisor": 16, "radius_texels": 1,
                            "formula": "Inside excluded only: protection=weighted3x3 occupancy(excluded)/16; tint_mask=round255*(1-protection). Outside excluded unchanged. Full occupancy core stays0.",
                            "sampler_changed": False, "source_atlas_changed": False, "global_blue_predicate_changed": False,
                            "global_blur_applied": False, "boundary_values_quantized_to_uint8": True},
              "semantic_texels": int(excluded.sum()), "fully_protected_core_texels": int(core.sum()),
              "partial1texel_boundary_texels": int(boundary.sum()), "mask_levels_within_semantic_texels": dict(zip(map(str, levels.tolist()), counts.tolist())),
              "changes_vs_binary": int((result != binary).sum()), "changes_outside_semantic1217": int(((result != binary) & ~excluded).sum()),
              "additions_vs_approved_footprint_support": int(((result > 0) & (footprint == 0)).sum()),
              "all_mask_weights_lte_approved_footprint": bool(np.all(result <= footprint)),
              "current_positive_mask_texels": int((result > 0).sum()), "effective_tint_weight_sum": float(result.sum() / 255),
              "front45_byte_identical": True, "previous30_uv_gaps_still_on": True,
              "noncloth_direct_and1px_overlap": 0,
              "noncloth_proof": "All weights are <= frozen exact-footprint mask at every atlas texel; therefore no new direct or1px noncloth support. No additional UV/semantic selection.",
              "original_selected_faces": 714, "held_faces": 6, "affected_source_faces_same_scope": previous["affected_source_faces"],
              "verified_old_game_probes": [{"atlas_pixel": [column, row], "binary": int(binary[row, column]), "weighted": int(result[row, column]),
                                             "source_rgb": atlas[row, column].tolist(), "is_core": bool(core[row, column])} for column, row in [(235, 156), (256, 197)]],
              "all38packages_unchanged": True, "source_atlas_mesh_uv_unchanged": True,
              "content_modified": False, "heavy_process_started": False, "new_ue_branch_created": False,
              "root_preview_review_passed": False, "actual_ue_visual_approved": False, "runtime_approved": False, "production_approved": False,
              "limitations": "One-texel partial mask weights soften discontinuity but cannot prove visual repair, especially with nearest sampling and faded/disconnected source strokes. Preview and a new immutable actual12-image UE comparison are required; this is not a rendered result."}
    team.check_records(records)
    save_json(WEIGHTED / "candidate_report.json", report)
    print(json.dumps({"report": str(WEIGHTED / "candidate_report.json"), "core": int(core.sum()), "boundary": int(boundary.sum()),
                      "probes": report["verified_old_game_probes"], "mask": report["new_mask"], "previews": previews}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--candidate", action="store_true")
    args = parser.parse_args()
    if args.review == args.candidate:
        raise ValueError("Choose exactly one evidence step")
    review() if args.review else candidate()


if __name__ == "__main__":
    main()
