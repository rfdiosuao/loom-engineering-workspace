use std::io::BufRead;
use std::io::Read;
use std::io::Write;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::process::Command;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::time::Duration;
use tauri::path::BaseDirectory;
use tauri::{Manager, WindowEvent};

mod bootstrap;
mod license;

static BRIDGE_PORT: AtomicU16 = AtomicU16::new(0);
static BRIDGE_TOKEN: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);
static BRIDGE_CHILD_PID: std::sync::Mutex<Option<u32>> = std::sync::Mutex::new(None);
static BRIDGE_START_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
static LAST_BRIDGE_STARTUP_ERROR: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);
static SHUTDOWN_REQUESTED: AtomicBool = AtomicBool::new(false);
static UPDATE_HANDOFF_STARTED: AtomicBool = AtomicBool::new(false);
static ACKNOWLEDGED_UPDATE_HEALTH_MARKER: std::sync::Mutex<Option<std::path::PathBuf>> =
    std::sync::Mutex::new(None);

struct UpdateHandoffStartGuard {
    reset_on_drop: bool,
}

impl Drop for UpdateHandoffStartGuard {
    fn drop(&mut self) {
        if self.reset_on_drop {
            UPDATE_HANDOFF_STARTED.store(false, Ordering::SeqCst);
        }
    }
}

#[cfg(windows)]
struct UpdateHandoffSystemMutex {
    _handle: std::os::windows::io::OwnedHandle,
}

#[cfg(windows)]
fn acquire_update_handoff_system_mutex() -> Result<UpdateHandoffSystemMutex, String> {
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::FromRawHandle;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    let name = std::ffi::OsStr::new("Local\\LOOM.Update.Handoff")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let handle = unsafe { CreateMutexW(std::ptr::null(), 1, name.as_ptr()) };
    if handle.is_null() {
        return Err(format!("unable to create LOOM update mutex: {}", unsafe {
            GetLastError()
        }));
    }
    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        unsafe {
            CloseHandle(handle);
        }
        return Err("another LOOM update handoff is already running".to_string());
    }
    Ok(UpdateHandoffSystemMutex {
        _handle: unsafe { std::os::windows::io::OwnedHandle::from_raw_handle(handle) },
    })
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const PRIMARY_PAYLOAD_DIR: &str = "LOOMFiles";
const LEGACY_PAYLOAD_DIR: &str = "OpenClawFiles";
const PORTABLE_PAYLOAD_DIRS: [&str; 2] = [PRIMARY_PAYLOAD_DIR, LEGACY_PAYLOAD_DIR];
const LAUNCHER_EXE_NAME: &str = "LOOM.exe";

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticSummary {
    status: String,
    ok: usize,
    warnings: usize,
    failed: usize,
    total: usize,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticCheck {
    id: String,
    label: String,
    status: String,
    message: String,
    detail: String,
    repairable: bool,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticReport {
    base_path: String,
    service_running: bool,
    service_pid: Option<u32>,
    checks: Vec<DiagnosticCheck>,
    summary: DiagnosticSummary,
    repair_available: bool,
}

fn set_bridge_startup_error(message: impl Into<String>) {
    if let Ok(mut guard) = LAST_BRIDGE_STARTUP_ERROR.lock() {
        *guard = Some(message.into());
    }
}

fn clear_bridge_startup_error() {
    if let Ok(mut guard) = LAST_BRIDGE_STARTUP_ERROR.lock() {
        *guard = None;
    }
}

fn bridge_token() -> Option<String> {
    BRIDGE_TOKEN.lock().ok().and_then(|guard| guard.clone())
}

fn clear_bridge_state_for_pid(pid: u32) {
    let mut should_clear = false;
    if let Ok(mut guard) = BRIDGE_CHILD_PID.lock() {
        if guard.map(|known_pid| known_pid == pid).unwrap_or(false) {
            *guard = None;
            should_clear = true;
        }
    }
    if should_clear {
        BRIDGE_PORT.store(0, Ordering::Relaxed);
        if let Ok(mut guard) = BRIDGE_TOKEN.lock() {
            *guard = None;
        }
    }
}

fn kill_process_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        command.args(["/F", "/T", "/PID", &pid.to_string()]);
        command.creation_flags(CREATE_NO_WINDOW);
        let _ = command.output();
    }

    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .output();
    }
}

fn terminate_bridge_process_tree() {
    let pid = BRIDGE_CHILD_PID.lock().ok().and_then(|guard| *guard);
    if let Some(pid) = pid {
        kill_process_tree(pid);
        clear_bridge_state_for_pid(pid);
    }
}

async fn post_bridge_shutdown(path: &str) {
    let port = BRIDGE_PORT.load(Ordering::Relaxed);
    if port == 0 {
        return;
    }

    let url = format!("http://127.0.0.1:{}/{}", port, path.trim_start_matches('/'));
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
    {
        Ok(client) => client,
        Err(_) => return,
    };

    let mut request = client.post(url);
    if let Some(token) = bridge_token() {
        request = request.header("X-Bridge-Token", token);
    }
    let _ = request.send().await;
}

