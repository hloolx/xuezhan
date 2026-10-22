"""Plan a four-render-vertex normal correction and isolated neutral-detail texture patch."""
from collections import defaultdict
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_stone_slinger_texture as texture


BASIS = texture.BRANCH / "textured_v01/normal_basis_01/normal_basis_diagnostic.json"
BASIS_SHA = "9c33658f12efcb39cb71bb59572e8f367fe3577a7b7169d3e9ae608673dbd168"
BLEND = texture.BRANCH / "textured_v01/pbr_review_02/Unit_StoneSlinger_textured.blend"
BLEND_SHA = "094dbc35f5b8a98e07d94a7074e91f92e1fe8d3371fe3f15fb15cc63b4228d51"


def cross2(first, second):
    return first[0] * second[1] - first[1] * second[0]


def signed_area(polygon):
    return sum(cross2(first, second) for first, second in zip(polygon, polygon[1:] + polygon[:1])) * .5


def intersection_area(first, second):
    polygon = [np.array(point, dtype=float) for point in first]
    clip = [np.array(point, dtype=float) for point in second]
    orientation = 1 if signed_area(clip) >= 0 else -1
    for start, end in zip(clip, clip[1:] + clip[:1]):
        if not polygon:
            break
        result = []
        previous = polygon[-1]
        previous_distance = cross2(end - start, previous - start) * orientation
        for point in polygon:
            distance = cross2(end - start, point - start) * orientation
            if (distance >= 0) != (previous_distance >= 0):
                fraction = previous_distance / (previous_distance - distance)
                result.append(previous + (point - previous) * fraction)
            if distance >= 0:
                result.append(point)
            previous, previous_distance = point, distance
        polygon = result
    return abs(signed_area(polygon)) if len(polygon) >= 3 else 0.0


def barycentric(points, triangle):
    edge_first, edge_second = triangle[1] - triangle[0], triangle[2] - triangle[0]
    denominator = cross2(edge_first, edge_second)
    if abs(denominator) < 1e-14:
        raise ValueError("Degenerate UV triangle")
    relative = points - triangle[0]
    first = (relative[:, 0] * edge_second[1] - relative[:, 1] * edge_second[0]) / denominator
    second = (edge_first[0] * relative[:, 1] - edge_first[1] * relative[:, 0]) / denominator
    return np.column_stack((1 - first - second, first, second))


def footprint(triangles, indices, target_vertices, size=2048):
    target_faces = np.flatnonzero(np.any(np.isin(indices, target_vertices), axis=1))
    minimum = triangles.min(axis=1)
    maximum = triangles.max(axis=1)
    overlaps = []
    base_pixels = {}
    for face in target_faces:
        triangle = triangles[face]
        candidates = np.flatnonzero(np.all(maximum > minimum[face], axis=1) & np.all(minimum < maximum[face], axis=1))
        for other in candidates:
            if other == face:
                continue
            area = intersection_area(triangle, triangles[other])
            if area > 1e-12:
                overlaps.append({"target_face": int(face), "other_face": int(other), "uv_overlap_area": area, "pixel_area": area * size * size})
        low = np.maximum(np.floor(minimum[face] * size).astype(int), 0)
        high = np.minimum(np.floor(maximum[face] * size).astype(int), size - 1)
        pixels = np.array([(column, row) for row in range(low[1], high[1] + 1) for column in range(low[0], high[0] + 1)])
        weights = barycentric((pixels + .5) / size, triangle)
        selected = np.min(weights, axis=1) >= -1e-10
        target_corner = np.isin(indices[face], target_vertices)
        influence = weights @ target_corner.astype(float)
        for pixel, value in zip(pixels[selected], influence[selected]):
            key = tuple(int(coordinate) for coordinate in pixel)
            base_pixels[key] = max(base_pixels.get(key, 0), float(np.clip(value, 0, 1)))
    padding = dict(base_pixels)
    for (column, row), influence in base_pixels.items():
        for offset_y in range(-2, 3):
            for offset_x in range(-2, 3):
                key = column + offset_x, row + offset_y
                if 0 <= key[0] < size and 0 <= key[1] < size and key not in base_pixels:
                    padding[key] = max(padding.get(key, 0), influence)
    pixel_keys = sorted(padding)
    positions = (np.array(pixel_keys) + .5) / size
    foreign = defaultdict(list)
    for face, triangle in enumerate(triangles):
        if face in target_faces:
            continue
        nearby = np.flatnonzero(np.all(positions >= minimum[face], axis=1) & np.all(positions <= maximum[face], axis=1))
        if not len(nearby):
            continue
        weights = barycentric(positions[nearby], triangle)
        for index in nearby[np.min(weights, axis=1) >= -1e-10]:
            foreign[pixel_keys[index]].append(face)
    collisions = sorted(set(base_pixels).intersection(foreign))
    safe = {key: value for key, value in padding.items() if key not in foreign}
    return {"target_faces": target_faces.tolist(), "exact_UV_triangle_overlaps": overlaps,
            "base_texel_count": len(base_pixels), "two_pixel_padding_candidates": len(padding) - len(base_pixels),
            "foreign_triangle_padding_texels_excluded": len(foreign), "base_texel_foreign_collisions": [list(key) for key in collisions],
            "foreign_neighbor_faces": sorted({face for faces in foreign.values() for face in faces}),
            "safe_texel_count": len(safe), "safe_texels_gltf_top_left": [[column, row, influence] for (column, row), influence in sorted(safe.items())],
            "image_size": [size, size], "neutral_policy": "Blend decoded tangent-space vector toward(0,0,1) by the barycentric influence of the corrected vertices. At outer unchanged edges influence tends to0; at corrected vertices it tends to1. Two-texel dilation is allowed only in unoccupied atlas space. Every foreign-face texel is excluded; no UV position changes.",
            "passed": not overlaps and not collisions}


