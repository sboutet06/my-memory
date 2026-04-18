"""CLI: `python -m ingestion <file-or-folder> [--store STORE] [-v]`.

Also: `python -m ingestion reocr <doc_id> [--backend ocrmac]` re-runs
an alternate OCR backend for a previously-ingested document, writing
the corrected content into the source correction overlay.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from corrections.io import (
    correction_path,
    load_source_correction,
    save_source_correction,
)
from corrections.schemas import SourceCorrection
from ingestion.ingest import (
    DEFAULT_STORE_ROOT,
    ingest_document,
)
from ingestion.models import IngestionResult, IngestionStatus
from ingestion.ocr_backends import KNOWN_BACKENDS, run_ocrmac_on_pdf

logger = logging.getLogger("ingestion")


def _format(result: IngestionResult, source: Path) -> str:
    status = result.status.value
    head = f"[{status}] {source.name}"
    match result.status:
        case IngestionStatus.INGESTED:
            quality = result.metadata.extraction_quality.value if result.metadata else "?"
            return f"{head} → {result.document_id} (quality={quality}, {result.storage_path})"
        case IngestionStatus.DUPLICATE:
            return f"{head} → existing {result.document_id}"
        case IngestionStatus.UNSUPPORTED | IngestionStatus.FAILED:
            return f"{head}: {result.message}"
    return head


def _ingest_batch(folder: Path, store_root: Path, *, classify: bool = True) -> int:
    files = sorted(p for p in folder.iterdir() if p.is_file())
    if not files:
        print(f"No files in {folder}")
        return 0

    failures = 0
    for fp in files:
        try:
            result = ingest_document(fp, store_root=store_root, classify=classify)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unhandled error on %s", fp)
            print(f"[error] {fp.name}: {exc}")
            failures += 1
            continue
        print(_format(result, fp))
        if result.status == IngestionStatus.FAILED:
            failures += 1
    return failures


def _run_reocr(doc_id: str, backend: str | None, store_root: Path,
               corrections_root: Path) -> int:
    """Re-OCR a previously-ingested document with an alternate backend.

    Resolution order for `backend`:
      1. explicit --backend argument
      2. `overrides.ocr_backend` on the existing source correction
    """
    doc_dir = store_root / doc_id
    meta_path = doc_dir / "metadata.json"
    if not meta_path.is_file():
        print(f"No store entry for {doc_id}", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    original_path = Path(meta.get("original_path", ""))
    if not original_path.is_file():
        print(f"Original file missing: {original_path}", file=sys.stderr)
        return 2

    correction = load_source_correction(corrections_root, doc_id)
    chosen_backend = (
        backend
        or (correction.overrides.get("ocr_backend") if correction else None)
    )
    if not chosen_backend:
        print(
            f"No backend specified and none set on the correction for {doc_id}. "
            f"Pass --backend or edit overrides.ocr_backend.",
            file=sys.stderr,
        )
        return 2
    if chosen_backend not in KNOWN_BACKENDS:
        print(
            f"Unknown backend {chosen_backend!r}. Known: {sorted(KNOWN_BACKENDS)}",
            file=sys.stderr,
        )
        return 2

    if chosen_backend == "ocrmac":
        text = run_ocrmac_on_pdf(original_path)
    else:  # pragma: no cover
        raise RuntimeError(f"unhandled backend {chosen_backend}")

    # Write the corrected content alongside the correction YAML.
    source_dir = corrections_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    overlay_rel = f"source/{doc_id}.md"
    (corrections_root / overlay_rel).write_text(text, encoding="utf-8")

    if correction is None:
        correction = SourceCorrection(
            document_id=doc_id,
            original_filename=meta.get("original_filename", ""),
        )
    correction.overrides["ocr_backend"] = chosen_backend
    correction.overrides["content_md_override_path"] = overlay_rel
    save_source_correction(corrections_root, correction)

    print(
        f"Re-OCR'd {doc_id} with {chosen_backend}: "
        f"{len(text)} chars → {overlay_rel}"
    )
    return 0


def _run_classify_existing(store_root: Path, only_doc_id: str | None) -> int:
    """Run the LLM classifier over already-ingested docs; update metadata.json."""
    from extraction.config import ExtractionConfig
    from ingestion.classifier import classify_document
    import asyncio

    if not store_root.exists():
        print(f"Store not found: {store_root}", file=sys.stderr)
        return 2

    try:
        config = ExtractionConfig.from_env()
        config.require_api_key()
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    async def run_all():
        count = 0
        for entry in sorted(store_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".tmp-"):
                continue
            if only_doc_id and entry.name != only_doc_id:
                continue
            meta_path = entry / "metadata.json"
            md_path = entry / "content.md"
            if not (meta_path.is_file() and md_path.is_file()):
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = md_path.read_text(encoding="utf-8")
            tags, rationale = await classify_document(
                config,
                filename=meta.get("original_filename", ""),
                content_md=content,
            )
            meta["doc_context"] = tags
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str))
            print(f"[{entry.name[:8]}] {tags}  ({rationale[:60]})")
            count += 1
        return count

    n = asyncio.run(run_all())
    print(f"\nClassified {n} documents.")
    return 0


def _main_classify(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion classify")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--doc-id", type=str, default=None,
                        help="Only (re-)classify this document_id")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return _run_classify_existing(args.store, args.doc_id)


def _main_reocr(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion reocr")
    parser.add_argument("doc_id")
    parser.add_argument(
        "--backend",
        help=f"OCR backend ({'|'.join(sorted(KNOWN_BACKENDS))}); "
             "defaults to overrides.ocr_backend from the source correction",
    )
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--corrections-root", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    corr_root = args.corrections_root if args.corrections_root is not None else args.store.parent / "corrections"
    return _run_reocr(args.doc_id, args.backend, args.store, corr_root)


def main(argv: list[str] | None = None) -> int:
    effective = list(argv) if argv is not None else sys.argv[1:]
    # `reocr` is a sibling subcommand — kept out of the main positional parser
    # so paths with leading dashes or absolute paths don't confuse argparse.
    if effective and effective[0] == "reocr":
        return _main_reocr(effective[1:])
    if effective and effective[0] == "classify":
        return _main_classify(effective[1:])

    parser = argparse.ArgumentParser(prog="python -m ingestion")
    parser.add_argument("target", type=Path, help="File or folder to ingest")
    parser.add_argument(
        "--store", type=Path, default=DEFAULT_STORE_ROOT,
        help=f"Store root (default: {DEFAULT_STORE_ROOT})",
    )
    parser.add_argument(
        "--no-classify", action="store_true",
        help="Skip the per-doc LLM classifier (offline / air-gapped mode)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logs")
    args = parser.parse_args(effective)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    target: Path = args.target
    if not target.exists():
        print(f"Not found: {target}", file=sys.stderr)
        return 2

    classify = not args.no_classify
    if target.is_dir():
        return 1 if _ingest_batch(target, args.store, classify=classify) else 0

    result = ingest_document(target, store_root=args.store, classify=classify)
    print(_format(result, target))
    return 0 if result.status in {IngestionStatus.INGESTED, IngestionStatus.DUPLICATE} else 1


if __name__ == "__main__":
    sys.exit(main())
