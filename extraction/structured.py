"""Inject pack-produced structured records into the LightRAG graph.

Pure planner (`plan_transaction_nodes`) builds the node + edge list; the
async `inject_*` function writes them to a real `LightRAG.chunk_entity_relation_graph`.
"""
from __future__ import annotations

import logging
from typing import Iterable

import hashlib
from collections import defaultdict
from decimal import Decimal

from packs.personal_documents.schemas.transaction import Transaction, TransactionDirection

logger = logging.getLogger(__name__)


def _account_node_name(rib: str | None) -> str:
    if not rib:
        return "account:unknown"
    return f"account:{rib}"


def _tx_node_name(t: Transaction) -> str:
    """Human-readable transaction node identifier.

    Front-loads meaningful tokens (direction, amount, date, description)
    so vector similarity can latch onto them; suffixes a short hash to
    keep the name unique across identical-looking rows.
    """
    short = t.description.strip().replace("\n", " ")[:60]
    # Stable hash across processes (Python's builtin hash() is randomized).
    suffix = hashlib.md5(t.description.encode("utf-8")).hexdigest()[:4]
    return (
        f"Transaction {t.direction.value} {t.amount} EUR {t.date.isoformat()} "
        f"{short} [{suffix}]"
    )


def _doc_node_name(doc_id: str) -> str:
    # Embed `/store/<uuid>/` so when the LLM cites this entity, the
    # citation regex in extract_document_ids recovers the source id.
    return f"Document /store/{doc_id}/ (bank statement)"


def _category_summary_name(doc_id: str, direction: str, category: str) -> str:
    return (
        f"Expense summary {category} ({direction}) from bank statement {doc_id}"
    )


