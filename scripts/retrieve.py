#!/usr/bin/env python3
"""retrieve.py - precise, citable slice from a PDF (the accuracy workhorse).

Pulls only the part of a document a question needs, using three accuracy levers:
  1. Structural anchors  - always include outline/headings + defined terms so a
                           term defined on p.3 but used on p.80 is never missed.
  2. Hybrid matching      - keyword always; semantic too if sentence-transformers
                           is installed (synonyms don't slip through).
  3. Neighbor expansion   - include pages around each hit, and follow explicit
                           cross-references ("see section 4.2").

It prints a coverage report and a loud WARNING when a query term matches nothing
-- the cue to widen retrieval (escalation ladder) before trusting the answer.

Usage:
  python retrieve.py report.pdf --query "revenue recognition for SaaS" \
      --top-k 5 --neighbors 1 --anchors --follow-xrefs -o slice.txt

Dependencies: pypdf (required). sentence-transformers (optional, for semantic).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

XREF_RE = re.compile(r"(?:see|cf\.?|refer to)\s+(?:section|sec\.?|\u00a7|clause|chapter|page|p\.?)\s*([\d]+(?:\.[\d]+)*)", re.I)
HEADING_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,'&/()-]{2,80}$")


def eprint(*a):
    print(*a, file=sys.stderr)


def load_pages(pdf_path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        eprint("Install pypdf:  pip install pypdf")
        sys.exit(2)
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text)
    outline = []
    try:
        for item in reader.outline or []:
            title = getattr(item, "title", None)
            if title:
                outline.append(str(title))
    except Exception:
        pass
    return pages, outline


def tokenize(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())


def keyword_scores(pages, query):
    terms = [t for t in tokenize(query) if len(t) > 2]
    scores, hits = [], {t: 0 for t in terms}
    for text in pages:
        toks = tokenize(text)
        counts = {t: toks.count(t) for t in terms}
        for t, c in counts.items():
            hits[t] += c
        scores.append(sum(counts.values()))
    missing = [t for t, c in hits.items() if c == 0]
    return scores, terms, missing


def semantic_scores(pages, query):
    try:
        from sentence_transformers import SentenceTransformer, util
    except ImportError:
        return None
    model = SentenceTransformer("all-MiniLM-L6-v2")
    q = model.encode(query, convert_to_tensor=True)
    embs = model.encode([p[:2000] for p in pages], convert_to_tensor=True)
    return util.cos_sim(q, embs)[0].tolist()


def find_anchors(pages, outline):
    anchors = list(outline)
    for text in pages:
        for line in text.splitlines():
            line = line.strip()
            if HEADING_RE.match(line) and len(line.split()) <= 10:
                anchors.append(line)
    # de-dup, keep order
    seen, out = set(), []
    for a in anchors:
        if a not in seen:
            seen.add(a); out.append(a)
    return out[:40]


def find_xref_pages(pages, hit_pages, outline):
    targets = set()
    for p in hit_pages:
        for m in XREF_RE.finditer(pages[p - 1]):
            ref = m.group(1)
            # try to resolve "page N"
            if ref.isdigit() and 1 <= int(ref) <= len(pages):
                targets.add(int(ref))
            else:
                # section number: scan for a heading containing it
                for idx, text in enumerate(pages, start=1):
                    if re.search(r"\b" + re.escape(ref) + r"\b", text[:400]):
                        targets.add(idx); break
    return sorted(targets)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--query", required=True)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--neighbors", type=int, default=1, help="pages of context around each hit")
    ap.add_argument("--anchors", action="store_true", help="prepend outline/headings + defined terms")
    ap.add_argument("--follow-xrefs", action="store_true", help="follow 'see section X' cross-references")
    ap.add_argument("-o", "--out", type=Path, help="write slice to file (default: stdout)")
    args = ap.parse_args()

    if not args.pdf.exists():
        eprint(f"No such file: {args.pdf}"); sys.exit(1)

    pages, outline = load_pages(args.pdf)
    n = len(pages)

    kw, terms, missing = keyword_scores(pages, args.query)
    sem = semantic_scores(pages, args.query)

    combined = []
    for i in range(n):
        s = kw[i]
        if sem is not None:
            s = s + 5.0 * max(sem[i], 0)  # blend; semantic on a comparable scale
        combined.append(s)

    ranked = sorted(range(n), key=lambda i: combined[i], reverse=True)
    top = [i + 1 for i in ranked[: args.top_k] if combined[i] > 0]

    selected = set(top)
    for p in list(top):
        for d in range(1, args.neighbors + 1):
            if p - d >= 1: selected.add(p - d)
            if p + d <= n: selected.add(p + d)

    xref_pages = []
    if args.follow_xrefs and top:
        xref_pages = find_xref_pages(pages, top, outline)
        selected.update(xref_pages)

    selected = sorted(selected)

    # ---- coverage report (stderr so it doesn't pollute the slice) ----
    eprint("=" * 60)
    eprint(f"COVERAGE REPORT  ({args.pdf.name}, {n} pages)")
    eprint(f"  query terms     : {', '.join(terms) or '(none)'}")
    eprint(f"  semantic match  : {'on' if sem is not None else 'off (keyword only)'}")
    eprint(f"  top pages       : {top or '(no keyword/semantic hits)'}")
    eprint(f"  + neighbors     : {sorted(selected)}")
    if args.follow_xrefs:
        eprint(f"  + cross-refs    : {xref_pages or '(none found)'}")
    if missing:
        eprint(f"  WARNING: query term(s) matched NOTHING: {', '.join(missing)}")
        eprint("           -> widen retrieval (raise --top-k / --neighbors) before trusting the answer.")
    if not top:
        eprint("  WARNING: no pages matched. Abstain or widen; do not answer from priors.")
    eprint("=" * 60)

    # ---- build slice ----
    parts = []
    if args.anchors:
        anchors = find_anchors(pages, outline)
        if anchors:
            parts.append("## STRUCTURAL ANCHORS (outline / headings)\n" + "\n".join(f"- {a}" for a in anchors))
    for p in selected:
        tag = "  [cross-ref]" if p in xref_pages else ""
        parts.append(f"\n----- [page {p}]{tag} -----\n{pages[p - 1].strip()}")

    out_text = "\n".join(parts).strip() + "\n"

    if args.out:
        args.out.write_text(out_text, encoding="utf-8")
        eprint(f"Wrote slice -> {args.out}  ({len(out_text)} chars, ~{len(out_text)//4} tokens)")
    else:
        sys.stdout.write(out_text)


if __name__ == "__main__":
    main()
