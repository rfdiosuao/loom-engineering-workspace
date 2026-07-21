# OpenClaw 启动器 Git 与 CI/CD 管理方案

> 日期: 2026-05-05  
> 目的: 让启动器、授权服务器、文档和打包流程进入可追踪、可回滚、可自动验证的工程化管理。

> 当前平台选择: Gitee。  
> 本文保留通用 CI/CD 原则；具体接入步骤以 `docs/GITEE_SETUP.md` 为准。

---

## 1. 是否应该放进 Git

应该。

这个项目已经不是一次性脚本，而是一个会持续销售、更新、授权、打包和售后的商业软件。必须进入 Git 管理。

Git 要管理的是:

- 启动器源码。
- 授权服务器源码。
- 前端 UI 源码。
- Rust/Tauri 源码。
- Python Bridge 源码。
- 文档。
- 打包脚本。
- CI/CD 配置。
- 示例配置模板。

Git 不应该管理的是:

- `node_modules/`
- `src-tauri/target/`
- `dist/`
- `release/`
- 离线包 zip。
- 客户授权文件。
- 安装 ID。
- API Key。
- 授权服务器私钥。
- 授权服务器数据库。
- 管理后台 token。
- 本地日志和缓存。

---

## 2. 推荐仓库形态

当前建议使用 monorepo，也就是整个 `D:\Axiangmu\AUSTART` 作为一个仓库。

推荐结构:

```text
AUSTART/
  openclaw_new_launcher/      # 新版启动器
  license_server/             # 授权服务器
  docs/                       # 可选，全局文档
  scripts/                    # 全局打包/验证脚本
  release/                    # 不进 Git，只放本地打包结果
  .github/workflows/          # 如果使用 GitHub Actions
  .gitignore
```

为什么不建议只把 `openclaw_new_launcher` 单独做仓库:

- 启动器和授权服务器强相关。
- 授权协议、主题配置、商户配置需要一起演进。
- 打包脚本需要同时读取启动器和服务端配置。

后续如果产品变大，再拆成多个仓库也可以，但现在 monorepo 更稳。

---

## 3. 分支策略

推荐简单策略，不要太复杂。

### main

稳定交付分支。

规则:

- 只有通过测试的版本才能合入。
- 每次对外发包都从 `main` 打 tag。
- 不直接在 `main` 上做大改。

### develop

日常开发分支。

规则:

- 新功能先合到 `develop`。
- 每隔一段时间整理后合入 `main`。

### feature/*

功能分支。

示例:

- `feature/license-server-webui`
- `feature/storyboard-editor`
- `feature/portable-build-script`
- `feature/theme-system`

### hotfix/*

紧急修复分支。

示例:

- `hotfix/port-18790-conflict`
- `hotfix/api-config-sync`
- `hotfix/license-activate-error`

---

## 4. 版本号策略

推荐使用语义化版本:

```text
主版本.次版本.修订号
```

示例:

- `v2.0.0`: 当前可交付基础版。
- `v2.0.1`: 修复启动失败、端口冲突等 bug。
- `v2.1.0`: Bridge 模块化整理。
- `v2.2.0`: 打包自动化。
- `v3.0.0`: 授权验签迁移 Rust，商业架构升级。

每次发包都打 tag:

```text
launcher-v2.0.1
server-v1.0.0
```

如果启动器和授权服务器一起发版:

```text
release-v2.0.1
```

---

## 5. CI 应该做什么

CI 的目标不是“自动发包”，而是先保证代码不会坏。

每次 push 或 PR 时建议执行:

### 前端检查

目录:

`openclaw_new_launcher/`

命令:

```powershell
npm ci
npm run build
```

检查:

- TypeScript 是否通过。
- Vite build 是否通过。
- UI 源码是否能正常编译。

### Rust 检查

目录:

`openclaw_new_launcher/src-tauri/`

命令:

```powershell
cargo check
```

检查:

- Tauri/Rust 编译是否通过。
- Rust command 是否有类型错误。

### Python 检查

目录:

`openclaw_new_launcher/`

命令:

```powershell
python -m py_compile python/bridge.py python/core/*.py python/services/*.py
```

检查:

- Python 语法是否正确。
- Bridge 是否能被编译。

### 授权服务器检查

目录:

`license_server/`

命令:

```powershell
python -m py_compile server.py
```

检查:

- 授权服务器语法是否正确。

---

## 6. CD 应该做什么

CD 分两条线。

### 6.1 启动器发包

触发方式:

- 手动触发。
- 或 tag 触发，例如 `launcher-v2.0.1`。

产物:

- Tauri 安装包。
- 便携离线包 zip。
- SHA256 校验值。
- 发布说明。

注意:

离线包不进 Git。它应该作为 CI artifact 或 GitHub Release 附件保存。

### 6.2 授权服务器部署

触发方式:

- 手动触发。
- 或 `server-v*` tag 触发。

部署方式:

- 推荐 SSH key，不推荐密码。
- 推荐先备份数据库，再部署新代码。
- 推荐重启 systemd 服务。

服务器敏感信息放在 CI Secrets:

- `LICENSE_SERVER_HOST`
- `LICENSE_SERVER_USER`
- `LICENSE_SERVER_SSH_KEY`
- `LICENSE_SERVER_PORT`

不要把服务器密码写进仓库。

---

## 7. Secrets 管理

绝对不能进 Git 的内容:

- API Key。
- 授权服务器私钥。
- 数据库文件。
- 后台 token。
- SSH 密码。
- 客户授权码列表。

建议:

- 授权服务器私钥只放服务器 `/opt/openclaw-license/private_key.b64`。
- CI 使用 SSH key，不使用 root 密码。
- 如果曾经在聊天或脚本里暴露过服务器密码或 API Key，建议尽快更换。

---

## 8. 当前 .gitignore 评价

当前 `.gitignore` 已经挡住了大部分高风险内容:

- `node_modules/`
- `src-tauri/target/`
- `dist/`
- `release/`
- `*.zip`
- `license_server/private_key.b64`
- `license_server/license.db`
- `license_server/admin_token.txt`
- `data/license.json`
- `data/install_id.txt`

需要注意:

- `*.png` 当前被忽略，这会导致部分 UI 图片资源不会进 Git。
- 如果某些 PNG 是正式资源，例如 Logo、截图说明、图标源文件，需要单独用 `!路径` 放行。
- 交付包和截图仍然不应该进 Git。

---

## 9. 推荐 CI/CD 阶段

### 阶段一: 只做 CI

先做:

- 前端 build。
- Rust check。
- Python py_compile。
- 授权服务器 py_compile。

不做:

- 自动部署。
- 自动发包。

目标:

先确保每次改动不会把项目编译坏。

### 阶段二: 增加打包流水线

新增:

- Windows Runner 打包 Tauri。
- 生成离线包。
- 执行 release 清理检查。
- 上传 zip artifact。

目标:

减少人工打包失误。

### 阶段三: 增加授权服务器部署

新增:

- SSH 部署。
- 数据库备份。
- systemd 重启。
- 健康检查。

目标:

让授权服务器可控更新。

---

## 10. 建议新增文件

后续建议新增:

```text
.github/workflows/ci.yml
.github/workflows/build-launcher.yml
.github/workflows/deploy-license-server.yml
scripts/verify-release.ps1
scripts/build-portable.ps1
scripts/clean-release.ps1
docs/RELEASE_CHECKLIST.md
docs/MODULE_BOUNDARIES.md
```

其中最先做:

1. `docs/RELEASE_CHECKLIST.md`
2. `scripts/verify-release.ps1`
3. `.github/workflows/ci.yml`

---

## 11. 最终建议

建议立刻开始 Git 版本管理。

但不要立刻把 CI/CD 做满。

正确顺序是:

1. 先清理 Git 状态。
2. 确认哪些文件应该提交。
3. 做第一次基线提交。
4. 加 CI，只做编译检查。
5. 加发包脚本。
6. 加打包流水线。
7. 最后再做服务器自动部署。

这能让项目从“本机抢救状态”进入“可追踪、可回滚、可交付”的工程状态。
