param([string]$OutputPath = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression

$sourcePath = Join-Path $PSScriptRoot '项目交接文档.md'
$outputPath = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $PSScriptRoot '曲境项目交接文档-v1.1.docx'
} else {
    [System.IO.Path]::GetFullPath($OutputPath)
}
$markdown = Get-Content -LiteralPath $sourcePath -Encoding utf8
$body = [System.Text.StringBuilder]::new()
$imageRelations = [System.Collections.Generic.List[string]]::new()
$imagePaths = [System.Collections.Generic.List[string]]::new()
$imageIndex = 0
$paragraphCount = 0
$tableCount = 0

function Escape-Xml([string]$value) {
    $value = [regex]::Replace($value, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
    return [System.Security.SecurityElement]::Escape($value)
}

function Clean-Inline([string]$text) {
    $text = [regex]::Replace($text, '\[([^\]]+)\]\(([^)]+)\)', '$1 ($2)')
    $text = [regex]::Replace($text, '<(https?://[^>]+)>', '$1')
    $text = $text.Replace('**', '').Replace('__', '').Replace('`', '')
    $text = [regex]::Replace($text, '(?<!\*)\*([^*]+)\*(?!\*)', '$1')
    return $text.Trim()
}

function New-Paragraph([string]$text, [string]$style, [int]$indent = 0) {
    $safeText = Escape-Xml (Clean-Inline $text)
    $paragraphSettings = "<w:pStyle w:val=`"$style`"/>"
    if ($indent -gt 0) {
        $paragraphSettings += "<w:ind w:left=`"$indent`"/>"
    }
    return "<w:p><w:pPr>$paragraphSettings</w:pPr><w:r><w:t xml:space=`"preserve`">$safeText</w:t></w:r></w:p>"
}

function New-CodeParagraph([string]$text, [bool]$keepNext = $false) {
    $safeText = Escape-Xml $text
    $keepNextXml = if ($keepNext) { '<w:keepNext/>' } else { '' }
    return "<w:p><w:pPr><w:pStyle w:val=`"Code`"/>$keepNextXml</w:pPr><w:r><w:t xml:space=`"preserve`">$safeText</w:t></w:r></w:p>"
}

function New-ImageParagraph([string]$path, [string]$caption) {
    $script:imageIndex++
    $relationId = 'rId' + ($script:imageIndex + 1)
    $mediaName = 'image' + $script:imageIndex + '.png'
    $script:imagePaths.Add($path)
    $script:imageRelations.Add("<Relationship Id=`"$relationId`" Type=`"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image`" Target=`"media/$mediaName`"/>")
    $safeCaption = Escape-Xml $caption
    $id = $script:imageIndex
    $drawing = @"
<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="5486400" cy="3429000"/><wp:effectExtent l="0" t="0" r="0" b="0"/>
<wp:docPr id="$id" name="交接脑图$id" descr="$safeCaption"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="$id" name="$mediaName"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="$relationId"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5486400" cy="3429000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
"@
    return $drawing + (New-Paragraph $caption 'Caption')
}

function Split-TableRow([string]$text) {
    $trimmed = $text.Trim().Trim('|')
    return @($trimmed.Split('|') | ForEach-Object { $_.Trim() })
}

function New-Table([string[]]$lines) {
    $rows = [System.Collections.Generic.List[object]]::new()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -eq 1 -and $lines[$i] -match '^\s*\|?\s*:?-{2,}') { continue }
        $rows.Add((Split-TableRow $lines[$i]))
    }
    if ($rows.Count -eq 0) { return '' }
    $columnCount = $rows[0].Count
    if ($columnCount -lt 1) { return '' }
    $width = [int][math]::Floor(9840 / $columnCount)
    $xml = [System.Text.StringBuilder]::new()
    [void]$xml.Append('<w:tbl><w:tblPr><w:tblW w:w="9840" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>')
    foreach ($side in @('top','left','bottom','right','insideH','insideV')) {
        [void]$xml.Append("<w:$side w:val=`"single`" w:sz=`"4`" w:color=`"D9D9D9`"/>")
    }
    [void]$xml.Append('</w:tblBorders><w:tblCellMar><w:top w:w="90" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="90" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>')
    for ($j = 0; $j -lt $columnCount; $j++) { [void]$xml.Append("<w:gridCol w:w=`"$width`"/>") }
    [void]$xml.Append('</w:tblGrid>')
    for ($i = 0; $i -lt $rows.Count; $i++) {
        if ($i -eq 0) { [void]$xml.Append('<w:tr><w:trPr><w:tblHeader w:val="true"/><w:cantSplit/></w:trPr>') }
        else { [void]$xml.Append('<w:tr><w:trPr><w:cantSplit/></w:trPr>') }
        for ($j = 0; $j -lt $columnCount; $j++) {
            $cellText = if ($j -lt $rows[$i].Count) { Clean-Inline ([string]$rows[$i][$j]) } else { '' }
            $safeText = Escape-Xml $cellText
            $fill = if ($i -eq 0) { 'DDE9F0' } elseif ($i % 2 -eq 0) { 'F5F8FA' } else { 'FFFFFF' }
            [void]$xml.Append("<w:tc><w:tcPr><w:tcW w:w=`"$width`" w:type=`"dxa`"/><w:shd w:fill=`"$fill`"/></w:tcPr><w:p><w:pPr><w:pStyle w:val=`"TableText`"/></w:pPr><w:r><w:t xml:space=`"preserve`">$safeText</w:t></w:r></w:p></w:tc>")
        }
        [void]$xml.Append('</w:tr>')
    }
    [void]$xml.Append('</w:tbl>')
    return $xml.ToString()
}

