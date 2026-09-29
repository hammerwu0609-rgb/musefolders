$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed or is not on PATH. Install uv, then run setup.ps1."
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"))) {
    Write-Host "First launch: preparing the local Python environment..."
    & (Join-Path $PSScriptRoot "setup.ps1")
}

Write-Host "MuseFolders is starting at http://127.0.0.1:8501"
Write-Host "Keep this window open while using the app. Close it to stop the local server."
$browserJob = Start-Job -ScriptBlock {
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:8501/_stcore/health" -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                Start-Process -FilePath "http://127.0.0.1:8501"
                return
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
}
try {
    & (Join-Path $PSScriptRoot "run_demo.ps1")
} finally {
    Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
    Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
}
