from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from itertools import product

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


module_spec = importlib.util.spec_from_file_location("stoneaxe_pose", Path(__file__).with_name("prepare_stoneaxe_pose_pilot.py"))
pose = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(pose)
CLIPS = {"Idle": 121, "Move": 37, "Attack": 61, "Hit": 31, "Death": 73}


def select(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def matrix_rows(matrix):
    return [list(row) for row in matrix]


def file_record(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fbx(path, objects, animated=False):
    select(objects)
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"ARMATURE", "MESH", "EMPTY"},
                             axis_forward="X", axis_up="Z", apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
                             bake_space_transform=False, use_mesh_modifiers=True, mesh_smooth_type="FACE",
                             add_leaf_bones=False, use_armature_deform_only=False, armature_nodetype="NULL",
                             primary_bone_axis="Y", secondary_bone_axis="X", bake_anim=animated,
                             bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
                             bake_anim_force_startend_keying=True, bake_anim_step=1.0, bake_anim_simplify_factor=0.0,
                             path_mode="COPY", embed_textures=False, use_custom_props=True)


def save_textures(body, output):
    files = {}
    for obj in body:
        for material in obj.data.materials:
            if not material or not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                image = node.image
                name = image.name.lower()
                channel = next((channel for channel in ("normal", "roughness", "metallic") if channel in name), "base_color")
                path = output / ("T_StoneAxe_" + channel + ".png")
                image.filepath_raw = str(path)
                image.file_format = "PNG"
                image.save()
                files[channel] = file_record(path) | {"color_space": image.colorspace_settings.name}
    if set(files) != {"normal", "roughness", "metallic", "base_color"}:
        raise ValueError("Full four-channel repaired PBR material is required")
    return files


def nearest_error(actual, expected):
    tree = KDTree(len(expected))
    for index, point in enumerate(expected):
        tree.insert(point, index)
    tree.balance()
    return max(tree.find(point)[2] for point in actual)


