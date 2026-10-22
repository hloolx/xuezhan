"""Local, source-preserving trials for canonical Tripo pine and grass geometry."""
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/geometry_v03_canonical_others/cleanup"
SOURCES = {
    "Env_Pine": ("Env_Pine/h39cff37208d3/Env_Pine.glb", "7e184939a8e287ef57509b8430b95161f3624de5f7a8fa8a18bbe3a69d6a74fb"),
    "Env_GrassClump": ("Env_GrassClump/hf3fd4140a8cb/Env_GrassClump.glb", None),
}
module_spec = importlib.util.spec_from_file_location("environment_prep", ROOT / "Tools/Blender/prepare_tripo_environment.py")
prep = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(prep)


def load(asset_id):
    source = OUTPUT.parent / SOURCES[asset_id][0]
    manifest = json.loads((OUTPUT.parent / "geometry_review.json").read_text(encoding="utf-8"))
    record = next(item for item in manifest["assets"] if item["id"] == asset_id)
    expected = next(item["sha256"] for item in record["artifacts"] if item["file"] == prep.project_path(source))
    if prep.sha256(source) != expected:
        raise ValueError("Normalized Tripo source changed after four-side review")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    prep.select(objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj = prep.join_static(objects, asset_id)
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = 2
    return obj, source, record


def graph(mesh):
    groups = defaultdict(list)
    for vertex in mesh.vertices:
        groups[tuple(round(value, 6) for value in vertex.co)].append(vertex.index)
    positions = [Vector(key) for key in groups]
    members = list(groups.values())
    vertex_group = {vertex: group_id for group_id, items in enumerate(members) for vertex in items}
    adjacency = [set() for point in positions]
    for edge in mesh.edges:
        first, second = [vertex_group[vertex] for vertex in edge.vertices]
        if first != second:
            adjacency[first].add(second)
            adjacency[second].add(first)
    return positions, members, vertex_group, adjacency


def connected(positions, adjacency, cutoff):
    unseen = {index for index, point in enumerate(positions) if point.z > cutoff}
    components = []
    while unseen:
        first = unseen.pop()
        component = {first}
        stack = [first]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return sorted(components, key=len, reverse=True)


def component_record(positions, component):
    low = [min(positions[index][axis] for index in component) for axis in range(3)]
    high = [max(positions[index][axis] for index in component) for axis in range(3)]
    centroid = sum((positions[index] for index in component), Vector()) / len(component)
    top = max(component, key=lambda index: positions[index].z)
    return {"vertices": len(component), "bounds_m": [low, high], "centroid_m": list(centroid), "tip_m": list(positions[top]), "group_ids": sorted(component)}


def diagnose(asset_id):
    obj, source, record = load(asset_id)
    positions, members, vertex_group, adjacency = graph(obj.data)
    cutoffs = [0.02, 0.04, 0.06, 0.08, 0.1, 0.12, 0.14, 0.18, 0.22, 0.25, 0.27, 0.3] if asset_id == "Env_GrassClump" else [0, 1.3, 2, 3.1, 4.5]
    report = {
        "asset_id": asset_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": prep.project_path(source),
        "source_sha256": prep.sha256(source),
        "task_id": record["task_id"],
        "mesh_modified": False,
        "position_grouping_precision_m": 0.000001,
        "source_vertices": len(obj.data.vertices),
        "position_groups": len(positions),
        "negative_y_tip_m": list(min(positions, key=lambda point: point.y)),
        "geometry": prep.geometry_report([obj]),
        "components_above_height": {
            str(cutoff): [component_record(positions, component) for component in connected(positions, adjacency, cutoff)]
            for cutoff in cutoffs
        },
    }
    prep.write_json(OUTPUT / asset_id / "diagnostic.json", report)
    print(json.dumps({"asset_id": asset_id, "component_summary": {cutoff: [{key: value for key, value in component.items() if key != "group_ids"} for component in rows] for cutoff, rows in report["components_above_height"].items()}}, ensure_ascii=False))


def grass_regions(positions, adjacency):
    specifications = [
        ("short_front_leaf", 0.12, Vector((0.052484, -0.101299, 0.171084)), 0.08),
        ("large_left_leaf", 0.22, Vector((0.001745, -0.191176, 0.337815)), 0.14),
    ]
    regions = {}
    for name, cutoff, tip, feather_bottom in specifications:
        candidates = connected(positions, adjacency, cutoff)
        region = min(candidates, key=lambda component: min((positions[index] - tip).length for index in component))
        initial = set(region)
        direction = Vector((tip.x, tip.y, 0)).normalized()
        stack = list(region)
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                point = positions[neighbor]
                horizontal = Vector((point.x, point.y, 0))
                aligned = horizontal.length > 0.025 and horizontal.normalized().dot(direction) > 0.85
                claimed = any(neighbor in previous["groups"] for previous in regions.values())
                lateral_limit = name != "large_left_leaf" or point.x < 0.03
                if neighbor not in region and not claimed and feather_bottom < point.z <= cutoff and aligned and lateral_limit:
                    region.add(neighbor)
                    stack.append(neighbor)
        regions[name] = {"groups": region, "seed_groups": initial, "feather_bottom": feather_bottom, "full_effect_height": cutoff + 0.015}
    if regions["short_front_leaf"]["groups"] & regions["large_left_leaf"]["groups"]:
        raise ValueError("Grass leaf regions overlap")
    return regions


def pine_regions(positions):
    crown = {index for index, point in enumerate(positions)
             if 1.35 < point.z < 6.45 and (math.hypot(point.x, point.y) > 0.75 or point.z > 4.85)}
    return {"crown_relaxation": {"groups": crown}}


def material(name, color):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    result.diffuse_color = (*color, 1)
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = 0.8
    shader.inputs["Metallic"].default_value = 0
    return result


def assign_regions(obj, regions, vertex_group):
    colors = [(0.18, 0.28, 0.38), (0.12, 0.68, 0.28), (0.85, 0.19, 0.06)]
    obj.data.materials.clear()
    obj.data.materials.append(material("Protected_Tripo_Source", colors[0]))
    for index, name in enumerate(regions):
        obj.data.materials.append(material(name, colors[index + 1]))
    for face in obj.data.polygons:
        face.material_index = 0
        groups = {vertex_group[index] for index in face.vertices}
        for region_index, region in enumerate(regions.values(), 1):
            if len(groups & region["groups"]) >= 2:
                face.material_index = region_index


def controlled_render(obj, directory, device, neutral=True, selected_views=None):
    directory.mkdir(parents=True, exist_ok=True)
    camera, centre, span = prep.setup_render(obj, device)
    scene = bpy.context.scene
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.cycles.samples = 12
    if neutral:
        bpy.context.view_layer.material_override = material("Review_Neutral", (0.4, 0.4, 0.4))
    for view, direction in [("preview", (2, -3, 1.6)), ("front", (1, 0, 0)), ("right", (0, 1, 0)), ("back", (-1, 0, 0)), ("left", (0, -1, 0))]:
        if selected_views and view not in selected_views:
            continue
        camera.location = centre + Vector(direction) * span * 2
        camera.rotation_euler = (centre - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = span * (1.55 if view == "preview" else 1.25)
        scene.render.filepath = str(directory / (view + ".png"))
        bpy.ops.render.render(write_still=True)


def segment(asset_id, args):
    obj, source, record = load(asset_id)
    positions, members, vertex_group, adjacency = graph(obj.data)
    regions = grass_regions(positions, adjacency) if asset_id == "Env_GrassClump" else pine_regions(positions)
    assign_regions(obj, regions, vertex_group)
    directory = OUTPUT / asset_id / ("segmentation_v02" if asset_id == "Env_GrassClump" else "segmentation")
    directory.mkdir(parents=True, exist_ok=True)
    prep.export(obj, directory / asset_id)
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / (asset_id + ".blend")))
    report = {
        "asset_id": asset_id,
        "source": prep.project_path(source),
        "source_sha256": prep.sha256(source),
        "task_id": record["task_id"],
        "geometry_modified": False,
        "colors": {"protected_source": "blue-grey", **{name: color for name, color in zip(regions, ["green", "orange"])}},
        "regions": {name: {**component_record(positions, region["groups"]), **{key: value for key, value in region.items() if key not in {"groups", "seed_groups"}}} for name, region in regions.items()},
        "production_approved": False,
    }
    prep.write_json(directory / "segmentation.json", report)
    if args.render:
        controlled_render(obj, directory, args.device, neutral=False, selected_views=args.views)


