// First-run layer bootstrap for the <100MB online installer.
//
// Mirrors scripts/dist/dist-lib.mjs: download (mirror fallthrough) -> sha256
// verify -> extract -> atomic swap -> marker. Runs in the Rust shell because
// `node` itself is a downloaded layer (can't use Node to fetch Node).
//
// SAFE BY DESIGN: does nothing unless LOOM_DIST_MANIFEST_URL is set AND a
// required layer is actually missing. A full/offline package with all layers
// preinstalled is detected as present and skipped.

use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::{AppHandle, Emitter};

const PRIMARY_PAYLOAD_DIR: &str = "LOOMFiles";
const LEGACY_PAYLOAD_DIR: &str = "OpenClawFiles";
const PAYLOAD_DIR_CANDIDATES: [&str; 2] = [PRIMARY_PAYLOAD_DIR, LEGACY_PAYLOAD_DIR];
const MAX_LAYER_DOWNLOAD_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const RELEASE_PUBLIC_KEY_B64: &str = include_str!("../../../release-public-key.txt");

#[derive(Debug, Deserialize)]
struct Manifest {
    mirrors: Vec<String>,
    layers: Vec<Layer>,
}

#[derive(Debug, Deserialize)]
struct Layer {
    id: String,
    #[serde(default)]
    title: String,
    file: String,
    sha256: String,
    #[serde(rename = "installPath")]
    install_path: String,
    #[serde(default)]
    version: Option<String>,
    #[serde(default)]
    required: bool,
}

// --- First-run download progress, emitted to the WebView as Tauri events ---
// `dist://start` { layers, count } | `dist://progress` ProgressPayload |
// `dist://done` | `dist://error` { message }. The frontend shows an overlay
// only while these fire (i.e. only on a fresh online install).
#[derive(serde::Serialize, Clone)]
struct LayerInfo {
    id: String,
    title: String,
    size: u64,
}

#[derive(serde::Serialize, Clone)]
struct ProgressPayload {
    id: String,
    title: String,
    phase: String, // "download" | "verify" | "install"
    downloaded: u64,
    total: u64,
    index: usize, // 1-based
    count: usize,
}

struct ProgressMeta {
    id: String,
    title: String,
    index: usize,
    count: usize,
}

fn layer_title(layer: &Layer) -> String {
    if layer.title.is_empty() {
        layer.id.clone()
    } else {
        layer.title.clone()
    }
}

fn emit_start(app: &AppHandle, layers: &[&Layer]) {
    let _ = app.emit(
        "dist://start",
        serde_json::json!({
            "count": layers.len(),
            "layers": layers.iter().map(|l| LayerInfo { id: l.id.clone(), title: layer_title(l), size: 0 }).collect::<Vec<_>>(),
        }),
    );
}

fn emit_progress(app: &AppHandle, meta: &ProgressMeta, phase: &str, downloaded: u64, total: u64) {
    let _ = app.emit(
        "dist://progress",
        ProgressPayload {
            id: meta.id.clone(),
            title: meta.title.clone(),
            phase: phase.to_string(),
            downloaded,
            total,
            index: meta.index,
            count: meta.count,
        },
    );
}

/// Resolve the install root (the directory that contains the payload folder).
pub fn install_root() -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        return std::env::current_dir().map_err(|e| format!("cwd failed: {e}"));
    }
    let exe = std::env::current_exe().map_err(|e| format!("current_exe failed: {e}"))?;
    let exe_dir = exe
        .parent()
        .map(|p| p.to_path_buf())
        .ok_or_else(|| "exe parent not found".to_string())?;

    let mut candidates = Vec::new();

    #[cfg(target_os = "macos")]
    {
        // <install>/LOOM.app/Contents/MacOS/LOOM -> <install>
        if let Some(contents_dir) = exe_dir.parent() {
            if contents_dir.file_name().and_then(|n| n.to_str()) == Some("Contents") {
                if let Some(app_dir) = contents_dir.parent() {
                    if app_dir.extension().and_then(|n| n.to_str()) == Some("app") {
                        if let Some(install_dir) = app_dir.parent() {
                            candidates.push(install_dir.to_path_buf());
                        }
                    }
                }
            }
        }
    }

    candidates.push(exe_dir.clone());

    for candidate in &candidates {
        for payload_dir in PAYLOAD_DIR_CANDIDATES {
            if candidate.join(payload_dir).is_dir() {
                return Ok(candidate.clone());
            }
        }
    }

    Ok(candidates.into_iter().next().unwrap_or(exe_dir))
}

fn marker_path(install_root: &Path, layer: &Layer) -> PathBuf {
    install_root.join(&layer.install_path).join(".layer.json")
}

