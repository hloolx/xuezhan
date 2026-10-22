from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_emblem_unmix as research
import base_stone_dual_mask_render as old_render


CANDIDATE = research.FOLDER.parent / "candidate_02"
FOLDER = CANDIDATE / "ue_rgb_contribution_v01"
CANDIDATE_SHA = "f581f42307c6bd3b69e9cfb101962c83ecf983ac54d7e8f1533c4350d065365e"
FIELDS_SHA = "ea61f6adcbd739bffb1123b44aacf53e209711b51589cbf257c42ca06c1cdd6f"
DECODE_SCALE = .5
FORMULA = "I=min(NativeBaseColor,0.5*BilinearLinearRGB(InkTexture)); S=NativeBaseColor-I; D=I+TeamColor*dot(S,Luma)/max(dot(TeamColor,Luma),0.01); Final=lerp(NativeBaseColor,D,NearestGuard*saturate(TeamColorStrength))"


def encode(values):
    if not np.isfinite(values).all() or values.min() < 0 or values.max() > DECODE_SCALE:
        raise ValueError("Ink contribution is outside the frozen linear encoding interval")
    return np.rint(values / DECODE_SCALE * 255).astype(np.uint8)


def decode(values):
    return values.astype(np.float64) * DECODE_SCALE / 255


def shader(source, encoded_ink, guard, color, strength=1):
    preserved = np.minimum(source, encoded_ink)
    tinted = research.tint_background(source, preserved, color)
    weight = np.asarray(guard)[..., None] * np.clip(strength, 0, 1)
    return source * (1 - weight) + tinted * weight


def rgb8(values):
    return np.rint(research.linear_to_srgb(values) * 255).astype(np.uint8)


def sampled(field, uv, rectangle):
    left, top, right, bottom = rectangle
    local_uv = [(uv[0] * 2048 - left) / (right - left), (uv[1] * 2048 - top) / (bottom - top)]
    return np.array([research.bilinear_sample(field[..., channel] * 255, local_uv)[0] for channel in range(3)])


