# 麓鸣授权云完整 SaaS 后台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `license.heang.top/admin` 改造成经营总览优先的完整 SaaS 授权后台，并让完整授权码默认不进入列表响应，只有经过确认、权限校验和审计后才能查看或导出。

**Architecture:** 保留现有 Python `ThreadingHTTPServer`、SQLite 和单文件 `admin_console.html` 部署形态。后端先将授权码元数据与秘密读取拆开，再提供受控的 reveal/export 接口；前端在同一 HTML 中重组导航、经营总览、发卡中心、授权码管理和系统设置，现有套餐、商家、网关、模板、邀请与审计接口继续复用。

**Tech Stack:** Python 3 标准库、SQLite、`unittest`、原生 HTML/CSS/JavaScript、PowerShell、systemd、Nginx/Cloudflare 现有入口。

## Global Constraints

- 不引入 React、Vue、前端打包器、外部 CDN 或新的生产依赖。
- 不修改客户端授权协议、Ed25519 签名私钥、安装器、Gitee 上传或桌面端功能。
- 授权有效期继续使用固定 `YYYY-MM-DD` 日期，不改成首次激活后计时。
- 所有状态数字必须来自真实接口；请求失败显示“暂不可用”，不得伪装成 `0`。
- 完整授权码、网关 Token 和 API Key 不写入 URL、LocalStorage、控制台日志或审计响应。
- 商家账号只能读取和操作归属于自己的授权码和设备；服务端 RBAC 是最终边界。
- 生产部署前必须备份 `license.db`、`server.py` 和 `admin_console.html`，不得覆盖 `private_key.b64`。
- 单次秘密导出最多 500 个明确选择的授权码，不提供隐式“导出所有”。
- 每个任务先写失败测试，再实现，再运行聚焦测试，再提交。

---

## File Map

- Modify: `license_server/server.py` — 授权码元数据序列化、秘密读取、reveal/export、激活设备清单和审计脱敏。
- Modify: `license_server/admin_console.html` — 完整 SaaS 导航、经营总览、快速发卡、发卡中心、授权码/设备管理和危险区。
- Modify: `license_server/tests/test_license_flow.py` — 后端安全、RBAC、审计和 HTTP 契约测试。
- Create: `license_server/tests/test_admin_console_contract.py` — 管理后台 HTML/JS 静态契约和危险操作位置测试。
- Use unchanged: `license_server/verify_db_preservation.py` — 发布前后数据库保护校验。
- Use unchanged: `license_server/deploy_member_update.py` — 参考其备份、原子替换和健康检查顺序；正式发布使用已有 SSH 私钥执行同等流程。

## Task 1: 授权码元数据与秘密读取分离

**Files:**
- Modify: `license_server/tests/test_license_flow.py`
- Modify: `license_server/server.py:2937-3010`

**Interfaces:**
- Produces: `get_code_rows(current_account=None) -> list[dict[str, Any]]`，永远不包含 `fullCode`。
- Produces: `get_code_secret_rows(code_hashes, current_account=None) -> list[dict[str, Any]]`，仅供受控秘密接口使用。
- Produces: `MAX_CODE_SECRET_EXPORT = 500`。

- [ ] **Step 1: 写元数据遮蔽和归属隔离失败测试**

在 `LicenseServerFlowTests` 中添加：

同时在文件顶部导入 `json`：

```python
import json
```

```python
def test_code_inventory_is_masked_and_secret_rows_are_scoped(self) -> None:
    merchant, _ = self.server.create_account_record(
        username="merchant-secret",
        password="merchant-password-123",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    other, _ = self.server.create_account_record(
        username="merchant-other",
        password="merchant-password-456",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    code = self.server.create_code_records(
        count=1,
        licensee="Secret Customer",
        edition="pro",
        features=["openclaw"],
        expires=self.expires(),
        max_activations=1,
        owner_account_id=merchant["accountId"],
    )[0]
    code_hash_value = self.server.code_hash(code)
    merchant_context = {"accountId": merchant["accountId"], "role": "merchant"}
    other_context = {"accountId": other["accountId"], "role": "merchant"}

    inventory = self.server.get_code_rows(merchant_context)
    self.assertEqual(len(inventory), 1)
    self.assertNotIn("fullCode", inventory[0])
    self.assertNotIn(code, json.dumps(inventory, ensure_ascii=False))

    secrets = self.server.get_code_secret_rows([code_hash_value], merchant_context)
    self.assertEqual(secrets[0]["code"], code)
    with self.assertRaises(self.server.ActivationError) as denied:
        self.server.get_code_secret_rows([code_hash_value], other_context)
    self.assertEqual(denied.exception.status, 404)

def test_new_code_expiry_must_be_after_today(self) -> None:
    with self.assertRaises(self.server.ActivationError):
        self.server.normalize_code_expires(date.today().isoformat())
    with self.assertRaises(self.server.ActivationError):
        self.server.normalize_code_expires((date.today() - timedelta(days=1)).isoformat())
```

