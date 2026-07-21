param(
    [Parameter(Mandatory = $true)]
    [string]$PackageUrl,
    [string[]]$PackageFallbackUrls = @(),
    [Parameter(Mandatory = $true)]
    [string]$PackageSha256,
    [Parameter(Mandatory = $true)]
    [string]$PackageRootName,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$OutputPath = "",
    [string]$MakeNsisPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ArtifactsDir = Join-Path $Root "artifacts\installer"
$ReleaseDir = Join-Path $Root "release"
$IconPath = Join-Path $Root "openclaw_new_launcher\src-tauri\icons\icon.ico"
$InstallerAssetDir = Join-Path $Root "openclaw_new_launcher\src-tauri\installer"
$SidebarBitmapPath = Join-Path $InstallerAssetDir "nsis-sidebar.bmp"
$HeaderBitmapPath = Join-Path $InstallerAssetDir "nsis-header.bmp"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ReleaseDir "LOOM-Setup-v$Version-nsis.exe"
}

if ($PackageRootName -notmatch [regex]::Escape($Version)) {
    throw "Version must match PackageRootName. Version=$Version PackageRootName=$PackageRootName"
}

function Get-MakeNsis {
    param([string]$ExplicitPath)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $candidates += $ExplicitPath
    }
    if (-not [string]::IsNullOrWhiteSpace($env:MAKENSIS_PATH)) {
        $candidates += $env:MAKENSIS_PATH
    }

    $command = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += $command.Source
    }

    $candidates += @(
        (Join-Path $env:LOCALAPPDATA "tauri\NSIS\Bin\makensis.exe"),
        (Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"),
        (Join-Path $env:LOCALAPPDATA "electron-builder\Cache\nsis\nsis-3.0.4.1\Bin\makensis.exe"),
        (Join-Path $env:LOCALAPPDATA "electron-builder\Cache\nsis\nsis-3.0.4.1\makensis.exe")
    )

    foreach ($candidate in $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Cannot find makensis.exe. Install NSIS or build Tauri once so the bundled NSIS is cached."
}

function Escape-NsisString {
    param([string]$Value)
    return (($Value -replace '\$', '$$') -replace '"', '$\"')
}

function Get-NumericFileVersion {
    param([string]$InputVersion)

    $parts = @($InputVersion -split '[^\d]+' | Where-Object { $_ -ne "" } | Select-Object -First 4)
    while ($parts.Count -lt 4) {
        $parts += "0"
    }
    return ($parts | ForEach-Object { [int]$_ }) -join "."
}

function New-DownloadAttempts {
    param([string[]]$Urls)

    $lines = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $Urls.Count; $i += 1) {
        $index = $i + 1
        $total = $Urls.Count
        $url = Escape-NsisString $Urls[$i]
        $lines.Add("  DetailPrint `"Downloading LOOM package: channel $index/$total`"")
        $lines.Add("  Delete `"`$TEMP\loom-online.zip`"")
        $lines.Add("  nsExec::ExecToLog '`"`$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -File `"`$PLUGINSDIR\loom-nsis-helper.ps1`" -Mode Download -Url `"$url`" -OutFile `"`$TEMP\loom-online.zip`"'")
        $lines.Add("  Pop `$0")
        $lines.Add("  `${If} `$0 == 0")
        $lines.Add("    Goto download_done")
        $lines.Add("  `${EndIf}")
        $lines.Add("")
    }
    $lines.Add("  MessageBox MB_ICONSTOP|MB_OK `"Failed to download LOOM. Check the network or try again later. Exit code: `$0`" /SD IDOK")
    $lines.Add("  Abort")
    $lines.Add("download_done:")
    return ($lines -join [Environment]::NewLine)
}

New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
    throw "Installer icon is missing: $IconPath"
}
if (-not (Test-Path -LiteralPath $SidebarBitmapPath -PathType Leaf)) {
    throw "Installer sidebar image is missing: $SidebarBitmapPath"
}
if (-not (Test-Path -LiteralPath $HeaderBitmapPath -PathType Leaf)) {
    throw "Installer header image is missing: $HeaderBitmapPath"
}

$makeNsis = Get-MakeNsis -ExplicitPath $MakeNsisPath
$sourcePath = Join-Path $ArtifactsDir "LOOMOnlineInstaller.nsi"
$helperPath = Join-Path $ArtifactsDir "loom-nsis-helper.ps1"
$urls = @($PackageUrl) + @($PackageFallbackUrls) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
if ($urls.Count -lt 1) {
    throw "At least one package URL is required."
}