def build():
    prior = research.prior
    if (FOLDER / "encoding_report.json").exists():
        raise FileExistsError("Preserve the immutable candidate02 encoding branch")
    if prior.sha(CANDIDATE / "candidate_report.json") != CANDIDATE_SHA or prior.sha(CANDIDATE / "decomposition_fields.npz") != FIELDS_SHA:
        raise ValueError("Root-reviewed candidate02 changed")
    candidate = prior.read(CANDIDATE / "candidate_report.json")
    context = old_render.check_team_report(prior.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    prior.check_records(records)
    config = prior.file_record(prior.ROOT / "Content/Data/BaseArtPilot.json")
    if prior.read(config["path"])["team_material_approved_for_pilot"] is not False:
        raise ValueError("Failed runtime shader must remain disabled during preparation")
    fields = dict(np.load(CANDIDATE / "decomposition_fields.npz"))
    source, ink, support, guard = (fields[name] for name in ("source_linear", "protected_ink_contribution_linear", "semantic_support", "guard"))
    if int(support.sum()) != 1240 or (ink[~support] != 0).any():
        raise ValueError("Exactly final1240 semantic support required")
    left, top, right, bottom = fields["atlas_rectangle"].tolist()
    encoded = encode(ink)
    full = np.zeros((2048, 2048, 3), dtype=np.uint8)
    full[top:bottom, left:right] = encoded
    FOLDER.mkdir(exist_ok=True)
    path = FOLDER / "T_Base_Stone_SideInkContribution_RGB.png"
    if path.exists():
        if not np.array_equal(np.asarray(Image.open(path).convert("RGB")), full):
            raise ValueError("Existing partial encoding differs; retain it without overwrite")
    else:
        Image.fromarray(full).save(path)
    reopened = np.asarray(Image.open(path).convert("RGB"))
    if not np.array_equal(reopened, full):
        raise ValueError("PNG RGB bytes failed lossless roundtrip")
    restored = decode(reopened[top:bottom, left:right])
    if np.any(restored[~support] != 0):
        raise ValueError("Encoding expanded semantic support")
    zeroed = support & ~np.any(restored != 0, axis=-1)
    rectangle = (0, 0, source.shape[1], source.shape[0])
    source_zoom, ink_zoom, restored_zoom = [research.resize_linear(value, rectangle) for value in (source, ink, restored)]
    guard_zoom = np.asarray(Image.fromarray(guard.astype(np.uint8)).resize((source_zoom.shape[1], source_zoom.shape[0]), Image.Resampling.NEAREST)).astype(bool)
    previews, errors = {}, {}
    for mode in ("original", "disabled", "blue", "red"):
        color = prior.shared.TEAM_COLORS["Red" if mode == "red" else "Blue"]
        strength = 0 if mode in ("original", "disabled") else 1
        actual = source_zoom if mode == "original" else shader(source_zoom, restored_zoom, guard_zoom, color, strength)
        ideal = source_zoom if strength == 0 else shader(source_zoom, ink_zoom, guard_zoom, color)
        path_preview = FOLDER / (mode + "_encoded_prediction_x6.png")
        Image.fromarray(rgb8(actual)).save(path_preview)
        previews[mode] = prior.file_record(path_preview)
        difference = rgb8(actual).astype(int) - rgb8(ideal).astype(int)
        errors[mode] = {"linear_rgb": research.metrics(actual - ideal), "rgb8_max": int(np.abs(difference).max()),
                        "rgb8_mean_abs": float(np.abs(difference).mean()), "guard_zero_max_linear_error": float(np.abs(actual[~guard_zoom] - source_zoom[~guard_zoom]).max())}
    clamp = np.maximum(restored_zoom - source_zoom, 0)
    probes = []
    historical = prior.read(prior.FOLDER / "candidate_report.json")
    for item in historical["actual_game_uv_probes"]:
        uv = item["source_uv"]
        original = sampled(source, uv, (left, top, right, bottom))
        expected = sampled(ink, uv, (left, top, right, bottom))
        actual = sampled(restored, uv, (left, top, right, bottom))
        probes.append({"source_uv": uv, "source_linear": original.tolist(), "ideal_ink_linear": expected.tolist(),
                       "decoded_ink_linear": actual.tolist(), "encoding_error": research.metrics(actual - expected),
                       "predicted_rgb8": {team: rgb8(shader(original, actual, True, color)).tolist() for team, color in prior.shared.TEAM_COLORS.items()},
                       "former_all_four_neighbors_protection1_gate": "withdrawn explicitly by root: mixed sourceRGB must not preserve blue substrate as ink"})
    snapshot = FOLDER / "encoder_snapshot.py"
    snapshot.write_bytes(Path(__file__).read_bytes())
    approval = {"created_at": datetime.now(timezone.utc).isoformat(), "source": "root direct instruction after actual candidate02 original/blue/red/shortbar23 overlay review",
                "candidate_report_sha256": CANDIDATE_SHA, "root_candidate02_preview_reviewed": True,
                "one_ue_control_trial_preparation_authorized": True, "candidate03_authorized": False,
                "scope": "Same final1240 semantic source-contribution decomposition; encoding only, no new semantic candidate. Root executes initial/fresh/exact12controls.",
                "actual_ue_visual_approved": False, "runtime_approved": False, "production_approved": False}
    (FOLDER / "root_trial_preparation_approval.json").write_text(json.dumps(approval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "candidate02_linear_rgb_encoding_verified_pending_single_actual_ue_trial",
              "candidate_report": prior.file_record(CANDIDATE / "candidate_report.json"), "decomposition_fields": prior.file_record(CANDIDATE / "decomposition_fields.npz"),
              "encoder": prior.file_record(snapshot), "contribution_texture": prior.file_record(path), "preview_images": previews,
              "formula": FORMULA, "encoding": {"source_max_linear": float(ink.max()), "linear_decode_scale": DECODE_SCALE,
                  "bits_per_channel": 8, "channels": 3, "dimensions": [2048, 2048], "png_pixel_roundtrip_exact": True,
                  "srgb": False, "compression": "TC_VECTOR_DISPLACEMENTMAP_RGBA8_uncompressed", "filter": "Bilinear", "mips": "NoMipmaps",
                  "theoretical_absolute_channel_error_bound": DECODE_SCALE / 510},
              "stored_texel_error_on1240": research.metrics(restored[support] - ink[support]),
              "bilinear_x6_ink_error": research.metrics(restored_zoom - ink_zoom),
              "native_source_clamp_approximation_x6": {"channels_clamped": int((clamp > 0).sum()), "error": research.metrics(clamp),
                  "reason": "Channelwise min(I, actualNativeBaseColor) prevents negative substrate after quantization or native BC1 differences. The latter remain unmeasured until actualUE controls."},
              "final_color_encoding_error_x6": errors, "actual_game_two_uv_predictions": probes,
              "semantic_support_texels_before": 1240, "semantic_support_texels_after": 1240,
              "nonzero_encoded_texels": int(np.any(full != 0, axis=-1).sum()),
              "quantized_to_zero": [{"atlas_pixel": [int(column + left), int(row + top)], "source_ink_linear": ink[row, column].tolist()} for row, column in zip(*np.nonzero(zeroed))],
              "partial_run_recovery": "Initial strict nonzero-count gate stopped after writing only the exact same PNG: one sub-half-LSB source contribution quantized to0. PNG was verified pixel-identical and reused, not replaced; semantic selection remained1240 and quantization error is explicit.",
              "guard_unchanged_sha256": prior.GUARD_SHA, "source714_and_held6_unchanged": True,
              "noncloth_direct_and1px_overlap": 0, "new_other_triangle_support": 0, "front45_and_prior30gaps_unchanged": True,
              "root_gate_revision": candidate["root_gate_revision"], "preserved_fit_residual": candidate["constant_F_fit_residual_entire1240"],
              "all43existing_packages_unchanged": True, "runtime_config_readonly_snapshot": config,
              "actual_gpu_texture_readback_error_measured": False, "actual_ue_execution_completed": False,
              "limitations": ["8bit contribution quantization and clamp are measured offline; nativeBC1 source difference, GPU filtering, TAA, lighting and actual visual fit require controlled UE12images.",
                              "Algebraic ink preservation is not physical groundtruth. No fullcloth, runtime, performance or production approval."],
              "runtime_approved": False, "production_approved": False}
    prior.check_records(records + [config])
    (FOLDER / "encoding_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(FOLDER / "encoding_report.json"), "texel_error": report["stored_texel_error_on1240"], "color_errors": errors, "clamp": report["native_source_clamp_approximation_x6"]}, indent=2))


if __name__ == "__main__":
    build()
