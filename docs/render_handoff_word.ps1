param([string]$DocumentPath = '')
$ErrorActionPreference = 'Stop'
$documentPath = if ([string]::IsNullOrWhiteSpace($DocumentPath)) {
    Join-Path $PSScriptRoot '曲境项目交接文档-v1.1.docx'
} else {
    [System.IO.Path]::GetFullPath($DocumentPath)
}
$outputDir = Join-Path $PSScriptRoot '.qa_handoff_word'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$pdfPath = Join-Path $outputDir ([System.IO.Path]::GetFileNameWithoutExtension($documentPath) + '.pdf')

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($documentPath, $false, $true)
    $pages = $document.ComputeStatistics(2)
    $document.ExportAsFixedFormat($pdfPath, 17)
    Write-Output "PAGES=$pages"
    Write-Output "PDF=$pdfPath"
} finally {
    if ($null -ne $document) { $document.Close($false) }
    if ($null -ne $word) { $word.Quit() }
}
