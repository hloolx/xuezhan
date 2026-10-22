"""Audit the immutable mammoth texture return and prepare a gated local PBR review."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from itertools import combinations
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_stone_slinger_texture as core
import cleanup_stone_slinger as native_reader


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
BRANCH = ART / "tripo_processed/mammoth_v01"
OWNED = BRANCH / "textured_v01"
SOURCE = BRANCH / "cleanup_v01/candidate_01/Mount_Mammoth_cleanup.glb"
SOURCE_SHA = "695efa8a59ccd2f4b39b03482ed64b44dfaff92331676e76ba26fad817f5e73f"
RETURNED = ART / "tripo_raw/Mount_Mammoth/textured_v01_cleanup01/model.glb"
RETURNED_SHA = "77eb2630093b7a99073ef0c9ec48409f751d653f9af09147e37719c3030443d8"
TASK = RETURNED.with_name("task.json")
TASK_ID = "bec13c23-8626-40a5-8cc0-3c700c44506d"
CLEANUP = SOURCE.with_name("cleanup_report.json")
APPROVAL = SOURCE.with_name("root_stage_review.json")
NORMALIZATION = BRANCH / "normalized_01/geometry_report.json"
DIAGNOSTIC_MODEL = OWNED / "pbr_review_01/Mount_Mammoth_PBR.glb"
DIAGNOSTIC_MODEL_SHA = "d0208f1a64a96c72c640b179314bbff3b44e5d96a6ef96d50f620ae78bfc9473"
FAILED_REPORT = OWNED / "pbr_review_01/pbr_report.json"
FAILED_REPORT_SHA = "7cb022b053f1e476ba98535f53158d0dd08372863544f5dead3b53c604191656"


def fresh_output(path):
    path = path.resolve()
    if not path.is_relative_to(OWNED.resolve()) or path == OWNED.resolve():
        raise ValueError("Output must be a new child of the owned textured_v01 directory")
    if path.exists():
        raise FileExistsError("Never overwrite existing evidence")
    return path


def checked_record(expected):
    actual = core.record(Path(expected["path"]))
    if actual != expected:
        raise ValueError("Frozen input changed: " + expected["path"])
    return actual


def triangle_mapping(source, returned, restore=True):
    original = source["POSITION"].astype(float)
    cloud = returned["POSITION"].astype(float)
    scale = float(np.ptp(original[:, 1]) / np.ptp(cloud[:, 1])) if restore else 1.0
    translation = original.min(axis=0) - cloud.min(axis=0) * scale if restore else np.zeros(3)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid positive uniform scale")
    positions = cloud * scale + translation
    source_ids, returned_ids = core.position_correspondence(original, positions)
    before = core.corner_groups(source, original, source_ids)
    after = core.corner_groups(returned, positions, returned_ids)
    if before.keys() != after.keys() or any(len(value) != 1 for value in before.values()) or any(len(value) != 1 for value in after.values()):
        raise ValueError("Full unique triangle correspondence failed")
    source_to_returned = defaultdict(set)
    returned_to_source = defaultdict(set)
    corner_source = np.full(returned["indices"].shape, -1, dtype=np.int64)
    maximum_position = maximum_uv = maximum_normal = 0.0
    reversed_faces = []
    normal_rows = []
    for key, entries in before.items():
        expected, actual = entries[0], after[key][0]
        expected_cycle, actual_cycle = expected["winding"], actual["winding"]
        if not any(actual_cycle == expected_cycle[offset:] + expected_cycle[:offset] for offset in range(3)):
            reversed_faces.append(actual["face"])
        maximum_position = max(maximum_position, float(np.linalg.norm(expected["position"] - actual["position"], axis=1).max()))
        maximum_uv = max(maximum_uv, float(np.linalg.norm(expected["uv"] - actual["uv"], axis=1).max()))
        maximum_normal = max(maximum_normal, float(np.linalg.norm(expected["normal"] - actual["normal"], axis=1).max()))
        for old, new in zip(expected["indices"], actual["indices"]):
            old, new = int(old), int(new)
            source_to_returned[old].add(new)
            returned_to_source[new].add(old)
            corner = int(np.flatnonzero(returned["indices"][actual["face"]] == new)[0])
            corner_source[actual["face"], corner] = old
            normal_rows.append((old, new, actual["face"], corner))
    if np.any(corner_source < 0):
        raise ValueError("Not every actual corner was mapped")
    bijective = all(len(values) == 1 for values in source_to_returned.values()) and all(len(values) == 1 for values in returned_to_source.values())
    result = {"triangles": len(source["indices"]), "corners": int(corner_source.size),
              "source_render_vertices": len(original), "returned_render_vertices": len(cloud),
              "full_triangle_multiset_identical": True, "winding_reversed_faces": reversed_faces,
              "restore_uniform_scale": scale, "restore_gltf_y_up_translation_m": translation.tolist(),
              "restore_blender_z_up_translation_m": [float(translation[0]), float(-translation[2]), float(translation[1])],
              "maximum_position_error_m": maximum_position, "maximum_uv_error": maximum_uv,
              "maximum_normal_vector_change": maximum_normal, "render_vertex_bijection_preserved": bijective,
              "surface_and_uv_passed": maximum_position < 1e-6 and maximum_uv < 1e-6 and not reversed_faces,
              "returned_vertex_merges": [{"returned_vertex": index, "source_render_vertices": sorted(values)} for index, values in returned_to_source.items() if len(values) > 1]}
    return result, corner_source, source_to_returned, normal_rows


def native_identity(source):
    cleanup = json.loads(CLEANUP.read_text(encoding="utf-8-sig"))
    approval = json.loads(APPROVAL.read_text(encoding="utf-8-sig"))
    if approval["source"]["sha256"] != SOURCE_SHA or not approval["texture_generation_approved"] or approval["geometry_report_sha256"] != core.record(CLEANUP)["sha256"]:
        raise ValueError("Missing exact root cleanup-stage approval")
    checked_record(cleanup["analysis"])
    checked_record(cleanup["source"])
    analysis = json.loads(Path(cleanup["analysis"]["path"]).read_text(encoding="utf-8-sig"))
    checked_record(analysis["normalization_report"])
    vertices, polygons, _, _ = native_reader.read_fbx(Path(cleanup["source"]["path"]))
    positions = list(vertices)
    faces = [list(polygon) for polygon in polygons]
    split_pairs = []
    for patch in analysis["plan"]["accessory_patches"]:
        mapping = {int(key): value for key, value in patch["duplicate_vertex_map"].items()}
        for old, new in sorted(mapping.items(), key=lambda item: item[1]):
            if new != len(positions):
                raise ValueError("Nonsequential immutable native split")
            positions.append(vertices[old])
            split_pairs.append((old, new))
        for face in patch["modified_faces"]:
            faces[face] = [mapping.get(index, index) for index in polygons[face]]
    if len(split_pairs) != 23 or len(faces) != 10078:
        raise ValueError("Unexpected approved split contract")
    matrix = np.array(json.loads(NORMALIZATION.read_text(encoding="utf-8-sig"))["normalization"]["matrix_source_world_to_result"])
    native_positions = (np.column_stack((positions, np.ones(len(positions)))) @ matrix.T)[:, :3]
    native_positions = native_positions[:, (0, 2, 1)] * (1, 1, -1)
    native_ids, render_ids = core.position_correspondence(native_positions, source["POSITION"].astype(float))
    lookup = defaultdict(list)
    for face, polygon in enumerate(faces):
        for triangle in combinations(polygon, 3):
            lookup[tuple(sorted(int(native_ids[index]) for index in triangle))].append(face)
    render_to_native = defaultdict(set)
    source_triangle_polygons = []
    for triangle in source["indices"]:
        matches = lookup[tuple(sorted(int(render_ids[index]) for index in triangle))]
        if len(matches) != 1:
            raise ValueError("Source triangle does not map to exactly one native polygon")
        source_triangle_polygons.append(matches[0])
        mapping = {int(native_ids[index]): index for index in faces[matches[0]]}
        for index in triangle:
            render_to_native[int(index)].add(mapping[int(render_ids[index])])
    if any(len(values) != 1 for values in render_to_native.values()):
        raise ValueError("Source render vertex spans different native identities")
    analysis["source_triangle_native_polygons"] = source_triangle_polygons
    analysis["native_polygons"] = faces
    return {index: next(iter(values)) for index, values in render_to_native.items()}, split_pairs, analysis


def split_identity(render_to_native, split_pairs, source_to_returned):
    native_to_returned = defaultdict(set)
    returned_to_native = defaultdict(set)
    for source_index, values in source_to_returned.items():
        native = render_to_native[source_index]
        native_to_returned[native].update(values)
        for index in values:
            returned_to_native[index].add(native)
    rows = [{"native_original": old, "native_accessory_duplicate": new,
             "shared_returned_vertices": sorted(native_to_returned[old] & native_to_returned[new]),
             "both_identities_present": bool(native_to_returned[old] and native_to_returned[new])} for old, new in split_pairs]
    merges = [{"returned_vertex": index, "native_vertices": sorted(values)} for index, values in returned_to_native.items() if len(values) > 1]
    return {"expected_split_pairs": len(split_pairs), "retained_split_pairs": sum(not row["shared_returned_vertices"] and row["both_identities_present"] for row in rows),
            "all_native_identities_preserved": not merges, "cross_native_merges": merges, "pairs": rows}


def normal_diagnostic(source, returned, rows):
    positions = returned["POSITION"].astype(float)
    triangles = returned["indices"]
    cross = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]], positions[triangles[:, 2]] - positions[triangles[:, 0]])
    lengths = np.linalg.norm(cross, axis=1)
    if np.any(lengths <= 1e-16):
        raise ValueError("Degenerate returned geometric face")
    face_normals = cross / lengths[:, None]
    old = source["NORMAL"][[row[0] for row in rows]].astype(float)
    new = returned["NORMAL"][[row[1] for row in rows]].astype(float)
    old /= np.linalg.norm(old, axis=1)[:, None]
    new /= np.linalg.norm(new, axis=1)[:, None]
    angles = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", old, new), -1, 1)))
    geometric = face_normals[[row[2] for row in rows]]
    old_dots = np.einsum("ij,ij->i", old, geometric)
    new_dots = np.einsum("ij,ij->i", new, geometric)
    detailed = []
    for index in np.flatnonzero((angles > .1) | (new_dots < 0)):
        original_index, returned_index, face, corner = rows[index]
        detailed.append({"source_vertex": original_index, "returned_vertex": returned_index, "returned_face": face,
                         "corner": corner, "angle_degrees": float(angles[index]), "source_dot_geometric": float(old_dots[index]),
                         "returned_dot_geometric": float(new_dots[index])})
    return {"tested_triangle_corners": len(rows), "maximum_angular_change_degrees": float(angles.max()),
            "changed_corner_counts_above_degrees": {str(value): int(np.count_nonzero(angles > value)) for value in (.001, .01, .1, 1, 5, 45, 90)},
            "minimum_source_dot_geometric": float(old_dots.min()), "minimum_returned_dot_geometric": float(new_dots.min()),
            "source_negative_geometric_corners": int(np.count_nonzero(old_dots < 0)),
            "returned_negative_geometric_corners": int(np.count_nonzero(new_dots < 0)),
            "new_negative_geometric_corners": int(np.count_nonzero((new_dots < 0) & (old_dots >= 0))),
            "detailed_changes": detailed,
            "interpretation": "Normal differences are quantified, not automatically failed or approved. Actual Mikk tangent and normal-map sampling plus closeups are still required; no source normals are restored onto an unrebaked map."}


def image_audit(document, binary, decode=True):
    material = document["materials"][0]
    roles = {"normal": material["normalTexture"]["index"],
             "base_color": material["pbrMetallicRoughness"]["baseColorTexture"]["index"],
             "metallic_roughness": material["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"]}
    if len(document["materials"]) != 1 or len(document["images"]) != 3:
        raise ValueError("Expected actual one-material three-image PBR")
    result = []
    for role, texture_index in roles.items():
        texture = document["textures"][texture_index]
        entry = document["images"][texture["source"]]
        view = document["bufferViews"][entry["bufferView"]]
        payload = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
        base = {"role": role, "name": entry.get("name"), "mime_type": entry["mimeType"],
                "texture_index": texture_index, "image_index": texture["source"], "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "required_colorspace": "sRGB" if role == "base_color" else "Non-Color"}
        if not decode:
            result.append(base)
            continue
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            pixels = np.asarray(image.convert("RGB"))
            channels = {name: {"minimum": int(pixels[:, :, index].min()), "maximum": int(pixels[:, :, index].max()),
                               "mean": float(pixels[:, :, index].mean()), "nonzero_pixels": int(np.count_nonzero(pixels[:, :, index]))} for index, name in enumerate(("R", "G", "B"))}
            result.append({**base, "size": list(image.size), "mode": image.mode, "channels": channels})
    return result


def audit(include_images=True):
    if core.record(SOURCE)["sha256"] != SOURCE_SHA or core.record(RETURNED)["sha256"] != RETURNED_SHA:
        raise ValueError("Frozen source/return GLB changed")
    receipt = json.loads(TASK.read_text(encoding="utf-8-sig"))
    if (receipt["task_id"], receipt["status"], receipt["type"]) != (TASK_ID, "success", "texture_model"):
        raise ValueError("Unexpected real texture task receipt")
    _, _, source = core.read_glb(SOURCE)
    document, binary, returned = core.read_glb(RETURNED)
    comparison, corners, source_to_returned, rows = triangle_mapping(source, returned)
    if comparison["triangles"] != 15601:
        raise ValueError("Frozen triangle count differs")
    native, pairs, analysis = native_identity(source)
    split = split_identity(native, pairs, source_to_returned)
    for item in comparison["returned_vertex_merges"]:
        item["native_vertices"] = sorted({native[index] for index in item["source_render_vertices"]})
    dependencies = [SOURCE, RETURNED, TASK, CLEANUP, APPROVAL, NORMALIZATION, Path(analysis["source"]["path"]),
                    Path(json.loads(CLEANUP.read_text(encoding="utf-8-sig"))["analysis"]["path"]), Path(core.__file__), Path(native_reader.__file__)]
    report = {"schema_version": 1, "asset_id": "Mount_Mammoth", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "surface_uv_passed_split_identity_failed" if not split["all_native_identities_preserved"] else "data_passed_pending_actual_pbr_review",
              "source_files": [core.record(path) for path in dependencies], "script": core.record(Path(__file__)),
              "task_id": TASK_ID, "actual_credits_consumed": receipt["credits_consumed"], "comparison": comparison,
              "split_identity": split, "normals": normal_diagnostic(source, returned, rows),
              "images": image_audit(document, binary, decode=include_images), "materials": document["materials"],
              "textures": document["textures"], "source_axis": "+X forward; Blender +Z up, glTF +Y up",
              "blender_started": False, "pbr_visual_approved": False, "rig_approved": False, "production_approved": False}
    return report, source, returned, corners


def restore_split_arrays(returned, corner_source):
    arrays = {name: value.copy() for name, value in returned.items()}
    mapping = {}
    original_owner = {}
    duplicates = []
    indices = returned["indices"].copy()
    for face, triangle in enumerate(returned["indices"]):
        for corner, old in enumerate(triangle):
            old, identity = int(old), int(corner_source[face, corner])
            pair = old, identity
            if pair not in mapping:
                if old not in original_owner:
                    original_owner[old] = identity
                    mapping[pair] = old
                else:
                    mapping[pair] = len(returned["POSITION"]) + len(duplicates)
                    duplicates.append(old)
            indices[face, corner] = mapping[pair]
    for name in returned:
        if name != "indices" and duplicates:
            arrays[name] = np.concatenate((returned[name], returned[name][duplicates]), axis=0)
    arrays["indices"] = indices
    if not all(np.array_equal(arrays[name][indices], returned[name][returned["indices"]]) for name in returned if name != "indices"):
        raise ValueError("Index-only restoration changed a surface-corner attribute")
    return arrays, {"duplicated_returned_vertex_indices": duplicates, "added_vertices": len(duplicates),
                    "all_corner_attributes_bit_identical_before_normalization": True}


def encode_glb(document, binary, arrays):
    document = json.loads(json.dumps(document))
    payload = bytearray(binary)
    primitive = document["meshes"][0]["primitives"][0]
    for name, values in arrays.items():
        while len(payload) % 4:
            payload.append(0)
        values = np.asarray(values, dtype="<u4" if name == "indices" else "<f4")
        flattened = values.reshape(-1, 1) if name == "indices" else values
        view = {"buffer": 0, "byteOffset": len(payload), "byteLength": flattened.nbytes}
        document["bufferViews"].append(view)
        payload.extend(flattened.tobytes())
        item = {"bufferView": len(document["bufferViews"]) - 1, "componentType": 5125 if name == "indices" else 5126,
                "count": len(flattened), "type": {1: "SCALAR", 2: "VEC2", 3: "VEC3"}[flattened.shape[1]]}
        if name == "POSITION":
            item.update({"min": values.min(axis=0).tolist(), "max": values.max(axis=0).tolist()})
        document["accessors"].append(item)
        if name == "indices":
            primitive["indices"] = len(document["accessors"]) - 1
        else:
            primitive["attributes"][name] = len(document["accessors"]) - 1
    document["buffers"][0]["byteLength"] = len(payload)
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    payload.extend(b"\x00" * (-len(payload) % 4))
    total = 12 + 8 + len(encoded) + 8 + len(payload)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + struct.pack("<II", len(payload), 0x004E4942) + payload


def material_nodes(obj):
    if len(obj.material_slots) != 1:
        raise ValueError("Actual imported material count differs")
    material = obj.material_slots[0].material
    principal = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    node = principal.inputs["Normal"].links[0].from_node
    if node.type != "NORMAL_MAP" or node.space != "TANGENT":
        raise ValueError("Unexpected actual PBR normal graph")
    image = node.inputs["Color"].links[0].from_node.image
    images = [{"name": node.image.name, "colorspace": node.image.colorspace_settings.name, "size": list(node.image.size)}
              for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
    if len(images) != 3 or image.colorspace_settings.name != "Non-Color":
        raise ValueError("Actual Blender PBR textures/colorspace differ")
    base_image = principal.inputs["Base Color"].links[0].from_node.image
    other_images = [node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image != base_image]
    if base_image.colorspace_settings.name != "sRGB" or any(item.colorspace_settings.name != "Non-Color" for item in other_images):
        raise ValueError("PBR channel color spaces are incorrect")
    graph = [{"from_node": link.from_node.name, "from_type": link.from_node.type, "from_socket": link.from_socket.name,
              "to_node": link.to_node.name, "to_socket": link.to_socket.name} for link in material.node_tree.links]
    return {"material": material.name, "images": images, "graph_links": graph, "normal_strength": float(node.inputs["Strength"].default_value),
            "normal_space": node.space, "no_material_override": True}, image, float(node.inputs["Strength"].default_value)


def mapped_normal_audit(mesh, image, strength):
    mesh.calc_tangents(uvmap=mesh.uv_layers.active.name)
    triangles = np.array([polygon.loop_indices[:] for polygon in mesh.polygons], dtype=int)
    if triangles.shape[1] != 3:
        raise ValueError("Expected actual triangular cloud mesh")
    normals = np.array([item.vector[:] for item in mesh.corner_normals])[triangles]
    tangents = np.array([loop.tangent[:] for loop in mesh.loops])[triangles]
    signs = np.array([loop.bitangent_sign for loop in mesh.loops])[triangles]
    coordinates = np.array([loop.uv[:] for loop in mesh.uv_layers.active.data])[triangles]
    positions = np.array([vertex.co[:] for vertex in mesh.vertices])
    points = positions[np.array([polygon.vertices[:] for polygon in mesh.polygons])]
    geometric = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    geometric /= np.linalg.norm(geometric, axis=1)[:, None]
    if np.any(signs != signs[:, :1]):
        raise ValueError("Mixed actual tangent handedness in a triangle")
    width, height = image.size
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    pixels = buffer.reshape(height, width, 4)[:, :, :3]
    summaries, adverse = [], []
    for label, weights in (("centroid", (1 / 3, 1 / 3, 1 / 3)), ("corner0", (.98, .01, .01)), ("corner1", (.01, .98, .01)), ("corner2", (.01, .01, .98))):
        normal = np.einsum("fcd,c->fd", normals, weights)
        normal /= np.linalg.norm(normal, axis=1)[:, None]
        tangent = np.einsum("fcd,c->fd", tangents, weights)
        tangent -= normal * np.einsum("ij,ij->i", tangent, normal)[:, None]
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        bitangent = np.cross(normal, tangent) * signs[:, :1]
        uv = np.einsum("fcd,c->fd", coordinates, weights)
        location = (uv % 1.0) * (width, height) - .5
        lower = np.floor(location).astype(int)
        fractions = location - lower
        sampled = np.zeros((len(triangles), 3))
        for offset_x in (0, 1):
            for offset_y in (0, 1):
                weight = (fractions[:, 0] if offset_x else 1 - fractions[:, 0]) * (fractions[:, 1] if offset_y else 1 - fractions[:, 1])
                sampled += pixels[(lower[:, 1] + offset_y) % height, (lower[:, 0] + offset_x) % width] * weight[:, None]
        tangent_normal = sampled * 2 - 1
        tangent_normal[:, :2] *= strength
        tangent_normal /= np.linalg.norm(tangent_normal, axis=1)[:, None]
        mapped = tangent * tangent_normal[:, :1] + bitangent * tangent_normal[:, 1:2] + normal * tangent_normal[:, 2:3]
        mapped /= np.linalg.norm(mapped, axis=1)[:, None]
        dots = np.einsum("ij,ij->i", mapped, geometric)
        if not np.isfinite(dots).all():
            raise ValueError("Nonfinite actual tangent/normal-map diagnostic")
        summaries.append({"sample": label, "count": len(dots), "minimum_mapped_dot_geometric": float(dots.min()), "negative_count": int(np.count_nonzero(dots < 0))})
        adverse.extend({"sample": label, "face": int(index), "mapped_dot_geometric": float(dots[index]), "uv": uv[index].tolist()} for index in np.flatnonzero(dots < 0))
    return {"method": "Actual Blender Mikk corner tangents; level0 repeat bilinear map, centroid plus98percent near each corner. Not a GPU mip/shader identity proof or automatic quality approval.",
            "summaries": summaries, "negative_samples": adverse, "tested_samples": len(triangles) * 4}


def prepare_render(output, analysis_path, allow_split_restore):
    import bpy

    frozen = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    report, source, returned, corners = audit(include_images=False)
    if frozen["source_files"] != report["source_files"] or frozen["script"] != report["script"]:
        raise ValueError("Frozen analysis inputs/script changed")
    for current, saved in zip(report["images"], frozen["images"]):
        if any(saved[key] != value for key, value in current.items()):
            raise ValueError("Immutable texture payloads changed")
    report["images"] = frozen["images"]
    if not report["comparison"]["surface_and_uv_passed"]:
        raise ValueError("Full surface/UV gate failed")
    if not report["split_identity"]["all_native_identities_preserved"] and not allow_split_restore:
        raise ValueError("Cloud split identity failed; explicit authorized local restoration required")
    arrays, restoration = restore_split_arrays(returned, corners)
    if restoration["added_vertices"] != 2:
        raise ValueError("Restoration must only separate the two proven cloud welds")
    comparison = report["comparison"]
    arrays["POSITION"] = (arrays["POSITION"].astype(float) * comparison["restore_uniform_scale"] + comparison["restore_gltf_y_up_translation_m"]).astype(np.float32)
    document, binary, _ = core.read_glb(RETURNED)
    output.mkdir(parents=True, exist_ok=False)
    model = output / "Mount_Mammoth_PBR.glb"
    model.write_bytes(encode_glb(document, binary, arrays))
    normalized_document, normalized_binary, normalized = core.read_glb(model)
    normalized_comparison, _, source_mapping, _ = triangle_mapping(source, normalized, restore=False)
    native, pairs, _ = native_identity(source)
    normalized_split = split_identity(native, pairs, source_mapping)
    if not normalized_comparison["surface_and_uv_passed"] or not normalized_comparison["render_vertex_bijection_preserved"] or not normalized_split["all_native_identities_preserved"]:
        raise ValueError("Restored model does not preserve full source split identity")
    if image_audit(normalized_document, normalized_binary, decode=False) != image_audit(document, binary, decode=False) or normalized_document["materials"] != document["materials"]:
        raise ValueError("Local normalization changed texture bytes or materials")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(model), merge_vertices=False)
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Unexpected actual mesh count")
    obj = objects[0]
    actual_positions = np.array([vertex.co[:] for vertex in obj.data.vertices])[:, (0, 2, 1)] * (1, 1, -1)
    if len(actual_positions) != len(normalized["POSITION"]) or np.max(np.linalg.norm(actual_positions - normalized["POSITION"], axis=1)) > 1e-6:
        raise ValueError("Actual Blender positions/index identities differ")
    if not np.array_equal(np.array([polygon.vertices[:] for polygon in obj.data.polygons]), normalized["indices"]):
        raise ValueError("Actual Blender triangle index order differs")
    material, normal_image, strength = material_nodes(obj)
    report["actual_normal_map_diagnostic"] = mapped_normal_audit(obj.data, normal_image, strength)
    spec = importlib.util.spec_from_file_location("mammoth_texture_prep", ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)
    minimum, maximum = prep.bounds(objects)
    if abs(minimum.z) > 1e-6 or abs(maximum.z - 1.8) > 1e-6:
        raise ValueError("Actual180cm/bottomZ0 gate failed")
    report.update({"status": "prepared_pending_actual_views", "blender_started": True, "local_index_restore": restoration,
                   "normalized_comparison": normalized_comparison, "normalized_split_identity": normalized_split,
                   "material_nodes": material, "actual_bounds_m": {"min": list(minimum), "max": list(maximum)},
                   "model": core.record(model), "mesh_statistics": prep.mesh_stats(objects), "analysis": core.record(analysis_path)})
    core.save(output / "pbr_report.json", report)
    prep.select(objects)
    roundtrip_path = output / "blender_roundtrip.glb"
    bpy.ops.export_scene.gltf(filepath=str(roundtrip_path), export_format="GLB", use_selection=True, export_yup=True,
                              export_animations=False, export_skins=False, export_morph=False, export_materials="EXPORT")
    roundtrip = core.read_glb(roundtrip_path)[2]
    roundtrip_comparison, _, roundtrip_map, _ = triangle_mapping(normalized, roundtrip, restore=False)
    report["roundtrip"] = {"file": core.record(roundtrip_path), "comparison": roundtrip_comparison,
                           "scope": "Full triangle corner/UV/normal and index identity comparison; diagnostic export is not the texture-byte-preserving deliverable."}
    if not roundtrip_comparison["surface_and_uv_passed"] or not roundtrip_comparison["render_vertex_bijection_preserved"] or roundtrip_comparison["maximum_normal_vector_change"] > 1e-4:
        core.save(output / "pbr_report.json", report)
        raise ValueError("Actual Blender roundtrip geometry/UV/index/normal gate failed")
    bpy.context.scene.world = bpy.data.worlds.new("MammothPBRReviewWorld")
    prep.render_setup(samples=8)
    bpy.context.scene.cycles.seed = 0
    views = [(name, direction, None, None) for name, direction in (("front", (1, 0, 0)), ("right", (0, -1, 0)), ("back", (-1, 0, 0)), ("left", (0, 1, 0)), ("preview", (1, -1, .45)))]
    cleanup = json.loads(CLEANUP.read_text(encoding="utf-8-sig"))
    for region in cleanup["regions"]:
        views.append(("buckle_" + str(region["patch_root"]), (.25, 1 if region["target"][1] > 0 else -1, .15), region["target"], region["framing"]))
    images = []
    for name, direction, target, framing in views:
        path = output / (name + ".png")
        prep.render_view(path, objects, direction, size=512, target=target, framing=framing)
        images.append(core.record(path))
        report["images_rendered"] = images
        core.save(output / "pbr_report.json", report)
    blend = output / "Mount_Mammoth_PBR.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report.update({"status": "nine_actual_pbr_views_pending_root_review", "blend": core.record(blend)})
    for item in report["source_files"]:
        checked_record(item)
    core.save(output / "pbr_report.json", report)
    print(json.dumps({"status": report["status"], "images": len(images), "model_sha256": report["model"]["sha256"]}))


def diagnostic_inputs():
    if core.record(DIAGNOSTIC_MODEL)["sha256"] != DIAGNOSTIC_MODEL_SHA or core.record(FAILED_REPORT)["sha256"] != FAILED_REPORT_SHA:
        raise ValueError("Frozen candidate or failed-roundtrip evidence changed")
    frozen = json.loads(FAILED_REPORT.read_text(encoding="utf-8-sig"))
    for item in frozen["source_files"]:
        checked_record(item)
    document, binary, candidate = core.read_glb(DIAGNOSTIC_MODEL)
    cloud_document, cloud_binary, _ = core.read_glb(RETURNED)
    if image_audit(document, binary, False) != image_audit(cloud_document, cloud_binary, False):
        raise ValueError("Candidate changed original PBR image bytes")
    source = core.read_glb(SOURCE)[2]
    comparison, corners, mapping, _ = triangle_mapping(source, candidate, restore=False)
    native, pairs, analysis = native_identity(source)
    splits = split_identity(native, pairs, mapping)
    if not comparison["surface_and_uv_passed"] or not comparison["render_vertex_bijection_preserved"] or not splits["all_native_identities_preserved"]:
        raise ValueError("Frozen candidate full surface/native identity gate failed")
    return frozen, source, candidate, corners, analysis, comparison, splits


def localize_negative_samples(output):
    frozen, source, candidate, corners, analysis, comparison, splits = diagnostic_inputs()
    source_faces = {tuple(sorted(int(index) for index in triangle)): face for face, triangle in enumerate(source["indices"])}
    patch_by_polygon = {face: patch["patch_root"] for patch in analysis["plan"]["accessory_patches"] for face in patch["face_indices"]}
    samples_by_face = defaultdict(list)
    for sample in frozen["actual_normal_map_diagnostic"]["negative_samples"]:
        samples_by_face[sample["face"]].append(sample)
    rows = []
    totals = defaultdict(lambda: {"triangles": 0, "samples": 0})
    for face, samples in sorted(samples_by_face.items()):
        source_face = source_faces[tuple(sorted(int(index) for index in corners[face]))]
        polygon = analysis["source_triangle_native_polygons"][source_face]
        patch = patch_by_polygon.get(polygon)
        positions = candidate["POSITION"][candidate["indices"][face]].astype(float)[:, (0, 2, 1)] * (1, -1, 1)
        center = positions.mean(axis=0)
        label = "approved_saddle_buckle_patch_" + str(patch) if patch is not None else "other_native_surface_not_semantically_assigned"
        totals[label]["triangles"] += 1
        totals[label]["samples"] += len(samples)
        rows.append({"candidate_triangle": face, "source_cleanup_glb_triangle": source_face, "source_native_polygon": polygon,
                     "source_native_polygon_vertices": analysis["native_polygons"][polygon], "region": label,
                     "vertices_blender_m": positions.tolist(), "center_blender_m": center.tolist(),
                     "uv_gltf": candidate["TEXCOORD_0"][candidate["indices"][face]].tolist(), "samples": samples})
    result = {"asset_id": "Mount_Mammoth", "status": "all914_actual_negative_samples_assigned_to_exact_source_triangles",
              "candidate": core.record(DIAGNOSTIC_MODEL), "failed_report": core.record(FAILED_REPORT), "script": core.record(Path(__file__)),
              "negative_samples": sum(len(values) for values in samples_by_face.values()), "affected_triangles": len(rows),
              "regions": dict(totals), "rows": rows,
              "interpretation": "Buckle identities come from root-reviewed four native patches. Other surfaces include fur/body and possibly anatomy/accessories; coordinates and exact source polygons are provided, but no unsupported fur-only semantic claim is made. Four actual body views plus four buckle closeups are needed to judge visible damage.",
              "pbr_visual_approved": False, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    core.save(output / "negative_sample_regions.json", result)
    print(json.dumps({"status": result["status"], "regions": result["regions"]}))


def render_diagnostic(output):
    import bpy

    frozen, _, candidate, _, _, comparison, splits = diagnostic_inputs()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(DIAGNOSTIC_MODEL), merge_vertices=False)
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Unexpected actual diagnostic mesh count")
    obj = objects[0]
    actual_positions = np.array([vertex.co[:] for vertex in obj.data.vertices])[:, (0, 2, 1)] * (1, 1, -1)
    if len(actual_positions) != len(candidate["POSITION"]) or np.max(np.linalg.norm(actual_positions - candidate["POSITION"], axis=1)) > 1e-6:
        raise ValueError("Actual diagnostic import changed positions/indices")
    if not np.array_equal(np.array([polygon.vertices[:] for polygon in obj.data.polygons]), candidate["indices"]):
        raise ValueError("Actual diagnostic triangle order differs")
    actual_normals = np.array([corner.vector[:] for corner in obj.data.corner_normals])[:, (0, 2, 1)] * (1, 1, -1)
    wanted = candidate["NORMAL"][candidate["indices"].reshape(-1)].astype(float)
    normal_errors = np.linalg.norm(actual_normals - wanted, axis=1)
    material, normal_image, strength = material_nodes(obj)
    mapped = mapped_normal_audit(obj.data, normal_image, strength)
    spec = importlib.util.spec_from_file_location("mammoth_pbr_diagnostic_prep", ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)
    minimum, maximum = prep.bounds(objects)
    if abs(minimum.z) > 1e-6 or abs(maximum.z - 1.8) > 1e-6:
        raise ValueError("Actual diagnostic180cm/bottomZ0 gate failed")
    output.mkdir(parents=True, exist_ok=False)
    report = {"asset_id": "Mount_Mammoth", "status": "actual_diagnostic_render_in_progress_no_roundtrip_approval",
              "model": core.record(DIAGNOSTIC_MODEL), "failed_roundtrip_report": core.record(FAILED_REPORT),
              "script": core.record(Path(__file__)), "comparison": comparison, "split_identity": splits,
              "material_nodes": material, "normal_map_diagnostic": mapped,
              "actual_blender_import_maximum_normal_vector_difference": float(normal_errors.max()),
              "actual_blender_import_corners_above_1e4_normal_difference": int(np.count_nonzero(normal_errors > 1e-4)),
              "actual_bounds_m": {"min": list(minimum), "max": list(maximum)},
              "scope": "Direct read-only import of frozen byte-preserving candidate. Blender custom-normal decoding differences are recorded, not concealed or approved. No mesh export, no source/candidate modification, no failed-roundtrip gate relaxation.",
              "pbr_visual_approved": False, "roundtrip_approved": False, "rig_approved": False, "production_approved": False}
    core.save(output / "diagnostic_render_report.json", report)
    bpy.context.scene.world = bpy.data.worlds.new("MammothFrozenPBRDiagnosticWorld")
    prep.render_setup(samples=8)
    bpy.context.scene.cycles.seed = 0
    views = [(name, direction, None, None) for name, direction in (("front", (1, 0, 0)), ("right", (0, -1, 0)), ("back", (-1, 0, 0)), ("left", (0, 1, 0)), ("preview", (1, -1, .45)))]
    for region in json.loads(CLEANUP.read_text(encoding="utf-8-sig"))["regions"]:
        views.append(("buckle_" + str(region["patch_root"]), (.25, 1 if region["target"][1] > 0 else -1, .15), region["target"], region["framing"]))
    images = []
    for name, direction, target, framing in views:
        path = output / (name + ".png")
        prep.render_view(path, objects, direction, size=512, target=target, framing=framing)
        images.append(core.record(path))
        report["images_rendered"] = images
        core.save(output / "diagnostic_render_report.json", report)
    diagnostic_inputs()
    report.update({"status": "nine_actual_frozen_candidate_diagnostic_views_pending_root_review",
                   "candidate_and_all_frozen_sources_unchanged": True, "model_exports_performed": 0})
    core.save(output / "diagnostic_render_report.json", report)
    print(json.dumps({"status": report["status"], "images": len(images), "candidate_sha256": DIAGNOSTIC_MODEL_SHA}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("analyze", "prepare-render", "localize", "render-diagnostic"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--allow-index-split-restoration", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = fresh_output(args.output)
    if args.mode == "analyze":
        report, _, _, _ = audit()
        output.mkdir(parents=True, exist_ok=False)
        core.save(output / "texture_audit.json", report)
        print(json.dumps({"status": report["status"], "split_pairs_retained": report["split_identity"]["retained_split_pairs"], "triangles": report["comparison"]["triangles"]}))
    elif args.mode == "localize":
        localize_negative_samples(output)
    elif args.mode == "render-diagnostic":
        render_diagnostic(output)
    elif args.analysis:
        prepare_render(output, args.analysis.resolve(), args.allow_index_split_restoration)
    else:
        raise ValueError("Preparation needs an immutable actual analysis")


if __name__ == "__main__":
    main()
