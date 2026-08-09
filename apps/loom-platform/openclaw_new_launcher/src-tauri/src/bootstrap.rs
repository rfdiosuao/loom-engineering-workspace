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
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};

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
// Every `dist://start`, `dist://progress`, `dist://done`, and `dist://error`
// payload is the complete persisted DistributionSetupSnapshot. The frontend
// reconciles events and the read-only snapshot query by monotonic revision.
#[derive(serde::Serialize, Clone, Debug, PartialEq)]
struct LayerInfo {
    id: String,
    title: String,
    size: u64,
}

#[derive(serde::Serialize, Clone, Debug, PartialEq)]
struct ProgressPayload {
    id: String,
    title: String,
    phase: String, // "download" | "verify" | "install"
    downloaded: u64,
    total: u64,
    index: usize, // 1-based
    count: usize,
}

#[derive(serde::Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum DistributionStatus {
    Idle,
    Running,
    Done,
    Error,
}

impl Default for DistributionStatus {
    fn default() -> Self {
        Self::Idle
    }
}

#[derive(serde::Serialize, Clone, Debug, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DistributionSetupSnapshot {
    revision: u64,
    run_id: u64,
    status: DistributionStatus,
    layers: Vec<LayerInfo>,
    progress: Option<ProgressPayload>,
    error: Option<String>,
}

#[derive(Default)]
struct DistributionSetupTracker {
    snapshot: DistributionSetupSnapshot,
}

impl DistributionSetupTracker {
    fn snapshot(&self) -> DistributionSetupSnapshot {
        self.snapshot.clone()
    }

    fn start(&mut self, layers: Vec<LayerInfo>) -> DistributionSetupSnapshot {
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.run_id = self.snapshot.run_id.saturating_add(1);
        self.snapshot.status = DistributionStatus::Running;
        self.snapshot.layers = layers;
        self.snapshot.progress = None;
        self.snapshot.error = None;
        self.snapshot()
    }

    fn progress(
        &mut self,
        run_id: u64,
        progress: ProgressPayload,
    ) -> Option<DistributionSetupSnapshot> {
        if run_id != self.snapshot.run_id || self.snapshot.status != DistributionStatus::Running {
            return None;
        }
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.progress = Some(progress);
        Some(self.snapshot())
    }

    fn done(&mut self, run_id: u64) -> Option<DistributionSetupSnapshot> {
        if run_id != self.snapshot.run_id || self.snapshot.status != DistributionStatus::Running {
            return None;
        }
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.status = DistributionStatus::Done;
        self.snapshot.error = None;
        Some(self.snapshot())
    }

    fn error(&mut self, run_id: u64, error: String) -> Option<DistributionSetupSnapshot> {
        if run_id != self.snapshot.run_id || self.snapshot.status != DistributionStatus::Running {
            return None;
        }
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.status = DistributionStatus::Error;
        self.snapshot.error = Some(error);
        Some(self.snapshot())
    }

    fn error_new_run(&mut self, error: String) -> DistributionSetupSnapshot {
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.run_id = self.snapshot.run_id.saturating_add(1);
        self.snapshot.status = DistributionStatus::Error;
        self.snapshot.layers.clear();
        self.snapshot.progress = None;
        self.snapshot.error = Some(error);
        self.snapshot()
    }

    fn idle_new_run(&mut self) -> DistributionSetupSnapshot {
        self.snapshot.revision = self.snapshot.revision.saturating_add(1);
        self.snapshot.run_id = self.snapshot.run_id.saturating_add(1);
        self.snapshot.status = DistributionStatus::Idle;
        self.snapshot.layers.clear();
        self.snapshot.progress = None;
        self.snapshot.error = None;
        self.snapshot()
    }
}

#[derive(Default)]
pub struct DistributionSetupState {
    tracker: Mutex<DistributionSetupTracker>,
}

