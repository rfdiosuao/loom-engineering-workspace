# 麓鸣账户与 Z-Pay 支付后端部署门禁

本候选包用于把当前麓鸣账户、权益、共享矩阵授权和 Z-Pay 支付路由部署到既有授权服务。它不包含生产环境文件、商户号、商户密钥、数据库、签名私钥或任何用户数据。

支付与部署代码源提交：`3cec228654290c334bacc1e8f18a32df1f0035d4`。

## 部署边界

- 仅部署 `server.py`、完整 `luming_license` 模块树和可选管理页；部署脚本会先在线备份 SQLite、程序目录和既有环境文件。
- `LICENSE_REQUIRE_ZPAY_READY=1` 时，脚本会在停止服务前检查九项 Z-Pay 配置，且只报告配置名和通过/失败，不打印配置值。
- 上传包必须包含 `luming_license/http/routes_payments.py`；切换后会以未授权请求确认账户权益路由和支付套餐路由都返回 `401`。
- 支付通知、主动查单与发放权益仍以服务端验签、金额/商户/订单/渠道/nonce 二次核验和数据库事务为准；同步返回页不会发放权益。
- 本流程不执行真实扣款、退款、结算、商户资料修改或正式发布。

## 生产配置门禁

由有权限的运维人员把以下配置写入 `/opt/openclaw-license/openclaw-license.env`，文件权限保持 `0600`。不要把真实值写进命令历史、工单、截图、日志或代码仓库。

```text
LICENSE_ZPAY_ENABLED=1
LICENSE_ZPAY_BASE_URL=https://<已核验的支付商域名>
LICENSE_ZPAY_PID=<商户号>
LICENSE_ZPAY_KEY=<商户密钥>
LICENSE_ZPAY_CREATE_PATH=/mapi.php
LICENSE_ZPAY_QUERY_ENABLED=1
LICENSE_ZPAY_QUERY_PATH=/api.php
LICENSE_ZPAY_NOTIFY_URL=https://license.heang.top/api/payments/zpay/notify
LICENSE_ZPAY_RETURN_URL=https://license.heang.top/api/payments/zpay/return
```

配置完成后，可先运行不输出配置值的只读校验：

```bash
DEPLOY_ENV_FILE=/opt/openclaw-license/openclaw-license.env \
DEPLOY_ENV_VALIDATE_ZPAY=1 \
python3 /tmp/openclaw-license-luming_license/deploy_env.py
```

## 受控部署

把候选包中的文件上传到部署脚本默认位置：

```text
license/server.py -> /tmp/openclaw-license-server.py
license/luming_license -> /tmp/openclaw-license-luming_license
license/admin_console.html -> /tmp/openclaw-license-admin_console.html
```

核对候选包 `SHA256SUMS.txt` 后，以严格支付门禁执行：

```bash
LICENSE_REQUIRE_ZPAY_READY=1 bash license/deploy.sh
```

脚本会依次完成：完整备份、候选模块编译、同文件系统暂存、配置预检、原子切换、健康检查、SQLite `quick_check`、账户权益路由检查、支付路由检查。任一步失败都会恢复旧程序；如果本次更新了中转令牌，也会恢复旧环境文件。

## 上线后验收

1. 先确认 `/health`、账户权益公钥和未授权服务路由状态正确。
2. 使用支付商沙箱或测试商户创建最小测试订单，确认二维码内容与浏览器跳转地址没有混淆。
3. 分别验证异步通知、重复通知、主动查单恢复、错误签名、错误金额、错误商户、应用重启恢复和权益刷新。
4. 只有支付商后台、麓鸣支付订单和账户权益三方一致时才判定成功。
5. 任何真实扣款、退款或结算前必须单独确认。

## 回滚

部署失败会自动回滚。若上线后人工判定需要回滚，应停止服务，从脚本输出的 `/opt/openclaw-license/backups/deploy-<UTC时间>` 恢复 `server.py`、`luming_license`、可选管理页和环境文件，再启动服务并复查数据库与路由。不要回退或覆盖生产 `license.db`，除非已完成独立备份并确认确需数据库恢复。
