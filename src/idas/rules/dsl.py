"""Rule DSL — JSON in, callable out.

A "rule" is a JSON object describing a predicate over a single tracked
identity at a single moment in time (with access to that track's history
via the evaluator context). Rules compose with boolean combinators:

    class_in(labels)         # detection label is in the given set
    in_zone(zone)            # detection centroid is inside a named polygon
    dwell_gt(seconds)        # track has existed >= N seconds
    and(clauses)
    or(clauses)
    not(clause)

Compiling a :class:`RuleDef` returns a callable that, given a
:class:`RuleContext`, returns True if the rule fires.

We compile eagerly so bad rules (typos, missing args) fail at stream-
creation time, not at frame N when the rule happens to be evaluated.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from idas.models.schemas import RuleDef, Track, Zone


@dataclass(frozen=True)
class RuleContext:
    """State handed to compiled rule callables."""

    track: Track
    zones: dict[str, Zone]
    track_age_seconds: float


RuleFn = Callable[[RuleContext], bool]


class RuleCompileError(ValueError):
    """Raised when a :class:`RuleDef` is malformed."""


# ----- leaf operators -----------------------------------------------------------


def _op_class_in(args: dict) -> RuleFn:
    labels = args.get("labels")
    if not isinstance(labels, list) or not labels:
        raise RuleCompileError("class_in.args.labels must be a non-empty list")
    label_set = {str(x) for x in labels}
    return lambda ctx: ctx.track.label in label_set


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting; inclusive on one edge pair to be stable at grid corners."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _op_in_zone(args: dict) -> RuleFn:
    name = args.get("zone")
    if not isinstance(name, str) or not name:
        raise RuleCompileError("in_zone.args.zone must be a non-empty string")

    def check(ctx: RuleContext) -> bool:
        zone = ctx.zones.get(name)
        if zone is None:
            return False
        return _point_in_polygon(ctx.track.bbox.cx, ctx.track.bbox.cy, zone.points)

    return check


def _op_dwell_gt(args: dict) -> RuleFn:
    seconds = args.get("seconds")
    if not isinstance(seconds, (int, float)) or seconds < 0:
        raise RuleCompileError("dwell_gt.args.seconds must be a non-negative number")
    threshold = float(seconds)
    return lambda ctx: ctx.track_age_seconds > threshold


# ----- combinators --------------------------------------------------------------


def _op_and(args: dict) -> RuleFn:
    clauses = _compile_clauses(args.get("clauses"), "and")
    return lambda ctx: all(c(ctx) for c in clauses)


def _op_or(args: dict) -> RuleFn:
    clauses = _compile_clauses(args.get("clauses"), "or")
    return lambda ctx: any(c(ctx) for c in clauses)


def _op_not(args: dict) -> RuleFn:
    raw = args.get("clause")
    if not isinstance(raw, dict):
        raise RuleCompileError("not.args.clause must be a rule object")
    inner = compile_rule(RuleDef.model_validate(raw))
    return lambda ctx: not inner(ctx)


def _compile_clauses(raw: object, op: str) -> list[RuleFn]:
    if not isinstance(raw, list) or not raw:
        raise RuleCompileError(f"{op}.args.clauses must be a non-empty list")
    return [compile_rule(RuleDef.model_validate(r)) for r in raw]


_REGISTRY: dict[str, Callable[[dict], RuleFn]] = {
    "class_in": _op_class_in,
    "in_zone": _op_in_zone,
    "dwell_gt": _op_dwell_gt,
    "and": _op_and,
    "or": _op_or,
    "not": _op_not,
}


def compile_rule(rule: RuleDef) -> RuleFn:
    """Turn a :class:`RuleDef` into a predicate callable.

    Raises :class:`RuleCompileError` on malformed input. The returned
    callable is pure with respect to its context — safe to memoize or share
    across threads.
    """
    builder = _REGISTRY.get(rule.op)
    if builder is None:
        raise RuleCompileError(f"unknown rule op: {rule.op!r}")
    return builder(rule.args)
