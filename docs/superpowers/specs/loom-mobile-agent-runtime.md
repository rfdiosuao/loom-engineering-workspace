# 麓鸣 Mobile Agent Runtime 规范（PoC v1）

状态：PoC 接口冻结，尚未作为默认生产能力启用
日期：2026-08-01
合同：`packages/contracts/mobile-agent-runtime.schema.json`

## 1. 目标

Mobile Agent Runtime 是 LumiAgent 的可选执行层，不替换现有 Android 原生 RPA、无障碍、截图、视频流、网络服务和急停能力。它为 Provider、Workspace、Memory、Skill、Native Offload 和后续可选 Linux backend 建立统一、类型化、可审计的边界。

本规范解决五个问题：

1. Provider 表单和协议能力由 schema 发现，手机 UI 与运行时不硬编码特定厂商字段。
2. Workspace 与 Memory 同时按账号、客户、工作区隔离。
3. Skill 仅常驻元数据，正文和资源在被选中且授权后按需加载。
4. 平台能力只能通过 `TypedNativeToolGateway` 的闭合集调用。
5. backend 缺失、未授权、不健康或被撤销时，确定性回退 Android 原生快路径，或者在执行前明确拒绝。

## 2. 非目标

- 不复制 OpenMinis 源码、协议实现、文件布局或 GPL 组合工程。
- PoC 不内嵌 Alpine rootfs、PRoot、`rish`、root shell 或通用终端。
- 不向模型、Skill、LAN API 或第三方 Agent 暴露任意命令字符串。
- 不允许可选 runtime 绕过麓鸣账号授权、确认、白名单、频控、幂等和审计。
- 不让调试 API 与正式配对 API 共用启用开关；正式包默认关闭调试 API。

## 3. 分层

```text
LOOM Desktop Control Plane
  -> account entitlement / approval / rate limit / audit
  -> Mobile Runtime contract + short-lived capability grant

LumiAgent Device Execution Plane
  -> Mobile Runtime Coordinator
       -> Provider Schema Registry (metadata only)
       -> Workspace Resolver (opaque handle)
       -> Memory Namespace (account + customer + workspace)
       -> Skill Metadata Catalog (lazy body loading)
       -> Backend Selector
            -> Android Native (default fast path)
            -> Optional Linux Runtime (later, separate gate)
       -> TypedNativeToolGateway (closed capability set)
```

控制面只下发被批准的能力子集。设备端再次校验 scope、审批 ID、过期时间、参数 schema 和幂等键；任何一层失败都在实际动作前失败关闭。

## 4. 统一合同

根对象使用 `loom.mobile-agent-runtime.v1`，包含：

- `scope`：`accountId + customerId + workspaceId`，三者都只允许安全 ID。
- `providerSchemas`：字段类型、必填性、敏感性和只写属性，不含值。
- `providerConfigurations`：普通值与 `vault:` 凭据句柄分离，禁止返回凭据值。
- `workspacePolicy`：只读输入、独立输出、禁宿主 socket、只接收凭据句柄。
- `memoryPolicy`：禁止跨账号、跨客户，并复用相同 scope。
- `skills`：仅元数据、来源摘要和所需能力。
- `capabilityGrant`：短期审批与闭合集，`remoteShell=false`、`arbitraryCommands=false`。
- `backends`：发现状态、授权状态、能力和确定性回退顺序。
- `tracePolicy`：敏感头脱敏、响应摘录上限、调试 API 默认关闭。

合同由 `packages/contracts/validate_contracts.py` 按 Draft 2020-12 校验，并有不包含真实密钥的 fixture。

## 5. Provider schema 与凭据事务

### 5.1 发现

`MobileProviderSchemaRegistry.discover()` 只返回 schema 元数据。任何 `SECRET` 字段必须同时标记 `sensitive=true` 和 `writeOnly=true`；构造不安全 schema 直接失败。

### 5.2 原子写入

Provider 配置流程固定为：

1. 校验 schema、协议和 Base URL。
2. 将非敏感配置写入 staging 文件。
3. 将密钥写入 AndroidKeyStore 支持的 vault，取得不透明 `vault:` handle。
4. 使用 staging 配置执行最小 live probe。
5. 成功后原子切换配置指针为 `committed`；失败则删除新 handle 并恢复旧指针。

任何读取接口只返回 handle 的存在状态和末次验证结果，不返回密钥、Authorization header 或可逆摘要。

