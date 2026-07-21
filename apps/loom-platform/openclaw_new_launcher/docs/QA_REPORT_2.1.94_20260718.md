# LOOM 2.1.94 全量验收与缺陷修复报告

## 验收结论

LOOM 2.1.94 已完成代码合同、桌面端三窗口、Python Bridge、Node 手机执行器、Rust/Tauri、受保护打包以及 ASCII/中文路径安装烟测。候选安装包可交付内部验收；抖音真实草稿仍需用户先在手机端手动登录，未登录前不把失败状态写成通过，也不会执行公开发布。

## 本版重点修复

| # | 严重度 | 缺陷 | 修复结果 |
|---|---|---|---|
| 48 | P0 | 更新时 `_up_` 内的 `python.exe`、`node.exe` 仍运行，安装器无法覆盖 | 更新前先关闭 Bridge；移交脚本按安装根目录清理全部自有进程，验证退出后才启动安装 |
| 49 | P0 | CIM 在低内存下失败时无法识别占用进程 | 增加 `Get-Process.Path` 降级和直接 Kill 回退，并拒绝带占用继续安装 |
| 50 | P1 | 大图片/视频依赖 JSON/base64，手机端返回无 JSON 或大文件失败 | 新增签名流式媒体上传，旧 APK 仅对小文件使用兼容端点，大文件明确提示升级 |
| 51 | P1 | 生图、生视频结果只留在电脑，发布时手机相册没有素材 | 生成结果进入共享素材库并自动传入指定手机相册，保留逐设备成功/失败结果 |
| 52 | P1 | 创作页生成结果没有可见预览 | 图片和视频结果使用真实素材路径预览；没有本地路径时显示明确状态而非死按钮 |
| 53 | P1 | Agent 工具调用逐事件刷屏，完成后仍停在“调用中” | 同一运行的 queued/started/completed 合并为一个执行组；成功自动收起，失败保留可操作说明 |
| 54 | P1 | Agent 思考、回复和工具状态互相竞争 | 思考状态绑定运行阶段，开始即时显示，流式回复或工具进入下一阶段时准确收敛 |
| 55 | P1 | 手机发布调用可能丢平台、素材、设备或草稿模式 | 使用标准 OpenAI 工具消息协议并冻结完整参数；旧能力 ID 继续兼容 |
| 56 | P1 | 启动矢量动画卡顿且 WebView 加载链复杂 | 使用用户提供视频，转为 H.264/yuv420p、静音、移除元数据并内置 poster；播放结束自动退场 |
| 57 | P1 | 登录弹窗和已登录账户卡引用不存在的 `/logo.png` | 两处统一使用共享麓鸣 Logo，并新增真实加载断言 `naturalWidth > 0` |
| 58 | P1 | 启动器内“邮箱注册”不可用且与网页注册冲突 | 删除内置注册标签、状态和提交逻辑；新用户统一打开网页注册 |
| 59 | P2 | Agent 中央标识仍是临时 `AGT` 字样 | 使用共享麓鸣品牌标识，状态动效支持 reduced-motion |
| 60 | P2 | 原始能力名和重复失败暴露给普通用户 | 能力由系统提示词自主路由；普通消息使用中文摘要并按运行去重错误 |
| 61 | P0 | 手机端返回“任务无法完成/抖音未登录”时，旧发布链仍可能把 Job 标为成功 | Node 与 Python 发布适配器同时识别业务失败文本并返回失败；定向合同验证该返回必须非零退出，Agent UI 显示真实登录前置条件 |

2.1.93 报告中的 47 项修复继续纳入本轮全量回归，未发现回归。

## 自动化证据

| 范围 | 结果 |
|---|---:|
| Python 全量 | 1217 passed，1 个测试辅助类收集提示 |
| 前端平台合同 | 116 passed |
| Node 手机、媒体、发布与视觉安全 | 59 passed |
| Rust/Tauri | 19 passed |
| Playwright 桌面端 | 213 passed，6 个按环境设计跳过 |
| 合计 | 1624 passed，0 failed |

Playwright 覆盖 960×640、1200×800、1440×900 三种发布窗口，遍历 14 个页面及其可见控件，并覆盖智能体、矩阵截图与人工控制、手机连接与任务、创作、账户、启动视频、设置、诊断和终端。登录弹窗和已登录账户卡都验证共享 Logo 已完成解码，不再只检查图片路径。

最终安装包的已登录账户页另做了真实 WebView 检查：页面中的 3 个麓鸣 Logo 均从内置 `/loom-motion/logo.svg` 完成解码，`naturalWidth=1024`、`naturalHeight=1024`；截图为 `artifacts/overnight-qa-20260718/screens/loom-2.1.94-account-logo-real-install.png`。

