/**
 * Matrix 会话的跨端持久化适配层。
 *
 * Web 为兼容现有部署继续使用原有 localStorage 键；Electron 则通过最小 preload 桥把
 * 完整会话交给 main 进程 safeStorage。业务层只调用本文件，不感知具体平台存储实现。
 */

export interface StoredSession {
  baseUrl: string
  accessToken: string
  userId: string
  deviceId?: string
  name?: string
}

export interface SessionVault {
  version: 1
  activeUserId: string
  accounts: StoredSession[]
}

const LEGACY_SESSION_KEY = 'cosmac.session'
const LEGACY_ACCOUNTS_KEY = 'guduu.accounts.v1'
const DESKTOP_ACTIVE_META_KEY = 'guduu.desktop.active-user.v1'
const DESKTOP_ACCOUNTS_META_KEY = 'guduu.desktop.accounts-meta.v1'
const MAX_ACCOUNT_COUNT = 20

let cachedVault: SessionVault | null = null
let loadingVault: Promise<SessionVault> | null = null

/** 创建一个没有登录账号的标准仓库。 */
function emptyVault(): SessionVault {
  return { version: 1, activeUserId: '', accounts: [] }
}

/**
 * 把未知对象收敛成受支持的单账号会话；非法记录返回 null。
 * renderer 仍做一次形状校验，让 Web 存储被手改时不会把脏数据传入 Matrix SDK。
 */
function normalizeSession(value: unknown): StoredSession | null {
  const record = value as Partial<StoredSession> | null
  if (
    !record ||
    typeof record.baseUrl !== 'string' || !record.baseUrl ||
    typeof record.accessToken !== 'string' || !record.accessToken ||
    typeof record.userId !== 'string' || !record.userId
  ) return null

  return {
    baseUrl: record.baseUrl,
    accessToken: record.accessToken,
    userId: record.userId,
    ...(typeof record.deviceId === 'string' && record.deviceId
      ? { deviceId: record.deviceId }
      : {}),
    ...(typeof record.name === 'string' && record.name ? { name: record.name } : {}),
  }
}

/** 校验、去重并复制一份完整仓库，拒绝悬空的活动账号。 */
function normalizeVault(value: unknown): SessionVault {
  const candidate = value as Partial<SessionVault> | null
  if (!candidate || candidate.version !== 1 || !Array.isArray(candidate.accounts)) {
    throw new Error('本机会话数据格式无效')
  }

  const byUserId = new Map<string, StoredSession>()
  for (const raw of candidate.accounts.slice(0, MAX_ACCOUNT_COUNT)) {
    const account = normalizeSession(raw)
    if (!account) throw new Error('本机会话账号格式无效')
    byUserId.set(account.userId, account)
  }
  const activeUserId = typeof candidate.activeUserId === 'string' ? candidate.activeUserId : ''
  if (activeUserId && !byUserId.has(activeUserId)) {
    throw new Error('本机活动会话不存在')
  }
  return { version: 1, activeUserId, accounts: [...byUserId.values()] }
}

