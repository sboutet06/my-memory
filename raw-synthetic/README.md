# Synthetic adversarial corpus

Generated for Phase 7 eval (D6 approved). Isolated from real dogfood
corpus (`raw/`, `raw-2/`) to keep personal data clean.

All documents concern **Jean Pierre DUPONT** — a fictional person.
No real personal data.

## Documents

| File | Type | Purpose |
|---|---|---|
| `contradiction-birthdate-dupont-A.txt` | Casier judiciaire (fictif) | Asserts birthdate **1980-01-15** |
| `contradiction-birthdate-dupont-B.txt` | Attestation SS (fictive) | Asserts birthdate **1982-03-22** → time-invariant conflict |
| `contradiction-address-dupont-A.txt` | Bail (fictif) | Address **15 Allée des Pins, Grenoble** (2015–2018) |
| `contradiction-address-dupont-B.txt` | Relevé bancaire (fictif) | Address **8 Impasse du Moulin, Lyon** (2021) → time-varying |
| `duplicate-invoice-A.txt` | Facture (fictive) | Invoice 2023-0142 original |
| `duplicate-invoice-B.txt` | Facture (fictive) | Invoice 2023-0142 duplicata — near-identical content |
| `update-contract-v1.txt` | Contrat (fictif) | Contract CONT-2022-087, rate 950€/day |
| `update-contract-v2.txt` | Avenant (fictif) | Amendment: rate updated to 1100€/day — update pair |

## Ingest command

```bash
source venv/bin/activate
python -m ingestion raw-synthetic/
python -m extraction extract
python -m extraction dedupe --apply
python -m extraction build-indexes
python -m facts detect-conflicts
```

## Eval cases targeting this corpus

See `evaluation/cases.json` — cases tagged `adversarial`.
Pass criterion: `conflict_detection_coverage >= 0.90` on adversarial cases.
