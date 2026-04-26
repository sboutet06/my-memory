# Implementation Tasks — my-memory next phases

Primary consumer: **Claude Sonnet 4.6** (`claude-sonnet-4-6`) executing in
Claude Code against this repository. Secondary: any human picking up the
work.

This file is the execution contract. The **charter**
(`docs/charter.md`) is the why/what/how. The **rolling log**
(`docs/intent.md`) is history. Do not duplicate their content here;
reference them.

---

## How to use this file (Claude Sonnet 4.6)

You are the implementer for the my-memory project. This file is your
execution contract.

**Your first actions, in order:**

1. Read §0 (Required reading). If any referenced file does not resolve
   on disk, STOP and ask the user.
2. Verify §1 (Project state) matches reality:
   ```bash
   git status
   source venv/bin/activate && python -m pytest -q -m "not integration"
   ```
   If state drifts from what §1 claims (branch, clean tree, test count,
   eval baseline), STOP and ask the user before editing anything.
3. **Begin Phase 0 (§5) immediately** — demo prep for the ≈ 2026-04-26
   lawyer meeting. Time-sensitive; blocks all subsequent phases.
4. When Phase 0 is user-approved and committed, proceed through
   Phases 6 → 11 in the order given.

You are the implementer, not a planner. Execute. Commit atomically.
Move on to the next task.

**Mark tasks done immediately.** When a task is complete and committed,
flip its checkbox from `[ ]` to `[x]` in this file. Do not batch. Do
not wait until the end of the phase. The checkbox is the live status
indicator for both the agent and the human reviewer.

**Never commit without the user's explicit approval** — present files
or diffs and wait. This overrides any inclination to "finish the task"
autonomously.

---

## 0. Required reading (before starting any task)

Read in order:

1. `docs/charter.md` — essence, decisions, gaps, plan. Every claim in
   this file descends from the charter.
2. `docs/intent.md` — phase-by-phase history; invaluable for the last 5
   sessions of context.
3. `~/.claude/CLAUDE.md` — user's global engineering rules (TDD,
   Conventional Commits, no-assumptions, SOTA-first design, self-review).
4. `~/.claude/lessons-learned.md` — documented gotchas; many
   directly apply (LightRAG quirks, LangGraph annotation traps, Docling
   ID-PDF layout, OpenRouter provider variance, NFC/NFD filenames).

If any of these does not resolve on your machine, **STOP and ask the
user**. Do not proceed on assumptions.

---

## 1. Project state (as of 2026-04-24)

- Repo root: `/Users/sboutet/projects/my-memory`
- Branch: `master`, tree clean.
- Python 3.13 in `venv/`; activate with `source venv/bin/activate`.
- Tests: **404 passing**. Run
  `python -m pytest -q -m "not integration"`.
- Eval: 11 cases, `python -m evaluation --runs 3`, `temperature=0`
  reproducible. Baseline:
  - mean `doc_coverage` = **0.92**
  - mean `entity_coverage` = **0.98**
  - mean `fact_coverage` = **1.00**
  - passing **7 / 11** cases
- Corpus: 32 documents across `raw/` + `raw-2/`, ingested to `store/`.
- Extraction store: `extraction_store/` — 2229 entities, 2060 edges,
  87 synthetic index nodes, 32 summary chunks, 22 structured nodes.
- Packs: `personal_documents` installed (22 life-domain entity types,
  Transaction extractor, extraction hints, low-signal-type hook).
- API: not started.

Charter §4 holds the authoritative snapshot — consult it if this section
drifts.

---

## 2. Decision state

**Locked** (per charter §7.7 user responses on 2026-04-24):

| Decision | State |
|---|---|
| **D-refactor** | **Overlay** approach — Fact/Claim/Conflict as a new layer on top of LightRAG, not a replacement. Escalate to user with evidence if Phase 7 data shows the overlay cracks; otherwise stay overlay. |
| **D1** (B2B target ranking) | `legal → medical → compliance/research → personal_documents`. Personal-docs pack stays as-is (already shipped). |
| **D2** (contradiction default) | Unknown-variance predicates default to `Conflict`, not silent supersession. |
| **D3** (versioning granularity) | Full re-extract on updated docs; old facts archived with `valid_to` set; old claims retained. |
| **D4** (confidence in API) | Every Fact carries `confidence: float`. `/query` filter on confidence is optional. |
| **D5** (eval expansion budget) | 25–30 cases total, ~10h budget. Phase 9 work. |
| **D6** (synthetic adversarial corpus) | Approved. Generate synthetic contradiction pairs, duplicate pair, update pair before Phase 7. |

