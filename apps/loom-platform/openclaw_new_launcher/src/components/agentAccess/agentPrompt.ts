import { APP_DISPLAY_NAME } from '../../version';

export const MCP_CONFIG_PATH = '<宿主官方 MCP 配置文件>';
export const MCP_SERVER_PATH = '${LOOM_CLI_DIR}/loom_mcp.py';
export const LUMING_SKILL_LIBRARY_PATH = '${AGENT_SKILLS_DIR}/luming-phone-agent/SKILL.md';
export const LUMING_SKILL_LIBRARY_URL =
  'https://loom.heang.top/downloads/luming-skills-library-20260721-36D03E43.zip';
export const LUMING_SKILL_LIBRARY_FALLBACK_URL =
  'https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/skills/luming-skills-library-20260721.zip';
export const LUMING_SKILL_LIBRARY_BUNDLED_URL = '/skills/luming-skills-library-20260721.zip';
export const LUMING_SKILL_LIBRARY_SHA256 =
  '36D03E43FEA6102AA6FEE96E7B91004FABAE45C6E40C5C3FC8D933F30DD03CA7';

export const CLI_SMOKE = '"${LOOM_PYTHON}" -B "${LOOM_CLI}" doctor --json';
export const MCP_SMOKE = '"${LOOM_PYTHON}" -B "${LOOM_CLI_DIR}/loom_mcp.py"';

const CODEX_CONFIG = `# Codex user config: config.toml under CODEX_HOME.
# Do not paste the real API key here. LOOM injects it through env.
model_provider = "heang"
model = "glm-5.2-coding"

[model_providers.heang]
name = "heang"
base_url = "https://api.heang.top/v1"
env_key = "LOOM_CODEX_API_KEY"
wire_api = "responses"
`;

const CONTROL_PROMPT = `You are the current host Agent using ${APP_DISPLAY_NAME} / LOOM as a local control plane. Keep your real host identity; never rename or impersonate Codex, Claude Code, CodeBuddy, WorkBuddy, or another Agent.
Use LOOM CLI/MCP as the local control plane; do not only describe actions.
Read <AgentSkillsDir>/luming-phone-agent/SKILL.md when the current host supports installed Skills. Otherwise follow the equivalent instructions embedded in this prompt and use LOOM CLI/MCP directly.
Run doctor --json and commands --json before selecting a command. Use doctor.data.paths.npmRoot for npm helpers, doctor.data.paths.pythonExe for Python, and doctor.data.paths.adbPath for ADB.
If bare adb is unavailable, use the absolute adbPath returned by doctor. Set LOOM_ADB for child commands and prepend its directory to the current process PATH; do not require a global Android SDK install.
Use the narrowest truthful surface: direct status/screenshot/read first, verified template second, phone Agent third. For multiple phones, dispatch once and supervise each device through matrix watch instead of repeatedly sending the same task.
Phone helpers include phone:agent, phone:vision, phone:video, phone:image, phone:image:edit, phone:fleet, phone:game, phone:publish, loom:phone:video, and signed events monitoring. Prefer click_ref from a fresh observation when a stable selector is available.
Phone recording may show an Android screen-capture consent prompt; stop for that OS-owned approval instead of claiming it was bypassed.
Creative commands include media image and media video. Transfer generated assets through LOOM's signed phone/media path and verify the destination devices.
Use the weak safety gate. The user's normalized task authorizes its named routine actions, including named publishing, comments, or private messages after account, target, content, frequency, duplicate, and audit checks. Stop for login submission, captcha, 2FA, payment, membership purchase, device-admin/accessibility/VPN/unknown-source enablement, security or ownership changes, platform-risk bypass, candidate rejection, or final hiring decisions.
If Computer Use, Node REPL, Browser, Chrome, or desktop control is unavailable, continue through LOOM CLI/MCP, local files, and phone direct/template/agent routes.
Never print or persist API keys, passwords, verification codes, private keys, launcher secrets, or phone tokens.
Generated HTML, Markdown, scripts, and config must be UTF-8. HTML must include <!doctype html>, <html lang="zh-CN">, <meta charset="UTF-8">, and viewport metadata.`;

