"""Six diagnostic closeups and actual Blender Mikk/normal-map sampling; no asset approval."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_stone_slinger_texture as texture


BLEND = texture.BRANCH / "textured_v01/pbr_review_02/Unit_StoneSlinger_textured.blend"
BLEND_SHA = "094dbc35f5b8a98e07d94a7074e91f92e1fe8d3371fe3f15fb15cc63b4228d51"


def unit(vector):
    length = np.linalg.norm(vector)
    if length < 1e-10:
        raise ValueError("Degenerate tangent/normal")
    return vector / length


def sample_bilinear(image, coordinates):
    width, height = image.size
    horizontal = float(coordinates[0] % 1.0) * width - .5
    vertical = float(coordinates[1] % 1.0) * height - .5
    left, bottom = math.floor(horizontal), math.floor(vertical)
    fraction_x, fraction_y = horizontal - left, vertical - bottom
    color = np.zeros(3)
    for offset_x, weight_x in ((0, 1 - fraction_x), (1, fraction_x)):
        for offset_y, weight_y in ((0, 1 - fraction_y), (1, fraction_y)):
            pixel = ((bottom + offset_y) % height * width + (left + offset_x) % width) * 4
            color += np.array(image.pixels[pixel:pixel + 3]) * weight_x * weight_y
    return color


def mapped_normal_checks(mesh, changes, normal_image, normal_strength, use_map):
    mesh.calc_tangents(uvmap=mesh.uv_layers.active.name)
    results = []
    for row in changes:
        polygon = mesh.polygons[row["returned_face"]]
        corners = list(polygon.loop_indices)
        if len(corners) != 3:
            raise ValueError("Expected retained cloud triangle")
        target = next(index for index, loop_index in enumerate(corners) if mesh.loops[loop_index].vertex_index == row["returned_vertex"])
        weights = np.array([.01, .01, .01])
        weights[target] = .98
        normals = np.array([mesh.corner_normals[index].vector[:] for index in corners])
        tangents = np.array([mesh.loops[index].tangent[:] for index in corners])
        signs = np.array([mesh.loops[index].bitangent_sign for index in corners])
        if len(set(signs)) != 1:
            raise ValueError("Mixed tangent handedness in one sampled triangle")
        normal = unit(weights @ normals)
        tangent = weights @ tangents
        tangent = unit(tangent - normal * np.dot(tangent, normal))
        bitangent = np.cross(normal, tangent) * signs[0]
        coordinates = weights @ np.array([mesh.uv_layers.active.data[index].uv[:] for index in corners])
        sampled = sample_bilinear(normal_image, coordinates)
        tangent_normal = sampled * 2 - 1
        tangent_normal[:2] *= normal_strength
        tangent_normal = unit(tangent_normal)
        shaded = unit(tangent * tangent_normal[0] + bitangent * tangent_normal[1] + normal * tangent_normal[2]) if use_map else normal
        points = np.array([mesh.vertices[mesh.loops[index].vertex_index].co[:] for index in corners])
        geometric = unit(np.cross(points[1] - points[0], points[2] - points[0]))
        results.append({"source_render_vertex": row["source_vertex"], "returned_render_vertex": row["returned_vertex"],
                        "triangle": row["returned_face"], "barycentric_weights": weights.tolist(), "uv_blender": coordinates.tolist(),
                        "sampled_linear_rgb": sampled.tolist(), "basis_normal_blender": normal.tolist(),
                        "mikk_tangent_blender": tangent.tolist(), "bitangent_sign": float(signs[0]),
                        "mapped_normal_blender": shaded.tolist(), "geometric_normal_blender": geometric.tolist(),
                        "basis_dot_geometric_face": float(normal @ geometric), "mapped_dot_geometric_face": float(shaded @ geometric)})
    return {"method": "Actual Blender Mikk corner tangents and custom normals, barycentric sample98percent at the affected corner plus1percent at each neighbor, repeat-wrapped bilinear level0 normal-image RGB. This is a diagnostic numerical sample, not GPU shader/mip identity proof.",
            "normal_image": normal_image.name, "normal_image_colorspace": normal_image.colorspace_settings.name,
            "normal_image_size": list(normal_image.size), "normal_strength": normal_strength,
            "normal_map_enabled": use_map, "rows": results,
            "mapped_negative_face_dot_samples": sum(row["mapped_dot_geometric_face"] < 0 for row in results)}


def run(output):
    import bpy

    if texture.record(BLEND)["sha256"] != BLEND_SHA:
        raise ValueError("Frozen original PBR blend changed")
    source = texture.read_glb(texture.SOURCE)[2]
    returned = texture.read_glb(texture.RETURNED)[2]
    comparison = texture.compare(source, returned)
    if not comparison["geometry_and_index_connectivity_passed"]:
        raise ValueError("Geometry/connectivity prerequisite failed")
    restored = returned["POSITION"].astype(float) * comparison["restore_uniform_scale"] + comparison["restore_gltf_y_up_translation_m"]
    source_ids, returned_ids = texture.position_correspondence(source["POSITION"].astype(float), restored)
    before = texture.corner_groups(source, source["POSITION"].astype(float), source_ids)
    after = texture.corner_groups(returned, restored, returned_ids)
    returned_to_source = {}
    for key in before:
        for original_index, returned_index in zip(before[key][0]["indices"], after[key][0]["indices"]):
            if int(returned_index) in returned_to_source and returned_to_source[int(returned_index)] != int(original_index):
                raise ValueError("Normal mapping is not single-valued")
            returned_to_source[int(returned_index)] = int(original_index)
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Unexpected diagnostic mesh count")
    obj = objects[0]
    original = obj.data
    actual_positions = np.array([vertex.co[:] for vertex in original.vertices])[:, (0, 2, 1)] * (1, 1, -1)
    if len(actual_positions) != len(restored) or np.max(np.linalg.norm(actual_positions - restored, axis=1)) > 1e-6:
        raise ValueError("Blender/cloud vertex order differs")
    if not np.array_equal(np.array([polygon.vertices[:] for polygon in original.polygons]), returned["indices"]):
        raise ValueError("Blender/cloud triangle index order differs")
    material = obj.material_slots[0].material
    principled = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    normal_input = principled.inputs["Normal"]
    if len(normal_input.links) != 1:
        raise ValueError("Expected one actual PBR normal-map link")
    normal_output = normal_input.links[0].from_socket
    normal_node = normal_output.node
    if normal_node.type != "NORMAL_MAP" or normal_node.space != "TANGENT" or len(normal_node.inputs["Color"].links) != 1:
        raise ValueError("Unexpected normal-map graph")
    normal_image = normal_node.inputs["Color"].links[0].from_node.image
    if normal_image.colorspace_settings.name != "Non-Color":
        raise ValueError("Normal image incorrectly uses color conversion")
    strength = normal_node.inputs["Strength"].default_value
    experiment = original.copy()
    experiment.name = "DIAGNOSTIC_SOURCE_BASIS_NOT_APPROVED"
    old_normals = []
    for loop in experiment.loops:
        normal = source["NORMAL"][returned_to_source[loop.vertex_index]]
        old_normals.append((float(normal[0]), float(-normal[2]), float(normal[1])))
    experiment.normals_split_custom_set(old_normals)
    experiment.update()
    assigned_error = max(np.linalg.norm(np.array(normal) - np.array(actual.vector[:])) for normal, actual in zip(old_normals, experiment.corner_normals))
    spec = importlib.util.spec_from_file_location("slinger_basis_prep", texture.ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)
    output.mkdir(parents=True, exist_ok=False)
    bpy.context.scene.cycles.samples = 8
    diagnostic = []
    images = []
    variants = [("returned_pbr", original, True), ("returned_basis_without_normal_map", original, False),
                ("source_basis_experiment_unrebaked", experiment, True)]
    for name, mesh, enable_map in variants:
        obj.data = mesh
        for link in list(normal_input.links):
            material.node_tree.links.remove(link)
        if enable_map:
            material.node_tree.links.new(normal_output, normal_input)
        bpy.context.view_layer.update()
        diagnostic.append({"variant": name, "analysis": mapped_normal_checks(mesh, comparison["normal_change_diagnostic"]["large_changes"], normal_image, strength, enable_map)})
        for view, direction in (("front", (.8, 1, .15)), ("back", (-.8, 1, .1))):
            bpy.context.scene.cycles.seed = 0
            path = output / (name + "_" + view + ".png")
            prep.render_view(path, objects, direction, size=512, target=(.005, .085, 1.188), framing=.24)
            images.append(texture.record(path))
    obj.data = original
    for link in list(normal_input.links):
        material.node_tree.links.remove(link)
    material.node_tree.links.new(normal_output, normal_input)
    if texture.record(BLEND)["sha256"] != BLEND_SHA:
        raise ValueError("Frozen original PBR changed during diagnostic")
    result = {"asset_id": "Unit_StoneSlinger", "status": "six_diagnostic_views_not_asset_approval",
              "script": texture.record(Path(__file__)), "source_pbr_blend": texture.record(BLEND),
              "images": images, "variants": diagnostic, "experimental_source_normal_max_assignment_error": float(assigned_error),
              "original_assets_saved_or_overwritten": False, "production_approved": False,
              "caveat": "Third group intentionally uses the old source custom normals with the new unrebaked map to isolate basis sensitivity; it is NOT a repaired or approved PBR asset."}
    texture.save(output / "basis_review.json", result)
    print(json.dumps({"status": result["status"], "images": len(images), "negative_shading_samples": {row["variant"]: row["analysis"]["mapped_negative_face_dot_samples"] for row in diagnostic}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a fresh directory")
    run(output)


if __name__ == "__main__":
    main()
