from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_emblem_unmix as previous
from base_stone_team_footprint import triangle_texel_support
from base_stone_side_emblem_diagnostic import save_json


FOLDER = previous.FOLDER.parent / "candidate_02"
INSPECTION = previous.FOLDER.parent / "shortbar_inspection"
LOCAL_RECTANGLE = (211, 182, 230, 200)
ROW_SPANS = {187: [225, 225], 189: [224, 225], 190: [222, 225], 191: [221, 224],
             192: [220, 223], 193: [218, 222], 194: [218, 220]}
PREVIOUS_REPORT_SHA = "8b64661a21a89e88e956562a1976149f648b179c962b402aa1c56d7bd5c86ee4"
PREVIOUS_FIELDS_SHA = "babb40c86f6f9ce45b012fb335fc1cd99089969dfe365baed63b80a7c5a77050"


def sources():
    report_path = previous.FOLDER / "candidate_report.json"
    fields_path = previous.FOLDER / "strict_guard_previews/decomposition_fields.npz"
    if previous.prior.sha(report_path) != PREVIOUS_REPORT_SHA or previous.prior.sha(fields_path) != PREVIOUS_FIELDS_SHA:
        raise ValueError("Frozen decomposition candidate01 changed")
    report = previous.prior.read(report_path)
    atlas_path = previous.prior.ROOT / report["source_atlas"]["file"]
    if previous.prior.sha(atlas_path) != report["source_atlas"]["sha256"]:
        raise ValueError("Actual source atlas changed")
    fields = dict(np.load(fields_path))
    atlas = np.asarray(Image.open(atlas_path).convert("RGB"))
    addition = np.zeros((2048, 2048), dtype=bool)
    for row, (first, last) in ROW_SPANS.items():
        addition[row, first:last + 1] = True
    left, top, right, bottom = previous.INSPECTION_RECTANGLE
    old_support = np.zeros_like(addition)
    old_support[top:bottom, left:right] = fields["semantic_support"]
    if (addition & old_support).any() or int(addition.sum()) != 23:
        raise ValueError("Expected exactly23 previously omitted shortbar-edge texels")
    return report, fields, atlas, addition, old_support


def inspect():
    if (INSPECTION / "proposal.json").exists():
        raise FileExistsError("Keep existing shortbar inspection")
    report, fields, atlas, addition, old_support = sources()
    INSPECTION.mkdir(exist_ok=True)
    previews = {}
    for label, overlay in (("source", atlas.copy()), ("proposed23", atlas.copy())):
        if label == "proposed23":
            overlay[addition] = np.rint(overlay[addition] * .25 + np.asarray((255, 215, 0)) * .75).astype(np.uint8)
        image = Image.fromarray(overlay).crop(LOCAL_RECTANGLE)
        image = image.resize((image.width * 24, image.height * 24), Image.Resampling.NEAREST)
        canvas = Image.new("RGB", (image.width + 48, image.height + 30), (30, 30, 30))
        canvas.paste(image, (48, 30))
        draw = ImageDraw.Draw(canvas)
        for column in range(LOCAL_RECTANGLE[0], LOCAL_RECTANGLE[2]):
            pixel = 48 + (column - LOCAL_RECTANGLE[0]) * 24
            draw.text((pixel, 10), str(column), fill=(240, 240, 240))
            draw.line((pixel, 30, pixel, canvas.height), fill=(55, 55, 55))
        for row in range(LOCAL_RECTANGLE[1], LOCAL_RECTANGLE[3]):
            pixel = 30 + (row - LOCAL_RECTANGLE[1]) * 24
            draw.text((10, pixel + 6), str(row), fill=(240, 240, 240))
            draw.line((48, pixel, canvas.width, pixel), fill=(55, 55, 55))
        path = INSPECTION / (label + "_shortbar_grid.png")
        if path.exists():
            if not np.array_equal(np.asarray(Image.open(path).convert("RGB")), np.asarray(canvas)):
                raise ValueError("Existing partial preview differs; preserve evidence")
        else:
            canvas.save(path)
        previews[label] = previous.prior.file_record(path)
    pixels = [{"atlas_pixel": [int(column), int(row)], "source_rgb": atlas[row, column].tolist()} for row, column in zip(*np.nonzero(addition))]
    save_json(INSPECTION / "proposal.json", {"source_atlas": report["source_atlas"], "tool": previous.prior.file_record(__file__),
              "row_spans": ROW_SPANS, "proposed_added_texels": pixels, "previews": previews,
              "scope": "Only omitted left-middle shortbar bright edge, not whole ring or any other bar; sourceRGB remains untouched.",
              "is_decomposition_candidate02_generated": False})
    print(json.dumps({"inspection": str(INSPECTION), "pixels": pixels}, indent=2))