同时把现有直接断言 `row["fullCode"]` 的测试改为比较 `codeHash`；需要验证完整码的测试调用 `get_code_secret_rows()`。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest license_server.tests.test_license_flow.LicenseServerFlowTests.test_code_inventory_is_masked_and_secret_rows_are_scoped -v
```

Expected: FAIL，原因是 `get_code_rows()` 仍含 `fullCode`，且 `get_code_secret_rows` 尚不存在。

- [ ] **Step 3: 实现秘密读取边界**

在常量区添加：

```python
MAX_CODE_SECRET_EXPORT = 500
```

从 `get_code_rows()` 的返回字典中删除 `fullCode`。新增：

```python
def get_code_secret_rows(
    code_hashes: list[Any],
    current_account: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_code_hashes(code_hashes)
    if not normalized:
        raise ActivationError("请选择授权码", 400)
    if len(normalized) > MAX_CODE_SECRET_EXPORT:
        raise ActivationError(f"单次最多导出 {MAX_CODE_SECRET_EXPORT} 个授权码", 400)
    placeholders = ",".join(["?"] * len(normalized))
    with connect() as conn:
        rows = conn.execute(
            f"""
            select code_hash, code_label, full_code, licensee, edition, plan, expires,
                   max_activations, owner_account_id, disabled
            from codes
            where code_hash in ({placeholders})
            """,
            tuple(normalized),
        ).fetchall()
    by_hash = {str(row["code_hash"]): row for row in rows}
    ordered: list[dict[str, Any]] = []
    for code_hash_value in normalized:
        row = by_hash.get(code_hash_value)
        if not row or not code_row_owned_by_context(row, current_account):
            raise ActivationError("授权码不存在或无权访问", 404)
        ordered.append(
            {
                "codeHash": row["code_hash"],
                "codeLabel": row["code_label"],
                "code": row["full_code"] or ("OC-" + str(row["edition"]).upper() + "-" + row["code_label"]),
                "licensee": row["licensee"],
                "plan": row["plan"],
                "expires": row["expires"],
                "maxActivations": int(row["max_activations"] or 1),
                "disabled": bool(row["disabled"]),
            }
        )
    return ordered
```

同时把 `normalize_code_expires()` 的日期解析改为：

```python
try:
    parsed = date.fromisoformat(candidate)
except ValueError:
    raise ActivationError(f"到期日期格式无效，需要 YYYY-MM-DD：{raw}")
if parsed <= date.today():
    raise ActivationError("到期日期必须晚于今天")
return candidate
```

- [ ] **Step 4: 运行聚焦测试和现有授权流测试**

Run:

```powershell
python -m unittest license_server.tests.test_license_flow -v
```

Expected: PASS；现有测试不再依赖列表接口返回完整码。

- [ ] **Step 5: 提交任务 1**

```powershell
git add license_server/server.py license_server/tests/test_license_flow.py
git commit -m "security: separate license code secrets"
```

## Task 2: reveal/export、激活设备清单和审计脱敏

**Files:**
- Modify: `license_server/tests/test_license_flow.py`
- Modify: `license_server/server.py:2880-3010`
- Modify: `license_server/server.py:3403-4300`

**Interfaces:**
- Consumes: `get_code_secret_rows()` 和 `MAX_CODE_SECRET_EXPORT`。
- Produces: `POST /admin/api/codes/reveal`。
- Produces: `POST /admin/api/codes/export`。
- Produces: `GET /admin/api/activations`。
- Produces: `audit_public_value(value) -> Any` 和审计动作 `codes.reveal`、`codes.export`。

- [ ] **Step 1: 写 HTTP、RBAC 和审计失败测试**

添加以下测试，使用现有 `request_json()` 与 `X-Admin-Session`：

```python
def test_reveal_and_export_require_confirmation_and_write_redacted_audit(self) -> None:
    admin, _ = self.server.create_account_record(
        username="admin-secret",
        password="admin-password-123",
        role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
    )
    session, _ = self.server.create_admin_session(admin["accountId"])
    code = self.server.create_code_records(
        count=1,
        licensee="Export Customer",
        edition="pro",
        features=["openclaw"],
        expires=self.expires(),
        max_activations=1,
        owner_account_id=admin["accountId"],
    )[0]
    code_hash_value = self.server.code_hash(code)
    headers = {"X-Admin-Session": session}

    self.request_json(
        "POST",
        "/admin/api/codes/reveal",
        payload={"codeHash": code_hash_value, "confirmation": ""},
        headers=headers,
        expected_status=400,
    )
    revealed = self.request_json(
        "POST",
        "/admin/api/codes/reveal",
        payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
        headers=headers,
    )
    self.assertEqual(revealed["code"], code)

    exported = self.request_json(
        "POST",
        "/admin/api/codes/export",
        payload={"codeHashes": [code_hash_value], "confirmation": "EXPORT"},
        headers=headers,
    )
    self.assertEqual(exported["codes"][0]["code"], code)

    logs = self.server.get_audit_rows(20)
    actions = {row["action"] for row in logs}
    self.assertTrue({"codes.reveal", "codes.export"}.issubset(actions))
    self.assertNotIn(code, json.dumps(logs, ensure_ascii=False))
```

再添加：

```python
def test_merchant_cannot_reveal_or_export_another_merchant_code(self) -> None:
    merchant_a, _ = self.server.create_account_record(
        username="merchant-a",
        password="merchant-password-123",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    merchant_b, _ = self.server.create_account_record(
        username="merchant-b",
        password="merchant-password-456",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    session_a, _ = self.server.create_admin_session(merchant_a["accountId"])
    session_b, _ = self.server.create_admin_session(merchant_b["accountId"])
    code = self.server.create_code_records(
        count=1,
        licensee="Merchant A Customer",
        edition="pro",
        features=["openclaw"],
        expires=self.expires(),
        max_activations=1,
        owner_account_id=merchant_a["accountId"],
    )[0]
    code_hash_value = self.server.code_hash(code)

    for path, payload in (
        ("/admin/api/codes/reveal", {"codeHash": code_hash_value, "confirmation": "REVEAL"}),
        ("/admin/api/codes/export", {"codeHashes": [code_hash_value], "confirmation": "EXPORT"}),
    ):
        self.request_json(
            "POST",
            path,
            payload=payload,
            headers={"X-Admin-Session": session_b},
            expected_status=404,
        )

    revealed = self.request_json(
        "POST",
        "/admin/api/codes/reveal",
        payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
        headers={"X-Admin-Session": session_a},
    )
    self.assertEqual(revealed["code"], code)

def test_activation_inventory_is_scoped_and_redacted(self) -> None:
    admin, _ = self.server.create_account_record(
        username="activation-admin",
        password="admin-password-123",
        role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
    )
    merchant, _ = self.server.create_account_record(
        username="activation-merchant",
        password="merchant-password-123",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    other, _ = self.server.create_account_record(
        username="activation-other",
        password="merchant-password-456",
        role=self.server.ACCOUNT_ROLE_MERCHANT,
    )
    owned_code = self.server.create_code_records(
        count=1,
        licensee="Owned Device",
        edition="pro",
        features=["openclaw"],
        expires=self.expires(),
        max_activations=1,
        owner_account_id=merchant["accountId"],
    )[0]
    other_code = self.server.create_code_records(
        count=1,
        licensee="Other Device",
        edition="pro",
        features=["openclaw"],
        expires=self.expires(),
        max_activations=1,
        owner_account_id=other["accountId"],
    )[0]
    self.server.activate_code({"code": owned_code, "installId": "owned-install", "deviceId": "owned-device"})
    self.server.activate_code({"code": other_code, "installId": "other-install", "deviceId": "other-device"})

    admin_rows = self.server.get_all_activation_rows(
        {"accountId": admin["accountId"], "role": self.server.ACCOUNT_ROLE_SUPER_ADMIN}
    )
    merchant_rows = self.server.get_all_activation_rows(
        {"accountId": merchant["accountId"], "role": self.server.ACCOUNT_ROLE_MERCHANT}
    )
    self.assertEqual(len(admin_rows), 2)
    self.assertEqual(len(merchant_rows), 1)
    serialized = json.dumps(merchant_rows, ensure_ascii=False)
    self.assertIn("owned-device", serialized)
    self.assertNotIn(owned_code, serialized)
    self.assertNotIn("licenseJson", serialized)
```

- [ ] **Step 2: 运行聚焦测试确认失败**

Run:

```powershell
python -m unittest license_server.tests.test_license_flow.LicenseServerFlowTests.test_reveal_and_export_require_confirmation_and_write_redacted_audit -v
```

Expected: FAIL，返回 404，因为 reveal/export 路由尚不存在。

- [ ] **Step 3: 实现审计输出脱敏**

新增：

```python
AUDIT_SECRET_KEYS = {
    "fullcode", "code", "gatewaytoken", "gatewayimagetoken",
    "gatewayvideotoken", "gatewayaccesstoken", "apikey", "token",
}

def masked_code_label(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return f"••••-{text[-8:]}" if text else "[REDACTED]"

def audit_public_value(value: Any, *, key: str = "") -> Any:
    normalized_key = "".join(ch for ch in key.lower() if ch.isalnum())
    if normalized_key in AUDIT_SECRET_KEYS:
        return masked_code_label(value) if normalized_key in {"fullcode", "code"} else "[REDACTED]"
    if normalized_key == "codes" and isinstance(value, list):
        return [masked_code_label(item) for item in value]
    if isinstance(value, dict):
        return {str(k): audit_public_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [audit_public_value(item, key=key) for item in value]
    return value
```

在 `get_audit_rows()` 返回 `before` / `after` 时调用该函数。把 `codes.create` 的 `after` 从完整 `codes` 数组改为：

```python
{
    "count": len(codes),
    "codeLabels": [code[-9:] for code in codes],
    "licensee": licensee,
    "memberMode": bool(body.get("memberMode")),
    "plan": str(body.get("plan", "")).strip(),
    "ownerAccountId": owner_account_id,
}
```

- [ ] **Step 4: 实现秘密路由和激活设备清单**

在 `Handler.do_POST()` 中增加：

```python
if path == "/admin/api/codes/reveal":
    if not self.require_admin():
        return
    try:
        body = self.read_json()
        if str(body.get("confirmation") or "") != "REVEAL":
            raise ActivationError("请确认查看完整授权码", 400)
        rows = get_code_secret_rows([body.get("codeHash")], self.admin_context())
        row = rows[0]
        self.audit_admin_change(
            "codes.reveal",
            target_type="code",
            target_id=row["codeHash"],
            after={"codeLabel": row["codeLabel"]},
        )
        self.send_json(200, {"code": row["code"], "codeLabel": row["codeLabel"]})
    except ActivationError as error:
        self.send_json(error.status, {"error": str(error)})
    except Exception:
        self.send_json(500, {"error": "查看授权码失败"})
    return
```

export 路由使用 `confirmation == "EXPORT"`，调用 `get_code_secret_rows(body.get("codeHashes"), context)`，先写 `codes.export` 审计，再返回 `{"codes": rows}`。审计 `after` 只能包含 `count` 和 `codeLabels`。

export 路由主体为：

```python
if path == "/admin/api/codes/export":
    if not self.require_admin():
        return
    try:
        body = self.read_json()
        if str(body.get("confirmation") or "") != "EXPORT":
            raise ActivationError("请确认导出完整授权码", 400)
        rows = get_code_secret_rows(body.get("codeHashes"), self.admin_context())
        self.audit_admin_change(
            "codes.export",
            target_type="codes",
            target_id=f"count:{len(rows)}",
            after={
                "count": len(rows),
                "codeLabels": [row["codeLabel"] for row in rows],
            },
        )
        self.send_json(200, {"codes": rows})
    except ActivationError as error:
        self.send_json(error.status, {"error": str(error)})
    except Exception:
        self.send_json(500, {"error": "导出授权码失败"})
    return
```

新增：

```python
def get_all_activation_rows(
    current_account: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    where_clause = ""
    params: tuple[Any, ...] = ()
    if current_account and not is_super_admin_context(current_account):
        where_clause = "where c.owner_account_id = ?"
        params = (context_account_id(current_account),)
    with connect() as conn:
        rows = conn.execute(
            f"""
            select a.id, a.code_hash, a.install_id, a.device_id, a.activated_at,
                   c.code_label, c.plan, c.owner_account_id,
                   coalesce(acc.display_name, '') as owner_display_name
            from activations a
            join codes c on c.code_hash = a.code_hash
            left join accounts acc on acc.id = c.owner_account_id
            {where_clause}
            order by a.activated_at desc, a.id desc
            """,
            params,
        ).fetchall()
    return [
        {
            "activationId": int(row["id"]),
            "codeHash": row["code_hash"],
            "codeLabel": row["code_label"],
            "installId": row["install_id"],
            "deviceId": row["device_id"],
            "plan": row["plan"],
            "ownerDisplayName": row["owner_display_name"],
            "activatedAt": row["activated_at"],
        }
        for row in rows
    ]
```

在 `do_GET()` 增加：

```python
if path == "/admin/api/activations":
    if not self.require_admin():
        return
    self.send_json(200, {"activations": get_all_activation_rows(self.admin_context())})
    return
```

- [ ] **Step 5: 运行安全测试和完整服务测试**

Run:

```powershell
python -m unittest discover -s license_server\tests -p "test_*.py" -v
```

Expected: PASS；测试输出和失败信息中不出现测试完整授权码或网关 Token。

- [ ] **Step 6: 提交任务 2**

```powershell
git add license_server/server.py license_server/tests/test_license_flow.py
git commit -m "security: audit license code access"
```

## Task 3: SaaS 后台壳与真实经营总览

**Files:**
- Create: `license_server/tests/test_admin_console_contract.py`
- Modify: `license_server/admin_console.html:1-2050`

**Interfaces:**
- Consumes: `/admin/api/me`、`/admin/api/codes`、`/admin/api/plans`、`/admin/api/accounts`、`/admin/api/audit-logs`。
- Produces: 页面 `overview`、`issuance`、`codes`、`activations`、`accounts`、`invites`、`plans`、`sales`、`gateway`、`templates`、`audit`、`settings`、`docs`。
- Produces: `loadOverview()`、`renderOverview()`、`renderRecentIssuance()`。

- [ ] **Step 1: 写后台壳和总览契约失败测试**

创建 `license_server/tests/test_admin_console_contract.py`：

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "license_server" / "admin_console.html"


class AdminConsoleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_saas_shell_and_overview_markers_exist(self) -> None:
        for marker in (
            'data-admin-shell',
            'data-page="overview"',
            'id="page-overview"',
            'data-overview-metrics',
            'data-quick-issuance',
            'data-recent-issuance',
            'data-system-protection',
            '麓鸣授权云',
            '经营总览',
            '发卡中心',
            '授权码',
            '激活设备',
            '系统设置',
        ):
            self.assertIn(marker, self.html)

    def test_clear_all_is_not_in_the_topbar(self) -> None:
        topbar_start = self.html.index('data-admin-topbar')
        topbar_end = self.html.index('</section>', topbar_start)
        self.assertNotIn('btnClearAll', self.html[topbar_start:topbar_end])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 运行契约测试确认失败**

Run:

```powershell
python -m unittest license_server.tests.test_admin_console_contract -v
```

Expected: FAIL，缺少 `data-admin-shell` 和 `page-overview`。

- [ ] **Step 3: 重组导航和页面壳**

保留登录视图与现有对话框，在登录后的主壳使用以下结构：

```html
<div class="admin-shell" data-admin-shell>
  <aside class="sidebar">
    <a class="brand" data-page-link="overview">麓鸣授权云</a>
    <nav class="nav" aria-label="后台导航">
      <div class="nav-group"><span>经营</span><button data-page="overview">经营总览</button></div>
      <div class="nav-group"><span>授权业务</span><button data-page="issuance">发卡中心</button><button data-page="codes">授权码</button><button data-page="activations">激活设备</button><button data-page="accounts">客户与商家</button><button data-page="invites">邀请码</button></div>
      <div class="nav-group"><span>商品配置</span><button data-page="plans">套餐与价格</button><button data-page="sales">销售渠道</button></div>
      <div class="nav-group"><span>AI 能力</span><button data-page="gateway">模型网关</button><button data-page="templates">模板库</button></div>
      <div class="nav-group"><span>系统治理</span><button data-page="audit">操作审计</button><button data-page="settings">系统设置</button><button data-page="docs">使用文档</button></div>
    </nav>
  </aside>
  <main class="content">
    <section class="topbar" data-admin-topbar>
      <div><h1 id="pageTitle">经营总览</h1><p id="pageSubtitle">授权销售、设备激活和系统交付状态</p></div>
      <div class="top-actions"><span class="pill">PRODUCTION</span><button class="btn secondary" id="refresh">刷新</button><span id="currentAccountName">当前账号</span><button class="btn secondary" id="logoutTopBtn">退出</button></div>
    </section>
    <section class="page active" id="page-overview">
      <div class="stats" data-overview-metrics></div>
      <div class="overview-grid">
        <section class="panel" data-quick-issuance><h2>快速发卡</h2><div id="quickIssuanceForm"></div></section>
        <section class="panel" data-recent-issuance><h2>最近发卡记录</h2><div id="recentIssuanceList"></div></section>
      </div>
      <section class="panel" data-system-protection><h2>系统保护状态</h2><div id="systemProtectionState"></div></section>
    </section>
  </main>
</div>
```

在同一任务中把原 `page-license` 的“生成 / 编辑授权”面板原样移动到 `page-issuance`，把“授权码列表”面板原样移动到 `page-codes`，保证新导航出现时旧功能仍可用。把 `btnExportAll` 和 `btnBulkEdit` 移入 `page-codes` 的表格工具栏。新增 `page-activations`，内容为带 `id="activationsTable"` 的只读表格；新增 `page-settings`，显示服务版本、授权模式，并把原 `btnClearAll` 移入仅超级管理员可见的危险区，暂时保留现有 confirm 行为。Task 4 和 Task 5 再分别替换这些页面的内部布局和确认方式，不创建空白页面，也不让现有事件绑定引用缺失元素。

顶部只保留当前环境、刷新、当前账号和退出，不再放 `btnExportAll`、`btnBulkEdit` 或 `btnClearAll`。

- [ ] **Step 4: 实现真实总览渲染**

新增纯函数：

```javascript
function overviewSnapshot(codes) {
  const today = new Date().toLocaleDateString("sv-SE");
  return {
    codeCount: codes.length,
    activationCount: codes.reduce((sum, code) => sum + Number(code.activations || 0), 0),
    createdToday: codes.filter(code => String(code.createdAt || "").slice(0, 10) === today).length,
  };
}
```

`renderOverview()` 把成功响应写入四个指标卡。`state.loadErrors.codes` 存在时，授权总量、激活数和今日新建显示“暂不可用”；只有 `/health` 或后台核心接口成功时服务状态显示“运行正常”。最近发卡对超级管理员读取 `codes.create` 审计，对商家从自有 `state.codes` 按 `createdAt` 排序。不得写死 `660`、`146` 或 `100`。

- [ ] **Step 5: 运行契约测试**

Run:

```powershell
python -m unittest license_server.tests.test_admin_console_contract -v
```

Expected: PASS。

- [ ] **Step 6: 提交任务 3**

```powershell
git add license_server/admin_console.html license_server/tests/test_admin_console_contract.py
git commit -m "feat: add license SaaS operations dashboard"
```

## Task 4: 快速发卡与三段式发卡中心

**Files:**
- Modify: `license_server/tests/test_admin_console_contract.py`
- Modify: `license_server/admin_console.html`

**Interfaces:**
- Consumes: `POST /admin/api/codes` 和套餐/账号状态。
- Produces: `buildIssuancePayload(source)`、`openIssuanceReview(payload)`、`submitIssuance(payload)`、`downloadGeneratedCsv()`。

- [ ] **Step 1: 写发卡 UI 契约失败测试**

添加：

```python
def test_quick_and_full_issuance_contract(self) -> None:
    for marker in (
        'id="page-issuance"',
        'data-issuance-step="basic"',
        'data-issuance-step="delivery"',
        'data-issuance-step="review"',
        'id="issuanceReviewDialog"',
        'id="generatedResultPanel"',
        'id="downloadGeneratedCsv"',
        '固定到期日',
        '生成前自动备份',
    ):
        self.assertIn(marker, self.html)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m unittest license_server.tests.test_admin_console_contract.AdminConsoleContractTests.test_quick_and_full_issuance_contract -v
```

Expected: FAIL，缺少新的发卡步骤与确认层。

- [ ] **Step 3: 实现首页快速发卡和完整发卡表单**

首页快速发卡只包含 `planTemplate`、`ownerAccountId`、`licensee`、`count`、`maxActivations`；套餐变化时把计算出的日期写入隐藏字段 `quickExpires`，并在确认层明确显示。发卡中心基础步骤使用相同字段，交付步骤容纳 `expires`、`memberMode`、`features` 和折叠的网关/模型覆盖字段。字段 ID 分别加 `quick` / `issue` 前缀，避免复用 DOM ID。

统一载荷函数：

```javascript
function optionalValue(id, fallback = "") {
  const element = document.getElementById(id);
  return element ? String(element.value || "").trim() : fallback;
}

function collectOptionalGateway(prefix) {
  return {
    gatewayBaseUrl: optionalValue(`${prefix}GatewayBaseUrl`),
    gatewayImageBaseUrl: optionalValue(`${prefix}GatewayImageBaseUrl`),
    gatewayVideoBaseUrl: optionalValue(`${prefix}GatewayVideoBaseUrl`),
    gatewayToken: optionalValue(`${prefix}GatewayToken`),
    gatewayImageToken: optionalValue(`${prefix}GatewayImageToken`),
    gatewayVideoToken: optionalValue(`${prefix}GatewayVideoToken`),
    gatewayDefaultModel: optionalValue(`${prefix}GatewayDefaultModel`),
    gatewayImageModel: optionalValue(`${prefix}GatewayImageModel`),
    gatewayVideoModel: optionalValue(`${prefix}GatewayVideoModel`),
    gatewayModels: optionalValue(`${prefix}GatewayModels`),
  };
}

function buildIssuancePayload(prefix) {
  return {
    licensee: optionalValue(`${prefix}Licensee`, "客户"),
    edition: optionalValue(`${prefix}Edition`, "pro"),
    count: Number(optionalValue(`${prefix}Count`, "1")),
    expires: optionalValue(`${prefix}Expires`),
    maxActivations: Number(optionalValue(`${prefix}MaxActivations`, "1")),
    memberMode: optionalValue(`${prefix}MemberMode`, "false") === "true",
    planTemplate: optionalValue(`${prefix}PlanTemplate`),
    plan: optionalValue(`${prefix}Plan`),
    ownerAccountId: Number(optionalValue(`${prefix}OwnerAccountId`, "0")),
    features: optionalValue(`${prefix}Features`),
    ...collectOptionalGateway(prefix),
  };
}
```

快速发卡的套餐变化事件必须同步隐藏的 `quickPlan`、`quickFeatures`、`quickMemberMode` 和 `quickExpires`，使商家账号在不能继承全局套餐密钥时仍能提交明确的非秘密套餐字段；网关密钥继续由服务端按商家账号默认配置补齐。

任何发卡请求先进入 `issuanceReviewDialog`，摘要显示数量、套餐、设备数和具体到期日。请求期间禁用确认按钮，成功后保存 `state.generated`，失败不清空表单、不自动重试。

`openIssuanceReview()` 在打开对话框前把 `payload.expires` 转为本地日期；日期为空、格式无效或不晚于今天时直接显示错误，不发送请求。服务端 Task 1 的同一校验仍为最终边界。

- [ ] **Step 4: 实现安全交付文件**

新增：

```javascript
function spreadsheetSafe(value) {
  const text = String(value ?? "");
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function csvCell(value) {
  return `"${spreadsheetSafe(value).replaceAll('"', '""')}"`;
}

function downloadGeneratedCsv() {
  const rows = [["授权码", "客户", "套餐", "到期日"], ...state.generated.map(code => [
    code,
    optionalValue("issueLicensee") || optionalValue("quickLicensee", "客户"),
    optionalValue("issuePlan") || optionalValue("quickPlan"),
    optionalValue("issueExpires") || optionalValue("quickExpires"),
  ])];
  const csv = `\uFEFF${rows.map(row => row.map(csvCell).join(",")).join("\r\n")}`;
  exportBlob(`luming-license-${Date.now()}.csv`, csv, "text/csv;charset=utf-8");
}
```

完整码只存在 `state.generated` 和当前 DOM；离开结果视图时清空文本与数组。

- [ ] **Step 5: 运行契约和服务回归测试**

```powershell
python -m unittest license_server.tests.test_admin_console_contract -v
python -m unittest license_server.tests.test_license_flow -v
```

Expected: PASS。

- [ ] **Step 6: 提交任务 4**

```powershell
git add license_server/admin_console.html license_server/tests/test_admin_console_contract.py
git commit -m "feat: streamline commercial license issuance"
```

## Task 5: 遮蔽列表、确认查看/导出、激活设备页与危险区

**Files:**
- Modify: `license_server/tests/test_admin_console_contract.py`
- Modify: `license_server/admin_console.html`

**Interfaces:**
- Consumes: `/admin/api/codes/reveal`、`/admin/api/codes/export`、`/admin/api/activations`。
- Produces: `maskedCodeLabel(code)`、`revealCode(codeHash)`、`exportSelectedCodes()`、`renderActivations()`。

- [ ] **Step 1: 写秘密操作和危险区契约失败测试**

添加：

```python
def test_secret_actions_and_danger_zone_contract(self) -> None:
    for marker in (
        'id="page-codes"',
        'id="page-activations"',
        'id="secretActionDialog"',
        'data-secret-action="reveal"',
        'data-secret-action="export"',
        'confirmation: "REVEAL"',
        'confirmation: "EXPORT"',
        'id="page-settings"',
        'data-danger-zone',
        '输入“清空全部授权码”',
    ):
        self.assertIn(marker, self.html)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m unittest license_server.tests.test_admin_console_contract.AdminConsoleContractTests.test_secret_actions_and_danger_zone_contract -v
```

Expected: FAIL。

- [ ] **Step 3: 改造授权码列表**

列表不再引用 `code.fullCode`。统一显示：

```javascript
function maskedCodeLabel(code) {
  const label = String(code.codeLabel || "").trim();
  return label ? `••••-${label}` : "已遮蔽";
}
```

“查看完整码”打开 `secretActionDialog`，用户确认后才调用：

```javascript
async function revealCode(codeHash) {
  const data = await api("api/codes/reveal", {
    method: "POST",
    body: JSON.stringify({ codeHash, confirmation: "REVEAL" }),
  });
  showEphemeralSecret(data.code, data.codeLabel);
}
```

关闭对话框时把 secret 文本改为空字符串。Toast 只显示“已复制”，不显示码值。

- [ ] **Step 4: 实现明确选择导出和 CSV 注入防护**

`exportSelectedCodes()` 必须检查 `state.selected.size` 为 1-500，并在确认层显示数量。确认后调用：

```javascript
const data = await api("api/codes/export", {
  method: "POST",
  body: JSON.stringify({
    codeHashes: [...state.selected],
    confirmation: "EXPORT",
  }),
});
```

用 Task 4 的 `csvCell()` 生成 UTF-8 CSV。移除旧 `exportAll()` 和顶部 `btnExportAll`。

- [ ] **Step 5: 实现激活设备页和系统设置危险区**

`loadActivations()` 请求 `/admin/api/activations`，`renderActivations()` 显示遮蔽码尾号、设备 ID、安装 ID、套餐、归属和激活时间，不显示 `license_json`。

把 `page-settings` 中的 `btnClearAll` 升级为 `data-danger-zone` 内的强确认操作。只有超级管理员显示该区；点击后要求输入完整短语 `清空全部授权码`，不匹配时按钮禁用。保持服务端原有超级管理员校验、自动备份和 `codes.clear` 审计。

- [ ] **Step 6: 运行前后端聚焦测试**

```powershell
python -m unittest discover -s license_server\tests -p "test_*.py" -v
```

Expected: PASS。

- [ ] **Step 7: 提交任务 5**

```powershell
git add license_server/admin_console.html license_server/tests/test_admin_console_contract.py
git commit -m "feat: secure license inventory operations"
```

## Task 6: RBAC、部分失败、响应式视觉与发布级验证

**Files:**
- Modify: `license_server/tests/test_admin_console_contract.py`
- Modify: `license_server/admin_console.html`
- Verify only: `license_server/server.py`
- Verify only: `openclaw_new_launcher`

**Interfaces:**
- Consumes: 前五个任务的所有页面与接口。
- Produces: 发布候选后台和完整验证记录。

- [ ] **Step 1: 写 RBAC 和响应式契约失败测试**

添加：

```python
def test_role_visibility_and_responsive_contract(self) -> None:
    for marker in (
        'const SUPER_ADMIN_PAGES',
        'const MERCHANT_PAGES',
        'Promise.allSettled',
        '@media (max-width: 1100px)',
        '@media (max-width: 760px)',
        '状态暂不可用',
    ):
        self.assertIn(marker, self.html)
```

- [ ] **Step 2: 实现角色页面集合和部分失败加载**

定义：

```javascript
const SUPER_ADMIN_PAGES = new Set([
  "overview", "issuance", "codes", "activations", "accounts", "invites",
  "plans", "sales", "gateway", "templates", "audit", "settings", "docs",
]);
const MERCHANT_PAGES = new Set([
  "overview", "issuance", "codes", "activations", "gateway", "docs",
]);
```

`refreshAdmin()` 先单独加载 `me`；会话失败时退出后台。拿到角色后构造允许的请求集合：所有角色加载 codes、plans、activations 和 account-gateway，只有超级管理员追加 accounts、audit 和 public-settings，再使用 `Promise.allSettled()`。失败结果写入 `state.loadErrors`，其余模块独立显示“状态暂不可用”和重试按钮。商家不得为了前端方便去请求超级管理员接口。

```javascript
async function refreshAdmin() {
  const me = await api("api/me");
  state.me = me.account || me;
  const jobs = [
    { key: "codes", load: () => api("api/codes"), select: data => data.codes || [] },
    { key: "plans", load: () => api("api/plans"), select: data => data.plans || [] },
    { key: "activations", load: () => api("api/activations"), select: data => data.activations || [] },
    { key: "accountGateway", load: () => api("api/account-gateway"), select: data => data.settings || {} },
  ];
  if (state.me.role === "super_admin") {
    jobs.push(
      { key: "accounts", load: () => api("api/accounts"), select: data => data.accounts || [] },
      { key: "auditLogs", load: () => api("api/audit-logs?limit=100"), select: data => data.logs || [] },
      { key: "publicSettings", load: () => api("api/public-settings"), select: data => data.settings || {} },
    );
  }
  const results = await Promise.allSettled(jobs.map(job => job.load()));
  state.loadErrors = {};
  results.forEach((result, index) => {
    const job = jobs[index];
    if (result.status === "fulfilled") state[job.key] = job.select(result.value);
    else state.loadErrors[job.key] = result.reason?.message || "状态暂不可用";
  });
  renderAll();
}

function renderAll() {
  applyRoleVisibility();
  renderOverview();
  renderCodes();
  renderActivations();
  renderAccounts();
  renderInvites();
  renderPlans();
  renderAudit();
  renderPublicSettings();
  renderAccountGatewayConfig();
}
```

- [ ] **Step 3: 完成响应式样式**

在 `1100px` 以下把总览指标改为两列、发卡主区改为单列；在 `760px` 以下把侧栏变为顶部可横向滚动的导航带，表格外层使用受控横向滚动，主按钮不溢出。固定按钮高度和表格最小列宽，避免加载状态造成布局跳动。

- [ ] **Step 4: 运行全部本地自动化测试**

Run:

```powershell
python -m unittest discover -s license_server\tests -p "test_*.py" -v
& 'openclaw_new_launcher\python-runtime\python.exe' -m unittest discover -s openclaw_new_launcher\python\tests -p "test_*.py"
Push-Location openclaw_new_launcher
npm run build
Pop-Location
```

Expected: 三组命令均以 exit code 0 完成。

- [ ] **Step 5: 使用临时数据库完成本地真实流程**

用独立临时目录和测试密钥启动 `127.0.0.1:18792`：

```powershell
$temp = Join-Path $env:TEMP ("luming-license-admin-rc-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$env:LICENSE_DB = Join-Path $temp 'license.db'
$env:LICENSE_BACKUP_DIR = Join-Path $temp 'backups'
$env:LICENSE_PRIVATE_KEY_FILE = Join-Path $temp 'private_key.b64'
$env:LICENSE_ADMIN_TOKEN = 'local-bootstrap-token'
$env:LICENSE_HOST = '127.0.0.1'
$env:LICENSE_PORT = '18792'
@'
import base64
import importlib.util
import os
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate().private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
with open(os.environ["LICENSE_PRIVATE_KEY_FILE"], "w", encoding="utf-8") as file:
    file.write(base64.b64encode(key).decode("ascii"))
spec = importlib.util.spec_from_file_location("license_admin_rc", "license_server/server.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.create_account_record(
    username="local-admin",
    display_name="Local Admin",
    password="local-password-123",
    role=module.ACCOUNT_ROLE_SUPER_ADMIN,
)
'@ | python -
$server = Start-Process -FilePath python -ArgumentList @('license_server/server.py', 'serve') -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
curl.exe -fsS http://127.0.0.1:18792/health
```

打开 `http://127.0.0.1:18792/admin`，使用测试账号 `local-admin` / `local-password-123`，走通：

1. 登录超级管理员。
2. 首页真实指标不是硬编码。
3. 快速生成 1 个测试码。
4. 下载 CSV，确认 Excel 打开后字段正确且无公式执行。
5. 刷新列表，完整码默认不可见。
6. 确认 reveal 后看到该码，关闭弹层后 DOM 不再保留。
7. 选择该码导出，审计出现 `codes.reveal` 和 `codes.export`，审计响应不含完整码。
8. 商家账号只能看到自己的码和设备。

检查完成后执行 `Stop-Process -Id $server.Id`。临时目录只包含测试数据，不复制到生产环境。

- [ ] **Step 6: 做桌面、1024px 和窄屏可视化检查**

使用 Computer Use 或浏览器控制逐项点击全部导航入口，分别截取 1440×900、1024×768、390×844。确认登录框、总览、发卡确认层、秘密查看层、列表、设备表和危险区不空白、不重叠，密钥和完整码默认遮蔽。

- [ ] **Step 7: 提交任务 6**

```powershell
git add license_server/admin_console.html license_server/tests/test_admin_console_contract.py
git commit -m "test: harden license admin release candidate"
```

## Task 7: 火山云生产部署与回滚验证

**Files:**
- Deploy: `license_server/server.py`
- Deploy: `license_server/admin_console.html`
- Preserve: `/opt/openclaw-license/license.db`
- Preserve: `/opt/openclaw-license/private_key.b64`

**Interfaces:**
- Consumes: 通过全部测试的本地发布候选。
- Produces: `https://license.heang.top/admin` 上线版本及远端备份文件。

- [ ] **Step 1: 部署前确认工作树和候选哈希**

```powershell
git status --short --branch
Get-FileHash license_server\server.py -Algorithm SHA256
Get-FileHash license_server\admin_console.html -Algorithm SHA256
```

Expected: 只有已知的非任务文件变更；两份候选文件均有稳定 SHA256。

- [ ] **Step 2: 检查远端服务和关键文件**

```powershell
$key = 'C:\Users\Administrator\Desktop\heang_server'
ssh -i $key root@118.145.98.220 "systemctl is-active openclaw-license && test -f /opt/openclaw-license/license.db && test -f /opt/openclaw-license/private_key.b64 && curl -fsS http://127.0.0.1:18791/health"
```

Expected: `active`，关键文件存在，健康接口成功。

- [ ] **Step 3: 上传临时文件、编译检查、备份并原子替换**

```powershell
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
$key = 'C:\Users\Administrator\Desktop\heang_server'
scp -i $key license_server\server.py "root@118.145.98.220:/opt/openclaw-license/server.py.uploading-$stamp"
scp -i $key license_server\admin_console.html "root@118.145.98.220:/opt/openclaw-license/admin_console.html.uploading-$stamp"
ssh -i $key root@118.145.98.220 "python3 -m py_compile /opt/openclaw-license/server.py.uploading-$stamp && cp /opt/openclaw-license/server.py /opt/openclaw-license/server.py.bak-$stamp && cp /opt/openclaw-license/admin_console.html /opt/openclaw-license/admin_console.html.bak-$stamp && cp /opt/openclaw-license/license.db /opt/openclaw-license/license.db.bak-$stamp && mv /opt/openclaw-license/server.py.uploading-$stamp /opt/openclaw-license/server.py && mv /opt/openclaw-license/admin_console.html.uploading-$stamp /opt/openclaw-license/admin_console.html && systemctl restart openclaw-license && systemctl is-active openclaw-license"
```

Expected: 编译通过、三个备份存在、服务重启后为 `active`。

- [ ] **Step 4: 生产只读冒烟测试**

```powershell
curl.exe -fsS https://license.heang.top/health
$html = curl.exe -fsS https://license.heang.top/admin
$html | Select-String '麓鸣授权云'
$html | Select-String 'data-admin-shell'
```

Expected: 健康接口成功；生产 HTML 含新品牌和后台壳标记。此步骤不生成授权码、不修改生产客户数据。

- [ ] **Step 5: 人工登录生产后台检查安全边界**

使用现有管理员账号登录后仅做只读检查：总览数字与生产库一致、授权码默认遮蔽、审计页不暴露完整码、清空全部只在系统设置危险区。不要在生产环境运行测试发卡。

- [ ] **Step 6: 失败时按同一时间戳回滚**

仅在步骤 3-5 失败时执行：

```powershell
$key = 'C:\Users\Administrator\Desktop\heang_server'
ssh -i $key root@118.145.98.220 "cp /opt/openclaw-license/server.py.bak-$stamp /opt/openclaw-license/server.py && cp /opt/openclaw-license/admin_console.html.bak-$stamp /opt/openclaw-license/admin_console.html && systemctl restart openclaw-license && systemctl is-active openclaw-license"
```

默认不恢复数据库，因为只读冒烟测试不会写业务数据；只有确认本次部署造成数据库异常时，经过用户确认后才使用 `license.db.bak-$stamp`。

- [ ] **Step 7: 记录发布证据**

记录本地 commit、两份候选 SHA256、远端备份路径、健康响应、生产页面标记和剩余债务。最终报告不得包含授权码、Token、密码或私钥内容。