impl DistributionSetupState {
    pub fn snapshot(&self) -> DistributionSetupSnapshot {
        self.tracker
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .snapshot()
    }

    fn transition_and_notify<F, N>(
        &self,
        transition: F,
        mut notify: N,
    ) -> Option<DistributionSetupSnapshot>
    where
        F: FnOnce(&mut DistributionSetupTracker) -> Option<DistributionSetupSnapshot>,
        N: FnMut(&DistributionSetupSnapshot),
    {
        let snapshot = {
            let mut tracker = self
                .tracker
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            transition(&mut tracker)
        };
        if let Some(snapshot) = snapshot.as_ref() {
            notify(snapshot);
        }
        snapshot
    }
}

struct ProgressMeta {
    id: String,
    title: String,
    index: usize,
    count: usize,
    run_id: u64,
}

fn layer_title(layer: &Layer) -> String {
    if layer.title.is_empty() {
        layer.id.clone()
    } else {
        layer.title.clone()
    }
}

fn transition_and_emit<F>(
    app: &AppHandle,
    event: &str,
    transition: F,
) -> Option<DistributionSetupSnapshot>
where
    F: FnOnce(&mut DistributionSetupTracker) -> Option<DistributionSetupSnapshot>,
{
    app.state::<DistributionSetupState>()
        .transition_and_notify(transition, |snapshot| {
            let _ = app.emit(event, snapshot);
        })
}

fn record_idle(app: &AppHandle) -> DistributionSetupSnapshot {
    app.state::<DistributionSetupState>()
        .transition_and_notify(|tracker| Some(tracker.idle_new_run()), |_| {})
        .expect("idle transition always returns a snapshot")
}

pub fn record_setup_error(app: &AppHandle, error: String) -> DistributionSetupSnapshot {
    transition_and_emit(app, "dist://error", |tracker| {
        Some(tracker.error_new_run(error))
    })
    .expect("new error run always returns a snapshot")
}

fn emit_start(app: &AppHandle, layers: &[&Layer]) -> DistributionSetupSnapshot {
    let layers = layers
        .iter()
        .map(|layer| LayerInfo {
            id: layer.id.clone(),
            title: layer_title(layer),
            size: 0,
        })
        .collect();
    transition_and_emit(app, "dist://start", |tracker| Some(tracker.start(layers)))
        .expect("start transition always returns a snapshot")
}

fn emit_progress(
    app: &AppHandle,
    meta: &ProgressMeta,
    phase: &str,
    downloaded: u64,
    total: u64,
) {
    let payload = ProgressPayload {
        id: meta.id.clone(),
        title: meta.title.clone(),
        phase: phase.to_string(),
        downloaded,
        total,
        index: meta.index,
        count: meta.count,
    };
    transition_and_emit(app, "dist://progress", |tracker| {
        tracker.progress(meta.run_id, payload)
    });
}

fn emit_done(app: &AppHandle, run_id: u64) {
    transition_and_emit(app, "dist://done", |tracker| tracker.done(run_id));
}

fn emit_error(app: &AppHandle, run_id: u64, error: String) {
    transition_and_emit(app, "dist://error", |tracker| {
        tracker.error(run_id, error)
    });
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
        let openclaw_candidates = [root
            .join("node_modules")
            .join("openclaw")
            .join("openclaw.mjs")];
        node_candidates.iter().any(|path| path.is_file())
            && python_candidates.iter().any(|path| path.is_file())
            && openclaw_candidates.iter().any(|path| path.is_file())
    })
}

#[derive(Debug)]
enum ManifestLoadError {
    Unavailable(String),
    Invalid(String),
}

impl ManifestLoadError {
    fn is_invalid(&self) -> bool {
        matches!(self, Self::Invalid(_))
    }

    fn into_message(self) -> String {
        match self {
            Self::Unavailable(message) | Self::Invalid(message) => message,
        }
    }
}

impl std::fmt::Display for ManifestLoadError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message) | Self::Invalid(message) => formatter.write_str(message),
        }
    }
}