/** 安全解析 localStorage JSON；浏览器禁用存储或数据损坏时返回回退值。 */
function parseLocalJson(key: string, fallback: unknown): unknown {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

/**
 * 从历史 Web 格式合并当前会话与多账号列表。
 * 当前会话优先覆盖同账号 token，但保留账号列表里已有的显示名。
 */
function readLegacyVault(): SessionVault {
  const accountsRaw = parseLocalJson(LEGACY_ACCOUNTS_KEY, [])
  const current = normalizeSession(parseLocalJson(LEGACY_SESSION_KEY, null))
  const byUserId = new Map<string, StoredSession>()

  if (Array.isArray(accountsRaw)) {
    for (const raw of accountsRaw.slice(0, MAX_ACCOUNT_COUNT)) {
      const account = normalizeSession(raw)
      if (account) byUserId.set(account.userId, account)
    }
  }
  if (current) {
    const previous = byUserId.get(current.userId)
    byUserId.set(current.userId, { ...current, name: previous?.name || current.name })
  }
  return {
    version: 1,
    activeUserId: current?.userId || '',
    accounts: [...byUserId.values()],
  }
}

/** Electron 是否提供了本项目定义的安全凭据桥。 */
function desktopCredentialBridge() {
  return window.guduuDesktop?.credentials || null
}

/**
 * 同步桌面端公开元数据，供路由首次渲染和账号菜单立即显示。
 * 这里只保存 userId/name，不允许写入 token、deviceId 或 homeserver 地址。
 */
function writeDesktopMetadata(vault: SessionVault): void {
  if (!desktopCredentialBridge()) return
  try {
    if (vault.activeUserId) localStorage.setItem(DESKTOP_ACTIVE_META_KEY, vault.activeUserId)
    else localStorage.removeItem(DESKTOP_ACTIVE_META_KEY)
    localStorage.setItem(
      DESKTOP_ACCOUNTS_META_KEY,
      JSON.stringify(vault.accounts.map((account) => ({
        userId: account.userId,
        name: account.name || account.userId,
      }))),
    )
  } catch {
    // 公开元数据写失败不影响安全仓库；下一次异步加载仍能从 safeStorage 恢复。
  }
}

/** 只有 Electron 安全写入成功后才删除历史明文，保证迁移失败仍可重试。 */
function clearLegacyDesktopSecrets(): void {
  try {
    localStorage.removeItem(LEGACY_SESSION_KEY)
    localStorage.removeItem(LEGACY_ACCOUNTS_KEY)
  } catch {
    // localStorage 不可用时本来就没有可迁移的持久明文，安全仓库仍可正常工作。
  }
}

/** 把完整仓库持久化到当前平台，并在成功后刷新内存缓存。 */
async function persistVault(value: SessionVault): Promise<SessionVault> {
  const vault = normalizeVault(value)
  const bridge = desktopCredentialBridge()
  if (bridge) {
    await bridge.write(vault)
    cachedVault = vault
    writeDesktopMetadata(vault)
    clearLegacyDesktopSecrets()
    return vault
  }

  const active = vault.accounts.find((account) => account.userId === vault.activeUserId)
  try {
    if (active) localStorage.setItem(LEGACY_SESSION_KEY, JSON.stringify(active))
    else localStorage.removeItem(LEGACY_SESSION_KEY)
    localStorage.setItem(LEGACY_ACCOUNTS_KEY, JSON.stringify(vault.accounts))
  } catch {
    throw new Error('浏览器会话存储不可用，请检查隐私设置')
  }
  cachedVault = vault
  return vault
}

/**
 * 首次读取当前平台仓库。
 * Electron 若尚无密文，会先安全写入历史会话，写成功后才擦除 localStorage 明文。
 */
export async function loadSessionVault(): Promise<SessionVault> {
  if (cachedVault) return cachedVault
  if (loadingVault) return loadingVault

  loadingVault = (async () => {
    const bridge = desktopCredentialBridge()
    if (!bridge) {
      cachedVault = readLegacyVault()
      return cachedVault
    }

    const encryptedVault = await bridge.read()
    if (encryptedVault) {
      cachedVault = normalizeVault(encryptedVault)
      writeDesktopMetadata(cachedVault)
      clearLegacyDesktopSecrets()
      return cachedVault
    }

    const legacyVault = readLegacyVault()
    if (legacyVault.accounts.length) return persistVault(legacyVault)
    cachedVault = emptyVault()
    writeDesktopMetadata(cachedVault)
    clearLegacyDesktopSecrets()
    return cachedVault
  })()

  try {
    return await loadingVault
  } finally {
    loadingVault = null
  }
}

/** 保存登录结果、加入多账号列表，并把该账号设为当前活动账号。 */
export async function saveAccountSession(session: StoredSession, name?: string): Promise<void> {
  const normalized = normalizeSession(session)
  if (!normalized) throw new Error('登录会话格式无效')
  const vault = await loadSessionVault()
  const previous = vault.accounts.find((account) => account.userId === normalized.userId)
  const account = {
    ...normalized,
    name: name || previous?.name || normalized.name || normalized.userId,
  }
  const accounts = vault.accounts.filter((item) => item.userId !== normalized.userId)
  accounts.push(account)
  if (accounts.length > MAX_ACCOUNT_COUNT) {
    // 新登录账号必须保留；超过上限时从最旧的账号开始淘汰，避免主进程拒绝整次保存。
    accounts.splice(0, accounts.length - MAX_ACCOUNT_COUNT)
  }

  const next = normalizeVault({ version: 1, activeUserId: account.userId, accounts })
  if (JSON.stringify(next) === JSON.stringify(vault)) return
  await persistVault(next)
}

/** 返回当前活动会话；没有登录时返回 null。 */
export async function getActiveAccountSession(): Promise<StoredSession | null> {
  const vault = await loadSessionVault()
  return vault.accounts.find((account) => account.userId === vault.activeUserId) || null
}

/** 选择已保存账号并返回对应会话；不存在时返回 null。 */
export async function selectAccountSession(userId: string): Promise<StoredSession | null> {
  const vault = await loadSessionVault()
  const account = vault.accounts.find((item) => item.userId === userId)
  if (!account) return null
  if (vault.activeUserId !== userId) {
    await persistVault({ ...vault, activeUserId: userId })
  }
  return account
}

/** 从本机移除账号；若它是活动账号，同时清空活动指针。 */
export async function removeAccountSession(userId: string): Promise<void> {
  const vault = await loadSessionVault()
  const accounts = vault.accounts.filter((account) => account.userId !== userId)
  if (accounts.length === vault.accounts.length && vault.activeUserId !== userId) return
  await persistVault({
    version: 1,
    activeUserId: vault.activeUserId === userId ? '' : vault.activeUserId,
    accounts,
  })
}

/**
 * 忘记本机全部会话。
 * Electron 直接删除密文文件，因此钥匙串暂不可用时仍能完成安全退出；Web 清空旧键。
 */
export async function clearAllAccountSessions(): Promise<void> {
  const bridge = desktopCredentialBridge()
  if (bridge) {
    await bridge.clear()
    cachedVault = emptyVault()
    writeDesktopMetadata(cachedVault)
    clearLegacyDesktopSecrets()
    return
  }
  await persistVault(emptyVault())
}

/** 路由守卫使用的可信异步用户 ID；Electron 必须先以安全仓库为准。 */
export async function storedCurrentUserId(): Promise<string> {
  return (await loadSessionVault()).activeUserId
}

/**
 * 已加载后的同步用户 ID，供业务请求头和 UI 使用。
 * 冷启动前的桌面元数据只负责减少闪烁，真正放行路由仍走 storedCurrentUserId。
 */
export function cachedCurrentUserId(): string {
  if (cachedVault) return cachedVault.activeUserId
  if (desktopCredentialBridge()) {
    try { return localStorage.getItem(DESKTOP_ACTIVE_META_KEY) || '' } catch { return '' }
  }
  return readLegacyVault().activeUserId
}

/** 返回不含任何 token/deviceId/baseUrl 的账号菜单摘要。 */
export function cachedAccountSummaries(): { userId: string; name: string }[] {
  if (cachedVault) {
    return cachedVault.accounts.map((account) => ({
      userId: account.userId,
      name: account.name || account.userId,
    }))
  }
  if (desktopCredentialBridge()) {
    const metadata = parseLocalJson(DESKTOP_ACCOUNTS_META_KEY, [])
    if (!Array.isArray(metadata)) return []
    return metadata.flatMap((item: any) => (
      typeof item?.userId === 'string' && item.userId
        ? [{ userId: item.userId, name: typeof item.name === 'string' ? item.name : item.userId }]
        : []
    ))
  }
  return readLegacyVault().accounts.map((account) => ({
    userId: account.userId,
    name: account.name || account.userId,
  }))
}

/** 当前活动会话的内存副本；token 只在页面运行期间存在，不写桌面 localStorage。 */
export function cachedActiveAccountSession(): StoredSession | null {
  if (!cachedVault) return null
  return cachedVault.accounts.find((account) => account.userId === cachedVault?.activeUserId) || null
}
