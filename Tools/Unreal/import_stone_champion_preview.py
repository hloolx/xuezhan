"""Import the newly generated chief, independent club and five preview clips."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import import_stoneaxe_pilot as common
import fit_stoneaxe_socket as socket_math

VERSION="champion_stone_preview_v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def package_file(unreal,asset_path):
    package=asset_path.split(".")[0]
    if not package.startswith("/Game/ArtPilot/ChampionStonePreview/"):
        raise ValueError("Refuse unrelated package: "+package)
    return Path(unreal.Paths.project_content_dir()).resolve()/(package[6:]+".uasset")


def options(unreal,kind,skeleton=None):
    result=unreal.FbxImportUI()
    animated=kind=="animation"
    common.set_properties(result,{
        "automated_import_should_detect_type":False,"import_mesh":not animated,
        "import_as_skeletal":kind!="weapon","import_animations":animated,
        "create_physics_asset":False,"import_materials":False,"import_textures":False,
        "mesh_type_to_import":unreal.FBXImportType.FBXIT_ANIMATION if animated else
                             unreal.FBXImportType.FBXIT_STATIC_MESH if kind=="weapon" else unreal.FBXImportType.FBXIT_SKELETAL_MESH})
    if skeleton:
        if not skeleton.get_path_name().startswith("/Game/ArtPilot/ChampionStonePreview/"):
            raise ValueError("Unrelated skeleton")
        result.set_editor_property("skeleton",skeleton)
    data=result.get_editor_property("anim_sequence_import_data" if animated else "static_mesh_import_data" if kind=="weapon" else "skeletal_mesh_import_data")
    common.set_properties(data,{"import_uniform_scale":1.0,"convert_scene":True,"convert_scene_unit":True,"force_front_x_axis":False})
    if animated:
        common.set_properties(data,{"use_default_sample_rate":False,"custom_sample_rate":60,"import_bone_tracks":True,
                                   "animation_length":unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME})
    elif kind=="weapon":
        common.set_properties(data,{"combine_meshes":True,"auto_generate_collision":False})
    else:
        common.set_properties(data,{"update_skeleton_reference_pose":False,"use_t0_as_ref_pose":False,
                                   "normal_import_method":unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS})
    return result


def make_pbr(unreal,manifest,dest,mesh,reopen):
    editor,lib=unreal.EditorAssetLibrary,unreal.MaterialEditingLibrary
    material_paths={}
    variants={"Blue":manifest["textures"]["base_color"]}
    if manifest.get("team_cloth"):
        variants["Red"]=manifest["team_cloth"]["red_base_color"]
    if reopen:
        for team in variants:
            material_paths[team]=common.load_existing(unreal,dest+"/M_ChampionStone_"+team).get_path_name()
        return material_paths
    textures={}
    records={**manifest["textures"]}
    if "Red" in variants:
        records["base_color_red"]=variants["Red"]
    for channel,record in records.items():
        texture,_=common.import_task(unreal,record["path"],dest+"/Textures","T_ChampionStone_"+channel,factory=unreal.TextureFactory())
        texture.set_editor_property("srgb",channel.startswith("base_color"))
        if channel=="normal":
            texture.set_editor_property("compression_settings",unreal.TextureCompressionSettings.TC_NORMALMAP)
            texture.set_editor_property("flip_green_channel",True)
        elif channel=="orm":
            texture.set_editor_property("compression_settings",unreal.TextureCompressionSettings.TC_MASKS)
        editor.save_loaded_asset(texture)
        textures[channel]=texture
    for team in variants:
        mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_ChampionStone_"+team,dest,unreal.Material,unreal.MaterialFactoryNew())
        samplers={}
        for index,channel in enumerate(("base_color","normal","orm")):
            texture=textures["base_color_red" if channel=="base_color" and team=="Red" else channel]
            node=lib.create_material_expression(mat,unreal.MaterialExpressionTextureSample,-400,index*200)
            node.set_editor_property("texture",texture)
            node.set_editor_property("sampler_type",unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if channel=="base_color" else
                                     unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel=="normal" else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
            samplers[channel]=node
        for channel,pin,prop in (("base_color","RGB",unreal.MaterialProperty.MP_BASE_COLOR),("normal","RGB",unreal.MaterialProperty.MP_NORMAL),
                                 ("orm","G",unreal.MaterialProperty.MP_ROUGHNESS),("orm","B",unreal.MaterialProperty.MP_METALLIC)):
            if not lib.connect_material_property(samplers[channel],pin,prop):
                raise ValueError("PBR connection failed: "+channel)
        lib.set_base_material_usage(mat,unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH,True)
        lib.recompile_material(mat)
        editor.save_loaded_asset(mat)
        material_paths[team]=mat.get_path_name()
    slots=list(mesh.get_editor_property("materials"))
    for slot in slots:
        slot.set_editor_property("material_interface",editor.load_asset(material_paths["Blue"]))
    mesh.set_editor_property("materials",slots)
    editor.save_loaded_asset(mesh)
    return material_paths


def club_materials(unreal,weapon,dest,reopen):
    if reopen:
        return
    editor,lib=unreal.EditorAssetLibrary,unreal.MaterialEditingLibrary
    materials={}
    for name,color in (("Ivory",(.64,.56,.40)),("End",(.43,.36,.24)),("Leather",(.17,.075,.026))):
        mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_BoneClub_"+name,dest,unreal.Material,unreal.MaterialFactoryNew())
        color_node=lib.create_material_expression(mat,unreal.MaterialExpressionConstant3Vector,-300,0)
        color_node.set_editor_property("constant",unreal.LinearColor(*color,1))
        lib.connect_material_property(color_node,"",unreal.MaterialProperty.MP_BASE_COLOR)
        rough=lib.create_material_expression(mat,unreal.MaterialExpressionConstant,-300,150)
        rough.set_editor_property("r",.82)
        lib.connect_material_property(rough,"",unreal.MaterialProperty.MP_ROUGHNESS)
        lib.recompile_material(mat)
        editor.save_loaded_asset(mat)
        materials[name]=mat
    slots=list(weapon.get_editor_property("static_materials"))
    for slot in slots:
        name=str(slot.get_editor_property("imported_material_slot_name")).lower()
        slot.set_editor_property("material_interface",materials["Leather" if "leather" in name else "End" if "end" in name else "Ivory"])
    weapon.set_editor_property("static_materials",slots)
    editor.save_loaded_asset(weapon)


def fit_club(unreal,mesh,weapon,clips,calibration,reopen):
    vertices=[]
    for section in range(weapon.get_num_sections(0)):
        actual,*_=unreal.ProceduralMeshLibrary.get_section_from_static_mesh(weapon,0,section)
        vertices.extend(socket_math.ue_vector(point) for point in actual)
    geometry,_=socket_math.compare_vertices(vertices,[socket_math.blender_point_to_ue(point) for point in calibration["local_vertices_m"]])
    if not geometry["passed"]:
        raise ValueError("Imported club size/axes differ from authored local geometry")
    poses={name:socket_math.evaluate_pose(unreal,mesh,clips,sample) for name,sample in calibration["poses"].items()}
    hands={name:unreal.AnimPoseExtensions.get_bone_pose(value,"hand_r",unreal.AnimPoseSpaces.WORLD) for name,value in poses.items()}
    fitted=socket_math.fit_socket(socket_math.ue_transform(hands["reference"]),calibration["poses"]["reference"]["weapon_rigid_world_matrix"])
    local=socket_math.compose(fitted["translation_cm"],fitted["rotation_xyzw"],fitted["scale"])
    errors={}
    for name,sample in calibration["poses"].items():
        predicted=socket_math.multiply(socket_math.ue_transform(hands[name]),local)
        expected=socket_math.blender_transform_to_ue(sample["weapon_rigid_world_matrix"])
        errors[name]=max(socket_math.distance(socket_math.transform_point(predicted,point),socket_math.transform_point(expected,point)) for point in vertices)
    if max(errors.values())>.1:
        raise ValueError("Actual UE club/hand poses differ by over 1 mm: "+str(errors))
    existing=[mesh.get_socket_by_index(index) for index in range(mesh.num_sockets()) if
              str(mesh.get_socket_by_index(index).get_editor_property("socket_name"))=="weapon_r"]
    if len(existing)>1 or reopen and not existing:
        raise ValueError("Invalid persisted weapon socket")
    if existing:
        socket=existing[0]
        if str(socket.get_editor_property("bone_name"))!="hand_r" or socket_math.matrix_error(socket_math.ue_transform(socket.get_socket_local_transform()),local)>1e-5:
            raise ValueError("Existing socket conflicts with the measured club fit")
    else:
        socket=unreal.new_object(unreal.SkeletalMeshSocket,outer=mesh)
        socket.set_socket_parent(mesh,"hand_r")
        socket.set_socket_local_transform(unreal.Transform(location=unreal.Vector(*fitted["translation_cm"]),
            rotation=unreal.Quat(*fitted["rotation_xyzw"]).rotator(),scale=unreal.Vector(*fitted["scale"])))
        mesh.add_socket(socket,False)
        automatic=str(socket.get_editor_property("socket_name"))
        if not unreal.SkeletalMeshEditorSubsystem.rename_socket(mesh,automatic,"weapon_r"):
            raise ValueError("Could not name the new club socket")
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    return {"socket":"weapon_r","bone":"hand_r","local_transform":fitted,"vertex_check":geometry,
            "pose_maximum_vertex_error_cm":errors,"numeric_fit_passed":True,"visual_grip_approved":False}


def execute(manifest_path,report_path,prior_path=None):
    import unreal
    original_package_file=common.package_file
    manifest=read(manifest_path)
    prior=read(prior_path) if prior_path else None
    fingerprint=hashlib.sha256((common.digest(manifest_path)+VERSION).encode()).hexdigest()[:16]
    dest="/Game/ArtPilot/ChampionStonePreview/h"+fingerprint
    report={"version":VERSION,"manifest":str(manifest_path),"destination":dest,"execution_process_id":os.getpid(),
            "production_approved":False,"runtime_integrated":False,"status":"running"}
    try:
        common.package_file=package_file
        if manifest["asset_id"]!="Champion_Stone" or not manifest["blender_fbx_roundtrip_passed"] or not manifest["centimetre_normalization_passed"]:
            raise ValueError("Expected a normalized and roundtrip-verified new Champion_Stone")
        records=[manifest["body"],manifest["weapon"]["fbx"],manifest["weapon"]["calibration"],manifest["physical_motion_reference"],
                 manifest["centimetre_normalization"]]+manifest["clips"]+list(manifest["textures"].values())
        if manifest.get("team_cloth"):
            records.append(manifest["team_cloth"]["red_base_color"])
        for item in records:
            if common.digest(Path(item["path"]))!=item["sha256"]:
                raise ValueError("Changed source: "+item["path"])
        if prior:
            if prior["execution_process_id"]==os.getpid() or prior["destination"]!=dest:
                raise ValueError("Fresh reopen requires a new process and the same destination")
            common.persisted_packages(unreal,dest,[],prior)
            mesh=common.load_existing(unreal,dest+"/SK_ChampionStone_Preview")
        else:
            mesh,_=common.import_task(unreal,manifest["body"]["path"],dest,"SK_ChampionStone_Preview",options(unreal,"body"),unreal.FbxFactory())
        skeleton=mesh.get_editor_property("skeleton")
        if not prior:
            settings=unreal.SkeletalMeshEditorSubsystem.get_lod_build_settings(mesh,0)
            settings.set_editor_property("use_high_precision_skin_weights",True)
            unreal.SkeletalMeshEditorSubsystem.set_lod_build_settings(mesh,0,settings)
            common.save_dependency(unreal,skeleton,dest)
        result={"body":mesh.get_path_name(),"team_materials":make_pbr(unreal,manifest,dest,mesh,bool(prior)),
                "body_material_slots":list(range(len(mesh.get_editor_property("materials")))),
                "reference_pose":common.skeleton_audit(unreal,mesh,manifest),"clips":[]}
        report["result"]=result
        motion=read(manifest["physical_motion_reference"]["path"])
        sequences={}
        required=[mesh,skeleton]
        for clip in manifest["clips"]:
            name="AN_ChampionStone_"+clip["clip"]
            if prior:
                sequence=common.load_existing(unreal,dest+"/Animations/"+name)
            else:
                sequence,_=common.import_task(unreal,clip["path"],dest+"/Animations",name,options(unreal,"animation",skeleton),unreal.FbxFactory())
            sequences[clip["clip"]]=sequence
            result["clips"].append(common.animation_audit(unreal,sequence,clip,skeleton,mesh,motion["clips"][clip["clip"]],bool(prior)))
            required.append(sequence)
        if prior:
            weapon=common.load_existing(unreal,dest+"/Weapon/SM_ChampionStone_BoneClub")
        else:
            weapon,_=common.import_task(unreal,manifest["weapon"]["fbx"]["path"],dest+"/Weapon","SM_ChampionStone_BoneClub",options(unreal,"weapon"),unreal.FbxFactory())
        club_materials(unreal,weapon,dest+"/Weapon",bool(prior))
        result["weapon"]={"path":weapon.get_path_name(),"separate_from_body":True,
                          "socket_fit":fit_club(unreal,mesh,weapon,sequences,read(manifest["weapon"]["calibration"]["path"]),bool(prior))}
        required.append(weapon)
        result["structural_checks_passed"]=(result["reference_pose"]["bone_names_match_source"] and
            result["reference_pose"]["maximum_reference_bone_basis_error_cm"]<.1 and
            result["reference_pose"]["maximum_reference_world_scale_error"]<.001 and
            abs(result["reference_pose"]["dimensions_cm"][2]-198)<5 and
            all(c["absolute_motion_validation"]["status"]=="passed" and c["duration_error_seconds"]<.001 and c["root_translation_delta_cm"]<.01 for c in result["clips"]))
        result["disk_dependency_validation"]=common.persisted_packages(unreal,dest,required,prior)
        if not result["structural_checks_passed"]:
            raise ValueError("Imported chief structural/physical animation checks failed")
        report["status"]="fresh_reopen_verified_preview" if prior else "imported_preview_requires_fresh_reopen"
    except Exception as error:
        report["status"]="failed"
        report["error"]=str(error)
        raise
    finally:
        common.package_file=original_package_file
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("CHAMPION_STONE_UE_REPORT "+str(report_path))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest",default=os.environ.get("CIVWAR_CHAMPION_STONE_MANIFEST"))
    parser.add_argument("--report",default=os.environ.get("CIVWAR_CHAMPION_STONE_REPORT"))
    parser.add_argument("--prior",default=os.environ.get("CIVWAR_CHAMPION_STONE_PRIOR"))
    args,_=parser.parse_known_args()
    execute(Path(args.manifest).resolve(),Path(args.report).resolve(),Path(args.prior).resolve() if args.prior else None)
