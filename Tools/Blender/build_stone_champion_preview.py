"""Author preview animation and a separate bone club for the new Tripo chief.

Requires the newly generated Champion_Stone UE5 rig. It never substitutes the
StoneAxe body. All products go into a new candidate directory, without approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_stoneaxe_pose_pilot as pose
import prepare_stoneaxe_export_pilot as exporter

ROOT = Path(__file__).resolve().parents[2]
CLIPS = {"Idle": 121, "Move": 37, "Attack": 55, "Hit": 31, "Death": 73}
HEIGHT = 1.98
SCALE = HEIGHT / 1.5


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def scaled(value):
    return Vector(value) * SCALE


def material(name, color, roughness=.8):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    bsdf = result.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    result.diffuse_color = (*color, 1)
    return result


def build_club(armature):
    """Source weapon is a separate mesh assembly with a measured hand transform."""
    grip = pose.close_grip(armature)
    center = grip["center"] - grip["longitudinal"] * .006 + grip["palm"] * (.035 * SCALE)
    up = grip["across"]
    forward = grip["longitudinal"]
    right = up.cross(forward).normalized()
    basis = Matrix((forward, right, up)).transposed().to_quaternion()
    world = Matrix.LocRotScale(center, basis, Vector((1, 1, 1)))
    socket = bpy.data.objects.new("ChampionClubGrip", None)
    bpy.context.scene.collection.objects.link(socket)
    socket.parent = armature
    socket.parent_type = "BONE"
    socket.parent_bone = "hand_r"
    socket.matrix_world = world
    ivory = material("BoneClub_Ivory", (.64, .56, .40))
    end = material("BoneClub_End", (.43, .36, .24))
    leather = material("BoneClub_Leather", (.17, .075, .026))
    meshes = []

    def attach(obj, name, mat):
        obj.name = name
        obj.data.materials.append(mat)
        # Scale assignments made immediately after primitive creation are lazy.
        # Evaluate before capturing the transform, otherwise an ico knob keeps
        # its original one metre radius despite the intended centimetre scale.
        bpy.context.view_layer.update()
        local = obj.matrix_world.copy()
        obj.parent = socket
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = local
        meshes.append(obj)

    bpy.ops.mesh.primitive_cone_add(vertices=10, radius1=.026, radius2=.047, depth=.92, location=(0, 0, .22))
    attach(bpy.context.object, "BoneClub_Shaft", ivory)
    for index, (location, size) in enumerate((((0, 0, .64), (.10, .085, .14)), ((0, 0, -.25), (.065, .06, .09)))):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1, location=location)
        bpy.context.object.scale = size
        attach(bpy.context.object, f"BoneClub_Knob_{index}", end if index else ivory)
    for index in range(7):
        bpy.ops.mesh.primitive_torus_add(major_segments=10, minor_segments=4, location=(0, 0, -.09 + index * .024),
                                       major_radius=.028, minor_radius=.0045)
        attach(bpy.context.object, f"BoneClub_GripWrap_{index}", leather)
    bpy.context.view_layer.update()
    return socket, meshes, world


def import_body(source, pbr_source):
    if "Champion_Stone" not in source.parts:
        raise ValueError("The source must be a genuine Champion_Stone asset, never a renamed StoneAxe")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objects = pose.inspection.import_model(source)
    rigs = [obj for obj in objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("A single real bound UE5 armature and body mesh are required")
    rig = rigs[0]
    # Blender's glTF importer makes a shared Icosphere bone display object.
    # It is not source geometry: require an actual pose-bone custom-shape
    # reference before excluding it, rather than ignoring unbound body pieces.
    custom_shapes = {bone.custom_shape for bone in rig.pose.bones if bone.custom_shape}
    excluded_shapes = [{"name":obj.name,"vertices":len(obj.data.vertices)} for obj in custom_shapes]
    objects = [obj for obj in objects if obj not in custom_shapes]
    bodies = [obj for obj in objects if obj.type == "MESH"]
    for bone in rig.pose.bones:
        if bone.custom_shape:
            bone.custom_shape = None
    for obj in custom_shapes:
        bpy.data.objects.remove(obj,do_unlink=True)
    if not bodies:
        raise ValueError("No body mesh remains after excluding actual rig display widgets")
    required = {"root", "pelvis", "spine_02", "neck_01", "upperarm_r", "lowerarm_r", "hand_r",
                "upperarm_l", "lowerarm_l", "hand_l", "foot_r", "foot_l", "ball_r", "ball_l"}
    if not required.issubset(rig.pose.bones.keys()):
        raise ValueError("Unexpected UE5 bone names: " + str(sorted(required - set(rig.pose.bones.keys()))))
    if any(not obj.vertex_groups or not any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers) for obj in bodies):
        raise ValueError("Every body mesh must actually be skinned")
    rig.animation_data_clear()
    pose.reset_pose(rig)
    if pbr_source:
        donors = pose.inspection.import_model(pbr_source)
        donor_meshes = [obj for obj in donors if obj.type == "MESH"]
        donor_materials = [mat for obj in donor_meshes for mat in obj.data.materials if mat]
        if len(bodies) != 1 or len(donor_materials) != 1:
            raise ValueError("Material transfer requires a single UV-matched body/material")
        source_uvs = [tuple(v.uv) for v in bodies[0].data.uv_layers.active.data]
        donor_uvs = [tuple(v.uv) for v in donor_meshes[0].data.uv_layers.active.data]
        if len(source_uvs) != len(donor_uvs) or any(max(abs(a-b) for a,b in zip(left,right)) > 1e-6 for left,right in zip(source_uvs,donor_uvs)):
            raise ValueError("Rigged and PBR mesh UVs differ; do not guess material correspondence")
        bodies[0].data.materials.clear()
        bodies[0].data.materials.append(donor_materials[0])
        for obj in donors:
            bpy.data.objects.remove(obj, do_unlink=True)
    # Feet provide an anatomical forward axis instead of guessing the GLB axes.
    forward = sum((pose.world_head(rig, rig.pose.bones["ball_" + side]) -
                   pose.world_head(rig, rig.pose.bones["foot_" + side]) for side in ("r", "l")), Vector())
    forward.z = 0
    if forward.length < 1e-5:
        raise ValueError("Cannot derive the character's forward axis from the real feet")
    yaw = -math.atan2(forward.y, forward.x)
    rotation = Matrix.Rotation(yaw, 4, "Z")
    roots = [obj for obj in objects if obj.parent not in objects]
    for obj in roots:
        obj.matrix_world = rotation @ obj.matrix_world
    bpy.context.view_layer.update()
    low, high = pose.inspection.helper.bounds(bodies)
    factor = HEIGHT / (high.z - low.z)
    center = Vector(((low.x + high.x)/2, (low.y + high.y)/2, low.z))
    transform = Matrix.Scale(factor, 4) @ Matrix.Translation(-center)
    for obj in roots:
        obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    return rig, bodies, {"height_cm": HEIGHT*100, "source_to_positive_x_yaw_degrees": math.degrees(yaw),
                        "scale": factor,"excluded_importer_bone_display_shapes":excluded_shapes}


def idle(rig, reference, phase=0):
    pose.reset_pose(rig)
    pose.close_grip(rig)
    pose.solve_arm(rig, rig.pose.bones["upperarm_r"], rig.pose.bones["lowerarm_r"], rig.pose.bones["hand_r"],
                   scaled((.20, -.36, .90 + .005*math.sin(phase))), scaled((-.15, -.55, .9)))
    across, longitudinal, palm, _ = reference
    original = Matrix((across, longitudinal, palm)).transposed()
    desired = Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0))).transposed()
    rotation = (desired @ original.inverted()).to_quaternion() @ (rig.matrix_world @ rig.data.bones["hand_r"].matrix_local).to_quaternion()
    pose.set_world_rotation(rig, rig.pose.bones["hand_r"], Quaternion(Vector((0, 1, 0)), math.radians(18)) @ rotation)
    pose.solve_arm(rig, rig.pose.bones["upperarm_l"], rig.pose.bones["lowerarm_l"], rig.pose.bones["hand_l"],
                   scaled((.11, .34, .81)), scaled((-.12, .55, .92)))


def attack(time):
    # Contact key is at precisely the live champion's 0.3 s windup.
    keys = [(0, (.20,-.36,.90),18,0),(.10,(.02,-.36,1.20),-30,-3),
            (.20,(-.03,-.35,1.30),-45,-5),(.30,(.39,-.34,1.00),90,7),
            (.42,(.34,-.35,.83),110,8),(.65,(.23,-.36,.86),45,2),(.90,(.20,-.36,.90),18,0)]
    for before, after in zip(keys, keys[1:]):
        if before[0] <= time <= after[0]:
            blend = (time-before[0])/(after[0]-before[0])
            blend = blend*blend*(3-2*blend)
            return scaled(before[1]).lerp(scaled(after[1]), blend), before[2]*(1-blend)+after[2]*blend, before[3]*(1-blend)+after[3]*blend
    return scaled(keys[-1][1]),18,0


def textures(body, output):
    result = {}
    def shader_targets(start):
        seen, targets, pending = set(), set(), [start]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            for socket in current.outputs:
                for link in socket.links:
                    if link.to_node.type == "BSDF_PRINCIPLED":
                        targets.add(link.to_socket.name)
                    else:
                        pending.append(link.to_node)
        return targets
    for obj in body:
        for mat in obj.data.materials:
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                image = node.image
                name = (node.name + " " + image.name).lower()
                targets = shader_targets(node)
                channel = ("normal" if "Normal" in targets else "orm" if targets & {"Metallic", "Roughness"} else
                           "base_color" if "Base Color" in targets else
                           "normal" if "normal" in name else "orm" if any(word in name for word in ("metal", "rough", "orm")) else "base_color")
                if channel in result:
                    raise ValueError("Multiple body maps for " + channel)
                path = output / ("T_ChampionStone_" + channel + ".png")
                image.filepath_raw, image.file_format = str(path), "PNG"
                image.save()
                result[channel] = record(path)
    if set(result) != {"base_color", "normal", "orm"}:
        raise ValueError("Base color, normal and metallic-roughness maps are required")
    return result


def export_delivery(output, rig, body, weapon, socket, report):
    for name in ("body", "animations", "textures", "weapon"):
        (output/name).mkdir(exist_ok=True)
    maps = textures(body, output/"textures")
    # Capture weapon transforms separately, so UE derives an actual hand socket.
    calibration = {"local_vertices_m": [], "poses": {}, "bone": "hand_r"}
    rig.animation_data.action = None
    pose.reset_pose(rig)
    basis = socket.matrix_world.copy()
    for obj in weapon:
        calibration["local_vertices_m"].extend(list(basis.inverted() @ point) for point in pose.evaluated_world_vertices(obj))
    for label, clip, frame in (("reference",None,1),("idle","Idle",1),("attack_contact","Attack",19),("death_end","Death",73)):
        rig.animation_data.action = bpy.data.actions["CW_ChampionStone_"+clip] if clip else None
        if clip:
            bpy.context.scene.frame_set(frame)
        else:
            pose.reset_pose(rig)
        bpy.context.view_layer.update()
        matrix = socket.matrix_world.copy()
        calibration["poses"][label] = {"clip":clip,"time_seconds":(frame-1)/60,
                                      "weapon_rigid_world_matrix":[list(row) for row in matrix]}
    rig.animation_data.action = None
    pose.reset_pose(rig)
    write(output/"weapon/calibration.json", calibration)
    # Weapon FBX has a physical grip-local origin. It remains separate from body.
    copies = []
    inverse = socket.matrix_world.inverted()
    for original in weapon:
        copied = original.copy()
        copied.data = original.data.copy()
        copied.data.transform(Matrix.Scale(100,4) @ inverse @ original.matrix_world)
        copied.parent = None
        copied.matrix_world = Matrix.Identity(4)
        bpy.context.scene.collection.objects.link(copied)
        copies.append(copied)
    bpy.context.scene.unit_settings.scale_length = .01
    weapon_path = output/"weapon/SM_ChampionStone_BoneClub.fbx"
    exporter.fbx(weapon_path, copies)
    bpy.context.scene.unit_settings.scale_length = 1
    for copied in copies:
        bpy.data.objects.remove(copied, do_unlink=True)
    exporter.CLIPS = CLIPS
    for clip in CLIPS:
        bpy.data.actions["CW_ChampionStone_"+clip].name = "CW_StoneAxe_"+clip
    expected, targets, evidence = exporter.capture_physical_motion(rig,body)
    write(output/"physical_motion_reference.json",evidence)
    normalized, meshes, actions, normalization = exporter.normalized_export_rig(rig,body,targets,expected)
    write(output/"centimetre_normalization_report.json",normalization)
    if not normalization["passed"]:
        raise ValueError("Centimetre normalization failed")
    body_path = output/"body/SK_ChampionStone_Preview.fbx"
    exporter.fbx(body_path,[normalized]+meshes)
    clips, paths = [], {}
    for clip,count in CLIPS.items():
        normalized.animation_data.action = actions[clip]
        bpy.context.scene.frame_start,bpy.context.scene.frame_end = 1,count
        path = output/f"animations/AN_ChampionStone_{clip}.fbx"
        exporter.fbx(path,[normalized]+meshes,animated=True)
        paths[clip] = path
        clips.append(record(path)|{"clip":clip,"first_frame":1,"last_frame":count,"duration_seconds":(count-1)/60})
    bones = sorted(b.name for b in normalized.data.bones)
    roundtrip = exporter.verify_exports(body_path,paths,expected,bones)
    write(output/"fbx_roundtrip_report.json",roundtrip)
    manifest = {"schema_version":1,"asset_id":"Champion_Stone","body":record(body_path),"clips":clips,"textures":maps,
                "bone_names":bones,"root_bone":"root","fps":60,"root_motion":False,"height_cm":198,
                "attack":{"windup":.3,"duration":.9,"release_frame":19},
                "physical_motion_reference":record(output/"physical_motion_reference.json"),
                "centimetre_normalization":record(output/"centimetre_normalization_report.json"),
                "centimetre_normalization_passed":normalization["passed"],"blender_fbx_roundtrip_passed":roundtrip["passed"],
                "weapon":{"fbx":record(weapon_path),"calibration":record(output/"weapon/calibration.json")},
                "source":report["source"],"status":"exported_preview_pending_ue_and_visual_review",
                "runtime_approved":False,"production_approved":False,
                "reference_bones":{name:{"head_m":data["head_m"]} for name,data in evidence["reference"].items()}}
    write(output/"delivery_manifest.json",manifest)
    if not roundtrip["passed"]:
        raise ValueError("FBX roundtrip failed")


def create(args):
    args.output.mkdir(parents=True,exist_ok=False)
    rows = json.loads((ROOT/"Content/Data/Champions.json").read_text(encoding="utf-8-sig"))
    champion = next(row for row in rows if row["VisualKey"] == "Champion_Stone")
    if champion["AttackWindup"] != .3 or champion["AttackInterval"] != .9 or champion["MoveSpeed"] != 200:
        raise ValueError("Authoritative champion timing changed")
    rig, body, normalization = import_body(args.source,args.pbr_source)
    rig.name = "ChampionStone_SourceRig"
    reference = pose.hand_frame(rig)
    rest_feet = {side:(pose.world_head(rig,rig.pose.bones["foot_"+side]),
                       (rig.matrix_world @ rig.pose.bones["foot_"+side].matrix).to_quaternion()) for side in ("l","r")}
    feet = pose.foot_surface_groups(rig,body)
    socket,weapon,_ = build_club(rig)
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("ChampionStonePreviewWorld")
    scene.render.fps,scene.render.fps_base = 60,1
    scene.unit_settings.system,scene.unit_settings.scale_length = "METRIC",1
    rig.animation_data_create()
    pose.reset_pose(rig)
    root_reference = pose.world_head(rig, rig.pose.bones["root"]).copy()
    report = {"asset_id":"Champion_Stone","source":record(args.source),"normalization":normalization,"height_cm":198,
              "bone_count":len(rig.data.bones),"body_not_substituted":True,"weapon_independent":True,"clips":{},"images":[],
              "production_approved":False,"game_ready":False}
    idle(rig,reference)
    bpy.context.view_layer.update()
    inverse = socket.matrix_world.inverted()
    local_weapon = [inverse @ point for obj in weapon for point in pose.evaluated_world_vertices(obj)]
    local_dimensions = [max(p[axis] for p in local_weapon)-min(p[axis] for p in local_weapon) for axis in range(3)]
    def world_bounds(objects):
        points = [p for obj in objects for p in pose.evaluated_world_vertices(obj)]
        low = [min(p[axis] for p in points) for axis in range(3)]
        high = [max(p[axis] for p in points) for axis in range(3)]
        return {"minimum_cm":[v*100 for v in low],"maximum_cm":[v*100 for v in high],
                "dimensions_cm":[(b-a)*100 for a,b in zip(low,high)]}
    report["dimensions"] = {"body_idle_world":world_bounds(body),"weapon_idle_world":world_bounds(weapon),
                            "weapon_grip_local_cm":[v*100 for v in local_dimensions]}
    write(args.output/"dimension_probe.json",report["dimensions"])
    if not (.95 <= local_dimensions[2] <= 1.2 and max(local_dimensions[:2]) < .25):
        raise ValueError("Independent bone club dimensions are invalid: "+str(local_dimensions))
    if not (1.9 <= report["dimensions"]["body_idle_world"]["dimensions_cm"][2]/100 <= 2.05):
        raise ValueError("Actual body idle height is outside its 198 cm contract")
    if args.probe_only:
        pose.inspection.helper.render_setup(samples=8)
        scene.cycles.device = "CPU"
        scene.render.threads_mode,scene.render.threads = "FIXED",2
        path = args.output/"Idle_probe.png"
        pose.inspection.helper.render_view(path,body+weapon,(1,-1.5,.35),size=640,framing=3.0,target=(.1,-.1,.95))
        report["images"].append(str(path))
        write(args.output/"preview_report.json",report)
        return
    for clip,count in CLIPS.items():
        action = bpy.data.actions.new("CW_ChampionStone_"+clip)
        action.use_fake_user = True
        rig.animation_data.action = action
        floor = 1e9
        root_displacement = 0.0
        foot_samples = []
        for frame in range(1,count+1):
            scene.frame_set(frame)
            fraction = (frame-1)/(count-1)
            idle(rig,reference,fraction*2*math.pi if clip=="Idle" else 0)
            wrist_rotation = (rig.matrix_world @ rig.pose.bones["hand_r"].matrix).to_quaternion()
            if clip == "Attack":
                target,tilt,lean = attack((frame-1)/60)
                pose.rotate_rest_axis(rig.pose.bones["spine_02"],Vector((0,1,0)),math.radians(lean))
                bpy.context.view_layer.update()
                pose.solve_arm(rig,rig.pose.bones["upperarm_r"],rig.pose.bones["lowerarm_r"],rig.pose.bones["hand_r"],target,scaled((-.18,-.60,1)))
                pose.set_world_rotation(rig,rig.pose.bones["hand_r"],Quaternion(Vector((0,1,0)),math.radians(tilt-18)) @ wrist_rotation)
            elif clip == "Move":
                measured = pose.pose_move_legs(rig,rest_feet,feet,fraction,(count-1)/60,2.0)
                foot_samples.append({"frame":frame,"time_seconds":(frame-1)/60,"feet":measured})
            elif clip == "Hit":
                pose.rotate_rest_axis(rig.pose.bones["spine_02"],Vector((0,1,0)),math.radians(-17*math.sin(math.pi*fraction)*(1-fraction)))
            elif clip == "Death":
                fall = fraction*fraction*(3-2*fraction)
                pose.rotate_rest_axis(rig.pose.bones["pelvis"],Vector((0,1,0)),math.radians(-86*fall))
                bpy.context.view_layer.update()
                pose.translate_bone_world(rig,rig.pose.bones["pelvis"],scaled((-.10*fall,0,-.58*fall)))
                relaxation = max(0.0,min(1.0,(fraction-.35)/.65))
                relaxation = relaxation*relaxation*(3-2*relaxation)
                if relaxation:
                    pelvis = pose.world_head(rig,rig.pose.bones["pelvis"])
                    for side,lateral in (("r",-.43),("l",.39)):
                        hand = rig.pose.bones["hand_"+side]
                        hand_rotation = (rig.matrix_world @ hand.matrix).to_quaternion()
                        target = pelvis+scaled((0,lateral,-.06))
                        target.z = max(target.z,.18 if side=="r" else .10)
                        target = pose.world_head(rig,hand).lerp(target,relaxation)
                        pole = pelvis+scaled((-.25,lateral*1.5,.04))
                        pose.solve_arm(rig,rig.pose.bones["upperarm_"+side],rig.pose.bones["lowerarm_"+side],hand,target,pole)
                        pose.set_world_rotation(rig,hand,hand_rotation)
            bpy.context.view_layer.update()
            points = [point for obj in body for point in pose.evaluated_world_vertices(obj)]
            minimum = min(point.z for point in points)
            if minimum < 0:
                pose.translate_bone_world(rig,rig.pose.bones["pelvis"],(0,0,-minimum+.0001))
                points = [point for obj in body for point in pose.evaluated_world_vertices(obj)]
                minimum = min(point.z for point in points)
            floor = min(floor,minimum)
            root_displacement = max(root_displacement,(pose.world_head(rig,rig.pose.bones["root"])-root_reference).length)
            pose.keyed_pose(rig,frame)
        report["clips"][clip] = {"frames":count,"duration_seconds":(count-1)/60,
                                "minimum_body_z_m_after_correction":floor,"maximum_root_displacement_m":root_displacement}
        if foot_samples:
            slips = []
            for before,after in zip(foot_samples,foot_samples[1:]):
                for side in ("r","l"):
                    left,right = before["feet"][side],after["feet"][side]
                    if left["stance"] and right["stance"]:
                        slips.append(abs(left["world_compensated_sole_x_m"]-right["world_compensated_sole_x_m"]))
            report["clips"][clip].update(
                reference_move_speed_cm_s=200, all_frame_feet=foot_samples,
                maximum_stance_ground_error_m=max(abs(item["minimum_z_m"]) for frame in foot_samples for item in frame["feet"].values() if item["stance"]),
                maximum_stance_world_compensated_step_m=max(slips,default=0))
    rig.animation_data.action = None
    pose.reset_pose(rig)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output/"ChampionStone_Gameplay.blend"))
    write(args.output/"preview_report.json",report)
    if args.render:
        if scene.world is None:
            scene.world = bpy.data.worlds.new("ChampionStonePreviewWorld")
        pose.inspection.helper.render_setup(samples=8)
        scene.cycles.device = "CPU"
        scene.render.threads_mode,scene.render.threads = "FIXED",2
        for clip,frame in (("Idle",1),("Move",8),("Move",29),("Attack",12),("Attack",19),("Attack",27),("Death",65)):
            rig.animation_data.action = bpy.data.actions["CW_ChampionStone_"+clip]
            scene.frame_set(frame)
            path = args.output/f"{clip}_{frame:03}.png"
            pose.inspection.helper.render_view(path,body+weapon,(1,-1.5,.35),size=640,framing=3.0,target=(.1,-.1,.95))
            report["images"].append(str(path))
    write(args.output/"preview_report.json",report)
    if args.export:
        export_delivery(args.output,rig,body,weapon,socket,report)
    print("CHAMPION_STONE_PREVIEW "+str(args.output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--pbr-source",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--render",action="store_true")
    parser.add_argument("--export",action="store_true")
    parser.add_argument("--probe-only",action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    create(args)
