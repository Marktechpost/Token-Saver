#!/usr/bin/env python3
"""retrieval_eval.py - real retrieval quality on gold question->page labels.

Measures the two numbers CRITICAL_REVIEW §1.3 says are currently unproven:
  - recall@5      : fraction of gold questions whose answer page is in the top 5
  - false-abstain : fraction of on-topic gold questions that return NOTHING
                    (the SEM_FLOOR gate over-rejecting)

It also calibrates the gate:  --sweep-floor 0.15:0.35:0.05  prints recall/abstain
per SEM_FLOOR so the default (0.25) can be checked against evidence.

Corpora:
  * A built-in SYNTHETIC document with KNOWN gold pages ships inline, so the eval
    ALWAYS runs (offline, no torch needed with --keyword-only). This validates the
    harness and gives a first floor reading.
  * Two real public documents — the Berkshire Hathaway 2023 annual report (152 pp,
    financial prose) and the Dobbs v. Jackson opinion (213 pp, legal prose) — are
    staged in CORPUS with pinned URLs and sha256; `--download` fetches them to
    eval/corpus/ (gitignored) and their gold lives in eval/gold/*.jsonl (committed).
    Those gold page labels are AUTHORED BUT UNVERIFIED

Usage:
  python eval/retrieval_eval.py                 # semantic if torch present, else keyword
  python eval/retrieval_eval.py --keyword-only  # CI-safe, no embeddings
  python eval/retrieval_eval.py --sweep-floor 0.15:0.35:0.05
  python eval/retrieval_eval.py --download      # fetch + include the real corpus

Dependencies: pypdf; numpy + sentence-transformers only for the semantic path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
CORPUS_DIR = HERE / "corpus"
GOLD_DIR = HERE / "gold"

# Real public documents, pinned by sha256 so every run scores the same bytes as
# the figures published in the README. Gold answer labels live in eval/gold/ and
# are committed; only these PDFs are fetched at runtime (eval/corpus/ is
# gitignored — the files are large and redistributable from their sources).
#
# Adding a document means authoring a matching eval/gold/<name>.jsonl, which
# changes the headline metric — so the set is deliberately small and fixed:
# two real documents (a 152-page financial report, a 213-page legal opinion)
# plus the built-in synthetic doc whose gold is correct by construction.
CORPUS = {
    "berkshire": {
        "url": "https://www.berkshirehathaway.com/2023ar/2023ar.pdf",
        "sha256": "2132b85f9c472a6f0b141551adb08d93f88db28e6a3794e7e2b13ca3f8a57b5b",
        "gold": "berkshire.jsonl",
    },
    "dobbs": {
        "url": "https://www.supremecourt.gov/opinions/21pdf/19-1392_6j37.pdf",
        "sha256": "24e1b14e521fd6cc653ddbe1fbb0c41bcdd7fda6c8f32d0867d23b4415a1e8b0",
        "gold": "dobbs.jsonl",
    },
}

# ---- built-in synthetic doc: content is KNOWN, so gold pages are verified ----
SYNTHETIC_PAGES = [
    "Introduction. This report covers fiscal year 2023 operations and strategy overview.",
    "Revenue. Total revenue for 2023 was 4.2 billion dollars, up twelve percent year over year.",
    "Costs. Cost of goods sold increased this period due to supply chain disruptions and freight.",
    "Revenue Recognition. SaaS subscription revenue is recognized ratably over the contract term.",
    "Risk Factors. Currency exposure and customer concentration remain the principal risks.",
    "Profitability. Adjusted EBITDA margin improved to eighteen percent this fiscal year.",
    "Governance. The board comprises nine directors organized into three standing committees.",
    "Indemnification. The indemnification cap is two million dollars per individual claim.",
]
SYNTHETIC_GOLD = [
    {"q": "what was 2023 revenue", "pages": [2]},
    {"q": "total sales for the year", "pages": [2]},
    {"q": "how is subscription income booked", "pages": [4]},
    {"q": "revenue recognition policy", "pages": [4]},
    {"q": "what are the principal risks", "pages": [5]},
    {"q": "currency and customer concentration exposure", "pages": [5]},
    {"q": "profitability margin", "pages": [6]},
    {"q": "adjusted EBITDA", "pages": [6]},
    {"q": "liability limit for a claim", "pages": [8]},
    {"q": "indemnification cap", "pages": [8]},
]


def eprint(*a):
    print(*a, file=sys.stderr)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _open_url(url: str):
    """urlopen with a certifi fallback: macOS venv Pythons often lack system CA
    certs (CERTIFICATE_VERIFY_FAILED). certifi ships a CA bundle; use it when
    the default context fails. Manual `curl` into eval/corpus/ also works —
    existing files are never re-downloaded."""
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": "token-saver-eval"})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        try:
            import certifi
        except ImportError:
            raise RuntimeError(
                "SSL CA certs unavailable in this Python. Either `pip install certifi` "
                "or download the file manually into eval/corpus/ (curl -L -o ...)") from e
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=60, context=ctx)


def download_corpus():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in CORPUS.items():
        dest = CORPUS_DIR / f"{name}.pdf"
        if dest.exists():
            continue
        eprint(f"downloading {name} <- {spec['url']}")
        try:
            with _open_url(spec["url"]) as r:
                dest.write_bytes(r.read())
        except Exception as e:
            eprint(f"  FAILED ({e}); skipping.")
            continue
        got = _sha256(dest)
        if spec["sha256"] and got != spec["sha256"]:
            eprint(f"  sha256 MISMATCH: expected {spec['sha256']} got {got} — deleting.")
            dest.unlink(missing_ok=True)
        elif not spec["sha256"]:
            eprint(f"  sha256 (pin this in CORPUS): {got}")


# --------------------------------------------------------------- retrieval ----
def _page_texts(pdf: Path):
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def _top5_keyword(pages, query):
    """Top-5 pages by BM25 alone (no embeddings). Empty list = abstain."""
    from retrieve import keyword_scores
    scores, _terms, _missing = keyword_scores(pages, query)
    ranked = sorted(range(len(pages)), key=lambda i: scores[i], reverse=True)
    return [i + 1 for i in ranked[:5] if scores[i] > 0]


def _top5_semantic(pdf: Path, query, floor):
    """Top-5 pages via the real index_store hybrid path at a given SEM_FLOOR."""
    import index_store
    from retrieve import tokenize, STOP
    old = index_store.SEM_FLOOR
    index_store.SEM_FLOOR = floor
    try:
        if not index_store.is_fresh(pdf):
            index_store.build_index(pdf, quiet=True)
        terms = [t for t in tokenize(query) if len(t) > 2 and t not in STOP]
        page_scores, _missing, _passages = index_store.query(pdf, query, terms)
    finally:
        index_store.SEM_FLOOR = old
    ranked = sorted(range(len(page_scores)), key=lambda i: page_scores[i], reverse=True)
    return [i + 1 for i in ranked[:5] if page_scores[i] > 0]


def evaluate(docs, keyword_only, floor):
    """docs: list of (name, pdf_path, gold_list). Returns (recall, abstain, n)."""
    total = hits = abstains = 0
    for name, pdf, gold in docs:
        pages = _page_texts(pdf)
        for item in gold:
            q, gold_pages = item["q"], set(item["pages"])
            top5 = (_top5_keyword(pages, q) if keyword_only
                    else _top5_semantic(pdf, q, floor))
            total += 1
            if not top5:
                abstains += 1
            if gold_pages & set(top5):
                hits += 1
    recall = hits / total if total else 0.0
    abstain = abstains / total if total else 0.0
    return recall, abstain, total


def build_docs(tmpdir: Path, include_real: bool):
    """Materialize the synthetic doc + any downloaded real docs with gold."""
    from make_sample_pdf import make_pdf
    docs = []
    syn = tmpdir / "synthetic.pdf"
    make_pdf(syn, SYNTHETIC_PAGES)
    docs.append(("synthetic", syn, SYNTHETIC_GOLD))
    if include_real:
        for name, spec in CORPUS.items():
            pdf = CORPUS_DIR / f"{name}.pdf"
            goldf = GOLD_DIR / spec["gold"]
            if pdf.exists() and goldf.exists():
                gold = [json.loads(ln) for ln in goldf.read_text().splitlines()
                        if ln.strip() and not ln.lstrip().startswith("//")]
                if gold:
                    docs.append((name, pdf, gold))
            else:
                eprint(f"(skipping real doc '{name}': need {pdf.name} + gold/{spec['gold']})")
    # Loud warning when only the synthetic doc is present. Without it a fresh
    # clone prints "recall@5 1.00 (10 gold questions)" — the synthetic-only
    # score — which is easily mistaken for the published headline figure
    # (0.90 over 30 questions). The real corpus is gitignored, so this is the
    # DEFAULT state of a fresh clone; say so unmissably.
    if include_real and len(docs) == 1:
        eprint("")
        eprint("!" * 72)
        eprint("! SYNTHETIC DOCUMENT ONLY — this is NOT the published number.")
        eprint("! The two real PDFs are gitignored and were not found locally, so the")
        eprint("! score below covers 10 synthetic questions, not the 30-question gold set.")
        eprint("!")
        eprint("!   Published figure: recall@5 0.90 over 30 questions (README)")
        eprint("!   To reproduce it:  python eval/retrieval_eval.py --download")
        eprint("!" * 72)
        eprint("")
    return docs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keyword-only", action="store_true", help="BM25 only; no embeddings (CI-safe)")
    ap.add_argument("--sweep-floor", metavar="LO:HI:STEP", help="calibrate SEM_FLOOR, e.g. 0.15:0.35:0.05")
    ap.add_argument("--download", action="store_true", help="fetch the real corpus first")
    ap.add_argument("--floor", type=float, default=0.25, help="SEM_FLOOR for the single semantic run")
    args = ap.parse_args()

    # Keep eval-built indexes out of the user's real cache. index_store reads
    # TOKEN_SAVER_CACHE at import (first imported inside _top5_semantic), so setting
    # it here — before any semantic call — takes effect.
    os.environ.setdefault("TOKEN_SAVER_CACHE", str(HERE / "corpus" / ".cache"))

    if args.download:
        download_corpus()

    # Auto-fall back to keyword-only if the semantic stack is missing.
    keyword_only = args.keyword_only
    if not keyword_only:
        try:
            import numpy  # noqa
            from sentence_transformers import SentenceTransformer  # noqa
        except ImportError:
            eprint("(sentence-transformers/numpy absent -> keyword-only mode)")
            keyword_only = True

    with tempfile.TemporaryDirectory() as td:
        docs = build_docs(Path(td), include_real=True)
        print(f"# Retrieval eval  ({len(docs)} doc(s): {', '.join(n for n, _, _ in docs)})")
        print(f"mode: {'keyword-only' if keyword_only else 'hybrid (semantic+keyword)'}\n")

        if args.sweep_floor and keyword_only:
            eprint("(--sweep-floor requires the semantic stack; ignoring)")

        if args.sweep_floor and not keyword_only:
            lo, hi, step = (float(x) for x in args.sweep_floor.split(":"))
            print("SEM_FLOOR   recall@5   false-abstain")
            f = lo
            while f <= hi + 1e-9:
                r, a, n = evaluate(docs, keyword_only=False, floor=round(f, 4))
                print(f"  {f:0.2f}       {r:6.2f}      {a:6.2f}")
                f += step
            return 0

        recall, abstain, n = evaluate(docs, keyword_only, args.floor)
        print(f"recall@5       : {recall:.2f}  ({n} gold questions)")
        print(f"false-abstain  : {abstain:.2f}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
