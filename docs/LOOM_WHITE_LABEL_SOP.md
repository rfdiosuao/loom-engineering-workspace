# LOOM / 麓鸣白标换壳 SOP

本文档用于指导 LOOM / 麓鸣后续做套壳、白标交付、客户定制和二开分发。目标是让每一次白标都可复制、可验收、可回滚，避免通过手动全局替换把主工程改乱。

## 1. 核心原则

白标不是复制一份项目再乱改，而是用一套稳定内核承载多个品牌配置。

- 核心能力层不随客户变化：安装器、账号、模型同步、手机控制、更新器、下载器、校验器保持同一套实现。
- 品牌差异只进配置：名称、Logo、颜色、域名、默认模型、模块开关、发布通道、文案资源全部配置化。
- 每个客户独立发布：独立 manifest、独立下载目录、独立版本号、独立回滚包。
- 不把密钥写死进源码：API Key、管理员 Token、私钥、客户账号凭证不能进入仓库和安装包。
- 可回滚优先：每次发布必须保留上一版包、上一版 manifest、上一版配置。

## 2. 白标前置资料清单

开始换壳前，先让客户或项目负责人补齐以下信息。

| 类别 | 必填内容 | 说明 |
| --- | --- | --- |
| 产品信息 | 中文名、英文名、安装包名、窗口标题 | 例如 LOOM / 麓鸣 |
| 品牌资源 | Logo、应用图标、安装器图标、启动图 | 至少需要 PNG 和 ICO |
| 视觉风格 | 主色、辅色、背景色、字体偏好 | 不建议每个页面单独发挥 |
| 中转站 | API Base URL、登录页、注册页、订阅页 | 必须确认 HTTPS 可用 |
| 模型策略 | 默认文本模型、手机模型、可选模型范围 | 避免主模型和手机模型混用 |
| 开放模块 | 安装器、手机控制、RPA、生图、生视频等 | 未开放模块走锁定态 |
| 发布渠道 | 在线包地址、离线包地址、manifest 地址 | 每个白标独立 |
| 客服与文档 | 文档站、客服入口、问题反馈地址 | 可以先用统一默认值 |
| 合规信息 | 公司名、发布者、协议、隐私政策 | Windows 签名也依赖发布者信息 |

## 3. 推荐目录结构

建议后续把白标配置集中到 `brands/`，不要散落在源码各处。

```text
brands/
  loom/
    brand.json
    copy.json
    modules.json
    manifest.json
    assets/
      icon.ico
      icon.png
      logo.svg
      splash.png
      installer-banner.png
  customer-a/
    brand.json
    copy.json
    modules.json
    manifest.json
    assets/
      icon.ico
      icon.png
      logo.svg
      splash.png
      installer-banner.png
```

如果短期不方便新增完整 `brands/` 机制，也应该至少做到：品牌配置集中在一个目录，构建脚本只读取该目录，不允许人工到处替换。

## 4. 品牌配置规范

`brand.json` 负责产品身份、域名、默认模型和发布渠道。

```json
{
  "brandId": "loom",
  "appName": "LOOM",
  "appNameZh": "麓鸣",
  "windowTitle": "LOOM",
  "publisher": "Heang",
  "primaryColor": "#ff6a3d",
  "secondaryColor": "#1f2937",
  "apiBaseUrl": "https://api-cn.heang.top",
  "docsUrl": "https://docs.heang.top",
  "supportUrl": "https://docs.heang.top/support",
  "downloadBaseUrl": "https://download.heang.top/loom",
  "manifestUrl": "https://download.heang.top/loom/manifest.json",
  "defaultTextModel": "qwen3.7-plus",
  "defaultPhoneModel": "agnes-2.0-flash",
  "channel": "stable"
}
```

`modules.json` 负责模块开放状态。

```json
{
  "enabled": ["installer", "phone"],
  "locked": ["desktop-rpa", "image", "video"],
  "hidden": ["debug", "internal-tools"]
}
```

`copy.json` 负责少量可替换文案。注意：UI 不要塞大量解释性文案，标题和状态说明够用。

```json
{
  "loginTitle": "账号登录",
  "installerTitle": "智能体安装",
  "phoneTitle": "手机控制",
  "lockedText": "暂未开放"
}
```

## 5. 换壳执行流程

### 5.1 新建品牌目录

1. 在 `brands/` 下创建客户目录，例如 `brands/customer-a/`。
2. 复制 `brands/loom/` 作为模板。
3. 修改 `brand.json`、`modules.json`、`copy.json`。
4. 放入客户图标和 Logo。
5. 不修改核心源码。

