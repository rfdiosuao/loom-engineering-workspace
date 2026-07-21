# 新手快速开始

本页说明首次使用 OpenClaw / Lumi 启动器时的最小配置流程，以及如何完成第一条可验证任务。

<div class="copy-line">首次使用建议先完成三项基础检查：核心服务已启动、模型配置可用、目标设备已连接。</div>

## 飞书云文档参考

如果你需要对照团队内部说明，可以打开这份飞书云文档：

<div class="route-grid">
  <a class="route-card" href="https://my.feishu.cn/wiki/SZSPwCIR8i5uApk8tLNcXqnFn6e?from=from_copylink" target="_blank" rel="noreferrer">
    <strong>打开飞书云文档</strong>
    <span>作为新手快速开始的补充资料；安装、授权、模型和设备连通仍以本站文档为主。</span>
  </a>
</div>

## 你需要准备什么

| 项目 | 说明 | 不满足时怎么做 |
| --- | --- | --- |
| Windows 机器 | 当前启动器以 Windows 便携包为主 | Mac 适配看 [Mac 适配](../dev/mac-porting.md) |
| OpenClaw 便携包 | 通常是 `OpenClaw.exe + OpenClawFiles/` | 需同时保留 `OpenClawFiles/` 目录 |
| 授权码 | 用于打开授权功能和设备能力 | 没有授权码时只能测试开放入口 |
| 模型网关 | Base URL、API Key、Model | 在“统一设置”集中配置 |
| 手机或桌面组件 | APKClaw 或 Luminode/SightFlow | 可先接入其中一个组件 |

## 第一次启动流程

1. 解压完整包。
2. 双击 `OpenClaw.exe`。
3. 进入“启动器”页，点击“启动核心服务”。
4. 进入“授权内测”，输入授权码并激活。
5. 进入“统一设置”，配置主模型网关。
6. 选择一个工作区：手机控制或桌面 RPA。
7. 执行一条最小任务，并检查结果和日志。

## 第一次任务怎么选

推荐从只读任务开始。

| 场景 | 推荐任务 | 原因 |
| --- | --- | --- |
| 手机控制 | 读取当前屏幕，判断下一步可以安全执行的动作 | 不触发真实点击，适合验证截图、视觉和签名 |
| 桌面 RPA | 获取桌面截图或读取微信未读状态 | 不写入、不发送，适合验证组件健康 |
| CLI | `npm run openclaw:context -- --json` | 获取能力上下文，避免猜测命令 |

## 统一设置最小配置

最小可用配置：

```text
Bridge Base URL: 开发环境通常是 /api 或 http://127.0.0.1:18791
Bridge Token: 由启动器或 Bridge 生成，避免写入文档和日志
Phone URL: http://手机局域网 IP:9527
Phone Token: 手机 APKClaw 显示的 Token
Main Base URL: 你的模型网关地址
Main API Key: 只在本机保存，界面脱敏显示
Main Model: 例如 gpt-4o、doubao-seed-2-0-lite-260215 等实际可用模型
```

如果 OpenAI Codex OAuth 登录失败，优先按网络路由、地区限制、代理环境、回调端口和 OpenAI 侧限制逐项排查。排查顺序见 [授权与模型](./auth-models.md)。

## 启动后的检查位置

<div class="signal-strip">
  <div><strong>当前状态</strong><br>核心服务、授权、API 网关、环境是否可用。</div>
  <div><strong>最近输出</strong><br>首页只展示最近摘要，完整日志进入服务页查看。</div>
  <div><strong>快速入口</strong><br>常用功能从首页进入，复杂配置折叠到对应页面。</div>
</div>

![启动器总览](/screenshots/launcher-dashboard.png)

## 常见失败首查项

| 现象 | 首查位置 | 常见原因 |
| --- | --- | --- |
| 核心服务启动失败 | 服务 / CLI 日志 | OpenClaw 模板缺失、端口占用、Node 运行时缺失 |
| 模型请求 401 | 统一设置 | API Key 格式错误、Base URL 指向了错误网关 |
| 手机已连接但任务失败 | 手机控制日志 | Lumi 签名、Token、锁屏、无障碍服务 |
| 桌面 RPA 无响应 | 桌面 RPA 页 | Luminode/SightFlow 未安装、Bridge policy 阻止 |
| 打包后模板丢失 | 发行包 `OpenClawFiles/node_modules/openclaw/src/agents/templates` | 打包脚本漏拷贝 OpenClaw 模板 |

## 交付前检查项

1. 新机器上启动一次完整包。
2. 确认授权页未保留个人授权码。
3. 确认统一设置里 API Key 为空或已清理。
4. 确认手机设备列表未保留个人设备。
5. 确认桌面 RPA 组件可安装或已随包存在。
6. 跑一次 `npm run openclaw:context -- --json` 或等价健康检查。
7. 检查 `OpenClawFiles/` 是否只包含交付所需文件。

<div class="ok-line">启动流程可在新环境按文档复现后，再进入交付验收。</div>
