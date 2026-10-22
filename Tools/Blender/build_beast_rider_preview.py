"""Pose the actual independently rigged Tripo rider for the mammoth preview."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import subprocess

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as common
import prepare_stoneaxe_pose_pilot as posing

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "RawAssets/Art/Tripo_v01"
SOURCE = ART / "tripo_raw/Unit_BeastRider/web_v01_canonical/rigged.glb"
SPEAR = ART / "weapons/Weapon_StoneSpear/Weapon_StoneSpear.glb"


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=False, disable_bone_shape=True)
    return [x for x in bpy.data.objects if x not in before]


def build(output, mammoth):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    objects = import_glb(SOURCE)
    rig = next(x for x in objects if x.type == "ARMATURE")
    body = next(x for x in objects if x.type == "MESH")
    body.name = "Rider_Body"
    rig.name = "Rider_Source"
    rig.animation_data_clear()
    low, high = common.render.bounds([body])
    # Source has face toward Blender-Y, anatomically-left arm toward+X.
    # The preview's existing rider design height is150cm, with pelvis at seat+12cm.
    transform = Matrix.Rotation(math.pi / 2, 4, "Z") @ Matrix.Scale(1.50 / (high.z - low.z), 4)
    pelvis = transform @ (rig.matrix_world @ rig.data.bones["pelvis"].head_local)
    transform = Matrix.Translation(Vector((0, 0, .12)) - pelvis) @ transform
    for obj in objects:
        if obj.parent not in objects:
            obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    common.select([rig])
    bpy.ops.object.mode_set(mode="EDIT")
    anchor = rig.data.edit_bones.new("weapon_r")
    anchor.head = rig.data.edit_bones["hand_r"].head.copy()
    anchor.tail = anchor.head + Vector((0, .08, 0))
    anchor.parent = rig.data.edit_bones["hand_r"]
    bpy.ops.object.mode_set(mode="OBJECT")
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    bpy.context.view_layer.update()
    rest = {b.name: rig.matrix_world @ b.matrix for b in rig.pose.bones}
    rest_across, rest_long, rest_palm, _ = posing.hand_frame(rig)
    rest_hand_rotation = rest["hand_r"].to_quaternion()
    arm_inv = rig.matrix_world.inverted()
    spear_objects = import_glb(SPEAR)
    spear_parts = [o for o in spear_objects if o.type == "MESH"]
    spear_original = {o: o.matrix_world.copy() for o in spear_parts}
    rig.animation_data_create()
    bpy.context.scene.render.fps = common.FPS
    actions, report = {}, []

    def chain_pose(names, target, pole):
        upper, lower, terminal = (rig.pose.bones[n] for n in names)
        posing.solve_arm(rig, upper, lower, terminal, target, pole)
        # Keep foot or wrist orientation independent of the solved chain twist.

    def pose(clip, t):
        common.reset(rig)
        bpy.context.view_layer.update()
        phase = t / common.CLIPS[clip]
        pulse = 0.
        if clip == "Attack":
            if t < .22:
                pulse = -.30 * math.sin(math.pi / 2 * t / .22)
            elif t < .4:
                pulse = -.3 + 1.3 * ((t - .22) / .18)
            elif t < .65:
                pulse = 1. - ((t - .4) / .25)
        lean = -7. * pulse
        if clip == "Hit":
            lean = 8 * math.sin(math.pi * phase)
        elif clip == "Death":
            lean = 30 * min(1, phase * 1.3)
        # Torso rotates in physical sagittal direction, not arbitrary bone-local axes.
        spine = rig.pose.bones["spine_01"]
        matrix = rig.matrix_world @ spine.matrix
        around = Matrix.Translation(matrix.translation) @ Matrix.Rotation(math.radians(lean), 4, "Y") @ Matrix.Translation(-matrix.translation)
        spine.matrix = arm_inv @ around @ matrix
        bpy.context.view_layer.update()
        # Seated, abducted thighs and hanging shins follow the saddle on each side.
        for side, sign in (("l", 1), ("r", -1)):
            foot_target = Vector((.10, .53 * sign, -.36))
            chain_pose(("thigh_" + side, "calf_" + side, "foot_" + side),
                       foot_target, Vector((.35, .55 * sign, .1)))
            ankle = rig.pose.bones["foot_" + side]
            world = rest[ankle.name].copy()
            world.translation = rig.matrix_world @ ankle.head
            ankle.matrix = arm_inv @ world
            bpy.context.view_layer.update()
        left_target = Vector((.30, .22, .22))
        right_target = Vector((.17 + .22 * pulse, -.50, .43 - .08 * max(pulse, 0)))
        chain_pose(("upperarm_l", "lowerarm_l", "hand_l"), left_target, Vector((-.1, .65, .3)))
        chain_pose(("upperarm_r", "lowerarm_r", "hand_r"), right_target, Vector((-.15, -.65, .3)))
        tilt = 64. - 87. * max(pulse, 0)
        if clip == "Death":
            tilt = 20.
        axis = Vector((math.cos(math.radians(tilt)), 0, math.sin(math.radians(tilt))))
        hand = rig.pose.bones["hand_r"]
        hand_position = rig.matrix_world @ hand.head
        rotation = rest_across.rotation_difference(axis) @ rest_hand_rotation
        hand.matrix = arm_inv @ Matrix.LocRotScale(hand_position, rotation, rig.matrix_world.to_scale())
        bpy.context.view_layer.update()
        posing.close_grip(rig)
        # Slightly stronger flexion closes the generated broad glove around the
        # 2.6cm shaft without changing the hand mesh or fusing the weapon.
        grip_across = posing.hand_frame(rig)[0]
        grip_axis = rig.matrix_world.to_quaternion().inverted() @ grip_across
        for finger in ("index", "middle", "ring", "pinky"):
            for joint in (1, 2):
                digit = rig.pose.bones[f"{finger}_{joint:02d}_r"]
                posing.rotate_rest_axis(digit, grip_axis, math.radians(posing.DIGIT_ANGLES[finger][joint - 1] + 10))
        bpy.context.view_layer.update()
        # The actual closed hand establishes a physical grip point.
        across, longitudinal, palm, center = posing.hand_frame(rig)
        grip = center + longitudinal * .025 - palm * .008
        weapon_matrix = Matrix.LocRotScale(grip, Vector((1, 0, 0)).rotation_difference(axis), Vector((1, 1, 1)))
        # Bone reference and animation retain the same physical scale. The
        # separate spear visual itself remains unit-scale in world metres.
        weapon_pose_matrix = Matrix.LocRotScale(grip, weapon_matrix.to_quaternion(), rig.matrix_world.to_scale())
        rig.pose.bones["weapon_r"].matrix = arm_inv @ weapon_pose_matrix
        bpy.context.view_layer.update()
        for obj in spear_parts:
            obj.matrix_world = weapon_matrix @ spear_original[obj]
        return {"pulse": pulse, "weapon_grip_m": list(grip),
                "weapon_axis": list(axis), "weapon_tip_m": list(weapon_matrix @ Vector((1.17, 0, 0))),
                "pelvis_m": list(rig.matrix_world @ rig.pose.bones["pelvis"].head)}

    for clip, duration in common.CLIPS.items():
        action = bpy.data.actions.new("Rider_" + clip)
        action.use_fake_user = True
        rig.animation_data.action = action
        actions[clip] = action
        for frame in range(1, round(duration * common.FPS) + 2):
            bpy.context.scene.frame_set(frame)
            data = pose(clip, (frame - 1) / common.FPS)
            common.keyed(rig, frame)
            report.append({"clip": clip, "frame": frame, **data})
    textures = common.extract_textures(body, output, "T_BeastRider")
    bundle = common.export_bundle(rig, [body], output, "SK_BeastRider", actions, textures)
    # Static prop exports in the same physical centimetre convention.
    for obj in spear_parts:
        obj.matrix_world = spear_original[obj]
    export_spear = []
    for obj in spear_parts:
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.data.transform(Matrix.Scale(100, 4) @ obj.matrix_world)
        copy.parent = None
        copy.matrix_world = Matrix.Identity(4)
        bpy.context.collection.objects.link(copy)
        export_spear.append(copy)
    bpy.context.scene.unit_settings.scale_length = .01
    spear_path = output / "SM_StoneSpear.fbx"
    common.fbx(spear_path, export_spear)
    for obj in export_spear:
        obj.hide_render = True
        obj.hide_set(True)
    bpy.context.scene.unit_settings.scale_length = 1.
    # Load mount only as assembly evidence. It is not merged or re-exported.
    with bpy.data.libraries.load(str(mammoth), link=False) as (available, requested):
        requested.objects = [name for name in available.objects if name in ("Mammoth_SourceRig", "tripo_node_37ec2f0d")]
    mount_objects = [o for o in requested.objects if o]
    for obj in mount_objects:
        bpy.context.collection.objects.link(obj)
    mount_rig = next(o for o in mount_objects if o.type == "ARMATURE")
    mount_body = next(o for o in mount_objects if o.type == "MESH")
    mount_rig.animation_data.action = bpy.data.actions.get("Mammoth_Idle")
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    seat = mount_rig.matrix_world @ mount_rig.pose.bones["saddle_seat"].matrix
    # Bone axes are exporter-defined; world offset is a translation to the seat.
    # Runtime uses inverse saddle rotation so both components face+X.
    seat_rotation = seat.to_quaternion()
    seat_position = seat.translation
    pose_local_matrix = Matrix.Translation(seat_position)
    rig.matrix_world = pose_local_matrix @ rig.matrix_world
    # Mesh is parented under rig, so only its top-level parent changes.
    rig.animation_data.action = actions["Idle"]
    bpy.context.scene.frame_set(1)
    common.render.render_setup(samples=8)
    rendered = []
    for label, clip, frame, direction in [
        ("assembly_idle_side", "Idle", 1, (0, -1, .12)),
        ("assembly_idle_front", "Idle", 1, (1, -.7, .2)),
        ("assembly_contact", "Attack", 13, (0, -1, .15)),
        ("hand_contact", "Attack", 13, (1, -1, .3)),
    ]:
        rig.animation_data.action = actions[clip]
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        weapon_world = rig.matrix_world @ rig.pose.bones["weapon_r"].matrix
        weapon_world = Matrix.LocRotScale(weapon_world.translation, weapon_world.to_quaternion(), Vector((1, 1, 1)))
        for obj in spear_parts:
            obj.matrix_world = weapon_world @ spear_original[obj]
        scene_objects = [body, mount_body, *spear_parts]
        if label == "hand_contact":
            common.render.render_view(output / (label + ".png"), scene_objects, direction,
                                      size=640, framing=.48, target=weapon_world.translation)
        else:
            common.render.render_view(output / (label + ".png"), scene_objects, direction, size=640)
        rendered.append(label + ".png")
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "BeastRider_assembly.blend"))
    inverse_saddle = seat_rotation.inverted().to_euler("XYZ")
    manifest = {"asset_id": "Unit_BeastRider", "status": "preview_candidate_pending_actual_review",
                "source": common.record(SOURCE), "bones": len(rig.data.bones), "weapon_bone": "weapon_r",
                "source_normalized_height_cm": 150, "attack_contact_seconds": .4,
                "attack_duration_seconds": 1.6, "rider_attach": {
                    "parent_part": "mount", "parent_socket": "saddle_seat",
                    "inverse_saddle_euler_xyz_degrees": [math.degrees(x) for x in inverse_saddle],
                    "saddle_rotation_xyzw": [*seat_rotation[1:], seat_rotation[0]],
                    "translation_cm": [0, 0, 0]},
                "weapon": common.record(spear_path), "rendered": rendered,
                "production_approved": False, **bundle}
    common.save(output / "manifest.json", manifest)
    common.save(output / "motion_report.json", report)
    python = Path("C:/Users/12153/AppData/Local/Programs/Python/Python314/python.exe")
    subprocess.run([str(python), "-X", "utf8",
                    str(Path(__file__).with_name("prepare_beast_rider_team_masks.py")),
                    str(output / "manifest.json")], check=True)
    red_sources = [
        (body, json.loads((output / "manifest.json").read_text(encoding="utf-8"))),
        (mount_body, json.loads((mammoth.parent / "manifest.json").read_text(encoding="utf-8"))),
    ]
    for obj, info in red_sources:
        shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        node = shader.inputs["Base Color"].links[0].from_node
        node.image = bpy.data.images.load(info["team_cloth"]["red_base_color"]["path"], check_existing=False)
    rig.animation_data.action = actions["Idle"]
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    weapon_world = rig.matrix_world @ rig.pose.bones["weapon_r"].matrix
    weapon_world = Matrix.LocRotScale(weapon_world.translation, weapon_world.to_quaternion(), Vector((1, 1, 1)))
    for obj in spear_parts:
        obj.matrix_world = weapon_world @ spear_original[obj]
    common.render.render_view(output / "assembly_red_front.png", [body, mount_body, *spear_parts],
                              (1, -.7, .2), size=640)
    print(json.dumps({"output": str(output), "manifest": common.record(output / "manifest.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mammoth", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    build(args.output.resolve(), args.mammoth.resolve())
