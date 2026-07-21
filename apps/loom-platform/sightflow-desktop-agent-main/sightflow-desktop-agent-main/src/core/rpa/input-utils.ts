import { clipboard } from 'electron'
import { AppType } from './types'
import { getWindowInfo } from './window-utils'
import { getInputAreaFromCache } from './vision-utils'
import { delay, randomDelayIn, getRobot } from './util'

const IS_WINDOWS = process.platform === 'win32'
const IS_MAC = process.platform === 'darwin'

async function humanLikeMove(
  targetX: number,
  targetY: number,
  options: {
    minSteps?: number
    maxSteps?: number
    baseDelay?: number
  } = {}
): Promise<void> {
  const robot = getRobot()
  if (!robot) return

  const { minSteps = 5, maxSteps = 15, baseDelay = 2 } = options
  const startPos = robot.getMousePos()
  const dx = targetX - startPos.x
  const dy = targetY - startPos.y
  const distance = Math.sqrt(dx * dx + dy * dy)

  if (distance < 1) {
    robot.moveMouse(Math.round(targetX), Math.round(targetY))
    return
  }

  const steps = Math.min(
    maxSteps,
    Math.max(minSteps, Math.floor(distance / 40) + Math.floor(Math.random() * 3))
  )
  const ctrl1X = startPos.x + dx * Math.random() * 0.5 + (Math.random() - 0.5) * distance * 0.2
  const ctrl1Y = startPos.y + dy * Math.random() * 0.5 + (Math.random() - 0.5) * distance * 0.2
  const ctrl2X = startPos.x + dx * (0.5 + Math.random() * 0.5) + (Math.random() - 0.5) * distance * 0.2
  const ctrl2Y = startPos.y + dy * (0.5 + Math.random() * 0.5) + (Math.random() - 0.5) * distance * 0.2

  for (let i = 1; i <= steps; i++) {
    const easeT = (i / steps) * (2 - i / steps)
    const mt = 1 - easeT
    const mt2 = mt * mt
    const mt3 = mt2 * mt
    const easeT2 = easeT * easeT
    const easeT3 = easeT2 * easeT
    const x = mt3 * startPos.x + 3 * mt2 * easeT * ctrl1X + 3 * mt * easeT2 * ctrl2X + easeT3 * targetX
    const y = mt3 * startPos.y + 3 * mt2 * easeT * ctrl1Y + 3 * mt * easeT2 * ctrl2Y + easeT3 * targetY
    const jitterX = i === steps ? 0 : (Math.random() - 0.5) * 2
    const jitterY = i === steps ? 0 : (Math.random() - 0.5) * 2

    robot.moveMouse(Math.round(x + jitterX), Math.round(y + jitterY))

    let stepDelay = baseDelay + Math.random() * 2
    if (i > steps * 0.8) stepDelay += 2
    await delay(stepDelay)
  }
}

export async function humanLikeClick(button: 'left' | 'right' = 'left'): Promise<void> {
  const robot = getRobot()
  if (!robot) return

  try {
    robot.mouseToggle('down', button)
    await delay(Math.round(120 + Math.random() * 100))
    robot.mouseToggle('up', button)
    await delay(Math.round(50 + Math.random() * 100))
  } catch (error) {
    console.error('[humanLikeClick] failed:', error)
    robot.mouseClick(button)
  }
}

const getWeChatInputPosition = (bounds: any, scaleFactor: number) => {
  if (IS_WINDOWS) {
    const baseInputX = Math.round((bounds.x + bounds.width - 150) * scaleFactor)
    const baseInputY = Math.round((bounds.y + bounds.height - 40) * scaleFactor)
    return { inputX: baseInputX + (Math.random() - 0.5) * 20, inputY: baseInputY - Math.random() * 5 }
  }
  const baseInputX = bounds.x + bounds.width - 250
  const baseInputY = bounds.y + bounds.height - 20
  return { inputX: baseInputX + (Math.random() - 0.5) * 20, inputY: baseInputY - Math.random() * 5 }
}

export type ReplySubmitMode = 'keyboard' | 'mouse'

interface SubmitTargetRect {
  x: number
  y: number
  width: number
  height: number
}

interface SendReplyOptions {
  submitMode?: ReplySubmitMode
  submitTarget?: SubmitTargetRect
}

export function defaultSubmitMode(appType: AppType): ReplySubmitMode {
  return appType === 'generic' ? 'mouse' : 'keyboard'
}

function estimateMouseSubmitPoint(rect: SubmitTargetRect): [number, number] {
  const marginX = Math.max(24, Math.min(64, rect.width * 0.12))
  const marginY = Math.max(14, Math.min(30, rect.height * 0.25))
  return [
    Math.round(rect.x + rect.width - marginX),
    Math.round(rect.y + rect.height - marginY)
  ]
}

