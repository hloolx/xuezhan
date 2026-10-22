"""Frozen Base cloth geometry/UV diagnostics. Color proposes regions, never approves them."""
from __future__ import annotations

import argparse
from collections import defaultdict
import importlib.util
import itertools
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "Tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "Tools"))
from base_stone_validate_ue import BASE, SOURCE_SHA, read_glb_geometry, read_json, sha256, write_new

OWNED = BASE / "team_color_v01"
SOURCE = BASE / "pbr_v01/hf150ba0cde05/Base_Stone_PBR.glb"
TEXTURE = BASE / "pbr_v01/hf150ba0cde05/textures/tripo_base_color_604f91ce-ac55-41ca-898d-bbb3c25f0165_74d3b750720b.jpg"
TEXTURE_SHA = "74d3b750720bebd7ea5a56a162fb7b0a8bd9dcc0f08ef31648a5e9ed4bea5f8a"
PALETTE = ((0.9, 0.05, 0.55), (0.03, 0.8, 0.3), (1, 0.4, 0.02), (0.05, 0.4, 1), (0.9, 0.85, 0.02), (0.5, 0.1, 0.9), (0.05, 0.8, 0.8), (0.9, 0.3, 0.3))


def record(path):
    return {"file": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}


def check_sources():
    if sha256(SOURCE) != SOURCE_SHA or sha256(TEXTURE) != TEXTURE_SHA:
        raise ValueError("Frozen source or atlas changed")
    fresh = read_json(BASE / "ue_fresh_preflight/fresh_01.json")
    if fresh.get("status") != "base_stone_fresh_reopen_structural_and_coordinate_checks_passed":
        raise ValueError("Actual source/UE correspondence approval missing")


def raster_triangle(uv, width, height, np):
    coordinates = np.asarray(uv, dtype=np.float64) * np.asarray((width, height))
    minimum = np.maximum(np.floor(coordinates.min(axis=0)).astype(int), 0)
    maximum = np.minimum(np.ceil(coordinates.max(axis=0)).astype(int), (width - 1, height - 1))
    if np.any(maximum < minimum):
        return None
    horizontal, vertical = np.meshgrid(np.arange(minimum[0], maximum[0] + 1) + 0.5, np.arange(minimum[1], maximum[1] + 1) + 0.5)
    first, second, third = coordinates
    denominator = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1])
    if abs(denominator) < 1e-10:
        return None
    bary_first = ((second[1] - third[1]) * (horizontal - third[0]) + (third[0] - second[0]) * (vertical - third[1])) / denominator
    bary_second = ((third[1] - first[1]) * (horizontal - third[0]) + (first[0] - third[0]) * (vertical - third[1])) / denominator
    inside = (bary_first >= -1e-5) & (bary_second >= -1e-5) & (bary_first + bary_second <= 1.00001)
    return (slice(minimum[1], maximum[1] + 1), slice(minimum[0], maximum[0] + 1)), inside


