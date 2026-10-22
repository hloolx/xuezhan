"""Author a new, explicitly preview-quality mammoth animation delivery.

The original parent-corrected 33-joint model is immutable. This makes a new
centimetre-normalized export with measured four-foot IK, a real saddle bone,
five in-place clips, and numeric/visual evidence for the gameplay preview.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).parent))
import prepare_tripo_character as render

ROOT = Path(__file__).resolve().parents[2]
BRANCH = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/mammoth_v01"
SOURCE = BRANCH / "rig_transfer_parent_02/Mount_Mammoth_parent_only.glb"
SOURCE_SHA = "65c1f2291b1917cafa97ec3b9be3181c7ca9f51a8360330f66e1762ca867effb"
FPS = 30
CLIPS = {"Idle": 2.0, "Move": .5, "Attack": 1.6, "Hit": .5, "Death": 1.2}
CHAINS = [
    ["tripo::0_Left_Limb_0", "tripo::0_Left_Limb_1", "tripo::0_Left_Limb_2"],
    ["tripo::1_Right_Limb_0", "tripo::1_Right_Limb_1", "tripo::1_Right_Limb_2"],
    ["tripo::1_Left_Limb_0", "bone_23", "bone_24", "bone_25"],
    ["tripo::1_Left_Limb_1", "tripo::1_Left_Limb_2", "tripo::1_Left_Limb_3"],
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(path):
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def select(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def world_vertices(body):
    obj = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = obj.to_mesh()
    result = np.asarray([list(obj.matrix_world @ vertex.co) for vertex in mesh.vertices])
    obj.to_mesh_clear()
    return result


def fbx(path, objects, animated=False):
    select(objects)
    bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types={"ARMATURE", "MESH"},
        axis_forward="X", axis_up="Z", apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS", bake_space_transform=False,
        use_mesh_modifiers=True, mesh_smooth_type="FACE", add_leaf_bones=False,
        use_armature_deform_only=False, armature_nodetype="NULL",
        primary_bone_axis="Y", secondary_bone_axis="X", bake_anim=animated,
        bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
        bake_anim_step=1, bake_anim_simplify_factor=0,
        path_mode="COPY", embed_textures=False)


def solve_chain(points, goal):
    """FABRIK on actual joint-head lengths; no limb scale or stretch."""
    p = [x.copy() for x in points]
    lengths = [(p[i + 1] - p[i]).length for i in range(len(p) - 1)]
    root = p[0].copy()
    distance = (goal - root).length
    if distance > sum(lengths) * .9999:
        goal = root + (goal - root).normalized() * sum(lengths) * .9999
    for _ in range(32):
        p[-1] = goal.copy()
        for i in range(len(p) - 2, -1, -1):
            p[i] = p[i + 1] + (p[i] - p[i + 1]).normalized() * lengths[i]
        p[0] = root.copy()
        for i in range(len(p) - 1):
            p[i + 1] = p[i] + (p[i + 1] - p[i]).normalized() * lengths[i]
        if (p[-1] - goal).length < .00003:
            break
    return p, (p[-1] - goal).length


def reset(rig):
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)


def keyed(rig, frame):
    for bone in rig.pose.bones:
        bone.keyframe_insert("location", frame=frame)
        bone.keyframe_insert("rotation_quaternion", frame=frame)
        bone.keyframe_insert("scale", frame=frame)


def export_bundle(rig, bodies, output, name, actions, textures):
    """Bake world physical matrices to a unit-scale centimetre export rig."""
    original_rest = {b.name: rig.matrix_world @ b.matrix_local for b in rig.data.bones}
    normalized = rig.copy()
    normalized.data = rig.data.copy()
    normalized.name = "Armature"
    normalized.animation_data_clear()
    normalized.parent = None
    normalized.matrix_world = Matrix.Identity(4)
    normalized.data.transform(Matrix.Scale(100, 4) @ rig.matrix_world)
    bpy.context.collection.objects.link(normalized)
    exported = []
    for body in bodies:
        copy = body.copy()
        copy.data = body.data.copy()
        copy.name = name + "_Body"
        copy.data.transform(Matrix.Scale(100, 4) @ body.matrix_world)
        copy.parent = None
        copy.matrix_world = Matrix.Identity(4)
        for modifier in copy.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = normalized
        bpy.context.collection.objects.link(copy)
        exported.append(copy)
    normalized.animation_data_create()
    for pb in normalized.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.scene.unit_settings.scale_length = .01
    normalized.animation_data.action = None
    reset(normalized)
    body_path = output / (name + ".fbx")
    fbx(body_path, [normalized, *exported])
    clip_records = []
    reference_samples = {}
    max_error = 0.0
    for clip, source_action in actions.items():
        rig.animation_data.action = source_action
        action = bpy.data.actions.new(name + "_" + clip)
        normalized.animation_data.action = action
        end = round(CLIPS[clip] * FPS) + 1
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = end
        for frame in range(1, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            desired = {}
            for pb in rig.pose.bones:
                world = rig.matrix_world @ pb.matrix
                desired[pb.name] = Matrix.LocRotScale(
                    world.translation * 100, world.to_quaternion(),
                    Vector(tuple(a / b for a, b in zip(world.to_scale(), original_rest[pb.name].to_scale()))))
            for pb in normalized.pose.bones:
                kw = {"parent_matrix": desired[pb.parent.name],
                      "parent_matrix_local": pb.parent.bone.matrix_local} if pb.parent else {}
                pb.matrix_basis = pb.bone.convert_local_to_pose(
                    desired[pb.name], pb.bone.matrix_local, invert=True, **kw)
            keyed(normalized, frame)
            bpy.context.view_layer.update()
            max_error = max(max_error, max(
                (pb.matrix.translation - desired[pb.name].translation).length / 100
                for pb in normalized.pose.bones))
            if frame in {1, round(.4 * FPS) + 1, end}:
                reference_samples.setdefault(clip, []).append({
                    "time": (frame - 1) / FPS,
                    "bones": {name: {"head_cm": list(value.translation),
                                     "scale": list(value.to_scale())}
                              for name, value in desired.items()}})
        clip_path = output / (name + "_" + clip + ".fbx")
        fbx(clip_path, [normalized, *exported], True)
        clip_records.append(record(clip_path) | {"clip": clip, "duration": CLIPS[clip], "fps": FPS})
    normalized.animation_data.action = None
    reset(normalized)
    for obj in [normalized, *exported]:
        obj.hide_render = True
        obj.hide_set(True)
    bpy.context.scene.unit_settings.scale_length = 1
    return {"body": record(body_path), "clips": clip_records, "textures": textures,
            "absolute_bone_bake_max_error_m": max_error,
            "physical_pose_reference": reference_samples,
            "centimetre_normalization_passed": max_error < .0001}


def extract_textures(body, output, prefix):
    material = body.data.materials[0]
    principled = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    nodes = list(material.node_tree.nodes)
    images = {n.image.name: n.image for n in nodes if n.type == "TEX_IMAGE" and n.image}
    records = {}
    for index, (name, image) in enumerate(images.items()):
        channel = "base_color"
        matching = [n for n in nodes if n.type == "TEX_IMAGE" and n.image == image]
        destinations = [link.to_node.type for n in matching for link in n.outputs["Color"].links]
        destination_sockets = [link.to_socket.name for n in matching for link in n.outputs["Color"].links]
        if "NORMAL_MAP" in destinations:
            channel = "normal"
        elif any(x in destinations for x in ("SEPARATE_COLOR", "SEPRGB")):
            channel = "metallic_roughness"
        elif "Roughness" in destination_sockets:
            channel = "roughness"
        elif "Metallic" in destination_sockets:
            channel = "metallic"
        path = output / (prefix + "_" + channel + ".png")
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        records[channel] = record(path)
    return records


def build(output):
    if output.exists():
        raise FileExistsError(output)
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("Parent-only source changed")
    output.mkdir(parents=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE), merge_vertices=False, disable_bone_shape=True)
    rig = next(x for x in bpy.context.scene.objects if x.type == "ARMATURE")
    body = next(x for x in bpy.context.scene.objects if x.type == "MESH")
    rig.name = "Mammoth_SourceRig"
    bpy.context.scene.render.fps = FPS
    mapping = {bone.name: "m_" + str(i).zfill(2) for i, bone in enumerate(rig.data.bones)}
    chains = [[mapping[n] for n in chain] for chain in CHAINS]
    for bone in list(rig.data.bones):
        old = bone.name
        bone.name = mapping[old]
        group = body.vertex_groups.get(old)
        if group:
            group.name = mapping[old]
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    select([rig])
    bpy.ops.object.mode_set(mode="EDIT")
    saddle = rig.data.edit_bones.new("saddle_seat")
    saddle.head = rig.matrix_world.inverted() @ Vector((-.20, 0, 1.47))
    saddle.tail = saddle.head + Vector((0, 0, .12))
    saddle.parent = rig.data.edit_bones[mapping["tripo::Spine_2"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.pose.bones["saddle_seat"].rotation_mode = "QUATERNION"
    bpy.context.view_layer.update()
    rest = {pb.name: rig.matrix_world @ pb.matrix for pb in rig.pose.bones}
    base_vertices = world_vertices(body)
    feet = []
    for i, chain in enumerate(chains):
        sx, sy = (1 if i < 2 else -1), (1 if i % 2 == 0 else -1)
        indices = np.flatnonzero((base_vertices[:, 0] * sx > 0) & (base_vertices[:, 1] * sy > .1) &
                                 (base_vertices[:, 2] < .12))
        minimum = base_vertices[indices, 2].min()
        sole = indices[base_vertices[indices, 2] < minimum + .008]
        feet.append({"indices": indices, "sole": sole, "min_z": float(minimum),
                     "rest_ankle": rest[chain[-1]].translation.copy()})
    # The received quadruped assigns scattered rear sole vertices to tail/upper
    # leg joints. Rigid hoof weights are local to the measured bottom12cm; the
    # entire source surface/UV/materials are unchanged in this new candidate.
    foot_weight_changes = []
    for foot, chain in zip(feet, chains):
        destination = body.vertex_groups[chain[-1]]
        for index in foot["indices"]:
            vertex = body.data.vertices[int(index)]
            before = {body.vertex_groups[g.group].name: g.weight for g in vertex.groups}
            for group in list(vertex.groups):
                body.vertex_groups[group.group].remove([int(index)])
            destination.add([int(index)], 1., "REPLACE")
            foot_weight_changes.append({"vertex": int(index), "before": before, "after": chain[-1]})
    save(output / "hoof_weight_patch.json", foot_weight_changes)
    root_name = mapping["tripo::Root"]
    arm_inv = rig.matrix_world.inverted()
    actions, diagnostics = {}, []
    rig.animation_data_create()

    def set_pose(clip, t):
        reset(rig)
        # Lowers the torso into a small load-bearing stance, opening joint reach.
        root_shift = Vector((0, 0, -.10))
        death = min(1, t / 1.05) if clip == "Death" else 0
        if clip == "Death":
            root_shift.z -= .58 * death
        world_root = rest[root_name].copy()
        world_root.translation += root_shift
        if death:
            world_root = Matrix.Translation((0, 0, .3)) @ Matrix.Rotation(math.radians(62) * death, 4, "X") @ Matrix.Translation((0, 0, -.3)) @ world_root
        rig.pose.bones[root_name].matrix = arm_inv @ world_root
        bpy.context.view_layer.update()
        if clip == "Death":
            minimum = float(world_vertices(body)[:, 2].min())
            world_root.translation.z -= minimum
            rig.pose.bones[root_name].matrix = arm_inv @ world_root
            bpy.context.view_layer.update()
            return {"death": death, "minimum_body_z_m": float(world_vertices(body)[:, 2].min())}
        goals, phases, clamped = [], [], []
        for i, chain in enumerate(chains):
            foot = feet[i]
            goal = foot["rest_ankle"].copy()
            goal.z -= foot["min_z"]
            phase = ((t / CLIPS["Move"]) + (0 if i in (0, 3) else .5)) % 1
            lift = 0.0
            if clip == "Move":
                # .25s support at220cm/s:55cm actual stance counter-travel.
                goal.x += .275 - 1.10 * phase if phase < .5 else -.275 + 1.10 * (phase - .5)
                lift = .10 * math.sin(math.pi * (phase - .5) / .5) ** 1.4 if phase >= .5 else 0
                goal.z += lift
            goals.append(goal)
            phases.append({"phase": phase, "lift_m": lift, "support": phase < .5 or clip != "Move"})
        # Surface-corrected ankle targets retain a flat hoof orientation.
        for correction in range(3):
            for i, chain in enumerate(chains):
                original = [rest[n].translation.copy() for n in chain]
                points = [p + root_shift for p in original]
                solved, error = solve_chain(points, goals[i])
                clamped.append(error)
                for j, name in enumerate(chain):
                    matrix = rest[name].copy()
                    if j < len(chain) - 1:
                        rotation = (original[j + 1] - original[j]).rotation_difference(solved[j + 1] - solved[j])
                        matrix = rotation.to_matrix().to_4x4() @ matrix
                    matrix.translation = solved[j]
                    rig.pose.bones[name].matrix = arm_inv @ matrix
                    bpy.context.view_layer.update()
            actual = world_vertices(body)
            for i, foot in enumerate(feet):
                minimum = float(actual[foot["indices"], 2].min())
                goals[i].z += phases[i]["lift_m"] - minimum
        if clip in ("Idle", "Move", "Attack", "Hit"):
            trunk = rig.pose.bones[mapping["tripo::0_Right_Limb_1"]]
            trunk.rotation_quaternion = Quaternion((0, 1, 0), math.radians(2) * math.sin(t * math.tau))
        actual = world_vertices(body)
        return {"feet": [
            dict(phases[i], minimum_z_m=float(actual[f["indices"], 2].min()),
                 sole_centroid_m=actual[f["sole"]].mean(axis=0).tolist())
            for i, f in enumerate(feet)], "minimum_body_z_m": float(actual[:, 2].min()),
                "ik_residual_max_m": max(clamped)}

    for clip, duration in CLIPS.items():
        action = bpy.data.actions.new("Mammoth_" + clip)
        action.use_fake_user = True
        rig.animation_data.action = action
        actions[clip] = action
        frames = round(duration * FPS) + 1
        for frame in range(1, frames + 1):
            t = (frame - 1) / FPS
            bpy.context.scene.frame_set(frame)
            row = set_pose(clip, t)
            keyed(rig, frame)
            diagnostics.append({"clip": clip, "frame": frame, "time": t, **row})
    textures = extract_textures(body, output, "T_Mammoth")
    bundle = export_bundle(rig, [body], output, "SK_Mammoth", actions, textures)
    rig.animation_data.action = actions["Idle"]
    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "Mammoth_preview.blend"))
    render.render_setup(samples=8)
    for label, clip, frame, direction in [
        ("idle_side", "Idle", 1, (0, -1, .18)),
        ("move_A", "Move", 4, (1, -1.4, .25)),
        ("move_B", "Move", 12, (0, -1, .18)),
        ("death", "Death", 37, (1, -1.4, .3)),
    ]:
        rig.animation_data.action = actions[clip]
        bpy.context.scene.frame_set(frame)
        render.render_view(output / (label + ".png"), [body], direction, size=640)
    save(output / "motion_diagnostics.json", diagnostics)
    manifest = {"asset_id": "Mount_Mammoth", "status": "preview_candidate_pending_actual_review",
                "source": record(SOURCE), "bones": len(rig.data.bones), "bone_rename": mapping,
                "saddle_bone": "saddle_seat", "saddle_reference_world_m": [-.20, 0, 1.47],
                "dimensions_source_cm": [232.4669, 114.1325, 180],
                "reference_move_speed_cm_s": 220, "attack_contact_seconds": .4,
                "attack_duration_seconds": 1.6, "preview_limitations": [
                    "Existing source buckle/cloth intersections retained; rejected follower not reused.",
                    "Charge variant is not replicated; no fabricated charge-specific action.",
                    "Gameplay and FBX reimport review pending."],
                "hoof_weight_patch": record(output / "hoof_weight_patch.json"), **bundle}
    save(output / "manifest.json", manifest)
    print(json.dumps({"output": str(output), "manifest": record(output / "manifest.json"),
                      "frames": len(diagnostics)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    build(args.output.resolve())
