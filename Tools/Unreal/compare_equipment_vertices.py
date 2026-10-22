"""Strict bidirectional vertex tolerance check with local spatial buckets.

Every point must have a counterpart within the original tolerance. On success
the reported nearest distances are exact: all possible points within tolerance
are inside the 27 queried cells. Unmatched points fail, never pass approximately.
"""
import itertools
import math

NEIGHBORS = tuple(itertools.product((-1, 0, 1), repeat=3))


def nearest_within(actual, expected, tolerance):
    if not actual or not expected or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Nonempty vertex arrays and a positive finite tolerance are required")
    cell = lambda point: tuple(math.floor(value/tolerance) for value in point)
    buckets = {}
    for index, point in enumerate(expected):
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise ValueError("Expected vertex is not a finite 3D point")
        buckets.setdefault(cell(point), []).append((index, point))
    indices, errors, missing = [], [], []
    limit = tolerance*tolerance
    for index, point in enumerate(actual):
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise ValueError("Actual vertex is not a finite 3D point")
        key = cell(point)
        best, selected = limit, None
        for delta in NEIGHBORS:
            for candidate, other in buckets.get(tuple(a+b for a, b in zip(key, delta)), ()):
                squared = sum((a-b)**2 for a, b in zip(point, other))
                if squared <= best:
                    best, selected = squared, candidate
        indices.append(selected)
        if selected is None:
            missing.append(index)
        else:
            errors.append(math.sqrt(best))
    return indices, errors, missing


def compare_vertices(actual, expected, tolerance):
    mapping, forward, missing_forward = nearest_within(expected, actual, tolerance)
    _, backward, missing_backward = nearest_within(actual, expected, tolerance)
    passed = not missing_forward and not missing_backward
    return {
        "expected_to_actual_max_cm": max(forward) if not missing_forward else None,
        "actual_to_expected_max_cm": max(backward) if not missing_backward else None,
        "expected_count": len(expected), "actual_count": len(actual),
        "passed": passed, "tolerance_cm": tolerance,
        "unmatched_expected_count": len(missing_forward), "unmatched_actual_count": len(missing_backward),
        "unmatched_expected_examples": missing_forward[:8], "unmatched_actual_examples": missing_backward[:8],
        "method": "Exact nearest within tolerance using 27 adjacent cells; both directions required",
    }, mapping
