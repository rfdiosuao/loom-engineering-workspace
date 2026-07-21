---
name: android-control
description: Control Android devices via Agent Phone HTTP API. Execute tap, swipe, screenshot, and other accessibility operations remotely. Requires Agent Phone app running on Android device with accessibility service enabled.
version: 1.0.0
author: Agent Phone Team
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Android, Accessibility, Remote Control, Mobile, Automation]
    config:
      - key: android.url
        description: Agent Phone device URL (e.g. http://192.168.1.100:9527)
        prompt: Agent Phone device URL
      - key: android.token
        description: API authentication token (configured in Agent Phone Settings)
        prompt: API Token
---

# Android Control

Control Android devices running Agent Phone via HTTP API. Execute touch gestures,
capture screenshots, read UI trees, and automate mobile interactions.

## Prerequisites

1. **Agent Phone app** installed on Android device (Android 9+)
2. **Accessibility Service** enabled in Agent Phone
3. **API Token** configured in Agent Phone Settings → API Token menu
4. **Device reachable** via HTTP (same network or VPN)

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

**How to get API Token from Agent Phone:**
1. Open Agent Phone app on your Android device
2. Go to Settings → API Token
3. Click "Generate Random" or enter your own token
4. Copy the token and save it in Hermes config

## Quick Reference

| Tool | Endpoint | Description |
|------|----------|-------------|
| **Execute Task** | `/api/agent/execute_task` | **Let Agent intelligently execute task (recommended)** |
| **Agent Status** | `/api/agent/status` | Check agent status |
| **Cancel Task** | `/api/agent/cancel_task` | Cancel running task |
| Tap | `/api/tool/tap` | Tap at coordinates |
| Swipe | `/api/tool/swipe` | Swipe gesture |
| Long Press | `/api/tool/long_press` | Long press at coordinates |
| Screenshot | `/api/tool/screenshot` | Capture screen (base64) |
| Screen Info | `/api/tool/get_screen_info` | Get UI hierarchy tree |
| Find Node | `/api/tool/find_node_info` | Find UI element by text/id |
| Open App | `/api/tool/open_app` | Open app by package name |
| Input Text | `/api/tool/input_text` | Input text to focused field |
| System Key | `/api/tool/system_key` | Press back/home/recent |
| Get Apps | `/api/tool/get_installed_apps` | List installed apps |
| Wait | `/api/tool/wait` | Wait for duration |
| Tool List | `/api/tool/list` | Get available tools |

## Agent Task Execution (Recommended)

**The Agent API is the recommended way to control your device.** Instead of manually
specifying tap/swipe coordinates, you can send a natural language prompt and let
Agent Phone's built-in AI Agent intelligently execute the task.

### Execute Task

```bash
curl -s -X POST "${ANDROID_URL}/api/agent/execute_task" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "打开微信，给张三发消息说你好"}'
```

Response (waits for task completion, up to 120 seconds):
```json
{
  "success": true,
  "data": "{\"success\":true,\"answer\":\"任务完成\",\"rounds\":5,\"tokens\":1200}"
}
```

### Check Agent Status

```bash
curl -s "${ANDROID_URL}/api/agent/status" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

Response:
```json
{
  "success": true,
  "data": "{\"taskRunning\":false,\"agentInitialized\":true,\"llmConfigured\":true,\"accessibilityRunning\":true}"
}
```

### Cancel Running Task

```bash
curl -s -X POST "${ANDROID_URL}/api/agent/cancel_task" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

### Requirements for Agent API

1. **LLM must be configured** in Agent Phone Settings → LLM Config
2. **Accessibility Service** must be enabled
3. Task execution is synchronous - waits up to 120 seconds
4. Only one task can run at a time

## Common Operations

### Tap

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/tap" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"x": 500, "y": 300}'
```

### Swipe

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/swipe" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"start_x": 0, "start_y": 500, "end_x": 500, "end_y": 500, "duration_ms": 300}'
```

### Screenshot

```bash
curl -s "${ANDROID_URL}/api/tool/screenshot" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

Response: `{"success": true, "data": "<base64-encoded-png>"}`

### Get Screen Info (UI Tree)

```bash
curl -s "${ANDROID_URL}/api/tool/get_screen_info" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

Response: `{"success": true, "data": "<xml-like-ui-hierarchy>"}`

### Open App

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/open_app" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"package_name": "com.example.app"}'
```

### Input Text

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/input_text" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello World"}'
```

### System Key (Back/Home/Recent)

```bash
# Press Back
curl -s -X POST "${ANDROID_URL}/api/tool/system_key" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "back"}'

# Press Home
curl -s -X POST "${ANDROID_URL}/api/tool/system_key" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "home"}'

# Open Recent Apps
curl -s -X POST "${ANDROID_URL}/api/tool/system_key" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "recent"}'
```

### Find Node by Text

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/find_node_info" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"text": "登录"}'
```

### Get Installed Apps

```bash
curl -s "${ANDROID_URL}/api/tool/get_installed_apps" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}"
```

## Workflow Example: Click a Button by Text

```bash
# 1. Get screen info to find button coordinates
SCREEN=$(curl -s "${ANDROID_URL}/api/tool/get_screen_info" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}")

