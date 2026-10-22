"""Measure a real downloaded FBX bind frame; write an isolated source adapter."""
import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import build_mammoth_preview as common


def build(source, output):
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.threads_mode, scene.render.threads = "FIXED", 2
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False,
                            automatic_bone_orientation=False)
    rigs = [o for o in scene.objects if o.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("Expected one actual bound rig")
    rig = rigs[0]
    rig.animation_data_clear()
    common.reset(rig)
    bodies = [o for o in scene.objects if o.type == "MESH" and
              any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
    if not bodies:
        raise ValueError("No actually skinned geometry")
    bpy.context.view_layer.update()
    report = {"source": common.record(source), "coordinate_system": "Blender Z-up physical metres",
              "rig": rig.name, "rig_matrix": [list(r) for r in rig.matrix_world],
              "meshes": [], "bones": {}, "material_images": [],
              "production_approved": False}
    for body in bodies:
        points = common.world_vertices(body)
        body.data.calc_loop_triangles()
        report["meshes"].append({"name": body.name, "vertices": len(points),
                                 "triangles": len(body.data.loop_triangles),
                                 "minimum": points.min(axis=0).tolist(),
                                 "maximum": points.max(axis=0).tolist()})
        np.save(output/(body.name.replace(":", "_")+"_world_vertices.npy"), points)
    for b in rig.pose.bones:
        matrix = rig.matrix_world @ b.matrix
        report["bones"][b.name] = {"head": list(matrix.translation),
                                   "tail": list(rig.matrix_world @ b.tail),
                                   "matrix": [list(r) for r in matrix],
                                   "parent": b.parent.name if b.parent else None}
    for im in bpy.data.images:
        report["material_images"].append({"name": im.name, "size": list(im.size), "filepath": im.filepath})
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"source_bind.blend"))
    common.select([rig, *bodies])
    path = output/"source_bind.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                             export_animations=False, export_skins=True, export_yup=True)
    report["derived_bind_glb"] = common.record(path)
    common.save(output/"bind_inspection.json", report)
    print(json.dumps({"output": str(output), "meshes": report["meshes"], "bones": len(report["bones"])}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(sys.argv[sys.argv.index("--")+1:])
    build(a.source.resolve(), a.output.resolve())
