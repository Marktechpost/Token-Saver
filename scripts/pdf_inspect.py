#!/usr/bin/env python3
"""pdf_inspect.py - cheap PDF inventory + targeted extraction.

Subcommands (run with --help on each):
  info     page count, outline, per-page text length, scanned-page flags
  text     extract text for a page range (e.g. --pages 12-14)
  search   find a phrase, return page numbers + context (+ neighbor suggestions)
  tables   extract tables to CSV (pdfplumber)
  map      split the document into N-page chunks on disk for map-reduce
  index    build a durable passage-level hybrid index (desktop; speeds up retrieve.py)
  clear    delete cached indexes (one PDF, all, or only TTL-expired)

Bulk text never enters the model's context: write to files and read only the
slice you need. Flags scanned/low-text pages so "no text" is not silently read
as "nothing relevant".

Dependencies: pypdf (info/text/search/map), pdfplumber (tables).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

LOW_TEXT = 40  # chars; below this a page is likely scanned/image-only


def eprint(*a):
    print(*a, file=sys.stderr)


def reader_for(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        eprint("Install pypdf:  pip install pypdf")
        sys.exit(2)
    if not path.exists():
        eprint(f"No such file: {path}")
        sys.exit(1)
    return PdfReader(str(path))


def page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def parse_pages(spec: str, n: int):
    """'12-14,17' -> [12,13,14,17] (1-based, clamped)."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return [p for p in out if 1 <= p <= n]


def cmd_info(args):
    reader = reader_for(args.pdf)
    pages = reader.pages
    n = len(pages)
    print(f"file   : {args.pdf}")
    print(f"pages  : {n}")
    outline = []
    try:
        for item in reader.outline or []:
            t = getattr(item, "title", None)
            if t:
                outline.append(str(t))
    except Exception:
        pass
    if outline:
        print("outline:")
        for t in outline[:60]:
            print(f"  - {t}")
    scanned = []
    print("pages (length / flag):")
    for i, p in enumerate(pages, start=1):
        ln = len(page_text(p))
        flag = "  <-- LOW TEXT (scanned?)" if ln < LOW_TEXT else ""
        if flag:
            scanned.append(i)
        if n <= 60 or flag:
            print(f"  p{i:>4}: {ln:>6}{flag}")
    if scanned:
        eprint(f"WARNING: {len(scanned)} low-text page(s) (maybe scanned): {scanned}")
        eprint("         OCR them, or note their content is NOT searchable text.")


def cmd_text(args):
    reader = reader_for(args.pdf)
    n = len(reader.pages)
    nums = parse_pages(args.pages, n) if args.pages else list(range(1, n + 1))
    parts = [f"----- [page {p}] -----\n{page_text(reader.pages[p - 1]).strip()}" for p in nums]
    out = "\n\n".join(parts) + "\n"
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        eprint(f"Wrote {len(nums)} page(s) -> {args.out}")
    else:
        sys.stdout.write(out)


def cmd_search(args):
    reader = reader_for(args.pdf)
    n = len(reader.pages)
    needle = args.query.lower()
    hits = []
    for i, p in enumerate(reader.pages, start=1):
        t = page_text(p)
        idx = t.lower().find(needle)
        if idx != -1:
            start = max(0, idx - 60)
            ctx = re.sub(r"\s+", " ", t[start:idx + len(args.query) + 60]).strip()
            hits.append((i, ctx))
    if not hits:
        eprint(f"No match for {args.query!r}. Try a synonym, or use retrieve.py for semantic match.")
        return
    suggest = set()
    for i, ctx in hits:
        print(f"[page {i}] ...{ctx}...")
        for d in range(1, args.neighbors + 1):
            if i - d >= 1: suggest.add(i - d)
            if i + d <= n: suggest.add(i + d)
    if args.neighbors:
        eprint(f"neighbor pages worth pulling: {sorted(suggest - {h[0] for h in hits})}")