def capture_physical_motion(armature, body):
    expected = {}
    matrices = {}
    evidence = {"schema_version": 1, "units": "metres", "bone_scale": "Relative to source world rest scale; normalized export rest scale is one",
                "matrix_convention": "4x4 row arrays, column vectors; physical Blender world coordinates", "clips": {}}
    armature.animation_data.action = None
    pose.reset_pose(armature)
    rest_scales = {bone.name: (armature.matrix_world @ bone.matrix_local).to_scale() for bone in armature.data.bones}
    expected["reference"] = [point.copy() for obj in body for point in pose.evaluated_world_vertices(obj)]
    evidence["reference"] = {bone.name: {"head_m": list(armature.matrix_world @ bone.head_local), "scale": [1, 1, 1]} for bone in armature.data.bones}
    sample_indices = sorted(set(range(0, len(expected["reference"]), 31)) | {len(expected["reference"]) - 1})
    evidence["skinned_sample_vertex_indices"] = sample_indices
    evidence["reference_skinned_points_m"] = [list(expected["reference"][index]) for index in sample_indices]
    for clip, last_frame in CLIPS.items():
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip]
        expected[clip], matrices[clip], evidence["clips"][clip] = {}, {}, []
        for frame in range(1, last_frame + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            expected[clip][frame] = [point.copy() for obj in body for point in pose.evaluated_world_vertices(obj)]
            targets, bones = {}, {}
            for bone in armature.pose.bones:
                world = armature.matrix_world @ bone.matrix
                scale = Vector(tuple(value / reference for value, reference in zip(world.to_scale(), rest_scales[bone.name])))
                targets[bone.name] = Matrix.LocRotScale(world.translation * 100, world.to_quaternion(), scale)
                bones[bone.name] = {"head_m": list(world.translation), "scale": list(scale)}
            matrices[clip][frame] = targets
            evidence["clips"][clip].append({"frame": frame, "time_seconds": (frame - 1) / 60, "bones": bones,
                                            "skinned_points_m": [list(expected[clip][frame][index]) for index in sample_indices]})
    armature.animation_data.action = None
    pose.reset_pose(armature)
    return expected, matrices, evidence


def normalized_export_rig(source, body, targets, expected):
    source_name = source.name
    source.name = "Source_" + source_name
    armature = source.copy()
    armature.data = source.data.copy()
    armature.name = "Armature"
    armature.animation_data_clear()
    armature.parent = None
    armature.matrix_world = Matrix.Identity(4)
    armature.data.transform(Matrix.Scale(100, 4) @ source.matrix_world)
    bpy.context.scene.collection.objects.link(armature)
    for bone in armature.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
        bone.rotation_mode = "QUATERNION"
        bone.matrix_basis = Matrix.Identity(4)
    exported_body = []
    for original in body:
        copied = original.copy()
        copied.data = original.data.copy()
        copied.data.transform(Matrix.Scale(100, 4) @ original.matrix_world)
        copied.name = "Normalized_" + original.name
        copied.parent = None
        copied.matrix_world = Matrix.Identity(4)
        copied.animation_data_clear()
        for modifier in copied.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = armature
        bpy.context.scene.collection.objects.link(copied)
        exported_body.append(copied)
    bpy.context.scene.unit_settings.scale_length = .01
    armature.animation_data_create()
    actions = {}
    result = {"source_armature_world_matrix": matrix_rows(source.matrix_world), "export_armature_world_matrix": matrix_rows(armature.matrix_world),
              "export_scene_unit_scale": .01, "coordinate_units": "centimetres", "clips": [],
              "source_and_approved_blend_modified_on_disk": False}
    for clip, last_frame in CLIPS.items():
        action = bpy.data.actions.new("Normalized_CW_StoneAxe_" + clip)
        armature.animation_data.action = action
        actions[clip] = action
        maximum_position_error = 0
        maximum_skin_error = 0
        for frame in range(1, last_frame + 1):
            bpy.context.scene.frame_set(frame)
            for bone in armature.pose.bones:
                values = {"parent_matrix": targets[clip][frame][bone.parent.name], "parent_matrix_local": bone.parent.bone.matrix_local} if bone.parent else {}
                bone.matrix_basis = bone.bone.convert_local_to_pose(targets[clip][frame][bone.name], bone.bone.matrix_local, invert=True, **values)
            pose.keyed_pose(armature, frame)
            bpy.context.view_layer.update()
            maximum_position_error = max(maximum_position_error, max((bone.matrix.translation - targets[clip][frame][bone.name].translation).length / 100 for bone in armature.pose.bones))
            actual = [point / 100 for obj in exported_body for point in pose.evaluated_world_vertices(obj)]
            maximum_skin_error = max(maximum_skin_error, max((left - right).length for left, right in zip(actual, expected[clip][frame])))
        result["clips"].append({"clip": clip, "frames": last_frame, "maximum_bone_position_error_m": maximum_position_error,
                                 "maximum_corresponding_skinned_vertex_error_m": maximum_skin_error})
    result["passed"] = all(item["maximum_bone_position_error_m"] < .0001 and item["maximum_corresponding_skinned_vertex_error_m"] < .0005 for item in result["clips"])
    armature.animation_data.action = None
    pose.reset_pose(armature)
    return armature, exported_body, actions, result


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True, anim_offset=0.0, automatic_bone_orientation=False)
    return [obj for obj in bpy.data.objects if obj not in before]


