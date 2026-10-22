"""Create mounted-unit horse clips from the actual FBX bind pose and original PBR."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as common
import prepare_era_character as character

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
FPS = 60
CLIPS = {"Idle": 2., "Move": .6, "Attack": 1.5, "Hit": .5, "Death": 1.4}
SPEED = 2.30


def source_material(body, textures):
    material = bpy.data.materials.new("Warhorse_OriginalPBR")
    material.use_nodes = True
    tree = material.node_tree
    shader = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    for channel, rec in textures.items():
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(rec["path"], check_existing=False)
        if channel != "base_color":
            node.image.colorspace_settings.name = "Non-Color"
        if channel == "base_color":
            tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
        elif channel == "normal":
            normal = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(node.outputs["Color"], normal.inputs["Color"])
            tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
        elif channel == "metallic_roughness":
            split = tree.nodes.new("ShaderNodeSeparateColor")
            tree.links.new(node.outputs["Color"], split.inputs["Color"])
            tree.links.new(split.outputs["Green"], shader.inputs["Roughness"])
            tree.links.new(split.outputs["Blue"], shader.inputs["Metallic"])
    body.data.materials.clear()
    body.data.materials.append(material)
    return material


def stride(phase):
    """Constant-speed stance plus C1 Hermite swing; endpoint velocity matches."""
    duration = CLIPS["Move"]
    distance = SPEED * duration / 2
    if phase < .5:
        return distance / 2 - SPEED * phase * duration, 0.
    s = (phase - .5) * 2
    start, end = -distance / 2, distance / 2
    tangent = -SPEED * duration / 2
    x = (2*s**3-3*s*s+1)*start + (s**3-2*s*s+s)*tangent
    x += (-2*s**3+3*s*s)*end + (s**3-s*s)*tangent
    return x, .12 * math.sin(math.pi*s)**2


def build(source_blend, source_pbr, output):
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(source_blend))
    scene = bpy.context.scene
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    scene.render.fps = FPS
    rig, = [o for o in scene.objects if o.type == "ARMATURE"]
    body, = [o for o in scene.objects if o.type == "MESH" and
             any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
    rig.animation_data_clear()
    common.reset(rig)
    points = common.world_vertices(body)
    low, high = points.min(axis=0), points.max(axis=0)
    forward = (rig.matrix_world @ rig.data.bones["tripo::Head_3"].head_local -
               rig.matrix_world @ rig.data.bones["tripo::Spine_0"].head_local)
    yaw = -math.atan2(forward.y, forward.x)
    transform = Matrix.Rotation(yaw, 4, "Z") @ Matrix.Scale(1.75/(high[2]-low[2]), 4)
    transform = Matrix.Translation((0, 0, -low[2]*1.75/(high[2]-low[2]))) @ transform
    for obj in list(scene.objects):
        if obj.parent is None:
            obj.matrix_world = transform @ obj.matrix_world
    rig.name, body.name = "Warhorse_SourceRig", "Warhorse_SourceBody"
    mapping = {b.name: "h_%02d" % i for i, b in enumerate(rig.data.bones)}
    hip_names = ["tripo::Spine_5", "bone_15", "bone_19", "bone_23"]
    original_chains = [[hip, *[f"tripo::{i}_{side}_Limb_{joint}" for joint in range(3)]]
                       for hip, (i, side) in zip(hip_names, [(0, "Left"), (0, "Right"), (1, "Left"), (1, "Right")])]
    chains = [[mapping[n] for n in chain] for chain in original_chains]
    for b in list(rig.data.bones):
        old = b.name
        b.name = mapping[old]
        if body.vertex_groups.get(old):
            body.vertex_groups[old].name = b.name
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    bpy.context.view_layer.update()
    points = common.world_vertices(body)
    body.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons([Vector(v) for v in points],
                              [list(t.vertices) for t in body.data.loop_triangles], all_triangles=True)
    centre = rig.matrix_world @ rig.data.bones[mapping["tripo::Spine_2"]].head_local
    seat_samples = []
    for dx, dy in ((0, 0), (-.025, -.02), (.025, -.02), (-.025, .02), (.025, .02)):
        hit = bvh.ray_cast(Vector((centre.x+dx, dy, 3.)), Vector((0, 0, -1)))
        if hit[0] is None:
            raise ValueError("Saddle ray missed the actual horse surface")
        seat_samples.append(list(hit[0]))
    seat = Vector((centre.x, 0., sum(p[2] for p in seat_samples)/len(seat_samples)+.005))
    if not 1.0 < seat.z < 1.65:
        raise ValueError("Actual saddle surface outside physical horse back")
    common.select([rig])
    bpy.ops.object.mode_set(mode="EDIT")
    saddle = rig.data.edit_bones.new("saddle_seat")
    saddle.head = rig.matrix_world.inverted() @ seat
    saddle.tail = saddle.head + Vector((0, 0, .06))
    saddle.parent = rig.data.edit_bones[mapping["tripo::Spine_2"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.pose.bones["saddle_seat"].rotation_mode = "QUATERNION"
    rest = {b.name: rig.matrix_world @ b.matrix for b in rig.pose.bones}
    feet, patches = [], []
    ankle_xy = np.array([rest[chain[-1]].translation[:2] for chain in chains])
    distances = np.linalg.norm(points[:, None, :2]-ankle_xy[None, :, :], axis=2)
    nearest_hoof = distances.argmin(axis=1)
    for foot_index, chain in enumerate(chains):
        ankle = rest[chain[-1]].translation
        # A vertex belongs to exactly one hoof, even where broad generated
        # hooves overlap neighboring selection radii.
        near = (nearest_hoof == foot_index) & (distances[:, foot_index] < .24)
        indices = np.flatnonzero(near & (points[:, 2] < .16))
        if len(indices) < 8:
            raise ValueError("Cannot identify real hoof surface")
        minimum = float(points[indices, 2].min())
        sole = indices[points[indices, 2] < minimum+.008]
        # Local rigid hoof weights preserve flat soles without editing geometry.
        for vi in indices:
            v = body.data.vertices[int(vi)]
            patches.append({"vertex": int(vi), "before": {body.vertex_groups[g.group].name:g.weight for g in v.groups},
                            "after": chain[-1]})
            for group in list(v.groups):
                body.vertex_groups[group.group].remove([int(vi)])
            body.vertex_groups[chain[-1]].add([int(vi)], 1., "REPLACE")
        feet.append({"indices": indices, "sole": sole, "min_z": minimum, "ankle": ankle.copy()})
    inverse = rig.matrix_world.inverted()
    root_name = mapping["tripo::Root"]
    root_shift = Vector((0, 0, -.10))
    rig.animation_data_create()
    actions, diagnostics = {}, []

    def pose(clip, t):
        common.reset(rig)
        world_root = rest[root_name].copy()
        world_root.translation += root_shift
        rig.pose.bones[root_name].matrix = inverse @ world_root
        bpy.context.view_layer.update()
        if clip == "Death":
            p = character.smooth(t / 1.08)
            centre = Vector((0, 0, .65))
            fall = Matrix.Translation((0, .10*p, -.55*p))
            fall = fall @ Matrix.Translation(centre) @ Matrix.Rotation(math.radians(78)*p, 4, "X") @ Matrix.Translation(-centre)
            world_root = fall @ world_root
            rig.pose.bones[root_name].matrix = inverse @ world_root
            bpy.context.view_layer.update()
            world_root.translation.z -= float(common.world_vertices(body)[:, 2].min())
            rig.pose.bones[root_name].matrix = inverse @ world_root
            bpy.context.view_layer.update()
            return {"death_fraction": p, "minimum_z": float(common.world_vertices(body)[:, 2].min())}
        goals, phases = [], []
        for i, foot in enumerate(feet):
            phase = (t/CLIPS["Move"]+(0 if i in (0, 3) else .5)) % 1.
            x, lift = stride(phase) if clip == "Move" else (0., 0.)
            goal = foot["ankle"] + Vector((x, 0, lift-foot["min_z"]))
            goals.append(goal)
            phases.append({"phase": phase, "lift": lift, "support": phase < .5 or clip != "Move"})
        residuals = []
        for _ in range(3):
            for chain, goal in zip(chains, goals):
                initial = [rest[n].translation.copy() for n in chain]
                solved, residual = common.solve_chain([p+root_shift for p in initial], goal)
                residuals.append(residual)
                for j, name in enumerate(chain):
                    matrix = rest[name].copy()
                    if j < len(chain)-1:
                        rotation = (initial[j+1]-initial[j]).rotation_difference(solved[j+1]-solved[j])
                        matrix = rotation.to_matrix().to_4x4() @ matrix
                    matrix.translation = solved[j]
                    rig.pose.bones[name].matrix = inverse @ matrix
                    bpy.context.view_layer.update()
            actual = common.world_vertices(body)
            for i, foot in enumerate(feet):
                goals[i].z += phases[i]["lift"]-float(actual[foot["indices"], 2].min())
        head_name = mapping["tripo::Head_1"]
        head = rig.pose.bones[head_name]
        matrix = rig.matrix_world @ head.matrix
        amplitude = 1.5*math.sin(math.tau*t/CLIPS[clip]) if clip in ("Idle", "Move") else 0.
        if clip == "Attack":
            amplitude = -5.*math.sin(math.pi*min(t/.8, 1)) if t < .8 else 0.
        if clip == "Hit":
            amplitude = 7.*math.sin(math.pi*t/CLIPS[clip])
        matrix = Matrix.Translation(matrix.translation) @ Matrix.Rotation(math.radians(amplitude), 4, "Y") @ Matrix.Translation(-matrix.translation) @ matrix
        head.matrix = inverse @ matrix
        bpy.context.view_layer.update()
        actual = common.world_vertices(body)
        return {"feet": [dict(phases[i], min_z=float(actual[f["indices"], 2].min()),
                              sole_centroid=actual[f["sole"]].mean(axis=0).tolist()) for i, f in enumerate(feet)],
                "ik_max_error_m": max(residuals)}

    for clip, duration in CLIPS.items():
        action = bpy.data.actions.new("Warhorse_"+clip)
        action.use_fake_user = True
        rig.animation_data.action = action
        actions[clip] = action
        for frame in range(1, round(duration*FPS)+2):
            scene.frame_set(frame)
            data = pose(clip, (frame-1)/FPS)
            common.keyed(rig, frame)
            diagnostics.append({"clip": clip, "frame": frame, "time": (frame-1)/FPS, **data})
    textures = character.exact_source_textures({"asset_id": "Mount_Warhorse",
                                               "source_rig": {"path": str(source_pbr)}}, output)
    source_material(body, textures)
    common.FPS, common.CLIPS = FPS, CLIPS
    bundle = common.export_bundle(rig, [body], output, "SK_Warhorse", actions, textures)
    rig.animation_data.action = actions["Idle"]
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"Warhorse_motion.blend"))
    if scene.world is None:
        scene.world = bpy.data.worlds.new("WarhorsePreviewWorld")
    common.render.render_setup(samples=8)
    for label, clip, frame in (("Idle", "Idle", 1), ("Move", "Move", 10), ("Death", "Death", 85)):
        rig.animation_data.action = actions[clip]
        scene.frame_set(frame)
        common.render.render_view(output/(label+".png"), [body], (1, -1.4, .25), size=640)
    common.save(output/"hoof_weight_patch.json", patches)
    common.save(output/"motion_diagnostics.json", diagnostics)
    common.save(output/"manifest.json", {
        "asset_id": "Mount_Warhorse", "source_bind": common.record(source_blend),
        "source_pbr": common.record(source_pbr), "status": "actual_motion_pending_gameplay",
        "source_height_cm": 175, "bone_rename": mapping, "bones": len(rig.data.bones),
        "saddle_bone": "saddle_seat", "saddle_reference_world_m": list(seat),
        "saddle_surface_samples_m": seat_samples, "reference_move_speed_cm_s": SPEED*100,
        "attack_contact_seconds": .4, "attack_duration_seconds": 1.5,
        "production_approved": False, **bundle})
    print("WARHORSE_MOTION_COMPLETE " + str(output))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source-blend", type=Path, required=True)
    p.add_argument("--source-pbr", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(sys.argv[sys.argv.index("--")+1:])
    build(a.source_blend.resolve(), a.source_pbr.resolve(), a.output.resolve())
