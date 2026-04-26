"""FastAPI application — my-memory knowledge graph API.

Phase 7: /health, /facts/{id}, /conflicts, /conflicts/{id},
         POST /conflicts/{id}/resolve (stub).
Phase 8: GET /entities/{id} with optional ?as_of=YYYY-MM-DD.
Phase 10 hardens with auth, CORS, rate limiting, and remaining endpoints.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import Path as PathParam

from facts.store import FactStore

app = FastAPI(title="my-memory", version="0.1.0-stub")

_DEFAULT_STORE_DIR = Path(__file__).parent.parent / "facts" / "store"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def get_store() -> FactStore:
    """Dependency: resolve the FactStore from env or default path."""
    store_dir = Path(os.environ.get("FACTS_STORE_DIR", str(_DEFAULT_STORE_DIR)))
    return FactStore(store_dir)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/facts/{fact_id}")
def get_fact(
    fact_id: Annotated[str, PathParam(pattern=_SHA256_PATTERN)],
    store: FactStore = Depends(get_store),
) -> dict:
    """Return a Fact with its Claims and Conflicts."""
    fact = store.get_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")

    claims = store.claims_for_fact(fact_id)
    conflicts = store.conflicts_for_fact(fact_id)
    return {
        "fact": fact.model_dump(),
        "claims": [c.model_dump() for c in claims],
        "conflicts": [c.model_dump() for c in conflicts],
    }


@app.get("/conflicts")
def list_conflicts(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=100, ge=1, le=1000),
    store: FactStore = Depends(get_store),
) -> dict:
    """List conflicts, optionally filtered by status."""
    all_conflicts = store.all_conflicts()
    if status is not None:
        all_conflicts = [c for c in all_conflicts if c.status == status]
    paged = all_conflicts[:limit]
    return {
        "conflicts": [c.model_dump() for c in paged],
        "total": len(all_conflicts),
    }


@app.get("/conflicts/{conflict_id}")
def get_conflict(
    conflict_id: Annotated[str, PathParam(pattern=_SHA256_PATTERN)],
    store: FactStore = Depends(get_store),
) -> dict:
    """Return a Conflict with all competing Facts and their Claims."""
    conflict = store.get_conflict(conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")

    valid_facts = [
        store.get_fact(fid)
        for fid in conflict.competing_fact_ids
        if store.get_fact(fid) is not None
    ]
    claims = {
        fid: store.claims_for_fact(fid)
        for fid in conflict.competing_fact_ids
    }
    return {
        "conflict": conflict.model_dump(),
        "competing_facts": [f.model_dump() for f in valid_facts],
        "claims": {fid: [c.model_dump() for c in cs] for fid, cs in claims.items()},
    }


@app.get("/entities/{entity_id}")
def get_entity(
    entity_id: str,
    as_of: Optional[date] = Query(default=None, description="ISO date YYYY-MM-DD"),
    store: FactStore = Depends(get_store),
) -> dict:
    """Return facts about entity_id, optionally filtered to a point in time.

    Phase 8.5 — bitemporal as_of query. A fact is in scope at date D iff
    (valid_from is None or valid_from <= D) and (valid_to is None or
    valid_to >= D).
    """
    if as_of is None:
        facts = store.facts_for_subject(entity_id)
    else:
        facts = store.facts_for_subject_as_of(entity_id, as_of)

    payload: dict = {
        "entity_id": entity_id,
        "facts": [f.model_dump() for f in facts],
    }
    if as_of is not None:
        payload["as_of"] = as_of.isoformat()
    return payload


@app.post("/conflicts/{conflict_id}/resolve", status_code=501)
def resolve_conflict(
    conflict_id: Annotated[str, PathParam(pattern=_SHA256_PATTERN)],
    body: dict,
    store: FactStore = Depends(get_store),
) -> dict:
    """Stub — resolution flows through YAML + Git (Phase 7.3).

    Returns 404 if the conflict does not exist; 501 otherwise.
    Use corrections/derivation/conflicts/<id>.yaml and
    python -m corrections apply-conflict-corrections --apply.
    """
    conflict = store.get_conflict(conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    raise HTTPException(
        status_code=501,
        detail=(
            "API-driven resolution not yet implemented. "
            "Edit corrections/derivation/conflicts/<id>.yaml and run "
            "python -m corrections apply-conflict-corrections --apply"
        ),
    )
