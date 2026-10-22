"""Read-only instrumentation of exact Mammoth imports, without rendering or mesh edits."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mammoth_follower_visual as visual


FOLDER = visual.transfer.BRANCH / "rig_follower_visual_01"
ORIGINAL_SPEC = FOLDER / "execution_spec.json"
ORIGINAL_SPEC_SHA = "e4c518b767d9143a6a68e2dcd2329b23992563269a95d9f925130fab690d30a0"
IMPORTER = Path("C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/5.2/scripts/addons_core/io_scene_gltf2/blender/imp/mesh.py")


def vector_difference(before, after):
    before, after = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    if before.shape != after.shape or before.ndim != 2 or before.shape[1] != 3:
        raise ValueError("Comparable three-component rows required")
    if not np.all(np.isfinite(before)) or not np.all(np.isfinite(after)):
        raise ValueError("Non-finite normal")
    magnitude = np.linalg.norm(after - before, axis=1)
    angles = np.degrees(np.arctan2(np.linalg.norm(np.cross(before, after), axis=1), np.sum(before * after, axis=1)))
    worst = np.argsort(-magnitude)[:20]
    return {"rows": len(before), "exact_rows": int(np.count_nonzero(np.all(before == after, axis=1))),
            "maximum_component_difference": float(np.max(abs(after - before))), "maximum_vector_difference": float(max(magnitude)),
            "maximum_angle_degrees": float(max(angles)), "worst_vector_index": int(np.argmax(magnitude)), "worst_angle_index": int(np.argmax(angles)),
            "top_rows": [{"index": int(index), "before": before[index].tolist(), "after": after[index].tolist(), "vector_difference": float(magnitude[index]), "angle_degrees": float(angles[index])} for index in worst]}, magnitude


def encoded_normals(mesh):
    attribute = mesh.attributes.get("custom_normal")
    if attribute is None or not attribute.data:
        raise ValueError("Encoded custom-normal attribute missing")
    properties = [prop.identifier for prop in attribute.data[0].bl_rna.properties if prop.type == "INT" and prop.array_length == 2 and not prop.is_readonly]
    if len(properties) != 1:
        raise ValueError("Cannot identify encoded custom-normal pair")
    return np.array([list(getattr(item, properties[0])) for item in attribute.data], dtype=int)


def prepare():
    if visual.core.record(ORIGINAL_SPEC)["sha256"] != ORIGINAL_SPEC_SHA:
        raise ValueError("Frozen failed visual specification changed")
    original = visual.read_json(ORIGINAL_SPEC)
    for record in original["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    path = FOLDER / "normal_probe_02_spec.json"
    if path.exists() or (FOLDER / "normal_probe_02").exists():
        raise FileExistsError("Preserve earlier normal-probe evidence")
    inputs = original["frozen_inputs"] + [visual.core.record(ORIGINAL_SPEC), visual.core.record(Path(__file__)), visual.core.record(IMPORTER), visual.core.record(IMPORTER.with_name("vnode.py"))]
    spec = {"status": "frozen_readonly_normal_probe", "root_authorization": "Root authorized one short independent zero-image read-only normal probe after PID75200 failed; no modification of source, candidate, earlier script, gate or report",
            "original_spec": visual.core.record(ORIGINAL_SPEC), "frozen_inputs": inputs,
            "scope": ["Exact authored GLB attributes", "Importer float32 bind-pose skin input and output", "Static raw corner vectors and encoded custom-normal pairs", "Static world-normalized snapshot", "Evaluated Armature rest corner vectors"],
            "restrictions": {"threads": 2, "priority": "BelowNormal", "renders": 0, "model_exports": 0, "mesh_or_normal_writes": 0, "paid_calls": 0, "UE_calls": 0},
            "command": {"executable": original["command"]["executable"], "arguments": ["--background", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--mode", "run", "--spec", str(path)]}}
    visual.core.save(path, spec)
    print(json.dumps(visual.core.record(path)))


def run(spec_path):
    import bpy
    spec = visual.read_json(spec_path)
    for record in spec["frozen_inputs"]:
        visual.transfer.audit_tool.texture.checked_record(record)
    output = FOLDER / "normal_probe_02"
    output.mkdir(exist_ok=False)
    original = visual.read_json(spec["original_spec"]["path"])
    report = {"status": "started_readonly", "process_id": __import__("os").getpid(), "renders": 0, "source_or_candidate_edits": 0, "previous_failure_reclassified": False}
    captures = []
    importer = importlib.import_module("io_scene_gltf2.blender.imp.mesh")
    actual_skin = importer.skin_into_bind_pose

    def observe_skin(*arguments, **keywords):
        bound = inspect.signature(actual_skin).bind(*arguments, **keywords).arguments
        normals, positions = bound["vert_normals"], bound["locs"][0]
        gltf, skin_index = bound["gltf"], bound["skin_idx"]
        skin = gltf.data.skins[skin_index]
        raw_inverse = importer.BinaryData.get_data_from_accessor(gltf, skin.inverse_bind_matrices)
        joint_matrices = np.array([gltf.vnodes[joint].bind_arma_mat @ gltf.matrix_gltf_to_blender(inverse) for joint, inverse in zip(skin.joints, raw_inverse)], dtype=np.float32)
        capture = {"normal_input": normals.copy(), "position_input": positions.copy(), "joint_matrices": joint_matrices}
        result = actual_skin(*arguments, **keywords)
        capture.update({"normal_output": normals.copy(), "position_output": positions.copy()})
        captures.append(capture)
        return result

    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        importer.skin_into_bind_pose = observe_skin
        before_body, before_rig = visual.import_rig(original["baseline"]["path"], 33)
        after_body, after_rig = visual.import_rig(original["candidate"]["path"], 35)
        importer.skin_into_bind_pose = actual_skin
        bpy.context.view_layer.update()
        if len(captures) != 2:
            raise ValueError("Expected exactly one instrumented bind-skin call per model")
        before_arrays = visual.transfer.source_arrays(*visual.transfer.read_container(original["baseline"]["path"]))
        after_arrays = visual.transfer.source_arrays(*visual.transfer.read_container(original["candidate"]["path"]))
        report["authored_accessors_exact"] = {key: np.array_equal(before_arrays[key], after_arrays[key]) for key in ("POSITION", "NORMAL", "TEXCOORD_0", "indices")}
        report["authored_normals"], _ = vector_difference(before_arrays["NORMAL"], after_arrays["NORMAL"])
        report["importer_normal_input"], _ = vector_difference(captures[0]["normal_input"], captures[1]["normal_input"])
        report["importer_bind_skin_normal_output"], imported_difference = vector_difference(captures[0]["normal_output"], captures[1]["normal_output"])
        report["importer_bind_skin_position_delta_m"] = float(np.linalg.norm(captures[0]["position_output"] - captures[1]["position_output"], axis=1).max())
        report["joint_bind_skin_matrix_max_identity_error"] = [float(np.max(abs(capture["joint_matrices"] - np.eye(4)))) for capture in captures]
        report["existing33_joint_bind_skin_matrix_max_difference"] = float(np.max(abs(captures[0]["joint_matrices"] - captures[1]["joint_matrices"][:33])))
        raw_before = np.array([list(corner.vector) for corner in before_body.data.corner_normals])
        raw_after = np.array([list(corner.vector) for corner in after_body.data.corner_normals])
        report["static_raw_corner_normals"], corner_difference = vector_difference(raw_before, raw_after)
        encoded_before, encoded_after = encoded_normals(before_body.data), encoded_normals(after_body.data)
        encoded_changed = np.flatnonzero(np.any(encoded_before != encoded_after, axis=1))
        report["static_encoded_custom_normal_pairs"] = {"rows": len(encoded_before), "changed_count": len(encoded_changed), "maximum_integer_delta": int(np.max(abs(encoded_before - encoded_after))),
                                                         "changed_indices": encoded_changed.tolist()}
        snapshots = [visual.transfer.audit_tool.rig_core.mesh_snapshot(body) for body in (before_body, after_body)]
        report["static_world_normalized_snapshot"], _ = vector_difference(snapshots[0]["normals"], snapshots[1]["normals"])
        report["static_positions_max_difference_m"] = float(np.linalg.norm(snapshots[0]["positions"] - snapshots[1]["positions"], axis=1).max())
        report["static_corner_UV_exact"] = np.array_equal(snapshots[0]["uv"], snapshots[1]["uv"])
        report["static_triangles_exact"] = np.array_equal(snapshots[0]["triangles"], snapshots[1]["triangles"])
        evaluated_normals, evaluated_positions = [], []
        for body in (before_body, after_body):
            evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
            evaluated_normals.append(np.array([list((matrix @ corner.vector).normalized()) for corner in mesh.corner_normals]))
            evaluated_positions.append(np.array([list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices]))
            evaluated.to_mesh_clear()
        report["evaluated_rest_world_normalized"], _ = vector_difference(evaluated_normals[0], evaluated_normals[1])
        report["evaluated_rest_surface_max_difference_m"] = float(np.linalg.norm(evaluated_positions[0] - evaluated_positions[1], axis=1).max())
        preparation = visual.read_json(original["preparation"]["path"])
        changed_weights = set(preparation["changed_render_vertices"])
        loop_vertices = np.array([loop.vertex_index for loop in after_body.data.loops])
        changed_corners = np.flatnonzero(corner_difference != 0)
        report["association"] = {"weight_changed_render_rows": len(changed_weights), "importer_output_changed_vertices": int(np.count_nonzero(imported_difference)),
                                 "importer_output_changed_outside_weight_scope": [int(index) for index in np.flatnonzero(imported_difference) if int(index) not in changed_weights],
                                 "static_corner_changed": len(changed_corners), "static_corner_changed_outside_weight_scope": [int(index) for index in changed_corners if int(loop_vertices[index]) not in changed_weights]}
        native_map, _, _ = visual.transfer.audit_tool.texture.native_identity(after_arrays)
        for row in report["static_raw_corner_normals"]["top_rows"]:
            loop = row["index"]
            vertex = int(loop_vertices[loop])
            row.update({"render_vertex": vertex, "native_vertex": native_map[vertex], "weight_changed": vertex in changed_weights,
                        "encoded_before": encoded_before[loop].tolist(), "encoded_after": encoded_after[loop].tolist(),
                        "importer_normal_before": captures[0]["normal_output"][vertex].tolist(), "importer_normal_after": captures[1]["normal_output"][vertex].tolist(),
                        "static_position_before": snapshots[0]["positions"][vertex].tolist(), "static_position_after": snapshots[1]["positions"][vertex].tolist()})
        report["actual_object_world_matrices"] = {"baseline_mesh": [list(row) for row in before_body.matrix_world], "candidate_mesh": [list(row) for row in after_body.matrix_world],
                                                 "baseline_armature": [list(row) for row in before_rig.matrix_world], "candidate_armature": [list(row) for row in after_rig.matrix_world]}
        report["importer_source"] = visual.core.record(IMPORTER)
        report["instrumentation"] = "Read-only copies immediately before and after the original skin_into_bind_pose function. No importer source patch, model change, normal reset, smoothing change, export or rendering. Original function restored in finally."
        report["status"] = "readonly_layers_measured_no_gate_changed"
        for record in spec["frozen_inputs"]:
            visual.transfer.audit_tool.texture.checked_record(record)
        report["frozen_inputs_unchanged"] = True
    except Exception as error:
        report["status"], report["error"] = "failed_preserved_no_retry", str(error)
        visual.core.save(output / "normal_diagnostic.json", report)
        raise
    finally:
        importer.skin_into_bind_pose = actual_skin
    visual.core.save(output / "normal_diagnostic.json", report)
    print(json.dumps({"status": report["status"], "static_raw": report["static_raw_corner_normals"]["maximum_angle_degrees"], "evaluated_rest": report["evaluated_rest_world_normalized"]["maximum_angle_degrees"], "report": visual.core.record(output / "normal_diagnostic.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "run"), required=True)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.mode == "prepare":
        prepare()
    elif args.spec:
        run(args.spec)
    else:
        parser.error("Frozen spec required")


if __name__ == "__main__":
    main()
