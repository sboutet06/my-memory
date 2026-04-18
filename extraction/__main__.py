"""CLI: `python -m extraction {extract,query} ...`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from lightrag import QueryParam

from corrections.derivation_applier import build_plan
from corrections.derivation_emitter import (
    emit_alias_corrections,
    emit_entity_type_buckets,
)
from corrections.derivation_io import (
    list_alias_corrections,
    list_entity_type_buckets,
    load_alias_correction,
    load_entity_type_bucket,
    merge_alias_correction,
    merge_entity_type_bucket,
    save_alias_correction,
    save_entity_type_bucket,
)
from extraction.config import ExtractionConfig, compose_entity_types
from packs.registry import discover_packs
from extraction.alias import DEFAULT_THRESHOLD
from extraction.graph import (
    DEFAULT_WORKING_DIR,
    annotate_temporal,
    apply_derivation_plan,
    build_rag,
    discover_store_docs,
    extract_documents,
    graph_stats,
    post_process,
    resolve_aliases,
    snapshot_nodes,
)
from extraction.diagnostics import trace_query
from extraction.retrieval_enhance import write_doc_summary_chunks, write_index_nodes
from extraction.provenance import extract_document_ids
from extraction.references import (
    extract_references_from_query_result,
    inject_references,
)

logger = logging.getLogger("extraction")

QUERY_MODES = ("hybrid", "local", "global", "naive", "mix")
DEFAULT_PACKS_DIR = Path("packs")


def _load_packs(packs_dir: Path | None, disable: bool) -> list:
    """Return the list of discovered Pack instances (empty if disabled)."""
    if disable:
        return []
    directory = packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR
    if not directory.exists():
        return []
    return discover_packs(directory).list()


def _config_with_packs(config: ExtractionConfig, packs: list) -> ExtractionConfig:
    """Return a new config whose entity_types union pack declared types."""
    if not packs:
        return config
    types = compose_entity_types(config.entity_types, packs)
    return ExtractionConfig(
        llm_model=config.llm_model,
        embed_model=config.embed_model,
        embed_dim=config.embed_dim,
        language=config.language,
        base_url=config.base_url,
        entity_types=types,
        temporal_user_prompt=config.temporal_user_prompt,
        temperature=config.temperature,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m extraction")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="Extract entities/relations from ingested docs")
    p_extract.add_argument("--store", type=Path, default=Path("store"))
    p_extract.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
        help=f"LightRAG working directory (default: {DEFAULT_WORKING_DIR})",
    )
    p_extract.add_argument(
        "--corrections-root", type=Path, default=None,
        help="Corrections root (default: <store>/../corrections)",
    )
    p_extract.add_argument(
        "--packs-dir", type=Path, default=None,
        help=f"Packs directory (default: {DEFAULT_PACKS_DIR})",
    )
    p_extract.add_argument(
        "--no-packs", action="store_true",
        help="Disable pack discovery (core taxonomy only)",
    )
    p_extract.add_argument(
        "--no-focus-hints", action="store_true",
        help="Skip per-doc `[EXTRACTION FOCUS: …]` prefixes derived from pack hints",
    )
    p_extract.add_argument("-v", "--verbose", action="store_true")

    p_temporal = sub.add_parser(
        "annotate-temporal",
        help="Prefix every node/edge description with its source document dates",
    )
    p_temporal.add_argument("--store", type=Path, default=Path("store"))
    p_temporal.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_temporal.add_argument(
        "--dry-run", action="store_true",
        help="Count what would be annotated without writing changes.",
    )
    p_temporal.add_argument("-v", "--verbose", action="store_true")

    p_dedupe = sub.add_parser(
        "dedupe",
        help="Cluster entities by name-embedding similarity and merge duplicates",
    )
    p_dedupe.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
    )
    p_dedupe.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Cosine similarity threshold (default: {DEFAULT_THRESHOLD})",
    )
    p_dedupe.add_argument(
        "--apply", action="store_true",
        help="Actually execute the merges (default: dry-run, print plan only)",
    )
    p_dedupe.add_argument(
        "--corrections-root", type=Path, default=None,
        help="Corrections root (default: <working-dir>/../corrections)",
    )
    p_dedupe.add_argument("-v", "--verbose", action="store_true")

    p_emit = sub.add_parser(
        "emit-corrections",
        help="Snapshot the extracted graph and write derivation correction files",
    )
    p_emit.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_emit.add_argument(
        "--corrections-root", type=Path, default=None,
        help="Corrections root (default: <working-dir>/../corrections)",
    )
    p_emit.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help="Alias-cluster cosine threshold (dry-run only)",
    )
    p_emit.add_argument("-v", "--verbose", action="store_true")

    p_struct = sub.add_parser(
        "extract-structured",
        help="Run pack extract_structured() on every doc and inject records into the graph",
    )
    p_struct.add_argument("--store", type=Path, default=Path("store"))
    p_struct.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_struct.add_argument(
        "--packs-dir", type=Path, default=None,
        help=f"Packs directory (default: {DEFAULT_PACKS_DIR})",
    )
    p_struct.add_argument(
        "--no-packs", action="store_true",
        help="Disable pack discovery",
    )
    p_struct.add_argument(
        "--dry-run", action="store_true",
        help="Count what would be injected without writing to the graph",
    )
    p_struct.add_argument("-v", "--verbose", action="store_true")

    p_apply = sub.add_parser(
        "apply-corrections",
        help="Execute user-reviewed derivation corrections against the graph",
    )
    p_apply.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_apply.add_argument(
        "--corrections-root", type=Path, default=None,
        help="Corrections root (default: <working-dir>/../corrections)",
    )
    p_apply.add_argument(
        "--apply", action="store_true",
        help="Actually mutate the graph (default: dry-run, print the plan)",
    )
    p_apply.add_argument("-v", "--verbose", action="store_true")

    p_enhance = sub.add_parser(
        "enhance-retrieval",
        help="Write per-doc summary chunks to chunks_vdb (fixes chunks bottleneck)",
    )
    p_enhance.add_argument("--store", type=Path, default=Path("store"))
    p_enhance.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_enhance.add_argument(
        "--packs-dir", type=Path, default=None,
        help=f"Packs directory (default: {DEFAULT_PACKS_DIR})",
    )
    p_enhance.add_argument(
        "--no-packs", action="store_true",
        help="Disable pack discovery (core-only summary extras)",
    )
    p_enhance.add_argument("-v", "--verbose", action="store_true")

    p_idx = sub.add_parser(
        "build-indexes",
        help="Inject answer-shaped Profile / Catalog synthetic nodes",
    )
    p_idx.add_argument("--store", type=Path, default=Path("store"))
    p_idx.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_idx.add_argument("--min-docs-for-profile", type=int, default=2)
    p_idx.add_argument("--min-entities-for-catalog", type=int, default=2)
    p_idx.add_argument(
        "--packs-dir", type=Path, default=None,
        help=f"Packs directory (default: {DEFAULT_PACKS_DIR})",
    )
    p_idx.add_argument(
        "--no-packs", action="store_true",
        help="Disable pack discovery (core low-signal types only)",
    )
    p_idx.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without mutating the graph.",
    )
    p_idx.add_argument("-v", "--verbose", action="store_true")

    p_diag = sub.add_parser(
        "diagnose",
        help="Trace retrieval stages for a question (no LLM call, read-only)",
    )
    p_diag.add_argument("question", type=str)
    p_diag.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_diag.add_argument("--top-k", type=int, default=30)
    p_diag.add_argument("--rerank-top-k", type=int, default=20)
    p_diag.add_argument("--full", action="store_true",
                        help="Include full hit payloads (default: summary counts)")
    p_diag.add_argument("--expected-docs", type=str, default=None,
                        help="Comma-separated filename-prefix list to track retention")
    p_diag.add_argument("--store", type=Path, default=Path("store"))
    p_diag.add_argument("-v", "--verbose", action="store_true")

    p_corpus = sub.add_parser(
        "diagnose-corpus",
        help="Corpus stats — counts per entity type, degree, chunks per doc",
    )
    p_corpus.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    p_corpus.add_argument("-v", "--verbose", action="store_true")

    p_query = sub.add_parser("query", help="Query the extracted knowledge graph")
    p_query.add_argument("question", type=str, help="Natural-language question")
    p_query.add_argument(
        "--mode", choices=QUERY_MODES, default="hybrid",
        help=f"Retrieval mode (default: hybrid). One of: {', '.join(QUERY_MODES)}",
    )
    p_query.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
        help=f"LightRAG working directory (default: {DEFAULT_WORKING_DIR})",
    )
    p_query.add_argument(
        "--json", action="store_true",
        help="Emit JSON with answer + referenced document_ids",
    )
    p_query.add_argument("-v", "--verbose", action="store_true")

    return parser


def _resolve_corrections_root(explicit: Path | None, default_parent: Path) -> Path:
    return explicit if explicit is not None else default_parent.parent / "corrections"


def _emit_entity_type_corrections(graph_snapshot: dict, corrections_root: Path) -> int:
    """Emit/update entity-type bucket files. Returns # buckets written."""
    buckets = emit_entity_type_buckets(graph_snapshot)
    for bucket in buckets:
        existing = load_entity_type_bucket(corrections_root, bucket.bucket)
        merged = merge_entity_type_bucket(existing, bucket.entries, bucket=bucket.bucket)
        save_entity_type_bucket(corrections_root, merged)
    return len(buckets)


