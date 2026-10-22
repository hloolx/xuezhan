"""Build a bounded gameplay preview from the accepted slinger body and sling.

No paid generation, no changes to the accepted sources.  The torso, sole,
mesh, UV and PBR corrections are retained.  The new sling bones only deform
the separate weapon meshes.  Preview approval is deliberately separate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_stone_slinger_sling_pilot as base
import review_stone_slinger_joint_pinch as prior
import review_stone_slinger_loop_anchor as loop_tools
import prepare_stoneaxe_export_pilot as exporter

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "RawAssets/Art/Tripo_v01/tripo_processed/stone_slinger_v01"
CLIPS = {"Idle": 121, "Move": 49, "Attack": 85, "Hit": 31, "Death": 73}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def smooth(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def keyed(armature, frame):
    exporter.pose.keyed_pose(armature, frame)


def translate(armature, name, delta):
    bone = armature.pose.bones[name]
    matrix = base.bone_world(armature, name)
    matrix.translation += Vector(delta)
    bone.matrix = armature.matrix_world.inverted() @ matrix
    bpy.context.view_layer.update()


def solve_chain(armature, upper, lower, end, target, pole):
    shoulder = base.bone_world(armature, upper).translation
    a = (base.bone_world(armature, lower).translation - shoulder).length
    b = (base.bone_world(armature, end).translation - base.bone_world(armature, lower).translation).length
    delta = Vector(target) - shoulder
    distance = min(delta.length, a + b - .0001)
    axis = delta.normalized()
    side = Vector(pole) - shoulder
    side = (side - axis * side.dot(axis)).normalized()
    along = (a*a - b*b + distance*distance) / (2 * distance)
    middle = shoulder + axis * along + side * math.sqrt(max(0, a*a - along*along))
    base.aim_joint(armature, upper, lower, middle)
    base.aim_joint(armature, lower, end, shoulder + axis * distance)


def weapon_mesh(armature, name, points, triangles, material, source_world):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([source_world @ Vector(point) for point in points], [], triangles)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material:
        mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        poly.use_smooth = True
        for index in poly.loop_indices:
            p = points[mesh.loops[index].vertex_index]
            uv.data[index].uv = (float(p[0]) * 8, -float(p[2]) * 4)
    obj.modifiers.new("SlingSkin", "ARMATURE").object = armature
    return obj


def build_weapon(armature, prep, plan):
    source_world = Matrix(plan["basis_columns"]).to_4x4()
    source_world.translation = Vector(plan["root_rest_m"])
    originals, _, _ = base.append_existing_weapon(prep)
    cord_mat = originals["cord_N1"].data.materials[0]
    parts = {}
    for name, geometry in plan["meshes"].items():
        parts[name] = weapon_mesh(armature, name, geometry["positions_local_m"], geometry["triangles"], cord_mat, source_world)
    for name in ("leather_pouch", "loaded_stone"):
        obj = originals[name]
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        obj.data.transform(source_world @ world)
        obj.modifiers.new("SlingSkin", "ARMATURE").object = armature
        parts[name] = obj
    for name, obj in originals.items():
        if name not in parts:
            bpy.data.objects.remove(obj, do_unlink=True)
    # Independent cord stations retain the exact accepted closed geometry.
    # The loop and hand-end stations remain attached to hand_r.
    stations = {}
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for kind in ("retained", "released"):
        for index in range(8):
            z = -.52 * index / 7
            name = f"sling_{kind}_{index:02}"
            bone = armature.data.edit_bones.new(name)
            bone.head = source_world @ Vector((0, 0, z))
            bone.tail = bone.head + Vector((0, .025, 0))
            bone.parent = armature.data.edit_bones["hand_r"]
            stations[name] = {"kind": kind, "z": z, "index": index}
    for name, local in (("sling_pouch", (0.025, 0, -.52)), ("sling_stone", (0.025, 0, -.52)),
                        ("sling_release", (0.025, 0, -.48))):
        bone = armature.data.edit_bones.new(name)
        bone.head = source_world @ Vector(local)
        bone.tail = bone.head + Vector((.04, 0, 0))
        bone.parent = armature.data.edit_bones["hand_r"]
        stations[name] = {"kind": name, "z": float(local[2]), "index": 7}
    bpy.ops.object.mode_set(mode="OBJECT")
    inv = source_world.inverted()
    for name, obj in parts.items():
        if name in ("leather_pouch", "loaded_stone"):
            group = obj.vertex_groups.new(name="sling_pouch" if name == "leather_pouch" else "sling_stone")
            group.add(list(range(len(obj.data.vertices))), 1., "REPLACE")
            continue
        kind = "retained" if name == "retained_loop_cord" else "released"
        groups = [obj.vertex_groups.new(name=f"sling_{kind}_{index:02}") for index in range(8)]
        for vertex in obj.data.vertices:
            z = (inv @ vertex.co).z
            station = max(0., min(7., -z / .52 * 7))
            first = int(station)
            second = min(7, first + 1)
            alpha = station - first
            groups[first].add([vertex.index], 1 - alpha, "REPLACE")
            if second != first and alpha:
                groups[second].add([vertex.index], alpha, "REPLACE")
    return parts, stations, source_world


def interpolation(keys, time):
    for index, (t, value) in enumerate(keys):
        if time <= t:
            if index == 0:
                return value
            before_t, before_v = keys[index-1]
            alpha = smooth((time - before_t)/(t - before_t))
            return tuple(a + (b-a)*alpha for a, b in zip(before_v, value))
    return keys[-1][1]


def body_pose(armature, plan, rest, clip, time):
    release = smooth((time - .42) / .03) * (1-smooth((time-.76)/.20)) if clip == "Attack" else 0.
    commands = [[name, axis, degree*(1-release if name.startswith(("index_", "thumb_")) else 1)]
                for name, axis, degree in plan["commands"]]
    base.transfer.set_pose([armature], commands)
    # Keep wrist channels neutral. The earlier diagnostic forced a severe
    # world-space wrist twist that caused the visible cuff fold.
    pelvis_drop = -.018
    bob = .004*math.sin(time*math.tau/2) if clip == "Idle" else 0.
    if clip == "Move":
        bob = .006*(1-math.cos(time*math.tau/.4))
    translate(armature, "pelvis", (0, 0, pelvis_drop+bob))
    for side in ("l", "r"):
        target = rest["foot_"+side].translation.copy()
        if clip == "Move":
            phase = ((time/.8) + (0.5 if side == "r" else 0)) % 1
            # Stance is exactly flat; swing clears the ground by 45 mm.
            if phase < .6:
                x = .11 - .22*phase/.6
                lift = 0
            else:
                q = (phase-.6)/.4
                x = -.11 + .22*smooth(q)
                lift = .045*math.sin(math.pi*q)
            target += Vector((x, 0, lift+.001))
        solve_chain(armature, "thigh_"+side, "calf_"+side, "foot_"+side, target, (.45, target.y, .40))
        prior.set_rotation_channels(armature, "foot_"+side, rest["foot_"+side].to_quaternion())
    r = (.17, -.43, .98)
    l = (.12, .34, .84)
    swing = -.12
    if clip == "Move":
        sway = .025*math.sin(time*math.tau/.8)
        r = (.17+sway, -.43, .98)
        l = (.12-sway, .34, .84)
        swing += .09*math.sin(time*math.tau/.8)
    elif clip == "Attack":
        r = interpolation([(0,r),(.16,(-.09,-.54,1.12)),(.31,(-.06,-.56,1.31)),
                           (.45,(.34,-.46,1.20)),(.59,(.34,-.42,.98)),(.86,(.10,-.39,.88)),(1.20,r),(1.4,r)], time)
        l = interpolation([(0,l),(.25,(.18,.32,1.00)),(.45,(.29,.28,.93)),(.80,l),(1.4,l)], time)
        swing = interpolation([(0,(-.12,)),(.14,(-1.0,)),(.28,(-3.0,)),(.38,(-4.6,)),
                               (.45,(-5.5,)),(.64,(-6.4,)),(.90,(-6.7,)),(1.4,(-math.tau-.12,))], time)[0]
    elif clip == "Hit":
        amount = math.sin(math.pi*min(1,time/.5))
        translate(armature, "pelvis", (-.035*amount, 0, 0))
        r = (.17-.04*amount,-.43,.98)
    elif clip == "Death":
        amount = smooth(time/.85)
        pelvis = armature.pose.bones["pelvis"]
        rotation = Quaternion((0,1,0), -1.48*amount) @ base.bone_world(armature,"pelvis").to_quaternion()
        prior.set_rotation_channels(armature, "pelvis", rotation)
        translate(armature, "pelvis", (-.36*amount,0,-.52*amount))
        r = (.17-.55*amount,-.43,.98-.70*amount)
        l = (.12-.52*amount,.34,.84-.58*amount)
    base.solve_arm(armature, "r", r, (-.15,-.60,1.03))
    base.solve_arm(armature, "l", l, (-.15,.60,.95))
    return release, swing


def animate_weapon(armature, stations, source_world, rest, release, swing):
    hand_delta = base.bone_world(armature,"hand_r") @ rest["hand_r"].inverted()
    for name, station in stations.items():
        z = station["z"]
        fraction = smooth(max(0, -z-.035)/.20)
        angle = swing*fraction
        rotation = Matrix.Rotation(angle, 4, "Y")
        deform = source_world @ rotation @ source_world.inverted()
        desired = hand_delta @ deform @ rest[name]
        if station["kind"] == "released":
            amount = (1 - max(0,min(1,-z/.52)))**2 * release
            desired.translation += (hand_delta @ source_world).to_3x3() @ Vector((.13*amount,.05*amount,-.025*amount))
        bone = armature.pose.bones[name]
        bone.matrix = armature.matrix_world.inverted() @ desired
        if name == "sling_stone":
            bone.scale = (max(.001, 1-release),)*3
    bpy.context.view_layer.update()


def texture_export(body, output):
    result = {}
    material = body.data.materials[0]
    nodes = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    for node in nodes:
        image = node.image
        n = (node.name+" "+image.name).lower()
        channel = "normal" if "normal" in n else "orm" if any(s in n for s in ("rough", "metal", "orm")) else "base_color"
        path = output / ("T_StoneSlinger_"+channel+".png")
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        result[channel] = exporter.file_record(path)
    return result


def create(output, do_export):
    output.mkdir(parents=True, exist_ok=False)
    frozen = read(WORK/"sling_pilot_v01/next_local_integration.json")
    for key in ("body_source","immutable_loop_geometry_and_grip_commands","original_weapon_archive"):
        record = frozen[key]
        if base.rig.record(Path(record["path"])) != record:
            raise ValueError("Frozen source changed: "+key)
    prep = read(WORK/"sling_pilot_v01/preparation_05/grip_preparation.json")
    plan = read(frozen["immutable_loop_geometry_and_grip_commands"]["path"])
    bpy.ops.wm.open_mainfile(filepath=frozen["body_source"]["path"])
    body, = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    armature, = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    armature.animation_data_clear()
    base.transfer.set_pose([armature], [])
    original = base.rig.mesh_snapshot(body)
    original_weights = base.foot.weights_of(body)
    original_materials = base.rig.materials_report([body])
    original_bones = base.foot.rest_bones(armature)
    base.set_bone_world_rotation = prior.set_rotation_channels
    parts, stations, source_world = build_weapon(armature,prep,plan)
    base.transfer.set_pose([armature], [])
    rest = {b.name: armature.matrix_world @ b.matrix_local.copy() for b in armature.data.bones}
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = 60,1
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC",1
    armature.animation_data_create()
    report = {"asset_id":"Unit_StoneSlinger","status":"gameplay_preview_candidate_pending_visual_review",
              "source":frozen["body_source"],"loop_source":frozen["immutable_loop_geometry_and_grip_commands"],
              "fps":60,"root_motion":False,"body_weights_modified":False,
              "wrist_strategy":"Neutral wrist channels; anatomically bent elbows replace prior fixed world wrist twist",
              "attack":{"windup":.45,"duration":1.4,"release_frame":28},"clips":{},"images":[],
              "production_approved":False,"game_ready":False}
    objects = [body]+list(parts.values())
    for clip,count in CLIPS.items():
        action=bpy.data.actions.new("CW_StoneSlinger_"+clip)
        armature.animation_data.action=action
        low=1e9
        maximum_root=0
        release_evidence={}
        for frame in range(1,count+1):
            scene.frame_set(frame)
            release,swing=body_pose(armature,plan,rest,clip,(frame-1)/60)
            animate_weapon(armature,stations,source_world,rest,release,swing)
            points,_=base.evaluated_snapshot(body)
            # A tiny positive-ground correction is pose-local to pelvis.
            # This is skin-aware, not a moving root or displaced actor.
            correction=max(0., .0002-float(points[:,2].min()))
            if correction:
                translate(armature,"pelvis",(0,0,correction))
                animate_weapon(armature,stations,source_world,rest,release,swing)
                points,_=base.evaluated_snapshot(body)
            low=min(low,float(points[:,2].min()))
            maximum_root=max(maximum_root,(base.bone_world(armature,"root").translation-rest["root"].translation).length)
            keyed(armature,frame)
            if clip=="Attack" and frame in (26,27,28,29,40,58,85):
                release_evidence[str(frame)]={"time":(frame-1)/60,"release_fraction":release,
                    "stone_local_scale":list(armature.pose.bones["sling_stone"].scale),
                    "release_position_m":list(base.bone_world(armature,"sling_release").translation)}
        report["clips"][clip]={"frames":count,"duration":(count-1)/60,"body_floor_min_m":low,"root_displacement_m":maximum_root}
        if release_evidence:
            report["clips"][clip]["release_evidence"]=release_evidence
    armature.animation_data.action=None
    base.transfer.set_pose([armature],[])
    report["source_preservation"]=base.transfer.check_rest_normals_uv(original,base.rig.mesh_snapshot(body))
    report["source_preservation"]["weights_exact"]=original_weights==base.foot.weights_of(body)
    report["source_preservation"]["PBR_exact"]=original_materials==base.rig.materials_report([body])
    report["original_bone_count"]=len(original_bones)
    report["bone_count"]=len(armature.data.bones)
    report["root_bone"]="root"
    report["muzzle_bone"]="sling_release"
    if not all(report["source_preservation"].values()):
        raise ValueError("Accepted body preservation failed")
    for obj in list(scene.objects):
        if obj.type in {"CAMERA","LIGHT"}:
            bpy.data.objects.remove(obj,do_unlink=True)
    renderer=base.rig.module("slinger_gameplay_renderer","prepare_tripo_character.py")
    renderer.render_setup(samples=8)
    scene.render.threads_mode,scene.render.threads="FIXED",2
    captures=[("Idle",1),("Move",7),("Move",31),("Attack",16),("Attack",28),("Attack",40),("Death",60)]
    for clip,frame in captures:
        armature.animation_data.action=bpy.data.actions["CW_StoneSlinger_"+clip]
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        path=output/f"{clip}_{frame:03}.png"
        renderer.render_view(path,objects,(1,-1.5,.35),size=640,framing=2.30,target=(.05,-.10,.72))
        report["images"].append(str(path))
    armature.animation_data.action=bpy.data.actions["CW_StoneSlinger_Idle"]
    scene.frame_set(1)
    hand=base.bone_world(armature,"hand_r").translation
    renderer.render_view(output/"grip_close.png",objects,(1,-1,.3),size=640,framing=.48,target=tuple(hand))
    report["images"].append(str(output/"grip_close.png"))
    armature.animation_data.action=None
    base.transfer.set_pose([armature],[])
    blend=output/"Unit_StoneSlinger_Gameplay.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"]=exporter.file_record(blend)
    write(output/"preview_report.json",report)
    if do_export:
        export(output, armature, objects, body, report)
    print("STONE_SLINGER_PREVIEW "+json.dumps({"output":str(output),"clips":report["clips"]}))


def export(output, armature, objects, body, report):
    for name in ("body","animations","textures"):
        (output/name).mkdir(exist_ok=True)
    # Reuse the already proven centimetre normalization and FBX convention.
    exporter.CLIPS=CLIPS
    for clip in CLIPS:
        bpy.data.actions["CW_StoneSlinger_"+clip].name="CW_StoneAxe_"+clip
    textures=texture_export(body,output/"textures")
    expected,targets,evidence=exporter.capture_physical_motion(armature,objects)
    write(output/"physical_motion_reference.json",evidence)
    rig, meshes, actions, normalization=exporter.normalized_export_rig(armature,objects,targets,expected)
    write(output/"centimetre_normalization_report.json",normalization)
    if not normalization["passed"]:
        raise ValueError("Physical centimetre normalization failed")
    path=output/"body/SK_StoneSlinger_Preview.fbx"
    exporter.fbx(path,[rig]+meshes)
    paths={}
    records=[]
    for clip,count in CLIPS.items():
        rig.animation_data.action=actions[clip]
        bpy.context.scene.frame_start,bpy.context.scene.frame_end=1,count
        clip_path=output/("animations/AN_StoneSlinger_"+clip+".fbx")
        exporter.fbx(clip_path,[rig]+meshes,animated=True)
        paths[clip]=clip_path
        records.append(exporter.file_record(clip_path)|{"clip":clip,"first_frame":1,"last_frame":count,"duration_seconds":(count-1)/60})
    bones=sorted(b.name for b in rig.data.bones)
    roundtrip=exporter.verify_exports(path,paths,expected,bones)
    write(output/"fbx_roundtrip_report.json",roundtrip)
    manifest={"schema_version":1,"asset_id":"Unit_StoneSlinger","body":exporter.file_record(path),"clips":records,
              "textures":textures,"bone_names":bones,"root_bone":"root","muzzle_bone":"sling_release",
              "fps":60,"root_motion":False,"height_cm":142.5,"attack":report["attack"],
              "physical_motion_reference":exporter.file_record(output/"physical_motion_reference.json"),
              "centimetre_normalization":exporter.file_record(output/"centimetre_normalization_report.json"),
              "centimetre_normalization_passed":normalization["passed"],"blender_fbx_roundtrip_passed":roundtrip["passed"],
              "source":report["blend"],"status":"exported_preview_pending_ue_and_visual_review",
              "runtime_approved":False,"production_approved":False,"weapon_integrated_as_separate_skinned_mesh_parts":True,
              "reference_bones":{name:{"head_m":data["head_m"]} for name,data in evidence["reference"].items()}}
    write(output/"delivery_manifest.json",manifest)
    if not roundtrip["passed"]:
        raise ValueError("FBX roundtrip failed")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--export",action="store_true")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    create(args.output.resolve(),args.export)