更新专项回归覆盖 `_up_/python-runtime/python.exe` 与 `_up_/node-runtime/node.exe` 同时存活的场景；安装移交必须先终止两者，再执行测试安装器。更新、回滚和无损保留专项 20 项通过，并已包含在 Python 全量结果中。

## 安装包证据

- 安装包：`src-tauri/target/release/bundle/nsis/Luming AI Matrix Acquisition Workbench_2.1.94_x64-setup.exe`
- 大小：257,719,117 字节
- SHA256：`0CC5DDBF91D248F29864B78D35BD5F1B443F9C4D77AF740E26851A0D55A801F9`
- 受保护资源：74 个 Python 文件编译，6 个必要加载器保留，8 个脚本复制，23 个脚本混淆；泄漏扫描通过。
- ASCII 路径安装：通过，打包 Python/Node、FastAPI Bridge、`loom-native` Agent 和 81 项能力正常。
- 中文路径升级安装：通过，客户数据保留，安装目录和卸载注册信息恢复正常。
- 两条安装链均完成静默卸载；测试目录和临时快捷方式已清理。

## 媒体与手机证据

- 6.60 手机端基线 APK：`AgentPhone_v6.60-stability_20260718_191101.apk`
- APK SHA256：`E26C34BE16A389FFE0AC1B299AB686ABE4B09E79A2F4EA93D24462E67E578609`
- 已通过真实流式链将 39,445,100 字节视频写入 Android MediaStore：`Movies/LOOM/loom-qa-publish-approval-recording.mp4`。
- 大文件中断、旧 APK 小文件兼容、旧 APK 大文件拒绝和逐设备失败摘要均有 Node/Python 合同覆盖。

## 最终安装包真实 Android 验收

- 使用 2.1.94 最终安装包连接 Android 模拟器，手机端为 `6.60-stability`、`versionCode=929`，矩阵工作台成功显示实时手机截图。
- 切换“人工”接管后，从矩阵焦点画面点击手机设置按钮，手机真实进入 Settings，矩阵截图同步更新。
- 矩阵“返回”和“主页”命令均通过真实手机控制协议执行；手机分别返回 APKClaw 控制台和 Android 启动器。
- 现场截图保存在 `artifacts/overnight-qa-20260718/screens/`：`loom-2.1.94-real-matrix-open.png`、`loom-2.1.94-real-matrix-after-touch.png`、`emulator-after-matrix-back.png`、`emulator-after-matrix-home.png`。
- 2.1.94 最终包验收录像：`artifacts/overnight-qa-20260718/LOOM-2.1.94-real-android-matrix-agent-qa.mp4`，35 秒、H.264/yuv420p、1920×1078，SHA256 `8F463F362A90861BE24ABBED84B5FC25CE43D81A5E7103FAF5CFD9EB823D45A6`。录像由最终安装 WebView 逐帧采集，避免 Windows GDI 对 WebView2 硬件合成只保留首帧的问题。

## Agent 抖音草稿核验

- 内置 Agent 已真实完成 `loom.cli.phone.status`、`loom.matrix.status` 和 `loom.phone.publish` 的自主选路，发布调用保留了抖音平台、目标设备、素材路径、正文和 `draftOnly=true`。
- 历史运行曾把手机返回的“任务无法完成：抖音应用当前未登录”保存为 `success=true`。该记录属于旧链路假成功，不作为草稿完成证据。
- 当前发布适配器会将相同业务返回判为失败；`node --test scripts/tests/publish-contract.test.mjs` 定向回归 3/3 通过，其中包含“底层返回 success 但正文明确失败”的场景。
- 最终安装包中的 Agent 会明确显示“抖音需要登录”，工具执行组结束为失败状态，不再卡在调用中或报告假成功。完成真实草稿仍需用户先在抖音手机客户端手动登录。

## 保留项

- 抖音草稿属于外部平台操作。用户需先在手机端手动登录；验收只允许 `draftOnly=true`，不得公开发布。当前未满足登录前置条件，因此不把真实草稿项标记为通过。
- 本轮真实媒体链覆盖一台 Android 设备；多设备并发由 API、Node、前端合同和三窗口 E2E 覆盖，发布前仍建议用两台实体手机补一次现场验收。
- 本轮自动化截图保存在 Playwright 测试产物目录；2.1.94 的真实矩阵与 Agent 验收录像已单独保存，2.1.93 的旧录屏仍保留但不作为本版证据。
