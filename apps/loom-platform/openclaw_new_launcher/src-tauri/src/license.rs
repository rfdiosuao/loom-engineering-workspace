use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::Serialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const LICENSE_PUBLIC_KEY_B64: &str = "njEIf3io24DAXRYVp37p2gIT5u2KZaWoGvBPD0JlTZ4=";
const LEGACY_LICENSE_SCHEMA: &str = "loom.license.v1";
const ACCOUNT_ENTITLEMENT_SCHEMA: &str = "loom.entitlement_lease.v1";
const ACCOUNT_ENTITLEMENT_ANCHOR_SCHEMA: &str = "loom.entitlement_anchor.v1";
const ACCOUNT_ENTITLEMENT_KEY_ID: &str = "openclaw-ed25519-v1";
const SESSION_BINDING_CONTEXT: &[u8] = b"loom-entitlement-session-v1\0";
const MAX_CLOCK_SKEW_SECONDS: i64 = 300;
const MAX_LEASE_WINDOW_SECONDS: i64 = 8 * 24 * 60 * 60;

#[derive(Debug, Clone, Serialize)]
pub struct LicenseStatus {
    pub authorized: bool,
    pub error: Option<String>,
    pub licensee: Option<String>,
    pub edition: Option<String>,
    pub expires: Option<String>,
    #[serde(rename = "deviceBound")]
    pub device_bound: bool,
}

impl LicenseStatus {
    fn ok(payload: &Map<String, Value>) -> Self {
        Self {
            authorized: true,
            error: None,
            licensee: payload
                .get("licensee")
                .or_else(|| payload.get("accountId"))
                .and_then(Value::as_str)
                .map(str::to_string),
            edition: payload
                .get("edition")
                .or_else(|| payload.get("plan"))
                .and_then(Value::as_str)
                .map(str::to_string),
            expires: payload
                .get("expires")
                .and_then(Value::as_str)
                .map(str::to_string)
                .or_else(|| {
                    payload
                        .get("expiresAt")
                        .and_then(Value::as_i64)
                        .and_then(|value| chrono::DateTime::<chrono::Utc>::from_timestamp(value, 0))
                        .map(|value| value.to_rfc3339())
                }),
            device_bound: payload
                .get("hostDeviceId")
                .or_else(|| payload.get("deviceId"))
                .and_then(Value::as_str)
                .map(|value| !value.trim().is_empty())
                .unwrap_or(false),
        }
    }

    fn fail(message: impl Into<String>) -> Self {
        Self {
            authorized: false,
            error: Some(message.into()),
            licensee: None,
            edition: None,
            expires: None,
            device_bound: false,
        }
    }
}

pub fn check_license(base_path: &Path) -> LicenseStatus {
    match verify_effective_payload(base_path, None) {
        Ok(payload) => LicenseStatus::ok(&payload),
        Err(error) => LicenseStatus::fail(error),
    }
}

pub fn ensure_authorized(base_path: &Path, feature: Option<&str>) -> Result<(), String> {
    verify_effective_payload(base_path, feature).map(|_| ())
}

fn verify_effective_payload(
    base_path: &Path,
    feature: Option<&str>,
) -> Result<Map<String, Value>, String> {
    let entitlement_path = account_entitlement_file(base_path);
    if entitlement_path.is_file() {
        return verify_account_entitlement_payload(base_path, feature);
    }
    if account_lease_seen(base_path)? {
        return Err("账号权益租约缺失，请重新登录模型账号并刷新权益".to_string());
    }
    verify_license_payload(base_path, feature)
}

fn verify_license_payload(
    base_path: &Path,
    feature: Option<&str>,
) -> Result<Map<String, Value>, String> {
    let license_path = license_file(base_path);
    let text = fs::read_to_string(&license_path).map_err(|_| "需要先完成授权激活".to_string())?;
    let mut license_value: Value =
        serde_json::from_str(&text).map_err(|_| "许可证文件格式无效".to_string())?;
    let payload = license_value
        .as_object_mut()
        .ok_or_else(|| "许可证文件格式无效".to_string())?;
    verify_legacy_license_domain(payload)?;
    let signature_text = payload
        .remove("signature")
        .and_then(|value| value.as_str().map(str::to_string))
        .ok_or_else(|| "许可证缺少签名".to_string())?;

    verify_signature(&Value::Object(payload.clone()), &signature_text)?;
    verify_install_id(base_path, payload)?;
    verify_device_id(base_path, payload)?;
    verify_expiry(payload)?;
    verify_feature(payload, feature)?;

    Ok(payload.clone())
}

fn verify_legacy_license_domain(payload: &Map<String, Value>) -> Result<(), String> {
    if let Some(schema) = payload.get("schema").and_then(Value::as_str) {
        if !schema.trim().is_empty() && schema != LEGACY_LICENSE_SCHEMA {
            return Err("许可证协议类型无效".to_string());
        }
    }
    for field in ["licenseId", "licensee", "installId", "expires"] {
        if payload
            .get(field)
            .and_then(Value::as_str)
            .map(str::trim)
            .unwrap_or_default()
            .is_empty()
        {
            return Err(format!("许可证缺少 {} 字段", field));
        }
    }
    if !payload.get("features").is_some_and(Value::is_array) {
        return Err("许可证能力字段无效".to_string());
    }
    chrono::NaiveDate::parse_from_str(
        payload
            .get("expires")
            .and_then(Value::as_str)
            .unwrap_or_default(),
        "%Y-%m-%d",
    )
    .map_err(|_| "许可证到期日期格式无效".to_string())?;
    Ok(())
}

