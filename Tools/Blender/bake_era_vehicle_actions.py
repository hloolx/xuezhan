"""Bind measured mechanical parts and bake five real skeletal clips.

Leased Blender only:
  blender -b -t 2 --python-exit-code 1 --python this.py -- --spec spec.json

Spec names an existing prepared .blend and its actual mesh objects, with
part_bones, joint_origins_cm, optional bone_parents, wheel/tread/leg measurements,
recoil bones and an actual muzzle bone. Geometry splitting is a separate step;
this refuses a lone rigid hull presented as a complete wheeled/tracked/mech rig.
No runtime/default/config files are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from era_vehicle_motion import Motion, capsule_frame, capsule_length
import prepare_era_mechanism as preparation

ROOT = Path(__file__).resolve().parents[2]


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "bytes": Path(path).stat().st_size}


def bind(bpy, spec):
    from mathutils import Vector
    motion = Motion(spec)
    originals = {}
    for name, bone in spec["part_bones"].items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH" or bone not in motion.origins or bone == "root":
            raise ValueError("Missing real part or measured deform bone: "+name)
        originals[name] = obj
    track_objects = {}
    for name, index in spec.get("track_objects", {}).items():
        obj = bpy.data.objects.get(name)
        if name in originals or obj is None or obj.type != "MESH" or not 0 <= index < len(spec.get("tracks", [])):
            raise ValueError("Missing actual tread surface mesh")
        track_objects[name] = (obj, index)
    deform_bones = set(spec["part_bones"].values())
    if motion.profile == "wheeled_unit":
        required = {wheel["bone"] for wheel in spec["wheels"]}
    elif motion.profile == "biped_mech":
        required = {leg[key] for leg in spec["legs"] for key in ("upper", "lower", "foot")}
    else:
        if set(spec.get("track_objects", {}).values()) != {0, 1}:
            raise ValueError("Two independent real tread surfaces are required")
        required = set()
    if not required.issubset(deform_bones):
        raise ValueError("Actual moving parts have no weighted source geometry: "+str(required-deform_bones))
    if spec["muzzle_bone"] not in motion.origins:
        raise ValueError("Missing measured real muzzle")
    armature_data = bpy.data.armatures.new("MechanicalSkeleton")
    rig = bpy.data.objects.new("Armature", armature_data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    # Parents must precede children. All bones use a predictable rest basis;
    # the pure motion adapter supplies full world delta matrices.
    parents = spec.get("bone_parents", {})
    if list(motion.origins)[0] != "root":
        raise ValueError("Root must be the first measured joint")
    for name, origin in motion.origins.items():
        bone = armature_data.edit_bones.new(name)
        bone.head = Vector(origin)
        bone.tail = Vector(origin)+Vector((0, 0, .05))
        if name != "root":
            parent = parents.get(name, "root")
            if parent not in armature_data.edit_bones:
                raise ValueError("Bone hierarchy must be parent-first: "+name)
            bone.parent = armature_data.edit_bones[parent]
        bone.use_deform = True
    bpy.ops.object.mode_set(mode="OBJECT")
    source_records = []
    objects = list(originals.values())+[value[0] for value in track_objects.values()]
    for obj in objects:
        # Convert all original mesh transforms to source world metres before
        # weighting. UVs, material slots and normals stay on the actual mesh.
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if obj.animation_data or obj.modifiers:
            raise ValueError("Prepared parts must have their source deformation baked: "+obj.name)
        obj.data.calc_loop_triangles()
        source_records.append({"object": obj.name, "triangles": len(obj.data.loop_triangles),
                               "vertices": len(obj.data.vertices)})
        obj.vertex_groups.clear()
        if obj.name in originals:
            group = obj.vertex_groups.new(name=spec["part_bones"][obj.name])
            group.add(list(range(len(obj.data.vertices))), 1., "REPLACE")
        else:
            track = spec["tracks"][track_objects[obj.name][1]]
            args = (track["half_straight_cm"]/100, track["radius_cm"]/100,
                    track["lateral_cm"]/100, track["centre_height_cm"]/100,
                    track.get("forward_cm", 0)/100)
            length = capsule_length(args[0], args[1])
            samples = np.array([capsule_frame(i*length/1024, *args)[:3, 3] for i in range(1024)])
            groups = [obj.vertex_groups.new(name=bone) for bone in track["bones"]]
            for vertex in obj.data.vertices:
                if obj.name in spec.get("rigid_tread_objects", []):
                    attribute = obj.data.attributes.get("tread_bone_index")
                    if attribute is None:
                        raise ValueError("Authored chain link lost its measured bone identity")
                    index = attribute.data[vertex.index].value
                    if not 0 <= index < len(groups):
                        raise ValueError("Invalid rigid chain-link bone index")
                    groups[index].add([vertex.index], 1., "REPLACE")
                    continue
                nearest = int(np.argmin(np.linalg.norm(samples-np.array(vertex.co), axis=1)))
                phase = nearest/1024*len(groups)
                a, weight = int(phase), phase-int(phase)
                groups[a].add([vertex.index], 1-weight, "REPLACE")
                groups[(a+1)%len(groups)].add([vertex.index], weight, "REPLACE")
        modifier = obj.modifiers.new("ActualMechanicalBones", "ARMATURE")
        modifier.object = rig
        obj.parent = rig
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    body = bpy.context.object
    body.name = "SK_"+spec["asset_id"]
    return rig, body, motion, source_records


def export(bpy, rig, body, path, animation=False):
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", axis_forward="X", axis_up="Z",
        use_mesh_modifiers=True, add_leaf_bones=False, use_armature_deform_only=True,
        bake_anim=animation, bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=1., bake_anim_simplify_factor=0.,
        path_mode="STRIP", embed_textures=False)


def run(spec_path, render=False):
    import bpy
    from mathutils import Matrix, Vector
    spec = preparation.static.read(spec_path)
    definitions = preparation.static.read(ROOT/"Content/Data/Units.json")
    definition = next((row for row in definitions if row["VisualKey"] == spec["asset_id"]), None)
    if not definition or any(abs(definition[key]-spec[field]) > .00001 for key, field in (
            ("AttackWindup", "contact_time"), ("AttackInterval", "attack_interval"),
            ("MoveSpeed", "reference_move_speed_cm_s"))):
        raise ValueError("Measured animation spec does not match actual gameplay timing")
    source = preparation.static.absolute(spec["scene"])
    if preparation.static.digest(source) != spec["scene_sha256"]:
        raise ValueError("Prepared mechanical scene changed")
    output = preparation.static.absolute(spec["output"])
    if (output/"vehicle_manifest.json").exists():
        raise ValueError("Use a new output candidate; completed bundles are immutable")
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    scene.render.fps = 60
    rig, body, motion, source_records = bind(bpy, spec)
    bpy.context.view_layer.update()
    vertices = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    bounds = {"minimum": [min(v[i] for v in vertices)*100 for i in range(3)],
              "maximum": [max(v[i] for v in vertices)*100 for i in range(3)]}
    material_names = [slot.material.name if slot.material else None for slot in body.material_slots]
    expected_names = [row["slot_name"] for row in spec["materials"]]
    if len(set(material_names)) != len(material_names) or set(material_names) != set(expected_names):
        raise ValueError("Actual joined material slots differ from prepared PBR records")
    body_path = output/(body.name+".fbx")
    export(bpy, rig, body, body_path)
    bind_matrices = {bone.name: bone.bone.matrix_local.copy() for bone in rig.pose.bones}
    parents = spec.get("bone_parents", {})
    levels = {}
    for name in motion.origins:
        levels[name] = 0 if name == "root" else levels[parents.get(name, "root")]+1
    reference_speed = motion.speed
    frames_move = max(2, round(motion.cycle*60))
    if motion.profile in {"wheeled_unit", "tracked_unit"}:
        motion.speed *= motion.cycle/(frames_move/60)
        reference_speed = motion.speed
        motion.cycle = frames_move/60
        motion.durations["Move"] = motion.cycle
    clips, reference, actions = [], {}, {}
    bind_reference = {name: [list(row) for row in matrix] for name, matrix in bind_matrices.items()}
    for clip, duration in motion.durations.items():
        frames = max(2, round(duration*60))
        duration = frames/60
        rig.animation_data_create()
        action = bpy.data.actions.new("AN_"+spec["asset_id"]+"_"+clip)
        actions[clip] = action
        rig.animation_data.action = action
        scene.frame_start, scene.frame_end = 0, frames
        samples, minimum_ground, maximum_root, maximum_ground_lift = [], float("inf"), 0., 0.
        previous_quaternions = {}
        for frame in range(frames+1):
            scene.frame_set(frame)
            delta = motion.pose(clip, min(frame/60, motion.durations[clip]))
            for level in sorted(set(levels.values())):
                for name in motion.origins:
                    if levels[name] == level:
                        rig.pose.bones[name].matrix = Matrix(delta[name].tolist()) @ bind_matrices[name]
                bpy.context.view_layer.update()
            evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
            lowest = min((evaluated.matrix_world @ v.co).z for v in evaluated.data.vertices)
            # Ground correction is a local skeleton adjustment, never root
            # motion. Mech support should already be grounded by measured IK.
            if lowest < -.0001:
                maximum_ground_lift = max(maximum_ground_lift, -lowest)
                lift = Vector((0, 0, -lowest))
                for level in sorted(set(levels.values())):
                    for name in motion.origins:
                        if name != "root" and levels[name] == level:
                            matrix = Matrix(delta[name].tolist()) @ bind_matrices[name]
                            matrix.translation += lift
                            rig.pose.bones[name].matrix = matrix
                    bpy.context.view_layer.update()
                evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
                lowest = min((evaluated.matrix_world @ v.co).z for v in evaluated.data.vertices)
                if lowest < -.0001:
                    raise ValueError("Mechanical pose still penetrates the actual ground")
            row = {"time": frame/60, "bones": {}}
            for bone in rig.pose.bones:
                bone.rotation_mode = "QUATERNION"
                previous = previous_quaternions.get(bone.name)
                if previous is not None and previous.dot(bone.rotation_quaternion) < 0:
                    bone.rotation_quaternion.negate()
                previous_quaternions[bone.name] = bone.rotation_quaternion.copy()
                bone.keyframe_insert("location", frame=frame, group=bone.name)
                bone.keyframe_insert("rotation_quaternion", frame=frame, group=bone.name)
                bone.keyframe_insert("scale", frame=frame, group=bone.name)
                point = bone.matrix.translation
                quat = bone.matrix.to_quaternion()
                row["bones"][bone.name] = {"position_cm": [point.x*100, point.y*100, point.z*100],
                                           "rotation_xyzw": [quat.x, quat.y, quat.z, quat.w],
                                           "world_matrix_m": [list(values) for values in bone.matrix]}
            maximum_root = max(maximum_root, float(rig.pose.bones["root"].matrix.translation.length))
            minimum_ground = min(minimum_ground, lowest)
            samples.append(row)
        if maximum_root > 1e-6:
            raise ValueError("Mechanical action introduced root translation")
        for layer in action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    for curve in channelbag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = "LINEAR"
        path = output/(action.name+".fbx")
        export(bpy, rig, body, path, True)
        clips.append(dict(record(path), id=clip, duration=duration, frames=frames+1,
                          minimum_ground_cm=minimum_ground*100, maximum_root_translation_cm=maximum_root*100,
                          maximum_ground_lift_cm=maximum_ground_lift*100))
        reference[clip] = samples
    reference_path = output/"physical_reference.json"
    write(reference_path, reference)
    scene.frame_set(scene.frame_end)
    blend_path = output/(spec["asset_id"]+"_actions.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    previews = []
    if render:
        for obj in scene.objects:
            if obj.type == "MESH" and obj != body:
                obj.hide_render = True
        rig.animation_data.action = actions["Idle"]
        scene.frame_set(0)
        preparation.static.render_preview(bpy, body, output)
        previews.extend(record(output/("preview_"+view+".png")) for view in ("front", "back"))
        for name, time in (("Move", motion.cycle*.2), ("Attack", motion.contact+.04), ("Death", 1.8)):
            rig.animation_data.action = actions[name]
            scene.frame_set(round(time*60))
            scene.render.filepath = str(output/("preview_"+name+".png"))
            bpy.ops.render.render(write_still=True)
            previews.append(record(scene.render.filepath))
    result = {"asset_id": spec["asset_id"], "status": "five_mechanical_clips_prepared_pending_unreal",
              "source_scene": record(source), "spec": record(spec_path), "tool": record(__file__),
              "body": record(body_path), "clips": clips, "physical_reference": record(reference_path),
              "bind_bone_matrices_m": bind_reference, "bounds_blender_cm": bounds,
              "blend": record(blend_path), "materials": spec["materials"], "source_parts": source_records,
              "bone_count": len(rig.data.bones), "muzzle_bone": spec["muzzle_bone"],
              "reference_move_speed_cm_s": reference_speed*100, "contact_time": motion.contact,
              "attack_interval": motion.attack, "vehicle": motion.profile != "biped_mech",
              "attack_style": spec["attack_style"],
              "mechanical_profile": motion.profile, "production_approved": False,
              "previews": previews,
              "rolling_speed_relative_error": getattr(motion, "rolling_speed_relative_error", 0.),
              "motion_tool": record(Path(__file__).with_name("era_vehicle_motion.py"))}
    write(output/"vehicle_manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    result = run(args.spec, args.render)
    print(json.dumps({"asset_id": result["asset_id"], "status": result["status"], "bone_count": result["bone_count"]}))


if __name__ == "__main__":
    main()
