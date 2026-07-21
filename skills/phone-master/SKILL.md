---
name: phone-master
description: Ultimate Android phone control skill. Full mastery over Agent Phone - natural language tasks, workflow templates, precise tool control, status monitoring, error recovery. The complete toolkit for AI-driven mobile automation.
version: 6.0.0
author: Agent Phone Team
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Android, AI Agent, Mobile Automation, Workflow Templates, Complete Control]
    config:
      - key: phone.url
        description: Agent Phone device URL (e.g. http://192.168.1.100:9527)
        prompt: Agent Phone device URL
      - key: phone.token
        description: API authentication token
        prompt: API Token
---

# Phone Master Skill - Complete Android Control

**Total mastery over your Android device through Agent Phone.** This skill gives Hermes full control:

- 🧠 **智能任务** - Natural language → Agent auto-plans & executes
- 🔄 **流程模板** - Reuse proven workflows, zero-token execution
- 🔧 **精确控制** - Tap/swipe/input at exact coordinates
- 📸 **视觉验证** - Screenshots & UI tree analysis
- 🔄 **错误恢复** - Auto-retry, fallback strategies
- 📊 **状态监控** - Real-time device status

---

## Quick Reference Card

| 功能 | 命令 | 用途 |
|------|------|------|
| **智能执行** | `execute("打开微信发消息")` | 自然语言任务 |
| **模板执行** | `template("wechat-message", params)` | 固化流程秒执行 |
| **查看模板** | `templates()` | 查看所有已保存流程 |
| **创建模板** | `create_template(...)` | 手动定义流程 |
| **截图** | `screenshot()` | 查看当前屏幕 |
| **点击** | `tap(x, y)` | 精确坐标点击 |
| **滑动** | `swipe(x1,y1,x2,y2)` | 手势操作 |
| **输入** | `input("Hello")` | 文字输入 |
| **状态** | `status()` | 检查设备状态 |
| **应用列表** | `apps()` | 已安装应用 |

---

## Configuration

```yaml
# ~/.hermes/config.yaml
skills:
  config:
    phone:
      url: "http://192.168.1.137:9527"
      token: "your-token-here"
```

---

## Core Functions

### 1. 检查状态 (必做第一步)

每次操作前检查设备是否就绪：

```bash
curl -s "${PHONE_URL}/api/agent/status" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

**关键状态：**
- `accessibilityRunning: true` → 必须为true（核心权限）
- `llmConfigured: true` → Agent任务需要
- `taskRunning: false` → 无任务正在执行

**状态不正常时的处理：**
```
❌ accessibilityRunning: false → 用户需在Agent Phone首页开启无障碍服务
❌ llmConfigured: false → 用户需在Settings配置LLM API Key
❌ taskRunning: true → 等待或取消当前任务
```

---

### 2. 智能任务执行

**推荐方式：发送详细指令，让Agent规划执行**

```bash
curl -X POST "${PHONE_URL}/api/agent/execute_task" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary '{"prompt": "<detailed task>", "use_template": true}'
```

**参数：**
- `prompt`: 详细任务描述（中文任务用中文描述）
- `use_template`: 是否优先使用模板（默认true）
- `force_agent`: 强制Agent规划，跳过模板（默认false）
- `template_params`: 模板参数 `{"contact_name": "张三", "message": "你好"}`

**超时：** 120秒

---

### 3. 流程模板系统 (零Token秒执行)

#### 查看所有模板

```bash
curl -s "${PHONE_URL}/api/workflow/templates" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

#### 执行模板（秒级完成）

```bash
curl -X POST "${PHONE_URL}/api/workflow/execute" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"templateId": "xxx", "params": {"contact_name": "张三", "message": "你好"}}'
```

#### 手动创建模板

```bash
curl -X POST "${PHONE_URL}/api/workflow/create" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "微信发消息",
    "description": "打开微信给联系人发消息",
    "taskPattern": "微信.*发消息",
    "keywords": ["微信", "发消息", "发送"],
    "appName": "微信",
    "steps": [
      {"toolName": "open_app", "paramsTemplate": {"package_name": "com.tencent.mm"}, "description": "打开微信", "waitFor": 2000},
      {"toolName": "tap", "paramsTemplate": {"x": 540, "y": 150}, "description": "点击搜索框"},
      {"toolName": "input_text", "paramsTemplate": {"text": "${contact_name}"}, "description": "输入联系人"},
      {"toolName": "tap", "paramsTemplate": {"x": 540, "y": 300}, "description": "点击联系人"},
      {"toolName": "input_text", "paramsTemplate": {"text": "${message}"}, "description": "输入消息"},
      {"toolName": "tap", "paramsTemplate": {"x": 900, "y": 1800}, "description": "发送"}
    ]
  }'
```

#### 删除模板

```bash
curl -X POST "${PHONE_URL}/api/workflow/delete" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"templateId": "xxx"}'
```

---

### 4. 底层工具控制 (精确操作)

#### 截图 (视觉验证)

```bash
curl -s "${PHONE_URL}/api/tool/screenshot" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
# 返回 base64 PNG，可解码查看
```

#### 获取UI树 (定位元素)

```bash
curl -s "${PHONE_URL}/api/tool/get_screen_info" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
# 返回完整UI层级，包含坐标、文本、resource-id
```

#### 查找UI元素

```bash
curl -X POST "${PHONE_URL}/api/tool/find_node_info" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"text": "登录"}'  # 或 {"resource_id": "com.app:id/button"}
```

#### 点击坐标

```bash
curl -X POST "${PHONE_URL}/api/tool/tap" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"x": 540, "y": 1200}'
```

#### 滑动

```bash
curl -X POST "${PHONE_URL}/api/tool/swipe" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"start_x": 540, "start_y": 1500, "end_x": 540, "end_y": 500, "duration_ms": 300}'
```

#### 长按

```bash
curl -X POST "${PHONE_URL}/api/tool/long_press" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"x": 540, "y": 1200, "duration_ms": 1000}'
```

#### 输入文本

```bash
curl -X POST "${PHONE_URL}/api/tool/input_text" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"text": "你好世界"}'
```

#### 打开应用

```bash
curl -X POST "${PHONE_URL}/api/tool/open_app" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"package_name": "com.tencent.mm"}'
```

#### 系统按键

```bash
curl -X POST "${PHONE_URL}/api/tool/system_key" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "back"}'  # back / home / recent
```

#### 滚动查找

```bash
curl -X POST "${PHONE_URL}/api/tool/scroll_to_find" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"target_text": "设置", "direction": "down", "max_swipes": 10}'
```

#### 等待

```bash
curl -X POST "${PHONE_URL}/api/tool/wait" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"duration_ms": 2000}'
```

#### 获取应用列表

```bash
curl -s "${PHONE_URL}/api/tool/get_installed_apps" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

#### 查看所有工具

```bash
curl -s "${PHONE_URL}/api/tool/list" \
  -H "X-AGENT-PHONE-TOKEN: ${PHONE_TOKEN}"
```

---

## 常见应用包名速查表

| 应用 | 包名 |
|------|------|
| 微信 | `com.tencent.mm` |
| QQ | `com.tencent.mobileqq` |
| 抖音 | `com.ss.android.article.news` |
| 淘宝 | `com.taobao.taobao` |
| 京东 | `com.jingdong.app.mall` |
| 支付宝 | `com.alibaba.wireless` |
| 钉钉 | `com.alibaba.android.rimet` |
| 飞书 | `com.ss.android.lark` |
| 微博 | `com.sina.weibo` |
| 美团 | `com.sankuai.meituan` |
| 美团外卖 | `com.sankuai.meituan.takeoutnew` |
| 网易云音乐 | `com.netease.cloudmusic` |
| 腾讯视频 | `com.tencent.qqlive` |
| 设置 | `com.android.settings` |

---

## 超详细任务指令模板

### 📱 微信操作

#### 发消息给联系人

```
打开微信应用，等待完全加载后执行以下步骤：

1. 点击底部"通讯录"标签（约屏幕底部 y=1800 位置）
2. 点击顶部搜索框（约 y=150 位置）
3. 输入联系人名称："{contact_name}"
4. 等待搜索结果显示，点击匹配的联系人
5. 进入聊天界面后，点击底部输入框激活
6. 输入消息内容："{message}"
7. 点击发送按钮（输入框右侧）

完成后截图验证：确认聊天界面显示刚发送的消息
```

#### 发朋友圈

```
打开微信应用：
1. 点击底部"发现"标签
2. 点击"朋友圈"进入
3. 点击右上角相机图标发布
4. 选择"从相册选择"或"拍摄"
5. 如果选择相册：浏览并选择图片
6. 输入朋友圈文字内容："{content}"
7. 点击"发表"按钮

验证：截图确认朋友圈发布成功
```

#### 查看群聊消息

```
打开微信应用：
1. 点击底部"微信"标签回到消息列表
2. 搜索或滚动找到群聊："{group_name}"
3. 点击进入群聊
4. 滚动查看最新消息内容
5. 截图返回群聊界面内容

任务完成标志：成功获取群聊消息截图
```

### 📱 QQ操作

#### 发消息

```
打开QQ应用：
1. 点击底部"消息"标签
2. 点击右上角搜索图标
3. 输入联系人/QQ号："{contact}"
4. 点击搜索结果进入聊天
5. 点击输入框
6. 输入消息："{message}"
7. 点击发送按钮

验证：截图确认消息出现在聊天区
```

#### 查看QQ空间

```
打开QQ应用：
1. 点击底部"动态"标签
2. 点击"好友动态"进入QQ空间
3. 滑动浏览动态内容
4. 如需评论：点击动态下的评论框，输入评论内容

任务完成：截图展示浏览到的动态内容
```

### 🛒 淘宝/京东购物

#### 搜索商品

```
打开淘宝应用：
1. 等待首页完全加载（约3秒）
2. 如有弹窗广告，点击关闭/跳过
3. 点击顶部搜索框
4. 输入搜索关键词："{keyword}"
5. 点击键盘搜索按钮或回车确认
6. 查看搜索结果列表
7. 点击第一个商品进入详情页

验证：截图确认已进入商品详情页，能看到价格和图片
```

#### 查看订单

```
打开淘宝应用：
1. 点击底部"我的淘宝"标签
2. 点击"我的订单"或"全部订单"
3. 滚动查看订单列表
4. 如需查看特定订单：点击该订单进入详情

验证：截图展示订单列表或订单详情
```

### 🎵 抖音/短视频

#### 刷视频

```
打开抖音应用：
1. 等待视频自动开始播放
2. 执行滑动操作切换视频：
   - 向下滑动{count}次，每次间隔2秒等待视频加载
3. 对视频执行互动（可选）：
   - 点赞：双击屏幕或点击右侧爱心图标
   - 评论：点击评论图标，输入评论内容，发送
   - 分享：点击分享图标

验证：截图展示当前观看的视频界面
```

#### 搜索内容

```
打开抖音应用：
1. 点击右上角搜索图标
2. 输入搜索关键词："{keyword}"
3. 点击搜索结果中的视频/用户/话题
4. 浏览搜索结果内容

验证：截图展示搜索结果页面
```

### 💰 支付宝操作

#### 充值话费

```
打开支付宝应用：
1. 点击首页"充值中心"或在搜索框搜索"充值"
2. 输入手机号码："{phone_number}"
3. 选择充值金额：{amount}元
4. 确认订单信息
5. 点击"立即付款"
6. 完成支付验证（指纹/密码）
7. 等待充值成功提示

⚠️ 敏感操作：需用户确认后执行
验证：截图确认充值成功页面
```

#### 转账

```
打开支付宝应用：
1. 点击"转账"功能
2. 选择转账方式：
   - 转给朋友：搜索或选择联系人
   - 转到银行卡：输入卡号、姓名
3. 输入转账金额：{amount}元
4. 确认转账信息
5. 完成支付验证
6. 等待转账成功提示

⚠️ 敏感操作：需用户确认后执行
验证：截图确认转账成功
```

### 📧 钉钉/飞书办公

#### 发送工作消息

```
打开钉钉应用：
1. 点击底部"消息"标签
2. 搜索联系人/群："{target}"
3. 点击进入聊天
4. 输入消息："{message}"
5. 点击发送

验证：截图确认消息发送成功
```

#### 查看日程

```
打开钉钉应用：
1. 点击底部"日程"标签
2. 查看今日/本周日程安排
3. 如需添加日程：点击"+"
4. 输入日程标题、时间、地点

验证：截图展示日程界面
```

### 📱 系统设置操作

#### 调整亮度

```
打开系统设置：
1. 点击"显示"或"亮度"选项
2. 拖动亮度滑块调整亮度：
   - 调低：向左拖动滑块
   - 调高：向右拖动滑块
3. 确认亮度已变化

验证：截图显示新的亮度设置值
```

#### 打开/关闭WiFi

```
打开系统设置：
1. 点击"网络和互联网"或"WLAN"
2. 点击WiFi开关按钮切换状态
3. 如需连接特定WiFi：点击该WiFi名称，输入密码

验证：截图显示WiFi状态已变更
```

#### 清理后台应用

```
执行系统操作：
1. 按"recent"键打开最近任务列表
2. 点击"清除全部"或逐个滑动关闭应用
3. 按"home"键回到桌面

验证：截图确认后台已清空
```

### 📂 文件管理

#### 查找文件

```
打开文件管理应用：
1. 进入{directory}目录（下载/DCIM/Documents等）
2. 使用搜索功能搜索："{filename}"
3. 或滚动浏览查找文件
4. 找到后点击查看/分享/操作

验证：截图展示找到的文件
```

#### 发送文件给联系人

```
打开微信/QQ应用：
1. 进入联系人聊天界面："{contact}"
2. 点击输入框右侧的"+"或附件图标
3. 选择"文件"或"图片"
4. 浏览并选择要发送的文件
5. 点击发送

验证：截图确认文件已发送
```

### 🎵 音乐播放

#### 播放指定歌曲

```
打开网易云音乐/QQ音乐应用：
1. 点击顶部搜索框
2. 输入歌曲名/歌手："{song}"
3. 点击搜索结果中的歌曲
4. 点击播放按钮开始播放
5. 如需加入歌单：点击"收藏"或"添加到歌单"

验证：截图显示歌曲正在播放界面
```

---

## 错误处理策略

### 常见错误及解决方案

| 错误 | 检测方式 | 解决方案 |
|------|----------|----------|
| **应用未找到** | Agent返回"cannot find app" | 用包名指定：`open_app(package_name="com.tencent.mm")` |
| **系统弹窗阻塞** | Agent返回"system dialog blocked" | 先关闭弹窗：`tap(x,y)` 点击"允许"/"确定" |
| **需要登录** | 截图显示登录页 | 通知用户："需要登录，请手动操作后继续" |
| **网络慢** | 任务超时>120s | 简化任务或拆分执行 |
| **权限被拒** | Agent报告permission denied | 引导用户在设置中开启权限 |
| **元素不存在** | find_node_info返回空 | 截图分析，调整坐标或换方法 |
| **输入框未激活** | 输入后文字未出现 | 先点击输入框激活再输入 |

### 重试策略

```
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    result = execute_task(prompt)
    if result.success:
        screenshot = take_screenshot()
        if verify_completion(screenshot):
            return SUCCESS
    # 根据错误调整策略
    if "system dialog" in result.error:
        close_dialog_and_retry()
    elif "timeout" in result.error:
        simplify_task_and_retry()
    else:
        adjust_prompt_based_on_error(result.error)

return FAILED after retries
```

---

## 最佳实践

### 1. 任务描述要详细具体

**❌ 差的描述：** "发个微信消息"
**✅ 好的描述：** "打开微信，在聊天列表找到'工作群'，点击进入，输入'今日会议取消'，点击发送按钮，确认消息显示在聊天区"

### 2. 包含等待时间

**❌ 差的描述：** "打开微信然后立刻发消息"
**✅ 好的描述：** "打开微信，等待3秒加载完成，然后进入聊天发送消息"

### 3. 处理可能的弹窗

**❌ 差的描述：** "打开淘宝搜索东西"
**✅ 好的描述：** "打开淘宝，如果有广告弹窗点击关闭，然后点击搜索框输入关键词"

### 4. 指定验证标准

**❌ 差的描述：** "打开支付宝"
**✅ 好的描述：** "打开支付宝首页，确认能看到余额显示和付款按钮"

### 5. 使用正确的语言

- 中文应用（微信/支付宝/抖音）→ 用中文描述任务
- 英文应用 → 用英文描述任务

### 6. 敏感操作需用户确认

- ⚠️ 涉及支付/转账 → 必须先询问用户确认
- ⚠️ 删除数据 → 必须先询问用户确认
- ⚠️ 发送重要消息 → 建议用户确认内容

---

## 完整工作流示例

### 示例1：微信发消息（全流程）

```
Step 1: 检查状态
status() → accessibilityRunning: true ✓

Step 2: 执行任务
execute_task(
  prompt: "打开微信应用，等待完全加载后：
           1. 点击底部'通讯录'标签
           2. 点击顶部搜索框
           3. 输入联系人名称'张三'
           4. 点击搜索结果中的联系人
           5. 点击输入框激活
           6. 输入消息'明天下午3点开会'
           7. 点击发送按钮
           完成后确认消息已出现在聊天记录中"
)

Step 3: 截图验证
screenshot() → 分析：聊天界面显示刚发送的消息 ✓

Step 4: 返回结果
"消息已成功发送给张三"
```

### 示例2：淘宝搜索商品（模板执行）

```
Step 1: 检查状态
status() → taskRunning: false ✓

Step 2: 匹配模板
match_template(prompt: "淘宝搜索蓝牙耳机看第一个商品")
→ 匹配到模板: "淘宝搜索商品" (successRate: 0.85)

Step 3: 执行模板
execute_template(
  templateId: "xxx",
  params: {"keyword": "蓝牙耳机"}
)
→ 3秒完成

Step 4: 截图
screenshot() → 商品详情页截图

Step 5: 返回
"已找到蓝牙耳机商品，展示详情页截图"
```

### 示例3：复杂任务分解

```
任务: "打开微信，在工作群发送今天的日报截图，然后转发给老板"

分解执行:
Task 1: "打开微信，进入'工作群'聊天界面"
→ 成功，截图展示群聊界面

Task 2: "点击输入框右侧'+'，选择'图片'，找到今天的日报截图，发送"
→ 成功，截图确认图片发送

Task 3: "长按刚发送的图片，点击'转发'，搜索'老板'，选择发送"
→ 成功，截图确认转发完成

最终结果: "日报截图已发送到工作群并转发给老板"
```

---

## 状态返回格式

### Agent执行成功

```json
{
  "success": true,
  "data": {
    "success": true,
    "answer": "任务完成描述",
    "rounds": 5,
    "tokens": 1200,
    "mode": "agent"  // 或 "template"
  }
}
```

### 模板执行成功

```json
{
  "success": true,
  "data": {
    "success": true,
    "mode": "template",
    "templateId": "xxx",
    "templateName": "微信发消息",
    "stepsExecuted": 7,
    "stepsTotal": 7,
    "executionTimeMs": 3200
  }
}
```

### 执行失败

```json
{
  "success": false,
  "data": {
    "success": false,
    "error": "Step 3 (tap) failed: cannot click at specified position",
    "rounds": 3
  }
}
```

---

## Safety Guidelines

### ⚠️ 绝对禁止

- **未经确认的支付操作** - 涉及转账/充值必须先询问用户
- **删除重要数据** - 文件删除需用户明确同意
- **发送敏感内容** - 重要消息内容需用户确认
- **修改安全设置** - 安全相关设置修改需用户确认

### ✅ 必须执行

- **敏感操作前询问** - 使用 AskUserQuestion 确认
- **完成后截图验证** - 截图证明任务完成
- **失败时详细报告** - 说明失败原因和已尝试的步骤
- **状态变化及时反馈** - 告知用户任务进度

---

## Troubleshooting

| 问题 | 解决方案 |
|------|----------|
| 🔴 Connection refused | Settings → LAN Config → 开启 |
| 🔴 Unauthorized | 检查 X-AGENT-PHONE-TOKEN Header |
| 🔴 Accessibility not running | 首页 → 开启无障碍服务 |
| 🔴 LLM not configured | Settings → LLM Config → 配置 API Key |
| 🔴 Task timeout | 简化任务或分步执行 |
| 🔴 中文乱码 | 使用 `--data-binary` + `charset=utf-8` |
| 🔴 Agent找不到应用 | 用包名指定：`com.tencent.mm` |
| 🔴 截图黑屏 | 等待应用加载后再截图 |

---

## Resources

- GitHub: https://github.com/rfdiosuao/Hermes-Agent-phone
- Hermes: https://github.com/nousresearch/hermes-agent
- Original ApkClaw: https://github.com/apkclaw-team/ApkClaw