async fn shutdown_backend() {
    post_bridge_shutdown("/api/process/stop").await;
    post_bridge_shutdown("/api/desktop-agent/stop").await;
    terminate_bridge_process_tree();
}

fn summarize_checks(checks: &[DiagnosticCheck]) -> DiagnosticSummary {
    let failed = checks.iter().filter(|item| item.status == "fail").count();
    let warnings = checks.iter().filter(|item| item.status == "warn").count();
    let ok = checks.iter().filter(|item| item.status == "ok").count();
    DiagnosticSummary {
        status: if failed > 0 {
            "fail"
        } else if warnings > 0 {
            "warn"
        } else {
            "ok"
        }
        .to_string(),
        ok,
        warnings,
        failed,
        total: checks.len(),
    }
}

fn path_check(id: &str, label: &str, path: &std::path::Path, required: bool) -> DiagnosticCheck {
    let exists = path.exists();
    DiagnosticCheck {
        id: id.to_string(),
        label: label.to_string(),
        status: if exists {
            "ok"
        } else if required {
            "fail"
        } else {
            "warn"
        }
        .to_string(),
        message: if exists {
            "已找到"
        } else if required {
            "缺失，启动器无法继续启动 Bridge"
        } else {
            "未找到，可能影响便携包完整性"
        }
        .to_string(),
        detail: path.to_string_lossy().to_string(),
        repairable: false,
    }
}

fn protected_feature(path: &str) -> Option<&'static str> {
    const RULES: [(&str, &str); 5] = [
        ("api/matrix/acquisition/feishu", "acquisition.feishu"),
        ("api/matrix/acquisition/templates", "templates.cloud"),
        ("api/matrix/acquisition", "acquisition.workbench"),
        ("api/matrix", "matrix.devices"),
        ("api/phone", "matrix.devices"),
    ];
    const PUBLIC_SAFETY_PATHS: [&str; 4] = [
        "api/matrix/cancel",
        "api/matrix/emergency-stop",
        "api/phone/daemon/stop",
        "api/phone/events/stop",
    ];

    let normalized = path
        .split('?')
        .next()
        .unwrap_or("")
        .trim_start_matches('/')
        .trim_end_matches('/');
    if PUBLIC_SAFETY_PATHS.contains(&normalized) {
        return None;
    }
    for (prefix, feature) in RULES {
        if normalized == prefix
            || normalized
                .strip_prefix(prefix)
                .map(|rest| rest.starts_with('/'))
                .unwrap_or(false)
        {
            return Some(feature);
        }
    }
    None
}

fn protected_feature_for_request(path: &str, body: Option<&str>) -> Option<&'static str> {
    if let Some(feature) = protected_feature(path) {
        return Some(feature);
    }
    let normalized = path
        .split('?')
        .next()
        .unwrap_or("")
        .trim_matches('/');
    if normalized != "api/cli/run" {
        return None;
    }
    let command = serde_json::from_str::<serde_json::Value>(body?)
        .ok()?
        .get("command")?
        .as_str()?
        .trim()
        .to_ascii_lowercase();
    if command.starts_with("phone:")
        || command.starts_with("loom:phone:")
        || command.starts_with("openclaw:phone:")
    {
        return Some("matrix.devices");
    }
    None
}

#[cfg(test)]
mod commercial_feature_path_tests {
    use super::protected_feature_for_request;

    #[test]
    fn maps_commercial_routes_with_longest_prefix_precedence() {
        let cases = [
            ("/api/matrix/acquisition/feishu/status", Some("acquisition.feishu")),
            ("/api/matrix/acquisition/templates/upload", Some("templates.cloud")),
            ("/api/matrix/acquisition/agent/result", Some("acquisition.workbench")),
            ("/api/matrix/status", Some("matrix.devices")),
            ("/api/phone/task", Some("matrix.devices")),
        ];

        for (path, expected) in cases {
            assert_eq!(protected_feature_for_request(path, None), expected, "path={path}");
        }
    }

    #[test]
    fn leaves_activation_diagnostics_and_namespace_lookalikes_public() {
        for path in [
            "/api/license/current",
            "/api/license/client-config",
            "/api/license/activate",
            "/api/system/info",
            "/api/diagnostics/export",
            "/api/publishing/draft",
            "/api/process/start",
            "/api/image/generate/submit",
            "/api/video/generate",
            "/api/matrix/cancel",
            "/api/matrix/emergency-stop",
            "/api/phone/daemon/stop",
            "/api/phone/events/stop",
            "/api/matrixevil/status",
            "/api/phonebook/task",
        ] {
            assert_eq!(protected_feature_for_request(path, None), None, "path={path}");
        }
        assert_eq!(
            protected_feature_for_request("/api/matrix/acquisitionevil", None),
            Some("matrix.devices")
        );
    }

