"""Crop the baked dark rim from a real terrain tile, retaining its original PBR."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


def record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trim-cm", type=float, default=45)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    source = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if source["asset_id"] != "Env_BattlefieldTile" or not 0 < args.trim_cm < 90:
        raise ValueError("Expected the profiled battlefield tile and a narrow edge crop")
    original_blend = source["exports"]["blend"]
    if record(original_blend["path"])["sha256"] != original_blend["sha256"]:
        raise ValueError("Prepared source changed")
    args.output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=original_blend["path"])
    mesh = bpy.data.objects["SM_Env_BattlefieldTile"]
    if mesh.matrix_world != Matrix.Identity(4):
        raise ValueError("Expected baked identity transform")
    half = source["dimensions_cm"][0] / 200
    cut = half - args.trim_cm / 100
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    for sign in (-1, 1):
        bmesh.ops.bisect_plane(
            bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            dist=1e-7, plane_co=Vector((sign * cut, 0, 0)),
            plane_no=Vector((sign, 0, 0)), clear_outer=True, clear_inner=False)
    # Keep the established 3000 cm footprint and runtime placement. Only the
    # 3% rim is removed; retained geometry and UVs receive a 1.031x X fit.
    for vertex in bm.verts:
        vertex.co.x *= half / cut
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    mesh.data.calc_loop_triangles()
    points = [v.co for v in mesh.data.vertices]
    low = [min(p[i] for p in points) * 100 for i in range(3)]
    high = [max(p[i] for p in points) * 100 for i in range(3)]
    if abs(low[0] + half * 100) > .01 or abs(high[0] - half * 100) > .01:
        raise ValueError("Crop did not produce the expected rectangular end planes")
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    fbx = args.output / (mesh.name + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=str(fbx), use_selection=True, object_types={"MESH"},
        apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="X", axis_up="Z", use_mesh_modifiers=False,
        bake_anim=False, path_mode="STRIP", embed_textures=False)
    glb = args.output / (mesh.name + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_selection=True,
        export_animations=False, export_yup=True, export_apply=False)
    blend = args.output / "Env_BattlefieldTile.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    result = copy.deepcopy(source)
    result.update(
        status="static_prepared_pending_unreal", tool=record(Path(__file__)),
        exports={"fbx": record(fbx), "glb": record(glb), "blend": record(blend)},
        triangles=len(mesh.data.loop_triangles),
        dimensions_cm=[high[i] - low[i] for i in range(3)],
        bounds_cm={"minimum": [low[0], -high[1], low[2]],
                   "maximum": [high[0], -low[1], high[2]]},
        seam_crop={"prepared_source": record(args.manifest),
                   "trim_each_end_cm": args.trim_cm, "x_refit": half / cut,
                   "uvs": "Original retained faces; split edge UVs interpolated by bmesh",
                   "textures": "Original material texture files reused byte-for-byte",
                   "runtime": "Alternate reflected static components; positive/negative primitives separate"})
    (args.output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "triangles": result["triangles"],
                      "dimensions_cm": result["dimensions_cm"]}))


if __name__ == "__main__":
    main()
