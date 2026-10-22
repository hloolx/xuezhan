"""Read the actual Tripo rig, preserving its received geometry and materials."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
from itertools import permutations, product
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
BRANCH = ART / "tripo_processed/stone_slinger_v01"
SOURCE = BRANCH / "textured_v01/normal_repair_candidate_01/Unit_StoneSlinger_PBR_LocalNormalRepair.glb"
RETURNED = ART / "tripo_raw/Unit_StoneSlinger/rigged_v01_repaired/model.fbx"
SOURCE_SHA = "39287590ac1d71c2cbc0cccdf0706b2b335d77969b6f0c802dfe7a2ee451ba11"
RETURNED_SHA = "4fd84a658e35d6a4ac12c26cd788e4fe39d8955ad7d8702f51d8860966549a4b"
TASK_ID = "1c7d836b-d6fa-4fbe-a755-235de973b7dc"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def record(path):
    return {"path": path.resolve().as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def proper_axis_rotations():
    result = []
    for axes in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            rotation = np.zeros((3, 3))
            for axis, original in enumerate(axes):
                rotation[axis, original] = signs[axis]
            if np.linalg.det(rotation) > .5:
                result.append(rotation)
    return result


def fit_axis_candidates(source, returned):
    source_extent = np.ptp(source, axis=0)
    candidates = []
    for rotation in proper_axis_rotations():
        rotated = returned @ rotation.T
        extent = np.ptp(rotated, axis=0)
        if np.min(extent) <= 0:
            continue
        scale = float(np.dot(extent, source_extent) / np.dot(extent, extent))
        translation = (source.min(axis=0) + source.max(axis=0)
                       - scale * (rotated.min(axis=0) + rotated.max(axis=0))) / 2
        extent_error = float(np.max(np.abs(extent * scale - source_extent)))
        candidates.append({"rotation": rotation.tolist(), "uniform_scale": scale,
                           "translation_m": translation.tolist(), "extent_error_m": extent_error})
    return sorted(candidates, key=lambda candidate: candidate["extent_error_m"])


def mesh_snapshot(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    positions = np.array([list(obj.matrix_world @ vertex.co) for vertex in mesh.vertices], dtype=float)
    normals = np.array([list((normal_matrix @ corner.vector).normalized()) for corner in mesh.corner_normals])
    uv = np.array([list(loop.uv) for loop in mesh.uv_layers.active.data]) if mesh.uv_layers.active else None
    return {"positions": positions, "normals": normals, "uv": uv,
            "triangles": np.array([list(triangle.vertices) for triangle in mesh.loop_triangles]),
            "triangle_loops": np.array([list(triangle.loops) for triangle in mesh.loop_triangles])}


def triangle_correspondence(source, returned, fit):
    audit = module("slinger_rig_texture_audit", "review_stone_slinger_texture.py")
    rotation = np.array(fit["rotation"])
    restored = returned["positions"] @ rotation.T * fit["uniform_scale"] + fit["translation_m"]
    source_ids, returned_ids = audit.position_correspondence(source["positions"], restored)

    def grouped(snapshot, ids):
        groups = defaultdict(list)
        for index, triangle in enumerate(snapshot["triangles"]):
            order = sorted(range(3), key=lambda corner: ids[triangle[corner]])
            vertices = triangle[order]
            loops = snapshot["triangle_loops"][index][order]
            key = tuple(int(ids[vertex]) for vertex in vertices)
            groups[key].append((index, vertices, loops, tuple(order)))
        return groups

    before, after = grouped(source, source_ids), grouped(returned, returned_ids)
    if Counter({key: len(rows) for key, rows in before.items()}) != Counter({key: len(rows) for key, rows in after.items()}):
        raise ValueError("Rig changed the complete geometric triangle multiset")
    if any(len(rows) != 1 for rows in before.values()):
        raise ValueError("Coincident triangles require explicit nonambiguous correspondence")
    mapping = defaultdict(set)
    reverse_mapping = defaultdict(set)
    maximum = {"position_m": 0.0, "uv": 0.0, "normal_vector": 0.0}
    normal_changes = []
    reversed_faces = []
    for key, values in before.items():
        source_face, source_vertices, source_loops, source_order = values[0]
        returned_face, returned_vertices, returned_loops, returned_order = after[key][0]
        if not any(returned_order == source_order[offset:] + source_order[:offset] for offset in range(3)):
            reversed_faces.append(returned_face)
        position_error = np.linalg.norm(source["positions"][source_vertices] - restored[returned_vertices], axis=1)
        normal_error = np.linalg.norm(source["normals"][source_loops] - returned["normals"][returned_loops] @ rotation.T, axis=1)
        uv_error = np.linalg.norm(source["uv"][source_loops] - returned["uv"][returned_loops], axis=1)
        for label, errors in (("position_m", position_error), ("uv", uv_error), ("normal_vector", normal_error)):
            maximum[label] = max(maximum[label], float(errors.max()))
        for corner, (source_vertex, returned_vertex) in enumerate(zip(source_vertices, returned_vertices)):
            mapping[int(source_vertex)].add(int(returned_vertex))
            reverse_mapping[int(returned_vertex)].add(int(source_vertex))
            if normal_error[corner] > 1e-4:
                normal_changes.append({"source_triangle": source_face, "returned_triangle": returned_face,
                                       "source_vertex": int(source_vertex), "returned_vertex": int(returned_vertex),
                                       "vector_error": float(normal_error[corner])})
    bijection = all(len(values) == 1 for values in mapping.values()) and all(len(values) == 1 for values in reverse_mapping.values())
    return {"full_triangle_correspondence": True, "triangles": len(before), "maximum_errors": maximum,
            "source_vertices": len(source["positions"]), "returned_vertices": len(returned["positions"]),
            "source_vertex_splits": {str(index): sorted(values) for index, values in mapping.items() if len(values) > 1},
            "returned_vertex_merges": {str(index): sorted(values) for index, values in reverse_mapping.items() if len(values) > 1},
            "vertex_incidence_bijection": bijection, "winding_reversals": reversed_faces,
            "normal_changes_above_1e_minus4": normal_changes,
            "geometry_uv_and_normals_preserved": maximum["position_m"] < 1e-6 and maximum["uv"] < 1e-6
                and maximum["normal_vector"] < 1e-4 and not reversed_faces,
            "scope": "Complete triangle/corner comparison, without changing or welding any source or returned vertex."}


def image_report(image):
    packed = image.packed_file
    payload = bytes(packed.data) if packed else None
    if payload is None:
        path = Path(image.filepath)
        payload = path.read_bytes() if path.is_file() else None
    return {"name": image.name, "filepath": image.filepath, "size": list(image.size),
            "channels": image.channels, "colorspace": image.colorspace_settings.name,
            "has_data": image.has_data, "packed": bool(packed),
            "bytes": len(payload) if payload else None,
            "sha256": hashlib.sha256(payload).hexdigest() if payload else None}


def materials_report(meshes):
    result = []
    materials = {material for obj in meshes for material in obj.data.materials if material}
    for material in sorted(materials, key=lambda item: item.name):
        nodes = []
        links = []
        for node in material.node_tree.nodes if material.node_tree else []:
            entry = {"name": node.name, "type": node.type}
            if node.type == "TEX_IMAGE" and node.image:
                entry["image"] = image_report(node.image)
                entry["uv_map_input_linked"] = node.inputs["Vector"].is_linked
            if node.type == "BSDF_PRINCIPLED":
                entry["inputs"] = {name: {"linked": node.inputs[name].is_linked,
                                          "default": list(node.inputs[name].default_value) if name == "Base Color" else node.inputs[name].default_value}
                                   for name in ("Base Color", "Roughness", "Metallic")}
                entry["normal_linked"] = node.inputs["Normal"].is_linked
            nodes.append(entry)
        for link in material.node_tree.links if material.node_tree else []:
            links.append({"from": [link.from_node.name, link.from_socket.name], "to": [link.to_node.name, link.to_socket.name]})
        result.append({"name": material.name, "use_nodes": material.use_nodes, "nodes": nodes, "links": links})
    return result


def texture_presence(source_materials, returned_materials):
    expected = {node["image"]["sha256"]: node["image"] for material in source_materials
                for node in material["nodes"] if node.get("image", {}).get("sha256")}
    received = {node["image"]["sha256"]: node["image"] for material in returned_materials
                for node in material["nodes"] if node.get("image", {}).get("sha256")}
    return {"source_unique_images": len(expected), "returned_unique_images": len(received),
            "exact_payload_matches": [{"source": value, "returned": received[checksum]}
                                      for checksum, value in expected.items() if checksum in received],
            "source_payloads_not_found_in_received_materials": [value for checksum, value in expected.items() if checksum not in received],
            "all_three_source_payloads_found": len(expected) == 3 and all(checksum in received for checksum in expected),
            "scope": "Content hashes and actual node links only. Different encoding is not proof of different pixels; missing exact payloads need separate diagnosis before PBR approval."}


def skeleton_report(armatures, meshes, fit):
    result = []
    rotation = np.array(fit["rotation"]) if fit else np.eye(3)
    factor = fit["uniform_scale"] if fit else 1.0
    translation = np.array(fit["translation_m"]) if fit else np.zeros(3)
    for armature in armatures:
        rows = []
        for bone in armature.data.bones:
            head = np.array(armature.matrix_world @ bone.head_local)
            tail = np.array(armature.matrix_world @ bone.tail_local)
            rows.append({"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                         "deform": bone.use_deform, "head_world_received_m": head.tolist(), "tail_world_received_m": tail.tolist(),
                         "head_world_review_m": (rotation @ head * factor + translation).tolist(),
                         "tail_world_review_m": (rotation @ tail * factor + translation).tolist(),
                         "rest_matrix_armature_local": [list(row) for row in bone.matrix_local],
                         "pose_basis_matrix": [list(row) for row in armature.pose.bones[bone.name].matrix_basis]})
        result.append({"name": armature.name, "object_matrix_world": [list(row) for row in armature.matrix_world],
                       "object_scale": list(armature.scale), "pose_position": armature.data.pose_position,
                       "bone_count": len(rows), "bones": rows})
    weight_rows = []
    for obj in meshes:
        group_names = {group.index: group.name for group in obj.vertex_groups}
        deform_names = {bone.name for armature in armatures for bone in armature.data.bones if bone.use_deform}
        total_by_bone = Counter()
        influence_counts = Counter()
        unweighted, invalid_groups, sum_errors, rows = [], [], [], []
        for vertex in obj.data.vertices:
            influences = {group_names[group.group]: group.weight for group in vertex.groups if group.weight > 0}
            influence_counts[len(influences)] += 1
            if not influences:
                unweighted.append(vertex.index)
            for name, weight in influences.items():
                total_by_bone[name] += weight
                if name not in deform_names:
                    invalid_groups.append({"vertex": vertex.index, "group": name})
            weight_sum = sum(influences.values())
            if abs(weight_sum - 1) > 1e-5:
                sum_errors.append({"vertex": vertex.index, "sum": weight_sum})
            received = np.array(obj.matrix_world @ vertex.co)
            reviewed = rotation @ received * factor + translation
            rows.append({"vertex": vertex.index, "world_review_m": reviewed.tolist(), "weights": influences})
        bottom = sorted(rows, key=lambda row: row["world_review_m"][2])[:max(16, len(rows) // 50)]
        weight_rows.append({"object": obj.name, "vertices": len(rows), "influence_histogram": dict(influence_counts),
                            "maximum_influences": max(influence_counts, default=0), "unweighted_vertices": unweighted,
                            "nondeform_or_unknown_groups": invalid_groups, "weight_sum_errors": sum_errors,
                            "total_weight_by_bone": dict(total_by_bone), "lowest_two_percent_vertices": bottom,
                            "all_vertex_weights": rows,
                            "armature_modifiers": [{"name": modifier.name, "object": modifier.object.name if modifier.object else None,
                                                    "use_vertex_groups": modifier.use_vertex_groups,
                                                    "use_bone_envelopes": modifier.use_bone_envelopes}
                                                   for modifier in obj.modifiers if modifier.type == "ARMATURE"]})
    return {"armatures": result, "weights": weight_rows,
            "hand_grip_and_foot_deformation_approved": False}


def inspect(output, render):
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.kdtree import KDTree

    for path, expected in ((SOURCE, SOURCE_SHA), (RETURNED, RETURNED_SHA)):
        if record(path)["sha256"] != expected:
            raise ValueError("Frozen input changed: " + str(path))
    receipt = json.loads(RETURNED.with_name("task.json").read_text(encoding="utf-8-sig"))
    submission = json.loads(RETURNED.with_name("submission.json").read_text(encoding="utf-8-sig"))
    intent = json.loads(RETURNED.with_name("submission.intent.json").read_text(encoding="utf-8-sig"))
    if receipt["task_id"] != TASK_ID or receipt["status"] != "success" or receipt["type"] != "animate_rig":
        raise ValueError("Unexpected rig receipt")
    if submission["task_id"] != TASK_ID or intent["source_sha256"] != SOURCE_SHA:
        raise ValueError("Rig submission lineage mismatch")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    prep = module("slinger_rig_prep", "prepare_tripo_character.py")
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    source_objects = list(bpy.context.scene.objects)
    source_meshes = [obj for obj in source_objects if obj.type == "MESH"]
    if len(source_meshes) != 1:
        raise ValueError("Unexpected repaired source object splitting")
    source = mesh_snapshot(source_meshes[0])
    source_materials = materials_report(source_meshes)
    for obj in source_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.import_scene.fbx(filepath=str(RETURNED), use_anim=True)
    imported = list(bpy.context.scene.objects)
    meshes = [obj for obj in imported if obj.type == "MESH"]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    if len(meshes) != 1:
        raise ValueError("Actual FBX has multiple meshes; refuse implicit concatenation")
    bpy.context.view_layer.update()
    returned = mesh_snapshot(meshes[0])
    report = {"schema_version": 1, "asset_id": "Unit_StoneSlinger", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "actual_rig_inspection_pending_visual_and_deformation_review", "source": record(SOURCE),
              "returned": record(RETURNED), "task": record(RETURNED.with_name("task.json")),
              "task_id": TASK_ID, "credits_consumed": receipt["credits_consumed"], "blender": bpy.app.version_string,
              "source_materials": source_materials, "received_materials": materials_report(meshes),
              "received_statistics": prep.mesh_stats(meshes), "received_surface_audit": prep.surface_audit(meshes),
              "received_objects": [{"name": obj.name, "type": obj.type, "parent": obj.parent.name if obj.parent else None,
                                    "matrix_world": [list(row) for row in obj.matrix_world]} for obj in imported],
              "actions": [action.name for action in bpy.data.actions], "source_files_modified": False,
              "material_repaired": False, "weights_modified": False, "grip_approved": False,
              "animation_approved": False, "production_approved": False}
    tree = KDTree(len(source["positions"]))
    for index, point in enumerate(source["positions"]):
        tree.insert(Vector(point), index)
    tree.balance()
    candidates = fit_axis_candidates(source["positions"], returned["positions"])
    if not candidates:
        raise ValueError("Degenerate received surface cannot establish a physical frame")
    for candidate in candidates:
        rotation = np.array(candidate["rotation"])
        transformed = returned["positions"] @ rotation.T * candidate["uniform_scale"] + candidate["translation_m"]
        distances = [tree.find(Vector(point))[2] for point in transformed]
        candidate["maximum_surface_point_error_m"] = max(distances)
        candidate["mean_surface_point_error_m"] = float(np.mean(distances))
    candidates.sort(key=lambda candidate: candidate["maximum_surface_point_error_m"])
    fit = candidates[0]
    report["frame_candidates"] = candidates
    report["frame_fit"] = fit
    try:
        report["surface_correspondence"] = triangle_correspondence(source, returned, fit)
    except ValueError as error:
        report["surface_correspondence"] = {"full_triangle_correspondence": False, "error": str(error)}
    proven = bool(report["surface_correspondence"].get("full_triangle_correspondence"))
    report["physical_frame_proven"] = proven
    report["skeleton"] = skeleton_report(armatures, meshes, fit if proven else None)
    report["texture_correspondence"] = texture_presence(source_materials, report["received_materials"])
    evaluated = meshes[0].evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    evaluated_points = np.array([list(evaluated.matrix_world @ vertex.co) for vertex in evaluated_mesh.vertices])
    report["received_rest_deformation"] = {"evaluated_vertices": len(evaluated_points),
                                           "index_count_equal": len(evaluated_points) == len(returned["positions"]),
                                           "maximum_indexed_difference_m": float(np.linalg.norm(evaluated_points - returned["positions"], axis=1).max())
                                           if len(evaluated_points) == len(returned["positions"]) else None}
    evaluated.to_mesh_clear()
    save(output / "inspection.json", report)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "Unit_StoneSlinger_received_rig.blend"))
    if proven:
        transform = Matrix.Translation(Vector(fit["translation_m"])) @ Matrix(fit["rotation"]).to_4x4() @ Matrix.Scale(fit["uniform_scale"], 4)
        for obj in imported:
            if not obj.parent or obj.parent not in imported:
                obj.matrix_world = transform @ obj.matrix_world
        bpy.context.view_layer.update()
        report["review_bounds_m"] = {"minimum": list(prep.bounds(meshes)[0]), "maximum": list(prep.bounds(meshes)[1])}
        report["review_transform"] = [list(row) for row in transform]
        report["normalization_scope"] = "Reversible review object transform only after complete triangle correspondence; no mesh, UV, normal, weight or material edits. Not an export-ready skeleton normalization."
    if render:
        bpy.context.scene.world = bpy.data.worlds.new("SlingerRigReviewWorld")
        bpy.context.scene.render.threads_mode = "FIXED"
        bpy.context.scene.render.threads = 2
        prep.render_setup(samples=8)
        images = []
        for name, direction in prep.overview_views()[:4]:
            path = output / (name + ".png")
            prep.render_view(path, meshes, direction, size=512)
            images.append(record(path))
        report["images"] = images
        report["render_material_scope"] = "Actual received FBX materials only, no source PBR reconstruction or hidden texture repair."
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "Unit_StoneSlinger_rig_review.blend"))
    report["received_blend"] = record(output / "Unit_StoneSlinger_received_rig.blend")
    report["review_blend"] = record(output / "Unit_StoneSlinger_rig_review.blend")
    if record(SOURCE)["sha256"] != SOURCE_SHA or record(RETURNED)["sha256"] != RETURNED_SHA:
        raise ValueError("Source modified during inspection")
    save(output / "inspection.json", report)
    print(json.dumps({"status": report["status"], "physical_frame_proven": proven,
                      "bones": [len(armature.data.bones) for armature in armatures], "images": len(report.get("images", [])),
                      "report": str(output / "inspection.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Use a fresh output directory")
    inspect(output, args.render)


if __name__ == "__main__":
    main()
