"""Freeze exact front-buckle cloth contact masks without applying weight changes."""
from __future__ import annotations

import argparse
from collections import defaultdict
import heapq
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_mammoth_accessory_weights as accessory
import prepare_mammoth_rig_transfer as transfer


REGIONS = transfer.BRANCH / "rig_weight_plan_01/exact_regions.json"
REGIONS_SHA = "7c74463827f3a510a477679694e9a8bfa0a37778ab4aa04345bcbf13e5466a9c"
RADIUS_M = .08


def geodesic_distances(adjacency, seeds, radius):
    distances = {int(index): 0.0 for index in seeds}
    queue = [(0.0, int(index)) for index in seeds]
    heapq.heapify(queue)
    while queue:
        distance, index = heapq.heappop(queue)
        if distance != distances[index]:
            continue
        for other, length in adjacency[index].items():
            proposed = distance + length
            if proposed <= radius and proposed < distances.get(other, float("inf")):
                distances[other] = proposed
                heapq.heappush(queue, (proposed, other))
    return distances


def transition_alpha(distance, radius):
    fraction = max(0., min(1., distance / radius))
    return 1 - fraction * fraction * (3 - 2 * fraction)


def blend_with_anchor(weights, anchor, alpha):
    if not 0 <= alpha <= 1:
        raise ValueError("Transition alpha outside0..1")
    result = {bone: float(weight) * (1 - alpha) for bone, weight in weights.items()}
    result[anchor] = result.get(anchor, 0) + alpha
    return {bone: weight for bone, weight in result.items() if weight > 0}


