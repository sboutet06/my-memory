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

---

## Session of 2026-04-18 — citation, retrieval, fragility

Opened with a codebase audit (Task #1) that surfaced three latent issues
and four candidate phases. All three issues fixed, two new phases
delivered, plus a scorer-fragility fix. `doc_coverage` climbed from
0.62 to 0.92 across the session; passing cases 3/11 → 7/11; 356 → 404
tests.

### Refactor — pack decoupling (commit 5300695)

`extraction/structured.py` was 100% bank-statement-specific code that
imported `packs.personal_documents.schemas.transaction` directly; core
also hardcoded `transaction` / `transaction_category` / `account` in
its `_LOW_SIGNAL_TYPES` filters, silently blocking any future pack from
shipping retrieval-infra types. Moved to
`packs/personal_documents/injector.py`. Three new optional Pack hooks:
- `low_signal_types: tuple[str, ...]` — unioned with core defaults at
  Profile/Catalog index time + summary-chunk filters.
- `async inject_structured(rag, result)` — pack owns its node/edge
  schema; core hands the opaque `extract_structured` dict back.
- `async summary_extras_for_doc(rag, doc_id)` — per-doc retrieval
  extras for `chunks_vdb` summaries.
`plan_index_nodes` gained `extra_low_signal_types`, and
`write_index_nodes` / `write_doc_summary_chunks` accept an optional
`packs` iterable. CLI wires packs through every post-processing step.

### Phase 5.3b — deterministic References injection (commit 14c9af9)

Diagnose pass across the 11 eval cases split failures into two buckets:
(a) real retrieval misses (Facture_250, Bulletin Paie, Déclaration
Impôts 2010 absent from rerank top-20), (b) citation-format drift (for
e.g. `owned-vehicles` the answer substance was perfect but the LLM's
trailing `### References` block used entity names like
`[4] Document d'Information Sur Le Produit d'Assurance AUTO`,
unparseable by `extract_document_ids`).

LightRAG's declared `include_references: bool = False` on `QueryParam`
is dead code (declared in `base.py`, never used in `operate.py`). The
real authoritative reference list lives on `aquery_llm().raw_data.data
.references` — `aquery` silently drops it for its "backwards-compat"
string return. Switch both `extraction query` and `evaluation.runner`
to `aquery_llm`; new module `extraction/references.py` parses the
references list and rewrites the answer's trailing References block
into canonical `- [n] /store/<uuid>/content.md` form. Idempotent,
preserves inline `[n]` refs, strips stale LLM-authored blocks.

Also fixed an eval-scoring bug surfaced along the way: macOS reports
filenames in NFD (`é` = `e` + `U+0301`) while `cases.json` authors edit
in NFC (`é` = `U+00E9`). `startswith()` silently returned False for
accented filenames — shaving doc_coverage for every case involving
`Déclaration Impôts`. NFC-normalize both sides in
`score_document_coverage`.

Measured impact: `doc_coverage 0.62 → 0.76`; `owned-vehicles 0.00 →
1.00`; `cross-doc-person 0.20 → 0.40`; `temporal-addresses 0.00 →
0.33`.

### Phase 5.6 — doc-kind-routed extraction hints (commit 0022d7d)

Payslips and tax forms extract mostly numeric entities even though the
pack taxonomy exposes `role`, `employer`, `medication`, etc. — the LLM
just doesn't force itself to use those types on table-heavy docs.

New pack hook `extraction_hints(metadata) → list[str]` maps a doc's
`doc_context` classifier tags (Phase 5.5b vocabulary) to a short focus
list. Core prepends one `[EXTRACTION FOCUS: …]` line to the doc body
before `rag.ainsert`. Generic in core; `packs/personal_documents/
focus.py` owns the `tag → types` table. Tag `other` deliberately maps
to nothing (no bad nudge on unclassified docs); focus list capped at 10
types for multi-tagged docs to keep prompt overhead bounded. Opt-out
via `python -m extraction extract --no-focus-hints` for ablation.

Full corpus re-extract cost ~\$0.35, ~8 min wall time. Backup of the
pre-5.6 graph kept at `extraction_store.pre-5.6/` for the session
(removed on confirmation).

Measured impact: `doc_coverage 0.76 → 0.85`; `ent_coverage 0.86 →
0.89`; passing 3/11 → 5/11. Flips:
- `children-medical-history 0.75 → 1.00` — healthcare hint forced
  `medication`/`diagnosis`/`medical_provider`.
- `employment-intel 0.50 → 1.00` — work hint pulled `role`/`employer`
  off the Bulletin Paie, long-standing retrieval miss resolved.
- `tax-timeline 0.33 → 0.67` — `Déclaration Impôts 2010` surfaced.

### Phase 5.7 — Profile/Catalog reference expansion (commit e8b5dc4)

Inspected `data.entities` on a cross-doc-person query: seven
`Profile: Sébastien …` variants were in the retrieved context (alias
resolution hadn't merged these synthetic nodes — only the underlying
entity names). Each contributed just its *primary* file_path to the
references list — LightRAG's `generate_reference_list_from_chunks`
reads `file_path` from CHUNKS only, dropping the breadth carried by
Profile/Catalog descriptions (which embed `/store/<uuid>/content.md`
paths for every member doc).

`extract_references_from_query_result` now also parses
`data.entities`: for every entity named `Profile: …` or `Catalog: …`,
pull `/store/<uuid>/` doc_ids out of its description and merge them
into the references list with new reference_ids (preserving the
chunk-derived primary indices). Dedups by doc_id.

### Scorer fragility — accent folding + OR alternatives (same commit)

Two silent eval fragilities:
- `Zoé` in `expected_entities` didn't match `Zoe` in the answer (common
  LLM unaccented drift) → owned-vehicles scored ent=0 despite correct
  content.
