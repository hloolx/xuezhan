"""One surface-derived retention loop and smooth release route, without Blender."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refine_stone_slinger_sling_diameter as prior_math


def unit(vector):
    length = np.linalg.norm(vector)
    if length < 1e-12:
        raise ValueError("Degenerate direction")
    return vector / length


def bezier(controls, segments):
    parameter = np.linspace(0, 1, segments + 1)[:, None]
    first, second, third, fourth = np.array(controls)
    return (1 - parameter) ** 3 * first + 3 * (1 - parameter) ** 2 * parameter * second + 3 * (1 - parameter) * parameter ** 2 * third + parameter ** 3 * fourth


def orient_closed_mesh(points, faces):
    adjacency = defaultdict(list)
    for index, face in enumerate(faces):
        for corner in range(3):
            start, end = int(face[corner]), int(face[(corner + 1) % 3])
            adjacency[tuple(sorted((start, end)))].append((index, 1 if start < end else -1))
    if any(len(rows) != 2 for rows in adjacency.values()):
        raise ValueError("Derivative mesh must have exactly two faces at every edge")
    neighbours = defaultdict(list)
    for rows in adjacency.values():
        (first, first_sign), (second, second_sign) = rows
        neighbours[first].append((second, first_sign == second_sign))
        neighbours[second].append((first, first_sign == second_sign))
    signs = {}
    components = []
    for seed in range(len(faces)):
        if seed in signs:
            continue
        signs[seed] = False
        queue, component = deque([seed]), []
        while queue:
            index = queue.popleft()
            component.append(index)
            for neighbour, invert in neighbours[index]:
                value = signs[index] ^ invert
                if neighbour in signs and signs[neighbour] != value:
                    raise ValueError("Nonorientable derivative topology")
                if neighbour not in signs:
                    signs[neighbour] = value
                    queue.append(neighbour)
        components.append(component)
    result = np.array([face[::-1] if signs[index] else face for index, face in enumerate(faces)])
    for component in components:
        surface = points[result[component]]
        volume = np.einsum("ti,ti->t", surface[:, 0], np.cross(surface[:, 1], surface[:, 2])).sum() / 6
        if volume < 0:
            result[component] = result[component][:, ::-1]
    used, inverse = np.unique(result, return_inverse=True)
    return points[used], inverse.reshape(-1, 3), {"closed_two_face_edges": True, "oriented": True, "connected_components": len(components), "removed_unused_vertices": len(points) - len(used)}


def tube(path, radius, first_normal=None, cap_start=True):
    path = np.array(path)
    points, sections, tangents = [], [], []
    first = None
    previous = None
    for index, center in enumerate(path):
        tangent = unit(path[min(index + 1, len(path) - 1)] - path[max(0, index - 1)])
        if first is None:
            reference = np.array(first_normal) if first_normal is not None else np.array([0., 1., 0.]) if abs(tangent[1]) < .9 else np.array([0., 0., 1.])
            first = unit(reference - tangent * np.dot(reference, tangent))
        else:
            rotation_axis = np.cross(previous, tangent)
            sine, cosine = np.linalg.norm(rotation_axis), np.dot(previous, tangent)
            if sine > 1e-12:
                rotation_axis /= sine
                first = first * cosine + np.cross(rotation_axis, first) * sine + rotation_axis * np.dot(rotation_axis, first) * (1 - cosine)
            elif cosine < 0:
                raise ValueError("Reversing route")
            first = unit(first - tangent * np.dot(first, tangent))
        second = np.cross(tangent, first)
        section = np.array([center + radius * (np.cos(side * np.pi / 4) * first + np.sin(side * np.pi / 4) * second) for side in range(8)])
        points.extend(section)
        sections.append(section)
        tangents.append(tangent)
        previous = tangent
    faces = [[0, side + 1, side] for side in range(1, 7)] if cap_start else []
    for ring in range(len(path) - 1):
        for side in range(8):
            first_index, second_index = ring * 8 + side, ring * 8 + (side + 1) % 8
            faces.extend(((first_index, second_index, second_index + 8), (first_index, second_index + 8, first_index + 8)))
    last = (len(path) - 1) * 8
    faces.extend((last, last + side, last + side + 1) for side in range(1, 7))
    sections, tangents = np.array(sections), np.array(tangents)
    edges = np.diff(path, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    directions = edges / lengths[:, None]
    turns = np.arccos(np.clip(np.sum(directions[:-1] * directions[1:], axis=1), -1, 1))
    circumradius = (lengths[:-1] + lengths[1:]) / np.maximum(4 * np.sin(turns * .5), 1e-30)
    average_tangent = prior_math.joint.normalized_rows(tangents[:-1] + tangents[1:])
    axial_edges = np.einsum("rsi,ri->rs", np.diff(sections, axis=0), average_tangent)
    radial_error = np.max(np.abs(np.linalg.norm(sections - path[:, None], axis=2) - radius))
    diagnostic = {"rings": len(path), "sides": 8, "radius_m": radius, "maximum_segment_turn_degrees": float(np.degrees(turns).max()),
                  "minimum_discrete_bend_radius_m": float(circumradius.min()), "maximum_radius_times_curvature": float(radius / circumradius.min()),
                  "minimum_corresponding_section_axial_advance_m": float(axial_edges.min()), "cross_section_radius_maximum_error_m": float(radial_error),
                  "checks": {"radius_curvature_at_most_half": bool(radius / circumradius.min() <= .5), "adjacent_sections_do_not_reverse": bool(axial_edges.min() > 0),
                             "cross_sections_remain_circular": bool(radial_error < 1e-10), "maximum_polyline_turn_at_most15degrees": bool(np.degrees(turns).max() <= 15)}}
    return np.array(points), np.array(faces), diagnostic


def plane_section_components(points, triangles, center, axis):
    locations, adjacency = {}, defaultdict(set)
    for triangle in points[triangles]:
        distances = (triangle - center) @ axis
        intersections = []
        for corner in range(3):
            other = (corner + 1) % 3
            if distances[corner] * distances[other] < 0:
                fraction = distances[corner] / (distances[corner] - distances[other])
                intersections.append(triangle[corner] + fraction * (triangle[other] - triangle[corner]))
        if len(intersections) == 2:
            keys = [tuple(np.rint(point / 1e-8).astype(int)) for point in intersections]
            if keys[0] == keys[1]:
                continue
            for key, point in zip(keys, intersections):
                if key in locations and np.linalg.norm(locations[key] - point) > 1e-8:
                    raise ValueError("Section-node analysis merge exceeded its explicit tolerance")
                locations[key] = point
            adjacency[keys[0]].add(keys[1])
            adjacency[keys[1]].add(keys[0])
    visited, records, eligible = set(), [], []
    reference = np.array([1., 0, 0]) if abs(axis[0]) < .9 else np.array([0., 1., 0])
    first = unit(reference - axis * np.dot(reference, axis))
    second = np.cross(axis, first)
    for seed in adjacency:
        if seed in visited:
            continue
        queue, component = deque([seed]), set()
        while queue:
            current = queue.popleft()
            if current in component:
                continue
            component.add(current)
            queue.extend(adjacency[current] - component)
        visited.update(component)
        closed = all(len(adjacency[key]) == 2 for key in component)
        row = {"vertices": len(component), "closed": closed, "contains_bone_axis": False}
        if closed:
            ordered, previous, current = [], None, seed
            while current not in ordered:
                ordered.append(current)
                next_key = next(key for key in sorted(adjacency[current]) if key != previous)
                previous, current = current, next_key
            polygon = np.array([locations[key] for key in ordered])
            coordinates = np.column_stack(((polygon - center) @ first, (polygon - center) @ second))
            following = np.roll(coordinates, -1, axis=0)
            cross = coordinates[:, 0] * following[:, 1] - coordinates[:, 1] * following[:, 0]
            winding = np.arctan2(cross, np.sum(coordinates * following, axis=1)).sum()
            row.update({"contains_bone_axis": bool(abs(winding) > np.pi), "area_m2": abs(float(cross.sum())) * .5,
                        "minimum_axis_radius_m": float(np.linalg.norm(coordinates, axis=1).min()), "maximum_axis_radius_m": float(np.linalg.norm(coordinates, axis=1).max())})
            if row["contains_bone_axis"]:
                eligible.append((row["area_m2"], polygon))
        records.append(row)
    if not eligible:
        raise ValueError("No closed local finger section surrounding its actual bone axis: " + json.dumps(records))
    return min(eligible, key=lambda row: row[0])[1], records


def plane_section(points, triangles, center, axis):
    return plane_section_components(points, triangles, center, axis)[0]


def tangent_arc(start, direction, end_direction, radius):
    direction, end_direction = unit(direction), unit(end_direction)
    angle = np.arccos(np.clip(np.dot(direction, end_direction), -1, 1))
    axis = unit(np.cross(direction, end_direction))
    inward = np.cross(axis, direction)
    parameters = np.linspace(0, angle, max(2, int(np.ceil(np.degrees(angle) / 6))) + 1)
    return np.array([start + radius * (np.sin(parameter) * direction + (1 - np.cos(parameter)) * inward) for parameter in parameters])


def loop_with_stem(center, axis, outward, loop_radius, path):
    ring_count, loop_tube_radius = 48, .002
    transverse = np.cross(axis, outward)
    points = []
    for ring in range(ring_count):
        angle = ring * 2 * np.pi / ring_count
        radial = np.cos(angle) * outward + np.sin(angle) * transverse
        for side in range(8):
            phase = side * np.pi / 4
            points.append(center + loop_radius * radial + loop_tube_radius * (np.cos(phase) * radial - np.sin(phase) * axis))
    faces = []
    for ring in range(ring_count):
        for side in range(8):
            if ring in (ring_count - 1, 0) and side in (7, 0):
                continue
            first = ring * 8 + side
            second = ring * 8 + (side + 1) % 8
            third = ((ring + 1) % ring_count) * 8 + (side + 1) % 8
            fourth = ((ring + 1) % ring_count) * 8 + side
            faces.extend(((first, second, third), (first, third, fourth)))
    boundary = np.array([((ring % ring_count) * 8 + side % 8) for ring, side in ((-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))])
    points = np.array(points)
    junction_center = points[boundary].mean(axis=0)
    first_normal = unit(points[boundary[0]] - junction_center - outward * np.dot(points[boundary[0]] - junction_center, outward))
    second_normal = np.cross(outward, first_normal)
    angles = np.arctan2((points[boundary] - junction_center) @ second_normal, (points[boundary] - junction_center) @ first_normal) % (2 * np.pi)
    boundary = boundary[np.argsort(angles)]
    stem_points, stem_faces, stem_diagnostic = tube(path, .004, first_normal=first_normal, cap_start=False)
    offset = len(points)
    faces.extend((stem_faces + offset).tolist())
    for side in range(8):
        next_side = (side + 1) % 8
        faces.extend(((int(boundary[side]), int(boundary[next_side]), offset + next_side), (int(boundary[side]), offset + next_side, offset + side)))
    points = np.vstack((points, stem_points))
    points, faces, topology = orient_closed_mesh(points, np.array(faces))
    return points, faces, {"loop_radius_m": loop_radius, "loop_cord_diameter_m": .004, "main_cord_diameter_m": .008, "loop_rings": ring_count,
                           "loop_radius_times_curvature": .002 / loop_radius, "junction": "Removed2x2outertorusquadpatch; connected8boundaryvertices to one flared stem. No overlapping separate pipes.",
                           "junction_boundary_vertex_count": 8, "stem": stem_diagnostic, "topology": topology}


def analyze(output):
    old, joint = prior_math.joint.old, prior_math.joint
    prep = json.loads((old.BRANCH / "preparation_05/grip_preparation.json").read_text(encoding="utf-8"))
    prior_path = old.BRANCH / "terminal_plan_01/terminal_comparison.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    chosen = prior["best_candidates"][2]
    for key in ("source", "weapon", "root_review"):
        if old.rig.record(Path(prep[key]["path"])) != prep[key]:
            raise ValueError("Immutable input changed: " + key)
    source = json.loads(Path(prep["actual_rig_transfer_report"]["path"]).read_text(encoding="utf-8"))
    mapping = json.loads(Path(source["mapping"]["path"]).read_text(encoding="utf-8"))
    bones = source["actual_final_skeleton"]["armatures"][0]["bones"]
    arrays = old.texture.read_glb(old.rig.SOURCE)[2]
    positions = arrays["POSITION"][:, (0, 2, 1)].astype(float) * (1, -1, 1)
    triangles = arrays["indices"].astype(int)
    weights = [mapping["source_vertex_weights"][str(index)] for index in range(len(positions))]
    basis, root = np.array(prep["weapon_basis_columns"]), np.array(prep["terminal_root_rest_m"])
    hand_ids = np.array([index for index, row in enumerate(weights) if any(name.endswith("_r") and name.startswith(("hand_", "index_", "thumb_", "middle_", "ring_", "pinky_")) and value > 0 for name, value in row.items())])
    hand_faces = np.flatnonzero(np.all(np.isin(triangles, hand_ids), axis=1))
    actual = positions.copy()
    actual[hand_ids] = old.skin.deform(positions[hand_ids], [weights[index] for index in hand_ids], bones, chosen["commands"])[0]
    local = (actual - root) @ basis
    bone_points = []
    anchor_bone = next(row for row in bones if row["name"] == "pinky_03_r")
    for endpoint_field in ("head_world_review_m", "tail_world_review_m"):
        point = np.array(anchor_bone[endpoint_field])
        moved = old.skin.deform(np.array([point]), [{"pinky_03_r": 1.}], bones, chosen["commands"])[0][0]
        bone_points.append((moved - root) @ basis)
    axis = unit(bone_points[1] - bone_points[0])
    center = (bone_points[0] + bone_points[1]) * .5
    outward = unit(np.array([0., -1., 0.]) - axis * np.dot([0., -1., 0.], axis))
    pinky_weighted = np.array([sum(value for name, value in row.items() if name.startswith("pinky_") and name.endswith("_r")) > .5 for row in weights])
    pinky_faces = np.flatnonzero(np.all(pinky_weighted[triangles], axis=1))
    sections = [plane_section_components(local, triangles[hand_faces], center + axis * distance, axis) for distance in (-.003, 0, .003)]
    section = np.vstack([row[0] for row in sections])
    projected = section - center - ((section - center) @ axis)[:, None] * axis
    loop_radius = float(np.linalg.norm(projected, axis=1).max()) + .0025
    if loop_radius > np.linalg.norm(bone_points[1] - bone_points[0]):
        raise ValueError("Local ring exceeds its actual finger-segment length; do not render a whole-hand loop")
    anchor = center + outward * (loop_radius + .002)
    stem_start = anchor + outward * .012
    escape = anchor + outward * .032 + np.array([-.025, 0., -.045])
    endpoint = np.array([-.05, 0., -.52])
    stem_first = bezier([stem_start, stem_start + outward * .018, escape + [0, 0, .025], escape], 24)
    stem_second = bezier([escape, escape + [0, 0, -.10], endpoint + [0, 0, .08], endpoint], 24)
    stem_path = np.vstack((stem_first, stem_second[1:]))
    retained_points, retained_faces, retained_quality = loop_with_stem(center, axis, outward, loop_radius, stem_path)
    old_release = np.array(chosen["released"]["path"])
    pinch_center = old_release[:2].mean(axis=0)
    pinch_axis = unit(old_release[0] - old_release[1])
    start, departure = pinch_center + pinch_axis * .006, pinch_center - pinch_axis * .006
    release_endpoint = np.array([.1, 0., -.52])
    neck = np.linspace(start, departure, 5)
    release_direction = unit(np.array([-.7, 0., -.7]))
    release_first = tangent_arc(departure, -pinch_axis, release_direction, .020)
    escape_release = release_first[-1]
    release_second = bezier([escape_release, escape_release + release_direction * .10, release_endpoint + [0, 0, .08], release_endpoint], 32)
    release_path = np.vstack((neck, release_first[1:], release_second[1:]))
    release_points, release_faces, release_quality = tube(release_path, .004)
    release_points, release_faces, release_topology = orient_closed_mesh(release_points, release_faces)
    release_quality["topology"] = release_topology
    result = {"asset_id": "Unit_StoneSlinger", "status": "one_new_loop_route_pure_diagnostic_pending_actual_DCC", "script": old.rig.record(Path(__file__)),
              "source": prep["source"], "weapon_source": prep["weapon"], "root_review": prep["root_review"], "prior_pose": old.rig.record(prior_path),
              "commands": chosen["commands"], "basis_columns": basis.tolist(), "root_rest_m": root.tolist(), "candidate_count": 1, "search_iterations": 0,
              "human_weights_PBR_or_original_weapon_modified": False, "actual_blender_executed": False, "grip_approved": False,
              "retention_surface_section": {"bone": "pinky_03_r", "fraction_along_actual_bone": .5, "section_offsets_m": [-.003, 0, .003], "source_triangle_ids": hand_faces.tolist(),
                                             "selection_policy": "Full actual hand surface plane intersection, then closed contour enclosing the pinky bone axis. A dominant-weight subset is not assumed to be a closed physical finger boundary.",
                                             "section_points_local_m": section.tolist(), "section_component_diagnostics": [row[1] for row in sections], "center_local_m": center.tolist(), "axis_local": axis.tolist(), "outward_local": outward.tolist(), "radius_m": loop_radius},
              "independent_controls": {"retained_anchor": anchor.tolist(), "released_tip": start.tolist(), "pouch_retained": endpoint.tolist(), "pouch_released": release_endpoint.tolist(),
                                       "retention_fixed_during_release": True, "release_motion_not_created": True, "pouch_and_stone_remain_separate_original_objects": True},
              "meshes": {}, "diagnostics": {}}
    output.mkdir(parents=True, exist_ok=False)
    for name, points, faces, quality in (("retained_loop_cord", retained_points, retained_faces, retained_quality), ("released_cord", release_points, release_faces, release_quality)):
        world = points @ basis.T + root
        self_crossings = joint.pair_crossings(world, faces, np.arange(len(faces)), np.arange(len(faces)), np.arange(len(world)))
        interior = prior_math.certify_triangle_interiors(actual, triangles, hand_faces, world, faces)
        crossings = prior_math.mesh_crossings(actual, triangles, hand_faces, world, faces)
        result["meshes"][name] = {"positions_local_m": points.tolist(), "triangles": faces.tolist(), "quality": quality}
        result["diagnostics"][name] = {"self_crossings": self_crossings, "hand_triangle_crossings": crossings, "full_face_interior": interior}
        old.rig.save(output / "loop_anchor_plan.json", result)
    loop_distances, _ = joint.nearest_surface(local[triangles[pinky_faces]].mean(axis=1), retained_points[retained_faces])
    loop_nearest = int(np.argmin(loop_distances))
    result["retention_surface_contact"] = {"triangle": int(pinky_faces[loop_nearest]), "barycentric": [1 / 3] * 3, "gap_m": float(loop_distances[loop_nearest])}
    palm = np.array(prep["hand_frame"]["palm"])
    contacts, radials = {}, []
    for finger in ("index", "thumb"):
        ids = joint.pad_faces(finger, positions, triangles, weights, bones, palm)
        centers, normals = joint.face_samples(local, triangles[ids])
        distances, closest = joint.nearest_surface(centers, release_points[release_faces])
        nearest = int(np.argmin(distances))
        delta = closest[nearest] - pinch_center
        radial = unit(delta - pinch_axis * np.dot(delta, pinch_axis))
        radials.append(radial)
        contacts[finger] = {"triangle": int(ids[nearest]), "barycentric": [1 / 3] * 3, "gap_m": float(distances[nearest]), "normal_dot_radial": float(np.dot(normals[nearest], radial))}
    result["true03_contacts"] = contacts
    result["opposed_radial_dot"] = float(np.dot(*radials))
    result["between_cords_crossings"] = prior_math.mesh_crossings(retained_points, retained_faces, np.arange(len(retained_faces)), release_points, release_faces)
    result["checks"] = {"retained_finger_contact_within2mm": result["retention_surface_contact"]["gap_m"] <= .002,
                        "true03_contacts_within2mm": max(row["gap_m"] for row in contacts.values()) <= .002,
                        "opposed_true03_pad_contact": result["opposed_radial_dot"] <= -.5 and all(row["normal_dot_radial"] <= -.3 for row in contacts.values()),
                        "retention_ring_curvature": retained_quality["loop_radius_times_curvature"] <= .5,
                        "smooth_retained_stem": all(retained_quality["stem"]["checks"].values()), "smooth_release_route": all(release_quality["checks"].values()),
                        "no_cord_self_crossings": all(not row["self_crossings"] for row in result["diagnostics"].values()),
                        "full_face_interiors_within2mm_certified": all(row["full_face_interior"]["passed"] for row in result["diagnostics"].values()),
                        "cords_do_not_cross_each_other": not result["between_cords_crossings"]}
    old.rig.save(output / "loop_anchor_plan.json", result)
    print(json.dumps({"path": str(output / "loop_anchor_plan.json"), "checks": result["checks"], "triangles": {name: len(mesh["triangles"]) for name, mesh in result["meshes"].items()}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(Path(args.output).resolve())
