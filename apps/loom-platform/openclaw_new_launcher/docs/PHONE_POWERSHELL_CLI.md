# LOOM Phone CLI PowerShell Notes

PowerShell 会改写内联 JSON 引号。手机动作请优先用文件或 stdin 传参。

## 连接配置

```powershell
$env:OPENCLAW_PHONE_BASE_URL = "http://手机IP:9527"
$env:OPENCLAW_PHONE_TOKEN = "<APKClaw LAN Config 里的连接令牌>"
node scripts\openclaw-phone-agent.mjs metrics --json
```

如果连接失败，请打开手机端 `APKClaw -> Settings -> LAN Config`，确认局域网服务已开启，并确认电脑和手机在同一网络。

## 动作 JSON 文件

```powershell
$body = @{
  action = "tap"
  gridCell = "C7"
  targetLabel = "settings button"
  reason = "open settings"
} | ConvertTo-Json -Compress

Set-Content -Encoding UTF8 .\action.json $body
node scripts\openclaw-phone-vision.mjs action --force-action --action-body-file .\action.json --json
```

## 动作 JSON stdin

```powershell
$body | node scripts\openclaw-phone-vision.mjs action --force-action --action-body-stdin --json
```

## 配置来源

CLI 的 JSON 输出会包含 `configSource`。如果为空，先在麓鸣手机页保存连接；也可以临时使用上面的环境变量。
