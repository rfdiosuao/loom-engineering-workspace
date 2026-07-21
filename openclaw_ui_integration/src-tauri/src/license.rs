use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::Serialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const LICENSE_PUBLIC_KEY_B64: &str = "njEIf3io24DAXRYVp37p2gIT5u2KZaWoGvBPD0JlTZ4=";

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
                .and_then(Value::as_str)
                .map(str::to_string),
            edition: payload
                .get("edition")
                .and_then(Value::as_str)
                .map(str::to_string),
            expires: payload
                .get("expires")
                .and_then(Value::as_str)
                .map(str::to_string),
            device_bound: payload
                .get("deviceId")
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
    match verify_license_payload(base_path, None) {
        Ok(payload) => LicenseStatus::ok(&payload),
        Err(error) => LicenseStatus::fail(error),
    }
}

pub fn ensure_authorized(base_path: &Path, feature: Option<&str>) -> Result<(), String> {
    verify_license_payload(base_path, feature).map(|_| ())
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

fn verify_signature(payload: &Value, signature_text: &str) -> Result<(), String> {
    let public_key_bytes = BASE64_STANDARD
        .decode(LICENSE_PUBLIC_KEY_B64)
        .map_err(|_| "授权公钥无效".to_string())?;
    let public_key_array: [u8; 32] = public_key_bytes
        .try_into()
        .map_err(|_| "授权公钥长度无效".to_string())?;
    let verifying_key =
        VerifyingKey::from_bytes(&public_key_array).map_err(|_| "授权公钥无效".to_string())?;

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

fn canonical_json(value: &Value) -> Result<Vec<u8>, String> {
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
        ('A'..='Z')
            .map(|letter| hash_device_payload(&format!("{}:\\|{}|openclaw-launcher", letter, serial))),
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
        canonical_json, device_id_candidates_for_serial, legacy_device_id_for_root_and_serial,
        volume_device_id_for_serial,
    };
    use serde_json::json;

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
}
