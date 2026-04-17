# Project context — Personal Knowledge Graph Pipeline

## Vision
Building a structured knowledge base from heterogeneous sources (documents, repos, Confluence spaces, Jira tickets, etc.), exposed via an API, to power downstream applications. The project has dual purpose:
1. Personal tool (starting point): structure personal documents (invoices, insurance, bank statements, contracts)
2. Future B2B product for specialist audiences (small B2B niche) — must guarantee information coherence and provenance

## Core requirements
- **Provenance at the fact level**: every piece of information must be traceable back to its source (document, page, paragraph, ingestion date, version)
- **Contradiction detection**: if source A says X and source B says not-X, system must flag it, not average
- **Versioning**: updating a document must not erase history
- **Incremental reindexing**: adding a source must not break what exists
- **Stable API**: downstream apps consume this backend, so the interface contract must be clean and durable
- **Data portability**: no lock-in, open formats
- **Self-hosted / sovereign**: possibly sensitive data, especially for future B2B clients

## Research journey — tools evaluated and rejected/selected

### Evaluated and rejected
- **claude-obsidian plugin**: Karpathy's LLM Wiki pattern implementation. Good for continuous personal note-taking, but too expensive in tokens for batch document ingestion. No clean API. No fact-level provenance. Not suitable as product backend. Could be useful as personal meta-project journal only.
- **AnythingLLM**: desktop app with RAG. Classic vector RAG (not GraphRAG). Fine UI but exactly the limitations the project wants to avoid (chunks, not structured knowledge).
- **NotebookLM (Google)**: good for quick testing but not self-hosted, no API for downstream apps.
- **Onyx (ex-Danswer)**: strong contender for enterprise search with 40+ native connectors (Confluence, Jira, GitHub, etc.). Vector RAG only. Good fallback option but doesn't give the graph/provenance depth the project needs.

### Selected approach — layered pipeline, fully owned
Rather than a single product, the project uses a layered architecture:

