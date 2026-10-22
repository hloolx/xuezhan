"""Freeze the approved uniform/Base_Stone ground transform and verify roundtrip."""
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import runpy
import shutil
import sys

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree


ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/base_stone_v01"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure = load("base_measurements", ROOT / "Tools/base_stone_diagnose.py")
shared = load("base_shared", ROOT / "Tools/Blender/prepare_tripo_environment.py")
approval_path = OWNED / "ground_placement_approval.json"
approval = json.loads(approval_path.read_text(encoding="utf-8"))
if not approval["approved_for_normalized_export"] or approval["source"]["sha256"] != measure.SOURCE_SHA:
    raise ValueError("Missing root source-specific placement approval")
for entry in approval["reviewed_axis_views"] + approval["reviewed_placement_views"]:
    if measure.digest(ROOT / entry["file"]) != entry["sha256"]:
        raise ValueError("Approved render evidence changed")
if measure.digest(measure.SOURCE) != measure.SOURCE_SHA:
    raise ValueError("Raw source changed")
fingerprint = hashlib.sha256((measure.SOURCE_SHA + ":640:0:-31").encode()).hexdigest()[:12]
OUTPUT = OWNED / ("normalized_v01_h" + fingerprint)
OUTPUT.mkdir(exist_ok=False)
shutil.copy2(approval_path, OUTPUT / "input_approval.json")
(OUTPUT / "source").mkdir()
shutil.copy2(measure.SOURCE, OUTPUT / "source/original.glb")


def save(name, value):
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def triangle_corners(objects):
    records = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        if not mesh.uv_layers:
            raise ValueError("Source UV missing")
        uv = mesh.uv_layers.active.data
        for triangle in mesh.loop_triangles:
            records.append([(obj.matrix_world @ mesh.vertices[mesh.loops[loop].vertex_index].co, uv[loop].uv.copy()) for loop in triangle.loops])
    return records


def compare_triangles(expected, actual):
    if len(expected) != len(actual):
        raise ValueError("Roundtrip triangle count changed")
    tree = KDTree(len(expected))
    for index, corners in enumerate(expected):
        tree.insert(sum((corner[0] for corner in corners), Vector()) / 3, index)
    tree.balance()
    used = set()
    maximum_position = maximum_uv = 0
    failed = []
    for triangle_index, corners in enumerate(actual):
        centre = sum((corner[0] for corner in corners), Vector()) / 3
        best = None
        for location, expected_index, distance in tree.find_n(centre, 12):
            if expected_index in used or distance > 2e-6:
                continue
            for order in itertools.permutations(range(3)):
                position_error = max((corners[index][0] - expected[expected_index][order[index]][0]).length for index in range(3))
                uv_error = max((corners[index][1] - expected[expected_index][order[index]][1]).length for index in range(3))
                score = max(position_error, uv_error)
                if best is None or score < best[0]:
                    best = (score, expected_index, position_error, uv_error)
        if best is None or best[0] > 2e-6:
            failed.append(triangle_index)
            continue
        used.add(best[1])
        maximum_position = max(maximum_position, best[2])
        maximum_uv = max(maximum_uv, best[3])
    return {"passed": not failed and len(used) == len(expected), "triangles_matched_one_to_one": len(used),
            "maximum_corner_position_error_m": maximum_position, "maximum_corner_uv_error": maximum_uv,
            "tolerance": 2e-6, "unmatched_triangles": failed,
            "vertex_count_policy": "glTF normal/UV seam splits may duplicate vertices, but every geometric triangle and attached UV corner must match one-to-one."}


save("checkpoint.json", {"status": "started_do_not_overwrite", "source": measure.record(measure.SOURCE), "production_approved": False})
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1
scene.render.threads_mode = "FIXED"
scene.render.threads = 2
bpy.ops.import_scene.gltf(filepath=str(measure.SOURCE))
objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
before = shared.geometry_report(objects)
uv_before = shared.uv_signature(objects)
materials_before = shared.material_report(objects)
normalization = shared.normalize(objects, "horizontal_max", 640, 0)
for obj in objects:
    obj.location.z -= .31
shared.select(objects)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
after = shared.geometry_report(objects)
if any(before[key] != after[key] for key in ("mesh_count", "vertices", "polygons", "triangles")):
    raise ValueError("Normalization altered source topology")
if shared.uv_signature(objects) != uv_before or shared.material_report(objects) != materials_before:
    raise ValueError("Normalization altered source UV/materials")
low, high = shared.bounds(objects)
if abs(low.z + .31) > 2e-6:
    raise ValueError("Candidate bottom must remain31cm below gameplay ground")
