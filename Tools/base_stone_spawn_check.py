"""Measure openings and check real posed surfaces without editing any source."""
import importlib.util
import json
from pathlib import Path
from collections import Counter

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_ray_tri


MODULE = Path(__file__).with_name("base_stone_diagnose.py")
MODULE_SPEC = importlib.util.spec_from_file_location("base_measurements", MODULE)
measure = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(measure)
OUTPUT = measure.OWNED / "cpu_spawn_diagnostic_v02"
BASE_Z_CM = 0


def save(name, value):
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def surface(objects):
    vertices, triangles = [], []
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        offset = len(vertices)
        vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        triangles.extend(tuple(offset + index for index in triangle.vertices) for triangle in mesh.loop_triangles)
        evaluated.to_mesh_clear()
    return vertices, triangles


def intersects(first, second):
    for moving, target in ((first, second), (second, first)):
        for edge_index in range(3):
            start, end = moving[edge_index], moving[(edge_index + 1) % 3]
            direction = end - start
            length = direction.length
            if length < 1e-10:
                continue
            hit = intersect_ray_tri(*target, direction / length, start, True)
            if hit is not None and (hit - start).length <= length + 1e-7:
                return hit
    return None


def openings(tree):
    records = []
    for y_cm in (-50, -25, 0, 25, 50):
        for x_cm in range(80, 221, 2):
            floor_hits = measure.all_hits(tree, (x_cm / 100, y_cm / 100, .8), (0, 0, -1), 1)
            candidates = [hit for hit in floor_hits if hit["normal"][2] > .65]
            floor = candidates[0] if candidates else None
            floor_z = floor["position_cm"][2] / 100 if floor else 0
            ceiling = measure.ray(tree, (x_cm / 100, y_cm / 100, floor_z + .002), (0, 0, 1), 5)
            records.append({"x_cm": x_cm, "y_cm": y_cm, "floor_hit": floor,
                            "ceiling_hit": ceiling, "clear_height_cm": ceiling["position_cm"][2] - floor_z * 100 if ceiling else None,
                            "floor_search_maximum_z_cm": 80})
    return records


