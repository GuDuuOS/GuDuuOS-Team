const MAX_INPUT_LENGTH = 2048
const MAX_WELL_KNOWN_BYTES = 64 * 1024
const MAX_MATRIX_VERSIONS_BYTES = 64 * 1024
const MAX_INSTANCE_CONFIG_BYTES = 2 * 1024 * 1024
const MAX_LOGO_DATA_URL_LENGTH = 1536 * 1024
const FETCH_TIMEOUT_MS = 10000

function isLoopback(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
}

/**
 * 把用户输入或服务器下发的 URL 收口为可用的 HTTPS 基址。
 * 用户名、密码、query 与 hash 一律拒绝；开发态仅例外允许本机 HTTP。
 */
export function normalizeDesktopServerUrl(
  value,
  { allowInsecureLoopback = false, requireOriginOnly = false } = {}
) {
  if (typeof value !== 'string') throw new Error('服务器地址无效')
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > MAX_INPUT_LENGTH) throw new Error('服务器地址无效')

  const withScheme = /^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
  let candidate
  try {
    candidate = new URL(withScheme)
  } catch {
    throw new Error('请输入正确的服务器域名')
  }

  if (candidate.username || candidate.password || candidate.search || candidate.hash) {
    throw new Error('服务器地址不能包含账号、参数或锚点')
  }
  const localHttp = allowInsecureLoopback && candidate.protocol === 'http:' && isLoopback(candidate.hostname)
  if (candidate.protocol !== 'https:' && !localHttp) {
    throw new Error('服务器必须使用 HTTPS')
  }
  if (!candidate.hostname) throw new Error('请输入正确的服务器域名')
  if (requireOriginOnly && candidate.pathname !== '/' && candidate.pathname !== '') {
    throw new Error('请只输入域名，不要附加路径')
  }

  candidate.pathname = requireOriginOnly ? '/' : candidate.pathname.replace(/\/+$/, '') || '/'
  return (requireOriginOnly ? candidate.origin : candidate.toString()).replace(/\/$/, '')
}

function boundedString(value, maxLength, fallback = '') {
  return typeof value === 'string' && value.length <= maxLength ? value : fallback
}

function sanitizeInstanceConfig(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('该服务器缺少 GuDuu OS 客户端配置')
  const brand = payload.brand && typeof payload.brand === 'object' ? payload.brand : {}
  const logo = boundedString(brand.logo_data_url, MAX_LOGO_DATA_URL_LENGTH)
  if (logo && !/^data:image\/(?:png|jpe?g|webp);base64,/i.test(logo)) {
    throw new Error('OEM Logo 格式无效')
  }
  return {
    setup_completed: Boolean(payload.setup_completed),
    brand: {
      product_name: boundedString(brand.product_name, 80, 'GuDuu OS') || 'GuDuu OS',
      company_name: boundedString(brand.company_name, 160),
      logo_data_url: logo
    }
  }
}

async function fetchJson(fetchImpl, url, maxBytes) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetchImpl(url, {
      method: 'GET',
      cache: 'no-store',
      redirect: 'follow',
      signal: controller.signal
    })
    if (!response?.ok) {
      const error = new Error(`服务器返回异常（${response?.status || 0}）`)
      error.status = Number(response?.status || 0)
      throw error
    }
    // 即使 fetch 自动跟随重定向，最终地址也不得降级为明文 HTTP。
    normalizeDesktopServerUrl(response.url || url)
    const announcedLength = Number(response.headers?.get?.('content-length') || 0)
    if (announcedLength > maxBytes) throw new Error('服务器配置过大')

    let text
    if (response.body?.getReader) {
      const reader = response.body.getReader()
      const chunks = []
      let total = 0
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        total += value.byteLength
        if (total > maxBytes) {
          await reader.cancel().catch(() => undefined)
          throw new Error('服务器配置过大')
        }
        chunks.push(Buffer.from(value))
      }
      text = Buffer.concat(chunks, total).toString('utf8')
    } else {
      // 仅供老 Response 实现和测试替身；真实 Electron net.fetch 走上面的流式限制。
      text = await response.text()
      if (Buffer.byteLength(text, 'utf8') > maxBytes) throw new Error('服务器配置过大')
    }
    try {
      return JSON.parse(text)
    } catch {
      throw new Error('服务器返回了无效配置')
    }
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error('连接服务器超时')
    if (error instanceof TypeError) throw new Error('无法连接该服务器')
    throw error
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 按 Matrix 标准发现 homeserver，验证 Matrix 版本端点，再读取
 * GuDuu OS 公开实例配置。整个过程不传递账号、密码或 access token。
 */
export async function discoverDesktopServer(
  input,
  { fetchImpl, allowInsecureLoopback = false } = {}
) {
  if (typeof fetchImpl !== 'function') throw new Error('服务器发现能力不可用')
  const entryUrl = normalizeDesktopServerUrl(input, {
    allowInsecureLoopback,
    requireOriginOnly: true
  })
  const wellKnown = await fetchJson(
    fetchImpl,
    `${entryUrl}/.well-known/matrix/client`,
    MAX_WELL_KNOWN_BYTES
  )
  const homeserverUrl = normalizeDesktopServerUrl(wellKnown?.['m.homeserver']?.base_url, {
    allowInsecureLoopback
  })

  const versions = await fetchJson(
    fetchImpl,
    `${homeserverUrl}/_matrix/client/versions`,
    MAX_MATRIX_VERSIONS_BYTES
  )
  if (!Array.isArray(versions?.versions) || !versions.versions.length) {
    throw new Error('该域名没有连接到可用的 Matrix 服务')
  }

  let instanceConfig
  try {
    instanceConfig = sanitizeInstanceConfig(await fetchJson(
      fetchImpl,
      `${homeserverUrl}/cosmac/instance/config`,
      MAX_INSTANCE_CONFIG_BYTES
    ))
  } catch (error) {
    // 当前线上及旧 OEM 节点可能尚未部署公开品牌端点。只对“明确 404”
    // 执行兼容探测；超时、过大响应、非 HTTPS 等安全错误必须继续失败。
    if (error?.status !== 404) throw error
    const legacyMarker = await fetchJson(
      fetchImpl,
      `${homeserverUrl}/cosmac/auth/config`,
      MAX_WELL_KNOWN_BYTES
    )
    if (typeof legacyMarker?.turnstile !== 'boolean') {
      throw new Error('该 Matrix 服务器不是受支持的 GuDuu OS 节点')
    }
    instanceConfig = sanitizeInstanceConfig({
      setup_completed: true,
      brand: { product_name: 'GuDuu OS', company_name: '', logo_data_url: '' }
    })
  }
  return Object.freeze({ entryUrl, homeserverUrl, ...instanceConfig })
}
