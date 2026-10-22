"""Verify original-task PBR coordinates, then apply the approved fixed matrix once."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"
DEFAULT_SPEC = OWNED / "pbr_preparation_spec.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    return {"file": Path(path).resolve().relative_to(ROOT).as_posix(), "sha256": digest(path)}


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preflight(spec):
    if spec.get("asset_id") != "Base_Stone" or spec.get("agent_paid_or_watch_calls_allowed") is not False:
        raise ValueError("Unexpected task scope")
    if not spec.get("root_download_complete_confirmed") or not spec.get("returned_texture"):
        return {"ready": False, "status": "waiting_for_root_confirmed_complete_download_no_half_files_read"}
    source = spec["original_geometry"]
    returned = spec["returned_texture"]
    for item in (source, returned):
        path = (ROOT / item["file"]).resolve()
        if not path.is_relative_to(ROOT / "RawAssets/Art/Tripo_v01/tripo_raw/Base_Stone") or digest(path) != item["sha256"]:
            raise ValueError("Unexpected or changed frozen source")
    task = read(ROOT / returned["task_file"])
    receipt = read(ROOT / returned["submission_file"])
    if task.get("task_id") != spec["texture_task_id"] or receipt.get("task_id") != spec["texture_task_id"] or task.get("status") != "success":
        raise ValueError("Texture receipt not final success for the approved task")
    if task.get("type") != "texture_model":
        raise ValueError("Expected texture task")
    actual_source = task.get("input", {}).get("original_model_id", task.get("input", {}).get("original_model_task_id", task.get("input", {}).get("source_task_id")))
    if actual_source != spec["source_geometry_task_id"]:
        raise ValueError("Provider input source task is different or unproven")
    if read(ROOT / spec["placement_approval"])["source_imported_blender_world_to_candidate_matrix_m"] != spec["normalization_matrix_imported_blender_world_m"]:
        raise ValueError("Placement matrix no longer matches root approval")
    return {"ready": True, "status": "ready_for_root_leased_local_comparison_only", "source": source, "returned": returned}


def execute(spec, spec_path, render):
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.kdtree import KDTree

    helper_spec = importlib.util.spec_from_file_location("base_pbr_helpers", ROOT / "Tools/Blender/prepare_tripo_environment.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    output = ROOT / spec["output_root"] / ("h" + hashlib.sha256((spec["returned_texture"]["sha256"] + json.dumps(spec["normalization_matrix_imported_blender_world_m"])).encode()).hexdigest()[:12])
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(spec_path, output / "input_spec.json")
    write(output / "checkpoint.json", {"status": "started_do_not_overwrite", "production_approved": False})

    def snapshot(path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        vertices, triangles = [], []
        for obj in meshes:
            offset = len(vertices)
            vertices.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
            obj.data.calc_loop_triangles()
            triangles.extend(tuple(index + offset for index in triangle.vertices) for triangle in obj.data.loop_triangles)
        lower, upper = helper.bounds(meshes)
        return {"objects": meshes, "vertices": vertices, "triangles": triangles, "bounds_m": [list(lower), list(upper)],
                "geometry": helper.geometry_report(meshes), "uv": helper.uv_signature(meshes), "materials": helper.material_report(meshes)}

    original = snapshot(ROOT / spec["original_geometry"]["file"])
    actual = snapshot(ROOT / spec["returned_texture"]["file"])
    unique = sorted(set(tuple(point) for point in original["vertices"]))
    lookup = {point: index for index, point in enumerate(unique)}
    tree = KDTree(len(unique))
    for index, point in enumerate(unique):
        tree.insert(point, index)
    tree.balance()
    original_map = [lookup[tuple(point)] for point in original["vertices"]]
    matches = [tree.find(point) for point in actual["vertices"]]
    actual_map = [entry[1] for entry in matches]
    forward_error = max(entry[2] for entry in matches)
    reverse_tree = KDTree(len(actual["vertices"]))
    for index, point in enumerate(actual["vertices"]):
        reverse_tree.insert(point, index)
    reverse_tree.balance()
    reverse_error = max(reverse_tree.find(point)[2] for point in original["vertices"])
    expected_faces = Counter(tuple(sorted(original_map[index] for index in triangle)) for triangle in original["triangles"])
    actual_faces = Counter(tuple(sorted(actual_map[index] for index in triangle)) for triangle in actual["triangles"])
    missing, added = expected_faces - actual_faces, actual_faces - expected_faces
    errors = []
    if max(forward_error, reverse_error) > spec["geometry_gate"]["maximum_symmetric_nearest_vertex_distance_m"]:
        errors.append("original_task_coordinate_or_surface_mismatch")
    if missing or added or len(actual["triangles"]) != spec["geometry_gate"]["expected_triangles"]:
        errors.append("source_triangle_topology_changed_requires_explicit_review")
    if any(not mesh["uv_layers"] or mesh["uv_zero_area_triangles"] for mesh in actual["geometry"]["meshes"]):
        errors.append("missing_or_degenerate_returned_uv")
    if not any(material["images"] for material in actual["materials"]):
        errors.append("no_returned_pbr_images")
    comparison = {"asset_id": "Base_Stone", "comparison_space": "Original imported Blender world metres; neither source is recentered/rescaled before comparison",
                  "original": spec["original_geometry"], "returned": spec["returned_texture"], "original_bounds_m": original["bounds_m"],
                  "returned_bounds_m": actual["bounds_m"], "original_triangles": len(original["triangles"]), "returned_triangles": len(actual["triangles"]),
                  "return_to_source_maximum_distance_m": forward_error, "source_to_return_maximum_distance_m": reverse_error,
                  "missing_triangles": [{"count": count, "points_m": [unique[index] for index in key]} for key, count in missing.items()],
                  "added_triangles": [{"count": count, "points_m": [unique[index] for index in key]} for key, count in added.items()],
                  "original_uv": original["uv"], "returned_uv": actual["uv"], "uv_same_as_original": original["uv"] == actual["uv"],
                  "returned_uv_texture_pair_used_as_delivered": True, "errors": errors, "passed": not errors, "production_approved": False}
    write(output / "source_coordinate_comparison.json", comparison)
    if errors:
        raise ValueError("PBR source gate failed: " + str(errors))
    objects = actual["objects"]
    original_textures = helper.extract_original_textures(objects, output / "textures")
    before_uv = helper.uv_signature(objects)
    before_materials = helper.material_report(objects)
    matrix = Matrix(spec["normalization_matrix_imported_blender_world_m"])
    transforms = {obj: matrix @ obj.matrix_world.copy() for obj in objects}
    for obj in objects:
        obj.parent = None
        obj.matrix_world = transforms[obj]
    bpy.context.view_layer.update()
    helper.select(objects)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if helper.uv_signature(objects) != before_uv or helper.material_report(objects) != before_materials:
        raise ValueError("Fixed transform changed provider UV/materials")
    low, high = helper.bounds(objects)
    expected = spec["expected_bounds_cm"]
    if max(abs(low[axis] * 100 - expected["min"][axis]) for axis in range(3)) > .002 or max(abs(high[axis] * 100 - expected["max"][axis]) for axis in range(3)) > .002:
        raise ValueError("Applying the saved matrix once did not reproduce approved ground bounds")
    geometry = helper.geometry_report(objects)
    root = bpy.data.objects.new("Base_Stone_GROUND_ROOT", None)
    bpy.context.scene.collection.objects.link(root)
    for obj in objects:
        obj.parent = root
    helper.select(objects + [root])
    glb, fbx, blend = [output / ("Base_Stone_PBR" + extension) for extension in (".glb", ".fbx", ".blend")]
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True, export_apply=False, export_yup=True,
                              export_extras=True, export_image_format="AUTO", export_animations=False)
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH", "EMPTY"}, apply_unit_scale=True,
                            apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
                            bake_anim=False, path_mode="COPY", embed_textures=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    roundtrip = helper.verify_roundtrip(glb, list((high - low) * 100), geometry["triangles"], len(before_materials), True)
    reimported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    returned_low, returned_high = helper.bounds(reimported)
    roundtrip["approved_ground_bounds_preserved"] = (returned_low - low).length < 2e-6 and (returned_high - high).length < 2e-6
    roundtrip["uv_loop_value_signature_match"] = helper.uv_signature(reimported) == before_uv
    roundtrip["position_weld_topology_preserved"] = all(first["coincident_seam_diagnostic"][key] == second["coincident_seam_diagnostic"][key]
        for first, second in zip(geometry["meshes"], roundtrip["geometry"]["meshes"])
        for key in ("boundary_edges_after_position_weld", "nonmanifold_edges_after_position_weld"))
    passed = roundtrip["pass"] and roundtrip["approved_ground_bounds_preserved"] and roundtrip["uv_loop_value_signature_match"] and roundtrip["position_weld_topology_preserved"]
    report = {"asset_id": "Base_Stone", "task_id": spec["texture_task_id"], "source_comparison": reference(output / "source_coordinate_comparison.json"),
              "normalization_matrix_imported_blender_world_m": spec["normalization_matrix_imported_blender_world_m"], "matrix_application_count": 1,
              "bottom_realignment_performed": False, "bounds_cm": {"min": list(low * 100), "max": list(high * 100), "dimensions": list((high - low) * 100)},
              "source_textures": original_textures, "provider_materials": before_materials, "processed_geometry": geometry,
              "provider_uv_unchanged_before_export": True, "roundtrip": roundtrip, "roundtrip_passed": passed,
              "files": [reference(path) for path in (glb, fbx, blend)], "approved_for_ue_import": False, "production_approved": False}
    write(output / "inspection.json", report)
    if not passed:
        raise ValueError("PBR normalized roundtrip failed; inspect retained output")
    renders = []
    if render:
        for material in {slot.material for obj in reimported for slot in obj.material_slots if slot.material}:
            if not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    for link in list(node.inputs["Metallic"].links):
                        material.node_tree.links.remove(link)
                    node.inputs["Metallic"].default_value = spec["render"]["metallic_preview_override"]
        camera, centre, span = helper.setup_render(reimported[0], "HIP")
        scene = bpy.context.scene
        scene.render.threads_mode = "FIXED"
        scene.render.threads = 2
        scene.cycles.samples = 8
        scene.render.resolution_x = scene.render.resolution_y = 512
        for view, direction in (("front", (1, 0, 0)), ("left", (0, -1, 0)), ("back", (-1, 0, 0)), ("right", (0, 1, 0)), ("preview", (2, -3, 1.6))):
            camera.location = centre + Vector(direction) * span * 2
            camera.rotation_euler = (centre - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.data.ortho_scale = span * (1.55 if view == "preview" else 1.25)
            path = output / (view + ".png")
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            renders.append({"view": view, **reference(path)})
    manifest = {"schema_version": 1, "batch_id": "tripo_base_stone_pbr_v01", "units": "cm", "source": "Tripo", "production_approved": False,
                "assets": [{"id": "Base_Stone", "role": "base_pbr_candidate", "file": reference(glb)["file"], "sha256": digest(glb),
                            "fbx": reference(fbx)["file"], "blend": reference(blend)["file"], "type": "static_mesh", "source_stage": "textured",
                            "expected_dimensions_cm": list((high - low) * 100), "expected_bounds_cm": report["bounds_cm"], "combine_meshes": False,
                            "import_scale": 1, "task_id": spec["texture_task_id"], "source_sha256": spec["returned_texture"]["sha256"],
                            "inspection": reference(output / "inspection.json")["file"], "textures": original_textures,
                            "runtime_material_overrides": {"Metallic": 0}, "override_saved_to_model": False,
                            "assembly_required": True, "ready_for_ue_pilot": False, "approved_for_ue_import": False, "production_approved": False}]}
    write(output / "manifest.json", manifest)
    write(output / "render_evidence.json", {"images": renders, "cpu_threads": 2, "samples": 8, "size": [512, 512],
                                           "metallic_preview_override": 0, "source_model_materials_unchanged": True, "production_approved": False})
    source_unchanged = all(digest(ROOT / item["file"]) == item["sha256"] for item in (spec["original_geometry"], spec["returned_texture"]))
    write(output / "checkpoint.json", {"status": "pbr_source_transform_roundtrip_complete_pending_visual_review", "source_bytes_unchanged": source_unchanged,
                                      "roundtrip_passed": passed, "render_count": len(renders), "active_processes": [], "production_approved": False})
    if not source_unchanged:
        raise ValueError("Raw source protection failed")
    print(json.dumps({"output": str(output), "geometry_comparison_passed": True, "roundtrip_passed": passed, "render_count": len(renders), "source_unchanged": source_unchanged}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    spec = read(args.spec)
    status = preflight(spec)
    if args.execute:
        if not status["ready"]:
            raise ValueError(status["status"])
        execute(spec, args.spec, args.render)
    else:
        print(json.dumps(status))


if __name__ == "__main__":
    main()