fn classify_manifest_file_error(message: String, error: &io::Error) -> ManifestLoadError {
    if error.kind() == io::ErrorKind::InvalidData {
        ManifestLoadError::Invalid(message)
    } else {
        ManifestLoadError::Unavailable(message)
    }
}

async fn read_manifest_text(source: &str) -> Result<String, ManifestLoadError> {
    if source.starts_with("http://") || source.starts_with("https://") {
        return client()
            .map_err(ManifestLoadError::Unavailable)?
            .get(source)
            .send()
            .await
            .map_err(|e| ManifestLoadError::Unavailable(format!("manifest fetch: {e}")))?
            .error_for_status()
            .map_err(|e| ManifestLoadError::Unavailable(format!("manifest status: {e}")))?
            .text()
            .await
            .map_err(|e| ManifestLoadError::Unavailable(format!("manifest body: {e}")));
    }

    let path = if source.starts_with("file://") {
        reqwest::Url::parse(source)
            .map_err(|e| ManifestLoadError::Invalid(format!("manifest file url parse: {e}")))?
            .to_file_path()
            .map_err(|_| ManifestLoadError::Invalid(format!("manifest file url is not local: {source}")))?
    } else {
        PathBuf::from(source)
    };
    std::fs::read_to_string(&path).map_err(|error| {
        classify_manifest_file_error(
            format!("manifest file {}: {error}", path.display()),
            &error,
        )
    })
}

async fn fetch_manifest_from_source_with_public_key(
    source: &str,
    public_key: &str,
) -> Result<(Manifest, String), ManifestLoadError> {
    let text = read_manifest_text(source).await?;
    let manifest = parse_manifest_text_with_public_key(&text, public_key)
        .map_err(ManifestLoadError::Invalid)?;
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
    fetch_manifest_classified_with_public_key(sources, cache_path, public_key)
        .await
        .map_err(ManifestLoadError::into_message)
}

async fn fetch_manifest_classified_with_public_key(
    sources: &[String],
    cache_path: &Path,
    public_key: &str,
) -> Result<Manifest, ManifestLoadError> {
    let mut errors = Vec::new();
    let mut saw_invalid_source = false;
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
            Err(error) => {
                saw_invalid_source |= error.is_invalid();
                errors.push(format!("{source}: {error}"));
            }
        }
    }

    match std::fs::read_to_string(cache_path) {
        Ok(text) => {
            let manifest = parse_manifest_text_with_public_key(&text, public_key)
                .map_err(|e| ManifestLoadError::Invalid(format!("cached manifest parse: {e}")))?;
            eprintln!(
                "[bootstrap] manifest loaded from local cache {}",
                cache_path.display()
            );
            Ok(manifest)
        }
        Err(cache_error) => {
            let message = format!(
                "manifest unavailable; sources failed [{}]; cache {} failed: {}",
                errors.join(" | "),
                cache_path.display(),
                cache_error
            );
            if saw_invalid_source || cache_error.kind() == io::ErrorKind::InvalidData {
                Err(ManifestLoadError::Invalid(message))
            } else {
                Err(ManifestLoadError::Unavailable(message))
            }
        }
    }
}

async fn fetch_manifest_or_accept_preinstalled_layers(
    sources: &[String],
    cache_path: &Path,
    install_root: &Path,
) -> Result<Option<Manifest>, String> {
    fetch_manifest_or_accept_preinstalled_layers_with_public_key(
        sources,
        cache_path,
        install_root,
        RELEASE_PUBLIC_KEY_B64,
    )
    .await
}

