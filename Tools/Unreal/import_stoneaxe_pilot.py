from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
VERSION = "stoneaxe_high_precision_skin_absolute_motion_audit_v5"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not manifest.get("blender_fbx_roundtrip_passed"):
        raise ValueError("Actual Blender FBX round trip must pass before UE import")
    if not manifest.get("centimetre_normalization_passed") or "physical_motion_reference" not in manifest:
        raise ValueError("Explicit identity-root centimetre normalization and physical animation evidence are required")
    if not manifest.get("grip_review_reference"):
        raise ValueError("Missing source grip review reference")
    records = [manifest["body"], manifest["weapon"]["fbx"], manifest["physical_motion_reference"], manifest["centimetre_normalization"]] + manifest["clips"] + list(manifest["textures"].values())
    for record in records:
        source = Path(record["path"]).resolve()
        if not source.is_file() or digest(source) != record["sha256"]:
            raise ValueError("Missing or changed approved export: " + str(source))
    if {item["clip"] for item in manifest["clips"]} != {"Idle", "Move", "Attack", "Hit", "Death"}:
        raise ValueError("Expected five separately exported animation clips")
    if set(manifest["textures"]) != {"base_color", "normal", "roughness", "metallic"}:
        raise ValueError("Four explicit repaired PBR channels required")
    settings = {"version": VERSION, "force_front_x_axis": False, "convert_scene_unit": True, "scale": 1.0,
                "animation_sample_rate": 60, "normal_flip_green_channel": True, "use_high_precision_skin_weights_lod0": True}
    fingerprint = hashlib.sha256((digest(path) + json.dumps(settings, sort_keys=True)).encode()).hexdigest()[:16]
    return manifest, settings, "/Game/ArtPilot/StoneAxeRig/h" + fingerprint


def set_properties(obj, values):
    for name, value in values.items():
        obj.set_editor_property(name, value)


def package_file(unreal, asset_path):
    package = asset_path.split(".")[0]
    if not package.startswith("/Game/ArtPilot/StoneAxeRig/"):
        raise ValueError("Refuse non-pilot package: " + package)
    return Path(unreal.Paths.project_content_dir()).resolve() / (package[len("/Game/"):] + ".uasset")


def load_existing(unreal, path):
    file = package_file(unreal, path)
    if not file.is_file():
        raise FileNotFoundError("Required package absent on disk: " + str(file))
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if asset is None:
        raise RuntimeError("Cannot load persisted asset: " + path)
    return asset


def save_dependency(unreal, asset, destination):
    if asset is None or not asset.get_path_name().startswith(destination + "/"):
        raise ValueError("Generated dependency absent or outside isolated destination")
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError("Generated dependency save failed: " + asset.get_path_name())
    if not package_file(unreal, asset.get_path_name()).is_file():
        raise FileNotFoundError("Save returned without an actual package: " + asset.get_path_name())


def persisted_packages(unreal, destination, required_assets, prior=None):
    library = unreal.EditorAssetLibrary
    if prior is None:
        for asset in required_assets:
            save_dependency(unreal, asset, destination)
        if not library.save_directory(destination, only_if_is_dirty=False, recursive=True):
            raise RuntimeError("Failed to persist isolated generated dependency directory")
        paths = set(library.list_assets(destination, recursive=True, include_folder=False))
        paths.update(asset.get_path_name() for asset in required_assets)
    else:
        if prior["execution_process_id"] == os.getpid():
            raise ValueError("Fresh reopen validation cannot run in the initial import process")
        paths = {record["asset_path"] for record in prior["result"]["disk_dependency_validation"]["files"]}
    records = []
    for path in sorted(paths):
        asset = load_existing(unreal, path)
        file = package_file(unreal, asset.get_path_name())
        records.append({"asset_path": asset.get_path_name(), "package_file": str(file), "bytes": file.stat().st_size,
                        "sha256": digest(file), "class_name": asset.get_class().get_name()})
    if not any(record["class_name"] == "Skeleton" for record in records):
        raise ValueError("No actual persisted Skeleton package in dependency set")
    if prior:
        previous = {record["asset_path"]: record["sha256"] for record in prior["result"]["disk_dependency_validation"]["files"]}
        if any(previous.get(record["asset_path"]) != record["sha256"] for record in records):
            raise ValueError("Persisted dependency changed between import and fresh reopen")
    return {"status": "passed", "validated_in_fresh_process": prior is not None,
            "initial_process_id": prior["execution_process_id"] if prior else os.getpid(),
            "validation_process_id": os.getpid(), "files": records}


