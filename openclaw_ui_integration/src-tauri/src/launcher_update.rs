// Launcher self-update interface (distinct from the OpenClaw runtime updater at
// /api/update/* and from the runtime-layer bootstrap). Protocol: a small JSON
// document — `launcher.json` — published next to the installer:
//
//   { "version": "2.0.7",
//     "url": "https://.../OpenClaw-Setup-v2.0.7.exe",
//     "sha256": "<hex>",
//     "notes": "..." }
//
// `check_launcher_update` fetches it and compares to the baked CARGO_PKG_VERSION.
// `apply_launcher_update` downloads the setup, sha256-verifies it, launches it
// and exits — the per-user installer overwrites in place (keeping the already
// downloaded runtime layers) and the user relaunches.
//
// The update source URL is resolved at runtime from OPENCLAW_LAUNCHER_UPDATE_URL
// (env, for testing) or baked at build time via option_env! of the same name.
// Unset = the interface is inert (returns "not configured"), never errors.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const UPDATE_HOSTS_ENV: &str = "OPENCLAW_LAUNCHER_UPDATE_ALLOW_HOSTS";

#[derive(Serialize)]
pub struct LauncherUpdateInfo {
    pub available: bool,
    pub current: String,
    pub latest: String,
    pub url: String,
    pub sha256: String,
    pub notes: String,
    pub configured: bool,
}

#[derive(Deserialize)]
struct LauncherManifest {
    version: String,
    url: String,
    #[serde(default)]
    sha256: String,
    // Tolerant: accept `notes` as a plain string OR an array of strings (joined
    // with newlines) OR missing. A past bug published array `notes` while this
    // expected a string, which broke self-update parsing for everyone.
    #[serde(default, deserialize_with = "deserialize_notes")]
    notes: String,
}

fn deserialize_notes<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Notes {
        One(String),
        Many(Vec<String>),
    }
    Ok(match Option::<Notes>::deserialize(deserializer)? {
        Some(Notes::One(text)) => text,
        Some(Notes::Many(items)) => items.join("\n"),
        None => String::new(),
    })
}

fn update_url() -> Option<String> {
    std::env::var("OPENCLAW_LAUNCHER_UPDATE_URL")
        .ok()
        .filter(|u| !u.trim().is_empty())
        .or_else(|| option_env!("OPENCLAW_LAUNCHER_UPDATE_URL").map(str::to_string))
        .filter(|u| !u.trim().is_empty())
}

/// True when `latest` is a strictly higher dotted version than `current`.
fn is_newer(latest: &str, current: &str) -> bool {
    fn parts(v: &str) -> Vec<u64> {
        v.split(|c| c == '.' || c == '-')
            .filter_map(|p| p.parse().ok())
            .collect()
    }
    let (a, b) = (parts(latest), parts(current));
    for i in 0..a.len().max(b.len()) {
        let x = a.get(i).copied().unwrap_or(0);
        let y = b.get(i).copied().unwrap_or(0);
        if x != y {
            return x > y;
        }
    }
    false
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

fn http_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent("OpenClaw-Launcher")
        .build()
        .map_err(|e| format!("http client: {e}"))
}

fn parse_https_url(value: &str, label: &str) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(value.trim()).map_err(|e| format!("{label}无效：{e}"))?;
    if url.scheme() != "https" {
        return Err(format!("{label}必须使用 HTTPS"));
    }
    if url.host_str().unwrap_or("").is_empty() {
        return Err(format!("{label}缺少域名"));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(format!("{label}不能包含用户名或密码"));
    }
    Ok(url)
}

fn configured_update_hosts() -> Result<Vec<String>, String> {
    let mut hosts = Vec::new();
    if let Some(source) = update_url() {
        let url = parse_https_url(&source, "启动器更新源")?;
        if let Some(host) = url.host_str() {
            hosts.push(host.to_ascii_lowercase());
        }
    }
    if let Ok(extra) = std::env::var(UPDATE_HOSTS_ENV) {
        hosts.extend(
            extra
                .split(',')
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(|item| item.to_ascii_lowercase()),
        );
    }
    hosts.sort();
    hosts.dedup();
    Ok(hosts)
}

fn validate_update_package_url(value: &str) -> Result<reqwest::Url, String> {
    let url = parse_https_url(value, "安装包地址")?;
    let host = url.host_str().unwrap_or("").to_ascii_lowercase();
    let allowed = configured_update_hosts()?;
    if allowed.is_empty() || !allowed.iter().any(|item| item == &host) {
        return Err(format!(
            "安装包域名不在启动器更新白名单中：{}",
            host
        ));
    }
    Ok(url)
}

fn validate_sha256(value: &str) -> Result<String, String> {
    let normalized = value.trim().to_ascii_lowercase();
    if normalized.len() != 64 || !normalized.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("安装包 sha256 必须是 64 位十六进制字符串".to_string());
    }
    Ok(normalized)
}

#[tauri::command]
pub async fn check_launcher_update() -> Result<LauncherUpdateInfo, String> {
    let current = env!("CARGO_PKG_VERSION").to_string();
    let url = match update_url() {
        Some(u) => u,
        None => {
            return Ok(LauncherUpdateInfo {
                available: false,
                current: current.clone(),
                latest: current,
                url: String::new(),
                sha256: String::new(),
                notes: "未配置启动器更新源".to_string(),
                configured: false,
            })
        }
    };
    let manifest_url = parse_https_url(&url, "启动器更新源")?;
    let text = http_client()?
        .get(manifest_url)
        .send()
        .await
        .map_err(|e| format!("检查更新失败：{e}"))?
        .error_for_status()
        .map_err(|e| format!("检查更新失败：{e}"))?
        .text()
        .await
        .map_err(|e| format!("读取更新清单失败：{e}"))?;
    let manifest: LauncherManifest =
        serde_json::from_str(&text).map_err(|e| format!("更新清单解析失败：{e}"))?;
    let package_url = validate_update_package_url(&manifest.url)?;
    let sha256 = validate_sha256(&manifest.sha256)?;
    Ok(LauncherUpdateInfo {
        available: is_newer(&manifest.version, &current),
        current,
        latest: manifest.version,
        url: package_url.to_string(),
        sha256,
        notes: manifest.notes,
        configured: true,
    })
}

#[tauri::command]
pub async fn apply_launcher_update(
    app: tauri::AppHandle,
    url: String,
    sha256: String,
) -> Result<(), String> {
    let package_url = validate_update_package_url(&url)?;
    let expected_sha256 = validate_sha256(&sha256)?;
    let bytes = http_client()?
        .get(package_url)
        .send()
        .await
        .map_err(|e| format!("下载安装包失败：{e}"))?
        .error_for_status()
        .map_err(|e| format!("下载安装包失败：{e}"))?
        .bytes()
        .await
        .map_err(|e| format!("下载安装包失败：{e}"))?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let got = hex(&hasher.finalize());
    if !got.eq_ignore_ascii_case(&expected_sha256) {
        return Err(format!(
            "安装包校验失败：期望 {}… 实际 {}…",
            &expected_sha256[..16],
            &got[..16]
        ));
    }
    let setup = std::env::temp_dir().join("OpenClaw-Setup-update.exe");
    std::fs::write(&setup, &bytes).map_err(|e| format!("写入安装包失败：{e}"))?;
    // Launch the installer detached, then exit so it can overwrite our files.
    std::process::Command::new(&setup)
        .spawn()
        .map_err(|e| format!("启动安装包失败：{e}"))?;
    app.exit(0);
    Ok(())
}
