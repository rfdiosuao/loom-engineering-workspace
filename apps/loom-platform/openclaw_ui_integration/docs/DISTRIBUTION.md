# 分发 / 分层下载 / 更新机制（设计 + 脚手架）

目标：把"安装包 <100MB + 首启分层下载 + 壳自动更新"做成一套可验证、可加速、
防投毒的机制，并且天然就是"以后支持多 Agent"的底座。

> 现状参考：便携包解压后 ~1.1GB（`node_modules` 407MB / `agents/luminode-desktop`
> 370MB / `_up_/python-runtime` 201MB / `node` 104MB），真正的启动器壳只有
> `OpenClaw.exe` ~10MB。所以把那四块重运行时改成"按需下载"是关键。

---

## 1. 分层模型

把重运行时切成独立"层（layer）"，每层一个 `.tar.gz`，由 manifest 描述：

| layer | 内容 | installPath（相对安装根） | required |
|---|---|---|---|
| `node` | 内置 Node 运行时 | `OpenClawFiles/node` | ✅ |
| `openclaw-deps` | OpenClaw npm 依赖 | `OpenClawFiles/node_modules` | ✅ |
| `python-runtime` | 内置 Python | `OpenClawFiles/_up_/python-runtime` | ✅ |
| `luminode-desktop` | 桌面 RPA Agent | `OpenClawFiles/agents/luminode-desktop` | ❌（用桌面控制时才下，省 370MB） |

安装根 = 包含 `OpenClawFiles/` 的目录。manifest 里的 `installPath` 全是相对路径，
所以与托管位置无关。

## 2. manifest.json（契约）

见 `scripts/dist/manifest.example.json`。字段：

```ts
interface DistManifest {
  schemaVersion: 1;
  product: string;
  version: string;
  tag: string;
  generatedAt: string;
  mirrors: string[];   // 基地址，按顺序尝试；谁先返回 sha256 匹配的字节谁赢
  layers: DistLayer[];
}
interface DistLayer {
  id: string;
  title: string;
  version?: string;
  file: string;        // 相对 mirror 基地址的文件名
  sha256: string;      // 命门：装前校验
  size: number;
  installPath: string; // 相对安装根
  required: boolean;
}
```

## 3. 安全模型（唯一不能省）

> **每个 layer 下载后必须用 manifest 里写死的 sha256 校验；manifest 本身必须走
> 可信 HTTPS 或带签名。**

- **镜像只负责快，不负责真。** ghproxy / 公共 CDN 是不可信管道——它们可能返回错误
  或被替换的字节。所以"加速源可换 + 内容 sha256 校验"是绑定的：换源加速，校验保真。
- **manifest 的信任根**：要么从你自己的可信 HTTPS 端点（如 `license_server`）取并校验
  TLS，要么对 manifest 做离线签名（复用 Tauri 的 `tauri signer` 那对密钥），App 内验签。
  否则中间人换掉 manifest 就能绕过所有 sha256（指向恶意层）。
- **私钥永不进包/仓库**（Tauri 签名私钥、license 私钥）。
- **原子安装**：下载→临时区→校验→`rename` 原子换入→写 `.layer.json` 标记→删旧；
  失败回滚，不留半截。已实现于 `dist-lib.mjs`。

## 4. 谁来执行下载（关键架构点）

- **首启 bootstrap 必须在 Rust 壳里做**（`src-tauri`），因为 `node` 本身是一个被
  下载的层——不能用 Node 去下载 Node（鸡生蛋）。Rust 已经有 `reqwest`，再加一个
  解压 + sha256 即可。`scripts/dist/dist-lib.mjs` 是这套逻辑的**参考实现**，Rust 照它
  实现即可（同样的：mirror 顺序、sha256 门、临时区→原子换入）。
- **node 之后的层**（deps / luminode）也可以由内置 node 跑 `dist-fetch` 来装。

## 5. 首启流程（建议）

1. Rust 壳启动 → 读取本地已装层标记（`.layer.json`）。
2. 缺哪些 required 层 → 显示"首次安装/初始化"界面（前端 redesign 加一个 setup 页）。
3. 取 manifest（可信端点/验签）→ 逐层：mirror 顺序下载 → sha256 → 原子换入 → 进度回传。
4. `luminode-desktop` 默认不装；用户点"桌面控制"时按需触发同一套 `installLayer`。
5. 全部 required 就绪 → 正常启动 bridge。

## 6. 交付兜底（对你这个产品尤其重要）

你的卖点是"可交付给客户能直接运行的产品包"，而企业/内网客户**下载不了**。所以保留
**两条线**：
- **在线瘦包**（默认）：<100MB 安装包 + 首启分层下载（本机制）。
- **全量离线包**（交付）：现在的便携 zip，所有层预置，`.layer.json` 预写好 → 首启直接
  跳过下载。`build-portable.ps1` 产物即可，额外补一步"预写各层 marker"。

## 7. 工具（已就绪，零 npm 依赖）

- `scripts/dist/dist-lib.mjs` — 核心库：`sha256File` / `tarCreate` / `tarExtract` /
  `download`（http(s) + 本地）/ `installLayer` / `installFromManifest`。
- `scripts/dist/build-layers.mjs` — 发布脚本：打各层 `.tar.gz` + 算 sha256 + 生成
  manifest。
  ```bash
  node scripts/dist/build-layers.mjs --source <OpenClawFiles 的父目录> \
    --version 2.0.6 --tag v2.0.6 --owner you/repo --out dist-layers
  gh release create v2.0.6 dist-layers/*.tar.gz dist-layers/manifest.json
  ```
- `scripts/dist/dist-selftest.mjs` — 离线自测：验证 打包→校验→原子安装 全链路，
  以及**篡改/损坏字节被 sha256 拒绝**。`node scripts/dist/dist-selftest.mjs`。

## 8. 你需要配的（最小版，基本免费）

1. 一个 GitHub 账号 + 一个 repo（放 Release）。
2. `tauri signer generate` 生成一对签名密钥（公钥进 App，私钥进 CI secret）。
3. 加速：`registry.npmmirror.com`（npm 那层）/ `ghproxy.com`（GitHub Release）。
4. （进阶）阿里云 OSS/腾讯云 COS + CDN；Windows EV 代码签名证书。

## 9. 多 Agent 扩展

本机制对 layer 的 id/installPath/来源是数据驱动的。要支持"装别的 Agent"，只需为它
写一份 manifest（它需要哪些层、从哪下、sha256、入口）。**OpenClaw 就是第一份 manifest。**
不用现在就做市场，但底座已经在这了。
