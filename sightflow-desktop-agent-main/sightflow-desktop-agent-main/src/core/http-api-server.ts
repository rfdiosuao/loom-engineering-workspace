// src/core/http-api-server.ts
// OpenClaw HTTP API 桥接层
//
// 在 Electron 主进程内启动一个轻量 HTTP 服务器，
// 让 OpenClaw Agent 通过 exec + curl 调用 Luminode 的桌面 RPA 能力。

import http from 'http'
import { DesktopDevice } from './device'

export interface HttpApiConfig {
  port: number
  host?: string
  token?: string
  allowUnauthenticated?: boolean
}

export class HttpApiServer {
  private server: http.Server | null = null
  private device: DesktopDevice | null = null

  constructor(private config: HttpApiConfig) {}

  attachDevice(device: DesktopDevice): void {
    this.device = device
  }

  getPort(): number {
    return this.config.port
  }

  getToken(): string {
    return this.config.token || ''
  }

  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.server = http.createServer(async (req, res) => {
        const origin = String(req.headers.origin || '')
        if (this.isAllowedOrigin(origin)) {
          res.setHeader('Access-Control-Allow-Origin', origin)
        }
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        res.setHeader(
          'Access-Control-Allow-Headers',
          'Content-Type, Authorization, X-Desktop-Agent-Token'
        )

        if (req.method === 'OPTIONS') {
          res.writeHead(204)
          res.end()
          return
        }

        if (!this.isAuthorized(req)) {
          res.writeHead(401, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify({ success: false, error: 'unauthorized' }))
          return
        }

        try {
          const body = await this.readBody(req)
          const result = await this.handleRequest(req.url || '/', req.method || 'GET', body)
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify(result))
        } catch (err: unknown) {
          res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(
            JSON.stringify({
              success: false,
              error: err instanceof Error ? err.message : String(err)
            })
          )
        }
      })

      const host = this.config.host || '127.0.0.1'
      this.server.listen(this.config.port, host, () => {
        console.log(`[HttpApiServer] Listening on http://${host}:${this.config.port}`)
        resolve()
      })

      this.server.on('error', (err) => {
        console.error('[HttpApiServer] Server error:', err)
        reject(err)
      })
    })
  }

  stop(): void {
    if (this.server) {
      this.server.close()
      this.server = null
      console.log('[HttpApiServer] Stopped')
    }
  }

  private async handleRequest(
    url: string,
    _method: string,
    body: unknown
  ): Promise<Record<string, unknown>> {
    // 去除 query string
    const path = url.split('?')[0]

    switch (path) {
      // ── 健康检查 ──
      case '/health':
      case '/':
        return {
          success: true,
          status: 'running',
          engine: false,
          device: !!this.device,
          tools: [
            'screenshot',
            'click',
            'type',
            'vlm_detect',
            'wechat_send',
            'wechat_unread',
            'measure_layout'
          ]
        }

      // ── 截屏 ──
      case '/screenshot':
        return await this.handleScreenshot(body)

      // ── 鼠标点击 ──
      case '/click':
        return await this.handleClick(body)

      // ── 键盘输入 ──
      case '/type':
        return await this.handleType(body)

      // ── 发送微信消息（高级：自动定位输入框 + 粘贴 + 回车） ──
      case '/wechat/send':
        return await this.handleWechatSend(body)

      // ── 未读检测 ──
      case '/wechat/unread':
        return await this.handleWechatUnread(body)

      // ── 联系人未读细检测 ──
      case '/wechat/contact_unread':
        return await this.handleContactUnread()

      // ── 布局测量 ──
      case '/measure_layout':
        return await this.handleMeasureLayout()

      // ── 聊天区域 diff ──
      case '/wechat/chat_diff':
        return await this.handleChatDiff()

      // ── 引擎状态 ──
      case '/engine/status':
        return {
          success: true,
          running: false
        }

      default:
        return { success: false, error: `Unknown endpoint: ${path}` }
    }
  }

  // ── 工具实现 ──

  private async handleScreenshot(_body: unknown): Promise<Record<string, unknown>> {
    void _body
    this.requireDevice()
    const screenshot = await this.device!.screenshot()
    return {
      success: true,
      // 返回 base64 截图（含 data:image/png;base64, 前缀）
      screenshot,
      timestamp: Date.now()
    }
  }

  private async handleClick(body: unknown): Promise<Record<string, unknown>> {
    this.requireDevice()
    const { x, y, coordinates } = (body || {}) as Record<string, unknown>

    let clickX: number, clickY: number

    if (coordinates && Array.isArray(coordinates)) {
      clickX = coordinates[0] as number
      clickY = coordinates[1] as number
    } else if (typeof x === 'number' && typeof y === 'number') {
      clickX = x
      clickY = y
    } else {
      return {
        success: false,
        error: 'Missing coordinates. Provide {x, y} or {coordinates: [x, y]}'
      }
    }

    await this.device!.clickAt(clickX, clickY)
    return { success: true, clicked: { x: clickX, y: clickY } }
  }

  private async handleType(body: unknown): Promise<Record<string, unknown>> {
    this.requireDevice()
    const { text } = (body || {}) as Record<string, unknown>
    if (!text) {
      return { success: false, error: 'Missing "text" field' }
    }
    await this.device!.sendMessage(String(text))
    return { success: true, typed: text }
  }

  private async handleWechatSend(body: unknown): Promise<Record<string, unknown>> {
    this.requireDevice()
    const { text } = (body || {}) as Record<string, unknown>
    if (!text) {
      return { success: false, error: 'Missing "text" field' }
    }
    await this.device!.sendMessage(String(text))
    return { success: true, sent: text }
  }

  private async handleWechatUnread(_body: unknown): Promise<Record<string, unknown>> {
    void _body
    this.requireDevice()
    const result = await this.device!.hasUnreadMessage()
    return {
      success: true,
      hasUnread: result.hasUnread,
      chatEntranceArea: result.chatEntranceArea || null
    }
  }

  private async handleContactUnread(): Promise<Record<string, unknown>> {
    this.requireDevice()
    const result = await this.device!.isChatContactUnread()
    return {
      success: true,
      isUnread: result.isUnread,
      firstContactCoords: result.firstContactCoords || null
    }
  }

  private async handleMeasureLayout(): Promise<Record<string, unknown>> {
    this.requireDevice()
    const result = await this.device!.measureLayout()
    return {
      success: true,
      measured: result.success,
      error: result.error || null
    }
  }

  private async handleChatDiff(): Promise<Record<string, unknown>> {
    this.requireDevice()
    const result = await this.device!.hasChatAreaChanged()
    return {
      success: true,
      hasDiff: result.hasDiff,
      hasBaseline: result.hasBaseline
    }
  }

  // ── 辅助 ──

  private requireDevice(): void {
    if (!this.device) {
      throw new Error('Device not attached. Start the engine first.')
    }
  }

  private isAuthorized(req: http.IncomingMessage): boolean {
    const expectedToken = this.config.token?.trim()
    if (!expectedToken) return this.config.allowUnauthenticated === true

    const authHeader = String(req.headers.authorization || '')
    if (authHeader === `Bearer ${expectedToken}`) return true

    const tokenHeader = req.headers['x-desktop-agent-token']
    if (Array.isArray(tokenHeader)) {
      return tokenHeader.includes(expectedToken)
    }
    return tokenHeader === expectedToken
  }

  private isAllowedOrigin(origin: string): boolean {
    if (!origin) return false
    try {
      const parsed = new URL(origin)
      return (
        parsed.hostname === 'localhost' ||
        parsed.hostname === '127.0.0.1' ||
        parsed.hostname === '[::1]'
      )
    } catch {
      return false
    }
  }

  private readBody(req: http.IncomingMessage): Promise<unknown> {
    return new Promise((resolve) => {
      if (req.method === 'GET') {
        resolve({})
        return
      }
      let data = ''
      req.on('data', (chunk) => {
        data += chunk
      })
      req.on('end', () => {
        if (!data) {
          resolve({})
          return
        }
        try {
          resolve(JSON.parse(data))
        } catch {
          resolve({})
        }
      })
    })
  }
}
