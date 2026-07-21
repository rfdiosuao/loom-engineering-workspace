import { RPADevice } from '../../rpa-device'
import * as fs from 'fs'

export async function runScreenshotTest() {
  console.log('[Test] Running screenshot atom...')
  const device = new RPADevice()
  device.setAppType('wechat')

  try {
    const screenshotStr = await device.screenshot()
    const base64Data = screenshotStr.replace(/^data:image\/\w+;base64,/, '')
    fs.writeFileSync('test-screenshot.png', Buffer.from(base64Data, 'base64'))
    console.log(`鉁?Screenshot saved to test-screenshot.png (Size: ${screenshotStr.length})`)
  } catch (err: any) {
    console.error('鉂?Screenshot failed', err)
  }
}