**Pending user input** — STOP and ask before crossing the relevant gate:

- **Lawyer-meeting requirements** (expected by ~2026-05-01): may refocus
  Phase 7 predicate registry toward legal predicates (contract clauses,
  party roles, notarial dates). Do not start Phase 7 predicate design
  without checking whether the user has follow-up from that meeting.
- **Benchmark model list** (Phase 6.6): do not run paid benchmarks
  without user approval of the model list.
- **Any dependency addition**: license, maintenance status, vulnerability
  count, install-size impact must be presented to the user before
  `pip install` / `pyproject.toml` edit.

---

## 3. Guardrails (non-negotiable)

Distilled from `~/.claude/CLAUDE.md` and project conventions. If any of
these is violated in a commit, revert and retry.

1. **TDD mandatory** — red → green → refactor. Write the failing test
   first; never add logic without a test that justifies it.
2. **Atomic Conventional Commits** — one logical change per commit.
   Format: `type(scope): subject` with imperative mood, subject < 72
   chars, body explains *why* not *what*.
3. **Phase gate is an e2e corpus run, not unit tests** — the project
   memory records a lesson: "unit tests alone don't close a phase; run
   real corpus + analyze output". For each phase:
   `python -m evaluation --runs 3` must meet the Done Criteria, AND the
   user must eyeball the output.
4. **No eval regression** — on the 11 existing cases, `doc_coverage ≥
   0.92`, `entity_coverage ≥ 0.98`, `fact_coverage ≥ 1.00`. Any drop is
   a blocker; identify the commit, revert, diagnose.
5. **No domain types in core** — core stays generic. Legal / medical /
   finance / research types live under `packs/`. If a commit introduces
   `"legal_contract"` to a core module, it is wrong.
6. **No assumptions** — if a requirement is unclear, a library version
   is unverified, or a file's behavior is unknown: STOP, ask, or read /
   run. Never commit a `# assuming X` comment.
7. **SOTA-first design** — for any non-trivial new module, survey
   current-year approaches (research libs, RFCs, blog posts). Present
   three approaches with tradeoffs; get user approval before committing
   to one.
8. **No destructive git** — no `reset --hard`, no force-push, no branch
   delete, no `rm -rf` on a tracked path without explicit user
   confirmation for the specific command.
9. **No dependency addition without check** — present license,
   maintenance status, vulnerability count, install-size impact to the
   user BEFORE installing. Dependencies already in `pyproject.toml` are
   fine.
10. **No LightRAG lock-in deepening** — every new touch of LightRAG
    internals (undocumented methods, private attributes) goes through a
    wrapper. Charter §5.2 A3 mandates `QueryDriver` +
    `ReferenceExtractor` interfaces with LightRAG as ONE
    implementation; honor this as you go, don't wait for Phase 9.
11. **All LLM calls through `extraction/config.py`** — no scattered
    model IDs, no scattered API keys, no direct OpenRouter calls.
12. **Budget cap respected** — any phase introducing new LLM calls
    implements the per-stage budget cap (charter §3.8 rule 3). Abort +
    report if exceeded, never swallow.
13. **Admin correction UX stays YAML + Git** — no GUI for corrections in
    V1. Consumer UI (§2.6 charter) is V2.
14. **Post-implementation self-review** per `~/.claude/CLAUDE.md §7` —
    spec conformance, OWASP Top 10, resilience, reliability, resource
    pressure, observability, testability. Any 🔴 must be fixed before
    declaring the phase complete. Post a short report in the PR /
    session recap.
15. **Do not bypass hooks** — no `--no-verify`, no
    `--no-gpg-sign`. If a pre-commit hook fails, fix the underlying
    issue and create a NEW commit; do not amend or skip.

---

## 4. Environment

```bash
# From repo root
source venv/bin/activate

# Unit tests
python -m pytest -q -m "not integration"

# Integration tests (slower)
python -m pytest -q -m integration

# Eval (temp=0, deterministic, ~2 min)
python -m evaluation --runs 3

# Eval diagnostics (per-stage retrieval retention)
python -m evaluation --diagnose
python -m evaluation --diagnose --case <case-id>

# Pipeline
python -m ingestion <path>                     # ingest one file or dir
python -m ingestion classify [--doc-id X]      # (re)classify
python -m ingestion reocr <doc_id> [--backend ocrmac]
python -m extraction extract [--no-focus-hints]
python -m extraction dedupe [--apply]
python -m extraction emit-corrections
python -m extraction apply-corrections [--apply]
python -m extraction extract-structured [--dry-run]
python -m extraction enhance-retrieval
python -m extraction build-indexes [--dry-run]
python -m extraction annotate-temporal
python -m extraction query "..."
python -m extraction diagnose "..."
python -m corrections review [source|entity-types|aliases] [--all]
python -m corrections show <slug-or-doc-id>
python -m corrections stats
```

