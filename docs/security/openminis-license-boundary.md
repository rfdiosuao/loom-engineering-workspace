# OpenMinis 启发式融合许可证与 clean-room 边界

状态：工程门禁，非法律意见
核对日期：2026-08-01

## 1. 核对结论

OpenMinis 官方仓库当前明确以 GPLv3 分发，并说明其组合应用链接 iSH（GPLv3）和 PRoot（GPLv2）；官方第三方清单还列出 Alpine、FFmpeg、LAME、Shizuku 等不同许可证组件。官方 README 同时公开描述 Provider、按需 Skill、Memory、Workspace、Native Offload 和设备端 Linux sandbox 等产品能力。

麓鸣面向商业闭源/OEM 交付，不能把 OpenMinis 应用源码、派生实现、GPL 组合模块或其构建产物直接复制、改名、静态/动态链接进 LumiAgent 后仍按闭源模块交付。许可证最终判断应由法律顾问结合具体分发与链接方式确认。

核对来源：

- [OpenMinis 官方仓库及 README](https://github.com/OpenMinis/OpenMinis)
- [OpenMinis LICENSE](https://github.com/OpenMinis/OpenMinis/blob/main/LICENSE)
- [OpenMinis THIRD_PARTY_LICENSES](https://github.com/OpenMinis/OpenMinis/blob/main/THIRD_PARTY_LICENSES.md)
- [OpenMinis Debug Server API 公开规范](https://github.com/OpenMinis/OpenMinis/blob/main/docs/specs/debug-server-api.md)

## 2. 本次允许借鉴的内容

只允许把公开、抽象的产品思想转化为麓鸣独立需求：

- Provider 字段由 schema 发现。
- Skill 元数据常驻、正文按需加载。
- Workspace 与 Memory 隔离。
- 平台重能力通过 typed native tool offload。
- 生产 Trace 脱敏并限长。
- 可选 runtime 的发现、健康检查和确定性回退。

这些思想必须先写入麓鸣自己的规范和 JSON Schema，再由未复制 OpenMinis 代码的实现者基于 Android/Java/Kotlin 公共 API独立实现。

## 3. 禁止进入商业闭源模块的材料

- OpenMinis `src/`、`deps/`、构建脚本、测试、资源、生成文件及其片段。
- 对 OpenMinis 类名、方法签名、目录布局、私有协议或数据结构的一一翻译。
- OpenMinis 修改版 PRoot/iSH 二进制、rootfs、补丁或组合构建产物。
- 从 OpenMinis APK/IPA 逆向获得的资源、协议或行为实现。
- 删除许可证头、改名或机械改写后形成的派生代码。

发现相似来源不明代码时停止合并，记录来源，隔离分支，并由安全/法务决定删除、重写或调整分发方式。

## 4. Clean-room 工作法

1. 产品人员只阅读公开 README、许可证和公开接口说明，产出功能级需求，不产出源码级伪代码。
2. 实现人员以本项目规范、Android 官方 API 和自有合同为输入，不打开或复制 OpenMinis 实现文件。
3. 新代码必须有本项目自己的命名、威胁模型、失败语义和测试。
4. 提交说明记录“OpenMinis-inspired clean-room”，同时列明没有新增其源码、子模块或二进制。
5. CI 对依赖清单、许可证、哈希、SBOM 和来源声明做门禁；正式包做内容清单比对。
6. 代码审查检查可疑字符串、包名、版权头、目录镜像和大段高相似代码。

当前 Task 9 只新增麓鸣自有合同、规范和纯 Kotlin 类型化网关，不引入 OpenMinis dependency、submodule、源码或二进制。

## 5. PRoot/Linux 的分发决策门禁

PRoot/Linux runtime 在 Task 12 中只能作为可选 backend 设计。在满足以下条件前，不进入正式 LumiAgent APK：

- 确定来源仓库、固定版本/提交、许可证及修改义务。
- 明确与闭源主应用的进程、IPC、打包和分发关系，并完成法律评审。
- 为 rootfs 内每个包生成 SBOM、许可证清单、哈希和可复现构建记录。
- 确定 companion 的升级、回滚、源码提供和书面要约策略。
- 完成网络、挂载、凭据、Shizuku/root 隔离和实体机安全测试。

如果最终采用 GPL companion，必须单独分发并履行对应 GPL 义务；“可选下载”本身不自动消除许可证义务。

## 6. Shizuku 边界

LumiAgent 不复制或内嵌 Shizuku 应用。Task 11 只允许通过经评审的兼容 API 与用户自行安装、启动并授权的服务协作，并且只暴露麓鸣定义的类型化白名单动作。`rish`、binder 转发、任意 shell 和 root 默认禁用且不得成为远程 API。

## 7. 发布检查表

- [ ] 无 OpenMinis 源码、补丁、submodule、二进制或资源。
- [ ] 新 runtime 文件均有本项目独立设计与测试证据。
- [ ] 依赖锁文件、SBOM 和第三方许可证清单已更新。
- [ ] PRoot/rootfs 如存在，已有法务批准和分发义务方案。
- [ ] Shizuku 仅为外部、用户授权、可撤销能力，不包含通用 shell。
- [ ] 正式 API 不返回 Provider 凭据、用户内容 Trace 或跨 scope Memory。
- [ ] 发行说明将 PoC、可选组件和已知限制表述准确。
