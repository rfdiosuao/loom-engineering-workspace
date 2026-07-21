# Redist

Place Microsoft Edge WebView2 Evergreen Runtime here before building offline or portable packages.

Expected file:

```text
MicrosoftEdgeWebView2RuntimeInstallerX64.exe
```

Use the workspace helper from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download-webview2-runtime.ps1
```

The portable packager copies this file into `OpenClawFiles\redist\` so a customer machine without WebView2 can install it before reopening the launcher.