    #[test]
    fn gates_all_phone_commands_on_the_shared_cli_endpoint() {
        let publish = r#"{"command":"phone:publish","confirmed":true}"#;
        let read = r#"{"command":"phone:agent","args":["history"]}"#;
        let desktop = r#"{"command":"desktop:agent","args":["status"]}"#;

        assert_eq!(
            protected_feature_for_request("/api/cli/run", Some(publish)),
            Some("matrix.devices")
        );
        assert_eq!(
            protected_feature_for_request("/api/cli/run", Some(read)),
            Some("matrix.devices")
        );
        assert_eq!(
            protected_feature_for_request("/api/cli/run", Some(desktop)),
            None
        );
        assert_eq!(
            protected_feature_for_request("/api/cli/run", Some("not-json")),
            None
        );
    }
}

fn portable_base_dir() -> Result<std::path::PathBuf, String> {
    let install_root = bootstrap::install_root()?;
    for payload_dir in PORTABLE_PAYLOAD_DIRS {
        let path = install_root.join(payload_dir);
        if path.exists() {
            return Ok(path);
        }
    }
    Ok(install_root)
}

fn media_asset_directories(root: &std::path::Path) -> Vec<std::path::PathBuf> {
    let roots = std::iter::once(root.to_path_buf())
        .chain(PORTABLE_PAYLOAD_DIRS.map(|payload_dir| root.join(payload_dir)));
    let mut directories = Vec::with_capacity(6);
    for root in roots {
        directories.push(root.join("data").join("generated-images"));
        directories.push(root.join("data").join("videos"));
    }
    directories
}

fn configure_media_asset_scope(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let root = bootstrap::install_root()
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::Other, error))?;
    let scope = app.asset_protocol_scope();
    for directory in media_asset_directories(&root) {
        scope.allow_directory(&directory, false)?;
    }
    Ok(())
}

#[cfg(test)]
mod media_asset_scope_tests {
    use super::media_asset_directories;
    use std::path::PathBuf;

    #[test]
    fn limits_preview_scope_to_generated_media_directories() {
        let root = PathBuf::from(r"C:\LOOM");

        assert_eq!(
            media_asset_directories(&root),
            vec![
                root.join("data").join("generated-images"),
                root.join("data").join("videos"),
                root.join("LOOMFiles").join("data").join("generated-images"),
                root.join("LOOMFiles").join("data").join("videos"),
                root.join("OpenClawFiles")
                    .join("data")
                    .join("generated-images"),
                root.join("OpenClawFiles").join("data").join("videos"),
            ]
        );
    }
}

fn payload_bridge_candidates(base_dir: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut candidates = vec![
        base_dir.join("python").join("bridge.py"),
        base_dir.join("_up_").join("python").join("bridge.py"),
    ];
    for payload_dir in PORTABLE_PAYLOAD_DIRS {
        candidates.push(
            base_dir
                .join(payload_dir)
                .join("_up_")
                .join("python")
                .join("bridge.py"),
        );
    }
    candidates
}

fn python_binary_names() -> &'static [&'static str] {
    if cfg!(windows) {
        &["python.exe", "python"]
    } else {
        &["python3", "python"]
    }
}

fn bridge_python_exe(py_path: &std::path::Path) -> std::path::PathBuf {
    if let Some(bridge_dir) = py_path.parent() {
        for binary_name in python_binary_names() {
            let local_python = bridge_dir.join(binary_name);
            if local_python.exists() {
                return local_python;
            }
        }

        if let Some(resource_dir) = bridge_dir.parent() {
            for binary_name in python_binary_names() {
                let runtime_python = resource_dir.join("python-runtime").join(binary_name);
                if runtime_python.exists() {
                    return runtime_python;
                }
            }
        }
    }

    if let Ok(base_dir) = portable_base_dir() {
        for runtime_dir in [
            base_dir.join("_up_").join("python-runtime"),
            base_dir.join("python-runtime"),
        ] {
            for binary_name in python_binary_names() {
                let runtime_python = runtime_dir.join(binary_name);
                if runtime_python.exists() {
                    return runtime_python;
                }
            }
        }
    }

    if cfg!(windows) {
        std::path::PathBuf::from("python")
    } else {
        std::path::PathBuf::from("python3")
    }
}

fn is_packaged_bridge(py_path: &std::path::Path) -> bool {
    let mut saw_up = false;
    let mut saw_resources = false;
    for component in py_path.components() {
        let text = component.as_os_str().to_string_lossy();
        if saw_up && text.eq_ignore_ascii_case("python") {
            return true;
        }
        if saw_resources && text.eq_ignore_ascii_case("python") {
            return true;
        }
        saw_up = text.eq_ignore_ascii_case("_up_");
        saw_resources = text.eq_ignore_ascii_case("resources");
    }
    false
}

fn is_bare_command(path: &std::path::Path) -> bool {
    path.components().count() == 1
}

