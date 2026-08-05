import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

import {
  createDesktopNotificationService,
  validateDesktopNotificationPayload
} from '../desktop-notifications.mjs'

/** 构造一个可观测点击、关闭与展示次数的假系统通知。 */
function fakeNotification() {
  const notification = new EventEmitter()
  notification.showCount = 0
  notification.closeCount = 0
  notification.show = () => {
    notification.showCount += 1
  }
  notification.close = () => {
    notification.closeCount += 1
    notification.emit('close')
  }
  return notification
}

/** 构造一个假窗口，便于验证通知点击会恢复并聚焦主窗口。 */
function fakeWindow({ focused = false, minimized = false } = {}) {
  return {
    focused,
    minimized,
    restoreCount: 0,
    showCount: 0,
    focusCount: 0,
    isDestroyed: () => false,
    isFocused() {
      return this.focused
    },
    isMinimized() {
      return this.minimized
    },
    restore() {
      this.restoreCount += 1
      this.minimized = false
    },
    show() {
      this.showCount += 1
    },
    focus() {
      this.focusCount += 1
      this.focused = true
    }
  }
}

test('桌面通知只接受长度受限的 title/body', () => {
  assert.deepEqual(
    validateDesktopNotificationPayload({ title: '  新私信 ', body: ' 安其发来了消息 ' }),
    { title: '新私信', body: '安其发来了消息' }
  )
  assert.throws(
    () => validateDesktopNotificationPayload({ title: '新私信', body: '消息', url: 'file:///tmp/a' }),
    /字段无效/
  )
  assert.throws(
    () => validateDesktopNotificationPayload({ title: 'x'.repeat(81), body: '消息' }),
    /标题无效/
  )
  assert.throws(
    () => validateDesktopNotificationPayload({ title: '新私信', body: 'x'.repeat(281) }),
    /正文无效/
  )
})

test('主窗口已聚焦时抑制系统通知', () => {
  let created = 0
  const service = createDesktopNotificationService({
    isSupported: () => true,
    createNotification: () => {
      created += 1
      return fakeNotification()
    },
    getMainWindow: () => fakeWindow({ focused: true })
  })

  assert.equal(service.show({ title: '新私信', body: '有人联系你' }), 'suppressed')
  assert.equal(created, 0)
})

test('后台通知点击后恢复并聚焦窗口', () => {
  const window = fakeWindow({ minimized: true })
  const notification = fakeNotification()
  const service = createDesktopNotificationService({
    isSupported: () => true,
    createNotification: () => notification,
    getMainWindow: () => window,
    now: () => 10_000
  })

  assert.equal(service.show({ title: '新私信', body: '有人联系你' }), 'shown')
  assert.equal(notification.showCount, 1)
  notification.emit('click')
  assert.equal(window.restoreCount, 1)
  assert.equal(window.showCount, 1)
  assert.equal(window.focusCount, 1)
  assert.equal(notification.closeCount, 1)
})

test('短时间内重复请求会被 main 进程限流', () => {
  let currentTime = 20_000
  let created = 0
  const service = createDesktopNotificationService({
    isSupported: () => true,
    createNotification: () => {
      created += 1
      return fakeNotification()
    },
    getMainWindow: () => fakeWindow(),
    now: () => currentTime
  })

  assert.equal(service.show({ title: '私信 1', body: '第一条' }), 'shown')
  currentTime += 500
  assert.equal(service.show({ title: '私信 2', body: '第二条' }), 'suppressed')
  assert.equal(created, 1)
})