**Layer 1 — Multi-format ingestion**
- **Docling (IBM Research)** selected as primary engine. MIT license. Fully local, auto-contained, no external LLM calls. Handles PDF, DOCX, PPTX, XLSX, HTML, images, audio, LaTeX. Produces structured DoclingDocument preserving semantic hierarchy.
- **ocrmac** (Apple Vision wrapper) for edge cases where Docling fails (ID cards, driver's licenses — validated empirically: Docling layout analyzer classifies these as "image" and skips OCR; ocrmac direct works perfectly).
- **Architecture**: dispatcher routing by document type → Docling for office docs, ocrmac for card-type docs.

**Layer 2 — Knowledge graph storage**
- **Neo4j** chosen over Kùzu for schema flexibility (heterogeneous domains: tech/software + vertical domains + research content). Stores entities, relationships, with provenance properties on each node and edge.
- **Qdrant** in parallel for vector embeddings (hybrid search).

**Layer 3 — Graph construction**
- **LightRAG** used as library (not server) for entity/relationship extraction from clean text.
- **RAG-Anything** considered as multimodal extension to LightRAG if needed.
- Wrapping LightRAG extraction to add custom provenance and versioning layer.

**Layer 4 — Source connectors**
- `atlassian-python-api` for Confluence/Jira
- GitHub API for repos
- Filesystem watcher for local docs
- Each connector tags source in metadata at ingestion time

**Layer 5 — API**
- **FastAPI** exposing: `/search` (hybrid graph + vector), `/entity/{id}`, `/provenance/{fact_id}`, `/diff` (contradiction detection)

## Downstream workflow vision (future)
Beyond the knowledge API, planned orchestration layer using **LangGraph** with:
- User request
- User-specific business rules
- Knowledge API (the structured backend)
- "Lessons learned" memory (scoped, versioned, human-validated)
- Multiple processing nodes (deterministic + LLM calls)
- Output with full provenance chain

**Cost concern flagged**: full workflow executions can reach 0.15–0.60 USD per user request with naive approach. Mitigation: route simple nodes to cheaper models (Haiku), aggressive prompt caching, load only necessary graph subsets per query.

**Rules engine**: deterministic engine (JSON Logic / GoRules) for hard constraints (compliance, validations), JSON-injected soft rules in prompts for preferences. Never rely on LLM alone to respect critical rules — always verify output.

**Memory pitfall to avoid**: lessons must be explicit, scoped, versioned, with human validation before storage. Consider Mem0 or Letta for memory layer, or custom Neo4j nodes (`:Lesson`).

**Evaluation layer is mandatory**: dataset of 50–200 real cases with expected outputs, metrics per node, observability tool (LangSmith native to LangGraph, or Langfuse open-source alternative). Without this, the whole architecture is unmaintainable.

## Strategic principles agreed
1. Start with user's own documents as first client (dogfooding)
2. Decouple knowledge backend from workflow engine from day one (LangGraph may be replaced by Burr, LlamaIndex Workflows, Pydantic AI, etc.)
3. Build eval layer before memory layer
4. Never code a layer whose need hasn't been empirically observed
5. Defer multi-tenancy until multiple real users exist
6. Defer UI until API is validated
7. Defer automatic contradiction detection to v2

## Current phase: V0 — Ingestion module
Starting with personal documents (invoices, bank statements, insurance, contracts) to:
- Validate the full pipeline end-to-end on known data
- Discover real-world issues (OCR quality, table extraction, entity resolution, versioning)
- Build reusable foundation
- Serve as dogfooding environment

V0 scope strictly limited to ingestion module (Docling + local filesystem storage + metadata). Entity extraction, graph construction, and API come after V0 validation.

### V0 progress (2026-04-16)
- End-to-end ingestion validated on 9 heterogeneous PDFs (7 `rich` office docs: invoice, bank statement, insurance proposal, sale compromis, tax declarations/notices; 2 `degraded` ID-type: passport, identity card) + 2 unsupported formats (`.pages`, `.ods`).
- Empirical sweep corrected an earlier assumption: **Docling does not skip OCR on ID-type PDFs** — the `ocrmac` plugin is auto-selected and text IS extracted. The failure mode is different: the layout analyzer wraps the whole page as a `picture` element, OCR'd text lands as children of that picture, and `export_to_markdown()` (which only walks the top-level body tree) emits just `<!-- image -->` placeholders.
- Added an `ExtractionQuality` classification on metadata (`rich` / `degraded` / `empty`) computed from the DoclingDocument structure (top-level vs. nested text counts).
- Added a fallback markdown renderer: on `degraded` docs, `content.md` is rebuilt from nested picture texts so the OCR output is actually usable.
- Batch CLI now surfaces unsupported files explicitly (was silently filtered).

### Layer 3 spike — LightRAG entity extraction (2026-04-16)
Ran under `spikes/lightrag_extract.py`. Library-mode LightRAG, Google Gemini 2.5 Flash via OpenRouter (picked for perf/price + no hidden CoT = budget-predictable), local multilingual MiniLM embeddings (384-dim, sovereign/offline). No Neo4j — LightRAG's default file-backed store. Two passes:

- **n=2 (1 rich + 1 degraded)**: 222 entities, 196 with edges. Passport entities surfaced cleanly despite `degraded` quality — **the V0 debt does not block Layer 3**.
- **n=9 (full corpus)**: 795 entities, 649 with edges (82%), 146 isolated. Queries produced production-adjacent answers: 10 named people with roles and source docs, 20 organizations categorized by domain, full fiscal recap (revenus, avis d'imposition, composition foyer), full compromis-de-vente decomposition (diagnostics, servitudes, financement). Cross-document synthesis worked (same person identified across invoice, insurance proposal, passport, tax notice).

Cost: ~$0.05-0.10 for the n=9 extraction. Affordable dogfooding.

**Gaps observed** — all solvable in the wrapper layer, none blocking the architecture:
1. 🔴 **No fact-level provenance on nodes/edges**. LightRAG tracks source at chunk level but the entity-relation tuples themselves carry no `source_doc_id` / `chunk_id`. This is the core V0 promise. Must be injected by wrapping LightRAG's insertion path.
2. 🔴 **Entity type inflation**: 10 types at n=2 → 26 at n=9, with 6 singleton types invented ad-hoc (`lighting`, `creature`, `route`, `furniture`…). `concept` (215) + `data` (175) = 49% of entities — catch-all buckets swallow real signal. Fix: constrain taxonomy in extraction prompt (`person | organization | location | date | amount | document | concept`).
3. ⚠️ **Fragmentation**: case/accent variants create duplicate nodes (`Les Adrets` vs `LES ADRETS`, `Système Ouvert` vs `Systeme Ouvert`). Needs a normalization step on entity names.
4. ⚠️ **Noise entities**: line-item numeric fragments extracted as entities (`Value 1`, `1,40 Value`, `TVA Code 1`). Prompt tuning or min-degree filter.
5. ⚠️ **LightRAG `pipmaster` auto-installs `openai`** on first run — supply-chain surprise. Pin `openai` in the venv and look for a flag to disable.

**Decisions from the spike**:
- LightRAG + Gemini 2.5 Flash + local multilingual embeddings is the validated Layer 3 stack.
- The wrapper anticipated by intent.md (*"Wrapping LightRAG extraction to add custom provenance and versioning layer"*) is now concrete: inject provenance properties + constrain type vocabulary via the extraction prompt override. Both are the scope of the next phase.

## Validated technical decisions so far
- Python 3.13 in venv
- Docling 2.88.0 works well on office documents (tested on invoice: `rich` quality, clean output)
- Docling on ID-type PDFs: produces `degraded` output — text is OCR'd but buried under picture nodes, recovered by the fallback renderer (validated on passport + identity card scans)
- ocrmac with Apple Vision (`fr-FR` language) gives excellent results on French administrative documents; reachable both via Docling's internal `ocrmac` plugin and — if ever needed — as a direct library call
- MPS acceleration available on the dev Mac
- Storage strategy for V0: local filesystem with `store/{document_id}/` containing metadata.json, content.json (Docling native), content.md, and copy of original file

## Known debt (V0)
- **`degraded` extraction quality**: currently accepted as-is for ID-type documents. The fallback markdown is serviceable but is a flat dump of OCR lines grouped per picture — no structural recovery (no key/value pairs, no logical ordering beyond picture traversal). Acceptable for V0 dogfooding. Revisit when Layer 3 (entity extraction) shows whether it's good enough for the graph or whether a dedicated ocrmac dispatcher producing cleaner linear text is needed.
- **`.pages` and other proprietary formats**: reported as `unsupported`, no conversion path. Out of V0 scope; add only when a real need surfaces.

---

## Architectural pivot (2026-04-17): core + packs, no domain in core

Dogfooding on personal docs was starting to pull the design toward
domain-specific typed schemas baked into core (Person/Address/Residence,
a personal-finance category taxonomy, bank-statement extractors). That
would have re-solved the problem for every new client/domain.

Revised shape:

```
┌─────────────────────────────────────────────────────┐
│ PACKS (optional, per-domain, shipped separately)    │
│   personal-finance: Transaction, Category, BankExtr │
│   legal:            Contract, Clause, PartyRole     │
│   research:         Paper, Citation, Author         │
│   → declare matchers + schemas; pluggable           │
├─────────────────────────────────────────────────────┤
│ CORE — domain-agnostic                              │
│   • alias resolution (embedding + lexical guards)   │
│   • temporal precedence (sourced-date annotations)  │
│   • retrieval reranking (cross-encoder)             │
│   • evidence/provenance (document_ids everywhere)   │
│   • eval harness (measurable floor per graph state) │
│   • pack framework (registry + discovery)           │
├─────────────────────────────────────────────────────┤
│ EVIDENCE — LightRAG + chunks + content.md           │
└─────────────────────────────────────────────────────┘
```

**Only CORE is required.** Packs are plugins. A graph with no matching
pack is still queryable — just less structured. If the product pivots
to a B2B legal client tomorrow, the personal-finance pack is dropped
and a `legal` pack added; core stays untouched.

## Phases delivered (2026-04-17)

- **Phase 0 — eval harness** (`evaluation/`): 3 gold-standard seed Q/A
  cases from real dogfooding, pure substring/set scoring, multi-run
  aggregation with cache purge between runs. Measurable floor for every
  future change. On this corpus, retrieval is deterministic given a
  stable graph — stddev across runs is 0.00, so single-run eval is
  trustworthy per graph state.
- **Reranker** (`extraction/rerank.py`): local cross-encoder
  (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` by default, ~117 MB).
  Deterministic, multilingual, addresses retrieval-variance directly.
  The `aggregation-expenses` case now surfaces the bank doc which
  vector similarity alone was dropping.
- **Phase 1 — alias resolution** (`extraction/alias.py`): embedding
  clustering + lexical-containment guard + ambiguity detector. 29 safe
  merges on 911 entities in the dogfood corpus; four surface forms of
  `Sébastien Boutet` correctly consolidate; three `Plan de Prévention
  des Risques …` variants correctly stay split.
- **Phase 2 — temporal annotations** (`extraction/temporal.py`):
  prefixes every node/edge description with `[sourced: YYYY-MM-DD, …]`
  from `document_ids → document_date`. 866 nodes + 924 edges annotated.
  `mean entity_coverage 0.89 → 1.00`, `mean fact_coverage 0.67 → 1.00`
  on the eval seed. The "most recent address" query now correctly
  returns Roquefort-les-Pins (2026-03-26), not the compromis-era Cagnes.
- **Phase 3 — pack framework** (`packs/`): `Pack` protocol,
  `PackRegistry`, filesystem `discover_packs(dir)`. No packs yet — the
  framework is ready for Phase 4.

## Design principles respected

- Generic core; no domain-specific types or rules anywhere outside
  `packs/<name>/`.
- Progressive refinement: alias resolution and relation-type induction
  are corpus-driven, not rule-driven. More docs → better graph.
- Minimal hardcoded precedence: only temporal ordering (newer sourced
  date wins for time-varying facts). Every other priority is emergent
  or pack-owned.
- Eval before tuning: any future phase moves measured numbers on the
  seed cases, or it doesn't land.

## Phases remaining

- **Phase 4** — first pack (personal-finance) under `packs/personal_finance/`
  implementing a bank-statement extractor + Transaction/Category
  schema. Validates the pack interface; fixes the
  `aggregation-expenses` case deterministically (no LLM guessing from
  scattered amount literals).
- **Phase 5** — relation-type induction: cluster edge descriptions
  across the graph to surface candidate predicates. Feeds both the
  emergent-schema UX and typed supersedes edges.