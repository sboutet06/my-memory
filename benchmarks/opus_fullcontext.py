"""Full-context baseline: stuff every doc into one cached system prompt and ask Opus.

Compares directly against the LightRAG pipeline on the same EvalCase suite +
scorer. The whole point is to measure whether the pipeline's structural
machinery (provenance, conflicts, bitemporal) earns its complexity vs a
frontier LLM with the corpus in-context.

Routed through OpenRouter so the user's existing OPEN_ROUTER_API_KEY works.
Uses Anthropic-style top-level `cache_control` so the corpus is cached
across cases.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from dotenv import load_dotenv

from corrections.io import load_source_correction
from corrections.overlay import resolve_content
from evaluation.runner import score_case
from evaluation.schema import EvalCase, EvalCaseResult
from extraction.provenance import extract_document_ids

logger = logging.getLogger(__name__)


# OpenRouter pass-through pricing for anthropic/claude-opus-4.7 (USD per token).
# Source: https://openrouter.ai/api/v1/models on 2026-05-01.
OPUS_47_PRICING = {
    "prompt": 5e-6,           # $5  / M
    "cache_write": 6.25e-6,   # $6.25 / M
    "cache_read": 0.5e-6,     # $0.50 / M
    "completion": 25e-6,      # $25 / M
}


@dataclass(frozen=True)
class CallUsage:
    prompt_tokens: int
    completion_tokens: int
    cache_creation_input_tokens: int  # Anthropic cache write
    cache_read_input_tokens: int      # Anthropic cache hit

    @property
    def cost_usd(self) -> float:
        # Plain prompt tokens count cache_write tokens too on some OR routes;
        # subtract them so we don't double-count.
        plain = max(0, self.prompt_tokens
                    - self.cache_creation_input_tokens
                    - self.cache_read_input_tokens)
        return (
            plain * OPUS_47_PRICING["prompt"]
            + self.cache_creation_input_tokens * OPUS_47_PRICING["cache_write"]
            + self.cache_read_input_tokens * OPUS_47_PRICING["cache_read"]
            + self.completion_tokens * OPUS_47_PRICING["completion"]
        )


@dataclass
class CaseRun:
    result: EvalCaseResult
    usage: CallUsage
    latency_s: float


# ---------- Corpus packing ----------

_DOC_HEADER = "\n\n=== /store/{doc_id}/content.md (filename: {filename}) ===\n\n"


def load_corpus(store_root: Path, corrections_root: Path) -> tuple[str, dict[str, str]]:
    """Load every doc body (with corrections overlay) into one big string + id→filename map."""
    parts: list[str] = []
    id_to_filename: dict[str, str] = {}
    if not store_root.exists():
        raise SystemExit(f"No ingested docs at {store_root}")
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        md_path = entry / "content.md"
        if not (meta_path.is_file() and md_path.is_file()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        doc_id = meta.get("document_id")
        filename = meta.get("original_filename") or doc_id
        if not doc_id:
            continue
        body = md_path.read_text(encoding="utf-8")
        corr = load_source_correction(corrections_root, doc_id)
        body = resolve_content(body, corr, corrections_root)
        id_to_filename[doc_id] = filename
        parts.append(_DOC_HEADER.format(doc_id=doc_id, filename=filename) + body)
    if not id_to_filename:
        raise SystemExit(f"No ingested docs at {store_root}")
    return "".join(parts), id_to_filename


_SYSTEM_INSTRUCTIONS = """Tu es un assistant qui répond aux questions de l'utilisateur \
sur ses documents personnels (factures, contrats, identité, fiscal, médical, bancaire).

