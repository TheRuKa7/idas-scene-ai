"""Rule evaluator — runs compiled rules over a stream of (frame, tracks).

Fires a :class:`RuleHitEvent` the first frame a rule becomes true for a
given (rule, track_id) pair, and a closing event on the frame it stops
being true. This state machine per pair lives inside :class:`RuleEvaluator`
so callers don't need to remember what fired last.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import time

from idas.models.schemas import RuleDef, Track, Zone
from idas.rules.dsl import RuleContext, RuleFn, compile_rule


@dataclass(frozen=True)
class RuleHitEvent:
    """Emitted on rule-edge transitions (false→true or true→false)."""

    rule_name: str
    track_id: int
    label: str
    score: float
    zone: str | None
    ts: datetime
    opened: bool  # True when rule fires, False when it closes


@dataclass
class _ActiveHit:
    opened_at: float  # monotonic timestamp when the rule first fired
    last_ts: datetime


class RuleEvaluator:
    """Stateful evaluator for a per-stream rule set."""

    def __init__(
        self,
        rules: list[RuleDef],
        zones: list[Zone],
        *,
        now: callable | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._compiled: list[tuple[str, RuleFn, RuleDef]] = []
        for i, r in enumerate(rules):
            name = r.name or f"rule_{i}"
            self._compiled.append((name, compile_rule(r), r))
        self._zones: dict[str, Zone] = {z.name: z for z in zones}
        self._track_born_at: dict[int, float] = {}  # monotonic seconds
        self._active: dict[tuple[str, int], _ActiveHit] = {}
        self._now = now or time

    # ---- track lifecycle -----------------------------------------------------

    def observe_track(self, track: Track) -> None:
        if track.track_id not in self._track_born_at:
            self._track_born_at[track.track_id] = self._now()

    def _track_age(self, track: Track) -> float:
        born = self._track_born_at.get(track.track_id)
        if born is None:
            return 0.0
        return max(0.0, self._now() - born)

    # ---- evaluation ----------------------------------------------------------

    def evaluate(self, tracks: list[Track], ts: datetime) -> list[RuleHitEvent]:
        """Evaluate all rules against all tracks; return edge-transition events."""
        events: list[RuleHitEvent] = []
        live_track_ids = {t.track_id for t in tracks}

        for track in tracks:
            self.observe_track(track)
            age = self._track_age(track)
            ctx = RuleContext(track=track, zones=self._zones, track_age_seconds=age)

            for rule_name, fn, rule_def in self._compiled:
                fired = bool(fn(ctx))
                key = (rule_name, track.track_id)
                was_active = key in self._active

                if fired and not was_active:
                    self._active[key] = _ActiveHit(opened_at=self._now(), last_ts=ts)
                    events.append(
                        RuleHitEvent(
                            rule_name=rule_name,
                            track_id=track.track_id,
                            label=track.label,
                            score=track.score,
                            zone=_zone_for(rule_def),
                            ts=ts,
                            opened=True,
                        )
                    )
                elif fired and was_active:
                    self._active[key].last_ts = ts  # keep-alive
                elif not fired and was_active:
                    events.append(
                        RuleHitEvent(
                            rule_name=rule_name,
                            track_id=track.track_id,
                            label=track.label,
                            score=track.score,
                            zone=_zone_for(rule_def),
                            ts=ts,
                            opened=False,
                        )
                    )
                    del self._active[key]

        # Tracks that vanished mid-rule: close them so downstream storage
        # doesn't accumulate zombie "open" hits.
        to_close = [k for k in self._active if k[1] not in live_track_ids]
        for key in to_close:
            rule_name, tid = key
            last = self._active[key]
            events.append(
                RuleHitEvent(
                    rule_name=rule_name,
                    track_id=tid,
                    label="",
                    score=0.0,
                    zone=None,
                    ts=last.last_ts,
                    opened=False,
                )
            )
            del self._active[key]

        # Retire track birthdays for identities we will never see again.
        for tid in list(self._track_born_at):
            if tid not in live_track_ids and not any(
                k[1] == tid for k in self._active
            ):
                del self._track_born_at[tid]

        return events


def _zone_for(rule: RuleDef) -> str | None:
    """Best-effort extraction of a zone name from a (possibly composite) rule.

    Helpful for storage — if the rule references `in_zone`, we record which
    zone it was so the UI can filter by zone without re-parsing the JSON.
    """
    if rule.op == "in_zone":
        z = rule.args.get("zone")
        return z if isinstance(z, str) else None
    if rule.op in ("and", "or"):
        for clause in rule.args.get("clauses", []):
            if isinstance(clause, dict):
                inner = RuleDef.model_validate(clause)
                found = _zone_for(inner)
                if found is not None:
                    return found
    if rule.op == "not":
        clause = rule.args.get("clause")
        if isinstance(clause, dict):
            return _zone_for(RuleDef.model_validate(clause))
    return None
