param(
  [string]$LogoSource = ""
)

$ErrorActionPreference = "Stop"

$launcherRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$brandTitle = [string][char]0x9E93 + [char]0x9E23
if ([string]::IsNullOrWhiteSpace($LogoSource)) {
  $LogoSource = Join-Path $launcherRoot "src\assets\luming-logo-full.png"
}
$LogoSource = [IO.Path]::GetFullPath($LogoSource)
$expectedLogoSha256 = "29BABD1FBB5A068E7222AD239FF237F68874B64E768625DB1A64761BFE8E9624"

if (-not (Test-Path -LiteralPath $LogoSource -PathType Leaf)) {
  throw "Full LOOM logo source is missing: $LogoSource"
}
$actualLogoSha256 = (Get-FileHash -LiteralPath $LogoSource -Algorithm SHA256).Hash
if ($actualLogoSha256 -ne $expectedLogoSha256) {
  throw "Unexpected full LOOM logo source hash: $actualLogoSha256"
}

Push-Location $launcherRoot
try {
  & npx tauri icon $LogoSource
  if ($LASTEXITCODE -ne 0) {
    throw "Tauri icon generation failed with exit code $LASTEXITCODE"
  }
} finally {
  Pop-Location
}

Add-Type -AssemblyName System.Drawing

function New-RoundedRectanglePath {
  param(
    [Drawing.RectangleF]$Bounds,
    [float]$Radius
  )

  $diameter = $Radius * 2
  $path = [Drawing.Drawing2D.GraphicsPath]::new()
  $path.AddArc($Bounds.X, $Bounds.Y, $diameter, $diameter, 180, 90)
  $path.AddArc($Bounds.Right - $diameter, $Bounds.Y, $diameter, $diameter, 270, 90)
  $path.AddArc($Bounds.Right - $diameter, $Bounds.Bottom - $diameter, $diameter, $diameter, 0, 90)
  $path.AddArc($Bounds.X, $Bounds.Bottom - $diameter, $diameter, $diameter, 90, 90)
  $path.CloseFigure()
  return $path
}