/// Present = marker sha matches, OR a known layer sentinel exists.
///
/// A plain "target directory is non-empty" check is too weak for online builds:
/// `LOOMFiles/node_modules` can exist before the openclaw dependency layer is
/// installed, causing first-run bootstrap to skip `openclaw-deps`.
fn is_present(install_root: &Path, layer: &Layer) -> bool {
    if let Ok(raw) = std::fs::read_to_string(marker_path(install_root, layer)) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw) {
            if v.get("sha256").and_then(|s| s.as_str()) == Some(layer.sha256.as_str()) {
                return true;
            }
        }
    }
    let target = install_root.join(&layer.install_path);
    match layer.id.as_str() {
        "node" => target.join("node.exe").is_file(),
        "openclaw-deps" => target.join("openclaw").join("openclaw.mjs").is_file(),
        "python-runtime" => target.join("python.exe").is_file(),
        _ => {
            target.is_dir()
                && std::fs::read_dir(&target)
                    .map(|mut d| d.next().is_some())
                    .unwrap_or(false)
        }
    }
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(12))
        .read_timeout(Duration::from_secs(90))
        .timeout(Duration::from_secs(20 * 60))
        .build()
        .map_err(|e| format!("http client: {e}"))
}

fn safe_relative_join(root: &Path, relative: &str, label: &str) -> Result<PathBuf, String> {
    let path = Path::new(relative);
    if relative.trim().is_empty() || path.is_absolute() {
        return Err(format!("{label} must be a non-empty relative path: {relative}"));
    }
    if path.components().any(|component| !matches!(component, std::path::Component::Normal(_))) {
        return Err(format!("{label} contains an unsafe path component: {relative}"));
    }
    Ok(root.join(path))
}

fn split_manifest_sources(raw: &str) -> Vec<String> {
    raw.split(|c| matches!(c, ';' | ',' | '\n' | '\r'))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect()
}

fn manifest_sources() -> Vec<String> {
    let candidates = [
        std::env::var("LOOM_DIST_MANIFEST_URLS").ok(),
        std::env::var("LOOM_DIST_MANIFEST_URL").ok(),
        std::env::var("LUMI_AGENT_DIST_MANIFEST_URLS").ok(),
        std::env::var("LUMI_AGENT_DIST_MANIFEST_URL").ok(),
        std::env::var("OPENCLAW_DIST_MANIFEST_URLS").ok(),
        std::env::var("OPENCLAW_DIST_MANIFEST_URL").ok(),
        option_env!("LOOM_DIST_MANIFEST_URLS").map(str::to_string),
        option_env!("LOOM_DIST_MANIFEST_URL").map(str::to_string),
        option_env!("LUMI_AGENT_DIST_MANIFEST_URLS").map(str::to_string),
        option_env!("LUMI_AGENT_DIST_MANIFEST_URL").map(str::to_string),
        option_env!("OPENCLAW_DIST_MANIFEST_URLS").map(str::to_string),
        option_env!("OPENCLAW_DIST_MANIFEST_URL").map(str::to_string),
    ];
    let mut seen = HashSet::new();
    let mut sources = Vec::new();
    for raw in candidates.into_iter().flatten() {
        for source in split_manifest_sources(&raw) {
            if seen.insert(source.clone()) {
                sources.push(source);
            }
        }
    }
    sources
}

fn manifest_cache_path(install_root: &Path) -> PathBuf {
    let payload_dir = PAYLOAD_DIR_CANDIDATES
        .iter()
        .find(|dir| install_root.join(dir).exists())
        .copied()
        .unwrap_or(PRIMARY_PAYLOAD_DIR);
    install_root
        .join(payload_dir)
        .join("data")
        .join(".openclaw")
        .join("dist-cache")
        .join("manifest.json")
}

fn default_required_layers_present(install_root: &Path) -> bool {
    let roots = [
        install_root.to_path_buf(),
        install_root.join(PRIMARY_PAYLOAD_DIR),
        install_root.join(LEGACY_PAYLOAD_DIR),
    ];
    roots.iter().any(|root| {
        let node_candidates = [
            root.join("_up_").join("node-runtime").join("node.exe"),
            root.join("node-runtime").join("node.exe"),
            root.join("node").join("node.exe"),
        ];
        let python_candidates = [
            root.join("_up_").join("python-runtime").join("python.exe"),
            root.join("python-runtime").join("python.exe"),
        ];
        node_candidates.iter().any(|path| path.is_file())
            && python_candidates.iter().any(|path| path.is_file())
    })
}

async fn read_manifest_text(source: &str) -> Result<String, String> {
    if source.starts_with("http://") || source.starts_with("https://") {
        return client()?
            .get(source)
            .send()
            .await
            .map_err(|e| format!("manifest fetch: {e}"))?
            .error_for_status()
            .map_err(|e| format!("manifest status: {e}"))?
            .text()
            .await
            .map_err(|e| format!("manifest body: {e}"));
    }

    let path = if source.starts_with("file://") {
        reqwest::Url::parse(source)
            .map_err(|e| format!("manifest file url parse: {e}"))?
            .to_file_path()
            .map_err(|_| format!("manifest file url is not local: {source}"))?
    } else {
        PathBuf::from(source)
    };
    std::fs::read_to_string(&path).map_err(|e| format!("manifest file {}: {e}", path.display()))
}