fn verify_signature(payload: &Value, signature_text: &str) -> Result<(), String> {
    let public_key_bytes = BASE64_STANDARD
        .decode(LICENSE_PUBLIC_KEY_B64)
        .map_err(|_| "授权公钥无效".to_string())?;
    let public_key_array: [u8; 32] = public_key_bytes
        .try_into()
        .map_err(|_| "授权公钥长度无效".to_string())?;
    let verifying_key =
        VerifyingKey::from_bytes(&public_key_array).map_err(|_| "授权公钥无效".to_string())?;

    verify_signature_with_key(payload, signature_text, &verifying_key)
}

fn verify_signature_with_key(
    payload: &Value,
    signature_text: &str,
    verifying_key: &VerifyingKey,
) -> Result<(), String> {
    let signature_bytes = BASE64_STANDARD
        .decode(signature_text)
        .map_err(|_| "许可证签名格式无效".to_string())?;
    let signature =
        Signature::from_slice(&signature_bytes).map_err(|_| "许可证签名长度无效".to_string())?;

    let canonical = canonical_json(payload)?;
    verifying_key
        .verify(&canonical, &signature)
        .map_err(|_| "许可证签名校验失败".to_string())
}

fn verify_account_entitlement_payload(
    base_path: &Path,
    feature: Option<&str>,
) -> Result<Map<String, Value>, String> {
    let mut lease_value = read_json_value(
        &account_entitlement_file(base_path),
        "账号权益租约不存在，请重新登录",
        "账号权益租约文件格式无效",
    )?;
    let key_id = lease_value
        .get("keyId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if key_id != ACCOUNT_ENTITLEMENT_KEY_ID {
        return Err("账号权益租约使用了未知签名密钥，请更新 LOOM".to_string());
    }
    let public_key_bytes = BASE64_STANDARD
        .decode(LICENSE_PUBLIC_KEY_B64)
        .map_err(|_| "账号权益公钥无效".to_string())?;
    let public_key_array: [u8; 32] = public_key_bytes
        .try_into()
        .map_err(|_| "账号权益公钥长度无效".to_string())?;
    let verifying_key =
        VerifyingKey::from_bytes(&public_key_array).map_err(|_| "账号权益公钥无效".to_string())?;
    verify_account_entitlement_value_with_key(base_path, &mut lease_value, feature, &verifying_key)
}

fn verify_account_entitlement_value_with_key(
    base_path: &Path,
    lease_value: &mut Value,
    feature: Option<&str>,
    verifying_key: &VerifyingKey,
) -> Result<Map<String, Value>, String> {
    let lease = lease_value
        .as_object_mut()
        .ok_or_else(|| "账号权益租约文件格式无效".to_string())?;
    let required = [
        "schema",
        "accountId",
        "sessionBinding",
        "installId",
        "deviceId",
        "features",
        "limits",
        "issuedAt",
        "expiresAt",
        "offlineGraceUntil",
        "entitlementVersion",
        "keyId",
        "signature",
    ];
    if required.iter().any(|key| !lease.contains_key(*key)) {
        return Err("账号权益租约字段不完整，请重新登录".to_string());
    }
    if lease.get("schema").and_then(Value::as_str) != Some(ACCOUNT_ENTITLEMENT_SCHEMA) {
        return Err("账号权益租约版本不受支持，请更新 LOOM".to_string());
    }

    let signature_text = lease
        .remove("signature")
        .and_then(|value| value.as_str().map(str::to_string))
        .ok_or_else(|| "账号权益租约缺少签名".to_string())?;
    verify_signature_with_key(
        &Value::Object(lease.clone()),
        &signature_text,
        verifying_key,
    )
    .map_err(|_| "账号权益租约验签失败，文件可能被修改或复制".to_string())?;

    verify_account_install_id(base_path, lease)?;
    verify_account_host_device(base_path, lease)?;
    verify_account_session(base_path, lease)?;
    verify_account_time_window(base_path, lease)?;
    if !lease.get("features").is_some_and(Value::is_array)
        || !lease.get("limits").is_some_and(Value::is_object)
    {
        return Err("账号权益能力或额度字段无效".to_string());
    }
    verify_feature(lease, feature)
        .map_err(|_| format!("当前账号未开通 {} 能力", feature.unwrap_or_default()))?;

    Ok(lease.clone())
}

fn verify_account_install_id(base_path: &Path, lease: &Map<String, Value>) -> Result<(), String> {
    let licensed_install = lease
        .get("installId")
        .and_then(Value::as_str)
        .ok_or_else(|| "账号权益租约缺少安装 ID".to_string())?
        .trim();
    let local_install = fs::read_to_string(install_id_file(base_path))
        .map_err(|_| "本机安装 ID 不存在，请重新登录".to_string())?;
    if licensed_install != local_install.trim() {
        return Err("账号权益租约不属于当前安装目录".to_string());
    }
    Ok(())
}

