"""Prove a source-surface weight transfer without launching Blender or welding."""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path

import numpy as np

import cleanup_stone_slinger as cleanup
import inspect_stone_slinger_rig as rig
import review_stone_slinger_texture as texture


AUDIT = rig.BRANCH / "rig_inspection_01/inspection.json"
AUDIT_SHA = "6d5b9c2d01b081265365269e5322be3f0ea98822e1e7530af254b99dd740355a"


def pair_triangles(source_positions, source_triangles, returned_positions, returned_triangles):
    source_ids, returned_ids = texture.position_correspondence(source_positions, returned_positions)
    source_faces = defaultdict(list)
    for face, triangle in enumerate(source_triangles):
        source_faces[tuple(sorted(int(source_ids[index]) for index in triangle))].append(face)
    vertex_map = defaultdict(set)
    triangle_map = {}
    maximum_error = 0.0
    for face, triangle in enumerate(returned_triangles):
        key = tuple(sorted(int(returned_ids[index]) for index in triangle))
        matches = source_faces.get(key, [])
        if len(matches) != 1 or matches[0] in triangle_map:
            raise ValueError("Every cloud triangle must match one unused source triangle")
        source_face = matches[0]
        source_triangle = source_triangles[source_face]
        by_position = {int(source_ids[index]): int(index) for index in source_triangle}
        ordered_source = [by_position[int(returned_ids[index])] for index in triangle]
        if not any(ordered_source == list(source_triangle[offset:]) + list(source_triangle[:offset]) for offset in range(3)):
            raise ValueError("Triangle winding changed")
        triangle_map[source_face] = {"returned_triangle": face, "source_vertices_in_returned_corner_order": ordered_source}
        for source_index, returned_index in zip(ordered_source, triangle):
            vertex_map[source_index].add(int(returned_index))
            maximum_error = max(maximum_error, float(np.linalg.norm(source_positions[source_index] - returned_positions[returned_index])))
    if len(triangle_map) != len(source_triangles) or len(vertex_map) != len(source_positions):
        raise ValueError("Incomplete source surface correspondence")
    return vertex_map, triangle_map, maximum_error


def resolve_weights(vertex_map, weights):
    resolved, inconsistent = {}, []
    for source_index, cloud_indices in vertex_map.items():
        rows = [weights[index] for index in sorted(cloud_indices)]
        keys = set().union(*(row.keys() for row in rows))
        maximum = max((abs(row.get(name, 0) - rows[0].get(name, 0)) for row in rows for name in keys), default=0.0)
        if maximum > 1e-7:
            inconsistent.append({"source_vertex": source_index, "cloud_vertices": sorted(cloud_indices), "maximum_weight_difference": maximum})
        else:
            resolved[source_index] = rows[0]
    return resolved, inconsistent


def native_identity(source_positions, source_triangles):
    vertices, polygons, _, _ = cleanup.read_fbx(cleanup.SOURCE)
    plan = cleanup.split_plan(vertices, polygons, split_point_joins=True)
    duplicate = {int(key): value for key, value in plan["duplicate_vertex_map"].items()}
    changed = set(plan["modified_face_indices"])
    native_vertices = list(vertices) + [vertices[index] for index in duplicate]
    native_polygons = [[duplicate.get(vertex, vertex) if face in changed else vertex for vertex in polygon]
                       for face, polygon in enumerate(polygons)]
    normalization = json.loads((rig.BRANCH / "normalized_01/geometry_report.json").read_text(encoding="utf-8-sig"))
    matrix = np.array(normalization["normalization"]["matrix_source_world_to_result"])
    native_positions = (np.column_stack((native_vertices, np.ones(len(native_vertices)))) @ matrix.T)[:, :3]
    native_ids, source_ids = texture.position_correspondence(native_positions, source_positions)
    parent_faces = defaultdict(list)
    for face, polygon in enumerate(native_polygons):
        for triangle in combinations(polygon, 3):
            parent_faces[tuple(sorted(int(native_ids[index]) for index in triangle))].append(face)
    source_native = defaultdict(set)
    for triangle in source_triangles:
        key = tuple(sorted(int(source_ids[index]) for index in triangle))
        parents = parent_faces[key]
        if len(parents) != 1:
            raise ValueError("Repaired source triangle lacks unique cleaned native parent")
        native_by_position = {int(native_ids[index]): index for index in native_polygons[parents[0]]}
        for index in triangle:
            source_native[int(index)].add(native_by_position[int(source_ids[index])])
    if any(len(values) != 1 for values in source_native.values()):
        raise ValueError("Source render vertex already merges independent cleaned native identities")
    return {index: next(iter(values)) for index, values in source_native.items()}, duplicate


