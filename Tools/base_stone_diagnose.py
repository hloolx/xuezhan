"""Read-only CPU measurements of the frozen Base_Stone axis probe."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"
PROBE = OWNED / "hb744e496242c_axis_probe/Base_Stone_geometry.glb"
PROBE_SHA = "e8e241e2070fb762a5f7994925b9035558495a26a737b0bc6970b020e1f8af08"
SOURCE = ROOT / "RawAssets/Art/Tripo_v01/tripo_raw/Base_Stone/v01_canonical/model.glb"
SOURCE_SHA = "d071b89ed9430fd5c99c92cd1d26b37b1dd7c358497c11f36d890502cca56a01"
BODY = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/stoneaxe_rig_pilot/animation_draft_v05/StoneAxe_animation_draft.blend"
BODY_SHA = "9bdc59d1fd7c049bedf4d208418d2597d44b8257409b2ae7b808d81bc9096b6b"
OUTPUT = OWNED / "cpu_diagnostic_v01"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path):
    return {"file": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}


def save(name, value):
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def vector_cm(point):
    return [round(float(value) * 100, 5) for value in point]


def bounds(points):
    lower = [min(point[axis] for point in points) for axis in range(3)]
    upper = [max(point[axis] for point in points) for axis in range(3)]
    return {"min_cm": vector_cm(lower), "max_cm": vector_cm(upper),
            "dimensions_cm": vector_cm([upper[axis] - lower[axis] for axis in range(3)])}


def ray(tree, start, direction, distance=10):
    point, normal, face, travel = tree.ray_cast(Vector(start), Vector(direction), distance)
    if point is None:
        return None
    return {"position_cm": vector_cm(point), "normal": list(normal), "triangle": face,
            "distance_cm": round(float(travel) * 100, 5)}


def all_hits(tree, start, direction, distance=10):
    position = Vector(start)
    direction = Vector(direction).normalized()
    travelled = 0
    result = []
    for attempt in range(64):
        point, normal, face, travel = tree.ray_cast(position, direction, distance - travelled)
        if point is None:
            break
        travelled += travel + .00001
        result.append({"position_cm": vector_cm(point), "normal": list(normal), "triangle": face})
        position = point + direction * .00001
        if travelled >= distance:
            break
    return result


def topology(mesh, matrix):
    copied = bmesh.new()
    copied.from_mesh(mesh)
    for vertex in copied.verts:
        vertex.co = matrix @ vertex.co
    bmesh.ops.remove_doubles(copied, verts=list(copied.verts), dist=6.4e-6)
    copied.verts.ensure_lookup_table()
    copied.edges.ensure_lookup_table()
    copied.faces.ensure_lookup_table()
    copied.verts.index_update()
    copied.faces.index_update()
    pending = set(copied.verts)
    components = []
    vertex_group = {}
    while pending:
        seed = pending.pop()
        stack, group = [seed], [seed]
        while stack:
            current = stack.pop()
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other in pending:
                    pending.remove(other)
                    stack.append(other)
                    group.append(other)
        identifier = len(components)
        faces = {face for vertex in group for face in vertex.link_faces}
        edges = {edge for vertex in group for edge in vertex.link_edges}
        components.append({"id": identifier, "vertices": len(group), "faces": len(faces),
                           "area_cm2": sum(face.calc_area() for face in faces) * 10000,
                           "bounds": bounds([vertex.co for vertex in group]),
                           "boundary_edges": sum(edge.is_boundary for edge in edges),
                           "nonmanifold_edges_including_boundary": sum(not edge.is_manifold for edge in edges)})
        vertex_group.update({vertex: identifier for vertex in group})
    bad_edges = []
    for edge in copied.edges:
        if edge.is_manifold:
            continue
        midpoint = (edge.verts[0].co + edge.verts[1].co) / 2
        bad_edges.append({"endpoints_cm": [vector_cm(vertex.co) for vertex in edge.verts],
                          "midpoint_cm": vector_cm(midpoint), "length_cm": edge.calc_length() * 100,
                          "adjacent_faces": len(edge.link_faces), "component": vertex_group[edge.verts[0]],
                          "face_centres_cm": [vector_cm(face.calc_center_median()) for face in edge.link_faces]})
    result = {"source_mesh_modified": False, "position_weld_copy_tolerance_m": 6.4e-6,
              "vertices_after_diagnostic_weld": len(copied.verts), "faces_after_diagnostic_weld": len(copied.faces),
              "boundary_edges": sum(edge.is_boundary for edge in copied.edges),
              "nonmanifold_edges_including_boundary": sum(not edge.is_manifold for edge in copied.edges),
              "components": sorted(components, key=lambda entry: -entry["faces"]), "exception_edges": bad_edges}
    copied.free()
    return result


def horizontal_profiles(tree):
    values = []
    for x_cm in range(-100, 281, 5):
        for z_cm in (20, 50, 80, 110, 140, 150, 170, 190):
            negative = ray(tree, (x_cm / 100, 0, z_cm / 100), (0, -1, 0), 4)
            positive = ray(tree, (x_cm / 100, 0, z_cm / 100), (0, 1, 0), 4)
            values.append({"x_cm": x_cm, "z_cm": z_cm,
                           "negative_y_hit": negative, "positive_y_hit": positive,
                           "clear_span_cm": positive["position_cm"][1] - negative["position_cm"][1]
                           if negative and positive else None})
    return values


def vertical_profiles(tree):
    values = []
    for y_cm in (-171.5, -161.5, -151.5, -95, -85, -75, 0, 75, 85, 95, 151.5, 161.5, 171.5):
        for x_cm in range(-100, 321, 5):
            floor = ray(tree, (x_cm / 100, y_cm / 100, .35), (0, 0, -1), .5)
            floor_z = floor["position_cm"][2] / 100 if floor else 0
            ceiling = ray(tree, (x_cm / 100, y_cm / 100, floor_z + .005), (0, 0, 1), 5)
            values.append({"x_cm": x_cm, "y_cm": y_cm, "floor_hit": floor,
                           "ceiling_hit": ceiling, "clear_height_cm": ceiling["position_cm"][2] - floor_z * 100
                           if ceiling else None})
    return values


def largest_rectangle(mask):
    if not mask:
        return None
    heights = [0] * len(mask[0])
    best = (0, None)
    for row_index, row in enumerate(mask):
        heights = [height + 1 if enabled else 0 for height, enabled in zip(heights, row)]
        stack = []
        for column_index in range(len(heights) + 1):
            current = heights[column_index] if column_index < len(heights) else 0
            first_column = column_index
            while stack and stack[-1][1] > current:
                first_column, height = stack.pop()
                area = (column_index - first_column) * height
                if area > best[0]:
                    best = area, (row_index - height + 1, row_index, first_column, column_index - 1)
            stack.append((first_column, current))
    return best[1]


def platform(tree, vertices, triangles, name, limits):
    candidate = []
    for face_index, triangle in enumerate(triangles):
        points = [vertices[index] for index in triangle]
        centre = sum(points, Vector()) / 3
        area_vector = (points[1] - points[0]).cross(points[2] - points[0])
        area = area_vector.length / 2
        if area == 0 or area_vector.normalized().z < .96:
            continue
        if all(limits[axis][0] <= centre[axis] <= limits[axis][1] for axis in range(3)):
            candidate.append((face_index, centre, area, area_vector.normalized()))
    bins = defaultdict(float)
    for face_index, centre, area, normal in candidate:
        bins[round(centre.z / .05)] += area
    if not bins:
        return {"id": name, "found": False}
    peak = max(bins, key=bins.get)
    selected = [entry for entry in candidate if abs(entry[1].z - peak * .05) < .08]
    total_area = sum(entry[2] for entry in selected)
    centre = sum((entry[1] * entry[2] for entry in selected), Vector()) / total_area
    centre_hit = ray(tree, (centre.x, centre.y, 5), (0, 0, -1), 6)
    surface_z = centre_hit["position_cm"][2] / 100
    x_values = [centimetres / 100 for centimetres in range(math.ceil(limits[0][0] * 100), math.floor(limits[0][1] * 100) + 1, 2)]
    y_values = [centimetres / 100 for centimetres in range(math.ceil(limits[1][0] * 100), math.floor(limits[1][1] * 100) + 1, 2)]
    grid, hits = [], []
    for x_value in x_values:
        row = []
        for y_value in y_values:
            hit = ray(tree, (x_value, y_value, 5), (0, 0, -1), 6)
            usable = hit is not None and hit["normal"][2] > .96 and abs(hit["position_cm"][2] / 100 - surface_z) <= .02
            row.append(usable)
            if usable:
                hits.append(hit)
        grid.append(row)
    rectangle = largest_rectangle(grid)
    footprint = None
    if rectangle:
        first_x, last_x, first_y, last_y = rectangle
        footprint = {"x_range_cm": [x_values[first_x] * 100, x_values[last_x] * 100],
                     "y_range_cm": [y_values[first_y] * 100, y_values[last_y] * 100],
                     "sample_span_dimensions_cm": [(x_values[last_x] - x_values[first_x]) * 100,
                                                   (y_values[last_y] - y_values[first_y]) * 100]}
    return {"id": name, "found": True, "roi_m": limits, "upward_normal_z_min": .96,
            "area_weighted_near_horizontal_face_centre_cm": vector_cm(centre),
            "centre_ray_top": centre_hit, "selected_face_area_cm2": total_area * 10000,
            "height_area_bins_cm_cm2": {str(key * 5): area * 10000 for key, area in sorted(bins.items())},
            "selected_triangle_ids": [entry[0] for entry in selected],
            "flat_grid_step_cm": 2, "flat_grid_height_tolerance_cm": 2,
            "largest_sampled_clear_rectangle": footprint,
            "flat_sample_height_range_cm": [min(hit["position_cm"][2] for hit in hits), max(hit["position_cm"][2] for hit in hits)] if hits else None,
            "approved_as_turret_socket": False,
            "limitation": "2 cm grid excludes top rims by slope/height but does not validate a RockTower sweep, support strength, or sub-grid holes."}


def body_envelopes():
    bpy.ops.wm.open_mainfile(filepath=str(BODY))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    result = []
    for clip, frames in {"Idle": [1, 61, 121], "Move": [1, 10, 19, 28, 37]}.items():
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            graph = bpy.context.evaluated_depsgraph_get()
            points = []
            for obj in meshes:
                evaluated = obj.evaluated_get(graph)
                mesh = evaluated.to_mesh()
                points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
                evaluated.to_mesh_clear()
            slices = []
            for height in range(0, 150, 10):
                subset = [point for point in points if height / 100 <= point.z < (height + 10) / 100]
                if subset:
                    slices.append({"z_band_cm": [height, height + 10], "bounds": bounds(subset)})
            result.append({"clip": clip, "frame": frame, "body_meshes": [obj.name for obj in meshes],
                           "body_vertex_bounds": bounds(points), "height_slices": slices})
    return {"source": record(BODY), "sampled_poses": result, "weapon_included": False,
            "limitation": "Actual evaluated body vertices; finite pose samples are not continuous collision testing. Weapon, mount and other unit bodies require separate gates."}


def main():
    for path, expected in ((SOURCE, SOURCE_SHA), (PROBE, PROBE_SHA), (BODY, BODY_SHA)):
        if digest(path) != expected:
            raise ValueError("Frozen source changed: " + str(path))
    OUTPUT.mkdir(exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(PROBE))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1:
        raise ValueError("Expected one source mesh; do not merge unexpected parts")
    obj = objects[0]
    obj.data.calc_loop_triangles()
    vertices = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    triangles = [tuple(triangle.vertices) for triangle in obj.data.loop_triangles]
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    topology_result = topology(obj.data, obj.matrix_world)
    save("topology.json", topology_result)
    horizontal, vertical = horizontal_profiles(tree), vertical_profiles(tree)
    save("horizontal_clearance_samples.json", horizontal)
    save("vertical_clearance_samples.json", vertical)
    platforms = [platform(tree, vertices, triangles, "front_negative_y", ((.8, 2.6), (-3, -1), (1.3, 2.5))),
                 platform(tree, vertices, triangles, "front_positive_y", ((.8, 2.6), (1, 3), (1.3, 2.5))),
                 platform(tree, vertices, triangles, "rear", ((-2.7, -.8), (-1, 1), (2.9, 4.2)))]
    save("platforms.json", platforms)
    roof_sections = []
    for z_cm in range(225, 301, 2):
        for y_cm in (0, -25, 25, -50, 50):
            roof_sections.append({"z_cm": z_cm, "y_cm": y_cm,
                                  "hits": all_hits(tree, (3, y_cm / 100, z_cm / 100), (-1, 0, 0), 6)})
    save("roof_cross_sections.json", roof_sections)
    body = body_envelopes()
    save("stoneaxe_actual_body_envelopes.json", body)
    unchanged = all(digest(path) == expected for path, expected in ((SOURCE, SOURCE_SHA), (PROBE, PROBE_SHA), (BODY, BODY_SHA)))
    summary = {"asset_id": "Base_Stone", "status": "numeric_diagnosis_only_pending_review", "created_at": datetime.now(timezone.utc).isoformat(),
               "source": record(SOURCE), "diagnostic_model": record(PROBE), "tool": record(Path(__file__)),
               "basis": "+X gate, +Z up, uniform horizontal maximum640cm, provisional bottom bounding centre; not gameplay-final origin",
               "source_bytes_unchanged": unchanged, "mesh_modified": False, "uv_modified": False, "gpu_used": False, "threads": 2,
               "dimensions": bounds(vertices), "triangles": len(triangles), "topology_component_count": len(topology_result["components"]),
               "topology_boundary_edges": topology_result["boundary_edges"], "topology_nonmanifold_edges_including_boundary": topology_result["nonmanifold_edges_including_boundary"],
               "gameplay_comparison": {"existing_gate_front_x_cm": 300, "StoneAxe_spawn_x_cm": 260, "Slinger_spawn_x_cm": 264, "BeastRider_spawn_x_cm": 240,
                                       "lane_row_centres_y_cm": [-85, 0, 85], "jitter_cm": [-10, 10], "champion_y_cm": [-161.5, 161.5],
                                       "sim_coordinates_modified": False, "inner_hut_traversal_required": False},
               "reports": [record(path) for path in sorted(OUTPUT.glob("*.json"))], "approved_for_texture": False,
               "approved_for_ue_import": False, "production_approved": False}
    save("report.json", summary)
    if not unchanged:
        raise ValueError("Source protection failed")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
