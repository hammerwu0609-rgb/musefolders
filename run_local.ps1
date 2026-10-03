$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Prepare the environment with setup.ps1 first.'
}
& '.\.venv\Scripts\python.exe' -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