fn verify_account_host_device(base_path: &Path, lease: &Map<String, Value>) -> Result<(), String> {
    let host_device_id = lease
        .get("hostDeviceId")
        .or_else(|| lease.get("deviceId"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    if host_device_id.is_empty()
        || !device_id_candidates(base_path)
            .iter()
            .any(|candidate| candidate == host_device_id)
    {
        return Err("账号权益租约不属于当前电脑或运行磁盘".to_string());
    }
    Ok(())
}

fn verify_account_session(base_path: &Path, lease: &Map<String, Value>) -> Result<(), String> {
    let session = read_json_value(
        &member_session_file(base_path),
        "账号会话不存在，请重新登录",
        "账号会话文件格式无效，请重新登录",
    )?;
    let source = session
        .get("source")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if !matches!(source, "newapi_account" | "heang_account") {
        return Err("当前账号会话来源无效，请重新登录".to_string());
    }
    let account_id = lease
        .get("accountId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let member_id = session
        .get("memberId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let user_id = session
        .get("newApi")
        .and_then(Value::as_object)
        .and_then(|value| value.get("userId"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    let stripped_member_id = member_id.strip_prefix("newapi:").unwrap_or(member_id);
    if account_id.is_empty()
        || ![member_id, stripped_member_id, user_id]
            .iter()
            .any(|candidate| !candidate.is_empty() && *candidate == account_id)
    {
        return Err("当前登录账号与权益租约不一致".to_string());
    }
    let session_token = session_secret(
        session
            .get("memberToken")
            .ok_or_else(|| "当前账号会话缺少安全凭据，请重新登录".to_string())?,
    )?;
    let mut binding_payload =
        Vec::with_capacity(SESSION_BINDING_CONTEXT.len() + session_token.len());
    binding_payload.extend_from_slice(SESSION_BINDING_CONTEXT);
    binding_payload.extend_from_slice(session_token.as_bytes());
    let expected_binding = hex_lower(&Sha256::digest(&binding_payload));
    let actual_binding = lease
        .get("sessionBinding")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if !constant_time_equal(actual_binding.as_bytes(), expected_binding.as_bytes()) {
        return Err("当前账号会话与权益租约不一致，请重新登录".to_string());
    }
    Ok(())
}

fn session_secret(value: &Value) -> Result<String, String> {
    if let Some(text) = value.as_str() {
        let normalized = text.trim();
        return if normalized.is_empty() {
            Err("当前账号会话缺少安全凭据，请重新登录".to_string())
        } else {
            Ok(normalized.to_string())
        };
    }
    let object = value
        .as_object()
        .ok_or_else(|| "当前账号会话安全凭据格式无效，请重新登录".to_string())?;
    if object.get("__loomSecret").and_then(Value::as_str) != Some("dpapi") {
        return Err("当前账号会话安全凭据格式无效，请重新登录".to_string());
    }
    let encrypted = BASE64_STANDARD
        .decode(
            object
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .map_err(|_| "当前账号会话安全凭据格式无效，请重新登录".to_string())?;
    let plaintext = dpapi_unprotect(&encrypted)?;
    String::from_utf8(plaintext)
        .map(|text| text.trim().to_string())
        .map_err(|_| "当前账号会话安全凭据无法读取，请重新登录".to_string())
        .and_then(|text| {
            if text.is_empty() {
                Err("当前账号会话缺少安全凭据，请重新登录".to_string())
            } else {
                Ok(text)
            }
        })
}

#[cfg(windows)]
fn dpapi_unprotect(data: &[u8]) -> Result<Vec<u8>, String> {
    use std::ptr;
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let input_len = u32::try_from(data.len())
        .map_err(|_| "当前账号会话安全凭据长度无效，请重新登录".to_string())?;
    let input = CRYPT_INTEGER_BLOB {
        cbData: input_len,
        pbData: data.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB::default();
    let ok = unsafe {
        CryptUnprotectData(
            &input,
            ptr::null_mut(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 || (output.cbData > 0 && output.pbData.is_null()) {
        return Err("当前账号会话安全凭据无法解密，请重新登录".to_string());
    }
    let plaintext = if output.cbData == 0 {
        Vec::new()
    } else {
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() }
    };
    if !output.pbData.is_null() {
        unsafe {
            LocalFree(output.pbData.cast());
        }
    }
    Ok(plaintext)
}

#[cfg(not(windows))]
fn dpapi_unprotect(_data: &[u8]) -> Result<Vec<u8>, String> {
    Err("当前平台无法读取 Windows 账号会话，请重新登录".to_string())
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

#[cfg(windows)]
fn system_uptime_ms() -> i64 {
    let uptime = unsafe { windows_sys::Win32::System::SystemInformation::GetTickCount64() };
    i64::try_from(uptime).unwrap_or(i64::MAX)
}

#[cfg(not(windows))]
fn system_uptime_ms() -> i64 {
    fs::read_to_string("/proc/uptime")
        .ok()
        .and_then(|value| value.split_whitespace().next().map(str::to_string))
        .and_then(|value| value.parse::<f64>().ok())
        .map(|value| (value * 1000.0).max(0.0) as i64)
        .unwrap_or_default()
}

fn effective_account_time(
    last_seen_at: i64,
    previous_uptime_ms: i64,
    now: i64,
    current_uptime_ms: i64,
) -> Result<i64, String> {
    if previous_uptime_ms > 0 && current_uptime_ms > 0 {
        if current_uptime_ms >= previous_uptime_ms {
            let elapsed_seconds = (current_uptime_ms - previous_uptime_ms) / 1000;
            return Ok(now.max(last_seen_at.saturating_add(elapsed_seconds)));
        }
        if last_seen_at > 0 && now <= last_seen_at {
            return Err("检测到电脑已重启但系统时间没有前进，请联网刷新账号权益".to_string());
        }
        return Ok(now.max(last_seen_at));
    }
    if last_seen_at > 0 && now + MAX_CLOCK_SKEW_SECONDS < last_seen_at {
        return Err("检测到系统时间明显回拨，请联网同步时间后重试".to_string());
    }
    Ok(now.max(last_seen_at))
}

fn verify_account_time_window(base_path: &Path, lease: &Map<String, Value>) -> Result<(), String> {
    let issued_at = integer_field(lease, "issuedAt")?;
    let expires_at = integer_field(lease, "expiresAt")?;
    let offline_grace_until = integer_field(lease, "offlineGraceUntil")?;
    let entitlement_version = integer_field(lease, "entitlementVersion")?;
    if !(0 < issued_at && issued_at < expires_at && expires_at <= offline_grace_until) {
        return Err("账号权益租约时间窗口无效".to_string());
    }
    if offline_grace_until - issued_at > MAX_LEASE_WINDOW_SECONDS {
        return Err("账号权益租约时间窗口异常".to_string());
    }

    let state_path = account_entitlement_state_file(base_path);
    if account_entitlement_file(base_path).is_file() && !state_path.is_file() {
        return Err("账号权益状态文件缺失，请联网刷新账号权益".to_string());
    }
    let state = read_optional_json_object(&state_path, "账号权益状态文件格式无效")?;
    let anchor = read_account_entitlement_anchor(base_path)?;
    verify_account_entitlement_anchor(lease, &state, &anchor)?;
    let now = chrono::Utc::now().timestamp();
    let last_seen_at = state
        .get("lastSeenAt")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let previous_uptime_ms = state
        .get("uptimeMs")
        .and_then(Value::as_i64)
        .or_else(|| anchor.get("uptimeMs").and_then(Value::as_i64))
        .unwrap_or_default();
    let effective_now =
        effective_account_time(last_seen_at, previous_uptime_ms, now, system_uptime_ms())?;
    if issued_at > effective_now + MAX_CLOCK_SKEW_SECONDS {
        return Err("账号权益租约签发时间晚于本机时间".to_string());
    }
    if effective_now > offline_grace_until {
        return Err("账号权益离线宽限已结束，请联网刷新账号".to_string());
    }
    let previous_account = state
        .get("accountId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let account_id = lease
        .get("accountId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let previous_version = state
        .get("entitlementVersion")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    if previous_account == account_id && entitlement_version < previous_version {
        return Err("检测到旧版本账号权益租约，可能已被撤销".to_string());
    }
    Ok(())
}

fn verify_account_entitlement_anchor(
    lease: &Map<String, Value>,
    state: &Map<String, Value>,
    anchor: &Map<String, Value>,
) -> Result<(), String> {
    let lease_hash = account_entitlement_lease_hash(lease)?;
    let account_id = lease
        .get("accountId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let install_id = lease
        .get("installId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let state_anchor_id = state
        .get("anchorId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let state_lease_hash = state
        .get("leaseHash")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let state_version = state
        .get("entitlementVersion")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let lease_version = integer_field(lease, "entitlementVersion")?;
    let state_last_seen = state
        .get("lastSeenAt")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let anchor_version = anchor
        .get("entitlementVersion")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let anchor_last_seen = anchor
        .get("lastSeenAt")
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let state_has_clock_anchor = state.contains_key("uptimeMs") || state.contains_key("bootMarker");
    let anchor_has_clock_anchor =
        anchor.contains_key("uptimeMs") || anchor.contains_key("bootMarker");
    let clock_anchor_matches = if state_has_clock_anchor && anchor_has_clock_anchor {
        state.get("uptimeMs").and_then(Value::as_i64)
            == anchor.get("uptimeMs").and_then(Value::as_i64)
            && state.get("bootMarker").and_then(Value::as_i64)
                == anchor.get("bootMarker").and_then(Value::as_i64)
            && state.get("uptimeMs").and_then(Value::as_i64).is_some()
            && state.get("bootMarker").and_then(Value::as_i64).is_some()
    } else {
        !state_has_clock_anchor && !anchor_has_clock_anchor
    };
    if anchor.get("schema").and_then(Value::as_str) != Some(ACCOUNT_ENTITLEMENT_ANCHOR_SCHEMA)
        || account_id.is_empty()
        || install_id.is_empty()
        || state_anchor_id.is_empty()
        || state_lease_hash.is_empty()
        || anchor.get("accountId").and_then(Value::as_str) != Some(account_id)
        || anchor.get("installId").and_then(Value::as_str) != Some(install_id)
        || anchor.get("anchorId").and_then(Value::as_str) != Some(state_anchor_id)
        || anchor.get("leaseHash").and_then(Value::as_str) != Some(state_lease_hash)
        || state_lease_hash != lease_hash
        || anchor_version != state_version
        || anchor_version != lease_version
        || anchor_last_seen < state_last_seen
        || !clock_anchor_matches
    {
        return Err("检测到账号权益状态被回滚或替换，请联网刷新账号权益".to_string());
    }
    Ok(())
}

fn account_entitlement_lease_hash(lease: &Map<String, Value>) -> Result<String, String> {
    Ok(hex_lower(&Sha256::digest(canonical_json(&Value::Object(
        lease.clone(),
    ))?)))
}

fn read_account_entitlement_anchor(base_path: &Path) -> Result<Map<String, Value>, String> {
    let path = account_entitlement_anchor_file(base_path)?;
    let protected = read_json_value(
        &path,
        "账号权益安全锚点缺失，请联网刷新账号权益",
        "账号权益安全锚点格式无效，请联网刷新账号权益",
    )?;
    #[cfg(test)]
    if protected.get("schema").and_then(Value::as_str) == Some(ACCOUNT_ENTITLEMENT_ANCHOR_SCHEMA) {
        return protected
            .as_object()
            .cloned()
            .ok_or_else(|| "账号权益安全锚点格式无效，请联网刷新账号权益".to_string());
    }
    let object = protected
        .as_object()
        .ok_or_else(|| "账号权益安全锚点格式无效，请联网刷新账号权益".to_string())?;
    if object.get("__loomSecret").and_then(Value::as_str) != Some("dpapi") {
        return Err("账号权益安全锚点未受本机保护，请联网刷新账号权益".to_string());
    }
    let encrypted = BASE64_STANDARD
        .decode(
            object
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .map_err(|_| "账号权益安全锚点格式无效，请联网刷新账号权益".to_string())?;
    let plaintext = dpapi_unprotect(&encrypted)
        .map_err(|_| "账号权益安全锚点无法读取，请联网刷新账号权益".to_string())?;
    serde_json::from_slice::<Value>(&plaintext)
        .map_err(|_| "账号权益安全锚点格式无效，请联网刷新账号权益".to_string())?
        .as_object()
        .cloned()
        .ok_or_else(|| "账号权益安全锚点格式无效，请联网刷新账号权益".to_string())
}

fn integer_field(payload: &Map<String, Value>, name: &str) -> Result<i64, String> {
    payload
        .get(name)
        .and_then(Value::as_i64)
        .ok_or_else(|| format!("账号权益租约字段 {} 无效", name))
}

fn read_json_value(
    path: &Path,
    missing_message: &str,
    invalid_message: &str,
) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|_| missing_message.to_string())?;
    serde_json::from_str(&text).map_err(|_| invalid_message.to_string())
}

fn read_optional_json_object(
    path: &Path,
    invalid_message: &str,
) -> Result<Map<String, Value>, String> {
    if !path.is_file() {
        return Ok(Map::new());
    }
    read_json_value(path, invalid_message, invalid_message)?
        .as_object()
        .cloned()
        .ok_or_else(|| invalid_message.to_string())
}

fn account_lease_seen(base_path: &Path) -> Result<bool, String> {
    let state = read_optional_json_object(
        &account_entitlement_state_file(base_path),
        "账号权益状态文件格式无效",
    )?;
    Ok(state
        .get("accountLeaseSeen")
        .and_then(Value::as_bool)
        .unwrap_or(false))
}

pub(crate) fn canonical_json(value: &Value) -> Result<Vec<u8>, String> {
    fn write_value(value: &Value, out: &mut String) -> Result<(), String> {
        match value {
            Value::Object(map) => {
                out.push('{');
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                for (index, key) in keys.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    out.push_str(
                        &serde_json::to_string(key)
                            .map_err(|_| "许可证键名序列化失败".to_string())?,
                    );
                    out.push(':');
                    if let Some(item) = map.get(*key) {
                        write_value(item, out)?;
                    }
                }
                out.push('}');
            }
            Value::Array(items) => {
                out.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    write_value(item, out)?;
                }
                out.push(']');
            }
            _ => out.push_str(
                &serde_json::to_string(value).map_err(|_| "许可证值序列化失败".to_string())?,
            ),
        }
        Ok(())
    }

    let mut out = String::new();
    write_value(value, &mut out)?;
    Ok(out.into_bytes())
}

fn verify_install_id(base_path: &Path, payload: &Map<String, Value>) -> Result<(), String> {
    let licensed_install = payload
        .get("installId")
        .and_then(Value::as_str)
        .ok_or_else(|| "许可证缺少安装 ID".to_string())?
        .trim();
    let local_install = fs::read_to_string(install_id_file(base_path))
        .map_err(|_| "本机安装 ID 不存在，请重新激活".to_string())?;
    if licensed_install != local_install.trim() {
        return Err("许可证不属于当前安装目录".to_string());
    }
    Ok(())
}

fn verify_device_id(base_path: &Path, payload: &Map<String, Value>) -> Result<(), String> {
    let Some(licensed_device) = payload.get("deviceId").and_then(Value::as_str) else {
        return Ok(());
    };
    if licensed_device.trim().is_empty() {
        return Ok(());
    }
    let device_candidates = device_id_candidates(base_path);
    if !device_candidates
        .iter()
        .any(|candidate| candidate == licensed_device)
    {
        return Err("许可证不属于当前运行磁盘".to_string());
    }
    Ok(())
}

fn verify_expiry(payload: &Map<String, Value>) -> Result<(), String> {
    let Some(expires) = payload.get("expires").and_then(Value::as_str) else {
        return Ok(());
    };
    if expires.trim().is_empty() {
        return Ok(());
    }
    let expires_date = chrono::NaiveDate::parse_from_str(expires, "%Y-%m-%d")
        .map_err(|_| "许可证过期日期无效".to_string())?;
    let today = chrono::Local::now().date_naive();
    if expires_date < today {
        return Err("许可证已过期".to_string());
    }
    Ok(())
}

fn verify_feature(payload: &Map<String, Value>, feature: Option<&str>) -> Result<(), String> {
    let Some(feature) = feature else {
        return Ok(());
    };
    let features = payload
        .get("features")
        .and_then(Value::as_array)
        .ok_or_else(|| "许可证缺少功能权限".to_string())?;
    if features.iter().any(|item| item.as_str() == Some(feature)) {
        return Ok(());
    }
    Err(format!("许可证未开通 {} 功能", feature))
}

pub fn device_id(base_path: &Path) -> String {
    let root = drive_root(base_path);
    let raw = match volume_serial(&root) {
        Some(serial) => format!("volume:{}|openclaw-launcher", serial),
        None => format!("fallback:{}|openclaw-launcher", fallback_serial()),
    };
    hash_device_payload(&raw)
}

fn legacy_device_id(base_path: &Path) -> String {
    let root = drive_root(base_path);
    let serial = volume_serial(&root).unwrap_or_else(|| fallback_serial());
    hash_device_payload(&format!("{}|{}|openclaw-launcher", root, serial))
}

fn legacy_device_id_candidates(base_path: &Path) -> Vec<String> {
    let root = drive_root(base_path);
    let serial = volume_serial(&root).unwrap_or_else(|| fallback_serial());
    ('A'..='Z')
        .map(|letter| hash_device_payload(&format!("{}:\\|{}|openclaw-launcher", letter, serial)))
        .collect()
}

fn device_id_candidates(base_path: &Path) -> Vec<String> {
    let current = device_id(base_path);
    let legacy = legacy_device_id(base_path);
    let mut candidates = vec![current, legacy];
    candidates.extend(legacy_device_id_candidates(base_path));
    candidates.sort();
    candidates.dedup();
    candidates
}

#[cfg(test)]
fn device_id_candidates_for_serial(serial: &str) -> Vec<String> {
    let mut candidates = vec![hash_device_payload(&format!(
        "volume:{}|openclaw-launcher",
        serial
    ))];
    candidates.extend(
        ('A'..='Z').map(|letter| {
            hash_device_payload(&format!("{}:\\|{}|openclaw-launcher", letter, serial))
        }),
    );
    candidates.sort();
    candidates.dedup();
    candidates
}

#[cfg(test)]
fn legacy_device_id_for_root_and_serial(root: &str, serial: &str) -> String {
    hash_device_payload(&format!("{}|{}|openclaw-launcher", root, serial))
}

#[cfg(test)]
fn volume_device_id_for_serial(serial: &str) -> String {
    hash_device_payload(&format!("volume:{}|openclaw-launcher", serial))
}

fn hash_device_payload(raw: &str) -> String {
    let digest = Sha256::digest(raw.as_bytes());
    hex_lower(&digest)
}

fn license_file(base_path: &Path) -> PathBuf {
    base_path.join("data").join("license.json")
}

fn account_entitlement_file(base_path: &Path) -> PathBuf {
    base_path.join("data").join("account-entitlement.json")
}

fn account_entitlement_state_file(base_path: &Path) -> PathBuf {
    base_path
        .join("data")
        .join("account-entitlement-state.json")
}

fn account_entitlement_anchor_file(base_path: &Path) -> Result<PathBuf, String> {
    let install_id = fs::read_to_string(install_id_file(base_path))
        .map_err(|_| "本机安装 ID 不存在，请重新登录".to_string())?;
    let install_hash = hex_lower(&Sha256::digest(install_id.trim().as_bytes()));
    #[cfg(test)]
    let local_app_data = base_path.join(".test-local-app-data");
    #[cfg(not(test))]
    let local_app_data = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("USERPROFILE")
                .map(|home| PathBuf::from(home).join(".local").join("share"))
        })
        .ok_or_else(|| "无法定位本机账号权益安全目录".to_string())?;
    Ok(local_app_data
        .join("LOOM")
        .join("entitlements")
        .join(format!("{install_hash}.json")))
}

fn member_session_file(base_path: &Path) -> PathBuf {
    base_path
        .join("data")
        .join(".openclaw")
        .join("launcher")
        .join("member-session.json")
}

fn install_id_file(base_path: &Path) -> PathBuf {
    base_path.join("data").join("install_id.txt")
}

fn drive_root(base_path: &Path) -> String {
    let path = base_path
        .canonicalize()
        .unwrap_or_else(|_| base_path.to_path_buf());
    let text = path.to_string_lossy().replace('/', "\\");
    let text = text.strip_prefix(r"\\?\").unwrap_or(&text);
    let bytes = text.as_bytes();
    if bytes.len() >= 2 && bytes[1] == b':' {
        return format!("{}\\", &text[..2]);
    }
    text.to_string()
}

#[cfg(windows)]
fn volume_serial(root: &str) -> Option<String> {
    use std::ptr;
    use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationW;

    let wide: Vec<u16> = root.encode_utf16().chain(std::iter::once(0)).collect();
    let mut serial = 0u32;
    let ok = unsafe {
        GetVolumeInformationW(
            wide.as_ptr(),
            ptr::null_mut(),
            0,
            &mut serial,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            0,
        )
    };
    if ok == 0 {
        None
    } else {
        Some(serial.to_string())
    }
}

#[cfg(not(windows))]
fn volume_serial(_root: &str) -> Option<String> {
    None
}

fn fallback_serial() -> String {
    "0".to_string()
}

fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::{
        account_entitlement_anchor_file, canonical_json, device_id,
        device_id_candidates_for_serial, effective_account_time, ensure_authorized, hex_lower,
        legacy_device_id_for_root_and_serial, verify_account_entitlement_value_with_key,
        verify_legacy_license_domain, volume_device_id_for_serial,
    };
    use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
    use base64::Engine;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_root(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "loom-license-{name}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(root.join("data").join(".openclaw").join("launcher")).unwrap();
        root
    }

    fn signed_account_lease(root: &PathBuf, signing_key: &SigningKey) -> Value {
        fs::write(root.join("data").join("install_id.txt"), "install-test").unwrap();
        fs::write(
            root.join("data")
                .join(".openclaw")
                .join("launcher")
                .join("member-session.json"),
            serde_json::to_vec(&json!({
                "source": "newapi_account",
                "memberId": "newapi:account-7",
                "memberToken": "session-token-7",
                "newApi": {"userId": "account-7"}
            }))
            .unwrap(),
        )
        .unwrap();
        let now = chrono::Utc::now().timestamp();
        let session_binding = hex_lower(&Sha256::digest(
            b"loom-entitlement-session-v1\0session-token-7",
        ));
        let mut lease = json!({
            "schema": "loom.entitlement_lease.v1",
            "accountId": "account-7",
            "sessionBinding": session_binding,
            "installId": "install-test",
            "deviceId": device_id(root),
            "hostDeviceId": device_id(root),
            "features": ["matrix.devices"],
            "limits": {"devices": 1},
            "issuedAt": now - 10,
            "expiresAt": now + 3600,
            "offlineGraceUntil": now + 7200,
            "entitlementVersion": 4,
            "keyId": "test-key"
        });
        let signature = signing_key.sign(&canonical_json(&lease).unwrap());
        lease.as_object_mut().unwrap().insert(
            "signature".to_string(),
            Value::String(BASE64_STANDARD.encode(signature.to_bytes())),
        );
        lease
    }

    fn write_account_anchor(root: &PathBuf, lease: &Value) {
        let mut unsigned = lease.clone();
        unsigned.as_object_mut().unwrap().remove("signature");
        let lease_hash = hex_lower(&Sha256::digest(canonical_json(&unsigned).unwrap()));
        let version = unsigned
            .get("entitlementVersion")
            .and_then(Value::as_i64)
            .unwrap();
        let now = chrono::Utc::now().timestamp();
        let anchor_id = "test-anchor-id";
        fs::write(
            root.join("data").join("account-entitlement-state.json"),
            serde_json::to_vec(&json!({
                "accountLeaseSeen": true,
                "accountId": "account-7",
                "entitlementVersion": version,
                "lastSeenAt": now,
                "anchorId": anchor_id,
                "leaseHash": lease_hash,
            }))
            .unwrap(),
        )
        .unwrap();
        let anchor_path = account_entitlement_anchor_file(root).unwrap();
        fs::create_dir_all(anchor_path.parent().unwrap()).unwrap();
        fs::write(
            anchor_path,
            serde_json::to_vec(&json!({
                "schema": "loom.entitlement_anchor.v1",
                "accountId": "account-7",
                "installId": "install-test",
                "entitlementVersion": version,
                "lastSeenAt": now,
                "anchorId": anchor_id,
                "leaseHash": lease_hash,
            }))
            .unwrap(),
        )
        .unwrap();
    }

    #[test]
    fn device_id_candidates_accept_old_drive_letters_and_new_volume_id() {
        let serial = "123456789";
        let candidates = device_id_candidates_for_serial(serial);

        assert!(candidates.contains(&volume_device_id_for_serial(serial)));
        assert!(candidates.contains(&legacy_device_id_for_root_and_serial("D:\\", serial)));
        assert!(candidates.contains(&legacy_device_id_for_root_and_serial("E:\\", serial)));
        assert!(candidates.contains(&legacy_device_id_for_root_and_serial("Z:\\", serial)));
    }

    #[test]
    fn canonical_json_sorts_keys_without_ascii_escaping() {
        let value = json!({
            "b": 2,
            "a": "中文",
            "arr": [{"z": true, "a": null}]
        });
        let text = String::from_utf8(canonical_json(&value).unwrap()).unwrap();
        assert_eq!(text, r#"{"a":"中文","arr":[{"a":null,"z":true}],"b":2}"#);
    }

    #[test]
    fn frozen_wall_clock_still_advances_with_system_uptime() {
        let effective = effective_account_time(1_000, 120_000, 1_000, 360_000).unwrap();

        assert_eq!(effective, 1_240);
    }

    #[test]
    fn reboot_with_non_advancing_wall_clock_requires_online_refresh() {
        let error = effective_account_time(1_000, 600_000, 1_000, 10_000).unwrap_err();

        assert!(error.contains("联网刷新"));
    }

    #[test]
    fn account_entitlement_payload_cannot_be_replayed_as_legacy_license() {
        let payload = json!({
            "schema": "loom.entitlement_lease.v1",
            "accountId": "account-7",
            "installId": "install-test",
            "expiresAt": chrono::Utc::now().timestamp() + 3600,
            "features": ["matrix.devices"],
        });

        let error = verify_legacy_license_domain(payload.as_object().unwrap()).unwrap_err();

        assert!(error.contains("协议类型"));
    }

    #[test]
    fn migrated_account_never_falls_back_to_legacy_license() {
        let root = test_root("migration-barrier");
        fs::write(
            root.join("data").join("account-entitlement-state.json"),
            br#"{"accountLeaseSeen":true,"entitlementVersion":9}"#,
        )
        .unwrap();
        fs::write(
            root.join("data").join("license.json"),
            br#"{"edition":"legacy"}"#,
        )
        .unwrap();

        let error = ensure_authorized(&root, Some("matrix.devices")).unwrap_err();

        assert!(error.contains("账号权益"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn signed_account_lease_binds_account_install_host_and_feature() {
        let root = test_root("signed-account");
        let signing_key = SigningKey::from_bytes(&[7u8; 32]);
        let mut lease = signed_account_lease(&root, &signing_key);
        write_account_anchor(&root, &lease);

        let verified = verify_account_entitlement_value_with_key(
            &root,
            &mut lease,
            Some("matrix.devices"),
            &signing_key.verifying_key(),
        )
        .unwrap();

        assert_eq!(
            verified.get("accountId").and_then(Value::as_str),
            Some("account-7")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn restoring_old_account_files_cannot_roll_back_external_anchor() {
        let root = test_root("account-anchor-rollback");
        let signing_key = SigningKey::from_bytes(&[12u8; 32]);
        let mut old_lease = signed_account_lease(&root, &signing_key);
        write_account_anchor(&root, &old_lease);
        let mut newer_lease = signed_account_lease(&root, &signing_key);
        newer_lease
            .as_object_mut()
            .unwrap()
            .insert("entitlementVersion".to_string(), Value::Number(5.into()));
        let mut unsigned = newer_lease.clone();
        unsigned.as_object_mut().unwrap().remove("signature");
        let signature = signing_key.sign(&canonical_json(&unsigned).unwrap());
        newer_lease.as_object_mut().unwrap().insert(
            "signature".to_string(),
            Value::String(BASE64_STANDARD.encode(signature.to_bytes())),
        );
        write_account_anchor(&root, &newer_lease);

        let error = verify_account_entitlement_value_with_key(
            &root,
            &mut old_lease,
            Some("matrix.devices"),
            &signing_key.verifying_key(),
        )
        .unwrap_err();

        assert!(error.contains("回滚") || error.contains("替换"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn persisted_account_lease_requires_monotonic_state_file() {
        let root = test_root("missing-account-state");
        let signing_key = SigningKey::from_bytes(&[8u8; 32]);
        let mut lease = signed_account_lease(&root, &signing_key);
        fs::write(
            root.join("data").join("account-entitlement.json"),
            serde_json::to_vec(&lease).unwrap(),
        )
        .unwrap();

        let error = verify_account_entitlement_value_with_key(
            &root,
            &mut lease,
            Some("matrix.devices"),
            &signing_key.verifying_key(),
        )
        .unwrap_err();

        assert!(error.contains("状态文件"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn copied_account_lease_is_rejected_on_another_host() {
        let root = test_root("copied-account");
        let signing_key = SigningKey::from_bytes(&[9u8; 32]);
        let mut lease = signed_account_lease(&root, &signing_key);
        lease.as_object_mut().unwrap().insert(
            "hostDeviceId".to_string(),
            Value::String("another-host".to_string()),
        );
        let signature_payload = {
            let mut payload = lease.clone();
            payload.as_object_mut().unwrap().remove("signature");
            payload
        };
        let signature = signing_key.sign(&canonical_json(&signature_payload).unwrap());
        lease.as_object_mut().unwrap().insert(
            "signature".to_string(),
            Value::String(BASE64_STANDARD.encode(signature.to_bytes())),
        );

        let error = verify_account_entitlement_value_with_key(
            &root,
            &mut lease,
            Some("matrix.devices"),
            &signing_key.verifying_key(),
        )
        .unwrap_err();

        assert!(error.contains("当前电脑"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn account_lease_is_rejected_after_session_token_changes() {
        let root = test_root("session-binding");
        let signing_key = SigningKey::from_bytes(&[11u8; 32]);
        let mut lease = signed_account_lease(&root, &signing_key);
        fs::write(
            root.join("data")
                .join(".openclaw")
                .join("launcher")
                .join("member-session.json"),
            serde_json::to_vec(&json!({
                "source": "newapi_account",
                "memberId": "newapi:account-7",
                "memberToken": "different-session-token",
                "newApi": {"userId": "account-7"}
            }))
            .unwrap(),
        )
        .unwrap();

        let error = verify_account_entitlement_value_with_key(
            &root,
            &mut lease,
            Some("matrix.devices"),
            &signing_key.verifying_key(),
        )
        .unwrap_err();

        assert!(error.contains("会话"));
        fs::remove_dir_all(root).unwrap();
    }
}
