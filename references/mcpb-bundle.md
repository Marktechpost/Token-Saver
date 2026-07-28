# One-click bundle (.mcpb) for Claude Desktop

The `.mcpb` (MCP Bundle) is Claude Desktop's one-click extension format. It lets
a user install Token Saver with **no Terminal, no `pip`, no venv, and no editing
`claude_desktop_config.json`** — the smoothest path for non-technical users.

## Why it uses the `uv` runtime (and the one caveat)

An `.mcpb` cannot portably bundle **compiled** Python dependencies, and Token
Saver depends on several (`torch` via sentence-transformers, `numpy`,
`pypdfium2`, `pydantic`). So a fully self-contained "nothing preinstalled ever"
bundle is not possible for this server.

Instead the bundle declares `server.type: "uv"`. Claude Desktop's managed `uv`
reads `pyproject.toml` and installs the correct platform wheels automatically.

**The one caveat:** the first time the extension runs, `uv` downloads the
dependencies (torch is a few hundred MB). It is automatic and one-time, but it
is not instant. Everything after that is fast.

## Build it

Needs Node.js (for the `mcpb` CLI, run via `npx`):

```bash
bash scripts/build_mcpb.sh
```

This stages a minimal bundle (`mcpb/manifest.json` + `pyproject.toml` + the
`scripts/` package + README/LICENSE), validates the manifest against the v0.4
schema, and writes `dist/token-saver-ccr.mcpb`.

To sign it (see "Signing: what actually happens" below — self-signing will NOT
remove the install warning):

```bash
npx -y @anthropic-ai/mcpb sign dist/token-saver-ccr.mcpb
```

## Install it (end user)

1. Download `token-saver-ccr.mcpb` (from a GitHub Release).
2. Claude Desktop → **Settings → Extensions → Install extension** → pick the file.
3. Switch **Enabled** on, then click **Configure** and choose the documents
   folder — **required** (the picker maps to the `TOKEN_SAVER_ALLOWED_DIRS`
   allowlist). A small, dedicated folder works best.
4. On the first question, choose **Always allow** on the permission prompt.
   That first run downloads dependencies once (2–5 min); then ask away.

## Release checklist (how you actually ship)

```bash
# 1. everything green
.venv/bin/python tests/mcp_selftest.py      # expect: 0 failed
.venv/bin/python tests/index_selftest.py

# 2. bump the version in BOTH files (they must match)
#    - mcpb/manifest.json  -> "version"
#    - pyproject.toml      -> version
# 3. build + validate
bash scripts/build_mcpb.sh                  # -> dist/token-saver-ccr.mcpb

# 4. sign — ONLY with a real CA cert. Self-signing passes `sign` but fails
#    `verify`, and does NOT remove the install warning. See "Signing" below.
# npx -y @anthropic-ai/mcpb sign dist/token-saver-ccr.mcpb --cert cert.pem --key key.pem
# npx -y @anthropic-ai/mcpb verify dist/token-saver-ccr.mcpb

# 5. smoke-test the built file in Claude Desktop
#    (install it, then run the 6 checks in ../INSTALL_GUIDE.md)

# 6. publish — the .mcpb is the ONLY artifact users need
gh release create v0.3.0 dist/token-saver-ccr.mcpb \
  --title "Token Saver v0.3.0" \
  --notes "Install: download the .mcpb, then Claude Desktop -> Settings -> Extensions -> Install extension."
```

`dist/` is gitignored on purpose: the bundle is a build artifact, and the
Release page is its distribution channel. Point users at Releases, never at a
clone of the repo.

## How the manifest wires up

- `server.mcp_config` runs `uv run --project <bundle> token-saver-mcp <folders>` —
  `uv` builds the `token-saver-ccr` project from `pyproject.toml`, installs deps,
  and launches the `token-saver-mcp` console entry point.
- The chosen folders are passed as CLI args; `mcp_server.main()` collapses them
  into `TOKEN_SAVER_ALLOWED_DIRS` (see `_apply_allowed_dirs`).
- The `tools` array lists the seven tools the server exposes
  (`ask`/`list_documents`/`ingest`/`search`/`clear`/`status`/`savings`).
  **Keep it in sync with `build_server()`** whenever a tool is added or renamed.

## Security

`.mcpb` does **not** sandbox — the server runs with full user privileges. Token
Saver's own defenses carry that weight: the ingest **path allowlist** (set via
the folder picker) and the **prompt-injection delimiting** of returned chunks
(see [SECURITY.md](../SECURITY.md)). Prefer setting Allowed folders for
sensitive work.

## Verification status

As of 0.3.0 the full path has been exercised on macOS: manifest validates, the
bundle packs, and the shipped `token-saver-mcp` entry point has been driven over
stdio against a real 16-PDF folder (all 16 ingest, including a 1,843-page
textbook, a 114 MB textbook, an encrypted opinion, and an image-heavy PDF).
Live install and tool-call flow confirmed in Claude Desktop across Opus, Sonnet
and Haiku — see `eval/RESULTS.md` §7.

**Still re-run per release:** the `uv` first-run dependency install on a clean
machine (it is the slowest, most environment-sensitive step), and the 6 checks
in [`../INSTALL_GUIDE.md`](../INSTALL_GUIDE.md).

## Signing: what actually happens

`mcpb sign --self-signed` reports success and rewrites the file, but
`mcpb verify` then reports **"Extension is not signed"** — a self-signed
certificate chains to nothing trusted, so Claude Desktop still shows the
"not verified by Anthropic" notice. Removing that notice requires either a real
CA code-signing certificate:

```bash
npx -y @anthropic-ai/mcpb sign dist/token-saver-ccr.mcpb --cert cert.pem --key key.pem
```

…or distribution through Anthropic's extension directory. Until then the notice
is expected, and `INSTALL_GUIDE.md` explains it to users rather than glossing it.

## Developer loop (not a shipping path)

`scripts/install.sh` / `install.ps1` and `requirements-mcp.txt` exist **only** to
build a local `.venv` for running the tests. They are not an install method and
must not appear in user-facing docs — users install the `.mcpb`, full stop.

```bash
bash scripts/install.sh              # dev venv for the test suite
.venv/bin/python tests/mcp_selftest.py
```
