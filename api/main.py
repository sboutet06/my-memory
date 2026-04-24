"""FastAPI application — my-memory knowledge graph API.

V1 stub: /health, /facts/{fact_id}.
Phase 10 hardens with auth, CORS, rate limiting, and all remaining
endpoints from charter §2.2.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
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
    """Return a Fact with its Claims and (empty until Phase 7) Conflicts."""
    fact = store.get_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")

    claims = store.claims_for_fact(fact_id)
    return {
        "fact": fact.model_dump(),
        "claims": [c.model_dump() for c in claims],
        "conflicts": [],
    }
