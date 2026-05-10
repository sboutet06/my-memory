# raw-medical — French clinical cases sample (Phase 8b.5b)

25 French clinical case studies sampled from the
`mlabonne/medical-cases-fr` HuggingFace dataset. Stratified across 15
medical specialties (top by volume). One Markdown file per case. No
real patient data — these are training-exam cases (DESC pharmacie,
ECN-style).

Added 2026-05-10 to validate Phase 8b.5 non-bank Fact extractors
(`treatment_date`, `prescriber`, `diagnosis_date`, `patient_age`) on
real French medical text without depending on print-then-scan.

## Source

- Dataset: [mlabonne/medical-cases-fr](https://huggingface.co/datasets/mlabonne/medical-cases-fr)
- Origin: scraped/curated medical exam cases (DrMistral training collection)
- Format: parquet (8134 rows, 7 cols)
- License: not explicit on dataset card — assumed permissive for
  research/dogfood under fair-use rationale (exam questions in public
  prep material). For V1 pilot, switch to a fully-licensed source
  (CAS corpus via direct contact, or QUAERO).

## Sampling rule

```python
unique = df.drop_duplicates(subset=['Specialite','Serie'])
top15 = unique['Specialite'].value_counts().head(15).index
sample = pd.concat([unique[unique.Specialite==s].sample(2, random_state=42) for s in top15]).head(25)
```

Deterministic (`random_state=42`); reproduces identically.

## Files

25 `.md` files, ~100 KB total. Each:

```
# Cas clinique — <specialty>
**Série**: <n> | **Question**: <n> | **Source**: ...

## Énoncé
<case description, 200–13k chars>

## Réponse / Explication
<answer + reasoning>
```

## Why a sample, not the full 8134?

- v0.5 needs validation that Fact extractors work on real medical text.
- 25 cases stratified across 15 specialties is sufficient to expose
  predicate-shape failures (e.g. extractor fails on neuro vs.
  cardio terminology).
- Full set is for V1+ benchmark / training, not v0.5.

## Alternative sources considered

- **CAS corpus** (Natalia Grabar, ATILF) — 4900 cases CC-BY but
  email-gated. Use for V1.
- **QuaeroFrenchMed** — Named-entity / normalization gold standard.
  Smaller scope, useful for entity validation.
- **DrBERT/NACHOS** — pretraining corpus, not case-shaped.
