# Mac 适配

Mac 端适配应从源码包开始。Windows 便携包中的 `node_modules`、Tauri target、桌面组件和路径规则不能原样复用。

## 先同步什么

| 内容 | 是否同步 | 说明 |
| --- | --- | --- |
| `openclaw_ui_integration/src` | 是 | React UI |
| `openclaw_ui_integration/src-tauri` | 是 | Tauri 配置需要 Mac 适配 |
| `openclaw_ui_integration/python` | 是 | Bridge 业务逻辑 |
| `scripts/` | 是 | 作为参考，Mac 需要对应脚本 |
| `docs/` | 是 | 包含二开文档和口径 |
| `release/` | 否 | 本地产物 |
| `node_modules/` | 否 | Mac 重新安装 |
| `src-tauri/target/` | 否 | Mac 重新构建 |
| 用户状态 | 否 | 授权、token、设备缓存必须排除 |

## Mac 适配检查点

1. Node 版本与前端构建。
2. Rust toolchain 与 Tauri 依赖。
3. Python Bridge 的依赖安装。
4. 路径分隔符和可执行文件后缀。
5. Tauri 权限和应用沙箱。
6. 桌面 RPA 组件是否有 Mac 版本。
7. 签名、公证和 Gatekeeper。
8. Release workflow 是否需要 macOS runner。

## 运行时层

Mac 不应该复用 Windows 的：

- `node.exe`。
- `.pyd`。
- Windows Electron 桌面组件。
- Windows Tauri bundle。
- PowerShell-only 启动脚本。

需要建立 Mac 自己的 runtime manifest。

## 打包边界

Mac 端先做到源码可构建，再考虑便携交付。

推荐阶段：

| 阶段 | 目标 |
| --- | --- |
| P0 | `npm install`、`npm run build` 通过 |
| P1 | Tauri dev 能启动 UI |
| P2 | Python Bridge 能启动和返回 health |
| P3 | OpenClaw runtime 能启动 |
| P4 | 手机控制可用 |
| P5 | 桌面 RPA 找到 Mac 替代方案 |
| P6 | 签名、公证、release |

## 给 Mac 同步方的说明

```text
请基于源码包适配，避免以 Windows release 包为源。
先保证 openclaw_ui_integration 的 npm build 和 Tauri dev。
Bridge、OpenClaw runtime、手机控制、桌面 RPA 分阶段接入。
提交前请排除 node_modules、target、release、授权文件、token 和本机缓存。
```

## 待确认

- Mac 桌面 RPA 是否继续使用 Luminode/SightFlow，还是另开组件。
- 是否需要 Apple Developer 证书和公证流程。
- Mac 包是否内置 OpenClaw runtime，还是首次启动下载。
- 是否需要同时支持 Apple Silicon 和 Intel。