RÈGLES IMPÉRATIVES (correspondent au format attendu par l'évaluation automatique) :

1. Réponds en français.
2. Cite chaque source au format exact `/store/<uuid>/content.md`. Les en-têtes de \
chaque document ci-dessous montrent l'identifiant à utiliser. Place les citations \
soit en ligne (ex. "...d'après /store/abc123.../content.md") soit dans une section \
finale `### References` listant `- [n] /store/<uuid>/content.md`.
3. Ne jamais "moyenner" silencieusement deux faits incompatibles. Si deux \
documents contiennent des valeurs contradictoires (deux dates de naissance, \
deux adresses sans temporalité claire, deux tarifs sur le même contrat), liste \
EXPLICITEMENT chaque valeur avec sa source. Ne pas trancher d'autorité.
4. Pour toute information susceptible de varier dans le temps (adresse, \
employeur, tarif, état civil, véhicule possédé), ordonne chronologiquement \
en t'appuyant sur les dates présentes dans les documents et indique la valeur \
la plus récente.
5. Si la question porte sur un état "à la date X" (`as_of`), choisis la valeur \
valide à cette date d'après le bornage temporel des documents.
6. Si une entité n'est mentionnée dans aucun document, dis-le explicitement \
("aucune mention dans la base"). Ne pas inventer.

DOCUMENTS DE L'UTILISATEUR :
"""


def build_system_prompt(corpus: str) -> str:
    return _SYSTEM_INSTRUCTIONS + corpus


# ---------- OpenRouter call ----------

OR_BASE = "https://openrouter.ai/api/v1"
OR_MODEL = "anthropic/claude-opus-4.7"


async def _post_chat(
    client: httpx.AsyncClient,
    api_key: str,
    system_prompt: str,
    user_question: str,
    model: str = OR_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 1500,
) -> tuple[str, CallUsage]:
    """One chat completion with top-level cache_control on the system prompt."""
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Anthropic-style: content is an array of typed blocks; cache_control
        # on the last system block marks everything up to and including it as
        # cacheable. Identical system across all cases → 1 write + N-1 reads.
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
            },
            {"role": "user", "content": user_question},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/sboutet/my-memory",
        "X-Title": "my-memory benchmark opus-fullcontext",
        "Content-Type": "application/json",
    }
    resp = await client.post(
        f"{OR_BASE}/chat/completions",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(180.0, connect=10.0),
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data["choices"][0]["message"]["content"] or ""
    u = data.get("usage") or {}
    cache_details = (u.get("prompt_tokens_details") or {})
    # OpenRouter exposes Anthropic cache metrics under prompt_tokens_details:
    #   cached_tokens     -> cache hit (read at 0.1x)
    #   cache_write_tokens -> new cache entry (write at 1.25x)
    cache_read = int(
        cache_details.get("cached_tokens")
        or u.get("cache_read_input_tokens", 0)
        or 0
    )
    cache_write = int(
        cache_details.get("cache_write_tokens")
        or u.get("cache_creation_input_tokens", 0)
        or 0
    )
    usage = CallUsage(
        prompt_tokens=int(u.get("prompt_tokens", 0)),
        completion_tokens=int(u.get("completion_tokens", 0)),
        cache_creation_input_tokens=int(cache_write),
        cache_read_input_tokens=int(cache_read),
    )
    return answer, usage


# ---------- Orchestration ----------

async def run_smoke(
    cases: Iterable[EvalCase],
    store_root: Path,
    corrections_root: Path,
    api_key: str,
    budget_usd: float = 8.0,
    max_cases: int | None = None,
    case_ids: list[str] | None = None,
    max_tokens: int = 1500,
    model: str = OR_MODEL,
) -> tuple[list[CaseRun], dict]:
    """Run the eval cases against full-context Opus. Aborts when budget hit."""
    cases_list = list(cases)
    if case_ids:
        wanted = set(case_ids)
        cases_list = [c for c in cases_list if c.id in wanted]
        missing = wanted - {c.id for c in cases_list}
        if missing:
            raise SystemExit(f"Unknown case ids: {sorted(missing)}")
    if max_cases is not None:
        cases_list = cases_list[:max_cases]

    corpus, id_to_filename = load_corpus(store_root, corrections_root)
    system_prompt = build_system_prompt(corpus)
    logger.info(
        "corpus packed: docs=%d system_prompt_chars=%d",
        len(id_to_filename),
        len(system_prompt),
    )

    runs: list[CaseRun] = []
    spent_usd = 0.0
    async with httpx.AsyncClient() as client:
        for case in cases_list:
            if spent_usd >= budget_usd:
                logger.warning(
                    "BUDGET_HIT: stopping at $%.4f after %d cases", spent_usd, len(runs)
                )
                break
            t0 = time.monotonic()
            answer, usage = await _post_chat(
                client, api_key, system_prompt, case.question,
                model=model, max_tokens=max_tokens,
            )
            latency = time.monotonic() - t0
            cited_ids = extract_document_ids(answer)
            cited_filenames = [id_to_filename.get(i, i) for i in cited_ids]
            scored = score_case(case, answer, cited_filenames)
            spent_usd += usage.cost_usd
            runs.append(CaseRun(result=scored, usage=usage, latency_s=latency))
            logger.info(
                "case=%s pass=%s doc=%.2f ent=%.2f fact=%.2f "
                "tokens(prompt=%d cache_w=%d cache_r=%d out=%d) "
                "cost=$%.4f cum=$%.4f t=%.1fs",
                case.id,
                scored.passed,
                scored.doc_coverage,
                scored.entity_coverage,
                scored.fact_coverage,
                usage.prompt_tokens,
                usage.cache_creation_input_tokens,
                usage.cache_read_input_tokens,
                usage.completion_tokens,
                usage.cost_usd,
                spent_usd,
                latency,
            )

    summary = _summarize(runs, spent_usd)
    return runs, summary


def _summarize(runs: list[CaseRun], spent_usd: float) -> dict:
    if not runs:
        return {"cases": 0, "spent_usd": spent_usd}
    n = len(runs)
    return {
        "cases": n,
        "spent_usd": round(spent_usd, 4),
        "passed": sum(1 for r in runs if r.result.passed),
        "mean_doc_coverage": round(sum(r.result.doc_coverage for r in runs) / n, 4),
        "mean_entity_coverage": round(sum(r.result.entity_coverage for r in runs) / n, 4),
        "mean_fact_coverage": round(sum(r.result.fact_coverage for r in runs) / n, 4),
        "mean_fact_provenance_coverage": round(
            sum(r.result.fact_provenance_coverage for r in runs) / n, 4,
        ),
        "mean_conflict_detection_coverage": round(
            sum(r.result.conflict_detection_coverage for r in runs) / n, 4,
        ),
        "mean_temporal_accuracy": round(
            sum(r.result.temporal_accuracy for r in runs) / n, 4,
        ),
        "total_forbidden_violations": sum(r.result.forbidden_violations for r in runs),
        "total_prompt_tokens": sum(r.usage.prompt_tokens for r in runs),
        "total_cache_write_tokens": sum(r.usage.cache_creation_input_tokens for r in runs),
        "total_cache_read_tokens": sum(r.usage.cache_read_input_tokens for r in runs),
        "total_completion_tokens": sum(r.usage.completion_tokens for r in runs),
        "mean_latency_s": round(sum(r.latency_s for r in runs) / n, 2),
    }


# ---------- CLI entry ----------

def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Opus-4.7 full-context baseline")
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument("--corrections", type=Path, default=Path("corrections"))
    parser.add_argument("--cases", type=Path, default=Path("evaluation/cases.json"))
    parser.add_argument("--max-cases", type=int, default=3, help="case-limit (smoke)")
    parser.add_argument(
        "--case-ids", type=str, default="",
        help="Comma-separated case IDs to run (overrides --max-cases ordering).",
    )
    parser.add_argument("--max-tokens", type=int, default=1500, help="LLM output cap")
    parser.add_argument("--budget-usd", type=float, default=8.0, help="abort cap")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/runs/opus47_smoke.json"))
    parser.add_argument("--model", type=str, default=OR_MODEL)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    load_dotenv(Path(".env"))
    api_key = os.environ.get("OPEN_ROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPEN_ROUTER_API_KEY missing — add to .env")

    from evaluation.schema import load_cases
    cases = load_cases(args.cases)
    case_ids = [s.strip() for s in args.case_ids.split(",") if s.strip()] or None
    runs, summary = asyncio.run(run_smoke(
        cases=cases,
        store_root=args.store,
        corrections_root=args.corrections,
        api_key=api_key,
        budget_usd=args.budget_usd,
        max_cases=args.max_cases,
        case_ids=case_ids,
        max_tokens=args.max_tokens,
        model=args.model,
    ))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": args.model,
        "summary": summary,
        "runs": [
            {
                "case_id": r.result.case_id,
                "question": r.result.question,
                "answer": r.result.answer,
                "document_ids": r.result.document_ids,
                "doc_coverage": r.result.doc_coverage,
                "entity_coverage": r.result.entity_coverage,
                "fact_coverage": r.result.fact_coverage,
                "fact_provenance_coverage": r.result.fact_provenance_coverage,
                "conflict_detection_coverage": r.result.conflict_detection_coverage,
                "temporal_accuracy": r.result.temporal_accuracy,
                "forbidden_violations": r.result.forbidden_violations,
                "passed": r.result.passed,
                "usage": {
                    "prompt_tokens": r.usage.prompt_tokens,
                    "completion_tokens": r.usage.completion_tokens,
                    "cache_creation_input_tokens": r.usage.cache_creation_input_tokens,
                    "cache_read_input_tokens": r.usage.cache_read_input_tokens,
                    "cost_usd": round(r.usage.cost_usd, 6),
                },
                "latency_s": round(r.latency_s, 2),
            }
            for r in runs
        ],
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nFull report: {args.out}")


if __name__ == "__main__":
    _main()
