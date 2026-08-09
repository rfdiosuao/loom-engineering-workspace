# Account Auto Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型账户页面打开即自动获取最新状态，同时静默使用安全快照降级并移除所有手动在线验证提示。

**Architecture:** 保留 `LicensePage` 已有的 cache-first + background `refresh()` 数据流，不新增授权旁路。只收紧 UI 合同：缓存来源属于内部状态，不再渲染页面级警告、来源标签或手动账户刷新按钮；具体余额/套餐操作仍保留。

**Tech Stack:** React 18、TypeScript、Python `unittest` 源码合同、Node test runner。

## Global Constraints

- 页面首次挂载时必须继续读取安全快照并自动调用在线 `refresh({ background: true })`。
- 删除“当前显示上次安全快照”横幅、“上次快照/在线数据”标签和账户级手动刷新按钮。
- 不改变商业授权、余额、套餐或服务端签名校验规则。
- 在线失败时保留最后可用值，不清空缓存、不伪造最新状态。

---

### Task 1: 静默自动刷新 Account 页面

**Files:**
- Modify: `apps/loom-platform/openclaw_new_launcher/python/tests/test_account_ui_contract.py`
- Modify: `apps/loom-platform/openclaw_new_launcher/src/components/license/LicensePage.tsx`

**Interfaces:**
- Consumes: `refresh(options?: { background?: boolean })`、`loadCachedAccount()`、`accountCacheUsable()`。
- Produces: cache-first 自动刷新页面；不再输出 `data-account-cache-warning`、`data-subscription-provenance` 或账户级 `onClick={() => void refresh()}` 控件。

- [ ] **Step 1: 写失败的 UI 合同测试**

将缓存测试改为同时断言自动后台刷新存在、快照提示不存在：

```python
self.assertIn("void refresh({ background: true });", page_source)
self.assertNotIn("data-account-cache-warning", page_source)
self.assertNotIn("当前显示上次安全快照", page_source)
self.assertNotIn("data-subscription-provenance", page_source)
self.assertNotIn("上次快照' : '在线数据", page_source)
```

在 logged-in header 片段中断言账户级手动刷新入口不存在：

```python
header = logged_in.split("</header>", 1)[0]
self.assertNotIn("onClick={() => void refresh()}", header)
self.assertNotIn("重试在线验证", header)
self.assertIn("模型选择", header)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
python -B -m pytest apps/loom-platform/openclaw_new_launcher/python/tests/test_account_ui_contract.py -q
```

Expected: FAIL，指出现有 `data-account-cache-warning`、快照来源标签或手动刷新按钮仍存在。

- [ ] **Step 3: 实现最小 UI 修改**

在 `LicensePage.tsx`：

```tsx
// Header 仅保留“模型选择”。
<div className="flex flex-wrap gap-3">
  <button type="button" onClick={() => setCurrentPage('models')} ...>
    模型选择
  </button>
</div>
```

完整删除 `usingCachedAccount ? <div data-account-cache-warning ...>` 横幅，并将余额标题右侧改为仅保留具体刷新动作：

```tsx
<div className="flex items-center gap-3">
  <button type="button" onClick={() => loadSubscription(false)} ...>
    刷新余额
  </button>
</div>
```

保留现有 cache-first effect：

```tsx
if (accountCacheUsable(cachedAccount.current)) {
  applyAccount(cachedAccount.current, { cached: true, persist: false });
  setStatusText('');
  setLoading(false);
  void refresh({ background: true });
  return;
}
void refresh();
```

- [ ] **Step 4: 运行定向测试并确认 GREEN**

Run:

```powershell
python -B -m pytest apps/loom-platform/openclaw_new_launcher/python/tests/test_account_ui_contract.py -q
```

Expected: PASS。

- [ ] **Step 5: 运行 Platform 完整合同**

Run:

```powershell
cd apps/loom-platform/openclaw_new_launcher
npm ci
npm run test:platform-contracts
```

Expected: TypeScript `tsc --noEmit` 成功，Node tests 全部通过。

- [ ] **Step 6: 提交修复**

```powershell
git add apps/loom-platform/openclaw_new_launcher/python/tests/test_account_ui_contract.py apps/loom-platform/openclaw_new_launcher/src/components/license/LicensePage.tsx
git commit -m "fix(account): refresh silently on page entry"
```