fn spawn_bridge(py_path: &std::path::Path) -> Result<String, String> {
    if !py_path.exists() {
        let message = format!("bridge.py 未找到: {}", py_path.display());
        set_bridge_startup_error(message.clone());
        return Err(message);
    }

    let python_exe = bridge_python_exe(py_path);
    if is_packaged_bridge(py_path) && (is_bare_command(&python_exe) || !python_exe.exists()) {
        let message = format!(
            "Python runtime missing: packaged Bridge requires bundled python-runtime. Expected {}. Please install a build that includes python-runtime.",
            python_exe.display()
        );
        set_bridge_startup_error(message.clone());
        return Err(message);
    }
    let mut child_cmd = Command::new(&python_exe);
    child_cmd.arg(py_path);
    child_cmd.env("PYTHONUTF8", "1");
    child_cmd.env("PYTHONIOENCODING", "utf-8");
    child_cmd.env("LOOM_APP_VERSION", env!("CARGO_PKG_VERSION"));
    if let Ok(app_exe) = std::env::current_exe() {
        child_cmd.env("LOOM_APP_EXE", app_exe);
    }
    // Cache compiled bytecode in a writable, stable location to speed up cold
    // starts. Previously bytecode writing was disabled entirely, which forced
    // Python to recompile every module (fastapi/pydantic/uvicorn/...) on every
    // launch. Routing the cache to a temp subdir keeps the delivered package
    // clean and still works when the portable package sits on read-only media.
    let pycache_dir = std::env::temp_dir().join("openclaw-pycache");
    let _ = std::fs::create_dir_all(&pycache_dir);
    child_cmd.env("PYTHONPYCACHEPREFIX", &pycache_dir);
    child_cmd.stdout(std::process::Stdio::piped());
    child_cmd.stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    child_cmd.creation_flags(CREATE_NO_WINDOW);
    let mut child = child_cmd.spawn().map_err(|e| {
        let message = format!(
            "启动 Python bridge 失败: python={} bridge={} error={}",
            python_exe.display(),
            py_path.display(),
            e
        );
        set_bridge_startup_error(message.clone());
        message
    })?;
    let child_pid = child.id();
    if let Ok(mut guard) = BRIDGE_CHILD_PID.lock() {
        *guard = Some(child_pid);
    }

    let mut child_stderr = child.stderr.take();
    let stdout = child.stdout.take().ok_or("无法获取 bridge 输出")?;
    let mut reader = std::io::BufReader::new(stdout);
    let mut line = String::new();

    loop {
        reader.read_line(&mut line).map_err(|e| {
            let message = format!("读取 bridge 输出失败: {}", e);
            set_bridge_startup_error(message.clone());
            message
        })?;
        if let Some(port_str) = line.trim().strip_prefix("BRIDGE_PORT=") {
            if let Ok(port) = port_str.parse::<u16>() {
                BRIDGE_PORT.store(port, Ordering::Relaxed);
                break;
            }
        }
        if line.is_empty() {
            let mut stderr_text = String::new();
            if let Some(mut stderr) = child_stderr.take() {
                let _ = stderr.read_to_string(&mut stderr_text);
            }
            let status = child.wait().ok();
            let message = format!(
                "无法获取 bridge 端口。python={} bridge={} exit={:?} stderr={}",
                python_exe.display(),
                py_path.display(),
                status.and_then(|s| s.code()),
                stderr_text.trim()
            );
            set_bridge_startup_error(message.clone());
            clear_bridge_state_for_pid(child_pid);
            return Err(message);
        }
        line.clear();
    }

    line.clear();
    loop {
        reader.read_line(&mut line).map_err(|e| {
            let message = format!("读取 bridge token 失败: {}", e);
            set_bridge_startup_error(message.clone());
            message
        })?;
        if let Some(token) = line.trim().strip_prefix("BRIDGE_TOKEN=") {
            if let Ok(mut guard) = BRIDGE_TOKEN.lock() {
                *guard = Some(token.to_string());
            }
            break;
        }
        if line.is_empty() {
            break;
        }
        line.clear();
    }

    // The bridge prints BRIDGE_PORT/BRIDGE_TOKEN before uvicorn actually binds
    // the socket, so a very early frontend request could hit connection-refused
    // ("刚打开就报错"). Wait until the port is accepting connections before
    // reporting success. A process that prints metadata but never binds is not
    // a healthy Bridge and must not complete an application update handshake.
    let ready_port = BRIDGE_PORT.load(Ordering::Relaxed);
    let mut bridge_ready = false;
    if ready_port != 0 {
        let addr = std::net::SocketAddr::from(([127, 0, 0, 1], ready_port));
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        while std::time::Instant::now() < deadline {
            if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                bridge_ready = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
    if !bridge_ready {
        let message = format!("bridge did not accept connections on port {ready_port}");
        let _ = child.kill();
        let _ = child.wait();
        clear_bridge_state_for_pid(child_pid);
        set_bridge_startup_error(message.clone());
        return Err(message);
    }

    std::thread::spawn(move || {
        let stderr = child_stderr;
        if let Some(stderr) = stderr {
            let mut reader = std::io::BufReader::new(stderr);
            let mut err_line = String::new();
            while reader.read_line(&mut err_line).ok() > Some(0) {
                eprintln!("[bridge stderr] {}", err_line.trim());
                set_bridge_startup_error(err_line.trim().to_string());
                err_line.clear();
            }
        }
        let _ = child.wait();
        clear_bridge_state_for_pid(child_pid);
        invalidate_update_health_marker();
    });

    Ok(format!(
        "Bridge started on port {}",
        BRIDGE_PORT.load(Ordering::Relaxed)
    ))
}

#[tauri::command]
fn get_bridge_port() -> u16 {
    BRIDGE_PORT.load(Ordering::Relaxed)
}

#[tauri::command]
fn get_portable_base_path() -> Result<String, String> {
    portable_base_dir().map(|path| path.to_string_lossy().to_string())
}

#[tauri::command]
fn bridge_startup_report() -> Result<DiagnosticReport, String> {
    let base_dir = portable_base_dir()?;
    let mut checks: Vec<DiagnosticCheck> = Vec::new();
    let exe_path = std::env::current_exe().unwrap_or_else(|_| base_dir.join(LAUNCHER_EXE_NAME));
    checks.push(path_check("tauri_exe", "启动器 EXE", &exe_path, true));
    checks.push(path_check("portable_base", "运行根目录", &base_dir, true));

    let candidates = payload_bridge_candidates(&base_dir);
    let bridge_path = candidates.iter().find(|path| path.exists()).cloned();
    checks.push(DiagnosticCheck {
        id: "bridge_py_outer".to_string(),
        label: "Bridge 脚本外层检查".to_string(),
        status: if bridge_path.is_some() { "ok" } else { "fail" }.to_string(),
        message: if bridge_path.is_some() {
            "已找到 bridge.py"
        } else {
            "未找到 bridge.py，Python Bridge 无法启动"
        }
        .to_string(),
        detail: candidates
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect::<Vec<_>>()
            .join("；"),
        repairable: false,
    });

    if let Some(ref py_path) = bridge_path {
        let python_exe = bridge_python_exe(py_path);
        let python_is_path = python_exe.exists();
        checks.push(DiagnosticCheck {
            id: "bridge_python_outer".to_string(),
            label: "Bridge Python 外层检查".to_string(),
            status: if python_is_path { "ok" } else { "fail" }.to_string(),
            message: if python_is_path {
                "已找到随包 Python"
            } else {
                "未找到随包 Python，离线包不能依赖系统 Python"
            }
            .to_string(),
            detail: python_exe.to_string_lossy().to_string(),
            repairable: false,
        });
    }

    let last_error = LAST_BRIDGE_STARTUP_ERROR
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .unwrap_or_else(|| "暂无 Rust/Tauri 外层 Bridge 启动错误。若页面显示启动失败，请点击重新诊断以触发一次外层捕获。".to_string());
    let bridge_running = BRIDGE_PORT.load(Ordering::Relaxed) > 0;
    checks.push(DiagnosticCheck {
        id: "bridge_startup_error".to_string(),
        label: "Bridge 启动失败快照".to_string(),
        status: if bridge_running {
            "ok"
        } else if last_error.starts_with("暂无") {
            "warn"
        } else {
            "fail"
        }
        .to_string(),
        message: if bridge_running {
            "Bridge 已启动"
        } else {
            "Bridge 未启动，下面是启动器外层捕获到的最近错误"
        }
        .to_string(),
        detail: last_error,
        repairable: false,
    });

    let summary = summarize_checks(&checks);
    Ok(DiagnosticReport {
        base_path: base_dir.to_string_lossy().to_string(),
        service_running: false,
        service_pid: None,
        checks,
        summary,
        repair_available: false,
    })
}

#[tauri::command]
fn verify_license() -> Result<license::LicenseStatus, String> {
    let base_dir = portable_base_dir()?;
    Ok(license::check_license(&base_dir))
}

#[tauri::command]
async fn start_bridge(app: tauri::AppHandle) -> Result<String, String> {
    let existing_port = BRIDGE_PORT.load(Ordering::Relaxed);
    if existing_port > 0 {
        return Ok(format!("Bridge already started on port {}", existing_port));
    }

    let _guard = BRIDGE_START_LOCK
        .lock()
        .map_err(|_| "Bridge 启动锁已损坏".to_string())?;
    let existing_port = BRIDGE_PORT.load(Ordering::Relaxed);
    if existing_port > 0 {
        return Ok(format!("Bridge already started on port {}", existing_port));
    }

    // Prefer the external payload root. Mac full/online packages keep the
    // payload next to the .app so runtime layers can be downloaded without
    // mutating the signed app bundle.
    if let Ok(base_dir) = portable_base_dir() {
        for rel_path in ["_up_/python/bridge.py", "python/bridge.py"] {
            let py_path = base_dir.join(rel_path);
            if py_path.exists() {
                return spawn_bridge(&py_path);
            }
        }
    }

    // Production bundles may place resources under either `python/` or `_up_/python/`
    // depending on how paths outside src-tauri are mapped by the bundler.
    for rel_path in ["python/bridge.py", "_up_/python/bridge.py"] {
        if let Ok(resource_py_path) = app.path().resolve(rel_path, BaseDirectory::Resource) {
            if resource_py_path.exists() {
                return spawn_bridge(&resource_py_path);
            }
        }
    }

    // Release binaries run next to the bundled payload directory before installation.
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            for py_path in payload_bridge_candidates(exe_dir) {
                if py_path.exists() {
                    return spawn_bridge(py_path.as_path());
                }
            }
        }
    }

    // Fall back to project-relative path (dev mode)
    let py_path = std::env::current_dir()
        .map_err(|e| format!("获取当前目录失败: {}", e))?
        .join("python")
        .join("bridge.py");

    spawn_bridge(&py_path)
}

