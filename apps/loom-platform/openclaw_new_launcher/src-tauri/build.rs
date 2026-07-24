fn main() {
    for name in [
        "LOOM_BRAND_ID",
        "LOOM_BRAND_DISPLAY_NAME",
        "LOOM_BRAND_BINARY_NAME",
        "LOOM_BRAND_UPDATE_CACHE_KEY",
        "LOOM_BRAND_UPDATE_FILE_PREFIX",
    ] {
        println!("cargo:rerun-if-env-changed={name}");
    }
    tauri_build::build()
}
