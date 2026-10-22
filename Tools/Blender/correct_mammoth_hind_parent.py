"""Change only the measured cross-hind parent, preserving every bind/surface byte."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mammoth_rig_transfer as transfer


BASE = transfer.BRANCH / "rig_transfer_01"
BASE_MODEL = BASE / "Mount_Mammoth_skin_candidate.glb"
BASE_SHA = "55c7db512eed89bef6028a2705b9efaeb70823280bb433333c9546da355b9c4e"
BASE_DIAGNOSTIC = BASE / "actual_diagnostic_01/diagnostic.json"
BASE_DIAGNOSTIC_SHA = "8d8a851142b6d00100bb074110912829a2cb53c2f9cca9f17a683861e3c654c6"
CHILD = "tripo::1_Left_Limb_1"
OLD_PARENT = "tripo::1_Left_Limb_0"
NEW_PARENT = "bone_21"


def reparent_preserving_world(document, child_name, parent_name):
    result = deepcopy(document)
    names = {node.get("name"): index for index, node in enumerate(result["nodes"])}
    if len(names) != len(result["nodes"]):
        raise ValueError("Node names must be unique")
    child, new_parent = names[child_name], names[parent_name]
    worlds, parents = transfer.world_matrices(result)
    old_parent = parents[child]
    ancestor = new_parent
    while ancestor in parents:
        if ancestor == child:
            raise ValueError("New parent is a descendant")
        ancestor = parents[ancestor]
    if ancestor == child or child == new_parent:
        raise ValueError("Reparent cycle")
    result["nodes"][old_parent]["children"].remove(child)
    if not result["nodes"][old_parent]["children"]:
        del result["nodes"][old_parent]["children"]
    result["nodes"][new_parent].setdefault("children", []).append(child)
    local = np.linalg.inv(worlds[new_parent]) @ worlds[child]
    for key in ("translation", "rotation", "scale"):
        result["nodes"][child].pop(key, None)
    result["nodes"][child]["matrix"] = local.T.reshape(-1).tolist()
    changed_worlds, _ = transfer.world_matrices(result)
    error = max(float(np.max(abs(worlds[index] - changed_worlds[index]))) for index in worlds)
    if error > 1e-12:
        raise ValueError("Reparent changed a world rest matrix")
    return result, {"child": child_name, "old_parent": result["nodes"][old_parent]["name"], "new_parent": parent_name, "max_world_rest_matrix_difference": error}


def prepare(output):
    for path, expected in ((BASE_MODEL, BASE_SHA), (BASE_DIAGNOSTIC, BASE_DIAGNOSTIC_SHA)):
        if transfer.audit_tool.texture.core.record(path)["sha256"] != expected:
            raise ValueError("Measured baseline changed")
    old_document, binary = transfer.read_container(BASE_MODEL)
    document, change = reparent_preserving_world(old_document, CHILD, NEW_PARENT)
    if change["old_parent"] != OLD_PARENT:
        raise ValueError("Only the measured cross-hind parent is authorized")
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "Mount_Mammoth_parent_only.glb"
    candidate.write_bytes(transfer.encode(document, binary))
    actual_document, actual_binary = transfer.read_container(candidate)
    if actual_binary != binary or actual_document["skins"] != old_document["skins"] or actual_document["meshes"] != old_document["meshes"]:
        raise ValueError("Parent-only candidate changed skin/mesh/binary")
    preparation = json.loads((BASE / "preparation.json").read_text(encoding="utf-8-sig"))
    preparation.update({"status": "parent_only_candidate_prepared_waiting_actual_comparison", "candidate": transfer.audit_tool.texture.core.record(candidate),
                        "parent_changes": 1, "parent_change": change, "all_inversebind_and_weight_bytes_unchanged": True,
                        "baseline": transfer.audit_tool.texture.core.record(BASE_MODEL), "baseline_actual_diagnostic": transfer.audit_tool.texture.core.record(BASE_DIAGNOSTIC)})
    transfer.audit_tool.texture.core.save(output / "preparation.json", preparation)
    old_spec = json.loads((BASE / "execution_spec.json").read_text(encoding="utf-8-sig"))
    dependencies = [Path(item["path"]) for item in old_spec["frozen_inputs"]]
    dependencies += [BASE_DIAGNOSTIC, candidate, output / "preparation.json", Path(__file__), Path(__file__).parent / "prepare_tripo_character.py"]
    spec = {"status": "frozen_root_authorized_single_parent_only_batch", "candidate": preparation["candidate"],
            "preparation": transfer.audit_tool.texture.core.record(output / "preparation.json"),
            "frozen_inputs": [transfer.audit_tool.texture.core.record(path) for path in dict.fromkeys(dependencies)],
            "diagnostic_poses": transfer.POSES, "parent_change": change,
            "restrictions": {"blender_threads": 2, "priority": "BelowNormal", "renders": 4, "render_size": 512, "samples": 8,
                             "paid_calls": 0, "ue_calls": 0, "model_reexports": 0, "weight_edits": 0, "buckle_or_tail_fixes": 0},
            "gates": {"full_surface_rest_and_non_target_bone_tolerance_m": transfer.TOLERANCE_M,
                      "binary_skin_weights_inversebind_source_material_bytes": "exact", "native_splits": 23},
            "render_scope": "Four actual front/back/side comparisons of the same8degree positive-Y hind command. Before left, parent-only right. Real bone endpoints become emission rods; copied PBR shaders are35%opaque diagnostic overlays, not PBR approval.",
            "command": {"executable": old_spec["command"]["executable"],
                        "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(output / "execution_spec.json"), "--output", str(output / "actual_diagnostic_01")]}}
    transfer.audit_tool.texture.core.save(output / "execution_spec.json", spec)
    print(json.dumps({"candidate": preparation["candidate"], "change": change, "spec": transfer.audit_tool.texture.core.record(output / "execution_spec.json")}))


def import_baseline():
    import bpy

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(BASE_MODEL), merge_vertices=False, disable_bone_shape=True)
    added = set(bpy.data.objects) - before
    meshes = [obj for obj in added if obj.type == "MESH"]
    rigs = [obj for obj in added if obj.type == "ARMATURE"]
    if len(meshes) != 1 or len(rigs) != 1:
        raise ValueError("Baseline object contract changed")
    return meshes[0], rigs[0]


def actual_weights(body):
    return [{body.vertex_groups[item.group].name: item.weight for item in vertex.groups} for vertex in body.data.vertices]


def compare_actual_rest(before_body, before_rig, after_body, after_rig):
    import bpy

    def evaluated(body):
        obj = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = obj.to_mesh()
        points = np.array([list(obj.matrix_world @ vertex.co) for vertex in mesh.vertices])
        obj.to_mesh_clear()
        return points

    bpy.context.view_layer.update()
    before, after = evaluated(before_body), evaluated(after_body)
    surface = float(np.linalg.norm(before - after, axis=1).max())
    rows = []
    for bone in before_rig.data.bones:
        actual = after_rig.data.bones[bone.name]
        head_error = float((before_rig.matrix_world @ bone.head_local - after_rig.matrix_world @ actual.head_local).length)
        tail_error = float((before_rig.matrix_world @ bone.tail_local - after_rig.matrix_world @ actual.tail_local).length)
        matrix_error = float(np.max(abs(np.array(before_rig.matrix_world @ bone.matrix_local) - np.array(after_rig.matrix_world @ actual.matrix_local))))
        rows.append({"bone": bone.name, "head_error_m": head_error, "tail_error_m": tail_error, "matrix_max_difference": matrix_error,
                     "before_parent": bone.parent.name if bone.parent else None, "after_parent": actual.parent.name if actual.parent else None})
    weights_equal = actual_weights(before_body) == actual_weights(after_body)
    changed = [row for row in rows if row["before_parent"] != row["after_parent"]]
    passed = surface < transfer.TOLERANCE_M and max(row["head_error_m"] for row in rows) < transfer.TOLERANCE_M and weights_equal
    if len(changed) != 1 or changed[0]["bone"] != CHILD or changed[0]["after_parent"] != NEW_PARENT:
        passed = False
    report = {"passed": passed, "full20598vertex_surface_error_m": surface, "actual_weight_rows_exact": weights_equal,
              "all33bones": rows, "actual_parent_changes": changed,
              "world_rest_bind_gate": "All33exactGLTFworldrestmatrices checked before import, entire inversebind binary unchanged; actual33joint heads and entire skinned surface must remain within3micrometres.",
              "display_tail_and_axis_note": "Blender5.2gltf vnode.py prettify_bones uses child-dependent pick_bone_length/temperance. Display tail/axis differences are explicitly reported, not substituted for physical GLTF bind matrices or hidden as zero."}
    if not passed:
        raise ValueError("Actual parent-only rest/weight gate failed: " + json.dumps(report))
    return report


def display_material(name, color):
    import bpy

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1)
    emission.inputs["Strength"].default_value = 1.0
    material.node_tree.links.new(emission.outputs[0], output.inputs[0])
    return material


def transparent_copy(body):
    for slot in body.material_slots:
        material = slot.material.copy()
        slot.material = material
        tree = material.node_tree
        output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL")
        surface = output.inputs["Surface"]
        shader = surface.links[0].from_socket
        tree.links.remove(surface.links[0])
        transparent = tree.nodes.new("ShaderNodeBsdfTransparent")
        mix = tree.nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = .35
        tree.links.new(transparent.outputs[0], mix.inputs[1])
        tree.links.new(shader, mix.inputs[2])
        tree.links.new(mix.outputs[0], surface)


def pose_hind(armature):
    import bpy
    from mathutils import Matrix, Quaternion, Vector

    bone = armature.pose.bones[OLD_PARENT]
    world = armature.matrix_world @ bone.matrix
    head = world.translation.copy()
    turn = Quaternion(Vector((0, 1, 0)), math.radians(8)).to_matrix().to_4x4()
    bone.matrix = armature.matrix_world.inverted() @ Matrix.Translation(head) @ turn @ Matrix.Translation(-head) @ world
    bpy.context.view_layer.update()


def render_comparisons(output, before_body, before_rig, after_body, after_rig):
    import bpy
    from mathutils import Vector
    import prepare_tripo_character as renderer

    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("MammothParentDiagnosticWorld")
    camera, _ = renderer.render_setup(samples=8)
    if scene.cycles.device != "GPU":
        raise ValueError("HIP unavailable; do not silently run heavy CPU render")
    scene.cycles.seed = 0
    orange = display_material("BeforeMeasuredRig", (1, .29, .035))
    cyan = display_material("AfterParentOnlyRig", (.025, .8, 1))
    highlighted = display_material("MeasuredNegativeYHindChain", (.93, .055, .18))
    labels = display_material("DiagnosticLabel", (.92, .95, 1))
    groups, all_bodies = [], [before_body, after_body]
    for prefix, body, rig, color in (("BEFORE", before_body, before_rig, orange), ("PARENT ONLY", after_body, after_rig, cyan)):
        pose_hind(rig)
        empty = bpy.data.objects.new(prefix, None)
        scene.collection.objects.link(empty)
        if body.parent != rig:
            body.parent = empty
        rig.parent = empty
        transparent_copy(body)
        bones = []
        for bone in rig.pose.bones:
            head, tail = rig.matrix_world @ bone.head, rig.matrix_world @ bone.tail
            curve = bpy.data.curves.new(prefix + "_" + bone.name, "CURVE")
            curve.dimensions = "3D"
            curve.bevel_depth = .009
            curve.bevel_resolution = 0
            spline = curve.splines.new("POLY")
            spline.points.add(1)
            spline.points[0].co = (*head, 1)
            spline.points[1].co = (*tail, 1)
            obj = bpy.data.objects.new(curve.name, curve)
            scene.collection.objects.link(obj)
            obj.parent = empty
            curve.materials.append(highlighted if bone.name in (CHILD, "tripo::1_Left_Limb_2", "tripo::1_Left_Limb_3") else color)
            bones.append({"bone": bone.name, "head_world_m": list(head), "tail_world_m": list(tail)})
        text = bpy.data.curves.new(prefix + "Label", "FONT")
        text.body = prefix
        text.align_x = "CENTER"
        text.size = .18
        text.materials.append(labels)
        label = bpy.data.objects.new(prefix + "Label", text)
        scene.collection.objects.link(label)
        groups.append((empty, label, bones))
    records = []
    for name, direction in (("front", (1, 0, 0)), ("back", (-1, 0, 0)), ("positive_y_side", (0, 1, 0)), ("negative_y_side", (0, -1, 0))):
        direction = Vector(direction)
        right = Vector((0, 0, 1)).cross(direction).normalized()
        target = Vector((0, 0, .83))
        for sign, (group, label, _) in zip((-1, 1), groups):
            group.location = right * (sign * 1.37)
            label.location = right * (sign * 1.37) + Vector((0, 0, 2.06))
            label.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
        bpy.context.view_layer.update()
        path = output / ("parent_comparison_" + name + ".png")
        renderer.render_view(path, all_bodies, direction, size=512, framing=5.5, target=target)
        records.append({"view": name, "image": transfer.audit_tool.texture.core.record(path), "camera_location": list(camera.location),
                        "ortho_scale": camera.data.ortho_scale, "left": "measured_original_parent", "right": "parent_only_candidate"})
    return {"images": records, "actual_pose": {"bone": OLD_PARENT, "world_axis": [0, 1, 0], "degrees": 8},
            "diagnostic_shader_override": "Copied PBR with35percentopacity; no source material/image edit. Bone rods occupy actual pose head/tail coordinates, no projection or invented poses.",
            "actual_bone_endpoints": {label: group[2] for label, group in zip(("before", "after"), groups)}}


def run(output, spec_path):
    import bpy

    transfer.diagnose(output, spec_path)
    corrected_body = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    corrected_rig = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    baseline_body, baseline_rig = import_baseline()
    rest = compare_actual_rest(baseline_body, baseline_rig, corrected_body, corrected_rig)
    report = {"status": "parent_only_actual_rest_passed_rendering", "process_id": __import__("os").getpid(), "rest": rest,
              "original_motion": transfer.audit_tool.texture.core.record(BASE_DIAGNOSTIC), "corrected_motion": transfer.audit_tool.texture.core.record(output / "diagnostic.json"),
              "weights_changed": False, "buckle_or_tail_fixes": False, "rig_approved": False, "production_approved": False}
    transfer.audit_tool.texture.core.save(output / "parent_comparison.json", report)
    report["render"] = render_comparisons(output, baseline_body, baseline_rig, corrected_body, corrected_rig)
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    for item in spec["frozen_inputs"]:
        transfer.audit_tool.texture.checked_record(item)
    report["status"] = "parent_only8pose_and4actual_comparisons_complete_pending_review"
    report["frozen_inputs_unchanged"] = True
    transfer.audit_tool.texture.core.save(output / "parent_comparison.json", report)
    print(json.dumps({"status": report["status"], "images": len(report["render"]["images"]), "rest_surface_m": rest["full20598vertex_surface_error_m"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "run"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare(transfer.fresh_output(args.output))
    elif args.spec:
        run(args.output.resolve(), args.spec.resolve())
    else:
        raise ValueError("Execution requires frozen spec")


if __name__ == "__main__":
    main()