function Set-InstallerLogo {
  param(
    [string]$TargetPath,
    [Drawing.RectangleF]$ClearBounds,
    [Drawing.RectangleF]$LogoBounds,
    [Drawing.Point]$BackgroundSample,
    [float]$CornerRadius = 0
  )

  $source = [Drawing.Bitmap]::new($LogoSource)
  $target = [Drawing.Bitmap]::new($TargetPath)
  $output = [Drawing.Bitmap]::new($target.Width, $target.Height, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $graphics = [Drawing.Graphics]::FromImage($output)
  $clipPath = $null
  $backgroundBrush = $null
  $temporary = "$TargetPath.$PID.tmp.bmp"
  try {
    $graphics.DrawImageUnscaled($target, 0, 0)
    $graphics.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::HighQuality

    $backgroundColor = $target.GetPixel($BackgroundSample.X, $BackgroundSample.Y)
    $backgroundBrush = [Drawing.SolidBrush]::new($backgroundColor)
    if ($CornerRadius -gt 0) {
      $clipPath = New-RoundedRectanglePath -Bounds $ClearBounds -Radius $CornerRadius
      $graphics.FillPath($backgroundBrush, $clipPath)
      $graphics.SetClip($clipPath)
    } else {
      $graphics.FillRectangle($backgroundBrush, $ClearBounds)
      $graphics.SetClip($ClearBounds)
    }

    $source.MakeTransparent($source.GetPixel(0, 0))
    $graphics.DrawImage($source, $LogoBounds)
    $graphics.ResetClip()

    $output.Save($temporary, [Drawing.Imaging.ImageFormat]::Bmp)
  } finally {
    if ($backgroundBrush) { $backgroundBrush.Dispose() }
    if ($clipPath) { $clipPath.Dispose() }
    $graphics.Dispose()
    $output.Dispose()
    $target.Dispose()
    $source.Dispose()
  }
  [IO.File]::Copy($temporary, $TargetPath, $true)
  [IO.File]::Delete($temporary)
}

function Set-InstallerText {
  param(
    [string]$TargetPath,
    [Drawing.Rectangle]$ClearBounds,
    [ValidateSet("Horizontal", "Vertical")]
    [string]$BackgroundFill,
    [string]$Title,
    [Drawing.RectangleF]$TitleBounds,
    [float]$TitlePixels,
    [string]$Subtitle = "",
    [Drawing.RectangleF]$SubtitleBounds = [Drawing.RectangleF]::Empty,
    [float]$SubtitlePixels = 0
  )

  $target = [Drawing.Bitmap]::new($TargetPath)
  $output = [Drawing.Bitmap]::new($target.Width, $target.Height, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $copyGraphics = [Drawing.Graphics]::FromImage($output)
  $copyGraphics.DrawImageUnscaled($target, 0, 0)
  $copyGraphics.Dispose()

  for ($y = $ClearBounds.Top; $y -lt $ClearBounds.Bottom; $y += 1) {
    for ($x = $ClearBounds.Left; $x -lt $ClearBounds.Right; $x += 1) {
      if ($BackgroundFill -eq "Vertical") {
        $startColor = $target.GetPixel($x, [Math]::Max(0, $ClearBounds.Top - 1))
        $endColor = $target.GetPixel($x, [Math]::Min($target.Height - 1, $ClearBounds.Bottom))
        $ratio = ($y - $ClearBounds.Top + 1) / ($ClearBounds.Height + 1)
      } else {
        $startColor = $target.GetPixel([Math]::Max(0, $ClearBounds.Left - 1), $y)
        $endColor = $target.GetPixel([Math]::Min($target.Width - 1, $ClearBounds.Right), $y)
        $ratio = ($x - $ClearBounds.Left + 1) / ($ClearBounds.Width + 1)
      }
      $red = [int][Math]::Round($startColor.R + (($endColor.R - $startColor.R) * $ratio))
      $green = [int][Math]::Round($startColor.G + (($endColor.G - $startColor.G) * $ratio))
      $blue = [int][Math]::Round($startColor.B + (($endColor.B - $startColor.B) * $ratio))
      $output.SetPixel($x, $y, [Drawing.Color]::FromArgb($red, $green, $blue))
    }
  }

  $graphics = [Drawing.Graphics]::FromImage($output)
  $titleFont = $null
  $subtitleFont = $null
  $titleBrush = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(245, 250, 250))
  $subtitleBrush = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(135, 211, 203))
  $format = [Drawing.StringFormat]::new()
  $temporary = "$TargetPath.$PID.tmp.bmp"
  try {
    $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $format.Alignment = [Drawing.StringAlignment]::Center
    $format.LineAlignment = [Drawing.StringAlignment]::Center
    $format.Trimming = [Drawing.StringTrimming]::None
    $titleFont = [Drawing.Font]::new("Microsoft YaHei UI", $TitlePixels, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
    $graphics.DrawString($Title, $titleFont, $titleBrush, $TitleBounds, $format)

    if (-not [string]::IsNullOrWhiteSpace($Subtitle) -and $SubtitlePixels -gt 0) {
      $subtitleFont = [Drawing.Font]::new("Microsoft YaHei UI", $SubtitlePixels, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Pixel)
      $graphics.DrawString($Subtitle, $subtitleFont, $subtitleBrush, $SubtitleBounds, $format)
    }

    $output.Save($temporary, [Drawing.Imaging.ImageFormat]::Bmp)
  } finally {
    if ($subtitleFont) { $subtitleFont.Dispose() }
    if ($titleFont) { $titleFont.Dispose() }
    $format.Dispose()
    $subtitleBrush.Dispose()
    $titleBrush.Dispose()
    $graphics.Dispose()
    $output.Dispose()
    $target.Dispose()
  }
  [IO.File]::Copy($temporary, $TargetPath, $true)
  [IO.File]::Delete($temporary)
}

Set-InstallerLogo `
  -TargetPath (Join-Path $launcherRoot "src-tauri\installer\nsis-header.bmp") `
  -ClearBounds ([Drawing.RectangleF]::new(0, 7, 43, 43)) `
  -LogoBounds ([Drawing.RectangleF]::new(0, 7, 43, 43)) `
  -BackgroundSample ([Drawing.Point]::new(1, 28))

Set-InstallerLogo `
  -TargetPath (Join-Path $launcherRoot "src-tauri\installer\nsis-sidebar.bmp") `
  -ClearBounds ([Drawing.RectangleF]::new(42, 89, 80, 80)) `
  -LogoBounds ([Drawing.RectangleF]::new(42, 89, 80, 80)) `
  -BackgroundSample ([Drawing.Point]::new(50, 100)) `
  -CornerRadius 13

Set-InstallerText `
  -TargetPath (Join-Path $launcherRoot "src-tauri\installer\nsis-header.bmp") `
  -ClearBounds ([Drawing.Rectangle]::new(44, 0, 106, 57)) `
  -BackgroundFill Horizontal `
  -Title $brandTitle `
  -TitleBounds ([Drawing.RectangleF]::new(48, 11, 96, 32)) `
  -TitlePixels 20

Set-InstallerText `
  -TargetPath (Join-Path $launcherRoot "src-tauri\installer\nsis-sidebar.bmp") `
  -ClearBounds ([Drawing.Rectangle]::new(25, 174, 114, 56)) `
  -BackgroundFill Vertical `
  -Title $brandTitle `
  -TitleBounds ([Drawing.RectangleF]::new(25, 183, 114, 32)) `
  -TitlePixels 23

Write-Host "Updated default LOOM icon and installer brand assets from $LogoSource"