#[tauri::command]
async fn install_distribution_layer(app: tauri::AppHandle, layer_id: String) -> Result<(), String> {
    let layer_id = layer_id.trim().to_string();
    if layer_id.is_empty() {
        return Err("distribution layer id is empty".to_string());
    }
    let root = bootstrap::install_root()?;
    bootstrap::install_layer_by_id(app, root, layer_id).await
}

#[tauri::command]
async fn retry_distribution_setup(app: tauri::AppHandle) -> Result<String, String> {
    clear_bridge_startup_error();
    let root = bootstrap::install_root()?;
    if let Err(error) = bootstrap::ensure_layers(app.clone(), root).await {
        let message = format!("运行组件补全失败：{error}");
        set_bridge_startup_error(message.clone());
        return Err(message);
    }
    start_bridge(app).await
}

#[tauri::command]
async fn proxy_request(
    app: tauri::AppHandle,
    path: String,
    method: String,
    body: Option<String>,
) -> Result<String, String> {
    if let Some(feature) = protected_feature_for_request(&path, body.as_deref()) {
        let base_dir = portable_base_dir()?;
        license::ensure_authorized(&base_dir, Some(feature))?;
    }

    let mut port = BRIDGE_PORT.load(Ordering::Relaxed);
    if port == 0 {
        start_bridge(app).await?;
        port = BRIDGE_PORT.load(Ordering::Relaxed);
        if port == 0 {
            return Err("Bridge 未启动".to_string());
        }
    }

    let url = format!("http://127.0.0.1:{}/{}", port, path.trim_start_matches('/'));
    let client = reqwest::Client::builder()
        .no_proxy()
        .build()
        .map_err(|e| format!("bridge_client_failed: {}", e))?;

    let method = method.trim().to_ascii_uppercase();
    let mut req = client.request(
        match method.as_str() {
            "GET" => reqwest::Method::GET,
            "POST" => reqwest::Method::POST,
            "PUT" => reqwest::Method::PUT,
            "PATCH" => reqwest::Method::PATCH,
            "DELETE" => reqwest::Method::DELETE,
            _ => return Err(format!("不支持的方法: {}", method)),
        },
        &url,
    );

    if let Some(b) = body {
        req = req.body(b).header("Content-Type", "application/json");
    }

    if let Ok(guard) = BRIDGE_TOKEN.lock() {
        if let Some(ref token) = *guard {
            req = req.header("X-Bridge-Token", token.as_str());
        }
    }

    let resp = req.send().await.map_err(|e| format!("请求失败: {}", e))?;
    let status = resp.status();
    let text = resp
        .text()
        .await
        .map_err(|e| format!("读取响应失败: {}", e))?;
    if !status.is_success() {
        return Err(format!("[{}] {}", status.as_u16(), text));
    }
    Ok(text)
}

