from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_ue as prior
import base_stone_dual_mask_render as render
from base_stone_dual_mask_candidate import bilinear_sample
from base_stone_team_emblem import INSPECTION_RECTANGLE
from base_stone_side_emblem_diagnostic import save_json


FOLDER = prior.FOLDER / "unmix_research_v01/candidate_01"
BACKGROUND_ANCHORS = [(247, 185), (249, 190), (235, 180), (238, 180), (220, 165), (250, 145), (278, 200)]
INK_ANCHOR = (221, 190)


def srgb_to_linear(value):
    return np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)


def linear_to_srgb(value):
    value = np.clip(value, 0, 1)
    return np.where(value <= .0031308, value * 12.92, 1.055 * value ** (1 / 2.4) - .055)


def unmix(source, background, ink):
    direction = ink - background
    denominator = np.sum(direction * direction, axis=-1)
    opacity = np.clip(np.sum((source - background) * direction, axis=-1) / np.maximum(denominator, 1e-12), 0, 1)
    substrate_fraction = 1 - opacity
    nonnegative_limit = np.min(np.divide(source, background, out=np.full_like(source, np.inf), where=background > 1e-12), axis=-1)
    substrate_fraction = np.minimum(substrate_fraction, nonnegative_limit)
    foreground_contribution = source - substrate_fraction[..., None] * background
    reconstruction = substrate_fraction[..., None] * background + (1 - substrate_fraction)[..., None] * ink
    return 1 - substrate_fraction, foreground_contribution, source - reconstruction


def tint_background(source, foreground_contribution, color):
    luminance = np.asarray(prior.shared.LUMINANCE)
    color = np.asarray(color)
    remaining = source - foreground_contribution
    return foreground_contribution + np.sum(remaining * luminance, axis=-1)[..., None] * color / max(.01, float(color @ luminance))


def metrics(value):
    absolute = np.abs(value)
    return {"mean_abs_linear_rgb": float(absolute.mean()), "p95_abs_linear_rgb": float(np.percentile(absolute, 95)), "max_abs_linear_rgb": float(absolute.max())}


def resize_linear(field, rectangle, factor=6):
    left, top, right, bottom = rectangle
    crop = field[top:bottom, left:right]
    shape = ((right - left) * factor, (bottom - top) * factor)
    return np.stack([np.asarray(Image.fromarray(crop[..., channel].astype(np.float32)).resize(shape, Image.Resampling.BILINEAR)) for channel in range(3)], axis=-1)


