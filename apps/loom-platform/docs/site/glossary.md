# 术语表

| 术语 | 解释 |
| --- | --- |
| OpenClaw | 核心运行时和项目名称之一 |
| Lumi | 启动器、控制台和能力层语境中的产品名称之一 |
| 启动器 | Windows 桌面入口，负责服务、授权、配置和工作区 |
| Bridge | Python 中间层，连接 UI、运行时、手机、桌面和授权 |
| Tauri | 桌面应用壳，提供 Rust 后端和 WebView |
| APKClaw | 安卓手机端 Agent App |
| Lumi Signature | 手机控制安全签名校验 |
| Phone URL | 手机 Agent 的局域网 HTTP 地址 |
| Phone Token | 手机端 API Token |
| Luminode | 桌面 RPA 组件名称之一 |
| SightFlow | 桌面控制代理项目名称之一 |
| Skills | 可安装、启用、调用的能力模块 |
| CLI | 命令行入口，供开发者和 Agent 自动化调用 |
| OpenClaw onboard | OpenClaw 原生引导命令，用于模型、OAuth、Provider 等配置 |
| 完整便携包 | 带运行时层的 Windows 离线交付包 |
| 在线瘦包 | 首装时按 manifest 下载运行时层的轻量包 |
| manifest | 描述运行时层、下载地址、版本和 hash 的清单 |
| SHA256 | 用于校验下载文件完整性的 hash |
| License Server | 授权码、许可证、会员和中继服务 |
| Ed25519 | 授权签名算法 |
| Runtime Adapter | 后续运行时抽象设计，用于拆分通用进程宿主和 OpenClaw 专属逻辑 |
| MCP | Model Context Protocol，可用于把设备能力暴露给 Agent |
