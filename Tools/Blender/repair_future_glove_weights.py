"""Repair the reviewed Future chief's residual glove spikes, under heavy lease.

Only surface weights change. Reuses the saved actions, skeleton, geometry,
UVs, original PBR and equipment. Exports one mesh for the existing UE skeleton.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as export
import prepare_stoneaxe_pose_pilot as pose


def record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def digest(body):
    result = {}
    for name, values in (
        ("positions", [[*v.co] for v in body.data.vertices]),
        ("faces", [[*p.vertices] for p in body.data.polygons]),
        ("uv", [[*p.uv] for p in body.data.uv_layers.active.data]),
    ):
        result[name] = hashlib.sha256(json.dumps(values).encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_blend = source/"Champion_Future_Actions.blend"
    bpy.ops.wm.open_mainfile(filepath=str(source_blend))
    scene = bpy.context.scene
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    rig = bpy.data.objects["Champion_Future_SourceRig"]
    bodies = [obj for obj in scene.objects if obj.type == "MESH" and
              any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)]
    body, = bodies
    # The saved delivery also holds hidden cm-sized FBX export copies. They
    # must not move the inspection framing 100x away or occupy the FBX rig name.
    for obj in list(scene.objects):
        if obj.hide_render and obj not in (rig, body):
            bpy.data.objects.remove(obj, do_unlink=True)
    objects = [obj for obj in scene.objects if obj.type == "MESH" and not obj.hide_render]
    actions = {clip: bpy.data.actions["Champion_Future_"+clip] for clip in ("Idle", "Move", "Attack", "Hit", "Death")}
    samples = [("Idle", 0., "Idle"), ("Move", .15, "Move"), ("Move", .45, "MoveRear"),
               ("Attack", .25, "Attack"), ("Hit", .18, "Hit"), ("Death", 1.4, "Death")]
    original_geometry = digest(body)
    rest = np.array([list(body.matrix_world @ v.co) for v in body.data.vertices])
    height = float(np.ptp(rest[:, 2]))
    edges = np.array([list(edge.vertices) for edge in body.data.edges])
    rest_lengths = np.linalg.norm(rest[edges[:, 0]]-rest[edges[:, 1]], axis=1)
    valid = rest_lengths >= .005
    group_names = {g.index: g.name for g in body.vertex_groups}
    original_weights = [{group_names[g.group]: float(g.weight) for g in vertex.groups} for vertex in body.data.vertices]
    rest_in_rig = np.array([list(rig.matrix_world.inverted() @ (body.matrix_world @ v.co)) for v in body.data.vertices])

    def activate(clip, t):
        rig.animation_data.action = actions[clip]
        for obj in scene.objects:
            name = "Champion_Future_"+clip+"_"+obj.name
            if obj.animation_data and name in bpy.data.actions:
                obj.animation_data.action = bpy.data.actions[name]
        scene.frame_set(round(t*scene.render.fps/scene.render.fps_base)+1)
        bpy.context.view_layer.update()

    def measurements():
        rows = []
        for clip, t, label in samples:
            activate(clip, t)
            points = np.array([list(v) for v in pose.evaluated_world_vertices(body)])
            lengths = np.linalg.norm(points[edges[:, 0]]-points[edges[:, 1]], axis=1)
            ratios = np.divide(lengths, rest_lengths, out=np.zeros_like(lengths), where=rest_lengths > 1e-8)
            ranked = sorted(np.flatnonzero(valid), key=lambda i: ratios[i], reverse=True)
            rows.append({"clip": clip, "time": t, "max_edge_stretch": float(max(ratios[valid])),
                         "p99_edge_stretch": float(np.quantile(ratios[valid], .99)),
                         "worst_edges": [{"vertices": edges[i].tolist(), "stretch": float(ratios[i]),
                                          "rest_positions_m": rest[edges[i]].tolist(),
                                          "weights": [original_weights[v] for v in edges[i]]} for i in ranked[:8]]})
        return rows

    before = measurements()
    (output/"before_deformation.json").write_text(json.dumps(before, indent=2)+"\n", encoding="utf-8")
    if args.render:
        if scene.world is None:
            scene.world = bpy.data.worlds.new("FutureGloveReviewWorld")
        pose.inspection.helper.render_setup(samples=8)
        scene.cycles.device = "CPU"
        scene.render.threads_mode, scene.render.threads = "FIXED", 2
        activate("Idle", 0.)
        pose.inspection.helper.render_view(output/"before_Idle.png", objects, (1, -1.4, .3), size=640, framing=height*1.55)

    # These are closed armored gloves. Residual finger-group influences on
    # the fused finger tips stretch their few triangles when the hand closes.
    # Rigid hand weights distal to the measured wrist keep the actual glove
    # silhouette; a short transition preserves the forearm/cuff connection.
    changed = {"l": [], "r": []}
    adjacency = [set() for _ in body.data.vertices]
    for a, b in edges:
        adjacency[a].add(int(b))
        adjacency[b].add(int(a))
    welded = {}
    for i, p in enumerate(rest_in_rig):
        welded.setdefault(tuple(np.round(p, 5)), []).append(i)
    for aliases in welded.values():
        for i in aliases:
            adjacency[i].update(aliases)
    regions = {}
    for side in ("l", "r"):
        hand = rig.data.bones["hand_"+side]
        knuckle = rig.data.bones["middle_01_"+side]
        axis = (knuckle.head_local-hand.head_local).normalized()
        # Rig local and world scale can differ: derive this length from bones.
        unit = (knuckle.head_local-hand.head_local).length/.075
        delta = rest_in_rig-np.array(hand.head_local[:])
        travel = delta@np.array(axis[:])
        radial = np.linalg.norm(delta-np.outer(travel, np.array(axis[:])), axis=1)
        domain = (travel > -.025*unit) & (travel < .23*unit) & (radial < .14*unit)
        prefix = ("hand_", "thumb_", "index_", "middle_", "ring_", "pinky_")
        seeds = {i for i, weights in enumerate(original_weights) if domain[i] and
                 sum(v for n, v in weights.items() if n.endswith("_"+side) and n.startswith(prefix)) > .5}
        # Spatially near hip plates are separate surfaces in the actual A
        # pose. Follow welded glove topology so they never receive hand weights.
        region, queue = set(seeds), list(seeds)
        for i in queue:
            for neighbor in adjacency[i]:
                if domain[neighbor] and neighbor not in region:
                    region.add(neighbor)
                    queue.append(neighbor)
        regions[side] = sorted(region)
        for index in sorted(region):
            q = max(0., min(1., (travel[index]+.025*unit)/(.032*unit)))
            strength = q*q*(3-2*q)
            if strength <= 1e-6:
                continue
            # The original bad fingertip transfer includes pure calf weights.
            # Remove those remote leg influences even in the cuff transition.
            source_weights = {n: v for n, v in original_weights[index].items()
                              if n.endswith("_"+side) and n.startswith(prefix+("lowerarm_", "upperarm_"))}
            total = sum(source_weights.values())
            source_weights = {n: v/total for n, v in source_weights.items()} if total else {"hand_"+side: 1.}
            weights = {name: value*(1-strength) for name, value in source_weights.items()}
            weights["hand_"+side] = weights.get("hand_"+side, 0.)+strength
            weights = {name: value for name, value in weights.items() if value > 1e-7}
            for group in body.vertex_groups:
                group.remove([index])
            for name, value in weights.items():
                body.vertex_groups[name].add([index], value, "REPLACE")
            changed[side].append(index)
    if min(len(values) for values in changed.values()) < 100:
        raise ValueError("Measured glove region is unexpectedly small")
    after = measurements()
    (output/"after_deformation.json").write_text(json.dumps({"samples": after, "changed_vertices": changed}, indent=2)+"\n", encoding="utf-8")
    if digest(body) != original_geometry:
        raise ValueError("Geometry/UV changed during weight-only repair")
    if max(row["max_edge_stretch"] for row in after) >= max(row["max_edge_stretch"] for row in before)*.6:
        raise ValueError("Local repair did not remove the extreme residual deformation")
    if args.render:
        for clip, t, label in samples:
            activate(clip, t)
            pose.inspection.helper.render_view(output/("after_"+label+".png"), objects,
                                               (-1, 1.4, .3) if label == "MoveRear" else (1, -1.4, .3),
                                               size=640, framing=height*1.55)
    activate("Idle", 0.)
    blend_path = output/"Champion_Future_GloveWeights.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    # Same cm-normalized rest export as the reviewed bundle, no action export.
    normalized = rig.copy()
    normalized.data = rig.data.copy()
    normalized.name = "Armature"
    normalized.animation_data_clear()
    normalized.parent = None
    normalized.matrix_world = Matrix.Identity(4)
    normalized.data.transform(Matrix.Scale(100, 4) @ rig.matrix_world)
    scene.collection.objects.link(normalized)
    copied = body.copy()
    copied.data = body.data.copy()
    copied.name = "SK_Champion_Future_GloveWeights_Body"
    copied.data.transform(Matrix.Scale(100, 4) @ body.matrix_world)
    copied.parent = None
    copied.matrix_world = Matrix.Identity(4)
    for modifier in copied.modifiers:
        if modifier.type == "ARMATURE":
            modifier.object = normalized
    scene.collection.objects.link(copied)
    for pb in normalized.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.matrix_basis = Matrix.Identity(4)
    scene.unit_settings.scale_length = .01
    fbx_path = output/"SK_Champion_Future_GloveWeights.fbx"
    export.fbx(fbx_path, [normalized, copied])
    report = {"schema": "future_glove_weight_repair_v1", "source_blend": record(source_blend),
              "mesh_fbx": record(fbx_path), "blend": record(blend_path), "geometry_before": original_geometry,
              "geometry_after": digest(body), "changed_vertices": changed, "before": before, "after": after,
              "retained": ["all five source actions", "original geometry/UV", "4K PBR", "weapon_r bone and attachment"],
              "runtime_activated": False, "gameplay_approved": False}
    (output/"repair_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "changed_counts": {k: len(v) for k, v in changed.items()},
                      "before_max": max(row["max_edge_stretch"] for row in before),
                      "after_max": max(row["max_edge_stretch"] for row in after)}))


if __name__ == "__main__":
    main()
