"""Rule compile / validate endpoint.

Separate from `/streams` so a UI can preflight a rule JSON before binding
it to a stream — avoids the round-trip of creating a stream just to find
out the rule is malformed.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from idas.models.schemas import RuleDef
from idas.rules.dsl import RuleCompileError, compile_rule

router = APIRouter(prefix="/rules", tags=["rules"])


@router.post("/validate")
async def validate_rule(rule: RuleDef) -> dict[str, object]:
    """Compile and introspect a rule. 400 with a human-readable error on failure."""
    try:
        compile_rule(rule)
    except RuleCompileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "op": rule.op, "name": rule.name}