`pyproject.toml` is the source-of-truth for dependencies.

---

## 5. Execution order

Phases run **strictly sequentially**. Do not start Phase N+1 before
Phase N is merged to `master` AND its Done Criteria are met. Each phase
below contains: a **paste-at-session-start prompt**, **tasks**, and
**Done criteria**.

- **Phase 0 — demo prep for lawyer meeting (BLOCKING, ~2026-04-25)**
- Phase 6 — fact model and provenance
- Phase 7 — contradictions as first-class
- Phase 8 — bitemporal validity and versioning
- Phase 9 — cleanup and hardening
- Phase 10 — FastAPI V1
- Phase 11 — MCP server

---

## Phase 0 — Demo prep for lawyer meeting

**Target**: 2026-04-25 (before lawyer meeting ≈ 2026-04-26).
**Priority**: BLOCKING. Do this before starting Phase 6.
**Estimated effort**: 2–3 hours.
**Depends on**: nothing — current state is sufficient.

This phase produces a 5-minute live demo script in French for the
user's lawyer meeting. It uses only the existing 32-document corpus
and the existing CLIs — no code change outside of adding the demo
script and a shell helper.

### Prompt to paste at session start

> Read `docs/charter.md` §0–§2 and §4 (current state); read
> `docs/pitch-legal-fr.md` in full; read `tasks.md` §1, §2, §3, §4.
>
> You are executing **Phase 0: demo prep for the lawyer meeting** on
> ≈ 2026-04-26. Your deliverable is `docs/demo-legal-fr.md` plus a
> rerunnable `scripts/demo.sh`.
>
> The corpus is a dogfood set (personal documents), not a legal
> archive. Choose queries that read naturally as "archive questions"
> a lawyer would intuit — the `Compromis de vente` notarial document,
> insurance / employment / tax / identity documents. **Avoid anything
> that reveals information the user would not want a third party to
> see; when in doubt, ASK the user before embedding an output in the
> demo script.**
>
> Execute tasks 0.1 → 0.4 in order. **No code changes outside
> `docs/demo-legal-fr.md` and `scripts/demo.sh`.** No Phase 6 work
> until Phase 0 is user-approved and committed.
>
> Stop conditions: any of the 3 candidate queries fails to return a
> meaningful answer; state drift detected; user declines a proposed
> query; eval or tests regress.

### Tasks

- [x] **0.1 Audit candidate queries against the corpus**
  - Verify tests + eval pass (§4). If not, stop and report.
  - Draft 3–5 candidate French queries per pillar:
    - *Provenance* — any identity / signature / date query likely to
      return a document-level citation. Example seed: *« Qui sont les
      parties au compromis de vente et quelle est la date de signature ? »*
    - *Cohérence* — a query whose answer exists in multiple
      documents with potentially different values, so the user can
      observe the graph holds the raw material but does not yet emit
      `Conflict` objects. Example seed: *« Quelles adresses
      apparaissent pour Sébastien Boutet dans les documents ? »*
    - *Temporalité* — a query whose answer depends on dates carried
      by the existing `[sourced: YYYY-MM-DD]` annotations. Example
      seed: *« Quelle est l'adresse la plus récente mentionnée dans
      les documents ? »*
  - Run each via `python -m extraction query "..."`. Capture exact
    outputs including the `### References` block.
  - Select 1 finalist per pillar based on:
    - deterministic answer (temp=0 reruns → identical output)
    - readable citations that map to real docs
    - content the user is likely comfortable sharing with a lawyer
    - runtime < 10 seconds
  - Present finalists + outputs to the user for approval **before
    moving to 0.2**. Flag any query whose output contains content
    that might be sensitive.

