# OpenClaw Agent 指挥 APKClaw 压测记录

日期：2026-05-11

测试目标：验证“OpenClaw / Agent 负责规划，APKClaw 负责手机执行”的路线，而不是只用电脑直接调用 APKClaw 底层端口。

## 这次测的不是纯 API

本轮优先走：

```text
OpenClaw 任务意图
-> /api/lumi/agent/execute_task
-> APKClaw 手机端 Agent
-> 手机端工具调用
-> 结果和 trace 回传
```

纯端口压测仍然有价值，用来确认截图、结构树、采集器、录屏、视频下载等底层能力是否稳定。但真实产品能力要看 Agent 是否能把这些能力选对、用对、收敛出结果。

## BOSS 岗位采集任务

任务：在 BOSS 直聘搜索“AI 产品经理”，采集最多 20 个岗位并返回摘要。

### safe_action 首次结果

结果：超时。

核心现象：

- Agent 能打开 BOSS、进入搜索并输入关键词。
- Agent 开始用 `get_screen_info`、`open_app`、`tap`、`input_text`、`swipe` 手动循环。
- Trace 中明确出现：当前工具列表没有 `collect_list_items`。
- 因为没有看到结构化采集工具，Agent 只能像人一样反复观察和滑动，效率低且容易超时。

### 根因

APKClaw 已注册 `collect_list_items`，但 `safe_action` 策略没有把它放进允许工具列表。

所以问题不是采集器不存在，而是 OpenClaw 通过安全任务模式指挥手机时，APKClaw 把最关键的采集工具藏起来了。

### 6.17 修复

APKClaw 6.17：

- `safe_action` 允许 `collect_list_items`。
- Agent 系统提示新增规则：岗位、商品、评论、搜索结果等列表任务优先使用 `collect_list_items`，不要重复手动 `get_screen_info + swipe`。
- Agent trace 的长采集结果增加占位压缩，避免上下文被列表数据撑爆。

构建产物：

```text
AgentPhone_v6.17_20260511_015711.apk
AgentPhone_latest.apk
versionName=6.17
versionCode=770
```

## 现机验证

由于当前手机仍是 6.16，本轮用 `full_access` 临时验证“Agent 能不能主动调用采集器”。

结果：成功。

工具链：

```text
open_app -> get_screen_info -> collect_list_items -> finish
```

采集结果：

- 目标：BOSS 岗位列表
- 目标数量：8
- 实际采集：8
- 结果状态：partial=false
- 截止原因：collected_enough
- 完成耗时：约 28 秒

样例结果包括：智谱华章、数势科技、作业帮、瑞幸咖啡、理想汽车、银河驿站、阿里巴巴集团等岗位卡片。

这证明只要工具对 Agent 可见，OpenClaw 指挥 APKClaw 走结构化采集是成立的。

## 当前判断

这是一个很关键的方向校准：

- APKClaw 不应该变成“大脑”。
- OpenClaw 应该负责拆任务、选择策略、判断结果质量。
- APKClaw 应该把手机能力做成稳定、可授权、可回放、可诊断的工具。
- 列表采集这类复杂任务不能让 Agent 纯靠滑屏记忆，需要给它确定性的手机端工具。

## 下一步验收

安装 6.17 后复跑 safe_action：

```powershell
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666
```

然后再跑一次 BOSS / 闲鱼 / 淘宝 / 京东 / 抖音评论区的小样本任务，看 trace 是否优先出现：

```text
collect_list_items
```

如果 safe_action 下也能稳定调用采集器，再继续做跨平台采集模板和演示场景。

## 6.17 安装后复测

手机状态：

```text
version=6.17
versionCode=770
accessibilityRunning=true
screenshotSupported=true
screenInfoSupported=true
llmConfigured=true
screenOn=true
deviceLocked=false
```

通用验收：

```powershell
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666
```

结果：

```text
Passed: 29
Failed: 0
Phone Agent verification passed.
```

BOSS safe_action 复测：

```text
toolPolicy=safe_action
tools=get_installed_apps -> open_app -> get_screen_info -> tap -> get_screen_info -> input_text -> tap -> collect_list_items -> finish
usedCollector=true
rounds=9
```

采集结果：

- 关键词：AI 产品经理
- 目标数量：8
- 实际采集：8
- `partial=false`
- `reason=collected_enough`
- 未投递、未沟通、未收藏、未点击岗位详情

样例包括：字节跳动、北京字节跳动、快手、智谱华章、月之暗面、小米、京东科技集团、美团等岗位卡片。

结论：6.17 已修复 safe_action 下采集器不可见的问题。OpenClaw 通过安全任务模式指挥 APKClaw 做结构化岗位采集已成立。

## 京东商品采集复测与 6.18 修正

随后用同样的 Agent 指挥路径测试京东商品搜索：

```text
任务：打开京东，搜索“500元左右 移动硬盘”，采集 6 条结果。
toolPolicy=safe_action
tools=open_app -> get_screen_info -> tap -> get_screen_info -> tap -> get_screen_info -> tap -> get_screen_info -> collect_list_items -> finish
usedCollector=true
```

