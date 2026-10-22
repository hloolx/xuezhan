from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image

import base_stone_team_render as review
from base_stone_validate_ue import read_glb_geometry


def pair_metrics(first, second, region=None):
    if region:
        left, top, right, bottom = region
        first, second = first[top:bottom, left:right], second[top:bottom, left:right]
    difference = np.abs(first.astype(np.int16) - second.astype(np.int16))
    maximum = difference.max(axis=2)
    return {"pixels": int(maximum.size), "mean_abs_rgb": float(difference.mean()), "max_rgb": int(difference.max()),
            "p95_max_channel": float(np.percentile(maximum, 95)), "p99_max_channel": float(np.percentile(maximum, 99)),
            "pixels_above2": int((maximum > 2).sum()), "pixels_above8": int((maximum > 8).sum()),
            "pixels_above24": int((maximum > 24).sum())}


def ray_hit(pixel, camera, vertices, corners, indices):
    target = np.asarray(camera["target"], dtype=float)
    origin = target + np.asarray(camera["offset"], dtype=float)
    forward = target - origin
    forward /= np.linalg.norm(forward)
    right = np.cross((0, 0, 1), forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    focal = 256 / math.tan(math.radians(camera["fov"] / 2))
    direction = forward + right * ((pixel[0] + .5 - 256) / focal) + up * ((256 - pixel[1] - .5) / focal)
    direction /= np.linalg.norm(direction)
    first_edge, second_edge = vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0]
    cross = np.cross(np.broadcast_to(direction, second_edge.shape), second_edge)
    determinant = np.einsum("ij,ij->i", first_edge, cross)
    valid = np.abs(determinant) > 1e-10
    inverse = np.divide(1., determinant, out=np.zeros_like(determinant), where=valid)
    relative = origin - vertices[:, 0]
    bary_first = np.einsum("ij,ij->i", relative, cross) * inverse
    another = np.cross(relative, first_edge)
    bary_second = another @ direction * inverse
    distance = np.einsum("ij,ij->i", second_edge, another) * inverse
    valid &= (bary_first >= 0) & (bary_second >= 0) & (bary_first + bary_second <= 1) & (distance > 0)
    choices = np.where(valid)[0]
    if not len(choices):
        return None
    index = int(choices[np.argmin(distance[choices])])
    bary = np.asarray((1 - bary_first[index] - bary_second[index], bary_first[index], bary_second[index]))
    uv = bary @ corners[indices[index], 3:]
    return index, uv, bary, origin + direction * distance[index]


def pixels_in_uv_triangles(pixel, uv_triangles):
    first, second, third = uv_triangles[:, 0], uv_triangles[:, 1], uv_triangles[:, 2]
    denominator = (second[:, 1] - third[:, 1]) * (first[:, 0] - third[:, 0]) + (third[:, 0] - second[:, 0]) * (first[:, 1] - third[:, 1])
    valid = np.abs(denominator) > 1e-10
    inverse = np.divide(1., denominator, out=np.zeros_like(denominator), where=valid)
    horizontal, vertical = pixel[0] + .5, pixel[1] + .5
    bary_first = ((second[:, 1] - third[:, 1]) * (horizontal - third[:, 0]) + (third[:, 0] - second[:, 0]) * (vertical - third[:, 1])) * inverse
    bary_second = ((third[:, 1] - first[:, 1]) * (horizontal - third[:, 0]) + (first[:, 0] - third[:, 0]) * (vertical - third[:, 1])) * inverse
    return valid & (bary_first >= -1e-5) & (bary_second >= -1e-5) & (bary_first + bary_second <= 1.00001)


