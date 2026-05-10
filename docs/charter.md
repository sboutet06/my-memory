# Project Charter — My-Memory / Personal Knowledge Graph

*Structured companion to `intent.md`, which remains the rolling session log.
This file defines the stable **why / what / how** and the active plan.*

*Last revised: 2026-04-24.*

---

## 0. Elevator

A self-hosted knowledge system that turns heterogeneous personal and
organizational documents into a queryable graph with **fact-level provenance,
coherent multi-document reasoning, and temporal truth**. V0 is dogfooded on
the author's own documents (invoices, contracts, medical records, identity).
V1 targets a small B2B niche where being wrong is expensive and being vague
is unacceptable — candidates include regulated-SMB legal/notarial,
independent medical practice, and compliance teams.

The bet: as of 2026, RAG systems answer confidently but not **accountably**.
This one answers accountably first.

---

## 1. Why — the essence

### 1.1 The first-principles problem

LLM-assisted knowledge tools in 2026 solve **recall** (find the passage) but
not **accountability** (which fact, from which document, at what point in
time, in the presence of which conflicting facts from other sources). Three
failure modes are endemic:

1. **Epistemic averaging.** Ask a RAG system a question whose answer exists
   in two documents with different values, and it either picks one silently
   or constructs a plausible blend. The user cannot tell a conflict exists.
2. **Temporal collapse.** Documents describing *states at a point in time*
   are flattened into a single synchronic view. "The customer's address"
   returns a value, not a history, not the moment it changed, not the source
   of the change.
3. **Weak provenance.** Citations point to documents or chunks, not to
   facts. The reader cannot follow a claim back to the sentence that
   produced it.

For personal notes or exploratory chat, these are tolerable. For contracts,
clinical records, compliance evidence, or research claims, they are
disqualifying.

### 1.2 The epistemic contract

The product defines a contract between the user and the knowledge base,
expressed as four properties the system must uphold for every fact it
exposes:

| Property | What it means | Why it matters |
|---|---|---|
| **Provenance** | Every fact resolves to `(document, location, ingestion_version, extractor_version, timestamp)`. | The user can re-verify. Auditable. |
| **Coherence** | Conflicting facts are surfaced, not silently resolved. A query with no single answer returns a structured disagreement, not a hallucination. | Trust under disagreement. |
| **Temporality** | Every fact carries the time at which it held, not just the time it was ingested. Updates are additions, not overwrites. | History preserved. Point-in-time queries possible. |
| **Sovereignty** | Data, graph, embeddings, LLM calls (eventually) all under user control. Open formats, exportable, no lock-in. | For regulated or sensitive data. |

These are not nice-to-have features; they are the product. Every
architectural choice should be justified by whether it preserves, extends,
or incidentally enables these four properties.

### 1.3 Who suffers most from the status quo

Candidate B2B targets, rough fit order (to narrow — see §7.7 D1):

- **Small law firms and solo notaries (FR/EU).** Contract archives,
  versioned clauses, party-role reasoning. Regulation (RGPD, professional
  secrecy) forbids cloud offload. Coherence failure = malpractice exposure.
- **Independent medical practices.** Clinical records, prescription
  histories, referrals across specialists. Temporal truth is
  safety-critical.
- **Compliance teams in regulated SMBs** (fintech, crypto, healthtech).
  Audit trail is the product.
- **Academic labs and research groups.** Paper archives, citation
  reasoning, claim-to-source traceability. Less regulated but
  coherence-hungry.

The personal-documents dogfood is **not the target market**; it is the
rigorous test bed where the author can judge correctness against ground
truth the author owns.

### 1.4 Why now

Three tailwinds mean this is buildable in 2026 by a small team:

1. **Document parsing is a solved commodity.** Docling, ocrmac,
   unstructured.io handle 95% of formats locally.
2. **Entity and relation extraction is a solved commodity.** LightRAG,
   Microsoft GraphRAG, LlamaIndex PropertyGraphIndex all offer library-mode
   LLM extraction.
3. **Local embedding and reranking models run on commodity hardware.**
   Multilingual MiniLM (117 MB), cross-encoders, all MPS/CUDA/CPU-capable.

What is **not** solved as commodity, and therefore where value accrues, is
the layer above extraction: provenance at the fact level, contradiction
detection, temporal supersession, human-auditable correction loops. That is
where this project's work must concentrate.

---

## 2. What — the product

### 2.1 North star

> A structured knowledge API plus a human-in-the-loop correction workflow
> that exposes a user's heterogeneous documents as a graph in which every
> fact is traceable, every conflict is visible, every change is historied,
> and every correction is auditable.

### 2.2 Product surface (V1)

Three audiences, three surfaces, one core. Divergence between surfaces is
forbidden; all three wrap the same service layer.

**Admin surface** (power users, customer sysadmins, the author during
dogfood):

- CLIs: `python -m ingestion|extraction|corrections|evaluation`.
- YAML files under `corrections/source/`, `corrections/derivation/`,
  `corrections/packs/`. Git-versioned, hand-editable, PR-reviewable.
- `python -m corrections review|show|stats`.
- **Admin conflicts dashboard (V1, decided 2026-05-10)**: read-only web
  UI listing open Conflicts with one-click resolve actions
  (`pick winner / mark coexist / mark temporal`). Writes still flow
  through YAML + Git under the hood — the UI emits a YAML correction
  file and stages it. Minimum viable, not a full admin GUI; enough so
  that a non-developer secretary at a customer SMB can triage conflicts
  without learning YAML. Scoped originally for V2 (see §2.6 historical),
  promoted to V1 by the 2026-05-10 premortem (SMB target inaccessible
  without it).

**Programmatic surface** (integrations, downstream apps, agent consumers):

- **MCP server (Phase 10, decided 2026-05-10)** — primary first surface.
  Built before FastAPI because the only concrete consumer
  (`/Users/sboutet/projects/orchestrator`) is LLM-agent shaped, not HTTP
  shaped. Wraps the same service layer as FastAPI.
- **FastAPI HTTP (Phase 11)** — endpoints below. Same service layer as
  MCP; no duplicate logic.

**Consumer surface** (non-technical end users — lawyers, clinicians,
compliance officers; V2, scoped in §2.6 so V1 API contracts do not box it
out):

- Minimal query UI with inline citations, conflicts view, as-of date
  picker, faceted filters. Distinct from the V1 admin conflicts
  dashboard above: consumer = end-user query; admin = triage of
  pipeline-detected conflicts.

HTTP endpoints (V1):

