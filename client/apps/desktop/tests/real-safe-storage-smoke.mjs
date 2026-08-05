import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { app, safeStorage } from 'electron'

import { createSecureSessionStore } from '../secure-session-store.mjs'

// 该脚本用真实 Electron/系统钥匙串做本机冒烟测试，不创建窗口，也不连接任何服务器。
const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'guduu-real-safe-storage-'))
app.setPath('userData', tempRoot)

try {
  await app.whenReady()
  const store = createSecureSessionStore({ safeStorage, userDataPath: tempRoot })
  const vault = {
    version: 1,
    activeUserId: '@smoke:guduu.local',
    accounts: [{
      baseUrl: 'https://dev-hs.guduu.co',
      accessToken: 'smoke-token-never-sent',
      userId: '@smoke:guduu.local',
      deviceId: 'SMOKE',
    }],
  }
  await store.write(vault)
  assert.deepEqual(await store.read(), vault)
  await store.clear()
  assert.equal(await store.read(), null)
  process.stdout.write('真实 Electron safeStorage 冒烟测试通过。\n')
} finally {
  await rm(tempRoot, { recursive: true, force: true })
  app.quit()
}
