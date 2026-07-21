; Per-user desktop installer for OpenClaw, Modern UI 2 + Simplified Chinese.
; Lays the thin-portable payload (OpenClaw.exe + OpenClawFiles skeleton) into
; %LOCALAPPDATA%\OpenClaw (writable, no admin), makes shortcuts, and registers
; an uninstaller. First run downloads the runtime layers next to it; re-running
; the setup overwrites the launcher but keeps the layers (the self-update path).
;
; Defines from build-installer.ps1 via makensis /D:
;   PAYLOAD_DIR, OUTFILE, APPVERSION, ART_DIR, ICON

Unicode true
!include "MUI2.nsh"

; ${APP} = install IDENTITY (folder, registry key, uninstall key) — MUST stay
; "OpenClaw" so updates land in-place over the legacy OpenClaw-branded installs
; instead of spawning a duplicate. ${BRAND} = DISPLAY brand (window title,
; shortcuts, wizard text) — "LumiClaw".
!ifndef APP
  !define APP "OpenClaw"
!endif
!ifndef BRAND
  !define BRAND "LumiClaw"
!endif
!ifndef PAYLOAD_DIR
  !define PAYLOAD_DIR "payload"
!endif
!ifndef OUTFILE
  !define OUTFILE "OpenClaw-Setup.exe"
!endif
!ifndef APPVERSION
  !define APPVERSION "2.0.6"
!endif
!ifndef ART_DIR
  !define ART_DIR "assets"
!endif

!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

Name "${BRAND} ${APPVERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\${APP}"
InstallDirRegKey HKCU "Software\${APP}" "InstallDir"
SetCompressor /SOLID lzma
BrandingText "${BRAND} ${APPVERSION}"

; --- Modern UI theming ---
!ifdef ICON
  !define MUI_ICON "${ICON}"
  !define MUI_UNICON "${ICON}"
!endif
!define MUI_WELCOMEFINISHPAGE_BITMAP "${ART_DIR}\welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${ART_DIR}\welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${ART_DIR}\header.bmp"
!define MUI_HEADERIMAGE_RIGHT
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${BRAND}"
!define MUI_WELCOMEPAGE_TEXT "即将把 ${BRAND} ${APPVERSION} 安装到你的电脑（无需管理员权限）。$\r$\n$\r$\n首次启动会自动下载运行组件，请保持联网。$\r$\n$\r$\n点击「下一步」继续。"
!define MUI_DIRECTORYPAGE_TEXT_TOP "选择安装位置（默认安装到当前用户目录，免管理员）。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\OpenClaw.exe"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 ${BRAND}"
!define MUI_FINISHPAGE_TEXT "${BRAND} 已安装完成。首次启动会下载运行组件，请保持联网。"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; Stop the launcher AND its child processes (the bundled node gateway + python
; bridge run from $INSTDIR). If they keep running they lock OpenClawFiles, which
; is why an uninstall used to leave that folder behind.
; Use nsExec::Exec (CreateProcess with CREATE_NO_WINDOW) instead of ExecWait so
; the taskkill / PowerShell helpers run hidden — no black console flashes during
; install / self-update / uninstall. Pop the exit code to keep the stack balanced.
!macro KillInstallProcesses
  nsExec::Exec 'taskkill /IM OpenClaw.exe /F'
  Pop $0
  nsExec::Exec `powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith('$INSTDIR', [System.StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
  Pop $0
  Sleep 800
!macroend

Section "Install"
  ; Single-instance guard: a double-click in Explorer can fire two installer
  ; processes; without a mutex both show a wizard ("opens twice"). 183 =
  ; ERROR_ALREADY_EXISTS — second instance exits cleanly.
  System::Call 'kernel32::CreateMutexW(i 0, i 1, w "OpenClaw_Setup_Mutex") i .r0 ?e'
  Pop $1
  IntCmp $1 183 0 mutex_ok mutex_ok
    MessageBox MB_OK|MB_ICONEXCLAMATION "安装程序已在运行，请勿重复启动。"
    Quit
  mutex_ok:

  ; Stop running launcher + children so files can be overwritten (self-update).
  !insertmacro KillInstallProcesses
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD_DIR}\*.*"

  ; Remove legacy OpenClaw-branded shortcuts left by pre-rebrand installs.
  Delete "$DESKTOP\OpenClaw.lnk"
  RMDir /r "$SMPROGRAMS\OpenClaw"

  CreateShortCut "$DESKTOP\${BRAND}.lnk" "$INSTDIR\OpenClaw.exe" "" "$INSTDIR\OpenClaw.exe" 0
  CreateDirectory "$SMPROGRAMS\${BRAND}"
  CreateShortCut "$SMPROGRAMS\${BRAND}\${BRAND}.lnk" "$INSTDIR\OpenClaw.exe" "" "$INSTDIR\OpenClaw.exe" 0
  CreateShortCut "$SMPROGRAMS\${BRAND}\Uninstall ${BRAND}.lnk" "$INSTDIR\Uninstall.exe"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${BRAND}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APPVERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\OpenClaw.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${BRAND}"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  !insertmacro KillInstallProcesses
  Delete "$DESKTOP\${BRAND}.lnk"
  Delete "$DESKTOP\OpenClaw.lnk"
  RMDir /r "$SMPROGRAMS\${BRAND}"
  RMDir /r "$SMPROGRAMS\OpenClaw"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP}"
SectionEnd
