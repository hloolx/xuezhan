"""Author a NEW local binding; never recover or trust broken Tripo skin data.

Actual target mesh/UV/PBR is preserved. A real FBX supplies a fitted template
and surface weights for explicitly local authoring. Requires the heavy lease.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import barycentric_transform

sys.path.insert(0, str(Path(__file__).parent))
import prepare_era_asset
import prepare_era_character as character

ROOT = Path(__file__).resolve().parents[2]


def smooth(a, b, value):
    q = max(0., min(1., (value-a)/(b-a)))
    return q*q*(3-2*q)


def digest_mesh(mesh):
    points = np.array([v.co[:] for v in mesh.data.vertices], dtype="<f8")
    faces = [[v for v in p.vertices] for p in mesh.data.polygons]
    uv = np.array([v.uv[:] for v in mesh.data.uv_layers.active.data], dtype="<f8")
    return {"vertices": len(points), "polygons": len(faces),
            "positions_sha256": hashlib.sha256(points.tobytes()).hexdigest(),
            "topology_sha256": hashlib.sha256(json.dumps(faces).encode()).hexdigest(),
            "uv_sha256": hashlib.sha256(uv.tobytes()).hexdigest()}


def unskinned_geometry(source, output):
    doc, binary = prepare_era_asset.glb(source)
    result = copy.deepcopy(doc)
    nodes = [copy.deepcopy(node) for node in doc["nodes"] if "mesh" in node]
    if len(nodes) != 1:
        raise ValueError("Prototype expects one actual source mesh")
    for node in nodes:
        node.pop("skin", None)
        node.pop("children", None)
    for mesh in result["meshes"]:
        for primitive in mesh["primitives"]:
            for name in list(primitive["attributes"]):
                if name.startswith(("JOINTS_", "WEIGHTS_")):
                    del primitive["attributes"][name]
    result["nodes"], result["scenes"], result["scene"] = nodes, [{"nodes": [0]}], 0
    result.pop("skins", None)
    result.pop("animations", None)
    result["asset"]["generator"] = "CivWar explicitly new local binding geometry input"
    text = json.dumps(result, separators=(",", ":")).encode()
    text += b" "*(-len(text) % 4)
    output.write_bytes(struct.pack("<III", 0x46546C67, 2, 28+len(text)+len(binary))+
                       struct.pack("<II", len(text), 0x4E4F534A)+text+
                       struct.pack("<II", len(binary), 0x004E4942)+binary)
    return {"binary_unchanged": prepare_era_asset.glb(output)[1] == binary,
            "operation": "Remove invalid skin references in a derived input only; keep BIN unchanged",
            "discarded_weights_recovered": False}


def blend_weights(a, b, fraction):
    return {key: a.get(key, 0)*(1-fraction)+b.get(key, 0)*fraction for key in a.keys() | b.keys()}


def normalize(weights):
    weights = {k: float(v) for k, v in weights.items() if v > 1e-7}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Region constraints removed every influence")
    return {k: v/total for k, v in weights.items()}


def refine_connected_regions(rig, body, target, height, region_path, source):
    regions = character.read(region_path)
    if regions["source"]["sha256"] != prepare_era_asset.record(source)["sha256"]:
        raise ValueError("Connected regions belong to another actual source")
    hand_fit = {}
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for side, sign in (("r", -1), ("l", 1)):
        wrist = rig.data.edit_bones["hand_"+side].head.copy()
        sample = target[(target[:, 0]*sign > .27*height) &
                        (abs(target[:, 2]-wrist.z) < .025*height)]
        if len(sample) < 8:
            raise ValueError("Missing actual wrist cross-section for local hand fit")
        wanted = Vector((float(np.median(sample[:, 0])), float(np.median(sample[:, 1])), wrist.z))
        delta = wanted-wrist
        delta.x = max(-.015*height, min(.015*height, delta.x))
        names = ["hand_"+side]+[b.name for b in rig.data.edit_bones
                                if b.name.endswith("_"+side) and b.name.startswith(
                                    ("thumb_", "index_", "middle_", "ring_", "pinky_"))]
        for name in names:
            bone = rig.data.edit_bones[name]
            bone.head += delta
            bone.tail += delta
        rig.data.edit_bones["lowerarm_"+side].tail = wrist+delta
        hand_fit[side] = {"actual_wrist_surface_vertices": len(sample), "shift_m": list(delta),
                          "wrist_before_m": list(wrist), "wrist_after_m": list(wrist+delta)}
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    tree = KDTree(regions["unique_vertices"])
    points = [Vector(p) for p in regions["points_world_m"]]
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    matching = [tree.find(Vector(point)) for point in target]
    if max(row[2] for row in matching) > 2e-5:
        raise ValueError("Actual imported mesh differs from connected region coordinates")
    aliases = [row[1] for row in matching]
    cape, tabard = regions["cape_strength"], regions["tabard_strength"]
    frames = {}
    for side in ("r", "l"):
        wrist = rig.data.bones["hand_"+side].head_local.copy()
        knuckle = rig.data.bones["middle_01_"+side].head_local.copy()
        frames[side] = wrist, (knuckle-wrist).normalized(), (knuckle-wrist).length

    def segment_distance(point, bone):
        a, b = bone.head_local, bone.tail_local
        segment = b-a
        t = max(0., min(1., (point-a).dot(segment)/max(segment.length_squared, 1e-10)))
        return (point-a-segment*t).length

    def cloth_constraint(weights, index):
        p = points[index]/height
        if cape[index] > .01:
            # A continuous real cloth face must never inherit the neighboring
            # arm, hand or leg simply because it is spatially close.
            lower = 1-smooth(.68, .80, p.z)
            controlled = {"local_cape": lower, "spine_02": 1-lower}
            strength = smooth(0., .25, cape[index])
            weights = blend_weights(weights, controlled, strength)
        if tabard[index] > .01:
            lower = 1-smooth(.47, .535, p.z)
            controlled = {"local_tabard": lower, "pelvis": 1-lower}
            weights = blend_weights(weights, controlled, smooth(0., .25, tabard[index]))
        if not regions.get("cloth_helpers", True):
            # These targets have separated legs/arms in the actual A pose.
            # Do not let surface proximity transfer a neighbouring limb.
            side = "r" if p.x < 0 else "l"
            other = "l" if side == "r" else "r"
            if p.z < .44 and .035 < abs(p.x) < .23:
                allowed = ("thigh_", "calf_", "foot_", "ball_")
                weights = {n: v for n, v in weights.items()
                           if n.startswith(allowed) and n.endswith("_"+side)}
                if not weights:
                    weights = {"calf_"+side: 1.}
            elif abs(p.x) > .24 and p.z > .38:
                weights = {n: v for n, v in weights.items()
                           if not n.endswith("_"+other) and not n.startswith(("thigh_", "calf_", "foot_", "ball_"))}
                if not weights:
                    weights = {"lowerarm_"+side: 1.}
            if p.z < .035 and abs(p.x) > .035:
                foot = rig.data.bones["foot_"+side].head_local
                ball = rig.data.bones["ball_"+side].head_local
                fraction = smooth(0., 1., (points[index].y-foot.y)/min(ball.y-foot.y, -1e-7))
                weights = {"foot_"+side: 1-fraction, "ball_"+side: fraction}
            plate = regions.get("pelvis_plate_strength")
            if plate and plate[index] > .001:
                weights = blend_weights(weights, {"pelvis": 1.}, plate[index])
            if regions.get("rigid_hands"):
                wrist, axis, _ = frames[side]
                offset = points[index]-wrist
                travel = offset.dot(axis)
                radial = (offset-axis*travel).length
                if abs(p.x) > .20 and -.03*height < travel < .18*height and radial < .075*height:
                    weights = blend_weights(weights, {"hand_"+side: 1.},
                                            smooth(-.03*height, .002*height, travel))
        return normalize(weights)

    group_names = {g.index: g.name for g in body.vertex_groups}
    dense, counts = [{} for _ in points], [0 for _ in points]
    glove_count = {"r": 0, "l": 0}
    for vertex, position, alias in zip(body.data.vertices, target, aliases):
        weights = {group_names[g.group]: g.weight for g in vertex.groups}
        p = Vector(position)
        side = "r" if p.x < 0 else "l"
        wrist, axis, knuckle_distance = frames[side]
        travel = (p-wrist).dot(axis)
        if abs(p.x) > regions.get("hand_lateral_min_height", .265)*height and p.z < .55*height and -.025*height < travel < .20*height:
            candidates = {}
            for digit in ("thumb", "index", "middle", "ring", "pinky"):
                names = [f"{digit}_{joint:02d}_{side}" for joint in (1, 2, 3)]
                distances = [(name, segment_distance(p, rig.data.bones[name])) for name in names]
                candidates[digit] = distances
            chosen = min(candidates.values(), key=lambda rows: min(d for _, d in rows))
            fingers = {name: 1/(distance+.006*height)**3 for name, distance in chosen}
            fingers = normalize(fingers)
            finger_fraction = smooth(knuckle_distance*.48, knuckle_distance*1.03, travel)
            hand = blend_weights({"hand_"+side: 1.}, fingers, finger_fraction)
            weights = blend_weights(weights, hand, smooth(-.025*height, .012*height, travel))
            glove_count[side] += 1
        weights = cloth_constraint(weights, alias)
        for name, value in weights.items():
            dense[alias][name] = dense[alias].get(name, 0)+value
        counts[alias] += 1
    dense = [normalize(row) for row in dense]
    adjacency = regions["welded_adjacency"]
    # Smooth real connected neighbors, with cloth constraints re-applied each
    # pass. UV seam duplicates share a single field; air gaps never join.
    for _ in range(5):
        next_values = []
        for i, neighbors in enumerate(adjacency):
            average = {}
            for neighbor in neighbors:
                for name, value in dense[neighbor].items():
                    average[name] = average.get(name, 0)+value/len(neighbors)
            value = blend_weights(dense[i], average, .32) if neighbors else dense[i]
            next_values.append(cloth_constraint(value, i))
        dense = next_values
    body.vertex_groups.clear()
    groups = {bone.name: body.vertex_groups.new(name=bone.name) for bone in rig.data.bones}
    mass = {name: 0. for name in groups}
    for index, alias in enumerate(aliases):
        weights = normalize(dict(sorted(dense[alias].items(), key=lambda pair: pair[1], reverse=True)[:4]))
        for name, value in weights.items():
            groups[name].add([index], value, "REPLACE")
            mass[name] += value
    return {"region_source": prepare_era_asset.record(region_path), "hand_fit": hand_fit,
            "glove_vertices_reweighted": glove_count, "welded_smoothing_iterations": 5,
            "cape_vertices_constrained": sum(cape[i] > .01 for i in aliases),
            "tabard_vertices_constrained": sum(tabard[i] > .01 for i in aliases),
            "joint_weight_mass": mass, "maximum_region_point_match_m": max(row[2] for row in matching)}


def author(source, template, output, region_path=None, asset_id="Champion_Medieval", cloth_helpers=True):
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    bpy.ops.import_scene.fbx(filepath=str(template), use_anim=False, automatic_bone_orientation=False)
    rig, = [o for o in scene.objects if o.type == "ARMATURE"]
    template_mesh, = [o for o in scene.objects if o.type == "MESH" and
                     any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
    template_objects = set(scene.objects)
    rig.animation_data_clear()
    for bone in rig.pose.bones:
        bone.matrix_basis.identity()
    bpy.context.view_layer.update()
    geometry_path = output/"original_geometry_without_invalid_skin.glb"
    geometry_receipt = unskinned_geometry(source, geometry_path)
    bpy.ops.import_scene.gltf(filepath=str(geometry_path), merge_vertices=False, disable_bone_shape=True)
    body, = [o for o in scene.objects if o not in template_objects and o.type == "MESH"]
    before = digest_mesh(body)
    original = np.array([template_mesh.matrix_world @ v.co for v in template_mesh.data.vertices])
    target = np.array([body.matrix_world @ v.co for v in body.data.vertices])
    old_low, old_high = original.min(axis=0), original.max(axis=0)
    low, high = target.min(axis=0), target.max(axis=0)
    height = float(high[2]-low[2])
    ratios = (high-low)/(old_high-old_low)
    # Cape depth does not imply the same change to the torso joint depth.
    scales = np.array([ratios[0], np.clip(ratios[1], .93*ratios[2], 1.08*ratios[2]), ratios[2]])
    translation = np.array([(low[0]+high[0])/2-(old_low[0]+old_high[0])/2*scales[0],
                            0, low[2]-old_low[2]*scales[2]])
    fitted = original*scales+translation
    fit = Matrix.Diagonal([*scales, 1.])
    fit.translation = Vector(translation)
    old_names = [bone.name for bone in rig.data.bones]
    group_names = {g.index: g.name for g in template_mesh.vertex_groups if g.name in old_names}
    source_weights = []
    for vertex in template_mesh.data.vertices:
        weights = {group_names[g.group]: g.weight for g in vertex.groups if g.group in group_names and g.weight > 1e-7}
        total = sum(weights.values())
        if total < .9:
            raise ValueError("Actual FBX template has unweighted geometry")
        source_weights.append({k: v/total for k, v in weights.items()})
    template_mesh.data.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in template_mesh.data.loop_triangles]
    tree = BVHTree.FromPolygons([Vector(v) for v in fitted], triangles, all_triangles=True)
    rig.matrix_world = fit @ rig.matrix_world
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()
    fitted_heads = {b.name: list(rig.matrix_world @ b.head_local) for b in rig.data.bones}
    helper_definitions = (
        ("local_cape", "spine_02", (0, .095*height, .755*height), (0, .14*height, .35*height)),
        ("local_tabard", "pelvis", (0, -.095*height, .51*height), (0, -.12*height, .28*height)),
    ) if cloth_helpers else ()
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent, head, tail in helper_definitions:
        bone = rig.data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        bone.parent = rig.data.edit_bones[parent]
        bone.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    body.vertex_groups.clear()
    groups = {b.name: body.vertex_groups.new(name=b.name) for b in rig.data.bones}
    distances, cape_count, tabard_count = [], 0, 0
    joint_mass = {name: 0. for name in groups}
    for index, point in enumerate(target):
        hit, normal, triangle_index, distance = tree.find_nearest(Vector(point))
        if hit is None:
            raise ValueError("No actual template surface correspondence")
        tri = triangles[triangle_index]
        bary = barycentric_transform(hit, *(Vector(fitted[i]) for i in tri),
                                     Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        bary = [max(0., min(1., f)) for f in bary]
        bary_total = sum(bary)
        if bary_total < .99:
            raise ValueError("Invalid nearest triangle barycentric projection")
        weights = {}
        for source_index, amount in zip(tri, bary):
            for bone, value in source_weights[source_index].items():
                weights[bone] = weights.get(bone, 0)+value*amount/bary_total
        # World X across, Y toward the back, Z up; include white cloth edges.
        lateral, rear, vertical = point/height
        cape = (smooth(.055, .095, rear) * (1-smooth(.19, .24, abs(lateral))) *
                smooth(.28, .34, vertical) * (1-smooth(.75, .81, vertical)))
        tabard = (smooth(.06, .10, -rear) * (1-smooth(.105, .14, abs(lateral))) *
                  smooth(.25, .29, vertical) * (1-smooth(.50, .54, vertical)))
        if cloth_helpers and cape and not region_path:
            weights = blend_weights(weights, {"local_cape": 1.}, cape)
            cape_count += cape > .5
        if cloth_helpers and tabard and not region_path:
            weights = blend_weights(weights, {"local_tabard": 1.}, tabard)
            tabard_count += tabard > .5
        weights.pop("root", None)
        weights = dict(sorted(weights.items(), key=lambda row: row[1], reverse=True)[:4])
        total = sum(weights.values())
        if total < .001:
            raise ValueError("New binding has an unsupported vertex")
        for name, value in weights.items():
            value /= total
            groups[name].add([index], value, "REPLACE")
            joint_mass[name] += value
        distances.append(distance)
    required = ("pelvis", "spine_02", "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
                "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r")
    if any(joint_mass[name] < 1 for name in required):
        raise ValueError("New local binding lacks actual limb coverage")
    # Actual boot silhouettes differ from the template. Locate ankle and toe
    # pivots inside each real sole; do not waive the downstream heel/toe gate.
    foot_fit = {}
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for side, sign in (("r", -1), ("l", 1)):
        points = target[(target[:, 0]*sign > .04*height) & (target[:, 2] < low[2]+.08*height)]
        sole = points[points[:, 2] < points[:, 2].min()+.025*height]
        if len(sole) < 8:
            raise ValueError("Insufficient actual sole geometry for local ankle fit")
        heel, toe = float(sole[:, 1].max()), float(sole[:, 1].min())
        center = float(np.median(sole[:, 0]))
        ankle = Vector((center, heel*.75+toe*.25, float(low[2]+.06*height)))
        ball = Vector((center, heel*.25+toe*.75, float(low[2]+.027*height)))
        foot_bone, ball_bone = rig.data.edit_bones["foot_"+side], rig.data.edit_bones["ball_"+side]
        ball_tail = ball_bone.tail-ball_bone.head
        foot_bone.head, foot_bone.tail = ankle, ball
        ball_bone.head, ball_bone.tail = ball, ball+ball_tail
        foot_fit[side] = {"actual_sole_vertices": len(sole), "heel_y_m": heel, "toe_y_m": toe,
                          "ankle_m": list(ankle), "ball_m": list(ball)}
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    region_refinement = refine_connected_regions(rig, body, target, height, region_path, source) if region_path else None
    if region_refinement:
        joint_mass = region_refinement["joint_weight_mass"]
        cape_count = region_refinement["cape_vertices_constrained"]
        tabard_count = region_refinement["tabard_vertices_constrained"]
    fitted_heads = {b.name: list(rig.matrix_world @ b.head_local) for b in rig.data.bones}
    world = body.matrix_world.copy()
    body.parent = rig
    body.matrix_world = world
    modifier = body.modifiers.new("LocallyAuthoredSkin", "ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = False
    for obj in list(template_objects):
        if obj != rig:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(scene.objects):
        if obj not in (body, rig):
            bpy.data.objects.remove(obj, do_unlink=True)
    body.name, rig.name = asset_id+"_OriginalGeometry", asset_id+"_LocalAuthoredRig"
    bpy.context.view_layer.update()
    after = digest_mesh(body)
    if before != after:
        raise ValueError("Binding modified original mesh/UV")
    evaluated_object = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated = evaluated_object.to_mesh()
    error = max((body.matrix_world @ v.co-Vector(target[i])).length for i, v in enumerate(evaluated.vertices))
    evaluated_object.to_mesh_clear()
    weight_sums = [sum(g.weight for g in v.groups) for v in body.data.vertices]
    if error > 1e-5 or min(weight_sums) < .9999 or max(weight_sums) > 1.0001:
        raise ValueError("Rest skin or normalization check failed")
    blend = output/"local_authored_bind.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    result = {
        "schema": "explicit_local_authored_human_binding_v1",
        "asset_id": asset_id, "rig_origin": "local_authored",
        "source_geometry": prepare_era_asset.record(source),
        "template_actual_fbx": prepare_era_asset.record(template),
        "template_role": "Measured skeleton and surface weights as inputs to a new locally fitted binding",
        "broken_tripo_skin_used": False, "recovered_tripo_binding": False,
        "source_geometry_derivation": geometry_receipt,
        "fit": {"scale_axes": scales.tolist(), "translation_m": translation.tolist()},
        "fitted_bone_heads_m": fitted_heads, "additional_local_bones": [row[0] for row in helper_definitions],
        "actual_sole_pivot_fit": foot_fit,
        "connected_region_refinement": region_refinement,
        "original_mesh_before": before, "original_mesh_after": after,
        "rest_deformation_max_m": error, "weight_sum_range": [min(weight_sums), max(weight_sums)],
        "weight_count_max": max(len(v.groups) for v in body.data.vertices),
        "joint_weight_mass": {k: float(v) for k, v in joint_mass.items()}, "cape_region_vertices": int(cape_count),
        "tabard_region_vertices": int(tabard_count),
        "template_surface_distance_m": {"mean": float(np.mean(distances)), "p95": float(np.percentile(distances, 95)),
                                         "max": float(max(distances))},
        "blend": prepare_era_asset.record(blend),
        "status": "actual_local_binding_saved_pending_motion_and_visual_review",
        "production_approved": False,
    }
    character.write(output/"binding_receipt.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--binding-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--regions", type=Path)
    parser.add_argument("--asset", default="Champion_Medieval")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    plan = next(p for p in character.read(args.plan)["entries"] if p["asset_id"] == args.asset)
    canonical = ROOT/"RawAssets/Art/Tripo_v01/tripo_raw"
    preparation = plan.get("local_binding_preparation", {})
    source = Path(preparation["source_geometry"]["path"]) if preparation else canonical/args.asset/"web_v01_canonical/pbr.glb"
    template = Path(preparation["template_actual_fbx"]["path"]) if preparation else canonical/"Unit_Knight/web_v01_canonical/rigged.fbx"
    for row in preparation.values():
        if isinstance(row, dict) and "sha256" in row and prepare_era_asset.record(Path(row["path"]))["sha256"] != row["sha256"]:
            raise ValueError("Frozen local-binding input changed")
    regions = args.regions or (Path(preparation["regions"]["path"]) if preparation else None)
    cloth_helpers = preparation.get("cloth_helpers", True)
    result = author(source, template, args.binding_output.resolve(), regions, args.asset, cloth_helpers)
    plan.pop("source_fbx", None)
    plan.pop("source_usd", None)
    plan["source_local_authored_rig"] = result["blend"]
    plan["source_local_bind_receipt"] = prepare_era_asset.record(args.binding_output/"binding_receipt.json")
    plan["source_geometry"] = result["source_geometry"]
    plan["rig_provenance"] = {"origin": "local_authored", "receipt": plan["source_local_bind_receipt"],
                              "tripo_skin_recovery": False}
    plan["status"], plan["missing_inputs"] = "ready_for_leased_blender_preparation", []
    if any(m["status"] != "source_module_present" for m in plan["modules"]):
        raise ValueError("Actual independent equipment is missing")
    plan["source_reference_pose_claim"] = "New local fit/weights on intact original geometry, not a recovered Tripo skin"
    plan["local_cloth_motion"], plan["render_local_bind_checks"] = cloth_helpers, True
    character.build(plan, args.output.resolve(), render=args.render)


if __name__ == "__main__":
    main()
