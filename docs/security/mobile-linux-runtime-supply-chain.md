# 麓鸣可选 Mobile Linux Runtime：供应链与分发门禁

> 状态：麓鸣 2.4.4 / LumiAgent 6.64 架构与合同阶段，发行门禁关闭
>
> 日期：2026-08-01
> 适用对象：LumiAgent 可选 Linux companion、PRoot 类用户态兼容层及其 rootfs/工具包

## 1. 2.4.4 的确定边界

麓鸣 2.4.4 随附的 LumiAgent 6.64 只交付 clean-room 合同、类型化策略、路由回退和基准工具，不在 APK 内包含 PRoot 二进制、Linux rootfs、发行版包管理器、`rish`、Root/Sui shell 或可交互终端。设置页也不宣称 Linux runtime 已安装或已带来性能提升。

未来若通过评审，Linux runtime 必须作为用户主动安装、可独立卸载的 companion 分发。LumiAgent 只发送固定 entrypoint ID、workspace handle、资源预算、审批和幂等信息；不得发送 executable path、命令正文或任意参数向量。

## 2. 上游事实与许可证门禁

- PRoot 官方仓库：`https://github.com/proot-me/proot`。
- 官方仓库在 2026-08-01 的许可证标识为 `GPL-2.0-or-later`，`COPYING` 载明 GPLv2 条款。
- rootfs、发行版包、动态库和工具各有自己的许可证、来源和安全更新责任，不能把“PRoot 是 GPL”误当成整个组合发行物已经完成合规。
- OpenMinis 的功能设计可以作为需求参考，但不得复制其 GPLv3 组合源码、补丁、构建脚本或打包产物到商业闭源 APKClaw/LumiAgent。

上述记录是工程门禁，不替代正式法律意见。任何二进制分发前必须由负责人确认分发形态、对应源码提供方式、许可证/版权声明、修改记录和下游依赖义务。

## 3. 允许的分发形态

只有以下方案可进入候选评审：

1. 单独签名、单独版本、单独下载和卸载的 optional companion。
2. companion 的 GPL 组件、对应源码、构建说明、补丁、许可证和 notice 可被用户从同一发布记录取得。
3. LumiAgent 与 companion 通过版本化数据合同通信，并由法律评审确认边界；不得以“单独进程”自动推定许可证没有传播影响。
4. rootfs 作为独立制品审查和分发，具有自己的来源、哈希、SBOM、许可证清单、CVE 基线和更新周期。

禁止直接把 PRoot/rootfs 静态链接、复制或解压进正式 APK 后仍按闭源依赖处理；禁止从不受控镜像、网盘或运行时任意 URL 安装。

## 4. 制品清单与证明

每个候选 companion/rootfs 必须同时具备：

- 不可变版本号和发布提交；
- SHA-256 和独立签名；
- SPDX 或 CycloneDX SBOM；
- 上游源码 URL、源码归档哈希和构建容器/工具链版本；
- 完整许可证、notice、修改补丁和对应源码交付记录；
- 支持的 ABI、最低 Android 版本、预计解压空间和最小空闲空间；
- 已知 CVE、修复状态、EOL 日期和回滚版本；
- 可复现构建或差异解释；
- 安装、健康检查、卸载与失败恢复测试证据。

缺少任一项时，合同状态只能是 `missing`、`damaged` 或 `unhealthy`，不得进入 `ready`。

## 5. 安装与升级事务

安装流程固定为：

```text
用户主动开启
  -> 检查 ABI / Android / 电量 / 可用空间
  -> 仅从白名单 HTTPS 来源下载到 staging
  -> 校验签名、artifact SHA-256、SBOM SHA-256
  -> 校验许可证清单和版本撤销列表
  -> 解包到本账号 runtime staging（不可见于当前版本）
  -> 无网络健康检查 + 资源上限测试
  -> 原子切换 active pointer
  -> 保留上一个健康版本用于回滚
```

任何一步失败都删除本次 staging 中可再生成文件并保留上一个健康版本；不得删除用户 workspace、Memory、输入、输出或附件。升级后健康检查失败时原子切回旧版本，不允许主 LumiAgent 进程因 companion 故障退出。

## 6. 隔离策略

- 输入以只读 handle 挂载，输出写入当前账号/客户/workspace 的隔离目录。
- companion 不可见 LumiAgent 私有数据库、KeyStore、Provider 凭据、其他账号 workspace、系统目录和宿主 Unix socket。
- 网络默认拒绝；只按任务 manifest 与用户审批临时放行完整 Provider hostname，不支持通配符、裸 IP 或重定向扩域。
- 凭据只通过有时效的一次性 vault handle 注入，runtime 不可回读或持久化凭据值。
- Native Offload 只能调用 `TypedNativeToolGateway` 的封闭能力；不得连接 Shizuku binder、`rish`、root shell 或系统包管理器。
- entrypoint 只能是合同枚举：`workspace.text.batch`、`workspace.jsonl.transform`、`agent.cli.batch`。具体适配器由已签名 manifest 解析，不接收模型或 LAN 提交的命令行。

## 7. 故障与回退

- 缺失、禁用、损坏、空间不足或健康检查失败发生在执行前：优先选择原生类型化工具；无原生等价能力时，只能选择已经审批的远程路径或返回明确不可用。
- OOM、超时、停止或 binder/进程丢失发生在执行开始后：标记 `linux_outcome_indeterminate`，禁止自动重放写操作，等待幂等状态查询或人工确认。
- companion 的故障不关闭配对、LAN/USB、MediaProjection、急停或标准 Agent 能力。

## 8. 性能声明门禁

PRoot/Linux 不是通用加速器。可能的收益只来自把多步文本/文件处理合并到本地、减少模型/网络往返或复用热进程；原生 Android 能力通常仍更快。

`tools/benchmark-mobile-runtime.ps1` 生成三类分离结果：原生 host harness 实测、可选 companion 实测（仅在提供已核对 SHA-256 的固定 benchmark adapter 时）以及明确标记的远程延迟模型。合成结果不能对外宣称提速。

对外性能结论必须来自至少 Android 7、10、14+ 的实体机，记录冷/热启动、端到端耗时、峰值内存、存储、电量/温升、失败率和输入规模；同任务至少 20 次，报告中位数和 P95。若 Linux 路径慢于原生，调度器必须保留原生快路径。

## 9. 当前结论

2.4.4 可以安全冻结“未来怎么接”的合同和策略，但不能把 PRoot/rootfs 当作已交付功能，更不能写成已证明的加速。发行门禁只有在供应链、许可证、实体机性能和故障恢复证据全部通过后才能开启。
