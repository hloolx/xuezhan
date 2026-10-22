"""Inspect real Blender-imported USD skin/bone data before action authoring."""
from pathlib import Path
import sys
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from prepare_era_asset import record


def import_and_inspect(source, required_names):
    bpy.ops.wm.usd_import(filepath=str(source))
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("Actual USD did not import exactly one armature")
    rig = rigs[0]
    missing = set(required_names)-set(rig.pose.bones.keys())
    if missing:
        raise ValueError("Actual USD skeleton lacks required named bones: "+str(sorted(missing)))
    rig.animation_data_clear()
    for bone in rig.pose.bones:
        bone.matrix_basis.identity()
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and
              any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)]
    if not meshes:
        raise ValueError("Actual USD has no geometry skinned to its skeleton")
    totals, used, points, bind_errors = [], {}, [], []
    for mesh in meshes:
        groups = {g.index: g.name for g in mesh.vertex_groups if g.name in required_names}
        evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated.to_mesh()
        if len(evaluated_mesh.vertices) != len(mesh.data.vertices):
            raise ValueError("USD bind evaluation changed source topology")
        for index, vertex in enumerate(mesh.data.vertices):
            world = mesh.matrix_world @ vertex.co
            actual = evaluated.matrix_world @ evaluated_mesh.vertices[index].co
            points.append(list(world))
            bind_errors.append((world-actual).length)
            total = 0.
            for weight in vertex.groups:
                if weight.group in groups:
                    total += weight.weight
                    if weight.weight > .01:
                        name = groups[weight.group]
                        used[name] = used.get(name, 0)+1
            totals.append(total)
        evaluated.to_mesh_clear()
    points, totals = np.asarray(points), np.asarray(totals)
    height = float(np.ptp(points, axis=0)[2])
    if not .1 < height < 100:
        raise ValueError("Actual USD body height is invalid")
    needed = {"pelvis", "spine_01", "upperarm_l", "upperarm_r",
              "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r"}
    if needed-set(used):
        raise ValueError("USD weights do not deform the required body regions: "+str(sorted(needed-set(used))))
    if np.count_nonzero(totals < .9) or np.count_nonzero(totals > 1.1):
        raise ValueError("USD contains unweighted or invalidly normalized body vertices")
    if max(bind_errors) > height*.001:
        raise ValueError("USD rest-bone evaluation does not preserve the actual body")
    bone_heads = np.asarray([list((rig.matrix_world @ bone.matrix).translation) for bone in rig.pose.bones])
    if np.ptp(bone_heads, axis=0)[2] < height*.65:
        raise ValueError("USD skeleton is collapsed or outside the body coordinate frame")
    return {"source": record(Path(source)), "status": "actual_imported_skin_structure_passed",
            "bones": len(rig.pose.bones), "actual_weighted_bones": used,
            "vertices": len(points), "weight_sum_range": [float(totals.min()), float(totals.max())],
            "rest_skin_max_vertex_displacement_m": max(bind_errors),
            "body_height_m": height, "bone_bounds_m": [bone_heads.min(0).tolist(), bone_heads.max(0).tolist()],
            "body_bounds_m": [points.min(0).tolist(), points.max(0).tolist()],
            "visual_pose_reviewed": False, "production_approved": False}