def preserved_signature(mesh, indices):
    return hashlib.sha256(json.dumps([(index, list(mesh.vertices[index].co)) for index in sorted(indices)], separators=(",", ":")).encode()).hexdigest()


def grass_deformation(positions, regions, strength):
    result = [point.copy() for point in positions]
    diagnostics = []
    for name, region in regions.items():
        group_ids = sorted(region["groups"])
        coordinates = np.array([tuple(positions[index]) for index in group_ids], dtype=np.float64)
        centroid = coordinates.mean(axis=0)
        eigenvalues, basis = np.linalg.eigh(np.cov((coordinates - centroid).T))
        longitudinal = basis[:, 2]
        normal = basis[:, 0]
        parameters = (coordinates - centroid) @ longitudinal
        depths = (coordinates - centroid) @ normal
        design = np.column_stack([np.ones(len(parameters)), parameters, parameters ** 2])
        coefficients = np.linalg.lstsq(design, depths, rcond=None)[0]
        residuals = depths - design @ coefficients
        for offset, group_id in enumerate(group_ids):
            point = positions[group_id]
            fade = min(1.0, max(0.0, (point.z - region["feather_bottom"]) / (region["full_effect_height"] - region["feather_bottom"])))
            fade = fade * fade * (3 - 2 * fade)
            amount = max(-0.03, min(0.03, residuals[offset] * strength * fade))
            result[group_id] = point - Vector(normal.tolist()) * amount
        diagnostics.append({"name": name, "groups": len(group_ids), "pca_eigenvalues": eigenvalues.tolist(), "normal": normal.tolist(), "longitudinal_axis": longitudinal.tolist(), "depth_rms_before_m": float(np.sqrt(np.mean(residuals ** 2))), "strength": strength, "max_displacement_limit_m": 0.03})
    return result, diagnostics


