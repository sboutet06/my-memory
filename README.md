# my-memory — Ingestion Module (V0)

First brick of a personal knowledge-structuring pipeline. Takes a raw
document, runs it through [Docling](https://github.com/docling-project/docling),
and persists a structured representation on the local filesystem.

Scope is deliberately narrow: **ingestion only**. Entity extraction,
knowledge graph, and API live downstream.

## Requirements

- Python 3.13
- The repo's virtualenv (`./venv/`) with Docling, Pydantic, puremagic, pytest.

```bash
source venv/bin/activate
pip install docling pydantic puremagic pytest  # only if starting fresh
```

## CLI

Ingest a single file:

```bash
python -m ingestion raw/Proposition\ auto.pdf
# [ingested] Proposition auto.pdf → a0e98147-... (store/a0e98147-...)
```

Ingest a whole folder (only supported extensions are processed):

```bash
python -m ingestion raw/
```

Flags:

- `--store PATH` — alternative store root (default: `store/`)
- `-v` / `--verbose` — DEBUG logging

Exit codes: `0` on ingested/duplicate, `1` on failures, `2` if target not found.

## Storage layout

```
store/
└── {document_id}/          # UUID v4
    ├── metadata.json       # See `ingestion/models.py::DocumentMetadata`
    ├── content.json        # Docling native JSON
    ├── content.md          # Docling markdown
    └── original.{ext}      # Copy of the source
```

Writes are atomic: artifacts are staged in `store/.tmp-{document_id}/`
and renamed to the final location only after every file lands. A crash
mid-write leaves no partial document in `store/`.

## Idempotence

Re-ingesting the same bytes returns status `duplicate` pointing at the
existing `document_id`. Dedup key is the SHA-256 of the source file.

## Python API

```python
from pathlib import Path
from ingestion import ingest_document

result = ingest_document(Path("raw/Proposition auto.pdf"))
print(result.status, result.document_id, result.storage_path)
```

See `ingestion/models.py` for `IngestionResult` / `DocumentMetadata`.

## Tests

```bash
python -m pytest -q -m "not integration"  # fast unit tests
python -m pytest -q -m integration        # real Docling on raw/Proposition auto.pdf
python -m pytest -q                       # everything
```

## Out of scope (V0)

Card documents (ID/passport via ocrmac), entity extraction, REST API,
database, encryption, multi-user. Listed in the brief that created this
module; tracked for later iterations.
