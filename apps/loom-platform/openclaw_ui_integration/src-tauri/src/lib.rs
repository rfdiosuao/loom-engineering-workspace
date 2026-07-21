use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::collections::HashMap;
use std::net::IpAddr;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::process::Command;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::OnceLock;
use std::time::Duration;
use tauri::path::BaseDirectory;
use tauri::{Manager, WindowEvent};

mod bootstrap;
mod launcher_update;
mod license;

static BRIDGE_PORT: AtomicU16 = AtomicU16::new(0);
static BRIDGE_TOKEN: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);
static BRIDGE_CHILD_PID: std::sync::Mutex<Option<u32>> = std::sync::Mutex::new(None);
static BRIDGE_START_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
static LAST_BRIDGE_STARTUP_ERROR: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);
static SHUTDOWN_REQUESTED: AtomicBool = AtomicBool::new(false);
static BRIDGE_HTTP_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
static PHONE_HTTP_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const PORTABLE_PAYLOAD_DIR: &str = "OpenClawFiles";
const DEFAULT_PHONE_PORT: u16 = 9527;

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

fn bridge_token() -> Option<String> {
    BRIDGE_TOKEN.lock().ok().and_then(|guard| guard.clone())
}

fn shared_http_client(
    cell: &'static OnceLock<reqwest::Client>,
    error_prefix: &str,
) -> Result<&'static reqwest::Client, String> {
    if let Some(client) = cell.get() {
        return Ok(client);
    }

    let client = reqwest::Client::builder()
        .no_proxy()
        .build()
        .map_err(|e| format!("{}: {}", error_prefix, e))?;
    let _ = cell.set(client);
    cell.get()
        .ok_or_else(|| format!("{}: client_unavailable", error_prefix))
}

fn clean_phone_base_url_input(value: &str) -> String {
    value
        .trim()
        .replace('：', ":")
        .replace('／', "/")
        .replace('。', ".")
        .replace('．', ".")
        .replace('｡', ".")
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>()
}

fn has_url_scheme(value: &str) -> bool {
    let Some(index) = value.find("://") else {
        return false;
    };
    let scheme = &value[..index];
    let mut chars = scheme.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    first.is_ascii_alphabetic()
        && chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '+' | '-' | '.'))
}

fn normalize_phone_base_url(value: &str) -> Result<String, String> {
    let mut text = clean_phone_base_url_input(value);
    if text.is_empty() {
        return Err("missing_base_url".to_string());
    }

    let lower = text.to_ascii_lowercase();
    if lower.starts_with("http:/") && !lower.starts_with("http://") {
        text = format!("http://{}", text[6..].trim_start_matches('/'));
    } else if lower.starts_with("https:/") && !lower.starts_with("https://") {
        text = format!("https://{}", text[7..].trim_start_matches('/'));
    }

    if text.starts_with("//") {
        text = format!("http:{text}");
    }
    if !has_url_scheme(&text) {
        text = format!("http://{text}");
    }

    let mut parsed = reqwest::Url::parse(&text).map_err(|_| "invalid_phone_base_url".to_string())?;
    match parsed.scheme() {
        "http" | "https" => {}
        _ => return Err("invalid_phone_base_url".to_string()),
    }

    let host = parsed.host_str().unwrap_or("").to_string();
    if host.is_empty() || is_malformed_ipv4_like(&host) {
        return Err("invalid_phone_base_url".to_string());
    }

    if parsed.port().is_none() && is_default_phone_port_host(&host) {
        parsed
            .set_port(Some(DEFAULT_PHONE_PORT))
            .map_err(|_| "invalid_phone_base_url".to_string())?;
    }
    let _ = parsed.set_username("");
    let _ = parsed.set_password(None);
    parsed.set_path("");
    parsed.set_query(None);
    parsed.set_fragment(None);
    Ok(parsed.to_string().trim_end_matches('/').to_string())
}

fn is_default_phone_port_host(host: &str) -> bool {
    if host.eq_ignore_ascii_case("localhost") {
        return true;
    }
    match host.parse::<IpAddr>() {
        Ok(IpAddr::V4(ip)) => ip.is_private() || ip.is_loopback(),
        Ok(IpAddr::V6(ip)) => ip.is_loopback(),
        Err(_) => false,
    }
}