def cmd_tables(args):
    try:
        import pdfplumber
    except ImportError:
        eprint("Install pdfplumber:  pip install pdfplumber")
        sys.exit(2)
    outdir = Path(args.out or "tables")
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    with pdfplumber.open(str(args.pdf)) as pdf:
        n = len(pdf.pages)
        nums = parse_pages(args.pages, n) if args.pages else list(range(1, n + 1))
        for p in nums:
            for ti, table in enumerate(pdf.pages[p - 1].extract_tables() or []):
                fp = outdir / f"page{p}_table{ti + 1}.csv"
                with open(fp, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(table)
                count += 1
                eprint(f"  wrote {fp}")
    eprint(f"Extracted {count} table(s) -> {outdir}/")


def cmd_map(args):
    reader = reader_for(args.pdf)
    pages = reader.pages
    n = len(pages)
    outdir = Path(args.out or "chunks")
    outdir.mkdir(parents=True, exist_ok=True)
    size = args.chunk
    for ci, start in enumerate(range(0, n, size), start=1):
        block = range(start + 1, min(start + size, n) + 1)
        text = "\n\n".join(f"----- [page {p}] -----\n{page_text(pages[p - 1]).strip()}" for p in block)
        fp = outdir / f"chunk{ci:03d}_p{block.start}-{block.stop - 1}.txt"
        fp.write_text(text + "\n", encoding="utf-8")
        eprint(f"  wrote {fp}")
    eprint(f"Split {n} pages into {size}-page chunks -> {outdir}/")
    eprint("Map-reduce: summarize each chunk to disk, then combine the summaries.")


def cmd_index(args):
    """Build the durable passage-level hybrid index in the central cache dir.

    One-time bulk work (extract + chunk + embed) persisted under ~/.token_saver/
    (override $TOKEN_SAVER_CACHE) so retrieve.py answers later queries instantly
    and losslessly instead of re-embedding the whole document every time. Built
    atomically under a lock; auto-expires per TTL; wipe with `clear`. Desktop only.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import index_store
    if index_store.is_fresh(args.pdf) and not args.force:
        eprint(f"index up to date: {index_store.index_path(args.pdf)}  (use --force to rebuild)")
        return
    index_store.build_index(args.pdf, force=args.force)


def cmd_clear(args):
    """Clear cached indexes (one PDF, all, or only expired)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import index_store
    if args.pdf:
        removed = index_store.clear_index(args.pdf)
        eprint(f"cleared index for {args.pdf}" if removed else f"no index for {args.pdf}")
    else:
        n = index_store.clear_all(expired_only=args.expired)
        scope = "expired" if args.expired else "all"
        eprint(f"cleared {n} {scope} index(es) from {index_store.CACHE_DIR}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info"); p.add_argument("pdf", type=Path); p.set_defaults(func=cmd_info)

    p = sub.add_parser("text"); p.add_argument("pdf", type=Path)
    p.add_argument("--pages"); p.add_argument("-o", "--out"); p.set_defaults(func=cmd_text)

    p = sub.add_parser("search"); p.add_argument("pdf", type=Path); p.add_argument("query")
    p.add_argument("--neighbors", type=int, default=0); p.set_defaults(func=cmd_search)

    p = sub.add_parser("tables"); p.add_argument("pdf", type=Path)
    p.add_argument("--pages"); p.add_argument("-o", "--out"); p.set_defaults(func=cmd_tables)

    p = sub.add_parser("map"); p.add_argument("pdf", type=Path)
    p.add_argument("--chunk", type=int, default=5); p.add_argument("-o", "--out"); p.set_defaults(func=cmd_map)

    p = sub.add_parser("index"); p.add_argument("pdf", type=Path)
    p.add_argument("--force", action="store_true", help="rebuild even if up to date")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("clear"); p.add_argument("pdf", type=Path, nargs="?",
        help="PDF whose index to clear; omit to clear the whole cache")
    p.add_argument("--expired", action="store_true", help="only clear TTL-expired indexes")
    p.set_defaults(func=cmd_clear)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