$downloadAttempts = New-DownloadAttempts -Urls $urls
$safeOutputPath = Escape-NsisString ([System.IO.Path]::GetFullPath($OutputPath))
$safeIconPath = Escape-NsisString ([System.IO.Path]::GetFullPath($IconPath))
$safeSidebarBitmapPath = Escape-NsisString ([System.IO.Path]::GetFullPath($SidebarBitmapPath))
$safeHeaderBitmapPath = Escape-NsisString ([System.IO.Path]::GetFullPath($HeaderBitmapPath))
$safeHelperPath = Escape-NsisString ([System.IO.Path]::GetFullPath($helperPath))
$safePackageRootName = Escape-NsisString $PackageRootName
$safeVersion = Escape-NsisString $Version
$safeSha = Escape-NsisString $PackageSha256.ToUpperInvariant()
$fileVersion = Get-NumericFileVersion -InputVersion $Version

$helper = @'
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Download", "Verify", "Expand", "Copy")]
    [string]$Mode,
    [string]$Url = "",
    [string]$OutFile = "",
    [string]$File = "",
    [string]$Sha256 = "",
    [string]$Destination = "",
    [string]$Source = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

try {
    switch ($Mode) {
        "Download" {
            if ([string]::IsNullOrWhiteSpace($Url) -or [string]::IsNullOrWhiteSpace($OutFile)) {
                throw "Download requires Url and OutFile."
            }
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $client = [System.Net.WebClient]::new()
            try {
                $client.DownloadFile($Url, $OutFile)
            }
            finally {
                $client.Dispose()
            }
        }
        "Verify" {
            if ([string]::IsNullOrWhiteSpace($File) -or [string]::IsNullOrWhiteSpace($Sha256)) {
                throw "Verify requires File and Sha256."
            }
            $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash.ToUpperInvariant()
            if ($actual -ne $Sha256.ToUpperInvariant()) {
                Write-Error "SHA256 mismatch. Actual=$actual"
                exit 21
            }
        }
        "Expand" {
            if ([string]::IsNullOrWhiteSpace($File) -or [string]::IsNullOrWhiteSpace($Destination)) {
                throw "Expand requires File and Destination."
            }
            Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
            Expand-Archive -LiteralPath $File -DestinationPath $Destination -Force
        }
        "Copy" {
            if ([string]::IsNullOrWhiteSpace($Source) -or [string]::IsNullOrWhiteSpace($Destination)) {
                throw "Copy requires Source and Destination."
            }
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
            Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
        }
    }
}
catch {
    Write-Error $_
    exit 1
}
'@

$template = @'
Unicode true
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "LOOM"
Caption "LOOM __VERSION__ Setup"
OutFile "__OUTPUT_PATH__"
InstallDir "$LOCALAPPDATA\LOOM"
InstallDirRegKey HKCU "Software\LOOM" "InstallDir"
RequestExecutionLevel user
BrandingText "LOOM __VERSION__"
ShowInstDetails show
ShowUninstDetails show

Icon "__ICON_PATH__"
UninstallIcon "__ICON_PATH__"

VIProductVersion "__FILE_VERSION__"
VIAddVersionKey /LANG=1033 "ProductName" "LOOM"
VIAddVersionKey /LANG=1033 "CompanyName" "LOOM"
VIAddVersionKey /LANG=1033 "FileDescription" "LOOM Online Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "__VERSION__"
VIAddVersionKey /LANG=1033 "ProductVersion" "__VERSION__"

!define MUI_ABORTWARNING
!define MUI_ICON "__ICON_PATH__"
!define MUI_UNICON "__ICON_PATH__"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "__HEADER_BITMAP_PATH__"
!define MUI_HEADERIMAGE_RIGHT
!define MUI_WELCOMEFINISHPAGE_BITMAP "__SIDEBAR_BITMAP_PATH__"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "__SIDEBAR_BITMAP_PATH__"
!define MUI_WELCOMEPAGE_TITLE "Install LOOM"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs LOOM and downloads the verified online package. Codex, Claude Code, opencode, OpenClaw, Hermes, and APKClaw are installed later inside LOOM when you choose them."
!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose the LOOM install folder. Short paths such as D:\LOOM or C:\LOOM are recommended."
!define MUI_FINISHPAGE_RUN "$INSTDIR\LOOM.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch LOOM"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Var StageDir