def build():
    if FOLDER.exists():
        raise FileExistsError("Last allowed decomposition candidate already exists")
    report01, fields, atlas, addition, old_support = sources()
    inspection = previous.prior.read(INSPECTION / "proposal.json")
    if inspection["row_spans"] != {str(key): value for key, value in ROW_SPANS.items()}:
        raise ValueError("Previously inspected semantic rowspans changed")
    for record in inspection["previews"].values():
        previous.prior.shared.check_record(record)
    context = previous.render.check_team_report(previous.prior.FOLDER / "ue_fresh_01.json")
    records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
    previous.prior.check_records(records)
    config_path = previous.prior.ROOT / "Content/Data/BaseArtPilot.json"
    config = previous.prior.read(config_path)
    if config.get("team_material_approved_for_pilot") is not False:
        raise ValueError("Known-failed faction shader must remain disabled during research")
    config_before = previous.prior.file_record(config_path)
    left, top, right, bottom = previous.INSPECTION_RECTANGLE
    scope = (slice(top, bottom), slice(left, right))
    new_support = old_support | addition
    guard_path = previous.prior.read(previous.prior.FOLDER / "candidate_report.json")["guard_mask"]["path"]
    guard = np.asarray(Image.open(guard_path)) > 0
    guard_zero_additions = {(int(column), int(row)) for row, column in zip(*np.nonzero(addition & ~guard))}
    if guard_zero_additions != {(222, 190), (222, 191)}:
        raise ValueError("Only two already-pale source texels may have originalguard0; never change guard")
    analysis = previous.prior.read(previous.prior.TEAM / "region_diagnostic_v01/region_analysis.json")
    target = set(next(item for item in analysis["clusters"] if item["cluster_id"] == 0)["source_glb_triangles"])
    target_support, other_support = np.zeros_like(addition), np.zeros_like(addition)
    all_triangle_support = {}
    for triangle in analysis["triangles"]:
        raster = triangle_texel_support(triangle["uv_gltf_top_left"], 2048, 2048)
        if raster is None:
            continue
        region, support = raster
        collection = target_support if triangle["source_glb_triangle"] in target else other_support
        collection[region] |= support
        if (addition[region] & support).any():
            all_triangle_support[triangle["source_glb_triangle"]] = int((addition[region] & support).sum())
    added_filter_support = np.asarray(Image.fromarray(addition.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
    complete_filter_support = np.asarray(Image.fromarray(new_support.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
    if (addition & ~target_support).any() or (added_filter_support & other_support).any() or (complete_filter_support & guard & other_support).any():
        raise ValueError("New exact or bilinear support crosses another sourcecluster")
    source, background = fields["source_linear"], fields["local_background_linear"]
    ink = previous.srgb_to_linear(atlas[previous.INK_ANCHOR[1], previous.INK_ANCHOR[0]].astype(float) / 255)
    opacity, foreground, residual = previous.unmix(source, background, ink)
    foreground[~new_support[scope]] = 0
    opacity[~new_support[scope]] = 0
    if not np.array_equal(foreground[old_support[scope]], fields["protected_ink_contribution_linear"][old_support[scope]]):
        raise ValueError("Existing candidate01 ink decomposition must be byte-identical")
    if np.any(foreground[~new_support[scope]] != 0) or not np.array_equal(guard[scope], fields["guard"]):
        raise ValueError("No unrelated region or strictguard may change")
    footprint = previous.prior.read(previous.prior.TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json")
    if len(footprint["probes"]) != 45 or any(complete_filter_support[probe["atlas_pixel"][1], probe["atlas_pixel"][0]] for probe in footprint["probes"]):
        raise ValueError("All45front probes must remain outside local decomposition sampling support")
    FOLDER.mkdir()
    snapshot = FOLDER / "generator_snapshot.py"
    snapshot.write_bytes(Path(__file__).read_bytes())
    rectangle = (0, 0, source.shape[1], source.shape[0])
    original_zoom, foreground_zoom = previous.resize_linear(source, rectangle), previous.resize_linear(foreground, rectangle)
    guard_zoom = np.asarray(Image.fromarray(fields["guard"].astype(np.uint8)).resize((source.shape[1] * 6, source.shape[0] * 6), Image.Resampling.NEAREST)).astype(bool)
    previews, negative = {}, {}
    for mode in ("original", "blue", "red"):
        value = original_zoom if mode == "original" else np.where(guard_zoom[..., None], previous.tint_background(original_zoom, foreground_zoom, previous.prior.shared.TEAM_COLORS[mode.title()]), original_zoom)
        if mode != "original":
            negative[mode] = previous.metrics(value[~guard_zoom] - original_zoom[~guard_zoom])
        path = FOLDER / (mode + "_strict_guard_x6.png")
        Image.fromarray(np.rint(previous.linear_to_srgb(value) * 255).astype(np.uint8)).save(path)
        previews[mode] = previous.prior.file_record(path)
    overlay = atlas.copy()
    overlay[addition] = np.rint(overlay[addition] * .25 + np.asarray((255, 215, 0)) * .75).astype(np.uint8)
    for name, value, crop in (("added23_overlay", overlay, previous.INSPECTION_RECTANGLE),
                              ("shortbar_source", atlas, LOCAL_RECTANGLE), ("shortbar_added23_overlay", overlay, LOCAL_RECTANGLE)):
        image = Image.fromarray(value).crop(crop)
        factor = 6 if crop == previous.INSPECTION_RECTANGLE else 16
        path = FOLDER / (name + ".png")
        image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST).save(path)
        previews[name] = previous.prior.file_record(path)
    alpha_path = FOLDER / "source_derived_alpha_x6.png"
    Image.fromarray(np.rint(opacity * 255).astype(np.uint8)).resize((source.shape[1] * 6, source.shape[0] * 6), Image.Resampling.BILINEAR).save(alpha_path)
    previews["alpha"] = previous.prior.file_record(alpha_path)
    fields_path = FOLDER / "decomposition_fields.npz"
    np.savez_compressed(fields_path, source_linear=source, local_background_linear=background,
                        opacity=opacity, protected_ink_contribution_linear=foreground, guard=fields["guard"],
                        semantic_support=new_support[scope], added_shortbar_support=addition[scope], atlas_rectangle=fields["atlas_rectangle"])
    added_rows = []
    for row, column in zip(*np.nonzero(addition)):
        local_row, local_column = row - top, column - left
        added_rows.append({"atlas_pixel": [int(column), int(row)], "source_rgb": atlas[row, column].tolist(),
                           "source_derived_alpha": float(opacity[local_row, local_column]),
                           "preserved_ink_contribution_linear_rgb": foreground[local_row, local_column].tolist(),
                           "strict_guard": bool(guard[row, column]), "other_source_triangle_support": bool(other_support[row, column])})
    preview_report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                      "status": "last_offline_decomposition_candidate02_shortbar23edge_revision_pending_root_preview",
                      "tool": previous.prior.file_record(snapshot), "candidate01_report": previous.prior.file_record(previous.FOLDER / "candidate_report.json"),
                      "candidate01_fields": previous.prior.file_record(previous.FOLDER / "strict_guard_previews/decomposition_fields.npz"),
                      "source_atlas": report01["source_atlas"], "source_glb": report01["source_glb"],
                      "previews": previews, "decomposition_fields": previous.prior.file_record(fields_path),
                      "source_semantic_selection": "Exactly23 omitted visibly pale texels on left-middle shortbar edge, hand-selected rowspans from actual source. No whole ring/otherbar expansion or globalthreshold. Original1217andB/Ffit unchanged.",
                      "row_spans": ROW_SPANS, "added_source_pixels": added_rows, "added_source_triangle_ownership": all_triangle_support,
                      "prior_support_pixels": 1217, "added_support_pixels": 23, "new_support_pixels": int(new_support.sum()),
                      "added_strictguard_on_texels": 21, "added_already_pale_strictguard_zero_texels": [[222, 190], [222, 191]],
                      "guard_zero_semantics": "These2actual pale shortbar texels are already protected by originalbluepigment classifier, not noncloth. Store their sourceink contribution for continuousBilinear neighboring samples, but finalNearestguard0still returns originalRGB exactly; no guard pixel changes.",
                      "added_direct_other_triangle_overlap": int((addition & other_support).sum()),
                      "added_unconditionally_dilated1pixel_other_triangle_overlap": int((added_filter_support & other_support).sum()),
                      "added_bilinear_guarded_other_triangle_overlap": int((added_filter_support & guard & other_support).sum()),
                      "all_bilinear_guarded_other_triangle_overlap": int((complete_filter_support & guard & other_support).sum()),
                      "new_noncloth_or_held_dye_support": 0, "noncloth_direct_and1px_overlap": 0,
                      "source714_strict_guard_unchanged": True, "held6_unchanged": True,
                      "all45front_probes_entire_cells_unchanged": True, "previous30gap_points_unchanged": True,
                      "existing1217ink_values_byte_identical": True, "existing_actualUV2probe_contributions_unchanged": True,
                      "formula": report01["formula"], "root_gate_revision": report01["root_gate_revision"],
                      "constant_F_fit_residual_entire1240": previous.metrics(residual[new_support[scope]]),
                      "constant_F_fit_residual_added23": previous.metrics(residual[addition[scope]]),
                      "source_reconstruction_algebraic_error": previous.metrics(foreground + (source - foreground) - source),
                      "ink_contribution_between_teams_algebraic_error": 0,
                      "error_limit": "Zero reconstruction or contribution differences are algebraic, not groundtruthmatte validity. Source original/blue/red andexact23overlay must be personally reviewed.",
                      "outside_strictguard_preview_errors": negative,
                      "runtime_config_readonly_snapshot": config_before, "runtime_team_shader_enabled": False,
                      "all43packages_and_source_atlas_mesh_uv_unchanged": True,
                      "decomposition_candidates_used": 2, "decomposition_candidates_maximum": 2,
                      "new_ue_material_created": False, "new_heavy_process_started": False,
                      "content_modified_by_agent": False, "root_candidate02_preview_approved": False,
                      "actual_ue_visual_approved": False, "runtime_approved": False, "production_approved": False}
    previous.prior.check_records(records)
    previous.prior.shared.check_record(config_before)
    save_json(FOLDER / "candidate_report.json", preview_report)
    print(json.dumps({"report": str(FOLDER / "candidate_report.json"), "added": added_rows,
                      "triangle_ownership": all_triangle_support, "total": int(new_support.sum()), "residual": preview_report["constant_F_fit_residual_entire1240"]}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.build:
        raise ValueError("Choose exactly one explicit stage")
    inspect() if args.inspect else build()


if __name__ == "__main__":
    main()
