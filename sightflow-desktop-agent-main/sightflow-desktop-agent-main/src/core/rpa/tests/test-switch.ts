import { RPADevice } from '../../rpa-device'

export async function runSwitchTest() {
  console.log('[Test] Running visual unread switch test...')
  const device = new RPADevice()
  device.setAppType('wechat')

  const unreadResult = await device.hasUnreadMessage()
  if (!unreadResult.hasUnread || !unreadResult.chatEntranceArea) {
    console.log('[Test] no unread chat entrance found')
    return
  }

  console.log('[Test] unread entrance found; activating chat...')
  await device.activeUnreadByClick(unreadResult.chatEntranceArea.coordinates)

  const contactResult = await device.isChatContactUnread()
  if (!contactResult.isUnread || !contactResult.firstContactCoords) {
    console.log('[Test] no unread contact found after switching')
    return
  }

  console.log('[Test] unread contact found; opening conversation...')
  await device.clickUnreadContact(contactResult.firstContactCoords)
  console.log('[Test] unread contact opened')
}