export async function sendReplyByCoordsAction(
  x: number,
  y: number,
  text: string,
  options: SendReplyOptions = {}
): Promise<boolean> {
  const robot = getRobot()
  if (!robot) {
    console.error('[sendReplyByCoordsAction] RobotJS missing')
    return false
  }

  try {
    await humanLikeMove(x, y)
    await randomDelayIn(100, 200)
    robot.mouseClick('left')
    await randomDelayIn(200, 300)

    clipboard.writeText(text)
    await randomDelayIn(50, 100)

    robot.keyTap('v', [IS_MAC ? 'command' : 'control'])
    await randomDelayIn(300, 500)

    if (options.submitMode === 'mouse') {
      if (!options.submitTarget) {
        console.warn('[sendReplyByCoordsAction] mouse submit target missing; fallback to keyboard submit')
      } else {
        const [submitX, submitY] = estimateMouseSubmitPoint(options.submitTarget)
        console.log('[sendReplyByCoordsAction] mouse submit', { submitX, submitY })
        await humanLikeMove(submitX, submitY)
        await randomDelayIn(80, 140)
        robot.mouseClick('left')
        await randomDelayIn(150, 250)
        return true
      }
    }

    robot.keyTap('enter')

    if (IS_WINDOWS) {
      robot.keyTap('enter', ['control'])
      await randomDelayIn(40, 60)
      robot.keyTap('backspace')
    } else {
      robot.keyTap('enter', ['command'])
      await randomDelayIn(20, 40)
      robot.keyToggle('command', 'up')
      await randomDelayIn(20, 40)
      robot.keyTap('backspace')
    }

    return true
  } catch (err: any) {
    console.error('[sendReplyByCoordsAction] failed:', err)
    return false
  }
}

export async function sendReplyAction(appType: AppType, text: string): Promise<boolean> {
  const windowInfo = await getWindowInfo(appType, false)
  if (!windowInfo?.bounds) {
    console.error('[sendReplyAction] missing window info')
    return false
  }

  let inputX: number | undefined
  let inputY: number | undefined
  const inputArea = getInputAreaFromCache(appType)

  if (inputArea) {
    inputX = inputArea.coordinates[0] + (Math.random() - 0.5) * 10
    inputY = inputArea.coordinates[1] + (Math.random() - 0.5) * 4
    console.log(`[sendReplyAction] cached input position (${inputX}, ${inputY})`)
  }

  if (inputX === undefined || inputY === undefined) {
    console.log('[sendReplyAction] using fallback input position')
    const pos = getWeChatInputPosition(windowInfo.bounds, windowInfo.scaleFactor || 1)
    inputX = pos.inputX
    inputY = pos.inputY
  }

  const submitMode = defaultSubmitMode(appType)
  return sendReplyByCoordsAction(inputX, inputY, text, {
    submitMode: submitMode === 'mouse' && inputArea?.rect ? 'mouse' : 'keyboard',
    submitTarget: inputArea?.rect
  })
}

export type ClickPolicy = 'single' | 'double'

export function defaultClickPolicy(appType: AppType): ClickPolicy {
  return appType === 'wechat' ? 'double' : 'single'
}

export async function activeUnreadByClickAction(
  coordinates: [number, number],
  appType: AppType,
  clickPolicy?: ClickPolicy
): Promise<void> {
  const robot = getRobot()
  if (!robot) return

  const [centerX, centerY] = coordinates
  const policy: ClickPolicy = clickPolicy ?? defaultClickPolicy(appType)
  const isSingleClick = policy === 'single'

  console.log(`[activeUnreadByClick] ${isSingleClick ? 'single' : 'double'} click`, {
    centerX,
    centerY,
    appType,
    policy
  })

  await humanLikeMove(centerX, centerY)
  await randomDelayIn(150, 250)
  robot.mouseClick('left')

  if (!isSingleClick) {
    await randomDelayIn(40, 60)
    robot.mouseClick('left')
  }
}

export async function clickUnreadContactAction(
  coordinates: [number, number]
): Promise<void> {
  const robot = getRobot()
  if (!robot) return

  const [firstContactX, firstContactY] = coordinates
  console.log('[clickUnreadContact] first unread contact', { firstContactX, firstContactY })

  await humanLikeMove(firstContactX, firstContactY)
  await randomDelayIn(150, 250)
  robot.mouseClick('left')
  console.log('[clickUnreadContact] clicked first unread contact')
  await randomDelayIn(150, 250)
}
