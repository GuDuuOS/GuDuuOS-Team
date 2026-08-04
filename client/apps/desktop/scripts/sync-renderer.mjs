import { cp, mkdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const desktopRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const webDist = path.resolve(desktopRoot, '../..', 'dist')
const rendererTarget = path.join(desktopRoot, 'renderer')

// 每次先整体替换 renderer，防止旧 hash 资源残留并被误打进新的桌面包。
await rm(rendererTarget, { recursive: true, force: true })
await mkdir(rendererTarget, { recursive: true })
await cp(webDist, rendererTarget, { recursive: true })

console.log(`桌面 renderer 已同步：${webDist} -> ${rendererTarget}`)
