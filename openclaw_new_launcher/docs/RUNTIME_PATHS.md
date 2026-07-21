# 运行时路径规范

本文档约定启动器、OpenClaw 本体、Node、Python Bridge、插件和用户数据在便携包里的位置，后续 Windows / Mac 打包都按这个规则走。

## 1. 便携包根目录

交付给客户时，根目录只保留：

- `OpenClaw.exe`
- `OpenClawFiles/`

所有依赖、配置模板、脚本、Node、OpenClaw 本体都放进 `OpenClawFiles/`，避免客户看到一堆散文件。

## 2. OpenClawFiles 目录

标准结构：

```text
OpenClawFiles/
├─ _up_/                 # 启动器 Bridge、主题等内置资源
├─ data/                 # 客户运行时数据
├─ node/                 # 离线 Node runtime
├─ node_modules/         # OpenClaw 本体和离线插件包
├─ scripts/              # 启动器辅助脚本
├─ start.js              # OpenClaw 启动入口
└─ package.json
```

兼容结构：

```text
OpenClawFiles/
└─ SystemData/.core/     # 未来可把底层 runtime 收进隐藏式核心目录
   ├─ node/
   └─ node_modules/
```

当前代码会优先查找 `SystemData/.core`，找不到再回退到根目录下的 `node` 和 `node_modules`。

## 3. Node 查找规则

Windows：

- `SystemData/.core/node/node.exe`
- `node/node.exe`

Mac / Linux：

- `SystemData/.core/node/node`
- `node/node`

如果本地离线 Node 不存在，才允许回退到系统 `node`。

## 4. Python Bridge 查找规则

Tauri 先查：

- `python/bridge.py`
- `_up_/python/bridge.py`
- `OpenClawFiles/_up_/python/bridge.py`

Python 可执行文件优先从 Bridge 同目录或 `python-runtime` 里找。

Windows 候选：

- `python.exe`
- `python`

Mac / Linux 候选：

- `python3`
- `python`

## 5. OpenClaw 数据目录

运行时只允许写入：

```text
OpenClawFiles/data/
```

OpenClaw 状态目录：

```text
OpenClawFiles/data/.openclaw/
```

关键环境变量：

- `OPENCLAW_STATE_DIR=OpenClawFiles/data/.openclaw`
- `OPENCLAW_CONFIG_PATH=OpenClawFiles/data/.openclaw/openclaw.json`
- `OPENCLAW_HOME=OpenClawFiles/data`

## 6. 禁止内置客户私密数据

正式交付包不得包含：

- `data/license.json`
- `data/install_id.txt`
- `imgapi_config.json` 里的真实 API Key
- `video_config.json` 里的真实 DashScope Key
- 客户扫码后的微信 / 飞书账号缓存

这些必须由客户在自己的机器上激活或填写。

## 7. 开发原则

- 新增依赖时，先明确它属于「启动器资源」「OpenClaw 本体」「客户运行数据」哪一类。
- 不要在业务代码里直接写死 `node.exe`、`python.exe`、`;`、`\`。
- 路径解析集中在：
  - Python：`python/core/paths.py`
  - Rust：`src-tauri/src/lib.rs`
  - 前端插件命令：`src/components/dialogs/botPluginRuntime.ts`
- 打包脚本可以是 Windows 专用，但运行时查找逻辑必须为 Mac 预留候选。
