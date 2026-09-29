$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$imageDir = Join-Path $PSScriptRoot 'images'
New-Item -ItemType Directory -Path $imageDir -Force | Out-Null

function New-Color([string]$hex) {
    return [System.Drawing.ColorTranslator]::FromHtml($hex)
}

function New-RoundedPath([float]$x, [float]$y, [float]$width, [float]$height, [float]$radius) {
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $diameter = 2 * $radius
    $path.AddArc($x, $y, $diameter, $diameter, 180, 90)
    $path.AddArc(($x + $width - $diameter), $y, $diameter, $diameter, 270, 90)
    $path.AddArc(($x + $width - $diameter), ($y + $height - $diameter), $diameter, $diameter, 0, 90)
    $path.AddArc($x, ($y + $height - $diameter), $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function Draw-Card($graphics, $card, $x, $y, $accent) {
    $path = New-RoundedPath $x $y 465 245 28
    $fill = [System.Drawing.SolidBrush]::new((New-Color '#FFFFFF'))
    $edge = [System.Drawing.Pen]::new($accent, 3)
    $graphics.FillPath($fill, $path)
    $graphics.DrawPath($edge, $path)
    $stripe = [System.Drawing.SolidBrush]::new($accent)
    $graphics.FillRectangle($stripe, $x + 27, $y + 32, 9, 42)

    $titleFont = [System.Drawing.Font]::new('Microsoft YaHei', 25, [System.Drawing.FontStyle]::Bold)
    $bodyFont = [System.Drawing.Font]::new('Microsoft YaHei', 18.5)
    $titleBrush = [System.Drawing.SolidBrush]::new((New-Color '#153348'))
    $bodyBrush = [System.Drawing.SolidBrush]::new((New-Color '#425C6E'))
    $graphics.DrawString($card.Title, $titleFont, $titleBrush, [System.Drawing.RectangleF]::new($x + 53, $y + 25, 388, 53))
    $i = 0
    foreach ($line in $card.Lines) {
        $graphics.DrawString(('• ' + $line), $bodyFont, $bodyBrush, [System.Drawing.RectangleF]::new($x + 31, $y + 89 + 45 * $i, 410, 45))
        $i++
    }
    $path.Dispose(); $fill.Dispose(); $edge.Dispose(); $stripe.Dispose()
    $titleFont.Dispose(); $bodyFont.Dispose(); $titleBrush.Dispose(); $bodyBrush.Dispose()
}

function Write-Mindmap($fileName, $heading, $root, $footer, $cards) {
    $bitmap = [System.Drawing.Bitmap]::new(2000, 1250)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear((New-Color '#F5F8FB'))
    $headingFont = [System.Drawing.Font]::new('Microsoft YaHei', 31, [System.Drawing.FontStyle]::Bold)
    $footFont = [System.Drawing.Font]::new('Microsoft YaHei', 16)
    $headingBrush = [System.Drawing.SolidBrush]::new((New-Color '#19394D'))
    $footBrush = [System.Drawing.SolidBrush]::new((New-Color '#5E7281'))
    $graphics.DrawString($heading, $headingFont, $headingBrush, [System.Drawing.PointF]::new(80, 29))
    $graphics.DrawString($footer, $footFont, $footBrush, [System.Drawing.PointF]::new(80, 1200))

    $positions = @(
        @{ X = 80; Y = 125; Side = 'L'; Color = '#4D88A4' },
        @{ X = 80; Y = 495; Side = 'L'; Color = '#5B8F80' },
        @{ X = 80; Y = 865; Side = 'L'; Color = '#AA806B' },
        @{ X = 1455; Y = 125; Side = 'R'; Color = '#7978A5' },
        @{ X = 1455; Y = 495; Side = 'R'; Color = '#4E8293' },
        @{ X = 1455; Y = 865; Side = 'R'; Color = '#A97888' }
    )
    for ($i = 0; $i -lt 6; $i++) {
        $position = $positions[$i]
        $accent = New-Color $position.Color
        $pen = [System.Drawing.Pen]::new($accent, 5)
        if ($position.Side -eq 'L') {
            $graphics.DrawBezier($pen, 795, 622, 680, 622, 666, ($position.Y + 123), 545, ($position.Y + 123))
        } else {
            $graphics.DrawBezier($pen, 1205, 622, 1320, 622, 1328, ($position.Y + 123), 1455, ($position.Y + 123))
        }
        $pen.Dispose()
    }

    $rootPath = New-RoundedPath 795 545 410 154 35
    $rootFill = [System.Drawing.SolidBrush]::new((New-Color '#17394D'))
    $graphics.FillPath($rootFill, $rootPath)
    $rootFont = [System.Drawing.Font]::new('Microsoft YaHei', 32, [System.Drawing.FontStyle]::Bold)
    $rootBrush = [System.Drawing.SolidBrush]::new((New-Color '#FFFFFF'))
    $center = [System.Drawing.StringFormat]::new()
    $center.Alignment = [System.Drawing.StringAlignment]::Center
    $center.LineAlignment = [System.Drawing.StringAlignment]::Center
    $graphics.DrawString($root, $rootFont, $rootBrush, [System.Drawing.RectangleF]::new(815, 558, 370, 126), $center)

    for ($i = 0; $i -lt 6; $i++) {
        $position = $positions[$i]
        Draw-Card $graphics $cards[$i] $position.X $position.Y (New-Color $position.Color)
    }
    $outputPath = Join-Path $imageDir $fileName
    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $center.Dispose(); $rootBrush.Dispose(); $rootFont.Dispose(); $rootFill.Dispose(); $rootPath.Dispose()
    $headingFont.Dispose(); $footFont.Dispose(); $headingBrush.Dispose(); $footBrush.Dispose()
    $graphics.Dispose(); $bitmap.Dispose()
    Write-Output $outputPath
}

Write-Mindmap '交接脑图-产品与系统.png' '图一  产品与系统关系' "曲境`n私人音乐地图" '实线关系表示当前架构；QQ 音乐写入为接口预留，尚未接入。' @(
    @{ Title = '本地输入'; Lines = @('普通可读音频与元数据', '封面、标题与可用歌词', '源文件保持只读') },
    @{ Title = '声音分析'; Lines = @('BPM、响度、调性、ACT/BRI', 'MusiCNN 听感画像', 'YAMNet 主要声源提示') },
    @{ Title = '文字分析'; Lines = @('标题线索与歌词证据', '主题群岛和语言判断', '缺证据保留待确认') },
    @{ Title = '四张地图'; Lines = @('听感、主题、流派、语言', '点选、区域选择、缩放', '同曲联动和来源解释') },
    @{ Title = '统一候选'; Lines = @('跨地图收集与去重', '试听、排除和顺序', '旧版有独立审查页面') },
    @{ Title = '安全输出'; Lines = @('M3U8 与本地复制', '预览、确认与撤销', 'QQ 写歌单接口待授权') }
)

Write-Mindmap '交接脑图-数据工程.png' '图二  数据工程与证据链' "主题与流派`n证据工程" '主题、流派、人声状态分别记录来源与版本；不能把模型候选写成事实。' @(
    @{ Title = '人声三态'; Lines = @('有人声／纯音乐／不确定', '多片段采样与冲突处理', '人工修正优先') },
    @{ Title = '歌词获取'; Lines = @('内嵌、同名、指定目录', '非唯一匹配要求确认', '记录合法来源与缺失状态') },
    @{ Title = '主题 Map'; Lines = @('纯音乐优先标题', '有人声采用标题＋歌词', '不确定时保留证据等级') },
    @{ Title = '流派证据'; Lines = @('原始标签与库级质检', '目录／平台 ID 消歧', '音频模型只给候选') },
    @{ Title = '数据结构'; Lines = @('候选及来源、置信度', '分析与模型版本号', '音频／文字缓存独立') },
    @{ Title = '验收样本'; Lines = @('150—300 首人声标注', '真歌词和错误匹配样本', '细分流派混淆矩阵') }
)

Write-Mindmap '交接脑图-交互与提交.png' '图三  交互改版与交付路径' "下一版`n找歌到保存" '旧版功能与下一版目标需分开说明；当前 Release 是源码包，不是安装程序。' @(
    @{ Title = '当前交接版'; Lines = @('找歌 → 审查 → 保存', '可手动改选星座', 'Streamlit 本地启动') },
    @{ Title = '目标交互'; Lines = @('找歌时直接试听与移除', '取消独立审查页面', '保存前保留复制预览') },
    @{ Title = '自动星座'; Lines = @('只显示自动匹配结果', '保留图层开关与依据', '不推断人格或运势') },
    @{ Title = 'LLM 助手'; Lines = @('一句话生成条件草案', '用户修改后再应用', '按次同意、可离线降级') },
    @{ Title = '本地封装'; Lines = @('先做 Windows 安装包', '干净机器启动与卸载', '中文路径及缓存回归') },
    @{ Title = '云与平台'; Lines = @('确定同步方式再买服务器', '保留目录／音频／写入端口', 'QQ 权限逐项确认') }
)
