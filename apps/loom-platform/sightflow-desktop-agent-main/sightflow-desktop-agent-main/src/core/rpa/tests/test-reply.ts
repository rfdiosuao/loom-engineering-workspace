import { RPADevice } from '../../rpa-device'

export async function runReplyTest() {
  console.log('[Test] Running reply atom...')
  const device = new RPADevice()
  device.setAppType('wechat')

  try {
    await device.sendMessage('杩欐槸涓€鏉¤嚜鍔ㄥ寲鏍稿績娴嬭瘯瀹夊叏鍥炲')
    console.log('鉁?Reply sent successfully')
  } catch (error) {
    console.error('鉂?Reply failed', error)
  }
}