Section "LOOM" SecMain
  SetOutPath "$INSTDIR"
  CreateDirectory "$INSTDIR"
  InitPluginsDir
  File "/oname=$PLUGINSDIR\loom-nsis-helper.ps1" "__HELPER_PATH__"

__DOWNLOAD_ATTEMPTS__

  DetailPrint "Verifying package checksum..."
  nsExec::ExecToLog '"$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\loom-nsis-helper.ps1" -Mode Verify -File "$TEMP\loom-online.zip" -Sha256 "__PACKAGE_SHA256__"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Package verification failed. Download the installer again or try another network. Exit code: $0" /SD IDOK
    Abort
  ${EndIf}

  DetailPrint "Extracting LOOM..."
  StrCpy $StageDir "$TEMP\loom-stage"
  RMDir /r "$StageDir"
  CreateDirectory "$StageDir"
  nsExec::ExecToLog '"$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\loom-nsis-helper.ps1" -Mode Expand -File "$TEMP\loom-online.zip" -Destination "$TEMP\loom-stage"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Failed to extract LOOM. Check disk space and try again. Exit code: $0" /SD IDOK
    Abort
  ${EndIf}

  IfFileExists "$StageDir\__PACKAGE_ROOT_NAME__\LOOM.exe" 0 install_bad_package
  DetailPrint "Installing to $INSTDIR..."
  nsExec::ExecToLog '"$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\loom-nsis-helper.ps1" -Mode Copy -Source "$TEMP\loom-stage\__PACKAGE_ROOT_NAME__" -Destination "$INSTDIR"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Failed to write files. Choose a short writable folder such as D:\LOOM or C:\LOOM. Exit code: $0" /SD IDOK
    Abort
  ${EndIf}
  Goto install_files_done

install_bad_package:
  MessageBox MB_ICONSTOP|MB_OK "The LOOM package is incomplete: LOOM.exe was not found." /SD IDOK
  Abort

install_files_done:
  WriteUninstaller "$INSTDIR\Uninstall LOOM.exe"
  WriteRegStr HKCU "Software\LOOM" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "DisplayName" "LOOM"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "DisplayVersion" "__VERSION__"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "Publisher" "LOOM"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "DisplayIcon" "$INSTDIR\LOOM.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "UninstallString" '"$INSTDIR\Uninstall LOOM.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\LOOM"
  CreateShortCut "$SMPROGRAMS\LOOM\LOOM.lnk" "$INSTDIR\LOOM.exe" "" "$INSTDIR\LOOM.exe"
  CreateShortCut "$DESKTOP\LOOM.lnk" "$INSTDIR\LOOM.exe" "" "$INSTDIR\LOOM.exe"

  RMDir /r "$StageDir"
  Delete "$TEMP\loom-online.zip"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\LOOM.lnk"
  Delete "$SMPROGRAMS\LOOM\LOOM.lnk"
  RMDir "$SMPROGRAMS\LOOM"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LOOM"
  DeleteRegKey HKCU "Software\LOOM"
  RMDir /r "$INSTDIR"
SectionEnd
'@

$source = $template.
    Replace("__OUTPUT_PATH__", $safeOutputPath).
    Replace("__ICON_PATH__", $safeIconPath).
    Replace("__SIDEBAR_BITMAP_PATH__", $safeSidebarBitmapPath).
    Replace("__HEADER_BITMAP_PATH__", $safeHeaderBitmapPath).
    Replace("__HELPER_PATH__", $safeHelperPath).
    Replace("__VERSION__", $safeVersion).
    Replace("__FILE_VERSION__", $fileVersion).
    Replace("__PACKAGE_ROOT_NAME__", $safePackageRootName).
    Replace("__PACKAGE_SHA256__", $safeSha).
    Replace("__DOWNLOAD_ATTEMPTS__", $downloadAttempts)

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($helperPath, $helper, $utf8NoBom)
[System.IO.File]::WriteAllText($sourcePath, $source, $utf8NoBom)

Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
& $makeNsis "/INPUTCHARSET" "UTF8" $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "makensis failed with exit code $LASTEXITCODE"
}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath
"$($hash.Hash)  $(Split-Path -Leaf $OutputPath)" |
    Set-Content -LiteralPath "$OutputPath.sha256.txt" -Encoding ASCII

Write-Host "NSIS installer: $OutputPath"
Write-Host "SHA256: $($hash.Hash)"
