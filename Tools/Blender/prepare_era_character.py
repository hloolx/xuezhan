"""Author preview actions on an actual downloaded UE5 Tripo human and equipment.

Leased Blender only:
  blender -b -t 2 --python-exit-code 1 --python Tools/Blender/prepare_era_character.py -- \
    --plan character_plan.json --asset Unit_ShieldSword --output <new-candidate> --render

Input planning is performed by Tools/prepare_era_character_plan.py. This tool
does not replace body geometry, modify gameplay data,
or approve a character before its real images/UE import have been checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


def sample_keys(keys, t):
    """C1 eased numeric key interpolation; endpoints are exactly reproducible."""
    if t <= keys[0][0]:
        return list(keys[0][1])
    if t >= keys[-1][0]:
        return list(keys[-1][1])
    for (a, av), (b, bv) in zip(keys, keys[1:]):
        if a <= t <= b:
            f = smooth((t-a)/(b-a))
            return [x+(y-x)*f for x, y in zip(av, bv)]
    raise ValueError("Uncovered motion time")


def exact_source_textures(plan, output):
    """Extract embedded original PBR bytes, without a color-management re-save."""
    import prepare_era_asset
    document, binary = prepare_era_asset.glb(plan.get("source_geometry", plan["source_rig"])["path"])
    material, = document["materials"]
    pbr = material["pbrMetallicRoughness"]
    textures = {
        "base_color": pbr["baseColorTexture"]["index"],
        "normal": material["normalTexture"]["index"],
        "metallic_roughness": pbr["metallicRoughnessTexture"]["index"],
    }
    records = {}
    for channel, index in textures.items():
        image = document["images"][document["textures"][index]["source"]]
        if "bufferView" not in image:
            raise ValueError("Source PBR image must be embedded")
        view = document["bufferViews"][image["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError("Unexpected external PBR buffer")
        start, size = view.get("byteOffset", 0), view["byteLength"]
        extension = {"image/png": ".png", "image/jpeg": ".jpg"}[image["mimeType"]]
        path = output/("T_"+plan["asset_id"]+"_"+channel+extension)
        path.write_bytes(binary[start:start+size])
        records[channel] = {"path": str(path), "bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return records


def bind_original_pbr(mesh, records):
    """FBX supplies binding; its JPEG conversion must not replace GLB PBR."""
    import bpy
    material = mesh.data.materials[0]
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    surface = tree.nodes.new("ShaderNodeBsdfPrincipled")
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(surface.outputs["BSDF"], output.inputs["Surface"])
    nodes = {}
    for channel, record in records.items():
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(record["path"], check_existing=True)
        node.image.colorspace_settings.name = "sRGB" if channel == "base_color" else "Non-Color"
        nodes[channel] = node
    tree.links.new(nodes["base_color"].outputs["Color"], surface.inputs["Base Color"])
    normal = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(nodes["normal"].outputs["Color"], normal.inputs["Color"])
    tree.links.new(normal.outputs["Normal"], surface.inputs["Normal"])
    separate = tree.nodes.new("ShaderNodeSeparateColor")
    tree.links.new(nodes["metallic_roughness"].outputs["Color"], separate.inputs["Color"])
    tree.links.new(separate.outputs["Green"], surface.inputs["Roughness"])
    tree.links.new(separate.outputs["Blue"], surface.inputs["Metallic"])


def attack_parameters(profile, t, contact, duration):
    """x/y/z hand target, weapon pitch about Y, spine pitch; 150cm reference."""
    if profile == "bow_crew":
        return [.15, -.05, 1.16, 0., 0.]
    if profile == "mounted_lance":
        return sample_keys([
            (0, [.20, -.36, .94, 0., 0.]),
            (.65*contact, [.10, -.36, .96, -5., -3.]),
            (contact, [.47, -.36, .93, 0., 5.]),
            (contact+.16*(duration-contact), [.51, -.36, .92, 3., 6.]),
            (duration, [.20, -.36, .94, 0., 0.])], t)
    melee = profile in {"sword_shield", "baton_shield", "energy_blade", "one_hand", "shovel", "two_hand_hammer"}
    if melee:
        idle = [.20, -.36, .94, 18., 0.]
        raised = [.03, -.38, 1.24, -35., -4.]
        strike = [.43, -.36, 1.00, 88., 7.]
        follow = [.37, -.36, .82, 108., 8.]
        if profile in {"two_hand_hammer", "shovel"}:
            idle = [.23, -.24, 1.02, 20., 0.]
            raised = [.02, -.24, 1.27, -30., -5.]
            strike = [.44, -.24, .95, 85., 9.]
            follow = [.35, -.24, .82, 105., 10.]
        return sample_keys([(0, idle), (.70*contact, raised), (contact, strike),
                            (contact+.20*(duration-contact), follow), (duration, idle)], t)
    idle = [.24, -.22, 1.12, 0., 0.]
    if profile == "launcher":
        idle = [.11, -.27, 1.27, 0., 0.]
    aim = [*idle[:3], -3., 1.]
    recoil = [idle[0]-.045, idle[1], idle[2]+.016, -8., -2.]
    lowered = [idle[0]+.015, idle[1], idle[2]-.12, 16., 0.]
    return sample_keys([(0, idle), (.55*contact, aim), (contact, aim),
                        (contact+.10*(duration-contact), recoil),
                        (contact+.48*(duration-contact), lowered), (duration, idle)], t)


def validate_plan(plan):
    if plan.get("execution_adapter", "generic_human") not in {"generic_human", "bow_crew_adapter_required", "mounted_lance_rider"}:
        raise ValueError("This source requires its explicit assembly adapter: " + plan["execution_adapter"])
    if plan["status"] != "ready_for_leased_blender_preparation":
        raise ValueError("Real source/modules not ready: " + str(plan["missing_inputs"]))
    records = [plan["source_rig"], plan["source_brief"], plan["gameplay_table"]]
    if plan.get("source_fbx"):
        records.append(plan["source_fbx"])
    if plan.get("source_usd"):
        records.extend([plan["source_usd"], plan["source_usd_receipt"]])
    if plan.get("source_local_authored_rig"):
        records.extend([plan["source_local_authored_rig"], plan["source_local_bind_receipt"], plan["source_geometry"]])
    for module in plan["modules"]:
        records.extend([module["source"], module["interface"]])
        if module.get("blend"):
            records.append(module["blend"])
        for material in (module.get("pbr_materials") or {}).values():
            records.extend(material["textures"].values())
    for row in records:
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Prepared plan input changed: " + row["path"])
    if not plan["primary_weapon"]:
        raise ValueError("Explicit main weapon required")
    if any(m["asset_id"].startswith("Prop_") and m["asset_id"] != "Prop_DemolitionPack" for m in plan["modules"]):
        raise ValueError("This auxiliary prop requires an explicit body attachment adapter")


def build(plan, output, render=False):
    validate_plan(plan)
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    sys.path.insert(0, str(Path(__file__).parent))
    import build_mammoth_preview as export
    import prepare_stoneaxe_pose_pilot as pose
    output.mkdir(parents=True, exist_ok=False)
    write(output/"input_plan.json", plan)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    scene.render.fps, scene.render.fps_base = plan["fps"], 1.
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1.
    if plan.get("source_local_authored_rig"):
        with bpy.data.libraries.load(plan["source_local_authored_rig"]["path"], link=False) as (library, loaded):
            loaded.objects = library.objects
        for obj in loaded.objects:
            scene.collection.objects.link(obj)
    elif plan.get("source_fbx"):
        bpy.ops.import_scene.fbx(filepath=plan["source_fbx"]["path"], use_anim=False)
    elif plan.get("source_usd"):
        from inspect_era_usd import import_and_inspect
        usd_inspection = import_and_inspect(Path(plan["source_usd"]["path"]), plan["source_rig"]["joint_names"])
        write(output/"actual_usd_bind_inspection.json", usd_inspection)
    else:
        bpy.ops.import_scene.gltf(filepath=plan["source_rig"]["path"], merge_vertices=False, disable_bone_shape=True)
    # FBX import changes scene timing to the source's 24fps even without
    # animations. Our keyed frames and authority samples are explicitly 60fps.
    scene.render.fps, scene.render.fps_base = plan["fps"], 1.
    rigs = [o for o in scene.objects if o.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("Expected one genuine bound human rig")
    rig = rigs[0]
    missing = set(plan["source_rig"]["joint_names"])-set(rig.pose.bones.keys())
    if missing:
        raise ValueError("Actual imported source is missing planned bone names: "+str(sorted(missing)))
    shapes = {pb.custom_shape for pb in rig.pose.bones if pb.custom_shape}
    body = [o for o in scene.objects if o.type == "MESH" and o not in shapes]
    for pb in rig.pose.bones:
        pb.custom_shape = None
    for shape in shapes:
        bpy.data.objects.remove(shape, do_unlink=True)
    if not body or any(not any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers) for o in body):
        raise ValueError("Every body mesh must be skinned to the actual source")
    if len(body) != 1 or len(body[0].data.materials) != 1:
        raise ValueError("Multi-material body requires an explicit PBR slot adapter")
    textures = exact_source_textures(plan, output)
    bind_original_pbr(body[0], textures)
    rig.animation_data_clear()
    pose.reset_pose(rig)
    bind_points = pose.evaluated_world_vertices(body[0])
    bind_low, bind_high = pose.inspection.helper.bounds(body)
    bind_names = {group.index: group.name for group in body[0].vertex_groups}
    sums = [sum(group.weight for group in vertex.groups if bind_names[group.group] in rig.pose.bones)
            for vertex in body[0].data.vertices]
    bone_heads = {bone.name: list(pose.world_head(rig, bone)) for bone in rig.pose.bones}
    bind_error = max((point-body[0].matrix_world @ vertex.co).length
                     for point, vertex in zip(bind_points, body[0].data.vertices))
    if min(sums) < .90 or max(sums) > 1.10 or bind_error > .001*(bind_high.z-bind_low.z):
        raise ValueError("Actual imported source binding fails coverage/rest geometry")
    write(output/"actual_source_bind.json", {
        "source_fbx": plan.get("source_fbx"), "source_local_authored_rig": plan.get("source_local_authored_rig"),
        "rig_origin": plan.get("rig_provenance", {"origin": "actual_tripo_export"})["origin"],
        "actual_named_bones": bone_heads, "actual_vertices": len(sums),
        "weight_sum_range": [min(sums), max(sums)], "rest_deformation_max_m": bind_error,
        "actual_bounds_m": [list(bind_low), list(bind_high)],
        "scope": "Actual imported source, before motion authoring; visual acceptance not inferred"})
    forward = sum((pose.world_head(rig, rig.pose.bones["ball_"+side]) -
                   pose.world_head(rig, rig.pose.bones["foot_"+side]) for side in ("r", "l")), Vector())
    forward.z = 0
    if forward.length < 1e-5:
        raise ValueError("Cannot derive +X forward from actual foot bones")
    yaw = -math.atan2(forward.y, forward.x)
    roots = [o for o in scene.objects if o.parent is None]
    for obj in roots:
        obj.matrix_world = Matrix.Rotation(yaw, 4, "Z") @ obj.matrix_world
    bpy.context.view_layer.update()
    low, high = pose.inspection.helper.bounds(body)
    scale = plan["reference_height_cm"]/100/(high.z-low.z)
    centre = Vector(((low.x+high.x)/2, (low.y+high.y)/2, low.z))
    transform = Matrix.Scale(scale, 4) @ Matrix.Translation(-centre)
    for obj in roots:
        obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    factor = plan["reference_height_cm"]/150
    scaled = lambda xyz: Vector(xyz)*factor
    inverse = rig.matrix_world.inverted()
    rig.name = plan["asset_id"]+"_SourceRig"
    rest_feet = {side: (pose.world_head(rig, rig.pose.bones["foot_"+side]),
                       (rig.matrix_world @ rig.pose.bones["foot_"+side].matrix).to_quaternion()) for side in ("r", "l")}
    mounted = plan["profile"] == "mounted_lance"
    foot_groups = pose.foot_surface_groups(rig, body) if not mounted else {}
    if not mounted and any(not foot_groups[s] for s in ("r", "l")):
        raise ValueError("No real weighted sole surface for foot support")

    def hand_frame(side):
        head = lambda name: pose.world_head(rig, rig.pose.bones[name+"_"+side])
        across = (head("index_01")-head("pinky_01")).normalized()
        longitudinal = head("middle_01")-head("hand")
        longitudinal = (longitudinal-across*longitudinal.dot(across)).normalized()
        return across, longitudinal, across.cross(longitudinal).normalized(), (head("index_01")+head("pinky_01"))/2

    references = {side: (hand_frame(side), (rig.matrix_world @ rig.pose.bones["hand_"+side].matrix).to_quaternion())
                  for side in ("r", "l")}

    def grip_rotation(side, prop_rotation):
        frame, bone_q = references[side]
        original = Matrix(frame[:3]).transposed()
        # Actual metacarpal across-axis follows a vertical handle; fingers
        # wrap forward. The left handed anatomy is measured independently.
        axes = ((1, 0, 0), (0, 0, -1), (0, 1, 0)) if mounted and side == "r" else (
            (0, 0, 1), (1, 0, 0), (0, 1, 0))
        target = Matrix(tuple(prop_rotation @ Vector(axis) for axis in axes)).transposed()
        return (target @ original.inverted()).to_quaternion() @ bone_q

    def close_hand(side):
        if side == "r":
            pose.close_grip(rig)
            return
        across, longitudinal, palm, _ = hand_frame(side)
        local = rig.matrix_world.to_quaternion().inverted()
        for digit in ("index", "middle", "ring", "pinky"):
            for joint, angle in enumerate(pose.DIGIT_ANGLES[digit], 1):
                pose.rotate_rest_axis(rig.pose.bones[f"{digit}_{joint:02d}_{side}"], local @ across, math.radians(angle))
        for joint, angle in ((1, -15), (2, 40), (3, 8)):
            pose.rotate_rest_axis(rig.pose.bones[f"thumb_{joint:02d}_{side}"], local @ palm, math.radians(angle))
        bpy.context.view_layer.update()

    def palm_point(side):
        _, longitudinal, palm, centre = hand_frame(side)
        return centre + longitudinal*.012*factor - palm*.008*factor

    def fit_hand(side, target_grip, prop_q):
        wrist = rig.pose.bones["hand_"+side]
        wrist_q = grip_rotation(side, prop_q)
        sign = -1 if side == "r" else 1
        error = None
        for _ in range(3):
            pose.set_world_rotation(rig, wrist, wrist_q)
            offset = palm_point(side)-pose.world_head(rig, wrist)
            error = pose.solve_arm(rig, rig.pose.bones["upperarm_"+side], rig.pose.bones["lowerarm_"+side],
                                   wrist, target_grip-offset, scaled((-.20, sign*.65, 1.0)))
        pose.set_world_rotation(rig, wrist, wrist_q)
        close_hand(side)
        return (palm_point(side)-target_grip).length, error

    # Keep every real source prop separate, including authored crossbow controls.
    equipment = {}
    for module in plan["modules"]:
        before = set(bpy.data.objects)
        if module.get("blend"):
            with bpy.data.libraries.load(module["blend"]["path"], link=False) as (available, requested):
                requested.objects = list(available.objects)
            imported = [o for o in requested.objects if o]
            for obj in imported:
                scene.collection.objects.link(obj)
        else:
            bpy.ops.import_scene.gltf(filepath=module["source"]["path"], merge_vertices=False)
            imported = list(set(bpy.data.objects)-before)
        extras = [o for o in imported if o.type in {"CAMERA", "LIGHT"} or o.name.startswith("DISPLAY_")]
        for obj in extras:
            bpy.data.objects.remove(obj, do_unlink=True)
        imported = [o for o in imported if o not in extras]
        bpy.context.view_layer.update()
        interface = read(module["interface"]["path"])
        main = next((o for o in imported if o.name == interface["root"]), None)
        if main is None:
            raise ValueError("Source prop root missing: "+module["asset_id"])
        # Existing source anchors and matrices are authoritative, not bbox guesses.
        equipment[module["asset_id"]] = {
            "source": module, "root": main, "objects": imported,
            "meshes": [o for o in imported if o.type == "MESH"],
            "anchors": interface["anchors"],
            "original_matrices": {o: main.matrix_world.inverted() @ o.matrix_world for o in imported},
        }
        main.parent = None
        main.matrix_world = Matrix.Identity(4)
        for obj in imported:
            obj.animation_data_clear()
            if obj.type == "MESH" and obj.data.shape_keys:
                obj.data.shape_keys.animation_data_clear()
    primary = equipment[plan["primary_weapon"]]
    shield = equipment.get(plan["shield"])
    backpack = equipment.get("Prop_DemolitionPack")
    bow = plan["profile"] == "bow_crew"
    primary_bone = "weapon_l" if bow else "weapon_r"
    primary["bone"] = primary_bone
    if shield:
        shield["bone"] = "shield_l"
    backpack_local = None
    backpack_contact = None
    if backpack:
        backpack["bone"] = "back_pack"
        spine_world = rig.matrix_world @ rig.pose.bones["spine_02"].matrix
        spine_rigid = Matrix.LocRotScale(spine_world.translation, spine_world.to_quaternion(), Vector((1, 1, 1)))
        points = [point for mesh in body for point in pose.evaluated_world_vertices(mesh)
                  if abs(point.y) < .16*factor and abs(point.z-spine_world.translation.z) < .20*factor]
        if not points:
            raise ValueError("Actual back surface could not be measured for the pack")
        mount = Vector((min(point.x for point in points)-.02, 0, spine_world.translation.z))
        anchor = Vector(backpack["anchors"]["back_mount"]["position_m"])
        # The outermost +X vertices belong to curved shoulder straps. Align
        # the real centre back panel to the body, rather than floating the bag
        # behind the tips of those straps.
        pack_points = [backpack["original_matrices"][mesh] @ vertex.co
                       for mesh in backpack["meshes"] for vertex in mesh.data.vertices]
        low = Vector(tuple(min(point[i] for point in pack_points) for i in range(3)))
        high = Vector(tuple(max(point[i] for point in pack_points) for i in range(3)))
        centre = (low+high)/2
        panel = [point for point in pack_points if
                 abs(point.y-centre.y) < (high.y-low.y)*.12 and
                 abs(point.z-centre.z) < (high.z-low.z)*.15]
        if not panel:
            raise ValueError("Actual pack centre back panel has no measurable surface")
        anchor.x = max(point.x for point in panel)
        backpack_contact = {"actual_body_back_m": list(mount), "actual_pack_panel_anchor_m": list(anchor),
                            "central_panel_vertex_count": len(panel), "body_clearance_m": .02}
        backpack_local = spine_rigid.inverted() @ Matrix.Translation(mount-anchor)
    primary_grip = Vector(primary["anchors"]["grip_l" if bow else "grip_r"]["position_m"])
    if bow:
        # The source bow deliberately contains no loaded arrow. Author this
        # small visual arrow separately; the authority projectile remains UE's.
        import build_weapons as kit
        for obj in (
                kit.rod("loaded_arrow", (-.33, -.027, .04), (.38, -.027, .04), .006, "wood_light", primary["root"], vertices=8),
                kit.rod("arrow_tip", (.36, -.027, .04), (.42, -.027, .04), .017, "iron", primary["root"], 0., 8)):
            primary["objects"].append(obj)
            primary["meshes"].append(obj)
            primary["original_matrices"][obj] = primary["root"].matrix_world.inverted() @ obj.matrix_world
        primary["anchors"]["muzzle"]["position_m"] = [.42, -.027, .04]
    # Named helper bones have true keyed transforms, so exports do not depend
    # on Blender-only object constraints or a guessed UE socket orientation.
    export.select([rig])
    bpy.ops.object.mode_set(mode="EDIT")
    helpers = {primary_bone: "hand_l" if bow else "hand_r"}
    if shield:
        helpers["shield_l"] = "lowerarm_l"
    if backpack:
        helpers["back_pack"] = "spine_02"
    if "muzzle" in primary["anchors"]:
        helpers["muzzle"] = primary_bone
    for name, parent in helpers.items():
        if name in rig.data.edit_bones:
            raise ValueError("Source already contains conflicting helper "+name)
        bone = rig.data.edit_bones.new(name)
        bone.head = rig.data.edit_bones[parent].head.copy()
        bone.tail = bone.head + Vector((0, .05, 0))
        bone.parent = rig.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    flexible = None
    if bow or plan["profile"] == "crossbow":
        from era_flexible_equipment import FlexibleEquipment
        flexible = FlexibleEquipment(rig, primary, plan["profile"], primary_bone)
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    rig.animation_data_create()
    actions, equipment_actions, measurements, calibration, control_tracks = {}, {}, [], {}, []
    shield_local = None
    left_wrist_local = None
    source_root = pose.world_head(rig, rig.pose.bones["root"]).copy()
    original_rest = {bone.name: rig.matrix_world @ bone.matrix_local for bone in rig.data.bones}
    physical_samples = {clip: [] for clip in plan["clips"]}
    fps = plan["fps"]
    contact, duration = plan["attack_contact_seconds"], plan["clips"]["Attack"]
    profile = plan["profile"]
    supported_two_hand = profile in {"crossbow", "rifle", "laser_rifle", "launcher", "two_hand_hammer"}
    death_arm_target = None
    arm_bones = [bone.name for bone in rig.pose.bones
                 if bone.name.startswith(("upperarm_", "lowerarm_", "hand_"))]
    if supported_two_hand and "grip_l" not in primary["anchors"]:
        raise ValueError("Two-hand source has no measured grip_l")

    def move_legs(phase):
        length = plan["clips"]["Move"]
        speed = plan["reference_move_speed_cm_s"]/100
        pose.translate_bone_world(rig, rig.pose.bones["pelvis"],
                                  (0, 0, factor*(-.065+.006*(1-math.cos(phase*4*math.pi)))))
        amplitude = speed*length/4
        targets = {}
        for side, offset in (("r", 0), ("l", .5)):
            cycle = (phase+offset) % 1
            stance = cycle < .5
            q = (cycle-.5)*2
            travel = amplitude-speed*length*cycle if stance else -amplitude+2*amplitude*(6*q*q-4*q*q*q-q)
            lift = 0. if stance else .075*factor*math.sin(math.pi*q)**2
            position, rotation = rest_feet[side]
            hip = rig.matrix_world @ rig.data.bones["thigh_"+side].head_local
            targets[side] = {"target": Vector((hip.x+travel, position.y, position.z+lift)),
                             "rotation": rotation, "stance": stance, "lift": lift}
        for _ in range(4):
            for side, values in targets.items():
                target = values["target"]
                pose.solve_arm(rig, rig.pose.bones["thigh_"+side], rig.pose.bones["calf_"+side],
                               rig.pose.bones["foot_"+side], target, (.45*factor, target.y, .4*factor))
                pose.set_world_rotation(rig, rig.pose.bones["foot_"+side], values["rotation"])
            measured = pose.measured_feet(foot_groups)
            for side, values in targets.items():
                values["target"].z += values["lift"]-measured[side]["minimum_z_m"]
        measured = pose.measured_feet(foot_groups)
        for side, values in targets.items():
            measured[side].update(stance=values["stance"], desired_sole_z_m=values["lift"],
                world_compensated_sole_x_m=measured[side]["sole_centroid_m"][0]+speed*length*phase)
        return measured

    def seated_legs():
        contract = plan["mounted_contract"]
        pelvis = rig.pose.bones["pelvis"]
        current = pose.world_head(rig, pelvis)
        pose.translate_bone_world(rig, pelvis, Vector((0, 0, contract["pelvis_above_origin_m"]))-current)
        result = {}
        for side, goal in contract["foot_goals_m"].items():
            target = Vector(goal)
            hip = pose.world_head(rig, rig.pose.bones["thigh_"+side])
            knee = pose.world_head(rig, rig.pose.bones["calf_"+side])
            ankle = pose.world_head(rig, rig.pose.bones["foot_"+side])
            leg_length = (knee-hip).length+(ankle-knee).length
            reach = target-hip
            if reach.length > leg_length*.87:
                target = hip+reach.normalized()*leg_length*.87
            sign = -1 if side == "r" else 1
            pose.solve_arm(rig, rig.pose.bones["thigh_"+side], rig.pose.bones["calf_"+side],
                rig.pose.bones["foot_"+side], target, (.30, sign*.48, -.12))
            pose.set_world_rotation(rig, rig.pose.bones["foot_"+side], rest_feet[side][1])
            result[side] = {"requested_goal_m": list(goal), "target_m": list(target), "actual_leg_length_m": leg_length,
                "actual_ankle_m": list(pose.world_head(rig, rig.pose.bones["foot_"+side])),
                "target_error_m": (pose.world_head(rig, rig.pose.bones["foot_"+side])-target).length}
        return result

    def pose_helper(name, world):
        pose_matrix = Matrix.LocRotScale(world.translation, world.to_quaternion(), rig.matrix_world.to_scale())
        rig.pose.bones[name].matrix = inverse @ pose_matrix
        bpy.context.view_layer.update()

    def follow_equipment():
        for module in equipment.values():
            world = rig.matrix_world @ rig.pose.bones[module["bone"]].matrix
            module["root"].matrix_world = Matrix.LocRotScale(world.translation, world.to_quaternion(), Vector((1, 1, 1)))
        bpy.context.view_layer.update()

    def activate(clip):
        rig.animation_data.action = actions[clip]
        for owner, action in equipment_actions[clip]:
            owner.animation_data.action = action

    def crossbow_controls(t, clip, frame):
        if profile != "crossbow":
            return
        fired = clip == "Attack" and t >= contact
        recovery = (t-contact)/(duration-contact) if fired else 0.
        draw = 1. if not fired else smooth((recovery-.18)/.45)
        visible = not fired or recovery >= .72
        for obj in primary["meshes"]:
            if obj.data.shape_keys and "Draw" in obj.data.shape_keys.key_blocks:
                key = obj.data.shape_keys.key_blocks["Draw"]
                key.value = draw
                key.keyframe_insert("value", frame=frame)
            if obj.name.startswith(("loaded_bolt", "bolt_tip")):
                obj.scale = Vector((1, 1, 1)) if visible else Vector((.001, .001, .001))
                obj.keyframe_insert("scale", frame=frame)
        # Named limb pivots are real source controls; the string deformation
        # itself is the source Draw shape, not a rigid rod substitute.
        for obj in primary["objects"]:
            if obj.name.startswith("limb_pivot"):
                sign = -1 if "_N" in obj.name or "_-" in obj.name else 1
                obj.rotation_euler.z = math.radians(3*draw*sign)
                obj.keyframe_insert("rotation_euler", frame=frame)
        control_tracks.append({"clip": clip, "time": t, "string_draw": draw, "bolt_visible": visible,
                               "release_is_visual_only": True})

    def frame_pose(clip, t, frame, capture=True):
        nonlocal shield_local, left_wrist_local
        pose.reset_pose(rig)
        phase = t/plan["clips"][clip]
        values = attack_parameters(profile, t if clip == "Attack" else 0., contact, duration)
        x, y, z, pitch, lean = values
        if clip == "Idle":
            z += .004*math.sin(phase*2*math.pi)
        if clip == "Hit":
            lean = -12*math.sin(math.pi*phase)*(1-phase)
        if mounted and clip == "Move":
            lean = 2.5*math.sin(phase*2*math.pi)
        if mounted and clip == "Death":
            lean = 22*smooth(phase/(1-plan["death_hold_last_fraction"]))
        spine = rig.pose.bones["spine_02"]
        spine_world = rig.matrix_world @ spine.matrix
        around = Matrix.Translation(spine_world.translation) @ Matrix.Rotation(math.radians(lean), 4, "Y") @ Matrix.Translation(-spine_world.translation)
        spine.matrix = inverse @ around @ spine_world
        bpy.context.view_layer.update()
        prop_q = Quaternion(Vector((0, 1, 0)), math.radians(pitch))
        if bow:
            left_error, _ = fit_hand("l", scaled((.48, -.05, 1.16)), prop_q)
            prop_position = palm_point("l") - prop_q @ primary_grip
            if clip == "Attack":
                x, y, z = sample_keys([
                    (0., [.13, -.09, 1.16]), (.08, [.10, -.11, 1.18]),
                    (.20, [.02, -.24, .89]), (.35, [.445, -.05, 1.16]),
                    (.70, [.15, -.05, 1.16]), (duration, [.15, -.05, 1.16])], t)
            right_error, _ = fit_hand("r", scaled((x, y, z)), prop_q)
        else:
            right_error, _ = fit_hand("r", scaled((x, y, z)), prop_q)
            prop_position = palm_point("r") - prop_q @ primary_grip
        prop_world = Matrix.LocRotScale(prop_position, prop_q, Vector((1, 1, 1)))
        pose_helper(primary_bone, prop_world)
        if "muzzle" in helpers:
            pose_helper("muzzle", prop_world @ Matrix.Translation(Vector(primary["anchors"]["muzzle"]["position_m"])))
        if not bow:
            left_error = None
        if bow:
            pass
        elif supported_two_hand:
            target = prop_world @ Vector(primary["anchors"]["grip_l"]["position_m"])
            if clip == "Attack" and profile == "crossbow" and t > contact:
                r = (t-contact)/(duration-contact)
                reload = math.sin(math.pi*min(1, r/.75)) if r < .75 else 0
                target = target.lerp(prop_world @ Vector((-.12, .015, .08)), max(0., reload))
            left_error, _ = fit_hand("l", target, prop_q)
        elif shield:
            target = scaled((.23, .28, 1.04))
            left_error, _ = fit_hand("l", target, Quaternion())
            forearm = rig.matrix_world @ rig.pose.bones["lowerarm_l"].matrix
            forearm = Matrix.LocRotScale(forearm.translation, forearm.to_quaternion(), Vector((1, 1, 1)))
            if shield_local is None:
                anchor_name = "shield_grip" if "shield_grip" in shield["anchors"] else "grip_l"
                grip = Vector(shield["anchors"][anchor_name]["position_m"])
                shield_world = Matrix.Translation(palm_point("l")-grip)
                shield_local = forearm.inverted() @ shield_world
                left_wrist_local = forearm.to_quaternion().inverted() @ (rig.matrix_world @ rig.pose.bones["hand_l"].matrix).to_quaternion()
            pose.set_world_rotation(rig, rig.pose.bones["hand_l"], forearm.to_quaternion() @ left_wrist_local)
            pose_helper("shield_l", forearm @ shield_local)
        else:
            pose.solve_arm(rig, rig.pose.bones["upperarm_l"], rig.pose.bones["lowerarm_l"],
                           rig.pose.bones["hand_l"], scaled((.06, .34, .84)), scaled((-.15, .60, .90)))
        feet = None
        if mounted:
            feet = seated_legs()
        elif clip == "Move":
            feet = move_legs(phase)
        if clip == "Death":
            # Reach the final fall at80%, then hold an identical final pose.
            fall = smooth(phase/(1-plan["death_hold_last_fraction"]))
            pelvis = rig.pose.bones["pelvis"]
            world = rig.matrix_world @ pelvis.matrix
            rotated = Matrix.Translation(world.translation) @ Matrix.Rotation(math.radians(-87*fall), 4, "Y") @ Matrix.Translation(-world.translation)
            if not mounted:
                pelvis.matrix = inverse @ rotated @ world
                bpy.context.view_layer.update()
                pose.translate_bone_world(rig, pelvis, scaled((-.12*fall, 0, -.58*fall)))
            # Stable local arm targets are solved once at the terminal pose.
            # Per-frame moving IK poles caused the former chief wrist flip.
            relaxation = smooth((phase-.12)/.55)
            if death_arm_target is not None and relaxation:
                for name in arm_bones:
                    bone = rig.pose.bones[name]
                    a, aq, asc = bone.matrix_basis.decompose()
                    b, bq, bsc = death_arm_target[name].decompose()
                    bone.matrix_basis = Matrix.LocRotScale(
                        a.lerp(b, relaxation), aq.slerp(bq, relaxation), asc.lerp(bsc, relaxation))
        if plan.get("local_cloth_motion"):
            # Authored cloth bones, not simulated cloth or recovered Tripo data.
            cape_angle, tabard_angle = 0., 0.
            if clip == "Move":
                cape_angle = 8+4*math.sin(phase*4*math.pi)
                tabard_angle = -18-6*math.cos(phase*4*math.pi)
            elif clip == "Attack":
                cape_angle, tabard_angle = -.45*lean, -abs(lean)*.8
            for name, angle in (("local_cape", cape_angle), ("local_tabard", tabard_angle)):
                bone = rig.pose.bones[name]
                world = rig.matrix_world @ bone.matrix
                around = Matrix.Translation(world.translation) @ Matrix.Rotation(math.radians(angle), 4, "Y") @ Matrix.Translation(-world.translation)
                bone.matrix = inverse @ around @ world
        bpy.context.view_layer.update()
        if backpack:
            spine_world = rig.matrix_world @ rig.pose.bones["spine_02"].matrix
            spine_rigid = Matrix.LocRotScale(spine_world.translation, spine_world.to_quaternion(), Vector((1, 1, 1)))
            pose_helper("back_pack", spine_rigid @ backpack_local)
        follow_equipment()
        if flexible:
            fired = clip == "Attack" and t >= contact
            if bow:
                draw = smooth((t-.35)/.35) if fired else 1.
                visible = not fired or t >= .35
            else:
                recovery = (t-contact)/(duration-contact) if fired else 0.
                draw = smooth((recovery-.18)/.45) if fired else 1.
                visible = not fired or recovery >= .72
            flexible.pose(primary["root"].matrix_world, draw, visible)
            if capture:
                control_tracks.append({"clip": clip, "time": t, "string_draw": draw,
                                       "projectile_visible": visible, "actual_skeletal_controls": len(flexible.bones)})
        all_meshes = body + (flexible.meshes if flexible else [o for module in equipment.values() for o in module["meshes"]])
        minimum = min(p.z for o in all_meshes for p in pose.evaluated_world_vertices(o))
        if minimum < 0 and not mounted:
            pose.translate_bone_world(rig, rig.pose.bones["pelvis"], (0, 0, -minimum+.0001))
            follow_equipment()
        # Keep separate source mechanisms genuinely animated in the .blend.
        if capture:
            crossbow_controls(t, clip, frame)
        root_displacement = (pose.world_head(rig, rig.pose.bones["root"])-source_root).length
        matrices = {name: [list(row) for row in rig.matrix_world @ rig.pose.bones[name].matrix] for name in helpers}
        physical = {}
        for bone in rig.pose.bones:
            world = rig.matrix_world @ bone.matrix
            physical[bone.name] = {
                "head_cm": list(world.translation*100),
                "scale": [a/b for a, b in zip(world.to_scale(), original_rest[bone.name].to_scale())],
            }
        if capture:
            physical_samples[clip].append({"time": t, "bones": physical})
        return {"clip": clip, "frame": frame, "time": t, "right_palm_target_error_m": right_error,
                "left_palm_target_error_m": left_error, "root_displacement_m": root_displacement,
                "feet": feet, "helper_matrices_world_m": matrices}

    for clip, length in plan["clips"].items():
        if clip == "Death":
            # This is preparation of the terminal target, not an extra exported
            # animation frame or another mechanism event.
            rig.animation_data.action = None
            frame_pose("Death", length, round(length*fps)+1, capture=False)
            pose.relax_death_arms(rig, pose.hand_frame(rig), 1.)
            death_arm_target = {name: rig.pose.bones[name].matrix_basis.copy() for name in arm_bones}
        action = bpy.data.actions.new(plan["asset_id"]+"_"+clip)
        action.use_fake_user = True
        rig.animation_data.action = action
        actions[clip] = action
        equipment_actions[clip] = []
        # Each prop mechanism has its own action for this same clip.
        for module in equipment.values():
            for obj in module["objects"]:
                obj.animation_data_create()
                obj.animation_data.action = bpy.data.actions.new(plan["asset_id"]+"_"+clip+"_"+obj.name)
                obj.animation_data.action.use_fake_user = True
                equipment_actions[clip].append((obj, obj.animation_data.action))
                if obj.type == "MESH" and obj.data.shape_keys:
                    obj.data.shape_keys.animation_data_create()
                    obj.data.shape_keys.animation_data.action = bpy.data.actions.new(plan["asset_id"]+"_"+clip+"_"+obj.name+"_Shape")
                    obj.data.shape_keys.animation_data.action.use_fake_user = True
                    equipment_actions[clip].append((obj.data.shape_keys, obj.data.shape_keys.animation_data.action))
        for frame in range(1, round(length*fps)+2):
            scene.frame_set(frame)
            measurement = frame_pose(clip, (frame-1)/fps, frame)
            pose.keyed_pose(rig, frame)
            for module in equipment.values():
                root = module["root"]
                root.rotation_mode = "QUATERNION"
                root.keyframe_insert("location", frame=frame)
                root.keyframe_insert("rotation_quaternion", frame=frame)
                root.keyframe_insert("scale", frame=frame)
            measurements.append(measurement)
            if frame in {1, round(contact*fps)+1, round(length*fps)+1}:
                calibration.setdefault(clip, []).append(measurement)
    write(output/"motion_samples.json", measurements)
    write(output/"attachment_calibration.json", calibration)
    write(output/"mechanism_tracks.json", control_tracks)
    # Confirm true endpoint continuity and a held death tail from baked poses.
    def sampled_basis(clip, t):
        activate(clip)
        scene.frame_set(round(t*fps)+1)
        bpy.context.view_layer.update()
        return {p.name: p.matrix.copy() for p in rig.pose.bones}
    idle = sampled_basis("Idle", 0)
    end = sampled_basis("Attack", duration)
    recovery_error = max(max(abs(a-b) for ra, rb in zip(idle[n], end[n]) for a, b in zip(ra, rb)) for n in idle)
    death_start = sampled_basis("Death", plan["clips"]["Death"]*.85)
    death_end = sampled_basis("Death", plan["clips"]["Death"])
    hold_error = max(max(abs(a-b) for ra, rb in zip(death_start[n], death_end[n]) for a, b in zip(ra, rb)) for n in death_start)
    if recovery_error > .001 or hold_error > .001:
        raise ValueError("Endpoint continuity failed: " + str((recovery_error, hold_error)))
    export.FPS, export.CLIPS = fps, plan["clips"]
    if scene.render.fps != fps or scene.render.fps_base != 1.:
        raise ValueError("Scene timing changed after authored frame sampling")
    bundle = export.export_bundle(rig, body+(flexible.meshes if flexible else []), output, "SK_"+plan["asset_id"], actions, textures)
    # The reusable mount exporter samples .4 seconds. Human weapons instead
    # carry every actual authored frame, including their exact authority time.
    bundle["physical_pose_reference"] = physical_samples
    attachments = []
    for module in equipment.values():
        if flexible and module is primary:
            continue
        bone_name = module["bone"]
        attachment_calibration = {"bone": bone_name, "local_vertices_m": [], "poses": {}}
        for original in module["meshes"]:
            evaluated = original.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            attachment_calibration["local_vertices_m"].extend(
                list(module["original_matrices"][original] @ vertex.co) for vertex in mesh.vertices)
            evaluated.to_mesh_clear()
        for label, clip, t in (("idle", "Idle", 0), ("attack_contact", "Attack", contact),
                               ("death_end", "Death", plan["clips"]["Death"])):
            activate(clip)
            scene.frame_set(round(t*fps)+1)
            follow_equipment()
            matrix = module["root"].matrix_world.copy()
            attachment_calibration["poses"][label] = {
                "clip": clip, "time_seconds": t,
                "weapon_rigid_world_matrix": [list(row) for row in matrix],
            }
        calibration_path = output/(module["source"]["asset_id"]+"_calibration.json")
        write(calibration_path, attachment_calibration)
        material_specs = {}
        for obj in module["meshes"]:
            for material in obj.data.materials:
                if not material or material.name in material_specs:
                    continue
                supplied_pbr = module["source"].get("pbr_materials") or {}
                if supplied_pbr:
                    if material.name not in supplied_pbr:
                        raise ValueError("Actual prop PBR material slot changed: "+material.name)
                    material_specs[material.name] = {"pbr": supplied_pbr[material.name], "team_color": False}
                    continue
                bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
                material_specs[material.name] = {
                    "base_color": list(bsdf.inputs["Base Color"].default_value),
                    "metallic": float(bsdf.inputs["Metallic"].default_value),
                    "roughness": float(bsdf.inputs["Roughness"].default_value),
                    "team_color": material.name.startswith("CW_cobalt"),
                }
        module["root"].matrix_world = Matrix.Identity(4)
        copies = []
        for original in module["meshes"]:
            copied = original.copy()
            # Bake the source bevels at metre scale before conversion. Leaving
            # a 0.005m Bevel on an already centimetre-scaled mesh changes shape.
            evaluated = original.evaluated_get(bpy.context.evaluated_depsgraph_get())
            copied.data = bpy.data.meshes.new_from_object(evaluated)
            copied.modifiers.clear()
            copied.animation_data_clear()
            copied.data.transform(Matrix.Scale(100, 4) @ module["original_matrices"][original])
            copied.parent = None
            copied.matrix_world = Matrix.Identity(4)
            scene.collection.objects.link(copied)
            copies.append(copied)
        scene.unit_settings.scale_length = .01
        path = output/("SM_"+module["source"]["asset_id"]+".fbx")
        export.fbx(path, copies)
        for copied in copies:
            bpy.data.objects.remove(copied, do_unlink=True)
        scene.unit_settings.scale_length = 1
        attachments.append({"asset_id": module["source"]["asset_id"], "fbx": export.record(path),
                            "bone": bone_name,
                            "calibration": export.record(calibration_path),
                            "materials": material_specs,
                            "source": module["source"]["source"],
                            "animated_mechanism": bool(module["source"]["deformation_controls"])})
    activate("Idle")
    scene.frame_set(1)
    follow_equipment()
    bpy.ops.wm.save_as_mainfile(filepath=str(output/(plan["asset_id"]+"_Actions.blend")))
    result = {"schema_version": 1, "asset_id": plan["asset_id"], "status": "authored_preview_pending_visual_and_unreal",
              "source": plan.get("source_geometry", plan["source_rig"]), "plan": export.record(output/"input_plan.json"),
              "normalization": {"yaw_degrees": math.degrees(yaw), "scale": scale,
                                "reference_height_cm": plan["reference_height_cm"]},
              "profile": profile, "attack_contact_seconds": contact,
              "mounted_contract": plan.get("mounted_contract"),
              "rig_provenance": plan.get("rig_provenance", {"origin": "actual_tripo_export"}),
              "actual_usd_bind_inspection": export.record(output/"actual_usd_bind_inspection.json") if plan.get("source_usd") else None,
              "actual_source_bind_inspection": export.record(output/"actual_source_bind.json"),
              "backpack_mount_policy": "Measured actual rear torso vertices; pack retained in all clips" if backpack else None,
              "backpack_contact_measurement": backpack_contact,
              "body_material_name": body[0].data.materials[0].name,
              "embedded_equipment_materials": flexible.material_specs() if flexible else {},
              "reference_move_speed_cm_s": plan["reference_move_speed_cm_s"],
              "root_motion": False, "attachments": attachments,
              "muzzle_bone": "muzzle" if "muzzle" in helpers else None,
              "recovery_to_idle_max_matrix_error": recovery_error, "death_hold_max_matrix_error": hold_error,
              "maximum_palm_target_error_m": max(max(r["right_palm_target_error_m"], r["left_palm_target_error_m"] or 0) for r in measurements),
              "maximum_root_displacement_m": max(r["root_displacement_m"] for r in measurements),
              "actual_hand_surface_clearance_checked": False,
              "mechanism_tracks": export.record(output/"mechanism_tracks.json"),
              "mechanism_runtime_ready": bool(flexible) or profile != "crossbow",
              "remaining": ["real_pose_and_grip_images", "actual_ue_bone_calibration", "runtime_game_view"],
              "gameplay_approved": False, "production_approved": False, **bundle}
    write(output/"manifest.json", result)
    if render:
        if scene.world is None:
            scene.world = bpy.data.worlds.new("EraCharacterPreviewWorld")
        pose.inspection.helper.render_setup(samples=8)
        scene.cycles.device = "CPU"
        scene.render.threads_mode, scene.render.threads = "FIXED", 2
        objects = body+(flexible.meshes if flexible else [o for module in equipment.values() for o in module["meshes"]])
        views = [("Idle", 0, (1, -1.4, .3), "Idle"),
                 ("Attack", contact, (1, -1.4, .3), "Attack"),
                 ("Death", plan["clips"]["Death"], (1, -1.4, .3), "Death")]
        inspect_skin = plan.get("render_local_bind_checks") or plan.get("render_source_motion_checks")
        if inspect_skin:
            views += [("Move", .15, (1, -1.4, .3), "Move"),
                      ("Move", .45, (-1, 1.4, .3), "MoveRear"),
                      ("Hit", .18, (1, -1.4, .3), "Hit")]
        local_deformation = []
        for clip, t, view, label in views:
            activate(clip)
            scene.frame_set(round(t*fps)+1)
            follow_equipment()
            if inspect_skin:
                actual = pose.evaluated_world_vertices(body[0])
                rest = [body[0].matrix_world @ v.co for v in body[0].data.vertices]
                ratios = []
                for edge in body[0].data.edges:
                    a, b = edge.vertices
                    length = (rest[a]-rest[b]).length
                    if length >= .005:
                        ratios.append((actual[a]-actual[b]).length/length)
                ratios.sort()
                local_deformation.append({"clip": clip, "time": t, "edges_over_5mm": len(ratios),
                    "edge_stretch_max": max(ratios), "edge_stretch_p99": ratios[int((len(ratios)-1)*.99)]})
            pose.inspection.helper.render_view(output/(label+".png"), objects, view,
                                               size=640, framing=plan["reference_height_cm"]/100*1.55)
        if local_deformation:
            diagnostic = "local_skin_deformation.json" if plan.get("render_local_bind_checks") else "source_skin_deformation.json"
            write(output/diagnostic, {"samples": local_deformation,
                "scope": "Actual evaluated mesh edges; diagnostic, not a substitute for real image review"})
    print(json.dumps({"asset_id": plan["asset_id"], "output": str(output), "status": result["status"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:])
    plan = next(r for r in read(args.plan)["entries"] if r["asset_id"] == args.asset)
    build(plan, args.output.resolve(), args.render)


if __name__ == "__main__":
    main()
