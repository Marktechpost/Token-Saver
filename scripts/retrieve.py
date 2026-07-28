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
import math
import re
import sys
from pathlib import Path

XREF_RE = re.compile(r"(?:see|cf\.?|refer to)\s+(?:section|sec\.?|\u00a7|clause|chapter|page|p\.?)\s*([\d]+(?:\.[\d]+)*)", re.I)
HEADING_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,'&/()-]{2,80}$")
# Stopwords: drop function words so "for", "the", etc. don't count as needles
# (previously any token >2 chars was a term, inflating filler pages \u2014 see TESTING.md).
#
# QUERY-SIDE ONLY: keyword_scores filters the query's terms through this set but
# tokenizes documents unfiltered, so nothing here can hide document content \u2014 it
# only stops filler from being scored or reported as a "missing term". The list
# grew when `ask` let people type whole questions: "what point does chapter 1
# make about databases?" used to report what/does/make/about as terms that
# "matched NOTHING", which reads as a retrieval failure to both model and user.
# Deliberately excludes words that can be contentful (point, key, main, value).
STOP = set("""
the a an and or of to in for on at by is are was were be been being as it this
that with from
what which who whom whose when where why how
do does did doing done have has had
can could shall should will would may might must
not nor but if then than so such
i me my we us our you your he him his she her they them their
there here these those
about into onto over under between across during within without
any all both each few more most other some only own same too very just also
please tell tells told say says said give gives gave show shows showed
explain explains describe describes summarize summarise summary list lists
make makes made get gets got use uses used need needs want wants know knows
mean means thing things
""".split())


def _stem(tok: str) -> str:
    """Light suffix stripping so plural/tense variants match ("contracts" ->
    "contract", "databases" -> "database", "policies" -> "policy").

    Applied inside tokenize(), i.e. to BOTH the query and the document text, so
    matching stays symmetric. Deliberately crude and dependency-free; a min stem
    length of 4 keeps it from mangling short words ("bed", "gas", "is").

    Deviation from the S5 spec's literal `ing/ed/es/s` order: stripping "es"
    before "s" turns "databases" into "databas", which then does NOT match the
    singular "database" \u2014 the exact case that motivated this item. We strip a
    bare "s" instead (plus a safe "ies" -> "y" rule), which makes regular
    singular/plural pairs agree. The trade-off is that -es plurals of s/x/ch/sh
    words (boxes, classes) still don't collapse; the FTS path's prefix matching
    in index_store covers much of that gap.
    """
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    for suf in ("ing", "ed"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[:-len(suf)]
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) - 1 >= 4:
        return tok[:-1]
    return tok


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
    """Lowercase word tokens, light-stemmed. Stemming both sides (query and
    document) is what makes "contract" find "contracts"."""
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())]


def keyword_scores(pages, query, k1=1.5, b=0.75):
    """BM25 (Okapi) over the passed text units (pages or passages).

    IDF down-weights terms common across the corpus (so a stopword that slips
    through contributes ~nothing), and length normalization stops long units from
    out-scoring short ones purely on size — both fixes over the old raw term-count
    sum. Returns (scores, terms, missing); the MCP server reuses this for its
    in-memory BM25 and its content-probe scoring.
    """
    terms = [t for t in tokenize(query) if len(t) > 2 and t not in STOP]
    docs = [tokenize(text) for text in pages]
    N = len(docs) or 1
    avgdl = (sum(len(d) for d in docs) / N) if N else 1.0
    df = {t: 0 for t in terms}
    for d in docs:
        present = set(d)
        for t in terms:
            if t in present:
                df[t] += 1
    idf = {t: math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5)) for t in terms}
    scores, hits = [], {t: 0 for t in terms}
    for d in docs:
        dl = len(d) or 1
        tf = {}
        for tok in d:
            if tok in idf:
                tf[tok] = tf.get(tok, 0) + 1
        sc = 0.0
        for t in terms:
            f = tf.get(t, 0)
            hits[t] += f
            if f:
                denom = f + k1 * (1 - b + b * dl / avgdl)
                sc += idf[t] * (f * (k1 + 1)) / denom
        scores.append(sc)
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
    ap.add_argument("--no-index", action="store_true", help="don't build or use an index; score the PDF directly")
    ap.add_argument("--passages", action="store_true",
                    help="emit top matching passages instead of whole pages "
                         "(indexed mode only; the biggest token saver)")
    ap.add_argument("-o", "--out", type=Path, help="write slice to file (default: stdout)")
    args = ap.parse_args()

    if not args.pdf.exists():
        eprint(f"No such file: {args.pdf}"); sys.exit(1)

    # Prefer a durable passage-level index: it avoids re-embedding the whole PDF
    # per query and matches at passage (not page) granularity. If none exists yet,
    # build it now (one-time) so this query already benefits and later ones are
    # instant. Any failure (missing deps, etc.) falls back transparently to direct
    # scoring. --no-index opts out entirely.
    idx = None
    if not args.no_index:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import index_store
            if not index_store.is_fresh(args.pdf):
                try:
                    eprint("no fresh index; building one (one-time) ...")
                    index_store.build_index(args.pdf, quiet=True)
                except Exception as e:
                    eprint(f"(index build skipped: {e}; scoring directly)")
            if index_store.is_fresh(args.pdf):
                idx = index_store
        except ImportError:
            idx = None

    if idx is not None:
        pages, outline = idx.load_corpus(args.pdf)
        n = len(pages)
        terms = [t for t in tokenize(args.query) if len(t) > 2 and t not in STOP]
        combined, missing, passages = idx.query(args.pdf, args.query, terms)
        sem = True  # report marker: semantic scoring active via the index
    else:
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
    if idx is not None:
        sem_status = "on (indexed passages)"
    elif sem is not None:
        sem_status = "on"
    else:
        sem_status = "off (keyword only)"
    eprint(f"  semantic match  : {sem_status}")
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
    if args.passages and idx is None:
        eprint("(note: --passages needs an index; falling back to page slice)")

    if args.passages and idx is not None:
        # Passage-granularity slice: the tightest, most token-efficient output.
        if args.neighbors:
            eprint("(note: --neighbors ignored in --passages mode)")
        parts = []
        if args.anchors:
            anchors = find_anchors(pages, outline)
            if anchors:
                parts.append("## STRUCTURAL ANCHORS (outline / headings)\n"
                             + "\n".join(f"- {a}" for a in anchors))
        kept, seen = [], []
        for page, score, text in passages:  # already sorted desc by score
            if score <= 0 or len(kept) >= max(args.top_k * 2, 6):
                break
            w = set(text.lower().split())
            if any(p2 == page and len(w & w2) / max(1, len(w | w2)) > 0.6
                   for p2, w2 in seen):
                continue
            kept.append((page, text))
            seen.append((page, w))
        for page, text in sorted(kept):
            parts.append(f"\n----- [page {page} | passage] -----\n{text.strip()}")
        if args.follow_xrefs and xref_pages:
            for p in xref_pages:
                parts.append(f"\n----- [page {p}]  [cross-ref] -----\n{pages[p - 1].strip()}")
        out_text = "\n".join(parts).strip() + "\n"
    else:
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
