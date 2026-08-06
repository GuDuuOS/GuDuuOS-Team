import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createDesktopDeepLinkBroker,
  parseDesktopDeepLink
} from '../desktop-deep-links.mjs'

test('工作区邀请深链转成现有 Vue join 路由', () => {
  const spaceId = '!studio:guduu.example'
  assert.equal(
    parseDesktopDeepLink(`guduu://join/${encodeURIComponent(spaceId)}`),
    `/join/${encodeURIComponent(spaceId)}`
  )
})

test('深链拒绝其他协议、主机、参数和路径穿越', () => {
  const encoded = encodeURIComponent('!studio:guduu.example')
  const rejected = [
    `https://join/${encoded}`,
    `guduu://room/${encoded}`,
    `guduu://join/${encoded}?next=https://evil.example`,
    `guduu://join/${encoded}#fragment`,
    `guduu://join///${encoded}`,
    'guduu://join/%2Fetc%2Fpasswd',
    'guduu://join/not-a-space-id',
    `guduu://join/${encodeURIComponent('!bad id:guduu.example')}`
  ]

  for (const candidate of rejected) assert.equal(parseDesktopDeepLink(candidate), null)
})

test('冷启动深链保留到 renderer 完成握手', () => {
  const sent = []
  let focused = 0
  const broker = createDesktopDeepLinkBroker({
    focusMainWindow: () => { focused += 1 },
    sendRoute: (route) => {
      sent.push(route)
      return true
    }
  })
  const expected = `/join/${encodeURIComponent('!cold:guduu.example')}`

  assert.equal(broker.deliver('guduu://join/!cold%3Aguduu.example'), true)
  assert.equal(focused, 1)
  assert.deepEqual(sent, [])
  assert.equal(broker.consumePending(), expected)
  assert.equal(broker.consumePending(), null)
})

test('应用运行中实时交付，renderer 重载后重新排队', () => {
  const sent = []
  const broker = createDesktopDeepLinkBroker({
    focusMainWindow: () => {},
    sendRoute: (route) => {
      sent.push(route)
      return true
    }
  })
  broker.consumePending()

  assert.equal(broker.deliver('guduu://join/!warm%3Aguduu.example'), true)
  assert.deepEqual(sent, [`/join/${encodeURIComponent('!warm:guduu.example')}`])

  broker.markRendererUnavailable()
  assert.equal(broker.deliver('guduu://join/!reload%3Aguduu.example'), true)
  assert.equal(
    broker.consumePending(),
    `/join/${encodeURIComponent('!reload:guduu.example')}`
  )
})

test('非法深链不聚焦窗口也不进入队列', () => {
  let focused = 0
  const broker = createDesktopDeepLinkBroker({
    focusMainWindow: () => { focused += 1 },
    sendRoute: () => true
  })

  assert.equal(broker.deliver('guduu://join/not-valid'), false)
  assert.equal(focused, 0)
  assert.equal(broker.consumePending(), null)
})