- `ordonnance` in `expected_facts` didn't match `prescription` in the
  LLM paraphrase → prescribed-medications scored fact=0 despite
  pertinent answer.

`_fold(s)` = NFKD decompose → strip combining marks → lowercase → trim;
any `|` in an expected entry splits into OR alternatives (one minimal
cases.json edit: `ordonnance` → `ordonnance|prescription`).

Measured impact (5.7 + fragility together):
`doc_coverage 0.85 → 0.92`, `ent_coverage 0.89 → 0.98`,
`fact_coverage 0.91 → 1.00`, passing 5/11 → 7/11. Flips:
`prescribed-medications`, `owned-vehicles`. Doc_coverage gains:
`cross-doc-person 0.40 → 0.80`, `temporal-addresses 0.33 → 0.67`
(Profile expansion doing its job).

### Tidy — configurable temperature (commit 02396a4)

`extraction/llm.py` hardcoded `kwargs.setdefault("temperature", 0.0)`.
Promoted to `ExtractionConfig.temperature` (default 0.0, env
`EXTRACTION_TEMPERATURE`). Default preserved — zero behavior change,
but unblocks sampling experiments and makes implicit behavior visible.

## Current state (end of 2026-04-18 session 2)

- **Tests**: 404 passing (`python -m pytest -q -m "not integration"`).
- **Corpus**: 32 docs across `raw/` (18) + `raw-2/` (14). Both
  ingested, extracted, summarized, indexed, classified.
- **Graph**: 2229 entities, 2060 edges in `extraction_store/` (after
  full Phase 5.6 re-extract with focus hints). 87 synthetic index
  nodes. 32 summary chunks. 22 structured transaction/category/
  account/document nodes.
- **Corrections pending** (from dedupe re-run): 13 alias clusters
  emitted. Source + entity-type buckets from prior session carried.
- **Eval** (temp=0, reproducible, 11 cases):
  - mean doc_coverage   = 0.92
  - mean entity_coverage = 0.98
  - mean fact_coverage   = 1.00
  - passing = 7/11 (aggregation-expenses, children-medical-history,
    prescribed-medications, employment-intel, owned-vehicles,
    property-acquisition-price, identity-documents)
- **Session trajectory** (baseline → this session end):
  - `doc_coverage`: 0.62 → 0.92 (+48% relative)
  - `entity_coverage`: 0.86 → 0.98
  - `fact_coverage`: 0.91 → 1.00
  - passing: 3/11 → 7/11
- **Commit trail** (most recent first):
  - `e8b5dc4` — Phase 5.7 Profile expansion + scorer fragility
  - `02396a4` — temperature configurable (`EXTRACTION_TEMPERATURE`)
  - `0022d7d` — Phase 5.6 doc-kind-routed extraction hints
  - `14c9af9` — Phase 5.3b deterministic References injection + NFC
  - `5300695` — pack decoupling (move bank injector out of core)
  - `8d24fbc` — docs(intent): Phases 3.5–5.5b recap
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

- **Residual cross-doc retrieval gaps** — `cross-doc-person` still at
  0.80 (Facture_250 not retrievable under "Sébastien" queries);
  `temporal-addresses` 0.67, `tax-timeline` 0.67. Profile expansion
  closed the easy gains; what remains is docs that simply aren't in
  the retrieved entity/chunk set at all. Expected to grow with corpus
  size; addressable by (a) stronger per-entity Profile completeness
  via pre-retrieval entity-to-doc expansion, or (b) query-intent hints
  that broaden initial entity_vdb top-K.
