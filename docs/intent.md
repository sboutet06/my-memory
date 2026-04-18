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

---

## Human-in-the-loop architecture (agreed 2026-04-18)

Every layer of the pipeline must accept human correction. Core design
principles, agreed before implementation:

### Three correction layers (distinct, don't conflate)

```
┌──────────────────────────────────────────────────┐
│ MEMORY / business rules    (workflow layer)      │
│   "tax threshold is X for 2026"                  │
│   applied at QUERY / workflow time, per session  │
├──────────────────────────────────────────────────┤
│ DERIVATION corrections     (graph layer)         │
│   "Gabriel is person, not concept"               │
│   "these two never merge; those always do"       │
│   applied POST-extraction                        │
├──────────────────────────────────────────────────┤
│ SOURCE corrections         (ingestion layer)     │
│   "Compromis document_date = 2016-05-13"         │
│   "Passport OCR: CEUNE → CEDRES"                 │
│   "mark doc obsolete / replaced-by <other>"      │
│   applied at INGESTION / persist                 │
└──────────────────────────────────────────────────┘
```

Source is the cleanest starting point: one fix at source prevents N
downstream derived errors. Derivation handles cases where source is
fine but a heuristic/LLM got it wrong. Memory is durable cross-session
rules applied at query/workflow time.

### Unified correction pattern (same at every layer)

1. **Seeded doubts**. Pipeline emits its own uncertainty as structured
   candidate entries — the user does not face a blank page. Each
   intervention point has observable signal the pipeline already has:
    - ingestion: `document_date=None`, low-confidence pick, `degraded` quality, unsupported extension
    - extraction: entity-type remapped to `concept` fallback
    - alias: ambiguous cluster, borderline cosine (0.80–0.85)
    - packs: pack-defined uncertainties
    - memory: rule conflicts, missing rules
2. **YAML-first human UX**. Each correction point is a YAML file on
   disk. Git-versioned, diffable, PR-reviewable, hand-editable,
   machine-generateable, degrades gracefully to a future GUI wrapper.
3. **Doubts + overrides in one file**. User reads the app's reasoning
   and inferred value, edits the `overrides` section, flips
   `status: pending` → `reviewed`. Empty overrides = accept inferred.
4. **Non-blocking**. Unresolved pending corrections don't gate the
   pipeline — the graph keeps running on inferred values. Optional
   `--strict` mode much later if anyone asks.
5. **Idempotent on re-apply**. Applying corrections N times yields
   identical state (required for determinism and re-ingestion).
6. **Only emit doubts that matter**. A doc with clean extraction gets
   no corrections file. Silence > noise.

### Directory layout

```
corrections/
  source/
    {document_id}.yaml     ← ingestion-layer doubts + overlay
  derivation/
    entity_types.yaml
    aliases.yaml           ← merge veto / affirm
  packs/
    {pack_name}/*.yaml     ← pack-specific
  memory/
    rules.yaml             ← workflow layer (Phase 6)
```

### Seeded-YAML example

```yaml
document_id: 5905ca2e-...
original_filename: Compromis MrMme BOUTET.pdf
status: pending

doubts:
  - field: document_date
    inferred_value: 2016-05-13
    confidence: medium
    rationale: |
      Heuristic found `FAIT à CHATEAUNEUF Le 13 mai 2016` in footer.
      Other 2016 dates present are diagnostic / transaction dates,
      not compromis signing.
    suggested_action: confirm

overrides:
  metadata: {}              # document_date: 2016-05-13 (uncomment to override)
  content_replacements: []
  tags: []
  replaced_by: null
```

### Pushbacks (don't drift)

- **Keep core schema tiny (5–6 fields).** Packs extend via pydantic.
- **Never let YAML get clever.** Flat where possible; no templating.
- **Corrections never re-write `store/`.** Original Docling output
  stays immutable; corrections are an overlay consulted downstream.

---

## Phases delivered (2026-04-18 continued)

### Phase 3.5 — corrections framework (source layer)
`corrections/` package. Pydantic schemas (Doubt, SourceCorrection),
YAML round-trip with inline hint comments on every user-editable field
(ruamel.yaml — humans never have to remember allowed values), idempotent
merge that preserves user overrides when the pipeline re-emits doubts.
Ingestion hook writes `corrections/source/{doc_id}.yaml` when Docling
produces missing dates / degraded / empty quality / unsupported format.
`python -m corrections review [--all]` CLI.