#[tauri::command]
async fn export_log(app: tauri::AppHandle, content: String) -> Result<String, String> {
    let mut base_dir = portable_base_dir().unwrap_or_else(|_| {
        std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
    });

    if cfg!(debug_assertions) {
        if let Ok(app_data) = app.path().app_data_dir() {
            base_dir = app_data;
        }
    }

    let log_dir = base_dir.join("data").join("logs");
    std::fs::create_dir_all(&log_dir).map_err(|e| format!("创建日志目录失败: {}", e))?;

    let timestamp = chrono_like_timestamp();
    let path = log_dir.join(format!("openclaw-log-{}.txt", timestamp));
    let mut file = std::fs::File::create(&path).map_err(|e| format!("创建日志文件失败: {}", e))?;
    file.write_all(content.as_bytes())
        .map_err(|e| format!("写入日志失败: {}", e))?;
    Ok(path.to_string_lossy().to_string())
}

#[tauri::command]
async fn open_path(path: String) -> Result<(), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("路径为空".to_string());
    }

    let target = std::path::PathBuf::from(trimmed);
    if !target.exists() {
        return Err(format!("路径不存在: {}", target.display()));
    }

    #[cfg(windows)]
    {
        let mut command = Command::new("explorer.exe");
        command.arg(&target);
        command.creation_flags(CREATE_NO_WINDOW);
        command
            .spawn()
            .map_err(|e| format!("打开目录失败: {}", e))?;
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("打开目录失败: {}", e))?;
        return Ok(());
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("打开目录失败: {}", e))?;
        return Ok(());
    }
}