async fn fetch_manifest_from_source_with_public_key(
    source: &str,
    public_key: &str,
) -> Result<(Manifest, String), String> {
    let text = read_manifest_text(source).await?;
    let manifest = parse_manifest_text_with_public_key(&text, public_key)?;
    Ok((manifest, text))
}

fn parse_manifest_text_with_public_key(text: &str, public_key: &str) -> Result<Manifest, String> {
    let normalized = text.trim_start_matches('\u{feff}');
    let envelope: Value =
        serde_json::from_str(normalized).map_err(|e| format!("manifest parse: {e}"))?;
    let envelope_object = envelope
        .as_object()
        .ok_or_else(|| "release manifest must be a JSON object".to_string())?;

    if envelope_object.get("schemaVersion").and_then(Value::as_u64) != Some(1) {
        return Err("release manifest schemaVersion must be 1".to_string());
    }
    if envelope_object.get("product").and_then(Value::as_str) != Some("LOOM") {
        return Err("release manifest product must be LOOM".to_string());
    }

    let signature_object = envelope_object
        .get("signature")
        .and_then(Value::as_object)
        .ok_or_else(|| "release manifest signature is required".to_string())?;
    let algorithm = signature_object
        .get("algorithm")
        .and_then(Value::as_str)
        .ok_or_else(|| "release manifest signature algorithm is required".to_string())?;
    if algorithm != "ed25519" {
        return Err("release manifest signature algorithm must be ed25519".to_string());
    }
    let signature_text = signature_object
        .get("value")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "release manifest signature value is required".to_string())?;

    let public_key_text = public_key
        .trim_start_matches('\u{feff}')
        .trim()
        .strip_prefix("ed25519:")
        .unwrap_or_else(|| public_key.trim_start_matches('\u{feff}').trim())
        .trim();
    let public_key_bytes = BASE64_STANDARD
        .decode(public_key_text)
        .map_err(|_| "release manifest public key must be base64 Ed25519".to_string())?;
    let public_key_array: [u8; 32] = public_key_bytes
        .try_into()
        .map_err(|_| "release manifest public key must contain 32 Ed25519 bytes".to_string())?;
    let verifying_key = VerifyingKey::from_bytes(&public_key_array)
        .map_err(|_| "release manifest public key is invalid".to_string())?;
    let signature_bytes = BASE64_STANDARD
        .decode(signature_text)
        .map_err(|_| "release manifest signature must be base64".to_string())?;
    let signature = Signature::from_slice(&signature_bytes)
        .map_err(|_| "release manifest signature must contain 64 Ed25519 bytes".to_string())?;

    let mut signed_payload = envelope.clone();
    signed_payload
        .as_object_mut()
        .expect("validated release manifest object")
        .remove("signature");
    let canonical = crate::license::canonical_json(&signed_payload)
        .map_err(|e| format!("release manifest canonical JSON failed: {e}"))?;
    verifying_key
        .verify(&canonical, &signature)
        .map_err(|_| "release manifest signature verification failed".to_string())?;

    let distribution = envelope_object
        .get("distribution")
        .cloned()
        .ok_or_else(|| "signed release manifest distribution is required".to_string())?;
    let manifest: Manifest = serde_json::from_value(distribution)
        .map_err(|e| format!("release manifest distribution parse: {e}"))?;
    let validation_root = Path::new("manifest-root");
    let allow_insecure = std::env::var("LOOM_ALLOW_INSECURE_DIST").ok().as_deref() == Some("1");
    let mut ids = HashSet::new();
    for layer in &manifest.layers {
        if !ids.insert(layer.id.as_str()) {
            return Err(format!("manifest contains duplicate layer id: {}", layer.id));
        }
        safe_relative_join(validation_root, &layer.file, "layer file")?;
        safe_relative_join(validation_root, &layer.install_path, "layer installPath")?;
        if layer.sha256.len() != 64 || !layer.sha256.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(format!("layer {} has an invalid sha256", layer.id));
        }
    }
    for mirror in &manifest.mirrors {
        if !mirror.starts_with("https://") && !(allow_insecure && mirror.starts_with("http://")) {
            return Err(format!("distribution mirror must use HTTPS: {mirror}"));
        }
    }
    Ok(manifest)
}

async fn fetch_manifest(sources: &[String], cache_path: &Path) -> Result<Manifest, String> {
    fetch_manifest_with_public_key(sources, cache_path, RELEASE_PUBLIC_KEY_B64).await
}