def import_task(unreal, source, destination, name, options=None, factory=None):
    path = destination + "/" + name
    lib = unreal.EditorAssetLibrary
    if lib.does_asset_exist(path):
        return lib.load_asset(path), "reused_existing"
    task = unreal.AssetImportTask()
    set_properties(task, {"filename": str(source), "destination_path": destination, "destination_name": name,
                          "replace_existing": False, "automated": True, "save": True, "async_": False})
    if options:
        task.set_editor_property("options", options)
    if factory:
        task.set_editor_property("factory", factory)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    asset = lib.load_asset(path)
    if not asset:
        objects = list(task.get_objects())
        raise RuntimeError("Expected named import missing: " + path + "; returned " + str([obj.get_path_name() for obj in objects]))
    return asset, "imported"


def fbx_options(unreal, kind, skeleton=None):
    options = unreal.FbxImportUI()
    skeletal = kind == "body"
    animated = kind == "animation"
    import_type = unreal.FBXImportType.FBXIT_ANIMATION if animated else (unreal.FBXImportType.FBXIT_SKELETAL_MESH if skeletal else unreal.FBXImportType.FBXIT_STATIC_MESH)
    set_properties(options, {"automated_import_should_detect_type": False, "import_mesh": not animated,
                             "import_as_skeletal": skeletal or animated, "import_animations": animated,
                             "create_physics_asset": False, "import_materials": kind == "weapon", "import_textures": False,
                             "mesh_type_to_import": import_type})
    if skeleton:
        if not skeleton.get_path_name().startswith("/Game/ArtPilot/StoneAxeRig/"):
            raise ValueError("Refuse to modify an unrelated or production skeleton")
        options.set_editor_property("skeleton", skeleton)
    data_name = "anim_sequence_import_data" if animated else ("skeletal_mesh_import_data" if skeletal else "static_mesh_import_data")
    data = options.get_editor_property(data_name)
    set_properties(data, {"import_uniform_scale": 1.0, "convert_scene": True, "convert_scene_unit": True, "force_front_x_axis": False})
    if animated:
        set_properties(data, {"use_default_sample_rate": False, "custom_sample_rate": 60, "import_bone_tracks": True,
                              "animation_length": unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME})
    elif skeletal:
        set_properties(data, {"update_skeleton_reference_pose": False, "use_t0_as_ref_pose": False,
                              "normal_import_method": unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS})
    else:
        set_properties(data, {"combine_meshes": True, "auto_generate_collision": False})
    return options


