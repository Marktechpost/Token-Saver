"""Token Saver — accuracy-preserving, token-minimal retrieval over heavy inputs.

This directory doubles as the installable package `token_saver` (see
pyproject.toml: package-dir maps `token_saver` -> `scripts/`). The modules keep
using flat sibling imports (`import index_store`) resolved via a runtime
`sys.path.insert(__file__ dir)`, so they work both when run as loose scripts and
when installed as a package — no import rewrite needed.

Console entry point: `token-saver-mcp` -> `token_saver.mcp_server:main`.
"""
