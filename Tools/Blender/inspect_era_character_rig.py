"""Bounded real source rig diagnostics, before deciding a local skin correction."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
import prepare_stoneaxe_pose_pilot as pose

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(args.source), merge_vertices=False, disable_bone_shape=True)
rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
shapes = {bone.custom_shape for bone in rig.pose.bones if bone.custom_shape}
body = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in shapes]
result = {"source": str(args.source), "bones": {}, "meshes": []}
for name in ("root", "pelvis", "thigh_r", "calf_r", "foot_r", "ball_r", "thigh_l", "calf_l", "foot_l", "ball_l"):
    result["bones"][name] = list(pose.world_head(rig, rig.pose.bones[name]))
for mesh in body:
    points = pose.evaluated_world_vertices(mesh)
    low = min(p.z for p in points)
    high = max(p.z for p in points)
    soles = []
    for vertex in mesh.data.vertices:
        if points[vertex.index].z < low+(high-low)*.08:
            weights = {mesh.vertex_groups[g.group].name: g.weight for g in vertex.groups}
            soles.append({"vertex": vertex.index, "position": list(points[vertex.index]), "weights": weights})
    result["meshes"].append({"name": mesh.name, "min_z": low, "max_z": high, "bottom_8_percent": soles})
args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"bones": result["bones"], "body_z": [[m["min_z"], m["max_z"]] for m in result["meshes"]]}))