### Phase 3.6 — derivation corrections
Entity-type buckets (batch YAML per reason: `concept_fallback`,
`remapped_singletons`) + one-file-per-cluster alias corrections under
`corrections/derivation/`. Taxonomy enforcer now preserves
`original_entity_type` so singletons stay inspectable; `cluster_entities`
exposes ambiguous groups. CLI extended: `review source|entity-types|
aliases`, `show <slug-or-doc-id>`, `stats`. `python -m extraction
emit-corrections` snapshots the graph offline (no re-extract).

### Phase 3.7 — apply derivation corrections
Pure planner `build_plan(graph, buckets, aliases) → Plan(type_changes,
merge_ops, warnings)`. Async mutator runs the plan against LightRAG via
`upsert_node` + `amerge_entities`. `python -m extraction apply-
corrections [--dry-run | --apply]`. E2E on a copy of the real graph:
`sebastien_boutet` split, `plan_de_prevention_des_risques` merge, one
type override — idempotent re-run produces empty plan with warnings.

### Phase 4 — personal_documents pack
First pack, installed under `packs/personal_documents/`. Declares 22
life-domain entity types (object, vehicle, property, animal; medication,
diagnosis, procedure, body_part, medical_provider; employer, role,
skill; account, transaction_category; ingredient, dish, nutrient,
cooking_technique; event, activity, trip, accommodation). Core adds
`compose_entity_types(base, packs)` — case-insensitive union, core wins
on conflict. Pack auto-discovered via `./packs/` scan, opt-out with
`--no-packs`. On the 18-doc corpus, `concept_fallback` ratio dropped
33% → 21% after re-extract; 18 of 22 pack types populated.