$insideCode = $false
$firstTitle = $true
for ($i = 0; $i -lt $markdown.Count; $i++) {
    $line = $markdown[$i]
    if ($line -match '^```') { $insideCode = -not $insideCode; continue }
    if ($insideCode) {
        $isFirstCodeLine = ($i -gt 0 -and $markdown[$i - 1] -match '^```')
        [void]$body.Append((New-CodeParagraph $line $isFirstCodeLine))
        $paragraphCount++
        continue
    }
    if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^---\s*$') { continue }
    if ($line -match '^\|') {
        $tableLines = [System.Collections.Generic.List[string]]::new()
        while ($i -lt $markdown.Count -and $markdown[$i] -match '^\|') {
            $tableLines.Add($markdown[$i]); $i++
        }
        $i--
        [void]$body.Append((New-Table $tableLines.ToArray()))
        $tableCount++
        continue
    }
    if ($line -match '^!\[([^\]]+)\]\(([^)]+)\)') {
        $caption = $Matches[1]
        $relative = $Matches[2].Replace('/', [IO.Path]::DirectorySeparatorChar)
        $imagePath = Join-Path $PSScriptRoot $relative
        if (-not (Test-Path -LiteralPath $imagePath)) { throw "Missing image: $imagePath" }
        [void]$body.Append((New-ImageParagraph $imagePath $caption))
        continue
    }
    if ($line -match '^(#{1,4})\s+(.+)$') {
        $level = $Matches[1].Length
        $headingText = $Matches[2]
        if ($level -eq 1 -and $firstTitle) {
            $style = 'Title'; $firstTitle = $false
        } else {
            $style = 'Heading' + [math]::Min(($level + 1), 4)
        }
        [void]$body.Append((New-Paragraph $headingText $style))
        $paragraphCount++
        continue
    }
    if ($line -match '^>\s?(.*)$') {
        [void]$body.Append((New-Paragraph $Matches[1] 'Meta'))
        $paragraphCount++
        continue
    }
    if ($line -match '^\s*-\s+(.+)$') {
        $item = $Matches[1]
        $item = $item.Replace('[ ]', '□').Replace('[x]', '☑')
        [void]$body.Append((New-Paragraph ('• ' + $item) 'List' 300))
        $paragraphCount++
        continue
    }
    if ($line -match '^\s*\d+[.、]\s+(.+)$') {
        [void]$body.Append((New-Paragraph $line.Trim() 'List' 300))
        $paragraphCount++
        continue
    }
    [void]$body.Append((New-Paragraph $line.Trim() 'Normal'))
    $paragraphCount++
}

$stylesXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/><w:lang w:val="zh-CN"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="135" w:line="295" w:lineRule="auto"/></w:pPr><w:rPr><w:color w:val="243746"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="290"/></w:pPr><w:rPr><w:b/><w:sz w:val="42"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="300" w:after="155"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="31"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="230" w:after="105"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="175" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="23"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Meta"><w:name w:val="Meta"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="70"/></w:pPr><w:rPr><w:sz w:val="18"/><w:color w:val="617583"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="List"><w:name w:val="List"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="90"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="20"/><w:ind w:left="220"/><w:shd w:fill="F2F5F7"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="Microsoft YaHei"/><w:sz w:val="17"/><w:color w:val="3A4851"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="250" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:before="35" w:after="175"/></w:pPr><w:rPr><w:sz w:val="18"/><w:color w:val="607789"/></w:rPr></w:style>
</w:styles>
'@

$documentXml = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><w:body>
$($body.ToString())
<w:sectPr><w:footerReference w:type="default" r:id="rId5"/><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="900" w:right="1080" w:bottom="900" w:left="1080" w:header="450" w:footer="450" w:gutter="0"/></w:sectPr>
</w:body></w:document>
"@

$relationships = '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
    ($imageRelations -join '') +
    '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
$documentRels = "<?xml version=`"1.0`" encoding=`"UTF-8`" standalone=`"yes`"?><Relationships xmlns=`"http://schemas.openxmlformats.org/package/2006/relationships`">$relationships</Relationships>"
$footerXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:color w:val="71818A"/><w:sz w:val="17"/></w:rPr><w:t>曲境项目交接文档 · </w:t></w:r><w:fldSimple w:instr="PAGE"/></w:p></w:ftr>'
$contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'
$packageRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'

function Add-TextEntry($archive, [string]$name, [string]$content) {
    $entry = $archive.CreateEntry($name, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
    try { $writer.Write($content) } finally { $writer.Dispose() }
}

$fileStream = [System.IO.File]::Open($outputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$archive = [System.IO.Compression.ZipArchive]::new($fileStream, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Add-TextEntry $archive '[Content_Types].xml' $contentTypes
    Add-TextEntry $archive '_rels/.rels' $packageRels
    Add-TextEntry $archive 'word/document.xml' $documentXml
    Add-TextEntry $archive 'word/styles.xml' $stylesXml
    Add-TextEntry $archive 'word/_rels/document.xml.rels' $documentRels
    Add-TextEntry $archive 'word/footer1.xml' $footerXml
    for ($i = 0; $i -lt $imagePaths.Count; $i++) {
        $entry = $archive.CreateEntry(('word/media/image' + ($i + 1) + '.png'), [System.IO.Compression.CompressionLevel]::Optimal)
        $read = [System.IO.File]::OpenRead($imagePaths[$i])
        $write = $entry.Open()
        try { $read.CopyTo($write) } finally { $read.Dispose(); $write.Dispose() }
    }
} finally {
    $archive.Dispose(); $fileStream.Dispose()
}

Write-Output "WORD=$outputPath"
Write-Output "PARAGRAPHS=$paragraphCount TABLES=$tableCount IMAGES=$imageIndex"
