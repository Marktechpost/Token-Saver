#!/usr/bin/env bash
# DEVELOPER TOOL — NOT the way Token Saver is installed.
#
# Users install the Claude Desktop extension (dist/token-saver-ccr.mcpb); see
# INSTALL_GUIDE.md. This script exists only to build a local .venv so the test
# suite and the bundle build can run on a contributor's machine.
#
# It also prints a Claude Desktop config block for running the server straight
# from a checkout, which is handy when debugging the server itself — but that is
# a development convenience, not a supported install path.
#
# Usage:
#   bash scripts/install.sh            # dev venv (server deps)
#   bash scripts/install.sh --full     # + CLI/eval extras
#   PYTHON=python3.12 bash scripts/install.sh   # pick a specific interpreter
set -euo pipefail

# Resolve the repo root (this script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.10+ from https://python.org/downloads" >&2
  exit 1
fi

# Require Python 3.10+ (the floor the tests target).
"$PY" - <<'EOF'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("ERROR: Python 3.10+ required, found %d.%d" % sys.version_info[:2])
EOF

REQ="requirements-mcp.txt"
if [ "${1:-}" = "--full" ]; then
  REQ="requirements.txt"
fi

VENV="$REPO_ROOT/.venv"
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment in .venv ..."
  "$PY" -m venv "$VENV"
fi
VENV_PY="$VENV/bin/python"

echo "Installing dependencies from $REQ"
echo "(this can take a few minutes — it downloads the embedding backend once) ..."
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r "$REQ"

echo
echo "Running the self-test (also warms up the embedding model) ..."
"$VENV_PY" tests/mcp_selftest.py

SERVER_PY="$REPO_ROOT/scripts/mcp_server.py"
cat <<EOF

============================================================
 Token Saver is installed.
 Add this to your Claude Desktop config:
   Settings -> Developer -> Edit Config
------------------------------------------------------------
{
  "mcpServers": {
    "token-saver-ccr": {
      "command": "$VENV_PY",
      "args": ["$SERVER_PY"]
    }
  }
}
------------------------------------------------------------
 Then FULLY quit Claude Desktop (Cmd+Q) and reopen it.
 (If a config already exists, add just the "token-saver-ccr"
  block inside the existing "mcpServers" object.)
============================================================
EOF
