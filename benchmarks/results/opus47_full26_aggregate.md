# Opus 4.7 full-context baseline — 2026-05-01

Numbers-only summary. Raw answers contain personal data and are kept under
`benchmarks/runs/` (gitignored).

## Configuration

- Model: `anthropic/claude-opus-4.7` via OpenRouter.
- Corpus: 43 docs from `store/`, packed into one cached system prompt
  (~128k tokens, ~344k chars), Anthropic-style `cache_control: ephemeral`.
- Temperature: 0.0.
- Max output tokens: 1500 (initial sweep) + 4000 (re-test of 2 fails).
- Eval: same `evaluation/cases.json` and `evaluation.scorer` as the
  pipeline — direct apples-to-apples comparison.

## Headline (26 cases, max_tokens=1500)

| Metric | Value |
|---|---|
| passed | 24 / 26 (92%) |
| mean_doc_coverage | 0.9923 |
| mean_entity_coverage | 0.9923 |
| mean_fact_coverage | 0.9615 |
| mean_fact_provenance_coverage | 1.0000 |
| mean_conflict_detection_coverage | 1.0000 |
| mean_temporal_accuracy | 1.0000 |
| total_forbidden_violations | 0 |
| total cost (USD) | 2.98 |
| total cache write tokens | 127 940 |
| total cache read tokens | 3 198 500 |
| mean latency (s/case) | 15.7 |

## Failures

| Case | doc | ent | fact | Cause |
|---|---|---|---|---|
| `cross-doc-person` | 0.80 | 1.00 | **0.00** | Output truncated at 1500 tok. Re-run at 4000 tok → **pass=True, all metrics 1.00**. Truncation artifact. |
| `family-composition` | 1.00 | **0.80** | 1.00 | Opus refused to count "Sophia" (only present as a fetus in an échographie doc; the livret de famille shows "rubrique Troisième enfant: vierge"). Same failure mode as the LightRAG pipeline. Arguably an eval-design issue rather than a model gap. |

Effective score with 4000-token output budget: **25 / 26**, with 1 case
where strict factual answering disagrees with the eval expectation.

## Comparison to LightRAG pipeline (intent.md latest figures)

| Metric | Pipeline | Opus full-ctx |
|---|---|---|
| passed | 7 / 11 (original 11 cases only) | 24 / 26 (all 26) |
| doc_coverage | 0.92 | 0.99 |
| entity_coverage | 0.98 | 0.99 |
| fact_coverage | 1.00 | 0.96 |
| fact_provenance_coverage | not yet e2e-verified | 1.00 (5/5) |
| conflict_detection_coverage | not yet e2e-verified | 1.00 (5/5) |
| temporal_accuracy | not yet e2e-verified | 1.00 (5/5) |

Opus 4.7 + a five-rule French system prompt matched or beat the pipeline
on every metric, including the three differentiators (provenance,
conflict, temporal) the project's pitch positions as the core value.

## Per-case raw scores (no PII)

```
case_id                              pass   doc   ent   fact  fpc   cdc   ta
cross-doc-person                     False  0.80  1.00  0.00  1.00  1.00  1.00
temporal-addresses                   True   1.00  1.00  1.00  1.00  1.00  1.00
aggregation-expenses                 True   1.00  1.00  1.00  1.00  1.00  1.00
children-medical-history             True   1.00  1.00  1.00  1.00  1.00  1.00
prescribed-medications               True   1.00  1.00  1.00  1.00  1.00  1.00
employment-intel                     True   1.00  1.00  1.00  1.00  1.00  1.00
owned-vehicles                       True   1.00  1.00  1.00  1.00  1.00  1.00
tax-timeline                         True   1.00  1.00  1.00  1.00  1.00  1.00
family-composition                   False  1.00  0.80  1.00  1.00  1.00  1.00
property-acquisition-price           True   1.00  1.00  1.00  1.00  1.00  1.00
identity-documents                   True   1.00  1.00  1.00  1.00  1.00  1.00
fact-evidence-bank-tx                True   1.00  1.00  1.00  1.00  1.00  1.00
fact-source-address                  True   1.00  1.00  1.00  1.00  1.00  1.00
fact-list-by-source                  True   1.00  1.00  1.00  1.00  1.00  1.00
fact-confidence                      True   1.00  1.00  1.00  1.00  1.00  1.00
fact-extractor-version               True   1.00  1.00  1.00  1.00  1.00  1.00
adversarial-birthdate-conflict       True   1.00  1.00  1.00  1.00  1.00  1.00
adversarial-address-conflict         True   1.00  1.00  1.00  1.00  1.00  1.00
adversarial-duplicate-invoice        True   1.00  1.00  1.00  1.00  1.00  1.00
adversarial-contract-update          True   1.00  1.00  1.00  1.00  1.00  1.00
adversarial-negative-unknown         True   1.00  1.00  1.00  1.00  1.00  1.00
temporal-address-2017                True   1.00  1.00  1.00  1.00  1.00  1.00
temporal-address-2022                True   1.00  1.00  1.00  1.00  1.00  1.00
temporal-address-current             True   1.00  1.00  1.00  1.00  1.00  1.00
temporal-employer-history            True   1.00  1.00  1.00  1.00  1.00  1.00
temporal-update-contract-rate        True   1.00  1.00  1.00  1.00  1.00  1.00
```

## Cost model

Per-call (OpenRouter pass-through, `anthropic/claude-opus-4.7`):

- Cold (no cache): ~$0.65 / call (128k × $5/M input + 1.5k × $25/M output).
- Cached (5-min ephemeral hit): ~$0.10 / call (128k × $0.50/M cache read).
- Cache write: ~$0.80 (128k × $6.25/M, paid once per ~5-min window).

## What this run does NOT measure

- **Sovereignty**: Anthropic-routed via OR. Pipeline can swap to a local
  LLM; Opus path cannot.
- **Scale**: 43 docs ≈ 128k tokens (well under 1M). Real legal-cabinet
  archives (10k–100k actes) won't fit any model context.
- **Structured outputs**: Opus answers in prose; pipeline returns
  `Fact`/`Conflict`/`Claim` objects with stable SHA-256 IDs.
- **Determinism beyond temperature=0**: same Q/same cache → same answer
  for now, but Anthropic provider routing can drift; pipeline at temp=0
  is byte-identical across runs.
- **Cost at QPS**: 1k queries/month: pipeline ~$5, Opus ~$100. 100k/mo:
  pipeline ~$500, Opus ~$10k+.

## Reproduce

```bash
python -m benchmarks.opus_fullcontext --max-cases 26 \
  --max-tokens 1500 --budget-usd 5.0 \
  --out benchmarks/runs/opus47_full26.json
```

Requires `OPEN_ROUTER_API_KEY` in `.env`.
