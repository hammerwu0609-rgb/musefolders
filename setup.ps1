$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location -LiteralPath $PSScriptRoot
$syncArgs = @("sync", "--extra", "dev", "--extra", "sonic", "--python", "3.11", "--no-install-project")
if ($env:MUSEFOLDERS_ENABLE_LYRICS -eq "1") {
    $syncArgs += @("--extra", "lyrics")
}
& uv @syncArgs
if ($LASTEXITCODE -ne 0) {
    throw "Could not prepare the local Python environment."
}

# Avoid an editable-install .pth containing the Chinese workspace path. The app
# loads ./src itself, and tests set it through pyproject.toml.

Write-Host "环境准备完成。运行 .\run_demo.ps1 启动产品。"
