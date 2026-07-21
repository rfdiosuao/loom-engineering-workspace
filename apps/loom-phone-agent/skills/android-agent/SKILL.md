---
name: android-agent
description: Control Android devices via Agent Phone's built-in AI Agent. Send natural language tasks and let the Agent intelligently execute them. Requires Agent Phone app with LLM configured.
version: 2.0.0
author: Agent Phone Team
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Android, AI Agent, Mobile Automation, Remote Control]
    config:
      - key: android.url
        description: Agent Phone device URL (e.g. http://192.168.1.100:9527)
        prompt: Agent Phone device URL
      - key: android.token
        description: API authentication token (configured in Agent Phone Settings → API Token)
        prompt: API Token
---

# Android Agent Control

Send natural language tasks to Agent Phone and let its built-in AI Agent intelligently
execute them on your Android device. No need to manually specify coordinates or
steps - just describe what you want done.

## Prerequisites

1. **Agent Phone app** installed on Android device (Android 9+)
2. **Accessibility Service** enabled in Agent Phone
3. **LLM configured** in Agent Phone Settings → LLM Config (requires API Key)
4. **API Token** configured in Agent Phone Settings → API Token
5. **Device reachable** via HTTP (same network or VPN)

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
skills:
  config:
    android:
      url: "http://192.168.1.100:9527"
      token: "your-api-token"
```

Or configure via `hermes config set`:

```bash
hermes config set skills.config.android.url http://192.168.1.100:9527
hermes config set skills.config.android.token your-api-token
```

## How It Works

When you use this skill, Hermes sends your task to Agent Phone's built-in Agent,
which then:

1. Analyzes the current screen state
2. Plans the necessary steps to complete your task
3. Executes actions (tap, swipe, input text, etc.)
4. Verifies results and adjusts if needed
5. Returns the final outcome

You don't need to specify exact coordinates or detailed steps - the Agent
handles all of that intelligently.

## Quick Reference

| Endpoint | Description |
|----------|-------------|
| `/api/agent/execute_task` | Execute a task (main endpoint) |
| `/api/agent/status` | Check agent status |
| `/api/agent/cancel_task` | Cancel running task |

## Execute Task

Send a natural language task to the Agent:

```bash
curl -s -X POST "${ANDROID_URL}/api/agent/execute_task" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "打开微信"}'
```

Response (waits up to 120 seconds for completion):

```json
{
  "success": true,
  "data": "{\"success\":true,\"answer\":\"任务完成\",\"rounds\":5,\"tokens\":1200}"
}
```

## Task Examples

Here are examples of tasks you can send:

### App Operations

```bash
# Open an app
'{"prompt": "打开微信"}'
'{"prompt": "打开支付宝"}'
'{"prompt": "打开抖音"}'

# Open and perform action
'{"prompt": "打开微信，查看朋友圈"}'
'{"prompt": "打开支付宝，扫一扫"}'
```

### Messaging

```bash
# Send message
'{"prompt": "打开微信，给张三发消息说下午三点开会"}'
'{"prompt": "打开QQ，给李四发文件，选择最近的照片"}'

# Check messages
'{"prompt": "打开微信，看看有没有新消息"}'
```

### Social Media

```bash
# Browse content
'{"prompt": "打开抖音，看几个视频"}'
'{"prompt": "打开微博，搜索最近的科技新闻"}'
'{"prompt": "打开小红书，搜索美食推荐"}'
```

### Shopping

```bash
# Search and browse
'{"prompt": "打开淘宝，搜索蓝牙耳机"}'
'{"prompt": "打开京东，看看我的订单"}'
'{"prompt": "打开美团，点一杯奶茶外卖"}'
```

### System Operations

```bash
# Settings
'{"prompt": "打开设置，调低屏幕亮度"}'
'{"prompt": "打开设置，关闭WiFi"}'
'{"prompt": "打开设置，查看电池用量"}'

# Files
'{"prompt": "打开文件管理，找到最近下载的PDF文件"}'
```

### Complex Tasks

```bash
# Multi-step tasks
'{"prompt": "打开微信，找到群聊"工作群"，发送今天的日报截图"}'
'{"prompt": "打开支付宝，充值话费100元"}'
'{"prompt": "打开音乐APP，播放我喜欢的歌单"}'
```

## Check Status

```bash
curl -s "${ANDROID_URL}/api/agent/status" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

Response:

```json
{
  "success": true,
  "data": {
    "taskRunning": false,
    "agentInitialized": true,
    "llmConfigured": true,
    "accessibilityRunning": true
  }
}
```

## Cancel Task

```bash
curl -s -X POST "${ANDROID_URL}/api/agent/cancel_task" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

## Response Format

All responses follow this format:

```json
{
  "success": true|false,
  "data": {
    "success": true|false,
    "answer": "Agent's final response",
    "error": "Error message if failed",
    "rounds": 5,
    "tokens": 1200
  }
}
```

## Error Handling

| Error | Solution |
|-------|----------|
| `Unauthorized` | Check token in Hermes config and Agent Phone Settings |
| `Accessibility service is not running` | Enable accessibility in Agent Phone |
| `LLM not configured` | Configure LLM in Agent Phone Settings → LLM Config |
| `A task is already running` | Wait or cancel the current task first |
| `Task timeout` | Task took too long (>120s), try simpler task |
| `System dialog blocked` | Check screen for system popups |

## Best Practices

1. **Keep tasks simple**: Break complex tasks into smaller ones
2. **Be specific**: Mention exact app names, contact names, or actions
3. **Check status first**: Ensure agent is ready before sending tasks
4. **Handle timeouts**: Complex tasks may need multiple calls
5. **Use Chinese**: For Chinese apps, use Chinese prompts for better recognition

## Limitations

- Task execution is synchronous (blocks up to 120 seconds)
- Only one task can run at a time
- Screen must be on and unlocked
- Protected system dialogs may block operations
- Agent depends on LLM quality and configuration

## Integration Tips

### When to use this skill

- User asks to perform actions on their phone
- User mentions specific apps (微信, 抖音, 淘宝, etc.)
- User wants automated mobile interactions

### Example Hermes prompts

```
User: "帮我用微信给老王发个消息说今天加班"
→ Use android-agent skill: execute_task with prompt "打开微信，给老王发消息说今天加班"

User: "看看我淘宝订单有没有发货"
→ Use android-agent skill: execute_task with prompt "打开淘宝，查看我的订单状态"

User: "手机上搜一下附近的餐厅"
→ Use android-agent skill: execute_task with prompt "打开美团，搜索附近的餐厅"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check device IP, ensure LAN Config is enabled in Agent Phone Settings |
| Token invalid | Re-generate token in Agent Phone and update Hermes config |
| Agent not initialized | Check LLM config has valid API Key |
| Task fails repeatedly | Check screen for popups, try simpler prompt |

## Resources

- Agent Phone GitHub: https://github.com/rfdiosuao/Hermes-Agent-phone
- Hermes Skills Hub: https://agentskills.io