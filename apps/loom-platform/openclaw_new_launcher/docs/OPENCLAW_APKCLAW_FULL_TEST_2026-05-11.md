# OpenClaw + APKClaw 全量回归测试记录

日期：2026-05-11

## 测试范围

本轮只看真实可交付能力，不看概念图。

- Launcher 编译
- APKClaw 真机基线验收
- 图片从电脑导入手机相册
- 手机录屏状态 / 列表 / 下载
- 游戏 / 视觉模式闭环

## 测试环境

- Launcher：`D:\Axiangmu\AUSTART\openclaw_new_launcher`
- APKClaw：`D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction`
- 目标手机：`http://192.168.1.110:9527`
- Token：`66666666`
- 手机版本：`6.26 / versionCode 860`

## 执行结果

### 1. Launcher 编译

命令：

```powershell
npm run build
```

结果：PASS

- `tsc` 通过
- `vite build` 通过
- 产物正常生成

### 2. APKClaw 真机基线

命令：

```powershell
npm run verify:phone -- -BaseUrl http://192.168.1.110:9527 -Token 66666666
```

结果：PASS

- `37 passed, 0 failed`
- `device/status` 正常
- 截图、结构树、画像、视觉状态、安全策略、录屏接口都可用
- 读写边界、只读探针、安全动作探针都通过

### 3. 图片导入

命令：

```powershell
npm run phone:image -- --image .\logo_256.png --phone-url http://192.168.1.110:9527 --phone-token 66666666 --filename openclaw-fulltest-import.png --json
```

结果：PASS

- 导入成功
- `relativePath = Pictures/OpenClaw/openclaw-fulltest-import.png`
- `uri = content://media/external/images/media/1000082806`

### 4. 录屏状态 / 列表 / 下载

状态命令：

```powershell
npm run phone:video -- status --phone-url http://192.168.1.110:9527 --phone-token 66666666 --json
```

结果：PASS

- `state = idle`
- `recording = false`

列表命令：

```powershell
npm run phone:video -- list --phone-url http://192.168.1.110:9527 --phone-token 66666666 --json
```

结果：PASS

- 找到历史录屏 2 条
- 最新一条可下载

下载命令：

```powershell
npm run phone:video -- download --latest --out-dir .\data\phone-videos --phone-url http://192.168.1.110:9527 --phone-token 66666666 --json
```

结果：PASS

- 下载成功
- 文件：`data/phone-videos/openclaw-record-test-6-16-20260511-0138.mp4`
- 大小：`871558 bytes`

### 5. 游戏 / 视觉模式

命令：

```powershell
npm run phone:game -- run --goal "open 洛克王国：世界 and inspect the current screen safely" --phone-url http://192.168.1.110:9527 --phone-token 66666666 --json
```

结果：PASS

- APKClaw Agent 成功打开 `洛克王国：世界`（`com.tencent.nrc`）
- 该界面无有效无障碍节点
- 返回 `needs_vision`
- Launcher 成功抓到视觉帧
- `vision.recommended = true`
- `vision.reason = no_accessibility_nodes`
- `safety.metadataRequiredByLauncher = true`

视觉帧：

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\data\phone-frames\game-frame-20260511-074207.jpg
```

## 关键发现

1. 基线验证对“当前屏幕状态”敏感。
   - 这次第一次跑 `verify:phone` 时，手机正停在《洛克王国：世界》上，`screen_tree` 节点数为 0。
   - 这不是接口坏了，而是当前屏幕本身就是 canvas / SurfaceView 场景。
   - 我随后发了 `system_key(home)`，再复跑一次，`37/37` 全通过。

2. 游戏模式现在能正确切到视觉闭环。
   - 无障碍树为空时，系统不再硬啃结构树。
   - 这个行为是对的，也是后面做游戏模式产品化的基础。

3. 图片导入、录屏列表、录屏下载这三条链路都已经通了。
   - 说明“电脑素材 -> 手机相册 / 手机素材 -> 电脑”两条路都可用。

## 建议

- 基线验收脚本可以考虑先自动 `home` 一次，再跑 `screen_tree`，减少屏幕状态干扰。
- 游戏类页面继续坚持“视觉优先，结构树兜底”的策略。
- 后续若要继续压测电商或社交 App，建议先把“搜索入口定位”和“collector 重复去重”两条规则再细化。

## 结论

当前这版可以对外说的结论是：

- 启动器能编译
- APKClaw 真机链路可用
- 图片导入可用
- 录屏状态 / 下载可用
- 游戏视觉闭环可用
- 只要先把屏幕状态归一化，基线验收可以稳定跑满