def pbr_material(unreal, manifest, destination, mesh, read_only=False):
    library = unreal.MaterialEditingLibrary
    if read_only:
        textures = {channel: load_existing(unreal, destination + "/Textures/T_StoneAxe_" + channel) for channel in manifest["textures"]}
        material = load_existing(unreal, destination + "/M_StoneAxe_RepairedPBR")
        return pbr_audit(unreal, material, textures, mesh)
    textures = {}
    for channel, record in manifest["textures"].items():
        texture, status = import_task(unreal, record["path"], destination + "/Textures", "T_StoneAxe_" + channel, factory=unreal.TextureFactory())
        texture.set_editor_property("srgb", channel == "base_color")
        if channel == "normal":
            texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            texture.set_editor_property("flip_green_channel", True)
        elif channel in {"roughness", "metallic"}:
            texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
        unreal.EditorAssetLibrary.save_loaded_asset(texture)
        textures[channel] = texture
    material_path = destination + "/M_StoneAxe_RepairedPBR"
    material = unreal.EditorAssetLibrary.load_asset(material_path) if unreal.EditorAssetLibrary.does_asset_exist(material_path) else None
    if material is None:
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_StoneAxe_RepairedPBR", destination, unreal.Material, unreal.MaterialFactoryNew())
        channels = {"base_color": (unreal.MaterialProperty.MP_BASE_COLOR, "RGB", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR),
                    "normal": (unreal.MaterialProperty.MP_NORMAL, "RGB", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL),
                    "roughness": (unreal.MaterialProperty.MP_ROUGHNESS, "R", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS),
                    "metallic": (unreal.MaterialProperty.MP_METALLIC, "R", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)}
        for index, (channel, (property_name, pin, sampler)) in enumerate(channels.items()):
            node = library.create_material_expression(material, unreal.MaterialExpressionTextureSample, -400, index * 190)
            node.set_editor_property("texture", textures[channel])
            node.set_editor_property("sampler_type", sampler)
            if not library.connect_material_property(node, pin, property_name):
                raise RuntimeError("Could not connect PBR channel " + channel)
    library.set_base_material_usage(material, unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    library.recompile_material(material)
    slots = list(mesh.get_editor_property("materials"))
    if not slots:
        raise ValueError("Skeletal mesh has no material slot")
    for slot in slots:
        slot.set_editor_property("material_interface", material)
    mesh.set_editor_property("materials", slots)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    return pbr_audit(unreal, material, textures, mesh)


def pbr_audit(unreal, material, textures, mesh):
    library = unreal.MaterialEditingLibrary
    if any(slot.get_editor_property("material_interface") != material for slot in mesh.get_editor_property("materials")):
        raise ValueError("Persisted skeletal mesh material assignment differs")
    result = {"material": material.get_path_name(), "skeletal_usage": library.has_material_usage(material, unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH), "channels": {}}
    for channel, property_name in (("base_color", unreal.MaterialProperty.MP_BASE_COLOR), ("normal", unreal.MaterialProperty.MP_NORMAL),
                                   ("roughness", unreal.MaterialProperty.MP_ROUGHNESS), ("metallic", unreal.MaterialProperty.MP_METALLIC)):
        node = library.get_material_property_input_node(material, property_name)
        assigned = node.get_editor_property("texture") if isinstance(node, unreal.MaterialExpressionTextureSample) else None
        if assigned != textures[channel]:
            raise ValueError("Actual material graph does not match expected texture: " + channel)
        texture = textures[channel]
        if bool(texture.get_editor_property("srgb")) != (channel == "base_color"):
            raise ValueError("Persisted texture color space incorrect: " + channel)
        if channel == "normal" and not texture.get_editor_property("flip_green_channel"):
            raise ValueError("Persisted normal map green convention incorrect")
        result["channels"][channel] = {"texture": texture.get_path_name(), "srgb": bool(texture.get_editor_property("srgb")),
                                       "compression": str(texture.get_editor_property("compression_settings")),
                                       "normal_green_flipped": bool(texture.get_editor_property("flip_green_channel")) if channel == "normal" else None}
    return result


def vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def transform(value):
    translation = value.translation
    rotation = value.rotation
    return {"translation_cm": vector(translation), "rotation_xyzw": [float(rotation.x), float(rotation.y), float(rotation.z), float(rotation.w)],
            "scale": vector(value.scale3d)}


def distance(first, second):
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(first, second)))


def skeleton_audit(unreal, mesh, manifest):
    skeleton = mesh.get_editor_property("skeleton")
    reference = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
    if not unreal.AnimPoseExtensions.is_valid(reference):
        raise RuntimeError("UE returned no valid reference pose")
    names = [str(name) for name in unreal.AnimPoseExtensions.get_bone_names(reference)]
    component = unreal.new_object(unreal.SkeletalMeshComponent)
    component.set_skeletal_mesh_asset(mesh)
    bones = {}
    for name in names:
        bones[name] = {"parent": str(component.get_parent_bone(name)),
                       "component": transform(unreal.AnimPoseExtensions.get_bone_pose(reference, name, unreal.AnimPoseSpaces.WORLD)),
                       "local": transform(unreal.AnimPoseExtensions.get_bone_pose(reference, name, unreal.AnimPoseSpaces.LOCAL))}
    lengths = {}
    for parent, child in (("upperarm_r", "lowerarm_r"), ("lowerarm_r", "hand_r"), ("upperarm_l", "lowerarm_l"),
                           ("lowerarm_l", "hand_l"), ("thigh_r", "calf_r"), ("calf_r", "foot_r"), ("thigh_l", "calf_l"), ("calf_l", "foot_l")):
        lengths[parent + "__" + child] = distance(bones[parent]["component"]["translation_cm"], bones[child]["component"]["translation_cm"])
    bounds = mesh.get_bounds()
    basis_errors = {}
    for name, source in manifest.get("reference_bones", {}).items():
        if name not in bones:
            continue
        position = source["head_m"]
        expected = [position[0] * 100, -position[1] * 100, position[2] * 100]
        basis_errors[name] = distance(expected, bones[name]["component"]["translation_cm"])
    return {"skeleton": skeleton.get_path_name(), "bone_count": len(names), "bone_names_match_source": sorted(names) == sorted(manifest["bone_names"]),
            "dimensions_cm": [value * 2 for value in vector(bounds.box_extent)], "bounds_origin_cm": vector(bounds.origin),
            "expected_basis": "Source Blender +X forward, +Z up -> UE +X forward, +Z up with Y handedness reflection; metres multiplied by 100",
            "reference_bone_basis_errors_cm": basis_errors, "maximum_reference_bone_basis_error_cm": max(basis_errors.values(), default=None),
            "maximum_reference_world_scale_error": max(abs(value - 1) for bone in bones.values() for value in bone["component"]["scale"]),
            "bones": bones, "joint_head_distances_cm": lengths, "existing_socket_names": [str(name) for name in unreal.AnimPoseExtensions.get_socket_names(reference)],
            "socket_approved": False, "basis_warning": "Blender-to-UE basis and hand_r mount remain a separate actual game-camera attachment review; no left/right renaming or mirroring is performed."}