### Phase 4.5 — first structured extractor
`packs/personal_documents/schemas/transaction.py` + `extractors/
bank_statement.py`: deterministic regex parser for French `RELEVE DE
COMPTE` tables produces `Transaction` records; debit/credit totals
matched the bank's printed `TOTAL` row exactly (914,00 / 540,00).
`extraction/structured.py::inject_transactions` writes them as
human-readable graph nodes via LightRAG's public `acreate_entity /
acreate_relation` API so they land in both the graph and the entity
vector DB. Adds `transaction`, `transaction_category` (summary
aggregate), `account`, `document` node kinds — the latter names embed
`/store/<uuid>/` so LLM citations survive regex parsing back into
doc_ids. `python -m extraction extract-structured [--dry-run]`.
Closes `aggregation-expenses` eval case from 0.00 → 1.00 doc_coverage.

### Phase 4.6 — OCR routing via corrections
`overrides.ocr_backend` + `overrides.content_md_override_path` on the
source correction. `ingestion/ocr_backends.py::run_ocrmac_on_pdf`
renders each PDF page via pdf2image at 200 dpi, OCRs with Apple Vision
(French first). `python -m ingestion reocr <doc_id> [--backend ocrmac]`
writes corrected markdown to `corrections/source/<doc_id>.md`, updates
the correction YAML. `corrections.overlay.resolve_content` returns the
corrected body when present; `extract_documents` consumes it. On
Certificat Benjamin (degraded Docling, no date): 945 → 1802 chars,
document_date populated via user-edited overlay.

### Eval surface expansion — 3 → 11 cases (commit 7e653c1)
Added: `children-medical-history`, `prescribed-medications`,
`employment-intel`, `owned-vehicles`, `tax-timeline`,
`family-composition`, `property-acquisition-price`,
`identity-documents`. Cases cover every life-domain present in the
corpus; gate every future phase against this suite.

### Phase 5.1 — retrieval diagnostics
`extraction/diagnostics.py` + `python -m extraction diagnose
"<question>"` + `python -m extraction diagnose-corpus` + `python -m
evaluation --diagnose [--case <id>]`. Zero behavior change — probes
`entity_vdb / chunks_vdb / relationships_vdb / rerank` per query and
reports per-stage retention of `expected_documents`. Revealed the
dominant bottleneck: **entity and relation vdbs find target docs
reliably, but chunks_vdb drops them silently** and the reranker only
trims the chunks_vdb subset.

### Phase 5.2 — per-doc summary chunks
`extraction/retrieval_enhance.py::write_doc_summary_chunks` upserts one
compact summary per doc into chunks_vdb — filename + filename tokens +
date + id + key (non-numeric) entity names + pack-produced structured
highlights. Deliberately NO body-content head (competition with
Docling content chunks measurably regressed eval). `python -m
extraction enhance-retrieval`. chunks_vdb retention went from ~50% of
target docs to ~85%.

### Phase 5.4 — answer-shaped index nodes
`extraction/index_nodes.py`: pure planner emitting **Profile:\<name\>**
for every entity with ≥N docs and **Catalog:\<entity_type\>** for every
declared type with ≥M entities across ≥N docs. Descriptions embed
`/store/<uuid>/` paths. 41 → 68 index nodes across the 32-doc corpus;
fully corpus-agnostic (no filenames, entity names, or query phrases in
the builder). `python -m extraction build-indexes [--dry-run]`.
Philosophical shift recorded: the KG is now a **retrieval cache** as
much as a semantic model — user approved since surface area is
corrections/rules/memory/queries, not raw graph nodes.

### temperature=0 fix (commit cfa7da8)
OpenRouter was load-balancing Gemini calls across provider instances
with different seeds, causing `run_all_multi` to report spurious
per-case deltas that single-runs contradicted. `extraction/llm.py`
defaults `temperature=0.0`. Two identical `python -m evaluation
--runs 1` invocations now produce byte-identical output; reliable
before/after metric for every future phase.

### Phase 5.5b — LLM document classifier
One call per doc at ingest time (~\$0.0005/doc), closed 13-tag
vocabulary (`work | healthcare | finance | property | vehicle | identity
| family | legal | education | travel | food | administrative |
other`), robust JSON parser, `DocumentMetadata.doc_context: list[str]`.
`python -m ingestion <path> [--no-classify]` opt-out for air-gapped
mode; `python -m ingestion classify [--doc-id X]` retroactively
classifies existing store. Tags propagate to summary chunks + per-doc
lines on Profile / Catalog entries. On all 32 docs, classifications
inspected and correct (passport→identity, payslip→work/finance,
medical cert→healthcare, etc.).

**Failed experiments worth recording** (not shipped):
  - Phase 5.3 (citation discipline prompt extension): net-regressed
    doc_coverage 0.40 → 0.28. Longer prompts dilute existing guidance.
  - Phase 5.5 (deriving doc-context from entity-type distribution):
    dossiers médicaux without enough `medication`/`diagnosis` entities
    mis-tagged `activity/animal/food`; tightening thresholds produced
    empty tags on most docs. Heuristics over extraction-noise counts
    generalize worse than a direct LLM classifier over the body.
  - Phase 5.5b's first shape (aggregated "Primary contexts" header in
    profiles): measured regression on cross-context queries
    (cross-doc-person 0.60 → 0.00); reverted to per-doc context only.

## Current state (end of 2026-04-18)

- **Tests**: 356 passing (`python -m pytest -q -m "not integration"`).
- **Corpus**: 32 docs across `raw/` (18) + `raw-2/` (14). Both
  ingested, extracted, summarized, indexed, classified.
- **Graph**: 2386 entities, 1902 edges in `extraction_store/`. 18 of
  22 pack types populated. 68 synthetic index nodes. 32 summary
  chunks. 50 structured transaction/account/document nodes.
- **Corrections pending**: 9 source, 2 entity-type buckets (450 entries),
  17 alias clusters.
- **Eval baseline** (temp=0, reproducible, 11 cases):
  - mean doc_coverage   = 0.62
  - mean entity_coverage = 0.86
  - mean fact_coverage   = 0.91
  - passing = 3/11 (aggregation-expenses,
    property-acquisition-price, identity-documents)
- **Commit trail** (most recent first):
  - `2c14ac6` — Phase 5.5b LLM doc classifier
  - `0809221` — gitignore raw-\*/
  - `cfa7da8` — temperature=0 for reproducible decoding
  - `7d1cbdf` — Phase 5.4 answer-shaped index nodes
  - `44f5a40` — Phase 5.2 per-doc summary chunks
  - `ea366f0` — Phase 5.1 retrieval diagnostics
  - `7e653c1` — 8 new eval cases across life-domains
  - `8eb8554` — Phase 4.6 OCR routing (ocrmac backend)
  - `d643b0a` — Phase 4.5 Transaction schema + bank extractor
  - `ff3e2a3` — Phase 4 personal_documents pack + type composition
  - `77aa50a` — Phase 3.7 apply derivation corrections
  - `510f6f8` — Phase 3.6 derivation corrections
  - `9ad5c26` — inline YAML hints via ruamel
  - `165852e` — Phase 3.5 source corrections

## Known weaknesses (measured, not yet addressed)

- **LLM citation format variability** — sometimes cites bare filenames
  instead of `/store/<uuid>/` paths; `extract_document_ids` then
  returns `[]` and doc_coverage drops to 0 even when the answer is
  substantively correct. Fixable by prompt tuning if needed, but carries
  overfitting risk (Phase 5.3 taught this).
- **Weak/inconsistent entity extraction on table-heavy docs** —
  payslips and tax forms yield mostly numeric entities; the pack's
  semantic types (role, employer, medication, etc.) are under-generated
  by the LLM on these docs. Classifier + answer-shaped indexes
  compensate but don't solve the root.
- **Cross-context drift with bigger corpora** — `cross-doc-person`
  regressed as more Intel work docs joined the corpus; the LLM fixates
  on the dense work cluster. Expected as corpora grow; addressable via
  better cross-context retrieval or query-intent hints.

## Phases remaining

- **Phase 5.3 (revisit)** — generic LLM-citation discipline. Options
  include: post-processing the answer to insert `/store/<uuid>/`
  references from cited entity/chunk IDs; or a tighter
  `temporal_user_prompt` extension (prior attempt regressed, so
  approach carefully with full 11-case measurement).
- **Phase 5 (original — relation-type induction)** — cluster edge
  descriptions to surface candidate predicates. Lower priority now
  that answer-shaped nodes handle aggregation queries; revisit when
  richer semantics are needed.
- **Phase 6 — memory / business rules** — workflow-layer `rules.yaml`
  applied at query time. Blocked on the workflow layer itself
  (LangGraph or similar).
- **FastAPI surface** (intent.md §48) — expose the KG via
  `/search`, `/entity/{id}`, `/provenance/{fact_id}`, `/diff`. KG is
  materially solid enough to start this.
- **Sovereign LLM** — swap OpenRouter/Gemini for a local backend
  (Gemma, llama.cpp, ollama) for the classifier + extraction + query
  LLM calls. Config change only; all call-sites go through
  `extraction/llm.py`.
- **Stronger per-doc-kind extraction** — use `doc_context` tags to
  route to specialized prompts (a payslip prompt that forces `role`
  and `employer` extraction; a medical prompt that forces `medication`
  and `diagnosis`). Natural next move but requires careful prompt
  engineering per doc-kind.

---

## Resuming in a fresh session — quick map

- **Repo root**: `/Users/sboutet/projects/my-memory`
- **Branch**: `master`, tree clean.
- **Tests**: `source venv/bin/activate && python -m pytest -q -m "not integration"` → 356 passing.
- **Corpus**: `raw/` + `raw-2/` = 32 docs, ingested in `store/`.
- **Extraction store**: `extraction_store/` — 2386 entities, 68 index nodes, 32 summary chunks.
- **Pipelines** (all local-only except LLM calls):
  - Ingest: `python -m ingestion <path> [--no-classify]`
  - Re-OCR: `python -m ingestion reocr <doc_id> [--backend ocrmac]`
  - Re-classify: `python -m ingestion classify [--doc-id X]`
  - Extract: `python -m extraction extract`
  - Dedupe: `python -m extraction dedupe [--apply]`
  - Emit corrections: `python -m extraction emit-corrections`
  - Apply corrections: `python -m extraction apply-corrections [--apply]`
  - Extract structured: `python -m extraction extract-structured [--dry-run]`
  - Enhance retrieval: `python -m extraction enhance-retrieval`
  - Build indexes: `python -m extraction build-indexes [--dry-run]`
  - Annotate temporal: `python -m extraction annotate-temporal`
  - Query: `python -m extraction query "..."`
  - Diagnose: `python -m extraction diagnose "..."` / `diagnose-corpus`
  - Review corrections: `python -m corrections review [source|entity-types|aliases] [--all]`
  - Show one correction: `python -m corrections show <slug-or-doc-id>`
  - Eval: `python -m evaluation --runs 3` (temp=0, reproducible)
  - Eval diagnostics: `python -m evaluation --diagnose [--case <id>]`
- **Latest eval (end-of-Phase-5.5b, temp=0)**: mean
  `doc_coverage = 0.62`, `ent_coverage = 0.86`, `fact_coverage = 0.91`;
  passing `3/11` (aggregation-expenses, property-acquisition-price,
  identity-documents).
- **Next action options**: see "Phases remaining" above — recommended
  starting direction on resume is either the sovereign LLM switch
  (infrastructure, unblocks other work) or the doc-kind-routed
  extraction prompts (measurable improvement on cases like
  employment-intel that have weak entity extraction).