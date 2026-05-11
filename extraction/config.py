"""Extraction configuration — defaults + env overrides.

All knobs are env-overridable so the module is not tied to the current
personal-docs corpus. Entity types are deliberately universal; forcing
French-admin-specific types (`impot`, `notaire`, …) would overfit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# Default entity taxonomy — small, universal, domain-agnostic.
# `entity_profile` and `catalog_index` are retrieval-infra types for
# synthetic Phase 5.4 index nodes; kept in core so taxonomy enforcement
# preserves them if the pipeline ever re-processes them.
_DEFAULT_ENTITY_TYPES: tuple[str, ...] = (
    "person",
    "organization",
    "location",
    "date",
    "amount",
    "document",
    "identifier",
    "concept",
    "entity_profile",
    "catalog_index",
)

_DEFAULT_LLM_MODEL = "google/gemini-2.5-flash"
_DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_DEFAULT_EMBED_DIM = 384
_DEFAULT_LANGUAGE = "auto"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# 0.0 keeps extraction + queries reproducible across runs (see commit
# cfa7da8). Override only for sampling experiments — eval metrics lose
# their measurable floor at temperature > 0.
_DEFAULT_TEMPERATURE = 0.0

# Default guidance appended at query time. Generic over any time-varying
# attribute so the graph can say something sensible about addresses,
# employers, phones, vehicles, etc. — anything that may change over time.
_DEFAULT_TEMPORAL_USER_PROMPT = (
    "Many entities and relations in the knowledge graph are prefixed "
    "with `[sourced: YYYY-MM-DD, …]` listing the dates of the documents "
    "they were extracted from. Treat the LATEST sourced date as the "
    "most recent observation of that fact. "
    "When listing facts that may change over time (addresses, employers, "
    "phones, emails, spouses, vehicles, bank accounts, prices, contract "
    "terms), order them chronologically from oldest to newest using "
    "those sourced dates, flag the most recent as current, and attach "
    "the source date when stating each fact. "
    "If multiple facts of the same kind appear with the same latest "
    "date, or if the chronology is ambiguous, say so explicitly rather "
    "than guess. "
    # Phase 8b.7-fix: point-in-time reasoning. Without this, the LLM
    # often returns the LATEST observed value for any time-scoped query
    # (e.g. picks the 2021 Lyon address for a 'in 2017' question).
    "For point-in-time questions (« en 2017 », « at as_of=YYYY-MM-DD », "
    "« à la date du … »), pick the fact whose validity window CONTAINS "
    "the queried date. Use the [sourced: …] tags AND in-document phrases "
    "(« à compter du DATE », « depuis YEAR », « valable du X au Y », "
    "« pendant la période X→Y », « jusqu'au DATE ») to determine each "
    "fact's validity window. NEVER return a fact whose start date is "
    "strictly after the queried date. If the queried date precedes all "
    "available evidence, abstain instead of returning the earliest. "
    # Phase 8b.6 abstention authorization (charter §3.8c, premortem F6).
    # Without this clause, the answerer fluently confabulates when the
    # corpus does not support a confident answer — directly contradicting
    # the §1.2 accountability promise.
    "Answer ONLY the exact question asked. Do not substitute a related "
    "entity, document, or predicate when the question's specific subject "
    "is missing. Examples of forbidden substitutions: (a) the question "
    "asks about person X's medical history but only X's family members "
    "have records — do NOT report family records as X's; (b) the question "
    "scopes a fact to document D (« décrits dans le compromis de vente ») "
    "but D does not contain that fact — do NOT pull the fact from a "
    "different document; (c) the question asks about predicate P (a car "
    "model) inside a real-estate document — do NOT volunteer car data "
    "from elsewhere. In all such cases, abstain. "
    "If the provided context does not contain sufficient evidence to "
    "answer the EXACT question (correct subject AND correct document "
    "scope AND correct predicate), respond explicitly with a sentence "
    "such as « Le corpus ne contient pas suffisamment d'informations "
    "pour répondre à cette question » (or its English equivalent "
    "« insufficient evidence »). Do NOT invent facts, do NOT speculate, "
    "do NOT extrapolate beyond what the context contains. Saying "
    "« I do not have sufficient evidence » is a correct, expected, and "
    "trust-preserving answer when the corpus does not support a "
    "confident response. "
    "However, when the context DOES contain evidence matching the "
    "question's subject, scope, and predicate, you MUST extract and "
    "report it — do not abstain on a question whose answer is present."
)


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def compose_entity_types(base: list[str], packs) -> list[str]:
    """Union base types with each pack's `declared_types` in registration order.

    Case-insensitive dedup: the first occurrence (base, then pack order)
    wins, preserving its original casing. Packs without `declared_types`
    contribute nothing.
    """
    out: list[str] = []
    seen: set[str] = set()
    for t in base:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    for pack in packs:
        declared = getattr(pack, "declared_types", None) or []
        for t in declared:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            # Normalize pack-contributed types to lowercase — downstream
            # enforcement (`extraction.taxonomy`) lowercases for comparison,
            # so any mixed casing in the declared list is moot and confusing.
            out.append(key)
    return out


@dataclass(frozen=True)
class ExtractionConfig:
    llm_model: str = _DEFAULT_LLM_MODEL
    embed_model: str = _DEFAULT_EMBED_MODEL
    embed_dim: int = _DEFAULT_EMBED_DIM
    language: str = _DEFAULT_LANGUAGE
    base_url: str = _DEFAULT_BASE_URL
    entity_types: list[str] = field(default_factory=lambda: list(_DEFAULT_ENTITY_TYPES))
    temporal_user_prompt: str = _DEFAULT_TEMPORAL_USER_PROMPT
    temperature: float = _DEFAULT_TEMPERATURE
    # Phase 8b.4 — sovereign-routable LLM (charter §3.8 r7).
    # OpenRouter accepts `provider.order=[...]` to pin which upstream
    # provider serves a request. Empty tuple = let OpenRouter route freely
    # (current Gemini behavior). Set to ("mistral",) for the v0.5 EU /
    # RGPD-aligned routing.
    provider_order: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ExtractionConfig":
        """Build a config from an env-like mapping. Pass `os.environ` in prod."""
        env = env if env is not None else os.environ
        raw_types = env.get("EXTRACTION_ENTITY_TYPES", "")
        types = _parse_csv_list(raw_types) if raw_types else list(_DEFAULT_ENTITY_TYPES)
        raw_providers = env.get("EXTRACTION_PROVIDER_ORDER", "")
        providers: tuple[str, ...] = tuple(_parse_csv_list(raw_providers)) if raw_providers else ()
        return cls(
            llm_model=env.get("EXTRACTION_LLM_MODEL", _DEFAULT_LLM_MODEL),
            embed_model=env.get("EXTRACTION_EMBED_MODEL", _DEFAULT_EMBED_MODEL),
            embed_dim=int(env.get("EXTRACTION_EMBED_DIM", str(_DEFAULT_EMBED_DIM))),
            language=env.get("EXTRACTION_LANGUAGE", _DEFAULT_LANGUAGE),
            base_url=env.get("EXTRACTION_BASE_URL", _DEFAULT_BASE_URL),
            entity_types=types,
            temporal_user_prompt=env.get(
                "EXTRACTION_TEMPORAL_USER_PROMPT", _DEFAULT_TEMPORAL_USER_PROMPT
            ),
            temperature=float(env.get("EXTRACTION_TEMPERATURE", str(_DEFAULT_TEMPERATURE))),
            provider_order=providers,
        )

    def addon_params(self) -> dict:
        """Params injected into LightRAG's `addon_params` constructor arg."""
        return {
            "entity_types": list(self.entity_types),
            "language": self.language,
        }

    def require_api_key(self) -> str:
        key = os.environ.get("OPEN_ROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                "OPEN_ROUTER_API_KEY is not set. Add it to .env or export it."
            )
        return key