async fn fetch_manifest_with_public_key(
    sources: &[String],
    cache_path: &Path,
    public_key: &str,
) -> Result<Manifest, String> {
    let mut errors = Vec::new();
    for source in sources {
        match fetch_manifest_from_source_with_public_key(source, public_key).await {
            Ok((manifest, text)) => {
                if let Some(parent) = cache_path.parent() {
                    if let Err(e) = std::fs::create_dir_all(parent) {
                        eprintln!("[bootstrap] manifest cache dir failed: {e}");
                    }
                }
                if let Err(e) = std::fs::write(cache_path, text) {
                    eprintln!("[bootstrap] manifest cache write failed: {e}");
                }
                eprintln!("[bootstrap] manifest loaded from {source}");
                return Ok(manifest);
            }
            Err(e) => errors.push(format!("{source}: {e}")),
        }
    }

    match std::fs::read_to_string(cache_path) {
        Ok(text) => {
            let manifest = parse_manifest_text_with_public_key(&text, public_key)
                .map_err(|e| format!("cached manifest parse: {e}"))?;
            eprintln!(
                "[bootstrap] manifest loaded from local cache {}",
                cache_path.display()
            );
            Ok(manifest)
        }
        Err(cache_err) => Err(format!(
            "manifest unavailable; sources failed [{}]; cache {} failed: {}",
            errors.join(" | "),
            cache_path.display(),
            cache_err
        )),
    }
}

/// Stream `url` to `dest`, returning the lowercase hex sha256 of the bytes.
/// Emits throttled `dist://progress` (phase "download") as bytes arrive.
async fn download_verify(
    app: &AppHandle,
    meta: &ProgressMeta,
    url: &str,
    dest: &Path,
) -> Result<String, String> {
    let mut resp = client()?
        .get(url)
        .send()
        .await
        .map_err(|e| format!("get {url}: {e}"))?
        .error_for_status()
        .map_err(|e| format!("status {url}: {e}"))?;
    let total = resp.content_length().unwrap_or(0);
    if total > MAX_LAYER_DOWNLOAD_BYTES {
        return Err(format!("layer is too large: {total} bytes"));
    }
    let mut file =
        std::fs::File::create(dest).map_err(|e| format!("create {}: {e}", dest.display()))?;
    let mut hasher = Sha256::new();
    let mut downloaded: u64 = 0;
    let mut last_emit = std::time::Instant::now();
    emit_progress(app, meta, "download", 0, total);
    while let Some(chunk) = resp
        .chunk()
        .await
        .map_err(|e| format!("chunk {url}: {e}"))?
    {
        hasher.update(&chunk);
        if downloaded.saturating_add(chunk.len() as u64) > MAX_LAYER_DOWNLOAD_BYTES {
            return Err(format!("layer exceeded the {} byte safety limit", MAX_LAYER_DOWNLOAD_BYTES));
        }
        file.write_all(&chunk)
            .map_err(|e| format!("write {}: {e}", dest.display()))?;
        downloaded += chunk.len() as u64;
        if last_emit.elapsed().as_millis() >= 200 {
            emit_progress(app, meta, "download", downloaded, total);
            last_emit = std::time::Instant::now();
        }
    }
    file.flush().ok();
    emit_progress(app, meta, "download", downloaded, total);
    Ok(hex(&hasher.finalize()))
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

fn extract_targz(archive: &Path, dest_parent: &Path) -> Result<(), String> {
    let f = std::fs::File::open(archive).map_err(|e| format!("open {}: {e}", archive.display()))?;
    let dec = flate2::read::GzDecoder::new(f);
    let mut ar = tar::Archive::new(dec);
    let entries = ar.entries().map_err(|e| format!("entries {}: {e}", archive.display()))?;
    for entry in entries {
        let mut entry = entry.map_err(|e| format!("entry {}: {e}", archive.display()))?;
        let unpacked = entry
            .unpack_in(dest_parent)
            .map_err(|e| format!("unpack {}: {e}", archive.display()))?;
        if !unpacked {
            return Err(format!("archive contains an unsafe path: {}", archive.display()));
        }
    }
    Ok(())
}

/// Rename with backoff retry. A freshly-extracted layer (especially
/// node_modules — tens of thousands of scripts/executables) is often briefly
/// held by Windows Defender's real-time scan, so moving the directory fails with
/// ACCESS_DENIED (os error 5) until the scan finishes. Retrying after a short
/// wait clears it; the final attempt propagates the real error if it persists.
fn rename_with_retry(from: &Path, to: &Path) -> io::Result<()> {
    move_path_with_retry(from, to, |source, target| std::fs::rename(source, target))
}

fn move_path_with_retry<F>(from: &Path, to: &Path, rename: F) -> io::Result<()>
where
    F: Fn(&Path, &Path) -> io::Result<()>,
{
    let mut delay = std::time::Duration::from_millis(200);
    for _ in 0..6 {
        match rename(from, to) {
            Ok(()) => return Ok(()),
            Err(error) if is_cross_volume_move_error(&error) => {
                return copy_path_then_remove_source(from, to);
            }
            Err(_) => {
                std::thread::sleep(delay);
                delay = (delay * 2).min(std::time::Duration::from_secs(2));
            }
        }
    }
    match rename(from, to) {
        Ok(()) => Ok(()),
        Err(error) if is_cross_volume_move_error(&error) => copy_path_then_remove_source(from, to),
        Err(error) => Err(error),
    }
}

fn is_cross_volume_move_error(error: &io::Error) -> bool {
    matches!(error.raw_os_error(), Some(17) | Some(18))
}

fn copy_path_then_remove_source(from: &Path, to: &Path) -> io::Result<()> {
    if let Some(parent) = to.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if from.is_dir() {
        if let Err(error) = copy_dir_recursive(from, to) {
            let _ = std::fs::remove_dir_all(to);
            return Err(error);
        }
        std::fs::remove_dir_all(from)
    } else {
        if let Err(error) = std::fs::copy(from, to) {
            let _ = std::fs::remove_file(to);
            return Err(error);
        }
        std::fs::remove_file(from)
    }
}

fn copy_dir_recursive(from: &Path, to: &Path) -> io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let source = entry.path();
        let target = to.join(entry.file_name());
        if source.is_dir() {
            copy_dir_recursive(&source, &target)?;
        } else {
            std::fs::copy(&source, &target)?;
        }
    }
    Ok(())
}

