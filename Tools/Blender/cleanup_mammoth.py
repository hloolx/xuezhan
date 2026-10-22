"""Read-only classification and index-split simulation for the frozen Tripo mammoth."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_stone_slinger as helpers


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
BRANCH = ART / "tripo_processed/mammoth_v01"
SOURCE = ART / "tripo_raw/Mount_Mammoth/v01_canonical/model.fbx"
SOURCE_SHA = "20ec5c0498e77817ab412d51586462873b79e5d0db0e20d4f73c347745d4cc81"
NORMALIZED = BRANCH / "normalized_01/Mount_Mammoth_geometry.blend"
NORMALIZED_SHA = "a530fe5e66cf918116a183194c5c6a2621689b84b4c6a2b9ecf0a79074baf02b"
NORMALIZATION = BRANCH / "normalized_01/geometry_report.json"


def classify(vertices, polygons):
    before = helpers.topology(vertices, polygons)
    bad = [(edge, faces) for edge, faces in before["edge_faces"].items() if len(faces) > 2]
    main_patch = max(before["patches"], key=lambda key: len(before["patches"][key]))
    selected_patches = set()
    rows = []
    for edge, faces in bad:
        by_patch = defaultdict(list)
        for face in faces:
            by_patch[before["face_patch"][face]].append(face)
        if len(faces) != 3 or sorted(map(len, by_patch.values())) != [1, 2] or len(by_patch.get(main_patch, ())) != 2:
            raise ValueError("Not the proven main-sheet plus accessory-sheet three-face junction")
        accessory = next(root for root in by_patch if root != main_patch)
        selected_patches.add(accessory)
        winding = []
        for face in by_patch[main_patch]:
            polygon = polygons[face]
            winding.extend(1 if (start, end) == edge else -1 for start, end in zip(polygon, polygon[1:] + polygon[:1]) if tuple(sorted((start, end))) == edge)
        if sorted(winding) != [-1, 1]:
            raise ValueError("The main sheet pair has inconsistent winding")
        rows.append({"edge": list(edge), "adjacent_faces": faces, "main_sheet_faces": by_patch[main_patch],
                     "accessory_patch": accessory, "accessory_face": by_patch[accessory][0],
                     "positions_raw_fbx": [vertices[index] for index in edge]})
    source_vertex_patches = defaultdict(set)
    for face, polygon in enumerate(polygons):
        for vertex in polygon:
            source_vertex_patches[vertex].add(before["face_patch"][face])
    candidate_vertices = list(vertices)
    candidate_faces = [list(polygon) for polygon in polygons]
    patch_rows = []
    all_affected_vertices = set()
    for root in sorted(selected_patches):
        patch = before["patches"][root]
        patch_vertices = {vertex for face in patch for vertex in polygons[face]}
        shared = sorted(vertex for vertex in patch_vertices if len(source_vertex_patches[vertex]) > 1)
        mapping = {vertex: len(candidate_vertices) + index for index, vertex in enumerate(shared)}
        candidate_vertices.extend(vertices[index] for index in shared)
        affected = [face for face in patch if any(vertex in mapping for vertex in polygons[face])]
        for face in affected:
            candidate_faces[face] = [mapping.get(vertex, vertex) for vertex in polygons[face]]
        all_affected_vertices.update(shared)
        all_affected_vertices.update(mapping.values())
        patch_rows.append({"patch_root": root, "face_count": len(patch), "face_indices": patch,
                           "bounds_raw_fbx": helpers.bounds([vertices[index] for index in patch_vertices]),
                           "duplicate_vertex_map": {str(key): value for key, value in mapping.items()},
                           "modified_faces": affected})
    after = helpers.topology(candidate_vertices, candidate_faces)
    original_boundary = helpers.edge_coordinate_multiset(vertices, before["boundary_edges"])
    candidate_boundary = helpers.edge_coordinate_multiset(candidate_vertices, after["boundary_edges"])
    added_boundary = candidate_boundary - original_boundary
    expected_added = helpers.edge_coordinate_multiset(vertices, [edge for edge, faces in bad])
    corners_equal = all([vertices[index] for index in old] == [candidate_vertices[index] for index in new] for old, new in zip(polygons, candidate_faces))
    affected_fans = helpers.vertex_face_fans(candidate_faces, after, sorted(all_affected_vertices))
    residual_bad = sum(len(faces) > 2 for faces in after["edge_faces"].values())
    if not corners_equal or residual_bad or original_boundary - candidate_boundary or added_boundary != expected_added:
        raise ValueError("Simulation changed source surfaces or unaccounted boundary geometry")
    return {"classification": "Four small accessory surface patches terminate at18three-face edges on the same large main sheet; this is2+1 T-junction topology, not Slinger's2+2 seam.",
            "semantic_inference": "Four side-localized patches at the visible saddle strap/buckle locations. Must confirm their exact physical part identities in colored regional closeups before applying.",
            "main_patch": {"root": main_patch, "faces": len(before["patches"][main_patch])},
            "nonmanifold_edges": rows, "accessory_patches": patch_rows,
            "all_manifold_patch_face_counts": sorted(len(patch) for patch in before["patches"].values()),
            "source_boundary_components": before["boundary_components"],
            "simulation": {"vertices_before": len(vertices), "vertices_after": len(candidate_vertices),
                           "vertices_duplicated": len(candidate_vertices) - len(vertices), "vertices_moved": 0,
                           "polygons_before": len(polygons), "polygons_after": len(candidate_faces), "faces_deleted": 0,
                           "surface_corner_positions_and_order_identical": corners_equal,
                           "nonmanifold_edges_before": len(bad), "nonmanifold_edges_after": residual_bad,
                           "boundary_edges_before": len(before["boundary_edges"]), "boundary_edges_after": len(after["boundary_edges"]),
                           "original_boundary_coordinate_multiset_retained": not bool(original_boundary - candidate_boundary),
                           "new_boundary_coordinate_multiset_equals18original_T_junctions": added_boundary == expected_added,
                           "additional_topological_boundary_edges": sum(added_boundary.values()),
                           "affected_vertex_fans": affected_fans,
                           "affected_vertices_with_multiple_face_fans_after": [row["vertex"] for row in affected_fans if row["fan_count"] != 1]},
            "boundary_interpretation": "Detaching the third incident sheet necessarily adds one topological boundary edge per T-junction:137to155. This is not removal of any surface or creation of a spatial slit; all faces stay at exactly the same positions. It is NOT an unchanged boundary-count claim or a watertightness approval.",
            "normal_uv_plan": "Retain face order, all per-corner UVs and raw encoded normals; retain original implicit nonmanifold smoothing-fan boundaries as explicit sharp edges on the surviving2face main-sheet edges. Native Blender vector equality must be measured before export; no threshold relaxation.",
            "source_geometry_modified": False, "candidate_applied": False}


def analyze(output):
    source = helpers.require_hash(SOURCE, SOURCE_SHA)
    normalized = helpers.require_hash(NORMALIZED, NORMALIZED_SHA)
    vertices, polygons, uv_layers, version = helpers.read_fbx(SOURCE)
    plan = classify(vertices, polygons)
    if len(plan["nonmanifold_edges"]) != 18 or sorted(row["face_count"] for row in plan["accessory_patches"]) != [61, 62, 63, 63]:
        raise ValueError("Unexpected frozen mammoth topology")
    report = {"asset_id": "Mount_Mammoth", "status": "readonly_topology_classification_and_candidate_simulation_not_applied",
              "generated_at": datetime.now(timezone.utc).isoformat(), "source": source, "normalized_blend": normalized,
              "normalization_report": helpers.file_record(NORMALIZATION), "script": helpers.file_record(Path(__file__)),
              "helper": helpers.file_record(Path(helpers.__file__)), "fbx_version": version,
              "uv_layer_loop_counts": {layer["name"]: len(layer["loops"]) for layer in uv_layers}, "plan": plan,
              "blender_started": False, "texture_approved": False, "rig_approved": False, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    helpers.save_json(output / "analysis.json", report)
    summary = {key: value for key, value in plan["simulation"].items() if key != "affected_vertex_fans"}
    print(json.dumps({"status": report["status"], "simulation": summary, "patches": [row["face_count"] for row in plan["accessory_patches"]]}))


def apply(output, analysis_path):
    import bpy
    from mathutils import Vector

    helpers.require_hash(SOURCE, SOURCE_SHA)
    helpers.require_hash(NORMALIZED, NORMALIZED_SHA)
    frozen = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    vertices, polygons, uv_layers, version = helpers.read_fbx(SOURCE)
    current = classify(vertices, polygons)
    if json.loads(json.dumps(current)) != frozen["plan"]:
        raise ValueError("Frozen/source topology classification changed")
    bpy.ops.wm.open_mainfile(filepath=str(NORMALIZED))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(objects) != 1 or objects[0].modifiers:
        raise ValueError("Expected one unmodified frozen normalized mammoth mesh")
    obj = objects[0]
    original = obj.data
    if [list(polygon.vertices) for polygon in original.polygons] != polygons:
        raise ValueError("Native polygon indices differ from the read-only FBX diagnosis")
    normalization = json.loads(NORMALIZATION.read_text(encoding="utf-8-sig"))["normalization"]["matrix_source_world_to_result"]
    expected = [[sum(normalization[row][axis] * point[axis] for axis in range(3)) + normalization[row][3] for row in range(3)] for point in vertices]
    vertex_error = max((obj.matrix_world @ vertex.co - Vector(point)).length for vertex, point in zip(original.vertices, expected))
    if vertex_error > 1e-6:
        raise ValueError("Actual normalized vertex correspondence differs")
    source_positions = [tuple(vertex.co) for vertex in original.vertices]
    positions = list(source_positions)
    candidate_faces = [list(polygon) for polygon in polygons]
    original_for_duplicate = {}
    for patch in current["accessory_patches"]:
        mapping = {int(key): value for key, value in patch["duplicate_vertex_map"].items()}
        for source_vertex, destination_vertex in sorted(mapping.items(), key=lambda item: item[1]):
            if len(positions) != destination_vertex:
                raise ValueError("Nonsequential immutable duplicate-vertex plan")
            positions.append(source_positions[source_vertex])
            original_for_duplicate[destination_vertex] = source_vertex
        for face in patch["modified_faces"]:
            candidate_faces[face] = [mapping.get(vertex, vertex) for vertex in polygons[face]]
    candidate = bpy.data.meshes.new("Mammoth_SeparatedSaddleAccessorySheets")
    candidate.from_pydata(positions, [], candidate_faces)
    candidate.update()
    for material in original.materials:
        candidate.materials.append(material)
    for old, new in zip(original.polygons, candidate.polygons):
        new.material_index = old.material_index
        new.use_smooth = old.use_smooth
    original_uvs = {layer.name: [tuple(loop.uv) for loop in layer.data] for layer in original.uv_layers}
    for name, coordinates in original_uvs.items():
        layer = candidate.uv_layers.new(name=name)
        layer.data.foreach_set("uv", [value for coordinate in coordinates for value in coordinate])
    candidate.uv_layers.active_index = original.uv_layers.active_index
    source_normals = [tuple(value.vector) for value in original.corner_normals]
    candidate.normals_split_custom_set(source_normals)
    source_sharp = {tuple(sorted(edge.vertices)): edge.use_edge_sharp for edge in original.edges}
    junctions = {tuple(row["edge"]) for row in current["nonmanifold_edges"]}
    explicitly_retained_boundaries = []
    for edge in candidate.edges:
        source_edge = tuple(sorted(original_for_duplicate.get(vertex, vertex) for vertex in edge.vertices))
        edge.use_edge_sharp = source_sharp[source_edge] or source_edge in junctions
        if source_edge in junctions:
            explicitly_retained_boundaries.append(list(edge.vertices))
    encoded_source = original.attributes["custom_normal"]
    properties = [prop.identifier for prop in encoded_source.data[0].bl_rna.properties
                  if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
    if len(properties) != 1:
        raise ValueError("Cannot identify original INT16 normal encoding")
    property_name = properties[0]
    encoded_values = [value for item in encoded_source.data for value in getattr(item, property_name)]
    candidate.attributes["custom_normal"].data.foreach_set(property_name, encoded_values)
    candidate.update()
    normal_errors = [(Vector(before) - corner.vector).length for before, corner in zip(source_normals, candidate.corner_normals)]
    uv_error = max((Vector(before) - candidate.uv_layers[name].data[index].uv).length for name, values in original_uvs.items() for index, before in enumerate(values))
    before_graph = helpers.topology(source_positions, polygons)
    after_graph = helpers.topology(positions, candidate_faces)
    before_boundary = helpers.edge_coordinate_multiset(source_positions, before_graph["boundary_edges"])
    after_boundary = helpers.edge_coordinate_multiset(positions, after_graph["boundary_edges"])
    expected_additions = helpers.edge_coordinate_multiset(source_positions, list(junctions))
    changed_originals = sorted(set(original_for_duplicate.values()))
    affected_fans = helpers.vertex_face_fans(candidate_faces, after_graph, changed_originals + sorted(original_for_duplicate))
    checks = {"all_surface_corner_positions_identical": all([source_positions[index] for index in old] == [positions[index] for index in new] for old, new in zip(polygons, candidate_faces)),
              "all_faces_retained": len(candidate.polygons) == len(original.polygons),
              "original_boundary_coordinates_retained": not bool(before_boundary - after_boundary),
              "added_boundaries_exactly_original18T_junctions": after_boundary - before_boundary == expected_additions,
              "nonmanifold_index_edges_zero": not any(len(faces) > 2 for faces in after_graph["edge_faces"].values()),
              "all_affected_vertices_single_face_fan": all(row["fan_count"] == 1 for row in affected_fans),
              "UV_maximum_error_zero": uv_error == 0,
              "native_corner_normal_vector_maximum_error_zero": max(normal_errors) == 0}
    output.mkdir(parents=True, exist_ok=False)
    result = {"asset_id": "Mount_Mammoth", "status": "strict_native_candidate_checks_passed_pending_region_render" if all(checks.values()) else "strict_native_candidate_checks_failed_no_export",
              "script": helpers.file_record(Path(__file__)), "source": helpers.require_hash(SOURCE, SOURCE_SHA),
              "normalized_blend": helpers.require_hash(NORMALIZED, NORMALIZED_SHA), "analysis": helpers.file_record(analysis_path),
              "checks": checks, "raw_to_normalized_vertex_error_m": vertex_error, "maximum_loop_UV_error": uv_error,
              "maximum_native_corner_normal_vector_error": max(normal_errors), "changed_normal_loops": sum(error != 0 for error in normal_errors),
              "largest_normal_errors": sorted([{"loop": index, "error": error} for index, error in enumerate(normal_errors)], key=lambda item: item["error"], reverse=True)[:12],
              "explicitly_retained_old_implicit_smoothing_boundaries": explicitly_retained_boundaries,
              "vertices_before": len(original.vertices), "vertices_after": len(candidate.vertices),
              "polygons": len(candidate.polygons), "boundary_edges_before": len(before_graph["boundary_edges"]),
              "boundary_edges_after": len(after_graph["boundary_edges"]), "affected_face_fans": affected_fans,
              "semantic_region_approved": False, "texture_approved": False, "rig_approved": False, "production_approved": False}
    helpers.save_json(output / "cleanup_report.json", result)
    if not all(checks.values()):
        raise ValueError("Strict native surface/UV/normal gate failed; no render or model export")
    module_spec = importlib.util.spec_from_file_location("mammoth_cleanup_prep", ROOT / "Tools/Blender/prepare_tripo_character.py")
    prep = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(prep)
    for scene_obj in list(bpy.context.scene.objects):
        if scene_obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(scene_obj, do_unlink=True)
    prep.render_setup(samples=8)
    diagnostic = original.copy()
    diagnostic.name = "Mammoth_DiagnosticRegionColors_NotDelivery"
    colors = [(.9, .12, .08, 1), (.06, .55, .82, 1), (.95, .5, .05, 1), (.16, .68, .25, 1)]
    regions = []
    for patch, color in zip(current["accessory_patches"], colors):
        material = bpy.data.materials.new("DiagnosticPatch" + str(patch["patch_root"]))
        material.use_nodes = True
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = color
        diagnostic.materials.append(material)
        for face in patch["face_indices"]:
            diagnostic.polygons[face].material_index = len(diagnostic.materials) - 1
        points = [obj.matrix_world @ original.vertices[vertex].co for face in patch["face_indices"] for vertex in polygons[face]]
        lower = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
        upper = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
        regions.append({"patch_root": patch["patch_root"], "faces": patch["face_count"], "color": color,
                        "target": list((lower + upper) * .5), "framing": max(.32, max(upper - lower) * 2.4)})
    images = []
    obj.data = diagnostic
    for region in regions:
        bpy.context.view_layer.update()
        direction = (.25, 1 if region["target"][1] > 0 else -1, .15)
        path = output / ("region_" + str(region["patch_root"]) + ".png")
        prep.render_view(path, objects, direction, size=512, target=region["target"], framing=region["framing"])
        images.append(helpers.file_record(path))
    for side, sign in (("negative", -1), ("positive", 1)):
        for stage, mesh in (("before", original), ("after", candidate)):
            obj.data = mesh
            bpy.context.view_layer.update()
            bpy.context.scene.cycles.seed = 0
            path = output / ("side_" + side + "_" + stage + ".png")
            prep.render_view(path, objects, (.2, sign, .12), size=512, target=(-.12, sign * .54, 1.10), framing=.95)
            images.append(helpers.file_record(path))
    obj.data = candidate
    bpy.context.view_layer.update()
    prep.select(objects)
    model = output / "Mount_Mammoth_cleanup.glb"
    bpy.ops.export_scene.gltf(filepath=str(model), export_format="GLB", use_selection=True, export_yup=True,
                              export_animations=False, export_skins=False, export_morph=False, export_materials="EXPORT")
    roundtrip = prep.verify_glb(model, objects)
    blend = output / "Mount_Mammoth_cleanup.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    result.update({"status": "candidate_and_eight_views_saved_pending_actual_region_and_visual_review", "images": images,
                   "regions": regions, "model": helpers.file_record(model), "blend": helpers.file_record(blend),
                   "roundtrip": roundtrip, "mesh_statistics": prep.mesh_stats(objects),
                   "diagnostic_colors_in_delivery": False})
    helpers.save_json(output / "cleanup_report.json", result)
    print(json.dumps({"status": result["status"], "images": len(images), "normal_error": max(normal_errors),
                      "UV_error": uv_error, "boundaries": [len(before_graph["boundary_edges"]), len(after_graph["boundary_edges"])], "roundtrip": roundtrip}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("analyze", "apply"), default="analyze")
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a fresh directory")
    if args.mode == "analyze":
        analyze(output)
    elif args.analysis:
        apply(output, args.analysis.resolve())
    else:
        raise ValueError("Apply requires the frozen analysis")


if __name__ == "__main__":
    main()
