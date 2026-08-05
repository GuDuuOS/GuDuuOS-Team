import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  createSecureSessionStore,
  validateSessionVault
} from '../secure-session-store.mjs'

/** 用简单异或模拟“密文”，测试只验证仓库协议，不冒充操作系统密码学实现。 */
function createFakeSafeStorage(available = true) {
  const transform = (buffer) => Buffer.from(buffer.map((byte) => byte ^ 0xa5))
  return {
    async isAsyncEncryptionAvailable() {
      return available
    },
    async encryptStringAsync(value) {
      return transform(Buffer.from(value, 'utf8'))
    },
    async decryptStringAsync(value) {
      return { result: transform(value).toString('utf8'), shouldReEncrypt: false }
    }
  }
}

const sampleVault = {
  version: 1,
  activeUserId: '@alice:guduu.local',
  accounts: [
    {
      baseUrl: 'https://dev-hs.guduu.co',
      accessToken: 'secret-access-token',
      userId: '@alice:guduu.local',
      deviceId: 'DEVICE1',
      name: 'Alice'
    }
  ]
}

test('安全仓库加密写入并能完整读回', async (t) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'guduu-secure-store-'))
  t.after(() => rm(tempRoot, { recursive: true, force: true }))
  const store = createSecureSessionStore({
    safeStorage: createFakeSafeStorage(),
    userDataPath: tempRoot
  })

  await store.write(sampleVault)
  const raw = await readFile(store.storePath)
  assert.equal(raw.includes(Buffer.from('secret-access-token')), false)
  assert.deepEqual(await store.read(), sampleVault)
})

test('系统加密不可用时拒绝落盘', async (t) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'guduu-secure-store-'))
  t.after(() => rm(tempRoot, { recursive: true, force: true }))
  const store = createSecureSessionStore({
    safeStorage: createFakeSafeStorage(false),
    userDataPath: tempRoot
  })

  await assert.rejects(() => store.write(sampleVault), /系统安全存储暂不可用/)
  await assert.rejects(() => readFile(store.storePath), { code: 'ENOENT' })
})

test('清除密文不依赖系统加密器', async (t) => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'guduu-secure-store-'))
  t.after(() => rm(tempRoot, { recursive: true, force: true }))
  const safeStorage = createFakeSafeStorage()
  const store = createSecureSessionStore({ safeStorage, userDataPath: tempRoot })
  await store.write(sampleVault)
  safeStorage.isAsyncEncryptionAvailable = async () => false

  await store.clear()
  assert.equal(await store.read().catch(() => null), null)
  await assert.rejects(() => readFile(store.storePath), { code: 'ENOENT' })
})

test('会话协议拒绝重复账号与悬空活动账号', () => {
  assert.throws(
    () => validateSessionVault({ ...sampleVault, activeUserId: '@missing:guduu.local' }),
    /活动账号不存在/
  )
  assert.throws(
    () => validateSessionVault({
      ...sampleVault,
      accounts: [sampleVault.accounts[0], sampleVault.accounts[0]]
    }),
    /重复账号/
  )
})
