from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_tower_contract", Path(__file__).with_name("build_rock_tower.py"))
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)
SOURCE = CONTRACT.OUTPUT_ROOT / "candidate_v02/Turret_RockTower.blend"
ASSEMBLY = CONTRACT.OUTPUT_ROOT / "assembly_v03"
GROUPS = ("Frame", "Arm", "Stone", "Cloth")


def ue_point(point):
    return [point[0] * 100, -point[1] * 100, point[2] * 100]


def ue_pitch_point(point, pitch):
    angle = math.radians(pitch)
    cosine, sine = math.cos(angle), math.sin(angle)
    return (cosine * point[0] - sine * point[2], point[1], sine * point[0] + cosine * point[2])


def material_key(name):
    return re.sub(r"\.\d{3}$", "", name)


def triangle_difference(expected, actual):
    best = None
    for offset in range(3):
        order = tuple((index + offset) % 3 for index in range(3))
        position = max(math.dist(expected["corners"][index]["position"], actual["corners"][order[index]]["position"]) for index in range(3))
        normal = max(math.dist(expected["corners"][index]["normal"], actual["corners"][order[index]]["normal"]) for index in range(3))
        uv = 0.0
        for index in range(3):
            first, second = expected["corners"][index]["uv"], actual["corners"][order[index]]["uv"]
            if len(first) != len(second):
                uv = 1e30
                break
            uv = max(uv, max((math.dist(left, right) for left, right in zip(first, second)), default=0))
        value = (position, uv, normal)
        if best is None or value < best:
            best = value
    return best


def dry_plan():
    upper = CONTRACT.frozen_upper_contract(SOURCE)
    review_path = ASSEMBLY / "visual_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not review.get("root_review", {}).get("dcc_controlled_assembly_approved"):
        raise ValueError("Root DCC assembly approval is required")
    assembly_path = ASSEMBLY / "inspection.json"
    assembly = json.loads(assembly_path.read_text(encoding="utf-8"))
    inspected = next(record for record in review["evidence"] if record["file"] == CONTRACT.file_record(assembly_path)["file"])
    if CONTRACT.file_record(assembly_path)["sha256"] != inspected["sha256"] or not assembly["numeric_pass"]:
        raise ValueError("Approved assembly evidence is absent or changed")
    adapters = []
    for platform in assembly["platforms"]:
        adapter = platform["platform_adapter"]
        model = next(record for record in adapter["exports"]["files"] if record["file"].endswith(".glb"))
        if CONTRACT.file_record(ROOT / model["file"])["sha256"] != model["sha256"]:
            raise ValueError("Frozen adapter bytes changed")
        adapters.append({"id": platform["id"], "source": model, "mount_blender_cm": platform["blender_mount_cm"],
                         "mount_ue_cm": platform["ue_mount_cm_basis_note_only"],
                         "upper_local_translation_cm": adapter["upper_local_translation_cm"],
                         "triangles": adapter["actual_extra_triangles"]})
    return {"schema_version": 1, "asset_id": "Turret_RockTower", "status": "grouped_delivery_plan_not_executed",
            "upper_source": upper, "assembly_review": CONTRACT.file_record(review_path),
            "assembly_inspection": CONTRACT.file_record(assembly_path), "adapters": adapters,
            "rigid_groups": list(GROUPS), "surface_geometry_changes_allowed": False,
            "material_deduplication": "Reuse the same material slots by identity; no atlas, reassignment, bake or palette change.",
            "coordinate_contract": {"blender": "metres, +X forward, +Z up, arm rotates around +Y",
                                    "ue_points_cm": "(100*x, -100*y, 100*z)",
                                    "ue_rotation": "FRotator(Pitch=-blender_y_angle, Yaw=0, Roll=0)",
                                    "arm_pivot_blender_m": CONTRACT.PIVOT, "arm_pivot_ue_cm": ue_point(CONTRACT.PIVOT),
                                    "stone_and_release_arm_local_blender_m": CONTRACT.RELEASE_LOCAL,
                                    "stone_and_release_arm_local_ue_cm": ue_point(CONTRACT.RELEASE_LOCAL),
                                    "ready_ue_pitch": 35, "followthrough_ue_pitch": -40, "reload_ue_pitch": 65,
                                    "both_teams": "Rotate whole assembly yaw 0/180; do not mirror geometry or weapons.",
                                    "ue_source_formula": "G:/epic/UE_5.8/Engine/Source/Runtime/Core/Public/Math/RotationTranslationMatrix.h:75"},
            "time_contract": {"FireSeq": "already released; never interpret as windup start", "cycle_seconds": 2.4,
                              "release_seconds": 0, "stone_visible_again_seconds": 1.2, "ready_again_seconds": 2.1,
                              "damage_from_animation": False, "authority_changed": False},
            "ue_import_plan": {"status": "dry_only_no_ue_execution", "destination_prefix": "/Game/ArtPilot/RockTower/",
                               "one_static_mesh_per_file": True, "import_uniform_scale": 1.0,
                               "convert_scene": True, "convert_scene_unit": True, "force_front_x_axis": False,
                               "combine_meshes": True, "auto_generate_collision": False,
                               "transform_vertex_to_absolute": False, "bake_pivot_in_vertex": False,
                               "normal_import_method": "import normals; generate tangents only", "material_factors_from_manifest": True,
                               "required_fresh_process_gate": "Actual seven StaticMeshes, material sections, vertices in expected basis, pivots and attachment; package hashes after fresh reload.",
                               "runtime_changes_authorized": False},
            "approved_for_ue_import": False, "production_approved": False, "paid_tasks": 0}