def pose_cache():
    bpy.ops.wm.open_mainfile(filepath=str(measure.BODY))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    body = [obj for obj in meshes if any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    weapon = [obj for obj in meshes if obj not in body]
    result = []
    for clip, frames in (("Idle", [1, 31, 61, 91, 121]), ("Move", range(1, 38))):
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            for group, objects in (("body", body), ("weapon", weapon)):
                vertices, triangles = surface(objects)
                result.append({"clip": clip, "frame": frame, "group": group, "objects": [obj.name for obj in objects],
                               "vertices": vertices, "triangles": triangles,
                               "bounds": measure.bounds(vertices), "tree": BVHTree.FromPolygons(vertices, triangles, all_triangles=True)})
    return result


def main():
    for path, expected in ((measure.SOURCE, measure.SOURCE_SHA), (measure.PROBE, measure.PROBE_SHA), (measure.BODY, measure.BODY_SHA)):
        if measure.digest(path) != expected:
            raise ValueError("Frozen source changed: " + str(path))
    OUTPUT.mkdir(exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(measure.PROBE))
    vertices, triangles = surface([obj for obj in bpy.context.scene.objects if obj.type == "MESH"])
    vertices = [vertex + Vector((0, 0, BASE_Z_CM / 100)) for vertex in vertices]
    base_tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    base_bounds = measure.bounds(vertices)
    ground_faces = []
    for face_index, triangle in enumerate(triangles):
        points = [vertices[index] for index in triangle]
        normal = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
        centre = sum(points, Vector()) / 3
        if normal.z > .65 and centre.z < .8 + BASE_Z_CM / 100:
            ground_faces.append({"triangle": face_index, "centre_cm": measure.vector_cm(centre),
                                 "normal": list(normal), "points_cm": [measure.vector_cm(point) for point in points]})
    contact_queries = []
    for label, x_cm, y_cm in (("gate_centre", 205, 0), ("gate_negative_post_base", 205, -65),
                              ("gate_positive_post_base", 205, 65), ("hut_threshold", 110, 0),
                              ("front_platform_negative_lower_support", 195, -250),
                              ("front_platform_positive_lower_support", 195, 250),
                              ("rear_platform_lower_support", -180, 45), ("front_soil_exit", 240, 0),
                              ("outer_row_worst_soil", 230.06287, 100.86468)):
        contact_queries.append({"label": label, "x_cm": x_cm, "y_cm": y_cm,
                                "hits_down_from_100cm": measure.all_hits(base_tree, (x_cm / 100, y_cm / 100, 1), (0, 0, -1), 2)})
    save("ground_surface_and_contact_probes.json", {"classification": "Spatial low upward surfaces only; not a completed semantic soil/architecture split",
                                                   "base_z_offset_cm": BASE_Z_CM, "low_upward_faces": ground_faces,
                                                   "contact_probes": contact_queries})
    save("refined_openings.json", openings(base_tree))
    poses = pose_cache()
    save("pose_geometry_inventory.json", [{key: value for key, value in pose.items() if key not in {"vertices", "triangles", "tree"}} for pose in poses])
    sample_counts = {"aabb_rejected": 0, "exact_surface_tests": 0, "candidate_triangle_pairs": 0, "confirmed_triangle_crossings": 0}
    evidence, summaries = [], []
    hit_faces = Counter()
    hit_points = []
    rows = [-95, -85, -75, -10, 0, 10, 75, 85, 95]
    for x_cm in range(260, 321, 5):
        for y_cm in rows:
            offset = Vector((x_cm / 100, y_cm / 100, 0))
            relative_vertices = [vertex - offset for vertex in vertices]
            relative_tree = None
            for pose in poses:
                lower, upper = pose["bounds"]["min_cm"], pose["bounds"]["max_cm"]
                if any(upper[axis] + offset[axis] * 100 < base_bounds["min_cm"][axis] - .001 or
                       lower[axis] + offset[axis] * 100 > base_bounds["max_cm"][axis] + .001 for axis in range(3)):
                    sample_counts["aabb_rejected"] += 1
                    continue
                if relative_tree is None:
                    relative_tree = BVHTree.FromPolygons(relative_vertices, triangles, all_triangles=True)
                sample_counts["exact_surface_tests"] += 1
                pairs = relative_tree.overlap(pose["tree"])
                sample_counts["candidate_triangle_pairs"] += len(pairs)
                confirmed = 0
                for base_face, actor_face in pairs:
                    hit = intersects([relative_vertices[index] for index in triangles[base_face]],
                                     [pose["vertices"][index] for index in pose["triangles"][actor_face]])
                    if hit is None:
                        continue
                    confirmed += 1
                    hit_faces[base_face] += 1
                    hit_points.append(hit + offset)
                    if len(evidence) < 120:
                        evidence.append({"spawn_offset_cm": [x_cm, y_cm, 0], "clip": pose["clip"], "frame": pose["frame"], "group": pose["group"],
                                         "base_triangle": base_face, "actor_triangle": actor_face, "hit_cm": measure.vector_cm(hit + offset)})
                sample_counts["confirmed_triangle_crossings"] += confirmed
                if confirmed:
                    summaries.append({"x_cm": x_cm, "y_cm": y_cm, "clip": pose["clip"], "frame": pose["frame"],
                                      "group": pose["group"], "triangle_crossings": confirmed})
    sweep_counts = {"rays_cast": 0, "hit_vertices": 0}
    sweep_evidence = []
    for y_cm in rows:
        offset = Vector((2.6, y_cm / 100, 0))
        for pose in poses:
            for vertex_index, vertex in enumerate(pose["vertices"]):
                origin = vertex + offset
                if origin.x > base_bounds["max_cm"][0] / 100 or origin.y < base_bounds["min_cm"][1] / 100 or origin.y > base_bounds["max_cm"][1] / 100:
                    continue
                sweep_counts["rays_cast"] += 1
                hit, normal, face, distance = base_tree.ray_cast(origin, Vector((1, 0, 0)), .6)
                if hit is not None:
                    sweep_counts["hit_vertices"] += 1
                    if len(sweep_evidence) < 120:
                        sweep_evidence.append({"y_cm": y_cm, "clip": pose["clip"], "frame": pose["frame"], "group": pose["group"],
                                               "vertex": vertex_index, "base_triangle": face, "hit_cm": measure.vector_cm(hit),
                                               "actor_origin_x_at_hit_cm": 260 + distance * 100})
    foot_records = []
    for y_cm in rows:
        for pose in poses:
            if pose["group"] != "body":
                continue
            penetrations = []
            for vertex_index, vertex in enumerate(pose["vertices"]):
                if vertex.z > .15:
                    continue
                origin = vertex + Vector((2.6, y_cm / 100, 0))
                hit = measure.ray(base_tree, (origin.x, origin.y, .8), (0, 0, -1), 1)
                if hit and hit["normal"][2] > .65 and hit["position_cm"][2] - origin.z * 100 > .1:
                    penetrations.append({"vertex": vertex_index, "surface_above_vertex_cm": hit["position_cm"][2] - origin.z * 100,
                                         "vertex_cm": measure.vector_cm(origin), "base_triangle": hit["triangle"]})
            if penetrations:
                foot_records.append({"y_cm": y_cm, "clip": pose["clip"], "frame": pose["frame"],
                                     "vertex_count": len(penetrations), "worst": max(penetrations, key=lambda entry: entry["surface_above_vertex_cm"])})
    source_faces = []
    for face_index, count in sorted(hit_faces.items()):
        points = [vertices[index] for index in triangles[face_index]]
        normal = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
        source_faces.append({"triangle": face_index, "crossing_pair_count": count, "bounds": measure.bounds(points),
                             "points_cm": [measure.vector_cm(point) for point in points], "normal": list(normal)})
    save("surface_intersections.json", {"counts": sample_counts, "nonzero_samples": summaries, "evidence_first120": evidence,
                                         "all_intersected_source_faces": source_faces,
                                         "confirmed_intersection_bounds": measure.bounds(hit_points) if hit_points else None})
    save("vertex_sweeps.json", {"counts": sweep_counts, "evidence_first120": sweep_evidence})
    save("spawn_ground_contact.json", foot_records)
    unchanged = all(measure.digest(path) == expected for path, expected in ((measure.SOURCE, measure.SOURCE_SHA), (measure.PROBE, measure.PROBE_SHA), (measure.BODY, measure.BODY_SHA)))
    result = {"asset_id": "Base_Stone", "status": "actual_spawn_surface_diagnostic_not_gate_traversal_approval",
              "source": measure.record(measure.SOURCE), "diagnostic_model": measure.record(measure.PROBE), "actor": measure.record(measure.BODY),
              "tool": measure.record(Path(__file__)), "mesh_modified": False, "source_bytes_unchanged": unchanged, "gpu_used": False, "threads": 2,
              "base_translation_cm": [0, 0, BASE_Z_CM], "base_yaw_degrees": 0, "actor_scale_factor": 1,
              "actor_x_samples_cm": list(range(260, 321, 5)), "actor_y_samples_cm": rows, "clip_samples": {"Idle": [1, 31, 61, 91, 121], "Move": list(range(1, 38))},
              "triangle_test_counts": sample_counts, "vertex_sweep_counts": sweep_counts, "ground_penetrating_pose_row_samples": len(foot_records),
              "limitations": ["AABB is broad-phase rejection only. Positive crossings require triangle edge/ray intersection in both directions.",
                              "Frozen-pose vertex sweeps cover X260 to320 continuously; posed surfaces are sampled every5cm with all Move frames, not formal continuous solid collision detection.",
                              "Coplanar triangle overlap without crossing, enclosed components, other units, champions, attack poses and mammoth spawnX240 remain untested.",
                              "This checks unshifted diagnostic source at current base root, not passage through the small gate or hut."],
              "reports": [measure.record(path) for path in sorted(OUTPUT.glob("*.json"))],
              "approved_for_texture": False, "approved_for_ue_import": False, "production_approved": False}
    save("report.json", result)
    if not unchanged:
        raise ValueError("Source protection failed")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