- `GET /documents` — list ingested sources with metadata.
- `GET /documents/{id}` — single source view.
- `GET /entities?type=&doc=&date=` — search entities with filters.
- `GET /entities/{id}?as_of=YYYY-MM-DD` — entity detail with all facts,
  all sources, temporal history, optional point-in-time view.
- `GET /facts/{id}` — single fact, full provenance, conflict set.
- `GET /conflicts` — every unresolved contradiction in the graph.
- `GET /search?q=` — hybrid retrieval, structured answer with citations.
- `POST /query` — LLM-assisted natural-language query with assembled
  context and provenance.

Response shapes are UI-renderable: structured answer + cited fact IDs +
conflict IDs + provenance trail, not opaque strings.

### 2.3 Non-goals (V1)

- Multi-tenant SaaS. Self-hosted per organization.
- Full admin authoring GUI — only the **conflicts triage dashboard** is in
  V1 (read-only with one-click resolve emitting YAML). Source / derivation
  / pack correction authoring stays YAML + Git. Consumer query UI is
  scoped in §2.6 but deferred to V2.
- Real-time streaming ingest.
- Memory / workflow rules layer (deferred to V2).
- Agent-style orchestration. The API is consumed, not driven from inside.
- Structured code-repository ingestion (functions, call graphs, imports).
  Text-mode code content (READMEs, docstrings, docs/) already flows through
  Docling as documents; deeper code KG is a future `code_repos` pack and
  overlaps with Sourcegraph / Cody / Aider-repo-map territory — not worth
  rebuilding in V1.

### 2.4 Competitive landscape and differentiation

| System | Ingestion | Extraction | Retrieval | Provenance | Contradictions | Temporal | Corrections UX | Self-hosted |
|---|---|---|---|---|---|---|---|---|
| **This project (V1 target)** | Docling + ocrmac dispatch, packs | LightRAG + pack extractors + focus hints | Hybrid graph + vector + rerank + index nodes | **Fact-level** | **First-class** | **Per-fact validity intervals** | **YAML + Git, 3-layer** | Fully |
| Microsoft GraphRAG | Generic | LLM extract | Hybrid | Doc-level | No | No | None | Yes (Azure-biased) |
| LightRAG (library) | Generic | LLM extract | Hybrid | Chunk-level | No | No | None | Yes |
| LlamaIndex PropertyGraphIndex | Generic | LLM extract | Graph + vector | Doc-level | No | No | None | Yes |
| Neo4j GraphRAG | Manual | Configurable | Graph + vector | User-authored | No | No | None | Yes (paid tiers) |
| Mem0 / Letta | N/A (agent memory) | N/A | KV / vector | Weak | No | Limited | None | Mem0 self-host; Letta yes |
| Onyx (ex-Danswer) | 40+ connectors | N/A (vector RAG) | Vector + BM25 | Doc-level | No | No | Admin UI | Yes |
| NotebookLM (Google) | PDF/docs | Hidden | Hybrid | Source snippets | No | No | None | No |
| Palantir / Bloomberg-style compliance KGs | Enterprise | Expert-authored | Custom | Full | Supported | Supported | Expensive workflows | Yes |

**Differentiation thesis**: the combination of (a) fact-level provenance,
(b) first-class contradictions, (c) per-fact temporal validity, and (d) a
three-layer human-in-the-loop correction UX (source / derivation / memory)
packaged into a self-hostable open pipeline **does not exist as a shipped
product in the SMB price band** as of 2026-04. Each of the four exists in
research or in high-end enterprise suites; none come together in a
small-team-operable package.

### 2.5 The core thesis

> **RAG systems in 2026 optimize for fluency. This project optimizes for
> accountability. Accountability is what regulated-SMB buyers will pay for
> and what personal-productivity tools cannot deliver.**

### 2.6 Consumer UX (scoped here, delivered in V2)

V1 ships APIs only. V2 adds a consumer UI surfacing what a non-technical
end user needs. The audience is simple-interaction: a lawyer, a GP, a
compliance officer. They do not read YAML and do not write queries in
graph traversal language.

Minimum viable consumer UI (V2):

- Search bar + document drag-and-drop upload.
- Answer view: natural-language response, inline `[1][2]` citations that
  link to source document highlighted at page/paragraph.
- Contradictions panel: per-entity list of unresolved conflicts with a
  one-click "choose winner / mark coexist / mark temporal".
- As-of date picker: slider or date field applying to the current query.
- Facet filters: document type (pack-classified), date range, entity
  type.
- "Why this answer?" button expanding the full provenance tree for the
  top-line claim.

The UI is constrained by the **V1 API contract**; the API must return
every piece of information the UI needs, pre-structured. No V2 breaking
change to the API is acceptable. Every `POST /query` response carries:
structured answer text, inline citation markers mapped to fact IDs, the
fact list with their claims and conflicts, the document list, and a
confidence score per fact.

Admin surface stays YAML + CLI; the target user there is the customer's
sysadmin or a technical power user. Two audiences, two UIs, one API.

---

## 3. How — architecture and engineering

### 3.1 Layered architecture (revised from intent.md §126)

```
┌─────────────────────────────────────────────────────┐
│ L6 — API                                            │
│   FastAPI: /documents /entities /facts /conflicts   │
├─────────────────────────────────────────────────────┤
│ L5 — PACKS (pluggable, per-domain)                  │
│   personal_documents (shipped)                      │
│   legal / medical / compliance / research (future)  │
├─────────────────────────────────────────────────────┤
│ L4 — CORE SEMANTICS  ← differentiation lives here   │
│   • provenance: fact-level IDs + source chain       │
│   • coherence: conflict objects, not silent merges  │
│   • temporality: per-fact validity intervals        │
│   • corrections: source / derivation / memory       │
│   • retrieval: hybrid graph + vector + rerank       │
│   • eval: gold cases + adversarial + calibration    │
├─────────────────────────────────────────────────────┤
│ L3 — GRAPH + VECTOR STORE                           │
│   LightRAG (library) + NetworkX + chunks vdb        │
│   Future: Neo4j when fact table outgrows            │
├─────────────────────────────────────────────────────┤
│ L2 — EXTRACTION                                     │
│   LLM entity/relation + pack structured extractors  │
│   + doc-kind extraction hints                       │
├─────────────────────────────────────────────────────┤
│ L1 — INGESTION                                      │
│   Docling (office) + ocrmac (IDs) + classifier      │
└─────────────────────────────────────────────────────┘
```

L1–L3 are largely commodity. L5 is domain customization. L6 is surface.
**L4 is where the product lives.**

### 3.2 Data model — proposed revision