# 2. Parse UI tree to find button (requires jq)
# The UI tree format is XML-like, parse to find node bounds
# Example: find node with text "登录"

# 3. Tap at found coordinates
curl -s -X POST "${ANDROID_URL}/api/tool/tap" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"x": 540, "y": 1200}'
```

## Workflow Example: Scroll to Find Element

```bash
curl -s -X POST "${ANDROID_URL}/api/tool/scroll_to_find" \
  -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"target_text": "目标文本", "direction": "down", "max_swipes": 10}'
```

## Error Handling

All responses follow this format:

```json
{
  "success": true|false,
  "data": "result data (if success)",
  "error": "error message (if failed)"
}
```

Common errors:
- `Unauthorized: invalid or missing token` → Check `android.token` config
- `Accessibility service is not running` → Enable accessibility in Agent Phone
- `Coordinates invalid` → Coordinates out of screen bounds
- `Android 11+ required` → Screenshot requires Android 11+

## Security Notes

- **Token required** for all `/api/tool/*` endpoints
- Configure token in Agent Phone Settings → API Token
- Token is stored locally on device (MMKV)
- Recommended: Use random 16+ character token
- Network: Ensure device is on trusted network (LAN/VPN)

## Limitations

- Screenshot requires Android 11+ (`takeScreenshot` API)
- Protected system dialogs block accessibility service
- Screen must be on for most operations
- Single-task model: only one command executes at a time

## Tips

1. **Find coordinates**: Use `get_screen_info` to get UI tree with bounds
2. **Wait for loading**: Use `wait` tool between operations
3. **Handle errors**: Check `success` field in response
4. **Vision analysis**: Use Hermes `vision_analyze` tool on screenshot base64

## Integration with Hermes

After taking a screenshot:

```
# Use vision_analyze to read the screenshot
SCREENSHOT=$(curl -s "${ANDROID_URL}/api/tool/screenshot" -H "X-AGENT-PHONE-TOKEN: ${ANDROID_TOKEN}" | jq -r '.data')
vision_analyze(image_base64="${SCREENSHOT}", question="What is displayed on this screen?")
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check device IP, ensure Agent Phone server running |
| 401 Unauthorized | Verify token in both Hermes config and Agent Phone |
| Accessibility not running | Enable in Agent Phone → Home → Accessibility |
| Tap fails | Check coordinates are within screen bounds |
| Screenshot fails | Ensure Android 11+ and screen capture permission |

## Resources

- Agent Phone GitHub: https://github.com/rfdiosuao/Hermes-Agent-phone
- Hermes Skills Hub: https://agentskills.io