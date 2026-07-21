# OpenClaw VitePress 文档站

这里是 `D:\Axiangmu\AUSTART\docs` 的 VitePress 文档站源码。旧的单页 HTML 站已经归档到 `legacy-html/`，新文档从 `index.md` 与各目录 Markdown 页面生成。

## 本地开发

```powershell
npm install
npm run docs:dev
```

## 构建与预览

```powershell
npm run docs:build
npm run docs:preview
```

构建产物位于 `.vitepress/dist/`，不提交到仓库。