Current implementation: entities and relations with document-level
provenance via `document_ids`. For V1 accountability, promote **facts** to
first-class:

```
Entity
  id, name, type, description
  canonical_of: Entity (alias target)
  source_entities: [source_doc_id]  # where entity was mentioned

Fact                                # NEW first-class
  id                                # stable, content-addressable
  subject: Entity
  predicate: str                    # 'address', 'birthdate', 'employer'...
  value: str | Entity | Amount | Date
  valid_from: Date | None
  valid_to: Date | None             # null = "still true as of latest source"
  asserted_by: [Claim]              # evidence chain

Claim                               # NEW first-class
  id
  fact: Fact
  source_doc_id: str
  source_location: str              # page, span, char offset
  extractor: str                    # 'llm:gemini-2.5-flash@2026-04',
                                    # 'pack:bank_statement@1.2'
  extracted_at: Date
  confidence: ConfidenceLevel       # CATEGORICAL (decided 2026-05-10).
                                    # Enum: deterministic | llm_high | llm_low.
                                    # Float dropped — un-calibrated float is
                                    # theatre and contradicts the
                                    # accountability promise. Calibration set
                                    # would be needed to revive a float;
                                    # categorical is honest by construction.
                                    # Mapping rules:
                                    #   deterministic → regex/structured
                                    #     extractor (bank, IBAN parser).
                                    #   llm_high → LLM extraction +
                                    #     deterministic post-validation
                                    #     (typed predicate, value matches
                                    #     declared format).
                                    #   llm_low → LLM extraction without
                                    #     post-validation (free-text
                                    #     predicates, fallback path).
  ingestion_version: int

Conflict                            # NEW first-class
  id
  subject: Entity
  predicate: str
  competing_facts: [Fact]
  status: 'open' | 'resolved_manually' | 'resolved_temporally'
  resolution: Correction | None
```

**Key shift**: currently, descriptions carry `[sourced: date]` prefixes and
`document_ids` lists. That is adequate for retrieval but not for
accountability — the API cannot answer *"what evidence supports this
address being current?"*. The Fact/Claim/Conflict model makes that trivial.

**Implementation path**: this model can be layered *on top of* the existing
LightRAG graph without replacing it. Entities and relations stay; a new
`facts/` store (JSON or DuckDB) references LightRAG entities by id and
provides the claim chain. Retrieval still hits the LightRAG graph first; the
API resolves facts at response time. This is the **overlay approach** — see
§7.7 D-refactor for the full-refactor alternative.

### 3.3 Correction model

Three layers, strictly distinct (already designed, intent.md §209):

- **Source corrections** (ingestion layer): document date, OCR errors,
  `replaced_by`, tags. YAML per document.
- **Derivation corrections** (graph layer): entity type overrides, alias
  merge/split, conflict resolutions. YAML per cluster or per fact.
- **Memory corrections** (workflow layer, V2): business rules applied at
  query time, not graph-mutating.

Phases 3.5 / 3.6 / 3.7 delivered the first two. V1 extension: a fourth
correction type under derivation — **conflict resolution** (pick winner,
mark coexistence, mark temporal supersession).

### 3.4 Retrieval model

No fundamental change from current (hybrid graph + vector + rerank +
Profile/Catalog index nodes). Two cleanups:

1. **Separate synthetic index nodes from real entities** in the graph
   namespace. Give Profile/Catalog a `kind: index_node` label so the API can
   filter them out of `/entities` results while still using them at
   retrieval time.
2. **Run alias resolution after index-node creation**, or build index
   nodes only for alias-clustered canonicals. Current Profile fragmentation
   (7 surface variants of the same person — intent.md §629) is a
   correctness bug, not only a retrieval inefficiency.

### 3.5 Temporal and contradiction semantics — proposal

Adopt a **bitemporal** model, simplified:

- **Valid time** (`valid_from`, `valid_to`): when the fact was true in the
  world.
- **Transaction time** (`extracted_at`, `ingestion_version`): when the
  system learned of it.

Rules, explicit and minimal:

1. **Time-varying predicates** (address, employer, role, marital status,
   price): a new fact with later `valid_from` supersedes the previous; both
   remain queryable. Supersession is automatic when the predicate is
   declared time-varying in a pack.
2. **Time-invariant predicates** (birthdate, passport_number,
   social_security_id): two different values = **Conflict object**, never
   automatic merge. Packs declare these.
3. **Unknown-variance predicates**: default to Conflict (safer than silent
   supersession).
4. **Conflict resolution**: user interaction via YAML under
   `corrections/derivation/conflicts/<conflict_id>.yaml`. Options: pick
   winner, mark coexistence (multi-valued fact), mark temporal supersession
   with ordering. Every resolution is itself a correction with provenance.

**Why this matters**: the current `[sourced: date]` prefix is a retrieval
hint. It is not a semantic commitment. A pack declaring
`predicate=address, time_varying=true` makes the commitment
machine-checkable and API-exposable.

### 3.6 Evaluation methodology — proposal

Current: 11 cases, substring/set scoring, 32 docs. Gaps:

1. **Adversarial bucket** (new): contradictions (two docs with different
   birthdates), negative queries (person not in corpus),
   out-of-distribution, near-duplicates.
2. **Calibration bucket**: queries where the expected answer is
   "insufficient evidence" or "conflicting". Measures whether the system
   says "don't know" when it should not confidently answer.
3. **Regression resistance**: 25–30 cases minimum; no single case should
   flip the aggregate by more than ~3pp. Currently one case = ~9pp.
4. **Update cases** (depend on versioning): ingest v1 of a doc, ask a
   question, ingest v2 with changed facts, ask again, assert old is
   historied and new is current.

### 3.7 What stays unchanged

- Python 3.13, venv.
- Docling + ocrmac ingestion.
- LightRAG as extraction library (wrapped, not embraced).
- Local multilingual MiniLM embeddings.
- Cross-encoder reranker (`mmarco-mMiniLMv2-L12-H384-v1`).
- Eval CLI, `temperature=0`, reproducible.

### 3.8 Multi-model routing

Single-model deployment is economically naive given the 2026 capability
and price spread. Each pipeline stage has different requirements, and
single-vendor lock-in is explicitly out of bounds (sovereignty is a
contract property, §1.2).

Proposed stage → tier mapping:

| Stage | Tier | Capability need | Candidates (2026-04) |
|---|---|---|---|
| Document classification (13 tags) | Cheap | Short-prompt JSON | Haiku 4.5 / Kimi K2 family / Gemma 3n / local Qwen-2.5 |
| LLM entity/relation extraction | Mid | Long-context, multilingual, structured output | Gemini 2.5 Flash (current) / Kimi K2 family / Claude Sonnet 4.6 |
| Structured extractor (regex) | Free | None | — (deterministic) |
| Alias resolution (embedding) | Free | Local | MiniLM (current) |
| Reranker (cross-encoder) | Free | Local | mmarco (current) |
| Query answer assembly | Premium | Reasoning, citation discipline | Claude Sonnet 4.6 / Opus 4.7 / Gemini 2.5 Pro |
| Conflict resolution suggestion (V2) | Premium | Reasoning | Same as query |

Engineering rules:

1. **Config-driven routing.** `extraction/config.py` already exposes
   temperature; extend to a `stage → (model_id, params)` table,
   env-overridable per deployment.
2. **Fallback and retry.** Each stage lists primary + fallback models;
   retry on 5xx / quota errors against the fallback.
3. **Per-stage budget cap.** Soft dollar ceiling per extraction run or
   per query. Abort + report if exceeded.
4. **Benchmark harness (next action).** On the eval suite, swap models
   per stage; record `doc_coverage`, `entity_coverage`, `fact_coverage`,
   latency, `$` per run. Pick winners empirically, not on vibes. Feeds
   both the routing table and the §7.6 sovereign-LLM swap.
5. **Kimi K2 family.** User-flagged; benchmarked in Phase 6 alongside
   open-weights (Qwen, DeepSeek, Llama). No model gets into the routing
   table without appearing in the benchmark.
6. **≥ 2 viable choices per stage before V1 ships.** If only one model
   meets the capability bar, the stage is a lock-in risk and is flagged.
7. **Sovereign-routable LLM swap is a v0.5 deliverable, not deferred**
   (decided 2026-05-10 premortem; revised 2026-05-10 after laptop-power
   reality-check). At least ONE non-US-hosted model wired through
   `extraction/config.py` and runnable before V1 pilot. Without this,
   the announced FR legal/medical market is inaccessible (RGPD + DPA
   blocks any extraction stage routing data to US-hosted LLMs).
   Concrete v0.5 target: **Mistral Small Latest** via OpenRouter with
   `provider.order=["mistral"]` pinning, so data stays in France
   (Mistral SA, Paris). Same OpenAI-compatible API as current Gemini
   routing — no new dependency, no new infrastructure. Metric =
   `fact_coverage` not worse than -0.05 vs Gemini 2.5 Flash on a
   3-case smoke benchmark. True local inference (Ollama / MLX with
   Qwen 2.5 or Mistral weights) is promoted to V1 work and only
   triggered when a customer demands offline operation.

### 3.8b Extraction cache and idempotence (v0.5)

Decided 2026-05-10 premortem. The accountability contract requires that
re-extracting the same document with the same extractor produces the same
Facts. Two fragilities to close before V1:

1. **OpenRouter provider load-balancing** introduces seed variance even at
   `temperature=0` (lesson 2026-04-18). Mitigation: keep `temperature=0`
   AND prefer single-provider routing when available.
2. **No version-keyed cache.** LightRAG's `kv_store_llm_response_cache.json`
   keys on prompt content. Adequate for cost but not for *idempotence
   under prompt edits*. v0.5 introduces an extraction cache keyed on
   `(doc_hash, extractor_version, model_id, prompt_hash)`. Cache hit ⇒
   skip LLM call, reuse stored result. Cache miss ⇒ extract, store, emit
   Facts. Lives under `extraction_store/cache/`. Cheap to add now,
   painful to retrofit at scale.

### 3.8c Abstention and "insufficient evidence" handling (v0.5)

Decided 2026-05-10. Charter §3.6 already lists calibration cases as a
gap (E3). Premortem promotes to v0.5: an accountability product that
fluently confabulates "yes, here is the clause" when no clause exists in
the corpus is broken at its core. Concrete deliverable:

- ≥ 3 eval cases where `expected_answer = "insufficient_evidence"`.
- Metric `abstention_accuracy` in `evaluation/scorer.py`: did the answerer
  abstain when the corpus warrants it?
- Pass criterion: `abstention_accuracy ≥ 0.75` on those cases (target
  raised in V1 to ≥ 0.90).
- Query answerer prompt must explicitly authorize "I do not have
  sufficient evidence in the corpus" and surface a structured response
  shape distinguishing "answered" vs "abstained".

### 3.9 Performance budget (v0.5 → V1)

Decided 2026-05-10. JSONL fact store works at dogfood scale; for the V1
pilot bar (≈ 50k Facts / 200 docs) latency budgets are required to avoid
a "demo well, scale badly" trap. Targets to hold by V1:

| Operation | p95 target | At |
|---|---|---|
| `GET /facts/{id}` (MCP/API) | < 100ms | 50k Facts |
| `GET /entities/{id}?as_of=` | < 300ms | 50k Facts |
| `GET /conflicts` (paged, n=50) | < 500ms | 5k open conflicts |
| `python -m facts detect-conflicts` | < 30s | 50k Facts |
| `python -m facts supersede` | < 30s | 50k Facts |
| End-to-end `/query` | < 5s | 50k Facts, 200 docs |

When JSONL scan misses a target, migrate that surface to DuckDB. Don't
pre-optimize — measure first, port second. The budget is the trigger,
not the plan.

---

## 4. Current state (end of 2026-04-18 session 2)

### 4.1 Delivered

**L1 Ingestion.** 32 docs (`raw/` + `raw-2/`). Docling + ocrmac routing;
degraded-quality fallback markdown; unsupported-format detection; document
classifier (13-tag closed vocabulary).

**L2 Extraction.** LightRAG + Gemini 2.5 Flash + multilingual embeddings.
Structured extractor for bank statements (Transaction schema). Doc-kind
extraction hints (Phase 5.6).

**L3 Store.** 2229 entities, 2060 edges, 87 synthetic index nodes
(Profile/Catalog), 32 summary chunks, 22 structured nodes.

**L4 Core semantics (partial).**
- Provenance: document-level only; fact-level unbuilt.
- Coherence: **not implemented**; conflicting facts silently merge or
  shadow by most-recent date.
- Temporality: `[sourced: date]` annotations on descriptions;
  retrieval-only, not a first-class semantic.
- Alias resolution: embedding + lexical + ambiguity guard.
- Reranking: cross-encoder.
- Retrieval: hybrid with Profile/Catalog index nodes, deterministic
  references injection, per-doc summary chunks.
- Corrections: source + derivation (entity types + aliases).
- Eval harness: 11 cases, substring/set scoring, temp=0.