fn is_malformed_ipv4_like(host: &str) -> bool {
    let clean = host.trim_matches(|ch| ch == '[' || ch == ']').to_ascii_lowercase();
    if !clean
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '-'))
    {
        return false;
    }
    let parts: Vec<&str> = clean.split('.').collect();
    let only_digits_and_dots = clean.chars().all(|ch| ch.is_ascii_digit() || ch == '.');
    if only_digits_and_dots {
        return parts.len() != 4 || parts.iter().any(|part| part.is_empty());
    }
    if parts.len() != 4 {
        return false;
    }
    parts
        .iter()
        .filter(|part| part.chars().any(|ch| ch.is_ascii_digit()))
        .count()
        >= 3
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
        status: if failed > 0 { "fail" } else if warnings > 0 { "warn" } else { "ok" }.to_string(),
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
        status: if exists { "ok" } else if required { "fail" } else { "warn" }.to_string(),
        message: if exists { "已找到" } else if required { "缺失，启动器无法继续启动 Bridge" } else { "未找到，可能影响便携包完整性" }.to_string(),
        detail: path.to_string_lossy().to_string(),
        repairable: false,
    }
}

fn protected_feature(path: &str) -> Option<&'static str> {
    match path.trim_start_matches('/').split('?').next().unwrap_or("") {
        "api/process/start" => Some("openclaw"),
        "api/image/generate" => Some("image"),
        "api/video/generate" => Some("video"),
        _ => None,
    }
}

fn portable_base_dir() -> Result<std::path::PathBuf, String> {
    if cfg!(debug_assertions) {
        return std::env::current_dir().map_err(|e| format!("get current directory failed: {}", e));
    }

    let exe_path =
        std::env::current_exe().map_err(|e| format!("get executable path failed: {}", e))?;
    let exe_dir = exe_path
        .parent()
        .ok_or_else(|| "executable directory not found".to_string())?;
    let payload_dir = exe_dir.join(PORTABLE_PAYLOAD_DIR);
    if payload_dir.exists() {
        return Ok(payload_dir);
    }
    Ok(exe_dir.to_path_buf())
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

    if cfg!(windows) {
        std::path::PathBuf::from("python")
    } else {
        std::path::PathBuf::from("python3")
    }
}

