# 更换 Logo、名称并重新打包

这份文档用于二开交付时快速替换品牌信息，包括启动器内的 Logo、显示名称、窗口标题、主题颜色和打包产物。

## 1. 两种换法

### 轻量换肤

只改客户在启动器里能看到的品牌：

- 左侧 Logo
- 左侧品牌名称
- 副标题
- 窗口标题
- 主题颜色

这是最推荐的交付方式，风险低，不需要改业务代码。

### 完整换壳

除了上面的内容，还要改：

- `OpenClaw.exe` 的图标
- 任务栏图标
- Windows 文件夹中显示的程序图标
- Tauri 产品名
- 安装包/便携包命名

完整换壳必须重新构建 Tauri 应用。

## 2. 主要文件

### 启动器运行时品牌

```text
openclaw_new_launcher/data/themes/default/theme.json
openclaw_new_launcher/data/themes/default/logo.png
```

`theme.json` 控制界面文字和颜色，`logo.png` 控制启动器内部展示的品牌图。

### 内置兜底品牌

```text
openclaw_new_launcher/src/theme/default.ts
openclaw_new_launcher/python/core/theme_manager.py
```

如果主题文件缺失，启动器会使用这里的内置默认值。正式换壳建议一起改，避免缺文件时露出旧品牌。

### 程序图标

```text
openclaw_new_launcher/logo.ico
openclaw_new_launcher/logo_square.ico
openclaw_new_launcher/logo_256.png
openclaw_new_launcher/src-tauri/icons/
```

`src-tauri/icons/` 会影响 Windows 任务栏、文件图标和打包图标。

### 窗口和产品名

```text
openclaw_new_launcher/index.html
openclaw_new_launcher/src-tauri/tauri.conf.json
```

`index.html` 影响页面初始标题和 favicon，`tauri.conf.json` 影响 Tauri 窗口标题、产品名、应用标识和打包图标。

## 3. 替换启动器内 Logo 和名称

编辑：

```text
openclaw_new_launcher/data/themes/default/theme.json
```

重点字段如下：

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
  }
}
```

然后替换：

```text
openclaw_new_launcher/data/themes/default/logo.png
```

建议 Logo 规格：

- 正方形 PNG
- 推荐 `512x512` 或 `1024x1024`
- 背景尽量透明或纯色
- 不要使用过小、模糊或带大面积白边的图片

## 4. 替换程序图标

准备一张正方形 PNG，例如：

```text
D:\brand\logo.png
```

在项目目录执行：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run tauri -- icon D:\brand\logo.png
```

然后同步根目录图标：

```powershell
Copy-Item .\src-tauri\icons\icon.ico .\logo.ico -Force
Copy-Item .\src-tauri\icons\icon.ico .\logo_square.ico -Force
Copy-Item .\src-tauri\icons\128x128@2x.png .\logo_256.png -Force
Copy-Item D:\brand\logo.png .\data\themes\default\logo.png -Force
```

如果 `npm run tauri -- icon` 不可用，需要手动准备并覆盖 `src-tauri/icons/` 下的图标文件，至少包括：

```text
32x32.png
128x128.png
128x128@2x.png
icon.ico
icon.icns
```

## 5. 修改窗口标题和产品名

编辑：

```text
openclaw_new_launcher/index.html
```

将 `<title>` 改成新名称：

```html
<title>客户品牌 - 智能AI服务平台</title>
```

编辑：

```text
openclaw_new_launcher/src-tauri/tauri.conf.json
```

常用字段：

```json
{
  "productName": "OpenClaw",
  "identifier": "com.yonghaotech.openclaw",
  "app": {
    "windows": [
      {
        "title": "客户品牌 - 智能AI服务平台"
      }
    ]
  }
}
```

建议：

- 面向客户展示的标题可以改。
- 如果只是普通贴牌交付，`productName` 可以暂时保留 `OpenClaw`，便于脚本和文档统一。
- 如果要把 exe 名也改掉，需要同步修改打包脚本和验收脚本。

涉及脚本：

```text
scripts/build-portable.ps1
scripts/verify-release.ps1
```

## 6. 清理旧主题缓存

打包或测试前，如果存在下面文件，它可能覆盖默认主题：

```text
openclaw_new_launcher/data/theme.json
```

正式交付包建议不要带这个文件，优先使用：

```text
openclaw_new_launcher/data/themes/default/theme.json
```

## 7. 构建前检查

在仓库根目录执行：

```powershell
cd D:\Axiangmu\AUSTART
powershell -ExecutionPolicy Bypass -File scripts\verify-source-text.ps1 -NoGit
```

然后构建前端：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run build
```

如果换了 Tauri 图标，建议清理一次 Rust 构建缓存：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher\src-tauri
cargo clean
```

## 8. 重新打包 Windows 便携版

回到仓库根目录：

```powershell
cd D:\Axiangmu\AUSTART
powershell -ExecutionPolicy Bypass -File scripts\build-portable.ps1 -Version 2.0.1 -PackageName OpenClaw-Portable-v2.0.1-YYYY.MM.DD-brand
```

打包成功后会在 `release/` 下生成便携包目录和 zip 文件。

## 9. 打包后验收

检查包根目录是否只有：

```text
OpenClaw.exe
OpenClawFiles/
```

然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\OpenClaw-Portable-v2.0.1-YYYY.MM.DD-brand.zip
```

手动打开一次启动器，确认：

- 顶部栏 Logo 正常
- 左侧 Logo 正常
- 窗口标题是新名称
- 任务栏图标是新图标
- 文件夹里的 `OpenClaw.exe` 图标是新图标
- 未授权状态不会自动带出旧授权
- API Key 输入框默认为空

## 10. 常见问题

### 只改了 `theme.json`，为什么文件图标没变？

`theme.json` 只控制启动器内部 UI，不控制 Windows 文件图标。文件图标需要更新 `src-tauri/icons/` 并重新构建 Tauri。

### 只改了 `src-tauri/icons/`，为什么左侧 Logo 没变？

左侧 Logo 来自主题目录：

```text
openclaw_new_launcher/data/themes/default/logo.png
```

### 为什么刚打开时闪一下旧标题？

页面初始化时会先读取 `index.html` 和 Tauri 窗口标题，主题加载后再更新。因此换壳时要同时改：

```text
openclaw_new_launcher/index.html
openclaw_new_launcher/src-tauri/tauri.conf.json
openclaw_new_launcher/data/themes/default/theme.json
```

### 为什么交付包打开后已经授权？

说明包里混入了本地激活文件。交付前必须确认不存在：

```text
data/license.json
data/install_id.txt
```

### 为什么客户看到旧 API Key？

说明包里混入了本地配置。交付前必须确认：

```text
imgapi_config.json
video_config.json
```

为空配置或不存在客户密钥。

## 11. 推荐交付命名

建议每次交付使用清晰的包名：

```text
OpenClaw-Portable-v2.0.1-2026.05.07-brand.zip
```

如果是客户定制版本，可以使用：

```text
OpenClaw-Portable-v2.0.1-2026.05.07-customer-name.zip
```