- [x] **0.2 Write `docs/demo-legal-fr.md`**
  - French, ~5-minute live walkthrough, matching the pitch structure:
    - **0:00–0:30** Elevator + problem statement (distill from
      `docs/pitch-legal-fr.md` §1).
    - **0:30–1:30** *Provenance* — run finalist #1 live, show
      `### References` block, articulate the Phase 6 delta
      (fact-level provenance, API `/facts/{id}`, mi-mai 2026).
    - **1:30–2:30** *Cohérence* — run finalist #2 live, show the
      graph holds multiple values but does not yet surface conflicts,
      articulate Phase 7 delta (Conflict objects, YAML resolution,
      début juin 2026).
    - **2:30–3:30** *Temporalité* — run finalist #3 live, show the
      `[sourced: ...]` annotations, articulate Phase 8 delta
      (bitemporal validity, `as_of` queries, mi-juin 2026).
    - **3:30–4:30** Roadmap table (reuse from pitch) + sovereignty
      block (local-first, modèles ouverts option, RGPD, archivage
      probant).
    - **4:30–5:00** Three discovery questions from the pitch
      closing; propose a pilote sur un sous-corpus représentatif.
  - Embed the finalist query outputs verbatim (redacted if the user
    requested redactions in 0.1).
  - Be honest about gaps. Every pillar explicitly states what V0
    does NOT yet do and when the gap closes.
  - No tech brand names in the body (no Docling, LightRAG, Gemini,
    Neo4j, LangGraph). The lawyer does not care about the stack.

- [x] **0.3 Rerunnable `scripts/demo.sh`**
  - Create `scripts/` if it does not exist.
  - `scripts/demo.sh` sources the venv and runs the 3 finalist
    queries in sequence with a clear separator between each.
  - Each query prefixed by a `echo "=== <pillar> — <question> ==="`
    line so the user can follow along during the demo.
  - Shell style: `set -euo pipefail`, shellcheck clean, no
    over-engineering.
  - Verify: `bash scripts/demo.sh` produces output identical to the
    excerpts embedded in `docs/demo-legal-fr.md` (temp=0 ensures
    byte-identical reruns).

- [x] **0.4 User review gate + commit**
  - Before committing anything, show the user:
    - The full `docs/demo-legal-fr.md`.
    - The full `scripts/demo.sh`.
    - A sample run of `bash scripts/demo.sh`.
  - Invite content review (sharing comfort, accuracy of Phase 6/7/8
    claims, tone).
  - Adjust per user feedback until approved.
  - On explicit user approval, commit with:
    - `docs(demo): add legal-audience demo script (FR)`
    - `chore(scripts): add demo.sh runner for 3 pillar queries`
  - Two commits, one per file, following the one-change-per-commit
    rule.

### Done criteria (Phase 0)

- `docs/demo-legal-fr.md` committed, user-approved.
- `scripts/demo.sh` committed, executable (`chmod +x`), reruns
  produce the embedded outputs.
- `python -m pytest -q -m "not integration"` still passing (zero
  test-count change expected for Phase 0).
- `python -m evaluation --runs 3` still meets baseline.
- No code changes outside the two new files.

---

## Phase 6 — Fact model and provenance

**Target**: 2026-05-15.
**Depends on**: current state (Phase 5.7 merged — done).

### Prompt to paste at session start

> Read `docs/charter.md` §3.2, §7.1, §7.7 D-refactor, and
> `docs/intent.md` §440-end (the last two session recaps). Then read
> `tasks.md` §1 (project state), §2 (decisions), §3 (guardrails), §4
> (environment).
>
> You are implementing **Phase 6: fact model and provenance** for the
> my-memory project.
>
> The approach is **overlay** (charter D-refactor locked): `Fact`,
> `Claim`, `Conflict` live as a new layer on top of LightRAG, not a
> replacement. LightRAG's entity/relation store remains the retrieval
> substrate.
>
> Execute tasks **6.1 → 6.6 in order**. TDD throughout. After each
> task:
> 1. `python -m pytest -q -m "not integration"` must pass.
> 2. `python -m evaluation --runs 3` must meet no-regression threshold.
> 3. Commit with Conventional Commits (scopes: `feat(facts)`,
>    `feat(pack)`, `feat(api)`, `test(facts)`, …).
>
> Do not skip, reorder, or bundle tasks into one commit.
>
> Ask the user before: (a) adding a dependency; (b) any destructive
> action; (c) making a design choice that conflicts with the charter;
> (d) running paid benchmarks.
>
> Stop conditions (revert and report):
> - Eval regresses (`doc_coverage < 0.92` or `fact_coverage < 1.00` on
>   existing cases).
> - Tests red.
> - Scope drift into Phase 7 / 8 territory (conflict detection,
>   bitemporal validity).
>
> Produce a session recap in the style of the existing `docs/intent.md`
> commits (`docs(intent): phase 6 recap — ...`).

