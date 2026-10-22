"""Derive local motion fixes from approved Stone Age rigs without replacing art.

Run one asset per Blender process. Source candidates and their textures stay
immutable; the destination must be new. No Unreal or runtime mapping is changed.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_stone_slinger_gameplay as sling
import build_stone_champion_preview as chief

pose = chief.pose
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def basis(rig):
    return {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}


def apply_basis(rig, values):
    for name, value in values.items():
        rig.pose.bones[name].matrix_basis = value
    bpy.context.view_layer.update()


def blended(left, right, alpha):
    lp, lr, ls = left.decompose()
    rp, rr, rs = right.decompose()
    return Matrix.LocRotScale(lp.lerp(rp, alpha), lr.slerp(rr, alpha), ls.lerp(rs, alpha))


def preserve_geometry(objects):
    """Hash actual rest mesh, UVs and weights, independently of animation."""
    result = {}
    for obj in objects:
        digest = hashlib.sha256()
        for values in (
            [tuple(vertex.co) for vertex in obj.data.vertices],
            [tuple(poly.vertices) for poly in obj.data.polygons],
            [[(entry.group, entry.weight) for entry in vertex.groups] for vertex in obj.data.vertices],
            [tuple(uv.uv) for uv in obj.data.uv_layers.active.data] if obj.data.uv_layers.active else [],
        ):
            digest.update(json.dumps(values, separators=(",", ":")).encode())
        result[obj.name] = digest.hexdigest()
    return result


def cache_action(rig, action, count):
    rig.animation_data.action = action
    rows = []
    for frame in range(1, count + 1):
        bpy.context.scene.frame_set(frame)
        rows.append(basis(rig))
    return rows


def new_action(rig, name):
    old = bpy.data.actions[name]
    old.name = "Prior_" + name
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    rig.animation_data.action = action
    return action


def swing_offset(amplitude, q):
    # Hermite endpoint tangents equal the backward stance velocity. The slight
    # 8.9% overshoot occurs above ground, instead of stopping the foot instantly.
    return -amplitude + 2 * amplitude * (6 * q*q - 4 * q*q*q - q)


def chief_move(rig, rest_feet, groups, fraction):
    targets = {}
    for side, offset in (("r", 0), ("l", .5)):
        cycle = (fraction + offset) % 1
        stance = cycle < .5
        position, rotation = rest_feet[side]
        q = max(0., (cycle - .5) * 2)
        travel = .30 - 1.2 * cycle if stance else swing_offset(.30, q)
        lift = 0. if stance else .075 * math.sin(math.pi*q)**2
        hip = rig.matrix_world @ rig.data.bones["thigh_" + side].head_local
        targets[side] = {"target": Vector((hip.x + travel, position.y, position.z + lift)),
                         "rotation": rotation, "stance": stance, "lift": lift}
    for _ in range(4):
        for side, values in targets.items():
            target = values["target"]
            pose.solve_arm(rig, rig.pose.bones["thigh_"+side], rig.pose.bones["calf_"+side],
                           rig.pose.bones["foot_"+side], target, (.45, target.y, .4))
            pose.set_world_rotation(rig, rig.pose.bones["foot_"+side], values["rotation"])
        measured = pose.measured_feet(groups)
        for side, values in targets.items():
            values["target"].z += values["lift"] - measured[side]["minimum_z_m"]
    measured = pose.measured_feet(groups)
    for side, values in targets.items():
        measured[side].update(stance=values["stance"], desired_sole_z_m=values["lift"],
                             world_compensated_sole_x_m=measured[side]["sole_centroid_m"][0] + 1.2*fraction)
    return measured


def floor_body(rig, body):
    points = [point for obj in body for point in pose.evaluated_world_vertices(obj)]
    minimum = min(point.z for point in points)
    correction = max(0., .0001 - minimum)
    if correction:
        pose.translate_bone_world(rig, rig.pose.bones["pelvis"], (0, 0, correction))
    return minimum + correction, correction


def death_terminal(rig, idle):
    """Solve relaxed arms once; avoid a moving IK pole flipping during the fall."""
    apply_basis(rig, idle)
    pelvis = rig.pose.bones["pelvis"]
    start_rotation = (rig.matrix_world @ pelvis.matrix).to_quaternion()
    pose.set_world_rotation(rig, pelvis, Quaternion(Vector((0, 1, 0)), math.radians(-86)) @ start_rotation)
    pose.translate_bone_world(rig, pelvis, (-.16, 0, -.76))
    reference = pose.hand_frame(rig)
    pose.relax_death_arms(rig, reference, 1.)
    return basis(rig)


def audit_motion(path):
    data = read(path)
    result = {}
    idle = np.asarray(data["clips"]["Idle"][0]["skinned_points_m"])
    for clip, rows in data["clips"].items():
        points = np.asarray([row["skinned_points_m"] for row in rows])
        delta = np.linalg.norm(np.diff(points, axis=0), axis=2)
        result[clip] = {
            "frames": len(rows), "first_last_max_cm": float(np.linalg.norm(points[-1]-points[0], axis=1).max()*100),
            "first_to_idle_max_cm": float(np.linalg.norm(points[0]-idle, axis=1).max()*100),
            "last_to_idle_max_cm": float(np.linalg.norm(points[-1]-idle, axis=1).max()*100),
            "maximum_frame_step_cm": float(delta.max()*100),
            "last_12_frame_steps_max_cm": float(delta[-12:].max()*100),
            "seam_velocity_difference_cm_s": float(np.linalg.norm(
                (points[1]-points[0]-points[-1]+points[-2])*6000, axis=1).max()),
        }
    return result


def main(args):
    slinger = args.asset == "slinger"
    source = BASE / ("stone_slinger_v01/gameplay_candidate_03" if slinger else "champion_stone_v01/preview_candidate_04")
    manifest = read(source / ("delivery_manifest_pbr_source02.json" if slinger else "delivery_manifest.json"))
    previous = read(source / "preview_report.json")
    blend = source / ("Unit_StoneSlinger_Gameplay.blend" if slinger else "ChampionStone_Gameplay.blend")
    for record in manifest["textures"].values():
        if chief.record(Path(record["path"])) != record:
            raise ValueError("Approved texture file changed")
    args.output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    rig, = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    rig.animation_data.action = None
    pose.reset_pose(rig)
    bound = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"
             and any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers)]
    body = [obj for obj in bound if obj.name not in {"retained_loop_cord", "released_cord", "leather_pouch", "loaded_stone"}]
    geometry = preserve_geometry(bound)
    rest = {bone.name: rig.matrix_world @ bone.matrix_local for bone in rig.data.bones}
    rest_feet = {side: (rest["foot_"+side].translation.copy(), rest["foot_"+side].to_quaternion()) for side in ("l", "r")}
    groups = None if slinger else pose.foot_surface_groups(rig, body)
    prefix = "CW_StoneSlinger_" if slinger else "CW_ChampionStone_"
    counts = {c["clip"]: c["last_frame"] for c in manifest["clips"]}
    changes = ("Move", "Attack") if slinger else ("Move", "Attack", "Death")
    cached = {clip: cache_action(rig, bpy.data.actions[prefix+clip], counts[clip]) for clip in changes}
    idle = cache_action(rig, bpy.data.actions[prefix+"Idle"], 1)[0]
    rig.animation_data.action = None
    terminal = None if slinger else death_terminal(rig, idle)
    arm_names = [bone.name for bone in rig.pose.bones if bone.name.startswith(("upperarm_", "lowerarm_", "hand_"))]
    bpy.context.scene.render.fps = 60
    frame_audit = {}
    for clip in changes:
        action = new_action(rig, prefix+clip)
        rows = []
        for frame, original in enumerate(cached[clip], 1):
            time = (frame-1)/60
            bpy.context.scene.frame_set(frame)
            apply_basis(rig, original)
            info = {"frame": frame, "time_seconds": time}
            if clip == "Move":
                if slinger:
                    for side in ("l", "r"):
                        phase = ((time/.6) + (.5 if side == "r" else 0)) % 1
                        target = rest_feet[side][0].copy()
                        if phase < .5:
                            travel, lift = .24 - .96*phase, 0.
                        else:
                            q = (phase-.5)*2
                            travel, lift = swing_offset(.24, q), .065*math.sin(math.pi*q)**2
                        target += Vector((travel, 0, lift+.001))
                        sling.solve_chain(rig, "thigh_"+side, "calf_"+side, "foot_"+side, target, (.5, target.y, .40))
                        sling.prior.set_rotation_channels(rig, "foot_"+side, rest_feet[side][1])
                    info["feet_m"] = {side: list(pose.world_head(rig, rig.pose.bones["foot_"+side])) for side in ("l","r")}
                else:
                    info["feet"] = chief_move(rig, rest_feet, groups, time/.6)
            elif clip == "Attack":
                if slinger:
                    recovery = smooth((time-.76)/.44)
                    for bone in rig.pose.bones:
                        if bone.name.startswith("sling_") and recovery:
                            bone.matrix_basis = blended(original[bone.name], idle[bone.name], recovery)
                else:
                    seam = 1-smooth(time/.08) if time < .08 else smooth((time-.76)/.14)
                    if seam:
                        pose.blend_pose_to_idle(rig, idle, seam)
            else:
                apply_basis(rig, idle)
                fall = smooth(time/.85)
                pelvis = rig.pose.bones["pelvis"]
                rotation = (rig.matrix_world @ pelvis.matrix).to_quaternion()
                pose.set_world_rotation(rig, pelvis, Quaternion(Vector((0,1,0)), math.radians(-86*fall)) @ rotation)
                pose.translate_bone_world(rig, pelvis, (-.16*fall, 0, -.76*fall))
                relax = smooth((time-.18)/.55)
                for name in arm_names:
                    rig.pose.bones[name].matrix_basis = blended(idle[name], terminal[name], relax)
            bpy.context.view_layer.update()
            info["body_floor_min_m"], info["floor_correction_m"] = floor_body(rig, body)
            info["pelvis_m"] = list(pose.world_head(rig, rig.pose.bones["pelvis"]))
            pose.keyed_pose(rig, frame)
            rows.append(info)
        frame_audit[clip] = rows
    rig.animation_data.action = None
    pose.reset_pose(rig)
    if preserve_geometry(bound) != geometry:
        raise ValueError("Rest mesh, UV or weights were modified")
    for clip in counts:
        bpy.data.actions[prefix+clip].use_fake_user = True
    report = {**previous, "images": [], "source_previous": chief.record(blend),
              "geometry_uv_weights_exact": True, "changes": list(changes),
              "frame_audit": frame_audit, "production_approved": False, "game_ready": False,
              "status": "motion_polish_pending_gameplay_review"}
    if slinger:
        report["blend"] = chief.record(blend)
    else:
        report["source"] = chief.record(blend)
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("StoneMotionReview")
    pose.inspection.helper.render_setup(samples=8)
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    scene.cycles.device = "CPU"
    weapon = [] if slinger else [obj for obj in scene.objects if obj.type == "MESH" and obj not in body]
    captures = [("Move", 1), ("Move", 19), ("Attack", counts["Attack"])]
    if not slinger:
        captures += [("Death", 25), ("Death", 43), ("Death", 61)]
    else:
        captures += [("Attack", 28), ("Attack", 58)]
    for clip, frame in captures:
        rig.animation_data.action = bpy.data.actions[prefix+clip]
        scene.frame_set(frame)
        path = args.output/f"{clip}_{frame:03}.png"
        pose.inspection.helper.render_view(path, bound+weapon, (1,-1.5,.35), size=640,
                                          framing=2.30 if slinger else 3.,
                                          target=(.05,-.10,.72) if slinger else (.1,-.1,.95))
        report["images"].append(str(path))
    rig.animation_data.action = None
    pose.reset_pose(rig)
    saved = args.output / blend.name
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    report["blend"] = chief.record(saved)
    chief.write(args.output/"preview_report.json", report)
    if slinger:
        sling.CLIPS = counts
        original_export = sling.texture_export
        sling.texture_export = lambda body, output: manifest["textures"]
        try:
            sling.export(args.output, rig, bound, body[0], report)
        finally:
            sling.texture_export = original_export
    else:
        chief.CLIPS = counts
        original_export = chief.textures
        chief.textures = lambda body, output: manifest["textures"]
        try:
            chief.export_delivery(args.output, rig, body, weapon, scene.objects["ChampionClubGrip"], report)
        finally:
            chief.textures = original_export
        delivery = read(args.output/"delivery_manifest.json")
        delivery["team_cloth"] = manifest["team_cloth"]
        chief.write(args.output/"delivery_manifest.json", delivery)
    audit = audit_motion(args.output/"physical_motion_reference.json")
    chief.write(args.output/"motion_polish_audit.json", audit)
    if audit["Move"]["first_last_max_cm"] > .01 or audit["Attack"]["last_to_idle_max_cm"] > .02:
        raise ValueError("Loop or attack recovery did not close")
    if not slinger and audit["Death"]["last_12_frame_steps_max_cm"] > .01:
        raise ValueError("Death terminal hold is not stationary")
    print("STONE_MOTION_POLISH " + json.dumps(audit))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", choices=("slinger", "chief"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    args.output = args.output.resolve()
    main(args)