### 5.2 替换视觉资源

必须检查以下位置是否被品牌配置覆盖：

- 应用窗口图标
- 任务栏图标
- 桌面快捷方式图标
- 安装器图标
- 启动画面
- 左上角品牌 Logo
- 登录弹窗 Logo
- 官网下载页 Logo
- 更新器 Logo

验收标准：启动器内不能出现错误品牌名、错误 Logo、旧项目残留字样。

### 5.3 替换服务地址

白标包至少需要确认这些地址：

- `apiBaseUrl`
- `manifestUrl`
- `downloadBaseUrl`
- `docsUrl`
- `supportUrl`
- 订阅页 URL
- 注册页 URL
- 模型同步接口

要求：

- 全部使用 HTTPS。
- 不共用其他客户 manifest。
- 线上地址不可指向 localhost。
- 开发地址不能进入正式包。

### 5.4 配置能力开关

模块状态分三类：

| 状态 | 表现 | 使用场景 |
| --- | --- | --- |
| enabled | 正常显示、可点击 | 当前客户已购买或需要演示 |
| locked | 显示但置灰、标记暂未开放 | 展示产品路线，但不承诺可用 |
| hidden | 不显示 | 内测、调试、未稳定功能 |

演示版建议只开放两个亮点：

- 智能体安装
- 手机控制

其他功能先锁定，避免用户点进去遇到半成品体验。

### 5.5 配置默认模型

建议固定分工：

- 主文本模型：`qwen3.7-plus`
- 手机 Agent 模型：`agnes-2.0-flash`

原则：

- 不要让手机模型覆盖主模型。
- 登录中转站后允许用户选择模型。
- 同步失败时保留上一次有效模型列表。
- 旧授权码路径继续保留，作为回滚路径。

### 5.6 构建白标包

推荐最终形成统一命令：

```powershell
scripts/build-brand.ps1 -Brand loom -Version 2.1.30 -Channel stable
scripts/build-brand.ps1 -Brand customer-a -Version 1.0.0 -Channel stable
```

每次构建至少产出：

- 完整离线包
- 在线安装器
- 在线资源包
- SHA256 文件
- manifest 文件
- 发布说明

命名建议：

```text
LOOM-Portable-v2.1.30-20260630-stable.zip
LOOM-Online-v2.1.30-20260630-stable.zip
LOOM-Online-Setup-v2.1.30-20260630-stable.exe
manifest.json
```

客户白标命名示例：

```text
CustomerA-Portable-v1.0.0-20260630-stable.zip
CustomerA-Online-v1.0.0-20260630-stable.zip
CustomerA-Online-Setup-v1.0.0-20260630-stable.exe
```

## 6. 在线安装器要求

在线安装器必须做到：

- 启动后读取当前品牌 manifest。
- 下载品牌对应的在线资源包。
- 校验 SHA256。
- 下载失败时提示可理解原因。
- 支持多源下载地址。
- 支持本地缓存。
- 不把下载地址写死在多个地方。

manifest 推荐字段：

```json
{
  "brandId": "loom",
  "version": "2.1.30",
  "channel": "stable",
  "packages": {
    "online": {
      "url": "https://download.heang.top/loom/LOOM-Online-v2.1.30-20260630-stable.zip",
      "sha256": "..."
    },
    "portable": {
      "url": "https://download.heang.top/loom/LOOM-Portable-v2.1.30-20260630-stable.zip",
      "sha256": "..."
    }
  },
  "fallbackUrls": [
    "https://cdn1.example.com/loom/",
    "https://cdn2.example.com/loom/"
  ]
}
```

## 7. Windows 安全与签名要求

白标交付不能靠关闭 Windows 安全提示解决。正确路径是降低误报和提升可信度。

必须做：

- 使用 OV 或 EV 代码签名证书签名 `.exe`。
- 安装器和主程序都签名。
- 文件属性填写公司名、产品名、版本号、版权信息。
- 在线下载包提供 SHA256。
- 官网下载页展示校验值。
- 避免安装器写入敏感目录、修改 Defender、修改注册表启动项。
- 如果 Defender 误报，走 Microsoft 安全中心提交误报。

禁止做：

- 禁用 Defender。
- 关闭 SmartScreen。
- 引导用户执行危险注册表命令。
- 把程序伪装成系统组件。
- 下载未校验的远程脚本直接执行。

## 8. 验收清单

每个白标包发布前必须逐项检查。

### 8.1 品牌验收

