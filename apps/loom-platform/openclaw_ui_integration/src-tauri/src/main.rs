// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[cfg(windows)]
fn wide_null(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn reg_key_has_webview2_version(key: &str) -> bool {
    use std::os::windows::process::CommandExt;

    std::process::Command::new("reg.exe")
        .args(["query", key, "/v", "pv"])
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .map(|output| {
            output.status.success()
                && String::from_utf8_lossy(&output.stdout)
                    .to_ascii_lowercase()
                    .contains("reg_sz")
        })
        .unwrap_or(false)
}

#[cfg(windows)]
fn webview2_runtime_present() -> bool {
    let registry_keys = [
        r"HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    ];
    if registry_keys.iter().any(|key| reg_key_has_webview2_version(key)) {
        return true;
    }

    let mut roots = Vec::new();
    for name in ["ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"] {
        if let Some(value) = std::env::var_os(name) {
            roots.push(std::path::PathBuf::from(value));
        }
    }

    roots.iter().any(|root| {
        let app_dir = root.join("Microsoft").join("EdgeWebView").join("Application");
        std::fs::read_dir(app_dir)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .any(|entry| entry.path().join("msedgewebview2.exe").exists())
    })
}

#[cfg(windows)]
fn find_bundled_webview2_installer() -> Option<std::path::PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.to_path_buf()));
    let current_dir = std::env::current_dir().ok();

    let mut candidates = Vec::new();
    for root in [exe_dir, current_dir].into_iter().flatten() {
        candidates.push(root.join("redist").join("MicrosoftEdgeWebView2RuntimeInstallerX64.exe"));
        candidates.push(
            root.join("OpenClawFiles")
                .join("redist")
                .join("MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
        );
        candidates.push(
            root.join("_up_")
                .join("redist")
                .join("MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
        );
    }

    candidates.into_iter().find(|path| path.exists())
}

#[cfg(windows)]
fn launch_webview2_installer(path: &std::path::Path) {
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let verb = wide_null("runas");
    let file = wide_null(&path.to_string_lossy());
    let params = wide_null("/silent /install");
    unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file.as_ptr(),
            params.as_ptr(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        );
    }
}

#[cfg(windows)]
fn ensure_webview2_before_tauri() {
    if webview2_runtime_present() {
        return;
    }

    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDYES, MB_ICONERROR, MB_OK, MB_SETFOREGROUND, MB_YESNO,
    };

    let title = wide_null("OpenClaw 启动环境缺失");
    if let Some(installer) = find_bundled_webview2_installer() {
        let message = wide_null(
            "当前系统缺少 Microsoft Edge WebView2 Runtime，启动器界面可能白屏或无法打开。\n\n已在离线包中找到 WebView2 安装器。是否现在安装？安装完成后请重新打开 OpenClaw。",
        );
        let result = unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                message.as_ptr(),
                title.as_ptr(),
                MB_ICONERROR | MB_YESNO | MB_SETFOREGROUND,
            )
        };
        if result == IDYES {
            launch_webview2_installer(&installer);
        }
    } else {
        let message = wide_null(
            "当前系统缺少 Microsoft Edge WebView2 Runtime，启动器界面可能白屏或无法打开。\n\n请安装 Microsoft Edge WebView2 Evergreen Runtime 后重新打开 OpenClaw。离线交付包应包含 redist\\MicrosoftEdgeWebView2RuntimeInstallerX64.exe。",
        );
        unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                message.as_ptr(),
                title.as_ptr(),
                MB_ICONERROR | MB_OK | MB_SETFOREGROUND,
            );
        }
    }

    std::process::exit(0);
}

fn main() {
    #[cfg(windows)]
    ensure_webview2_before_tauri();

    app_lib::run();
}