def animation_audit(unreal, sequence, clip, skeleton, mesh, source_frames, read_only=False):
    same_skeleton = sequence.get_editor_property("skeleton") == skeleton
    if not read_only:
        sequence.set_editor_property("enable_root_motion", False)
        sequence.set_editor_property("rate_scale", 1.0)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    if sequence.get_editor_property("enable_root_motion") or abs(sequence.get_editor_property("rate_scale") - 1.0) > .0001:
        raise ValueError("Actual saved root-motion/rate configuration differs")
    duration = float(unreal.AnimationLibrary.get_sequence_length(sequence))
    frames = int(unreal.AnimationLibrary.get_num_frames(sequence))
    keys = int(unreal.AnimationLibrary.get_num_keys(sequence))
    options = unreal.AnimPoseEvaluationOptions()
    options.set_editor_property("evaluation_type", unreal.AnimDataEvalType.RAW)
    options.set_editor_property("should_retarget", False)
    options.set_editor_property("extract_root_motion", False)
    options.set_editor_property("optional_skeletal_mesh", mesh)
    samples = []
    for source_frame in source_frames:
        time = source_frame["time_seconds"]
        evaluated = unreal.AnimPoseExtensions.get_anim_pose_at_time(sequence, time, options)
        if not unreal.AnimPoseExtensions.is_valid(evaluated):
            raise RuntimeError("Cannot evaluate actual UE animation pose: " + clip["clip"])
        poses = {name: transform(unreal.AnimPoseExtensions.get_bone_pose(evaluated, name, unreal.AnimPoseSpaces.WORLD)) for name in source_frame["bones"]}
        errors = {}
        for name, expected in source_frame["bones"].items():
            source = expected["head_m"]
            expected_position = [source[0] * 100, -source[1] * 100, source[2] * 100]
            errors[name] = {"position_cm": distance(expected_position, poses[name]["translation_cm"]),
                            "scale": max(abs(left - right) for left, right in zip(expected["scale"], poses[name]["scale"]))}
        samples.append({"frame": source_frame["frame"], "time_seconds": time, "bones": poses,
                        "maximum_absolute_bone_position_error_cm": max(item["position_cm"] for item in errors.values()),
                        "maximum_absolute_bone_scale_error": max(item["scale"] for item in errors.values()), "source_errors": errors})
    roots = [sample["bones"]["root"] for sample in samples]
    root_delta = max(distance(root["translation_cm"], roots[0]["translation_cm"]) for root in roots)
    position_error = max(sample["maximum_absolute_bone_position_error_cm"] for sample in samples)
    scale_error = max(sample["maximum_absolute_bone_scale_error"] for sample in samples)
    return {"clip": clip["clip"], "path": sequence.get_path_name(), "same_skeleton": same_skeleton, "duration_seconds": duration,
            "expected_duration_seconds": clip["duration_seconds"], "duration_error_seconds": abs(duration - clip["duration_seconds"]),
            "source_frame_count": frames, "source_key_count": keys, "derived_source_fps": frames / duration if duration else None,
            "root_translation_delta_cm": root_delta, "enable_root_motion": False, "actual_ue_pose_samples": samples,
            "absolute_motion_validation": {"status": "passed" if position_error < .05 and scale_error < .001 else "failed",
                                            "frames": len(samples), "bones_per_frame": len(source_frames[0]["bones"]),
                                            "maximum_absolute_bone_position_error_cm": position_error, "maximum_absolute_bone_scale_error": scale_error,
                                            "limits": {"position_cm": .05, "scale": .001}},
            "damage_notifies_added": False, "animation_visual_approved": False}


