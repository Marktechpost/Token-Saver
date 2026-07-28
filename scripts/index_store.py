#!/usr/bin/env python3
"""index_store.py - a durable, passage-level hybrid index for one PDF.

Why this exists (desktop / shell environments only):
  retrieve.py without an index re-extracts AND re-embeds the entire PDF on every
  query, and truncates each page to 2000 chars for the embedding. That is slow
  (you pay it per question) and leaks accuracy (anything past the truncation is
  invisible to semantic match). On a real filesystem we can do the bulk work
  ONCE and persist it, so repeat queries are instant and lossless.

What the index is:
  A single SQLite file in a central cache dir (~/.token_saver/index, keyed by the
  PDF's absolute-path hash; override with $TOKEN_SAVER_CACHE) holding
    - pages(page, text)              full page text, so callers never reopen the PDF
    - passages(id, page, text, vec)  ~180-word windows w/ page provenance + embedding
    - passages_fts                   FTS5 mirror of passage text -> BM25 keyword score
    - meta(key, value)               pdf mtime/size, model, dim, outline, schema ver
  Keyword (FTS5) and semantic (float32 vectors) live in the same file -> hybrid
  search from one durable artifact that survives across chats (the MCP server
  reuses it read-only when fresh; otherwise it embeds in RAM).

Vector engine:
  Vectors are stored as normalized float32 BLOBs and scored with a brute-force
  numpy cosine. At desktop scale (a few thousand passages) this is sub-ms and
  needs no native extension. If sqlite-vec ever becomes loadable it can replace
  the numpy step without changing this module's public surface.

Public surface (used by pdf_inspect.py and retrieve.py):
  index_path(pdf)                      -> Path of the sidecar
  is_fresh(pdf)                        -> bool (index exists and matches pdf stat)
  build_index(pdf, ...)                -> builds/overwrites the sidecar
  load_corpus(pdf)                     -> (pages, outline) from the index
  query(pdf, query_text, terms, ...)   -> (page_scores, missing_terms, passages)

Dependencies: pypdf, sentence-transformers, numpy (all required for indexed mode).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384
SCHEMA_VERSION = 4  # bump on any chunking/format/extractor change so old indexes rebuild
PASSAGE_WORDS = 180   # ~1 dense paragraph; small enough to localize a hit to a passage
PASSAGE_OVERLAP = 40  # carry context across window boundaries so a sentence isn't split blind

# --- Storage policy --------------------------------------------------------
# The command-line tools have no long-running process to keep vectors in memory,
# so the index is persisted to disk to avoid re-embedding on every query. To keep
# that disk state safe and tidy: a single central cache directory (no files
# scattered next to each PDF), an atomic build under a lock (no corruption races),
# and a time-to-live plus a `clear` command so caches don't accumulate forever.
# Default ~/.token_saver/index; override with $TOKEN_SAVER_CACHE. TTL in days via
# $TOKEN_SAVER_INDEX_TTL_DAYS (0 or negative = never expire).
CACHE_DIR = Path(os.environ.get("TOKEN_SAVER_CACHE", Path.home() / ".token_saver" / "index"))
TTL_DAYS = float(os.environ.get("TOKEN_SAVER_INDEX_TTL_DAYS", "14"))
# Absolute relevance floor: a passage must clear this raw cosine OR have a keyword
# hit to be eligible, so off-topic queries abstain instead of returning junk that
# min-max flattered to 1.0.
SEM_FLOOR = float(os.environ.get("TOKEN_SAVER_SEM_FLOOR", "0.25"))


def eprint(*a):
    print(*a, file=sys.stderr)


def index_path(pdf) -> Path:
    """Map a PDF to its index file inside the central cache dir.

    Keyed by the absolute path hash so two PDFs with the same name don't collide
    and so every index lives in one directory you can wipe in a single command.
    """
    p = Path(pdf).resolve()
    key = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{p.stem}.{key}.idx.db"


def _pdf_stat(pdf: Path):
    st = Path(pdf).stat()
    return st.st_size, st.st_mtime_ns


# ---------------------------------------------------------------- chunking ----
_WORD_RE = re.compile(r"\S+")


def passages_for_page(text: str):
    """Split one page's text into overlapping ~PASSAGE_WORDS windows.

    Windows never cross a page boundary, so every passage keeps an exact page
    number for citation. Overlap means a fact straddling two windows still lands
    wholly inside at least one of them.
    """
    words = _WORD_RE.findall(text)
    if not words:
        return []
    step = max(1, PASSAGE_WORDS - PASSAGE_OVERLAP)
    out = []
    for start in range(0, len(words), step):
        if start > 0 and len(words) - start <= PASSAGE_OVERLAP:
            break  # tail window would be pure overlap of the previous one
        chunk = words[start:start + PASSAGE_WORDS]
        if chunk:
            out.append(" ".join(chunk))
        if start + PASSAGE_WORDS >= len(words):
            break
    return out

    # ------------------------------------------------------------- extraction ----
def _pypdfium_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        return True
    except Exception:
        return False


def _extractor_name() -> str:
    """Which per-page text extractor to use, honoring TOKEN_SAVER_EXTRACTOR.

    Default is pypdfium2 (higher extraction quality, permissive license) when it
    is importable, else pypdf. An explicit `pypdf` always wins; an explicit
    `pypdfium` falls back to pypdf if the package is missing so the index still
    builds. Deterministic given env + installed packages, so it doubles as the
    value recorded in meta and checked by is_fresh — flipping extractors rebuilds.
    """
    choice = os.environ.get("TOKEN_SAVER_EXTRACTOR", "").strip().lower()
    if choice == "pypdf":
        return "pypdf"
    if choice in ("", "pypdfium", "pypdfium2"):
        return "pypdfium" if _pypdfium_available() else "pypdf"
    return "pypdfium" if _pypdfium_available() else "pypdf"


def _pages_pypdfium(pdf: Path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    pages = []
    try:
        for i in range(len(doc)):
            try:
                page = doc[i]
                tp = page.get_textpage()
                try:
                    pages.append(tp.get_text_range() or "")
                finally:
                    tp.close()
                    page.close()
            except Exception:
                pages.append("")
    finally:
        doc.close()
    return pages


def _pages_pypdf(pdf: Path):
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _read_outline(pdf: Path):
    # Outline is always read via pypdf: pypdfium's bookmark API is clumsier and the
    # outline is tiny, so there is no quality/speed reason to switch it.
    from pypdf import PdfReader
    outline = []
    try:
        reader = PdfReader(str(pdf))
        for item in reader.outline or []:
            t = getattr(item, "title", None)
            if t:
                outline.append(str(t))
    except Exception:
        pass
    return outline


def _extract(pdf: Path):
    """Per-page text (via the selected extractor) + outline (always pypdf)."""
    pages = _pages_pypdfium(pdf) if _extractor_name() == "pypdfium" else _pages_pypdf(pdf)
    return pages, _read_outline(pdf)


_MODEL = None  # process-wide cache: query() may be called repeatedly (eval, daemons)


def _embedder():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


# ------------------------------------------------------------- build lock ----
def _acquire_build_lock(dbp: Path, timeout=180):
    """Best-effort cross-process lock so two auto-builds of the same new PDF don't
    both do the work. Returns the lock Path (release by deleting it) or None if we
    gave up waiting and should proceed unlocked. Stale locks (older than timeout)
    are reclaimed."""
    lock = dbp.with_suffix(dbp.suffix + ".lock")
    start = time.time()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > timeout:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() - start > timeout:
                return None
            time.sleep(0.2)


# ----------------------------------------------------------------- build -----
def build_index(pdf, *, quiet=False, force=False) -> Path:
    import numpy as np

    pdf = Path(pdf)
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    dbp = index_path(pdf)
    dbp.parent.mkdir(parents=True, exist_ok=True)

    # Serialize concurrent builds; if another process already produced a fresh
    # index while we waited, don't redo the work.
    lock = _acquire_build_lock(dbp)
    if not force and is_fresh(pdf):
        if lock:
            lock.unlink(missing_ok=True)
        return dbp
    try:
        return _build_locked(pdf, dbp, np, quiet)
    finally:
        if lock:
            lock.unlink(missing_ok=True)


def _build_locked(pdf: Path, dbp: Path, np, quiet) -> Path:
    pages, outline = _extract(pdf)

    # Collect passages with page provenance.
    pass_rows = []  # (page, text)
    for pno, text in enumerate(pages, start=1):
        for chunk in passages_for_page(text):
            pass_rows.append((pno, chunk))

    if not quiet:
        eprint(f"indexing {pdf.name}: {len(pages)} pages -> {len(pass_rows)} passages, embedding...")

    # Embed once (the expensive step we are persisting), normalized for cosine.
    if pass_rows:
        model = _embedder()
        embs = model.encode([t for _, t in pass_rows], convert_to_numpy=True,
                             normalize_embeddings=True, batch_size=64,
                             show_progress_bar=not quiet)
        embs = embs.astype(np.float32)
    else:
        embs = np.zeros((0, DIM), dtype=np.float32)

    # Build into a unique temp file, then atomically replace the target — a
    # concurrent reader never sees a half-written index, and a crash mid-build
    # leaves the old index (or none) intact rather than a corrupt file.
    tmp = dbp.with_suffix(dbp.suffix + f".{os.getpid()}.tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(str(tmp))
    db.executescript(
        """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE pages(page INTEGER PRIMARY KEY, text TEXT);
        CREATE TABLE passages(id INTEGER PRIMARY KEY, page INTEGER, text TEXT, vec BLOB);
        CREATE VIRTUAL TABLE passages_fts USING fts5(text, content='passages', content_rowid='id');
        """
    )
    db.executemany("INSERT INTO pages(page, text) VALUES (?, ?)",
                   [(i, t) for i, t in enumerate(pages, start=1)])
    for (pno, text), vec in zip(pass_rows, embs):
        cur = db.execute("INSERT INTO passages(page, text, vec) VALUES (?, ?, ?)",
                         (pno, text, vec.tobytes()))
        db.execute("INSERT INTO passages_fts(rowid, text) VALUES (?, ?)", (cur.lastrowid, text))
    size, mtime_ns = _pdf_stat(pdf)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "model": MODEL_NAME,
        "extractor": _extractor_name(),
        "dim": DIM,
        "pdf_size": size,
        "pdf_mtime_ns": mtime_ns,
        "n_pages": len(pages),
        "n_passages": len(pass_rows),
        "outline": json.dumps(outline),
        "built_at": time.time(),  # for TTL expiry
    }
    db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                   [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.close()
    os.replace(tmp, dbp)  # atomic publish
    if not quiet:
        eprint(f"wrote index -> {dbp}  ({len(pass_rows)} passages, model {MODEL_NAME})")
    return dbp


# --------------------------------------------------------------- freshness ---
def _open_meta(pdf):
    dbp = index_path(pdf)
    if not dbp.exists():
        return None, None
    db = sqlite3.connect(str(dbp))
    try:
        meta = {k: v for k, v in db.execute("SELECT key, value FROM meta")}
    except sqlite3.DatabaseError:
        db.close()
        return None, None
    return db, meta


def _expired(meta) -> bool:
    """True if the index is older than the TTL (so it should be rebuilt/swept)."""
    if TTL_DAYS <= 0:
        return False
    try:
        return (time.time() - float(meta["built_at"])) > TTL_DAYS * 86400
    except (KeyError, ValueError):
        return False  # pre-TTL index: don't expire on a missing field


def is_fresh(pdf) -> bool:
    """True iff the index exists, matches this schema/model, the PDF on disk has
    not changed since it was built (size + mtime), AND it is within the TTL. Any
    miss means the index is ignored and rebuilt — never silently trusted."""
    pdf = Path(pdf)
    if not pdf.exists():
        return False
    db, meta = _open_meta(pdf)
    if db is None:
        return False
    db.close()
    try:
        if int(meta.get("schema_version", -1)) != SCHEMA_VERSION:
            return False
        if meta.get("model") != MODEL_NAME:
            return False
        if meta.get("extractor") != _extractor_name():
            return False
        if _expired(meta):
            return False
        size, mtime_ns = _pdf_stat(pdf)
        return int(meta["pdf_size"]) == size and int(meta["pdf_mtime_ns"]) == mtime_ns
    except (KeyError, ValueError):
        return False


# ----------------------------------------------------------------- clear -----
def clear_index(pdf) -> bool:
    """Delete one PDF's index. Returns True if a file was removed."""
    dbp = index_path(pdf)
    existed = dbp.exists()
    dbp.unlink(missing_ok=True)
    dbp.with_suffix(dbp.suffix + ".lock").unlink(missing_ok=True)
    return existed