def pine_deformation(positions, adjacency, regions, strength):
    result = [point.copy() for point in positions]
    affected = regions["crown_relaxation"]["groups"]
    maximum = 0.045 if strength < 0.5 else 0.075
    for iteration in range(4):
        previous = [point.copy() for point in result]
        for index in affected:
            if not adjacency[index]:
                continue
            centre = sum((previous[neighbor] for neighbor in adjacency[index]), Vector()) / len(adjacency[index])
            proposal = previous[index].lerp(centre, strength)
            delta = proposal - positions[index]
            if delta.length > maximum:
                delta = delta.normalized() * maximum
            result[index] = positions[index] + delta
    return result, [{"iterations": 4, "strength": strength, "max_displacement_limit_m": maximum, "protected_policy": "z<=1.35m, radial<=0.75m below4.85m, and z>=6.45m are unchanged; no remesh or topology replacement"}]


def trial(asset_id, strength, args):
    obj, source, record = load(asset_id)
    positions, members, vertex_group, adjacency = graph(obj.data)
    regions = grass_regions(positions, adjacency) if asset_id == "Env_GrassClump" else pine_regions(positions)
    affected = set().union(*(region["groups"] for region in regions.values()))
    protected = {vertex for group_id, group in enumerate(members) if group_id not in affected for vertex in group}
    protected_before = preserved_signature(obj.data, protected)
    uv_before = prep.uv_signature([obj])
    source_geometry = prep.geometry_report([obj])
    original_face_normals = [face.normal.copy() for face in obj.data.polygons]
    if asset_id == "Env_GrassClump":
        moved, details = grass_deformation(positions, regions, strength)
        name = "uncurl_" + str(round(strength * 100))
    else:
        moved, details = pine_deformation(positions, adjacency, regions, strength)
        name = "relax_" + str(round(strength * 100))
    changes = []
    for group_id in affected:
        delta = moved[group_id] - positions[group_id]
        if delta.length < 0.0000001:
            continue
        for vertex in members[group_id]:
            obj.data.vertices[vertex].co += delta
        changes.append({"group_id": group_id, "vertex_ids": members[group_id], "displacement_m": list(delta)})
    obj.data.update()
    obj.data.normals_split_custom_set([(0, 0, 0)] * len(obj.data.loops))
    flipped_faces = [face.index for face, normal in zip(obj.data.polygons, original_face_normals) if face.normal.dot(normal) < 0]
    protected_after = preserved_signature(obj.data, protected)
    uv_after = prep.uv_signature([obj])
    if protected_before != protected_after or uv_before["sha256"] != uv_after["sha256"]:
        raise ValueError("Protected source vertices or source UVs changed")
    directory = OUTPUT / asset_id / name
    directory.mkdir(parents=True, exist_ok=True)
    prep.export(obj, directory / asset_id)
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / (asset_id + ".blend")))
    low, high = prep.bounds([obj])
    report = {
        "asset_id": asset_id, "trial": name, "source": prep.project_path(source), "source_sha256": prep.sha256(source),
        "source_task_id": record["task_id"], "geometry_source": "original_Tripo_surface_positions_locally_adjusted",
        "source_geometry": source_geometry, "processed_geometry": prep.geometry_report([obj]),
        "dimensions_cm": [value * 100 for value in high - low], "minimum_z_cm": low.z * 100,
        "protected_vertex_count": len(protected), "protected_before_sha256": protected_before, "protected_after_sha256": protected_after,
        "protected_positions_unchanged": protected_before == protected_after, "uv_unchanged": uv_before["sha256"] == uv_after["sha256"],
        "topology_changed": False, "uv_reunwrap_required": False, "textures_exist": False,
        "face_normal_flips_relative_to_source": flipped_faces,
        "normal_policy": "reset custom normals to geometry-derived normals after local deformation",
        "deformation": details, "changes": changes, "production_approved": False, "texture_pilot_ready": False,
        "limitations": ["Visual review pending; local deformation does not certify watertight topology or runtime readiness", "Original surface topology/UVs are retained; no legacy texture is assumed valid because this source is untextured"],
    }
    prep.write_json(directory / "trial.json", report)
    if args.render:
        controlled_render(obj, directory, args.device, selected_views=args.views)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=SOURCES, required=True)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--segment", action="store_true")
    parser.add_argument("--trials", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--device", choices=("CPU", "HIP"), default="CPU")
    parser.add_argument("--views", nargs="+", choices=("preview", "front", "right", "back", "left"), default=["preview", "front", "left"])
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.diagnose:
        diagnose(args.asset)
    if args.segment:
        segment(args.asset, args)
    if args.trials:
        for strength in ([0.55, 0.8] if args.asset == "Env_GrassClump" else [0.25, 0.5]):
            trial(args.asset, strength, args)


if __name__ == "__main__":
    main()
