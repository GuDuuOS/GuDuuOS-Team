import assert from 'node:assert/strict'
import test from 'node:test'

import {
  discoverDesktopServer,
  normalizeDesktopServerUrl
} from '../desktop-server-discovery.mjs'

function response(url, payload, { status = 200, contentLength = '' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    url,
    headers: { get: (name) => name.toLowerCase() === 'content-length' ? contentLength : '' },
    text: async () => JSON.stringify(payload)
  }
}

test('裸域名按 well-known 发现 Matrix 与 GuDuu 品牌', async () => {
  const calls = []
  const result = await discoverDesktopServer('chat.example.com', {
    fetchImpl: async (url) => {
      calls.push(url)
      if (url.endsWith('/.well-known/matrix/client')) {
        return response(url, { 'm.homeserver': { base_url: 'https://matrix.example.com/' } })
      }
      if (url.endsWith('/_matrix/client/versions')) {
        return response(url, { versions: ['v1.11'] })
      }
      return response(url, {
        setup_completed: true,
        brand: { product_name: '海外团队', company_name: 'Example Ltd', logo_data_url: '' }
      })
    }
  })

  assert.equal(result.entryUrl, 'https://chat.example.com')
  assert.equal(result.homeserverUrl, 'https://matrix.example.com')
  assert.equal(result.brand.product_name, '海外团队')
  assert.deepEqual(calls, [
    'https://chat.example.com/.well-known/matrix/client',
    'https://matrix.example.com/_matrix/client/versions',
    'https://matrix.example.com/cosmac/instance/config'
  ])
})

test('生产发现拒绝明文、账号、参数和额外路径', () => {
  assert.throws(() => normalizeDesktopServerUrl('http://chat.example.com'), /HTTPS/)
  assert.throws(() => normalizeDesktopServerUrl('https://a:b@chat.example.com'), /账号/)
  assert.throws(() => normalizeDesktopServerUrl('https://chat.example.com?tenant=1'), /参数/)
  assert.throws(
    () => normalizeDesktopServerUrl('https://chat.example.com/path', { requireOriginOnly: true }),
    /域名/
  )
})

test('开发态只对 loopback 例外允许 HTTP', () => {
  assert.equal(
    normalizeDesktopServerUrl('http://127.0.0.1:8008', { allowInsecureLoopback: true }),
    'http://127.0.0.1:8008'
  )
  assert.throws(
    () => normalizeDesktopServerUrl('http://192.168.1.10', { allowInsecureLoopback: true }),
    /HTTPS/
  )
})

test('拒绝不安全的重定向与非 Matrix 服务', async () => {
  await assert.rejects(
    discoverDesktopServer('chat.example.com', {
      fetchImpl: async (url) => response('http://attacker.example/final', {})
    }),
    /HTTPS/
  )
  await assert.rejects(
    discoverDesktopServer('chat.example.com', {
      fetchImpl: async (url) => {
        if (url.includes('.well-known')) {
          return response(url, { 'm.homeserver': { base_url: 'https://matrix.example.com' } })
        }
        return response(url, { versions: [] })
      }
    }),
    /Matrix/
  )
})

test('拒绝过大配置和非图片 Logo', async () => {
  await assert.rejects(
    discoverDesktopServer('chat.example.com', {
      fetchImpl: async (url) => response(url, {}, { contentLength: String(3 * 1024 * 1024) })
    }),
    /过大/
  )

  await assert.rejects(
    discoverDesktopServer('chat.example.com', {
      fetchImpl: async (url) => {
        if (url.includes('.well-known')) {
          return response(url, { 'm.homeserver': { base_url: 'https://matrix.example.com' } })
        }
        if (url.includes('/versions')) return response(url, { versions: ['v1.11'] })
        return response(url, { brand: { logo_data_url: 'javascript:alert(1)' } })
      }
    }),
    /Logo/
  )
})

test('旧 GuDuu 节点品牌端点 404 时经受控兼容探测', async () => {
  const result = await discoverDesktopServer('legacy.example.com', {
    fetchImpl: async (url) => {
      if (url.includes('.well-known')) {
        return response(url, { 'm.homeserver': { base_url: 'https://matrix.example.com' } })
      }
      if (url.includes('/versions')) return response(url, { versions: ['v1.11'] })
      if (url.includes('/instance/config')) return response(url, {}, { status: 404 })
      return response(url, { turnstile: false, turnstile_site_key: '' })
    }
  })
  assert.equal(result.brand.product_name, 'GuDuu OS')
  assert.equal(result.setup_completed, true)
})

test('品牌端点非 404 错误不降级兼容', async () => {
  await assert.rejects(
    discoverDesktopServer('broken.example.com', {
      fetchImpl: async (url) => {
        if (url.includes('.well-known')) {
          return response(url, { 'm.homeserver': { base_url: 'https://matrix.example.com' } })
        }
        if (url.includes('/versions')) return response(url, { versions: ['v1.11'] })
        return response(url, {}, { status: 503 })
      }
    }),
    /503/
  )
})
