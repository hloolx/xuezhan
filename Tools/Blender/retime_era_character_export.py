"""Re-export existing reviewed frame poses with the declared FPS after FBX import.

Does not regenerate motion, meshes, texture pixels, equipment or review images.
It checks every frozen physical bone sample against the saved source action.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as export


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    source, output = args.source.resolve(), args.output.resolve()
    manifest = read(source/"manifest.json")
    plan = read(source/"input_plan.json")
    output.mkdir(parents=True, exist_ok=False)
    blend = source/(manifest["asset_id"]+"_Actions.blend")
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    rig = bpy.data.objects[manifest["asset_id"]+"_SourceRig"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and
              any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)]
    if not meshes:
        raise ValueError("No original skinned meshes in the saved candidate")
    actions = {name: bpy.data.actions[manifest["asset_id"]+"_"+name] for name in plan["clips"]}
    scene = bpy.context.scene
    previous_fps = scene.render.fps/scene.render.fps_base
    scene.render.fps, scene.render.fps_base = plan["fps"], 1.
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    maximum = 0.
    for clip, samples in manifest["physical_pose_reference"].items():
        rig.animation_data.action = actions[clip]
        for sample in samples:
            scene.frame_set(round(sample["time"]*plan["fps"])+1)
            for name, expected in sample["bones"].items():
                point = (rig.matrix_world @ rig.pose.bones[name].matrix).translation*100
                maximum = max(maximum, sum((x-y)**2 for x, y in zip(point, expected["head_cm"]))**.5)
    if maximum > .001:
        raise ValueError("Saved reviewed frame poses changed: "+str(maximum)+"cm")
    export.FPS, export.CLIPS = plan["fps"], plan["clips"]
    bundle = export.export_bundle(rig, meshes, output, "SK_"+manifest["asset_id"], actions, manifest["textures"])
    # Full-frame references remain the unchanged source of truth.
    bundle["physical_pose_reference"] = manifest["physical_pose_reference"]
    manifest.update(bundle)
    manifest["retime_evidence"] = {
        "source_manifest": export.record(source/"manifest.json"),
        "source_blend": export.record(blend),
        "previous_scene_fps": previous_fps, "export_fps": plan["fps"],
        "actual_saved_pose_max_error_cm": maximum,
        "reviewed_images": [export.record(source/(name+".png")) for name in ("Idle", "Attack", "Death")],
        "motion_reauthored": False, "original_pbr_and_attachments_reused": True,
    }
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"asset": manifest["asset_id"], "output": str(output),
                      "previous_fps": previous_fps, "actual_pose_error_cm": maximum}))


if __name__ == "__main__":
    main()
