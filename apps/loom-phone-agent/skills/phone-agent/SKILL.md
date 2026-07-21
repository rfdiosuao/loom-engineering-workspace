---
name: phone-agent
description: Intelligent Android phone control via Agent Phone Agent. Send detailed natural language tasks, verify completion, handle errors automatically. Best for complex multi-step operations.
version: 2.1.0
author: Agent Phone Team
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Android, AI Agent, Mobile Automation, Task Verification]
    config:
      - key: phone.url
        description: Agent Phone device URL (e.g. http://192.168.1.100:9527)
        prompt: Agent Phone device URL
      - key: phone.token
        description: API authentication token
        prompt: API Token
---

# Phone Agent Control

Control Android devices through Agent Phone's built-in AI Agent. This skill provides
**intelligent task execution with automatic verification** - send detailed instructions,
the Agent executes them, and we verify completion before reporting success.

## Core Workflow

```
1. Check device status → Ensure Agent ready
2. Send detailed task prompt → Agent plans and executes
3. Take screenshot → Verify task completed correctly  
4. If failed → Retry with adjusted instructions
5. Return result to user
```

## Prerequisites

| Requirement | How to verify |
|-------------|---------------|
| Agent Phone installed | Check `/api/agent/status` returns `accessibilityRunning: true` |
| Accessibility enabled | Agent Phone home screen shows green status |
| LLM configured | Settings → LLM Config has API Key |
| API Token set | Settings → API Token has value |
| LAN Config enabled | Settings → LAN Config is ON |

## Configuration

```yaml
# ~/.hermes/config.yaml
skills:
  config:
    phone:
      url: "http://192.168.1.137:9527"
      token: "your-token-here"
```

## Quick Reference

| Function | Endpoint | Purpose |
|----------|----------|---------|
| **Execute Task** | `/api/agent/execute_task` | Main task execution (120s timeout) |
| **Check Status** | `/api/agent/status` | Verify Agent ready before task |
| **Screenshot** | `/api/tool/screenshot` | Visual verification of completion |
| **Screen Info** | `/api/tool/get_screen_info` | Check UI state programmatically |
| **Cancel Task** | `/api/agent/cancel_task` | Abort running task |
| **Press Key** | `/api/tool/system_key` | back/home/recent navigation |

## Usage Patterns

### Pattern 1: Basic Task (No Verification)

```bash
execute_task("打开微信")
```

Suitable for simple single-step tasks where success is obvious.

### Pattern 2: Task + Screenshot Verification

```bash
execute_task("打开支付宝首页")
screenshot() → verify: screen shows Alipay home
```

For tasks where visual confirmation matters.

### Pattern 3: Complex Multi-Step with Retry

```bash
execute_task("打开微信，搜索联系人'张三'，发送消息'明天下午3点开会'")
screenshot() → verify: chat screen with sent message visible
if failed → retry: "在微信聊天界面，确认消息已发送成功"
```

For complex tasks requiring multiple operations.

---

## Task Templates (Detailed Prompts)

### Messaging Tasks

#### Send WeChat Message
```
打开微信应用，等待完全加载后：
1. 点击底部"通讯录"标签
2. 在搜索框输入联系人名称"{contact_name}"
3. 点击搜索结果中的联系人
4. 在聊天界面的输入框点击激活
5. 输入消息内容"{message}"
6. 点击发送按钮
完成后确认消息已出现在聊天记录中
```

#### Send QQ Message
```
打开QQ应用，进入聊天界面：
1. 在联系人列表找到"{contact_name}"
2. 点击进入聊天窗口
3. 点击输入框
4. 输入"{message}"
5. 点击发送
确认消息显示在聊天区域
```

### App Operations

#### Open and Navigate App
```
打开{app_name}应用：
1. 等待应用完全启动（约3秒）
2. 如果有广告弹窗，点击关闭或跳过
3. 进入{destination}页面
确认已到达目标页面，屏幕显示{expected_content}
```

#### Search in Shopping App
```
打开{app_name}（淘宝/京东/拼多多）：
1. 等待首页加载完成
2. 点击顶部搜索框
3. 输入搜索关键词"{keyword}"
4. 点击搜索按钮或键盘确认
5. 查看搜索结果列表
确认搜索结果页面已显示，能看到相关商品
```

### Social Media Tasks

#### Douyin/TikTok Video Interaction
```
打开抖音应用：
1. 等待视频自动播放
2. 执行以下操作：
   - 向下滑动{count}次切换视频
   - 每次滑动后等待视频加载
3. 对视频执行互动操作：{action}（点赞/评论/分享）
确认操作完成，能看到互动效果（如红心已点亮）
```

#### Weibo Browse
```
打开微博应用：
1. 等待首页加载
2. 点击"发现"或搜索图标
3. 搜索话题"{topic}"
4. 点击进入话题详情
5. 浏览热门微博内容
确认已进入话题页面，能看到相关微博列表
```

### System Operations

#### Adjust Settings
```
打开系统设置：
1. 在设置列表中找到"{setting_name}"选项
2. 点击进入设置详情
3. 调整{setting_type}为{target_value}
4. 如果有确认提示，点击确认
确认设置已成功修改，显示新值{target_value}
```

#### File Management
```
打开文件管理应用：
1. 进入{directory}目录（如：下载/DCIM/Documents）
2. 找到文件"{filename}"
3. 执行操作：{action}（打开/分享/删除/移动）
确认操作完成，能看到结果
```

### Payment Tasks

#### Alipay Transfer
```
打开支付宝应用：
1. 点击"转账"功能
2. 选择转账方式：{method}（联系人/银行卡）
3. 输入收款方：{recipient}
4. 输入金额：{amount}元
5. 确认转账信息
6. 完成支付验证（指纹/密码）
确认转账成功页面显示
```

#### WeChat Pay
```
打开微信应用：
1. 点击"我"标签
2. 进入"服务"/"支付"
3. 选择功能：{feature}（收付款/转账/充值）
4. 执行操作
确认支付界面正常显示
```

---

## Verification Methods

### Method 1: Screenshot Analysis

After task execution, take screenshot and check:

```
POST /api/tool/screenshot → returns base64 PNG

Expected patterns to verify:
- App icon visible = app opened successfully
- Chat message visible = message sent
- Search results visible = search completed
- Settings changed = adjustment made
- Payment success page = transaction done
```

### Method 2: Screen Info (UI Tree)

```
GET /api/tool/get_screen_info → returns UI hierarchy

Check for:
- Text containing expected strings
- Nodes with specific resource-id
- Visible elements matching task target
```

### Method 3: Status Polling

```
GET /api/agent/status → check taskRunning

Wait until taskRunning: false
Then verify result via screenshot
```

---

## Error Handling

### Common Errors and Solutions

| Error | Detection | Solution |
|-------|-----------|----------|
| **App not found** | Agent returns "cannot find app" | Retry with package name: `com.tencent.mm` |
| **System dialog blocked** | Agent returns "system dialog" | Instruct: "关闭系统弹窗后继续" |
| **Login required** | Screenshot shows login page | Notify user: "需要登录，请手动操作" |
| **Network slow** | Task timeout > 120s | Retry with simpler task or wait |
| **Permission denied** | Agent reports permission issue | Guide user to grant permission |

### Retry Strategy

```python
max_retries = 3
for attempt in range(max_retries):
    result = execute_task(prompt)
    if result.success:
        screenshot = take_screenshot()
        if verify_completion(screenshot):
            return "SUCCESS"
    # Adjust prompt based on error
    prompt = adjust_prompt_based_on_error(result.error, attempt)
```

---

## Best Practices

### 1. Be Specific About Steps

**Bad:** "发个微信消息"  
**Good:** "打开微信，在聊天列表找到'工作群'，点击进入，输入'今日会议取消'，发送"

### 2. Include Wait Instructions

**Bad:** "打开微信然后立刻发消息"  
**Good:** "打开微信，等待3秒加载完成，然后进入聊天发送消息"

### 3. Handle Popups Proactively

**Bad:** "打开淘宝搜索东西"  
**Good:** "打开淘宝，如果有广告弹窗点击关闭，然后点击搜索框输入关键词"

### 4. Specify Verification Criteria

**Bad:** "打开支付宝"  
**Good:** "打开支付宝首页，确认能看到余额显示和付款按钮"

### 5. Use Chinese for Chinese Apps

WeChat/支付宝/抖音 etc. → Use Chinese prompts  
Foreign apps → Use English prompts

---

## API Reference

### execute_task(prompt: string)

Execute a task through the Agent.

```bash
curl -X POST "${PHONE_URL}/api/agent/execute_task" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary '{"prompt": "<detailed task prompt>"}'
```

**Response:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "answer": "任务完成描述",
    "rounds": 5,
    "tokens": 12000
  }
}
```

**Timeout:** 120 seconds

### check_status()

Check if Agent is ready and not busy.

```bash
curl "${PHONE_URL}/api/agent/status" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