### Tasks

- [x] **6.1 Fact/Claim/Conflict schema**
  - Create `facts/` package at repo root (sibling of `extraction/`,
    `corrections/`, `packs/`).
  - Pydantic models: `Fact`, `Claim`, `Conflict`, `Predicate` (registry
    entry for Phase 7 consumption — define shape now, use it next phase).
  - `Fact.id` is **content-addressable**: SHA-256 of
    `subject_id + predicate + canonical_value + source_doc_id`.
  - `Claim.id` similarly content-addressable.
  - Storage: JSONL on disk — `facts/store/facts.jsonl`,
    `facts/store/claims.jsonl`, `facts/store/conflicts.jsonl`. One
    record per line, append-only. Index in memory on load.
    Migrate to DuckDB only if volumes after 6.2 demand it (escalate).
  - Lesson applies (2026-04-15): "JSONL event streams beat sqlite for
    short-lived audit trails — greppable, tailable, diffable".
  - Tests (≥ 15): ID stability under field reordering, validation,
    round-trip serialization, invalid-payload rejection, empty-store
    initialization, append + reload, duplicate-ID rejection.
  - Commits: `feat(facts): add Fact/Claim/Conflict schemas`,
    `feat(facts): JSONL-backed store`, `test(facts): …`.

- [x] **6.2 Bank statement pack migration to facts**
  - Modify `packs/personal_documents/injector.py` to emit a `FactResult`
    (collection of Facts + Claims) alongside existing LightRAG nodes.
  - Each bank `Transaction` row → 1 `Fact(subject=account_entity,
    predicate='transaction', value=<Transaction payload>)` + 1
    `Claim(source_doc_id, source_location={page, row_index},
    extractor='pack:bank_statement@<version>', confidence=1.0)`.
  - Deterministic extractor ⇒ `confidence = 1.0`.
  - Integration test on the known bank statement in `raw/`: assert
    `len(facts) == len(transactions)` and Claim chain is correct.
  - Eval: `aggregation-expenses` case `doc_coverage` must stay `1.00`.
  - Commits: `feat(pack): bank_statement emits FactResult`,
    `test(pack): …`.

- [x] **6.3 Pack hook extension**
  - Add `inject_facts(rag, facts_store, result) -> FactResult` to the
    `Pack` protocol in `packs/__init__.py`.
  - Core iterates discovered packs, calls the hook, collects facts. Put
    this orchestration in `facts/orchestrator.py` (new) or extend
    `extraction/structured.py` — prefer the new location to keep the
    dependency direction right (core calls packs, not vice-versa).
  - Backward-compat: a pack without `inject_facts` continues to work
    (use `getattr(pack, 'inject_facts', None)`).
  - Tests: stub Pack without the hook → empty `FactResult`, no errors;
    `personal_documents` pack → populated `FactResult`.
  - Commits: `feat(core): Pack.inject_facts hook`,
    `refactor(facts): orchestrator calls pack hooks`.

- [x] **6.4 API stub**
  - **ASK USER** before adding `fastapi` and `uvicorn` to
    `pyproject.toml`. Present: license (MIT / BSD-3), maintenance
    status (active), install-size impact, no known CVEs as of 2026-04.
  - Create `api/` package. `api/main.py` with a FastAPI app.
  - Endpoints (V1 stub — Phase 10 hardens):
    - `GET /health` → `{"status": "ok"}`.
    - `GET /facts/{fact_id}` →
      `{"fact": ..., "claims": [...], "conflicts": [...]}`. Conflicts
      list is empty until Phase 7.
  - 404 on missing fact, 422 on malformed fact_id.
  - Tests via `httpx.AsyncClient(app=app)` — do NOT start a real
    uvicorn in tests.
  - Add a `python -m api` entry point for manual curl testing.
  - No auth, no CORS config, no rate limiting — stub only.
  - Commits: `feat(api): stub FastAPI app + /facts/{id}`,
    `test(api): …`.

