# raw-ocr — OCR-stress corpus (Phase 8b.7)

Public-domain documents added 2026-05-10 to exercise the full ingestion
chain including OCR. No PII. License: Licence Ouverte 2.0 (French
government open license).

Source: French National Assembly archives —
`https://archives.assemblee-nationale.fr/`.

| File | Size | Pages | Mode | Source |
|---|---|---|---|---|
| `an-7-qst-1985-01-14-extract.pdf` | 3.0M | 15 | hybrid (image + OCR text layer by AN) | 7-qst-1985-01-14.pdf, p1-15 |
| `an-7-qst-1985-12-30-extract.pdf` | 2.0M | 15 | hybrid | 7-qst-1985-12-30.pdf, p1-15 |
| `an-9-qst-1992-08-10-extract.pdf` | 2.4M | 15 | hybrid | 9-qst-1992-08-10.pdf, p1-15 |
| `an-9-cri-1992-1993-011-extract.pdf` | 3.2M | 15 | hybrid | 9/cri/1992-1993-ordinaire1/011.pdf, p1-15 |
| `an-7-qst-1985-01-14-image-only.pdf` | 6.3M | 15 | pure image (rasterized 200dpi) | derived from -extract |
| `an-9-qst-1992-08-10-image-only.pdf` | 5.2M | 15 | pure image | derived from -extract |

## Modes

- **hybrid** = original AN scan with embedded OCR text layer (typos
  preserved, e.g. `(® .)` for `(Q.)`). Forces post-OCR text-quality
  stress on extraction. Docling will likely use the text layer
  directly; Profile fragmentation + entity extraction still see OCR
  artifacts.
- **pure image** = Ghostscript rasterized at 200dpi to remove the text
  layer. Forces our pipeline to run OCR (Docling layout → ocrmac
  fallback path).

## Why not Gallica / Légifrance / Archives départementales?

- Gallica blocked WebFetch via captcha (manual download possible but
  out of v0.5 scope).
- Légifrance JORF page returned 403 to WebFetch.
- Archives départementales sites typically don't expose direct PDF
  URLs to crawlers.

AN archives have stable per-week URL patterns (`/<legislature>/<type>/<n>-<type>-YYYY-MM-DD.pdf`),
no auth, real scans, and Licence Ouverte. Best public source identified
in the 2026-05-10 dorking session.

## Re-fetching

```bash
curl -o an-7-qst-1985-01-14.pdf https://archives.assemblee-nationale.fr/7/qst/7-qst-1985-01-14.pdf
gs -dNOPAUSE -dQUIET -dBATCH -sDEVICE=pdfwrite \
   -dFirstPage=1 -dLastPage=15 \
   -sOutputFile=an-7-qst-1985-01-14-extract.pdf an-7-qst-1985-01-14.pdf
gs -dNOPAUSE -dQUIET -dBATCH -sDEVICE=pdfimage8 -r200 \
   -sOutputFile=an-7-qst-1985-01-14-image-only.pdf an-7-qst-1985-01-14-extract.pdf
```
