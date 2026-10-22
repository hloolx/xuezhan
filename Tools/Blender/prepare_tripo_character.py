"""Inspect and normalize real Tripo character geometry without reshaping it.

Blender --background --factory-startup --python this.py -- --mode inspect
First inspect the four axis renders; prepare requires a visually verified front
axis. Blender uses meters, +Z up; prepared geometry faces +X and stands on Z=0.
No remeshing, joining, decimation, rigging, skinning or animation is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
DEFAULT_SOURCE = ART / "tripo_raw/Unit_StoneAxe/v01/model.fbx"
DEFAULT_OUTPUT = ART / "tripo_processed/characters_geometry_v01/Unit_StoneAxe"
AXES = {"+X": Vector((1, 0, 0)), "-X": Vector((-1, 0, 0)),
        "+Y": Vector((0, 1, 0)), "-Y": Vector((0, -1, 0))}


def parse_options(arguments):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["inspect", "prepare"], default="inspect")
    parser.add_argument("--asset-id", default="Unit_StoneAxe")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-front-axis", choices=list(AXES))
    parser.add_argument("--orientation-evidence", help="Human/agent visual finding based on axis renders")
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--height-evidence", help="Explicit game-code or approved design evidence for this asset height")
    parser.add_argument("--render-size", type=int, choices=[256, 384, 512, 768, 1024])
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--render-profile", choices=["legacy", "overview"])
    args = parser.parse_args(arguments)
    if not re.fullmatch(r"(?:Unit|Mount)_[A-Za-z][A-Za-z0-9_]{0,63}", args.asset_id):
        raise ValueError("asset-id must be a safe Unit_ or Mount_ identifier, without paths or punctuation")
    args.is_mount = args.asset_id.startswith("Mount_")
    if args.is_mount and args.height_cm is None:
        raise ValueError("Mount assets require explicit height-cm; do not reuse human150cm default")
    args.height_cm = 150.0 if args.height_cm is None else args.height_cm
    args.render_profile = args.render_profile or ("overview" if args.is_mount else "legacy")
    if args.is_mount and args.render_profile != "overview":
        raise ValueError("Mount assets require overview; biped hand/foot closeups are not applicable")
    if not math.isfinite(args.height_cm) or not 0 < args.height_cm <= 1000:
        raise ValueError("height-cm must be finite and within(0,1000]")
    args.height_evidence = args.height_evidence.strip() if args.height_evidence else None
    if (args.asset_id != "Unit_StoneAxe" or args.height_cm != 150.0) and not args.height_evidence:
        raise ValueError("Nondefault asset or height requires explicit height-evidence")
    if not 1 <= args.samples <= 32:
        raise ValueError("samples must remain within1..32 for bounded resource use")
    if args.mode == "prepare" and (not args.source_front_axis or not (args.orientation_evidence or "").strip()):
        raise ValueError("Inspect axis renders first; prepare requires source-front-axis and orientation-evidence")
    default_source = DEFAULT_SOURCE if args.asset_id == "Unit_StoneAxe" else ART / "tripo_raw" / args.asset_id / "v01/model.fbx"
    default_category = "mounts_geometry_v01" if args.is_mount else "characters_geometry_v01"
    default_output = DEFAULT_OUTPUT if args.asset_id == "Unit_StoneAxe" else ART / "tripo_processed" / default_category / args.asset_id
    args.source = (args.source or default_source).resolve()
    args.output = (args.output or default_output).resolve()
    args.render_size = args.render_size or (512 if args.mode == "inspect" else 1024)
    return args


def validate_io(args):
    if not args.source.is_file():
        raise FileNotFoundError(args.source)
    if args.source.suffix.lower() not in {".fbx", ".glb", ".gltf"}:
        raise ValueError("Supported source formats: FBX or glTF/GLB")
    if args.output.exists():
        raise FileExistsError("Use a new output directory; never overwrite prior model or review evidence")
    return json.loads((args.source.parent / "task.json").read_text(encoding="utf-8-sig"))


def height_contract(args):
    result = {"asset_id": args.asset_id, "height_cm": args.height_cm, "evidence": args.height_evidence}
    if not args.height_evidence:
        result.update({"source_code": "Source/CivWar/View/CWModels.cpp:335,603",
                       "formula": "Rig.Height = 150.f * Scale; Unit_StoneAxe BuildHuman(..., 1.0f)",
                       "evidence": "Existing StoneAxe game visual contract:150cm at BuildHuman scale1.0"})
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bounds(objects):
    vertices = [o.matrix_world @ v.co for o in objects for v in o.data.vertices]
    minimum = Vector(tuple(min(v[i] for v in vertices) for i in range(3)))
    maximum = Vector(tuple(max(v[i] for v in vertices) for i in range(3)))
    return minimum, maximum


def vector(v):
    return [round(float(x), 8) for x in v]


def positional_topology(obj, tolerance=1e-6):
    """Diagnose UV/normal-split GLB topology without modifying a vertex."""
    canonical, vertex_map = {}, []
    for vertex in obj.data.vertices:
        position = obj.matrix_world @ vertex.co
        key = tuple(round(value / tolerance) for value in position)
        if key not in canonical:
            canonical[key] = len(canonical)
        vertex_map.append(canonical[key])
    parent = list(range(len(canonical)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    edge_faces = Counter()
    for polygon in obj.data.polygons:
        indices = [vertex_map[index] for index in polygon.vertices]
        for index in range(len(indices)):
            a, b = indices[index], indices[(index + 1) % len(indices)]
            if a != b:
                parent[find(b)] = find(a)
                edge_faces[tuple(sorted((a, b)))] += 1
    return {"method": "Read-only positional quantization; no actual welding/export changes. GLB UV/normal seams can split source indices.",
            "quantization_m": tolerance, "unique_position_bins": len(canonical),
            "connected_components": len({find(index) for index in range(len(parent))}),
            "boundary_edges": sum(count == 1 for count in edge_faces.values()),
            "edges_with_more_than_two_faces": sum(count > 2 for count in edge_faces.values())}


def mesh_stats(objects):
    rows = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        parent = list(range(len(mesh.vertices)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for edge in mesh.edges:
            a, b = (find(i) for i in edge.vertices)
            parent[b] = a
        components = Counter(find(i) for i in range(len(parent)))
        face_counts = Counter(len(p.vertices) for p in mesh.polygons)
        edge_faces = Counter()
        for polygon in mesh.polygons:
            for edge in polygon.edge_keys:
                edge_faces[tuple(sorted(edge))] += 1
        regions = {}
        for vertex in mesh.vertices:
            regions.setdefault(find(vertex.index), []).append(obj.matrix_world @ vertex.co)
        minimum, maximum = bounds([obj])
        rows.append({"name": obj.name, "vertices": len(mesh.vertices), "edges": len(mesh.edges),
                     "polygons": len(mesh.polygons), "triangles": face_counts[3], "quads": face_counts[4],
                     "ngons": sum(n for sides, n in face_counts.items() if sides > 4),
                     "evaluated_triangles": len(mesh.loop_triangles),
                     "connected_components": len(components),
                     "component_vertex_counts_descending": sorted(components.values(), reverse=True),
                     "component_regions": [{"component_root_vertex": root, "vertex_count": len(points),
                                             "world_bounds_min": [min(point[axis] for point in points) for axis in range(3)],
                                             "world_bounds_max": [max(point[axis] for point in points) for axis in range(3)]}
                                            for root, points in sorted(regions.items(), key=lambda item: len(item[1]), reverse=True)],
                     "boundary_edges": sum(n == 1 for n in edge_faces.values()),
                     "edges_with_more_than_two_faces": sum(n > 2 for n in edge_faces.values()),
                     "nonmanifold_edge_locations": [{"vertex_indices": list(edge), "adjacent_faces": count,
                                                      "world_endpoints": [vector(obj.matrix_world @ mesh.vertices[index].co) for index in edge]}
                                                     for edge, count in edge_faces.items() if count > 2],
                     "loose_edges": sum(tuple(sorted(e.vertices)) not in edge_faces for e in mesh.edges),
                     "materials": [m.name if m else None for m in mesh.materials],
                     "uv_layers": [uv.name for uv in mesh.uv_layers],
                     "modifiers": [m.type for m in obj.modifiers],
                     "positional_topology_diagnostic": positional_topology(obj),
                     "world_bounds_min": vector(minimum), "world_bounds_max": vector(maximum)})
    sums = ["vertices", "edges", "polygons", "triangles", "quads", "ngons", "evaluated_triangles",
            "connected_components", "boundary_edges", "edges_with_more_than_two_faces", "loose_edges"]
    return {"objects": rows, "totals": {key: sum(r[key] for r in rows) for key in sums},
            "component_method": "Mesh-edge connectivity per imported object, no welding across disconnected vertices/objects."}


def surface_audit(objects):
    rows = []
    materials = {}
    for obj in objects:
        mesh = obj.data
        normals = [corner.vector for corner in mesh.corner_normals]
        rows.append({"object": obj.name,
                     "nonfinite_vertex_positions": sum(not all(math.isfinite(value) for value in vertex.co) for vertex in mesh.vertices),
                     "zero_area_polygon_count": sum(polygon.area <= 1e-12 for polygon in mesh.polygons),
                     "custom_split_normals": mesh.has_custom_normals,
                     "corner_normals_count": len(normals),
                     "nonfinite_corner_normals": sum(not all(math.isfinite(value) for value in normal) for normal in normals),
                     "zero_length_corner_normals": sum(normal.length < 1e-8 for normal in normals),
                     "corner_normal_length_range": [min(normal.length for normal in normals), max(normal.length for normal in normals)] if normals else None})
        for material in mesh.materials:
            if material is None or material.name in materials:
                continue
            nodes = material.node_tree.nodes if material.use_nodes and material.node_tree else []
            materials[material.name] = {"use_nodes": material.use_nodes, "diffuse_color": list(material.diffuse_color),
                                        "node_types": [node.bl_idname for node in nodes],
                                        "image_textures": [{"node": node.name, "image": node.image.name if node.image else None,
                                                            "size": list(node.image.size) if node.image else None,
                                                            "colorspace": node.image.colorspace_settings.name if node.image else None,
                                                            "linked_outputs": [output.name for output in node.outputs if output.is_linked]}
                                                           for node in nodes if node.type == "TEX_IMAGE"]}
    return {"method": "Read-only imported FBX mesh and material datablocks, before any normalization or texture changes.",
            "objects": rows, "materials": materials,
            "visual_normal_direction_review_required": True, "finger_separation_and_pouch_shoulder_clearance_approved": False}


def overview_views():
    return [("front", (1, 0, 0)), ("right", (0, 1, 0)), ("back", (-1, 0, 0)),
            ("left", (0, -1, 0)), ("preview", (1, -1.3, .40))]


def select(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def render_setup(samples=24):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    try:
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "HIP"
        preferences.get_devices()
        for device in preferences.devices:
            device.use = device.type == "HIP"
        if any(d.type == "HIP" for d in preferences.devices):
            scene.cycles.device = "GPU"
    except Exception:
        scene.cycles.device = "CPU"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.world.color = (0.36, 0.36, 0.36)
    scene.view_settings.view_transform = "AgX"
    camera_data = bpy.data.cameras.new("InspectionCamera")
    camera = bpy.data.objects.new("InspectionCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    lights = []
    for index, power in enumerate((650, 380, 460)):
        data = bpy.data.lights.new("InspectionLight" + str(index), "AREA")
        data.energy = power
        obj = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(obj)
        lights.append(obj)
    return camera, lights


def render_view(path, objects, direction, size=1024, framing=None, target=None):
    scene = bpy.context.scene
    camera = scene.camera
    minimum, maximum = bounds(objects)
    center = Vector(target) if target is not None else (minimum + maximum) / 2
    extent = max(maximum - minimum)
    direction = Vector(direction).normalized()
    camera.location = center + direction * extent * 4
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.ortho_scale = framing or extent * 1.22
    camera.data.clip_start = extent * 0.001
    camera.data.clip_end = extent * 20
    # Light rig follows the camera so the four axis diagnostics have comparable
    # face illumination. This changes lighting only, never the source mesh.
    right = direction.cross(Vector((0, 0, 1))).normalized()
    for light, offset in zip([o for o in scene.objects if o.type == "LIGHT"],
                             [(2, -2, 3), (1, 2, 1.7), (-2, 1, 2.4)]):
        light.location = center + (direction * offset[0] + right * offset[1] + Vector((0, 0, offset[2]))) * extent
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        light.data.shape = "DISK"
        light.data.size = extent * 2
        light.data.energy = (650 if offset[0] == 2 else 380) * extent * extent
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def section_clearances(objects, height):
    """Front-silhouette gaps at explicit horizontal planes, not rig approval.

    Intersect triangulated surfaces with Z planes; project intersection segments
    onto lateral Y, union intervals, then report empty gaps. This detects fused
    silhouettes but does not label anatomy or validate deformation/collisions.
    """
    triangles = []
    for obj in objects:
        obj.data.calc_loop_triangles()
        vertices = [obj.matrix_world @ v.co for v in obj.data.vertices]
        triangles.extend([[vertices[i] for i in t.vertices] for t in obj.data.loop_triangles])
    rows = []
    for fraction in (.12, .22, .32, .42, .50, .55, .60, .65, .70, .75):
        z = fraction * height
        intervals = []
        for triangle in triangles:
            hits = []
            for index in range(3):
                a, b = triangle[index], triangle[(index + 1) % 3]
                if (a.z <= z < b.z) or (b.z <= z < a.z):
                    t = (z - a.z) / (b.z - a.z)
                    hits.append(a.y + t * (b.y - a.y))
            if len(hits) == 2:
                intervals.append((min(hits), max(hits)))
        merged = []
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(hi, merged[-1][1])
            else:
                merged.append([lo, hi])
        gaps = [merged[i + 1][0] - merged[i][1] for i in range(len(merged) - 1)]
        rows.append({"height_fraction": fraction, "height_cm": round(z * 100, 4),
                     "lateral_occupied_intervals_cm": [[round(v * 100, 4) for v in interval] for interval in merged],
                     "empty_lateral_gaps_cm": [round(g * 100, 4) for g in gaps]})
    return {"method": "Actual triangle/plane intersections, front projection, lateral Y interval union; empty gaps are measured in cm.",
            "interpretation": "Heuristic static silhouette clearance only. Upper gaps may correspond to arm/torso separation and lower gaps to legs. No semantic joint segmentation, skin weights, socket fit or attack animation has been validated.",
            "joint_clearance_approved": False, "sections": rows}


def verify_glb(path, objects):
    """Round-trip GLB and compare dimensions and surface vertex positions."""
    original_scene = bpy.context.scene
    reference = [obj.matrix_world @ obj.data.vertices[index].co for obj in objects
                 for index in sorted({index for polygon in obj.data.polygons for index in polygon.vertices})]
    temporary = bpy.data.scenes.new("GLBRoundTripVerification")
    bpy.context.window.scene = temporary
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
        meshes = [obj for obj in temporary.objects if obj.type == "MESH"]
        actual = [obj.matrix_world @ v.co for obj in meshes for v in obj.data.vertices]

        def furthest_nearest(points, target):
            tree = KDTree(len(target))
            for index, point in enumerate(target):
                tree.insert(point, index)
            tree.balance()
            return max(tree.find(point)[2] for point in points)

        distance = max(furthest_nearest(reference, actual), furthest_nearest(actual, reference))
        minimum, maximum = bounds(meshes)
        count = sum(len(obj.data.polygons) for obj in meshes)
        expected = sum(len(obj.data.loop_triangles) for obj in objects)
        if distance > 1e-5 or count != expected:
            raise ValueError(f"GLB round-trip shape mismatch: distance={distance}, triangles={count}/{expected}")
        return {"status": "passed", "actual_imported_triangles": count,
                "maximum_bidirectional_nearest_vertex_error_m": distance,
                "imported_bounds_cm": {"minimum": vector(minimum * 100), "maximum": vector(maximum * 100)},
                "note": "Surface vertices compared in both directions after glTF reimport. UV/normal splits may duplicate vertices; isolated source vertices do not represent surface geometry."}
    finally:
        bpy.context.window.scene = original_scene
        for obj in list(temporary.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(temporary)


def main():
    args = parse_options(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    source_task = validate_io(args)
    args.output.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    if args.source.suffix.lower() == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(args.source), use_anim=False)
    elif args.source.suffix.lower() in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(args.source))
    else:
        raise ValueError("Supported source formats: FBX or glTF/GLB")
    bpy.context.view_layer.update()
    objects = [obj for obj in scene.objects if obj.type == "MESH"]
    if not objects or any(o.modifiers for o in objects):
        raise ValueError("Missing mesh or unexpected modifiers; refuse shape-changing preparation")
    source_stats = mesh_stats(objects)
    minimum, maximum = bounds(objects)
    source_bounds = {"minimum": vector(minimum), "maximum": vector(maximum), "dimensions": vector(maximum - minimum)}
    report = {"schema_version": 1, "asset_id": args.asset_id, "generated_at": datetime.now(timezone.utc).isoformat(),
              "mode": args.mode, "blender_version": bpy.app.version_string,
              "source": rel(args.source), "source_sha256": sha(args.source), "source_bytes": args.source.stat().st_size,
              "source_bounds_blender_meters": source_bounds, "source_mesh_statistics": source_stats,
              "source_surface_audit": surface_audit(objects),
              "source_task": source_task, "source_task_sha256": sha(args.source.parent / "task.json"),
              "height_contract": height_contract(args), "render_settings": {"size": args.render_size, "samples": args.samples, "profile": args.render_profile},
              "production_approved": False, "rig_approved": False, "animation_approved": False}
    render_setup(samples=args.samples)
    if args.mode == "inspect":
        for axis, direction in AXES.items():
            render_view(args.output / ("inspect_from_" + axis.replace("+", "pos").replace("-", "neg") + ".png"), objects, direction, size=args.render_size)
        if args.render_profile == "overview":
            render_view(args.output / "inspect_preview.png", objects, (1, -1.3, .40), size=args.render_size)
        report["orientation_status"] = "Await visual inspection of axis renders before normalize/export"
        write(args.output / "source_inspection.json", report)
        print("CHARACTER_INSPECTION " + json.dumps(source_stats["totals"]))
        return
    front = AXES[args.source_front_axis]
    angle = -math.atan2(front.y, front.x)
    rotation = Matrix.Rotation(angle, 4, "Z")
    source_world = [(obj, [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]) for obj in objects]
    rotated = [rotation @ point for _, vertices in source_world for point in vertices]
    low = Vector(tuple(min(v[i] for v in rotated) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in rotated) for i in range(3)))
    factor = (args.height_cm / 100.0) / (high.z - low.z)
    origin = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    transform = Matrix.Scale(factor, 4) @ Matrix.Translation(-origin) @ rotation
    max_error = 0.0
    for obj, original in source_world:
        # Bake only the source world transform, rigid rotation, uniform scale and
        # grounding translation. Vertex count/order and polygon indices persist.
        local_to_result = transform @ obj.matrix_world
        obj.data.transform(local_to_result)
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        for vertex, before in zip(obj.data.vertices, original):
            max_error = max(max_error, (vertex.co - transform @ before).length)
        obj.data.update()
    bpy.context.view_layer.update()
    normalized = mesh_stats(objects)
    if source_stats["totals"] != normalized["totals"]:
        raise ValueError("Topology changed during rigid normalization")
    minimum, maximum = bounds(objects)
    report.update({"orientation": {"source_front_axis": args.source_front_axis, "prepared_front_axis": "+X", "up_axis": "+Z",
                                    "evidence": args.orientation_evidence, "visual_review_required": True},
                   "height_contract": height_contract(args),
                   "normalization": {"uniform_scale": factor, "rotation_z_degrees": math.degrees(angle), "matrix_source_world_to_result": [list(row) for row in transform],
                                     "origin": "bottom center of rotated world-space bounding box, in meters", "maximum_vertex_transform_error_m": max_error,
                                     "allowed_changes": ["rigid Z rotation", "uniform scale", "translation"], "topology_changed": False},
                   "prepared_bounds_cm": {"minimum": vector(minimum * 100), "maximum": vector(maximum * 100), "dimensions": vector((maximum - minimum) * 100)},
                   "prepared_mesh_statistics": normalized,
                   "static_clearance_measurements": {"performed": False, "reason": "Biped silhouette-plane semantics are not applicable to mounts; species-specific anatomy/rig review is required."} if args.is_mount else section_clearances(objects, args.height_cm / 100)})
    select(objects)
    export_path = args.output / (args.asset_id + "_geometry.glb")
    bpy.ops.export_scene.gltf(filepath=str(export_path), export_format="GLB", use_selection=True,
                              export_yup=True, export_apply=False, export_animations=False, export_skins=False,
                              export_morph=False, export_materials="EXPORT")
    report["exports"] = {"rig_check_glb": rel(export_path), "glb_sha256": sha(export_path), "glb_units": "meters",
                         "glb_coordinate_system": "glTF standard +Y-up; Blender +X-front remains +X; Blender +Y-right becomes glTF -Z",
                         "glb_topology_note": "glTF exports triangles; the retained .blend source preserves imported polygon/quad topology."}
    report["export_round_trip_verification"] = verify_glb(export_path, objects)
    body_views = overview_views() if args.render_profile == "overview" else [
        ("front", (1, 0, 0)), ("right", (0, 1, 0)), ("back", (-1, 0, 0)),
        ("preview", (1, -1.3, .40)), ("preview_back", (-1, -1.3, .40))]
    for name, direction in body_views:
        render_view(args.output / (name + ".png"), objects, direction, size=args.render_size)
    height = args.height_cm / 100.0
    detail_views = [] if args.render_profile == "overview" else [
        ("detail_head_back", (-1, 0, 0), (0, 0, height * .89)),
        ("detail_head_front", (1, 0, 0), (0, 0, height * .89)),
        ("detail_hand_right", (1, .65, .15), (0, height * .28, height * .46)),
        ("detail_hand_left", (1, -.65, .15), (0, -height * .28, height * .46)),
        ("detail_hand_right_rear", (-1, .65, .15), (0, height * .28, height * .46)),
        ("detail_hand_left_rear", (-1, -.65, .15), (0, -height * .28, height * .46))]
    for name, direction, target in detail_views:
        render_view(args.output / (name + ".png"), objects, direction, size=args.render_size,
                    framing=height * .32, target=target)
    feet_views = [] if args.render_profile == "overview" else [("detail_feet_front", (1, -.3, .40)), ("detail_feet_back", (-1, -.3, .40))]
    for name, direction in feet_views:
        render_view(args.output / (name + ".png"), objects, direction, size=args.render_size,
                    framing=height * .58, target=(0, 0, height * .12))
    select(objects)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / (args.asset_id + "_geometry.blend")))
    report["status"] = "geometry_prepared_pending_visual_and_rig_check"
    report["next_checks"] = ["Review actual four-side/preview renders for +X facing and ground contact", "Free Tripo rig suitability check", "Species-specific legs/head/appendages and rider-seat clearance", "Separate mount rig, locomotion and rider attachment review"] if args.is_mount else ["Review actual front/right/back renders for +X facing and ground contact", "Free Tripo rig suitability check", "Hands/finger topology and grip fitting", "Rig deformation and weapon/socket/attack animation tests"]
    report["source_preserved"] = sha(args.source) == report["source_sha256"]
    review_path = args.output / "visual_review.json"
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8-sig"))
        if review.get("source_sha256") == report["source_sha256"]:
            report["visual_review"] = review
            report["status"] = review["status"]
    write(args.output / "geometry_report.json", report)
    print("CHARACTER_PREPARED " + json.dumps({"glb": str(export_path), "totals": normalized["totals"], "dimensions_cm": vector((maximum - minimum) * 100)}))


if __name__ == "__main__":
    main()