- **LLM answer exhaustiveness** — `family-composition` ent=0.80: LLM
  names 4 of 5 expected family members despite all being in context.
  Generic model diligence issue, addressable via prompt tuning with
  strict before/after measurement.
- **Profile/Catalog alias fragmentation** — cross-doc-person query
  retrieved 7 distinct `Profile: …` nodes for the same person
  (`Profile: Sébastien Boutet`, `Profile: Sebastien Boutet`,
  `Profile: Monsieur Sebastien Boutet`, `Profile: Sebastien Jean
  Christophe Boutet`, `Profile: Mr Boutet Sebastien`, etc.). Alias
  resolution runs BEFORE index-node creation; Profile names are built
  from whatever surface-form entities survived. Consider running
  alias resolution on entity names a second time, or generating
  Profile nodes only for alias-clustered canonicals.

## Phases remaining

- **FastAPI surface** (intent.md §48) — expose the KG via
  `/search`, `/entity/{id}`, `/provenance/{fact_id}`, `/diff`. KG is
  materially solid enough (92/98/100 eval) to start this.
- **Sovereign LLM** — swap OpenRouter/Gemini for a local backend
  (Gemma, llama.cpp, ollama). Config change only now that
  `temperature` is configurable and all LLM call-sites go through
  `extraction/llm.py`. `doc_context` classifier also uses
  `extraction.config` so the swap affects it too.
- **Phase 6 — memory / business rules** — workflow-layer `rules.yaml`
  applied at query time. Blocked on the workflow layer itself
  (LangGraph or similar).
- **Profile dedup on canonical aliases** — per the weakness above,
  cheap tightening of index-node generation.
- **Cross-doc retrieval expansion** — when a query mentions a named
  entity present in the graph, pre-populate top-K with that entity's
  full `document_ids` list. Would close the remaining 4 failing cases.
- **Phase 5 (original — relation-type induction)** — cluster edge
  descriptions to surface candidate predicates. Low priority now that
  answer-shaped nodes + Profile expansion handle breadth queries;
  revisit when richer semantics are actually needed.

---

## Resuming in a fresh session — quick map

- **Repo root**: `/Users/sboutet/projects/my-memory`
- **Branch**: `master`, tree clean.
- **Tests**: `source venv/bin/activate && python -m pytest -q -m "not integration"` → 404 passing.
- **Corpus**: `raw/` + `raw-2/` = 32 docs, ingested in `store/`.
- **Extraction store**: `extraction_store/` — 2229 entities, 87 index
  nodes, 32 summary chunks, 22 structured nodes.
- **Pipelines** (all local-only except LLM calls):
  - Ingest: `python -m ingestion <path> [--no-classify]`
  - Re-OCR: `python -m ingestion reocr <doc_id> [--backend ocrmac]`
  - Re-classify: `python -m ingestion classify [--doc-id X]`
  - Extract: `python -m extraction extract [--no-focus-hints]`
  - Dedupe: `python -m extraction dedupe [--apply]`
  - Emit corrections: `python -m extraction emit-corrections`
  - Apply corrections: `python -m extraction apply-corrections [--apply]`
  - Extract structured: `python -m extraction extract-structured [--dry-run]`
  - Enhance retrieval: `python -m extraction enhance-retrieval`
  - Build indexes: `python -m extraction build-indexes [--dry-run]`
  - Annotate temporal: `python -m extraction annotate-temporal`
  - Query: `python -m extraction query "..."` (uses `aquery_llm`,
    deterministic References injection)
  - Diagnose: `python -m extraction diagnose "..."` / `diagnose-corpus`
  - Review corrections: `python -m corrections review [source|entity-types|aliases] [--all]`
  - Show one correction: `python -m corrections show <slug-or-doc-id>`
  - Eval: `python -m evaluation --runs 3` (temp=0, reproducible)
  - Eval diagnostics: `python -m evaluation --diagnose [--case <id>]`
- **Latest eval** (end of session 2, temp=0): mean
  `doc_coverage = 0.92`, `ent_coverage = 0.98`, `fact_coverage = 1.00`;
  passing `7/11`.
- **Next action options** (in descending leverage):
  1. Cross-doc retrieval expansion — close the last 4 failing cases
     (`cross-doc-person`, `temporal-addresses`, `tax-timeline`,
     `family-composition`). Pre-retrieval entity-to-doc expansion
     when the query mentions a known entity.
  2. FastAPI surface — KG is stable enough to expose.
  3. Sovereign LLM swap — infrastructure move; unblocks air-gapped
     deployments.

---

## Phase 6 — Fact model and provenance (session 3, 2026-04-24)

**Goal**: overlay `Fact`/`Claim`/`Conflict` on top of LightRAG; wire
bank-statement pack; API stub; extend eval; benchmark scaffold.

