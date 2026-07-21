# OpenClaw 启动器模块扩展说明

> 目标：让后续新增功能、视频模型、机器人插件和 skills 时，尽量只改清晰边界内的文件。

## 1. 功能入口

前端功能入口集中在：

- `src/features/registry.ts`
- `src/features/pages.tsx`

新增一个普通页面功能时：

1. 在 `src/components/` 下创建页面组件。
2. 在 `src/features/pages.tsx` 注册页面组件。
3. 在 `src/features/registry.ts` 增加功能定义。

功能定义示例：

```ts
{
  key: 'new_feature',
  label: '新功能',
  desc: '显示在菜单里的说明',
  icon: 'NEW',
  group: '工作台',
  requiresLicense: true,
  action: { type: 'page' },
}
```

## 2. 菜单与权限

菜单不再建议直接写死在 `Sidebar.tsx` 里。

- 菜单来源：`FEATURE_DEFINITIONS`
- 授权控制：`requiresLicense`
- 外部链接：`action: { type: 'external', url }`
- 弹窗入口：`action: { type: 'dialog', dialog }`
- 特殊动作：`action: { type: 'command', command }`

这样新增功能时不用反复改 `App.tsx` 的跳转逻辑。

## 3. 视频服务商

视频服务商定义集中在：

- `src/features/video/providers.ts`

当前设计为三层：

- 服务商：阿里云 DashScope / 火山引擎 Seedance / 自定义兼容服务
- 模型：不同服务商维护自己的模型列表
- 参数：文生视频、图生视频、分辨率、时长、比例、图片输入

新增视频服务商时：

1. 在 `VIDEO_PROVIDERS` 中增加 provider。
2. 前端会自动显示服务商和模型。
3. 后端在 `python/services/video_api.py` 中增加对应 adapter。

## 4. 后端视频 Adapter

当前后端视频入口仍是：

- `python/services/video_api.py`
- `python/bridge.py` 的 `/api/video/generate`

请求字段已经支持：

```json
{
  "providerId": "dashscope",
  "apiBase": "https://example.com",
  "model": "model-id",
  "dashKey": "api-key",
  "prompt": "提示词",
  "mode": "t2v",
  "resolution": "720P",
  "duration": 5,
  "ratio": "16:9"
}
```

注意：字段名 `dashKey` 为兼容旧代码保留，后续 FastAPI 迁移时可重命名为 `apiKey`。

## 5. Skills 契约

Skills 的基础契约在：

- `src/features/skills/contract.ts`

它暂时不执行安装逻辑，只定义未来 skills 应该具备的元信息：

- id
- name
- version
- category
- runtime
- configFields
- nav

后续可以在此基础上继续做：

- skills 列表页
- 安装 / 卸载
- 启用 / 禁用
- 权限检测
- 配置面板
- 执行日志

## 6. 当前边界

本次只是模块化入口和 provider 骨架，不是 FastAPI 大迁移。

当前仍需后续处理：

- `python/bridge.py` 还是手写 HTTP 路由
- 授权仍主要在 Python 层处理
- 视频服务商 adapter 仍集中在一个 Python 文件里
- skills 还没有完整运行时

这些会在 FastAPI 迁移和插件系统阶段继续拆分。
