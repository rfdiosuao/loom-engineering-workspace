import { defineConfig } from "vitepress";

export default defineConfig({
  lang: "zh-CN",
  title: "OpenClaw Docs",
  description: "OpenClaw / Lumi 启动器的新手、进阶、稳定性、打包和二开文档站。",
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: [/^\/skills\/openclaw-cli\.skill$/, /^\/skills\/openclaw-cli(?:\/.*)?$/],
  head: [
    ["link", { rel: "icon", href: "/logo.png" }],
    ["meta", { name: "theme-color", content: "#0f766e" }]
  ],
  markdown: {
    image: {
      lazyLoading: true
    }
  },
  themeConfig: {
    logo: "/logo.png",
    siteTitle: "OpenClaw Docs",
    search: {
      provider: "local",
      options: {
        translations: {
          button: { buttonText: "搜索文档", buttonAriaLabel: "搜索文档" },
          modal: {
            displayDetails: "显示详细列表",
            resetButtonTitle: "清除搜索",
            backButtonTitle: "关闭搜索",
            noResultsText: "没有找到结果",
            footer: { selectText: "选择", navigateText: "切换", closeText: "关闭" }
          }
        }
      }
    },
    nav: [
      { text: "快速开始", link: "/guide/getting-started" },
      { text: "功能手册", link: "/guide/phone-control" },
      { text: "稳定性", link: "/advanced/stability" },
      { text: "更新日志", link: "/updates/changelog" },
      { text: "二开", link: "/dev/secondary-development" },
      { text: "待确认", link: "/confirmations" }
    ],
    sidebar: [
      {
        text: "起步",
        collapsed: false,
        items: [
          { text: "文档首页", link: "/" },
          { text: "新手快速开始", link: "/guide/getting-started" },
          { text: "安装与更新", link: "/guide/install-update" },
          { text: "授权与模型", link: "/guide/auth-models" }
        ]
      },
      {
        text: "能力工作区",
        collapsed: false,
        items: [
          { text: "手机控制", link: "/guide/phone-control" },
          { text: "桌面 RPA", link: "/guide/desktop-rpa" },
          { text: "Skills 与 CLI", link: "/guide/skills-cli" },
          { text: "OpenClaw CLI Skill", link: "/guide/openclaw-cli-skill" }
        ]
      },
      {
        text: "稳定交付",
        collapsed: false,
        items: [
          { text: "更新日志", link: "/updates/changelog" },
          { text: "稳定性手册", link: "/advanced/stability" },
          { text: "故障排查矩阵", link: "/advanced/troubleshooting" },
          { text: "打包发布与 CI/CD", link: "/advanced/release-packaging" }
        ]
      },
      {
        text: "项目二开",
        collapsed: false,
        items: [
          { text: "架构说明", link: "/dev/architecture" },
          { text: "二次开发指南", link: "/dev/secondary-development" },
          { text: "Mac 适配", link: "/dev/mac-porting" }
        ]
      },
      {
        text: "表达与确认",
        collapsed: false,
        items: [
          { text: "文案与微文案", link: "/writing/microcopy" },
          { text: "FAQ", link: "/faq" },
          { text: "术语表", link: "/glossary" },
          { text: "待确认事项", link: "/confirmations" }
        ]
      }
    ],
    outline: {
      level: [2, 3],
      label: "本页目录"
    },
    footer: {
      message: "完成基础检查后，再执行自动化任务。",
      copyright: "OpenClaw / Lumi documentation workspace"
    },
    editLink: {
      pattern: "https://github.com/openclaw/openclaw",
      text: "查看项目源"
    },
    lastUpdated: {
      text: "最后更新",
      formatOptions: {
        dateStyle: "medium",
        timeStyle: "short"
      }
    }
  }
});
