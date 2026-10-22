from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


module_spec = importlib.util.spec_from_file_location("stoneaxe_export", Path(__file__).with_name("prepare_stoneaxe_export_pilot.py"))
export = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(export)
pose = export.pose


def bone_world(armature, rest=False):
    if rest:
        return {bone.name: armature.matrix_world @ bone.matrix_local for bone in armature.data.bones}
    return {bone.name: armature.matrix_world @ bone.matrix for bone in armature.pose.bones}


def error(actual, expected):
    return {"maximum_head_m": max((matrix.translation - expected[name].translation).length for name, matrix in actual.items()),
            "maximum_matrix_element": max(abs(matrix[row][column] - expected[name][row][column]) for name, matrix in actual.items() for row in range(4) for column in range(4)),
            "selected": {name: {"head_m": list(actual[name].translation), "expected_head_m": list(expected[name].translation)} for name in ("root", "pelvis", "hand_r", "foot_r")}}


def import_fbx_with_original_default_offset(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True, anim_offset=1.0, automatic_bone_orientation=False)
    return [obj for obj in bpy.data.objects if obj not in before]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.source = args.source.resolve()
    args.delivery = args.delivery.resolve()
    args.output = args.output.resolve()
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    source = {}
    for name, end in export.CLIPS.items():
        armature.animation_data.action = bpy.data.actions["CW_StoneAxe_" + name]
        source[name] = {}
        for frame in sorted({1, 22, end}):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            source[name][frame] = bone_world(armature)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body_objects = import_fbx_with_original_default_offset(args.delivery / "body/SK_StoneAxe_Pilot.fbx")
    body_armature = next(obj for obj in body_objects if obj.type == "ARMATURE")
    body_rest = bone_world(body_armature, True)
    result = {"body_matrix_world": export.matrix_rows(body_armature.matrix_world), "clips": []}
    bpy.context.scene.render.fps = 60
    for name, end in export.CLIPS.items():
        imported = import_fbx_with_original_default_offset(args.delivery / ("animations/AN_StoneAxe_" + name + ".fbx"))
        clip_armature = next(obj for obj in imported if obj.type == "ARMATURE")
        action = clip_armature.animation_data.action
        slot = clip_armature.animation_data.action_slot
        record = {"name": name, "action_name": action.name, "action_slot": slot.identifier,
                  "frame_range": list(action.frame_range), "rest_vs_body": error(bone_world(clip_armature, True), body_rest),
                  "clip_matrix_world": export.matrix_rows(clip_armature.matrix_world), "samples": []}
        body_armature.animation_data_create()
        body_armature.animation_data.action = action
        body_armature.animation_data.action_slot = slot
        for frame, expected in source[name].items():
            bpy.context.scene.frame_set(frame + 1)
            bpy.context.view_layer.update()
            record["samples"].append({"source_frame": frame, "import_frame": frame + 1,
                                      "clip_itself_vs_source": error(bone_world(clip_armature), expected),
                                      "body_action_transfer_vs_source": error(bone_world(body_armature), expected),
                                      "clip_object_world": export.matrix_rows(clip_armature.matrix_world),
                                      "body_object_world": export.matrix_rows(body_armature.matrix_world)})
        result["clips"].append(record)
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
        body_armature.animation_data.action = None
        pose.reset_pose(body_armature)
    pose.inspection.helper.write(args.output, result)
    print("FBX_DIAGNOSTIC " + str(args.output))


if __name__ == "__main__":
    main()
