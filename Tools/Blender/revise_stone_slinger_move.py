"""Replace only Move in candidate02 with a physically matched 160cm/s gait."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
import build_stone_slinger_gameplay as build


def restore_other_actions(source, armature, body, loop, stations, source_world, rest):
    manifest=build.read(source/"delivery_manifest.json")
    evidence=build.read(manifest["physical_motion_reference"]["path"])
    reports={}
    for name in ("Idle","Attack","Hit","Death"):
        record=next(c for c in manifest["clips"] if c["clip"]==name)
        if build.exporter.file_record(Path(record["path"]))["sha256"]!=record["sha256"]:
            raise ValueError("Original FBX clip changed")
        action=bpy.data.actions.new("CW_StoneSlinger_"+name)
        action.use_fake_user=True
        armature.animation_data.action=action
        max_bone_error=max_skin_error=0.
        sample_ids=evidence["skinned_sample_vertex_indices"]
        body_indices=[(index,vertex) for index,vertex in enumerate(sample_ids) if vertex<len(body.data.vertices)]
        for row in evidence["clips"][name]:
            frame=row["frame"]
            bpy.context.scene.frame_set(frame)
            release,swing=build.body_pose(armature,loop,rest,name,(frame-1)/60)
            build.animate_weapon(armature,stations,source_world,rest,release,swing)
            points,_=build.base.evaluated_snapshot(body)
            correction=max(0.,.0002-float(points[:,2].min()))
            if correction:
                build.translate(armature,"pelvis",(0,0,correction))
                build.animate_weapon(armature,stations,source_world,rest,release,swing)
            build.keyed(armature,frame)
            max_bone_error=max(max_bone_error,max((build.base.bone_world(armature,b).translation-Vector(v["head_m"])).length
                                                 for b,v in row["bones"].items()))
            points,_=build.base.evaluated_snapshot(body)
            max_skin_error=max(max_skin_error,max((Vector(points[vertex])-Vector(row["skinned_points_m"][index])).length
                                                 for index,vertex in body_indices))
        reports[name]={"frames":len(evidence["clips"][name]),"maximum_bone_position_error_m":max_bone_error,
                       "maximum_original_body_sample_error_m":max_skin_error,"source_fbx":record,
                       "method":"Rebuilt with exact candidate02 algorithm, compared against candidate02 physical motion"}
        if max_bone_error>.0001 or max_skin_error>.0005:
            raise ValueError("Other-action recovery differs from02: "+name+" "+str(reports[name]))
    armature.animation_data.action=None
    build.base.transfer.set_pose([armature],[])
    return reports


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    source=args.source.resolve()
    output=args.output.resolve()
    if (output/"preview_report.json").exists() or (output/"Unit_StoneSlinger_Gameplay.blend").exists():
        raise ValueError("Refuse overwrite of an executed candidate")
    output.mkdir(parents=True,exist_ok=True)
    previous=build.read(source/"preview_report.json")
    if build.exporter.file_record(Path(previous["blend"]["path"]))!=previous["blend"]:
        raise ValueError("Reviewed source changed")
    bpy.ops.wm.open_mainfile(filepath=previous["blend"]["path"])
    armature,=[o for o in bpy.context.scene.objects if o.type=="ARMATURE"]
    body,=[o for o in bpy.context.scene.objects if o.type=="MESH" and o.name not in
           {"retained_loop_cord","released_cord","leather_pouch","loaded_stone"}]
    parts={name:bpy.context.scene.objects[name] for name in ("retained_loop_cord","released_cord","leather_pouch","loaded_stone")}
    objects=[body]+list(parts.values())
    loop=build.read(build.WORK/"sling_pilot_v01/loop_anchor_plan_04/loop_anchor_plan.json")
    source_world=build.Matrix(loop["basis_columns"]).to_4x4()
    source_world.translation=Vector(loop["root_rest_m"])
    armature.animation_data.action=None
    build.base.transfer.set_pose([armature],[])
    rest={b.name:armature.matrix_world@b.matrix_local for b in armature.data.bones}
    original=build.base.rig.mesh_snapshot(body)
    weights=build.base.foot.weights_of(body)
    stations={}
    for name in rest:
        if name.startswith(("sling_retained_","sling_released_")):
            kind,index=name.split("_")[1:]
            stations[name]={"kind":kind,"index":int(index),"z":-.52*int(index)/7}
        elif name.startswith("sling_"):
            stations[name]={"kind":name,"index":7,"z":-.48 if name=="sling_release" else -.52}
    build.base.set_bone_world_rotation=build.prior.set_rotation_channels
    recovered=restore_other_actions(source,armature,body,loop,stations,source_world,rest)
    if bpy.data.actions.get("CW_StoneSlinger_Move"):
        bpy.data.actions["CW_StoneSlinger_Move"].name="Archived_CW_StoneSlinger_Move_02"
    action=bpy.data.actions.new("CW_StoneSlinger_Move")
    action.use_fake_user=True
    armature.animation_data.action=action
    before_actions={name:bpy.data.actions["CW_StoneSlinger_"+name].as_pointer() for name in ("Idle","Attack","Hit","Death")}
    rows=[]
    scene=bpy.context.scene
    for frame in range(1,38):
        time=(frame-1)/60
        scene.frame_set(frame)
        build.base.transfer.set_pose([armature],loop["commands"])
        bob=.006*(1-math.cos(time*math.tau/.3))
        build.translate(armature,"pelvis",(0,0,-.085+bob))
        phases={}
        targets={}
        for side in ("l","r"):
            phase=((time/.6)+(0.5 if side=="r" else 0))%1
            phases[side]=phase
            target=rest["foot_"+side].translation.copy()
            if phase<.5:
                travel=.24-.48*phase/.5
                lift=0
            else:
                q=(phase-.5)/.5
                travel=-.24+.48*build.smooth(q)
                lift=.065*math.sin(math.pi*q)
            target+=Vector((travel,0,lift+.001))
            targets[side]=target.copy()
            build.solve_chain(armature,"thigh_"+side,"calf_"+side,"foot_"+side,target,(.5,target.y,.40))
            build.prior.set_rotation_channels(armature,"foot_"+side,rest["foot_"+side].to_quaternion())
        sway=.035*math.sin(time*math.tau/.6)
        build.base.solve_arm(armature,"r",(.17+sway,-.43,.98),(-.15,-.60,1.03))
        build.base.solve_arm(armature,"l",(.12-sway,.34,.84),(-.15,.60,.95))
        build.animate_weapon(armature,stations,source_world,rest,0,-.12+.09*math.sin(time*math.tau/.6))
        points,_=build.base.evaluated_snapshot(body)
        correction=max(0.,.0002-float(points[:,2].min()))
        if correction:
            build.translate(armature,"pelvis",(0,0,correction))
            build.animate_weapon(armature,stations,source_world,rest,0,-.12+.09*math.sin(time*math.tau/.6))
            points,_=build.base.evaluated_snapshot(body)
        feet={s:list(build.base.bone_world(armature,"foot_"+s).translation) for s in ("l","r")}
        errors={s:(Vector(feet[s])-targets[s]).length for s in ("l","r")}
        rows.append({"frame":frame,"time":time,"phase":phases,"feet_m":feet,"target_error_m":errors,
                     "body_floor_min_m":float(points[:,2].min()),"floor_correction_m":correction})
        build.keyed(armature,frame)
    velocity={}
    for side in ("l","r"):
        speeds=[]
        for a,b in zip(rows,rows[1:]):
            if 0<=a["phase"][side]<b["phase"][side]<.5:
                speeds.append(-(b["feet_m"][side][0]-a["feet_m"][side][0])/.016666666666666666*100)
        velocity[side]={"samples":len(speeds),"minimum_cm_s":min(speeds),"maximum_cm_s":max(speeds),
                        "maximum_error_from_160":max(abs(v-160) for v in speeds)}
    maximum_error=max(v for row in rows for v in row["target_error_m"].values())
    report={**previous,"status":"move_160cm_s_preview_pending_visual_review","source_previous":previous["blend"],"images":[],
            "move_revision":{"duration":.6,"frames":37,"foot_half_travel_m":.24,"stance_fraction":.5,
                             "reference_move_speed":160.0,"actual_stance_velocity":velocity,"rows":rows,
                             "maximum_foot_target_error_m":maximum_error},
            "nonmove_fbx_recovery_against_original_physical_reference":recovered,
            "unmodified_other_actions":{name:before_actions[name]==bpy.data.actions["CW_StoneSlinger_"+name].as_pointer() for name in before_actions}}
    armature.animation_data.action=None
    build.base.transfer.set_pose([armature],[])
    report["source_preservation"]=build.base.transfer.check_rest_normals_uv(original,build.base.rig.mesh_snapshot(body))
    report["source_preservation"]["weights_exact"]=weights==build.base.foot.weights_of(body)
    report["clips"]={**previous["clips"],"Move":{"frames":37,"duration":.6,"body_floor_min_m":min(row["body_floor_min_m"] for row in rows),"root_displacement_m":0,
                                               "reference_move_speed":160}}
    build.write(output/"preview_report.json",report)
    if maximum_error>.003 or any(v["maximum_error_from_160"]>.5 for v in velocity.values()):
        raise ValueError("Actual foot reach or stance velocity failed; do not export")
    for obj in list(scene.objects):
        if obj.type in {"CAMERA","LIGHT"}:
            bpy.data.objects.remove(obj,do_unlink=True)
    renderer=build.base.rig.module("slinger_move_renderer","prepare_tripo_character.py")
    renderer.render_setup(samples=8)
    scene.render.threads_mode,scene.render.threads="FIXED",2
    for frame in (1,7,13,19,25,31):
        armature.animation_data.action=action
        scene.frame_set(frame)
        path=output/f"Move_{frame:03}.png"
        renderer.render_view(path,objects,(1,-1.5,.35),size=640,framing=2.30,target=(.05,-.10,.72))
        report["images"].append(str(path))
    armature.animation_data.action=None
    build.base.transfer.set_pose([armature],[])
    blend=output/"Unit_StoneSlinger_Gameplay.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    report["blend"]=build.exporter.file_record(blend)
    build.write(output/"preview_report.json",report)
    build.CLIPS["Move"]=37
    build.export(output,armature,objects,body,report)
    print("STONE_SLINGER_MOVE "+json.dumps(report["move_revision"]["actual_stance_velocity"]))


if __name__=="__main__":
    main()