def plan_transaction_nodes(
    transactions: Iterable[Transaction],
) -> tuple[list[dict], list[dict]]:
    """Return `(nodes, edges)` for the given transactions.

    Emits three node kinds:
      - transaction (per row)
      - account (per rib)
      - document (per source_doc_id)
      - category_summary (per doc × direction × category; aggregates total & count)

    And edges:
      - transaction → account
      - transaction → source document
      - transaction → its category summary
      - category summary → source document
    """
    transactions = list(transactions)

    nodes_by_name: dict[str, dict] = {}
    edges: list[dict] = []

    # First pass: aggregate totals per (doc, direction, category)
    buckets: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"total": Decimal("0"), "count": 0},
    )
    for t in transactions:
        key = (t.source_doc_id, t.direction.value, t.category or "other")
        buckets[key]["total"] += t.amount
        buckets[key]["count"] += 1

    # Emit summary nodes.
    for (doc_id, direction, category), agg in buckets.items():
        name = _category_summary_name(doc_id, direction, category)
        nodes_by_name[name] = {
            "name": name,
            "entity_type": "transaction_category",
            "attrs": {
                "document_id": doc_id,
                "direction": direction,
                "category": category,
                "total_amount": str(agg["total"]),
                "count": str(agg["count"]),
            },
        }

    for t in transactions:
        tx_name = _tx_node_name(t)
        if tx_name not in nodes_by_name:
            nodes_by_name[tx_name] = {
                "name": tx_name,
                "entity_type": "transaction",
                "attrs": {
                    "date": t.date.isoformat(),
                    "value_date": t.value_date.isoformat(),
                    "direction": t.direction.value,
                    "amount": str(t.amount),
                    "category": t.category or "other",
                    "description": t.description,
                    "source_doc_id": t.source_doc_id,
                },
            }

        account_name = _account_node_name(t.account_rib)
        if account_name not in nodes_by_name:
            nodes_by_name[account_name] = {
                "name": account_name,
                "entity_type": "account",
                "attrs": {"rib": t.account_rib or ""},
            }
        edges.append({"src": tx_name, "tgt": account_name, "relation": "on_account"})

        doc_name = _doc_node_name(t.source_doc_id)
        if doc_name not in nodes_by_name:
            nodes_by_name[doc_name] = {
                "name": doc_name,
                "entity_type": "document",
                "attrs": {"document_id": t.source_doc_id},
            }
        edges.append({"src": tx_name, "tgt": doc_name, "relation": "from_document"})

        summary_name = _category_summary_name(
            t.source_doc_id, t.direction.value, t.category or "other",
        )
        edges.append({
            "src": tx_name, "tgt": summary_name, "relation": "in_category",
        })
        # One edge per summary → document, deduplicated via tuple-check below.
        edges.append({
            "src": summary_name, "tgt": doc_name, "relation": "summary_of_document",
        })

    # Dedupe edges by (src, tgt, relation).
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for e in edges:
        key = (e["src"], e["tgt"], e["relation"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    return list(nodes_by_name.values()), deduped


def _tx_description(attrs: dict) -> str:
    """Rich, retrieval-friendly description for a transaction node."""
    return (
        f"Bank transaction on {attrs['date']} ({attrs['direction']}) of "
        f"{attrs['amount']} EUR, category {attrs['category']}. "
        f"Description: {attrs['description']}."
    )


def _summary_description(attrs: dict) -> str:
    direction = attrs["direction"]
    kind = "expense" if direction == "debit" else "income"
    return (
        f"Bank statement aggregate: category {attrs['category']} "
        f"({direction}/{kind}) totalling {attrs['total_amount']} EUR across "
        f"{attrs['count']} transaction(s). Source document: {attrs['document_id']}."
    )


async def inject_transactions(rag, transactions: list[Transaction]) -> dict:
    """Create structured nodes + edges via LightRAG's public API.

    `acreate_entity` / `acreate_relation` write to BOTH the graph storage
    AND the entity/relation vector stores, so the new records are
    reachable from vector-similarity retrieval at query time.

    Idempotent: on re-run, LightRAG updates existing entities in place
    (same name → same doc, LightRAG merges).
    """
    if not transactions:
        return {"nodes_upserted": 0, "edges_upserted": 0, "errors": []}

    nodes, edges = plan_transaction_nodes(transactions)

    nodes_upserted = 0
    edges_upserted = 0
    errors: list[str] = []

    existing = set()
    kg = rag.chunk_entity_relation_graph

    for node in nodes:
        name = node["name"]
        t = node["entity_type"]
        if t == "transaction":
            description = _tx_description(node["attrs"])
        elif t == "transaction_category":
            description = _summary_description(node["attrs"])
        else:
            description = f"{t} {name}"
        doc_id_for_citation = (
            node["attrs"].get("source_doc_id")
            or node["attrs"].get("document_id", "")
        )
        payload = {
            "entity_type": t,
            "description": description,
            "source_id": doc_id_for_citation,
        }
        if doc_id_for_citation:
            # `file_path` surfaces in LightRAG citations. Any string
            # containing `/store/<uuid>/…` is parseable back to the
            # source document by extract_document_ids.
            payload["file_path"] = f"store/{doc_id_for_citation}/content.md"
        for k, v in node["attrs"].items():
            payload[k] = str(v) if v is not None else ""

        try:
            existing_node = await kg.get_node(name)
            if existing_node is None:
                await rag.acreate_entity(name, payload)
            else:
                # keep the existing source_id blob intact; just update fields.
                await rag.aedit_entity(name, payload, allow_rename=False)
            existing.add(name)
            nodes_upserted += 1
        except Exception as exc:
            errors.append(f"node {name!r}: {exc}")

    for edge in edges:
        src, tgt = edge["src"], edge["tgt"]
        if src not in existing or tgt not in existing:
            continue
        relation_data = {
            "description": edge["relation"],
            "keywords": edge["relation"],
            "weight": 1.0,
        }
        try:
            existing_edge = await kg.get_edge(src, tgt)
            if existing_edge is None:
                await rag.acreate_relation(src, tgt, relation_data)
                edges_upserted += 1
            # else: already present, no-op (acreate_relation raises on dup)
        except Exception as exc:
            errors.append(f"edge {src!r}→{tgt!r}: {exc}")

    return {
        "nodes_upserted": nodes_upserted,
        "edges_upserted": edges_upserted,
        "errors": errors,
    }
