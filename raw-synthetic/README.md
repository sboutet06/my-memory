# Synthetic adversarial corpus

Generated for Phase 7+8 eval (D6 approved). Isolated from real dogfood
corpus (`raw/`, `raw-2/`) to keep personal data clean.

All documents concern **Jean Pierre DUPONT** — a fictional person.
No real personal data.

## Documents

### Phase 7 — conflicts and duplicates

| File | Type | Purpose |
|---|---|---|
| `contradiction-birthdate-dupont-A.txt` | Casier judiciaire (fictif) | Asserts birthdate **1980-01-15** |
| `contradiction-birthdate-dupont-B.txt` | Attestation SS (fictive) | Asserts birthdate **1982-03-22** → time-invariant conflict |
| `duplicate-invoice-A.txt` | Facture (fictive) | Invoice 2023-0142 original |
| `duplicate-invoice-B.txt` | Facture (fictive) | Invoice 2023-0142 duplicata — near-identical content |
| `update-contract-v1.txt` | Contrat (fictif) | Contract CONT-2022-087, rate 950€/day |
| `update-contract-v2.txt` | Avenant (fictif) | Amendment: rate updated to 1100€/day — update pair |

### Phase 8 — temporal supersession (3-step address chain + 2-step employer chain)

| File | Date asserted | Value |
|---|---|---|
| `contradiction-address-dupont-A.txt` | bail 2015 | **15 Allée des Pins, Grenoble** (valid 2015–2018) |
| `contradiction-address-dupont-B.txt` | relevé bancaire 2021 | **8 Impasse du Moulin, Lyon** (valid 2021→2023) |
| `contradiction-address-dupont-C.txt` | assurance 2024 | **102 Avenue de la République, Marseille** (valid 2024→) |
| `temporal-employer-dupont-A.txt` | CDI 2018 | **SARL TechSolutions Lyon** (valid 2018-04-01 → 2022-10-31) |
| `temporal-employer-dupont-B.txt` | CDI 2022 | **SAS Cabinet Veridia Conseil** (valid 2022-11-01 →) |

The address chain has 3 steps to test multi-step supersession.
The employer chain has explicit dates including a clean handover.

## Ingest command

```bash
source venv/bin/activate
python -m ingestion raw-synthetic/
python -m extraction extract
python -m extraction dedupe --apply
python -m extraction build-indexes
python -m extraction extract-structured       # populates facts/store/
python -m facts detect-conflicts
python -m facts supersede                     # closes valid_to on time-varying facts
```

## Eval cases targeting this corpus

See `evaluation/cases.json` — cases tagged `adversarial` (Phase 7) and `temporal` (Phase 8).

Pass criteria:
- `conflict_detection_coverage >= 0.90` on adversarial cases.
- `temporal_accuracy >= 0.90` on temporal/update cases.
