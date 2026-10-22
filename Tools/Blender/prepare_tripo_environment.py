"""Preserve real Tripo GLBs while normalizing game scale and bottom origin.

blender --background --python-exit-code 1 --python Tools/Blender/prepare_tripo_environment.py -- \
  --asset Env_Pine --input <downloaded.glb> --task-id <actual-id> --no-render

No new asset geometry, remeshing, decimation, UV generation, or material replacement.
The primary Unreal interchange file is GLB; FBX is a secondary compatibility copy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=ROOT/"RawAssets/Art/Tripo_v01/tripo_processed"
TARGETS={
    "Env_BoulderA":("horizontal_max",125),
    "Env_BoulderB":("horizontal_max",165),
    "Env_RockSlab":("horizontal_max",115),
    "Env_Shrub":("height",90),
    "Env_Pine":("height",650),
    "Env_Broadleaf":("height",590),
    "Env_GrassClump":("height",43),
}


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def project_path(path):
    try: return str(Path(path).resolve().relative_to(ROOT)).replace("\\","/")
    except ValueError: return str(Path(path).resolve())


def glb_container_report(path):
    data=Path(path).read_bytes()
    magic,version,length=struct.unpack_from("<III",data,0)
    if magic!=0x46546C67 or version!=2 or length!=len(data):
        raise ValueError("Invalid glTF 2 binary container: "+str(path))
    offset=12;document=None;binary=b""
    while offset<len(data):
        size,kind=struct.unpack_from("<II",data,offset);offset+=8
        payload=data[offset:offset+size];offset+=size
        if kind==0x4E4F534A: document=json.loads(payload.decode("utf-8").rstrip(" \t\r\n\0"))
        elif kind==0x004E4942: binary=payload
    if document is None: raise ValueError("GLB has no JSON chunk")
    images=[]
    for index,record in enumerate(document.get("images",[])):
        item={"index":index,"name":record.get("name"),"mime_type":record.get("mimeType")}
        if "bufferView" in record:
            view=document["bufferViews"][record["bufferView"]]
            start=view.get("byteOffset",0);image_bytes=binary[start:start+view["byteLength"]]
            item.update(sha256=hashlib.sha256(image_bytes).hexdigest(),byte_length=len(image_bytes))
        else: item["uri"]=record.get("uri")
        images.append(item)
    return {"materials":len(document.get("materials",[])),"meshes":len(document.get("meshes",[])),
            "images":images,"extensions_used":document.get("extensionsUsed",[])}


def bounds(objects):
    points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
    if not points: raise ValueError("Tripo file contains no mesh vertices")
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    if any(not math.isfinite(c) for p in points for c in p):
        raise ValueError("Non-finite source mesh coordinates")
    if min(high-low)<=1e-7: raise ValueError("Source has a collapsed bounding dimension")
    return low,high


def geometry_report(objects):
    result=[]
    for obj in objects:
        mesh=obj.data
        mesh.calc_loop_triangles()
        bm=bmesh.new();bm.from_mesh(mesh)
        boundary=sum(e.is_boundary for e in bm.edges)
        nonmanifold=sum(not e.is_manifold for e in bm.edges)
        degenerate=sum(f.calc_area()<1e-12 for f in bm.faces)
        # glTF often duplicates seam vertices. Diagnose coincident seams on a disposable
        # BMesh copy only; never write this welded diagnostic back to the source mesh.
        weld_tolerance=max(max(obj.dimensions),1e-6)*1e-6
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=weld_tolerance)
        welded_boundary=sum(e.is_boundary for e in bm.edges)
        welded_nonmanifold=sum(not e.is_manifold for e in bm.edges)
        bm.free()
        uv_degenerate=0
        if mesh.uv_layers:
            uv=mesh.uv_layers.active.data
            for tri in mesh.loop_triangles:
                a,b,c=[uv[i].uv for i in tri.loops]
                if abs((b-a).cross(c-a))<1e-12: uv_degenerate+=1
        result.append({"object":obj.name,"vertices":len(mesh.vertices),"polygons":len(mesh.polygons),
                       "triangles":len(mesh.loop_triangles),"uv_layers":[layer.name for layer in mesh.uv_layers],
                       "uv_zero_area_triangles":uv_degenerate,"boundary_edges":boundary,
                       "nonmanifold_edges":nonmanifold,"degenerate_faces":degenerate,
                       "coincident_seam_diagnostic":{"source_mesh_modified":False,"tolerance_m":weld_tolerance,
                            "boundary_edges_after_position_weld":welded_boundary,
                            "nonmanifold_edges_after_position_weld":welded_nonmanifold},
                       "color_attributes":[a.name for a in mesh.color_attributes],
                       "materials":[m.name if m else None for m in mesh.materials],
                       "has_custom_normals":mesh.has_custom_normals})
    return {"mesh_count":len(result),"vertices":sum(r["vertices"] for r in result),
            "polygons":sum(r["polygons"] for r in result),"triangles":sum(r["triangles"] for r in result),"meshes":result}


def material_report(objects):
    materials={m.name:m for o in objects for m in o.data.materials if m}
    rows=[]
    for material in materials.values():
        nodes=material.node_tree.nodes if material.use_nodes else []
        images=[]
        for node in nodes:
            if node.type=="TEX_IMAGE" and node.image:
                images.append({"node":node.name,"image":node.image.name,"size":list(node.image.size),
                               "colorspace":node.image.colorspace_settings.name,"extension":node.extension,
                               "interpolation":node.interpolation})
        rows.append({"name":material.name,"use_nodes":material.use_nodes,"images":images,
                     "diffuse_color":list(material.diffuse_color),"use_backface_culling":material.use_backface_culling,
                     "nodes":[{"name":n.name,"type":n.type} for n in nodes],
                     "principled_inputs":[{"node":n.name,"inputs":{
                         socket.name:(list(socket.default_value) if hasattr(socket.default_value,"__len__") else socket.default_value)
                         for socket in n.inputs if hasattr(socket,"default_value")
                         and socket.name in {"Base Color","Metallic","Roughness","Alpha","IOR"}}}
                         for n in nodes if n.type=="BSDF_PRINCIPLED"],
                     "links":[{"from_node":link.from_node.name,"from_socket":link.from_socket.name,
                                "to_node":link.to_node.name,"to_socket":link.to_socket.name}
                               for link in material.node_tree.links] if material.use_nodes else []})
    return rows


def uv_signature(objects):
    records=[]
    for obj in objects:
        for layer in obj.data.uv_layers:
            records.extend((layer.name,round(float(item.uv.x),9),round(float(item.uv.y),9)) for item in layer.data)
    records.sort()
    return {"loop_values":len(records),"sha256":hashlib.sha256(json.dumps(records,separators=(",",":")).encode()).hexdigest(),
            "layer_sets":[sorted(layer.name for layer in obj.data.uv_layers) for obj in objects]}


def texture_extension(data,image):
    if data[:8]==b"\x89PNG\r\n\x1a\n": return ".png"
    if data[:3]==b"\xff\xd8\xff": return ".jpg"
    if data[:4]==b"RIFF" and data[8:12]==b"WEBP": return ".webp"
    extension={"PNG":".png","JPEG":".jpg","OPEN_EXR":".exr","TARGA":".tga"}.get(image.file_format)
    if extension: return extension
    raise ValueError("Unrecognized packed image format: "+image.name)


def extract_original_textures(objects,directory):
    images={}
    for obj in objects:
        for material in obj.data.materials:
            if material and material.use_nodes:
                for node in material.node_tree.nodes:
                    if node.type=="TEX_IMAGE" and node.image:
                        images[node.image.name]=node.image
    records=[]
    directory.mkdir(parents=True,exist_ok=True)
    for image in images.values():
        if image.packed_file:
            data=bytes(image.packed_file.data)
            original="embedded_in_downloaded_glb"
        else:
            image_path=Path(bpy.path.abspath(image.filepath))
            if not image_path.is_file():
                raise ValueError("Referenced source texture is unavailable: "+image.name)
            data=image_path.read_bytes();original=str(image_path)
        digest=hashlib.sha256(data).hexdigest()
        safe=re.sub(r"[^A-Za-z0-9_.-]","_",image.name)[:80] or "texture"
        target=directory/(Path(safe).stem+"_"+digest[:12]+texture_extension(data,image))
        target.write_bytes(data)
        # Save exact original bytes. The material graph and its image data remain untouched.
        records.append({"image":image.name,"file":project_path(target),"sha256":digest,
                        "size":list(image.size),"colorspace":image.colorspace_settings.name,
                        "source":original,"bytes_preserved":True})
    return records


def select(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False);obj.hide_render=False;obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]


def normalize(objects,measure,target_cm,yaw_deg):
    rotation=Matrix.Rotation(math.radians(yaw_deg),4,"Z")
    # Freeze the source world transforms before severing parents; preserve actual vertices/UVs.
    transforms={obj:rotation@obj.matrix_world.copy() for obj in objects}
    for obj in objects:
        if obj.data.users>1:
            obj.data=obj.data.copy()  # Flatten shared instances without changing their geometry.
        obj.parent=None
        obj.matrix_world=transforms[obj]
    bpy.context.view_layer.update()
    low,high=bounds(objects);dim=high-low
    source_measure=dim.z if measure=="height" else max(dim.x,dim.y)
    ratio=(target_cm/100)/source_measure
    origin=Vector(((low.x+high.x)/2,(low.y+high.y)/2,low.z))
    transform=Matrix.Scale(ratio,4)@Matrix.Translation(-origin)
    for obj in objects:
        obj.matrix_world=transform@obj.matrix_world
    bpy.context.view_layer.update()
    select(objects)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    return {"yaw_degrees":yaw_deg,"measure":measure,"target_cm":target_cm,
            "uniform_scale_factor":ratio,"source_bottom_centre_after_yaw_m":list(origin),
            "scale_policy":"Uniform only; no anisotropic resizing or shape replacement",
            "origin_policy":"horizontal bounding centre and lowest source vertex; no automatic deletion of generated ground"}


def join_static(objects,asset_id):
    select(objects)
    if len(objects)>1: bpy.ops.object.join()
    obj=bpy.context.object
    obj.name=asset_id;obj.data.name=asset_id+"_TripoMesh"
    # All vertices have been baked into the desired space, so the single root is exactly zero.
    obj.location=(0,0,0);obj.rotation_euler=(0,0,0);obj.scale=(1,1,1)
    for other in list(bpy.context.scene.objects):
        if other!=obj:
            bpy.data.objects.remove(other,do_unlink=True)
    return obj


def setup_render(obj,device,frame=None):
    scene=bpy.context.scene
    scene.render.engine="CYCLES";scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.cycles.device="CPU";scene.render.threads_mode="FIXED";scene.render.threads=4
    if device=="HIP":
        preferences=bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type="HIP";preferences.get_devices()
        enabled=[]
        for item in preferences.devices:
            item.use=item.type=="HIP"
            if item.use: enabled.append(item.name)
        if not enabled: raise RuntimeError("HIP requested but unavailable")
        scene.cycles.device="GPU"
    scene.render.resolution_x=scene.render.resolution_y=1024
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG";scene.render.image_settings.color_mode="RGB"
    scene.world=bpy.data.worlds.new("TripoReviewWorld")
    scene.world.use_nodes=True
    background=scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value=(.20,.23,.27,1)
    background.inputs["Strength"].default_value=.35
    scene.view_settings.view_transform="AgX"
    low,high=bounds([obj]);centre=(low+high)*.5;span=max(high-low)
    if frame is not None: centre,span=frame
    for name,offset,energy in [("Key",(-2,-3,4),700),("Fill",(3,2,3),180)]:
        bpy.ops.object.light_add(type="AREA",location=centre+Vector(offset)*span)
        light=bpy.context.object;light.name="REVIEW_"+name
        light.data.energy=energy*span*span;light.data.shape="DISK";light.data.size=span*1.6
        light.rotation_euler=(centre-light.location).to_track_quat("-Z","Y").to_euler()
    bpy.ops.object.camera_add(location=centre+Vector((2,-3,1.6))*span)
    camera=bpy.context.object;camera.name="REVIEW_Camera";camera.data.type="ORTHO"
    camera.data.ortho_scale=span*1.55
    camera.rotation_euler=(centre-camera.location).to_track_quat("-Z","Y").to_euler()
    scene.camera=camera
    return camera,centre,span


def render_views(obj,directory,device,frame=None,neutral=False,include_left=False):
    directory.mkdir(parents=True,exist_ok=True)
    camera,centre,span=setup_render(obj,device,frame)
    if neutral:
        material=bpy.data.materials.new("REVIEW_NEUTRAL_ONLY")
        material.use_nodes=True
        shader=material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value=(.4,.4,.4,1)
        shader.inputs["Roughness"].default_value=.8
        shader.inputs["Metallic"].default_value=0
        # Render-layer override affects only this comparison, never the asset datablock/export.
        bpy.context.view_layer.material_override=material
    views=[("preview",(2,-3,1.6)),("front",(1,0,0)),("right",(0,1,0)),("back",(-1,0,0))]
    if include_left: views.append(("left",(0,-1,0)))
    for view,direction in views:
        camera.location=centre+Vector(direction)*span*2
        camera.rotation_euler=(centre-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.data.ortho_scale=span*(1.55 if view=="preview" else 1.25)
        bpy.context.scene.render.filepath=str(directory/(view+".png"))
        bpy.ops.render.render(write_still=True)


def render_comparison(asset_id,current_path,manifest_path,directory,device,neutral=False,include_left=False):
    previous=json.loads(manifest_path.read_text(encoding="utf-8"))
    entry=next((row for row in previous["assets"] if row["id"]==asset_id),None)
    if entry is None: raise ValueError("Comparison manifest does not contain "+asset_id)
    previous_path=ROOT/entry["file"]
    if not previous_path.is_file(): raise ValueError("Comparison source missing: "+str(previous_path))
    limits=[]
    for path in (previous_path,current_path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
        limits.append(bounds([o for o in bpy.context.scene.objects if o.type=="MESH"]))
    low=Vector([min(pair[0][axis] for pair in limits) for axis in range(3)])
    high=Vector([max(pair[1][axis] for pair in limits) for axis in range(3)])
    frame=((low+high)*.5,max(high-low))
    for name,path in (("before",previous_path),("after",current_path)):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
        objects=[o for o in bpy.context.scene.objects if o.type=="MESH"]
        select(objects)
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        obj=join_static(objects,asset_id)
        render_views(obj,directory/name,device,frame,neutral,include_left)
    return {"before_file":project_path(previous_path),"after_file":project_path(current_path),
            "before_sha256":sha256(previous_path),"after_sha256":sha256(current_path),
            "shared_camera_centre_m":list(frame[0]),"shared_span_m":frame[1],"size":[1024,1024],
            "views":["preview","front","right","back"]+(["left"] if include_left else []),"identical_camera_lighting_and_material_policy":True,
            "neutral_material_override":neutral,
            "note":("Render-only identical grey .4, roughness .8, metallic 0 override; source model materials unchanged" if neutral
                    else "Both source materials retained; no exposure or shader changes between versions")}


def export(obj,path):
    select([obj])
    bpy.ops.export_scene.gltf(filepath=str(path.with_suffix(".glb")),export_format="GLB",use_selection=True,
                              export_apply=False,export_yup=True,export_extras=True,export_image_format="AUTO",
                              export_animations=False)
    bpy.ops.export_scene.fbx(filepath=str(path.with_suffix(".fbx")),use_selection=True,object_types={"MESH"},
                             apply_unit_scale=True,apply_scale_options="FBX_SCALE_UNITS",axis_forward="X",axis_up="Z",
                             use_mesh_modifiers=False,bake_anim=False,path_mode="COPY",embed_textures=True,
                             use_custom_props=True)


def verify_roundtrip(path,expected_dimensions,expected_triangles,expected_material_count,expected_uv_layers):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects=[o for o in bpy.context.scene.objects if o.type=="MESH"]
    low,high=bounds(objects);dimensions=list((high-low)*100)
    geometry=geometry_report(objects);materials=material_report(objects)
    errors=[]
    if geometry["triangles"]!=expected_triangles: errors.append("triangle_count_changed")
    if len(materials)!=expected_material_count: errors.append("material_count_changed")
    if any(abs(a-b)>max(.02,b*.0001) for a,b in zip(dimensions,expected_dimensions)): errors.append("dimensions_changed")
    if expected_uv_layers and any(not row["uv_layers"] for row in geometry["meshes"]): errors.append("uvs_lost")
    if any(not image["size"][0] or not image["size"][1] for row in materials for image in row["images"]): errors.append("texture_unavailable")
    return {"pass":not errors,"errors":errors,"dimensions_cm":dimensions,"geometry":geometry,"materials":materials}


def prepare(item,args):
    aid=item["id"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",aid): raise ValueError("Invalid asset id")
    catalog=json.loads((ROOT/"RawAssets/Art/Tripo_v01/catalog.json").read_text(encoding="utf-8"))
    known={v["id"] for group in catalog.values() if isinstance(group,list) for v in group}
    if aid not in known: raise ValueError("Asset id is not in the project catalogue")
    source=Path(item["file"]).resolve()
    if source.suffix.lower()!=".glb" or not source.is_file(): raise ValueError("A real downloaded GLB file is required")
    default=TARGETS.get(aid)
    target=item.get("target_cm",args.target_cm or (default[1] if default else None))
    measure=item.get("measure",args.measure or (default[0] if default else None))
    if not target or not measure or target<=0: raise ValueError("Asset needs an explicit positive centimetre target and measure")
    yaw=float(item.get("yaw_deg",args.yaw_deg))
    source_hash=sha256(source)
    original_container=glb_container_report(source)
    fingerprint=hashlib.sha256((source_hash+json.dumps([target,measure,yaw])).encode()).hexdigest()[:12]
    out=args.output_root/aid/("h"+fingerprint)
    out.mkdir(parents=True,exist_ok=True)
    original=out/"source"/"original.glb";original.parent.mkdir(exist_ok=True)
    if source!=original: shutil.copy2(source,original)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system="METRIC";bpy.context.scene.unit_settings.scale_length=1
    bpy.ops.import_scene.gltf(filepath=str(source))  # Resolve any delivered sidecar textures beside the download.
    objects=[o for o in bpy.context.scene.objects if o.type=="MESH"]
    if any(o.data.shape_keys for o in objects) or any(o.type=="ARMATURE" for o in bpy.context.scene.objects):
        raise ValueError("This static environment pass will not collapse a rigged or morphing source")
    source_geometry=geometry_report(objects);source_materials=material_report(objects)
    source_uv=uv_signature(objects)
    source_low,source_high=bounds(objects)
    textures=extract_original_textures(objects,out/"textures")
    source_stage=item.get("source_stage",args.source_stage)
    if source_stage=="auto":
        source_stage="textured" if textures else "untextured_geometry"
    if source_stage=="textured" and not textures:
        raise ValueError("Source declared textured but no source images exist")
    normalization=normalize(objects,measure,float(target),yaw)
    obj=join_static(objects,aid)
    processed_geometry=geometry_report([obj]);processed_materials=material_report([obj])
    processed_uv=uv_signature([obj])
    if source_geometry["vertices"]!=processed_geometry["vertices"] or source_geometry["polygons"]!=processed_geometry["polygons"]:
        raise RuntimeError("Unexpected topology change during static join")
    if sorted(source_materials,key=lambda row:row["name"])!=sorted(processed_materials,key=lambda row:row["name"]):
        raise RuntimeError("Unexpected source material graph change during static join")
    common_layers=all(value==source_uv["layer_sets"][0] for value in source_uv["layer_sets"])
    if common_layers and source_uv["sha256"]!=processed_uv["sha256"]:
        raise RuntimeError("Unexpected UV coordinate change during static join")
    low,high=bounds([obj]);dimensions=[round(v*100,6) for v in high-low]
    if abs(low.z)>.00001: raise RuntimeError("Bottom origin normalization failed")
    obj["asset_origin"]="Tripo generated; uniform scale and static join only"
    obj["source_sha256"]=source_hash
    stem=out/aid
    export(obj,stem)
    processed_container=glb_container_report(stem.with_suffix(".glb"))
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(stem.with_suffix(".blend")))
    warnings=[]
    if not textures: warnings.append("untextured_source_no_image_textures; original_constant_or_vertex_material_preserved; not_final_art")
    if processed_geometry["triangles"]>2000: warnings.append("above_2k_small_environment_reference_budget_review_LODs_and_screen_cost")
    if any(row["coincident_seam_diagnostic"]["nonmanifold_edges_after_position_weld"] for row in source_geometry["meshes"]):
        warnings.append("source_has_open_or_nonmanifold_edges_even_after_coincident_seam_diagnostic; original_geometry_preserved")
    if any(row["degenerate_faces"] for row in source_geometry["meshes"]): warnings.append("source_has_degenerate_faces_preserved_for_review")
    if textures and any(not row["uv_layers"] for row in source_geometry["meshes"]): warnings.append("textured_source_has_mesh_without_UVs")
    original_image_hashes={row.get("sha256") for row in original_container["images"] if row.get("sha256")}
    exported_image_hashes={row.get("sha256") for row in processed_container["images"] if row.get("sha256")}
    if original_image_hashes-exported_image_hashes:
        warnings.append("GLB_export_reencoded_or_repacked_some_images_compare_PBR_render; exact_original_texture_bytes_are_preserved_in_textures_folder")
    report={"asset_id":aid,"status":"tripo_processed_pending_ue_material_and_gameplay_acceptance",
            "source":"real_downloaded_tripo_glb","source_file":project_path(source),"source_sha256":source_hash,
            "task_id":item.get("task_id",args.task_id),"blender_version":bpy.app.version_string,
            "source_stage":source_stage,"source_image_texture_count":len(textures),
            "source_dimensions_m":list(source_high-source_low),"normalization":normalization,
            "scale_target_basis":"Explicit game centimetre target; catalogue supplies identity and silhouette, not numeric environment dimensions",
            "source_geometry":source_geometry,"processed_geometry":processed_geometry,
            "source_glb_container":original_container,"processed_glb_container":processed_container,
            "all_original_image_bytes_embedded_unchanged":original_image_hashes<=exported_image_hashes,
            "uv_preservation":{"source":source_uv,"processed":processed_uv,"direct_comparison_applicable":common_layers,
                               "unchanged":source_uv["sha256"]==processed_uv["sha256"]},
            "source_materials":source_materials,"processed_materials":processed_materials,"original_textures":textures,
            "dimensions_cm":dimensions,"minimum_z_cm":low.z*100,"warnings":warnings,
            "material_policy":"Original image bytes extracted and preserved; source shader graph retained. GLB is primary PBR interchange; FBX material equivalence requires UE review.",
            "prohibited_operations_performed":[],"production_approved":False,
            "pending":["inspect generated ground disk or unwanted attached objects before cleanup","UE material/textures and instanced-static-mesh usage","both-team gameplay cameras","LODs and actual instance performance"]}
    if not args.no_render:
        render_views(obj,out,args.device,include_left=args.include_left)
        report["renders"]={"size":[1024,1024],"same_scale_orthographic_views":["front","right","back"]+(["left"] if args.include_left else []),"device":args.device}
    report["glb_roundtrip"]=verify_roundtrip(stem.with_suffix(".glb"),dimensions,processed_geometry["triangles"],len(processed_materials),any(row["uv_layers"] for row in processed_geometry["meshes"]))
    if args.comparison_manifest and not args.no_render:
        report["comparison"]=render_comparison(aid,stem.with_suffix(".glb"),args.comparison_manifest,out/"comparison",args.device,args.comparison_neutral,args.include_left)
    write_json(out/"inspection.json",report)
    if not report["glb_roundtrip"]["pass"]:
        raise RuntimeError("Processed GLB round trip failed; see "+str(out/"inspection.json"))
    entry={"id":aid,"role":"environment_mother","file":project_path(stem.with_suffix(".glb")),
           "fbx":project_path(stem.with_suffix(".fbx")),"blend":project_path(stem.with_suffix(".blend")),
           "type":"static_mesh","expected_dimensions_cm":dimensions,"import_scale":1,
           "import_materials":True,"combine_meshes":True,"source":"tripo_generated_processed_in_blender",
           "task_id":report["task_id"],"source_sha256":source_hash,"inspection":project_path(out/"inspection.json"),
           "source_stage":source_stage,
           "textures":textures,"material_requirements":["retain original Tripo base color, roughness, metallic, normal and alpha inputs","enable Used with Instanced Static Meshes on imported parent materials before runtime ISM use"],
           "production_approved":False}
    manifest_path=args.output_root/"manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version":1,"batch_id":args.batch_id,"units":"cm","source":"Tripo","assets":[]}
    manifest["assets"]=[old for old in manifest["assets"] if old["id"]!=aid]+[entry]
    manifest["assets"].sort(key=lambda row:row["id"])
    manifest["updated_at"]=datetime.now(timezone.utc).isoformat()
    manifest["status"]="tripo_assets_normalized_pending_unreal_acceptance"
    write_json(manifest_path,manifest)
    print("CIVWAR_TRIPO_PREPARED "+aid+" "+str(out),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset");parser.add_argument("--input");parser.add_argument("--task-id")
    parser.add_argument("--source-stage",choices=("auto","geometry_only","textured"),default="auto")
    parser.add_argument("--batch-spec",help="JSON object with assets [{id,file,task_id,target_cm?,measure?,yaw_deg?}]")
    parser.add_argument("--batch-id",default="tripo_environment_v01")
    parser.add_argument("--output-root",type=Path,default=OUTPUT_ROOT/"environment_v01")
    parser.add_argument("--target-cm",type=float);parser.add_argument("--measure",choices=("height","horizontal_max"))
    parser.add_argument("--yaw-deg",type=float,default=0)
    parser.add_argument("--no-render",action="store_true");parser.add_argument("--device",choices=("CPU","HIP"),default="CPU")
    parser.add_argument("--comparison-manifest",type=Path,help="Render before/after versions with identical camera and lighting")
    parser.add_argument("--comparison-neutral",action="store_true",help="Use identical render-only neutral grey for geometry comparison")
    parser.add_argument("--include-left",action="store_true",help="Render left in addition to preview/front/right/back")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    args.output_root=args.output_root.resolve()
    if OUTPUT_ROOT.resolve() not in args.output_root.parents and args.output_root!=OUTPUT_ROOT.resolve():
        raise ValueError("Output must remain within owned tripo_processed directory")
    if args.batch_spec:
        items=json.loads(Path(args.batch_spec).read_text(encoding="utf-8-sig"))["assets"]
    elif args.asset and args.input:
        items=[{"id":args.asset,"file":args.input}]
    else: parser.error("Provide --asset/--input or --batch-spec")
    for item in items: prepare(item,args)


if __name__=="__main__":
    main()