def plan(output):
    if texture.record(BASIS)["sha256"] != BASIS_SHA or texture.record(BLEND)["sha256"] != BLEND_SHA:
        raise ValueError("Frozen basis diagnostic or PBR blend changed")
    basis = json.loads(BASIS.read_text(encoding="utf-8-sig"))
    selected = {row["returned_render_vertex"]: row for row in basis["rows"] if row["native_cleaned_vertex"] in {5539, 5540}}
    if set(selected) != {878, 879, 8242, 8243}:
        raise ValueError("Unexpected affected vertex identity")
    arrays = texture.read_glb(texture.RETURNED)[2]
    triangles = arrays["TEXCOORD_0"][arrays["indices"]].astype(float)
    region = footprint(triangles, arrays["indices"], list(selected))
    changes = [{"returned_render_vertex": index, "native_cleaned_vertex": row["native_cleaned_vertex"],
                "normal_gltf_y_up": row["area_weighted_fan_normal"],
                "normal_blender_z_up": [row["area_weighted_fan_normal"][0], -row["area_weighted_fan_normal"][2], row["area_weighted_fan_normal"][1]]} for index, row in sorted(selected.items())]
    report = {"asset_id": "Unit_StoneSlinger", "status": "local_normal_neutral_detail_plan_ready" if region["passed"] else "UV_region_gate_failed",
              "script": texture.record(Path(__file__)), "source_PBR_blend": texture.record(BLEND), "returned_GLB": texture.record(texture.RETURNED),
              "native_basis_diagnostic": texture.record(BASIS), "vertex_changes": changes, "texture_region": region,
              "position_face_UV_change_allowed": False, "unaffected_corner_normal_change_allowed": False,
              "native3921_remains_unchanged": True,
              "texture_policy": "Independent PNG normal derivative only; source JPEG/basecolor/metallicroughness remain byte-identical. This is a controlled loss of tiny local normal-map detail, NOT a claim that the original map is compatible with the corrected basis or a restoration of the old source normals.",
              "apply_gates": ["Only4render vertices/11triangle corners get geometric fan normals; preserve exact encoded custom normals elsewhere", "Actual Mikk samples on a dense barycentric grid over all9affected triangles must be checked", "Derive the normal texture only inside proven non-overlapping owned texels/unoccupied padding; compare decoded pixels outside mask exactly", "UV/positions/face indices remain unchanged; fresh GLB roundtrip and two closeups plus full figure check", "No formalrig/production approval from this local correction"],
              "applied": False, "blender_started": False, "paid_submission": False, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    texture.save(output / "repair_plan.json", report)
    print(json.dumps({"status": report["status"], "vertices": list(selected), "texture_region": {key: value for key, value in region.items() if key != "safe_texels_gltf_top_left"}}))


def image_pixels(image):
    values = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)


def sample_pixels(pixels, coordinates):
    height, width = pixels.shape[:2]
    positions = coordinates % 1.0 * (width, height) - .5
    low = np.floor(positions).astype(int)
    fraction = positions - low
    colors = np.zeros((len(coordinates), 3))
    for offset_x in (0, 1):
        for offset_y in (0, 1):
            weight = (fraction[:, 0] if offset_x else 1 - fraction[:, 0]) * (fraction[:, 1] if offset_y else 1 - fraction[:, 1])
            colors += pixels[(low[:, 1] + offset_y) % height, (low[:, 0] + offset_x) % width, :3] * weight[:, None]
    return colors


