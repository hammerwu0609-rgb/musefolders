param(
    [string]$Version = "0.1.0-handoff"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".git"))) {
    throw "A Git repository is required so the release contains tracked files only."
}

$trackedChanges = git status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Git working tree."
}
if ($trackedChanges) {
    throw "Commit tracked changes before building a release."
}

$releaseRoot = Join-Path $projectRoot "release"
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$archiveName = "MuseFolders-$Version-source.zip"
$archivePath = Join-Path $releaseRoot $archiveName
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

git archive --format=zip --prefix="MuseFolders-$Version/" -o $archivePath HEAD
if ($LASTEXITCODE -ne 0) {
    throw "git archive failed."
}

$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
$checksumPath = "$archivePath.sha256.txt"
Set-Content -LiteralPath $checksumPath -Encoding ascii -Value "$hash  $archiveName"

Write-Host "Release archive: $archivePath"
Write-Host "SHA-256: $hash"
Write-Host "This is a source/demo bundle. It intentionally excludes user music, lyrics, analysis artifacts, secrets, the local virtual environment, and the optional fastText model."