export function buildMcpJson() {
  return JSON.stringify(
    {
      mcpServers: {
        loom: {
          command: '${LOOM_PYTHON}',
          args: ['-B', MCP_SERVER_PATH],
          env: {
            LOOM_MCP_PERMISSION: 'control',
            LOOM_ADB: '${LOOM_ADB}',
            PYTHONDONTWRITEBYTECODE: '1',
            PYTHONUTF8: '1',
            PYTHONIOENCODING: 'utf-8',
          },
        },
      },
    },
    null,
    2,
  );
}

export function buildOneShotAgentPrompt(mcpJson: string) {
  return `请让当前 Agent 接入 ${APP_DISPLAY_NAME}（LOOM），之后把 LOOM 当作本地总控能力使用。请直接执行，不要只给教程。

身份边界（最高优先级）：
- 保持你当前真实宿主的身份，不得把自己改称或伪装成 Codex，也不得因为下文包含 Codex 示例就采用 Codex 目录。
- 只有获得运行时、环境变量、产品配置或用户明确说明等可靠证据后，才能确定宿主；目录存在本身不是充分证据。
- 先输出并在本次执行中保存 HOST_KIND=codex|claude-code|codebuddy|workbuddy|unknown。HOST_KIND 未确定前禁止写入任何 Agent 配置目录。
- 同时输出 HOST_CAPABILITIES，列出当前真实具备的 shell、file-write、mcp、skill-import 能力，并据此选择 ACCESS_MODE=skill+mcp|mcp|cli|instructions-only。
- 当 HOST_KIND=unknown 时，不得创建 .codex、.claude、.codebuddy 或 .workbuddy；只在临时目录解压并使用 LOOM CLI 做当次只读验证。
- 如果 shell、file-write、mcp、skill-import 四项能力都不可用，设置 ACCESS_MODE=instructions-only，只给出可执行的导入信息；不得声称已经完成接入、安装或验证。

宿主适配表：
- Codex：Skill 目录为 CODEX_HOME/skills；未设置 CODEX_HOME 时才使用 Windows 的 %USERPROFILE%\\.codex\\skills 或 macOS/Linux 的 $HOME/.codex/skills。
- Claude Code：Skill 目录为 ~/.claude/skills（即 $HOME/.claude/skills）；项目级 MCP 使用项目 .mcp.json。不要写入 .codex。
- CodeBuddy：优先 CODEBUDDY_CONFIG_DIR/skills，否则使用 ~/.codebuddy/skills（即 $HOME/.codebuddy/skills）。不要写入 .codex。
- WorkBuddy：MCP 使用 <项目目录>/.workbuddy/mcp.json，只有用户明确要求全局复用时才用 ~/.workbuddy/mcp.json。Skill 应通过 WorkBuddy 的“插件 → 技能 → 上传技能”官方入口导入；若当前运行时提供官方 Skill 导入工具则调用它，否则保留已校验 ZIP 并报告路径，禁止猜测私有 Skill 目录，更不能写入 .codex。
- unknown：不持久化 Skill 或 MCP；继续使用 LOOM CLI，报告当前宿主需要提供的官方导入入口。

1. 按身份边界识别 HOST_KIND、HOST_CAPABILITIES 和 ACCESS_MODE，并报告判定证据。无法可靠识别宿主时保持 unknown；有 shell 时仍可完成 CLI 只读接入，没有本地工具时诚实进入 instructions-only。
2. 自动发现 LOOM CLI：优先 LOOM_CLI；否则在常见安装目录和当前工作区寻找 _up_/python/loom_cli.py、python/loom_cli.py 或 openclaw_new_launcher/python/loom_cli.py。Windows 常见根目录包括 %LOCALAPPDATA%\\LOOM、%ProgramFiles%\\LOOM、D:\\LOOM、C:\\LOOM；macOS 包括 /Applications/LOOM.app/Contents/Resources 和 ~/Library/Application Support/LOOM。
3. 用发现到的 Python 执行 doctor --json。以后以 data.paths.pythonExe、cliPath、mcpPath、npmRoot 和 adbPath 为准，不猜路径。
4. 下载 BEGIN_SKILL_LIBRARY 中唯一的统一 Skill 压缩包。依次尝试国内 cloudUrl、GitHub fallbackUrl；在 LOOM 页面内执行且云端均不可用时使用 bundledUrl。无论使用哪个来源，下载后都必须校验 SHA256，不一致立即停止，不安装。
5. 解压到临时目录并读取 manifest.json 与 luming-phone-agent/SKILL.md。只有 HOST_KIND=codex|claude-code|codebuddy 且官方 Skill 目录已按宿主适配表确定时，Windows 才可执行 scripts/install.ps1 -Destination "<官方 Skill 目录>"；macOS/Linux 按 manifest.json 原子复制到同一明确目录。安装器必须显式传 -Destination，禁止无参数运行。只移除 manifest.replaces 精确列出的旧 Skill，保留所有无关 Skill，不清空 skills 目录。
6. HOST_KIND=workbuddy 时优先调用官方 Skill 导入工具；工具不可用就保留已校验 ZIP 供界面上传，不直接写任何猜测目录。HOST_KIND=unknown 时只读取临时 Skill，不持久化。其他宿主确认 ${LUMING_SKILL_LIBRARY_PATH} 存在后读取它。
7. 如果当前宿主支持 MCP，把 BEGIN_MCP_JSON 到 END_MCP_JSON 合并到宿主官方配置，保留其他 MCP server，并把占位符替换为 doctor 返回的绝对路径。WorkBuddy 默认写 <项目目录>/.workbuddy/mcp.json；Codex、Claude Code、CodeBuddy 必须遵循各自已确认的官方配置位置；unknown 不写配置。
8. 如果命令行找不到 adb，不要要求用户另装 Android SDK：使用 doctor.data.paths.adbPath；为当前子进程设置 LOOM_ADB，并把其目录加入当前 PATH。不要修改用户全局 PATH。
9. 验证：先执行 doctor --json 和 commands --json，再执行只读的 phone status --json、matrix status --json。MCP 可启动时再验证 MCP；不要用真实发布动作做冒烟测试。
10. 接入完成后，报告 HOST_KIND、HOST_CAPABILITIES、ACCESS_MODE、判定证据、LOOM CLI、Skill 状态、MCP 配置位置、ADB 路径和验证结果。WorkBuddy 若还需一次界面导入，应明确报告 ZIP 路径；任何密钥与手机令牌必须脱敏。

运行规则：
- LOOM 的能力包含安装/启动智能体、模型配置、单手机控制、手机矩阵、截图与只读监控、生图、图片编辑、生视频、素材传手机、获客与招聘场景。
- 使用弱安全门禁：用户明确任务中点名的常规动作可自动连续执行；仅登录、验证码、2FA、支付/购买、安全权限、所有权变更、平台风控绕过、候选人淘汰与最终录用决定必须停下来交给人。
- 多手机任务只下发一次，用 matrix watch / 事件流监督；不要重复派发，不要用工具调用过程刷屏。
- 不写死单台电脑路径，不泄露 API Key、Token、密码、验证码或手机配对密钥。
- Computer Use、Node REPL、Browser 或 Chrome 不可用时，继续使用 LOOM CLI/MCP 和手机 direct/template/agent 通道。
- 生成 HTML/Markdown/脚本/配置必须使用 UTF-8；HTML 必须包含 <!doctype html>、<html lang="zh-CN">、<meta charset="UTF-8"> 和 viewport。

BEGIN_SKILL_LIBRARY
name: luming-phone-agent
cloudUrl: ${LUMING_SKILL_LIBRARY_URL}
fallbackUrl: ${LUMING_SKILL_LIBRARY_FALLBACK_URL}
bundledUrl: ${LUMING_SKILL_LIBRARY_BUNDLED_URL}
sha256: ${LUMING_SKILL_LIBRARY_SHA256}
installer: scripts/install.ps1
installedPathTemplate: ${LUMING_SKILL_LIBRARY_PATH}
END_SKILL_LIBRARY

BEGIN_MCP_JSON
${mcpJson}
END_MCP_JSON

仅当 HOST_KIND=codex 时可参考以下 Codex 模型配置；其他宿主必须忽略，不要把真实 Key 写入文件：
${CODEX_CONFIG}

总控规则：
${CONTROL_PROMPT}

现在开始：先识别真实宿主并输出 HOST_KIND，再发现 LOOM 路径、按宿主接入并完成只读验证。`;
}
