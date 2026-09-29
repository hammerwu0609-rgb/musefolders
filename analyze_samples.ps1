$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "src")).Path

Set-Location -LiteralPath $PSScriptRoot
uv run --no-sync python -m musefolders.cli analyze `
    --source "..\音乐samples" `
    --artifacts ".\artifacts"