结果：Agent 路线仍然成立，但当时使用 `target=generic`，采集结果混入了“显示模式、筛选栏、优惠券、加购物车”等页面控件。6 条里实际纯商品卡片约 1 条。

这是采集器设计问题，不是 Agent 调度问题。

6.18 修正：

- `collect_list_items` 新增 `target=product`。
- 商品采集以价格节点锚定商品卡片，再向上寻找商品标题。
- 过滤排序栏、筛选栏、优惠券、加购物车、负反馈、购物车等页面控件。
- OpenClaw Skill / TOOLS / CAPABILITIES 已同步：商品任务应指定 `target=product`。

构建产物：

```text
AgentPhone_v6.18_20260511_021614.apk
AgentPhone_latest.apk
versionName=6.18
versionCode=780
```

6.18 待安装后复测项：

- 京东：`target=product` 搜索移动硬盘，检查商品卡片纯度。
- 闲鱼：`target=product` 搜索二手硬盘，检查价格和标题是否稳定。
- 淘宝 / 拼多多：先小样本验证商品卡片，再决定是否需要平台特化解析器。

## 6.18 安装后复测

手机状态：

```text
version=6.18
versionCode=780
accessibilityRunning=true
screenshotSupported=true
screenInfoSupported=true
llmConfigured=true
screenOn=true
deviceLocked=false
```

通用验收：

```text
Passed: 29
Failed: 0
Phone Agent verification passed.
```

京东 `target=product` 复测：

```text
toolPolicy=safe_action
tools=open_app -> get_screen_info -> tap -> get_screen_info -> find_node_info -> tap -> get_screen_info -> collect_list_items -> finish
usedCollector=true
target=product
```

结果：

- 成功搜索“500元左右 移动硬盘”。
- 采集器返回 6 条，均来自商品卡片区域。
- 未再混入筛选栏、优惠券、底部导航栏、加购物车等非商品控件。
- 样例包括 KODAK 柯达 500GB、纽曼 2TB、科硕 500GB、西部升级 20TB 等商品。

剩余问题：

- 京东同一商品卡片内可能出现多个价格，例如当前价、到手价、活动价。
- 6.18 会把同一卡片不同价格锚点拆成多条 product 记录，导致 6 条里实际独立商品约 4 款。
- 下一步应按商品卡片 bounds / 标题相似度合并多价格记录，并保留 `price`、`effectivePrice`、`listPrice` 等价格字段。

## 6.18 跨电商补测

测试前置：电脑代理关闭后，`192.168.1.137:9527` 恢复；手机 `version=6.18 / versionCode=780`，无障碍、截图、结构树和 LLM 均在线。

### 闲鱼

任务：搜索“移动硬盘 500元左右”，使用 `collect_list_items target=product`。

结果：

- `safe_action` 下 Agent 确实调用了 `collect_list_items`。
- 首次采集发生得过早，搜索结果尚未稳定，返回 `No list items were collected`。
- 后续 Agent 在闲鱼搜索入口、清空旧搜索词、确认搜索按钮之间绕行，最终超时。

判断：

- 当前不是 product 解析器先失败，而是闲鱼“进入搜索结果页”的前置流程不稳。
- 后续应增加“电商搜索模板”：打开 App 后先定位搜索框、清空旧词、输入、点击搜索、等待结果页出现，再调用采集器。

### 淘宝

任务：搜索“移动硬盘 500元左右”，使用 `collect_list_items target=product`。

结果：

- Agent 成功进入淘宝搜索结果页，并多次调用 `collect_list_items target=product`。
- 采集器返回 0 条。
- 直接读取屏幕树可见淘宝商品节点：商品标题、价格、付款人数被放在同一个长 `description` 中，例如“商品名 155.00元 1万+人付款”。

判断：

- 无障碍节点不是空的，问题是 6.18 的 product 解析器只处理短价格节点，没有从长描述中抽取价格并拆出标题。
- 后续应补“长文本商品解析”：从 description 中抽取价格、价格前文本作为标题、价格后文本作为销量/付款信息。

### 拼多多

任务：搜索“移动硬盘 500元左右”，使用 `collect_list_items target=product`。

结果：

- Agent 成功进入拼多多搜索结果页。
- `collect_list_items target=product` 返回 6 条。
- 未混入筛选栏、底部导航、按钮等非商品控件。
- 价格解析存在误差：部分促销标签如“立减1元”“10元”会被误判为商品价格。

判断：

- product 模式在拼多多能定位商品卡片，但价格字段需要优先选择主价格。
- 后续应补“促销价过滤 / 主价格选择”：同卡片多价格时，优先选择字号/位置更接近主价的节点，过滤“立减、券、补贴、返、折”等促销价格。

## 跨平台结论

- 京东：商品卡片过滤可用，下一步解决同商品多价格去重。
- 淘宝：搜索入口可用，商品节点可读，下一步解决长文本商品解析。
- 拼多多：商品卡片过滤可用，下一步解决促销价格误判。
- 闲鱼：采集器可调用，但搜索入口不稳，下一步先做搜索流程模板。

这说明 6.18 的 `target=product` 是正确方向，但电商采集要从“单一规则”升级为“通用商品核心 + 平台适配层”。