def clear_all(expired_only=False) -> int:
    """Wipe the whole index cache (or only TTL-expired entries). Returns the count
    removed. This is the trivial cleanup the central cache dir buys us."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for dbp in CACHE_DIR.glob("*.idx.db"):
        if expired_only:
            try:
                db = sqlite3.connect(str(dbp))
                meta = {k: v for k, v in db.execute("SELECT key, value FROM meta")}
                db.close()
            except sqlite3.DatabaseError:
                meta = {}
            if not _expired(meta):
                continue
        dbp.unlink(missing_ok=True)
        dbp.with_suffix(dbp.suffix + ".lock").unlink(missing_ok=True)
        removed += 1
    return removed


def load_corpus(pdf):
    """Return (pages, outline) straight from the index — caller need not reopen the PDF."""
    db, meta = _open_meta(pdf)
    if db is None:
        raise FileNotFoundError(f"no index for {pdf}")
    rows = db.execute("SELECT page, text FROM pages ORDER BY page").fetchall()
    db.close()
    pages = [t for _, t in rows]
    outline = json.loads(meta.get("outline", "[]"))
    return pages, outline


def load_passages(pdf):
    """Return (chunks, vecs, outline) from a fresh index: chunks is
    list[(page:int, text:str)], vecs is float32 (n, DIM) unit-normalized.
    Caller must have verified is_fresh(pdf)."""
    import numpy as np
    db, meta = _open_meta(pdf)
    if db is None:
        raise FileNotFoundError(f"no index for {pdf}")
    rows = db.execute("SELECT page, text, vec FROM passages ORDER BY id").fetchall()
    db.close()
    chunks = [(int(r[0]), r[1]) for r in rows]
    if rows:
        vecs = np.frombuffer(b"".join(r[2] for r in rows),
                             dtype=np.float32).reshape(len(rows), DIM)
    else:
        vecs = np.zeros((0, DIM), dtype=np.float32)
    outline = json.loads(meta.get("outline", "[]"))
    return chunks, vecs, outline


# ------------------------------------------------------------------ query ----
def _fts_term(t: str) -> str:
    """Quote a term for FTS5 and prefix-match it.

    Quoting stops punctuation in the raw query from breaking FTS5 syntax. The
    trailing `*` is a prefix query: query terms arrive light-stemmed (see
    retrieve._stem) but the indexed passage text is RAW, so "contract" must still
    hit "contracts"/"contracting". Prefix matching is what bridges the two."""
    return f'"{t}"*'


def _fts_match_string(terms):
    return " OR ".join(_fts_term(t) for t in terms) if terms else ""


def _minmax(vals):
    import numpy as np
    a = np.asarray(vals, dtype="float64")
    lo, hi = a.min(), a.max()
    if hi <= lo:
        # Uniform scores: keep positive scores pickable instead of zeroing them.
        return np.where(a > 0, 1.0, 0.0)
    return (a - lo) / (hi - lo)


def query(pdf, query_text, terms, *, kw_weight=0.4, sem_weight=0.6, passage_k=40):
    """Hybrid passage search against the index.

    Returns:
      page_scores : list[float] length n_pages (max passage score per page),
                    so retrieve.py's existing page-level pipeline plugs straight in.
      missing     : query terms with zero keyword hits anywhere (the widen cue).
      passages    : top (page, score, text) passages for an optional precise slice.
    """
    import numpy as np

    db, meta = _open_meta(pdf)
    if db is None:
        raise FileNotFoundError(f"no index for {pdf}")
    n_pages = int(meta["n_pages"])
    rows = db.execute("SELECT id, page, text, vec FROM passages ORDER BY id").fetchall()
    if not rows:
        db.close()
        return [0.0] * n_pages, list(terms), []

    ids = [r[0] for r in rows]
    pages = np.asarray([r[1] for r in rows])
    texts = [r[2] for r in rows]
    mat = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(len(rows), DIM)
    id_to_idx = {pid: i for i, pid in enumerate(ids)}

    # --- semantic: one query embed, cosine vs every passage (vectors prenormalized).
    model = _embedder()
    q = model.encode(query_text, convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
    sem = mat @ q  # cosine in [-1, 1]
    sem = np.clip(sem, 0, None)

    # --- keyword: FTS5 BM25 (more-negative = better -> flip to positive relevance).
    kw = np.zeros(len(rows))
    match = _fts_match_string(terms)
    if match:
        for rid, score in db.execute(
                "SELECT rowid, bm25(passages_fts) FROM passages_fts WHERE passages_fts MATCH ?",
                (match,)):
            kw[id_to_idx[rid]] = -score

    # --- which terms matched nothing at all (the escalation cue).
    missing = []
    for t in terms:
        # Same prefix form as the scoring query, so a stemmed term isn't reported
        # "missing" just because the document holds its plural/tense variant.
        hit = db.execute("SELECT 1 FROM passages_fts WHERE passages_fts MATCH ? LIMIT 1",
                         (_fts_term(t),)).fetchone()
        if not hit:
            missing.append(t)
    db.close()

    combined = kw_weight * _minmax(kw) + sem_weight * _minmax(sem)
    # Absolute gate: a passage must have a real semantic signal OR a keyword hit.
    eligible = (sem >= SEM_FLOOR) | (kw > 0)
    combined = np.where(eligible, combined, 0.0)

    # Aggregate passages -> page scores (max), so a single strong passage lifts its page.
    page_scores = [0.0] * n_pages
    for idx, sc in enumerate(combined):
        p = int(pages[idx])
        if sc > page_scores[p - 1]:
            page_scores[p - 1] = float(sc)

    order = np.argsort(combined)[::-1][:passage_k]
    top_passages = [(int(pages[i]), float(combined[i]), texts[i]) for i in order if combined[i] > 0]
    return page_scores, missing, top_passages
