"""Import an isolated BeastRider/Mammoth preview bundle, with PBR and five clips."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import math
from pathlib import Path
import sys


def set_properties(obj, properties):
    for key, value in properties.items():
        obj.set_editor_property(key, value)


def quaternion_product(a, b):
    x, y, z, w = a
    xx, yy, zz, ww = b
    return [w*xx+x*ww+y*zz-z*yy, w*yy-x*zz+y*ww+z*xx,
            w*zz+x*yy-y*xx+z*ww, w*ww-x*xx-y*yy-z*zz]


def task(u, source, destination, name, options=None, factory=None):
    path = destination + "/" + name
    if u.EditorAssetLibrary.does_asset_exist(path):
        return u.EditorAssetLibrary.load_asset(path)
    job = u.AssetImportTask()
    set_properties(job, {"filename": str(source), "destination_path": destination,
                         "destination_name": name, "replace_existing": False,
                         "automated": True, "save": True, "async_": False})
    if options:
        job.set_editor_property("options", options)
    if factory:
        job.set_editor_property("factory", factory)
    u.AssetToolsHelpers.get_asset_tools().import_asset_tasks([job])
    result = u.EditorAssetLibrary.load_asset(path)
    if result is None:
        raise RuntimeError("Expected imported asset absent: " + path)
    return result


def options(u, skeleton=None):
    result = u.FbxImportUI()
    animated = skeleton is not None
    set_properties(result, {"automated_import_should_detect_type": False,
                            "import_mesh": not animated, "import_as_skeletal": True,
                            "import_animations": animated, "create_physics_asset": False,
                            "import_materials": False, "import_textures": False,
                            "mesh_type_to_import": u.FBXImportType.FBXIT_ANIMATION if animated else u.FBXImportType.FBXIT_SKELETAL_MESH})
    if skeleton:
        result.set_editor_property("skeleton", skeleton)
    data = result.get_editor_property("anim_sequence_import_data" if animated else "skeletal_mesh_import_data")
    set_properties(data, {"import_uniform_scale": 1, "convert_scene": True,
                          "convert_scene_unit": True, "force_front_x_axis": False})
    if animated:
        set_properties(data, {"use_default_sample_rate": False, "custom_sample_rate": 30,
                              "import_bone_tracks": True,
                              "animation_length": u.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME})
    else:
        set_properties(data, {"update_skeleton_reference_pose": False, "use_t0_as_ref_pose": False,
                              "normal_import_method": u.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS})
    return result


def pbr(u, manifest, destination, mesh, red=False):
    textures = {}
    for channel, record in manifest["textures"].items():
        record = manifest["team_cloth"]["red_base_color"] if red and channel == "base_color" else record
        suffix = "_Red" if red and channel == "base_color" else ""
        tex = task(u, record["path"], destination + "/Textures", "T_" + channel + suffix, factory=u.TextureFactory())
        tex.set_editor_property("srgb", channel == "base_color")
        if channel == "normal":
            tex.set_editor_property("compression_settings", u.TextureCompressionSettings.TC_NORMALMAP)
            tex.set_editor_property("flip_green_channel", True)
        elif channel != "base_color":
            tex.set_editor_property("compression_settings", u.TextureCompressionSettings.TC_MASKS)
        u.EditorAssetLibrary.save_loaded_asset(tex, only_if_is_dirty=False)
        textures[channel] = tex
    lib = u.MaterialEditingLibrary
    material_name = "M_PBR_Red" if red else "M_PBR"
    path = destination + "/" + material_name
    material = u.EditorAssetLibrary.load_asset(path)
    if material is None:
        material = u.AssetToolsHelpers.get_asset_tools().create_asset(
            material_name, destination, u.Material, u.MaterialFactoryNew())
        for i, (channel, tex) in enumerate(textures.items()):
            node = lib.create_material_expression(material, u.MaterialExpressionTextureSample, -400, i * 180)
            node.set_editor_property("texture", tex)
            node.set_editor_property("sampler_type",
                                    u.MaterialSamplerType.SAMPLERTYPE_COLOR if channel == "base_color" else
                                    u.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel == "normal" else
                                    u.MaterialSamplerType.SAMPLERTYPE_MASKS)
            channels = {
                "base_color": [("RGB", u.MaterialProperty.MP_BASE_COLOR)],
                "normal": [("RGB", u.MaterialProperty.MP_NORMAL)],
                "roughness": [("R", u.MaterialProperty.MP_ROUGHNESS)],
                "metallic": [("R", u.MaterialProperty.MP_METALLIC)],
                "metallic_roughness": [("G", u.MaterialProperty.MP_ROUGHNESS), ("B", u.MaterialProperty.MP_METALLIC)],
            }[channel]
            for pin, property_name in channels:
                if not lib.connect_material_property(node, pin, property_name):
                    raise RuntimeError("PBR graph connection failed: " + channel)
    lib.set_base_material_usage(material, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
    lib.recompile_material(material)
    slots = list(mesh.get_editor_property("materials"))
    for slot in slots:
        slot.set_editor_property("material_interface", material)
    mesh.set_editor_property("materials", slots)
    u.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
    return {"material": material.get_path_name(),
            "textures": {k: v.get_path_name() for k, v in textures.items()}}


def run(u, path, output):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not manifest.get("centimetre_normalization_passed"):
        raise ValueError("Centimetre-normalized export did not pass")
    for record in [manifest["body"], *manifest["clips"], *manifest["textures"].values()]:
        if hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Source export hash mismatch")
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    asset = manifest["asset_id"]
    destination = "/Game/ArtPilot/StoneEraPreview/" + asset + "/h" + fingerprint
    mesh = task(u, manifest["body"]["path"], destination, "SK_" + asset, options(u), u.FbxFactory())
    skeleton = mesh.get_editor_property("skeleton")
    settings = u.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh, 0)
    settings.set_editor_property("use_high_precision_skin_weights", True)
    u.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh, 0, settings)
    materials = pbr(u, manifest, destination, mesh)
    team_materials = {}
    if manifest.get("team_cloth"):
        red_material = pbr(u, manifest, destination, mesh, True)
        team_materials = {"Blue": materials["material"], "Red": red_material["material"]}
        slots = list(mesh.get_editor_property("materials"))
        for slot in slots:
            slot.set_editor_property("material_interface", u.EditorAssetLibrary.load_asset(materials["material"]))
        mesh.set_editor_property("materials", slots)
    clips, failures = {}, []
    for row in manifest["clips"]:
        clip = task(u, row["path"], destination + "/Animations", "A_" + row["clip"],
                    options(u, skeleton), u.FbxFactory())
        clip.set_editor_property("enable_root_motion", False)
        clip.set_editor_property("rate_scale", 1.)
        duration = float(u.AnimationLibrary.get_sequence_length(clip))
        if abs(duration - row["duration"]) > .005:
            failures.append("Duration mismatch: " + row["clip"])
        clips[row["clip"]] = {"asset": clip.get_path_name(), "duration": duration}
        pose_reference = manifest.get("physical_pose_reference", {}).get(row["clip"], [])
        errors = []
        evaluate = u.AnimPoseEvaluationOptions()
        evaluate.set_editor_property("evaluation_type", u.AnimDataEvalType.RAW)
        evaluate.set_editor_property("should_retarget", False)
        evaluate.set_editor_property("extract_root_motion", False)
        evaluate.set_editor_property("optional_skeletal_mesh", mesh)
        for sample in pose_reference:
            evaluated = u.AnimPoseExtensions.get_anim_pose_at_time(clip, sample["time"], evaluate)
            for bone_name, expected in sample["bones"].items():
                actual = u.AnimPoseExtensions.get_bone_pose(evaluated, bone_name, u.AnimPoseSpaces.WORLD)
                target = expected["head_cm"]
                delta = ((actual.translation.x - target[0]) ** 2 +
                         (actual.translation.y + target[1]) ** 2 +
                         (actual.translation.z - target[2]) ** 2) ** .5
                errors.append(delta)
        if errors and max(errors) > .1:
            failures.append("Physical animation mismatch " + row["clip"] + ": " + str(max(errors)) + "cm")
        clips[row["clip"]]["physical_max_bone_error_cm"] = max(errors) if errors else None
        u.EditorAssetLibrary.save_loaded_asset(clip, only_if_is_dirty=False)
    reference = u.AnimPoseExtensions.get_reference_pose(skeleton)
    names = [str(x) for x in u.AnimPoseExtensions.get_bone_names(reference)]
    anchor = "saddle_seat" if asset == "Mount_Mammoth" else "weapon_r"
    if anchor not in names:
        failures.append("Required attachment bone absent: " + anchor)
    anchor_transform = u.AnimPoseExtensions.get_bone_pose(reference, anchor, u.AnimPoseSpaces.WORLD)
    anchor_q = anchor_transform.rotation
    inverse_rotation = u.Quat(-anchor_q.x, -anchor_q.y, -anchor_q.z, anchor_q.w).rotator()
    idle_sequence = u.EditorAssetLibrary.load_asset(clips["Idle"]["asset"])
    idle_options = u.AnimPoseEvaluationOptions()
    set_properties(idle_options, {"evaluation_type": u.AnimDataEvalType.RAW,
                                  "should_retarget": False, "extract_root_motion": False,
                                  "optional_skeletal_mesh": mesh})
    idle_pose = u.AnimPoseExtensions.get_anim_pose_at_time(idle_sequence, 0., idle_options)
    idle_anchor = u.AnimPoseExtensions.get_bone_pose(idle_pose, anchor, u.AnimPoseSpaces.WORLD)
    idle_head = None
    if "head" in names:
        reference_head = u.AnimPoseExtensions.get_bone_pose(reference, "head", u.AnimPoseSpaces.WORLD)
        posed_head = u.AnimPoseExtensions.get_bone_pose(idle_pose, "head", u.AnimPoseSpaces.WORLD)
        idle_head = {"reference_z_cm": reference_head.translation.z, "idle_z_cm": posed_head.translation.z,
                     "translation_delta_cm": [posed_head.translation.x - reference_head.translation.x,
                                              posed_head.translation.y - reference_head.translation.y,
                                              posed_head.translation.z - reference_head.translation.z]}
    scale_error = max(abs(c - 1) for name in names
                      for c in (
                          u.AnimPoseExtensions.get_bone_pose(reference, name, u.AnimPoseSpaces.WORLD).scale3d.x,
                          u.AnimPoseExtensions.get_bone_pose(reference, name, u.AnimPoseSpaces.WORLD).scale3d.y,
                          u.AnimPoseExtensions.get_bone_pose(reference, name, u.AnimPoseSpaces.WORLD).scale3d.z))
    if scale_error > .01:
        failures.append("Nonunit reference bone scale")
    for dependency in [skeleton, mesh]:
        u.EditorAssetLibrary.save_loaded_asset(dependency, only_if_is_dirty=False)
    u.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    weapon = None
    weapon_attachment = None
    if manifest.get("weapon"):
        static_options = u.FbxImportUI()
        set_properties(static_options, {"automated_import_should_detect_type": False,
                                        "import_mesh": True, "import_as_skeletal": False,
                                        "import_animations": False, "import_materials": True,
                                        "import_textures": False,
                                        "mesh_type_to_import": u.FBXImportType.FBXIT_STATIC_MESH})
        set_properties(static_options.get_editor_property("static_mesh_import_data"),
                       {"import_uniform_scale": 1., "convert_scene": True,
                        "convert_scene_unit": True, "force_front_x_axis": False,
                        "combine_meshes": True, "auto_generate_collision": False})
        weapon = task(u, manifest["weapon"]["path"], destination + "/Weapon", "SM_StoneSpear",
                      static_options, u.FbxFactory())
        u.EditorAssetLibrary.save_directory(destination + "/Weapon", only_if_is_dirty=False, recursive=True)
        # FBX joint frames can differ from Blender bone display axes. Fit the
        # physical+X spear to three actual evaluated weapon-bone poses.
        motion = json.loads((path.parent / "motion_report.json").read_text(encoding="utf-8"))
        corrections = []
        for clip_name, frame in (("Idle", 1), ("Attack", 13), ("Death", 37)):
            expected = next(r for r in motion if r["clip"] == clip_name and r["frame"] == frame)
            sequence = u.EditorAssetLibrary.load_asset(clips[clip_name]["asset"])
            evaluation = u.AnimPoseEvaluationOptions()
            set_properties(evaluation, {"evaluation_type": u.AnimDataEvalType.RAW,
                                        "should_retarget": False, "extract_root_motion": False,
                                        "optional_skeletal_mesh": mesh})
            evaluated = u.AnimPoseExtensions.get_anim_pose_at_time(sequence, (frame-1)/30., evaluation)
            pose = u.AnimPoseExtensions.get_bone_pose(evaluated, "weapon_r", u.AnimPoseSpaces.WORLD)
            axis = expected["weapon_axis"]
            # Rotation from+X to source axis, converted by reflectionY.
            target = [0., -axis[2], -axis[1], 1. + axis[0]]
            norm = math.sqrt(sum(c*c for c in target))
            target = [c / norm for c in target]
            q = pose.rotation
            correction = quaternion_product([-q.x, -q.y, -q.z, q.w], target)
            corrections.append(correction)
        if any(abs(sum(a*b for a,b in zip(corrections[0], q))) < .9999 for q in corrections[1:]):
            failures.append("Weapon bone/static frame correction is not stable across actual clips")
        corrected = u.Quat(*corrections[0]).rotator()
        weapon_attachment = {"rotation_degrees": [corrected.pitch, corrected.yaw, corrected.roll],
                             "translation_cm": [0, 0, 0], "uniform_scale": 1,
                             "actual_ue_pose_samples": 3}
    bounds = mesh.get_bounds()
    files = []
    for asset_path in u.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False):
        package = Path(u.Paths.project_content_dir()) / (asset_path.split(".")[0][len("/Game/"):] + ".uasset")
        files.append({"asset": asset_path, "file": str(package), "exists": package.is_file()})
        if not package.is_file():
            failures.append("Missing persisted package: " + str(package))
    result = {"asset_id": asset, "status": "imported_preview_pending_gameplay" if not failures else "failed",
              "mesh": mesh.get_path_name(), "skeleton": skeleton.get_path_name(), "clips": clips,
              "materials": materials, "team_materials": team_materials,
              "bone_names": names, "attachment_bone": anchor,
              "attachment_reference": {
                  "translation_cm": [anchor_transform.translation.x, anchor_transform.translation.y, anchor_transform.translation.z],
                  "quaternion_xyzw": [anchor_q.x, anchor_q.y, anchor_q.z, anchor_q.w],
                  "inverse_rotation_degrees": [inverse_rotation.pitch, inverse_rotation.yaw, inverse_rotation.roll]},
              "attachment_idle": {"translation_cm": [idle_anchor.translation.x, idle_anchor.translation.y, idle_anchor.translation.z],
                                  "quaternion_xyzw": [idle_anchor.rotation.x, idle_anchor.rotation.y,
                                                       idle_anchor.rotation.z, idle_anchor.rotation.w]},
              "head_idle": idle_head,
              "reference_scale_max_error": scale_error,
              "dimensions_cm": [bounds.box_extent.x * 2, bounds.box_extent.y * 2, bounds.box_extent.z * 2],
              "bounds_origin_cm": [bounds.origin.x, bounds.origin.y, bounds.origin.z],
              "source_manifest": str(path), "destination": destination, "process_id": os.getpid(),
              "weapon": weapon.get_path_name() if weapon else None,
              "weapon_attachment": weapon_attachment,
              "packages": files, "failures": failures, "production_approved": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise RuntimeError("; ".join(failures))
    return result


if __name__ == "__main__":
    import unreal
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:])
    try:
        run(unreal, args.manifest.resolve(), args.output.resolve())
    finally:
        unreal.SystemLibrary.quit_editor()