def analyze(output):
    for path, expected in ((rig.SOURCE, rig.SOURCE_SHA), (rig.RETURNED, rig.RETURNED_SHA), (AUDIT, AUDIT_SHA)):
        if rig.record(path)["sha256"] != expected:
            raise ValueError("Frozen rig audit/source changed")
    audit = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
    source = texture.read_glb(rig.SOURCE)[2]
    source_positions = source["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    raw_vertices, raw_faces, raw_uv_layers, version = cleanup.read_fbx(rig.RETURNED)
    if any(len(face) != 3 for face in raw_faces):
        raise ValueError("Actual rig FBX is no longer the audited triangle mesh")
    mesh_object = next(item for item in audit["received_objects"] if item["type"] == "MESH")
    received_world = (np.column_stack((raw_vertices, np.ones(len(raw_vertices)))) @ np.array(mesh_object["matrix_world"]).T)[:, :3]
    fit = audit["frame_fit"]
    restored = received_world @ np.array(fit["rotation"]).T * fit["uniform_scale"] + fit["translation_m"]
    recorded = audit["skeleton"]["weights"][0]["all_vertex_weights"]
    recorded_positions = np.array([item["world_review_m"] for item in recorded])
    indexed_error = float(np.linalg.norm(restored - recorded_positions, axis=1).max())
    if indexed_error > 1e-6:
        raise ValueError("Raw FBX indices do not correspond to actual Blender rig vertex indices")
    vertex_map, triangle_map, position_error = pair_triangles(source_positions, source["indices"], restored, raw_faces)
    weights, inconsistent = resolve_weights(vertex_map, {item["vertex"]: item["weights"] for item in recorded})
    source_native, duplicates = native_identity(source_positions, source["indices"])
    cloud_native = defaultdict(set)
    native_cloud = defaultdict(set)
    for source_index, cloud_indices in vertex_map.items():
        native = source_native[source_index]
        native_cloud[native].update(cloud_indices)
        for index in cloud_indices:
            cloud_native[index].add(native)
    separated_pairs = [{"original_native_vertex": original, "duplicate_native_vertex": duplicate,
                        "original_cloud_vertices": sorted(native_cloud[original]),
                        "duplicate_cloud_vertices": sorted(native_cloud[duplicate]),
                        "shared_cloud_vertices": sorted(native_cloud[original] & native_cloud[duplicate])}
                       for original, duplicate in duplicates.items()]
    mixed = {str(index): sorted(values) for index, values in cloud_native.items() if len(values) > 1}
    cloud_graph = cleanup.topology(raw_vertices, raw_faces)
    affected = sorted({index for row in separated_pairs for index in row["original_cloud_vertices"] + row["duplicate_cloud_vertices"]})
    fan_rows = cleanup.vertex_face_fans(raw_faces, cloud_graph, affected)
    uv_errors = []
    cloud_uv = np.array(raw_uv_layers[0]["loops"]).reshape(-1, 3, 2)
    for row in triangle_map.values():
        expected_uv = source["TEXCOORD_0"][row["source_vertices_in_returned_corner_order"]].astype(float)
        expected_uv[:, 1] = 1 - expected_uv[:, 1]
        uv_errors.extend(np.linalg.norm(expected_uv - cloud_uv[row["returned_triangle"]], axis=1).tolist())
    if max(uv_errors) > 1e-6:
        raise ValueError("Explicit GLTF-to-FBX UV convention check failed")
    output.mkdir(parents=True, exist_ok=False)
    mapping_file = output / "source_weight_correspondence.json"
    rig.save(mapping_file, {"schema_version": 1, "source_vertex_count": len(source_positions),
                           "source_render_vertex_to_cloud_vertices": {str(index): sorted(values) for index, values in vertex_map.items()},
                           "source_render_vertex_to_cleaned_native_vertex": source_native,
                           "source_vertex_weights": weights, "triangle_map": triangle_map})
    result = {"asset_id": "Unit_StoneSlinger", "status": "transfer_correspondence_proven_candidate_not_applied" if not inconsistent else "inconsistent_corner_weights_reject_transfer",
              "source": rig.record(rig.SOURCE), "returned": rig.record(rig.RETURNED), "audit": rig.record(AUDIT),
              "mapping": rig.record(mapping_file), "script": rig.record(Path(__file__)), "fbx_version": version,
              "actual_indexed_raw_FBX_to_imported_vertex_error_m": indexed_error,
              "full_triangle_count": len(triangle_map), "maximum_source_corner_position_error_m": position_error,
              "maximum_uv_error": max(uv_errors), "source_render_vertices": len(source_positions), "cloud_vertices": len(raw_vertices),
              "source_vertices_mapping_to_multiple_cloud_vertices": sum(len(values) > 1 for values in vertex_map.values()),
              "source_vertex_corner_weights_inconsistent": inconsistent, "weight_averaging_performed": False,
              "six_cleaned_split_pairs": separated_pairs, "cloud_vertices_merging_distinct_native_vertices": mixed,
              "affected_cloud_vertex_fans": fan_rows,
              "cloud_fan_merge_detected": bool(mixed), "source_geometry_and_PBR_untouched": True,
              "candidate_recipe": ["Import exact approved repaired GLB, retaining every render index, triangle, UV, encoded custom normal and material image byte",
                                   "Transfer each source vertex its consistent actual cloud weight row; never average or position-weld",
                                   "Import actual61bone rig; bake the proven proper world rotation/uniform scale/translation into armature rest data with identity armature object transform and unit root pose scale",
                                   "Attach retained source mesh with identity bind transforms; verify actual evaluated rest geometry and all bone world positions before saving",
                                   "Compare source normals/UV/PBR and six native split identities, then actual material views and diagnostic pose; no paid calls or animation approval"],
              "remaining_weight_warning": "53of154lowest2.5cm vertices primarily calf_twist weighted. Transfer preserves real weights, not an approval of heel/sole deformation.",
              "blender_started": False, "candidate_applied": False, "production_approved": False}
    rig.save(output / "transfer_plan.json", result)
    print(json.dumps({key: result[key] for key in ("status", "full_triangle_count", "maximum_source_corner_position_error_m", "maximum_uv_error", "source_vertices_mapping_to_multiple_cloud_vertices", "cloud_vertices_merging_distinct_native_vertices", "six_cleaned_split_pairs")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Use a new analysis directory")
    analyze(output)


if __name__ == "__main__":
    main()
