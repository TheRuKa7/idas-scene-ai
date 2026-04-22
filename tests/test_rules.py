"""Rule DSL + evaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from idas.models.schemas import BBox, RuleDef, Track, Zone
from idas.rules.dsl import RuleCompileError, RuleContext, compile_rule
from idas.rules.evaluator import RuleEvaluator


def _track(label: str, track_id: int = 1, x: float = 0.5, y: float = 0.5) -> Track:
    return Track(
        track_id=track_id,
        label=label,
        score=0.9,
        bbox=BBox(x1=x - 0.05, y1=y - 0.05, x2=x + 0.05, y2=y + 0.05),
        hits=5,
        age=5,
    )


def test_class_in_matches() -> None:
    fn = compile_rule(RuleDef(op="class_in", args={"labels": ["person", "car"]}))
    assert fn(RuleContext(track=_track("person"), zones={}, track_age_seconds=0.0))
    assert not fn(RuleContext(track=_track("bike"), zones={}, track_age_seconds=0.0))


def test_class_in_empty_labels_rejected() -> None:
    with pytest.raises(RuleCompileError):
        compile_rule(RuleDef(op="class_in", args={"labels": []}))


def test_in_zone_point_in_polygon() -> None:
    zone = Zone(name="doorway", points=[(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)])
    fn = compile_rule(RuleDef(op="in_zone", args={"zone": "doorway"}))
    inside = RuleContext(
        track=_track("p", x=0.5, y=0.5),
        zones={"doorway": zone},
        track_age_seconds=0.0,
    )
    outside = RuleContext(
        track=_track("p", x=0.1, y=0.1),
        zones={"doorway": zone},
        track_age_seconds=0.0,
    )
    assert fn(inside)
    assert not fn(outside)


def test_in_zone_missing_zone_returns_false() -> None:
    fn = compile_rule(RuleDef(op="in_zone", args={"zone": "missing"}))
    assert not fn(RuleContext(track=_track("p"), zones={}, track_age_seconds=0.0))


def test_dwell_gt() -> None:
    fn = compile_rule(RuleDef(op="dwell_gt", args={"seconds": 10}))
    assert not fn(RuleContext(track=_track("p"), zones={}, track_age_seconds=9.9))
    assert fn(RuleContext(track=_track("p"), zones={}, track_age_seconds=10.5))


def test_and_or_not() -> None:
    person_dwell = RuleDef(
        op="and",
        args={
            "clauses": [
                {"op": "class_in", "args": {"labels": ["person"]}},
                {"op": "dwell_gt", "args": {"seconds": 5}},
            ]
        },
    )
    fn = compile_rule(person_dwell)
    assert fn(RuleContext(track=_track("person"), zones={}, track_age_seconds=6))
    assert not fn(RuleContext(track=_track("person"), zones={}, track_age_seconds=3))
    assert not fn(RuleContext(track=_track("car"), zones={}, track_age_seconds=60))

    never_bike = RuleDef(
        op="not",
        args={"clause": {"op": "class_in", "args": {"labels": ["bike"]}}},
    )
    fn2 = compile_rule(never_bike)
    assert fn2(RuleContext(track=_track("car"), zones={}, track_age_seconds=0.0))
    assert not fn2(RuleContext(track=_track("bike"), zones={}, track_age_seconds=0.0))


def test_unknown_op_rejected_at_model_layer() -> None:
    """Pydantic's Literal on `op` catches bad ops before compile_rule runs.

    That's the preferred failure site — rejecting at schema load time means
    bad rules never reach the compiler. We keep compile_rule's own
    registry check as a belt-and-braces second line of defense.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RuleDef(op="teleport", args={})  # type: ignore[arg-type]

    # Also confirm the compiler's own guard: bypass validation by
    # constructing with model_construct, which skips the Literal check.
    bogus = RuleDef.model_construct(op="teleport", args={})  # type: ignore[arg-type]
    with pytest.raises(RuleCompileError):
        compile_rule(bogus)


# ---- evaluator edge-transition semantics ---------------------------------------


def test_evaluator_opens_then_closes() -> None:
    rule = RuleDef(
        op="class_in", args={"labels": ["person"]}, name="person_seen"
    )
    evaluator = RuleEvaluator([rule], zones=[])

    now = datetime.utcnow()
    events1 = evaluator.evaluate([_track("person", track_id=7)], now)
    assert len(events1) == 1
    assert events1[0].opened is True
    assert events1[0].rule_name == "person_seen"
    assert events1[0].track_id == 7

    # Same track still visible — no new event.
    events2 = evaluator.evaluate([_track("person", track_id=7)], now)
    assert events2 == []

    # Track disappears — evaluator must close the open hit.
    events3 = evaluator.evaluate([], now)
    assert len(events3) == 1
    assert events3[0].opened is False


def test_evaluator_dwell_uses_wall_clock() -> None:
    """The `dwell_gt` clause must see `track_age_seconds` derived from the
    evaluator's clock, not from any Track field."""
    t = [0.0]

    def fake_now() -> float:
        return t[0]

    rule = RuleDef(op="dwell_gt", args={"seconds": 2}, name="lingering")
    evaluator = RuleEvaluator([rule], zones=[], now=fake_now)
    tr = _track("person", track_id=1)

    # t=0: just observed
    assert evaluator.evaluate([tr], datetime.utcnow()) == []
    # t=1: still <= 2
    t[0] = 1.0
    assert evaluator.evaluate([tr], datetime.utcnow()) == []
    # t=3: dwell passes threshold → open
    t[0] = 3.0
    events = evaluator.evaluate([tr], datetime.utcnow())
    assert len(events) == 1 and events[0].opened is True