fn remove_path_if_exists(path: &Path) -> io::Result<()> {
    if !path.exists() {
        return Ok(());
    }
    if path.is_dir() {
        std::fs::remove_dir_all(path)
    } else {
        std::fs::remove_file(path)
    }
}

fn replace_directory_transactionally_with<F>(
    source: &Path,
    target: &Path,
    backup: &Path,
    marker: &Path,
    marker_bytes: &[u8],
    mut move_path: F,
) -> Result<(), String>
where
    F: FnMut(&Path, &Path) -> io::Result<()>,
{
    if backup.exists() {
        return Err(format!(
            "refusing to overwrite recovery backup {}",
            backup.display()
        ));
    }

    let had_previous_target = target.exists();
    if had_previous_target {
        move_path(target, backup)
            .map_err(|error| format!("backup {}: {error}", target.display()))?;
    }

    if let Err(error) = move_path(source, target) {
        if had_previous_target {
            if let Err(rollback_error) = move_path(backup, target) {
                return Err(format!(
                    "swap into {}: {error}; rollback failed, previous layer remains at {}: {rollback_error}",
                    target.display(),
                    backup.display()
                ));
            }
        }
        return Err(format!("swap into {}: {error}", target.display()));
    }

    if let Err(error) = std::fs::write(marker, marker_bytes) {
        if let Err(cleanup_error) = remove_path_if_exists(target) {
            return Err(format!(
                "marker: {error}; failed to remove incomplete layer {}: {cleanup_error}; previous layer remains at {}",
                target.display(),
                backup.display()
            ));
        }
        if had_previous_target {
            if let Err(rollback_error) = move_path(backup, target) {
                return Err(format!(
                    "marker: {error}; rollback failed, previous layer remains at {}: {rollback_error}",
                    backup.display()
                ));
            }
        }
        return Err(format!("marker: {error}"));
    }

    if backup.exists() {
        let _ = remove_path_if_exists(backup);
    }
    Ok(())
}

async fn install_layer(
    app: &AppHandle,
    meta: &ProgressMeta,
    install_root: &Path,
    mirrors: &[String],
    layer: &Layer,
    cache: &Path,
) -> Result<(), String> {
    std::fs::create_dir_all(cache).map_err(|e| format!("cache dir: {e}"))?;
    let archive = safe_relative_join(cache, &layer.file, "layer file")?;

    let mut verified = false;
    let mut last_err = String::new();
    for base in mirrors {
        let url = format!(
            "{}{}",
            base.trim_end_matches('/'),
            format!("/{}", layer.file)
        );
        match download_verify(app, meta, &url, &archive).await {
            Ok(sha) if sha == layer.sha256 => {
                verified = true;
                break;
            }
            Ok(sha) => {
                last_err = format!(
                    "sha mismatch from {url}: got {}…",
                    &sha[..12.min(sha.len())]
                )
            }
            Err(e) => last_err = e,
        }
    }
    if !verified {
        let _ = std::fs::remove_file(&archive);
        return Err(format!("layer {}: no trusted source. {last_err}", layer.id));
    }
    emit_progress(app, meta, "verify", 0, 0);

    let target = safe_relative_join(install_root, &layer.install_path, "layer installPath")?;
    let stage = cache.join(format!("stage-{}-{}", layer.id, std::process::id()));
    let _ = std::fs::remove_dir_all(&stage);
    let result = (|| {
        extract_targz(&archive, &stage)?;
        // build-layers tars `-C parent <basename>`, so content is at stage/<basename>.
        let base = Path::new(&layer.install_path)
            .file_name()
            .map(|n| stage.join(n))
            .filter(|p| p.exists())
            .unwrap_or_else(|| stage.clone());
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
        }
        let backup = target.with_extension(format!("old-{}", std::process::id()));
        let marker = serde_json::json!({
            "id": layer.id, "version": layer.version, "sha256": layer.sha256,
            "installedAt": chrono::Utc::now().to_rfc3339(),
        });
        let marker_bytes = serde_json::to_vec_pretty(&marker)
            .map_err(|error| format!("serialize marker: {error}"))?;
        replace_directory_transactionally_with(
            &base,
            &target,
            &backup,
            &marker_path(install_root, layer),
            &marker_bytes,
            rename_with_retry,
        )
    })();
    let _ = std::fs::remove_dir_all(&stage);
    let _ = std::fs::remove_file(&archive);
    if result.is_ok() {
        emit_progress(app, meta, "install", 0, 0);
    }
    result
}