def normalized_rows(vectors):
    lengths = np.linalg.norm(vectors, axis=1)
    if np.min(lengths) < 1e-10:
        raise ValueError("Degenerate Mikk basis")
    return vectors / lengths[:, None]


def dense_mikk(mesh, pixels, faces, subdivisions=8):
    mesh.calc_tangents(uvmap=mesh.uv_layers.active.name)
    weights = np.array([(first / subdivisions, second / subdivisions, 1 - (first + second) / subdivisions)
                        for first in range(subdivisions + 1) for second in range(subdivisions + 1 - first)])
    result = []
    for face in faces:
        polygon = mesh.polygons[face]
        loops = list(polygon.loop_indices)
        normal = normalized_rows(weights @ np.array([mesh.corner_normals[index].vector[:] for index in loops]))
        tangent = weights @ np.array([mesh.loops[index].tangent[:] for index in loops])
        tangent = normalized_rows(tangent - normal * np.sum(tangent * normal, axis=1)[:, None])
        signs = [mesh.loops[index].bitangent_sign for index in loops]
        if len(set(signs)) != 1:
            raise ValueError("Mixed handedness inside one triangle")
        bitangent = np.cross(normal, tangent) * signs[0]
        coordinates = weights @ np.array([mesh.uv_layers.active.data[index].uv[:] for index in loops])
        detail = normalized_rows(sample_pixels(pixels, coordinates) * 2 - 1)
        shaded = normalized_rows(tangent * detail[:, 0, None] + bitangent * detail[:, 1, None] + normal * detail[:, 2, None])
        points = np.array([mesh.vertices[mesh.loops[index].vertex_index].co[:] for index in loops])
        geometric = np.cross(points[1] - points[0], points[2] - points[0])
        geometric /= np.linalg.norm(geometric)
        base_dots, shaded_dots = normal @ geometric, shaded @ geometric
        result.append({"face": int(face), "samples": len(weights), "basis_minimum_face_dot": float(base_dots.min()),
                       "mapped_minimum_face_dot": float(shaded_dots.min()),
                       "basis_negative_samples": int((base_dots < 0).sum()), "mapped_negative_samples": int((shaded_dots < 0).sum()),
                       "worst_barycentric_weights": weights[int(np.argmin(shaded_dots))].tolist(),
                       "all_mapped_face_dots": shaded_dots.tolist(), "mapped_normals": shaded.tolist()})
    return result


