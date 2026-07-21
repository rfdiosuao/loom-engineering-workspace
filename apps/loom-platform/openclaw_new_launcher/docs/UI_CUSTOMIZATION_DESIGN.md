# UI 自定义与模块化设计方案

> 目标：让启动器在不改业务代码的前提下，快速替换品牌、颜色、文案和部分布局。

## 1. 设计原则

1. 外壳和业务分离。
2. 品牌和主题配置化。
3. 页面和菜单注册化。
4. 默认值必须可回退。
5. 商户定制尽量不碰核心逻辑。

这套方案不是“把所有东西都做成配置”，而是把最常变的东西独立出来：

- 品牌名
- Logo
- 窗口标题
- 主题颜色
- 菜单项
- 常用文案

## 2. 三层结构

### 2.1 外壳层

负责界面骨架和全局区域：

- 顶部标题栏
- 左侧侧边栏
- 主工作区
- 底部状态区
- 弹窗容器

这一层尽量稳定，只控制布局，不写业务规则。

### 2.2 主题层

负责视觉和品牌：

- 名称
- 副标题
- Logo
- 窗口标题
- 颜色
- 字体
- 图标

当前对应文件主要是：

- `openclaw_new_launcher/data/themes/default/theme.json`
- `openclaw_new_launcher/data/themes/default/logo.png`
- `openclaw_new_launcher/src/theme/default.ts`
- `openclaw_new_launcher/python/core/theme_manager.py`

### 2.3 功能层

负责具体功能页：

- 服务日志
- 授权页
- API 配置
- AI 生图
- AI 视频
- 广告视频
- 飞书 / 微信绑定
- Skills

这一层通过注册表挂到菜单，不直接写死在壳里。

## 3. 当前可自定义项

建议优先支持这些项目：

- `brand.name`
- `brand.subtitle`
- `brand.logoUrl`
- `window.title`
- `colors.accent`
- `colors.sidebar_bg`
- `colors.surface`
- `colors.text`
- `navItems`
- 部分页面标题文案
- 空状态文案
- 按钮文案

## 4. 暂不建议开放的项

以下内容不建议先做成客户可自由配置：

- Bridge 启动逻辑
- 授权验签逻辑
- OpenClaw 进程管理
- API 协议字段
- 插件命令名
- 运行时目录结构

这些属于稳定底座，暴露太多会让维护成本暴涨。

## 5. 推荐配置模型

建议把可变内容分成两份：

### 5.1 `theme.json`

只放视觉和品牌信息：

```json
{
  "brand": {
    "name": "客户品牌",
    "subtitle": "智能AI服务平台",
    "terminal_header": "Service Console",
    "logoUrl": "logo.png"
  },
  "window": {
    "title": "客户品牌 - 智能AI服务平台"
  },
  "modes": {
    "light": {
      "accent": "#1A56DB"
    },
    "dark": {
      "accent": "#9D4EDD"
    }
  }
}
```

### 5.2 `ui-profile.json`

建议未来新增一份 UI 配置文件，专门放布局和文案：

```json
{
  "layout": {
    "sidebarWidth": 286,
    "topbarHeight": 40,
    "density": "comfortable"
  },
  "navigation": {
    "hidden": ["diagnostics"],
    "order": ["terminal", "image", "video", "license"]
  },
  "copy": {
    "serviceStart": "启动核心服务",
    "serviceStop": "停止服务",
    "emptyLog": "等待服务启动..."
  },
  "links": {
    "docs": "https://example.com",
    "skills": "https://www.skillhub.cn/skills"
  }
}
```

`theme.json` 管“长什么样”，`ui-profile.json` 管“怎么组织和怎么说话”。

## 6. 运行时流程

建议加载顺序：

1. 读取本地主题模式。
2. 先应用默认主题，避免白屏闪烁。
3. 拉取当前品牌主题。
4. 合并 `theme.json`。
5. 合并 `ui-profile.json`。
6. 生成菜单、标题、按钮文案。
7. 如果加载失败，回退到默认主题。

## 7. 目录建议

推荐最终结构：

```text
openclaw_new_launcher/
  data/
    themes/
      default/
        theme.json
        logo.png
    ui-profile.json
  src/
    theme/
    features/
    components/
```

## 8. UI 外壳拆分建议

建议把壳拆成四个稳定组件：

- `WindowTitlebar`
- `Sidebar`
- `Workspace`
- `StatusBar`

每个页面只负责渲染内容，不直接控制整壳布局。

## 9. 菜单注册建议

菜单不要硬编码在组件里，应该来自功能注册表：

- `src/features/registry.ts`
- `src/features/pages.tsx`

一个功能要能带着这些信息注册：

- key
- label
- desc
- group
- icon
- license requirement
- action 类型

这样新增页面时，只加注册项，不改大壳。

## 10. 自定义包交付方式

建议以后给客户交付两类包：

### 10.1 通用包

- 固定品牌
- 固定菜单
- 固定主题
- 适合内部测试和演示

### 10.2 客户定制包

- 客户 Logo
- 客户名称
- 客户主题色
- 客户默认菜单
- 客户文案

这类包只替换主题和配置，不改底层代码。

## 11. 实施顺序

推荐按这个顺序做：

1. 统一主题入口。
2. 抽出 `ui-profile.json`。
3. 菜单注册化。
4. 页面标题和空状态配置化。
5. 导出/导入主题包。
6. 最后再做客户级白标包。

## 12. 验收标准

如果这套设计完成，应该满足：

- 不改业务代码就能换 Logo、名称和主色。
- 不改页面代码就能隐藏或重排菜单。
- 不同客户可以共用同一个启动器底座。
- 视觉和业务不会互相缠住。
- 主题失败时能自动回退默认值。

## 13. 和现有文档的关系

相关文档：

- `docs/BRAND_THEME.md`
- `docs/BRANDING_AND_PACKAGING.md`
- `openclaw_new_launcher/docs/MODULE_EXTENSION_GUIDE.md`
- `openclaw_new_launcher/docs/PRODUCT_ROADMAP.md`

这份文档是“UI 自定义”的总设计，品牌文档偏换壳操作，模块扩展文档偏功能扩展。
