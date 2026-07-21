# 麓鸣 AI 矩阵获客工作台 2.1.56 商业稳定版

验证日期：2026-07-10（Asia/Shanghai）

## 版本与基线

- 分支：`codex/customer-acquisition-v1`
- 可追溯基线：`v2.1.45-20260706-ai-matrix-name-rc14` / `12106a7`
- 2.1.55 工作区 checkpoint：`9ecd566`
- 产品代码构建提交：`79cc864`
- 版本：`2.1.56`
- 正式标签：`v2.1.56-commercial-stable`（本地 annotated tag，不推送）

## 本版交付

1. 启动流程变为品牌动画、签名授权检查、商业授权墙或主工作台。未授权、过期、停用、设备不匹配、服务异常分别显示明确状态，不使用无限加载伪装。
2. 授权墙包含授权码激活、套餐与到期信息、机器码/安装 ID、脱敏诊断、购买和支持入口。
3. Python Bridge 与 Tauri 代理共同执行 feature 门禁，不只依赖前端隐藏。受保护 feature 包括：
   - `acquisition.workbench`
   - `acquisition.feishu`
   - `matrix.devices`
   - `templates.cloud`
   - `publishing.draft`
   - `diagnostics.export`
4. 有效授权只来自本地签名授权文件；账号登录和网关配置不再绕过商业授权。
5. GitHub CI/Release 的当前产品事实源统一为 `openclaw_new_launcher`，不再从 `openclaw_ui_integration` 构建当前版本。
6. 所有真实发布、评论、私信、加好友和加微动作继续遵循草稿、人工确认、白名单、频控与日志留痕约束。
7. 新增事务式 NSIS 冒烟脚本，可保护并恢复现有安装注册表与快捷方式，验证英文/中文路径、随包 Python/FastAPI Bridge、未授权 403、线上激活和重启持久化。
8. 新增授权数据库保护工具，只输出表计数和摘要一致性，不输出授权码、账号或行内容。

## 主要文件

- `openclaw_new_launcher/src/components/license/LicensePaywall.tsx`
- `openclaw_new_launcher/src/components/license/licenseGate.ts`
- `openclaw_new_launcher/src/App.tsx`
- `openclaw_new_launcher/src/stores/appStore.ts`
- `openclaw_new_launcher/python/core/feature_access.py`
- `openclaw_new_launcher/python/core/license_manager.py`
- `openclaw_new_launcher/python/api/fastapi_routes.py`
- `openclaw_new_launcher/python/api/routes_license.py`
- `openclaw_new_launcher/src-tauri/src/lib.rs`
- `license_server/server.py`
- `license_server/verify_db_preservation.py`
- `scripts/smoke-test-tauri-nsis.ps1`
- `scripts/verify-release-secrets.ps1`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`

## 最终验证证据

| 检查 | 结果 |
|---|---|
| 根 `scripts/ci-check.ps1` | 通过 |
| `npm run build` | 通过，Vite 8.0.16 |
| 启动器 Python 测试 | 488/488 通过 |
| 授权服务测试 | 23/23 通过 |
| `cargo test` | 7/7 通过 |
| `cargo check` | 通过 |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| 源码秘密扫描 | 415 个文本文件通过，无放行项 |
| 授权墙视觉状态 | 未授权、有效、过期、设备不匹配、断网宽限全部通过 |
| 窄屏检查 | 无横向溢出，表单可滚动到底部，浏览器错误为 0 |
| 最终 NSIS 英文路径 | 随包 FastAPI Bridge 启动，未授权 Matrix/获客 API 返回 403 |
| 最终 NSIS 中文路径 | 随包 FastAPI Bridge 启动，未授权 Matrix/获客 API 返回 403 |
| 安装目录秘密扫描 | 每个路径扫描 2532 个文本文件；仅放行 5 个精确第三方示例路径 |
| 专用线上测试码 | 激活 200，6 项商业 feature 齐全，重启后授权保持，受保护 API 返回 200 |
| 测试码回收 | 授权码和激活记录恢复原计数；临时码文件全部删除 |

## Windows 安装包

- 文件：`artifacts/commercial-stable-2.1.56/Luming-AI-Matrix-Acquisition-Workbench-2.1.56-x64-setup-FA09F5D5.exe`
- 大小：`58,115,498` bytes（55.42 MiB）
- PE FileVersion：`2.1.56`
- PE ProductVersion：`2.1.56`
- SHA256：`FA09F5D5416CE026319164E3E148DC0323417B9DCC6C5F26E8C7DAEB0A9EBDCC`
- Authenticode：`NotSigned`

校验文件和元数据位于同一交付目录。历史安装包和 release 产物未删除、未覆盖。

## 火山云部署

- 目标：`118.145.98.220`，`/opt/openclaw-license`
- 主机验证：使用本机已有 `known_hosts` 严格校验，未接受新主机密钥。
- 部署前备份：`/opt/openclaw-license/backups/deploy-2.1.56-20260709T232757Z`
- 备份权限：`700`，包含程序、后台页、数据库、授权密钥、管理员令牌、环境文件、systemd unit 与 drop-in。
- 实际替换：仅 `server.py`。
- 远端 `server.py` SHA256：`CBFB46FE21E0EA883F2A46CE82DF0CA1CB59298A13C0393BD9AFCE1F9C137A25`
- 服务：`openclaw-license` 为 `active`，近 30 分钟 error journal 为空。
- 公网：`/health`、`/admin`、`/api/client/config` 均返回 200。
- 购买与支持：均指向现有可达入口 `https://68n.cn/HlLRH`。
- 数据保护：授权码 560、激活 146、账号 1、邀请码 2 等客户表部署前后摘要一致；只允许 `plans`、公开 `settings` 和管理员 `audit_logs` 发生预期变化。

## 回滚

优先只回滚程序，不回滚数据库：

```bash
cp -a /opt/openclaw-license/backups/deploy-2.1.56-20260709T232757Z/server.py /opt/openclaw-license/server.py
chmod 0644 /opt/openclaw-license/server.py
systemctl restart openclaw-license
curl -fsS http://127.0.0.1:18791/health
```

数据库备份为 `/opt/openclaw-license/backups/deploy-2.1.56-20260709T232757Z/license.db`。除非确认发生数据迁移故障，不应恢复该数据库；恢复会丢失备份之后的合法管理操作，必须先停服务并由负责人明确确认。

客户端回滚使用保留的 2.1.55 安装包。事务式冒烟验证已确认测试安装不会覆盖现有 2.1.55 注册表和快捷方式。

## 剩余风险与边界

1. 安装器尚未做 Authenticode 代码签名，Windows SmartScreen 仍可能提示未知发布者。正式大规模商业分发前应购买并接入 Windows 代码签名证书。
2. Vite 构建仍有 `INEFFECTIVE_DYNAMIC_IMPORT` 警告，来自 Tauri event 同时被静态和动态导入；不影响本版构建和运行，但应在后续前端依赖整理中清除。
3. 本轮未开发 BOSS 直聘采集、自治获客编排或新平台能力。
4. 安装包和本地 tag 尚未推送到 Gitee/GitHub，也未公开发布；发布动作需再次人工确认。
5. 本地 `license_server` 的真实密钥、管理员令牌和数据库均处于 Git ignore 状态，未被跟踪、未进入安装包、未写入本文档。
