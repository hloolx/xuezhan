from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_ue as team
import base_stone_dual_mask_render as renderer
from base_stone_dual_mask_candidate import sample_dual
from base_stone_side_emblem_diagnostic import SIDE_REGIONS, continuous_mask, save_json
from base_stone_team_review_controls import REGIONS
from base_stone_team_pixel_diagnostic import pair_metrics, ray_hit
from base_stone_validate_ue import read_glb_geometry


FOLDER = team.FOLDER / "ue_control_review_01"


def main():
    outputs = [FOLDER / name for name in ("pixel_diagnostic.json", "visual_review.json", "continuous_alpha_feasibility.json", "runtime_field_suggestion.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("Preserve actual review evidence")
    context = renderer.check_team_report(team.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    team.check_records(records)
    packages = {item["path"]: item for item in records if Path(item["path"]).suffix.lower() == ".uasset"}
    if len(packages) != 43:
        raise ValueError("Expected immutable38plusnew5")
    capture = team.read(FOLDER / "ue_render_report.json")
    expected = {item[0] for item in renderer.SHOTS}
    if capture.get("status") != "actual12images_captured_pending_visual_and_pixel_control_review" or capture.get("actual_images") != 12 or len(capture["images"]) != 12 or {item["label"] for item in capture["images"]} != expected:
        raise ValueError("All12actualcontrols required")
    paths = set(context["original_textures"] + [context["result"]["mask"], context["result"]["protection"]])
    if len(paths) != 5:
        raise ValueError("Actual5texture set required")
    images, evidence = {}, []
    for item in capture["images"]:
        team.shared.check_record(item)
        if not renderer.renderer.textures_resident(item["actual_check"]["actual_texture_residency"], paths):
            raise ValueError("Missing native2048resource in actual shot")
        image = np.asarray(Image.open(item["path"]).convert("RGB"))
        if image.shape != (512, 512, 3):
            raise ValueError("Expected actual512square")
        images[item["label"]] = image
        evidence.append({"label": item["label"], **team.file_record(item["path"]), "all5textures_native2048": True})
    comparisons = {}
    for view in ("wide", "flag", "side_flag"):
        regions = SIDE_REGIONS if view == "side_flag" else REGIONS[view]
        comparisons[view] = {mode: {"whole_image": pair_metrics(images["original_" + view], images[mode + "_" + view]),
                                    "finite_rois": {name: {"rectangle": rectangle, **pair_metrics(images["original_" + view], images[mode + "_" + view], rectangle)}
                                                    for name, rectangle in regions.items()}}
                             for mode in ("disabled", "blue", "red")}
    proof = team.read(team.FOLDER / "candidate_report.json")
    guard = np.asarray(Image.open(proof["guard_mask"]["path"]))
    protection = np.asarray(Image.open(proof["protection_mask"]["path"]))
    atlas = np.asarray(Image.open(team.ROOT / proof["source_atlas"]["file"]).convert("RGB"))
    corners, triangles = read_glb_geometry(Path(context["source_glb"]["path"]))
    corners, indices = np.asarray(corners), np.asarray(triangles)
    vertices = corners[indices, :3]
    probes = []
    for pixel in ((177, 221), (183, 265), (181, 245), (191, 282), (327, 278), (328, 278), (213, 277), (214, 277), (318, 271), (270, 325)):
        hit = ray_hit(pixel, renderer.CAMERAS["side_flag"], vertices, corners, indices)
        if hit is None:
            raise ValueError("Expected finite side flag hit")
        face, uv, bary, position = hit
        sample = sample_dual(guard, protection, uv)
        column, row = sample["guard_nearest_texel"]
        probes.append({"screen_pixel": pixel, "source_triangle": face, "actual_uv_sampling": sample,
                       "source_nearest_rgb": atlas[row, column].tolist(),
                       "actual_original_rgb": images["original_side_flag"][pixel[1], pixel[0]].tolist(),
                       "actual_red_rgb": images["red_side_flag"][pixel[1], pixel[0]].tolist()})
    unused, excluded, occupancy = continuous_mask(guard, np.where(protection > 0, 0, guard).astype(np.uint8))
    core = excluded & (occupancy == 16)
    ratios = atlas[:, :, 0].astype(float) / np.maximum(atlas[:, :, 2], 1)
    source_samples = []
    labels = {"actual_core_center1": (235, 156), "actual_core_center2": (256, 197),
              "actual_core2_bilinear_neighbor": (255, 197), "visible_left_patch1": (252, 210),
              "visible_left_patch2": (264, 204), "visible_left_patch3": (259, 207),
              "plain_blue_inner1": (247, 185), "plain_blue_inner2": (249, 190), "plain_blue_outer": (250, 145)}
    for label, (column, row) in labels.items():
        source_samples.append({"label": label, "atlas_pixel": [column, row], "source_rgb": atlas[row, column].tolist(),
                               "source_srgb_red_blue_ratio": float(ratios[row, column]), "binary_protection": int(protection[row, column]),
                               "is_previous613_entire_cell_core": bool(core[row, column])})
    diagnostic = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                  "status": "all12actual_resource_and_package_checks_pass_but_side_emblem_visual_rejected",
                  "tool": team.file_record(__file__), "fresh_report": team.file_record(team.FOLDER / "ue_fresh_01.json"),
                  "capture_report": team.file_record(FOLDER / "ue_render_report.json"), "actual_render_pid": capture["execution_process_id"],
                  "images": evidence, "comparisons": comparisons, "finite_exact_ray_probes": probes,
                  "source_semantic_color_samples": source_samples,
                  "source_protection_texels": int(excluded.sum()), "fully_protected_source_texels_R_over_B_below0_70": int((excluded & (ratios < .70)).sum()),
                  "previous613_core_texels_R_over_B_below0_70": int((core & (ratios < .70)).sum()),
                  "protected_R_over_B_quantiles_0_10_25_50_75_90_100": np.quantile(ratios[excluded], [0, .1, .25, .5, .75, .9, 1]).tolist(),
                  "all12shots_all5native2048": True, "all43packages_unchanged": True, "verified_packages": list(packages.values()),
                  "source_records_verified": context["source_evidence"], "all_sources_unchanged": True,
                  "limits": "Ratios are diagnostic in stored source-sRGB pixels, not a physical paint-opacity ground truth. Finite camera ray UVs exclude temporal jitter and source bilinear texture blending; actual screenshots are the visual evidence. Color quantiles alone cannot classify semantics.",
                  "runtime_approved": False, "production_approved": False}
    save_json(outputs[0], diagnostic)
    visual = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "rejected_local_bilinear_alone_does_not_remove_overwide_semantic_protection",
              "reviewers": ["agent_A_personally_viewed_all12_original512_images", "root_viewed_side4_and_rejected"],
              "images": evidence, "pixel_diagnostic": team.file_record(outputs[0]),
              "passes": ["Original/disabled visually match; wide team readability remains.",
                         "Front-white core and prior triangle-gap correction remain; noncloth wood/rope/stone show no visible dye spill.",
                         "5native2048resources on every shot and43immutable package hashes are verified; bilateral sampler/strict multiplicative guard graph passed fresh audit."],
              "failure": "Bilinear reduces some abrupt one-pixel transitions but the red side emblem still has a broad hard blue-gray ring, staircase outline and detached left blue-gray shapes. The original same-camera emblem is soft and low-contrast. This is not acceptable final side-emblem quality.",
              "root_cause": "The1217binary protection selection itself labels dark blue cloth fringe/ghost pieces as fully protected. Bilinear interpolation smooths the perimeter of this footprint but cannot remove its broad constant-one interior. Sampling fix alone cannot recover semantic source ink opacity.",
              "continuous_alpha_research": "continuous_alpha_feasibility.json",
              "front_and_wide_partial_regression_passed": True, "side_emblem_final_approved": False,
              "runtime_approved": False, "production_approved": False, "content_modified": False,
              "performance_limit": "Controlled37.469second editor capture only; no new gameplay/full-load or network performance approval."}
    save_json(outputs[1], visual)
    critical = proof["actual_game_uv_probes"][0]["dual_sample"]
    feasibility = {"schema_version": 1, "status": "color_only_monotone_alpha_direction_blocked_spatial_semantic_refinement_needed_no_new_mask_or_ue",
                   "source_samples": source_samples, "critical_actual_game_sample": critical,
                   "finding": "Core2 actual bilinear ray includes texel255,197with RGB81,96,127 and R/B0.6378 at weight0.222541. Proven bad left fragments have higher R/B0.6791..0.6985. Therefore a monotone grayscale/blue-desaturation protection curve that keeps every core2sample at1must also keep these bad fragments at1; changing the threshold or adding wider blur cannot satisfy both requirements.",
                   "unprotected_core_neighbor_weight": 0.2225410800143495,
                   "implication_if_removed_completely": "Removing that dark neighbor while all other core2samples remain1would yield0.222541team tint at the previously protected actual-game core ray. It is not legitimate to claim the two core rays are preserved after such a color-only cut.",
                   "why_original_low_contrast_is_not_sufficient": "A single baked RGB atlas combines blue substrate, pale ink, shadow and JPEG/AA. Several true edge samples and false blue-gray fragments overlap in color. Unique physically correct ink opacity cannot be inferred from color alone without spatial semantic constraints.",
                   "minimum_next_proposal_not_executed": [
                       "Keep the frozen714Nearest guard exactly unchanged and retain a separateBilinear protection channel; reject global pigment changes and whole-atlas blur.",
                       "Re-review targetcluster0 actual source stroke anatomy: ring centerline, divider and genuine bars versus disconnected broad blue cloth/shadow patches. Record explicit exclude polygons for confirmed false fragments, not an unseen automatic threshold.",
                       "If those local spatial semantics are approved, fit a continuous source-derived matte inside each true stroke using local blue-cloth and pale-ink samples; preserve the twoactual UV2x2sampling footprints with explicit anatomical evidence, not hidden one-pixel clamps.",
                       "Before anyUE trial, report exact alpha at bothactualUVrays and all falsepatch probes, source-gradient/alpha overlays, noncloth pointwiseguard proof and front45regression. If source ambiguity or contradictory support remains, defer side-emblem refinement rather than claim success."
                   ],
                   "no_new_candidate_generated": True, "no_new_paid_task": True, "no_new_heavy_process": True,
                   "no_runtime_switch_recommended": True, "production_approved": False}
    save_json(outputs[2], feasibility)
    save_json(outputs[3], {"status": "blocked_do_not_switch_to_dual_mask_branch", "branch": context["destination"],
                           "reason": visual["failure"], "proposed_runtime_fields": None, "content_modified": False,
                           "visual_review": team.file_record(outputs[1]), "research": team.file_record(outputs[2])})
    team.check_records(records)
    print(json.dumps({"review": str(outputs[1]), "packages": len(packages), "source_blue_fringe_count": diagnostic["fully_protected_source_texels_R_over_B_below0_70"],
                      "old_core_blue_fringe_count": diagnostic["previous613_core_texels_R_over_B_below0_70"],
                      "disabled": {view: comparisons[view]["disabled"]["whole_image"] for view in comparisons}}, indent=2))


if __name__ == "__main__":
    main()
