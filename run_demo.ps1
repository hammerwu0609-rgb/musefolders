$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

Set-Location -LiteralPath $PSScriptRoot
# Do not install this project editably: Python 3.11 may read its Chinese path
# from a .pth file with the Windows GBK locale. app.py imports live src/ itself.
$syncArgs = @("sync", "--no-install-project", "--extra", "sonic")
if ($env:MUSEFOLDERS_ENABLE_LYRICS -eq "1") {
    $syncArgs += @("--extra", "lyrics")
}
& uv @syncArgs
if ($LASTEXITCODE -ne 0) {
    throw "Could not prepare the local Python environment. Check network access and free disk space."
}
uv run --no-sync streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false