def execute(unreal, manifest, destination, prior=None):
    read_only = prior is not None
    if read_only:
        persisted_packages(unreal, destination, [], prior)
        body, body_status = load_existing(unreal, destination + "/SK_StoneAxe_Pilot"), "reopened_from_disk"
    else:
        body, body_status = import_task(unreal, manifest["body"]["path"], destination, "SK_StoneAxe_Pilot", fbx_options(unreal, "body"), unreal.FbxFactory())
    if not isinstance(body, unreal.SkeletalMesh):
        raise ValueError("Imported body is not a SkeletalMesh")
    skeleton = body.get_editor_property("skeleton")
    if skeleton is None:
        raise ValueError("Body has no actual Skeleton dependency")
    build_settings = unreal.SkeletalMeshEditorSubsystem.get_lod_build_settings(body, 0)
    if not read_only and not build_settings.get_editor_property("use_high_precision_skin_weights"):
        build_settings.set_editor_property("use_high_precision_skin_weights", True)
        unreal.SkeletalMeshEditorSubsystem.set_lod_build_settings(body, 0, build_settings)
    actual_build_settings = unreal.SkeletalMeshEditorSubsystem.get_lod_build_settings(body, 0)
    if not actual_build_settings.get_editor_property("use_high_precision_skin_weights"):
        raise ValueError("Actual LOD0 requires persisted16-bit skin weights; 8-bit quantization exceeds source skin tolerance")
    if not read_only:
        save_dependency(unreal, skeleton, destination)
        save_dependency(unreal, body, destination)
    required_assets = [body, skeleton]
    result = {"body_import_status": body_status, "body": body.get_path_name(), "materials": pbr_material(unreal, manifest, destination, body, read_only),
              "reference_pose": skeleton_audit(unreal, body, manifest), "clips": [], "warnings": [],
              "skin_weight_precision": {"lod": 0, "use_high_precision_skin_weights": True, "verified_from_actual_build_settings": True,
                                        "verified_after_fresh_reopen": read_only, "scope": "This isolated skeletal mesh only; no project defaults or bone-index precision changed"}}
    motion = json.loads(Path(manifest["physical_motion_reference"]["path"]).read_text(encoding="utf-8-sig"))
    for clip in manifest["clips"]:
        if read_only:
            sequence, status = load_existing(unreal, destination + "/Animations/AN_StoneAxe_" + clip["clip"]), "reopened_from_disk"
        else:
            sequence, status = import_task(unreal, clip["path"], destination + "/Animations", "AN_StoneAxe_" + clip["clip"], fbx_options(unreal, "animation", skeleton), unreal.FbxFactory())
        if not isinstance(sequence, unreal.AnimSequence):
            raise ValueError("Imported clip is not an AnimSequence: " + clip["clip"])
        result["clips"].append(animation_audit(unreal, sequence, clip, skeleton, body, motion["clips"][clip["clip"]], read_only) | {"import_status": status})
        required_assets.append(sequence)
    if read_only:
        weapon, weapon_status = load_existing(unreal, destination + "/Weapon/SM_StoneAxe_Fitted"), "reopened_from_disk"
    else:
        weapon, weapon_status = import_task(unreal, manifest["weapon"]["fbx"]["path"], destination + "/Weapon", "SM_StoneAxe_Fitted", fbx_options(unreal, "weapon"), unreal.FbxFactory())
    if not isinstance(weapon, unreal.StaticMesh):
        raise ValueError("Independent fitted axe did not import as a StaticMesh")
    required_assets.append(weapon)
    required_assets.extend(slot.get_editor_property("material_interface") for slot in weapon.get_editor_property("static_materials") if slot.get_editor_property("material_interface") and slot.get_editor_property("material_interface").get_path_name().startswith(destination + "/"))
    result["weapon"] = {"path": weapon.get_path_name(), "import_status": weapon_status, "separate_from_body": True,
                         "dimensions_cm": [value * 2 for value in vector(weapon.get_bounds().box_extent)], "triangles_lod0": weapon.get_num_triangles(0)}
    if not result["reference_pose"]["bone_names_match_source"]:
        result["warnings"].append("imported_bone_names_differ")
    if not result["materials"]["skeletal_usage"]:
        result["warnings"].append("skeletal_material_usage_missing")
    if abs(result["reference_pose"]["dimensions_cm"][2] - 150) > 7.5:
        result["warnings"].append("body_height_not_150cm_check_axes_and_scale")
    basis_error = result["reference_pose"]["maximum_reference_bone_basis_error_cm"]
    if basis_error is None or basis_error > .1:
        result["warnings"].append("reference_bone_basis_differs_from_expected_x_forward_y_reflection")
    if result["reference_pose"]["maximum_reference_world_scale_error"] > .001:
        result["warnings"].append("reference_bone_world_scale_not_identity")
    for clip in result["clips"]:
        if not clip["same_skeleton"] or clip["duration_error_seconds"] > .001 or clip["root_translation_delta_cm"] > .01 or abs(clip["derived_source_fps"] - 60) > .01:
            result["warnings"].append("clip_structure_requires_review:" + clip["clip"])
        if clip["absolute_motion_validation"]["status"] != "passed":
            result["warnings"].append("actual_animated_world_bones_differ_from_dcc:" + clip["clip"])
    result["absolute_motion_validation"] = {"status": "passed" if all(clip["absolute_motion_validation"]["status"] == "passed" for clip in result["clips"]) and result["reference_pose"]["maximum_reference_world_scale_error"] < .001 else "failed",
                                            "frames": sum(clip["absolute_motion_validation"]["frames"] for clip in result["clips"]), "reference_and_each_clip_checked": True,
                                            "source": manifest["physical_motion_reference"]}
    result["actual_skinned_mesh_validation"] = {"status": "pending_actual_component_pose_extraction", "approved": False,
                                                "limitation": "Bone RAW-track equality does not prove actual component skinning; compare actual deformed mesh after pose refresh during assembly review."}
    result["structural_checks_passed"] = not result["warnings"]
    result["disk_dependency_validation"] = persisted_packages(unreal, destination, required_assets, prior)
    result["runtime_integrated"] = False
    result["in_game_visual_approved"] = False
    result["production_approved"] = False
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=os.environ.get("CIVWAR_STONEAXE_MANIFEST"))
    parser.add_argument("--report", default=os.environ.get("CIVWAR_STONEAXE_REPORT"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reopen-only", action="store_true", default=os.environ.get("CIVWAR_STONEAXE_REOPEN_ONLY") == "1")
    parser.add_argument("--prior-import-report", default=os.environ.get("CIVWAR_STONEAXE_PRIOR_IMPORT_REPORT"))
    args, unknown = parser.parse_known_args()
    if not args.manifest:
        raise ValueError("Set CIVWAR_STONEAXE_MANIFEST to the reviewed export delivery_manifest.json")
    path = Path(args.manifest).resolve()
    manifest, settings, destination = read_manifest(path)
    report_path = Path(args.report).resolve() if args.report else path.with_name("unreal_stoneaxe_import_report.json")
    report = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "manifest": str(path), "destination": destination,
              "settings": settings, "dry_run": args.dry_run, "execution_process_id": os.getpid(), "reopen_only": args.reopen_only,
              "production_approved": False, "runtime_integrated": False}
    try:
        if args.dry_run:
            report["status"] = "validated_input_only_no_ue_executed"
        else:
            import unreal
            prior = None
            if args.reopen_only:
                if not args.prior_import_report:
                    raise ValueError("Fresh reopen requires the original persisted import report")
                prior_path = Path(args.prior_import_report).resolve()
                if prior_path == report_path:
                    raise ValueError("Do not overwrite initial persistence evidence with fresh-reopen report")
                prior = json.loads(prior_path.read_text(encoding="utf-8-sig"))
                if prior.get("version") != VERSION or prior.get("destination") != destination or prior.get("dry_run") or prior.get("status") == "failed":
                    raise ValueError("Fresh reopen report must match this exact persisted importer and destination")
            report["result"] = execute(unreal, manifest, destination, prior)
            if prior:
                report["result"]["disk_dependency_validation"]["prior_import_report"] = str(prior_path)
            report["status"] = "isolated_import_fresh_reopen_structural_review_only" if prior else "isolated_import_persisted_requires_fresh_reopen"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("STONEAXE_UE_REPORT " + str(report_path))


if __name__ == "__main__":
    main()
