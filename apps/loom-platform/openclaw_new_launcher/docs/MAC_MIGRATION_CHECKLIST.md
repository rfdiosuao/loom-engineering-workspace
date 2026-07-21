# Mac 迁移验收清单

这份清单给 Mac 迁移人员使用，用来判断源码是否真正跑通，而不是只编译通过。

## 1. 解压后先确认

源码包不应包含：

- `node_modules`
- `dist`
- `src-tauri/target`
- `release`
- `data/license.json`
- `data/install_id.txt`
- 任何真实 API Key

## 2. 基础环境

在 Mac 上确认：

```bash
xcode-select -p
rustc --version
cargo --version
node -v
npm -v
python3 --version
```

建议：

- macOS 13+
- Node.js 20 或 22
- Python 3.11+
- Rust stable

## 3. 前端和 Tauri

进入：

```bash
cd openclaw_new_launcher
npm ci
npm run build
npm run tauri dev
```

必须确认：

- 窗口能打开。
- 不白屏。
- 标题、Logo、主题正常。
- 暗色 / 浅色切换不闪烁。

## 4. Python Bridge

开发环境里可以先用系统 Python：

```bash
python3 python/bridge.py
```

看到类似输出才算 Bridge 能启动：

```text
BRIDGE_PORT=18791
BRIDGE_TOKEN=...
```

如果失败，优先检查：

- Python 依赖是否缺失。
- `PYTHONPATH` 是否指向 `openclaw_new_launcher/python`。
- Tauri 资源路径是否和 Windows 不同。

## 5. OpenClaw 本体

Mac 源码包默认不带 Windows 便携包里的离线 OpenClaw 依赖，需要在 Mac 上重新准备：

```bash
npm install openclaw@latest
npm install @larksuite/openclaw-lark@latest
npm install @tencent-weixin/openclaw-weixin@latest
```

然后确认：

```bash
node node_modules/openclaw/openclaw.mjs --version
```

## 6. 启动器功能验收

按顺序测试：

1. 未授权启动时进入授权页。
2. 未授权也能打开环境诊断。
3. 环境诊断可以运行。
4. 一键修复不会报错。
5. 授权码激活成功后能进入服务日志。
6. API 配置能保存。
7. 启动核心服务后能打开 `http://127.0.0.1:18790`。
8. AI 生图能调用。
9. AI 视频能生成、预览、下载。
10. 广告视频工作台能保存分镜。
11. 飞书机器人能安装并扫码或手动配置。
12. 微信机器人能安装并扫码绑定。

## 7. 打包验收

先打 `.app`：

```bash
npm run tauri build -- --bundles app
```

再打 `.dmg`：

```bash
npm run tauri build -- --bundles dmg
```

产物位置通常是：

```text
src-tauri/target/release/bundle/
```

必须拿另一台 Mac 重新测试一次，不能只在开发机上测试。

## 8. 正式交付前

正式给客户前需要决定：

- 是否内置 Mac 版 Node。
- 是否内置 Python runtime。
- 是否做 Apple Developer 签名。
- 是否做 Notarization 公证。
- `OpenClawFiles/` 放在 `.app` 外部还是 `.app/Contents/Resources` 内部。

建议先做外部 `OpenClawFiles/`，便于排查和替换依赖；稳定后再考虑收进 `.app`。
