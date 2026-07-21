# 安装与更新

OpenClaw 当前有两类交付方式：完整便携包和在线瘦包。完整包侧重离线可用，在线瘦包侧重体积和首次下载流程；两者的验收标准应分别定义。

## 当前发布版本

| 项 | 当前值 |
| --- | --- |
| 最新启动器 | `2.1.19` |
| OpenClaw runtime | `2026.6.5` |
| 在线便携包 | `LumiClaw-Online-v2.1.19.zip` |
| 完整离线包 | `OpenClaw-Portable-v2.1.19-2026.06.26-full-offline.zip` |
| 更新安装器 | `LumiClaw-Setup-v2.1.19.exe` |
| Release 地址 | [openclaw-runtime-layers v2.1.19](https://github.com/rfdiosuao/openclaw-runtime-layers/releases/tag/v2.1.19) |

## 交付形态

| 类型 | 适合谁 | 包里有什么 | 风险 |
| --- | --- | --- | --- |
| 完整便携包 | 客户机网络不稳定、需要开箱即用 | `OpenClaw.exe`、`OpenClawFiles/`、Node/Python/OpenClaw 运行时、必要脚本 | 包体大，构建时间长 |
| 在线瘦包 | 内测用户、可访问镜像源的机器 | 启动器、bootstrap、manifest URL、缓存逻辑 | 首装依赖网络和 manifest 可用性 |
| 源码包 | Mac 端适配、二开工程师 | 源码、脚本、文档，不带用户状态和构建缓存 | 需要本地构建环境 |

## 便携包目录结构

```text
OpenClaw-Portable-*/
├─ OpenClaw.exe
└─ OpenClawFiles/
   ├─ node/
   ├─ python/
   ├─ node_modules/openclaw/
   ├─ scripts/
   ├─ agents/
   ├─ data/
   └─ logs/
```

交付包最重要的规则：可以带运行时，不可以带用户状态。

## 不能带进包里的东西

| 类型 | 示例 |
| --- | --- |
| 授权状态 | `license.json`、安装 ID、设备绑定信息 |
| 密钥 | API Key、OAuth token、Bridge Token、Phone Token |
| 用户缓存 | 聊天记录、工作区缓存、手机设备列表、桌面截图 |
| 构建缓存 | `node_modules` 的开发依赖缓存、`dist/`、`src-tauri/target/` |
| 服务端私密文件 | license server 私钥、数据库、后台 token |

## 更新启动器

“统一设置”里有启动器自更新入口。当前口径是：更新只替换启动器本体，已下载的运行时层保留。更新前先确认：

1. 当前版本号。
2. manifest 是否可访问。
3. 下载源是否可信。
4. SHA256 是否匹配。
5. 失败后能否回滚到旧包。

当前线上 `launcher.json` 指向：

```text
https://github.com/rfdiosuao/openclaw-runtime-layers/releases/download/v2.1.19/LumiClaw-Setup-v2.1.19.exe
```

SHA256：

```text
B7D1F185F4546AD8A838B8DC1855E7161F8AD17EA3A7142B04C8AB62B09E264F
```

## 在线瘦包的稳定设计

瘦包不是“少打文件”这么简单，它需要稳定的 bootstrap。

推荐机制：

1. manifest 多源：官方源、备用 CDN、镜像源。
2. 本地缓存：第一次成功下载后写入缓存，下次首选本地。
3. sha256 校验：每个运行时层都校验。
4. 断点与重试：下载失败后提示明确来源，而不是只说 fetch failed。
5. 离线提示：告诉用户当前缺哪一层、去哪下载、放到哪个目录。

<div class="danger-line">公共 ghproxy 只能当临时兜底，不适合作为生产唯一下载源。</div>

v2.1.8 在线瘦包当前使用 GitHub Release 主源和 ghproxy 备用源。后续如果切换到自有 OSS/CDN，应同时更新 `manifest.json`、`launcher.json`、文档站和 Release note。

## 更新失败怎么判断

| 报错 | 说明 | 处理 |
| --- | --- | --- |
| manifest 拉取失败 | 下载源不可达或被拦截 | 换备用源，检查本地缓存 |
| sha256 mismatch | 文件损坏或源被替换 | 丢弃缓存，重新下载，核对 release |
| runtime missing | 运行时层没落到 `OpenClawFiles/` | 检查 bootstrap 日志 |
| template missing | OpenClaw 核心模板没带全 | 检查 `src/agents/templates` 是否完整 |

## 安装后验收

```powershell
cd D:\Axiangmu\AUSTART\openclaw_ui_integration
npm run openclaw:context -- --json
npm run verify:phone
```

如果是完整包，还要在新目录解压后启动一次，确认路径推导没有依赖原开发机绝对路径。
