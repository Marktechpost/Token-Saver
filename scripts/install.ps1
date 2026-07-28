# Token Saver installer (Windows / PowerShell).
#
# Creates a virtual environment, installs the MCP-server dependencies, runs the
# self-test, and prints the exact Claude Desktop config to paste — with the
# venv Python and server path already filled in.
#
# Usage (from the Token Saver folder, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 --full
$ErrorActionPreference = "Stop"

# Repo root = parent of this script's folder (scripts\).
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$py = "python"
try { & $py --version | Out-Null } catch {
  Write-Error "Python not found. Install Python 3.10+ from https://python.org/downloads (tick 'Add Python to PATH')."
  exit 1
}
& $py -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Error "Python 3.10+ required."; exit 1 }

$req = "requirements-mcp.txt"
if ($args -contains "--full") { $req = "requirements.txt" }

$venv = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $venv)) {
  Write-Host "Creating virtual environment in .venv ..."
  & $py -m venv $venv
}
$venvPy = Join-Path $venv "Scripts\python.exe"

Write-Host "Installing dependencies from $req (downloads the embedding backend once) ..."
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r $req

Write-Host ""
Write-Host "Running the self-test (also warms up the embedding model) ..."
& $venvPy tests\mcp_selftest.py

# JSON needs backslashes escaped.
$serverPy = Join-Path $RepoRoot "scripts\mcp_server.py"
$venvPyJson = $venvPy -replace '\\', '\\'
$serverPyJson = $serverPy -replace '\\', '\\'
Write-Host @"

============================================================
 Token Saver is installed.
 Add this to your Claude Desktop config (Settings -> Developer -> Edit Config):
------------------------------------------------------------
{
  "mcpServers": {
    "token-saver-ccr": {
      "command": "$venvPyJson",
      "args": ["$serverPyJson"]
    }
  }
}
------------------------------------------------------------
 Then fully quit Claude Desktop (tray icon -> Quit) and reopen it.
============================================================
"@
