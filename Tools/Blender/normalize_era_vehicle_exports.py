"""Re-export existing measured vehicle poses in explicit centimetres.

UE FBX imports a metre armature's reference root at scale 100 but its
animation root at scale 1. Bake centimetres into mesh/rest/pose translations;
preserve the source geometry, UVs, weights, materials, and every measured pose.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).parent))
import bake_era_vehicle_actions as author


def normalize(manifest_path):
    original = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if author.record(original["blend"]["path"])["sha256"] != original["blend"]["sha256"]:
        raise ValueError("Authored scene changed")
    output = Path(manifest_path).parent.with_name("candidate_03_cm")
    output.mkdir(exist_ok=True)
    if (output / "vehicle_manifest.json").exists():
        raise ValueError("Completed normalized candidate is immutable")
    bpy.ops.wm.open_mainfile(filepath=original["blend"]["path"])
    scene = bpy.context.scene
    source_body = bpy.data.objects["SK_"+original["asset_id"]]
    source_rig = next(mod.object for mod in source_body.modifiers if mod.type == "ARMATURE")
    source_rig.name = "SourceArmature"
    rig = source_rig.copy()
    rig.data = source_rig.data.copy()
    rig.animation_data_clear()
    rig.parent = None
    rig.matrix_world = Matrix.Identity(4)
    rig.data.transform(Matrix.Scale(100, 4) @ source_rig.matrix_world)
    rig.name = "Armature"
    scene.collection.objects.link(rig)
    body = source_body.copy()
    body.data = source_body.data.copy()
    body.data.transform(Matrix.Scale(100, 4) @ source_body.matrix_world)
    body.animation_data_clear()
    body.parent = None
    body.matrix_world = Matrix.Identity(4)
    for modifier in body.modifiers:
        if modifier.type == "ARMATURE":
            modifier.object = rig
    scene.collection.objects.link(body)
    rig.animation_data_create()
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.matrix_basis = Matrix.Identity(4)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = .01
    scene.render.fps = 60
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    body_path = output / ("SK_"+original["asset_id"]+".fbx")
    author.export(bpy, rig, body, body_path)
    reference = json.loads(Path(original["physical_reference"]["path"]).read_text(encoding="utf-8"))
    clips, maximum_error = [], 0.
    for clip in original["clips"]:
        samples = reference[clip["id"]]
        action = bpy.data.actions.new("CM_"+original["asset_id"]+"_"+clip["id"])
        action.use_fake_user = True
        rig.animation_data.action = action
        scene.frame_start, scene.frame_end = 0, clip["frames"]-1
        previous = {}
        for frame, sample in enumerate(samples):
            scene.frame_set(frame)
            desired = {}
            for name, row in sample["bones"].items():
                desired[name] = Matrix(row["world_matrix_m"])
                desired[name].translation *= 100
            for bone in rig.pose.bones:
                parent = {"parent_matrix": desired[bone.parent.name],
                          "parent_matrix_local": bone.parent.bone.matrix_local} if bone.parent else {}
                bone.matrix_basis = bone.bone.convert_local_to_pose(
                    desired[bone.name], bone.bone.matrix_local, invert=True, **parent)
                if bone.name in previous and previous[bone.name].dot(bone.rotation_quaternion) < 0:
                    bone.rotation_quaternion.negate()
                previous[bone.name] = bone.rotation_quaternion.copy()
                for prop in ("location", "rotation_quaternion", "scale"):
                    bone.keyframe_insert(prop, frame=frame, group=bone.name)
            bpy.context.view_layer.update()
            maximum_error = max(maximum_error, max(
                max(abs(bone.matrix[row][col]-desired[bone.name][row][col])
                    for row in range(4) for col in range(4)) for bone in rig.pose.bones))
        if maximum_error > .001:
            raise ValueError("Unit conversion changed physical poses: "+str(maximum_error))
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = "LINEAR"
        path = output / ("AN_"+original["asset_id"]+"_"+clip["id"]+".fbx")
        author.export(bpy, rig, body, path, True)
        clips.append(dict(clip, **author.record(path)))
    bpy.ops.wm.save_as_mainfile(filepath=str(output / (original["asset_id"]+"_cm.blend")))
    result = copy.deepcopy(original)
    result.update(body=author.record(body_path), clips=clips,
                  blend=author.record(output/(original["asset_id"]+"_cm.blend")))
    result["unit_normalization"] = {
        "source_manifest": author.record(manifest_path), "tool": author.record(__file__),
        "scene_unit_scale": .01, "mesh_and_rest_translation_factor": 100,
        "pose_count": sum(len(rows) for rows in reference.values()),
        "maximum_replayed_matrix_error_cm": maximum_error,
        "original_physical_reference_unchanged": True,
        "geometry_uv_weights_materials": "copied exactly; vertex coordinates multiplied by 100"}
    author.write(output / "vehicle_manifest.json", result)
    print(json.dumps({"asset_id": result["asset_id"], "status": "cm_export_complete",
                      "maximum_pose_error_cm": maximum_error}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    for entry in json.loads(args.plan.read_text(encoding="utf-8"))["entries"]:
        normalize(entry["manifest"])