**L5 Packs.** `personal_documents` (22 life-domain types, Transaction
extractor, extraction hints, low-signal-type hook).

**L6 API.** Not started.

### 4.2 Metrics (baseline → current)

| Metric | Baseline | Current |
|---|---|---|
| `doc_coverage` (mean) | 0.62 | 0.92 |
| `entity_coverage` (mean) | 0.86 | 0.98 |
| `fact_coverage` (mean) | 0.91 | 1.00 |
| Passing cases (of 11) | 3 | 7 |
| Test count | — | 404 |
| Full-corpus extract | — | ~$0.35 / 32 docs / ~8 min |

### 4.3 Validated

- Docling 2.88 on office docs: clean.
- ocrmac backend routing via corrections overlay: end-to-end.
- Phase-gate discipline: e2e corpus runs, not unit tests alone.
- `temperature=0` for reproducible eval.
- Core + packs separation: bank extractor moved out of core; hooks
  (`low_signal_types`, `inject_structured`, `summary_extras_for_doc`,
  `extraction_hints`) carry the contract.

---

## 5. Gaps

Categorized by what they block.

### 5.1 Strategic (block the product thesis)

- **S1. No fact-level provenance.** Document-level only. The entire
  accountability pitch rests on this. Severity: blocking for V1.
  *Status 2026-05-10: schema + bank pack done in Phase 6. Non-bank
  predicates (address, employer, birthdate) not yet wired — see S7.*
- **S2. No contradiction objects.** Conflicting facts silently merge or
  shadow. The coherence pillar of the epistemic contract is unbuilt.
  Severity: blocking for V1. *Status 2026-05-10: detector + YAML UX +
  API done in Phase 7. 0 conflicts in store because S7 not closed.*
- **S3. No per-fact temporal validity.** Only description prefixes. Cannot
  answer "as of 2020-06-01" queries. Severity: blocking for V1.
  *Status 2026-05-10: Phase 8 partial — `valid_from` + supersession +
  `as_of` API done. Bites only on bank Transactions until S7 closes.*
- **S4. Update / re-ingest semantics undefined.** `replaced_by` field
  exists in YAML, no pipeline behavior. Versioning pillar unbuilt.
  Severity: blocking for V1. *Status 2026-05-10: still open — Phase 8.2
  + 8.3 deferred at session 5; promoted into v0.5 by 2026-05-10
  premortem.*
- **S5. No abstention behavior.** Query answerer always answers — no
  "insufficient evidence" path. Discovered 2026-05-10 premortem;
  contradicts §1.2 accountability promise. Severity: blocking for V1.
- **S6. No local-LLM option.** All extraction stages call OpenRouter →
  Gemini. RGPD/DPA blocks announced FR legal/medical market. Severity:
  blocking for V1 pilot. Discovered 2026-05-10; promoted to v0.5.
- **S7. Pack emits Facts only on bank Transactions.** Synthetic
  contradiction/temporal corpus exists but no extractor populates
  Facts for `address`, `birthdate`, `employer` — so Phase 7 / Phase 8
  metrics measure nothing on real or synthetic non-bank docs.
  Discovered 2026-05-10 premortem. Severity: blocking for V1.

### 5.2 Architectural (block scale)

- **A1. Profile/Catalog fragmentation.** Seven variants of the same
  person. Diagnosed in intent.md §629; fix proposed (rerun alias after
  index build, or canonical-only profiles) not executed.
- **A2. Synthetic nodes share namespace with real entities.** `/entities`
  would expose `Profile: …` as an entity. Requires a `kind` label.
- **A3. LightRAG wrapping is deepening.** Undocumented `aquery_llm`, dead
  `include_references` flag, source-reading for the reference list.
  Migration surface is growing. Abstract `QueryDriver` and
  `ReferenceExtractor` interfaces to cap the blast radius.
- **A4. No incremental extraction.** Full re-extract each time. At 32
  docs: fine. At 1000: painful.
- **A5. Per-fact confidence not propagated.** Facts from `degraded` OCR
  docs are treated identically to facts from `rich` invoices.

### 5.3 Operational (block velocity)

- **O1. Cost model per B2B client not articulated.** Current ~$0.011/doc
  for extract. Re-extract frequency unknown.
- **O2. Sovereign LLM swap deferred.** OK for V1 dogfood; may surface as
  blocker in first B2B conversation.
- **O3. No CI gating.** Eval harness exists; not wired to prevent
  regressions automatically.

### 5.4 Evaluation (block trust)

- **E1. Only 11 cases.** One case flip = 9pp. Target 25–30.
- **E2. No adversarial bucket.** No contradiction, negative,
  out-of-distribution, or duplicate cases.
- **E3. No calibration cases.** System always answers; unclear when it
  should say "insufficient evidence".
- **E4. No update cases.** Depends on S4.

---

## 6. Where SOTA already suffices vs. where to dig

### 6.1 Use COTS (commodity; do not rebuild)

- **Document parsing**: Docling + ocrmac. No reason to invest.
- **LLM entity extraction**: LightRAG library mode is a good-enough
  engine. Wrap it, don't replace it.
- **Embeddings and reranking**: multilingual MiniLM + mmarco cross-encoder.
  Solid 2026 picks.
- **Graph substrate**: LightRAG's NetworkX-backed store for V1. Move to
  Neo4j only when the fact table forces it.
- **Dev tooling**: pytest, ruff, mypy. No custom.

### 6.2 Invest here (where to dig to differentiate)

1. **Fact-level provenance model and migration from document-level.** The
   core semantic promise.
2. **Contradiction detection and conflict-object UX.** Research exists
   (temporal KG, truth discovery); no productized version integrated with
   personal/SMB RAG.
3. **Per-fact bitemporal validity with pack-declared predicate
   semantics.** Combines research patterns in a shippable product shape.
4. **Auditable human-in-the-loop correction across all three layers.**
   Already strong; extend to conflicts. This is a real moat candidate.
5. **Adversarial + calibration eval methodology for KG systems.**
   Underserved. Potentially publishable.
6. **Update / re-ingest semantics with supersession chain.** Absent from
   every SOTA library surveyed.

### 6.3 Explicit moat claim

Of the six, **two are true differentiators** (not merely better
implementations of something that exists):

- **First-class contradictions** packaged with human-in-the-loop
  resolution UX.
- **Bitemporal per-fact validity** with pack-declared predicate semantics
  and queryable `as_of` semantics in the API.

These should receive disproportionate engineering attention. The other
gaps are tidying.

### 6.4 Where SOTA already beats this project

Honest call-outs:

- **Microsoft GraphRAG** does better community detection and summary
  synthesis than LightRAG. If community-level reasoning becomes important,
  consider porting that layer.
- **Neo4j GraphRAG** has stronger schema enforcement. If regulated-SMB
  buyers demand strict schemas, inherit their model.
- **Onyx** crushes this project on connector breadth (40+). If the B2B
  target has Jira/Confluence/Slack as inputs, consume Onyx's connector
  layer rather than write new ones.

None of these is a reason to pivot. They are reasons not to waste effort
re-implementing common infrastructure.

---

## 7. Actionable plan

Ordered by leverage on the V1 thesis. Dates assume 2–3 focused sessions per
week; adjust on confirmation of §7.7 D-deadline.

### Milestone naming (decided 2026-05-10)

- **v0.5** = "differentiator demonstrably works end-to-end on dogfood +
  synthetic adversarial corpus, distributable to a single pilot". Closes
  S4 / S5 / S6 / S7 + adds 8.2/8.3 + admin conflicts GUI minimal + MCP
  minimal. Ends with Phase 10 (MCP).
- **V1** = "ready for first paying B2B pilot". Adds Phase 9 cleanup
  (Profile fragmentation, namespace, QueryDriver wrapper, incremental
  extract), Phase 11 FastAPI complete, eval expansion to 25–30 cases, CI
  gate. Optionally one second domain pack (legal first, per §7.7 D1).

### 7.1 Phase 6 — Fact model and provenance

*Target: 2026-05-15.*

- **6.1** Define `Fact`, `Claim`, `Conflict` Pydantic schemas. Storage:
  JSON under `facts/` or DuckDB file (decide after 6.2 volume check).
- **6.2** Migrate one pack (`personal_documents.bank_statement`) to emit
  `Fact + Claim` tuples alongside LightRAG nodes. Measure: answer *"what
  evidence supports Transaction X"* with the full chain.
- **6.3** Extend `extraction/structured.py` hooks: packs return
  `FactResult` with claims.
- **6.4** API stub: `GET /facts/{id}` returning fact + claims + conflicts.
- **6.5** New eval cases: fact-provenance queries (5 cases minimum).

**Decision point after 6.2**: can LightRAG reliably produce facts, or do
facts remain the province of structured pack extractors? Likely split:
LightRAG → entities and relations; packs → facts. That is a product-shape
call.

### 7.2 Phase 7 — Contradictions as first-class

*Target: 2026-06-01.*

- **7.1** Predicate registry in core: `time_varying: bool`,
  `allow_multi: bool`. Packs declare per predicate.
- **7.2** Conflict detector: when two facts with same
  `(subject, predicate)` exist and predicate is not `allow_multi`, emit a
  `Conflict`.
- **7.3** Corrections layer:
  `corrections/derivation/conflicts/<id>.yaml` with resolution options
  (winner / coexist / temporal_supersede).
- **7.4** API: `GET /conflicts`, `GET /conflicts/{id}`.
- **7.5** Eval: adversarial bucket, ≥ 5 contradiction cases (depends on
  §7.7 D6).

### 7.3 Phase 8 — Bitemporal validity and versioning

*Target: 2026-06-15.*

- **8.1** `valid_from / valid_to` on Fact.
- **8.2** `ingestion_version` on Claim. Re-ingest of same doc → new
  version, old version archived not deleted.
- **8.3** Wire `replaced_by` into the ingest pipeline (not only the YAML
  field).
- **8.4** Supersession engine: for `time_varying=true` predicates, a new
  Fact with later `valid_from` closes the previous (sets its `valid_to`).
- **8.5** API: `GET /entities/{id}?as_of=2020-06-01`.
- **8.6** Eval: update cases (≥ 5), contradictions across time-varying vs.
  time-invariant.

### 7.3b Phase 8b — v0.5 consolidation (decided 2026-05-10)

*Target: 2026-06-15. Inserted between Phase 8 and Phase 9 by the
2026-05-10 premortem.*

Closes S4–S7 and §3.8 / §3.8b / §3.8c v0.5 deliverables before any
cleanup work. Without 8b, the v0.5 differentiator pitch is theatre.

- **8b.1** Close Phase 8 deferred items: 8.2 ingestion_version archive
  (`store/<doc_id>/versions/<v>/`, `current` pointer), 8.3
  `replaced_by` wiring through the ingest pipeline.
- **8b.2** Categorical confidence migration (S5 prerequisite): rewrite
  `Claim.confidence: float` → `ConfidenceLevel` enum
  (`deterministic | llm_high | llm_low`). Migrate existing 17 claims on
  disk (deterministic). Update API + scorer + tests.
- **8b.3** Extract caching keyed on
  `(doc_hash, extractor_version, model_id, prompt_hash)`. Lives under
  `extraction_store/cache/`. Cache hit ⇒ no LLM call. Idempotence test:
  `extract → store fingerprint → re-extract → bit-identical Facts`.
- **8b.4** Local LLM swap (S6): one local model wired through
  `extraction/config.py` for the extraction stage. Target: Ollama or
  MLX `qwen2.5:7b`. Smoke test: `python -m evaluation --runs 1` on a
  3-case subset with the local model. Pass: `fact_coverage` not worse
  than -0.05 vs Gemini.
- **8b.5** Non-bank Fact extractors (S7): add `address`, `birthdate`,
  `employer` predicate extractors in `personal_documents`. LLM-extract
  with deterministic post-validation (date format, regex on address
  shape, etc.). `confidence = llm_high` when post-validation passes,
  `llm_low` when it does not. Synthetic corpus must produce ≥ 1
  Conflict and ≥ 1 supersession on `address` chain.
- **8b.6** Abstention (S5 / §3.8c): query answerer can return
  "insufficient evidence". Add ≥ 3 eval cases with
  `expected_answer = "insufficient_evidence"` + metric
  `abstention_accuracy`. Pass: ≥ 0.75.
- **8b.7** E2E phase gate for Phase 7 + Phase 8 + Phase 8b: rerunnable
  script `scripts/phase-gate-v0.5.sh` covering ingest synthetic →
  extract → extract-structured → detect-conflicts → supersede → eval,
  with all metric thresholds asserted.

### 7.4 Phase 9 — Cleanup and hardening

*Target: 2026-07-15. (Re-dated 2026-05-10.)*

- **9.1** Profile fragmentation fix (rerun alias after index build, or
  canonical-only profiles).
- **9.2** Separate `:Entity` from `:IndexNode` namespace.
- **9.3** `QueryDriver` + `ReferenceExtractor` interfaces; LightRAG becomes
  one implementation.