def weapon_landmarks(armature, weapon_meshes, socket_rigid):
    inverse = socket_rigid.inverted()
    by_name = {obj.name: obj for obj in weapon_meshes}
    local = {obj.name: [inverse @ point for point in pose.evaluated_world_vertices(obj)] for obj in weapon_meshes}
    definitions = {}
    for name, axis, maximum in (("handle_tail", 2, False), ("handle_top", 2, True)):
        points = local["shaft"]
        extreme = (max if maximum else min)(point[axis] for point in points)
        definitions[name] = [("shaft", index) for index, point in enumerate(points) if abs(point[axis] - extreme) < 1e-5]
    definitions["grip_center"] = [(name, index) for name, points in local.items() if name.startswith("grip_wrap") for index in range(len(points))]
    edge = local["stone_edge_facet"]
    extreme = max(point.x for point in edge)
    definitions["axe_edge_end"] = [("stone_edge_facet", index) for index, point in enumerate(edge) if abs(point.x - extreme) < 1e-5]
    for signs in product((-1, 1), repeat=3):
        direction = Vector(signs)
        name, index = max(((name, index) for name, points in local.items() for index in range(len(points))), key=lambda pair: local[pair[0]][pair[1]].dot(direction))
        label = "geometry_extreme_" + "".join("p" if sign > 0 else "n" for sign in signs)
        definitions[label] = [(name, index)]
    result = {"schema_version": 1, "units": "metres", "coordinate_system": "Blender right-handed +X forward +Z up",
              "matrix_convention": "4x4 row arrays representing column-vector transforms; translation in last column",
              "local_space": "Exported fitted static mesh physical coordinates; all original weapon and armature scale is baked. Do not multiply by 0.82 again.",
              "markers": {name: {"local_position_m": list(sum((local[part][index] for part, index in sources), Vector()) / len(sources)),
                                  "source_evaluated_vertices": [{"object": part, "vertex": index} for part, index in sources]} for name, sources in definitions.items()},
              "poses": {}}
    result["local_vertices_m"] = []
    result["parts"] = []
    for name, points in local.items():
        result["parts"].append({"object": name, "vertex_start": len(result["local_vertices_m"]), "vertex_count": len(points)})
        result["local_vertices_m"].extend(list(point) for point in points)
    for label, clip, frame in (("reference", None, 1), ("idle", "Idle", 1), ("attack_contact", "Attack", 22), ("death_end", "Death", 73)):
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + clip] if clip else None
        if clip:
            bpy.context.scene.frame_set(frame)
        else:
            pose.reset_pose(armature)
        bpy.context.view_layer.update()
        world = {name: pose.evaluated_world_vertices(obj) for name, obj in by_name.items()}
        hand_world = armature.matrix_world @ armature.pose.bones["hand_r"].matrix
        hand_rigid = Matrix.LocRotScale(hand_world.translation, hand_world.to_quaternion(), Vector((1, 1, 1)))
        weapon_world = bpy.context.scene.objects["weapon_r"].matrix_world.copy()
        weapon_rigid = Matrix.LocRotScale(weapon_world.translation, weapon_world.to_quaternion(), Vector((1, 1, 1)))
        result["poses"][label] = {"clip": clip, "frame": frame, "time_seconds": (frame - 1) / 60,
                                   "hand_r_world_matrix": matrix_rows(hand_world), "hand_r_rigid_world_matrix": matrix_rows(hand_rigid),
                                   "weapon_rigid_world_matrix": matrix_rows(weapon_rigid), "weapon_world_scale": list(weapon_world.to_scale()),
                                   "world_positions_m": {name: list(sum((world[part][index] for part, index in sources), Vector()) / len(sources)) for name, sources in definitions.items()}}
    armature.animation_data.action = None
    pose.reset_pose(armature)
    return result