def materials_record(objects):
    records = {}
    for obj in objects:
        for material in obj.data.materials:
            if material is None:
                raise ValueError("Unassigned source material")
            node = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if node is None:
                raise ValueError("Expected source Principled material")
            key = material_key(material.name)
            records[key] = {"name": key, "base_color_linear": list(node.inputs["Base Color"].default_value),
                            "metallic": float(node.inputs["Metallic"].default_value),
                            "roughness": float(node.inputs["Roughness"].default_value),
                            "alpha": float(node.inputs["Alpha"].default_value),
                            "linked_inputs": [socket.name for socket in node.inputs if socket.is_linked]}
    return records


def compare_materials(expected, actual):
    if set(expected) != set(actual):
        return {"passed": False, "expected": sorted(expected), "actual": sorted(actual), "reason": "material set changed"}
    errors = {}
    for name in expected:
        first, second = expected[name], actual[name]
        values = [abs(left - right) for left, right in zip(first["base_color_linear"], second["base_color_linear"])]
        values.extend(abs(first[key] - second[key]) for key in ("metallic", "roughness", "alpha"))
        errors[name] = max(values)
    return {"passed": all(value <= 1e-5 for value in errors.values()), "scalar_tolerance": 1e-5, "max_errors": errors}


def surface_records(objects):
    records = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        normals = [corner.vector.copy() for corner in mesh.corner_normals]
        for triangle in mesh.loop_triangles:
            corners = []
            for vertex, loop in zip(triangle.vertices, triangle.loops):
                corners.append({"position": list(obj.matrix_world @ mesh.vertices[vertex].co),
                                "normal": list((normal_matrix @ normals[loop]).normalized()),
                                "uv": [list(layer.data[loop].uv) for layer in mesh.uv_layers]})
            records.append({"material": material_key(mesh.materials[triangle.material_index].name), "corners": corners})
    return records


