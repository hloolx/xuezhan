from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix


def file_record(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def raster_triangle(uv, width, height):
    coordinates = np.asarray(uv, dtype=np.float64) * np.asarray((width, height))
    minimum = np.maximum(np.floor(coordinates.min(axis=0)).astype(int), 0)
    maximum = np.minimum(np.ceil(coordinates.max(axis=0)).astype(int), (width - 1, height - 1))
    if np.any(maximum < minimum):
        return None
    horizontal, vertical = np.meshgrid(np.arange(minimum[0], maximum[0] + 1) + .5, np.arange(minimum[1], maximum[1] + 1) + .5)
    first, second, third = coordinates
    denominator = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1])
    if abs(denominator) < 1e-10:
        return None
    bary_first = ((second[1] - third[1]) * (horizontal - third[0]) + (third[0] - second[0]) * (vertical - third[1])) / denominator
    bary_second = ((third[1] - first[1]) * (horizontal - third[0]) + (first[0] - third[0]) * (vertical - third[1])) / denominator
    inside = (bary_first >= -1e-5) & (bary_second >= -1e-5) & (bary_first + bary_second <= 1.00001)
    return (slice(minimum[1], maximum[1] + 1), slice(minimum[0], maximum[0] + 1)), inside


def save_mask(path, pixels):
    height, width = pixels.shape
    image = bpy.data.images.new("ClothCandidateMask", width=width, height=height, alpha=False, float_buffer=False)
    image.colorspace_settings.name = "Non-Color"
    rgba = np.ones((height, width, 4), dtype=np.float32)
    rgba[:, :, :3] = pixels[:, :, None]
    image.pixels.foreach_set(rgba.ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()


def render_review(meshes, mask_path, output, device):
    module_spec = importlib.util.spec_from_file_location("stoneaxe_inspection", Path(__file__).with_name("prepare_stoneaxe_rig_pilot.py"))
    inspection = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(inspection)
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
        elif obj.type == "MESH" and obj not in meshes:
            obj.hide_render = True
    mask_image = bpy.data.images.load(str(mask_path), check_existing=False)
    mask_image.colorspace_settings.name = "Non-Color"
    copies = {}
    for obj in meshes:
        for index, original in enumerate(obj.data.materials):
            if original not in copies:
                material = original.copy()
                material.name = "ReviewMagentaMask_" + original.name
                shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
                original_color = shader.inputs["Base Color"].links[0].from_socket
                texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.image = mask_image
                mixed = material.node_tree.nodes.new("ShaderNodeMixRGB")
                mixed.blend_type = "MIX"
                mixed.inputs[2].default_value = (.65, .006, .38, 1)
                material.node_tree.links.new(original_color, mixed.inputs[1])
                material.node_tree.links.new(texture.outputs["Color"], mixed.inputs[0])
                material.node_tree.links.new(mixed.outputs["Color"], shader.inputs["Base Color"])
                copies[original] = material
            obj.data.materials[index] = copies[original]
    inspection.render_setup(device, 8)
    paths = []
    for label, direction, framing, target in (("front_mask", (1, 0, .02), 1.72, (0, 0, .75)),
                                               ("back_mask", (-1, 0, .02), 1.72, (0, 0, .75)),
                                               ("face_mask", (1, -.08, .03), .43, (.04, 0, 1.345)),
                                               ("rear_head_mask", (-1, .08, .03), .55, (-.07, 0, 1.275))):
        path = output / (label + ".png")
        inspection.helper.render_view(path, meshes, direction, size=512, framing=framing, target=target)
        paths.append(file_record(path))
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base-color", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selected-clusters", default="")
    parser.add_argument("--analysis-reference", type=Path)
    parser.add_argument("--render-review", action="store_true")
    parser.add_argument("--device", choices=("CPU", "HIP"), default="CPU")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.source, args.base_color, args.output = args.source.resolve(), args.base_color.resolve(), args.output.resolve()
    if (args.output / "cloth_region_analysis.json").exists():
        raise FileExistsError("Choose a new analysis subdirectory; preserve previous selection evidence")
    source_record, color_record = file_record(args.source), file_record(args.base_color)
    if args.selected_clusters:
        if not args.analysis_reference:
            raise ValueError("Explicit cluster selection needs the earlier immutable analysis reference")
        reference = json.loads(args.analysis_reference.resolve().read_text(encoding="utf-8-sig"))
        if reference["source"]["sha256"] != source_record["sha256"] or reference["base_color"]["sha256"] != color_record["sha256"]:
            raise ValueError("Selection reference source hashes differ")
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.animation_data.action = None
    for bone in armature.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    image = bpy.data.images.load(str(args.base_color), check_existing=False)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgb = pixels.reshape((height, width, 4))[:, :, :3]
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    blue_candidate = (blue > red * 1.12) & (blue > green * 1.03) & (blue - red > .018)
    triangles, adjacency, candidate_indices = [], defaultdict(list), []
    for obj in meshes:
        obj.data.calc_loop_triangles()
        uv_layer = obj.data.uv_layers.active
        if uv_layer is None:
            raise ValueError("Source mesh lacks original UVs")
        for triangle in obj.data.loop_triangles:
            uv = [list(uv_layer.data[index].uv) for index in triangle.loops]
            raster = raster_triangle(uv, width, height)
            fraction = 0.0
            if raster is not None:
                region, inside = raster
                count = int(inside.sum())
                fraction = float((blue_candidate[region] & inside).sum()) / count if count else 0
            points = [obj.matrix_world @ obj.data.vertices[index].co for index in triangle.vertices]
            area = (points[1] - points[0]).cross(points[2] - points[0]).length / 2
            candidate = fraction >= .15
            record = {"index": len(triangles), "object": obj.name, "source_polygon": triangle.polygon_index,
                      "vertices": list(triangle.vertices), "uv": uv, "world_vertices_m": [list(point) for point in points],
                      "area_m2": area, "blue_pixel_fraction": fraction, "candidate": candidate}
            triangles.append(record)
            if candidate:
                candidate_indices.append(record["index"])
                for first, second in ((0, 1), (1, 2), (2, 0)):
                    key = (obj.name, tuple(sorted((triangle.vertices[first], triangle.vertices[second]))))
                    adjacency[key].append(record["index"])
    neighbors = defaultdict(set)
    for shared in adjacency.values():
        for index in shared:
            neighbors[index].update(shared)
    unseen, clusters = set(candidate_indices), []
    while unseen:
        stack, members = [min(unseen)], []
        while stack:
            index = stack.pop()
            if index not in unseen:
                continue
            unseen.remove(index)
            members.append(index)
            stack.extend(neighbors[index] & unseen)
        points = np.asarray([point for index in members for point in triangles[index]["world_vertices_m"]])
        clusters.append({"cluster_id": len(clusters), "triangle_indices": sorted(members), "triangles": len(members),
                         "area_cm2": sum(triangles[index]["area_m2"] for index in members) * 10000,
                         "bounds_min_m": points.min(axis=0).tolist(), "bounds_max_m": points.max(axis=0).tolist(),
                         "centroid_m": points.mean(axis=0).tolist(), "semantic_approval": False})
    selected = {int(value) for value in args.selected_clusters.split(",") if value} if args.selected_clusters else set(range(len(clusters)))
    if not selected.issubset(set(range(len(clusters)))):
        raise ValueError("Unknown candidate cluster ID")
    selected_triangles = {index for cluster in clusters if cluster["cluster_id"] in selected for index in cluster["triangle_indices"]}
    mask = np.zeros((height, width), dtype=bool)
    other_coverage = np.zeros_like(mask)
    for triangle in triangles:
        raster = raster_triangle(triangle["uv"], width, height)
        if raster is None:
            continue
        region, inside = raster
        if triangle["index"] in selected_triangles:
            mask[region] |= inside & blue_candidate[region]
        else:
            other_coverage[region] |= inside
    args.output.mkdir(parents=True, exist_ok=True)
    mask_path = args.output / "T_StoneAxe_ClothMask_candidate.png"
    save_mask(mask_path, mask)
    report = {"schema_version": 1, "status": "candidate_cloth_regions_require_geometry_visual_review", "source": source_record, "base_color": color_record,
              "source_files_modified": False, "ue_assets_modified": False, "body_height_m": 1.5, "coordinates": "Blender physical metres +X forward +Z up",
              "analysis_reference": str(args.analysis_reference.resolve()) if args.analysis_reference else None,
              "selection": {"cluster_ids": sorted(selected), "explicit_selection": bool(args.selected_clusters), "semantically_approved": False},
              "classification": {"blue_over_red": 1.12, "blue_over_green": 1.03, "blue_minus_red": .018, "minimum_candidate_triangle_pixel_fraction": .15,
                                 "warning": "Color proposes candidates only, not semantic cloth approval. Eyes and painted artifacts must be excluded by actual geometry/UV review."},
              "texture_dimensions": [width, height], "candidate_triangles": len(candidate_indices), "all_triangles": len(triangles),
              "clusters": clusters, "mask": file_record(mask_path), "mask_covered_pixels": int(mask.sum()),
              "mask_nonselected_triangle_overlap_pixels": int((mask & other_coverage).sum()), "uv_padding_added": False,
              "production_approved": False, "triangles": triangles}
    (args.output / "cloth_region_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.render_review:
        report["diagnostic_previews"] = render_review(meshes, mask_path, args.output, args.device)
        report["diagnostic_color"] = "Magenta cloth-only candidate mask sentinel; not final red-team material. Original nonmask PBR unchanged in memory. No source/UE assets saved."
        (args.output / "cloth_region_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("STONEAXE_CLOTH_ANALYSIS " + json.dumps({key: report[key] for key in ("status", "candidate_triangles", "mask_covered_pixels", "mask_nonselected_triangle_overlap_pixels")}))


if __name__ == "__main__":
    main()