def prepare(output):
    for path, expected in ((accessory.MODEL, accessory.MODEL_SHA), (REGIONS, REGIONS_SHA)):
        if transfer.audit_tool.texture.core.record(path)["sha256"] != expected:
            raise ValueError("Frozen region input changed")
    if output.exists() or output.parent.resolve() != transfer.BRANCH.resolve() or not output.name.startswith("rig_weight_masks_plan_"):
        raise ValueError("Use a fresh owned mask-plan directory")
    document, binary = transfer.read_container(accessory.MODEL)
    arrays = transfer.source_arrays(document, binary)
    regions = json.loads(REGIONS.read_text(encoding="utf-8-sig"))
    native_map, split_pairs, native = transfer.audit_tool.texture.native_identity(arrays)
    positions = arrays["POSITION"] @ transfer.BASIS.T
    native_positions = {native_map[index]: positions[index] for index in native_map}
    excluded = {face for patch in native["plan"]["accessory_patches"] for face in patch["face_indices"]}
    adjacency = defaultdict(dict)
    outside_triangles = []
    for face, triangle in enumerate(arrays["indices"]):
        if native["source_triangle_native_polygons"][face] in excluded:
            continue
        outside_triangles.append(face)
        vertices = [native_map[int(index)] for index in triangle]
        for first, second in zip(vertices, vertices[1:] + vertices[:1]):
            length = float(np.linalg.norm(native_positions[first] - native_positions[second]))
            adjacency[first][second] = length
            adjacency[second][first] = length
    joint_names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    actual_weights = [{int(joint): float(weight) for joint, weight in zip(joints, weights) if weight > 0}
                      for joints, weights in zip(arrays["JOINTS_0"], arrays["WEIGHTS_0"])]
    anchor = joint_names.index("tripo::Spine_2")
    inverse = transfer.accessor(document, binary, document["skins"][0]["inverseBindMatrices"])
    plans = []
    for patch in regions["patches"]:
        if patch["native_patch"] not in (5857, 8674):
            continue
        metal = set(patch["source_render_vertices"])
        distances = geodesic_distances(adjacency, patch["surrounding_native_vertices"], .12)
        active_native = {index: distance for index, distance in distances.items() if distance <= RADIUS_M}
        transition = {index: transition_alpha(active_native[native_map[index]], RADIUS_M) for index in native_map if native_map[index] in active_native and index not in metal}
        seeds = {index for index in transition if active_native[native_map[index]] == 0}
        unchanged_duplicates = defaultdict(list)
        for index in transition:
            unchanged_duplicates[native_map[index]].append(actual_weights[index])
        if any(any(row != rows[0] for row in rows) for rows in unchanged_duplicates.values()):
            raise ValueError("Same native identity has inconsistent actual weights; do not average")
        hypothetical = [dict(weights) for weights in actual_weights]
        for index in metal:
            hypothetical[index] = {anchor: 1.0}
        for index, alpha in transition.items():
            hypothetical[index] = blend_with_anchor(actual_weights[index], anchor, alpha)
        changed = sorted(metal | set(transition))
        max_influences = max(len(hypothetical[index]) for index in changed)
        simulated_joints = np.zeros((len(positions), max(4, max_influences)), dtype=int)
        simulated_weights = np.zeros_like(simulated_joints, dtype=float)
        for index, weights in enumerate(hypothetical):
            for column, (joint, weight) in enumerate(weights.items()):
                simulated_joints[index, column] = joint
                simulated_weights[index, column] = weight
        affected_faces = [face for face in outside_triangles if any(int(index) in transition for index in arrays["indices"][face])]
        affected_edges = sorted({tuple(sorted((int(first), int(second)))) for face in affected_faces for first, second in zip(arrays["indices"][face], np.roll(arrays["indices"][face], -1))})
        original_triangles = arrays["POSITION"][arrays["indices"][affected_faces]].astype(float)
        original_cross = np.cross(original_triangles[:, 1] - original_triangles[:, 0], original_triangles[:, 2] - original_triangles[:, 0])
        original_area = np.linalg.norm(original_cross, axis=1)
        simulations = []
        commands = [command for command in transfer.POSES if command["name"].startswith("shoulder_")]
        for command in commands:
            matrices = accessory.pose_matrices(document, command) @ inverse
            current = transfer.skin_positions(arrays["POSITION"], arrays["JOINTS_0"], arrays["WEIGHTS_0"], matrices)
            posed = transfer.skin_positions(arrays["POSITION"], simulated_joints, simulated_weights, matrices)
            seam_gap = max(np.linalg.norm(posed[first] - posed[second]) for first, second in patch["coincident_patch_to_surrounding_pairs"])
            new_triangles = posed[arrays["indices"][affected_faces]]
            new_cross = np.cross(new_triangles[:, 1] - new_triangles[:, 0], new_triangles[:, 2] - new_triangles[:, 0])
            area_ratio = np.linalg.norm(new_cross, axis=1) / original_area
            edge_strain = [abs(np.linalg.norm(posed[first] - posed[second]) / np.linalg.norm(arrays["POSITION"][first] - arrays["POSITION"][second]) - 1) for first, second in affected_edges]
            current_strain = [abs(np.linalg.norm(current[first] - current[second]) / np.linalg.norm(arrays["POSITION"][first] - arrays["POSITION"][second]) - 1) for first, second in affected_edges]
            simulations.append({"pose": command["name"], "seam_gap_max_m": float(seam_gap), "transition_max_edge_strain": float(max(edge_strain)),
                                "current_same_region_max_edge_strain": float(max(current_strain)),
                                "transition_area_ratio_min": float(min(area_ratio)), "transition_area_ratio_max": float(max(area_ratio)),
                                "rest_normal_dot_negative_faces": int(np.count_nonzero(np.sum(original_cross * new_cross, axis=1) < 0)),
                                "scope": "PureGLTFhypothetical data only; not actual Blender or weight approval."})
        points = positions[sorted(metal)]
        plans.append({"native_patch": patch["native_patch"], "metal_render_vertices": sorted(metal), "contact_render_vertices": sorted(seeds),
                      "contact_native_vertices": patch["surrounding_native_vertices"], "transition_native_geodesic_distances_m": active_native,
                      "outer12cm_native_geodesic_distances_m": distances, "transition_render_alpha": transition, "transition_affected_triangles": affected_faces,
                      "native_render_weight_identity_exact": True, "proposed_anchor_not_applied": "tripo::Spine_2", "hypothetical_max_influences": max_influences,
                      "hypothetical_seam_and_strain": simulations,
                      "camera": {"target": ((points.min(axis=0) + points.max(axis=0)) * .5).tolist(),
                                 "direction": [.12, -1 if patch["native_patch"] == 5857 else 1, .12], "framing_m": .50},
                      "actual_pose": next(command for command in transfer.POSES if command["name"] == ("shoulder_negative_y" if patch["native_patch"] == 5857 else "shoulder_positive_y"))})
    report = {"status": "front_buckle_color_masks_prepared_weights_not_changed", "model": transfer.audit_tool.texture.core.record(accessory.MODEL),
              "regions": plans, "formula": "alpha(d)=1-smoothstep(clamp(d/0.08m,0,1)); proposed weights=(1-alpha)*original+alpha*Spine_2. Entire isolated metal patch would use Spine_2=1. Contactd0 uses identical rigid row, retaining coincident seam under every rigid bone transform.",
              "topology_scope": "Native identity merges only originalUV/normalduplicate indices of the same cleaned-native vertex. Dijkstra traverses actual non-metal triangle edges; no positional weld or crossing disconnected23splits.",
              "hard_limits": ["No actual weight changes in this batch", "Metal faces excluded from cloth graph", "Native identity conflicts rejected, never averaged", "Outer region beyond8cm keeps original weights exactly in the future proposal", "Do not truncate if more than4influences; report instead", "Mask may include fur/body; semantic boundary requires actual local images before applying any weights", "Shoulder-only pure simulation is not a full motion/strain approval"],
              "tail_scope": "Excluded from this batch; separate tail-foot plan remains unchanged.", "source_edits": 0, "weight_edits": 0, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    transfer.audit_tool.texture.core.save(output / "region_plan.json", report)
    dependencies = [accessory.MODEL, REGIONS, transfer.MAPPING, output / "region_plan.json", Path(__file__), Path(accessory.__file__), Path(transfer.__file__),
                    Path(transfer.audit_tool.__file__), Path(transfer.audit_tool.texture.__file__), Path(transfer.audit_tool.rig_core.__file__),
                    Path(transfer.audit_tool.texture.core.__file__), Path(__file__).parent / "prepare_tripo_character.py"]
    result = output / "actual_masks_01"
    spec = {"status": "frozen_prepared_waiting_root_single_heavy_lease", "model": report["model"], "region_plan": transfer.audit_tool.texture.core.record(output / "region_plan.json"),
            "frozen_inputs": [transfer.audit_tool.texture.core.record(path) for path in dependencies], "paid_calls": 0, "model_exports": 0, "weight_changes": 0,
            "render": {"count": 4, "size": 512, "samples": 8, "threads": 2, "priority": "BelowNormal", "views": "5857rest/actualshoulder8degrees and8674rest/actualshoulder8degrees", "legend": {"amber": "isolatedmetal", "magenta": "exactclothcontactseeds", "cyan": "0..8cmclothtransition", "blue": "8..12cmouterdiagnosticring", "gray": "unchangedoutside"}},
            "command": {"executable": "C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe",
                        "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "render", "--spec", str(output / "execution_spec.json"), "--output", str(result)]}}
    transfer.audit_tool.texture.core.save(output / "execution_spec.json", spec)
    print(json.dumps({"spec": transfer.audit_tool.texture.core.record(output / "execution_spec.json"), "regions": [{"patch": row["native_patch"], "transition_native": len(row["transition_native_geodesic_distances_m"]), "transition_render": len(row["transition_render_alpha"]), "max_influences": row["hypothetical_max_influences"], "simulated": row["hypothetical_seam_and_strain"]} for row in plans]}))


def render(output, spec_path):
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    import prepare_tripo_character as renderer

    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    for record in spec["frozen_inputs"]:
        transfer.audit_tool.texture.checked_record(record)
    if output.exists() or output.resolve() != spec_path.parent.resolve() / "actual_masks_01":
        raise ValueError("Expected fresh frozen mask output")
    plan = json.loads(Path(spec["region_plan"]["path"]).read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=spec["model"]["path"], merge_vertices=False, disable_bone_shape=True)
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(bodies) != 1 or len(rigs) != 1:
        raise ValueError("Frozen object contract changed")
    body, rig = bodies[0], rigs[0]
    bpy.context.view_layer.update()
    before = transfer.audit_tool.rig_core.mesh_snapshot(body)
    original_weights = [[(item.group, item.weight) for item in vertex.groups] for vertex in body.data.vertices]
    original_pose = {bone.name: bone.matrix_basis.copy() for bone in rig.pose.bones}
    source = transfer.audit_tool.source_snapshot(transfer.source_arrays(*transfer.read_container(transfer.SOURCE)))
    if len(body.data.vertices) != 20598 or np.linalg.norm(before["positions"] - source["positions"], axis=1).max() > transfer.TOLERANCE_M:
        raise ValueError("Actual frozen source surface mismatch")
    body.data = body.data.copy()
    body.data.materials.clear()
    material = bpy.data.materials.new("TemporaryPartitionMaskNotPBR")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    principled = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    principled.inputs["Roughness"].default_value = .85
    color = nodes.new("ShaderNodeVertexColor")
    color.layer_name = "ExactWeightPartition"
    material.node_tree.links.new(color.outputs["Color"], principled.inputs["Base Color"])
    body.data.materials.append(material)
    attribute = body.data.color_attributes.new(name=color.layer_name, type="FLOAT_COLOR", domain="CORNER")
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("MammothMaskWorld")
    renderer.render_setup(samples=8)
    if scene.cycles.device != "GPU":
        raise ValueError("HIP required; no silent CPU render")
    images = []
    for region in plan["regions"]:
        metal = set(region["metal_render_vertices"])
        contact = set(region["contact_render_vertices"])
        transition = {int(key): value for key, value in region["transition_render_alpha"].items()}
        native_map = json.loads(transfer.MAPPING.read_text(encoding="utf-8-sig"))["source_render_vertex_to_native_vertex"]
        outer = {int(key) for key in region["outer12cm_native_geodesic_distances_m"]}
        for loop in body.data.loops:
            index = loop.vertex_index
            if index in metal:
                rgba = (1, .45, .015, 1)
            elif index in contact:
                rgba = (1, .015, .55, 1)
            elif index in transition:
                rgba = (.015, .75, .9, 1)
            elif int(native_map[str(index)]) in outer:
                rgba = (.035, .15, .8, 1)
            else:
                rgba = (.2, .2, .2, 1)
            attribute.data[loop.index].color = rgba
        for mode in ("rest", "current_shoulder8"):
            for bone in rig.pose.bones:
                bone.matrix_basis = original_pose[bone.name].copy()
            bpy.context.view_layer.update()
            if mode != "rest":
                command = region["actual_pose"]
                bone = rig.pose.bones[command["bone"]]
                world = rig.matrix_world @ bone.matrix
                head = world.translation.copy()
                turn = Quaternion(Vector(command["axis_world"]), math.radians(command["degrees"])).to_matrix().to_4x4()
                bone.matrix = rig.matrix_world.inverted() @ Matrix.Translation(head) @ turn @ Matrix.Translation(-head) @ world
                bpy.context.view_layer.update()
            path = output / ("buckle_" + str(region["native_patch"]) + "_" + mode + ".png")
            renderer.render_view(path, [body], region["camera"]["direction"], size=512, framing=region["camera"]["framing_m"], target=region["camera"]["target"])
            images.append({"patch": region["native_patch"], "pose": mode, "image": transfer.audit_tool.texture.core.record(path)})
    for bone in rig.pose.bones:
        bone.matrix_basis = original_pose[bone.name].copy()
    bpy.context.view_layer.update()
    after = transfer.audit_tool.rig_core.mesh_snapshot(body)
    actual_weights = [[(item.group, item.weight) for item in vertex.groups] for vertex in body.data.vertices]
    checks = {key: np.array_equal(before[key], after[key]) for key in ("positions", "triangles", "uv", "normals")}
    checks["weights_exact"] = actual_weights == original_weights
    if not all(checks.values()):
        raise ValueError("Diagnostic masks changed actual surface or weights")
    for record in spec["frozen_inputs"]:
        transfer.audit_tool.texture.checked_record(record)
    transfer.audit_tool.texture.core.save(output / "mask_review.json", {"status": "four_actual_masks_complete_pending_semantic_review_no_weights_changed", "process_id": __import__("os").getpid(),
            "checks": checks, "images": images, "render_legend": spec["render"]["legend"], "model_exports": 0, "weight_changes": 0, "production_approved": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "render"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare(args.output.resolve())
    elif args.spec:
        render(args.output.resolve(), args.spec.resolve())
    else:
        raise ValueError("Frozen spec required")


if __name__ == "__main__":
    main()