def compare_surfaces(expected, actual):
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    if len(expected) != len(actual):
        return {"passed": False, "expected_triangles": len(expected), "actual_triangles": len(actual)}
    tree = KDTree(len(actual))
    for index, triangle in enumerate(actual):
        centre = sum((Vector(corner["position"]) for corner in triangle["corners"]), Vector()) / 3
        tree.insert(centre, index)
    tree.balance()
    used, failures = set(), []
    maxima = [0.0, 0.0, 0.0]
    for index, triangle in enumerate(expected):
        centre = sum((Vector(corner["position"]) for corner in triangle["corners"]), Vector()) / 3
        candidates = []
        for location, candidate, distance in tree.find_range(centre, .00002):
            if candidate not in used and actual[candidate]["material"] == triangle["material"]:
                candidates.append((triangle_difference(triangle, actual[candidate]), candidate))
        if not candidates:
            failures.append({"triangle": index, "reason": "No matching surface/material"})
            continue
        errors, chosen = min(candidates)
        used.add(chosen)
        maxima = [max(previous, current) for previous, current in zip(maxima, errors)]
        if errors[0] > .00001 or errors[1] > .00001 or errors[2] > .002:
            failures.append({"triangle": index, "position_uv_normal_error": errors})
    return {"passed": not failures and len(used) == len(actual), "triangles_checked": len(expected),
            "position_tolerance_m": .00001, "uv_tolerance": .00001, "normal_vector_tolerance": .002,
            "max_position_error_m": maxima[0], "max_uv_error": maxima[1], "max_normal_vector_error": maxima[2],
            "unmatched_or_failed_triangles": len(failures), "examples": failures[:16]}


def merge_rigid_group(name, objects, target_world):
    import bpy
    vertices, faces, uv_coordinates, normals, source_materials, material_indices, smooth = [], [], [], [], [], [], []
    uv_count = None
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        if uv_count is None:
            uv_count = len(mesh.uv_layers)
            uv_coordinates = [[] for unused in range(uv_count)]
        if len(mesh.uv_layers) != uv_count:
            raise ValueError("Source UV layer counts differ; refusing implicit UV loss")
        transform = target_world.inverted() @ obj.matrix_world
        normal_matrix = transform.to_3x3().inverted().transposed()
        source_normals = [corner.vector.copy() for corner in mesh.corner_normals]
        offset = len(vertices)
        vertices.extend(transform @ vertex.co for vertex in mesh.vertices)
        for triangle in mesh.loop_triangles:
            material = mesh.materials[triangle.material_index]
            if material not in source_materials:
                source_materials.append(material)
            material_indices.append(source_materials.index(material))
            faces.append(tuple(offset + index for index in triangle.vertices))
            smooth.append(mesh.polygons[triangle.polygon_index].use_smooth)
            for loop in triangle.loops:
                normals.append((normal_matrix @ source_normals[loop]).normalized())
                for layer_index, layer in enumerate(mesh.uv_layers):
                    uv_coordinates[layer_index].append(tuple(layer.data[loop].uv))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for material in source_materials:
        mesh.materials.append(material)
    for polygon, material_index, use_smooth in zip(mesh.polygons, material_indices, smooth):
        polygon.material_index = material_index
        polygon.use_smooth = use_smooth
    for index, coordinates in enumerate(uv_coordinates):
        layer = mesh.uv_layers.new(name="UVMap" if index == 0 else "UVMap" + str(index))
        layer.data.foreach_set("uv", [value for point in coordinates for value in point])
    mesh.normals_split_custom_set(normals)
    mesh.update()
    group = bpy.data.objects.new("RT_" + name, mesh)
    bpy.context.scene.collection.objects.link(group)
    group.matrix_world = target_world
    return group


def export_and_roundtrip(out, group):
    import bpy
    from mathutils import Matrix
    original_world = group.matrix_world.copy()
    group.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    expected = surface_records([group])
    expected_materials = materials_record([group])
    files, checks = [], []
    for extension in ("glb", "fbx"):
        bpy.ops.object.select_all(action="DESELECT")
        group.select_set(True)
        bpy.context.view_layer.objects.active = group
        path = out / (group.name + "." + extension)
        if path.exists():
            raise FileExistsError(path)
        if extension == "glb":
            bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                                      export_animations=False, export_extras=True, export_apply=False)
        else:
            bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"},
                                     apply_unit_scale=True, axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                                     bake_anim=False, add_leaf_bones=False, mesh_smooth_type="EDGE")
        files.append(CONTRACT.file_record(path))
        before = set(bpy.context.scene.objects)
        if extension == "glb":
            bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False, use_image_search=False)
        bpy.context.view_layer.update()
        imported = [obj for obj in bpy.context.scene.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == "MESH"]
        comparison = compare_surfaces(expected, surface_records(meshes))
        actual_materials = materials_record(meshes)
        material_comparison = compare_materials(expected_materials, actual_materials)
        checks.append({"format": extension, "mesh_count": len(meshes), "surface_check": comparison,
                       "actual_material_factors": actual_materials, "material_factor_check": material_comparison,
                       "passed": comparison["passed"] and material_comparison["passed"] and len(meshes) == 1})
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
    group.matrix_world = original_world
    bpy.context.view_layer.update()
    reference = out / (group.name + ".surface_reference.json")
    CONTRACT.write_new(reference, {"local_vertices_basis": "Blender metres", "triangles": expected,
                                   "material_factors_authoritative": expected_materials})
    group.data.calc_loop_triangles()
    bounds = CONTRACT.point_bounds([vertex.co for vertex in group.data.vertices])
    return {"name": group.name, "files": files, "triangles": len(group.data.loop_triangles),
            "vertices": len(group.data.vertices), "material_sections": len(group.data.materials),
            "local_bounds_m": bounds, "materials": expected_materials,
            "roundtrip": checks, "surface_reference": CONTRACT.file_record(reference),
            "passed": all(check["passed"] for check in checks)}


