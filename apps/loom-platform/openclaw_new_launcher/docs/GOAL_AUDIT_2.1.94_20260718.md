# LOOM 2.1.94 整晚目标完成审计

## 结论

本轮目标尚不能标记为全部完成。除“由麓鸣内置 Agent 在真实抖音账号中保存一份草稿”外，其余要求均有当前源码、测试、安装包或真实 Android 证据。抖音手机客户端当前未登录；旧链路曾把“任务无法完成”误记为成功，2.1.94 已修复为真实失败，因此不能用旧 Job 冒充草稿闭环。

2026-07-19 续测：2.1.95 进一步修复了模型漏字段后在审批前失败、以及自纠轮只用文字收尾却被标成完成的问题。真实麓鸣模型已完成“固定漏标题 -> 后台自纠 -> 完整审批”的边界验证；抖音模拟器当前停留在手机号与验证码登录页，真实草稿仍等待人工登录。

## 逐项证据

| 要求 | 状态 | 权威证据 |
|---|---|---|
| 使用中转站账号完成授权和模型准备 | 通过 | 独立 QA 安装保留授权数据，最终安装包 Agent 显示模型已就绪；凭据未写入报告、日志或命令行 |
| 像真人小白一样测试完整桌面流程 | 通过 | 14 页面、3 个发布视口 Playwright 全量 213 passed；最终安装包另有真实 Android 逐帧录像 |
| 至少发现并修复 20 个真实 Bug | 通过 | `QA_REPORT_2.1.93_20260718.md` 47 项，`QA_REPORT_2.1.94_20260718.md` 14 项，共 61 项 |
| 矩阵手机人工点击可用 | 通过 | 最终安装包真实 Android 验证截图、人工租约、聚焦画面点击、返回和主页；点击后手机前台页面实际变化 |
| 矩阵截图可见且持续更新 | 通过 | `artifacts/overnight-qa-20260718/screens/loom-2.1.94-real-matrix-open.png` 与 after-touch 截图 |
| Agent 使用麓鸣内置能力而非外部 Agent | 通过 | 真实 trace 包含 `loom.cli.phone.status`、`loom.matrix.status`、`loom.phone.publish`，能力由系统提示词自主选择 |
| Agent 真实完成抖音自动草稿 | **未完成** | 调用和审批已真实执行，但抖音手机客户端未登录；当前最终包正确显示“抖音需要登录”，没有草稿成功证据 |
| Agent Markdown 正常渲染 | 通过 | `messageBlocks.tsx` 的结构化 Markdown 渲染、链接安全和代码块测试已纳入 116 项前端合同 |
| 工具调用不刷屏、不永久卡在调用中 | 通过 | queued/started/completed 按 run 合并；成功收起、失败保留原因；Agent view-model、store 和 E2E 覆盖 |
| Agent Harness 与能力继承 | 通过 | 原生 runtime、orchestrator、policy、approval resume、81 项能力继承和旧能力 ID 兼容均有 Python/前端测试 |
| 生图、生视频自动进入手机相册 | 通过 | 真实流式上传将 39,445,100 字节视频写入 Android MediaStore `Movies/LOOM/`；逐设备结果有 Node/Python 合同 |
| 创作页能看到图片和视频 | 通过 | `CreativeMediaPage.tsx` 使用真实素材路径显示图片/视频预览；缺少路径时显示明确状态 |
| AGT 与缺失 Logo 替换为麓鸣品牌 | 通过 | Agent 头部、空状态、登录弹窗和已登录账户卡统一使用 `LoomLogoMark`；账户专项 18 passed；最终安装 WebView 的 3 个 Logo 均解码为 1024×1024 |
| 删除启动器内不可用的邮箱注册 | 通过 | `LicensePage.tsx` 无注册 tab、状态或 `accountApi.register`，只保留网页登录；账户专项 18 passed |
| 启动矢量动画换成用户视频 | 通过 | 内置 H.264/yuv420p 视频和 poster，WebView2 播放失败可降级，播放后自动退场 |
| 更新时 `_up_` 的 Python/Node 可被覆盖 | 通过 | 更新前关闭 Bridge，安装根进程扫描、CIM 降级、Kill 回退和占用拒绝；专项 20 passed |
| OpenClaw 旧残留清理 | 通过（保留必要兼容） | `LEGACY.md` 和旧顶层 Logo 已删除；现存 OpenClaw 引用均用于兼容运行时、安装组件、CLI/MCP、手机脚本、配置迁移或正在使用的首页资源 |
| 形成可复用的“人话”验收提示词 | 通过 | `docs/prompts/LOOM_REAL_USER_OVERNIGHT_QA_PROMPT.md` |
| 监控 C/D 盘并避免误删 | 通过 | 验收末 C 盘约 9.17 GB、D 盘约 76.49 GB 可用；未删除用户项目、模型缓存、授权和手机配置 |
| 录制测试过程 | 通过 | `artifacts/overnight-qa-20260718/LOOM-2.1.94-real-android-matrix-agent-qa.mp4`，35 秒，SHA256 `8F463F362A90861BE24ABBED84B5FC25CE43D81A5E7103FAF5CFD9EB823D45A6` |
| 生成受保护安装包 | 通过 | 2.1.94 NSIS 257,719,117 字节，SHA256 `0CC5DDBF91D248F29864B78D35BD5F1B443F9C4D77AF740E26851A0D55A801F9` |

## 新鲜回归

- Python：1217 passed。
- 前端平台合同：116 passed。
- Node 手机/媒体/发布：59 passed。
- Rust/Tauri：19 passed。
- Playwright：213 passed，6 个按环境设计跳过。
- 合计：1624 passed，0 failed。
- 历史审查员指出的更新 mock 和 Agent 控件基线已在当前工作树定向复跑：2 passed。
- 账户 Logo 与注册流程专项：18 passed。
- 发布业务假成功专项：3 passed。

## 完成真实抖音草稿的唯一剩余动作

1. 用户在 Android 虚拟机的抖音客户端手动登录，验证码、密码和账号信息不交给自动化填写。
2. 回到麓鸣 Agent，重试原会话，保持 `draftOnly=true`。
3. Agent 等待手机任务真实终态，并在抖音草稿箱读取验证；只有看到草稿条目才标记完成，不执行公开发布。
