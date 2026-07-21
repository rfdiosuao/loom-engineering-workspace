# 麓鸣图生图、图生视频与本机素材库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有创作页真实接通图生图、图生视频、六个常用图片比例和跨重启本机素材库，并生成经过源码保护验证的 `2.1.82` Tauri NSIS 安装包。

**Architecture:** 保留现有异步 Job、图像客户端和视频客户端。新增独立 `MediaLibrary` 服务，以 `data/generated-images`、`data/videos` 中的文件作为事实来源，通过有界扫描提供列表、解析、删除与 sidecar 元数据；前端把模式、参考图和素材库拆成小组件。发布阶段从源码生成隔离的 protected staging，再由 Tauri 资源映射打入 NSIS，绝不原地改写开发源码。

**Tech Stack:** React 18、TypeScript、Tauri 2、FastAPI、Python 3.12、Node.js ESM、Vite 8、unittest、Node test、PowerShell、NSIS。

## Global Constraints

- 图片页面只展示 `1:1`、`3:4`、`4:3`、`9:16`、`16:9`、`5:2`，不显示自定义宽高。
- 图生图使用现有 `editImagePath`；图生视频使用现有 `mode: "i2v"` 与 `imagePath`。
- 本地上传和素材库图片都只能准备任务，不得自动提交生成或发布。
- UI、`loom_cli.py media image/video`、`npm run phone:image` 的产物必须能被同一本机素材库发现。
- 现有 `data/generated-images`、`data/videos` 和用户配置不得因升级、回滚或卸载流程改动而被删除。
- 不新增云存储、自动发布、自动评论、自动私信、自动加好友或批量触达。
- 发布包不得包含第三方 Agent payload，不得把前端压缩误报为整包不可逆加密。
- 所有实现遵循 TDD；每项功能必须先观察失败测试，再实现并观察通过。

---

### Task 1: 本机素材库核心

**Files:**
- Create: `openclaw_new_launcher/python/services/media_library.py`
- Create: `openclaw_new_launcher/python/tests/test_media_library.py`

**Interfaces:**
- Produces: `MediaAsset`, `MediaLibrary.list_assets(kind, cursor, limit)`, `MediaLibrary.resolve(asset_id)`, `MediaLibrary.record(path, metadata)`, `MediaLibrary.delete(asset_id)`、`MediaLibrary.reveal(asset_id)`。
- Consumes: `data_dir`，并且只允许 `generated-images` 与 `videos` 两个子目录。

- [ ] **Step 1: 写失败测试，锁定扫描、分页、去重和旧文件兼容**

```python
class MediaLibraryTests(unittest.TestCase):
    def test_list_discovers_ui_python_cli_and_node_cli_files(self):
        library = MediaLibrary(self.temp_dir)
        self.write("generated-images/loom-image-20260716.png", b"png")
        self.write("generated-images/openclaw-image-20260716.png", b"png")
        self.write("videos/loom-video-20260716.mp4", b"video")

        result = library.list_assets(kind=None, cursor="", limit=20)

        self.assertEqual([item["kind"] for item in result["items"]], ["video", "image", "image"])
        self.assertTrue(all(item["id"] for item in result["items"]))
        self.assertFalse(result["hasMore"])
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `python -m unittest python.tests.test_media_library -v`

Expected: `ModuleNotFoundError: No module named 'services.media_library'`。

- [ ] **Step 3: 实现素材数据结构与允许目录扫描**

```python
@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    kind: str
    path: str
    filename: str
    mime: str
    size: int
    created_at: str
    metadata: dict[str, Any]


class MediaLibrary:
    def __init__(self, data_dir: str):
        self.data_dir = os.path.realpath(data_dir)
        self.roots = {
            "image": os.path.realpath(os.path.join(data_dir, "generated-images")),
            "video": os.path.realpath(os.path.join(data_dir, "videos")),
        }

    def list_assets(self, kind: str | None, cursor: str, limit: int = 20) -> dict:
        assets = sorted(self._scan(kind), key=lambda item: (item.created_at, item.asset_id), reverse=True)
        start = self._decode_cursor(cursor, assets)
        page = assets[start:start + max(1, min(limit, 50))]
        return {"items": [self._public(item) for item in page], "nextCursor": self._next_cursor(assets, start, len(page)), "hasMore": start + len(page) < len(assets)}