def analyze(output):
    import numpy as np
    from PIL import Image

    check_sources()
    output.mkdir(parents=True, exist_ok=False)
    corners, triangles = read_glb_geometry(SOURCE)
    rgb = np.asarray(Image.open(TEXTURE).convert("RGB"), dtype=np.float32) / 255
    height, width = rgb.shape[:2]
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    blue_candidate = (blue > red * 1.12) & (blue > green * 1.03) & (blue - red > 0.018)
    records, adjacency, candidate_ids = [], defaultdict(list), set()
    position_keys = [tuple(round(value, 4) for value in corner[:3]) for corner in corners]
    for index, triangle in enumerate(triangles):
        selected_corners = [corners[vertex] for vertex in triangle]
        uv = [list(corner[3:]) for corner in selected_corners]
        raster = raster_triangle(uv, width, height, np)
        pixels, blue_pixels = 0, 0
        if raster is not None:
            region, inside = raster
            pixels = int(inside.sum())
            blue_pixels = int((inside & blue_candidate[region]).sum())
        fraction = blue_pixels / pixels if pixels else 0
        points = np.asarray([(corner[0], -corner[1], corner[2]) for corner in selected_corners])
        cross = np.cross(points[1] - points[0], points[2] - points[0])
        area = float(np.linalg.norm(cross) / 2)
        normal = cross / (area * 2) if area else cross
        candidate = fraction >= 0.15
        records.append({"source_glb_triangle": index, "source_indices": list(triangle), "uv_gltf_top_left": uv,
                        "blender_vertices_cm": points.tolist(), "area_cm2": area, "normal_blender": normal.tolist(),
                        "uv_pixel_count": pixels, "blue_pixel_count": blue_pixels, "blue_fraction": fraction,
                        "candidate_only": candidate, "semantic_approval": False})
        if candidate:
            candidate_ids.add(index)
            for first, second in ((0, 1), (1, 2), (2, 0)):
                key = tuple(sorted((position_keys[triangle[first]], position_keys[triangle[second]])))
                adjacency[key].append(index)
    neighbors = defaultdict(set)
    for group in adjacency.values():
        for index in group:
            neighbors[index].update(group)
    unseen, clusters = set(candidate_ids), []
    while unseen:
        stack, members = [min(unseen)], []
        while stack:
            index = stack.pop()
            if index not in unseen:
                continue
            unseen.remove(index)
            members.append(index)
            stack.extend(neighbors[index] & unseen)
        points = np.asarray([point for index in members for point in records[index]["blender_vertices_cm"]])
        clusters.append({"cluster_id": len(clusters), "source_glb_triangles": sorted(members), "triangle_count": len(members),
                         "bounds_blender_cm": {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()},
                         "centroid_blender_cm": points.mean(axis=0).tolist(),
                         "area_cm2": sum(records[index]["area_cm2"] for index in members),
                         "review_color_linear_rgb": list(PALETTE[len(clusters) % len(PALETTE)]), "semantic_approval": False})
    candidate_coverage = np.zeros((height, width), dtype=bool)
    other_coverage = np.zeros_like(candidate_coverage)
    for item in records:
        raster = raster_triangle(item["uv_gltf_top_left"], width, height, np)
        if raster is not None:
            region, inside = raster
            target = candidate_coverage if item["candidate_only"] else other_coverage
            target[region] |= inside
    diagnostic = candidate_coverage & blue_candidate
    image_path = output / "candidate_pixels_DIAGNOSTIC_NOT_TEAM_MASK.png"
    Image.fromarray(diagnostic.astype(np.uint8) * 255).save(image_path)
    report = {"schema_version": 1, "status": "geometry_uv_candidate_clusters_require_semantic_four_view_review",
              "source": record(SOURCE), "base_color": record(TEXTURE), "source_files_modified": False,
              "ue_packages_modified": False, "coordinates": "Blender cm +X forward/+Z up; GLB UV top-left raster convention",
              "texture_dimensions": [width, height], "classification": {"color_is_proposal_only": True,
              "blue_over_red": 1.12, "blue_over_green": 1.03, "blue_minus_red": 0.018, "min_blue_triangle_fraction": 0.15,
              "spatial_adjacency": "Shared world-position welded triangle edges at0.0001cm, retaining original source IDs/UV; mesh is not welded or edited."},
              "all_triangles": len(records), "candidate_triangles": len(candidate_ids), "clusters": clusters,
              "candidate_diagnostic": record(image_path), "candidate_blue_pixels": int(diagnostic.sum()),
              "candidate_blue_pixels_overlapping_non_candidate_triangles": int((diagnostic & other_coverage).sum()),
              "candidate_region_pixels_overlapping_non_candidate_triangles": int((candidate_coverage & other_coverage).sum()),
              "required_next": ["Personally review four geometry-colored views and atlas; assign cloth semantics to explicit triangle clusters, reject noncloth.",
                                "Only explicit source-hash-bound semantic selection may produce a delivery mask; colored pixels alone never approve cloth.",
                                "Protect every unselected wood/stone/roof UV footprint; report any shared UV coverage instead of recoloring both.",
                                "Retain pale emblem/rope if required; blue-pigment mask must be intersected with approved cloth geometry.",
                                "Compare team red, team blue and neutral controls at fixed camera/light, including rear/side cloth and noncloth negative controls."],
              "production_approved": False, "delivery_mask_created": False, "triangles": records}
    check_sources()
    write_new(output / "region_analysis.json", report)
    print(json.dumps({"output": str(output), "clusters": len(clusters), "candidate_triangles": len(candidate_ids),
                      "candidate_blue_pixels": report["candidate_blue_pixels"], "shared_pixels": report["candidate_blue_pixels_overlapping_non_candidate_triangles"]}))


