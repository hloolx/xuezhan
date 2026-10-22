"""Headless weapon asset checks, including a real GLB import round trip.

blender --background --python Tools/Blender/inspect_asset.py -- --all
This validates authored props, not body fit, animation, or gameplay integration.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"RawAssets/Art/Tripo_v01/weapons"


def inspect(asset_dir):
    contract=json.loads((asset_dir/"interface.json").read_text(encoding="utf-8"))
    asset_id=contract["asset_id"]
    bpy.ops.wm.open_mainfile(filepath=str(asset_dir/(asset_id+".blend")))
    meshes=[o for o in bpy.context.scene.objects if o.type=="MESH" and o.get("civwar_part")]
    problems=[]
    mesh_reports=[]
    for obj in meshes:
        mesh=obj.data
        mesh.calc_loop_triangles()
        bm=bmesh.new()
        bm.from_mesh(mesh)
        boundary=sum(e.is_boundary for e in bm.edges)
        nonmanifold=sum(not e.is_manifold for e in bm.edges)
        zero_area=sum(f.calc_area()<1e-10 for f in bm.faces)
        volume=bm.calc_volume(signed=True)
        bm.free()
        report={"name":obj.name,"vertices":len(mesh.vertices),"triangles":len(mesh.loop_triangles),"boundary_edges":boundary,"nonmanifold_edges":nonmanifold,"degenerate_faces":zero_area,"volume_m3":volume,"shape_keys":list(mesh.shape_keys.key_blocks.keys()) if mesh.shape_keys else []}
        mesh_reports.append(report)
        if nonmanifold or zero_area:
            problems.append(f"{obj.name}: nonmanifold={nonmanifold}, degenerate={zero_area}")
        if volume<=0:
            problems.append(f"{obj.name}: non-positive closed volume {volume}")
        if any(not math.isfinite(c) for v in mesh.vertices for c in v.co):
            problems.append(f"{obj.name}: non-finite vertex")
        if mesh.shape_keys:
            basis=mesh.shape_keys.key_blocks["Basis"]
            report["shape_key_max_deltas_m"]={}
            for key in mesh.shape_keys.key_blocks:
                if key.name=="Basis": continue
                delta=max((a.co-b.co).length for a,b in zip(key.data,basis.data))
                report["shape_key_max_deltas_m"][key.name]=delta
                if delta<.01:
                    problems.append(f"{obj.name}: deformation Basis collapsed into {key.name}")
                if key.value!=0:
                    problems.append(f"{obj.name}: unexpected nonzero default morph {key.name}")
            if asset_id=="Weapon_Sling" and obj.name.startswith("cord_"):
                end=sum((v.co for v in basis.data[-8:]),Vector())/8
                end_world=obj.matrix_world@end
                pouch=bpy.context.scene.objects["sling_pouch"].matrix_world.translation
                if (end_world-pouch).length>.10 or abs(end_world.x-pouch.x)<.06:
                    problems.append(f"{obj.name}: sling cord disconnected from pouch in rest pose")
    missing=[name for name in contract["anchors"] if name not in bpy.context.scene.objects]
    if missing: problems.append("Missing source anchors: "+str(missing))
    source_triangles=sum(r["triangles"] for r in mesh_reports)
    if source_triangles>10000: problems.append("Prototype exceeds 10k source triangles")
    # Actual exported GLB loading confirms the files are parseable and their scale is preserved.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(asset_dir/(asset_id+".glb")))
    bpy.context.view_layer.update()
    imported=[o for o in bpy.context.scene.objects if o.type=="MESH"]
    points=[o.matrix_world@Vector(c) for o in imported for c in o.bound_box]
    low=[min(p[i] for p in points) for i in range(3)]
    high=[max(p[i] for p in points) for i in range(3)]
    dims=[high[i]-low[i] for i in range(3)]
    expected=contract["dimensions_m"]
    # Bevel modifiers are exported for ordinary meshes; tolerate the bevel's small bound variation.
    if any(abs(a-b)>max(.008,b*.015) for a,b in zip(dims,expected)):
        problems.append(f"GLB dimensions changed: {dims}, expected {expected}")
    glb_missing=[name for name in contract["anchors"] if name not in bpy.context.scene.objects]
    if glb_missing: problems.append("Missing GLB anchors: "+str(glb_missing))
    glb_triangles=0
    for o in imported:
        o.data.calc_loop_triangles()
        glb_triangles+=len(o.data.loop_triangles)
    glb_controls={o.name: list(o.data.shape_keys.key_blocks.keys()) for o in imported if o.data.shape_keys}
    for control in contract["deformation_controls"]:
        if any(key not in glb_controls.get(control["object"],[]) for key in control["keys"]):
            problems.append("Missing GLB deformation control: "+control["object"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(asset_dir/(asset_id+".fbx")),use_anim=False)
    bpy.context.view_layer.update()
    fbx_meshes=[o for o in bpy.context.scene.objects if o.type=="MESH"]
    fbx_points=[o.matrix_world@Vector(c) for o in fbx_meshes for c in o.bound_box]
    fbx_dims=[max(p[i] for p in fbx_points)-min(p[i] for p in fbx_points) for i in range(3)]
    fbx_missing=[name for name in contract["anchors"] if name not in bpy.context.scene.objects]
    fbx_scale_ok=all(abs(a-b)<=max(.008,b*.015) for a,b in zip(fbx_dims,expected))
    if not fbx_scale_ok: problems.append(f"FBX dimensions changed: {fbx_dims}, expected {expected}")
    if fbx_missing: problems.append("Missing FBX anchors: "+str(fbx_missing))
    fbx_controls={o.name: list(o.data.shape_keys.key_blocks.keys()) for o in fbx_meshes if o.data.shape_keys}
    for control in contract["deformation_controls"]:
        if any(key not in fbx_controls.get(control["object"],[]) for key in control["keys"]):
            problems.append("Missing FBX deformation control: "+control["object"])
    result={"asset_id":asset_id,"blender":bpy.app.version_string,"source_triangles":source_triangles,
            "exported_triangles":glb_triangles,"mesh_count":len(meshes),"anchor_count":len(contract["anchors"]),
            "glb_import_dimensions_m":dims,"glb_roundtrip_ok":not glb_missing and not any("GLB dimensions" in p for p in problems),
            "fbx_import_dimensions_m":fbx_dims,"fbx_roundtrip_ok":not fbx_missing and fbx_scale_ok,
            "exported_deformation_controls":{"glb":glb_controls,"fbx":fbx_controls},
            "problems":problems,"pass":not problems,"checks":"closed source meshes, finite coordinates, non-degenerate faces, catalogue interface anchors, GLB import and bounding scale",
            "not_checked":["character fingers / arm IK","body or shield clearance","UE FBX orientation","server timing","production topology / texture polish"],"meshes":mesh_reports}
    (asset_dir/"inspection.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("CIVWAR_INSPECT "+asset_id+" "+("PASS" if result["pass"] else "FAIL"),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--all",action="store_true")
    parser.add_argument("--asset",action="append")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    paths=sorted(p.parent for p in OUT.glob("*/interface.json")) if args.all else [OUT/a for a in (args.asset or ["Weapon_StoneAxe","Weapon_Rifle"])]
    results=[inspect(path) for path in paths]
    summary={"assets":len(results),"passed":sum(r["pass"] for r in results),"failed":[r["asset_id"] for r in results if not r["pass"]],"total_exported_triangles":sum(r["exported_triangles"] for r in results),"reports":[{k:r[k] for k in ("asset_id","pass","source_triangles","exported_triangles","glb_roundtrip_ok","problems")} for r in results]}
    (OUT/"inspection_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    if summary["failed"]:
        raise RuntimeError("Asset validation failed: "+", ".join(summary["failed"]))


if __name__=="__main__":
    main()
