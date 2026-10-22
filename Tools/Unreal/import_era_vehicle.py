"""Import a measured mechanical skeletal bundle without editing activation.

run(unreal, manifest, report) joins a root-leased serial batch. Five clips,
actual slot names, centimetres and bone rotation/position must survive FBX.
Rotation checks matter: a wheel can have the correct centre yet never turn.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).parent))
import import_beast_rider_preview as base
import import_era_assets as static
import fit_stoneaxe_socket as fit

VERSION = "actual_mechanical_five_clips_cm_v2"
CLIPS = {"Idle", "Move", "Attack", "Hit", "Death"}
KEYS = {"Unit_ArmoredCar", "Unit_MainTank", "Unit_Mech"}


def checked(record):
    path = static.resolve(record["path"])
    if static.sha(path) != record["sha256"]:
        raise ValueError("Mechanical source changed: "+str(path))
    return path


def options(u, skeleton=None):
    settings = base.options(u, skeleton)
    if skeleton:
        settings.get_editor_property("anim_sequence_import_data").set_editor_property("custom_sample_rate", 60)
    return settings


def evaluate(u, mesh, animation, time):
    settings = u.AnimPoseEvaluationOptions()
    base.set_properties(settings, {"evaluation_type": u.AnimDataEvalType.RAW,
                                  "should_retarget": False, "extract_root_motion": False,
                                  "optional_skeletal_mesh": mesh})
    value = u.AnimPoseExtensions.get_anim_pose_at_time(animation, time, settings)
    if not u.AnimPoseExtensions.is_valid(value):
        raise ValueError("Actual mechanical animation pose is invalid")
    return value


def rotation_error_degrees(first, second):
    # Scale has its own strict check. Do not interpret a scaled identity
    # matrix as a 119-degree rotation when reporting an FBX unit mismatch.
    first_scale = [math.sqrt(sum(first[row][column]**2 for row in range(3))) for column in range(3)]
    second_scale = [math.sqrt(sum(second[row][column]**2 for row in range(3))) for column in range(3)]
    if min(first_scale+second_scale) <= 0:
        raise ValueError("Zero-scale mechanical rotation")
    trace = sum(first[row][column]*second[row][column]/first_scale[column]/second_scale[column]
                for row in range(3) for column in range(3))
    return math.degrees(math.acos(max(-1., min(1., (trace-1.)/2))))


def materials(u, mesh, rows, destination):
    canonical = lambda name: name.replace(".", "_")
    specs = {canonical(row["slot_name"]): row for row in rows}
    if len(specs) != len(rows):
        raise ValueError("Mechanical material names collide")
    slots = list(mesh.get_editor_property("materials"))
    actual, seen = [], set()
    for index, slot in enumerate(slots):
        name = str(slot.get_editor_property("imported_material_slot_name"))
        key = canonical(name)
        if key not in specs or key in seen:
            raise ValueError("Unexpected actual mechanical material slot: "+name)
        seen.add(key)
        row = specs[key]
        blue = static.material(u, row, destination+"/Materials")
        red = static.material(u, row, destination+"/Materials", red=True) if row.get("team_cloth") else blue
        for mat in (blue, red):
            u.MaterialEditingLibrary.set_base_material_usage(mat, u.MaterialUsage.MATUSAGE_SKELETAL_MESH, True)
            errors = list(u.MaterialEditingLibrary.recompile_material(mat))
            if errors:
                raise ValueError("Mechanical skeletal shader failed: "+str(errors))
            u.EditorAssetLibrary.save_loaded_asset(mat, only_if_is_dirty=False)
        slot.set_editor_property("material_interface", blue)
        actual.append({"slot": index, "name": name, "path": blue.get_path_name(), "red_path": red.get_path_name()})
    if seen != set(specs):
        raise ValueError("Prepared mechanical material slot was lost")
    mesh.set_editor_property("materials", slots)
    return actual


def run(u, manifest_path, report_path):
    manifest_path = static.resolve(manifest_path)
    manifest = static.read(manifest_path)
    if manifest["asset_id"] not in KEYS or manifest["status"] != "five_mechanical_clips_prepared_pending_unreal":
        raise ValueError("Expected an actual mechanical unit bundle")
    if {row["id"] for row in manifest["clips"]} != CLIPS or len(manifest["clips"]) != 5:
        raise ValueError("Five distinct mechanical clips are required")
    definition = next(row for row in static.read(static.ROOT/"Content/Data/Units.json")
                      if row["VisualKey"] == manifest["asset_id"])
    if abs(definition["AttackWindup"]-manifest["contact_time"]) > .001 or abs(
            definition["AttackInterval"]-manifest["attack_interval"]) > .001:
        raise ValueError("Mechanical animation disagrees with authoritative timing")
    for record in (manifest["body"], manifest["physical_reference"], *manifest["clips"]):
        checked(record)
    for row in manifest["materials"]:
        for record in row["textures"].values():
            checked(record)
        if row.get("team_cloth"):
            checked(row["team_cloth"]["mask"])
            checked(row["team_cloth"]["red_base_color"])
            if row["team_cloth"]["unmasked_pixels_changed"] != 0:
                raise ValueError("Team repaint changed non-team source pixels")
    fingerprint = hashlib.sha256((static.sha(manifest_path)+VERSION).encode()).hexdigest()[:16]
    destination = "/Game/ArtPilot/EraVehicles/"+manifest["asset_id"]+"/h"+fingerprint
    mesh = base.task(u, manifest["body"]["path"], destination, "SK_"+manifest["asset_id"], options(u), u.FbxFactory())
    skeleton = mesh.get_editor_property("skeleton")
    build = u.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh, 0)
    build.set_editor_property("use_high_precision_skin_weights", True)
    u.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh, 0, build)
    material_rows = materials(u, mesh, manifest["materials"], destination)
    reference = u.AnimPoseExtensions.get_reference_pose(skeleton)
    bone_names = [str(name) for name in u.AnimPoseExtensions.get_bone_names(reference)]
    if set(bone_names) != set(manifest["bind_bone_matrices_m"]) or len(bone_names) != manifest["bone_count"]:
        raise ValueError("Actual mechanical bone set changed")
    if manifest["muzzle_bone"] not in bone_names:
        raise ValueError("Measured mechanical muzzle bone was lost")
    actual_bind, expected_bind, reference_error, reference_scale_error = {}, {}, 0., 0.
    for name in bone_names:
        transform = u.AnimPoseExtensions.get_bone_pose(reference, name, u.AnimPoseSpaces.WORLD)
        actual_bind[name] = fit.ue_transform(transform)
        reference_scale_error = max(reference_scale_error, max(abs(value-1.) for value in fit.ue_vector(transform.scale3d)))
        expected_bind[name] = fit.blender_transform_to_ue(manifest["bind_bone_matrices_m"][name])
        reference_error = max(reference_error, fit.distance([actual_bind[name][i][3] for i in range(3)],
                                                           [expected_bind[name][i][3] for i in range(3)]))
    if reference_error > .1:
        raise ValueError("Actual reference joints differ by %.6fcm" % reference_error)
    if reference_scale_error > .005:
        raise ValueError("Reference bones must use unit scale; error %.6f" % reference_scale_error)
    # Keep referenced packages valid even if a later pose check reports a
    # genuine animation defect.
    for obj in (mesh, skeleton):
        u.EditorAssetLibrary.save_loaded_asset(obj, only_if_is_dirty=False)
    expected_inverse = {name: fit.inverse(value) for name, value in expected_bind.items()}
    actual_inverse = {name: fit.inverse(value) for name, value in actual_bind.items()}
    samples = static.read(checked(manifest["physical_reference"]))
    clips, clip_reports, muzzle_samples = {}, {}, {}
    for row in manifest["clips"]:
        name = row["id"]
        animation = base.task(u, row["path"], destination+"/Animations", "AN_"+name, options(u, skeleton), u.FbxFactory())
        animation.set_editor_property("enable_root_motion", False)
        animation.set_editor_property("rate_scale", 1.)
        duration = float(u.AnimationLibrary.get_sequence_length(animation))
        if abs(duration-row["duration"]) > .005 or animation.get_editor_property("skeleton") != skeleton:
            raise ValueError("Actual mechanical duration or skeleton mismatch")
        clips[name] = animation
        max_position, max_angle, max_scale, count = 0., 0., 0., 0
        if len(samples[name]) != row["frames"]:
            raise ValueError("Mechanical physical reference is incomplete")
        for sample in samples[name]:
            pose = evaluate(u, mesh, animation, sample["time"])
            for bone, expected in sample["bones"].items():
                value = u.AnimPoseExtensions.get_bone_pose(pose, bone, u.AnimPoseSpaces.WORLD)
                actual_world = fit.ue_transform(value)
                expected_world = fit.blender_transform_to_ue(expected["world_matrix_m"])
                actual_delta = fit.multiply(actual_world, actual_inverse[bone])
                expected_delta = fit.multiply(expected_world, expected_inverse[bone])
                max_position = max(max_position, fit.distance(fit.ue_vector(value.translation),
                    [expected_world[i][3] for i in range(3)]))
                max_angle = max(max_angle, rotation_error_degrees(actual_delta, expected_delta))
                max_scale = max(max_scale, max(abs(component-1.) for component in fit.ue_vector(value.scale3d)))
                count += 1
        if max_position > .1 or max_angle > .1 or max_scale > .005:
            raise ValueError(f"{name} actual bones differ: {max_position}cm / {max_angle}deg / {max_scale}scale")
        clip_reports[name] = {"asset": animation.get_path_name(), "duration": duration,
                              "physical_samples": count, "max_position_error_cm": max_position,
                              "max_rotation_error_degrees": max_angle, "max_scale_error": max_scale}
        u.EditorAssetLibrary.save_loaded_asset(animation, only_if_is_dirty=False)
    for label, clip, time in (("ready", "Idle", 0.), ("release", "Attack", manifest["contact_time"])):
        pose = evaluate(u, mesh, clips[clip], time)
        muzzle_samples[label] = fit.ue_transform(u.AnimPoseExtensions.get_bone_pose(
            pose, manifest["muzzle_bone"], u.AnimPoseSpaces.WORLD))
    bounds = mesh.get_bounds()
    low = [bounds.origin.x-bounds.box_extent.x, bounds.origin.y-bounds.box_extent.y, bounds.origin.z-bounds.box_extent.z]
    high = [bounds.origin.x+bounds.box_extent.x, bounds.origin.y+bounds.box_extent.y, bounds.origin.z+bounds.box_extent.z]
    source = manifest["bounds_blender_cm"]
    expected_low = [source["minimum"][0], -source["maximum"][1], source["minimum"][2]]
    expected_high = [source["maximum"][0], -source["minimum"][1], source["maximum"][2]]
    bounds_error = max(abs(a-b) for a, b in zip(low+high, expected_low+expected_high))
    if bounds_error > .1:
        raise ValueError("Actual imported mechanical dimensions differ by %.6fcm" % bounds_error)
    for obj in (mesh, skeleton):
        u.EditorAssetLibrary.save_loaded_asset(obj, only_if_is_dirty=False)
    u.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    runtime = {"asset_id": manifest["asset_id"], "kind": "skeletal_unit", "enabled": False,
               "default_runtime_enabled": False, "preview_enabled": False, "production_approved": False,
               "height_cm": high[2]-min(low[2], 0.), "reference_move_speed": manifest["reference_move_speed_cm_s"],
               "contact_time": manifest["contact_time"], "attack_style": manifest["attack_style"],
               "vehicle": manifest["vehicle"], "muzzle_part": "body", "muzzle_socket": manifest["muzzle_bone"],
               "parts": [{"id": "body", "skeletal_mesh": mesh.get_path_name(), "translation_cm": [0, 0, 0],
                          "rotation_degrees": [0, 0, 0], "uniform_scale": 1,
                          "animations": {key: clip.get_path_name() for key, clip in clips.items()},
                          "team_materials": [{key: row[key] for key in ("slot", "path", "red_path")} for row in material_rows]}],
               "attachments": []}
    result = {"status": "imported_pending_gameplay", "asset_id": manifest["asset_id"], "process_id": os.getpid(),
              "source_manifest": str(manifest_path), "source_manifest_sha256": static.sha(manifest_path),
              "destination": destination, "mesh": mesh.get_path_name(), "skeleton": skeleton.get_path_name(),
              "bone_names": bone_names, "reference_position_error_cm": reference_error,
              "reference_unit_scale_error": reference_scale_error, "clips": clip_reports,
              "materials": material_rows, "bounds_cm": {"minimum": low, "maximum": high, "max_error_cm": bounds_error},
              "muzzle_samples": muzzle_samples, "packages": static.snapshot(u, destination),
              "runtime_entry": runtime, "failures": [], "production_approved": False}
    static.write(report_path, result)
    return result


def execute(manifest_path, report_path):
    import unreal
    try:
        return run(unreal, manifest_path, report_path)
    except Exception as error:
        static.write(report_path, {"status": "failed", "error": str(error), "traceback": traceback.format_exc(),
                                   "source_manifest": str(manifest_path), "process_id": os.getpid()})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    execute(arguments.manifest, arguments.output)