def _emit_alias_corrections(ambiguous_groups: list[list[str]], corrections_root: Path) -> int:
    fresh = emit_alias_corrections(ambiguous_groups=ambiguous_groups)
    for c in fresh:
        existing = load_alias_correction(corrections_root, c.cluster)
        merged = merge_alias_correction(existing, c)
        save_alias_correction(corrections_root, merged)
    return len(fresh)


async def _run_extract(store_root: Path, working_dir: Path,
                       corrections_root: Path | None,
                       packs_dir: Path | None, no_packs: bool,
                       no_focus_hints: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    packs = _load_packs(packs_dir, no_packs)
    config = _config_with_packs(config, packs)
    # `--no-focus-hints` skips only the extraction hints; packs still
    # contribute taxonomy + structured injection.
    focus_packs = [] if no_focus_hints else packs

    docs = discover_store_docs(store_root)
    if not docs:
        print(f"No ingested docs found under {store_root}", file=sys.stderr)
        return 1

    resolved_corr = _resolve_corrections_root(corrections_root, store_root)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        inserted = await extract_documents(
            rag, docs, corrections_root=resolved_corr, packs=focus_packs,
        )
        pp_stats = await post_process(rag, allowed_entity_types=config.entity_types)
        stats = await graph_stats(rag)
        snapshot = await snapshot_nodes(rag)
    finally:
        await rag.finalize_storages()

    buckets_written = _emit_entity_type_corrections(snapshot, resolved_corr)

    report = {
        "inserted": inserted,
        "post_process": pp_stats,
        "graph": stats,
        "corrections": {
            "entity_type_buckets_written": buckets_written,
            "root": str(resolved_corr),
        },
        "packs": [{"name": p.name, "version": p.version,
                   "declared_types": getattr(p, "declared_types", [])}
                  for p in packs],
        "config": {
            "llm_model": config.llm_model,
            "embed_model": config.embed_model,
            "entity_types": config.entity_types,
            "language": config.language,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_annotate_temporal(store_root: Path, working_dir: Path, dry_run: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        report = await annotate_temporal(rag, store_root, dry_run=dry_run)
    finally:
        await rag.finalize_storages()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_dedupe(working_dir: Path, threshold: float, apply: bool,
                      corrections_root: Path | None) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()  # fail fast; embedding stack reused from extraction

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    resolved_corr = _resolve_corrections_root(corrections_root, working_dir)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        report = await resolve_aliases(
            rag, config, threshold=threshold, dry_run=not apply,
        )
    finally:
        await rag.finalize_storages()

    ambiguous = report.get("ambiguous_groups", [])
    alias_files_written = _emit_alias_corrections(ambiguous, resolved_corr)
    report["corrections"] = {
        "alias_files_written": alias_files_written,
        "root": str(resolved_corr),
    }
    # Drop the raw groups from the summary now that they're persisted.
    report.pop("ambiguous_groups", None)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_extract_structured(store_root: Path, working_dir: Path,
                                  packs_dir: Path | None, no_packs: bool,
                                  dry_run: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    packs = _load_packs(packs_dir, no_packs)
    if not packs:
        print("No packs active — nothing to do.", file=sys.stderr)
        return 1

    docs = discover_store_docs(store_root)
    if not docs:
        print(f"No ingested docs under {store_root}.", file=sys.stderr)
        return 1

    from corrections.io import load_source_correction
    from corrections.overlay import resolve_content

    corrections_root = _resolve_corrections_root(None, store_root)

    # Collect (pack, result) pairs. Core never inspects `result`; it's
    # opaque pack-owned data handed back to the pack for injection.
    pack_results: list[tuple[object, dict]] = []
    per_doc_stats = []
    for md_path, meta in docs:
        raw = md_path.read_text(encoding="utf-8")
        correction = load_source_correction(corrections_root, meta["document_id"])
        content = resolve_content(raw, correction, corrections_root)
        for pack in packs:
            extractor = getattr(pack, "extract_structured", None)
            if not callable(extractor):
                continue
            result = extractor(meta, content)
            if result is None:
                continue
            pack_results.append((pack, result))
            per_doc_stats.append({
                "document_id": meta["document_id"],
                "pack": pack.name,
                "kind": result.get("kind", "unknown"),
            })

    report = {
        "docs_scanned": len(docs),
        "results_found": len(pack_results),
        "per_doc": per_doc_stats,
        "dry_run": dry_run,
    }

    if not dry_run and pack_results:
        rag = await build_rag(working_dir=working_dir, config=config)
        try:
            mutations: list[dict] = []
            for pack, result in pack_results:
                hook = getattr(pack, "inject_structured", None)
                if not callable(hook):
                    continue
                m = await hook(rag, result)
                mutations.append({"pack": pack.name, **m})
        finally:
            await rag.finalize_storages()
        report["mutations"] = mutations

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_emit_corrections(working_dir: Path, corrections_root: Path | None,
                                threshold: float) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    resolved_corr = _resolve_corrections_root(corrections_root, working_dir)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        snapshot = await snapshot_nodes(rag)
        dedupe = await resolve_aliases(
            rag, config, threshold=threshold, dry_run=True,
        )
    finally:
        await rag.finalize_storages()

    entity_buckets = _emit_entity_type_corrections(snapshot, resolved_corr)
    alias_files = _emit_alias_corrections(
        dedupe.get("ambiguous_groups", []), resolved_corr,
    )

    print(json.dumps({
        "corrections_root": str(resolved_corr),
        "entity_type_buckets": entity_buckets,
        "alias_files": alias_files,
        "graph_entities": len(snapshot),
    }, indent=2))
    return 0


def _plan_to_dict(plan) -> dict:
    return {
        "type_changes": [
            {"name": c.name, "old_type": c.old_type, "new_type": c.new_type}
            for c in plan.type_changes
        ],
        "merge_ops": [
            {"canonical": op.canonical, "sources": list(op.sources)}
            for op in plan.merge_ops
        ],
        "warnings": plan.warnings,
    }


async def _run_apply_corrections(working_dir: Path, corrections_root: Path | None,
                                 apply: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    resolved_corr = _resolve_corrections_root(corrections_root, working_dir)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        snapshot = await snapshot_nodes(rag)
        buckets = list_entity_type_buckets(resolved_corr)
        aliases = list_alias_corrections(resolved_corr)
        plan = build_plan(snapshot, buckets=buckets, aliases=aliases)

        report = {
            "corrections_root": str(resolved_corr),
            "dry_run": not apply,
            "plan": _plan_to_dict(plan),
            "summary": plan.summary(),
        }

        if apply and not plan.is_empty():
            mutation = await apply_derivation_plan(rag, plan)
            report["mutation"] = mutation
    finally:
        await rag.finalize_storages()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def _build_id_to_filename(store_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not store_root.exists():
        return mapping
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir():
            continue
        mp = entry / "metadata.json"
        if not mp.is_file():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "document_id" in m and "original_filename" in m:
            mapping[m["document_id"]] = m["original_filename"]
    return mapping


async def _run_enhance_retrieval(store_root: Path, working_dir: Path,
                                 packs_dir: Path | None, no_packs: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    packs = _load_packs(packs_dir, no_packs)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        report = await write_doc_summary_chunks(rag, store_root, packs=packs)
    finally:
        await rag.finalize_storages()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_build_indexes(store_root: Path, working_dir: Path,
                             min_docs: int, min_entities: int,
                             dry_run: bool,
                             packs_dir: Path | None, no_packs: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    packs = _load_packs(packs_dir, no_packs)

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        report = await write_index_nodes(
            rag, store_root,
            min_docs_for_profile=min_docs,
            min_entities_for_catalog=min_entities,
            dry_run=dry_run,
            packs=packs,
        )
    finally:
        await rag.finalize_storages()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_diagnose(question: str, working_dir: Path, top_k: int,
                        rerank_top_k: int, full: bool,
                        expected_docs: str | None, store_root: Path) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    id_to_filename = _build_id_to_filename(store_root)
    expected_list = [p.strip() for p in (expected_docs or "").split(",") if p.strip()]

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        trace = await trace_query(
            rag, question,
            top_k=top_k, rerank_top_k=rerank_top_k,
            expected_documents=expected_list,
            id_to_filename=id_to_filename,
        )
    finally:
        await rag.finalize_storages()

    if full:
        report = {
            "question": trace.question,
            "expected_documents": trace.expected_documents,
            "stages": [
                {
                    "stage": s.stage,
                    "hit_count": len(s.hits),
                    "expected_seen": s.expected_docs_seen,
                    "expected_missing": s.expected_docs_missing,
                    "hits": s.hits[:10],   # cap for readability
                }
                for s in trace.stages
            ],
        }
    else:
        report = trace.summary()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


async def _run_diagnose_corpus(working_dir: Path) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(f"No extraction store at {working_dir}. Run `extract` first.", file=sys.stderr)
        return 1

    from collections import Counter, defaultdict
    from extraction.provenance import parse_document_ids

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        kg = rag.chunk_entity_relation_graph
        labels = await kg.get_all_labels()
        type_count: Counter = Counter()
        type_degrees: dict[str, list[int]] = defaultdict(list)
        type_docs_touched: dict[str, set] = defaultdict(set)
        docs_touched_overall: set = set()
        for name in labels:
            node = await kg.get_node(name)
            if node is None:
                continue
            t = node.get("entity_type") or "null"
            type_count[t] += 1
            edges = await kg.get_node_edges(name) or []
            type_degrees[t].append(len(edges))
            doc_ids = parse_document_ids(node.get("document_ids"))
            for d in doc_ids:
                type_docs_touched[t].add(d)
                docs_touched_overall.add(d)
    finally:
        await rag.finalize_storages()

    rows = []
    for t, n in sorted(type_count.items(), key=lambda x: -x[1]):
        degrees = type_degrees[t]
        rows.append({
            "type": t,
            "entities": n,
            "mean_degree": round(sum(degrees) / len(degrees), 2) if degrees else 0.0,
            "isolated": sum(1 for d in degrees if d == 0),
            "docs_with_type": len(type_docs_touched[t]),
        })
    report = {
        "total_entities": sum(type_count.values()),
        "total_docs_with_entities": len(docs_touched_overall),
        "types": rows,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_query(question: str, mode: str, working_dir: Path, as_json: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(
            f"No extraction store at {working_dir}. Run `extract` first.",
            file=sys.stderr,
        )
        return 1

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        result = await rag.aquery_llm(
            question,
            param=QueryParam(
                mode=mode,
                user_prompt=config.temporal_user_prompt,
            ),
        )
    finally:
        await rag.finalize_storages()

    llm_resp = result.get("llm_response") or {}
    answer = llm_resp.get("content") or ""
    refs = extract_references_from_query_result(result)
    answer = inject_references(answer, refs)

    doc_ids = extract_document_ids(answer)

    if as_json:
        print(json.dumps(
            {
                "question": question,
                "mode": mode,
                "answer": answer,
                "document_ids": doc_ids,
            },
            indent=2,
            ensure_ascii=False,
        ))
    else:
        print(answer)
        if doc_ids:
            print("\n=== Referenced documents ===")
            for d in doc_ids:
                print(f"  - {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "extract":
        return asyncio.run(_run_extract(
            args.store, args.working_dir, args.corrections_root,
            args.packs_dir, args.no_packs, args.no_focus_hints,
        ))
    if args.cmd == "annotate-temporal":
        return asyncio.run(_run_annotate_temporal(args.store, args.working_dir, args.dry_run))
    if args.cmd == "dedupe":
        return asyncio.run(_run_dedupe(
            args.working_dir, args.threshold, args.apply, args.corrections_root,
        ))
    if args.cmd == "emit-corrections":
        return asyncio.run(_run_emit_corrections(
            args.working_dir, args.corrections_root, args.threshold,
        ))
    if args.cmd == "apply-corrections":
        return asyncio.run(_run_apply_corrections(
            args.working_dir, args.corrections_root, args.apply,
        ))
    if args.cmd == "extract-structured":
        return asyncio.run(_run_extract_structured(
            args.store, args.working_dir, args.packs_dir, args.no_packs,
            args.dry_run,
        ))
    if args.cmd == "query":
        return asyncio.run(_run_query(args.question, args.mode, args.working_dir, args.json))
    if args.cmd == "enhance-retrieval":
        return asyncio.run(_run_enhance_retrieval(
            args.store, args.working_dir, args.packs_dir, args.no_packs,
        ))
    if args.cmd == "build-indexes":
        return asyncio.run(_run_build_indexes(
            args.store, args.working_dir,
            args.min_docs_for_profile, args.min_entities_for_catalog,
            args.dry_run, args.packs_dir, args.no_packs,
        ))
    if args.cmd == "diagnose":
        return asyncio.run(_run_diagnose(
            args.question, args.working_dir, args.top_k, args.rerank_top_k,
            args.full, args.expected_docs, args.store,
        ))
    if args.cmd == "diagnose-corpus":
        return asyncio.run(_run_diagnose_corpus(args.working_dir))

    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