expected_triangles = triangle_corners(objects)
root = bpy.data.objects.new("Base_Stone_GROUND_ROOT", None)
scene.collection.objects.link(root)
for obj in objects:
    obj.parent = root
shared.select(objects + [root])
glb, fbx, blend = [OUTPUT / ("Base_Stone_normalized" + extension) for extension in (".glb", ".fbx", ".blend")]
bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True, export_apply=False,
                          export_yup=True, export_extras=True, export_image_format="AUTO", export_animations=False)
bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH", "EMPTY"},
                        apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
                        use_mesh_modifiers=False, bake_anim=False, path_mode="COPY", embed_textures=True)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
expected_dimensions = list((high - low) * 100)
roundtrip = shared.verify_roundtrip(glb, expected_dimensions, after["triangles"], len(materials_before), True)
reimported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
roundtrip["triangle_uv_correspondence"] = compare_triangles(expected_triangles, triangle_corners(reimported))
roundtrip_low, roundtrip_high = shared.bounds(reimported)
roundtrip["bounds_match"] = (roundtrip_low - low).length < 2e-6 and (roundtrip_high - high).length < 2e-6
roundtrip["position_weld_topology_equal"] = all(
    first["coincident_seam_diagnostic"][key] == second["coincident_seam_diagnostic"][key]
    for first, second in zip(after["meshes"], roundtrip["geometry"]["meshes"])
    for key in ("boundary_edges_after_position_weld", "nonmanifold_edges_after_position_weld"))
roundtrip["passed_all"] = roundtrip["pass"] and roundtrip["triangle_uv_correspondence"]["passed"] and roundtrip["bounds_match"] and roundtrip["position_weld_topology_equal"]
source_unchanged = measure.digest(measure.SOURCE) == measure.SOURCE_SHA
report = {"asset_id": "Base_Stone", "status": "immutable_normalized_geometry_only", "source": measure.record(measure.SOURCE),
          "source_task_id": approval["source"]["task_id"], "approval": measure.record(OUTPUT / "input_approval.json"),
          "tool": measure.record(Path(__file__)), "normalization": normalization, "additional_translation_cm": [0, 0, -31],
          "source_imported_blender_world_to_candidate_matrix_m": approval["source_imported_blender_world_to_candidate_matrix_m"],
          "bounds_cm": {"min": list(low * 100), "max": list(high * 100), "dimensions": expected_dimensions},
          "ground_z_cm": 0, "bbox_bottom_is_below_ground_by_design": True, "uniform_shape_unchanged": True,
          "source_bytes_unchanged": source_unchanged, "uv_unchanged_before_export": True, "materials_unchanged_before_export": True,
          "source_topology": before, "normalized_topology": after, "roundtrip": roundtrip,
          "files": [measure.record(path) for path in (glb, fbx, blend)], "semantic_parts_separated": False,
          "sockets_implemented": False, "gate_traversable": False, "larger_units_and_turret_fit_approved": False,
          "approved_for_texture_submission": False, "approved_for_ue_import": False, "production_approved": False}
save("inspection.json", report)
if not source_unchanged or not roundtrip["passed_all"]:
    raise RuntimeError("Immutable export gate failed; retained output must be inspected, not overwritten")
manifest = {"schema_version": 1, "batch_id": "tripo_base_stone_v01", "units": "cm", "source": "Tripo", "production_approved": False,
            "assets": [{"id": "Base_Stone", "role": "base_geometry_candidate", "file": measure.record(glb)["file"], "sha256": measure.digest(glb),
                        "fbx": measure.record(fbx)["file"], "blend": measure.record(blend)["file"], "expected_dimensions_cm": expected_dimensions,
                        "expected_bounds_cm": report["bounds_cm"], "import_scale": 1, "combine_meshes": False,
                        "source_stage": "geometry_only", "source_task_id": approval["source"]["task_id"], "source_sha256": measure.SOURCE_SHA,
                        "assembly_required": True, "inspection": measure.record(OUTPUT / "inspection.json")["file"],
                        "approved_for_ue_import": False, "production_approved": False}]}
save("manifest.json", manifest)
save("checkpoint.json", {"status": "immutable_export_roundtrip_passed_pending_root_texture_gate", "source_sha256": measure.SOURCE_SHA,
                          "model_sha256": measure.digest(glb), "roundtrip_passed": True, "active_processes": [], "production_approved": False})
print(json.dumps({"output": str(OUTPUT), "model_sha256": measure.digest(glb), "roundtrip_passed": True}))
if "--render-front" in sys.argv:
    sys.argv = [str(ROOT / "Tools/base_stone_render_origin_comparison.py"), "--front-only"]
    runpy.run_path(str(ROOT / "Tools/base_stone_render_origin_comparison.py"), run_name="__main__")
