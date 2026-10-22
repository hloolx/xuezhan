from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_emblem_unmix as unmix
from base_stone_side_emblem_diagnostic import save_json


def main():
    folder = unmix.FOLDER / "strict_guard_previews"
    if folder.exists():
        raise FileExistsError("Preserve diagnostic correction evidence")
    proof = unmix.prior.read(unmix.prior.FOLDER / "candidate_report.json")
    context = unmix.render.check_team_report(unmix.prior.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    unmix.prior.check_records(records)
    source_atlas = np.asarray(Image.open(unmix.prior.ROOT / proof["source_atlas"]["file"]).convert("RGB"))
    source_linear = unmix.srgb_to_linear(source_atlas.astype(float) / 255)
    left, top, right, bottom = unmix.INSPECTION_RECTANGLE
    source = source_linear[top:bottom, left:right]
    support = np.asarray(Image.open(proof["protection_mask"]["path"]))[top:bottom, left:right] > 0
    guard = np.asarray(Image.open(proof["guard_mask"]["path"]))[top:bottom, left:right] > 0
    rows, columns = np.indices(source.shape[:2])
    rows, columns = rows + top, columns + left
    background, total = np.zeros_like(source), np.zeros(source.shape[:2])
    for column, row in unmix.BACKGROUND_ANCHORS:
        value = np.median(source_linear[row - 1:row + 2, column - 1:column + 2].reshape((-1, 3)), axis=0)
        weight = 1 / ((columns - column) ** 2 + (rows - row) ** 2 + 36)
        background += value * weight[..., None]
        total += weight
    background /= total[..., None]
    ink = source_linear[unmix.INK_ANCHOR[1], unmix.INK_ANCHOR[0]]
    opacity, foreground, residual = unmix.unmix(source, background, ink)
    foreground[~support] = 0
    opacity[~support] = 0
    rectangle = (0, 0, source.shape[1], source.shape[0])
    source_zoom = unmix.resize_linear(source, rectangle)
    foreground_zoom = unmix.resize_linear(foreground, rectangle)
    guard_zoom = np.asarray(Image.fromarray(guard.astype(np.uint8)).resize((source.shape[1] * 6, source.shape[0] * 6), Image.Resampling.NEAREST)).astype(bool)
    folder.mkdir()
    records_out, assertions = {}, {}
    for mode in ("Original", "Blue", "Red"):
        image = source_zoom if mode == "Original" else np.where(guard_zoom[..., None], unmix.tint_background(source_zoom, foreground_zoom, unmix.prior.shared.TEAM_COLORS[mode]), source_zoom)
        if mode != "Original":
            error = np.abs(image[~guard_zoom] - source_zoom[~guard_zoom])
            assertions[mode] = {"outside_strict_guard_changed_pixels": int(np.any(error > 0, axis=1).sum()), "outside_guard_max_error": float(error.max()),
                                "ink_contribution_recolored": False}
        path = folder / (mode.lower() + "_strict_guard_x6.png")
        Image.fromarray(np.rint(unmix.linear_to_srgb(image) * 255).astype(np.uint8)).save(path)
        records_out[mode] = unmix.prior.file_record(path)
    fields_path = folder / "decomposition_fields.npz"
    np.savez_compressed(fields_path, source_linear=source, local_background_linear=background,
                        opacity=opacity, protected_ink_contribution_linear=foreground, guard=guard,
                        semantic_support=support, atlas_rectangle=np.asarray(unmix.INSPECTION_RECTANGLE))
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "candidate01_corrected_strict_guard_offline_previews_pending_visual_review",
              "same_decomposition_candidate": True, "candidate_budget_used": 1, "candidate_budget_maximum": 2,
              "original_candidate_report": unmix.prior.file_record(unmix.FOLDER / "candidate_report.json"),
              "tool": unmix.prior.file_record(__file__), "previews": records_out,
              "frozen_local_decomposition_fields": unmix.prior.file_record(fields_path),
              "correction": "First atlas previews evaluated the decomposition expression over the entirecrop without the originalNearest guard, so noncloth atcrop margins was incorrectly tinted. Preserve those outputs as failed diagnostic previews; these corrected images multiply every change by the exact originalNearest guard. No decomposition or semantic parameters changed; this is not a secondcandidate.",
              "native_sampling_model": "LinearRGB source and preservedink fields use mathematicalBilinear interpolation; original714footprint guard usesNearest. No actualUE lighting/TAA/tonemapping.",
              "checks": assertions, "linear_constant_F_residual": unmix.metrics(residual[support]),
              "source_reconstruction_error": unmix.metrics(foreground + (source - foreground) - source),
              "exact_source_contribution_kept_across_teams": True,
              "contribution_error_limit": "This is algebraic consistency, not semantic ink truth. True foreground opacity remains estimated and must be visually reviewed against source, particularly faint disconnected marks.",
              "all43packages_unchanged": True, "source_atlas_mesh_uv_unchanged": True,
              "content_modified": False, "new_ue_started": False, "actual_ue_visual_approved": False,
              "runtime_approved": False, "production_approved": False}
    unmix.prior.check_records(records)
    save_json(folder / "preview_report.json", report)
    print(json.dumps({"report": str(folder / "preview_report.json"), "checks": assertions}, indent=2))


if __name__ == "__main__":
    main()
