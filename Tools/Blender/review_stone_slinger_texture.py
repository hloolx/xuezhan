"""Audit the returned Tripo texture GLB before restoring its proven physical frame."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from itertools import product
import json
from pathlib import Path
import struct
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
BRANCH = ART / "tripo_processed/stone_slinger_v01"
SOURCE = BRANCH / "cleanup_v01/candidate_04/Unit_StoneSlinger_cleanup.glb"
SOURCE_SHA = "4886561f2bf3376025e9ad868ab91d956b2ed189a8891497b29b46514f066013"
RETURNED = ART / "tripo_raw/Unit_StoneSlinger/textured_v01_cleanup04/model.glb"
TASK = RETURNED.with_name("task.json")
TASK_ID = "47a36697-567e-47d8-8760-904c627c9e2e"


def record(path):
    return {"path": path.resolve().as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_glb(path):
    data = path.read_bytes()
    if struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("Invalid GLB header")
    json_size, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise ValueError("Missing GLB JSON chunk")
    document = json.loads(data[20:20 + json_size])
    binary_size, binary_type = struct.unpack_from("<II", data, 20 + json_size)
    if binary_type != 0x004E4942:
        raise ValueError("Missing embedded GLB binary chunk")
    binary = data[28 + json_size:28 + json_size + binary_size]
    if len(document["nodes"]) != 1 or any(key in document["nodes"][0] for key in ("matrix", "rotation", "translation", "scale", "children", "skin")):
        raise ValueError("Nonidentity node hierarchy needs an explicit transform audit")
    if len(document["meshes"]) != 1 or len(document["meshes"][0]["primitives"]) != 1:
        raise ValueError("Unexpected primitive splitting")
    primitive = document["meshes"][0]["primitives"][0]
    if primitive.get("mode", 4) != 4:
        raise ValueError("Expected indexed triangles")

    def accessor(index):
        item = document["accessors"][index]
        if "sparse" in item or item.get("normalized"):
            raise ValueError("Sparse or normalized accessor needs separate audit")
        view = document["bufferViews"][item["bufferView"]]
        dtype = np.dtype({5126: "<f4", 5123: "<u2", 5125: "<u4"}[item["componentType"]])
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[item["type"]]
        stride = view.get("byteStride", dtype.itemsize * width)
        offset = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        return np.ndarray((item["count"], width), dtype, buffer=binary, offset=offset,
                          strides=(stride, dtype.itemsize)).copy()

    arrays = {name: accessor(index) for name, index in primitive["attributes"].items()}
    arrays["indices"] = accessor(primitive["indices"]).reshape(-1, 3)
    if any(not np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("Nonfinite GLB data")
    return document, binary, arrays


def position_correspondence(original, restored):
    unique = {tuple(point): index for index, point in enumerate(original)}
    buckets = defaultdict(list)
    cell_size = 1e-5
    for point, index in unique.items():
        buckets[tuple(np.floor(np.array(point) / cell_size).astype(int))].append(index)
    source_ids = np.array([unique[tuple(point)] for point in original])
    restored_ids = []
    for point in restored:
        cell = np.floor(point / cell_size).astype(int)
        candidates = [index for offset in product((-1, 0, 1), repeat=3)
                      for index in buckets.get(tuple(cell + offset), ())]
        if not candidates:
            raise ValueError("Returned point has no source position within10micrometers")
        distances = np.linalg.norm(original[candidates] - point, axis=1)
        chosen = int(np.argmin(distances))
        if distances[chosen] >= 1e-6:
            raise ValueError("Returned point differs from source by at least1micrometer")
        restored_ids.append(candidates[chosen])
    return source_ids, np.array(restored_ids)


def corner_groups(arrays, positions, position_ids):
    result = defaultdict(list)
    for face, triangle in enumerate(arrays["indices"]):
        ordered = sorted(range(3), key=lambda corner: position_ids[triangle[corner]])
        vertices = triangle[ordered]
        key = tuple(int(position_ids[index]) for index in vertices)
        result[key].append({"face": face, "indices": vertices, "winding": tuple(ordered),
                            "position": positions[vertices], "uv": arrays["TEXCOORD_0"][vertices],
                            "normal": arrays["NORMAL"][vertices]})
    return result


def compare(source, returned):
    original = source["POSITION"].astype(float)
    cloud = returned["POSITION"].astype(float)
    scale = float(np.ptp(original[:, 1]) / np.ptp(cloud[:, 1]))
    translation = original.min(axis=0) - cloud.min(axis=0) * scale
    restored = cloud * scale + translation
    source_ids, restored_ids = position_correspondence(original, restored)
    before = corner_groups(source, original, source_ids)
    after = corner_groups(returned, restored, restored_ids)
    if Counter({key: len(value) for key, value in before.items()}) != Counter({key: len(value) for key, value in after.items()}):
        raise ValueError("Texture output changed the geometry triangle multiset")
    ambiguous = [key for key, values in before.items() if len(values) != 1]
    if ambiguous:
        raise ValueError("Coincident duplicate triangles need explicit pairing")
    errors = {"position_m": 0.0, "uv": 0.0, "normal_vector": 0.0}
    normal_changes = []
    vertex_map = defaultdict(set)
    winding_reversals = 0
    for key in before:
        expected, actual = before[key][0], after[key][0]
        for field, label in (("position", "position_m"), ("uv", "uv"), ("normal", "normal_vector")):
            errors[label] = max(errors[label], float(np.linalg.norm(expected[field] - actual[field], axis=1).max()))
        expected_cycle = expected["winding"]
        actual_cycle = actual["winding"]
        if not any(actual_cycle == expected_cycle[offset:] + expected_cycle[:offset] for offset in range(3)):
            winding_reversals += 1
        for source_index, returned_index in zip(expected["indices"], actual["indices"]):
            vertex_map[int(source_index)].add(int(returned_index))
        normal_distances = np.linalg.norm(expected["normal"] - actual["normal"], axis=1)
        for corner in np.flatnonzero(normal_distances > 1e-5):
            normal_changes.append({"source_face": expected["face"], "returned_face": actual["face"],
                                   "source_vertex": int(expected["indices"][corner]), "returned_vertex": int(actual["indices"][corner]),
                                   "position_gltf_y_up_m": expected["position"][corner].tolist(),
                                   "source_normal": expected["normal"][corner].tolist(), "returned_normal": actual["normal"][corner].tolist(),
                                   "normal_vector_error": float(normal_distances[corner])})
    bijective = all(len(values) == 1 for values in vertex_map.values())
    bijective = bijective and len({next(iter(values)) for values in vertex_map.values()}) == len(vertex_map)
    geometry_passed = errors["position_m"] < 1e-6 and bijective and winding_reversals == 0
    passed = geometry_passed and errors["uv"] < 1e-6 and errors["normal_vector"] < 1e-5
    return {"passed": passed, "triangles": len(source["indices"]), "source_render_vertices": len(original),
            "returned_render_vertices": len(cloud), "cloud_gltf_y_up_bounds_m": {"min": cloud.min(axis=0).tolist(), "max": cloud.max(axis=0).tolist()},
            "restore_uniform_scale": scale, "restore_gltf_y_up_translation_m": translation.tolist(),
            "restore_blender_z_up_translation_m": [float(translation[0]), float(-translation[2]), float(translation[1])],
            "triangle_multiset_identical_after_restoration": True, "maximum_corner_errors": errors,
            "index_connectivity_bijection_preserved": bijective, "corresponding_vertices": len(vertex_map),
            "winding_reversals": winding_reversals,
            "geometry_and_index_connectivity_passed": geometry_passed,
            "uv_preserved": errors["uv"] == 0.0,
            "custom_normals_preserved": errors["normal_vector"] < 1e-5,
            "normal_change_diagnostic": {"affected_triangle_corners": len(normal_changes),
                                         "affected_render_vertices": len({row["source_vertex"] for row in normal_changes}),
                                         "error_threshold_counts": {str(threshold): sum(row["normal_vector_error"] > threshold for row in normal_changes) for threshold in (1e-5, .001, .01, .1, .5, 1)},
                                         "large_changes": [row for row in normal_changes if row["normal_vector_error"] > .01]},
            "scope": "Full triangle-corner correspondence and bijective vertex incidence, not position welding. Detects rollback of the cleaned split topology even where coincident surface positions exist."}


def audit(include_images=True):
    if record(SOURCE)["sha256"] != SOURCE_SHA:
        raise ValueError("Approved cleanup04 GLB changed")
    receipt = json.loads(TASK.read_text(encoding="utf-8-sig"))
    if receipt["task_id"] != TASK_ID or receipt["status"] != "success" or receipt["type"] != "texture_model":
        raise ValueError("Unexpected texture task receipt")
    source_document, source_binary, source = read_glb(SOURCE)
    document, binary, returned = read_glb(RETURNED)
    comparison = compare(source, returned)
    images = []
    for item in document["images"] if include_images else []:
        from PIL import Image
        view = document["bufferViews"][item["bufferView"]]
        payload = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            images.append({"name": item["name"], "mime_type": item["mimeType"], "size": list(image.size),
                           "mode": image.mode, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {"asset_id": "Unit_StoneSlinger", "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "data_passed_pending_actual_pbr_views" if comparison["passed"] else "data_gate_failed",
            "source": record(SOURCE), "returned": record(RETURNED), "task": record(TASK), "script": record(Path(__file__)),
            "task_id": TASK_ID, "actual_credits_consumed": receipt["credits_consumed"], "comparison": comparison,
            "materials": document["materials"], "textures": document["textures"], "images": images,
            "source_node": source_document["nodes"], "returned_node": document["nodes"],
            "cloud_change": "Reordered vertices and triangles, normalized total height to1m and centered atY0 in glTF. Restore only the numerically proven uniform scale and translation; do not reuse raw geometry or re-unwrap.",
            "blender_started": False, "pbr_visual_approved": False, "rig_approved": False, "production_approved": False}


def render(output, analysis_path):
    import bpy
    from mathutils import Vector

    frozen = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    actual = audit(include_images=False)
    for key in ("source", "returned", "task"):
        if frozen[key] != actual[key]:
            raise ValueError("Frozen texture analysis inputs changed")
    if not actual["comparison"]["geometry_and_index_connectivity_passed"]:
        raise ValueError("Geometry/connectivity gate prevents even diagnostic PBR preparation")
    actual["images"] = frozen["images"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(RETURNED))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Unexpected Blender import mesh count")
    comparison = actual["comparison"]
    obj = objects[0]
    for vertex in obj.data.vertices:
        vertex.co = vertex.co * comparison["restore_uniform_scale"] + Vector(comparison["restore_blender_z_up_translation_m"])
    obj.data.update()
    module_spec = importlib.util.spec_from_file_location("slinger_texture_prep", ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(prep)
    minimum, maximum = prep.bounds(objects)
    if abs(minimum.z) > 1e-6 or abs(maximum.z - 1.425) > 1e-6:
        raise ValueError("Actual restored Blender height/ground gate failed")
    output.mkdir(parents=True, exist_ok=False)
    bpy.context.scene.world = bpy.data.worlds.new("StoneSlingerReviewWorld")
    prep.render_setup(samples=8)
    images = []
    for name, direction in (("front", (1, 0, 0)), ("right", (0, -1, 0)), ("back", (-1, 0, 0)), ("left", (0, 1, 0)), ("preview", (1, -1, .45))):
        path = output / (name + ".png")
        prep.render_view(path, objects, direction, size=512)
        images.append(record(path))
    for name, direction in (("neck_front", (.8, 1, .15)), ("neck_back", (-.8, 1, .1))):
        path = output / (name + ".png")
        prep.render_view(path, objects, direction, size=512, target=(.005, .085, 1.188), framing=.24)
        images.append(record(path))
    prep.select(objects)
    model = output / "Unit_StoneSlinger_textured.glb"
    bpy.ops.export_scene.gltf(filepath=str(model), export_format="GLB", use_selection=True, export_yup=True,
                              export_animations=False, export_skins=False, export_morph=False, export_materials="EXPORT")
    roundtrip = prep.verify_glb(model, objects)
    blend = output / "Unit_StoneSlinger_textured.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    actual.update({"status": "pbr_seven_diagnostic_views_pending_normal_basis_and_visual_review", "blender_started": True,
                   "analysis": record(analysis_path), "images_rendered": images, "model": record(model), "blend": record(blend),
                   "actual_blender_bounds_m": {"min": list(minimum), "max": list(maximum)},
                   "roundtrip": roundtrip, "mesh_statistics": prep.mesh_stats(objects)})
    save(output / "pbr_report.json", actual)
    print(json.dumps({"status": actual["status"], "images": len(images), "roundtrip": roundtrip}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("analyze", "render"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a fresh directory")
    if args.mode == "analyze":
        report = audit()
        output.mkdir(parents=True, exist_ok=False)
        save(output / "texture_audit.json", report)
        print(json.dumps({"status": report["status"], "comparison": report["comparison"]}))
    elif args.analysis:
        render(output, args.analysis.resolve())
    else:
        raise ValueError("Rendering requires the frozen analysis")


if __name__ == "__main__":
    main()