/// Ensure all required layers are present. No-op unless a manifest URL is
/// configured and something is actually missing. Emits dist:// events so the
/// WebView can show a first-run download overlay.
pub async fn ensure_layers(app: AppHandle, install_root: PathBuf) -> Result<(), String> {
    // Resolution order: runtime env (override/testing) -> compile-time baked
    // value (set by the slim-installer build) -> inert (portable build). The
    // plural form accepts semicolon/comma/newline separated sources.
    let manifest_cache = manifest_cache_path(&install_root);
    let mut sources = manifest_sources();
    if sources.is_empty() && manifest_cache.is_file() {
        sources.push(manifest_cache.to_string_lossy().to_string());
    }
    if sources.is_empty() {
        return Ok(());
    }

    let manifest = match fetch_manifest(&sources, &manifest_cache).await {
        Ok(m) => m,
        Err(e) => {
            if default_required_layers_present(&install_root) {
                eprintln!(
                    "[bootstrap] manifest unavailable ({e}); continuing with preinstalled layers"
                );
                return Ok(());
            }
            return Err(e);
        }
    };
    let cache = manifest_cache
        .parent()
        .map(|p| p.join("layers"))
        .unwrap_or_else(|| std::env::temp_dir().join("loom-dist-cache"));

    // Determine what's actually missing BEFORE announcing, so the overlay only
    // appears on a fresh install (and shows the right set + total).
    let missing: Vec<&Layer> = manifest
        .layers
        .iter()
        .filter(|l| l.required && !is_present(&install_root, l))
        .collect();
    if missing.is_empty() {
        return Ok(());
    }
    emit_start(&app, &missing);

    let count = missing.len();
    for (i, layer) in missing.iter().enumerate() {
        let meta = ProgressMeta {
            id: layer.id.clone(),
            title: layer_title(layer),
            index: i + 1,
            count,
        };
        eprintln!("[bootstrap] installing layer {}…", layer.id);
        if let Err(e) =
            install_layer(&app, &meta, &install_root, &manifest.mirrors, layer, &cache).await
        {
            let _ = app.emit("dist://error", serde_json::json!({ "message": e }));
            return Err(e);
        }
        eprintln!("[bootstrap] layer {} installed", layer.id);
    }
    let _ = app.emit("dist://done", serde_json::json!({ "count": count }));
    Ok(())
}