async fn fetch_manifest_or_accept_preinstalled_layers_with_public_key(
    sources: &[String],
    cache_path: &Path,
    install_root: &Path,
    public_key: &str,
) -> Result<Option<Manifest>, String> {
    match fetch_manifest_classified_with_public_key(sources, cache_path, public_key).await {
        Ok(manifest) => Ok(Some(manifest)),
        Err(ManifestLoadError::Unavailable(error)) => {
            if default_required_layers_present(install_root) {
                eprintln!(
                    "[bootstrap] manifest unavailable ({error}); continuing with preinstalled layers"
                );
                Ok(None)
            } else {
                Err(error)
            }
        }
        Err(ManifestLoadError::Invalid(error)) => Err(error),
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
        record_idle(&app);
        return Ok(());
    }

    let manifest = match fetch_manifest_or_accept_preinstalled_layers(
        &sources,
        &manifest_cache,
        &install_root,
    )
    .await
    {
        Ok(Some(manifest)) => manifest,
        Ok(None) => {
            record_idle(&app);
            return Ok(());
        }
        Err(error) => {
            record_setup_error(&app, error.clone());
            return Err(error);
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
        record_idle(&app);
        return Ok(());
    }
    let run_id = emit_start(&app, &missing).run_id;

    let count = missing.len();
    for (i, layer) in missing.iter().enumerate() {
        let meta = ProgressMeta {
            id: layer.id.clone(),
            title: layer_title(layer),
            index: i + 1,
            count,
            run_id,
        };
        eprintln!("[bootstrap] installing layer {}…", layer.id);
        if let Err(e) =
            install_layer(&app, &meta, &install_root, &manifest.mirrors, layer, &cache).await
        {
            emit_error(&app, run_id, e.clone());
            return Err(e);
        }
        eprintln!("[bootstrap] layer {} installed", layer.id);
    }
    emit_done(&app, run_id);
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
        let error = "distribution layer id is empty".to_string();
        record_setup_error(&app, error.clone());
        return Err(error);
    }

    let sources = manifest_sources();
    if sources.is_empty() {
        let error = "distribution manifest is not configured".to_string();
        record_setup_error(&app, error.clone());
        return Err(error);
    }

    let manifest_cache = manifest_cache_path(&install_root);
    let manifest = match fetch_manifest(&sources, &manifest_cache).await {
        Ok(manifest) => manifest,
        Err(error) => {
            record_setup_error(&app, error.clone());
            return Err(error);
        }
    };
    let cache = manifest_cache
        .parent()
        .map(|p| p.join("layers"))
        .unwrap_or_else(|| std::env::temp_dir().join("loom-dist-cache"));

    let layer = match manifest
        .layers
        .iter()
        .find(|layer| layer.id == layer_id)
    {
        Some(layer) => layer,
        None => {
            let error = format!("distribution layer not found: {layer_id}");
            record_setup_error(&app, error.clone());
            return Err(error);
        }
    };

    if is_present(&install_root, layer) {
        record_idle(&app);
        return Ok(());
    }

    let selected = vec![layer];
    let run_id = emit_start(&app, &selected).run_id;
    let meta = ProgressMeta {
        id: layer.id.clone(),
        title: layer_title(layer),
        index: 1,
        count: 1,
        run_id,
    };

    eprintln!("[bootstrap] installing optional layer {}", layer.id);
    if let Err(e) =
        install_layer(&app, &meta, &install_root, &manifest.mirrors, layer, &cache).await
    {
        emit_error(&app, run_id, e.clone());
        return Err(e);
    }
    eprintln!("[bootstrap] optional layer {} installed", layer.id);
    emit_done(&app, run_id);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        default_required_layers_present, DistributionSetupTracker, DistributionStatus,
        fetch_manifest_or_accept_preinstalled_layers,
        fetch_manifest_or_accept_preinstalled_layers_with_public_key,
        fetch_manifest_with_public_key, move_path_with_retry, parse_manifest_text_with_public_key,
        replace_directory_transactionally_with, safe_relative_join,
    };
    use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
    use base64::Engine;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::{json, Value};
    use std::io;

    fn required_layer_test_root(case: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "loom-required-layers-{case}-{}",
            std::process::id()
        ))
    }

    fn write_required_layer_sentinel(path: &std::path::Path, contents: &[u8]) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, contents).unwrap();
    }

    fn write_complete_required_layers(root: &std::path::Path) -> [std::path::PathBuf; 3] {
        let node = root.join("_up_").join("node-runtime").join("node.exe");
        let python = root.join("_up_").join("python-runtime").join("python.exe");
        let openclaw = root
            .join("node_modules")
            .join("openclaw")
            .join("openclaw.mjs");
        write_required_layer_sentinel(&node, b"node");
        write_required_layer_sentinel(&python, b"python");
        write_required_layer_sentinel(&openclaw, b"openclaw");
        [node, python, openclaw]
    }

    fn fetch_missing_manifest_with_fallback(root: &std::path::Path) -> Result<bool, String> {
        let source = root.join("missing-source-manifest.json");
        let cache = root.join("missing-cache").join("manifest.json");
        tauri::async_runtime::block_on(fetch_manifest_or_accept_preinstalled_layers(
            &[source.to_string_lossy().to_string()],
            &cache,
            root,
        ))
        .map(|manifest| manifest.is_none())
    }

    fn fetch_manifest_source_with_fallback(
        root: &std::path::Path,
        source: &std::path::Path,
    ) -> Result<bool, String> {
        let cache = root.join("missing-cache").join("manifest.json");
        tauri::async_runtime::block_on(fetch_manifest_or_accept_preinstalled_layers(
            &[source.to_string_lossy().to_string()],
            &cache,
            root,
        ))
        .map(|manifest| manifest.is_none())
    }

    fn assert_missing_manifest_error(error: &str) {
        assert!(error.contains("manifest unavailable"), "{error}");
        assert!(error.contains("missing-source-manifest.json"), "{error}");
        assert!(error.contains("missing-cache"), "{error}");
    }

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

    fn resign_release_envelope(envelope: &mut Value) -> String {
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let mut payload = envelope.clone();
        payload.as_object_mut().unwrap().remove("signature");
        let signature = signing_key.sign(&canonical_json_for_test(&payload));
        envelope["signature"]["value"] = json!(BASE64_STANDARD.encode(signature.to_bytes()));
        BASE64_STANDARD.encode(signing_key.verifying_key().to_bytes())
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
    fn offline_manifest_fallback_accepts_complete_preinstalled_layers() {
        let root = required_layer_test_root("complete");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);

        assert!(default_required_layers_present(&root));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn offline_manifest_fallback_rejects_missing_openclaw_dependencies() {
        let root = required_layer_test_root("missing-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(openclaw).unwrap();

        assert!(!default_required_layers_present(&root));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn offline_manifest_fallback_rejects_damaged_openclaw_entrypoint() {
        let root = required_layer_test_root("damaged-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(&openclaw).unwrap();
        std::fs::create_dir_all(&openclaw).unwrap();

        assert!(!default_required_layers_present(&root));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn offline_manifest_fallback_recovers_after_openclaw_is_restored() {
        let root = required_layer_test_root("restore-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(&openclaw).unwrap();

        assert!(!default_required_layers_present(&root));

        write_required_layer_sentinel(&openclaw, b"openclaw");
        assert!(default_required_layers_present(&root));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_unavailable_accepts_complete_preinstalled_layers() {
        let root = required_layer_test_root("manifest-unavailable-complete");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);

        let result = fetch_missing_manifest_with_fallback(&root);

        assert_eq!(result, Ok(true), "{result:?}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_unavailable_rejects_missing_openclaw_dependencies() {
        let root = required_layer_test_root("manifest-unavailable-missing-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(openclaw).unwrap();

        let error = fetch_missing_manifest_with_fallback(&root).unwrap_err();

        assert_missing_manifest_error(&error);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_unavailable_rejects_damaged_openclaw_entrypoint() {
        let root = required_layer_test_root("manifest-unavailable-damaged-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(&openclaw).unwrap();
        std::fs::create_dir_all(&openclaw).unwrap();

        let error = fetch_missing_manifest_with_fallback(&root).unwrap_err();

        assert_missing_manifest_error(&error);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_unavailable_recovers_after_openclaw_is_restored() {
        let root = required_layer_test_root("manifest-unavailable-restore-openclaw");
        let _ = std::fs::remove_dir_all(&root);
        let [_, _, openclaw] = write_complete_required_layers(&root);
        std::fs::remove_file(&openclaw).unwrap();

        let error = fetch_missing_manifest_with_fallback(&root).unwrap_err();
        assert_missing_manifest_error(&error);

        write_required_layer_sentinel(&openclaw, b"openclaw");
        let recovered = fetch_missing_manifest_with_fallback(&root);
        assert_eq!(recovered, Ok(true), "{recovered:?}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_integrity_invalid_signature_never_falls_back_to_sentinels() {
        let root = required_layer_test_root("manifest-integrity-invalid-signature");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);
        let source = root.join("invalid-signature.json");
        let (mut envelope, _) = signed_release_envelope();
        envelope["signature"]["value"] = json!(BASE64_STANDARD.encode([0_u8; 64]));
        std::fs::write(&source, serde_json::to_string(&envelope).unwrap()).unwrap();

        let error = fetch_manifest_source_with_fallback(&root, &source).unwrap_err();

        assert!(error.contains("signature"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_integrity_invalid_json_never_falls_back_to_sentinels() {
        let root = required_layer_test_root("manifest-integrity-invalid-json");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);
        let source = root.join("invalid-json.json");
        std::fs::write(&source, b"{not-json").unwrap();

        let error = fetch_manifest_source_with_fallback(&root, &source).unwrap_err();

        assert!(error.contains("manifest parse"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_integrity_invalid_cache_never_falls_back_to_sentinels() {
        let root = required_layer_test_root("manifest-integrity-invalid-cache");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);
        let cache = root.join("invalid-cache").join("manifest.json");
        std::fs::create_dir_all(cache.parent().unwrap()).unwrap();
        std::fs::write(&cache, b"{not-json").unwrap();

        let result = tauri::async_runtime::block_on(
            fetch_manifest_or_accept_preinstalled_layers(&[], &cache, &root),
        );
        let error = result.unwrap_err();

        assert!(error.contains("cached manifest parse"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_integrity_signed_invalid_manifest_never_falls_back_to_sentinels() {
        let root = required_layer_test_root("manifest-integrity-signed-invalid-manifest");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);
        let source = root.join("signed-invalid-manifest.json");
        let (mut envelope, _) = signed_release_envelope();
        envelope["distribution"]["layers"] = json!([{
            "id": "node",
            "title": "Node",
            "file": "node-runtime.tar.gz",
            "sha256": "0".repeat(64),
            "installPath": "../outside",
            "required": true
        }]);
        let public_key = resign_release_envelope(&mut envelope);
        std::fs::write(&source, serde_json::to_string(&envelope).unwrap()).unwrap();
        let cache = root.join("missing-cache").join("manifest.json");

        let result = tauri::async_runtime::block_on(
            fetch_manifest_or_accept_preinstalled_layers_with_public_key(
                &[source.to_string_lossy().to_string()],
                &cache,
                &root,
                &public_key,
            ),
        );
        let error = result.unwrap_err();

        assert!(error.contains("unsafe path component"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_integrity_invalid_source_uses_valid_signed_cache() {
        let root = required_layer_test_root("manifest-integrity-valid-cache");
        let _ = std::fs::remove_dir_all(&root);
        write_complete_required_layers(&root);
        let source = root.join("invalid-source.json");
        std::fs::write(&source, b"{not-json").unwrap();
        let cache = root.join("valid-cache").join("manifest.json");
        std::fs::create_dir_all(cache.parent().unwrap()).unwrap();
        let (envelope, public_key) = signed_release_envelope();
        std::fs::write(&cache, serde_json::to_string(&envelope).unwrap()).unwrap();

        let result = tauri::async_runtime::block_on(
            fetch_manifest_or_accept_preinstalled_layers_with_public_key(
                &[source.to_string_lossy().to_string()],
                &cache,
                &root,
                &public_key,
            ),
        );

        assert!(result.unwrap().is_some());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn distribution_setup_state_tracks_revision_run_and_rejects_stale_updates() {
        let mut tracker = DistributionSetupTracker::default();
        let initial = tracker.snapshot();
        assert_eq!(initial.revision, 0);
        assert_eq!(initial.run_id, 0);
        assert_eq!(initial.status, DistributionStatus::Idle);

        let started = tracker.start(vec![super::LayerInfo {
            id: "node".to_string(),
            title: "Node.js".to_string(),
            size: 10,
        }]);
        assert_eq!(started.revision, 1);
        assert_eq!(started.run_id, 1);
        assert_eq!(started.status, DistributionStatus::Running);
        let serialized = serde_json::to_value(&started).unwrap();
        assert_eq!(serialized["runId"], 1);
        assert_eq!(serialized["status"], "running");
        assert!(serialized.get("run_id").is_none());

        let progress = tracker
            .progress(
                started.run_id,
                super::ProgressPayload {
                    id: "node".to_string(),
                    title: "Node.js".to_string(),
                    phase: "download".to_string(),
                    downloaded: 5,
                    total: 10,
                    index: 1,
                    count: 1,
                },
            )
            .expect("current run progress must be accepted");
        assert_eq!(progress.revision, 2);
        assert_eq!(progress.run_id, 1);

        let done = tracker
            .done(started.run_id)
            .expect("current run completion must be accepted");
        assert_eq!(done.revision, 3);
        assert_eq!(done.status, DistributionStatus::Done);

        let restarted = tracker.start(Vec::new());
        assert_eq!(restarted.revision, 4);
        assert_eq!(restarted.run_id, 2);
        let before_stale = tracker.snapshot();
        assert!(tracker.progress(started.run_id, progress.progress.unwrap()).is_none());
        assert!(tracker.error(started.run_id, "late error".to_string()).is_none());
        assert_eq!(tracker.snapshot(), before_stale);
    }

    #[test]
    fn distribution_setup_snapshot_query_is_read_only() {
        let mut tracker = DistributionSetupTracker::default();
        tracker.start(Vec::new());

        let first = tracker.snapshot();
        let second = tracker.snapshot();

        assert_eq!(first, second);
        assert_eq!(first.revision, 1);
    }

    #[test]
    fn distribution_setup_state_records_prestart_error_and_clears_it_on_noop_recovery() {
        let mut tracker = DistributionSetupTracker::default();

        let failed = tracker.error_new_run("manifest unavailable".to_string());
        assert_eq!(failed.revision, 1);
        assert_eq!(failed.run_id, 1);
        assert_eq!(failed.status, DistributionStatus::Error);
        assert_eq!(failed.error.as_deref(), Some("manifest unavailable"));

        let recovered = tracker.idle_new_run();
        assert_eq!(recovered.revision, 2);
        assert_eq!(recovered.run_id, 2);
        assert_eq!(recovered.status, DistributionStatus::Idle);
        assert!(recovered.error.is_none());
        assert!(recovered.progress.is_none());
    }

    #[test]
    fn distribution_setup_state_persists_snapshot_before_notifying() {
        let state = super::DistributionSetupState::default();
        let mut notified = Vec::new();

        let result = state.transition_and_notify(
            |tracker| Some(tracker.start(Vec::new())),
            |snapshot| {
                assert_eq!(state.snapshot(), *snapshot);
                notified.push(snapshot.clone());
            },
        );

        assert_eq!(result.as_ref(), notified.first());
        assert_eq!(state.snapshot().revision, 1);
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
