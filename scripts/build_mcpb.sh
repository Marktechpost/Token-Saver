#!/usr/bin/env bash
# Build the Token Saver one-click bundle (dist/token-saver-ccr.mcpb) for Claude
# Desktop. Stages a minimal bundle (manifest + pyproject + package code), then
# validates and packs it with the official mcpb CLI (via npx — needs Node).
#
# Usage:  bash scripts/build_mcpb.sh
# Then in Claude Desktop: Settings -> Extensions -> install the .mcpb file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx (Node.js) not found — needed for the mcpb CLI. Install Node 18+." >&2
  exit 1
fi

STAGE="$(mktemp -d)/token-saver-mcpb"
mkdir -p "$STAGE/scripts"
cp "$REPO_ROOT/mcpb/manifest.json" "$STAGE/manifest.json"
cp "$REPO_ROOT/pyproject.toml"     "$STAGE/pyproject.toml"
cp "$REPO_ROOT/README.md"          "$STAGE/README.md"
cp "$REPO_ROOT/LICENSE"            "$STAGE/LICENSE"
# Ship ONLY what the server imports (uv builds token-saver-ccr from pyproject at
# first run). pdf_inspect.py is a developer CLI the server never imports, so
# shipping it would just bloat the bundle and widen its attack surface.
for m in __init__.py mcp_server.py index_store.py retrieve.py; do
  cp "$REPO_ROOT/scripts/$m" "$STAGE/scripts/$m"
done
[ -f "$REPO_ROOT/mcpb/icon.png" ] && cp "$REPO_ROOT/mcpb/icon.png" "$STAGE/icon.png"

echo "Validating manifest ..."
npx -y @anthropic-ai/mcpb validate "$STAGE/manifest.json"

OUT="$REPO_ROOT/dist"
mkdir -p "$OUT"
echo "Packing ..."
npx -y @anthropic-ai/mcpb pack "$STAGE" "$OUT/token-saver-ccr.mcpb"

echo
echo "Built: $OUT/token-saver-ccr.mcpb"
echo "Install: Claude Desktop -> Settings -> Extensions -> Install extension -> pick that file."
echo "(To sign for distribution:  npx -y @anthropic-ai/mcpb sign $OUT/token-saver-ccr.mcpb)"