- **9.4** Incremental extraction (per-doc diff).
- **9.5** Eval expansion to 25–30 cases.
- **9.6** CI gate on eval regression.
- **9.7** Admin conflicts dashboard (V1 surface, decided 2026-05-10).
  Read-only web UI listing open Conflicts; one-click `pick winner /
  mark coexist / mark temporal` emits a YAML correction file. Stack:
  minimal — server-rendered HTML or a tiny SPA, whatever costs least
  given the v0.5/V1 timeline. Auth: same model as MCP/FastAPI (Phase
  11). Out of scope: source/derivation/pack correction authoring (stays
  YAML+Git+CLI).
- **9.8** Performance budget (charter §3.9) measured + asserted in CI.
  Surfaces missing the budget trigger a JSONL → DuckDB port for that
  surface only.

### 7.5 Phase 10 — MCP server

*Target: 2026-08-01. (Reordered 2026-05-10: was Phase 11, swapped with
FastAPI.)*

MCP (Model Context Protocol) is the natural consumption path for the
only concrete consumer (the author's `orchestrator` project at
`/Users/sboutet/projects/orchestrator`). Built before the FastAPI HTTP
surface so v0.5 ships against a real client, not a hypothetical one.

- **10.1** Service layer extraction first — the shared core both MCP and
  the future FastAPI HTTP surface (Phase 11) wrap. Lives under
  `service/` (new package). Stateless functions; no MCP/HTTP knowledge.
- **10.2** MCP server scaffolded using the latest Anthropic MCP Python
  SDK. Tools:
  - `my_memory.search(query)` → hybrid retrieval result.
  - `my_memory.fact_get(fact_id)` → fact + provenance + conflicts.
  - `my_memory.entity_get(entity_id, as_of?)` → entity temporal view.
  - `my_memory.conflicts_list(filter?)` → open conflicts.
  - `my_memory.document_get(doc_id)` → document metadata + content.
- **10.3** Tool descriptions tuned for agent consumption: cost-per-call
  hint, response-shape example, common pitfalls, idempotency guarantee.
- **10.4** Integration test: end-to-end orchestrator flow — request a
  fact, receive provenance chain, resolve a conflict via correction
  YAML, re-query, receive resolved value.

### 7.5b Phase 11 — FastAPI V1

*Target: 2026-08-15. (Reordered 2026-05-10: was Phase 10.)*

- Endpoints as §2.2.
- OpenAPI spec committed as `docs/api-v1.yaml`.
- Response shapes designed for V2 consumer UI (§2.6): structured answer,
  inline citation markers mapped to fact IDs, per-fact confidence (now
  categorical per §3.2).
- **Same service layer as Phase 10 MCP. Adding capability on one side is
  never reason to add it on the other.**

### 7.6 Deferred, explicit

- **~~Sovereign LLM swap per stage~~** — promoted to v0.5 (§3.8 rule 7).
  ONE local model in v0.5 (extraction stage); the per-stage ≥ 2 sweep
  stays for V1.
- **Phase 5 original (relation-type induction)**: deferred;
  answer-shaped nodes + Profile expansion cover breadth queries for now.
- **Workflow layer (LangGraph or similar)**: post-V1; the `orchestrator`
  project consumes this project via MCP.
- **Second pack**: per D1, ordering is legal → medical → compliance /
  research. Personal-documents pack stays as-is (already shipped); it is
  the dogfood and the back-stop, not a V1 target market.
- **`code_repos` pack**: structured code-repository ingestion —
  functions as entities, imports as relations, file paths as source
  locations. Overlaps with Sourcegraph / Cody / Aider repo-map.
  Dogfooding the `orchestrator` repo is a plausible first internal use;
  not a V1 target.
- **V2 consumer UI**: scoped in §2.6, not built in V1.

### 7.7 Open decisions (user input required)

These materially shape Phases 6–10. Ranked by how quickly the plan needs
them.

- **D1. B2B target domain.** Legal (notaries / SMB law firms) has the
  strongest fit on the "coherence matters" axis; medical has the strongest
  on "temporality matters"; research has the lowest regulation friction.
  Ranking preferred order affects the priority of the second pack and the
  shape of Phase 7 predicates. *Can proceed without for Phase 6; must
  resolve before Phase 7.*
  Response: this order is ok for me, but, do not forget that it shall also adapt to initial intent (personal docs like insurance, bank account..). It can be the last pack though.

- **D2. Contradiction default policy.** Proposal: unknown-variance
  predicates default to `Conflict`, not silent supersession. Confirm or
  override. *Needed for Phase 7.*
  Response: I agree with the proposal

- **D3. Versioning granularity.** Proposal: full re-extract of updated
  docs, old facts archived with `valid_to` set, old claims retained.
  Alternative: diff-based — cheaper but more complex. Pick. *Needed for
  Phase 8.*
  Response: Agree with the proposal

- **D4. Confidence exposure in API.** Proposal: every Fact carries a
  `confidence: float`; `/query` optionally filters `confidence >
  threshold`. Confirm or exclude. *Needed for Phase 6.*
  Response: Agree with the proposal
  **Revised 2026-05-10 (premortem D9 supersedes D4)**: float dropped,
  replaced by `ConfidenceLevel` enum
  (`deterministic | llm_high | llm_low`). Un-calibrated float is theatre
  and contradicts §1.2. See §3.2 + Phase 8b.2.

- **D5. Eval suite expansion budget.** Each new case ≈ 30–60 min authoring
  plus ongoing maintenance. Target 25–30 cases ≈ 10h of work. Scheduled
  explicitly? *Needed for Phase 9.*
  Response: Agree with the proposal

- **D6. Corpus extension for adversarial cases.** Current 32 docs
  likely too thin for Phase 7 eval. Need at least:
  - 2 known contradiction pairs (e.g. two docs with a time-varying fact
    that changed — address, employer, price — and at least one
    time-invariant conflict like a birthdate or ID-number mismatch).
  - 1 known duplicate pair (near-identical content, slightly different
    metadata).
  - 1 clear update pair (same document, two versions).

  **Please either flag existing contradictions/duplicates/updates you
  already know about in the corpus, or approve adding synthetic
  examples.** *Needed for Phase 7.*
  Response: Agree with the creation of synthetic data

- **D-refactor. Overlay vs. full refactor for facts.** Proposal above is
  the **overlay**: keep LightRAG entities/relations unchanged, derive
  Fact/Claim/Conflict as a parallel layer. Cheaper; ~2 weeks of work. The
  **full refactor** would replace LightRAG's triple store with a fact
  table as the system of record; more honest to the thesis but ~2 months
  of work with migration risk. Default is overlay. Push back if the bet
  justifies the refactor. *Needed for Phase 6.*
  Response: refactor as needed

