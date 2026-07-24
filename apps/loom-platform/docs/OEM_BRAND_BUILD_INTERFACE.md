# LOOM OEM 统一品牌构建接口

OEM 工厂必须通过统一入口构建，不应直接修改核心仓中的品牌名称、图标或应用标识。

## 命令

```powershell
apps/loom-platform/scripts/build-brand.ps1 `
  -BrandPath D:\path\to\brands\customer `
  -OutputPath D:\path\to\artifacts\customer-build `
  -Configuration Release `
  -FactoryCommit <40-character-factory-commit>
```

`BrandPath` 必须包含：

- `brand.json`
- `copy.json`
- `modules.json`
- `assets/`

只校验和编译品牌计划，不生成交付产物：

```powershell
apps/loom-platform/scripts/build-brand.ps1 `
  -BrandPath D:\path\to\brands\demo-brand `
  -OutputPath D:\path\to\artifacts\demo-plan `
  -Configuration Debug `
  -FactoryCommit <40-character-factory-commit> `
  -AllowDemo `
  -PlanOnly
```

## 签名输入

正式构建必须通过进程环境提供签名材料：

- `LOOM_DESKTOP_UPDATE_PRIVATE_KEY` 或 `LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH`
- `KEYSTORE_FILE`
- `KEYSTORE_PASSWORD`
- `KEY_ALIAS`
- `KEY_PASSWORD`

品牌包、构建计划、日志和产物元数据不会写入私钥、密码或令牌。桌面更新配置只包含由私钥派生的 Ed25519 公钥。

## 输出

完整构建成功后，`OutputPath` 至少包含：

```text
windows/
  <file-prefix>-<version>-setup.exe
  <file-prefix>-Portable-v<version>-oem.zip
android/
  <file-prefix>-phone-<version>.apk
update/
  latest.json
metadata/
  build-provenance.json
  artifacts.sha256.txt
brand-build-plan.json
```

若品牌未启用手机矩阵，则不会构建 Android APK。

`build-provenance.json` 记录品牌 ID、核心仓提交、工厂仓提交、版本、构建时间和每个产物的 SHA-256。

## 失败关闭

以下情况不会生成假成功产物：

- 品牌配置不完整、路径越界、模块冲突或包含疑似密钥字段；
- 正式品牌使用 HTTP、占位域名或非 `active` 状态；
- 工厂提交或核心提交不是完整 Git SHA；
- 桌面更新私钥或 Android 签名材料缺失；
- Windows 安装包、便携包、更新签名、APK 或来源证明缺失；
- 输出目录包含同名旧构建目录；
- 正式产物构建使用非 `Release` 配置。

## 参数化范围

统一入口覆盖：

- 前端品牌名称、说明、首页文案、任务输入文案和模块可见性；
- 运行时主题、Logo、窗口标题；
- Tauri `productName`、`identifier`、主程序名、程序图标和 NSIS 素材；
- Android `applicationId`、应用名称、图标和 APK 文件前缀；
- 桌面更新产品、通道、缓存隔离、文件前缀、清单地址和签名公钥；
- 便携包名称、启动程序名、品牌主题和更新配置。