def build(out):
    import bpy
    from mathutils import Matrix, Vector
    plan = dry_plan()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    CONTRACT.write_new(out / "input_plan.json", plan)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    bpy.context.scene.frame_set(145)
    bpy.context.view_layer.update()
    source_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("civwar_part")]
    source_signatures = CONTRACT.geometry_data_signature(source_meshes)
    pivot = bpy.context.scene.objects["arm_pivot"]
    expected_release_world = bpy.context.scene.objects["release_point"].matrix_world.translation.copy()
    expected_pivot_world = pivot.matrix_world.translation.copy()
    grouped = {name: [] for name in GROUPS}
    for obj in source_meshes:
        if obj.name == "loaded_stone_mesh":
            grouped["Stone"].append(obj)
        elif obj.name == "team_cloth_panel":
            grouped["Cloth"].append(obj)
        else:
            ancestor = obj.parent
            while ancestor and ancestor != pivot:
                ancestor = ancestor.parent
            grouped["Arm" if ancestor == pivot else "Frame"].append(obj)
    if sum(map(len, grouped.values())) != 71 or any(not objects for objects in grouped.values()):
        raise ValueError("Unexpected frozen group membership")
    targets = {"Frame": Matrix.Identity(4), "Cloth": Matrix.Identity(4), "Arm": pivot.matrix_world.copy(),
               "Stone": pivot.matrix_world @ Matrix.Translation(Vector(CONTRACT.RELEASE_LOCAL))}
    groups, records, merge_checks, world_references = {}, [], [], {}
    for name in GROUPS:
        expected = surface_records(grouped[name])
        world_references[name] = expected
        groups[name] = merge_rigid_group(name, grouped[name], targets[name])
        bpy.context.view_layer.update()
        check = compare_surfaces(expected, surface_records([groups[name]]))
        merge_checks.append({"group": name, "source_pieces": [obj.name for obj in grouped[name]], "world_surface_check": check})
        records.append(export_and_roundtrip(out, groups[name]))
    if CONTRACT.geometry_data_signature(source_meshes) != source_signatures:
        raise RuntimeError("Source upper mesh data was modified")
    adapter_records = []
    for adapter in plan["adapters"]:
        before = set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(ROOT / adapter["source"]["file"]))
        bpy.context.view_layer.update()
        imported = [obj for obj in bpy.context.scene.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == "MESH"]
        expected = surface_records(meshes)
        merged = merge_rigid_group("Adapter_" + adapter["id"], meshes, Matrix.Identity(4))
        bpy.context.view_layer.update()
        check = compare_surfaces(expected, surface_records([merged]))
        record = export_and_roundtrip(out, merged)
        adapter_records.append({**adapter, "merged": record, "merge_surface_check": check})
        for obj in imported + [merged]:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(bpy.context.scene.objects):
        if obj not in groups.values():
            bpy.data.objects.remove(obj, do_unlink=True)
    root = bpy.data.objects.new("Turret_RockTower", None)
    arm_pivot = bpy.data.objects.new("arm_pivot", None)
    release = bpy.data.objects.new("release_point", None)
    for obj in (root, arm_pivot, release):
        bpy.context.scene.collection.objects.link(obj)
    arm_pivot.parent = root
    arm_pivot.location = CONTRACT.PIVOT
    arm_pivot.rotation_euler[1] = math.radians(CONTRACT.READY_ANGLE)
    for name, obj in groups.items():
        obj.parent = arm_pivot if name in ("Arm", "Stone") else root
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.location = CONTRACT.RELEASE_LOCAL if name == "Stone" else (0, 0, 0)
        obj.rotation_euler = (0, 0, 0)
        obj.scale = (1, 1, 1)
    release.parent = arm_pivot
    release.location = CONTRACT.RELEASE_LOCAL
    bpy.context.view_layer.update()
    final_checks = []
    for name, merge in zip(GROUPS, merge_checks):
        local_reference = json.loads((out / (groups[name].name + ".surface_reference.json")).read_text(encoding="utf-8"))
        expected = local_reference["triangles"]
        before_world = groups[name].matrix_world.copy()
        groups[name].matrix_world = Matrix.Identity(4)
        bpy.context.view_layer.update()
        local_check = compare_surfaces(expected, surface_records([groups[name]]))
        groups[name].matrix_world = before_world
        bpy.context.view_layer.update()
        final_checks.append({"group": name, "check": local_check,
                             "final_world_check": compare_surfaces(world_references[name], surface_records([groups[name]]))})
    marker_errors = {"arm_pivot_world_error_m": (arm_pivot.matrix_world.translation - expected_pivot_world).length,
                     "release_world_error_m": (release.matrix_world.translation - expected_release_world).length}
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "grouped_review.blend"))
    passed = all(item["world_surface_check"]["passed"] for item in merge_checks) and all(record["passed"] for record in records)
    passed = passed and all(item["merge_surface_check"]["passed"] and item["merged"]["passed"] for item in adapter_records)
    passed = passed and all(item["check"]["passed"] and item["final_world_check"]["passed"] for item in final_checks)
    passed = passed and all(error <= .00001 for error in marker_errors.values())
    frozen_checks = dry_plan()
    if frozen_checks["upper_source"] != plan["upper_source"] or frozen_checks["adapters"] != plan["adapters"]:
        raise RuntimeError("Frozen inputs changed during grouped delivery")
    manifest = {"schema_version": 1, "asset_id": "Turret_RockTower", "status": "grouped_dcc_delivery_requires_root_and_ue_review",
                "input_plan": CONTRACT.file_record(out / "input_plan.json"), "script": CONTRACT.file_record(Path(__file__)),
                "upper": records, "adapters": adapter_records, "merge_checks": merge_checks,
                "final_local_surface_checks": final_checks, "source_upper_geometry_unchanged": True,
                "final_world_marker_errors": marker_errors,
                "source_upper_mesh_signatures": source_signatures, "blender_fbx_glb_roundtrip_passed": passed,
                "component_count_per_turret": 5, "upper_material_sections": sum(record["material_sections"] for record in records),
                "material_section_warning": "Four rigid upper components do not mean four draws; original material sections remain.",
                "coordinate_contract": plan["coordinate_contract"], "time_contract": plan["time_contract"],
                "cycle_samples_60fps": [{"time_seconds": frame / 60, **CONTRACT.sample_cycle(frame / 60)} for frame in range(145)],
                "ue_import_plan": plan["ue_import_plan"], "source_geometry_unchanged": True,
                "approved_for_ue_import": False, "production_approved": False, "paid_tasks": 0}
    CONTRACT.write_new(out / "delivery_manifest.json", manifest)
    print("CIVWAR_ROCKTOWER_DELIVERY " + json.dumps({"passed": passed, "manifest": CONTRACT.file_record(out / "delivery_manifest.json")}), flush=True)
    if not passed:
        raise RuntimeError("Grouped delivery surface or roundtrip gate failed; evidence retained")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--build", action="store_true")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    out = CONTRACT.safe_output(arguments.out)
    if not out.name.startswith("delivery"):
        raise ValueError("Grouped output must be a fresh delivery* directory")
    if arguments.build:
        build(out)
    else:
        CONTRACT.write_new(out / "delivery_plan.json", dry_plan())


if __name__ == "__main__":
    main()