- **D-deadline. Hard V1 date.** Is there a deadline driven by investor,
  employer, or customer conversation? Affects scope trimming. *Needed
  always.*
  Response: I'll get in touch with a lawyer in 2 days so I may come back with requirements soon
  Charter note (2026-04-24): lawyer meeting ≈ 2026-04-26. This is both a
  potential first B2B conversation and a concrete source of domain
  requirements (contract archive structure, clause versioning, party
  roles, notarial signing dates). Plan does not shift on a 2-day
  horizon, but requirements surfaced there will refocus the Phase 7
  predicate registry and may promote `legal` pack work ahead of Phase 9
  cleanup if the conversation converts. Follow-up expected within ~1 week.

### Decisions added 2026-05-10 (premortem)

- **D7. Admin conflicts GUI in V1**: yes (read-only dashboard with
  one-click resolve, emits YAML). Without it the SMB target market is
  inaccessible. Implemented in Phase 9.7. See §2.2.
- **D8. MCP before FastAPI**: yes. Phase 10 = MCP, Phase 11 = FastAPI.
  Built for the only concrete consumer (`orchestrator`), not a
  hypothetical HTTP one. See §7.5 / §7.5b.
- **D9. Confidence categorical, not float** (supersedes D4): enum
  `deterministic | llm_high | llm_low`. Honest by construction; float
  would require a calibration set we do not have. See §3.2 + §3.8c +
  Phase 8b.2.
- **D10. Sovereign-routable LLM in v0.5, not deferred**
  (supersedes §7.6 entry; revised 2026-05-10 after user's laptop
  reality-check ruled out local inference): one non-US-hosted model
  wired through `extraction/config.py`. v0.5 target = Mistral Small
  Latest via OpenRouter with `provider.order=["mistral"]` pinning
  (data stays in Paris). True local inference (Ollama/MLX) promoted
  to V1 when a customer asks for offline operation. See §3.8 rule 7
  + Phase 8b.4.
- **D11. End-to-end OCR stress in v0.5 corpus**: user requested
  exercising the full chain including OCR. Add representative scanned /
  degraded documents to the corpus (notarial / legal / medical / old
  invoices) — see Phase 8b corpus subtask. Raw scans only; no
  pre-OCR'd doctored content.

---

## 8. Open questions owed back to the user

1. Which of D1–D6 above are you ready to commit to, and which need more
   thought?
   Response: I answered inline
2. Is there a hard V1 date (investor, employer, customer conversation)?
   Response: I'll know it within a week max
3. Is the "small B2B niche" a deliberate optionality, or an
   actively-researched candidate you have not fully disclosed yet?
   Response: I can do this activity part time for now (aside from my employment), so I thought targetting small businesses would be more reasonable.
4. What is your appetite for the fact-model refactor (D-refactor)?
   Response: no issue with refactoring at all.

## 9. Notes from me
1. Ensure to keep a very very good UX => the app must be flexible/configurable enough but it will surface simple user interactions (given the audience)
   Charter response: accepted. Split §2.2 into three surfaces (admin /
   programmatic / consumer). New §2.6 scopes a consumer UI for V2 and
   constrains V1 API response shapes so the UI can be added without a
   breaking change. Admin surface keeps YAML + CLI; consumer surface is
   the simple-interaction layer for lawyers, GPs, compliance officers.
2. LLM usage and pricing are important to keep under control: the right model at the right price. Use SOTA for model selection for each stage of the app. I heard about Kimi k2.6?
   Charter response: accepted. New §3.8 "Multi-model routing" adds a
   stage → tier table (Cheap / Mid / Free / Premium), config-driven
   routing with fallbacks and a per-stage budget cap, and a mandatory
   benchmark harness before V1 with Kimi K2 family, Qwen, DeepSeek, and
   local open-weights all in the comparison. Rule added: no single
   stage may ship with < 2 viable models (sovereignty constraint).
3. Add in the roadmap the implementation of a MCP (or a better fitted API?) as I plan to give it to another project as food (see /Users/sboutet/projects/orchestrator)
   Charter response: accepted. New Phase 11 (§7.5b), target 2026-08-01,
   MCP server wrapping the Phase 10 service layer. FastAPI and MCP both
   wrap the same core — no duplicate logic. `orchestrator` is the first
   integration client. FastAPI stays for UI / non-agent integrations;
   MCP is purpose-built for LLM agent consumption and is the right
   surface for an agent orchestrator.
4. Can this project also ingest codebases (repos)?
   Charter response: out of V1 scope. Two framings: (a) code as text —
   READMEs, docstrings, docs/ — already flows through the existing
   Docling pipeline; (b) code as structured entities (functions,
   classes, imports, call graphs) — this is a `code_repos` pack and a
   multi-month undertaking that overlaps with Sourcegraph / Cody /
   Aider-repo-map. Listed in §7.6 deferred. Dogfooding the
   `orchestrator` repo is a plausible first internal use once V1 ships.
---

## Appendix A — Cross-references

- Session-by-session log: `docs/intent.md` (rolling).
- Corrections spec: this doc §3.3 + a future `corrections/README.md`.
- API spec (V1): `docs/api-v1.yaml` (pending Phase 10).

## Appendix B — Glossary

- **Fact**: a `(subject, predicate, value)` tuple with valid-time interval
  and an evidence chain of Claims. First-class.
- **Claim**: a single assertion of a Fact by one source at one extraction
  time, with confidence and extractor version.
- **Conflict**: two or more competing Facts on the same `(subject,
  predicate)` that the system did not automatically resolve.
- **Valid time**: the time a Fact held in the world.
- **Transaction time**: the time the system learned of a Fact (ingestion
  version).
- **Pack**: a pluggable domain module that declares entity types,
  extractors, predicate semantics, and retrieval hints.
- **Index node**: a synthetic graph node (Profile, Catalog) created for
  retrieval, not a real-world entity.
- **Correction**: a human-authored YAML file that overrides or resolves a
  pipeline output at one of three layers (source, derivation, memory).
- **MCP (Model Context Protocol)**: open standard for exposing
  capabilities as agent-callable tools. Phase 11 deliverable. FastAPI
  target = humans + deterministic integrations; MCP target = LLM agents.
- **Stage (LLM)**: a pipeline step that invokes an LLM (classification,
  extraction, query answering). Each stage has its own model tier per
  §3.8. Non-LLM stages (Docling, regex extractors, embeddings, rerank)
  are not "stages" in this sense.