#[tauri::command]
async fn prepare_update_install(app: tauri::AppHandle, installer_path: String) -> Result<String, String> {
    #[cfg(not(windows))]
    {
        let _ = (app, installer_path);
        return Err("LOOM automatic update is currently available on Windows only".to_string());
    }

    #[cfg(windows)]
    {
        if UPDATE_HANDOFF_STARTED
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err("LOOM update handoff is already running".to_string());
        }
        let mut handoff_guard = UpdateHandoffStartGuard {
            reset_on_drop: true,
        };
        let system_mutex = acquire_update_handoff_system_mutex()?;
        let installer = std::fs::canonicalize(installer_path.trim())
            .map_err(|e| format!("更新安装包不存在: {e}"))?;
        let local_app_data = std::env::var_os("LOCALAPPDATA")
            .map(std::path::PathBuf::from)
            .ok_or_else(|| "LOCALAPPDATA 不可用，无法创建安全更新目录".to_string())?;
        let update_state_root = local_app_data.join("LOOM-Update-Recovery");
        let cache_root = update_state_root.join("updates");
        let canonical_cache = std::fs::canonicalize(&cache_root)
            .map_err(|e| format!("更新缓存目录不可用: {e}"))?;
        if !installer.starts_with(&canonical_cache) {
            return Err("拒绝启动更新：安装包不在 LOOM 外部更新缓存中".to_string());
        }
        let filename = installer
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("");
        if !filename.starts_with("LOOM-") || !filename.ends_with("-setup.exe") {
            return Err("拒绝启动更新：安装包名称不符合正式发布规则".to_string());
        }
        let target_version = filename
            .strip_prefix("LOOM-")
            .and_then(|value| value.strip_suffix("-setup.exe"))
            .ok_or_else(|| "拒绝启动更新：无法从安装包名称读取目标版本".to_string())?;
        let version_parts = target_version.split('.').collect::<Vec<_>>();
        if version_parts.len() != 3
            || version_parts
                .iter()
                .any(|part| part.is_empty() || !part.chars().all(|character| character.is_ascii_digit()))
        {
            return Err("拒绝启动更新：目标版本格式无效".to_string());
        }
        let target_version = target_version.to_string();

        shutdown_backend().await;
        let install_root = bootstrap::install_root()?;
        let app_exe = std::env::current_exe().map_err(|e| format!("无法定位当前 LOOM: {e}"))?;
        let recovery_root = local_app_data
            .join("LOOM-Update-Recovery")
            .join("upgrade-backups")
            .join(format!(
                "{}-{}-{}",
                target_version,
                chrono_like_timestamp(),
                std::process::id()
            ));
        std::fs::create_dir_all(&recovery_root)
            .map_err(|e| format!("无法创建升级恢复目录: {e}"))?;
        let marker_path = update_state_root.join("update-pending.json");
        let script_path = recovery_root.join("update-handoff.ps1");
        let script = include_str!("../installer/update-handoff.ps1");
        std::fs::write(&script_path, script.as_bytes())
            .map_err(|e| format!("无法写入升级交接脚本: {e}"))?;

        let powershell = std::path::PathBuf::from(
            std::env::var_os("WINDIR").unwrap_or_else(|| "C:\\Windows".into()),
        )
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe");
        let mut command = Command::new(powershell);
        command.args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ]);
        command.arg(&script_path);
        command.arg("-Installer").arg(&installer);
        command.arg("-InstallRoot").arg(&install_root);
        command.arg("-AppExe").arg(&app_exe);
        command.arg("-RecoveryRoot").arg(&recovery_root);
        command.arg("-MarkerPath").arg(&marker_path);
        command.arg("-ParentPid").arg(std::process::id().to_string());
        command.arg("-Version").arg(&target_version);
        let test_mode = std::env::var("LOOM_UPDATE_TEST_MODE").ok().as_deref() == Some("1");
        if test_mode {
            command.arg("-TestMode");
        }
        command.creation_flags(CREATE_NO_WINDOW);
        command
            .spawn()
            .map_err(|e| format!("无法启动升级交接进程: {e}"))?;

        if !test_mode {
            handoff_guard.reset_on_drop = false;
            std::mem::forget(system_mutex);
            let app_handle = app.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(350));
                app_handle.exit(0);
            });
        }
        Ok(recovery_root.to_string_lossy().to_string())
    }
}

fn invalidate_update_health_marker() {
    let marker = ACKNOWLEDGED_UPDATE_HEALTH_MARKER
        .lock()
        .ok()
        .and_then(|mut guard| guard.take());
    if let Some(marker) = marker {
        let _ = std::fs::remove_file(marker);
    }
}