/// Install one optional distribution layer on demand. This uses the same
/// manifest, mirrors, sha256 verification, extraction, and marker logic as the
/// first-run bootstrap path.
pub async fn install_layer_by_id(
    app: AppHandle,
    install_root: PathBuf,
    layer_id: String,
) -> Result<(), String> {
    let layer_id = layer_id.trim().to_string();
    if layer_id.is_empty() {
        return Err("distribution layer id is empty".to_string());
    }

    let sources = manifest_sources();
    if sources.is_empty() {
        return Err("distribution manifest is not configured".to_string());
    }

    let manifest_cache = manifest_cache_path(&install_root);
    let manifest = fetch_manifest(&sources, &manifest_cache).await?;
    let cache = manifest_cache
        .parent()
        .map(|p| p.join("layers"))
        .unwrap_or_else(|| std::env::temp_dir().join("loom-dist-cache"));

    let layer = manifest
        .layers
        .iter()
        .find(|layer| layer.id == layer_id)
        .ok_or_else(|| format!("distribution layer not found: {layer_id}"))?;

    if is_present(&install_root, layer) {
        return Ok(());
    }

    let selected = vec![layer];
    emit_start(&app, &selected);
    let meta = ProgressMeta {
        id: layer.id.clone(),
        title: layer_title(layer),
        index: 1,
        count: 1,
    };

    eprintln!("[bootstrap] installing optional layer {}", layer.id);
    if let Err(e) =
        install_layer(&app, &meta, &install_root, &manifest.mirrors, layer, &cache).await
    {
        let _ = app.emit("dist://error", serde_json::json!({ "message": e }));
        return Err(e);
    }
    eprintln!("[bootstrap] optional layer {} installed", layer.id);
    let _ = app.emit("dist://done", serde_json::json!({ "count": 1 }));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        default_required_layers_present, fetch_manifest_with_public_key, move_path_with_retry,
        parse_manifest_text_with_public_key, replace_directory_transactionally_with,
        safe_relative_join,
    };
    use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
    use base64::Engine;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::{json, Value};
    use std::io;

    fn canonical_json_for_test(value: &Value) -> Vec<u8> {
        fn write_value(value: &Value, out: &mut String) {
            match value {
                Value::Object(map) => {
                    out.push('{');
                    let mut keys: Vec<&String> = map.keys().collect();
                    keys.sort();
                    for (index, key) in keys.iter().enumerate() {
                        if index > 0 {
                            out.push(',');
                        }
                        out.push_str(&serde_json::to_string(key).unwrap());
                        out.push(':');
                        write_value(map.get(*key).unwrap(), out);
                    }
                    out.push('}');
                }
                Value::Array(items) => {
                    out.push('[');
                    for (index, item) in items.iter().enumerate() {
                        if index > 0 {
                            out.push(',');
                        }
                        write_value(item, out);
                    }
                    out.push(']');
                }
                _ => out.push_str(&serde_json::to_string(value).unwrap()),
            }
        }

        let mut out = String::new();
        write_value(value, &mut out);
        out.into_bytes()
    }

    fn signed_release_envelope() -> (Value, String) {
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let mut envelope = json!({
            "product": "LOOM",
            "distribution": {
                "layers": [],
                "mirrors": ["https://example.invalid/runtime/"]
            },
            "signature": {
                "value": "",
                "algorithm": "ed25519"
            },
            "schemaVersion": 1
        });
        let mut payload = envelope.clone();
        payload.as_object_mut().unwrap().remove("signature");
        let signature = signing_key.sign(&canonical_json_for_test(&payload));
        envelope["signature"]["value"] = json!(BASE64_STANDARD.encode(signature.to_bytes()));
        let public_key = BASE64_STANDARD.encode(signing_key.verifying_key().to_bytes());
        (envelope, public_key)
    }

    fn parse_test_envelope(envelope: &Value, public_key: &str) -> Result<super::Manifest, String> {
        parse_manifest_text_with_public_key(
            &serde_json::to_string_pretty(envelope).unwrap(),
            public_key,
        )
    }

    #[test]
    fn distribution_paths_cannot_escape_the_install_root() {
        let root = std::env::temp_dir().join("loom-safe-layer-root");
        assert!(safe_relative_join(&root, "_up_/node-runtime", "installPath").is_ok());
        assert!(safe_relative_join(&root, "../outside", "installPath").is_err());
        assert!(safe_relative_join(&root, "C:/outside", "installPath").is_err());
    }

    #[test]
    fn protected_full_runtime_is_detected_without_legacy_payload_folder() {
        let root = std::env::temp_dir().join(format!("loom-protected-runtime-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let node = root.join("_up_").join("node-runtime").join("node.exe");
        let python = root.join("_up_").join("python-runtime").join("python.exe");
        std::fs::create_dir_all(node.parent().unwrap()).unwrap();
        std::fs::create_dir_all(python.parent().unwrap()).unwrap();
        std::fs::write(&node, b"node").unwrap();
        std::fs::write(&python, b"python").unwrap();

        assert!(default_required_layers_present(&root));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn move_path_with_retry_copies_directory_when_rename_is_unavailable() {
        let root = std::env::temp_dir().join(format!(
            "loom-bootstrap-move-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        let source = root.join("source");
        let nested = source.join("nested");
        let target = root.join("target");
        std::fs::create_dir_all(&nested).unwrap();
        std::fs::write(nested.join("payload.txt"), b"ok").unwrap();

        let result = move_path_with_retry(&source, &target, |_, _| Err(io::Error::from_raw_os_error(17)));

        assert!(result.is_ok(), "{result:?}");
        assert!(!source.exists());
        assert_eq!(
            std::fs::read_to_string(target.join("nested").join("payload.txt")).unwrap(),
            "ok"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn transactional_layer_swap_restores_previous_target_when_new_layer_move_fails() {
        let root = std::env::temp_dir().join(format!(
            "loom-bootstrap-swap-failure-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        let source = root.join("new-layer");
        let target = root.join("runtime");
        let backup = root.join("runtime.old");
        let marker = target.join(".layer.json");
        std::fs::create_dir_all(&source).unwrap();
        std::fs::create_dir_all(&target).unwrap();
        std::fs::write(source.join("new.txt"), b"new").unwrap();
        std::fs::write(target.join("old.txt"), b"old").unwrap();

        let result = replace_directory_transactionally_with(
            &source,
            &target,
            &backup,
            &marker,
            b"{}",
            |from, to| {
                if from == source && to == target {
                    return Err(io::Error::new(io::ErrorKind::PermissionDenied, "blocked"));
                }
                std::fs::rename(from, to)
            },
        );

        assert!(result.is_err());
        assert_eq!(std::fs::read_to_string(target.join("old.txt")).unwrap(), "old");
        assert!(!target.join("new.txt").exists());
        assert!(!backup.exists());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn transactional_layer_swap_restores_previous_target_when_marker_write_fails() {
        let root = std::env::temp_dir().join(format!(
            "loom-bootstrap-marker-failure-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        let source = root.join("new-layer");
        let target = root.join("runtime");
        let backup = root.join("runtime.old");
        let marker = target.join("marker-is-a-directory");
        std::fs::create_dir_all(source.join("marker-is-a-directory")).unwrap();
        std::fs::create_dir_all(&target).unwrap();
        std::fs::write(source.join("new.txt"), b"new").unwrap();
        std::fs::write(target.join("old.txt"), b"old").unwrap();

        let result = replace_directory_transactionally_with(
            &source,
            &target,
            &backup,
            &marker,
            b"{}",
            |from, to| std::fs::rename(from, to),
        );

        assert!(result.is_err());
        assert_eq!(std::fs::read_to_string(target.join("old.txt")).unwrap(), "old");
        assert!(!target.join("new.txt").exists());
        assert!(!backup.exists());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn accepts_valid_signed_release_envelope() {
        let (envelope, public_key) = signed_release_envelope();

        let manifest = parse_test_envelope(&envelope, &public_key).unwrap();

        assert_eq!(manifest.mirrors, vec!["https://example.invalid/runtime/"]);
        assert!(manifest.layers.is_empty());
    }

    #[test]
    fn rejects_legacy_unsigned_distribution_manifest() {
        let (_envelope, public_key) = signed_release_envelope();
        let text = r#"{"mirrors":["https://example.invalid/"],"layers":[]}"#;

        let error = parse_manifest_text_with_public_key(text, &public_key).unwrap_err();

        assert!(
            error.contains("schemaVersion") || error.contains("signature"),
            "{error}"
        );
    }

    #[test]
    fn rejects_release_envelope_without_signature() {
        let (mut envelope, public_key) = signed_release_envelope();
        envelope.as_object_mut().unwrap().remove("signature");

        let error = parse_test_envelope(&envelope, &public_key).unwrap_err();

        assert!(error.contains("signature"), "{error}");
    }

    #[test]
    fn rejects_tampered_distribution() {
        let (mut envelope, public_key) = signed_release_envelope();
        envelope["distribution"]["mirrors"][0] = json!("https://tampered.invalid/runtime/");

        let error = parse_test_envelope(&envelope, &public_key).unwrap_err();

        assert!(error.contains("signature"), "{error}");
    }

    #[test]
    fn rejects_wrong_signature_algorithm() {
        let (mut envelope, public_key) = signed_release_envelope();
        envelope["signature"]["algorithm"] = json!("rsa-sha256");

        let error = parse_test_envelope(&envelope, &public_key).unwrap_err();

        assert!(error.contains("algorithm"), "{error}");
    }

    #[test]
    fn rejects_wrong_schema_version_and_product() {
        let (envelope, public_key) = signed_release_envelope();

        for (field, value, expected) in [
            ("schemaVersion", json!(2), "schemaVersion"),
            ("product", json!("OTHER"), "product"),
        ] {
            let mut invalid = envelope.clone();
            invalid[field] = value;
            let error = parse_test_envelope(&invalid, &public_key).unwrap_err();
            assert!(error.contains(expected), "{error}");
        }
    }

    #[test]
    fn rejects_signature_from_wrong_public_key() {
        let (envelope, _public_key) = signed_release_envelope();
        let wrong_key = BASE64_STANDARD.encode(
            SigningKey::from_bytes(&[8_u8; 32])
                .verifying_key()
                .to_bytes(),
        );

        let error = parse_test_envelope(&envelope, &wrong_key).unwrap_err();

        assert!(error.contains("signature"), "{error}");
    }

    #[test]
    fn parse_manifest_text_accepts_utf8_bom() {
        let (envelope, public_key) = signed_release_envelope();
        let text = format!("\u{feff}{}", serde_json::to_string(&envelope).unwrap());
        let manifest = parse_manifest_text_with_public_key(&text, &public_key).unwrap();

        assert_eq!(manifest.mirrors, vec!["https://example.invalid/runtime/"]);
        assert!(manifest.layers.is_empty());
    }

    #[test]
    fn caches_only_verified_original_envelope_and_rejects_unsigned_cache() {
        let (mut envelope, public_key) = signed_release_envelope();
        let root = std::env::temp_dir().join(format!(
            "loom-signed-manifest-cache-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("remote.json");
        let cache = root.join("cache.json");
        envelope["distribution"]["mirrors"][0] = json!("https://tampered.invalid/runtime/");
        std::fs::write(&source, serde_json::to_string(&envelope).unwrap()).unwrap();

        let error = tauri::async_runtime::block_on(fetch_manifest_with_public_key(
            &[source.to_string_lossy().to_string()],
            &cache,
            &public_key,
        ))
        .unwrap_err();

        assert!(error.contains("signature"), "{error}");
        assert!(!cache.exists());

        let (envelope, _) = signed_release_envelope();
        let original = format!(
            "\u{feff}{}\n",
            serde_json::to_string_pretty(&envelope).unwrap()
        );
        std::fs::write(&source, &original).unwrap();

        let result = tauri::async_runtime::block_on(fetch_manifest_with_public_key(
            &[source.to_string_lossy().to_string()],
            &cache,
            &public_key,
        ));

        assert!(result.is_ok(), "{result:?}");
        assert_eq!(std::fs::read_to_string(&cache).unwrap(), original);

        let unsigned = r#"{"mirrors":["https://example.invalid/"],"layers":[]}"#;
        std::fs::write(&cache, unsigned).unwrap();
        let error = tauri::async_runtime::block_on(fetch_manifest_with_public_key(
            &[],
            &cache,
            &public_key,
        ))
        .unwrap_err();

        assert!(error.contains("cached manifest"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }
}