def render_analysis(analysis_path, output, device, detail_clusters=None):
    import bpy
    from mathutils import Vector

    check_sources()
    analysis = read_json(analysis_path)
    if analysis["source"]["sha256"] != SOURCE_SHA or analysis["base_color"]["sha256"] != TEXTURE_SHA:
        raise ValueError("Candidate analysis source binding mismatch")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise ValueError("Expected one frozen Base mesh")
    mesh = meshes[0]
    colors = []
    for index, color in enumerate(((0.24, 0.24, 0.24),) + PALETTE):
        material = bpy.data.materials.new("DIAGNOSTIC_" + str(index))
        material.use_nodes = True
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (*color, 1)
        material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.8
        colors.append(material)
    mesh.data.materials.clear()
    for material in colors:
        mesh.data.materials.append(material)
    source_corners, source_triangles = read_glb_geometry(SOURCE)
    canonical = {corner: index for index, corner in enumerate(sorted(set(source_corners)))}
    source_ids = [canonical[corner] for corner in source_corners]
    buckets = defaultdict(list)
    for corner, index in canonical.items():
        buckets[tuple(math.floor(value / 0.001) for value in corner[:3])].append((corner, index))
    offsets = list(itertools.product((-1, 0, 1), repeat=3))
    cache = {}
    def corner_id(corner):
        if corner not in cache:
            cell = tuple(math.floor(value / 0.001) for value in corner[:3])
            candidates = []
            for offset in offsets:
                for original, index in buckets.get(tuple(value + delta for value, delta in zip(cell, offset)), ()):
                    position_error = max(abs(actual - expected) for actual, expected in zip(corner[:3], original[:3]))
                    uv_error = max(abs(actual - expected) for actual, expected in zip(corner[3:], original[3:]))
                    if position_error <= 0.001 and uv_error <= 0.000001:
                        candidates.append((position_error, uv_error, index))
            if not candidates:
                raise ValueError("Imported diagnostic corner has no frozen geometry/UV correspondence")
            cache[corner] = min(candidates)[2]
        return cache[corner]
    selected = {}
    for cluster in analysis["clusters"]:
        if detail_clusters is not None and cluster["cluster_id"] not in detail_clusters:
            continue
        for index in cluster["source_glb_triangles"]:
            key = tuple(sorted(source_ids[vertex] for vertex in source_triangles[index]))
            selected[key] = 1 + cluster["cluster_id"] % len(PALETTE)
    assigned, matched = 0, set()
    uv_data = mesh.data.uv_layers.active.data
    for polygon in mesh.data.polygons:
        indices = []
        for loop_index in polygon.loop_indices:
            position = mesh.matrix_world @ mesh.data.vertices[mesh.data.loops[loop_index].vertex_index].co * 100
            uv = uv_data[loop_index].uv
            indices.append(corner_id((float(position.x), -float(position.y), float(position.z), float(uv.x), 1 - float(uv.y))))
        key = tuple(sorted(indices))
        polygon.material_index = selected.get(key, 0)
        if key in selected:
            assigned += 1
            matched.add(key)
    expected_faces = sum(cluster["triangle_count"] for cluster in analysis["clusters"] if detail_clusters is None or cluster["cluster_id"] in detail_clusters)
    if set(selected) != matched or assigned != expected_faces:
        raise ValueError("Imported diagnostic mesh does not match every selected source triangle")
    module_spec = importlib.util.spec_from_file_location("base_team_render_helpers", ROOT / "Tools/Blender/prepare_tripo_environment.py")
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    camera, centre, span = helper.setup_render(mesh, device)
    scene = bpy.context.scene
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.cycles.samples = 8
    scene.render.resolution_x = scene.render.resolution_y = 512
    images = []
    views = [(name, direction, centre, span * 1.25) for name, direction in (("front", (1, 0, 0)), ("left", (0, -1, 0)), ("back", (-1, 0, 0)), ("right", (0, 1, 0)))]
    if detail_clusters is not None:
        directions = {2: ((-1, -0.35, 0.12), 1.1), 5: ((0.35, 1, 0.12), 0.95), 6: ((0.7, 1, 0.15), 0.70), 8: ((0.7, 1, 0.15), 0.80)}
        views = [("cluster_" + str(index), directions[index][0], Vector(analysis["clusters"][index]["centroid_blender_cm"]) / 100, directions[index][1]) for index in detail_clusters]
    for name, direction, target, framing in views:
        camera.location = target + Vector(direction).normalized() * span * 2
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = framing
        path = output / (name + "_regions.png")
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        images.append({"view": name, **record(path)})
    check_sources()
    write_new(output / "render_evidence.json", {"analysis": record(analysis_path), "views": images,
              "source_unchanged": True, "mesh_saved": False, "delivery_mask_created": False, "assigned_faces": assigned,
              "semantic_approval": False, "detail_clusters": detail_clusters, "other_faces_kept_visible_gray": True,
              "palette_repeat_every": len(PALETTE), "threads": 2, "samples": 8, "size": [512, 512]})


