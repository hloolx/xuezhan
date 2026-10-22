"""Pure geometry checks for a bounded local skin-weight experiment."""
from __future__ import annotations

import numpy as np


def edge_touches_band(first_height, second_height, full_height, zero_height):
    return bool(max(first_height, second_height) >= full_height and min(first_height, second_height) <= zero_height)


def segment_triangle_interior(start, end, triangle, epsilon=1e-9, include_boundary=False):
    direction = end - start
    first, second = triangle[1] - triangle[0], triangle[2] - triangle[0]
    cross = np.cross(direction, second)
    determinant = float(np.dot(first, cross))
    if abs(determinant) < epsilon * np.linalg.norm(direction) * np.linalg.norm(first) * np.linalg.norm(second):
        return False
    relative = start - triangle[0]
    first_barycentric = float(np.dot(relative, cross) / determinant)
    other_cross = np.cross(relative, first)
    second_barycentric = float(np.dot(direction, other_cross) / determinant)
    along = float(np.dot(second, other_cross) / determinant)
    if include_boundary:
        return (-epsilon <= along <= 1 + epsilon and first_barycentric >= -epsilon
                and second_barycentric >= -epsilon and first_barycentric + second_barycentric <= 1 + epsilon)
    return (epsilon < along < 1 - epsilon and first_barycentric > epsilon
            and second_barycentric > epsilon and first_barycentric + second_barycentric < 1 - epsilon)


def cross2(first, second):
    return float(first[0] * second[1] - first[1] * second[0])


def signed_area(points):
    return .5 * sum(cross2(points[index], points[(index + 1) % len(points)]) for index in range(len(points)))


def coplanar_overlap_area(first, second, normal):
    drop = int(np.argmax(np.abs(normal)))
    polygon = [np.delete(point, drop) for point in first]
    clip = [np.delete(point, drop) for point in second]
    orientation = 1 if signed_area(clip) >= 0 else -1
    for start, end in zip(clip, clip[1:] + clip[:1]):
        if not polygon:
            return 0.
        result = []
        previous = polygon[-1]
        previous_distance = orientation * cross2(end - start, previous - start)
        for current in polygon:
            distance = orientation * cross2(end - start, current - start)
            if (distance >= 0) != (previous_distance >= 0):
                result.append(previous + (current - previous) * previous_distance / (previous_distance - distance))
            if distance >= 0:
                result.append(current)
            previous, previous_distance = current, distance
        polygon = result
    projected = abs(signed_area(polygon)) if len(polygon) >= 3 else 0.
    return projected * float(np.linalg.norm(normal) / abs(normal[drop]))


def triangle_contact_kind(first, second, epsilon=1e-9):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    first_normal = np.cross(first[1] - first[0], first[2] - first[0])
    second_normal = np.cross(second[1] - second[0], second[2] - second[0])
    first_length, second_length = np.linalg.norm(first_normal), np.linalg.norm(second_normal)
    if min(first_length, second_length) < 1e-14:
        return "degenerate"
    distance_second = (second - first[0]) @ first_normal / first_length
    distance_first = (first - second[0]) @ second_normal / second_length
    if (np.all(distance_first > epsilon) or np.all(distance_first < -epsilon)
            or np.all(distance_second > epsilon) or np.all(distance_second < -epsilon)):
        return "none"
    if np.max(np.abs(distance_second)) <= epsilon and np.max(np.abs(distance_first)) <= epsilon:
        return "coplanar_area_overlap" if coplanar_overlap_area(first, second, first_normal) > 1e-12 else "coplanar_no_area"
    for source, target in ((first, second), (second, first)):
        if any(segment_triangle_interior(source[index], source[(index + 1) % 3], target, epsilon) for index in range(3)):
            return "proper_crossing"
    for source, target in ((first, second), (second, first)):
        if any(segment_triangle_interior(source[index], source[(index + 1) % 3], target, epsilon, True) for index in range(3)):
            return "touch_only"
    return "none"


def native_edges(triangles, native_ids):
    result = {}
    for triangle in triangles:
        for start, end in zip(triangle, np.roll(triangle, -1)):
            native_pair = tuple(sorted((int(native_ids[start]), int(native_ids[end]))))
            if native_pair[0] != native_pair[1]:
                result.setdefault(native_pair, (int(start), int(end)))
    return result


def triangle_orientation(rest_positions, actual_positions, triangles, vertex_linear):
    rest = rest_positions[triangles]
    actual = actual_positions[triangles]
    rest_cross = np.cross(rest[:, 1] - rest[:, 0], rest[:, 2] - rest[:, 0])
    actual_cross = np.cross(actual[:, 1] - actual[:, 0], actual[:, 2] - actual[:, 0])
    average = vertex_linear[triangles].mean(axis=1)
    cofactor = np.stack((np.cross(average[:, :, 1], average[:, :, 2]),
                         np.cross(average[:, :, 2], average[:, :, 0]),
                         np.cross(average[:, :, 0], average[:, :, 1])), axis=2)
    expected = np.einsum("nij,nj->ni", cofactor, rest_cross)
    actual_lengths = np.linalg.norm(actual_cross, axis=1)
    expected_lengths = np.linalg.norm(expected, axis=1)
    denominator = actual_lengths * expected_lengths
    cosine = np.divide(np.einsum("ni,ni->n", actual_cross, expected), denominator,
                       out=np.ones(len(triangles)), where=denominator > 1e-25)
    return {"negative_triangles": np.flatnonzero(cosine < 0).tolist(),
            "degenerate_triangles": np.flatnonzero(actual_lengths < 1e-14).tolist(),
            "minimum_expected_normal_dot": float(cosine.min()),
            "minimum_triangle_area_m2": float(actual_lengths.min() * .5),
            "expected_basis": "Cofactor of triangle mean LBS linear map applied to rest face normal; no world-up assumption."}