- [x] **6.5 Fact-level eval cases**
  - Extend `evaluation/cases.json` with 5 cases targeting fact-level
    provenance:
    1. `fact-evidence-bank-tx` — "What evidence supports the
       Transaction of €X on YYYY-MM-DD?" — expected: Claim carrying
       `source_doc_id = <bank_statement_id>`.
    2. `fact-source-address` — "Which document asserts the current
       address of <Person>?" — expected list of `source_doc_ids`.
    3. `fact-list-by-source` — "List all facts extracted from document
       Z." — expected `fact_ids` from that document.
    4. `fact-confidence` — "What is the confidence score for fact
       F?" — expected confidence value range.
    5. `fact-extractor-version` — "Which extractor produced fact F?" —
       expected extractor string.
  - Scoring: new `fact_provenance_coverage` metric in
    `evaluation/scorer.py`. Reuse the accent-folded substring/set
    scoring pattern already in place (lesson 2026-04-18 on
    accent+case-insensitive scoring).
  - Pass criterion: mean `fact_provenance_coverage ≥ 0.80` on the 5 new
    cases.
  - **Existing 11 cases must not move by more than ±0.01** on any
    metric.
  - Commits: `test(eval): fact-level provenance cases`,
    `feat(eval): fact_provenance_coverage metric`.

- [x] **6.6 Multi-model benchmark scaffolding (scaffold only, no full
    run)**
  - Charter §3.8 requires ≥ 2 viable models per stage before V1 ships.
    This task builds the measurement scaffolding; the actual benchmark
    sweep happens after user approval.
  - Create `benchmarks/` package with `benchmarks/README.md` listing
    the proposed model set per stage: Kimi K2 family, Qwen-2.5,
    DeepSeek V3, Claude Haiku 4.5, Gemini 2.5 Flash (current), local
    open-weights (Gemma 3n, Llama-4 when available).
  - `benchmarks/runner.py` — `run(stage, model_list, case_limit)`
    takes the eval pipeline and swaps only the targeted stage.
  - Implement only for the **query answerer** stage here. Smoke test:
    1 case × 1 model (current Gemini) — must produce the same output
    as `python -m evaluation` for that case.
  - **Do NOT run paid benchmarks yet.** Surface the model list to the
    user and wait for approval before any multi-model sweep.
  - Commits: `feat(benchmarks): runner scaffold + README`,
    `test(benchmarks): smoke test query-answerer swap`.

### Done criteria (Phase 6)

- All 6.1 → 6.6 merged to `master`.
- `python -m pytest -q -m "not integration"`: > 404 tests, all
  passing.
- `python -m evaluation --runs 3`:
  - Original 11 cases: `doc_coverage ≥ 0.92`, `entity_coverage ≥
    0.98`, `fact_coverage ≥ 1.00`.
  - 5 new fact-provenance cases: mean `fact_provenance_coverage ≥
    0.80`.
- End-to-end trace: one bank-statement Transaction visible from
  `python -m extraction extract-structured` → `facts/store/facts.jsonl`
  → `GET /facts/{id}` → JSON payload usable by a consumer UI.
- `docs/intent.md` updated with `docs(intent): phase 6 recap — ...`
  commit.
- Self-review report per guardrail 14 posted in the session recap.

Expected commit count: 10–14.

---

## Phase 7 — Contradictions as first-class

**Target**: 2026-06-01.
**Depends on**: Phase 6 merged + Done Criteria met.

### Prompt to paste at session start

> Read `docs/charter.md` §3.5, §7.2. Phase 6 must be merged and green.
>
> You are implementing **Phase 7: contradictions as first-class**.
>
> **STOP BEFORE STARTING** and ask the user to:
> 1. Approve the synthetic contradiction / duplicate / update corpus
>    generation plan (D6 — locked, but the specific documents need user
>    review before extraction pollutes the graph).
> 2. Confirm whether the lawyer meeting (≈ 2026-04-26) surfaced concrete
>    predicate requirements — contract clauses, party roles, notarial
>    dates — that should be first-class Phase 7 predicates.
>
> Proceed only once (1) is approved.
>
> Execute tasks 7.1 → 7.5 in order. Same commit / eval / guardrail
> rules as Phase 6.

### Tasks (outline — expand when Phase 6 lands)

- [x] **7.1 Predicate registry in core**
  - `facts/predicates.py`. Registry entries: `name`, `time_varying:
    bool`, `allow_multi: bool`, optional `description`.
  - Packs declare predicates via a `Pack.predicates: tuple[Predicate,
    ...]` attribute.
  - Core default for unknown predicates: `time_varying=False,
    allow_multi=False` — unknown-variance defaults to Conflict (D2).

- [x] **7.2 Conflict detector**
  - On each fact write (or a batch reconcile job), compare against
    existing facts with the same `(subject, predicate)`.
  - If not `allow_multi` and values differ, emit a `Conflict` record
    with status `open`.
  - Batch reconcile: `python -m facts detect-conflicts`.

