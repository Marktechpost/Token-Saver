# Resident MCP server

`scripts/mcp_server.py` is a long-lived, in-memory retrieval server. On
**Claude Desktop**, instead of shipping a whole PDF to the cloud, the model
calls a local `search` tool and gets back only the top-K passages.

This is the RAM-resident counterpart to the CLI's disk index (`index_store.py`).
A resident process can keep vectors hot in memory, so **this server never
writes to disk** — though it will *reuse* a fresh index the CLI already built,
read-only, to skip re-embedding. (The CLI has no resident process, so it
persists instead. Same logic, two runtimes.)

## What it exposes

| Tool | Purpose |
|---|---|
| `ask(target, query, k=5)` | **Preferred entry point.** Resolves a loose reference (`"the Q3 report"`, `"my latest PDF"`, a filename, a topic, or a path) to a file in the approved folders, then loads + searches in ONE call — so the user needn't say "ingest" or paste a path. A single match is auto-loaded and announced; only genuine ambiguity returns a numbered list. |
| `list_documents(folder="")` | List PDFs in the approved folder(s), newest first, marking loaded ones. |
| `ingest(path)` | Extract + chunk + embed a PDF into RAM. Usually unnecessary — prefer `ask`. |
| `search(query, k=5, doc="")` | Hybrid (cosine + BM25) top-K passages, each wrapped `<document-chunk source="doc pN">` with the full session savings block. |
| `clear(doc="")` | Drop one document from RAM, or — with no argument — clear everything **and reset the savings counter**. Clearing a single document keeps the running total, which is session-wide and can't be split per document. |
| `status()` | List what's loaded and how long it's been idle. |
| `savings()` | Session token savings vs. pasting the document(s) each turn, incl. accumulated context. Token counts use `tiktoken` (cl100k_base) when installed for accurate figures, falling back to a rough chars/4 estimate otherwise. |

**Loose document resolution (`ask` / `list_documents`)** only ever scans folders
the user approved: `$TOKEN_SAVER_ALLOWED_DIRS` (set at install), plus optional
`$TOKEN_SAVER_DOC_DIRS`. If neither is set, resolution is disabled and `ask` asks
for a real path — the server never lists unapproved files. Scans are capped by
`$TOKEN_SAVER_SCAN_MAX_FILES` (2000) and `$TOKEN_SAVER_SCAN_MAX_DEPTH` (3). A
fuzzy/recency match is **auto-loaded and announced** ("Reading X.pdf — the
closest match…"), not confirmed first: the confirm-then-recall handshake was the
main reason `ask` stalled on weaker models, which had to relay the prompt, wait,
and re-call with an exact path. The safety net is that the answer names the file
and cites its pages, so a wrong pick is visible and correctable next turn. Set
`TOKEN_SAVER_CONFIRM=1` to restore confirm-first.

### How a reference is resolved

1. **Exact path** the user typed → used as-is (subject to the allowlist).
2. **Filename match** ≥ 0.5 fuzzy score → one match loads; 2+ ask which.
3. **Near-miss rescue** — a top scorer ≥ 0.35 that beats the runner-up by 1.5×
   is accepted. Real requests routinely land just under the bar: *"Warren
   Buffett's 2023 letter to shareholders"* scores **0.494** on
   `berkshire-2023-letter.pdf`, the correct file ranked first by 2.3×.
4. **Content probe** — when the filename says nothing, the first
   `TOKEN_SAVER_PROBE_PAGES` (3) pages plus PDF metadata of each candidate are
   scored against the request. This is what bridges *"affirmative action"* → a
   court-ruling file. The winner must match ≥ 2 distinct query terms, so one
   incidental word can't manufacture a match.
5. Otherwise → "not found", listing the approved folders.

**Known limit:** front-matter probing can't distinguish two large books whose
subject appears only deep inside (e.g. *"Pavlov … the textbook"* against two
1000-page textbooks). See `eval/RESULTS.md` §7.3.

The **savings footer is the full session block on every answer** (searches,
chunks, accumulated tokens, naive baseline, saved + % + est. $) — there is no
"chat ended" event an MCP server can hook, so the last answer always carries the
running totals. The `savings()` tool repeats the same block on demand.

Handled explicitly: an `asyncio.Lock` guards ingest-vs-search; overlapping
chunks (reused from `index_store`); graceful degradation if the embedding model
can't initialize; TTL eviction of idle documents
(`$TOKEN_SAVER_MCP_TTL_MINUTES`, default 30); a response character budget
(`$TOKEN_SAVER_MCP_MAX_CHARS`, default 8000); an ingest path allowlist
(`$TOKEN_SAVER_ALLOWED_DIRS`, see SECURITY.md); and search results delimited as
quoted document data (prompt-injection mitigation).

## Install

Token Saver ships **only** as a Claude Desktop extension (`.mcpb`). There is no
pip/venv/config-file path for users — the manifest *is* the configuration.

1. Get `token-saver-ccr.mcpb` (from the Releases page, or build it with
   `bash scripts/build_mcpb.sh`).
2. Claude Desktop → **Settings → Extensions → Install extension** → pick the file.
3. Choose the folder(s) holding your PDFs (required).
4. Fully quit and reopen Claude Desktop.

Build, sign and release details: [`mcpb-bundle.md`](mcpb-bundle.md).
End-user walkthrough: [`../INSTALL_GUIDE.md`](../INSTALL_GUIDE.md).

## Typical use

> "What does my lease agreement say about termination? Cite the pages."

Claude calls `ask`, which finds the file in an approved folder, loads it, and
searches in one step, naming the file it read — the full document never enters
the context window; only the returned chunks do.

## Tuning knobs (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `TOKEN_SAVER_MCP_TTL_MINUTES` | 30 | idle minutes before a RAM doc is evicted |
| `TOKEN_SAVER_MCP_MAX_CHARS` | 8000 | response budget per search (~2000 tokens) |
| `TOKEN_SAVER_SEM_FLOOR` | 0.25 | min raw cosine for a keyword-less chunk to be eligible |
| `TOKEN_SAVER_CACHE` | `~/.token_saver/index` | disk-index cache dir (CLI) |
| `TOKEN_SAVER_INDEX_TTL_DAYS` | 14 | disk-index expiry (0 = never) |
| `TOKEN_SAVER_EXTRACTOR` | auto | `pypdfium` (preferred, higher fidelity) or `pypdf` (fallback); auto-picks pypdfium when installed |
| `TOKEN_SAVER_INSTRUCTION_DOCS` | 25 | max filenames listed in the server's startup instructions (rides in every conversation's context) |
| `TOKEN_SAVER_TRIM` | `1` (on) | sentence-window trimming of returned chunks; `0` returns whole chunks (~44% more characters) |
| `TOKEN_SAVER_NO_MODEL` | unset | **Dev/diagnostic hook, not a user feature.** Forces keyword-only retrieval: no torch import, instant startup, BM25 only (recall@5 0.90, same as hybrid on the current gold set, but it misses different questions). There is deliberately no UI switch — a toggle that silently lowers answer quality is a trap. The same degradation happens automatically when the model can't load. |
| `TOKEN_SAVER_CONFIRM` | unset | `1` = confirm a fuzzy match before loading (privacy-strict setups) |
| `TOKEN_SAVER_ALLOWED_DIRS` | unset | folder allowlist for `ingest`, and the ONLY folders `ask`/`list_documents` may scan (see SECURITY.md) |
| `TOKEN_SAVER_DOC_DIRS` | unset | extra folders the resolver may scan, beyond the allowlist |
| `TOKEN_SAVER_SCAN_MAX_FILES` | 2000 | cap on PDFs scanned per `ask`/`list_documents` |
| `TOKEN_SAVER_SCAN_MAX_DEPTH` | 3 | subfolder depth cap for those scans |
| `TOKEN_SAVER_PROBE_PAGES` | 3 | pages read per candidate during the content probe |
| `TOKEN_SAVER_PROBE_MAX_FILES` | 40 | candidates the content probe will open |
| `TOKEN_SAVER_SANITIZE` | unset | `1` = replace injection-marker lines in chunks with a visible marker |
| `TOKEN_SAVER_PRICE_PER_MTOK` | 3.0 | $/Mtok used for the estimated-savings dollar figure |

