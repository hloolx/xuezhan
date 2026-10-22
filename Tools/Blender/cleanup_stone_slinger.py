"""Audit and split one accidental shared edge between existing Tripo surfaces.

Analyze runs in ordinary Python without launching Blender. Apply requires Blender
and creates a fresh candidate without deleting a face or moving any surface point.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
BRANCH = ART / "tripo_processed/stone_slinger_v01"
SOURCE = ART / "tripo_raw/Unit_StoneSlinger/v01_canonical/model.fbx"
SOURCE_SHA = "207a2046f413d45fc0b0ddba5e63478a9a0329cfdda8c1f022a279471f80d372"
NORMALIZED = BRANCH / "normalized_01/Unit_StoneSlinger_geometry.blend"
NORMALIZED_SHA = "91a93b9edbc0588820005aef8e6a381e7dcb3e3bb09e08cd45d4cbf62e2a2b72"
ADDON = Path("C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/5.2/scripts/addons_core/io_scene_fbx")


def file_record(path):
    return {"path": path.resolve().as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require_hash(path, expected):
    record = file_record(path)
    if record["sha256"] != expected:
        raise ValueError("Frozen source hash mismatch: " + str(path))
    return record


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def child(element, name):
    return next(item for item in element.elems if item.id == name)


def read_fbx(path):
    package = types.ModuleType("stone_slinger_readonly_fbx")
    package.__path__ = [str(ADDON)]
    sys.modules[package.__name__] = package
    threading = importlib.import_module(package.__name__ + ".fbx_utils_threading")
    threading._MULTITHREADING_ENABLED = False
    parser = importlib.import_module(package.__name__ + ".parse_fbx")
    tree, version = parser.parse(str(path))
    geometries = [item for item in child(tree, b"Objects").elems if item.id == b"Geometry"]
    if len(geometries) != 1:
        raise ValueError("Expected one frozen Tripo geometry")
    geometry = geometries[0]
    flat = child(geometry, b"Vertices").props[0]
    vertices = [tuple(flat[index:index + 3]) for index in range(0, len(flat), 3)]
    polygons, current = [], []
    for index in child(geometry, b"PolygonVertexIndex").props[0]:
        current.append(index if index >= 0 else ~index)
        if index < 0:
            polygons.append(current)
            current = []
    if current:
        raise ValueError("Unterminated FBX polygon")
    uv_layers = []
    for layer in geometry.elems:
        if layer.id != b"LayerElementUV":
            continue
        mapping = child(layer, b"MappingInformationType").props[0]
        reference = child(layer, b"ReferenceInformationType").props[0]
        if mapping != b"ByPolygonVertex" or reference != b"IndexToDirect":
            raise ValueError("Unexpected UV indexing; refuse to assume loop correspondence")
        coordinates = child(layer, b"UV").props[0]
        indices = child(layer, b"UVIndex").props[0]
        uv_layers.append({"name": child(layer, b"Name").props[0].decode(),
                          "loops": [tuple(coordinates[index * 2:index * 2 + 2]) for index in indices]})
    return vertices, polygons, uv_layers, version


def topology(vertices, polygons):
    edge_faces = defaultdict(list)
    for face_index, polygon in enumerate(polygons):
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            edge_faces[tuple(sorted((start, end)))].append(face_index)
    parent = list(range(len(polygons)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for adjacent in edge_faces.values():
        if len(adjacent) == 2:
            parent[find(adjacent[1])] = find(adjacent[0])
    patches = defaultdict(list)
    for index in range(len(polygons)):
        patches[find(index)].append(index)
    boundary = [edge for edge, adjacent in edge_faces.items() if len(adjacent) == 1]
    boundary_neighbors = defaultdict(set)
    for start, end in boundary:
        boundary_neighbors[start].add(end)
        boundary_neighbors[end].add(start)
    remaining = set(boundary_neighbors)
    boundaries = []
    while remaining:
        pending, members = [min(remaining)], set()
        while pending:
            vertex = pending.pop()
            if vertex in members:
                continue
            members.add(vertex)
            pending.extend(boundary_neighbors[vertex] - members)
        remaining -= members
        boundaries.append({"vertex_indices": sorted(members), "edge_count": sum(len(boundary_neighbors[vertex]) for vertex in members) // 2,
                           "closed_simple_loop": all(len(boundary_neighbors[vertex]) == 2 for vertex in members),
                           "vertex_degree_counts": dict(Counter(len(boundary_neighbors[vertex]) for vertex in members)),
                           "bounds_raw_fbx": bounds([vertices[vertex] for vertex in members])})
    return {"edge_faces": edge_faces, "patches": patches, "face_patch": [find(index) for index in range(len(polygons))],
            "boundary_edges": boundary, "boundary_components": boundaries}


def bounds(points):
    return {"minimum": [min(point[axis] for point in points) for axis in range(3)],
            "maximum": [max(point[axis] for point in points) for axis in range(3)]}


def edge_coordinate_multiset(vertices, edges):
    return Counter(tuple(sorted((tuple(vertices[start]), tuple(vertices[end])))) for start, end in edges)


def vertex_face_fans(polygons, graph, vertex_indices):
    rows = []
    for vertex in vertex_indices:
        incident = [index for index, face in enumerate(polygons) if vertex in face]
        neighbors = {index: set() for index in incident}
        for edge, adjacent in graph["edge_faces"].items():
            if vertex in edge:
                for face in adjacent:
                    neighbors[face].update(set(adjacent) - {face})
        remaining, fans = set(incident), []
        while remaining:
            pending, members = [min(remaining)], set()
            while pending:
                face = pending.pop()
                if face in members:
                    continue
                members.add(face)
                pending.extend(neighbors[face] - members)
            remaining -= members
            fans.append(sorted(members))
        rows.append({"vertex": vertex, "incident_faces": incident, "face_fans": fans, "fan_count": len(fans),
                     "sheet_roots_by_fan": [sorted({graph["face_patch"][face] for face in fan}) for fan in fans]})
    return rows


def split_plan(vertices, polygons, split_point_joins=False):
    before = topology(vertices, polygons)
    problematic = [(edge, faces) for edge, faces in before["edge_faces"].items() if len(faces) > 2]
    if len(problematic) != 1 or len(problematic[0][1]) != 4:
        raise ValueError("Expected exactly one four-face edge")
    edge, adjacent = problematic[0]
    groups = defaultdict(list)
    for face in adjacent:
        groups[before["face_patch"][face]].append(face)
    if sorted(map(len, groups.values())) != [2, 2]:
        raise ValueError("Four faces do not separate into two existing manifold sheets")
    for faces in groups.values():
        directions = []
        for face in faces:
            polygon = polygons[face]
            directions.extend(1 if (start, end) == edge else -1 for start, end in zip(polygon, polygon[1:] + polygon[:1]) if tuple(sorted((start, end))) == edge)
        if sorted(directions) != [-1, 1]:
            raise ValueError("Sheet pair has inconsistent edge winding")
    selected = min(groups, key=lambda root: len(before["patches"][root]))
    duplicate_vertices = list(edge)
    point_fans = None
    if split_point_joins:
        sheet_vertices = [{vertex for face in before["patches"][root] for vertex in polygons[face]} for root in groups]
        point_joins = sorted(sheet_vertices[0].intersection(sheet_vertices[1]) - set(edge))
        if point_joins != [2494, 2499, 3888, 5320]:
            raise ValueError("Targeted point-join topology differs from frozen source")
        point_fans = vertex_face_fans(polygons, before, point_joins)
        if any(row["fan_count"] != 2 or any(len(roots) != 1 for roots in row["sheet_roots_by_fan"]) for row in point_fans):
            raise ValueError("Point joins are not the proven two disconnected sheet fans")
        duplicate_vertices.extend(point_joins)
    duplicates = {vertex: len(vertices) + index for index, vertex in enumerate(duplicate_vertices)}
    changed_faces = [face for face in before["patches"][selected] if any(vertex in duplicates for vertex in polygons[face])]
    repaired_vertices = list(vertices) + [vertices[vertex] for vertex in duplicate_vertices]
    repaired_faces = [[duplicates.get(vertex, vertex) if face in changed_faces else vertex for vertex in polygon] for face, polygon in enumerate(polygons)]
    after = topology(repaired_vertices, repaired_faces)
    polygon_positions_equal = all([vertices[vertex] for vertex in old] == [repaired_vertices[vertex] for vertex in new] for old, new in zip(polygons, repaired_faces))
    boundary_equal = edge_coordinate_multiset(vertices, before["boundary_edges"]) == edge_coordinate_multiset(repaired_vertices, after["boundary_edges"])
    residual = sum(len(faces) > 2 for faces in after["edge_faces"].values())
    if not polygon_positions_equal or not boundary_equal or residual:
        raise ValueError("Candidate changes a surface/boundary or leaves a nonmanifold edge")
    result = {"edge_vertex_indices": list(edge), "adjacent_faces": adjacent,
            "sheets": [{"face_patch_root": root, "face_count": len(before["patches"][root]),
                        "adjacent_faces": faces, "bounds_raw_fbx": bounds([vertices[vertex] for face in before["patches"][root] for vertex in polygons[face]])} for root, faces in groups.items()],
            "duplicate_vertex_map": {str(key): value for key, value in duplicates.items()}, "modified_face_indices": changed_faces,
            "proof": {"faces_deleted": 0, "vertices_moved": 0, "vertices_duplicated": len(duplicate_vertices),
                      "polygon_order_and_each_corner_position_identical": polygon_positions_equal,
                      "boundary_edge_coordinate_multiset_identical": boundary_equal,
                      "boundary_edges_before": len(before["boundary_edges"]), "boundary_edges_after": len(after["boundary_edges"]),
                      "nonmanifold_index_edges_before": 1, "nonmanifold_index_edges_after": residual,
                      "manifold_face_patches_before": len(before["patches"]), "manifold_face_patches_after": len(after["patches"]),
                      "positional_weld_caveat": "The two independent sheets still physically touch along the original edge. Rewelding equal positions would recreate it; no gap, face deletion or silhouette change is introduced."},
            "boundary_components": before["boundary_components"]}
    if split_point_joins:
        affected_fans = vertex_face_fans(repaired_faces, after, duplicate_vertices + list(duplicates.values()))
        if any(row["fan_count"] != 1 for row in affected_fans):
            raise ValueError("Targeted bow-tie vertex remains after split")
        result["point_only_join_diagnostic"] = {"classification": "Four genuine nonmanifold bow-tie vertices, not continuous surface joins",
                                                "before": point_fans, "all_affected_source_and_duplicate_vertices_after": affected_fans,
                                                "all12_affected_vertices_have_one_face_fan": True,
                                                "normalization_note": "Six duplicated vertices in total: original two-edge repair plus four additional point-only joins. All source surface positions and boundaries remain identical."}
    return result


def analyze(output, split_point_joins=False):
    source = require_hash(SOURCE, SOURCE_SHA)
    normalized = require_hash(NORMALIZED, NORMALIZED_SHA)
    vertices, polygons, uv_layers, version = read_fbx(SOURCE)
    plan = split_plan(vertices, polygons, split_point_joins)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "asset_id": "Unit_StoneSlinger", "status": "readonly_source_analysis_and_candidate_simulation_passed_not_applied",
              "generated_at": datetime.now(timezone.utc).isoformat(), "source": source, "normalized_blend": normalized,
              "script": file_record(Path(__file__)), "fbx_version": version, "raw_vertices": len(vertices), "raw_polygons": len(polygons),
              "uv_layers": [{"name": layer["name"], "loop_count": len(layer["loops"]), "loop_values_sha256": hashlib.sha256(json.dumps(layer["loops"]).encode()).hexdigest()} for layer in uv_layers],
              "plan": plan, "source_coordinate_note": "Raw FBX positions; Blender axis/model transforms cancel for this exact source. Apply independently verifies every imported normalized vertex against the recorded normalization matrix.",
              "split_point_joins": split_point_joins, "blender_started": False, "production_approved": False}
    save_json(output / "analysis.json", report)
    print(json.dumps({"status": report["status"], "proof": plan["proof"], "modified_faces": plan["modified_face_indices"]}))


def preserve_encoded_normals(original, candidate, plan):
    source = original.attributes["custom_normal"]
    destination = candidate.attributes["custom_normal"]
    properties = [prop.identifier for prop in source.data[0].bl_rna.properties
                  if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
    if len(properties) != 1:
        raise ValueError("Cannot identify encoded custom-normal property")
    property_name = properties[0]
    values = [value for item in source.data for value in getattr(item, property_name)]
    destination.data.foreach_set(property_name, values)
    original_edge = tuple(plan["edge_vertex_indices"])
    duplicate_edge = tuple(plan["duplicate_vertex_map"][str(index)] for index in original_edge)
    required = {tuple(sorted(original_edge)), tuple(sorted(duplicate_edge))}
    changed = []
    for edge in candidate.edges:
        if tuple(sorted(edge.vertices)) in required:
            edge.use_edge_sharp = True
            changed.append(list(edge.vertices))
    if len(changed) != 2:
        raise ValueError("Expected exactly two separated smoothing-fan boundaries")
    candidate.update()
    copied = [value for item in destination.data for value in getattr(item, property_name)]
    if copied != values:
        raise ValueError("Encoded custom-normal loop values changed")
    return {"method": "Exact INT16_2D per-corner encoded copy with the original implicit nonmanifold smoothing-fan boundary retained on both separated edges",
            "encoded_values_sha256": hashlib.sha256(json.dumps(values).encode()).hexdigest(),
            "encoded_loop_values_equal": True, "explicit_fan_boundary_edges": changed,
            "geometric_sharpness_or_silhouette_changed": False}


def apply(output, plan_path, diagnose_only=False):
    import bpy
    from mathutils import Vector

    require_hash(SOURCE, SOURCE_SHA)
    require_hash(NORMALIZED, NORMALIZED_SHA)
    report = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if report["source"]["sha256"] != SOURCE_SHA or report["normalized_blend"]["sha256"] != NORMALIZED_SHA:
        raise ValueError("Analysis source lineage mismatch")
    vertices, polygons, uv_layers, version = read_fbx(SOURCE)
    split_point_joins = report.get("split_point_joins", False)
    plan = split_plan(vertices, polygons, split_point_joins)
    if json.loads(json.dumps(plan)) != report["plan"]:
        raise ValueError("Analysis/actual candidate mismatch")
    bpy.ops.wm.open_mainfile(filepath=str(NORMALIZED))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1 or objects[0].modifiers:
        raise ValueError("Expected one unmodified normalized body")
    obj = objects[0]
    original = obj.data
    if [list(polygon.vertices) for polygon in original.polygons] != polygons:
        raise ValueError("Imported normalized polygon indexing differs from FBX analysis")
    normalization = json.loads((BRANCH / "normalized_01/geometry_report.json").read_text(encoding="utf-8"))["normalization"]["matrix_source_world_to_result"]
    expected = [[sum(normalization[row][axis] * point[axis] for axis in range(3)) + normalization[row][3] for row in range(3)] for point in vertices]
    vertex_error = max((obj.matrix_world @ vertex.co - Vector(point)).length for vertex, point in zip(original.vertices, expected))
    if vertex_error > 1e-6:
        raise ValueError("Raw/normalized vertex correspondence failed")
    original_normals = [tuple(corner.vector) for corner in original.corner_normals]
    original_uvs = {layer.name: [tuple(loop.uv) for loop in layer.data] for layer in original.uv_layers}
    positions = [tuple(vertex.co) for vertex in original.vertices]
    duplicate_map = {int(key): value for key, value in plan["duplicate_vertex_map"].items()}
    duplicate_vertices = [index for index, target in sorted(duplicate_map.items(), key=lambda item: item[1])]
    positions.extend(positions[index] for index in duplicate_vertices)
    modified = set(plan["modified_face_indices"])
    candidate_faces = [[duplicate_map.get(vertex, vertex) if face in modified else vertex for vertex in polygon] for face, polygon in enumerate(polygons)]
    candidate = bpy.data.meshes.new("StoneSlinger_SeparatedNeckSheets")
    candidate.from_pydata(positions, [], candidate_faces)
    candidate.update()
    for material in original.materials:
        candidate.materials.append(material)
    for old, new in zip(original.polygons, candidate.polygons):
        new.material_index = old.material_index
        new.use_smooth = old.use_smooth
    for name, coordinates in original_uvs.items():
        layer = candidate.uv_layers.new(name=name)
        layer.data.foreach_set("uv", [value for coordinate in coordinates for value in coordinate])
    candidate.uv_layers.active_index = original.uv_layers.active_index
    candidate.normals_split_custom_set(original_normals)
    candidate.update()
    normal_preservation = None if diagnose_only else preserve_encoded_normals(original, candidate, plan)
    candidate.calc_loop_triangles()
    candidate_normals = [tuple(corner.vector) for corner in candidate.corner_normals]
    normal_error = max((Vector(before) - Vector(after)).length for before, after in zip(original_normals, candidate_normals))
    uv_error = max((Vector(before) - candidate.uv_layers[name].data[index].uv).length for name, coordinates in original_uvs.items() for index, before in enumerate(coordinates))
    if diagnose_only:
        diagnostic_path = output.with_suffix(".normal_diagnostic.json")
        if diagnostic_path.exists():
            raise FileExistsError(diagnostic_path)
        differences = sorted([{"loop": index, "vertex": original.loops[index].vertex_index,
                               "error": (Vector(before) - Vector(after)).length, "before": before, "after": after}
                              for index, (before, after) in enumerate(zip(original_normals, candidate_normals))], key=lambda row: row["error"], reverse=True)
        diagnostic = {"status": "read_only_rebuild_normal_diagnostic_no_export_or_render", "maximum_uv_error": uv_error,
                      "maximum_normal_vector_error": normal_error, "normal_loops_above1e_5": sum(row["error"] > 1e-5 for row in differences),
                      "largest_normal_differences": differences[:25],
                      "source_attributes": [{"name": attribute.name, "data_type": attribute.data_type, "domain": attribute.domain} for attribute in original.attributes],
                      "candidate_attributes": [{"name": attribute.name, "data_type": attribute.data_type, "domain": attribute.domain} for attribute in candidate.attributes],
                      "source_sharp_edges": sum(edge.use_edge_sharp for edge in original.edges), "candidate_sharp_edges": sum(edge.use_edge_sharp for edge in candidate.edges),
                      "source": require_hash(SOURCE, SOURCE_SHA), "normalized_blend": require_hash(NORMALIZED, NORMALIZED_SHA)}
        source_encoded = original.attributes["custom_normal"]
        destination_encoded = candidate.attributes["custom_normal"]
        value_properties = [prop.identifier for prop in source_encoded.data[0].bl_rna.properties
                            if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
        if len(value_properties) != 1:
            raise ValueError("Cannot identify exact encoded custom-normal value property")
        value_property = value_properties[0]
        encoded_values = [value for item in source_encoded.data for value in getattr(item, value_property)]
        experiments = []
        for name, preserve_nonmanifold_fan_boundary in [("raw_encoded_copy", False), ("raw_encoded_copy_preserve_original_nonmanifold_fan_boundary", True)]:
            destination_encoded.data.foreach_set(value_property, encoded_values)
            if preserve_nonmanifold_fan_boundary:
                original_edge = tuple(plan["edge_vertex_indices"])
                duplicate_edge = tuple(duplicate_map[index] for index in original_edge)
                edge_keys = {tuple(sorted(original_edge)), tuple(sorted(duplicate_edge))}
                for edge in candidate.edges:
                    if tuple(sorted(edge.vertices)) in edge_keys:
                        edge.use_edge_sharp = True
            candidate.update()
            trial_errors = [(Vector(before) - corner.vector).length for before, corner in zip(original_normals, candidate.corner_normals)]
            experiments.append({"method": name, "maximum_normal_vector_error": max(trial_errors),
                                "loops_above1e_5": sum(error > 1e-5 for error in trial_errors),
                                "sharp_edge_count": sum(edge.use_edge_sharp for edge in candidate.edges),
                                "largest_errors": sorted([{"loop": index, "vertex": original.loops[index].vertex_index, "error": error} for index, error in enumerate(trial_errors)], key=lambda row: row["error"], reverse=True)[:8]})
        diagnostic["encoded_normal_property"] = value_property
        diagnostic["encoded_copy_experiments"] = experiments
        save_json(diagnostic_path, diagnostic)
        print(json.dumps({"normal_diagnostic": str(diagnostic_path), "uv_error": uv_error, "normal_error": normal_error, "experiments": experiments}))
        return
    if uv_error != 0.0 or normal_error > 1e-5:
        raise ValueError(f"Preserved UV/custom normals did not roundtrip: UV={uv_error}, normals={normal_error}")
    actual_positions = [tuple(vertex.co) for vertex in candidate.vertices]
    actual_polygons = [list(polygon.vertices) for polygon in candidate.polygons]
    original_positions = [tuple(vertex.co) for vertex in original.vertices]
    if any([original_positions[index] for index in old] != [actual_positions[index] for index in new] for old, new in zip(polygons, actual_polygons)):
        raise ValueError("Actual rebuilt mesh changed polygon surface positions")
    original_topology = topology(original_positions, polygons)
    actual_topology = topology(actual_positions, actual_polygons)
    if edge_coordinate_multiset(original_positions, original_topology["boundary_edges"]) != edge_coordinate_multiset(actual_positions, actual_topology["boundary_edges"]):
        raise ValueError("Actual rebuilt mesh changed a boundary edge")
    if any(len(faces) > 2 for faces in actual_topology["edge_faces"].values()):
        raise ValueError("Actual candidate retains a nonmanifold index edge")
    actual_affected_fans = vertex_face_fans(actual_polygons, actual_topology, duplicate_vertices + list(duplicate_map.values()))
    if split_point_joins and any(row["fan_count"] != 1 for row in actual_affected_fans):
        raise ValueError("Actual rebuilt mesh retains a targeted bow-tie vertex")
    output.mkdir(parents=True, exist_ok=False)
    module_spec = importlib.util.spec_from_file_location("character_prep", ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(prep)
    for item in list(bpy.context.scene.objects):
        if item.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(item, do_unlink=True)
    prep.render_setup(samples=8)
    shots = [
        ("seam_before", False, (0.8, 1, .15), (0.005, .085, 1.188), .24),
        ("seam_after", True, (0.8, 1, .15), (0.005, .085, 1.188), .24),
        ("seam_back_before", False, (-.8, 1, .1), (0.005, .085, 1.188), .24),
        ("seam_back_after", True, (-.8, 1, .1), (0.005, .085, 1.188), .24),
        ("hand_positive_y", True, (1, 1, .15), (0, .419, .652), .24),
        ("hand_negative_y", True, (1, -1, .15), (0, -.419, .652), .24),
        ("shoulder", True, (1, 1, .3), (0, .21, 1.047), .39),
        ("pouch", True, (1, 1, .1), (.025, .191, .707), .32)]
    if split_point_joins:
        shots = shots[:4] + [("hand_positive_y_complete", True, (1, 1, .15), (0, .419, .61), .38),
                            ("hand_negative_y_complete", True, (1, -1, .15), (0, -.419, .61), .38)]
    images = []
    hand_framing = []
    for name, repaired, direction, target, framing in shots:
        obj.data = candidate if repaired else original
        bpy.context.view_layer.update()
        bpy.context.scene.cycles.seed = 0
        path = output / (name + ".png")
        prep.render_view(path, objects, direction, size=512, framing=framing, target=target)
        if "complete" in name:
            side = 1 if "positive" in name else -1
            inverse_camera = bpy.context.scene.camera.matrix_world.inverted()
            hand_points = [obj.matrix_world @ vertex.co for vertex in candidate.vertices if side * vertex.co.y > .33 and .46 <= vertex.co.z <= .76]
            projected = [inverse_camera @ point for point in hand_points]
            maximum_fraction = max(max(abs(point.x), abs(point.y)) / (framing * .5) for point in projected)
            hand_framing.append({"image": name + ".png", "candidate_hand_region_vertices": len(hand_points),
                                 "geometry_mask": "side*Y>.33m and .46m<=Z<=.76m, includes palm and fingertip extremes but not the upper forearm",
                                 "maximum_absolute_projected_half_frame_fraction": maximum_fraction,
                                 "minimum_projected_frame_margin_fraction": (1.0 - maximum_fraction) / 2.0})
            if maximum_fraction > .96:
                raise ValueError("Complete hand framing does not leave a safe image margin")
        images.append(file_record(path))
    obj.data = candidate
    bpy.context.view_layer.update()
    prep.select(objects)
    model = output / "Unit_StoneSlinger_cleanup.glb"
    bpy.ops.export_scene.gltf(filepath=str(model), export_format="GLB", use_selection=True, export_yup=True, export_apply=False,
                              export_animations=False, export_skins=False, export_morph=False, export_materials="EXPORT")
    roundtrip = prep.verify_glb(model, objects)
    blend = output / "Unit_StoneSlinger_cleanup.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    result = {"asset_id": "Unit_StoneSlinger", "status": f"candidate_saved_pending_actual_{len(images)}_view_review",
              "source": require_hash(SOURCE, SOURCE_SHA), "normalized_blend": require_hash(NORMALIZED, NORMALIZED_SHA),
              "analysis": file_record(plan_path), "script": file_record(Path(__file__)), "plan": plan,
              "raw_to_normalized_max_vertex_error_m": vertex_error, "maximum_loop_uv_error": uv_error,
              "maximum_custom_corner_normal_vector_error": normal_error,
              "normal_preservation": normal_preservation,
              "actual_candidate_surface_corners_and_boundary_multiset_unchanged": True,
              "actual_affected_vertex_face_fans": actual_affected_fans,
              "source_attributes": [{"name": attribute.name, "data_type": attribute.data_type, "domain": attribute.domain} for attribute in original.attributes],
              "candidate_attributes": [{"name": attribute.name, "data_type": attribute.data_type, "domain": attribute.domain} for attribute in candidate.attributes],
              "mesh_statistics": prep.mesh_stats(objects), "roundtrip": roundtrip,
              "model": file_record(model), "blend": file_record(blend), "images": images, "complete_hand_framing": hand_framing,
              "all_faces_retained": len(candidate.polygons) == len(original.polygons), "production_approved": False, "rig_approved": False}
    save_json(output / "cleanup_report.json", result)
    print(json.dumps({"status": result["status"], "images": len(images), "uv_error": uv_error, "normal_error": normal_error, "roundtrip": roundtrip}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["analyze", "apply"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--split-point-joins", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a new directory")
    if args.mode == "analyze":
        analyze(output, args.split_point_joins)
    elif args.plan:
        apply(output, args.plan.resolve(), args.diagnose_only)
    else:
        raise ValueError("Apply requires the frozen analysis plan")


if __name__ == "__main__":
    main()
