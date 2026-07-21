---
layout: home
hero:
  name: OpenClaw Docs
  text: OpenClaw 启动器使用、交付与二开指南
  tagline: 面向使用者、交付人员和二次开发者的 VitePress 文档站，覆盖首次启动、授权模型、手机控制、桌面 RPA、Skills/CLI、稳定性排障、打包发布和 Mac 适配。
  image:
    src: /screenshots/launcher-dashboard.png
    alt: OpenClaw 启动器总览
  actions:
    - theme: brand
      text: 新手快速开始
      link: /guide/getting-started
    - theme: alt
      text: 二次开发入口
      link: /dev/secondary-development
features:
  - title: 新手能走完
    details: 从解压、启动核心服务、授权和模型配置，到第一次执行手机或桌面任务。
  - title: 交付能复盘
    details: 把完整包、在线瘦包、CI/CD、清理用户状态和发布校验写成检查清单。
  - title: 二开有边界
    details: 说明哪些改 UI，哪些改 Bridge，哪些改手机端或桌面端，以及每一步如何验证。
---

<div class="copy-line">完成基础配置和连通性检查后，再执行自动化任务。</div>

## 现在你在哪一步

<div class="route-grid">
  <a class="route-card" href="/guide/getting-started">
    <strong>首次使用启动器</strong>
    <span>按顺序完成核心服务启动、授权、模型配置和第一条任务。</span>
  </a>
  <a class="route-card" href="/advanced/troubleshooting">
    <strong>遇到报错或超时</strong>
    <span>依次检查签名、Token、网络、锁屏、Bridge 和桌面组件状态。</span>
  </a>
  <a class="route-card" href="/dev/secondary-development">
    <strong>准备二次开发</strong>
    <span>先确认目录边界、API 分层、测试命令和 Mac 适配注意事项。</span>
  </a>
</div>

<figure class="home-shot">
  <img src="/screenshots/launcher-dashboard.png" alt="OpenClaw 启动器总览截图">
  <figcaption class="small-note">本图来自本地预览验收截图，已避免展示真实密钥。正式发布前请替换为当前版本截图。</figcaption>
</figure>

## 三类读者路径

<div class="path-grid">
  <div class="path-card">
    <strong>使用者：完成基础使用</strong>
    <span>建议阅读“新手快速开始”“手机控制”“桌面 RPA”“FAQ”。高级概念可在需要时再查看。</span>
  </div>
  <div class="path-card">
    <strong>交付人员：准备交付包</strong>
    <span>建议阅读“安装与更新”“打包发布与 CI/CD”“稳定性手册”。重点确认用户状态清理。</span>
  </div>
  <div class="path-card">
    <strong>二次开发者：扩展功能</strong>
    <span>建议阅读“架构说明”“二次开发指南”“Mac 适配”。先确认变更层级，再进入实现。</span>
  </div>
  <div class="path-card">
    <strong>排障人员：要快速定位问题</strong>
    <span>建议阅读“故障排查矩阵”。先查看日志，再缩小到授权、Bridge、手机端或桌面端。</span>
  </div>
</div>

## 第一次启动检查清单

<div class="check-grid">
  <div class="check-card"><strong>1. 启动核心服务</strong><span>启动器首页确认核心服务不是“待启动”。</span></div>
  <div class="check-card"><strong>2. 授权状态</strong><span>授权页显示有效授权，未授权时只使用开放入口。</span></div>
  <div class="check-card"><strong>3. 模型配置</strong><span>统一设置里填 Base URL、API Key、Model，密钥只脱敏显示。</span></div>
  <div class="check-card"><strong>4. 设备连通</strong><span>手机控制验证 Token 与 Lumi 签名，桌面 RPA 检查组件健康。</span></div>
</div>

## 截图导览

<div class="shot-grid">
  <figure class="shot-card">
    <img src="/screenshots/phone-control.png" alt="手机控制台截图">
    <figcaption>手机控制台：保存设备、刷新截图、下发任务、录屏留证。</figcaption>
  </figure>
  <figure class="shot-card">
    <img src="/screenshots/desktop-rpa.png" alt="桌面 RPA 截图">
    <figcaption>桌面 RPA：启动 Luminode/SightFlow、截图、读取未读、发送已确认回复。</figcaption>
  </figure>
  <figure class="shot-card">
    <img src="/screenshots/settings-models.png" alt="统一设置截图">
    <figcaption>统一设置：集中维护桥接、手机、模型、图像和视频配置。</figcaption>
  </figure>
  <figure class="shot-card">
    <img src="/screenshots/launcher-dashboard-mobile.png" alt="移动宽度总览截图">
    <figcaption>移动宽度检查：文档和启动器截图都要保证无横向溢出。</figcaption>
  </figure>
</div>

## 自动化工具使用范围

如果只使用自动化工具能力，可以优先关注当前版本的三项基础要求：

1. 保证启动器核心服务稳定。
2. 保证手机控制与桌面 RPA 的安全通道可验证。
3. 保证每次交付包都不带上一台机器的授权、密钥、缓存和用户数据。

满足以上三项后，OpenClaw 可作为基础自动化工具底座进入试用和交付验收。
