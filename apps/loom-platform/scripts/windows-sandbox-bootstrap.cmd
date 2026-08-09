@echo off
setlocal

>C:\LumingEvidence\logon-command-launcher-started.txt echo Windows Sandbox logon launcher started.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\LumingHarness\windows-sandbox-bootstrap.ps1 -ConfigPath C:\LumingEvidence\sandbox-bootstrap-config.json >C:\LumingEvidence\logon-command-console.txt 2>&1
set "LOOM_SANDBOX_EXIT_CODE=%ERRORLEVEL%"
>C:\LumingEvidence\logon-command-exit-code.txt echo %LOOM_SANDBOX_EXIT_CODE%
exit /b %LOOM_SANDBOX_EXIT_CODE%