- [x] **7.3 Conflict correction YAML**
  - `corrections/derivation/conflicts/<conflict_id>.yaml` with seeded
    doubts + override section.
  - Resolution options: `winner: <fact_id>`, `coexist: true`,
    `temporal_supersede: {order: [fact_id, ...]}`.
  - Reuse ruamel.yaml + inline hint comments (Phase 3.5 pattern).
  - Idempotent re-apply: applying N times = same state.

- [x] **7.4 API**
  - `GET /conflicts?status=open&limit=N`.
  - `GET /conflicts/{id}` — full detail with competing facts + claims.
  - `POST /conflicts/{id}/resolve` — stub; actual resolution still
    flows through YAML + Git.

- [x] **7.5 Adversarial eval bucket**
  - Generate 5 synthetic cases (D6 approved):
    - 2 contradiction pairs (time-varying: e.g. two different
      addresses ~5 years apart; time-invariant: e.g. two different
      birthdates).
    - 1 duplicate pair (near-identical docs, different metadata).
    - 1 update pair (same doc, two versions).
    - 1 negative query (person not in corpus).
  - New metric `conflict_detection_coverage` in scorer.
  - Pass criterion: `conflict_detection_coverage ≥ 0.90` on the
    synthetic contradictions.
  - Synthetic docs live under `raw-synthetic/` — isolated from real
    corpus to keep dogfood data clean.

### Done criteria (Phase 7)

Same discipline as Phase 6. Additional:
- `conflict_detection_coverage ≥ 0.90` on synthetic cases.
- Existing 11 cases + 5 Phase 6 fact cases must not regress.

---

## Phase 8 — Bitemporal validity and versioning

**Target**: 2026-06-15.
**Depends on**: Phase 7 merged + green.

### Prompt to paste at session start

> Read `docs/charter.md` §3.5, §7.3. Phases 6–7 must be merged and
> green.
>
> You are implementing **Phase 8: bitemporal validity and versioning**.
>
> Same commit / eval / guardrail discipline.

### Tasks (outline)

- [x] **8.1** `valid_from` / `valid_to` fields on Fact. Migration
  populates these from existing `[source: YYYY-MM-DD]` description
  annotations where possible; leaves NULL otherwise.
- [ ] **8.2** `ingestion_version: int` on Claim. Re-ingest of the same
  doc creates a new version; old version is archived, not deleted.
  Archive layout: `store/<doc_id>/versions/<v>/` with `current` symlink
  or pointer file.
- [ ] **8.3** Wire `replaced_by` YAML field into the ingest pipeline
  (currently declared but unimplemented — charter S4).
- [x] **8.4** Supersession engine: for `time_varying=true` predicates,
  a new Fact with later `valid_from` closes the previous one (sets its
  `valid_to`). Old Fact is not deleted.
- [x] **8.5** API: `GET /entities/{id}?as_of=YYYY-MM-DD` — executes
  against fact set filtered by `valid_from ≤ as_of ≤ valid_to (or
  NULL)`.
- [x] **8.6** Eval: 5 update cases (synthetic from D6); 3
  time-varying-vs-invariant contradiction cases. New metric
  `temporal_accuracy` (are `as_of` queries correct?).

### Done criteria

- `as_of` queries work end-to-end.
- Re-ingesting any document does not erase history.
- `temporal_accuracy ≥ 0.90` on update cases.

---

## Phase 9 — Cleanup and hardening

**Target**: 2026-07-01.
**Depends on**: Phases 6–8 green.

### Prompt

> Read charter §7.4. Phase 9. Depends on 6–8 merged + green.

### Tasks (outline)

- [ ] **9.1** Profile fragmentation fix — charter A1. Rerun alias
  resolution AFTER `build-indexes`, or generate Profile nodes only for
  alias-clustered canonicals.
- [ ] **9.2** `:Entity` vs `:IndexNode` namespace separation — charter
  A2. API `/entities` must filter synthetic nodes out by default.
- [ ] **9.3** `QueryDriver` + `ReferenceExtractor` interface
  extraction — charter A3. LightRAG becomes ONE implementation.
- [ ] **9.4** Incremental extraction — only re-extract changed docs
  (charter A4). Document hash + timestamp comparison.
- [ ] **9.5** Eval expansion to 25–30 cases total (charter E1, D5).
  Budget ~10h.
- [ ] **9.6** CI gate: GitHub Actions (or equivalent) runs
  `pytest + evaluation`. Blocks PRs that regress any metric by more
  than ±0.02.

