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
- End-to-end ingestion validated on 3 heterogeneous PDFs (1 office doc, 2 ID-type) + 1 unsupported format (`.pages`).
- Empirical sweep corrected an earlier assumption: **Docling does not skip OCR on ID-type PDFs** — the `ocrmac` plugin is auto-selected and text IS extracted. The failure mode is different: the layout analyzer wraps the whole page as a `picture` element, OCR'd text lands as children of that picture, and `export_to_markdown()` (which only walks the top-level body tree) emits just `<!-- image -->` placeholders.
- Added an `ExtractionQuality` classification on metadata (`rich` / `degraded` / `empty`) computed from the DoclingDocument structure (top-level vs. nested text counts).
- Added a fallback markdown renderer: on `degraded` docs, `content.md` is rebuilt from nested picture texts so the OCR output is actually usable.
- Batch CLI now surfaces unsupported files explicitly (was silently filtered).

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