"""Split measured Tripo parts for later guns, vehicles and mechs.

An entry uses the existing source/scale/selection/material contract plus a
parent-first parts list [{id,pivot_gltf,parent_part?}]. Every source triangle
must belong to a real part. Only new cut boundaries are capped.

Ordinary Python: --plan plan.json --stage inspect|textures
Leased Blender: --plan plan.json --stage prepare [--render]

For turrets provide actual fire_animation channels and muzzle.part/point_gltf;
the result feeds import_era_mechanism without a second format. A vehicle gets
an actual separated .blend/parts manifest, then its measured joint/drive spec
feeds bake_era_vehicle_actions. Missing source measurements are not invented.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import prepare_era_mechanism as common

static = common.static


def destination(plan, entry):
    identity = {"entry": entry, "source": static.digest(static.absolute(entry["source"])),
                "tool": static.digest(__file__), "split_tool": static.digest(common.__file__)}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return static.absolute(plan["output_root"])/entry["asset_id"]/("h"+key)


def inspect(entry):
    geometry = common.source_geometry(entry)
    geometry = slice_source(geometry, entry.get("slice_planes", []))
    centres = geometry["vertices"][geometry["faces"]].mean(1)
    labels = np.full(len(centres), entry.get("remainder_part", "frame"), dtype=object)
    claimed = np.zeros(len(centres), dtype=bool)
    for selection in entry.get("selections", []):
        mask = np.zeros(len(centres), dtype=bool)
        for region in selection["regions"]:
            mask |= common.inside(centres, region)
        for region in selection.get("exclude_regions", []):
            mask &= ~common.inside(centres, region)
        mask &= ~claimed
        if not mask.any():
            raise ValueError("Empty source partition: "+selection["part"])
        labels[mask] = selection["part"]
        claimed |= mask
    names = [part["id"] for part in entry["parts"]]
    if len(names) != len(set(names)) or set(names) != set(labels):
        raise ValueError("Every source triangle needs exactly one declared real part")
    earlier = set()
    for part in entry["parts"]:
        if part.get("parent_part") and part["parent_part"] not in earlier:
            raise ValueError("Mechanical assembly must be parent-first")
        if len(part["pivot_gltf"]) != 3:
            raise ValueError("Each part requires a measured source pivot")
        earlier.add(part["id"])
    return geometry, labels


def slice_source(geometry, planes):
    """Subdivide at measured hinge planes without removing source surfaces."""
    if not planes:
        return geometry
    original_count = len(geometry["faces"])
    original_area = np.linalg.norm(np.cross(
        geometry["vertices"][geometry["faces"]][:, 1]-geometry["vertices"][geometry["faces"]][:, 0],
        geometry["vertices"][geometry["faces"]][:, 2]-geometry["vertices"][geometry["faces"]][:, 0]), axis=1).sum()/2
    for plane in planes:
        normal, offset = np.asarray(plane[:3], dtype=float), float(plane[3])
        if not np.isfinite(plane).all() or np.linalg.norm(normal) < 1e-8:
            raise ValueError("Invalid measured slicing plane")
        vertices = geometry["vertices"].tolist()
        normals, uvs = geometry["normals"].tolist(), geometry["uvs"].tolist()
        faces, materials, crossings = [], [], {}

        def intersection(a, b):
            key = tuple(sorted((a, b)))
            if key not in crossings:
                pa, pb = np.asarray(vertices[a]), np.asarray(vertices[b])
                amount = (offset-normal@pa)/(normal@(pb-pa))
                if amount <= 1e-9:
                    return a
                if amount >= 1-1e-9:
                    return b
                crossings[key] = len(vertices)
                vertices.append((pa+(pb-pa)*amount).tolist())
                n = np.asarray(normals[a])*(1-amount)+np.asarray(normals[b])*amount
                normals.append((n/max(np.linalg.norm(n), 1e-12)).tolist())
                uvs.append((np.asarray(uvs[a])*(1-amount)+np.asarray(uvs[b])*amount).tolist())
            return crossings[key]

        for face, material in zip(geometry["faces"], geometry["materials"]):
            face = list(map(int, face))
            distances = np.asarray([normal@np.asarray(vertices[i])-offset for i in face])
            if distances.min() >= -1e-10 or distances.max() <= 1e-10:
                faces.append(face)
                materials.append(material)
                continue
            for sign in (1, -1):
                polygon = []
                for a, b in zip(face, face[1:]+face[:1]):
                    da, db = sign*(normal@np.asarray(vertices[a])-offset), sign*(normal@np.asarray(vertices[b])-offset)
                    if da >= 0:
                        polygon.append(a)
                    if (da < 0 < db) or (db < 0 < da):
                        polygon.append(intersection(a, b))
                for i in range(1, len(polygon)-1):
                    faces.append([polygon[0], polygon[i], polygon[i+1]])
                    materials.append(material)
        geometry = {**geometry, "vertices": np.asarray(vertices), "normals": np.asarray(normals),
                    "uvs": np.asarray(uvs), "faces": np.asarray(faces), "materials": np.asarray(materials)}
    triangles = geometry["vertices"][geometry["faces"]]
    area = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1).sum()/2
    if abs(area-original_area) > max(1e-10, original_area*1e-8):
        raise ValueError("Hinge slicing changed the original source surface area")
    geometry["subdivision"] = {"original_source_triangles": original_count,
                               "subdivided_source_triangles": len(triangles),
                               "slice_planes_gltf": planes,
                               "source_surface_area_error": float(abs(area-original_area)),
                               "corner_attributes": "Interpolated original source UVs and normals"}
    return geometry


def create_part(bpy, name, selected, geometry, basis, pivot, materials):
    from mathutils import Vector
    from mathutils.geometry import tessellate_polygon
    vertices = common.normalized_point(geometry["vertices"], basis)
    normals = geometry["normals"] @ basis[0].T
    used, remap = np.unique(geometry["faces"][selected], return_inverse=True)
    points = (vertices[used]-pivot).tolist()
    faces = remap.reshape(-1, 3).tolist()
    cap_uvs = []
    for loop in common.cut_boundary_loops(geometry, selected):
        ring = vertices[loop]-pivot
        start = len(points)
        points.extend(ring.tolist())
        uv = geometry["uvs"][loop].mean(0).tolist()
        vectors = [Vector(point.tolist()) for point in ring]
        indices = {tuple(point): i for i, point in enumerate(vectors)}
        for triangle in tessellate_polygon([vectors]):
            faces.append([start+(vertex if isinstance(vertex, int) else indices[tuple(vertex)])
                          for vertex in triangle])
            cap_uvs.append(uv)
    data = bpy.data.meshes.new("Source_"+name)
    data.from_pydata(points, [], faces)
    data.update()
    uv = data.uv_layers.new(name="UVMap")
    for material in materials:
        data.materials.append(material)
    corner_normals = []
    for polygon, face_id in zip(data.polygons, selected):
        polygon.material_index = int(geometry["materials"][face_id])
        polygon.use_smooth = True
        for loop_index, source_index in zip(polygon.loop_indices, geometry["faces"][face_id]):
            u, v = geometry["uvs"][source_index]
            uv.data[loop_index].uv = (u, 1-v)
            corner_normals.append(normals[source_index].tolist())
    for polygon, (u, v) in zip(list(data.polygons)[len(selected):], cap_uvs):
        polygon.material_index = 0
        for loop_index in polygon.loop_indices:
            uv.data[loop_index].uv = (u, 1-v)
            corner_normals.append(list(polygon.normal))
    data.normals_split_custom_set(corner_normals)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = pivot.tolist()
    return obj, len(cap_uvs)


def create_ready_rocket(bpy, recipe, basis, output):
    """Necessary solid missile for a source launcher with genuinely empty tubes."""
    from mathutils import Matrix, Vector
    import math
    radius, length = recipe["radius_cm"]/100, recipe["length_cm"]/100
    if not 0 < radius < length/4:
        raise ValueError("Invalid measured ready missile dimensions")
    nose = length*.34
    pieces = []
    for cone in (False, True):
        if cone:
            bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=radius, radius2=0,
                                            depth=nose, location=((length-nose)/2, 0, 0))
        else:
            bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius,
                                                depth=length-nose, location=(-nose/2, 0, 0))
        obj = bpy.context.object
        obj.rotation_euler = (0, math.pi/2, 0)
        pieces.append(obj)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in pieces:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    bpy.context.view_layer.update()
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    direction = basis[0] @ np.asarray(recipe["axis_gltf"], dtype=float)
    direction /= np.linalg.norm(direction)
    rotation = Vector((1, 0, 0)).rotation_difference(Vector(direction.tolist())).to_matrix().to_4x4()
    obj.data.transform(rotation)
    obj.name = recipe["id"]
    texture = output/"authored_missile_base_color.png"
    common.constant_png(texture, (190, 194, 183))
    material = bpy.data.materials.new("M_AuthoredReadyMissile")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (.515, .539, .474, 1)
    shader.inputs["Roughness"].default_value = .5
    shader.inputs["Metallic"].default_value = .35
    obj.data.materials.clear()
    obj.data.materials.append(material)
    row = {"slot_name": material.name, "source_name": material.name,
           "textures": {"base_color": static.record(texture)}, "double_sided": False,
           "base_color_factor": [1, 1, 1, 1], "roughness_factor": .5, "metallic_factor": .35,
           "normal_scale": 1, "occlusion_strength": 1, "emissive_factor": [0, 0, 0]}
    return obj, row


def create_tread_loop(bpy, recipe, output):
    """Necessary closed links where the generated upper track is fused."""
    from era_vehicle_motion import capsule_frame, capsule_length
    count = len(recipe["bones"])
    args = (recipe["half_straight_cm"]/100, recipe["radius_cm"]/100,
            recipe["lateral_cm"]/100, recipe["centre_height_cm"]/100,
            recipe.get("forward_cm", 0)/100)
    length = capsule_length(args[0], args[1])
    half = np.array([length/count*recipe["link_fraction"],
                     recipe["width_cm"]/100, recipe["thickness_cm"]/100])/2
    corners = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                        [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], dtype=float)*half
    cube_faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    vertices, faces, indices = [], [], []
    for index in range(count):
        matrix = capsule_frame(index*length/count, *args)
        start = len(vertices)
        vertices.extend((corners@matrix[:3, :3].T+matrix[:3, 3]).tolist())
        faces.extend([[start+vertex for vertex in face] for face in cube_faces])
        indices.extend([index]*8)
    data = bpy.data.meshes.new("AuthoredClosedLinks_"+recipe["id"])
    data.from_pydata(vertices, [], faces)
    data.update()
    attribute = data.attributes.new("tread_bone_index", "INT", "POINT")
    for value, index in zip(attribute.data, indices):
        value.value = index
    uv = data.uv_layers.new(name="UVMap")
    for polygon in data.polygons:
        for loop_index, coordinate in zip(polygon.loop_indices, [(0,0),(1,0),(1,1),(0,1)]):
            uv.data[loop_index].uv = coordinate
    material = bpy.data.materials.get("M_AuthoredRubberLinks")
    if material is None:
        material = bpy.data.materials.new("M_AuthoredRubberLinks")
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (.030, .032, .030, 1)
        shader.inputs["Roughness"].default_value = .86
        shader.inputs["Metallic"].default_value = .15
    data.materials.append(material)
    obj = bpy.data.objects.new(recipe["id"], data)
    bpy.context.scene.collection.objects.link(obj)
    texture = output/"authored_rubber_links_base_color.png"
    common.constant_png(texture, (48, 50, 48))
    row = {"slot_name": material.name, "source_name": material.name,
           "textures": {"base_color": static.record(texture)}, "double_sided": False,
           "base_color_factor": [1,1,1,1], "roughness_factor": .86, "metallic_factor": .15,
           "normal_scale": 1, "occlusion_strength": 1, "emissive_factor": [0,0,0]}
    return obj, row


def prepare(plan, entry, render=False):
    import bpy
    from mathutils import Euler, Matrix, Vector
    import math
    geometry, labels = inspect(entry)
    basis = common.normalized_basis(entry, geometry["vertices"])
    output = destination(plan, entry)
    if (output/"parts_manifest.json").exists():
        raise ValueError("Completed part candidates are immutable; use a new revision")
    output.mkdir(parents=True, exist_ok=True)
    textures = static.read(static.folder(entry, plan["output_root"])/"textures.json")
    if textures["source"]["sha256"] != geometry["inspection"]["source"]["sha256"]:
        raise ValueError("Part textures belong to another source")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1.
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    bpy.ops.import_scene.gltf(filepath=str(static.absolute(entry["source"])))
    material_rows, materials = textures["materials"], []
    for row in material_rows:
        material = bpy.data.materials.get(row["source_name"])
        if material is None:
            raise ValueError("Original PBR material absent")
        material.name = row["slot_name"]
        materials.append(material)
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    pivots = {part["id"]: common.normalized_point(part["pivot_gltf"], basis) for part in entry["parts"]}
    meshes, parts, objects = [], [], {}
    for part in entry["parts"]:
        name = part["id"]
        selected = np.flatnonzero(labels == name)
        part_materials, part_rows = materials, material_rows
        if part.get("emission"):
            if len(materials) != 1:
                raise ValueError("An emissive source part needs an explicit single material")
            emission = part["emission"]
            material = materials[0].copy()
            material.name = "M_Emitter_"+name
            shader = material.node_tree.nodes.get("Principled BSDF")
            shader.inputs["Emission Color"].default_value = (*emission["color"], 1)
            shader.inputs["Emission Strength"].default_value = emission["default"]
            part_materials = [material]
            row = deepcopy(material_rows[0])
            row.update(slot_name=material.name, source_name=material.name, dynamic_emissive=emission)
            row.pop("team_cloth", None)
            part_rows = [row]
        obj, caps = create_part(bpy, name, selected, geometry, basis, pivots[name], part_materials)
        objects[name] = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.context.view_layer.update()
        saved = obj.matrix_world.copy()
        obj.matrix_world = Matrix.Identity(4)
        bpy.context.view_layer.update()
        path = output/("SM_"+entry["asset_id"]+"_"+name+".fbx")
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"},
            apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
            use_mesh_modifiers=False, bake_anim=False, path_mode="STRIP", embed_textures=False)
        obj.matrix_world = saved
        points = np.array([vertex.co[:] for vertex in obj.data.vertices])
        low, high = points.min(0), points.max(0)
        obj.data.calc_loop_triangles()
        meshes.append({"id": name, "exports": {"fbx": static.record(path)}, "materials": part_rows,
                       "triangles": len(obj.data.loop_triangles), "source_triangles": len(selected),
                       "authored_cut_cap_triangles": caps,
                       "bounds_cm": {"minimum": [low[0]*100, -high[1]*100, low[2]*100],
                                     "maximum": [high[0]*100, -low[1]*100, high[2]*100]}})
        parent = part.get("parent_part")
        local = pivots[name]-(pivots[parent] if parent else np.zeros(3))
        runtime_part = {"id": name, "mesh_id": name, "translation_cm": common.ue(local)}
        if parent:
            runtime_part["parent_part"] = parent
            obj.parent = objects[parent]
            obj.location = local.tolist()
        parts.append(runtime_part)
    for recipe in entry.get("authored_rockets", []):
        name, parent = recipe["id"], recipe["parent_part"]
        if name in objects or parent not in objects:
            raise ValueError("Ready missile requires a unique id and actual launcher parent")
        obj, material_row = create_ready_rocket(bpy, recipe, basis, output)
        pivot = common.normalized_point(recipe["centre_gltf"], basis)
        objects[name] = obj
        pivots[name] = pivot
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        path = output/("SM_"+entry["asset_id"]+"_"+name+".fbx")
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"},
            apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
            use_mesh_modifiers=False, bake_anim=False, path_mode="STRIP", embed_textures=False)
        vertices = np.array([vertex.co[:] for vertex in obj.data.vertices])
        low, high = vertices.min(0), vertices.max(0)
        obj.data.calc_loop_triangles()
        meshes.append({"id": name, "exports": {"fbx": static.record(path)}, "materials": [material_row],
                       "triangles": len(obj.data.loop_triangles), "source_triangles": 0,
                       "authored_geometry": "Solid ready missile inside measured empty source launch tube",
                       "bounds_cm": {"minimum": [low[0]*100, -high[1]*100, low[2]*100],
                                     "maximum": [high[0]*100, -low[1]*100, high[2]*100]}})
        local = pivot-pivots[parent]
        obj.parent = objects[parent]
        obj.location = local.tolist()
        parts.append({"id": name, "mesh_id": name, "parent_part": parent,
                      "translation_cm": common.ue(local)})
    for recipe in entry.get("authored_treads", []):
        name, parent = recipe["id"], recipe["parent_part"]
        if name in objects or parent not in objects:
            raise ValueError("Closed tread requires a unique part and actual hull")
        obj, row = create_tread_loop(bpy, recipe, output)
        objects[name], pivots[name] = obj, np.zeros(3)
        if row["slot_name"] not in {material["slot_name"] for material in material_rows}:
            material_rows = [*material_rows, row]
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        path = output/("SM_"+entry["asset_id"]+"_"+name+".fbx")
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"},
            apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
            use_mesh_modifiers=False, bake_anim=False, path_mode="STRIP", embed_textures=False)
        vertices = np.asarray([vertex.co[:] for vertex in obj.data.vertices])
        low, high = vertices.min(0), vertices.max(0)
        obj.data.calc_loop_triangles()
        meshes.append({"id": name, "exports": {"fbx": static.record(path)}, "materials": [row],
                       "triangles": len(obj.data.loop_triangles), "source_triangles": 0,
                       "authored_geometry": recipe["reason"], "link_count": len(recipe["bones"]),
                       "bounds_cm": {"minimum": [low[0]*100,-high[1]*100,low[2]*100],
                                     "maximum": [high[0]*100,-low[1]*100,high[2]*100]}})
        obj.parent, obj.location = objects[parent], (-pivots[parent]).tolist()
        parts.append({"id": name, "mesh_id": name, "parent_part": parent,
                      "translation_cm": common.ue(-pivots[parent])})
    bpy.context.view_layer.update()
    blend = output/(entry["asset_id"]+"_measured_parts.blend")
    result = {"asset_id": entry["asset_id"], "status": "measured_parts_pending_motion",
              "source": geometry["inspection"]["source"], "tool": static.record(__file__),
              "meshes": meshes, "parts": parts,
              "materials": material_rows, "pivots_blender_cm": {key: (value*100).tolist() for key, value in pivots.items()},
              "source_triangles_retained": sum(row["source_triangles"] for row in meshes),
              "production_approved": False}
    if "subdivision" in geometry:
        result["surface_subdivision"] = geometry["subdivision"]
    if entry["kind"] == "turret":
        animation = entry["fire_animation"]
        actual = next(row for row in static.read(static.ROOT/"Content/Data/Turrets.json")
                      if row["VisualKey"] == entry["asset_id"])
        if abs(animation["duration"]-actual["AttackInterval"]) > .001 or not animation["channels"]:
            raise ValueError("Actual turret requires authoritative fire timing and visible part channels")
        if any(channel["part"] not in objects for channel in animation["channels"]):
            raise ValueError("Fire channel names an absent actual part")
        # Store the same FireSeq-relative part transforms consumed by runtime.
        # Source parts remain at Ready outside the fire interval.
        scene.render.fps = 60
        scene.frame_start, scene.frame_end = 0, round(animation["duration"]*60)
        for channel in animation["channels"]:
            obj = objects[channel["part"]]
            ready_location, ready_rotation = obj.location.copy(), obj.rotation_euler.to_quaternion()
            previous_time = -1.
            for key in channel["keyframes"]:
                time = float(key["time"])
                if not previous_time < time <= animation["duration"]:
                    raise ValueError("Fire keyframes must be strictly ordered within interval")
                previous_time = time
                delta = key.get("translation_cm", [0, 0, 0])
                pitch, yaw, roll = key.get("rotation_degrees", [0, 0, 0])
                obj.location = ready_location + Vector((delta[0]/100, -delta[1]/100, delta[2]/100))
                obj.rotation_mode = "QUATERNION"
                obj.rotation_quaternion = ready_rotation @ Euler(
                    (math.radians(roll), -math.radians(pitch), -math.radians(yaw)), "XYZ").to_quaternion()
                frame = time*60
                obj.keyframe_insert("location", frame=frame)
                obj.keyframe_insert("rotation_quaternion", frame=frame)
                obj.hide_render = not key.get("visible", True)
                obj.keyframe_insert("hide_render", frame=frame)
                if channel.get("scalar_parameter"):
                    slot = channel["material_slot"]
                    material = obj.data.materials[slot]
                    shader = material.node_tree.nodes.get("Principled BSDF")
                    strength = shader.inputs["Emission Strength"]
                    strength.default_value = key["scalar"]
                    strength.keyframe_insert("default_value", frame=frame)
            # Blender 5 layered actions; match runtime's linear interpolation.
            actions = [obj.animation_data.action]
            for material in obj.data.materials:
                if material.use_nodes and material.node_tree.animation_data:
                    actions.append(material.node_tree.animation_data.action)
            for action in actions:
                for layer in action.layers:
                    for strip in layer.strips:
                        for bag in strip.channelbags:
                            for curve in bag.fcurves:
                                for key in curve.keyframe_points:
                                    key.interpolation = "CONSTANT" if curve.data_path == "hide_render" else "LINEAR"
        scene.frame_set(scene.frame_end)
        muzzle = entry["muzzle"]
        point = common.normalized_point(muzzle["point_gltf"], basis)-pivots[muzzle["part"]]
        result.update(kind="mechanical_turret", status="mechanism_prepared_pending_unreal",
                      muzzle={"part": muzzle["part"], "translation_cm": common.ue(point)}, fire_animation=animation)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    result["blend"] = static.record(blend)
    if entry["kind"] == "turret":
        static.write(output/"mechanism_manifest.json", result)
    static.write(output/"parts_manifest.json", result)
    if render:
        # A joined temporary copy preserves each actual world transform.
        copies = []
        for obj in objects.values():
            copy = obj.copy()
            copy.data = obj.data.copy()
            copy.animation_data_clear()
            copy.parent = None
            copy.matrix_world = obj.matrix_world.copy()
            scene.collection.objects.link(copy)
            copies.append(copy)
            obj.hide_render = True
        bpy.ops.object.select_all(action="DESELECT")
        for obj in copies:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = copies[0]
        bpy.ops.object.join()
        joined = bpy.context.object
        static.render_preview(bpy, joined, output)
        bpy.data.objects.remove(joined, do_unlink=True)
        for obj in objects.values():
            obj.hide_render = False
        if entry["kind"] == "turret":
            fire_time = entry.get("review_fire_time", 0.)
            scene.frame_set(int(fire_time*60), subframe=(fire_time*60) % 1)
            scene.render.filepath = str(output/"preview_fire_back.png")
            bpy.ops.render.render(write_still=True)
    return result, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=("inspect", "textures", "prepare"), required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else None)
    plan = static.read(args.plan)
    results = []
    for entry in plan["entries"]:
        if args.stage == "inspect":
            geometry, labels = inspect(entry)
            result = {"asset_id": entry["asset_id"], "source": geometry["inspection"],
                      "part_triangles": {str(key): int(np.count_nonzero(labels == key)) for key in np.unique(labels)}}
        elif args.stage == "textures":
            result = static.prepare_textures(entry, plan["output_root"], textures_only=True)
        else:
            value, output = prepare(plan, entry, args.render)
            result = {"asset_id": entry["asset_id"], "status": value["status"], "output": str(output)}
        results.append(result)
    static.write(args.plan.with_name(args.plan.stem+"_"+args.stage+".json"), {"results": results})
    print(json.dumps({"stage": args.stage, "entries": len(results)}))


if __name__ == "__main__":
    main()