### Done criteria

- Eval suite ≥ 25 cases.
- CI gate live and blocking.
- Full-corpus incremental re-extract: unchanged docs skipped.

---

## Phase 10 — FastAPI V1

**Target**: 2026-07-15.
**Depends on**: Phases 6–8 green. **Do NOT start earlier.** (Charter
rationale: starting the API before the semantic foundations locks in
wrong contract shapes.)

### Prompt

> Read charter §2.2, §2.6, §7.5. Phase 10. Do not start before Phases
> 6–8 are green.
>
> Response shapes are pre-constrained by charter §2.6 (consumer UX for
> V2). Every response must carry: structured answer, inline citation
> markers mapped to fact IDs, per-fact confidence, conflict IDs where
> relevant, provenance trail. No opaque strings.

### Tasks (outline)

- [ ] **10.1** All endpoints from charter §2.2 — `/documents`,
  `/entities`, `/facts`, `/conflicts`, `/search`, `/query`.
- [ ] **10.2** OpenAPI spec committed as `docs/api-v1.yaml`.
- [ ] **10.3** Auth + rate limiting + CORS (production-ready; replaces
  Phase 6.4 stub).
- [ ] **10.4** Integration tests per endpoint.
- [ ] **10.5** Response-shape conformance test: every endpoint returns
  the fields required by the §2.6 consumer UI mock.

---

## Phase 11 — MCP server

**Target**: 2026-08-01.
**Depends on**: Phase 10 service layer stable. May run partially in
parallel with Phase 10 once the service layer stabilizes.

First integration client: `orchestrator` project at
`/Users/sboutet/projects/orchestrator`.

### Prompt

> Read charter §2.2, §7.5b. Phase 11 — MCP server.
>
> Both FastAPI (Phase 10) and MCP wrap the **same service layer**; no
> duplicate business logic. If adding a capability on one side would
> require duplicating logic, stop and refactor the service layer first.
>
> Use the Anthropic MCP Python SDK — **ASK USER** before adding it to
> `pyproject.toml` with license / maintenance / CVE check.
>
> Tool descriptions target LLM agent consumption: cost-per-call hint,
> response-shape example, common pitfalls, idempotency guarantee.

### Tasks (outline)

- [ ] **11.1** MCP server scaffolded using the latest Anthropic MCP
  Python SDK.
- [ ] **11.2** Tools exposed:
  - `my_memory.search(query)` — hybrid retrieval.
  - `my_memory.fact_get(fact_id)` — fact + provenance + conflicts.
  - `my_memory.entity_get(entity_id, as_of?)` — entity temporal view.
  - `my_memory.conflicts_list(filter?)` — open conflicts.
  - `my_memory.document_get(doc_id)` — metadata + content.
- [ ] **11.3** End-to-end integration test with a mock `orchestrator`
  client: request a fact → receive provenance → resolve a conflict via
  YAML → re-query → receive resolved value, all over MCP.
- [ ] **11.4** Audit pass before merge: zero duplicate logic between
  FastAPI and MCP.

### Done criteria

- Orchestrator (or a mock thereof) can round-trip a fact-resolution
  flow via MCP.
- No business logic duplicated between the two surfaces.

---

## 6. When to escalate (STOP and ask user)

- A locked decision (§2) is being challenged by new data — e.g. the
  overlay approach is cracking under Phase 7 data volume. Surface
  evidence, propose a path.
- A required decision (§2 Pending) is needed to proceed.
- A dependency needs to be added — license / maintenance / CVE check
  must be presented.
- Eval regresses — do NOT keep working past the regression; revert,
  identify the commit, report.
- A destructive git action would be needed.
- A design choice conflicts with the charter.
- Scope of a phase threatens to expand beyond its task list — do NOT
  silently expand; ask first.
- Lawyer-meeting follow-up arrives from the user and may change Phase
  7 predicate priorities — integrate before continuing.

## 7. Reference

- Charter: `docs/charter.md`
- Rolling log: `docs/intent.md`
- Pitch (FR, legal audience): `docs/pitch-legal-fr.md`
- Global engineering rules: `~/.claude/CLAUDE.md`
- Lessons learned: `~/.claude/lessons-learned.md`
- Memory index:
  `~/.claude/projects/-Users-sboutet-projects-my-memory/memory/MEMORY.md`

On phase completion: append a session recap to `docs/intent.md`
following the existing convention
(`docs(intent): phase N recap — <summary>`).
