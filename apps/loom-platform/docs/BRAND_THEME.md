# 品牌主题替换说明

用于给不同客户或不同版本快速替换启动器品牌，不需要改前端代码。

## 需要替换的位置

品牌主题位于：

```text
openclaw_new_launcher/data/themes/<themeId>/
  theme.json
  logo.png
```

打包后对应：

```text
OpenClawFiles/data/themes/<themeId>/
  theme.json
  logo.png
```

当前常用 profile：

```text
lumi     -> data/themes/lumi          # Lumi 私人版 / 内部演示版
customer -> data/themes/yonghao_tech  # 客户交付版默认主题
```

打包脚本会把选择写入：

```text
OpenClawFiles/data/brand_profile.json
```

未授权、无服务器主题下发时，启动器会按这个 profile 选择默认主题。

## 可改内容

`theme.json` 里常用字段：

```json
{
  "brand": {
    "name": "永浩科技",
    "subtitle": "智能AI服务平台",
    "terminal_header": "Service Console",
    "logoUrl": "logo.png"
  },
  "window": {
    "title": "永浩科技 - 智能AI服务平台"
  },
  "modes": {
    "light": {
      "accent": "#1A56DB",
      "accent_hover": "#1444AD",
      "accent_soft": "#E4E8F0",
      "accent_ink": "#0F327F"
    },
    "dark": {
      "accent": "#9D4EDD",
      "accent_hover": "#B76BFF",
      "accent_soft": "rgba(157, 78, 221, 0.18)",
      "accent_ink": "#F5EAFF"
    }
  }
}
```

`logoUrl` 可以写同目录图片名，例如 `logo.png`。替换 Logo 时保持文件名不变最稳。

## 打包建议

1. 先确认或新增 `data/themes/<themeId>/theme.json` 和 `logo.png`。
2. 再运行打包脚本，并显式指定 `-BrandProfile`。
3. 打包完成后检查根目录仍然只有 `OpenClaw.exe` 和 `OpenClawFiles`。
4. 用 `verify-release.ps1` 检查 `brand_profile.json` 和对应主题是否存在。

示例：

```powershell
# Lumi 私人版
powershell -ExecutionPolicy Bypass -File scripts\build-portable.ps1 -BrandProfile lumi

# 客户交付版
powershell -ExecutionPolicy Bypass -File scripts\build-portable.ps1 -BrandProfile customer

# 自定义主题，要求 data/themes/acme/theme.json 存在
powershell -ExecutionPolicy Bypass -File scripts\build-portable.ps1 -BrandProfile acme
```

## 注意

当前方案是“方便出定制包”，不是防客户篡改。后续商业版可以加主题签名或授权服务器下发主题。