```

- [ ] **Step 4: 增加失败测试，锁定 sidecar、损坏文件与稳定 ID**

```python
def test_sidecar_is_optional_and_corruption_does_not_break_listing(self):
    image = self.write("generated-images/loom-image-a.png", b"png")
    self.write_text(f"{image}.json", "{bad-json")
    first = self.library.list_assets("image", "", 20)
    second = self.library.list_assets("image", "", 20)
    self.assertEqual(first["items"][0]["id"], second["items"][0]["id"])
    self.assertEqual(first["items"][0]["filename"], "loom-image-a.png")
```

- [ ] **Step 5: 实现 sidecar、记录、解析、安全删除和打开位置**

```python
def record(self, path: str, metadata: dict[str, Any]) -> dict:
    asset = self._asset_from_path(self._assert_allowed_file(path))
    write_json(f"{asset.path}.json", {"schema": "loom.media.asset.v1", **metadata})
    return self._public(self._asset_from_path(asset.path))

def delete(self, asset_id: str) -> dict:
    asset = self.resolve(asset_id)
    os.unlink(asset.path)
    sidecar = f"{asset.path}.json"
    if os.path.isfile(sidecar):
        os.unlink(sidecar)
    return {"deleted": True, "id": asset.asset_id}
```

- [ ] **Step 6: 增加路径穿越、符号链接越界、目录删除测试并实现拒绝逻辑**

Run: `python -m unittest python.tests.test_media_library -v`

Expected: 所有素材库测试通过，未知 ID、目录、越界链接均抛出 `MediaLibraryError`。

- [ ] **Step 7: 提交素材库核心**

```powershell
git add openclaw_new_launcher/python/services/media_library.py openclaw_new_launcher/python/tests/test_media_library.py
git commit -m "feat(media): add persistent local asset library"
```

---

### Task 2: Bridge 素材接口与生成元数据

**Files:**
- Modify: `openclaw_new_launcher/python/api/routes_media.py`
- Modify: `openclaw_new_launcher/python/tests/test_creative_media_contract.py`
- Create: `openclaw_new_launcher/python/tests/test_media_library_routes.py`

**Interfaces:**
- Consumes: Task 1 `MediaLibrary`。
- Produces: `GET /api/media/assets`、`GET /api/media/assets/{assetId}/content`、`POST /api/media/assets/{assetId}/reveal`、`DELETE /api/media/assets/{assetId}`。

- [ ] **Step 1: 写失败路由测试**

```python
def test_media_assets_list_content_range_reveal_and_delete(self):
    response = self.client.get("/api/media/assets?kind=video&limit=20")
    self.assertEqual(response.status_code, 200)
    asset_id = response.json()["items"][0]["id"]
    partial = self.client.get(f"/api/media/assets/{asset_id}/content", headers={"Range": "bytes=0-3"})
    self.assertEqual(partial.status_code, 206)
    self.assertEqual(partial.headers["content-range"], "bytes 0-3/10")
    deleted = self.client.delete(f"/api/media/assets/{asset_id}")
    self.assertTrue(deleted.json()["deleted"])
```

- [ ] **Step 2: 运行测试并确认 404/接口不存在**

Run: `python -m unittest python.tests.test_media_library_routes -v`

Expected: 素材接口返回 404。

- [ ] **Step 3: 注册路由并实现有界 Range 响应**

```python
@app.get("/api/media/assets")
async def media_assets(request: Request, kind: str | None = None, cursor: str = "", limit: int = 20):
    if error := ctx.auth_error(request):
        return error
    return ctx.fastapi_json(library.list_assets(kind, cursor, limit))

@app.get("/api/media/assets/{asset_id}/content")
async def media_asset_content(request: Request, asset_id: str):
    if error := ctx.auth_error(request):
        return error
    return _media_file_response(library.resolve(asset_id), request.headers.get("range", ""))