def validate_motion_acceptance(path, source):
    acceptance = json.loads(path.read_text(encoding="utf-8-sig"))
    if acceptance.get("status") != "dcc_motion_pilot_approved_only" or acceptance.get("source_sha256") != file_record(source)["sha256"]:
        raise ValueError("Motion approval does not match actual source BLEND")
    diagnostic_path = path.parent / acceptance["full_frame_diagnostic"]
    if file_record(diagnostic_path)["sha256"] != acceptance["full_frame_diagnostic_sha256"]:
        raise ValueError("Full-frame diagnostic evidence hash changed")
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8-sig"))
    if diagnostic["source_sha256"] != acceptance["source_sha256"]:
        raise ValueError("Full-frame diagnostic refers to a different source")
    for clip in diagnostic["clips"]:
        if clip["sample_count"] != CLIPS[clip["name"]] or clip["body_floor_minimum_m"] < -.0005 or clip["weapon_floor_minimum_m"] < -.0005:
            raise ValueError("Full-frame count or floor gate failed: " + clip["name"])
        if clip["maximum_non_hand_weighted_triangle_pairs"] or clip["maximum_head_triangle_pairs"] or clip["maximum_hand_points_penetrating_over_2mm"]:
            raise ValueError("Full-frame grip/body gate failed: " + clip["name"])
    for key in ("Attack_1", "Attack_61", "Hit_1", "Hit_31", "Idle_121"):
        if any(item["position_m"] > 1e-5 or item["rotation_deg"] > .01 for item in diagnostic["seams_to_idle"][key].values()):
            raise ValueError("Idle transition gate failed: " + key)
    return acceptance, diagnostic_path