def build():
    if FOLDER.exists():
        raise FileExistsError("Maximum2research candidates; preserve prior evidence")
    context = render.check_team_report(prior.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    prior.check_records(records)
    proof = prior.read(prior.FOLDER / "candidate_report.json")
    atlas = np.asarray(Image.open(prior.ROOT / proof["source_atlas"]["file"]).convert("RGB"))
    source = srgb_to_linear(atlas.astype(float) / 255)
    support = np.asarray(Image.open(proof["protection_mask"]["path"])) > 0
    guard = np.asarray(Image.open(proof["guard_mask"]["path"])) > 0
    if int(support.sum()) != 1217 or (support & ~guard).any():
        raise ValueError("Original1217semantic ink envelope within strict714guard required")
    rows, columns = np.indices((2048, 2048))
    background = np.zeros_like(source)
    weights_total = np.zeros(source.shape[:2])
    anchor_records = []
    for column, row in BACKGROUND_ANCHORS:
        value = np.median(source[row - 1:row + 2, column - 1:column + 2].reshape((-1, 3)), axis=0)
        weight = 1 / ((columns - column) ** 2 + (rows - row) ** 2 + 36)
        background += value * weight[..., None]
        weights_total += weight
        anchor_records.append({"atlas_pixel": [column, row], "source_rgb": atlas[row, column].tolist(), "median3x3_linear_rgb": value.tolist(),
                               "role": "manually inspected plain blue substrate inside this one flag island, not a global color threshold"})
    background /= weights_total[..., None]
    ink = source[INK_ANCHOR[1], INK_ANCHOR[0]]
    opacity, foreground, residual = unmix(source, background, ink)
    foreground[~support] = 0
    opacity[~support] = 0
    if np.min(foreground) < -1e-10 or np.max(foreground - source) > 1e-10:
        raise ValueError("Preserved source contribution must stay nonnegative and not exceed original")
    FOLDER.mkdir(parents=True)
    snapshot = FOLDER / "generator_snapshot.py"
    snapshot.write_bytes(Path(__file__).read_bytes())
    source_zoom = resize_linear(source, INSPECTION_RECTANGLE)
    foreground_zoom = resize_linear(foreground, INSPECTION_RECTANGLE)
    paths = {}
    outputs = {"original_linear_filtered_x6": source_zoom,
               "blue_substrate_only_x6": tint_background(source_zoom, foreground_zoom, prior.shared.TEAM_COLORS["Blue"]),
               "red_substrate_only_x6": tint_background(source_zoom, foreground_zoom, prior.shared.TEAM_COLORS["Red"]),
               "preserved_source_ink_contribution_x6": foreground_zoom,
               "estimated_local_substrate_x6": resize_linear(background, INSPECTION_RECTANGLE)}
    for name, value in outputs.items():
        path = FOLDER / (name + ".png")
        Image.fromarray(np.rint(linear_to_srgb(value) * 255).astype(np.uint8)).save(path)
        paths[name] = prior.file_record(path)
    left, top, right, bottom = INSPECTION_RECTANGLE
    alpha_crop = Image.fromarray(np.rint(opacity[top:bottom, left:right] * 255).astype(np.uint8)).resize(((right - left) * 6, (bottom - top) * 6), Image.Resampling.BILINEAR)
    alpha_path = FOLDER / "source_derived_alpha_x6.png"
    alpha_crop.save(alpha_path)
    paths["source_derived_alpha_x6"] = prior.file_record(alpha_path)
    anchors_preview = Image.open(paths["original_linear_filtered_x6"]["path"]).convert("RGB")
    draw = ImageDraw.Draw(anchors_preview)
    for index, (column, row) in enumerate(BACKGROUND_ANCHORS):
        point = ((column - left) * 6 + 3, (row - top) * 6 + 3)
        draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), outline=(255, 220, 0), width=2)
        draw.text((point[0] + 5, point[1] - 5), "B" + str(index + 1), fill=(255, 220, 0))
    point = ((INK_ANCHOR[0] - left) * 6 + 3, (INK_ANCHOR[1] - top) * 6 + 3)
    draw.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), outline=(255, 80, 180), width=2)
    draw.text((point[0] + 6, point[1] - 6), "F", fill=(255, 80, 180))
    anchor_path = FOLDER / "source_anchor_overlay_x6.png"
    anchors_preview.save(anchor_path)
    paths["source_anchor_overlay_x6"] = prior.file_record(anchor_path)
    probes = []
    for probe in proof["actual_game_uv_probes"]:
        uv = probe["source_uv"]
        original = np.asarray([bilinear_sample(source[..., channel] * 255, uv)[0] for channel in range(3)])
        preserved = np.asarray([bilinear_sample(foreground[..., channel] * 255, uv)[0] for channel in range(3)])
        alpha = bilinear_sample(opacity * 255, uv)[0]
        probes.append({"uv": uv, "previous_nearest_texel": probe["source_nearest_texel"],
                       "source_derived_alpha_bilinear": alpha, "original_linear_rgb": original.tolist(),
                       "preserved_ink_contribution_linear_rgb": preserved.tolist(),
                       "recolorable_substrate_contribution_linear_rgb": (original - preserved).tolist(),
                       "predicted_offline_colors_srgb255": {name: np.rint(linear_to_srgb(tint_background(original, preserved, color)) * 255).astype(int).tolist() for name, color in prior.shared.TEAM_COLORS.items()},
                       "old_full_protection_gate_revised": True, "ink_contribution_identical_across_teams": True})
    patch_rows = []
    for column, row in ((252, 210), (264, 204), (259, 207), (230, 156), (254, 197)):
        patch_rows.append({"atlas_pixel": [column, row], "original_rgb": atlas[row, column].tolist(),
                           "source_derived_alpha": float(opacity[row, column]),
                           "preserved_ink_contribution_linear_rgb": foreground[row, column].tolist(),
                           "foreground_fraction_of_original_luminance": float((foreground[row, column] @ prior.shared.LUMINANCE) / max(1e-10, source[row, column] @ prior.shared.LUMINANCE)),
                           "red_preview_rgb": np.rint(linear_to_srgb(tint_background(source[row, column], foreground[row, column], prior.shared.TEAM_COLORS["Red"])) * 255).astype(int).tolist()})
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "offline_local_source_unmix_candidate01_pending_actual_image_review_not_ue_ready",
              "tool": prior.file_record(snapshot), "source_atlas": proof["source_atlas"], "source_glb": proof["source_glb"],
              "previews": paths, "scope": {"source_cluster": 0, "source_semantic_texels": 1217, "existing_strict_guard_unchanged": True,
                                            "possible_bilinear_fringe_cells": 683, "noncloth_additions": 0, "held6_unchanged": True},
              "root_gate_revision": "Root explicitly withdrew exact RGB and all4bilinear-neighbors protection1 gates: source mixed pixels contain both blue substrateB and pale inkF. Preserve the ink contribution, not the entire original mixed RGB. Historical tests/results remain unchanged as historical evidence.",
              "background_estimation": {"anchors": anchor_records, "method": "Inverse squared spatial distance weighting of7manually selected plain-blue3x3median anchors, stabilizer36pixels_squared; only the target semantic stroke region uses this estimate."},
              "ink_reference": {"atlas_pixel": INK_ANCHOR, "source_rgb": atlas[INK_ANCHOR[1], INK_ANCHOR[0]].tolist(), "linear_rgb": ink.tolist(), "role": "Observed pale source middle bar, not invented white paint."},
              "formula": "Estimate alpha by constrained least squares C~(1-alpha)B+alphaFref in linearRGB. Bound beta=1-alpha so C-betaB>=0. Preserve I=C-betaB (includes source residual); recolor only C-I. D_team=I+TeamColor*Luminance(C-I)/Luminance(TeamColor). Outside local support I=0; future strict guard still gates all dye.",
              "local_constant_F_reference_reconstruction_residual": metrics(residual[support]),
              "source_reconstruction_using_preserved_residual": metrics((foreground + (source - foreground) - source)[support]),
              "preserved_ink_contribution_difference_between_teams": 0,
              "error_interpretation": "Zero contribution difference/reconstruction is algebraic, NOT proof that inferredI equals true paint. The nonzero constant-F residual and actual source/blue/red morphology must be judged. No source atlas pixels were overwritten.",
              "alpha_quantiles_0_25_50_75_100": np.quantile(opacity[support], [0, .25, .5, .75, 1]).tolist(),
              "actual_game_uv_revised_probes": probes, "previous_bad_fragment_samples": patch_rows,
              "new_ue_shader_not_prepared": True, "why_not_a_mask_only_change": "The old shader tints the entiremixedC. This candidate needs an explicit preserved-source-ink RGB contribution and tints only the residual substrate. A scalar protection alpha alone cannot implement this equation faithfully.",
              "offline_view_limit": "Atlas crop in linearRGB with mathematical bilinear sampling, no UE lighting/TAA/tonemapping. Display may clip bright tinted output. This is a decomposition study, not a generated/repainted atlas or an in-game result.",
              "candidate_budget": {"maximum": 2, "used": 1}, "all43packages_unchanged": True,
              "original_atlas_mesh_uv_unchanged": True, "content_modified": False, "heavy_process_started": False,
              "actual_ue_visual_approved": False, "runtime_approved": False, "production_approved": False}
    prior.check_records(records)
    save_json(FOLDER / "candidate_report.json", report)
    print(json.dumps({"report": str(FOLDER / "candidate_report.json"), "residual": report["local_constant_F_reference_reconstruction_residual"],
                      "probes": probes, "patches": patch_rows}, indent=2))


if __name__ == "__main__":
    build()