Set them in the Desktop config: `"env": {"TOKEN_SAVER_MCP_TTL_MINUTES": "60"}`
inside the server entry.

## What crosses each boundary

| Location | What lives there | Lifetime |
|---|---|---|
| Model's context (the cloud) | tool-call JSON + top-K chunks (~1–2k tokens) | the conversation |
| Server RAM | chunk text + vector matrix (a few MB/doc) | 30-min idle TTL / `clear` / exit |
| Disk (CLI cache only) | SQLite index per PDF | 14-day TTL / `clear` |
| Never anywhere | the full document in the model's context | — |

## The savings math, and how far to trust it

Two quantities per search, both counted with the same tokenizer (`count_tokens`
→ tiktoken `cl100k_base`, or chars÷4 as a fallback):

```
naive_tokens  = count_tokens(whole document text)              # measured once at load
actual_tokens = count_tokens(returned chunks + preamble) + 8   # +8 = tool-result framing
saved         = max(0, naive_tokens − actual_tokens)           # accrues across the session
percent_saved = saved ÷ naive_tokens × 100
dollars_saved = saved ÷ 1,000,000 × 3.0                        # TOKEN_SAVER_PRICE_PER_MTOK
```

**The modelling choice:** the baseline counts the whole document *once per
search* — "what if you re-pasted the PDF on every question?" It is a deliberate
assumption, not a measurement. Two consequences seen in real sessions: an
unscoped search charges the baseline for **every loaded document**, and models
issue 2–6 searches per question, so the totals climb fast.

| Number | How it's obtained | Trust |
|---|---|---|
| **% saved** | Both sides use the same tokenizer, so error largely cancels in the ratio. Consistent at 96–98% across Opus/Sonnet/Haiku. | **Measured** |
| **Token counts** | Exact for `cl100k`; Claude's own tokenizer isn't public, so this is a close proxy. | **Proxy** |
| **Naive baseline** | Whole doc per search, every loaded doc — an upper bound. | **Assumption** |
| **Dollars saved** | Token proxy × a generic $3/Mtok. Illustrative, not a bill. | **Assumption** |
| **recall@5 = 0.90, false-abstain = 0.00** | Real documents, 30 questions (measured 2026-07-25); keyword-only also 0.90. Gold is author-written, not yet human-verified. | **Measured** |

**The honest headline:** quote the **percentage** and the direction. Treat
absolute token and dollar figures as estimates, not invoices.

## Test without Claude Desktop

```bash
python tests/mcp_selftest.py     # ingest → search → clear → TTL, all in-process
```

## CLI vs. MCP server — when to use which

| | CLI (`retrieve.py` + `index_store.py`) | MCP server (`mcp_server.py`) |
|---|---|---|
| Runtime | process per query | one resident process |
| Vectors | persisted to disk (central cache, TTL, `clear`) | in RAM only, TTL-evicted |
| Best for | scripted/agent shell use, cross-session reuse | interactive Claude Desktop / Cursor sessions |

Both reuse the *same* chunking, embedding model (`all-MiniLM-L6-v2`), and hybrid
scoring — they differ only in where the index lives.