```

- [ ] **Step 4: 写失败测试，要求生成完成后写 sidecar 并清理 Data URL 临时文件**

```python
def test_image_and_video_generation_record_mode_ratio_model_and_source(self):
    image = routes_media._image_generate_payload(self.ctx, {"prompt": "edit", "editImagePath": self.data_url, "ratio": "5:2", "size": "2560x1024", "source": "ui"})
    video = routes_media._video_generate_payload(self.ctx, {"prompt": "move", "mode": "i2v", "imagePath": self.data_url, "ratio": "9:16", "source": "cli"})
    self.assertEqual(self.read_sidecar(image["files"][0]["path"])["ratio"], "5:2")
    self.assertEqual(self.read_sidecar(video["path"])["mode"], "i2v")
```

- [ ] **Step 5: 在生成落盘后调用 `library.record`，失败不删除媒体结果**

```python
metadata = {
    "prompt": prompt,
    "mode": "i2i" if edit_path else "t2i",
    "ratio": _text(body.get("ratio")),
    "model": model,
    "source": _text(body.get("source")) or "ui",
    "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
for file_item in files:
    library.record(file_item["path"], metadata)
```

- [ ] **Step 6: 运行媒体后端测试**

Run: `python -m unittest python.tests.test_media_library python.tests.test_media_library_routes python.tests.test_creative_media_contract -v`

Expected: 全部通过。

- [ ] **Step 7: 提交 Bridge 素材接口**

```powershell
git add openclaw_new_launcher/python/api/routes_media.py openclaw_new_launcher/python/tests/test_creative_media_contract.py openclaw_new_launcher/python/tests/test_media_library_routes.py
git commit -m "feat(media): expose persistent asset routes"
```

---

### Task 3: 创作模式、常用比例与参考图

**Files:**
- Create: `openclaw_new_launcher/src/components/creative/mediaPresets.ts`
- Create: `openclaw_new_launcher/src/components/creative/ReferenceImagePicker.tsx`
- Modify: `openclaw_new_launcher/src/components/creative/CreativeMediaPage.tsx`
- Modify: `openclaw_new_launcher/src/services/api.ts`
- Modify: `openclaw_new_launcher/python/tests/test_creative_media_contract.py`
- Modify: `openclaw_new_launcher/src/components/controlIntegrity.test.ts`

**Interfaces:**
- Produces: `ImageMode = 't2i' | 'i2i'`、`VideoMode = 't2v' | 'i2v'`、`ReferenceImage`、`IMAGE_RATIO_PRESETS`、`validateReferenceFile(file)`。
- Consumes: 现有 `imageApi.submit`、`videoApi.submit` 与独立 Job 轮询。

- [ ] **Step 1: 写失败契约测试，锁定四种模式和六个图片比例**

```python
for marker in (
    "data-creative-mode-t2i", "data-creative-mode-i2i",
    "data-creative-mode-t2v", "data-creative-mode-i2v",
    "data-reference-image-picker", "5:2", "IMAGE_RATIO_PRESETS",
):
    self.assertIn(marker, source)
self.assertNotIn("自定义宽高", source)
```

- [ ] **Step 2: 运行测试并确认缺少模式标记而失败**

Run: `python -m unittest python.tests.test_creative_media_contract -v`

Expected: 缺少 `data-creative-mode-i2i`。

- [ ] **Step 3: 实现集中比例 preset 与上传校验**

```ts
export const IMAGE_RATIO_PRESETS = [
  { ratio: '1:1', size: '1024x1024' },
  { ratio: '3:4', size: '1152x1536' },
  { ratio: '4:3', size: '1536x1152' },
  { ratio: '9:16', size: '1152x2048' },
  { ratio: '16:9', size: '2048x1152' },
  { ratio: '5:2', size: '2560x1024' },
] as const;

export function validateReferenceFile(file: File): string {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return '仅支持 PNG、JPG、WebP 图片';
  if (file.size > 20 * 1024 * 1024) return '参考图不能超过 20 MB';
  return '';
}
```

- [ ] **Step 4: 实现参考图组件和本地 FileReader 流程**

```tsx
<input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={onFileChange} />
<Button variant="quiet" onClick={() => inputRef.current?.click()}>上传参考图</Button>
<Button variant="quiet" onClick={onUseLatest} disabled={!latestAsset}>使用最近生成图片</Button>
```

- [ ] **Step 5: 修改提交负载，文生模式绝不携带参考图**

```ts
const imageRequest = {
  ...imagePayload({ imageBaseUrl, imageApiKey, imageModel, imageSize: selectedImagePreset.size, imageCount }),
  prompt: imagePrompt.trim(),
  ratio: selectedImagePreset.ratio,
  source: 'ui',
  ...(imageMode === 'i2i' ? { editImagePath: imageReference?.requestValue } : {}),
};

const videoRequest = {
  ...videoPayload({ videoProvider, videoBaseUrl, videoApiKey, videoModel, videoResolution, videoDuration, videoRatio }),
  prompt: videoPrompt.trim(),
  mode: videoMode,
  source: 'ui',
  ...(videoMode === 'i2v' ? { imagePath: videoReference?.requestValue } : {}),
};
```

- [ ] **Step 6: 增加缺图拦截与任务独立性测试并运行**

Run: `npm run test:platform-contracts`

Expected: TypeScript 与 Node 契约全部通过，图片和视频按钮只由各自 Job 状态禁用。

- [ ] **Step 7: 提交创作模式与比例**

```powershell
git add openclaw_new_launcher/src/components/creative openclaw_new_launcher/src/services/api.ts openclaw_new_launcher/python/tests/test_creative_media_contract.py openclaw_new_launcher/src/components/controlIntegrity.test.ts
git commit -m "feat(creative): add image and video reference modes"
```

---

### Task 4: 持久结果区与素材复用

**Files:**
- Create: `openclaw_new_launcher/src/components/creative/MediaLibraryPanel.tsx`
- Modify: `openclaw_new_launcher/src/components/creative/CreativeMediaPage.tsx`
- Modify: `openclaw_new_launcher/src/services/api.ts`
- Modify: `openclaw_new_launcher/python/tests/test_creative_media_contract.py`

**Interfaces:**
- Consumes: Task 2 素材 API、Task 3 `ReferenceImage`。
- Produces: `MediaAsset`, `MediaAssetPage` 类型与 `mediaApi.assets/reveal/deleteAsset`。

- [ ] **Step 1: 写失败契约测试，锁定本次结果、本机素材库、加载更多和安全删除**

```python
for marker in (
    "data-current-generation-results", "data-local-media-library",
    "mediaApi.assets", "mediaApi.reveal", "mediaApi.deleteAsset",
    "加载更多", "用作图生图", "用作图生视频",
):
    self.assertIn(marker, source)
```

- [ ] **Step 2: 运行测试并确认缺少素材库 UI 而失败**

Run: `python -m unittest python.tests.test_creative_media_contract -v`

Expected: 缺少 `data-local-media-library`。

- [ ] **Step 3: 增加素材 API 类型与调用**

```ts
export interface MediaAsset {
  id: string;
  kind: 'image' | 'video';
  path: string;
  filename: string;
  mime: string;
  size: number;
  createdAt: string;
  ratio?: string;
  prompt?: string;
  source?: string;
}

// Add these methods to the existing mediaApi object in src/services/api.ts.
export const mediaLibraryApi = {
  assets: (kind?: 'image' | 'video', cursor = '', limit = 20) => api<MediaAssetPage>(`/api/media/assets?${params}`),
  reveal: (id: string) => api(`/api/media/assets/${encodeURIComponent(id)}/reveal`, 'POST', {}),
  deleteAsset: (id: string) => api(`/api/media/assets/${encodeURIComponent(id)}`, 'DELETE'),
};
```

- [ ] **Step 4: 实现分页素材面板和对象 URL 生命周期**

```tsx
<section data-local-media-library>
  {assets.map((asset) => (
    <MediaAssetCard
      key={asset.id}
      asset={asset}
      src={convertFileSrc(asset.path)}
      onUseForImage={() => onUseReference(asset, 'image')}
      onUseForVideo={() => onUseReference(asset, 'video')}
      onDelete={() => setDeleteCandidate(asset)}
    />
  ))}
</section>
```

- [ ] **Step 5: Job 完成后刷新第一页，失败保留旧素材列表**

```ts
if (jobDone(job)) {
  applyFinishedJob(job, kind);
  await refreshAssets({ preserveOnError: true });
}
```

- [ ] **Step 6: 增加删除确认 Modal、空状态和失败状态**

删除确认必须显示文件名，并只在用户二次确认后调用 `DELETE`。素材库刷新失败保留上一份 `assets`，本次结果不受影响。

- [ ] **Step 7: 运行前端构建与媒体契约测试**

Run: `python -m unittest python.tests.test_creative_media_contract -v; npm run build`

Expected: 测试通过，Vite 构建退出码 0。

- [ ] **Step 8: 提交持久结果区**

```powershell
git add openclaw_new_launcher/src/components/creative openclaw_new_launcher/src/services/api.ts openclaw_new_launcher/python/tests/test_creative_media_contract.py
git commit -m "feat(creative): show persistent local media library"
```

---

### Task 5: CLI 来源标记与兼容验证

**Files:**
- Modify: `openclaw_new_launcher/python/loom_cli.py`
- Modify: `openclaw_new_launcher/python/tests/test_loom_cli_contract.py`
- Modify: `openclaw_new_launcher/scripts/openclaw-image-phone.mjs`
- Create: `openclaw_new_launcher/scripts/tests/openclaw-image-phone-contract.test.mjs`

**Interfaces:**
- Consumes: Bridge 现有 `source` 元数据与素材目录扫描。
- Produces: Python CLI 请求 `source: "cli"`；Node CLI JSON 结果包含 `libraryDirectory`。

- [ ] **Step 1: 写失败测试，要求 Python 媒体命令标记 CLI 来源**

```python
def test_media_image_and_video_mark_cli_source(self):
    image = self.run_cli(["media", "image", "--prompt", "x"])
    video = self.run_cli(["media", "video", "--prompt", "x"])
    self.assertEqual(image.request_body["source"], "cli")
    self.assertEqual(video.request_body["source"], "cli")
```

- [ ] **Step 2: 实现 CLI 来源字段并运行定向测试**

```python
body["prompt"] = prompt
body["source"] = "cli"
```

Run: `python -m unittest python.tests.test_loom_cli_contract -v`

Expected: CLI 媒体测试通过。

- [ ] **Step 3: 写 Node 失败测试，锁定默认输出目录仍为素材库目录**

```js
assert.match(source, /data['"], ['"]generated-images/);
assert.match(source, /libraryDirectory/);
```

- [ ] **Step 4: 在 JSON 输出中公开非秘密素材目录，不改生成协议**

`openclaw-image-phone.mjs` 继续默认保存到 `data/generated-images`，返回结果增加 `libraryDirectory: config.outDir`，不记录 API Key。

- [ ] **Step 5: 运行现有 Node CLI 契约测试**

Run: `node --test scripts/tests/*.test.mjs`

Expected: 全部 Node 测试通过。

- [ ] **Step 6: 提交 CLI 兼容改动**

```powershell
git add openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/tests/test_loom_cli_contract.py openclaw_new_launcher/scripts/openclaw-image-phone.mjs openclaw_new_launcher/scripts/tests/openclaw-image-phone-contract.test.mjs
git commit -m "feat(cli): register generated media with local library"
```

---

### Task 6: 受保护发布 staging

**Files:**
- Create: `openclaw_new_launcher/scripts/stage-protected-python.py`
- Create: `openclaw_new_launcher/scripts/stage-protected-release.mjs`
- Create: `openclaw_new_launcher/scripts/verify-protected-release.ps1`
- Create: `openclaw_new_launcher/src-tauri/tauri.protected.conf.json`
- Create: `openclaw_new_launcher/python/tests/test_protected_release_contract.py`
- Modify: `openclaw_new_launcher/package.json`
- Modify: `openclaw_new_launcher/package-lock.json`

**Interfaces:**
- Produces: `build/protected-resources/python`、`build/protected-resources/scripts`，以及 `npm run package:protected:nsis`。
- Consumes: 原始 `python`、`scripts`，不得原地修改。

- [ ] **Step 1: 写失败契约测试，锁定 protected staging 和 Tauri 资源映射**

```python
def test_protected_release_uses_staging_instead_of_source_resources(self):
    config = json.load(open(PROTECTED_TAURI_CONFIG, encoding="utf-8"))
    resources = config["bundle"]["resources"]
    self.assertEqual(resources["../build/protected-resources/python/**/*"], "python/")
    self.assertEqual(resources["../build/protected-resources/scripts/**/*"], "scripts/")
    self.assertNotIn("../python/**/*", resources)
    self.assertNotIn("../scripts/**/*", resources)
```

- [ ] **Step 2: 运行测试并确认 protected 配置不存在**

Run: `python -m unittest python.tests.test_protected_release_contract -v`

Expected: `FileNotFoundError`。

- [ ] **Step 3: 实现 Python 无源码字节码 staging**

```python
def stage_python(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    entries = {"bridge.py", "loom_cli.py", "loom_mcp.py"}
    for source_file in sorted(target.rglob("*.py")):
        pyc_file = source_file.with_suffix(".pyc")
        py_compile.compile(str(source_file), cfile=str(pyc_file), doraise=True, optimize=2)
        if source_file.name in entries and source_file.parent == target:
            source_file.write_text(loader_for(pyc_file.name), encoding="utf-8")
        else:
            source_file.unlink()
```

加载器只负责使用 `SourcelessFileLoader` 执行同名 `.pyc`，不得包含业务实现。

- [ ] **Step 4: 使用固定版本 `javascript-obfuscator@4.1.1` 生成 Node staging**

在 `devDependencies` 中锁定 `javascript-obfuscator` 为精确版本 `4.1.1`。`stage-protected-release.mjs` 清空 `build/protected-resources`，复制非 JS 资源，并对每个 `.mjs` 使用固定配置：`compact: true`、`controlFlowFlattening: false`、`deadCodeInjection: false`、`identifierNamesGenerator: 'hexadecimal'`、`stringArray: true`、`stringArrayThreshold: 0.75`。避免激进控制流改写破坏 CLI。

- [ ] **Step 5: 创建 Tauri protected 资源映射**

```json
{
  "bundle": {
    "resources": {
      "../../release-manifest.json": "release-manifest.json",
      "../../release-public-key.txt": "release-public-key.txt",
      "../.mcp.json": ".mcp.json",
      "../build/protected-resources/python/**/*": "python/",
      "../python-runtime/**/*": "python-runtime/",
      "../node-runtime/**/*": "node-runtime/",
      "../public/skills/**/*": "public/skills/",
      "../data/themes/**/*": "data/themes/",
      "../build/protected-resources/scripts/**/*": "scripts/",
      "../openclaw-workspace/**/*": "openclaw-workspace/",
      "../redist/**/*": "redist/"
    }
  }
}
```

- [ ] **Step 6: 实现 staging smoke 与源码泄漏扫描**

`verify-protected-release.ps1` 必须：

1. 用 bundled Python 启动 staged `bridge.py --port 0 --bridge-token <temporary>` 并等待端口输出。
2. 调用 staged `loom_cli.py --help`。
3. 调用 staged Node `openclaw-context.mjs --json` 和 `openclaw-image-phone.mjs --help`。
4. 拒绝 staging 中除三个最小加载器外的 `.py`。
5. 拒绝 `.ts`、`.tsx`、`.map` 和包含原始函数体特征的 `.mjs`。
6. 在 finally 中终止临时 Bridge，不接触正在运行的生产 Bridge。

- [ ] **Step 7: 运行 protected staging 契约与 smoke**

Run: `npm run stage:protected; powershell -ExecutionPolicy Bypass -File scripts/verify-protected-release.ps1`

Expected: Python/Node smoke 全部通过，源码泄漏扫描 0 项。

- [ ] **Step 8: 提交发布保护流程**

```powershell
git add openclaw_new_launcher/scripts/stage-protected-python.py openclaw_new_launcher/scripts/stage-protected-release.mjs openclaw_new_launcher/scripts/verify-protected-release.ps1 openclaw_new_launcher/src-tauri/tauri.protected.conf.json openclaw_new_launcher/python/tests/test_protected_release_contract.py openclaw_new_launcher/package.json openclaw_new_launcher/package-lock.json
git commit -m "build(release): add protected NSIS resource staging"
```

---

### Task 7: 版本、发布验证与 NSIS

**Files:**
- Modify: `openclaw_new_launcher/package.json`
- Modify: `openclaw_new_launcher/package-lock.json`
- Modify: `openclaw_new_launcher/src-tauri/Cargo.toml`
- Modify: `openclaw_new_launcher/src-tauri/tauri.conf.json`
- Modify: `openclaw_new_launcher/python/tests/test_release_source_of_truth.py`
- Create: `docs/releases/2.1.82.md`

**Interfaces:**
- Produces: `LOOM_2.1.82_x64-setup.exe` 与 SHA256。
- Consumes: Tasks 1-6 的代码、测试和 protected staging。

- [ ] **Step 1: 写失败版本测试并将目标版本锁定为 `2.1.82`**

```python
self.assertEqual(package["version"], "2.1.82")
self.assertEqual(package_lock["version"], "2.1.82")
self.assertEqual(package_lock["packages"][""]["version"], "2.1.82")
self.assertEqual(tauri["version"], "2.1.82")
```

- [ ] **Step 2: 更新四处版本源并运行版本测试**

Run: `python -m unittest python.tests.test_release_source_of_truth -v`

Expected: 全部通过。

- [ ] **Step 3: 写发布日志**

`docs/releases/2.1.82.md` 必须列出四种创作模式、六个图片比例、本机素材库、CLI 自动汇入、路径安全与 protected NSIS，不得声称云同步或不可逆加密。

- [ ] **Step 4: 运行完整验证**

```powershell
python -m unittest discover -s python\tests -p "test_*.py"
npm run test:platform-contracts
node --test scripts/*.test.mjs
npm run build
git diff --check
```

Expected: 所有命令退出码 0。

- [ ] **Step 5: 启动本地桌面视觉检查**

在 `960x640`、`1200x800`、`1920x1080` 检查图片/视频主入口、模式分段、六个比例、参考图、素材库空态和删除确认；文本不得溢出或重叠。用临时素材验证图片预览和视频播放，不使用生产账号或密钥。

- [ ] **Step 6: 生成 protected NSIS**

Run: `npm run package:protected:nsis`

Expected: `src-tauri/target/release/bundle/nsis/LOOM_2.1.82_x64-setup.exe` 存在且为标准 Tauri NSIS，而不是约 160 KB 的下载壳。

- [ ] **Step 7: 扫描安装包与构建资源**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-protected-release.ps1 -Installer src-tauri/target/release/bundle/nsis/LOOM_2.1.82_x64-setup.exe`

Expected: 无 Agent payload、无 TS/TSX/sourcemap、无 Python 业务源码、Node staging 已混淆，安装资源中存在最小 `python/bridge.py` 加载器和 `bridge.pyc`。

- [ ] **Step 8: 执行无损升级 smoke**

在一次性测试目录安装旧版，放入 `data/generated-images/preserve-me.png` 与 `data/videos/preserve-me.mp4`，再安装 `2.1.82`。验证两个文件仍存在、素材库可见、卸载器存在；不得操作真实 `D:\LOOM`。

- [ ] **Step 9: 计算 SHA256 并提交发布改动**

```powershell
Get-FileHash src-tauri\target\release\bundle\nsis\LOOM_2.1.82_x64-setup.exe -Algorithm SHA256
git add openclaw_new_launcher/package.json openclaw_new_launcher/package-lock.json openclaw_new_launcher/src-tauri/Cargo.toml openclaw_new_launcher/src-tauri/tauri.conf.json openclaw_new_launcher/python/tests/test_release_source_of_truth.py docs/releases/2.1.82.md
git commit -m "release: prepare LOOM 2.1.82"
```

- [ ] **Step 10: PR 前审查**

Run: `D:\Axiangmu\LOOM-Workspace\scripts\status.ps1`

检查完整 changed-file 列表、`git diff --check`、暂存区秘密扫描、安装包与本地媒体未被 Git 跟踪。PR 正文附测试证据、安装包路径、SHA256、保护级别、回滚说明和未上传状态。
