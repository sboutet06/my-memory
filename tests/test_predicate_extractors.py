"""Phase 8b.5 — address / birthdate / employer Fact extractors.

LLM is mocked so the tests are deterministic and offline. The
real-traffic pass criterion lives in the Phase 8b.7 phase-gate
script.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Callable

import pytest

from facts.models import ConfidenceLevel
from packs.personal_documents.predicate_extractors import (
    extract_address_facts,
    extract_birthdate_facts,
    extract_diagnosis_facts,
    extract_employer_facts,
    extract_prescribed_medication_facts,
    parse_llm_json,
    should_run_address_for,
    should_run_birthdate_for,
    should_run_diagnosis_for,
    should_run_employer_for,
    should_run_medication_for,
    validate_address,
    validate_birthdate,
    validate_employer_name,
)


def _run(coro):
    return asyncio.run(coro)


def _stub_llm(response: str) -> Callable:
    async def _f(prompt, system_prompt=None, history_messages=None, **kw):
        return response
    return _f


# ============================================================================
# Trigger sets
# ============================================================================


def test_address_trigger_matches_proposition_assurance() -> None:
    assert should_run_address_for({"doc_context": ["proposition_assurance"]})


def test_address_trigger_misses_unknown_tag() -> None:
    assert not should_run_address_for({"doc_context": ["random_tag"]})


def test_birthdate_trigger_matches_identity() -> None:
    assert should_run_birthdate_for({"doc_context": ["identity"]})


def test_employer_trigger_matches_bulletin_paie() -> None:
    assert should_run_employer_for({"doc_context": ["bulletin_paie"]})


def test_no_doc_context_means_no_trigger() -> None:
    assert not should_run_address_for({})
    assert not should_run_birthdate_for({"doc_context": []})


# ============================================================================
# Validators
# ============================================================================


def test_validate_address_french_pattern_passes() -> None:
    assert validate_address("10 Rue de la Paix, 75002 Paris")


def test_validate_address_with_multi_line_collapses() -> None:
    assert validate_address("10 Rue de la Paix\n75002 Paris")


def test_validate_address_with_accents_passes() -> None:
    assert validate_address("12 Boulevard Saint-Germain, 75006 Paris")


def test_validate_address_rejects_no_number() -> None:
    assert not validate_address("Rue de la Paix, Paris")


def test_validate_address_rejects_empty() -> None:
    assert not validate_address("")


def test_validate_birthdate_valid_iso() -> None:
    assert validate_birthdate("1985-06-15")


def test_validate_birthdate_rejects_invalid_format() -> None:
    assert not validate_birthdate("15/06/1985")
    assert not validate_birthdate("1985-13-01")  # invalid month
    assert not validate_birthdate("")


def test_validate_birthdate_rejects_future_year() -> None:
    assert not validate_birthdate("2099-01-01")


def test_validate_birthdate_rejects_pre_1900() -> None:
    assert not validate_birthdate("1850-01-01")


def test_validate_employer_name_strips() -> None:
    assert validate_employer_name("Acme Corp")
    assert not validate_employer_name("")
    assert not validate_employer_name("   ")


# ============================================================================
# LLM JSON parsing
# ============================================================================


def test_parse_llm_json_plain_array() -> None:
    raw = '[{"a": 1}, {"b": 2}]'
    assert parse_llm_json(raw) == [{"a": 1}, {"b": 2}]


def test_parse_llm_json_strips_code_fences() -> None:
    raw = '```json\n[{"a": 1}]\n```'
    assert parse_llm_json(raw) == [{"a": 1}]


def test_parse_llm_json_empty_array() -> None:
    assert parse_llm_json("[]") == []


def test_parse_llm_json_malformed_returns_empty() -> None:
    assert parse_llm_json("not json at all") == []


def test_parse_llm_json_non_array_returns_empty() -> None:
    assert parse_llm_json('{"obj": "not list"}') == []


def test_parse_llm_json_filters_non_dict_items() -> None:
    raw = '["string", 42, {"a": 1}, null]'
    assert parse_llm_json(raw) == [{"a": 1}]


# ============================================================================
# Address extractor
# ============================================================================


def test_address_extractor_emits_fact_on_valid_response() -> None:
    response = (
        '[{"entity_name":"Jean Dupont","address_text":"10 Rue de la Paix, '
        '75002 Paris","components":{"street":"10 Rue de la Paix",'
        '"postal_code":"75002","city":"Paris"},"role":"current"}]'
    )
    result = _run(extract_address_facts(
        content_md="some text",
        source_doc_id="doc-1",
        llm_func=_stub_llm(response),
        document_date=date(2024, 1, 1),
    ))
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert fact.subject_id == "entity:jean-dupont"
    assert fact.predicate == "address"
    assert fact.canonical_value == "10 Rue de la Paix, 75002 Paris"
    assert fact.confidence == ConfidenceLevel.LLM_HIGH
    assert fact.valid_from == date(2024, 1, 1)


def test_address_extractor_emits_llm_low_when_regex_fails() -> None:
    response = (
        '[{"entity_name":"X","address_text":"no number here, 75002 Paris",'
        '"components":{},"role":"unknown"}]'
    )
    result = _run(extract_address_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 1
    assert result.facts[0].confidence == ConfidenceLevel.LLM_LOW


def test_address_extractor_drops_empty_entity_name() -> None:
    response = '[{"entity_name":"","address_text":"10 Rue X, 75002 Paris"}]'
    result = _run(extract_address_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


def test_address_extractor_returns_empty_on_empty_array() -> None:
    result = _run(extract_address_facts(
        content_md="no address here",
        source_doc_id="d",
        llm_func=_stub_llm("[]"),
    ))
    assert result.facts == [] and result.claims == []


def test_address_extractor_returns_empty_on_malformed_json() -> None:
    result = _run(extract_address_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm("garbage"),
    ))
    assert result.facts == []


def test_address_extractor_multiple_items() -> None:
    response = (
        '[{"entity_name":"Alice","address_text":"1 Rue A, 75001 Paris",'
        '"components":{"street":"1 Rue A","postal_code":"75001","city":"Paris"}},'
        '{"entity_name":"Bob","address_text":"2 Rue B, 69000 Lyon",'
        '"components":{"street":"2 Rue B","postal_code":"69000","city":"Lyon"}}]'
    )
    result = _run(extract_address_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 2
    subjects = {f.subject_id for f in result.facts}
    assert subjects == {"entity:alice", "entity:bob"}


def test_address_extractor_idempotent_fact_ids() -> None:
    """Same LLM response twice → same Fact ids (content-addressable)."""
    response = (
        '[{"entity_name":"Z","address_text":"7 Avenue X, 75009 Paris",'
        '"components":{"street":"7 Avenue X","postal_code":"75009","city":"Paris"}}]'
    )
    r1 = _run(extract_address_facts(content_md="x", source_doc_id="d", llm_func=_stub_llm(response)))
    r2 = _run(extract_address_facts(content_md="x", source_doc_id="d", llm_func=_stub_llm(response)))
    assert r1.facts[0].id == r2.facts[0].id
    assert r1.claims[0].id == r2.claims[0].id


# ============================================================================
# Birthdate extractor
# ============================================================================


def test_birthdate_extractor_valid_iso() -> None:
    response = '[{"entity_name":"Jean Dupont","birthdate_iso":"1985-06-15"}]'
    result = _run(extract_birthdate_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 1
    f = result.facts[0]
    assert f.predicate == "birthdate"
    assert f.canonical_value == "1985-06-15"
    assert f.confidence == ConfidenceLevel.LLM_HIGH


def test_birthdate_extractor_llm_low_on_bad_format() -> None:
    response = '[{"entity_name":"X","birthdate_iso":"15/06/1985"}]'
    result = _run(extract_birthdate_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts[0].confidence == ConfidenceLevel.LLM_LOW


def test_birthdate_extractor_drops_missing_iso() -> None:
    response = '[{"entity_name":"X","birthdate_iso":""}]'
    result = _run(extract_birthdate_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


def test_birthdate_fact_valid_from_stays_none() -> None:
    """Birthdate is invariant; no temporal interval is set."""
    response = '[{"entity_name":"Y","birthdate_iso":"1970-01-01"}]'
    result = _run(extract_birthdate_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts[0].valid_from is None
    assert result.facts[0].valid_to is None


# ============================================================================
# Employer extractor
# ============================================================================


def test_employer_extractor_valid() -> None:
    response = (
        '[{"employee_name":"Alice Martin","employer_name":"Acme SARL",'
        '"period_start_iso":"2020-01-01","period_end_iso":null,"role":"Engineer"}]'
    )
    result = _run(extract_employer_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 1
    f = result.facts[0]
    assert f.predicate == "employer"
    assert f.canonical_value == "Acme SARL"
    assert f.subject_id == "entity:alice-martin"
    assert f.confidence == ConfidenceLevel.LLM_HIGH
    assert f.valid_from == date(2020, 1, 1)
    assert f.valid_to is None


def test_employer_extractor_falls_back_to_doc_date() -> None:
    response = (
        '[{"employee_name":"A","employer_name":"Co","period_start_iso":null,'
        '"period_end_iso":null}]'
    )
    result = _run(extract_employer_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
        document_date=date(2023, 6, 1),
    ))
    assert result.facts[0].valid_from == date(2023, 6, 1)


def test_employer_extractor_llm_low_on_empty_name() -> None:
    response = (
        '[{"employee_name":"A","employer_name":"   ","period_start_iso":null}]'
    )
    result = _run(extract_employer_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


def test_employer_extractor_drops_missing_employee() -> None:
    response = '[{"employee_name":"","employer_name":"Co"}]'
    result = _run(extract_employer_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


# ============================================================================
# Medical scaffold (8b.5b)
# ============================================================================


def test_diagnosis_trigger_matches_healthcare() -> None:
    assert should_run_diagnosis_for({"doc_context": ["healthcare"]})


def test_medication_trigger_matches_healthcare() -> None:
    assert should_run_medication_for({"doc_context": ["healthcare"]})


def test_diagnosis_extractor_emits_fact() -> None:
    response = (
        '[{"patient_name":"Kévin","diagnosis":"Traumatisme médullaire incomplet",'
        '"certainty":"confirmed"}]'
    )
    result = _run(extract_diagnosis_facts(
        content_md="x", source_doc_id="doc-1", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 1
    f = result.facts[0]
    assert f.predicate == "diagnosis"
    # Always llm_low until V1 adds ontology validation.
    assert f.confidence == ConfidenceLevel.LLM_LOW
    # Subject scoped by source_doc_id so the same anonymous "patient"
    # in different cases is not collapsed.
    assert "doc-1" in f.subject_id


def test_diagnosis_extractor_multiple() -> None:
    response = (
        '[{"patient_name":"A","diagnosis":"d1","certainty":"confirmed"},'
        '{"patient_name":"A","diagnosis":"d2","certainty":"differential"}]'
    )
    result = _run(extract_diagnosis_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 2


def test_diagnosis_extractor_drops_empty() -> None:
    response = '[{"patient_name":"","diagnosis":"d"}]'
    result = _run(extract_diagnosis_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


def test_medication_extractor_emits_fact() -> None:
    response = (
        '[{"patient_name":"Alice","medication":"paracétamol",'
        '"dose":"1 g","indication":"douleur"}]'
    )
    result = _run(extract_prescribed_medication_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert len(result.facts) == 1
    f = result.facts[0]
    assert f.predicate == "prescribed_medication"
    assert f.canonical_value == "paracétamol"
    assert f.confidence == ConfidenceLevel.LLM_LOW


def test_medication_extractor_drops_empty_medication() -> None:
    response = '[{"patient_name":"A","medication":""}]'
    result = _run(extract_prescribed_medication_facts(
        content_md="x", source_doc_id="d", llm_func=_stub_llm(response),
    ))
    assert result.facts == []


def test_medical_subject_scoped_by_doc() -> None:
    """Same anonymous "patient" in different docs must NOT collapse."""
    response = '[{"patient_name":"patient","diagnosis":"d"}]'
    r1 = _run(extract_diagnosis_facts(
        content_md="x", source_doc_id="doc-A", llm_func=_stub_llm(response),
    ))
    r2 = _run(extract_diagnosis_facts(
        content_md="x", source_doc_id="doc-B", llm_func=_stub_llm(response),
    ))
    assert r1.facts[0].subject_id != r2.facts[0].subject_id