### Key decisions taken

- **Overlay, not replacement** (D-refactor locked): LightRAG entity/relation
  store remains the retrieval substrate. Facts are a separate JSONL layer.
- **Content-addressable IDs**: SHA-256 of `subject_id|predicate|canonical_value|source_doc_id`.
  Computed via Pydantic `@computed_field` → recomputed on deserialization;
  stored in JSON for API consumers. Collision = `DuplicateIDError`.
- **JSONL append-only**: `facts/store/{facts,claims,conflicts}.jsonl`. Bad
  lines logged+skipped; in-memory index rebuilt on init. Matches lesson
  2026-04-15 (JSONL beats sqlite for short-lived audit trails).
- **Pack hook pattern**: `inject_facts(rag, facts_store, result) -> FactResult`
  optional hook via `getattr(pack, "inject_facts", None)`. Backward-compat:
  packs without the hook pass silently.
- **API stub**: FastAPI `GET /health` + `GET /facts/{fact_id}` (SHA-256
  pattern validation → 422 on bad input; 404 on missing). No auth — Phase 10
  hardens. `Depends(get_store)` pattern for testability.
- **Eval extension**: `fact_provenance_coverage` metric added. 5 new cases
  targeting bank-statement provenance (virement, carte, Roquefort, 2026).
  Same accent+case-insensitive OR-alternative scoring as `fact_coverage`.
- **Benchmark scaffold**: `benchmarks/runner.run(stage, model_list, ...)` swaps
  only `config.llm_model` via `dataclasses.replace()` — caller's config never
  mutated. Sequential per model (no parallel API calls). `case_limit` for cheap
  smoke runs. Stage "query_answerer" only; extractor/embedder planned Phase 7.

### What was implemented (tasks 6.1 → 6.6)

- `facts/` package: `models.py` (Fact, Claim, Conflict, Predicate, FactResult),
  `store.py` (FactStore JSONL), `orchestrator.py` (run_inject_facts),
  `__init__.py`.
- `packs/personal_documents/injector.py`: `plan_transaction_facts()` → one
  Fact + one Claim per bank Transaction row.
- `packs/personal_documents/__init__.py`: `inject_facts()` hook — calls
  `plan_transaction_facts`, swallows `DuplicateIDError` for idempotency,
  returns empty FactResult for non-bank-statement docs.
- `packs/protocol.py`: `inject_facts` documented in Pack protocol.
- `api/main.py` + `api/__main__.py`: FastAPI stub.
- `evaluation/scorer.py`: `score_fact_provenance_coverage`.
- `evaluation/schema.py`: `EvalCase.expected_provenance`, `EvalCaseResult.fact_provenance_coverage`.
- `evaluation/runner.py`: `score_case` wires fpc; `run_all` accepts optional
  `config` arg for benchmark runner.
- `evaluation/aggregate.py`: `mean/std_fact_provenance_coverage` fields.
- `evaluation/cases.json`: 5 new fact-provenance cases (total: 16).
- `benchmarks/` package: `schema.py` (BenchmarkResult), `runner.py` (run()),
  `README.md` (proposed model set + cost guard).
- Test count: 404 → 517 (+113 tests across 6 new test files).

### What did NOT change

- LightRAG internals — zero new touches.
- Extraction graph pipeline — `extract`, `dedupe`, `build-indexes` unmodified.
- Existing 11 eval cases — no expected_documents/entities/facts changes.

### Self-review (CLAUDE.md §7)

| Axis | Status | Note |
|------|--------|------|
| Spec conformance | ✅ | All 6.1–6.6 implemented and committed |
| Security OWASP | ⚠️ | No auth on API — documented V1 stub; `fact_id` regex-validated |
| Resilience | ✅ | Bad JSONL lines skipped; pack hook exceptions caught |
| Reliability | ✅ | Content-addressable IDs; append-only JSONL |
| Resource pressure | ✅ | O(n) load, O(1) lookup; sequential benchmarks |
| Observability | ✅ | logger.info per run, logger.warning on hook failures |
| Testability | ✅ | 517 tests; API via TestClient; benchmarks via AsyncMock |

No 🔴 items.

### Pending before Phase 7

- Run `python -m evaluation --runs 3` (needs live corpus + API key) and eyeball.
- User approves benchmark model list before any paid sweep.
- User confirms lawyer-meeting (≈ 2026-04-26) predicate requirements before
  Phase 7 predicate design starts.

### Next phase

Phase 7 — Contradictions as first-class. Predicate registry in core,
Conflict detector, YAML resolution UX. STOP before starting: ask user for
(1) synthetic corpus plan approval, (2) lawyer-meeting predicate requirements.