## 6. Workspace 与 Memory

Workspace 解析器只接受合同中的 opaque `workspace:` handle，禁止外部传入绝对路径、`..`、符号链接逃逸目标或宿主 socket。运行时视图固定为：

```text
input/   read-only
output/  read-write, isolated
cache/   regenerable, quota-bound
```

Memory 物理命名空间必须绑定完整 scope。账号或客户切换时，旧 scope 立即从当前运行时解绑；后台写入携带启动时 generation，generation 不一致则丢弃。Memory 不自动复制到另一个账号或客户，导入必须走显式、可审计流程。

## 7. Skill 按需加载

Desktop 与 Mobile 共享以下最小元数据：`id`、`version`、`summary`、`sourceDigest`、`requiredCapabilities`。调度器先根据元数据选择候选 Skill，再校验来源摘要和能力 grant，最后才读取 `SKILL.md` 正文及必要资源。

Skill 不可声明合同闭集之外的设备能力。请求 shell、Shizuku binder、root、宿主 socket或未声明网络域名的 Skill 在加载阶段拒绝，不进入执行阶段。

## 8. Typed Native Offload

PoC 的 `MobileRuntimeCapability` 是编译期闭合集：

- `device.screen.observe`
- `device.profile.read`
- `device.app.open`
- `device.system.key`
- `workspace.file.read`
- `workspace.file.write`

`TypedNativeToolGateway` 对每次调用按顺序校验：grant 启用、scope 完全相等、审批 ID、过期时间、能力子集、幂等键、handler 注册和参数 schema。未知参数（包括 `command`）直接返回 `argument_not_declared`。

相同 scope、capability 和幂等键只执行一次；输入一致时返回缓存结果，输入改变时返回 `idempotency_conflict`。审计只记录 capability、状态、耗时以及 scope/审批/幂等键的 SHA-256，不记录参数正文和输出内容。

## 9. Backend 发现与回退

backend 状态为 `AVAILABLE`、`UNAVAILABLE`、`UNAUTHORIZED`、`UNHEALTHY` 或 `DISABLED`。选择规则：

1. 明确请求的 backend 只有在 `AVAILABLE` 且具备能力时才可选。
2. 首选 backend 不可用时，优先选择健康的 Android Native backend。
3. 未指定 backend 时默认 Android Native 快路径，再按 priority 和稳定 ID 选择。
4. 没有 backend 可执行时返回 `capability_unavailable`，不得先执行一部分再回退。

Linux runtime 超时、OOM、撤权和损坏的具体策略由 Task 12 合同补充；不得把一个 backend 的半执行动作自动重放到另一个 backend。

## 10. Trace 与调试隔离

`MobileRuntimeTraceSanitizer` 至少脱敏 `Authorization`、`Proxy-Authorization`、`x-api-key`、`api-key`、Cookie 和 Set-Cookie，普通 header 每项限长，响应摘录默认最多 2048 字符、硬上限 16384 字符。

生产 API 只提供健康状态、能力与脱敏结果；请求/响应调试 body、Provider 原始配置和 runtime 文件浏览只能存在于 debug build，并要求本地开发开关。正式构建的合同固定 `debugApiEnabled=false`。

## 11. PoC 验收与后续门禁

已由 JVM 单测覆盖：闭集能力、scope/过期/参数失败关闭、幂等执行、审计脱敏、Provider credential 只写、可选 backend 失败后回退 Native、Trace 限长脱敏。

进入生产前仍需：

- 把 Provider 配置事务接到现有 AndroidKeyStore vault，并做故障注入回滚测试。
- 实现真实 Workspace/Memory 存储并验证账号/客户并发切换。
- 建立 Desktop/Mobile Skill 元数据一致性合同测试。
- 对每个真实 Native handler 做参数、审批、超时和实体机测试。
- 完成 Task 11 Shizuku 与 Task 12 PRoot/Linux 的独立安全及供应链门禁。

## 12. 参考来源

本规范只参考公开功能描述与接口思想，不参考实现源码：

- [OpenMinis README](https://github.com/OpenMinis/OpenMinis)
- [OpenMinis Debug Server API](https://github.com/OpenMinis/OpenMinis/blob/main/docs/specs/debug-server-api.md)
- [本项目 OpenMinis 许可证边界](../../security/openminis-license-boundary.md)