- 应用名正确。
- 窗口标题正确。
- 安装包名正确。
- 桌面快捷方式名正确。
- Logo 和图标正确。
- 没有残留其他品牌名。
- 没有残留 OpenClaw 专用文案，除非该模块明确叫 OpenClaw。

### 8.2 账号验收

- 可注册账号。
- 可登录账号。
- 邮箱验证码流程正常。
- 可退出登录。
- 重启后登录状态正确。
- 订阅页可打开。
- 余额或套餐信息展示正确。
- 断网时保留上次账号快照。

### 8.3 模型验收

- 登录后可同步模型。
- 文本模型列表正常。
- 图像模型列表正常。
- 视频模型只展示，不强行切换 provider，除非已完成专门适配。
- 默认主模型正确。
- 默认手机模型正确。
- 同步失败时保留上一次有效列表。

### 8.4 安装器验收

- 在线 setup 能启动。
- 在线 setup 能下载资源包。
- SHA256 校验生效。
- 下载失败有清晰提示。
- 完整离线包可直接运行。
- 首次启动不访问 localhost 页面。
- 正式包不显示开发模式标识。

### 8.5 功能验收

- 智能体安装入口可用。
- Codex / Claude Code / OpenCode / OpenClaw / Hermes 的安装状态展示合理。
- 手机控制入口可用。
- 未开放模块显示锁定态。
- 锁定模块不能进入半成品页面。

### 8.6 工程验收

- `git diff --check` 通过。
- 没有真实密钥进入源码。
- 没有私钥进入包。
- 没有 localhost 进入正式包。
- 没有客户 A 的域名进入客户 B 的包。
- 构建产物和源码版本一致。
- release 目录包含 hash 文件。

## 9. 发布流程

1. 确认品牌配置。
2. 运行构建。
3. 生成 SHA256。
4. 解包 smoke。
5. 验证登录、订阅、模型同步。
6. 上传在线包和离线包。
7. 上传 manifest。
8. 验证在线安装器真实下载。
9. 更新下载页。
10. 保存上一版回滚包。
11. 写发布说明。
12. 通知客户验收。

发布说明必须包含：

- 版本号
- 发布日期
- 包下载地址
- SHA256
- 新增能力
- 已知限制
- 回滚方式

## 10. 回滚流程

如果新白标包出现严重问题：

1. 暂停下载页新版本入口。
2. 将 manifest 指回上一版稳定包。
3. 保留问题包，不要立即删除，用于复盘。
4. 记录问题影响范围。
5. 修复后重新出 rc 包。
6. smoke 通过后再恢复 stable。

回滚时只改发布配置，不要临时改源码。

## 11. 二开交付边界

可以交给客户改：

- Logo
- 名称
- 颜色
- 文案
- 官网下载页
- 中转站域名
- 模型套餐
- 模块开关

不建议交给客户随意改：

- 更新器校验逻辑
- 账号 Token 存储逻辑
- 模型同步协议
- `managedBy` 兼容字段
- 在线安装器下载校验
- 核心 CLI / MCP 能力协议

## 12. 标准交付物

每次白标交付至少包含：

```text
release/
  CustomerA-Portable-v1.0.0-20260630-stable.zip
  CustomerA-Portable-v1.0.0-20260630-stable.zip.sha256.txt
  CustomerA-Online-v1.0.0-20260630-stable.zip
  CustomerA-Online-v1.0.0-20260630-stable.zip.sha256.txt
  CustomerA-Online-Setup-v1.0.0-20260630-stable.exe
  CustomerA-Online-Setup-v1.0.0-20260630-stable.exe.sha256.txt
  manifest.json
  RELEASE_NOTES.md
  ACCEPTANCE_CHECKLIST.md
```

## 13. 推荐落地路线

第一阶段：先人工配置，但必须集中到品牌目录。

- 建 `brands/loom/`
- 把名称、图标、域名、模型、模块开关迁进去
- 构建脚本读取品牌配置

第二阶段：做白标构建脚本。

- `build-brand.ps1`
- 自动替换 Tauri 元信息
- 自动替换图标
- 自动生成 manifest
- 自动生成 hash

第三阶段：做白标管理后台。

- 上传 Logo
- 配置中转站
- 配置模块开关
- 一键生成在线包
- 一键回滚上一版

## 14. 最小可执行版本

如果时间很紧，最低限度也要做到：

- 一个品牌配置文件
- 一个品牌资源目录
- 一个构建命令
- 一份验收清单
- 一个独立 manifest
- 一套回滚包

只要做到这六件事，白标就不会变成不可维护的复制项目。
