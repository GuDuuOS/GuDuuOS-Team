import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

const STORE_FILE_NAME = 'matrix-sessions.v1.bin'
const MAX_ACCOUNT_COUNT = 20
const MAX_PLAINTEXT_BYTES = 256 * 1024
const MAX_CIPHERTEXT_BYTES = 512 * 1024

/**
 * 校验一个字符串字段并返回原值。
 * 主进程不信任 renderer 传来的任何对象；长度上限同时防止异常 IPC 占满磁盘或内存。
 */
function assertString(value, label, maxLength, allowEmpty = false) {
  if (typeof value !== 'string' || (!allowEmpty && !value) || value.length > maxLength) {
    throw new Error(`桌面安全会话字段无效：${label}`)
  }
  return value
}

/**
 * 校验并复制 renderer 提交的会话仓库。
 * 返回全新的普通对象，避免保留跨进程对象原型，也确保写盘内容只有协议允许的字段。
 */
export function validateSessionVault(value) {
  if (!value || typeof value !== 'object' || value.version !== 1) {
    throw new Error('桌面安全会话版本无效')
  }
  if (!Array.isArray(value.accounts) || value.accounts.length > MAX_ACCOUNT_COUNT) {
    throw new Error('桌面安全会话账号数量无效')
  }

  const seen = new Set()
  const accounts = value.accounts.map((account, index) => {
    if (!account || typeof account !== 'object') {
      throw new Error(`桌面安全会话账号无效：${index}`)
    }
    const userId = assertString(account.userId, `accounts[${index}].userId`, 512)
    if (seen.has(userId)) throw new Error('桌面安全会话包含重复账号')
    seen.add(userId)
    return {
      baseUrl: assertString(account.baseUrl, `accounts[${index}].baseUrl`, 2048),
      accessToken: assertString(account.accessToken, `accounts[${index}].accessToken`, 16384),
      userId,
      ...(account.deviceId
        ? { deviceId: assertString(account.deviceId, `accounts[${index}].deviceId`, 1024) }
        : {}),
      ...(account.name
        ? { name: assertString(account.name, `accounts[${index}].name`, 512) }
        : {})
    }
  })
  const activeUserId = assertString(value.activeUserId, 'activeUserId', 512, true)
  if (activeUserId && !seen.has(activeUserId)) {
    throw new Error('桌面安全会话的活动账号不存在')
  }

  const normalized = { version: 1, activeUserId, accounts }
  if (Buffer.byteLength(JSON.stringify(normalized), 'utf8') > MAX_PLAINTEXT_BYTES) {
    throw new Error('桌面安全会话数据过大')
  }
  return normalized
}

/**
 * 创建桌面安全会话仓库。
 * safeStorage 由 Electron main 注入，测试可以使用假加密器验证原子写入和失败关闭行为。
 */
export function createSecureSessionStore({ safeStorage, userDataPath }) {
  const storePath = path.join(userDataPath, STORE_FILE_NAME)
  let pendingWrite = Promise.resolve()

  /** 确认操作系统加密器可用；不可用时绝不写入明文或弱化格式。 */
  async function requireEncryption() {
    if (!(await safeStorage.isAsyncEncryptionAvailable())) {
      throw new Error('系统安全存储暂不可用，请解锁系统钥匙串后重试')
    }
  }

  /** 把已校验的仓库加密并通过同目录临时文件原子替换。 */
  async function writeNow(vault) {
    const normalized = validateSessionVault(vault)
    const plaintext = JSON.stringify(normalized)
    await requireEncryption()
    const encrypted = await safeStorage.encryptStringAsync(plaintext)
    if (!Buffer.isBuffer(encrypted) || encrypted.length > MAX_CIPHERTEXT_BYTES) {
      throw new Error('系统安全存储返回了无效数据')
    }

    await mkdir(userDataPath, { recursive: true })
    const tempPath = `${storePath}.tmp-${process.pid}`
    await writeFile(tempPath, encrypted, { mode: 0o600 })
    await rename(tempPath, storePath)
  }

  return Object.freeze({
    /**
     * 读取并解密会话；文件不存在表示尚未登录。
     * 密钥轮换时立即用当前密钥重新封装，避免长期保留旧保护等级的密文。
     */
    async read() {
      await pendingWrite
      let fileStat
      try {
        fileStat = await stat(storePath)
      } catch (error) {
        if (error?.code === 'ENOENT') return null
        throw error
      }
      if (!fileStat.isFile() || fileStat.size > MAX_CIPHERTEXT_BYTES) {
        throw new Error('桌面安全会话文件无效')
      }

      await requireEncryption()
      const encrypted = await readFile(storePath)
      const decrypted = await safeStorage.decryptStringAsync(encrypted)
      let parsed
      try {
        parsed = JSON.parse(decrypted.result)
      } catch {
        throw new Error('桌面安全会话已损坏，请重新登录')
      }
      const normalized = validateSessionVault(parsed)
      if (decrypted.shouldReEncrypt) {
        const operation = pendingWrite.then(() => writeNow(normalized))
        pendingWrite = operation.catch(() => undefined)
        await operation
      }
      return normalized
    },

    /**
     * 串行写入完整仓库，保证快速切换账号和退出登录不会互相覆盖。
     * 调用者只有在 Promise 成功后才能删除旧 localStorage 明文。
     */
    async write(vault) {
      const operation = pendingWrite.then(() => writeNow(vault))
      pendingWrite = operation.catch(() => undefined)
      await operation
    },

    /**
     * 删除整个密文仓库。
     * 退出或凭据失效时即便系统钥匙串暂不可用也必须能“忘记此设备”，因此清除不依赖解密。
     */
    async clear() {
      const operation = pendingWrite.then(() => rm(storePath, { force: true }))
      pendingWrite = operation.catch(() => undefined)
      await operation
    },

    /** 仅供测试和诊断确认文件位置；renderer 永远拿不到该路径。 */
    storePath
  })
}
