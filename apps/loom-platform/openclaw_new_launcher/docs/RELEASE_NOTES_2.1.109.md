# LOOM 2.1.109 更新说明

## Agent 通用接入

- 接入提示词先识别真实宿主，不再默认把任意 Agent 当作 Codex。
- 支持 Codex、Claude Code、CodeBuddy、WorkBuddy 和未知宿主的差异化 Skill/MCP 接入。
- 新增 `HOST_KIND`、`HOST_CAPABILITIES` 和 `ACCESS_MODE`，避免无工具的聊天 Agent 谎报接入成功。
- WorkBuddy 使用官方 `.workbuddy/mcp.json` 与 Skill 导入入口，不再写入 `.codex`。
- 未识别宿主时只进行临时 CLI 验证，不创建任何 Agent 配置目录。

## Skill 安装安全

- 统一 Skill 安装器取消隐式 Codex 默认目录。
- Windows 安装必须显式传入 `-Destination`，遗漏时立即停止且不写磁盘。
- 新版统一 Skill Library 为 `2026.07.21`，国内源、GitHub 固定提交源与安装包内置文件 SHA256 完全一致。

## 校验值

```text
44176023CF4E24FB7E839B7A4D1794245AD4314AC2ED2EF74A02254F8882D90D
```
