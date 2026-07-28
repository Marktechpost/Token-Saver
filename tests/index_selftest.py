#!/usr/bin/env python3
"""index_selftest.py - exercises the durable PDF index (scripts/index_store.py).

Builds a tiny synthetic PDF in a temp dir, indexes it, and asserts:
  - semantic retrieval finds the right page with NO shared keywords,
  - keyword (FTS5/BM25) matching ranks the on-topic page,
  - the missing-term WARNING fires only for genuinely absent terms,
  - the index is invalidated when the PDF changes (freshness guard).

Skips cleanly if sentence-transformers / numpy aren't installed (indexed mode
is optional; retrieve.py still works keyword-only without them).

Run:  python tests/index_selftest.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

PASSED = FAILED = 0


def check(name, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}")


def make_pdf(path, pages_text):
    """Minimal multi-page text PDF, no dependencies."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages_text)))
    objs.append(f"<< /Type /Pages /Count {len(pages_text)} /Kids [{kids}] >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, t in enumerate(pages_text):
        content = f"BT /F1 11 Tf 50 750 Td ({esc(t)}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    Path(path).write_bytes(out)


PAGES = [
    "Chapter 1 Introduction. This document defines EBITDA as earnings before interest taxes depreciation and amortization.",
    "Chapter 2 Market Overview. The widget market grew twelve percent across the consumer segment.",
    "Chapter 3 Operations. Supply chain costs fell after renegotiating vendor contracts.",
    "Section 4 Revenue Recognition. For SaaS subscriptions revenue is recognized ratably over the contract term.",
    "Chapter 5 Risk Factors. Currency exposure and customer concentration remain the principal risks.",
]


def run_suite(index_store):
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "sample.pdf"
        make_pdf(pdf, PAGES)

        print(f"[1] Build + freshness (extractor={index_store._extractor_name()})")
        index_store.build_index(pdf, quiet=True)
        check("index reports fresh after build", index_store.is_fresh(pdf))
        check("meta records the extractor used",
              index_store._open_meta(pdf)[1].get("extractor") == index_store._extractor_name())

        print("[2] Semantic retrieval (no shared keywords)")
        terms = ["subscription", "income", "booked"]
        scores, missing, passages = index_store.query(pdf, "how is subscription income booked", terms)
        top_page = max(range(len(scores)), key=lambda i: scores[i]) + 1
        check("page 4 (SaaS revenue) ranks top for a synonym query", top_page == 4)

        print("[3] Keyword/BM25 path")
        kterms = ["ebitda"]
        kscores, kmissing, _ = index_store.query(pdf, "what is EBITDA", kterms)
        ktop = max(range(len(kscores)), key=lambda i: kscores[i]) + 1
        check("page 1 (defines EBITDA) ranks top", ktop == 1)
        check("present term not flagged missing", "ebitda" not in kmissing)

        print("[4] Miss safety")
        _, miss2, _ = index_store.query(pdf, "quantum teleportation", ["quantum", "teleportation"])
        check("absent terms flagged missing", set(miss2) == {"quantum", "teleportation"})

        print("[6] Stemming reaches the FTS path (prefix match)")
        # Page 3 says "vendor contracts"; the singular query term must still hit
        # it and must NOT be reported missing.
        cscores, cmissing, _ = index_store.query(pdf, "vendor contract", ["contract"])
        check("singular 'contract' hits the page saying 'contracts'",
              max(range(len(cscores)), key=lambda i: cscores[i]) + 1 == 3)
        check("present-as-plural term not flagged missing", "contract" not in cmissing)

        print("[5] Freshness invalidation")
        os.utime(pdf, (0, 0))  # change mtime
        check("index invalidated after PDF change", not index_store.is_fresh(pdf))


def main():
    try:
        import index_store  # noqa
        import numpy  # noqa
        from sentence_transformers import SentenceTransformer  # noqa
    except ImportError as e:
        print(f"SKIP: indexed mode deps not installed ({e}). retrieve.py still works keyword-only.")
        return 0

    import index_store

    # Run the whole suite under each requested extractor. pypdfium is only
    # exercised when the package is importable; pypdf always runs.
    extractors = ["pypdf"]
    if index_store._pypdfium_available():
        extractors.insert(0, "pypdfium")
    old = os.environ.get("TOKEN_SAVER_EXTRACTOR")
    try:
        for ex in extractors:
            print(f"\n===== extractor: {ex} =====")
            os.environ["TOKEN_SAVER_EXTRACTOR"] = ex
            run_suite(index_store)
    finally:
        if old is None:
            os.environ.pop("TOKEN_SAVER_EXTRACTOR", None)
        else:
            os.environ["TOKEN_SAVER_EXTRACTOR"] = old

    print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
