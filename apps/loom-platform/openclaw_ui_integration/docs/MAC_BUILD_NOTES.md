# Mac 源码编译注意事项

这份源码包用于把启动器迁移到 macOS 上编译和验证。它不是 Windows 便携包，也不包含 Windows 的 `node_modules`、离线运行时、授权文件、API Key 或本机缓存。

## 1. 适用目标

- 目标产物：macOS `.app` / `.dmg`
- 技术栈：Tauri 2 + React + TypeScript + Python Bridge + OpenClaw Node 本体
- 建议先跑通开发版，再做离线安装包

## 2. Mac 上需要准备

建议环境：

- macOS 13 或更新
- Xcode Command Line Tools
- Rust 1.77.2 或更新
- Node.js 20/22
- Python 3.11 或更新

基础安装：

```bash
xcode-select --install

# 安装 Rust 后确认版本
rustc --version
cargo --version

# 安装 Node 后确认版本
node -v
npm -v

# 确认 Python
python3 --version
```

## 3. 第一次编译流程

进入源码目录：

```bash
cd openclaw_new_launcher
npm ci
npm run build
npm run tauri dev
```

开发版可以打开后，再尝试打包：

```bash
npm run tauri build -- --bundles app,dmg
```

产物一般在：

```text
src-tauri/target/release/bundle/
```

## 4. 重要：不要复用 Windows 依赖

Mac 不能直接复用 Windows 上的这些目录：

- `node_modules`
- `dist`
- `src-tauri/target`
- Windows 便携包里的 `node`
- Windows 便携包里的 `.exe`

这些必须在 Mac 上重新安装或重新编译。

## 5. OpenClaw 本体和插件

当前源码包不内置 Mac 版 OpenClaw 运行依赖。Mac 上如果要完整启动核心服务，需要在 Mac 环境重新安装 OpenClaw 本体和机器人插件。

建议在 Mac 源码目录中安装：

```bash
npm install openclaw@latest
npm install @larksuite/openclaw-lark@latest
npm install @tencent-weixin/openclaw-weixin@latest
```

注意：

- 飞书插件需要实测二维码扫码和 App ID/App Secret 手动配置。
- 微信插件只能扫码绑定，不能用 ID/Key 绑定。
- 微信插件在 Mac 上是否完全可用，要以真实扫码测试为准。

## 6. 当前源码里的 Mac 适配状态

下面这些底层路径已经做过跨平台候选，Mac 迁移时不需要再从零改：

- `python/core/paths.py`
  - Windows 查 `node.exe`，Mac / Linux 查 `node`。
  - 支持 `node/` 和 `SystemData/.core/node/` 两套目录。
  - 会把 Node 和 `node_modules/.bin` 加入子进程 PATH。

- `src-tauri/src/lib.rs`
  - Windows 查 `python.exe/python`。
  - Mac / Linux 查 `python3/python`。
  - Bridge 会优先从随包资源里找 Python，再回退系统 Python。

- 机器人插件命令
  - 前端插件命令会按当前系统生成 PATH 分隔符。
  - Windows 用 `;`，Mac / Linux 用 `:`。
  - Mac 仍需实机验证飞书 / 微信二维码输出和扫码流程。

仍需在 Mac 上实测确认的风险：

- Tauri `.app` 资源目录和 `OpenClawFiles/` 的相对位置。
- 是否内置 Mac 版 Node，还是要求客户机预装 Node。
- 是否内置 Python runtime，还是要求客户机预装 Python 3。
- 微信插件在 Mac 上的扫码登录是否稳定。
- `.app` / `.dmg` 是否需要签名和公证后才能顺利打开。

## 7. Mac 离线包建议结构

后续做 Mac 离线包时，建议不要把所有散文件铺在根目录。推荐结构：

```text
OpenClaw.app
OpenClawFiles/
  data/
  python/
  scripts/
  node/
  node_modules/
```

其中：

- `OpenClaw.app` 是 Tauri 产物。
- `OpenClawFiles` 放 OpenClaw 本体、Python Bridge、主题、脚本和离线依赖。
- `data/.openclaw` 不要内置授权文件，避免客户无需激活即可使用。

## 8. 签名和分发

Mac 客户机打开未签名应用时，可能被系统拦截。内部测试可以右键打开，但正式交付建议准备：

- Apple Developer 账号
- Developer ID Application 证书
- 应用签名
- Notarization 公证

如果不做签名公证，客户可能看到“无法验证开发者”之类的提示。

## 9. 验收顺序

建议按这个顺序验收，不要一口气测全部：

1. `npm run build` 通过。
2. `npm run tauri dev` 能打开窗口。
3. 授权页能打开，未授权时不能启动核心服务。
4. API 配置能保存，重启后仍可读取。
5. 核心服务能启动，OpenClaw 页面能打开。
6. AI 生图能调用。
7. AI 视频能生成并预览/下载。
8. 广告视频工作台能保存分镜和素材。
9. 飞书插件能安装、扫码或手动配置。
10. 微信插件能安装并扫码绑定。
11. `.app` / `.dmg` 在另一台 Mac 上测试。

## 10. 不要打进源码包的内容

这些内容不能进入发给别人编译的源码包：

- `data/license.json`
- `data/install_id.txt`
- `data/.openclaw`
- `imgapi_config.json`
- `video_config.json`
- 任何 API Key
- 任何授权码服务器密钥
- `node_modules`
- `dist`
- `src-tauri/target`
- release 目录里的历史包

## 11. 推荐开发节奏

第一阶段先做“Mac 开发版能启动”：

- 改掉 `node.exe` / `python.exe` 平台硬编码。
- 使用 Mac 本机 Node/Python 跑通核心服务。
- 验证 OpenClaw 页面能打开。

第二阶段做“Mac 离线包”：

- 内置 Mac 版 Node。
- 内置或声明 Python 运行时。
- 重新安装 Mac 版 `openclaw` 和插件依赖。
- 打包 `.app` / `.dmg`。

第三阶段做“正式交付包”：

- 应用签名。
- Notarization。
- 空机器验收。
- 授权流程验收。
