"""Pure-Python IoU + Hungarian-style greedy matching.

Deliberately dependency-free so it can run inside the subprocess worker too
if we ever decide to track there. The matching is O(n*m) greedy (not optimal
Hungarian), which is fine for the <100 detections/frame regime iDAS targets
and keeps the implementation MIT-clean with no scipy pull.
"""
from __future__ import annotations

from idas.models.schemas import BBox


def iou(a: BBox, b: BBox) -> float:
    """Intersection-over-union of two axis-aligned boxes."""
    xx1 = max(a.x1, b.x1)
    yy1 = max(a.y1, b.y1)
    xx2 = min(a.x2, b.x2)
    yy2 = min(a.y2, b.y2)
    w = max(0.0, xx2 - xx1)
    h = max(0.0, yy2 - yy1)
    inter = w * h
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def iou_matrix(tracks: list[BBox], dets: list[BBox]) -> list[list[float]]:
    """Return a |tracks| x |dets| IoU matrix."""
    return [[iou(t, d) for d in dets] for t in tracks]


def greedy_match(
    cost_matrix: list[list[float]],
    *,
    threshold: float,
    n_cols: int | None = None,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy matcher: at each step pick the pair with the highest IoU.

    Returns (matches, unmatched_track_indices, unmatched_det_indices).

    ``n_cols`` must be provided by the caller whenever ``cost_matrix`` might
    be empty (i.e. zero tracks) — otherwise we can't know how many
    detections were *possible* to match and would wrongly report no
    unmatched detections.
    """
    rows = len(cost_matrix)
    if rows == 0:
        cols = n_cols if n_cols is not None else 0
    else:
        cols = len(cost_matrix[0])
    used_rows: set[int] = set()
    used_cols: set[int] = set()
    matches: list[tuple[int, int]] = []

    # Flatten into (score, r, c) and sort descending.
    flat = [
        (cost_matrix[r][c], r, c)
        for r in range(rows)
        for c in range(cols)
        if cost_matrix[r][c] >= threshold
    ]
    flat.sort(reverse=True)

    for _score, r, c in flat:
        if r in used_rows or c in used_cols:
            continue
        used_rows.add(r)
        used_cols.add(c)
        matches.append((r, c))

    unmatched_rows = [r for r in range(rows) if r not in used_rows]
    unmatched_cols = [c for c in range(cols) if c not in used_cols]
    return matches, unmatched_rows, unmatched_cols
