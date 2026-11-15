Add-Type -AssemblyName System.Drawing

$size = 1024
$bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)

function New-RoundedPath([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $r * 2
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    return $p
}

# Backplate
$plate = New-RoundedPath 40 40 944 944 200
$brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    (New-Object System.Drawing.Point(40, 40)),
    (New-Object System.Drawing.Point(984, 984)),
    [System.Drawing.Color]::FromArgb(255, 20, 27, 40),
    [System.Drawing.Color]::FromArgb(255, 11, 14, 20))
$g.FillPath($brush, $plate)

# Frame
$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(90, 75, 123, 236), 10)
$g.DrawPath($pen, $plate)

# "Take apart" motif: a 2x2 block set where one cell is lifted away
$cell = 224
$gap = 60
$originX = 512 - $cell - ($gap / 2)
$originY = 512 - $cell - ($gap / 2)

$solid = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 123, 224, 192))
$blue = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 75, 123, 236))

$g.FillPath($solid, (New-RoundedPath $originX $originY $cell $cell 48))
$g.FillPath($blue, (New-RoundedPath ($originX + $cell + $gap) $originY $cell $cell 48))
$g.FillPath($blue, (New-RoundedPath $originX ($originY + $cell + $gap) $cell $cell 48))

# Detached, brighter cell - the piece being read on its own
$liftedX = $originX + $cell + $gap + 28
$liftedY = $originY + $cell + $gap - 28
$lighter = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 236, 244, 255))
$g.FillPath($lighter, (New-RoundedPath $liftedX $liftedY $cell $cell 48))

$g.Dispose()
$out = Join-Path $PSScriptRoot "icon-source.png"
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Host "wrote $out"