**Response:**
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

**Check before every task:**
- `accessibilityRunning: true` → Required for all operations
- `llmConfigured: true` → Required for Agent tasks
- `taskRunning: false` → No task in progress

### take_screenshot()

Capture current screen for verification.

```bash
curl "${PHONE_URL}/api/tool/screenshot" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

**Response:** base64 encoded PNG image

### get_screen_info()

Get UI tree for programmatic verification.

```bash
curl "${PHONE_URL}/api/tool/get_screen_info" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

**Response:** XML-like UI hierarchy

### press_key(key: string)

Navigate back or to home.

```bash
curl -X POST "${PHONE_URL}/api/tool/system_key" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "home"}'  # or "back", "recent"
```

---

## Integration Examples

### Hermes Usage Flow

When user says: "帮我用微信给老王发消息说明天开会"

```
Step 1: check_status() → Ensure Agent ready
Step 2: execute_task(
  prompt: "打开微信应用，等待加载后：
           1. 点击底部通讯录
           2. 搜索联系人'老王'
           3. 点击联系人进入聊天
           4. 在输入框输入'明天开会'
           5. 点击发送按钮
           确认消息已发送成功"
)
Step 3: screenshot() → Verify chat screen shows sent message
Step 4: Report to user: "消息已发送成功"
```