def main():
    output = review.team.TEAM / "ue_color_review_04/pixel_geometry_diagnostic.json"
    if output.exists():
        raise FileExistsError("Do not overwrite actual diagnostic evidence")
    context = review.check_team_report(review.team.TEAM / "ue_fresh_02.json")
    folder = output.parent
    report = review.team.read(folder / "ue_render_report.json")
    for image in report["images"]:
        review.team.shared.check_record(image)
    images = {image["label"]: np.asarray(Image.open(image["path"]).convert("RGB")) for image in report["images"]}
    rois = {"wide": {"roof": [170, 245, 265, 275], "platform_top": [263, 297, 296, 308], "gate_wood": [171, 339, 192, 361], "ground": [50, 450, 180, 480]},
            "flag": {"left_wood_and_rope": [70, 160, 128, 370], "right_wood_and_rope": [388, 166, 465, 365], "top_wood": [200, 20, 280, 65],
                     "pale_emblem_left_ring_core": [197, 243, 202, 265], "cloth_interior": [154, 136, 357, 375]}}
    comparisons = {}
    for crop in ("wide", "flag"):
        original = images["original_" + crop]
        comparisons[crop] = {mode: {"whole_image": pair_metrics(original, images[mode + "_" + crop]),
                                   "manual_roi": {name: {"rectangle": rect, **pair_metrics(original, images[mode + "_" + crop], rect)} for name, rect in rois[crop].items()}}
                             for mode in ("disabled", "blue", "red")}
    original, tinted = images["original_flag"].astype(float), images["red_flag"].astype(float)
    residual = (tinted[:, :, 2] > tinted[:, :, 0] * 1.1) & (tinted[:, :, 2] > tinted[:, :, 1] * 1.01) & (tinted[:, :, 2] - tinted[:, :, 0] > 5)
    scope = np.zeros((512, 512), dtype=bool)
    scope[108:420, 135:383] = True
    residual &= scope & (np.max(np.abs(original - tinted), axis=2) < 12)
    vertical, horizontal = np.nonzero(residual)
    ranked = sorted(zip(horizontal.tolist(), vertical.tolist()), key=lambda point: float(tinted[point[1], point[0], 2] - tinted[point[1], point[0], 0]), reverse=True)
    probes = []
    for point in ranked:
        if all((point[0] - prior[0]) ** 2 + (point[1] - prior[1]) ** 2 >= 12 ** 2 for prior in probes):
            probes.append(point)
        if len(probes) == 45:
            break
    corners, triangles = read_glb_geometry(Path(context["source_glb"]["path"]))
    corners, indices = np.asarray(corners), np.asarray(triangles)
    vertices = corners[indices, :3]
    uv_triangles = corners[indices, 3:] * 2048
    diagnostic = review.team.read(review.team.TEAM / "region_diagnostic_v01/region_analysis.json")
    selection = review.team.read(review.team.TEAM / "main_cloth_candidate_v02_safe1/candidate_mask_report.json")
    selected = set(selection["selected_source_triangles"])
    raw = np.asarray(Image.open(review.team.TEAM / "main_cloth_candidate_v01/T_Base_Stone_MainClothMask_CANDIDATE.png")) > 0
    safe = np.asarray(Image.open(review.team.TEAM / "main_cloth_candidate_v02_safe1/T_Base_Stone_MainClothMask_CANDIDATE.png")) > 0
    coverage = np.asarray(Image.open(review.team.TEAM / "main_cloth_candidate_v02_safe1/selected714_geometry_coverage.png")) > 0
    atlas = np.asarray(Image.open(review.team.ROOT / selection["base_color"]["file"]).convert("RGB"))
    uv_min, uv_max = uv_triangles.min(axis=1), uv_triangles.max(axis=1)
    rows = []
    for pixel in probes:
        hit = ray_hit(pixel, review.CAMERAS["flag"], vertices, corners, indices)
        if hit is None:
            rows.append({"pixel": pixel, "hit": False})
            continue
        face, uv, bary, position = hit
        atlas_pixel = np.clip(np.floor(uv * 2048).astype(int), 0, 2047)
        horizontal, vertical = atlas_pixel.tolist()
        if safe[vertical, horizontal]:
            reason = "safe_mask_on_at_exact_ray_pixel_sampling_or_temporal_boundary_requires_neighborhood_review"
        elif raw[vertical, horizontal]:
            reason = "safe1_removed_original_selected_pigment"
        elif not coverage[vertical, horizontal]:
            reason = "nearest_texel_center_outside_selected714_uv_coverage"
        else:
            reason = "selected_coverage_but_original_pigment_classifier_excluded"
        candidates = np.flatnonzero(np.all(uv_min <= atlas_pixel + 1.5, axis=1) & np.all(uv_max >= atlas_pixel - .5, axis=1))
        owners = set()
        for delta_x in (-1, 0, 1):
            for delta_y in (-1, 0, 1):
                inside = pixels_in_uv_triangles(atlas_pixel + (delta_x, delta_y), uv_triangles[candidates])
                owners.update(candidates[inside].tolist())
        protected = []
        for other in sorted(owners - selected):
            protected.append({"face": other, "blue_fraction": diagnostic["triangles"][other]["blue_fraction"],
                              "centroid_distance_to_probe_cm": float(np.linalg.norm(vertices[other].mean(axis=0) - position)),
                              "shared_position_vertices_with_hit": sum(any(np.linalg.norm(point - matched) < .001 for matched in vertices[face]) for point in vertices[other]),
                              "vertices_ue_cm": vertices[other].tolist()})
        region = (slice(max(0, vertical - 1), min(2048, vertical + 2)), slice(max(0, horizontal - 1), min(2048, horizontal + 2)))
        rows.append({"pixel": list(pixel), "original_rgb": original[pixel[1], pixel[0]].astype(int).tolist(), "red_rgb": tinted[pixel[1], pixel[0]].astype(int).tolist(),
                     "source_triangle": face, "selected_face": face in selected, "hit_ue_cm": position.tolist(), "barycentric": bary.tolist(),
                     "uv": uv.tolist(), "atlas_pixel": atlas_pixel.tolist(), "atlas_rgb": atlas[vertical, horizontal].tolist(), "classification": reason,
                     "near3x3_raw_on": int(raw[region].sum()), "near3x3_safe_on": int(safe[region].sum()), "near3x3_selected_coverage": int(coverage[region].sum()),
                     "protected_uv_neighbors": protected})
    counts = {}
    for row in rows:
        reason = row.get("classification", "miss")
        counts[reason] = counts.get(reason, 0) + 1
    result = {"status": "actual_controls_and_finite_source_uv_probe_diagnostic_not_color_approval",
              "render_report": review.team.file_record(folder / "ue_render_report.json"), "source": context["source_glb"],
              "safe_mask": context["mask_source"], "comparisons": comparisons,
              "residual_blue_pixels_in_front_flag_scope": int(residual.sum()), "probe_count": len(rows), "probe_classification": counts,
              "source_uv_probes": rows, "all8shots_native4resident2048": all(review.textures_resident(image["actual_check"]["actual_texture_residency"], set(context["original_textures"] + [context["result"]["mask"]])) for image in report["images"]),
              "source_base5_stoneaxe21_and_derived4_unchanged": True, "images_modified": False,
              "limits": "Finite camera pixel rays use exact scripted camera but no temporal-jitter reconstruction. Neighborhood evidence distinguishes UV raster holes/protection; not exhaustive noncloth surface coverage. Manual ROIs are negative controls, not semantic mesh selection.",
              "closeup_final_approved": False, "production_approved": False}
    review.team.check_records(context["frozen_packages"] + context["source_evidence"] + context["result"]["files"])
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "probe_classification": counts, "residual_blue_pixels": int(residual.sum()),
                      "controls": {crop: comparisons[crop]["disabled"]["whole_image"] for crop in comparisons}}, indent=2))


if __name__ == "__main__":
    main()
