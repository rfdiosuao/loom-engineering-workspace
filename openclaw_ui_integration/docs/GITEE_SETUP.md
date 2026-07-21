# Gitee 仓库与流水线接入说明

> 日期: 2026-05-05  
> 目标: 使用 Gitee 管理源码，用 Gitee Go 或本地脚本做持续检查，后续再逐步接入自动打包和服务器部署。

---

## 1. 仓库选择

建议在 Gitee 新建一个私有仓库。

推荐仓库名:

```text
openclaw-usb-launcher
```

推荐仓库根目录:

```text
D:\Axiangmu\AUSTART
```

原因:

- 当前 Git 根目录已经是 `D:\Axiangmu\AUSTART`。
- `openclaw_new_launcher` 和 `license_server` 是同一个产品的客户端和服务端。
- 授权协议、主题配置、打包脚本需要一起演进。

---

## 2. 第一次推送前必须确认

绝对不能推送:

- `release/`
- `node_modules/`
- `openclaw_new_launcher/dist/`
- `openclaw_new_launcher/src-tauri/target/`
- `license_server/private_key.b64`
- `license_server/license.db`
- `license_server/admin_token.txt`
- `data/license.json`
- `data/install_id.txt`
- 客户 API Key
- 客户授权码批量表

当前 `.gitignore` 已经覆盖了大部分风险项，但第一次推送前仍必须执行:

```powershell
git status --short --ignored
```

重点看有没有私钥、数据库、zip 包、release 包、API Key 被列为待提交。

---

## 3. 推荐远程仓库配置

在 Gitee 创建空仓库后，执行:

```powershell
git remote add origin git@gitee.com:<你的用户名或组织>/openclaw-usb-launcher.git
git remote -v
```

如果已经存在 origin:

```powershell
git remote set-url origin git@gitee.com:<你的用户名或组织>/openclaw-usb-launcher.git
```

推荐使用 SSH key，不推荐 HTTPS 密码。

---

## 4. 推荐分支

```text
main      稳定交付分支
develop   日常开发分支
hotfix/*  紧急修复
feature/* 新功能
```

第一版可以先只用 `main`，等项目稳定后再开 `develop`。

---

## 5. 本地 CI 检查脚本

已新增:

```text
scripts/ci-check.ps1
```

本地执行:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ci-check.ps1
```

它会检查:

- 前端 `npm run build`
- Rust `cargo check`
- Python Bridge 编译
- 授权服务器编译

如果只想先检查 Python:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ci-check.ps1 -SkipFrontend -SkipRust
```

---

## 6. Gitee Go 策略

Gitee Go 官方流水线配置通常放在:

```text
.workflow/
```

但是当前项目是 Windows Tauri 桌面应用，完整打包依赖 Windows 环境、WebView、Rust、Node、Python Runtime。普通 Linux Runner 不一定适合直接打 Windows 离线包。

因此推荐分三阶段:

### 阶段一: 只做检查

在 Gitee Go 中先只做:

- 前端构建。
- Python 编译。
- 授权服务器编译。

Rust/Tauri 可以先在本机执行 `scripts/ci-check.ps1`。

### 阶段二: 接入 Windows 构建机

准备一台 Windows 构建机，安装:

- Node.js
- Rust
- Python
- Tauri 依赖
- Git
- PowerShell

然后让流水线调用:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ci-check.ps1
```

### 阶段三: 自动生成离线包

再加入:

- `scripts/build-portable.ps1`
- `scripts/clean-release.ps1`
- `scripts/verify-release.ps1`

产物作为 Gitee Release 附件或流水线产物保存，不提交进 Git。

---

## 7. 授权服务器部署策略

授权服务器不建议一开始就自动部署。

第一阶段:

- 手动 SSH 部署。
- 手动备份数据库。
- 手动重启服务。

第二阶段:

- 使用 Gitee Go Secrets 保存 SSH Key。
- Tag 触发部署。
- 部署前自动备份 `/opt/openclaw-license/license.db`。
- 部署后健康检查 `/health` 或后台首页。

绝对不要把服务器密码、私钥、数据库放进仓库。

---

## 8. 建议第一次提交内容

第一次基线提交建议包含:

- `openclaw_new_launcher/src/`
- `openclaw_new_launcher/python/`
- `openclaw_new_launcher/src-tauri/`
- `openclaw_new_launcher/docs/`
- `license_server/server.py`
- `license_server/logo.ico`
- `scripts/ci-check.ps1`
- `.gitignore`

不包含:

- `release/`
- `node_modules/`
- `dist/`
- `target/`
- 数据库。
- 授权私钥。
- 客户数据。

---

## 9. 推荐第一次提交命令

先检查:

```powershell
git status --short
git status --short --ignored
```

确认无敏感文件后:

```powershell
git add .gitignore scripts/ci-check.ps1 license_server/logo.ico license_server/server.py openclaw_new_launcher
git status --short
git commit -m "chore: establish OpenClaw launcher baseline"
git push -u origin main
```

如果当前分支不是 `main`:

```powershell
git branch -M main
```

---

## 10. 当前建议

先把 Gitee 作为源码管理平台。

短期目标:

- 私有仓库。
- 基线提交。
- 本地 CI 脚本。
- Gitee Go 只做轻量检查。

中期目标:

- Windows 构建机。
- 自动打包离线包。
- 自动生成 SHA256。

长期目标:

- 授权服务器 tag 自动部署。
- 客户端更新包自动发布。
- 发版记录和回滚机制完整化。