### Shopping Task

When user says: "淘宝搜索蓝牙耳机看第一个商品"

```
Step 1: check_status() → Verify ready
Step 2: execute_task(
  prompt: "打开淘宝应用：
           1. 如果有首页弹窗，点击关闭
           2. 点击顶部搜索框
           3. 输入'蓝牙耳机'
           4. 点击搜索确认
           5. 点击搜索结果第一个商品
           6. 进入商品详情页
           确认能看到商品图片和价格信息"
)
Step 3: screenshot() → Show user the product page
```

---

## Troubleshooting Guide

### Issue: Task Returns "乱码" / Garbled Text

**Solution:** Use `--data-binary` and charset header
```bash
-H "Content-Type: application/json; charset=utf-8"
--data-binary '{"prompt": "中文指令"}'
```

### Issue: Agent Says "Cannot Find App"

**Solution:** Use package name
```
"打开应用 com.tencent.mm（微信）"
```

### Issue: Task Timeout

**Solution:** Break into smaller tasks
```
Instead of: "打开微信发消息给张三再转发给李四"
Use: 
  Task 1: "打开微信，给张三发消息'hello'"
  Task 2: "转发刚才的消息给李四"
```

### Issue: System Dialog Blocks

**Solution:** Handle proactively
```
"如果出现系统弹窗（如权限请求），点击允许后继续任务"
```

### Issue: Agent Not Initialized

**Solution:** First task initializes Agent, wait 30s then retry

---

## Safety Notes

- **Never** send tasks involving payments without user confirmation
- **Never** execute tasks that delete data without explicit consent  
- **Always** verify sensitive operations with screenshot
- **Report** any unexpected behavior to user immediately

---

## Resources

- GitHub: https://github.com/rfdiosuao/Hermes-Agent-phone
- Hermes: https://github.com/nousresearch/hermes-agent
- Original ApkClaw: https://github.com/apkclaw-team/ApkClaw
