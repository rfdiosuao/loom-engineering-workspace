; The detached update handoff owns process shutdown, backup, restore and
; rollback. Installer hooks stay deliberately narrow so a normal uninstall or
; manual reinstall cannot inherit stale update state from another operation.

!macro NSIS_HOOK_PREINSTALL
  ; A user may run the new setup directly instead of entering through the
  ; detached in-app handoff. Stop only executables owned by this install root
  ; before replacing Python or Node; never kill global image names.
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "/oname=loom-stop-owned-install-processes.ps1" "${__FILEDIR__}\..\..\..\..\installer\stop-owned-install-processes.ps1"
  SetOutPath "$INSTDIR"
  StrCpy $1 "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" 0 loom_owned_process_shell_ready
  StrCpy $1 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  loom_owned_process_shell_ready:
  ExecWait '"$1" -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "$PLUGINSDIR\loom-stop-owned-install-processes.ps1" -InstallRoot "$INSTDIR"' $0
  StrCmp $0 "0" loom_owned_process_cleanup_ok
  MessageBox MB_ICONSTOP|MB_OK "LOOM background processes are still using installation files. Close LOOM and retry. Diagnostic log: $TEMP\LOOM-installer-process-cleanup.log"
  Abort
  loom_owned_process_cleanup_ok:

  ; Protected releases ship bytecode beside a small loader surface. Remove
  ; managed code first so source files from an older release cannot shadow it.
  RMDir /r "$INSTDIR\_up_\python"
  RMDir /r "$INSTDIR\_up_\scripts"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\scripts"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; No-op: the handoff performs a nonce-scoped external backup before setup.
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; No-op: the handoff restores data and verifies the new process health.
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Recovery is completed by the detached update handoff after setup exits.
!macroend
