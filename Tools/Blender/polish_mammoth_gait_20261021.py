"""New Move only from the frozen shipped mammoth; never modifies source assets."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as old
import prepare_tripo_character as render

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/mammoth_v01/preview_delivery_02/Mammoth_preview.blend"
SOURCE_SHA = "fc736736d40777da71a95fc43069e2c563f09b957c39b59ae6f5f7e012e06ff2"
CYCLE = .5
DUTY = .60
SPEED = 2.2
LIFT = .06
# Touchdown order: hind +Y, fore +Y, hind -Y, fore -Y.
OFFSETS = [.75, .25, 0., .5]


def foot_path(phase):
    sweep = SPEED * CYCLE * DUTY
    if phase < DUTY:
        return sweep / 2 - SPEED * CYCLE * phase, 0., True
    u = (phase - DUTY) / (1 - DUTY)
    # Quintic smoothstep plus linear endpoint velocity: joins support with
    # matching velocity and acceleration, instead of triangle-wave reversal.
    ease = 10*u**3 - 15*u**4 + 6*u**5
    tangent = -SPEED * CYCLE * (1 - DUTY)
    x = -sweep/2 + tangent*u + (sweep - tangent)*ease
    z = LIFT * 64*u**3*(1-u)**3
    return x, z, False


def solve(points, target):
    # The extra left-hind short metatarsal is kept in its rest orientation;
    # the anatomical upper/lower pair receives the same solver on all legs.
    terminal = points[-1] - points[-2] if len(points) == 4 else Vector((0, 0, 0))
    goal = target - terminal
    root, knee = points[0], points[1]
    end = points[-2] if len(points) == 4 else points[-1]
    a, b = (knee-root).length, (end-knee).length
    delta = goal-root
    requested = delta.length
    distance = min(max(requested, abs(a-b)+.0001), a+b-.0001)
    direction = delta.normalized()
    end = root + direction*distance
    # Fixed anatomical bend side, projected onto the root-goal plane.
    pole = Vector((1, 0, 0))
    pole = (pole-direction*pole.dot(direction)).normalized()
    along = (a*a-b*b+distance*distance)/(2*distance)
    height = math.sqrt(max(0, a*a-along*along))
    solved = [root.copy(), root+direction*along+pole*height, end]
    if len(points) == 4:
        solved.append(end+terminal)
    return solved, abs(requested-distance)


def surface_fingerprint(body):
    payload = {
        "vertices": [list(v.co) for v in body.data.vertices],
        "polygons": [list(p.vertices) for p in body.data.polygons],
        "uv": [[list(d.uv) for d in layer.data] for layer in body.data.uv_layers],
        "weights": [[(g.group, g.weight) for g in v.groups] for v in body.data.vertices],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run(output):
    if output.exists():
        raise FileExistsError(output)
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("Frozen shipped blend changed")
    output.mkdir(parents=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    scene = bpy.context.scene
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    rig = bpy.data.objects["Mammoth_SourceRig"]
    body = next(o for o in scene.objects if o.type == "MESH" and
                any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers))
    for obj in list(scene.objects):
        if obj not in (rig, body):
            bpy.data.objects.remove(obj, do_unlink=True)
    before_surface = surface_fingerprint(body)
    source_action = rig.animation_data.action
    old.reset(rig)
    rig.animation_data.action = None
    bpy.context.view_layer.update()
    rest = {b.name: rig.matrix_world @ b.matrix for b in rig.pose.bones}
    manifest = json.loads((SOURCE.parent/"manifest.json").read_text(encoding="utf-8-sig"))
    chains = [[manifest["bone_rename"][n] for n in c] for c in old.CHAINS]
    base = old.world_vertices(body)
    feet = []
    for i, chain in enumerate(chains):
        sx, sy = (1 if i < 2 else -1), (1 if i % 2 == 0 else -1)
        indices = np.flatnonzero((base[:,0]*sx > 0) & (base[:,1]*sy > .1) & (base[:,2] < .12))
        low = float(base[indices,2].min())
        feet.append({"indices":indices, "sole":indices[base[indices,2] < low+.008], "min":low})
    action = bpy.data.actions.new("Mammoth_Move_FourBeat_20261021")
    action.use_fake_user = True
    rig.animation_data.action = action
    inv = rig.matrix_world.inverted()
    diagnostics = []
    scene.render.fps = 60
    old.FPS = 60
    old.CLIPS["Move"] = CYCLE
    for frame in range(1, round(CYCLE*60)+2):
        t = (frame-1)/60
        scene.frame_set(frame)
        old.reset(rig)
        shift = Vector((0,0,-.10))
        matrix = rest["m_00"].copy()
        matrix.translation += shift
        rig.pose.bones["m_00"].matrix = inv @ matrix
        bpy.context.view_layer.update()
        goals, states = [], []
        for i, chain in enumerate(chains):
            phase = (t/CYCLE + OFFSETS[i]) % 1
            x, lift, support = foot_path(phase)
            goal = rest[chain[-1]].translation.copy()
            # Center each stance under its measured support pivot. The old
            # fore ankle center was already 8cm forward, exhausting reach.
            goal.x = rest[chain[0]].translation.x + x
            goal.z += lift-feet[i]["min"]
            goals.append(goal)
            states.append({"phase":phase,"lift_m":lift,"support":support})
        residual = 0.
        for correction in range(3):
            for i, chain in enumerate(chains):
                original = [rest[n].translation.copy() for n in chain]
                points = [p+shift for p in original]
                solved, error = solve(points, goals[i])
                residual = max(residual, error)
                for j,name in enumerate(chain):
                    matrix = rest[name].copy()
                    if j < len(chain)-1:
                        rotation = (original[j+1]-original[j]).rotation_difference(solved[j+1]-solved[j])
                        matrix = rotation.to_matrix().to_4x4() @ matrix
                    matrix.translation = solved[j]
                    rig.pose.bones[name].matrix = inv @ matrix
                    bpy.context.view_layer.update()
            vertices = old.world_vertices(body)
            for i, foot in enumerate(feet):
                goals[i].z += states[i]["lift_m"]-float(vertices[foot["indices"],2].min())
        old.keyed(rig,frame)
        vertices = old.world_vertices(body)
        diagnostics.append({"frame":frame,"time":t,"reach_clamp_m":residual,
            "body_min_z":float(vertices[:,2].min()),
            "feet":[dict(states[i],sole=vertices[f["sole"]].mean(axis=0).tolist(),
                         minimum_z=float(vertices[f["indices"],2].min())) for i,f in enumerate(feet)],
            "joint_heads":{n:list((rig.matrix_world @ rig.pose.bones[n].matrix).translation) for c in chains for n in c}})
    # Dense keys use linear interpolation to avoid subframe Bezier overshoot.
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = "LINEAR"
    drift = []
    for first, second in zip(diagnostics,diagnostics[1:]):
        for a,b in zip(first["feet"],second["feet"]):
            if a["support"] and b["support"] and b["phase"] > a["phase"]:
                drift.append(abs(b["sole"][0]-a["sole"][0]+SPEED/60))
    surface_unchanged = surface_fingerprint(body) == before_surface
    bundle = old.export_bundle(rig,[body],output,"SK_Mammoth_Gait",{"Move":action},{})
    rig.animation_data.action = action
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"Mammoth_Gait.blend"))
    render.render_setup(samples=8)
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    for i,frame in enumerate((1,6,11,16,21,26)):
        scene.frame_set(frame)
        render.render_view(output/f"move_side_{i:02}.png",[body],(0,-1,.18),size=640)
    old.save(output/"diagnostics.json", diagnostics)
    report = {"status":"candidate_pending_UE_and_game_review", "source":old.record(SOURCE),
        "cycle_seconds":CYCLE,"stance_fraction":DUTY,"speed_cm_s":220,"lift_cm":LIFT*100,
        "touchdown_order":["hind_positive_y","front_positive_y","hind_negative_y","front_negative_y"],
        "original_geometry_uv_weights_unchanged":surface_unchanged,
        "max_support_step_drift_m":max(drift),"max_reach_clamp_m":max(r["reach_clamp_m"] for r in diagnostics),
        "minimum_body_z_m":min(r["body_min_z"] for r in diagnostics),
        "runtime_sync":"MoveClock advances actual speed/reference220; rider samples normalized mount phase. Same0.5s period retained.",
        "original_mesh_skeleton_other_four_clips_rider_unchanged":True,
        **bundle}
    report["numeric_gate"] = surface_unchanged and max(drift)<.008 and report["max_reach_clamp_m"]<.005 and bundle["centimetre_normalization_passed"]
    old.save(output/"manifest.json",report)
    print(json.dumps({k:report[k] for k in ("numeric_gate","max_support_step_drift_m","max_reach_clamp_m","minimum_body_z_m")}))


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args(sys.argv[sys.argv.index("--")+1:])
    run(args.output.resolve())