fn spawn_bridge(py_path: &std::path::Path) -> Result<String, String> {
    if !py_path.exists() {
        let message = format!("bridge.py 未找到: {}", py_path.display());
        set_bridge_startup_error(message.clone());
        return Err(message);
    }

    let python_exe = bridge_python_exe(py_path);
    let mut child_cmd = Command::new(&python_exe);
    child_cmd.arg(py_path);
    child_cmd.env("PYTHONUTF8", "1");
    child_cmd.env("PYTHONIOENCODING", "utf-8");
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
    let mut child = child_cmd
        .spawn()
        .map_err(|e| {
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
    // reporting success. This is best-effort: if it never becomes ready within
    // the window we still return Ok and let the frontend retry.
    let ready_port = BRIDGE_PORT.load(Ordering::Relaxed);
    if ready_port != 0 {
        let addr = std::net::SocketAddr::from(([127, 0, 0, 1], ready_port));
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        while std::time::Instant::now() < deadline {
            if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
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
    let exe_path = std::env::current_exe().unwrap_or_else(|_| base_dir.join("OpenClaw.exe"));
    checks.push(path_check("tauri_exe", "启动器 EXE", &exe_path, true));
    checks.push(path_check("portable_base", "运行根目录", &base_dir, true));

    let candidates = [
        base_dir.join("python").join("bridge.py"),
        base_dir.join("_up_").join("python").join("bridge.py"),
        base_dir.join(PORTABLE_PAYLOAD_DIR).join("_up_").join("python").join("bridge.py"),
    ];
    let bridge_path = candidates.iter().find(|path| path.exists()).cloned();
    checks.push(DiagnosticCheck {
        id: "bridge_py_outer".to_string(),
        label: "Bridge 脚本外层检查".to_string(),
        status: if bridge_path.is_some() { "ok" } else { "fail" }.to_string(),
        message: if bridge_path.is_some() { "已找到 bridge.py" } else { "未找到 bridge.py，Python Bridge 无法启动" }.to_string(),
        detail: candidates.iter().map(|path| path.to_string_lossy().to_string()).collect::<Vec<_>>().join("；"),
        repairable: false,
    });

    if let Some(ref py_path) = bridge_path {
        let python_exe = bridge_python_exe(py_path);
        let python_is_path = python_exe.exists();
        checks.push(DiagnosticCheck {
            id: "bridge_python_outer".to_string(),
            label: "Bridge Python 外层检查".to_string(),
            status: if python_is_path { "ok" } else { "fail" }.to_string(),
            message: if python_is_path { "已找到随包 Python" } else { "未找到随包 Python，离线包不能依赖系统 Python" }.to_string(),
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
        status: if bridge_running { "ok" } else if last_error.starts_with("暂无") { "warn" } else { "fail" }.to_string(),
        message: if bridge_running { "Bridge 已启动" } else { "Bridge 未启动，下面是启动器外层捕获到的最近错误" }.to_string(),
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
            for rel_path in [
                "python/bridge.py",
                "_up_/python/bridge.py",
                "OpenClawFiles/_up_/python/bridge.py",
            ] {
                let py_path = exe_dir.join(rel_path);
                if py_path.exists() {
                    return spawn_bridge(&py_path);
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
async fn proxy_request(
    app: tauri::AppHandle,
    path: String,
    method: String,
    body: Option<String>,
) -> Result<String, String> {
    if let Some(feature) = protected_feature(&path) {
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
    let client = shared_http_client(&BRIDGE_HTTP_CLIENT, "bridge_client_failed")?;

    let mut req = client.request(
        match method.as_str() {
            "GET" => reqwest::Method::GET,
            "POST" => reqwest::Method::POST,
            "PUT" => reqwest::Method::PUT,
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
async fn phone_proxy_request(
    base_url: String,
    path: String,
    method: String,
    body: Option<String>,
    token: String,
    timeout_ms: Option<u64>,
    extra_headers: Option<HashMap<String, String>>,
) -> Result<String, String> {
    if token.trim().is_empty() {
        return Err("missing_token".to_string());
    }

    let base_url = normalize_phone_base_url(&base_url)?;
    let url = format!("{}/{}", base_url, path.trim_start_matches('/'));
    let parsed = reqwest::Url::parse(&url).map_err(|_| "invalid_phone_url".to_string())?;

    let timeout = timeout_ms.unwrap_or(30_000).clamp(1_000, 615_000);
    let client = shared_http_client(&PHONE_HTTP_CLIENT, "phone_client_failed")?;

    let mut req = client
        .request(
            match method.to_uppercase().as_str() {
                "GET" => reqwest::Method::GET,
                "POST" => reqwest::Method::POST,
                "PUT" => reqwest::Method::PUT,
                "DELETE" => reqwest::Method::DELETE,
                _ => return Err(format!("unsupported_method: {}", method)),
            },
            parsed,
        )
        .timeout(Duration::from_millis(timeout))
        .header("Accept", "application/json")
        .header("X-AGENT-PHONE-TOKEN", token.trim())
        .header("X-APKCLAW-TOKEN", token.trim());

    if let Some(headers) = extra_headers {
        for (name, value) in headers {
            let trimmed_name = name.trim();
            let trimmed_value = value.trim();
            if trimmed_name.is_empty() || trimmed_value.is_empty() {
                continue;
            }
            if trimmed_name.contains('\r') || trimmed_name.contains('\n') || trimmed_value.contains('\r') || trimmed_value.contains('\n') {
                return Err("invalid_phone_header".to_string());
            }
            req = req.header(trimmed_name, trimmed_value);
        }
    }

    if let Some(b) = body {
        req = req
            .body(b)
            .header("Content-Type", "application/json; charset=utf-8");
    }

    let resp = req
        .send()
        .await
        .map_err(|e| format!("phone_request_failed: {}", e))?;
    let status = resp.status();
    let text = resp
        .text()
        .await
        .map_err(|e| format!("phone_response_read_failed: {}", e))?;
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

fn chrono_like_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    format!("{}", seconds)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            app.handle().plugin(tauri_plugin_shell::init())?;
            // Start bridge on app launch. First ensure required runtime layers
            // are present (no-op unless OPENCLAW_DIST_MANIFEST_URL is set and a
            // layer is missing — the full/offline package already has them).
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
                if let Err(e) = start_bridge(app_handle).await {
                    eprintln!("[Bridge startup error] {}", e);
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
            proxy_request,
            phone_proxy_request,
            export_log,
            open_path,
            launcher_update::check_launcher_update,
            launcher_update::apply_launcher_update,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri");
}