#[cfg(windows)]
fn acknowledge_update_health() -> Result<(), String> {
    let marker_value = std::env::var_os("LOOM_UPDATE_HEALTH_MARKER");
    let nonce_value = std::env::var("LOOM_UPDATE_HEALTH_NONCE").ok();
    let (marker_value, nonce) = match (marker_value, nonce_value) {
        (None, None) => return Ok(()),
        (Some(marker), Some(nonce)) => (marker, nonce),
        _ => return Err("incomplete update health handshake environment".to_string()),
    };
    if nonce.len() != 32 || !nonce.chars().all(|character| character.is_ascii_hexdigit()) {
        return Err("invalid update health nonce".to_string());
    }

    let marker_path = std::path::PathBuf::from(marker_value);
    if !marker_path.is_absolute()
        || marker_path
            .components()
            .any(|component| matches!(component, std::path::Component::ParentDir))
        || marker_path.file_name().and_then(|value| value.to_str())
            != Some("new-version-health.txt")
    {
        return Err("invalid update health marker path".to_string());
    }

    let marker_parent = marker_path
        .parent()
        .ok_or_else(|| "update health marker has no parent".to_string())?;
    let local_app_data = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA is unavailable for update health confirmation".to_string())?;
    let allowed_root = local_app_data
        .join("LOOM-Update-Recovery")
        .join("upgrade-backups");
    let canonical_allowed = std::fs::canonicalize(&allowed_root)
        .map_err(|error| format!("update recovery root is unavailable: {error}"))?;
    let canonical_parent = std::fs::canonicalize(marker_parent)
        .map_err(|error| format!("update health marker parent is unavailable: {error}"))?;
    if !canonical_parent.starts_with(&canonical_allowed) {
        return Err("update health marker is outside the recovery root".to_string());
    }

    let bridge_stability_deadline = std::time::Instant::now() + Duration::from_secs(1);
    while std::time::Instant::now() < bridge_stability_deadline {
        let bridge_pid = BRIDGE_CHILD_PID.lock().ok().and_then(|guard| *guard);
        let bridge_port = BRIDGE_PORT.load(Ordering::Relaxed);
        let bridge_ready = bridge_pid.is_some()
            && bridge_port > 0
            && std::net::TcpStream::connect_timeout(
                &std::net::SocketAddr::from(([127, 0, 0, 1], bridge_port)),
                Duration::from_millis(200),
            )
            .is_ok();
        if !bridge_ready {
            return Err("bridge health was not stable during update confirmation".to_string());
        }
        std::thread::sleep(Duration::from_millis(250));
    }

    let temporary_path =
        marker_parent.join(format!(".new-version-health-{}.tmp", std::process::id()));
    std::fs::write(&temporary_path, nonce.as_bytes())
        .map_err(|error| format!("failed to write update health marker: {error}"))?;
    if marker_path.exists() {
        std::fs::remove_file(&marker_path)
            .map_err(|error| format!("failed to replace update health marker: {error}"))?;
    }
    std::fs::rename(&temporary_path, &marker_path)
        .map_err(|error| format!("failed to publish update health marker: {error}"))?;
    if let Ok(mut guard) = ACKNOWLEDGED_UPDATE_HEALTH_MARKER.lock() {
        *guard = Some(marker_path);
    }
    let final_bridge_port = BRIDGE_PORT.load(Ordering::Relaxed);
    let final_bridge_ready = BRIDGE_CHILD_PID
        .lock()
        .ok()
        .and_then(|guard| *guard)
        .is_some()
        && final_bridge_port > 0
        && std::net::TcpStream::connect_timeout(
            &std::net::SocketAddr::from(([127, 0, 0, 1], final_bridge_port)),
            Duration::from_millis(200),
        )
        .is_ok();
    if !final_bridge_ready {
        invalidate_update_health_marker();
        return Err("bridge health was not stable after update confirmation".to_string());
    }
    Ok(())
}

#[cfg(not(windows))]
fn acknowledge_update_health() -> Result<(), String> {
    Ok(())
}

fn chrono_like_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let milliseconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    format!("{}", milliseconds)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            configure_media_asset_scope(app)?;
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            app.handle().plugin(tauri_plugin_shell::init())?;
            // Start bridge on app launch after online-package runtime layers
            // have been downloaded and verified.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match bootstrap::install_root() {
                    Ok(root) => {
                        if let Err(e) = bootstrap::ensure_layers(app_handle.clone(), root).await {
                            eprintln!("[Bootstrap error] {}", e);
                            set_bridge_startup_error(format!("运行时组件下载失败：{}", e));
                        }
                    }
                    Err(e) => eprintln!("[Bootstrap] install root unresolved: {}", e),
                }
                if let Err(e) = start_bridge(app_handle.clone()).await {
                    eprintln!("[Bridge startup error] {}", e);
                } else if let Err(error) = acknowledge_update_health() {
                    eprintln!("[Update health] {error}");
                    app_handle.exit(70);
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                if SHUTDOWN_REQUESTED.swap(true, Ordering::SeqCst) {
                    return;
                }

                let app_handle = window.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    shutdown_backend().await;
                    app_handle.exit(0);
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_bridge_port,
            get_portable_base_path,
            bridge_startup_report,
            verify_license,
            start_bridge,
            install_distribution_layer,
            retry_distribution_setup,
            proxy_request,
            export_log,
            open_path,
            prepare_update_install,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri");
}