def build_candidate(selection_path, output, protected_gutter=0):
    import numpy as np
    from PIL import Image, ImageFilter

    check_sources()
    selection = read_json(selection_path)
    if not selection.get("root_semantic_candidate_approved") or selection.get("production_approved"):
        raise ValueError("Explicit root candidate-only semantic selection required")
    analysis_path = ROOT / selection["analysis"]["file"]
    if sha256(analysis_path) != selection["analysis"]["sha256"] or selection["source_sha256"] != SOURCE_SHA:
        raise ValueError("Semantic selection is not bound to this frozen source and analysis")
    analysis = read_json(analysis_path)
    selected_clusters = set(selection["primary_cloth_candidate_clusters"])
    if selected_clusters != {0, 1, 3, 4, 7} or set(selection["held_clusters"]) != {2, 5, 6, 8}:
        raise ValueError("Do not silently expand approved cloth into held fragments")
    selected_faces = {index for cluster in analysis["clusters"] if cluster["cluster_id"] in selected_clusters for index in cluster["source_glb_triangles"]}
    if len(selected_faces) != 714:
        raise ValueError("Expected exactly the root-reviewed714 faces")
    rgb = np.asarray(Image.open(TEXTURE).convert("RGB"), dtype=np.float32) / 255
    height, width = rgb.shape[:2]
    blue = (rgb[:, :, 2] > rgb[:, :, 0] * 1.12) & (rgb[:, :, 2] > rgb[:, :, 1] * 1.03) & (rgb[:, :, 2] - rgb[:, :, 0] > 0.018)
    selected_coverage = np.zeros((height, width), dtype=bool)
    protected_coverage = np.zeros_like(selected_coverage)
    for item in analysis["triangles"]:
        raster = raster_triangle(item["uv_gltf_top_left"], width, height, np)
        if raster is not None:
            region, inside = raster
            target = selected_coverage if item["source_glb_triangle"] in selected_faces else protected_coverage
            target[region] |= inside
    raw_mask = selected_coverage & blue
    mask = raw_mask.copy()
    if protected_gutter:
        protected_image = Image.fromarray(protected_coverage.astype(np.uint8) * 255)
        unsafe_neighborhood = np.asarray(protected_image.filter(ImageFilter.MaxFilter(1 + 2 * protected_gutter))) > 0
        mask &= ~unsafe_neighborhood
    if (mask & ~raw_mask).any():
        raise ValueError("Safety margin must never expand color into unselected or pale-insignia pixels")
    overlap = int((mask & protected_coverage).sum())
    if overlap:
        raise ValueError("Selected pigment UV overlaps protected noncloth geometry")
    output.mkdir(parents=True, exist_ok=False)
    mask_path = output / "T_Base_Stone_MainClothMask_CANDIDATE.png"
    mask_image = Image.fromarray(mask.astype(np.uint8) * 255)
    mask_image.save(mask_path)
    coverage_path = output / "selected714_geometry_coverage.png"
    Image.fromarray(selected_coverage.astype(np.uint8) * 255).save(coverage_path)
    expanded_one_pixel = np.asarray(mask_image.filter(ImageFilter.MaxFilter(3))) > 0
    report = {"status": "root_reviewed_main_cloth_candidate_mask_not_all_cloth_delivery", "source": record(SOURCE), "base_color": record(TEXTURE),
              "selection": record(selection_path), "mask": record(mask_path), "selected_geometry_coverage": record(coverage_path),
              "selected_clusters": sorted(selected_clusters), "held_clusters": selection["held_clusters"], "selected_source_triangles": sorted(selected_faces),
              "selected_triangle_count": len(selected_faces), "mask_pixels": int(mask.sum()), "protected_uv_overlap_pixels": overlap,
              "one_pixel_filter_footprint_protected_overlap_pixels": int((expanded_one_pixel & protected_coverage).sum()),
              "protected_gutter_pixels": protected_gutter, "raw_selected_pigment_pixels": int(raw_mask.sum()),
              "selected_edge_pixels_retained_original_color_for_safety": int((raw_mask & ~mask).sum()),
              "nonblue_selected_region_pixels_preserved": int((selected_coverage & ~blue).sum()),
              "pale_insignia_preservation": "Nonblue/pale pigment receives mask0; only selected cloth blue pigment is tinted. Boundary antialias/texture filtering remains visual control gate.",
              "padding_added": False, "blur_applied": False, "mask_expanded": False,
              "required_sampler_policy": "Reuse proven NoMipmaps/Nearest/Clamp/NonColor controls in an isolated derived material; no implicit linear/mip sampling approval. Safety margin is a candidate, not permission to blur or recolor pale insignia.",
              "all_cloth_coverage_approved": False, "team_material_created": False, "production_approved": False,
              "source_modified": False, "ue_packages_modified": False}
    check_sources()
    write_new(output / "candidate_mask_report.json", report)
    print(json.dumps({key: report[key] for key in ("status", "mask_pixels", "protected_uv_overlap_pixels", "one_pixel_filter_footprint_protected_overlap_pixels")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--render-analysis", type=Path)
    parser.add_argument("--detail-clusters", default="")
    parser.add_argument("--build-candidate", type=Path)
    parser.add_argument("--protected-gutter", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", choices=("HIP", "CPU"), default="HIP")
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(arguments)
    check_sources()
    if not args.analyze and not args.render_analysis and not args.build_candidate:
        print("Ready for lightweight --analyze; render-analysis requires root's exclusive Blender lease. No delivery mask exists.")
        return
    if not args.output or not args.output.resolve().is_relative_to(OWNED.resolve()):
        raise ValueError("Output must be a new directory inside owned team_color_v01")
    if sum(bool(value) for value in (args.analyze, args.render_analysis, args.build_candidate)) != 1:
        raise ValueError("Analysis and GPU review must use separate explicit stages")
    if args.analyze:
        analyze(args.output.resolve())
    elif args.build_candidate:
        build_candidate(args.build_candidate.resolve(), args.output.resolve(), args.protected_gutter)
    else:
        detail = [int(value) for value in args.detail_clusters.split(",") if value] if args.detail_clusters else None
        if detail is not None and (len(detail) > 4 or not set(detail).issubset({2, 5, 6, 8})):
            raise ValueError("Only the four explicitly held diagnostic fragments may use detail mode")
        render_analysis(args.render_analysis.resolve(), args.output.resolve(), args.device, detail)


if __name__ == "__main__":
    main()