def apply(output, plan_path):
    import bpy

    frozen = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if texture.record(BLEND)["sha256"] != BLEND_SHA or texture.record(BASIS)["sha256"] != BASIS_SHA:
        raise ValueError("Frozen source lineage changed")
    if frozen["source_PBR_blend"] != texture.record(BLEND) or frozen["returned_GLB"] != texture.record(texture.RETURNED):
        raise ValueError("Repair plan source drift")
    arrays = texture.read_glb(texture.RETURNED)[2]
    targets = [row["returned_render_vertex"] for row in frozen["vertex_changes"]]
    actual_region = footprint(arrays["TEXCOORD_0"][arrays["indices"]].astype(float), arrays["indices"], targets)
    if not actual_region["passed"] or actual_region != frozen["texture_region"]:
        raise ValueError("Actual atlas ownership differs from frozen safe region")
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Unexpected original PBR mesh count")
    obj = objects[0]
    original = obj.data
    if not np.array_equal(np.array([polygon.vertices[:] for polygon in original.polygons]), arrays["indices"]):
        raise ValueError("Blender/cloud triangle correspondence changed")
    candidate = original.copy()
    candidate.name = "StoneSlinger_LocalGeometricFanNormalRepair"
    prior_normals = np.array([value.vector[:] for value in original.corner_normals])
    target_by_vertex = {row["returned_render_vertex"]: row["normal_blender_z_up"] for row in frozen["vertex_changes"]}
    target_mask = np.array([loop.vertex_index in target_by_vertex for loop in candidate.loops])
    desired = np.array([target_by_vertex.get(loop.vertex_index, prior_normals[loop.index]) for loop in candidate.loops])
    original_encoded = original.attributes["custom_normal"]
    properties = [prop.identifier for prop in original_encoded.data[0].bl_rna.properties
                  if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
    if len(properties) != 1:
        raise ValueError("Cannot identify encoded custom-normal storage")
    property_name = properties[0]
    encoded = np.empty(len(original.loops) * 2, dtype=np.int32)
    original_encoded.data.foreach_get(property_name, encoded)
    candidate.normals_split_custom_set(desired.tolist())
    new_encoded = np.empty_like(encoded)
    candidate.attributes["custom_normal"].data.foreach_get(property_name, new_encoded)
    new_encoded.reshape(-1, 2)[~target_mask] = encoded.reshape(-1, 2)[~target_mask]
    candidate.attributes["custom_normal"].data.foreach_set(property_name, new_encoded)
    candidate.update()
    actual_normals = np.array([value.vector[:] for value in candidate.corner_normals])
    outside_error = float(np.linalg.norm(actual_normals[~target_mask] - prior_normals[~target_mask], axis=1).max())
    target_error = float(np.linalg.norm(actual_normals[target_mask] - desired[target_mask], axis=1).max())
    unchanged = {"positions": all(first.co[:] == second.co[:] for first, second in zip(original.vertices, candidate.vertices)),
                 "face_indices": all(first.vertices[:] == second.vertices[:] for first, second in zip(original.polygons, candidate.polygons)),
                 "UVs": all(first.uv[:] == second.uv[:] for first, second in zip(original.uv_layers.active.data, candidate.uv_layers.active.data)),
                 "sharp_edge_flags": all(first.use_edge_sharp == second.use_edge_sharp for first, second in zip(original.edges, candidate.edges)),
                 "unaffected_encoded_corner_normals": bool(np.array_equal(new_encoded.reshape(-1, 2)[~target_mask], encoded.reshape(-1, 2)[~target_mask]))}
    if not all(unchanged.values()) or outside_error != 0 or target_error > 1e-3 or int(target_mask.sum()) != 11:
        raise ValueError(f"Strict geometry/UV/normal-domain gate failed: {unchanged}, outside={outside_error}, target={target_error}")
    original_material = original.materials[0]
    original_normal_node = next(node for node in original_material.node_tree.nodes if node.type == "NORMAL_MAP")
    image_node = original_normal_node.inputs["Color"].links[0].from_node
    source_image = image_node.image
    if source_image.colorspace_settings.name != "Non-Color" or original_normal_node.inputs["Strength"].default_value != 1:
        raise ValueError("Unexpected normal-map decoding")
    source_pixels = image_pixels(source_image)
    changed_pixels = source_pixels.copy()
    pixel_mask = np.zeros(source_pixels.shape[:2], dtype=bool)
    for column, top_row, influence in actual_region["safe_texels_gltf_top_left"]:
        row = source_pixels.shape[0] - 1 - top_row
        detail = source_pixels[row, column, :3].astype(float) * 2 - 1
        detail = detail * (1 - influence) + np.array((0, 0, 1)) * influence
        detail /= np.linalg.norm(detail)
        changed_pixels[row, column, :3] = (detail + 1) * .5
        pixel_mask[row, column] = True
    if not np.array_equal(source_pixels[~pixel_mask], changed_pixels[~pixel_mask]):
        raise ValueError("Derived texture altered a foreign texel")
    output.mkdir(parents=True, exist_ok=False)
    derived_image = source_image.copy()
    derived_image.name = "StoneSlinger_LocalNeutralDetail_Normal"
    derived_image.pixels.foreach_set(changed_pixels.reshape(-1))
    derived_image.update()
    derived_image.filepath_raw = str(output / "StoneSlinger_LocalNeutralDetail_Normal.png")
    derived_image.file_format = "PNG"
    derived_image.save()
    reloaded = bpy.data.images.load(derived_image.filepath_raw, check_existing=False)
    reloaded.colorspace_settings.name = "Non-Color"
    actual_pixels = image_pixels(reloaded)
    pixel_outside_error = float(np.max(np.abs(actual_pixels[~pixel_mask] - source_pixels[~pixel_mask])))
    if pixel_outside_error != 0 or not np.array_equal(source_pixels, image_pixels(source_image)):
        raise ValueError(f"Saved PNG changed outside-mask source pixels: {pixel_outside_error}")
    candidate_material = original_material.copy()
    candidate_material.name = "StoneSlinger_LocalBasisMatchedPBR"
    candidate_material.node_tree.nodes[image_node.name].image = reloaded
    candidate.materials[0] = candidate_material
    faces = actual_region["target_faces"]
    neighbors = actual_region["foreign_neighbor_faces"]
    baseline_dense = dense_mikk(original, source_pixels, faces)
    candidate_dense = dense_mikk(candidate, actual_pixels, faces)
    baseline_neighbors = dense_mikk(original, source_pixels, neighbors)
    candidate_neighbors = dense_mikk(candidate, actual_pixels, neighbors)
    neighbor_delta = max(float(np.linalg.norm(np.array(first["mapped_normals"]) - np.array(second["mapped_normals"]), axis=1).max()) for first, second in zip(baseline_neighbors, candidate_neighbors))
    dense_passed = all(row["basis_minimum_face_dot"] > 0 and row["mapped_minimum_face_dot"] > 0 for row in candidate_dense)
    result = {"asset_id": "Unit_StoneSlinger", "status": "local_repair_numeric_gate_passed_pending_actual_views" if dense_passed else "local_repair_dense_numeric_gate_failed_no_model_export",
              "script": texture.record(Path(__file__)), "plan": texture.record(plan_path), "source_blend": texture.record(BLEND),
              "strict_unchanged_fields": unchanged, "changed_render_vertices": targets, "changed_loop_count": int(target_mask.sum()),
              "unaffected_normal_max_error": outside_error, "target_geometric_normal_max_error": target_error,
              "normal_map_derivative": texture.record(Path(derived_image.filepath_raw)), "texture_region": actual_region,
              "decoded_PNG_outside_mask_max_error": pixel_outside_error, "decoded_source_image_unchanged": True,
              "dense_sample_definition": "45barycentric points including every vertex/edge/midtriangle per face,9affected faces=405samples; actual Blender Mikk and actual savedPNG bilinear level0. Minima and all45dots per face retained.",
              "baseline_affected_dense": baseline_dense, "candidate_affected_dense": candidate_dense,
              "baseline_neighbor_dense": baseline_neighbors, "candidate_neighbor_dense": candidate_neighbors,
              "maximum_neighbor_filtered_shading_normal_delta": neighbor_delta,
              "dense_gate_passed": dense_passed, "pbr_stage_approved": False, "rig_approved": False, "production_approved": False}
    texture.save(output / "repair_report.json", result)
    if not dense_passed:
        raise ValueError("At least one affected face has a nonpositive dense normal sample; export blocked")
    module_spec = importlib.util.spec_from_file_location("local_normal_repair_prep", texture.ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(prep)
    images = []
    for stage, mesh in (("before", original), ("after", candidate)):
        obj.data = mesh
        bpy.context.view_layer.update()
        for view, direction in (("front", (.8, 1, .15)), ("back", (-.8, 1, .1))):
            bpy.context.scene.cycles.samples = 8
            bpy.context.scene.cycles.seed = 0
            path = output / (stage + "_neck_" + view + ".png")
            prep.render_view(path, objects, direction, size=512, target=(.005, .085, 1.188), framing=.24)
            images.append(texture.record(path))
    path = output / "after_preview.png"
    prep.render_view(path, objects, (1, -1, .45), size=512)
    images.append(texture.record(path))
    prep.select(objects)
    model = output / "Unit_StoneSlinger_PBR_LocalNormalRepair.glb"
    bpy.ops.export_scene.gltf(filepath=str(model), export_format="GLB", use_selection=True, export_yup=True,
                              export_animations=False, export_skins=False, export_morph=False, export_materials="EXPORT")
    roundtrip = prep.verify_glb(model, objects)
    blend = output / "Unit_StoneSlinger_PBR_LocalNormalRepair.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if texture.record(BLEND)["sha256"] != BLEND_SHA or frozen["returned_GLB"] != texture.record(texture.RETURNED):
        raise ValueError("Frozen original assets changed")
    result.update({"status": "local_normal_repair_five_views_and_export_pending_visual_review", "images": images,
                   "model": texture.record(model), "blend": texture.record(blend), "roundtrip": roundtrip,
                   "original_frozen_assets_unchanged": True})
    texture.save(output / "repair_report.json", result)
    print(json.dumps({"status": result["status"], "images": len(images), "dense_gate_passed": dense_passed,
                      "minimum_mapped_dot": min(row["mapped_minimum_face_dot"] for row in candidate_dense),
                      "normal_outside_error": outside_error, "pixel_outside_error": pixel_outside_error,
                      "neighbor_filtered_delta": neighbor_delta, "roundtrip": roundtrip}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("plan", "apply"), default="plan")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a fresh directory")
    if args.mode == "plan":
        plan(output)
    elif args.plan:
        apply(output, args.plan.resolve())
    else:
        raise ValueError("Apply requires a frozen plan")


if __name__ == "__main__":
    main()
