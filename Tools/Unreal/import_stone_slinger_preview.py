"""Isolated StoneSlinger preview import; never changes runtime configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_stoneaxe_pilot as common
import import_stoneaxe_teamcolor as team

VERSION = "stone_slinger_integrated_sling_preview_v1"
MASK_REPORT = Path(__file__).resolve().parents[2]/"RawAssets/Art/Tripo_v01/tripo_processed/stone_slinger_v01/team_mask_preview_01/mask_report.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def package_file(unreal, asset_path):
    package = asset_path.split(".")[0]
    if not package.startswith("/Game/ArtPilot/StoneSlingerPreview/"):
        raise ValueError("Refuse unrelated package: "+package)
    return Path(unreal.Paths.project_content_dir()).resolve()/(package[6:]+".uasset")


def options(unreal, skeleton=None):
    result = unreal.FbxImportUI()
    animated = skeleton is not None
    common.set_properties(result, {
        "automated_import_should_detect_type":False,"import_mesh":not animated,
        "import_as_skeletal":True,"import_animations":animated,"create_physics_asset":False,
        "import_materials":False,"import_textures":False,
        "mesh_type_to_import":unreal.FBXImportType.FBXIT_ANIMATION if animated else unreal.FBXImportType.FBXIT_SKELETAL_MESH})
    if animated:
        if not skeleton.get_path_name().startswith("/Game/ArtPilot/StoneSlingerPreview/"):
            raise ValueError("Unrelated skeleton")
        result.set_editor_property("skeleton",skeleton)
    data=result.get_editor_property("anim_sequence_import_data" if animated else "skeletal_mesh_import_data")
    common.set_properties(data,{"import_uniform_scale":1.0,"convert_scene":True,"convert_scene_unit":True,"force_front_x_axis":False})
    if animated:
        common.set_properties(data,{"use_default_sample_rate":False,"custom_sample_rate":60,"import_bone_tracks":True,
                                   "animation_length":unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME})
    else:
        common.set_properties(data,{"update_skeleton_reference_pose":False,"use_t0_as_ref_pose":False,
                                   "normal_import_method":unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS})
    return result


def materials(unreal,manifest,destination,mesh,reopen):
    lib=unreal.MaterialEditingLibrary
    editor=unreal.EditorAssetLibrary
    body_name="M_StoneSlinger_PBR"
    if reopen:
        slots=[{"slot":str(s.get_editor_property("material_slot_name")),
                 "material":s.get_editor_property("material_interface").get_path_name()} for s in mesh.get_editor_property("materials")]
        return {"slots":slots,"team_materials":[{"slot":i,"path":destination+"/M_StoneSlinger_TeamCloth.M_StoneSlinger_TeamCloth"}
                    for i,s in enumerate(slots) if s["material"].endswith(body_name+"."+body_name)]}
    textures={}
    for channel,record in manifest["textures"].items():
        texture,_=common.import_task(unreal,record["path"],destination+"/Textures","T_StoneSlinger_"+channel,factory=unreal.TextureFactory())
        texture.set_editor_property("srgb",channel=="base_color")
        if channel=="normal":
            texture.set_editor_property("compression_settings",unreal.TextureCompressionSettings.TC_NORMALMAP)
            texture.set_editor_property("flip_green_channel",True)
        elif channel=="orm":
            texture.set_editor_property("compression_settings",unreal.TextureCompressionSettings.TC_MASKS)
        editor.save_loaded_asset(texture)
        textures[channel]=texture
    mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset(body_name,destination,unreal.Material,unreal.MaterialFactoryNew())
    samplers={}
    for index,(channel,texture) in enumerate(textures.items()):
        node=lib.create_material_expression(mat,unreal.MaterialExpressionTextureSample,-400,index*200)
        node.set_editor_property("texture",texture)
        node.set_editor_property("sampler_type",unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel=="normal" else
                                 unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if channel=="base_color" else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        samplers[channel]=node
    for channel,pin,prop in (("base_color","RGB",unreal.MaterialProperty.MP_BASE_COLOR),
                             ("normal","RGB",unreal.MaterialProperty.MP_NORMAL),
                             ("orm","G",unreal.MaterialProperty.MP_ROUGHNESS),
                             ("orm","B",unreal.MaterialProperty.MP_METALLIC)):
        if channel not in samplers or not lib.connect_material_property(samplers[channel],pin,prop):
            raise ValueError("Missing PBR channel "+channel)
    lib.set_base_material_usage(mat,unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH,True)
    lib.recompile_material(mat)
    editor.save_loaded_asset(mat)
    mask_report=read(MASK_REPORT)
    if mask_report["base_color"]["sha256"]!=manifest["textures"]["base_color"]["sha256"]:
        raise ValueError("Cloth mask and body texture differ")
    mask,_=common.import_task(unreal,mask_report["mask"]["path"],destination+"/Textures","T_StoneSlinger_ClothMask",factory=unreal.TextureFactory())
    common.set_properties(mask,team.mask_settings(unreal))
    editor.save_loaded_asset(mask)
    team_mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_StoneSlinger_TeamCloth",destination,unreal.Material,unreal.MaterialFactoryNew())
    nodes={}
    for i,(name,cls) in enumerate(team.NODE_CLASSES.items()):
        if name in {"roughness","metallic"}:
            continue
        nodes[name]=lib.create_material_expression(team_mat,getattr(unreal,cls),-1400+(i%4)*320,(i//4)*240)
        nodes[name].set_editor_property("desc",name)
    for channel in ("base_color","normal"):
        common.set_properties(nodes[channel],{"texture":textures[channel],"sampler_type":unreal.MaterialSamplerType.SAMPLERTYPE_COLOR
                              if channel=="base_color" else unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL})
    common.set_properties(nodes["cloth_mask"],{"texture":mask,"sampler_type":unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE})
    nodes["luminance_weights"].set_editor_property("constant",team.color(unreal,team.LUMINANCE))
    nodes["safe_team_luminance"].set_editor_property("const_b",.01)
    common.set_properties(nodes["team_color"],{"parameter_name":"TeamColor","default_value":team.color(unreal,team.TEAM_COLORS["Blue"])})
    common.set_properties(nodes["team_strength"],{"parameter_name":"TeamColorStrength","default_value":0.0,"slider_min":0.0,"slider_max":1.0})
    for source,pin,target,input_pin in team.LINKS:
        if not lib.connect_material_expressions(nodes[source],pin,nodes[target],input_pin):
            raise ValueError("Cloth graph connection failed")
    orm=lib.create_material_expression(team_mat,unreal.MaterialExpressionTextureSample,-300,750)
    common.set_properties(orm,{"texture":textures["orm"],"sampler_type":unreal.MaterialSamplerType.SAMPLERTYPE_MASKS})
    for node,pin,prop in ((nodes["cloth_blend"],"",unreal.MaterialProperty.MP_BASE_COLOR),
                           (nodes["normal"],"RGB",unreal.MaterialProperty.MP_NORMAL),
                           (orm,"G",unreal.MaterialProperty.MP_ROUGHNESS),(orm,"B",unreal.MaterialProperty.MP_METALLIC)):
        if not lib.connect_material_property(node,pin,prop):
            raise ValueError("Team PBR connection failed")
    lib.set_base_material_usage(team_mat,unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH,True)
    errors=list(lib.recompile_material(team_mat))
    if errors:
        raise ValueError("Team material compile error: "+str(errors))
    editor.save_loaded_asset(team_mat)
    simple={}
    for label,color in (("Cord",(.17,.10,.045)),("Pouch",(.23,.10,.04)),("Stone",(.30,.28,.23))):
        m=unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_Sling_"+label,destination,unreal.Material,unreal.MaterialFactoryNew())
        color_node=lib.create_material_expression(m,unreal.MaterialExpressionConstant3Vector,-300,0)
        color_node.set_editor_property("constant",unreal.LinearColor(*color,1))
        lib.connect_material_property(color_node,"",unreal.MaterialProperty.MP_BASE_COLOR)
        rough=lib.create_material_expression(m,unreal.MaterialExpressionConstant,-300,150)
        rough.set_editor_property("r",.83)
        lib.connect_material_property(rough,"",unreal.MaterialProperty.MP_ROUGHNESS)
        lib.set_base_material_usage(m,unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH,True)
        lib.recompile_material(m)
        editor.save_loaded_asset(m)
        simple[label]=m
    slots=list(mesh.get_editor_property("materials"))
    result=[]
    for slot in slots:
        name=str(slot.get_editor_property("imported_material_slot_name"))
        low=name.lower()
        actual=mat if "stoneslinger" in low or "pbr" in low else simple["Stone" if "stone" in low or "rock" in low else "Pouch" if "leather" in low else "Cord"]
        slot.set_editor_property("material_interface",actual)
        result.append({"slot":name,"material":actual.get_path_name()})
    if not any(r["material"]==mat.get_path_name() for r in result):
        raise ValueError("Body PBR slot was not identified")
    mesh.set_editor_property("materials",slots)
    editor.save_loaded_asset(mesh)
    return {"slots":result,"team_materials":[{"slot":i,"path":team_mat.get_path_name()}
            for i,row in enumerate(result) if row["material"]==mat.get_path_name()],
            "mask":mask_report["mask"],"scope":"Only scarf/sash blue cloth; original PBR and noncloth materials preserved"}


def execute(manifest_path,report_path,prior_path=None):
    import unreal
    manifest=read(manifest_path)
    if not manifest["blender_fbx_roundtrip_passed"] or not manifest["centimetre_normalization_passed"]:
        raise ValueError("Source FBX and scale checks did not pass")
    records=[manifest["body"],manifest["physical_motion_reference"],manifest["centimetre_normalization"]]+manifest["clips"]+list(manifest["textures"].values())
    for record in records:
        if common.digest(Path(record["path"]))!=record["sha256"]:
            raise ValueError("Source file changed: "+record["path"])
    mask_report=read(MASK_REPORT)
    if common.digest(Path(mask_report["mask"]["path"]))!=mask_report["mask"]["sha256"]:
        raise ValueError("Cloth mask changed")
    fingerprint=hashlib.sha256((common.digest(manifest_path)+VERSION+mask_report["mask"]["sha256"]).encode()).hexdigest()[:16]
    dest="/Game/ArtPilot/StoneSlingerPreview/h"+fingerprint
    prior=read(prior_path) if prior_path else None
    report={"version":VERSION,"manifest":str(manifest_path),"destination":dest,"execution_process_id":os.getpid(),
            "production_approved":False,"runtime_integrated":False,"status":"running"}
    previous_package_file=common.package_file
    try:
        common.package_file=package_file
        if prior:
            if prior["execution_process_id"]==os.getpid() or prior["destination"]!=dest:
                raise ValueError("Fresh reopen requires different process and same destination")
            common.persisted_packages(unreal,dest,[],prior)
            mesh=common.load_existing(unreal,dest+"/SK_StoneSlinger_Preview")
        else:
            mesh,_=common.import_task(unreal,manifest["body"]["path"],dest,"SK_StoneSlinger_Preview",options(unreal),unreal.FbxFactory())
        skeleton=mesh.get_editor_property("skeleton")
        if not prior:
            settings=unreal.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh,0)
            settings.set_editor_property("use_high_precision_skin_weights",True)
            unreal.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh,0,settings)
            common.save_dependency(unreal,skeleton,dest)
        result={"body":mesh.get_path_name(),"materials":materials(unreal,manifest,dest,mesh,bool(prior)),
                "reference_pose":common.skeleton_audit(unreal,mesh,manifest),"clips":[],"muzzle_bone":"sling_release"}
        report["result"]=result
        motion=read(manifest["physical_motion_reference"]["path"])
        required=[mesh,skeleton]
        for clip in manifest["clips"]:
            name="AN_StoneSlinger_"+clip["clip"]
            if prior:
                sequence=common.load_existing(unreal,dest+"/Animations/"+name)
            else:
                sequence,_=common.import_task(unreal,clip["path"],dest+"/Animations",name,options(unreal,skeleton),unreal.FbxFactory())
            result["clips"].append(common.animation_audit(unreal,sequence,clip,skeleton,mesh,motion["clips"][clip["clip"]],bool(prior)))
            required.append(sequence)
        result["structural_checks_passed"]=(result["reference_pose"]["bone_names_match_source"] and
             result["reference_pose"]["maximum_reference_bone_basis_error_cm"]<.1 and
             all(c["absolute_motion_validation"]["status"]=="passed" and c["duration_error_seconds"]<.001 and
                 c["root_translation_delta_cm"]<.01 for c in result["clips"]))
        result["disk_dependency_validation"]=common.persisted_packages(unreal,dest,required,prior)
        report["status"]="fresh_reopen_verified_preview" if prior else "imported_preview_requires_fresh_reopen"
        if not result["structural_checks_passed"]:
            raise ValueError("Structural or physical motion validation failed; retain diagnostics")
    except Exception as error:
        report["status"]="failed"
        report["error"]=str(error)
        raise
    finally:
        common.package_file=previous_package_file
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("STONE_SLINGER_UE_REPORT "+str(report_path))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest",default=os.environ.get("CIVWAR_STONE_SLINGER_MANIFEST"))
    parser.add_argument("--report",default=os.environ.get("CIVWAR_STONE_SLINGER_REPORT"))
    parser.add_argument("--prior",default=os.environ.get("CIVWAR_STONE_SLINGER_PRIOR"))
    args,_=parser.parse_known_args()
    execute(Path(args.manifest).resolve(),Path(args.report).resolve(),Path(args.prior).resolve() if args.prior else None)