def verify_exports(body_path, clip_paths, expected, bone_names):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body_objects = import_fbx(body_path)
    armature = next(obj for obj in body_objects if obj.type == "ARMATURE")
    body = [obj for obj in body_objects if obj.type == "MESH"]
    actual_bones = sorted(bone.name for bone in armature.data.bones)
    pose.reset_pose(armature)
    reference_points = [point for obj in body for point in pose.evaluated_world_vertices(obj)]
    result = {"body_bone_names_equal": actual_bones == bone_names, "body_bone_count": len(actual_bones),
              "body_reference_maximum_nearest_vertex_error_m": nearest_error(reference_points, expected["reference"]),
              "body_height_m": max(point.z for point in reference_points) - min(point.z for point in reference_points), "clips": [],
              "total_integer_animation_frames_tested": sum(CLIPS.values())}
    armature.animation_data_create()
    bpy.context.scene.render.fps = 60
    bpy.context.scene.render.fps_base = 1
    for name, path in clip_paths.items():
        imported = import_fbx(path)
        imported_armature = next(obj for obj in imported if obj.type == "ARMATURE")
        imported_body = [obj for obj in imported if obj.type == "MESH"]
        rest_error = max(abs(bone.matrix_local[row][column] - armature.data.bones[bone.name].matrix_local[row][column]) for bone in imported_armature.data.bones for row in range(4) for column in range(4))
        imported_action = imported_armature.animation_data.action
        if imported_action is None:
            raise ValueError("Missing actual FBX clip: " + name)
        slot_identifier = imported_armature.animation_data.action_slot.identifier
        armature.animation_data.action = imported_action
        armature.animation_data.action_slot = next(slot for slot in imported_action.slots if slot.identifier == slot_identifier)
        samples = []
        for frame, vertices in expected[name].items():
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            points = [point for obj in body for point in pose.evaluated_world_vertices(obj)]
            own_points = [point for obj in imported_body for point in pose.evaluated_world_vertices(obj)]
            samples.append({"frame": frame, "maximum_nearest_vertex_error_m": nearest_error(points, vertices),
                            "clip_own_skinned_mesh_maximum_nearest_vertex_error_m": nearest_error(own_points, vertices) if own_points else None})
        result["clips"].append({"name": name, "bone_names_equal": sorted(bone.name for bone in imported_armature.data.bones) == bone_names,
                               "frame_range": list(imported_action.frame_range), "rest_matrix_maximum_element_difference": rest_error,
                               "skin_bind_mesh_present": bool(imported_body), "samples": samples})
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
    errors = [result["body_reference_maximum_nearest_vertex_error_m"]] + [sample["maximum_nearest_vertex_error_m"] for clip in result["clips"] for sample in clip["samples"]]
    own_errors = [sample["clip_own_skinned_mesh_maximum_nearest_vertex_error_m"] for clip in result["clips"] for sample in clip["samples"]]
    result["passed"] = result["body_bone_names_equal"] and all(clip["bone_names_equal"] and clip["skin_bind_mesh_present"] and clip["rest_matrix_maximum_element_difference"] < 1e-5 and clip["frame_range"] == [1.0, float(CLIPS[clip["name"]])] for clip in result["clips"]) and max(errors) < .0005 and all(value is not None and value < .0005 for value in own_errors)
    result["limit"] = "Blender FBX round trip only; UE import orientation, skeletal scale, sockets, material assignment, gameplay timing, and both-team cameras still require root review."
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grip-review-reference", required=True)
    parser.add_argument("--motion-review-reference", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    motion_review_path = args.motion_review_reference.resolve()
    motion_acceptance, diagnostic_path = validate_motion_acceptance(motion_review_path, args.source)
    if (args.output / "delivery_manifest.json").exists():
        raise FileExistsError("Choose a fresh candidate output directory; preserve previous verification evidence")
    for name in ("body", "animations", "weapon", "textures"):
        (args.output / name).mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    review_path = Path(args.grip_review_reference).resolve()
    acceptance = json.loads(review_path.read_text(encoding="utf-8-sig"))
    if acceptance.get("status") != "static_grip_approved_only" or armature.get("reviewed_static_grip_source_sha256") != acceptance.get("source_sha256"):
        raise ValueError("Animation scene does not carry the actually approved static-grip source hash")
    body = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    weapon = bpy.context.scene.objects["Weapon_StoneAxe"]
    weapon_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj not in body]
    socket = bpy.context.scene.objects["weapon_r"]
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.fps = 60
    scene.render.fps_base = 1
    bone_names = sorted(bone.name for bone in armature.data.bones)
    manifest = {"schema_version": 1, "source": file_record(args.source), "grip_review_reference": args.grip_review_reference,
                "grip_acceptance": file_record(review_path), "rig_task_id": "903d3c61-34d6-4205-98b2-fd823cdb060e",
                "dcc_motion_acceptance": file_record(motion_review_path), "full_frame_diagnostic": file_record(diagnostic_path),
                "shoe_weight_repair": file_record(args.source.parent / "shoe_weight_repair.json"),
                "status": "local_export_candidate_not_ue_approved", "bone_names": bone_names, "fps": 60,
                "root_motion": False, "damage_authority_modified": False, "runtime_approved": False, "production_approved": False,
                "attack": {"duration_seconds": 1.0, "visual_contact_seconds": .35, "blender_contact_frame": 22, "ue_zero_based_contact_sample": 21},
                "textures": save_textures(body, args.output / "textures")}
    armature.animation_data.action = None
    pose.reset_pose(armature)
    manifest["reference_bones"] = {bone.name: {"parent": bone.parent.name if bone.parent else None,
                                              "head_m": list(armature.matrix_world @ bone.head_local)} for bone in armature.data.bones}
    expected = {"reference": [point.copy() for obj in body for point in pose.evaluated_world_vertices(obj)]}
    hand_world = armature.matrix_world @ armature.pose.bones["hand_r"].matrix
    socket_world = socket.matrix_world.copy()
    hand_rigid = Matrix.LocRotScale(hand_world.translation, hand_world.to_quaternion(), Vector((1, 1, 1)))
    socket_rigid = Matrix.LocRotScale(socket_world.translation, socket_world.to_quaternion(), Vector((1, 1, 1)))
    mount = {"bone": "hand_r", "coordinate_system": "Blender right-handed, physical metres, +X forward, +Z up",
             "hand_head_world_matrix": matrix_rows(hand_world), "weapon_root_world_matrix": matrix_rows(socket_world),
             "full_relative_matrix_before_weapon_scale_bake": matrix_rows(hand_world.inverted() @ socket_world),
             "physical_rigid_hand_head_relative_matrix_after_weapon_scale_bake": matrix_rows(hand_rigid.inverted() @ socket_rigid),
             "weapon_scale_baked_in_mesh": .82,
             "warning": "Do not paste Blender quaternion or matrix into UE. Root must verify imported bone basis, centimetres, and handedness; never mirror or rename left/right bones."}
    pose.inspection.helper.write(args.output / "weapon/hand_r_mount.json", mount)
    markers_path = args.output / "weapon/weapon_landmarks.json"
    calibration_path = args.output / "weapon/calibration.json"
    calibration = weapon_landmarks(armature, weapon_meshes, socket_rigid)
    pose.inspection.helper.write(calibration_path, calibration)
    pose.inspection.helper.write(markers_path, {key: value for key, value in calibration.items() if key not in {"local_vertices_m", "parts"}})
    expected, targets, motion_evidence = capture_physical_motion(armature, body)
    motion_path = args.output / "physical_motion_reference.json"
    pose.inspection.helper.write(motion_path, motion_evidence)
    manifest["physical_motion_reference"] = file_record(motion_path)
    source_armature = armature
    armature, body, actions, normalization = normalized_export_rig(source_armature, body, targets, expected)
    normalization_path = args.output / "centimetre_normalization_report.json"
    pose.inspection.helper.write(normalization_path, normalization)
    manifest["centimetre_normalization"] = file_record(normalization_path)
    manifest["centimetre_normalization_passed"] = normalization["passed"]
    manifest["expected_reference_bone_world_scale"] = [1, 1, 1]
    if not normalization["passed"]:
        pose.inspection.helper.write(args.output / "delivery_manifest.json", manifest)
        raise RuntimeError("Normalization changed physical animation; preserve diagnostic and do not export")
    body_path = args.output / "body/SK_StoneAxe_Pilot.fbx"
    fbx(body_path, [armature] + body)
    manifest["body"] = file_record(body_path)
    manifest["clips"] = []
    clip_paths = {}
    for name, last_frame in CLIPS.items():
        action = actions[name]
        armature.animation_data.action = action
        scene.frame_start = 1
        scene.frame_end = last_frame
        path = args.output / ("animations/AN_StoneAxe_" + name + ".fbx")
        fbx(path, [armature] + body, animated=True)
        clip_paths[name] = path
        manifest["clips"].append(file_record(path) | {"clip": name, "first_frame": 1, "last_frame": last_frame, "duration_seconds": (last_frame - 1) / 60,
                                                    "includes_reference_skin_for_bind_pose": True, "ue_import_mode": "animation only, existing body skeleton; ignore included bind mesh"})
    armature.animation_data.action = None
    pose.reset_pose(armature)
    inverse = socket_rigid.inverted()
    fitted = []
    for obj in weapon_meshes:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=bpy.context.evaluated_depsgraph_get())
        mesh.transform(Matrix.Scale(100, 4) @ inverse @ evaluated.matrix_world)
        fitted_obj = bpy.data.objects.new("Fitted_" + obj.name, mesh)
        scene.collection.objects.link(fitted_obj)
        fitted.append(fitted_obj)
    fbx_path = args.output / "weapon/SM_StoneAxe_Fitted.fbx"
    glb_path = args.output / "weapon/SM_StoneAxe_Fitted.glb"
    fbx(fbx_path, fitted)
    select(fitted)
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True, export_animations=False, export_extras=True)
    manifest["weapon"] = {"fbx": file_record(fbx_path), "glb": file_record(glb_path), "mount": "weapon/hand_r_mount.json", "mount_record": file_record(args.output / "weapon/hand_r_mount.json"), "landmarks": file_record(markers_path), "calibration": file_record(calibration_path), "separate_from_body": True, "handle_diameter_m": .036}
    roundtrip = verify_exports(body_path, clip_paths, expected, bone_names)
    pose.inspection.helper.write(args.output / "fbx_roundtrip_report.json", roundtrip)
    manifest["blender_fbx_roundtrip_passed"] = roundtrip["passed"]
    pose.inspection.helper.write(args.output / "delivery_manifest.json", manifest)
    print("STONEAXE_EXPORT " + json.dumps({"output": str(args.output), "roundtrip_passed": roundtrip["passed"]}))
    if not roundtrip["passed"]:
        raise RuntimeError("FBX round-trip gate failed; do not hand candidate to UE as verified")


if __name__ == "__main__":
    main()
