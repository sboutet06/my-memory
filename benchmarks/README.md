# Benchmark Scaffolding

Multi-model sweep against the eval case suite. Only the **query answerer** stage is supported today — the extraction graph stays fixed; only the LLM that generates the final answer is swapped.

## How to run

```bash
# DO NOT run this without reviewing the cost estimate below.
# Current eval suite = 16 cases × N models × ~8k tokens/case ≈ 128k tokens/model.

python -m benchmarks --stage query_answerer --models gemini,haiku --case-limit 3
```

No `--run` subcommand yet — use the Python API directly:

```python
import asyncio
from pathlib import Path
from benchmarks.runner import run
from evaluation.schema import load_cases

cases = load_cases(Path("evaluation/cases.json"))
results = asyncio.run(run(
    stage="query_answerer",
    model_list=["google/gemini-2.5-flash", "anthropic/claude-haiku-4-5"],
    cases=cases,
    store_root=Path("store"),
    working_dir=Path(".lightrag"),
    case_limit=3,  # smoke before full sweep
))
for r in results:
    print(r.model_id, r.summary)
```

## Proposed model set

All accessed via OpenRouter. Approval required before running any paid sweep.

### Tier 1 — current baseline

| Model | OpenRouter ID | Est. cost / 16 cases |
|-------|---------------|----------------------|
| Gemini 2.5 Flash | `google/gemini-2.5-flash` | ~$0.10 |

### Tier 2 — candidate swaps (pending approval)

| Model | OpenRouter ID | Rationale |
|-------|---------------|-----------|
| Claude Haiku 4.5 | `anthropic/claude-haiku-4-5` | Fastest Anthropic, strong French |
| Gemini 2.5 Flash-8B | `google/gemini-2.5-flash-8b` | Cheaper variant, same family |
| Qwen-2.5 72B | `qwen/qwen-2.5-72b-instruct` | Strong multilingual open-weight |
| DeepSeek V3 | `deepseek/deepseek-chat` | High reasoning, budget-friendly |

### Tier 3 — future / local (not yet available on OpenRouter)

| Model | Notes |
|-------|-------|
| Kimi K2 | MoE, strong long-context; await stable OpenRouter listing |
| Gemma 3n (local) | On-device, zero API cost; requires Ollama wrapper |
| Llama-4 Scout (local) | 17B MoE; available via Ollama once weights released |

## Stage map

| Stage | What it controls | Status |
|-------|-----------------|--------|
| `query_answerer` | LLM that generates the final RAG answer | ✅ Implemented |
| `extractor` | LLM that extracts entities/relations at ingest | Planned Phase 7 |
| `embedder` | Embedding model for vector retrieval | Planned Phase 7 |

## Cost guard

Before any multi-model sweep: estimate tokens × models × price/token. Post estimate here and get explicit user approval. Never run > 3 models without prior approval.
