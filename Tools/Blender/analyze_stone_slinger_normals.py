"""Compare changed cloud normals with each preserved native connected face fan."""
from collections import defaultdict
from itertools import combinations
import argparse
import json
from pathlib import Path

import numpy as np

import cleanup_stone_slinger as cleanup
import review_stone_slinger_texture as texture


def analyze(output):
    vertices, polygons, uv_layers, version = cleanup.read_fbx(cleanup.SOURCE)
    plan = cleanup.split_plan(vertices, polygons, split_point_joins=True)
    duplicate = {int(key): value for key, value in plan["duplicate_vertex_map"].items()}
    changed = set(plan["modified_face_indices"])
    native_vertices = list(vertices) + [vertices[index] for index in duplicate]
    native_polygons = [[duplicate.get(vertex, vertex) if face in changed else vertex for vertex in polygon] for face, polygon in enumerate(polygons)]
    normalization = json.loads((texture.BRANCH / "normalized_01/geometry_report.json").read_text(encoding="utf-8-sig"))
    matrix = np.array(normalization["normalization"]["matrix_source_world_to_result"])
    homogeneous = np.column_stack((native_vertices, np.ones(len(native_vertices))))
    blender_positions = (homogeneous @ matrix.T)[:, :3]
    native_positions = blender_positions[:, (0, 2, 1)] * (1, 1, -1)
    source = texture.read_glb(texture.SOURCE)[2]
    returned = texture.read_glb(texture.RETURNED)[2]
    comparison = texture.compare(source, returned)
    native_ids, source_ids = texture.position_correspondence(native_positions, source["POSITION"].astype(float))
    parent_lookup = defaultdict(list)
    for face, polygon in enumerate(native_polygons):
        for triangle in combinations(polygon, 3):
            parent_lookup[tuple(sorted(int(native_ids[index]) for index in triangle))].append(face)
    render_to_native = defaultdict(set)
    triangles = source["indices"]
    mapped_triangles = []
    for triangle in triangles:
        key = tuple(sorted(int(source_ids[index]) for index in triangle))
        matches = parent_lookup[key]
        if len(matches) != 1:
            raise ValueError("Triangle cannot be assigned to exactly one native polygon")
        native_polygon = native_polygons[matches[0]]
        native_by_position = {int(native_ids[index]): index for index in native_polygon}
        mapped = [native_by_position[int(source_ids[index])] for index in triangle]
        mapped_triangles.append(mapped)
        for index, native_index in zip(triangle, mapped):
            render_to_native[int(index)].add(native_index)
    if any(len(values) != 1 for values in render_to_native.values()):
        raise ValueError("Render vertex maps to multiple independent native face fans")
    mapped_triangles = np.array(mapped_triangles)
    positions = source["POSITION"].astype(float)
    cross = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]], positions[triangles[:, 2]] - positions[triangles[:, 0]])
    lengths = np.linalg.norm(cross, axis=1)
    face_normals = cross / lengths[:, None]
    unique_changes = {row["source_vertex"]: row for row in comparison["normal_change_diagnostic"]["large_changes"]}
    rows = []
    for source_index, change in unique_changes.items():
        native = next(iter(render_to_native[source_index]))
        faces = np.flatnonzero(np.any(mapped_triangles == native, axis=1))
        weighted = cross[faces].sum(axis=0)
        weighted /= np.linalg.norm(weighted)
        old = np.array(change["source_normal"])
        new = np.array(change["returned_normal"])
        old_dots = face_normals[faces] @ old
        new_dots = face_normals[faces] @ new
        rows.append({"source_render_vertex": source_index, "returned_render_vertex": change["returned_vertex"],
                     "native_cleaned_vertex": native, "native_fan_triangles": faces.tolist(),
                     "native_fan_triangle_count": len(faces), "position_gltf_y_up_m": positions[source_index].tolist(),
                     "source_normal": old.tolist(), "returned_normal": new.tolist(), "area_weighted_fan_normal": weighted.tolist(),
                     "source_dot_weighted_fan": float(old @ weighted), "returned_dot_weighted_fan": float(new @ weighted),
                     "source_dot_each_face": old_dots.tolist(), "returned_dot_each_face": new_dots.tolist(),
                     "source_negative_face_dots": int((old_dots < 0).sum()), "returned_negative_face_dots": int((new_dots < 0).sum()),
                     "returned_improves_fan_alignment": bool(new @ weighted > old @ weighted)})
    unique_native = sorted({row["native_cleaned_vertex"] for row in rows})
    graph = cleanup.topology(native_vertices, native_polygons)
    fans = cleanup.vertex_face_fans(native_polygons, graph, unique_native)
    result = {"asset_id": "Unit_StoneSlinger", "status": "actual_native_fan_normal_diagnostic_only_not_quality_approval",
              "source": texture.record(texture.SOURCE), "returned": texture.record(texture.RETURNED),
              "script": texture.record(Path(__file__)), "all10770_triangles_assigned_to_unique_native_polygon": True,
              "all_render_vertices_map_to_unique_native_vertex": True, "native_face_fan_checks": fans,
              "large_change_triangle_corners": len(comparison["normal_change_diagnostic"]["large_changes"]),
              "large_change_render_vertices": len(rows), "native_vertices": unique_native, "rows": rows,
              "interpretation": "Fan normals aggregate the full cleaned native face fan, not a position-welded patch or just the UV-split render-vertex subset. Negative geometric-face dot values require paired normal-map/TBN assessment; differing custom normals alone are not a quality failure or approval.",
              "blender_started": False, "production_approved": False}
    output.mkdir(parents=True, exist_ok=False)
    texture.save(output / "normal_basis_diagnostic.json", result)
    print(json.dumps({"rows": [{key: row[key] for key in ("source_render_vertex", "native_cleaned_vertex", "native_fan_triangle_count", "source_dot_weighted_fan", "returned_dot_weighted_fan", "source_negative_face_dots", "returned_negative_face_dots")} for row in rows]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Output must be a fresh directory")
    analyze(output)


if __name__ == "__main__":
    main()
