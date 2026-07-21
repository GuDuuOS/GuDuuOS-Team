// GuDuu OS 客户端的 Matrix 适配层：用 matrix-js-sdk 连 Synapse 后端。
// 能力：登录（带会话记忆，刷新不用重登）→ 同步 → 列频道 → 读消息（含 cosmac.card 富卡）→ 发消息。

// matrix-js-sdk 里有些代码引用了 node 风格的 global，浏览器里先补个垫片。
;(globalThis as any).global ||= globalThis

import { createClient, type MatrixClient } from 'matrix-js-sdk'

/** 给 UI 用的精简频道结构 */
export interface LiveRoom {
  id: string
  name: string
  /** 频道简介（Matrix m.room.topic），频道头展示用 */
  topic?: string
  /** 是否被收藏（Matrix m.favourite 标签）——收藏的频道在左栏进「收藏」组 */
  fav?: boolean
}

/** 给 UI 用的精简消息结构；card 为 cosmac.card 自定义富卡（可能没有） */
/** 消息附件（图片 / 视频 / 音频 / 文件）：由 m.image / m.video / m.audio / m.file 事件解析而来。 */
export interface MsgAttachment {
  kind: 'image' | 'video' | 'audio' | 'file'
  mxc: string          // 原始 mxc:// 地址——由 AttachmentView 组件带 token 拉成可显示的 blob URL
  name: string         // 文件名（body）
  mimetype?: string
  size?: number        // 字节
  w?: number           // 图片宽（用于占位比例）
  h?: number           // 图片高
}

export interface LiveMsg {
  id: string
  sender: string
  senderName: string
  body: string
  ts: number
  card?: any
  /** 图片/文件附件（有则消息体渲染成缩略图或下载卡片，而非纯文本） */
  attachment?: MsgAttachment
  /** 是否被编辑过（m.replace），显示"已编辑" */
  edited?: boolean
  /** 回复的目标消息（m.in_reply_to）：对方 id/名 + 正文预览 */
  replyToId?: string
  replyToSender?: string
  replyToName?: string
  replyToBody?: string
}

/** 一条消息上某个 emoji 的聚合反应 */
export interface ReactionAgg {
  key: string
  count: number
  mine: boolean
  myId?: string // 我那条 reaction 的 eventId（取消时 redact 用）
}

const SESSION_KEY = 'cosmac.session'
const SYNC_PREPARED_TIMEOUT_MS = 60000  // 大账号初始同步可能很慢;15s 会误杀有效登录

// 单例：整个前端共用一个登录后的 Matrix client
let mx: MatrixClient | null = null

export function getClient(): MatrixClient | null {
  return mx
}

// ── 多账号缓存（"切换账号"用）──────────────────────────────
// SESSION_KEY 存"当前活动会话"(restoreSession 读它)；ACCOUNTS_KEY 存"所有登录过的账号"，
// 供免密切换。切账号 = 把目标账号写进 SESSION_KEY 再整页 reload（复用 restoreSession）。
const ACCOUNTS_KEY = 'guduu.accounts.v1'
interface StoredAccount { baseUrl: string; accessToken: string; userId: string; deviceId?: string; name?: string }

function readAccounts(): StoredAccount[] {
  try { const a = JSON.parse(localStorage.getItem(ACCOUNTS_KEY) || '[]'); return Array.isArray(a) ? a : [] }
  catch { return [] }
}
function writeAccounts(list: StoredAccount[]): void {
  try { localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(list)) } catch { /* 存储不可用忽略 */ }
}

/**
 * 把一个账号会话写进多账号缓存（供以后免密切换）。同 userId 覆盖（去重）。
 * name 缺省时**保留原有缓存里的显示名**，避免复活会话时把名字退化成裸 userId。
 */
function upsertAccount(sess: StoredAccount, name?: string): void {
  const prev = readAccounts()
  const keptName = name || prev.find((a) => a.userId === sess.userId)?.name || sess.userId
  const list = prev.filter((a) => a.userId !== sess.userId)
  list.push({ ...sess, name: keptName })
  writeAccounts(list)
}

function saveSession(baseUrl: string, res: any, name?: string): void {
  const sess = { baseUrl, accessToken: res.access_token, userId: res.user_id, deviceId: res.device_id }
  localStorage.setItem(SESSION_KEY, JSON.stringify(sess))
  upsertAccount(sess, name) // 顺带进多账号缓存
}

/** 已缓存可切换的账号列表（不暴露 token；name 缺省用 userId）。 */
export function listCachedAccounts(): { userId: string; name: string }[] {
  return readAccounts().map((a) => ({ userId: a.userId, name: a.name || a.userId }))
}

/** 当前活动账号 userId（读 SESSION_KEY）。 */
export function currentUserId(): string {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || '{}')?.userId || '' } catch { return '' }
}

/** 切换到某个已缓存账号：把它设为活动会话。返回是否找到（调用方随后整页 reload 让其生效）。 */
export function switchToAccount(userId: string): boolean {
  const a = readAccounts().find((x) => x.userId === userId)
  if (!a) return false
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    baseUrl: a.baseUrl, accessToken: a.accessToken, userId: a.userId, deviceId: a.deviceId,
  }))
  return true
}

/** 从缓存里移除某账号（仅本机缓存，不动服务端会话）。 */
export function removeCachedAccount(userId: string): void {
  writeAccounts(readAccounts().filter((a) => a.userId !== userId))
}

/** 当前登录者的真实资料（个人主页展示用）：id / 显示名 / 头像 http 地址。未登录返回空。 */
export function myProfileInfo(): { userId: string; name: string; avatarUrl: string } {
  const uid = mx?.getUserId() || ''
  if (!uid) return { userId: '', name: '', avatarUrl: '' }
  const u: any = mx?.getUser?.(uid)
  const localpart = uid.replace(/^@/, '').split(':')[0]
  const name = (u?.displayName && u.displayName !== uid) ? u.displayName : localpart
  const mxc = u?.avatarUrl || ''
  return { userId: uid, name, avatarUrl: mxc ? mxcToHttp(mxc, 96) : '' }
}

/* ===== 在线状态（presence）=====
 * 中文四态存 account data（`cosmac.presence`，跨端同步 + 刷新留存）——**不只依赖 Matrix presence**，
 * 因为 Synapse 常把 presence 关掉(性能考虑)，那样 setPresence 不生效、状态点永远绿。所以本地以
 * account data 为准来驱动 UI 指示灯；同时尽力把状态推给 Matrix presence（server 开了就多端/联邦可见）。
 */
const PRESENCE_ACCOUNT_DATA = 'cosmac.presence'
const PRESENCE_MAP: Record<string, 'online' | 'unavailable' | 'offline'> = {
  在线: 'online', 忙碌: 'unavailable', 离开: 'unavailable', 隐身: 'offline',
}

/** 读本人当前选择的在线状态（存在 account data 里；没设过默认「在线」）。 */
export function getMyPresence(): string {
  try {
    const c = (mx as any)?.getAccountData?.(PRESENCE_ACCOUNT_DATA)?.getContent?.()
    return c?.status || '在线'
  } catch { return '在线' }
}

/** 设本人在线状态：写 account data（UI 指示灯的真值来源）+ 尽力推 Matrix presence（禁用则忽略）。 */
export async function setMyPresence(status: string): Promise<void> {
  if (!mx) return
  try { await (mx as any).setAccountData?.(PRESENCE_ACCOUNT_DATA, { status }) } catch { /* 忽略 */ }
  try {
    await (mx as any).setPresence?.({ presence: PRESENCE_MAP[status] || 'online', status_msg: status })
  } catch { /* 服务器禁用 presence 时忽略，不影响本地指示灯 */ }
}

async function startFrom(opts: {
  baseUrl: string
  accessToken: string
  userId: string
  deviceId?: string
}): Promise<string> {
  // 覆盖单例前先停掉旧客户端——否则旧账号的 client 留在内存里用旧 token 持续 /sync 永不停止,
  // 每走一次"添加账号"往返就泄漏一个(双倍流量、线性累积,审查 bug#2)。stopClient 幂等。
  try { mx?.stopClient() } catch { /* 未启动/已停,忽略 */ }
  try { (mx as any)?.removeAllListeners?.() } catch { /* ignore */ }
  mx = createClient({
    baseUrl: opts.baseUrl,
    accessToken: opts.accessToken,
    userId: opts.userId,
    deviceId: opts.deviceId,
  })
  await mx.startClient({ initialSyncLimit: 30 })
  // 等首次同步完成（房间列表加载好）再返回，避免后续逻辑在空列表上重复建房间
  try {
    await new Promise<void>((resolve, reject) => {
      const client = mx as any
      let timer: number | null = null
      const cleanup = () => {
        if (timer !== null) window.clearTimeout(timer)
        client.off?.('sync', handler)
      }
      const fail = (reason: string, errcode?: string) => {
        cleanup()
        const err: any = new Error(reason)
        if (errcode) err.errcode = errcode   // 调用方据此区分"鉴权失效"和"瞬时网络错误"
        reject(err)
      }
      const handler = (state: string, _prev?: string, data?: any) => {
        if (state === 'PREPARED') {
          cleanup()
          resolve()
          return
        }
        if (state === 'STOPPED') {
          fail('Matrix sync STOPPED')
          return
        }
        if (state === 'ERROR') {
          // 只有**确定的鉴权失效**才判死刑;其它 ERROR(网络抖动/5xx)SDK 会自动重试,
          // 继续等 PREPARED 或超时——别把一次网络错当"会话失效"(审查 bug#1)。
          const errcode = data?.error?.errcode || data?.error?.data?.errcode
          if (errcode === 'M_UNKNOWN_TOKEN' || errcode === 'M_USER_DEACTIVATED' || errcode === 'M_USER_LOCKED') {
            fail(`Matrix auth error: ${errcode}`, errcode)
          }
        }
      }
      const currentState = client.getSyncState?.()
      if (currentState === 'PREPARED') {
        cleanup()
        resolve()
      }
      else {
        // ERROR/STOPPED 初始态也交给 handler 统一裁决(SDK 对 ERROR 会重试)
        timer = window.setTimeout(() => fail('Matrix sync timeout'), SYNC_PREPARED_TIMEOUT_MS)
        client.on('sync', handler)
      }
    })
  } catch (e) {
    try { mx?.stopClient() } catch { /* ignore */ }
    mx = null
    throw e
  }
  // —— 运行中的会话失效监听（启动成功后挂上）——
  // 上面那套 M_UNKNOWN_TOKEN 判定只覆盖**启动阶段**;若用户正用着、账号被后台停用(Synapse 会吊销
  // token),此后所有请求静默 401:任务点「开始」没反应、消息发不出,页面却毫无提示(线上实测)。
  // 这里监听两路信号,一旦确认会话死亡就通知 UI(弹提示→回登录页):
  //   ① SDK 的 Session.logged_out——任何请求返回 M_UNKNOWN_TOKEN 时由 js-sdk 主动发出;
  //   ② sync 进入 ERROR 且 errcode 为鉴权失效——双保险(不同版本 SDK 事件行为略有差异)。
  sessionExpiredFired = false
  ;(mx as any).on('Session.logged_out', () => fireSessionExpired('M_UNKNOWN_TOKEN'))
  ;(mx as any).on('sync', (state: string, _prev: string, data: any) => {
    if (state !== 'ERROR') return
    const errcode = data?.error?.errcode || data?.error?.data?.errcode
    if (errcode === 'M_UNKNOWN_TOKEN' || errcode === 'M_USER_DEACTIVATED' || errcode === 'M_USER_LOCKED') fireSessionExpired(errcode)
  })
  return opts.userId
}

// —— 会话失效通知：UI 注册回调,收到后弹提示并送回登录页 ——
let sessionExpiredCb: ((reason: string) => void) | null = null
let sessionExpiredFired = false   // 每次 startFrom 成功后重置;保证一次会话只通知一次
/** 注册「登录已失效」回调（LiveView 挂载时调用；重复调用覆盖前一个）。 */
export function onSessionExpired(cb: (reason: string) => void): void {
  sessionExpiredCb = cb
}
function fireSessionExpired(reason: string): void {
  if (sessionExpiredFired) return
  sessionExpiredFired = true
  // 先取身份信息再清 session（清完就取不到了）:查"是否被别处登录顶掉"要用。
  const uid = currentUserId()
  const dev = String((mx as any)?.getDeviceId?.() || '')
  const base = String((mx as any)?.baseUrl || '').replace(/\/$/, '')
  // 清掉本机记住的死会话:不清的话回登录页后 restoreSession 又拿它自动登录、无限循环。
  try { removeCachedAccount(uid) } catch { /* ignore */ }
  localStorage.removeItem(SESSION_KEY)
  try { mx?.stopClient() } catch { /* ignore */ }
  // token 被吊销可能是「别处登录顶号」(单端在线,后端踢的)——问后端拿明确原因,
  // 换成专属提示"账号已在别处登录";查询失败/不是被踢 → 按原 reason 走笼统文案。
  if (reason === 'M_UNKNOWN_TOKEN' && uid && dev && base) {
    fetch(`${base}/cosmac/session/kicked?user_id=${encodeURIComponent(uid)}&device_id=${encodeURIComponent(dev)}`)
      .then((r) => r.json())
      .then((j) => sessionExpiredCb?.(j?.kicked ? 'KICKED_BY_OTHER_LOGIN' : reason))
      .catch(() => sessionExpiredCb?.(reason))
    return
  }
  sessionExpiredCb?.(reason)
}

// (旧的「登录+立即启动客户端」函数 login()/loginWithEmail() 已删除:它们直连 Synapse、
//  绕过后端的限频/审计/异地检测(登录收口)。现行路径=AuthView 用 loginNoStart/
//  loginWithEmailNoStart(经 cosmac 后端),LiveView 挂载时 restoreSession 统一启动。)

// 注：注册不走 Matrix 原生开放注册（那只能发验证链接、且要服务端开放注册）。
// GuDuu OS 用「自建邮箱验证码」注册：见下方 registerRequestCode/registerVerify（调 cosmac 后端）。


/**
 * 只「认证 + 存会话」，**不启动 Matrix 客户端**（不 startFrom、不首次同步）。
 * 给独立登录页 AuthView 用:认证成功后直接路由进主应用,由 LiveView 挂载时 restoreSession
 * 做**唯一一次**同步——避免"登录页同步一次、进主应用又同步一次"的双同步拖慢。
 */
/** 登录结果:正常成功返回 { ok: true };触发异地二次验证返回 { stepUp: true, emailHint }。 */
export interface LoginResult { ok?: boolean; stepUp?: boolean; emailHint?: string }

export async function loginNoStart(
  baseUrl: string,
  user: string,
  password: string,
  code = '',
): Promise<LoginResult> {
  // 账号登录**收口到后端**(安全阶段0)：不再前端直连 Synapse，改走 cosmac 后端
  // /cosmac/login/account。阶段2:异地登录时后端回 step_up,前端引导输邮箱验证码后带 code 重试。
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/login/account`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: user, password, code }),
  })
  const j = await r.json().catch(() => ({}))
  if (r.ok && j?.step_up) return { stepUp: true, emailHint: j.email_hint || '' }
  if (!r.ok || !j?.access_token) throw new Error(j?.error || '登录失败')
  saveSession(baseUrl, j)
  return { ok: true }
}

/** 邮箱+密码「只认证不启动」（走 cosmac 后端反查账号,同 loginNoStart 的语义）。 */
export async function loginWithEmailNoStart(
  baseUrl: string,
  email: string,
  password: string,
  code = '',
): Promise<LoginResult> {
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/login/email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, code }),
  })
  const j = await r.json().catch(() => ({}))
  if (r.ok && j?.step_up) return { stepUp: true, emailHint: j.email_hint || '' }
  if (!r.ok || !j?.access_token) throw new Error(j?.error || '登录失败')
  saveSession(baseUrl, j)
  return { ok: true }
}

// 允许的 homeserver host 白名单：localStorage 可被同源脚本/扩展篡改，若不校验 baseUrl，
// 被改成攻击者主机后，恢复会话时会把 Authorization: Bearer <token> 发往该主机 → token 泄露。
// 追加 window.location.hostname：OEM 自部实例（发行版）homeserver 与页面同源；
// 同源天然可信——代码本身就是从该源加载的，伪造同源即已完全控制页面，白名单挡不了也不必挡。
const ALLOWED_HS_HOSTS = ['hs.cosmac.cc', 'localhost', '127.0.0.1', window.location.hostname]

function isValidBaseUrl(u: unknown): u is string {
  if (typeof u !== 'string' || !u) return false
  try {
    const url = new URL(u)
    // 生产强制 https；仅本地开发允许 http（localhost/127.0.0.1）。
    const isLocal = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    if (url.protocol !== 'https:' && !isLocal) return false
    return ALLOWED_HS_HOSTS.includes(url.hostname)
  } catch {
    return false
  }
}

/** 尝试用上次记住的会话恢复登录；没有/失效/被篡改返回 null。 */
export async function restoreSession(): Promise<string | null> {
  const raw = localStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    const s = JSON.parse(raw)
    // 校验形状 + baseUrl 白名单：任何不合预期就丢弃会话，绝不拿不可信的 baseUrl 启动客户端。
    if (
      !isValidBaseUrl(s?.baseUrl) ||
      typeof s?.accessToken !== 'string' || !s.accessToken ||
      typeof s?.userId !== 'string' || !s.userId
    ) {
      localStorage.removeItem(SESSION_KEY)
      return null
    }
    const uid = await startFrom(s)
    // 关键：把"通过 restore 复活的当前账号"也补进多账号缓存。否则功能上线前就登录过、
    // 或只靠 SESSION_KEY 活着的账号永远进不了"切换账号"列表——表现就是：加了新号后
    // 看不到旧号、无法一键切回。upsert 幂等，同号覆盖、保留原显示名。
    if (uid) upsertAccount(s)
    return uid
  } catch (e: any) {
    // 只有**确定的鉴权失效**(token 无效/账号停用)才删会话；网络抖动/初始同步超时等瞬时失败
    // 必须保留会话——否则弱网刷新一次就把有效 token 删了、把人踢回登录页重输密码(审查 bug#1)。
    if (e?.errcode === 'M_UNKNOWN_TOKEN' || e?.errcode === 'M_USER_DEACTIVATED' || e?.errcode === 'M_USER_LOCKED') {
      localStorage.removeItem(SESSION_KEY)
    }
    return null
  }
}

/** 退出登录、清掉记住的会话，并尽力撤销服务端 access token。 */
export async function logout(): Promise<void> {
  const cur = mx
  try {
    await (cur as any)?.logout?.()
  } catch {
    /* ignore */
  } finally {
    // 退出登录 = 把当前这个账号从缓存里也移除（其它已缓存账号保留，仍可切换）。
    removeCachedAccount(currentUserId())
    localStorage.removeItem(SESSION_KEY)
    try {
      cur?.stopClient()
    } catch {
      /* ignore */
    }
    if (mx === cur) mx = null
  }
}

/** 注册"有更新就回调"——同步完成或来新消息时触发，UI 据此刷新。
 *
 * 关键：登录/重连的**初始同步**会把一批历史消息逐条灌进时间线，`Room.timeline`
 * 因此密集触发；若每条都立刻 refresh，历史消息就会"一条一条蹦出来"。这里做个
 * 80ms 短防抖：把这一**批**密集事件合并成**一次**渲染——历史整批瞬间出现；
 * 而真正的新消息（彼此间隔远大于 80ms）仍各自触发一次，逐条自然出现。 */
export function onUpdate(cb: () => void): () => void {
  if (!mx) return () => {}
  let timer: number | null = null
  const fire = () => {
    if (timer !== null) clearTimeout(timer)
    timer = window.setTimeout(() => { timer = null; cb() }, 80)
  }
  const onSync = (state: string) => {
    if (state === 'PREPARED' || state === 'SYNCING') fire()
  }
  const onTimeline = () => fire()
  ;(mx as any).on('sync', onSync)
  ;(mx as any).on('Room.timeline', onTimeline)
  // 返回解绑函数：调用方在 onBeforeUnmount/登出时调用，否则反复挂载会累积监听、同一更新触发多次。
  return () => {
    if (timer !== null) { clearTimeout(timer); timer = null }
    try { (mx as any)?.off?.('sync', onSync) } catch { /* mx 可能已销毁 */ }
    try { (mx as any)?.off?.('Room.timeline', onTimeline) } catch { /* ignore */ }
  }
}

/** 订阅"正在输入…"变化（③ 流式体感）：某房间有人开始/停止输入时触发 cb。
 *
 * typing 是 Matrix 的 ephemeral 信号，matrix-js-sdk 收到后会 emit 'RoomMember.typing'。
 * 返回解绑函数（登出/卸载时调用，避免累积监听）。 */
export function onTyping(cb: () => void): () => void {
  if (!mx) return () => {}
  const handler = () => cb()
  ;(mx as any).on('RoomMember.typing', handler)
  return () => {
    try { (mx as any)?.off?.('RoomMember.typing', handler) } catch { /* mx 可能已销毁 */ }
  }
}

/** 某房间里是否有**别人**（非本人）正在输入。中枢 AI 私聊里只有 bot 与我，故=bot 在输入。 */
export function roomTyping(roomId: string): boolean {
  if (!mx || !roomId) return false
  const room = mx.getRoom(roomId)
  if (!room) return false
  const me = (mx as any).getUserId?.()
  try {
    return room.getMembers().some((m: any) => m.typing && m.userId !== me)
  } catch {
    return false
  }
}

/** 列出我加入的群频道（排除 Space 空间本身、"中枢 AI"私聊和无名 DM；按名称排序）。 */
/** 读房间简介（m.room.topic 状态事件 → topic）。 */
function roomTopic(room: any): string | undefined {
  const ev = room?.currentState?.getStateEvents?.('m.room.topic', '')
  return ev?.getContent?.()?.topic || undefined
}

export function listRooms(): LiveRoom[] {
  if (!mx) return []
  const aiIds = aiSessionRoomIds() // 主 AI 的所有会话房都不进频道列表（它们在右侧 AI 面板里）
  return mx
    .getRooms()
    // Space（工作区）本身不是频道，不进频道列表
    .filter((r) => !(r as any).isSpaceRoom?.())
    // 排除全部主 AI 会话房（多会话后可能有多个，统一按标记排除）
    .filter((r) => !aiIds.has(r.roomId))
    // 排除真人私信(DM):它们渲染在"私信"区,不是频道(含被邀请阶段的,靠 is_direct 识别)
    .filter((r) => !isDmRoom(r))
    // 排除 GuDuu OS 控制室：它是平台的"配置数据库"(AI配置/会员/门控/套餐等 state event 都存这),
    // 不是聊天频道。出现在列表里会被管理员当普通频道误删(实测发生过——退出后后台配置读写全断)。
    // 按 canonical alias 判定(#cosmac-ctrl),改名也藏得住。
    .filter((r) => !((r as any).getCanonicalAlias?.() || '').startsWith('#cosmac-ctrl:'))
    // 无名 DM 的 name 会回退成对方 mxid（以 @ 开头）不进频道列表；但**显式设了频道名**的房间即便
    // 名字以 @ 开头（如"@全体公告"）也是正常频道，不能滤掉（L5）。故仅在**无显式 m.room.name**
    // 时才按 @ 前缀丢弃（DM 本就已被上面的 isDmRoom 排除，这里只是兜无名房的名字回退）。
    .filter((r) => {
      const hasName = !!(r as any).currentState?.getStateEvents?.('m.room.name', '')
      return hasName || !((r.name || r.roomId) || '').startsWith('@')
    })
    .map((r) => ({ id: r.roomId, name: r.name || r.roomId, topic: roomTopic(r), fav: !!(r as any).tags?.['m.favourite'] }))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh'))
}

/**
 * 登录后自动接受所有「待接受」的频道邀请(把 invite 态 join 掉)。返回本次实际 join 的房间数。
 * 为什么:GuDuu OS 是"AI/管理员把你拉进项目频道"的工作台模型——邀请就应入群(像 Slack 拉你进频道)。
 * 否则邀请永远挂在 invite 态,被邀请方看不到、也没真加入,成员数还里外对不上(修 QA bug 9/10/11)。
 * best-effort:单个房进不去不影响其它;全程兜异常,绝不阻断登录。
 */
export async function acceptPendingInvites(): Promise<number> {
  if (!mx) return 0
  const myId = (mx as any).getUserId?.() || ''
  const myServer = myId.split(':').slice(1).join(':')   // @u:server → server
  let joined = 0
  const invited = mx.getRooms().filter((r: any) => {
    try { return r.getMyMembership?.() === 'invite' } catch { return false }
  })
  for (const r of invited) {
    // 防垃圾邀请(审查 bug#10):**明确**是外部服务器用户发来的邀请才不自动进。
    // ⚠️ invite 态的房间客户端常只有**精简状态**(stripped state),经常读不出邀请人——
    // 读不到时必须**默认接受**:否则本服正常邀请也被挡,成员永远进不了群(实测踩过)。
    // 当前部署联邦上没有外部用户,fail-open 风险极低;真被外服骚扰再收紧。
    let inviter = ''
    try {
      inviter = (r as any).currentState?.getStateEvents?.('m.room.member', myId)?.getSender?.() || ''
    } catch { /* 精简状态读不到,按可信处理 */ }
    if (inviter && myServer) {
      const inviterServer = inviter.split(':').slice(1).join(':')
      if (inviterServer !== myServer) continue   // 只有确证外服才跳过
    }
    try {
      await mx.joinRoom(r.roomId)
      joined++
    } catch (e: any) {
      // 永久性失败(403 无权/404 房间没了) → 直接拒掉邀请(leave),否则这条坏邀请每次登录
      // 都重试一遍、永远打不进也永远清不掉(审查 bug#10)。瞬时错误(网络)保留下次再试。
      const st = e?.httpStatus
      if (st === 403 || st === 404) {
        try { await (mx as any).leave(r.roomId) } catch { /* 拒不掉就留着 */ }
      }
    }
  }
  return joined
}

/** 给 UI 用的工作区（Matrix Space）结构 */
export interface LiveSpace {
  id: string
  name: string
  /** 左栏图标的自定义简称（存在 cosmac.workspace 状态事件里；没有就由 UI 取名字前 2 字） */
  label?: string
  /** 工作区头像（m.room.avatar）转好的 http 地址；有图就用图、没图用简称文字 */
  avatarUrl?: string
  /** 排序序号（存在 cosmac.workspace.order；和名字无关，改名不影响顺序） */
  order?: number
}

/** 读某个 Space 的 cosmac.workspace 元数据（简称 label + 排序 order）。 */
function spaceMeta(room: any): { label?: string; order?: number } {
  const c = room?.currentState?.getStateEvents?.('cosmac.workspace', '')?.getContent?.() || {}
  return {
    label: c.label || undefined,
    order: typeof c.order === 'number' ? c.order : undefined,
  }
}

/** mxc:// 转成可显示的 http 地址（走 /_matrix/media，已被 nginx 代理）。 */
export function mxcToHttp(mxc: string, size = 64): string {
  if (!mx || !mxc) return ''
  return (mx as any).mxcUrlToHttp?.(mxc, size, size, 'crop') || ''
}

/** 读某个 Space 的头像（m.room.avatar → mxc → http）。 */
function spaceAvatar(room: any): string | undefined {
  const ev = room?.currentState?.getStateEvents?.('m.room.avatar', '')
  const url = ev?.getContent?.()?.url
  return url ? mxcToHttp(url, 48) : undefined
}

/** 上传一张图片到 Matrix 媒体库，返回 mxc:// 地址。 */
export async function uploadMedia(file: File): Promise<string> {
  if (!mx) throw new Error('未登录')
  const res: any = await (mx as any).uploadContent(file, { type: file.type })
  return res?.content_uri || res?.contentUri || ''
}

/** 列出我加入的工作区（Space），按名称排序。 */
export function listSpaces(): LiveSpace[] {
  if (!mx) return []
  return mx
    .getRooms()
    .filter((r) => (r as any).isSpaceRoom?.())
    .map((r) => {
      const m = spaceMeta(r)
      return { id: r.roomId, name: r.name || r.roomId, label: m.label, order: m.order, avatarUrl: spaceAvatar(r) }
    })
    // 稳定排序：先按 order（没有的排后面），同 order 再按名字。改名不影响顺序。
    .sort((a, b) => (a.order ?? 1e9) - (b.order ?? 1e9) || a.name.localeCompare(b.name, 'zh'))
}

/** 取某个工作区(Space)下挂的频道 roomId 集合（读 m.space.child 状态事件）。 */
export function roomIdsInSpace(spaceId: string): Set<string> {
  const ids = new Set<string>()
  const space = mx?.getRoom(spaceId)
  if (!space) return ids
  const evs = (space as any).currentState?.getStateEvents?.('m.space.child') || []
  for (const ev of evs) {
    const child = ev.getStateKey?.()
    const via = ev.getContent?.()?.via
    // via 为空 = 该子关系已被撤销
    if (child && via && via.length) ids.add(child)
  }
  return ids
}

/** 真建一个工作区（Matrix Space）。opts.public=公开可加入；opts.label=左栏简称。返回 room_id。 */
export async function createSpace(
  name: string,
  opts: { public?: boolean; label?: string } = {},
): Promise<string> {
  if (!mx) throw new Error('未登录')
  const res: any = await mx.createRoom({
    name,
    preset: (opts.public ? 'public_chat' : 'private_chat') as any,
    creation_content: { type: 'm.space' } as any,
    invite: [botId()], // 拉主 AI 进 Space：文档(按 Space 存)鉴权要 bot 能读 Space 成员状态
  })
  const sid = res.room_id
  // 简称 + 排序序号存进 cosmac.workspace 状态。order 取现有工作区最大值+1（排到末尾）。
  try {
    const orders = listSpaces().map((s) => s.order).filter((n): n is number => typeof n === 'number')
    const nextOrder = (orders.length ? Math.max(...orders) : -1) + 1
    await (mx as any).sendStateEvent(sid, 'cosmac.workspace', { label: opts.label || '', order: nextOrder }, '')
  } catch { /* 存元数据失败不影响主流程 */ }
  return sid
}

/** 读某工作区(Space)的加入规则：'public'(开放加入·社区) / 'invite'(仅邀请) / 其它。默认 invite。 */
export function spaceJoinRule(spaceId: string): string {
  const room = mx?.getRoom(spaceId)
  const ev = room?.currentState?.getStateEvents?.('m.room.join_rules', '')
  return ev?.getContent?.()?.join_rule || 'invite'
}

/** 开放/关闭某工作区「任何人凭链接加入」(社区服务器)。开放时同步把其下频道也设为可加入，
 *  否则加入了服务器却进不去频道。需要在该 Space 有改 join_rules 的权限(创建者天然有)。 */
export async function setSpaceOpenJoin(spaceId: string, open: boolean): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rule = open ? 'public' : 'invite'
  await (mx as any).sendStateEvent(spaceId, 'm.room.join_rules', { join_rule: rule }, '')
  for (const cid of roomIdsInSpace(spaceId)) {
    try {
      await (mx as any).sendStateEvent(cid, 'm.room.join_rules', { join_rule: rule }, '')
    } catch { /* 某频道无权/失败跳过，不影响 Space 本身开放 */ }
  }
}

/** 生成某工作区的可分享邀请链接（别人点开→加入这个社区服务器）。用 hash 路由 /join/:space。 */
export function spaceJoinLink(spaceId: string): string {
  return `${location.origin}/#/join/${encodeURIComponent(spaceId)}`
}

/** 凭链接加入一个工作区(社区服务器)：加入 Space 本身 + 其下各频道。返回是否加入成功。
 *  注意：Matrix 里加入 Space 不会自动加入子频道，要逐个 join（频道需已设为可加入）。 */
export async function joinSpaceByLink(spaceId: string): Promise<boolean> {
  if (!mx || !spaceId) return false
  try {
    await mx.joinRoom(spaceId)
  } catch {
    return false  // Space 非公开/不可加入 → 失败
  }
  // 加入 Space 后，其子频道列表(m.space.child)可能要等 sync；轮询几次再逐个 join。
  for (let attempt = 0; attempt < 5; attempt++) {
    const children = [...roomIdsInSpace(spaceId)]
    if (children.length) {
      for (const cid of children) {
        try { await mx.joinRoom(cid) } catch { /* 某频道进不了不影响整体 */ }
      }
      break
    }
    await new Promise((r) => setTimeout(r, 600))
  }
  return true
}

/** 退出并遗忘一个房间/工作区（leave + forget）。用于"删除工作区/频道"（客户端能做的是退出）。 */
export async function leaveAndForget(roomId: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await mx.leave(roomId)
  try { await (mx as any).forget(roomId) } catch { /* forget 失败不影响已退出 */ }
}

/** 改工作区(Space)的名称 / 简称。name→m.room.name；label→cosmac.workspace 状态。 */
export async function updateSpace(
  spaceId: string,
  opts: { name?: string; label?: string; avatar?: string; order?: number } = {},
): Promise<void> {
  if (!mx) throw new Error('未登录')
  if (opts.name) {
    await (mx as any).sendStateEvent(spaceId, 'm.room.name', { name: opts.name }, '')
  }
  // label / order 合并写进同一个 cosmac.workspace 状态（避免互相覆盖）
  if (opts.label !== undefined || opts.order !== undefined) {
    const cur = mx.getRoom(spaceId)?.currentState?.getStateEvents('cosmac.workspace', '')?.getContent() || {}
    const next: any = { ...cur }
    if (opts.label !== undefined) next.label = opts.label
    if (opts.order !== undefined) next.order = opts.order
    await (mx as any).sendStateEvent(spaceId, 'cosmac.workspace', next, '')
  }
  // avatar：undefined=不动；''=清空头像；mxc://=设置头像
  if (opts.avatar !== undefined) {
    await (mx as any).sendStateEvent(spaceId, 'm.room.avatar', opts.avatar ? { url: opts.avatar } : {}, '')
  }
}

/** 改频道的名称 / 简介。name→m.room.name；topic→m.room.topic。 */
export async function updateRoom(
  roomId: string,
  opts: { name?: string; topic?: string } = {},
): Promise<void> {
  if (!mx) throw new Error('未登录')
  if (opts.name) {
    await (mx as any).sendStateEvent(roomId, 'm.room.name', { name: opts.name }, '')
  }
  if (opts.topic !== undefined) {
    await (mx as any).sendStateEvent(roomId, 'm.room.topic', { topic: opts.topic }, '')
  }
}

/* ===== 频道级 GuDuu OS 配置（频道管理面板：人设/模型/规则等）=====
 * 存成每频道一条自定义 state event `cosmac.channel_config`（与 cosmac.workspace 同套命名）。
 * 选 state event 而非 account data：群级共享（所有成员/多端一致）、留在房间里、不改 Synapse 核心。
 * 写需要发状态事件的权限（房间 state_default，一般管理员），普通成员写会被服务器拒（M_FORBIDDEN）。
 */
const CHANNEL_CONFIG_EVENT = 'cosmac.channel_config'

/** 读某频道的 GuDuu OS 配置内容；无则返回空对象 {}。 */
export function getChannelConfig(roomId: string): Record<string, any> {
  const room = mx?.getRoom(roomId)
  const ev = room?.currentState?.getStateEvents?.(CHANNEL_CONFIG_EVENT, '')
  return ev?.getContent?.() || {}
}

/** 该频道是否为「已归档专班」：bot 收尾时写 `cosmac.project.archived`{archived:true}。
 *  前端据此把归档频道灰显/排到最后（项目已结、记忆已清，留档不打扰）。 */
export function isProjectArchived(roomId: string): boolean {
  const room = mx?.getRoom(roomId)
  const ev = room?.currentState?.getStateEvents?.('cosmac.project.archived', '')
  return !!ev?.getContent?.()?.archived
}

/** 写某频道配置：读旧内容 merge 进 patch 再整体写回（保留其它键，便于逐标签页增量接入）。 */
export async function setChannelConfig(roomId: string, patch: Record<string, any>): Promise<void> {
  if (!mx) throw new Error('未登录')
  const next = { ...getChannelConfig(roomId), ...patch }
  await (mx as any).sendStateEvent(roomId, CHANNEL_CONFIG_EVENT, next, '')
}

/**
 * 平台管理员「接管」某频道:请求后端用 Synapse make_room_admin 给**我自己**在该频道授 power=100,
 * 之后就能直接写频道配置了。用于"服务器管理员管理别人建的频道"(bug14:admin≠房间管理员,默认没权限)。
 * 后端仅对平台管理员放行(非管理员回 403 → 这里返回 false)。成功返回 true。
 */
export async function claimChannelAdmin(roomId: string): Promise<boolean> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token || !roomId) return false
  try {
    const r = await fetch(`${payBase()}/cosmac/channel/claim-admin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ room_id: roomId }),
    })
    return r.ok
  } catch { return false }
}

/* ===== 看板数据源（数据看板 / 任务看板的数据源配置）=====
 * 按工作区(Space)存一条 state event `cosmac.board_sources`，内容 { dashboard: [...], tasks: [...] }。
 * 数据源目前是配置占位（名称/类型/备注），真实取数以后接。Space 本身也是 Matrix 房间，复用 state event。
 */
const BOARD_SOURCES_EVENT = 'cosmac.board_sources'

/** 读某工作区的看板数据源配置；无则返回空对象 {}。 */
export function getBoardSources(spaceId: string): Record<string, any> {
  const room = mx?.getRoom(spaceId)
  const ev = room?.currentState?.getStateEvents?.(BOARD_SOURCES_EVENT, '')
  return ev?.getContent?.() || {}
}

/** 写某工作区的看板数据源配置（整体覆盖；需该 Space 发状态事件的权限）。 */
export async function setBoardSources(spaceId: string, data: Record<string, any>): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).sendStateEvent(spaceId, BOARD_SOURCES_EVENT, data, '')
}

/* ===== 社媒数据源（数据看板真实取数的配置）=====
 * 按工作区(Space)存一条 state event `cosmac.social_sources`，内容 { sources: SocialSource[] }。
 * 设计要点（与模块3 工作流连接器同构）：
 *  · 定义（平台/账号/模式/凭据名/间隔）存这里——浏览器够不到 DB，走 Matrix state event、多端同步。
 *  · 凭据本身（API key/token/cookie）只进**服务端 env** `COSMAC_SOCIAL_<平台>_<字段>`，定义里只放凭据**名**。
 *  · 运行态（lastSync/lastStatus）由后端采集器回写，前端只读。
 * P1 只落「读写配置」；真实取数（采集器/工作流/写 DB）是 P2~P4，见 DEVLOG/CLAUDE.md 路线图。
 */
const SOCIAL_SOURCES_EVENT = 'cosmac.social_sources'

/** 读某工作区的社媒数据源配置；无则返回 { sources: [] }。 */
export function getSocialSources(spaceId: string): Record<string, any> {
  const room = mx?.getRoom(spaceId)
  const ev = room?.currentState?.getStateEvents?.(SOCIAL_SOURCES_EVENT, '')
  return ev?.getContent?.() || {}
}

/** 写某工作区的社媒数据源配置（整体覆盖；需该 Space 发状态事件的权限）。 */
export async function setSocialSources(spaceId: string, data: Record<string, any>): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).sendStateEvent(spaceId, SOCIAL_SOURCES_EVENT, data, '')
}

/* ===== 首次引导标记（per-account）=====
 * 存在**每账号 account data** `cosmac.onboarding`，内容 { done: boolean, ts }。
 * 用 account data 而非"有没有工作区"来判首次——更可靠（用户删光工作区也不会被反复引导），
 * 且每账号自动多端同步、零新基建（符合 CLAUDE.md 存储表「每账号轻量配置」走 account data）。
 */
const ONBOARDING_ACCOUNT_DATA = 'cosmac.onboarding'

/** 是否已完成首次引导。读不到（新号/没写过）→ false。 */
export function isOnboarded(): boolean {
  try {
    const c = (mx as any)?.getAccountData?.(ONBOARDING_ACCOUNT_DATA)?.getContent?.() || {}
    return !!c.done
  } catch {
    return false
  }
}

/** 标记首次引导已完成（含跳过）。 */
export async function setOnboarded(done = true): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).setAccountData(ONBOARDING_ACCOUNT_DATA, { done, ts: Date.now() })
}

/** 把本人引导时选的入驻模板上报给 bot(记进 cosmac DB)——资源级权限「指定模板可用」
 *  据此判定。best-effort:失败不阻断引导(最多该用户暂时用不上模板专属资源)。 */
export async function reportOnboardingTemplate(templateSlug: string): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token || !templateSlug) return
  try {
    await fetch(`${payBase()}/cosmac/onboarding/select`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ template: templateSlug }),
    })
  } catch { /* 静默:引导主流程不受影响 */ }
}

/** 在某工作区(Space)下真建一个频道：建房间 + 邀请主 AI + 挂到 Space 下。返回 room_id。 */
export async function createChannelInSpace(
  spaceId: string,
  name: string,
  opts: { public?: boolean; topic?: string } = {},
): Promise<string> {
  if (!mx) throw new Error('未登录')
  const res: any = await mx.createRoom({
    name,
    topic: opts.topic || undefined, // 频道简介
    preset: (opts.public ? 'public_chat' : 'private_chat') as any,
    invite: [botId()], // 拉主 AI 进群，频道里 AI 能回
  })
  const cid = res.room_id
  const server = serverName()
  // 双向挂接：Space 记子频道，子频道指回父 Space。**必须挂上**——挂不上频道就成孤儿、
  // 不进工作区频道树。突发建多个频道时可能限流，故 m.space.child 失败退避重试几次。
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await (mx as any).sendStateEvent(spaceId, 'm.space.child', { via: [server] }, cid)
      break
    } catch {
      if (attempt < 2) await new Promise((r) => setTimeout(r, 700 * (attempt + 1)))
    }
  }
  try {
    await (mx as any).sendStateEvent(cid, 'm.space.parent', { via: [server], canonical: true }, spaceId)
  } catch { /* parent 指回是辅助,失败不影响频道进工作区(靠 m.space.child) */ }
  // 默认「频道资源边界」规则(负责人硬性要求:每次建频道都要植入):频道管理「规则」tab
  // 可见可改;服务端另有恒定的代码层隔离,这条是给成员看的透明化声明。失败不阻断建频道。
  try {
    await (mx as any).sendStateEvent(cid, CHANNEL_CONFIG_EVENT, {
      rules: [{
        label: '频道资源边界',
        desc: '本频道 AI 仅使用本频道的技能、智能体、规则与知识库(含管理员显式绑定进本频道的知识源)作答,不引用频道外内容。',
      }],
    }, '')
  } catch { /* 规则写入失败不影响频道可用 */ }
  return cid
}

/** 本服务器域名（从当前用户 id 取，如 @admin:cosmac.cc → cosmac.cc）。 */
export function serverName(): string {
  return (mx?.getUserId() || '').split(':')[1] || 'cosmac.cc'
}

/** 把一个房间挂进某工作区(Space)：先加入它（bot 已邀请），再写 m.space.child 让它进频道树。
 *
 * 用于 bot 建好专班后的"挂工作区"——bot 不在用户 Space 里写不了 m.space.child，由客户端
 * （在 Space 有权限）补这一步。best-effort：已加入/无权限都吞掉，不抛。返回是否挂上。 */
export async function linkRoomToSpace(spaceId: string, roomId: string): Promise<boolean> {
  if (!mx || !spaceId || !roomId) return false
  try { await mx.joinRoom(roomId) } catch { /* 可能已加入 */ }
  const via = serverName()
  try {
    await (mx as any).sendStateEvent(spaceId, 'm.space.child', { via: [via] }, roomId)
  } catch {
    // 直接写失败=我在该工作区没有写 state 的权限(凭链接加入的普通成员 power=0)。
    // 回退走 bot 代写:后端校验"我同时是工作区与频道的成员"后由 bot 挂接——否则这类成员
    // 手动「归入」和 AI 建专班的自动挂接都会失败,频道永远躺在「未归类」(线上实报)。
    if (!(await spaceAdoptViaBot(spaceId, roomId))) return false
  }
  // 子房间指回父 Space（有权限就写，没有也无妨——频道树只看 Space 里的 m.space.child）
  try { await (mx as any).sendStateEvent(roomId, 'm.space.parent', { via: [via], canonical: true }, spaceId) } catch { /* ignore */ }
  return true
}

/** 把频道从一个工作区移到另一个（频道设置里的「移动到工作区」）。
 *
 * 顺序是**先挂进新的、再从旧的摘除**——挂接失败就整体失败，绝不会把频道弄成
 * 两边都不在的孤儿。摘除（往旧 Space 写空 content 的 m.space.child）失败只说明
 * 在旧工作区没写权限，此时频道已进新工作区、只是旧的还挂着 → 返回 'partial'
 * 让调用方提示一下，不算失败。 */
export async function moveRoomToSpace(
  fromSpaceId: string,
  toSpaceId: string,
  roomId: string,
): Promise<'ok' | 'partial' | 'fail'> {
  if (!mx || !toSpaceId || !roomId) return 'fail'
  if (!(await linkRoomToSpace(toSpaceId, roomId))) return 'fail'
  if (fromSpaceId && fromSpaceId !== toSpaceId) {
    try {
      // Matrix 惯例:m.space.child 写空 content = 从频道树摘除该子房间
      await (mx as any).sendStateEvent(fromSpaceId, 'm.space.child', {}, roomId)
    } catch { return 'partial' }
  }
  return 'ok'
}

/* ===== 站点页面内容（注册/登录页的「隐私政策 / 帮助中心」）=====
 * 内容存控制室 state event `cosmac.pages`(后台「页面内容」编辑);未配置时后端回内置默认稿。
 * 读走 bot 公开端点(注册页未登录也要能看);写走 state event(与其它后台配置同套路)。 */
const PAGES_EVENT_TYPE = 'cosmac.pages'
export interface SitePage { title: string; md: string }

/** 公开读页面内容。baseUrl 可省略(已登录时用当前 homeserver);未登录页(AuthView)须显式传。 */
export async function fetchSitePage(key: 'privacy' | 'help', baseUrl?: string): Promise<SitePage> {
  const base = (baseUrl || (mx as any)?.baseUrl || '').replace(/\/$/, '')
  try {
    const r = await fetch(`${base}/cosmac/page?key=${key}`)
    if (r.ok) {
      const j = await r.json().catch(() => ({}))
      if (j?.md) return { title: String(j.title || ''), md: String(j.md) }
    }
  } catch { /* 回落 */ }
  return { title: key === 'privacy' ? '隐私政策' : '帮助中心', md: '内容加载失败，请稍后重试。' }
}

/** 写页面内容(管理员,整体覆盖 cosmac.pages)。pages = { privacy: {...}, help: {...} }。 */
export async function setSitePages(pages: Record<string, SitePage>): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, PAGES_EVENT_TYPE, pages, '')
}

/** 请求后端由 bot 代写 m.space.child（成员无 Space 写权限时的回退）。成功 true。 */
async function spaceAdoptViaBot(spaceId: string, roomId: string): Promise<boolean> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return false
  try {
    const r = await fetch(`${payBase()}/cosmac/space/adopt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ space_id: spaceId, room_id: roomId }),
    })
    return r.ok
  } catch { return false }
}

/** 把"用户名 / @用户名 / @用户名:域名"都规范成完整 Matrix id（@用户名:本服务器）。
 *
 * 关键容错：输入 `@wenan`（带 @ 但**没域名**）以前会被原样返回成非法 id `@wenan`，导致
 * 建账号/邀请失败。现在统一：去掉前导 @ → 没冒号就补本服务器域名 → 补回 @。 */
export function normalizeUserId(input: string): string {
  const s = input.trim().replace(/^@+/, '')   // 去掉开头的 @（可能多个/没有）
  if (!s) return ''
  if (s.includes(':')) return `@${s}`          // 已带 :域名 → 只补 @
  return `@${s}:${serverName()}`               // 只有 localpart → 补本服务器域名
}

/** 探测某用户是否存在（发私信/邀请前先校验，别建出一个邀请不到人的死房）。
 *  用 `GET /profile/{userId}`：404=不存在 → 返回 false；200 或其它状态(403/网络错等探测不可靠)
 *  一律返回 true（放行），只在**明确 404** 时判定不存在，避免因服务器限制/抖动误拦真实用户。 */
export async function userExists(input: string): Promise<boolean> {
  if (!mx) return true
  const uid = normalizeUserId(input)
  if (!uid) return false
  const base = ((mx as any).getHomeserverUrl?.() || (mx as any).baseUrl || '').replace(/\/$/, '')
  const token = (mx as any).getAccessToken?.() || ''
  try {
    const r = await fetch(`${base}/_matrix/client/v3/profile/${encodeURIComponent(uid)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    return r.status !== 404
  } catch {
    return true  // 网络异常放行，交给后续建房/邀请那步兜底
  }
}

/** 私信对方（除自己/主AI 外那个人）及其在场状态。
 *  - joined  = membership 'join'（已接受、在场）
 *  - pending = membership 'invite'（刚发起、对方还没接受——这是**正常**待接受态，不是"送不达"）
 *  - 两者都为 false = 对方已离场（leave/ban，被停用或退出）→ 此时发消息没人收，才提醒发送人。
 *  M10：旧实现把 invite 也当成"不在场"，导致刚发起的私信立刻误报"送不达"。 */
export function dmPeerStatus(roomId: string): { peerId: string; joined: boolean; pending: boolean } {
  const room = mx?.getRoom(roomId)
  const meId = mx?.getUserId?.() || ''
  if (!room) return { peerId: '', joined: false, pending: false }
  const all = (room as any).getMembers?.() || []   // 含 join/invite/leave（离场者也在 state 里）
  const peer = all.find((m: any) => m.userId !== meId && m.userId !== botId())
  if (!peer) return { peerId: '', joined: false, pending: false }
  return {
    peerId: peer.userId,
    joined: peer.membership === 'join',
    pending: peer.membership === 'invite',
  }
}

/** 查某用户是否已停用（私信对方不在场时用于区分「已停用」还是「已退出」的措辞）。失败/未知返回 false。 */
export async function checkUserDeactivated(userId: string): Promise<boolean> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token || !userId) return false
  try {
    const r = await fetch(`${payBase()}/cosmac/user/deactivated?user_id=${encodeURIComponent(userId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return false
    const j = await r.json().catch(() => ({}))
    return !!j?.deactivated
  } catch { return false }
}

/** 这个房间是否被收藏（Matrix 标准 m.favourite 标签）。 */
export function isFavourite(roomId: string): boolean {
  return !!mx?.getRoom(roomId)?.tags?.['m.favourite']
}

/** 设置/取消收藏（写 m.favourite 标签，per-room、跨设备同步）。 */
export async function setFavourite(roomId: string, on: boolean): Promise<void> {
  if (!mx) throw new Error('未登录')
  if (on) await (mx as any).setRoomTag(roomId, 'm.favourite', {})
  else await (mx as any).deleteRoomTag(roomId, 'm.favourite')
}

/** 读某个房间的真实成员（已加入的）。返回 {id, name, isBot}。 */
export function listRoomMembers(roomId: string): { id: string; name: string; isBot: boolean; pending?: boolean }[] {
  const room = mx?.getRoom(roomId)
  if (!room) return []
  // 口径与「频道管理」一致:已加入 + 待接受邀请 都算成员——否则频道头显示 1、
  // 管理面板显示 3,里外数字对不上(QA 实测报过)。待接受的带 pending 标记,列表可标注。
  const joined = (room.getJoinedMembers() || []).map((m: any) => ({
    id: m.userId,
    name: m.name || m.userId,
    // 主 AI 与 AI 同事傀儡账号(方案B,@guduu-ai-*)都按 bot 渲染(头像「智」)
    isBot: m.userId === botId() || isAiWorkerId(m.userId),
  }))
  const invited = ((room as any).getMembersWithMembership?.('invite') || []).map((m: any) => ({
    id: m.userId,
    name: m.name || m.userId,
    isBot: m.userId === botId(),
    pending: true,
  }))
  return [...joined, ...invited]
}

/** 我的联系人 = 跟我共享了房间/私信的所有人（去重，排除自己和中枢AI）。
 *
 * 普通用户没有 admin 的全量用户列表权限，但能看到自己共处一室的人——这就是"已加的朋友/协作人"。
 * 「我的协作人」据此自动列出，用户只给他们补能力备注，无需重新敲 id。 */
export function listMyContacts(): { id: string; name: string }[] {
  if (!mx) return []
  const me = mx.getUserId?.() || ''
  const bot = botId()
  const seen = new Map<string, string>()  // userId → name（保留首次见到的名字）
  for (const r of mx.getRooms()) {
    if ((r as any).isSpaceRoom?.()) continue  // Space 本身不算"人"
    for (const m of (r.getJoinedMembers() || [])) {
      const id = (m as any).userId
      if (!id || id === me || id === bot || seen.has(id)) continue
      seen.set(id, (m as any).name || id)
    }
  }
  return Array.from(seen, ([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, 'zh'))
}

/** 频道管理「人员」标签用的成员（含头像/角色/在不在群） */
export interface ChannelMember {
  id: string              // 完整 Matrix 用户 id，如 @alice:cosmac.cc
  name: string            // 显示名（没设昵称就退回用户名段）
  avatar: string          // http 头像地址；没有则空串（UI 退回首字母圆头像）
  isBot: boolean          // 是否中枢 AI（按 botId() 判定，UI 标 APP）
  role: 'owner' | 'admin' | 'member'  // 由 m.room.power_levels 推出：100=owner，≥50=admin，其余 member
  roleLabel: string       // 角色中文标签：群主 / 管理员 / 成员
  power: number           // 原始 power level 数值（移除/降权判断用）
  pending: boolean        // true=已邀请但还没加入（invite 态）
}

/** power level → 角色（与 Matrix 默认 100/50 阈值一致） */
function roleOfPower(power: number): { role: ChannelMember['role']; roleLabel: string } {
  if (power >= 100) return { role: 'owner', roleLabel: '群主' }
  if (power >= 50) return { role: 'admin', roleLabel: '管理员' }
  return { role: 'member', roleLabel: '成员' }
}

/**
 * 读频道真实成员（频道管理「人员」标签用）。
 * 已加入(join) + 已邀请待入(invite) 都返回；invite 的标 pending。
 * 头像取 m.room.member 里的 avatar_url(mxc) 转 http；角色由房间 power_levels 推出。
 * 排序：群主 > 管理员 > 成员，bot 排在同级末尾，便于 UI 展示。
 */
export function listChannelMembers(roomId: string): ChannelMember[] {
  const room = mx?.getRoom(roomId)
  if (!room) return []
  // power_levels 状态事件：users 字典存了每个被显式赋权的用户的 power
  const plContent = room.currentState?.getStateEvents?.('m.room.power_levels', '')?.getContent?.() || {}
  const usersPower: Record<string, number> = plContent.users || {}
  const defaultPower: number = plContent.users_default ?? 0
  // join + invite 两种状态都算"频道成员"
  const raw = room.getMembersWithMembership?.('join') || room.getJoinedMembers() || []
  const invited = room.getMembersWithMembership?.('invite') || []
  const all = [...raw, ...invited]
  const out: ChannelMember[] = all.map((m: any) => {
    const power = usersPower[m.userId] ?? defaultPower
    const { role, roleLabel } = roleOfPower(power)
    const isBot = m.userId === botId()
    const mxc = m.getMxcAvatarUrl?.() || m.events?.member?.getContent?.()?.avatar_url || ''
    // js-sdk 在没设昵称时把 name 填成完整 userId（@guduu:cosmac.cc），显示难看；
    // 这种情况退回用 id 的 localpart（@后、:前那段），仍是真实信息、只是更干净。
    const localpart = m.userId.replace(/^@/, '').split(':')[0]
    const name = (!m.name || m.name === m.userId) ? localpart : m.name
    // 主AI(bot)即便建房是 power=100,也不叫「群主/频道主」——那是真人的位置。AI 作为频道内置
    // 助理,有管理权的标「副频道主」，只有真人才显示「群主」。普通成员两者都是「成员」。
    const label = (isBot && role !== 'member') ? '副频道主' : roleLabel
    return {
      id: m.userId,
      name,
      avatar: mxc ? mxcToHttp(mxc, 64) : '',
      isBot,
      role,
      roleLabel: label,
      power,
      pending: m.membership === 'invite',
    }
  })
  // 排序：power 高在前；同 power 时真人优先于 bot、再按名字
  return out.sort((a, b) => b.power - a.power || Number(a.isBot) - Number(b.isBot) || a.name.localeCompare(b.name))
}

/** 邀请一个已有用户进某频道（标准 Matrix 邀请）。 */
export async function inviteToRoom(roomId: string, userId: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await mx.invite(roomId, userId)
}

/**
 * 把某用户移出频道（标准 Matrix kick）。需当前登录者 power 足够（一般是管理员）。
 * 注：kick 只是踢出当前房间，不删账号；被踢者可被再次邀请。
 */
export async function kickFromRoom(roomId: string, userId: string, reason?: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).kick(roomId, userId, reason)
}

/** 我在某房间/服务器(Space)的 power level（决定我能做什么）。读不到默认 0。 */
export function myPowerIn(roomId: string): number {
  const room = mx?.getRoom(roomId)
  const me = mx?.getUserId() || ''
  const pl: any = room?.currentState?.getStateEvents?.('m.room.power_levels', '')?.getContent?.() || {}
  return (pl.users?.[me]) ?? (pl.users_default ?? 0)
}

/** 设某成员在服务器(Space)的 power level（=角色）。保留 power_levels 其它字段、只改 users。
 *  power<=0 视为"成员"(删除显式赋权)。需当前用户权限足够(通常所有者)，否则服务器会拒。 */
export async function setMemberPower(spaceId: string, userId: string, power: number): Promise<void> {
  if (!mx) throw new Error('未登录')
  const room = mx.getRoom(spaceId)
  const pl: any = room?.currentState?.getStateEvents?.('m.room.power_levels', '')?.getContent?.()
  if (!pl || typeof pl !== 'object') throw new Error('读取权限信息失败，请稍后重试')
  const users: Record<string, number> = { ...(pl.users || {}) }
  if (power <= 0) delete users[userId]
  else users[userId] = power
  await (mx as any).sendStateEvent(spaceId, 'm.room.power_levels', { ...pl, users }, '')
}

/** 把某成员移出服务器：踢出 Space 本身 + 其下各频道（尽力而为）。 */
export async function kickFromSpace(spaceId: string, userId: string, reason?: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  for (const cid of roomIdsInSpace(spaceId)) {
    try { await (mx as any).kick(cid, userId, reason) } catch { /* 某频道踢不了跳过 */ }
  }
  await (mx as any).kick(spaceId, userId, reason)
}

/** 封禁某成员：ban 出 Space + 其下频道。被封禁者**不能再加入**（即使开放加入/有链接），直到解封。 */
export async function banFromSpace(spaceId: string, userId: string, reason?: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  for (const cid of roomIdsInSpace(spaceId)) {
    try { await (mx as any).ban(cid, userId, reason) } catch { /* 某频道 ban 不了跳过 */ }
  }
  await (mx as any).ban(spaceId, userId, reason)
}

/** 解封某成员（Space + 其下频道）。解封后其恢复"未加入"，可重新凭链接加入。 */
export async function unbanFromSpace(spaceId: string, userId: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  for (const cid of roomIdsInSpace(spaceId)) {
    try { await (mx as any).unban(cid, userId) } catch { /* 跳过 */ }
  }
  await (mx as any).unban(spaceId, userId)
}

/** 列出某服务器(Space)被封禁的用户（membership=ban）。用于成员管理里的"已封禁"区。 */
export function listBannedMembers(spaceId: string): { id: string; name: string; avatar: string }[] {
  const room = mx?.getRoom(spaceId)
  if (!room) return []
  const banned = room.getMembersWithMembership?.('ban') || []
  return banned.map((m: any) => {
    const localpart = m.userId.replace(/^@/, '').split(':')[0]
    const name = (!m.name || m.name === m.userId) ? localpart : m.name
    const mxc = m.getMxcAvatarUrl?.() || ''
    return { id: m.userId, name, avatar: mxc ? mxcToHttp(mxc, 64) : '' }
  })
}

/**
 * 用 Synapse Admin API 新建一个账号（需当前登录者是服务器管理员，如 @admin）。
 * 返回完整用户 id。失败抛错（含状态码/原因）。
 */
export async function createUser(
  username: string,
  password: string,
  displayname?: string,
): Promise<string> {
  if (!mx) throw new Error('未登录')
  const uid = normalizeUserId(username)
  const localpart = uid.slice(1).split(':')[0]  // 干净的默认显示名（去掉 @ 和域名）
  const base = (mx as any).baseUrl as string
  const token = (mx as any).getAccessToken?.() as string
  const res = await fetch(`${base}/_synapse/admin/v2/users/${encodeURIComponent(uid)}`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ password, displayname: displayname || localpart, admin: false }),
  })
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json())?.error || msg } catch { /* ignore */ }
    throw new Error(`建账号失败：${msg}`)
  }
  return uid
}

/* ========================================================================
 *  平台管理后台（/admin）—— 用户管理
 *  全部走 Synapse Admin API（/_synapse/admin/...），用当前登录管理员的 token。
 *  需当前账号是服务器管理员（@admin 之类）；非管理员调用会被 Synapse 拒（403）。
 * ===================================================================== */

/** 统一的 Admin API 请求封装：自动带上 base 地址与管理员 token，出错抛带原因的错误。 */
async function adminFetch(path: string, init: RequestInit = {}): Promise<any> {
  if (!mx) throw new Error('未登录')
  const base = (mx as any).baseUrl as string
  const token = (mx as any).getAccessToken?.() as string
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json())?.error || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  // 有些 Admin 端点回空体，容错处理
  try { return await res.json() } catch { return {} }
}

/** 管理后台用的精简用户结构 */
export interface AdminUser {
  id: string            // 完整 id，如 @alice:cosmac.cc
  name: string          // 显示名（没设就退回 localpart）
  admin: boolean        // 是否服务器管理员
  deactivated: boolean  // 是否已**注销**(旧版停用,Synapse deactivate:已退出所有房间,不可逆)
  locked: boolean       // 是否已**停用**(锁定:禁登录但频道/工作区/历史全保留,可无损恢复)
  isBot: boolean        // 是否中枢 AI（按 botId() 判定）
  email?: string       // 注册邮箱(cosmac DB 反查;仅管理员可见,可能没有)
}

/**
 * 当前登录者是否服务器管理员。
 * 非管理员访问 /admin 时用它挡回。查询失败（如 403）一律按"不是管理员"处理。
 */
export async function isServerAdmin(): Promise<boolean> {
  try {
    const uid = mx?.getUserId() || ''
    const data = await adminFetch(`/_synapse/admin/v1/users/${encodeURIComponent(uid)}/admin`)
    return !!data.admin
  } catch {
    return false
  }
}

/**
 * 拉全部用户列表（Synapse Admin API v2，自动翻页直到取完）。
 * guests=false 不含访客；deactivated=true 连已停用的也返回（后台要能看到并恢复）。
 */
export async function listUsers(): Promise<AdminUser[]> {
  const out: AdminUser[] = []
  let from = 0
  const limit = 100
  // Synapse 用 next_token 分页；没有 next_token 表示取完了
  for (let guard = 0; guard < 100; guard++) {
    const data = await adminFetch(
      `/_synapse/admin/v2/users?from=${from}&limit=${limit}&guests=false&deactivated=true`,
    )
    for (const u of data.users || []) {
      // AI 同事傀儡账号(方案B,@guduu-ai-*)不进「用户管理」——它们不是真实用户,
      // 混进来会污染账号统计,管理员误停用还会弄哑对应智能体。
      if (isAiWorkerId(u.name)) continue
      const localpart = (u.name || '').replace(/^@/, '').split(':')[0]
      out.push({
        id: u.name,
        name: u.displayname || localpart,
        admin: !!u.admin,
        deactivated: !!u.deactivated,
        locked: !!u.locked,
        isBot: u.name === botId(),
      })
    }
    if (data.next_token === undefined || data.next_token === null) break
    from = Number(data.next_token)
  }
  // 附加邮箱(仅管理员能拿到;失败则静默不显示)。按 localpart 匹配。
  try {
    const emails = await listUserEmails()
    for (const u of out) {
      const lp = u.id.replace(/^@/, '').split(':')[0].toLowerCase()
      if (emails[lp]) u.email = emails[lp]
    }
  } catch { /* 拿不到邮箱不影响用户列表 */ }
  return out
}

/**
 * 拉「用户名 localpart → 邮箱」映射(走 cosmac 后端 /cosmac/admin/emails,仅管理员)。
 * 邮箱只在 cosmac DB(Synapse 不存),故经 bot 端点取。失败/无权限返回空表(不影响用户列表)。
 */
export async function listUserEmails(): Promise<Record<string, string>> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return {}
  try {
    const r = await fetch(`${payBase()}/cosmac/admin/emails`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return {}
    const j = await r.json()
    return (j && j.emails) || {}
  } catch { return {} }
}

/**
 * ⚠️ 注销账号（POST deactivate,**不可逆**）：Synapse 会把该用户从**所有房间退出**、
 * 删除登录凭据/邮箱绑定——恢复后频道/工作区成员关系与历史读取权都救不回来
 * （负责人线上踩过：恢复后只剩 cosmac DB 里的看板任务）。
 * 日常「停用」请用 lockUser（锁定：禁登录、数据全保留、可无损恢复）；本函数仅留给
 * 真要抹除账号的场景。
 */
export async function deactivateUser(userId: string): Promise<void> {
  await adminFetch(`/_synapse/admin/v1/deactivate/${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ erase: false }),
  })
}

/** 停用账号（锁定,Synapse locked）：禁止登录并踢下线,但频道/工作区成员关系、
 * 聊天历史、配置全部原样保留;unlockUser 一键无损恢复。日常停用一律用它。 */
export async function lockUser(userId: string): Promise<void> {
  await adminFetch(`/_synapse/admin/v2/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ locked: true }),
  })
}

/** 解除锁定：账号恢复可登录,一切数据如常(无需重设密码)。 */
export async function unlockUser(userId: string): Promise<void> {
  await adminFetch(`/_synapse/admin/v2/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ locked: false }),
  })
}

/**
 * 恢复一个已停用的账号：Synapse 要求"恢复"时必须同时设一个新密码。
 * 用 PUT users 把 deactivated 置回 false 并写入新密码。
 */
export async function reactivateUser(userId: string, newPassword: string): Promise<void> {
  await adminFetch(`/_synapse/admin/v2/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ deactivated: false, password: newPassword }),
  })
}

/** 给某账号重置密码；logout_devices=true 同时把该用户已登录的设备全部踢下线。 */
export async function resetPassword(userId: string, newPassword: string): Promise<void> {
  await adminFetch(`/_synapse/admin/v1/reset_password/${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword, logout_devices: true }),
  })
}

/**
 * 设/撤某账号的服务器管理员权限（PUT users 的 admin 字段）。
 * 返回值：控制室「期望管理员集」是否成功同步——false 表示**主 AI 还没收到新期望、
 * 撤销者可能仍有 AI 配置写权限**，调用方应据此告警（绝不静默报全成）。
 */
export async function setUserAdmin(userId: string, admin: boolean): Promise<boolean> {
  await adminFetch(`/_synapse/admin/v2/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ admin }),
  })
  // 控制室成员随服务器管理员身份联动。关键：**真正的移除交给 power=100 的主 AI**，
  // 浏览器只“提交期望”——因为同级(50)管理员之间互相无法降权/踢出，前端做不到可靠移除。
  // 服务器管理员身份已经改成功（不回滚）；这里只报告控制室同步成没成。
  try {
    await syncControlRoomAdmins()
    return true
  } catch {
    return false // 期望集没写进控制室 → 主 AI 不会对齐，需调用方提示重试
  }
}

/**
 * 把「当前服务器管理员集」写进控制室的 cosmac.ctrl.admins 状态事件，并尽力即时对齐。
 *
 * 设计（守住「撤权后真的失去配置写权限」这条线）：
 *  - 浏览器只**声明期望**（管理员 power=50 足够写这个 state event）；
 *  - 拥有 power=100 的**主 AI(bot)** 读到后强制对齐控制室成员：降权 + 踢出不在期望集里的人。
 *    这绕过了「50 无法移除 50」的 Matrix 约束，撤权后约 1 个事件往返内即生效。
 *  - 同时做一次**前端尽力**：ensureControlRoom 邀请/提权在场管理员（即时可见），但不依赖它。
 */
async function syncControlRoomAdmins(): Promise<void> {
  if (!mx) return
  // 当前服务器管理员集（未停用的）
  const desired = (await listUsers())
    .filter((u) => u.admin && !u.deactivated)
    .map((u) => u.id)
  // 建房（首次）+ 邀请/提权在场管理员（尽力即时生效，bot 随后也会兜底对齐）
  const rid = await ensureControlRoom()
  // 写「期望管理员集」——主 AI 据此踢出被撤销者（前端无权踢同级，这步才是可靠保证）
  await (mx as any).sendStateEvent(rid, CONTROL_ADMINS_EVENT_TYPE, { admins: desired }, '')
}

/* =====================================================================
 *  管理后台 · 频道/群管理（Synapse Admin Rooms API）
 *  和用户管理一样走 /_synapse/admin/...，需服务器管理员 token。
 *  注意：这里列的是「整台服务器上的所有房间」，不同于侧栏只列「我加入的」。
 * ===================================================================== */

/** 管理后台用的精简房间结构 */
export interface AdminRoom {
  id: string                 // room_id，如 !abc:cosmac.cc
  name: string               // 房间名（没设名就退回别名或 room_id）
  alias: string | null       // 规范别名 #xxx:host（可能没有）
  members: number            // 已加入成员数
  localMembers: number       // 本服成员数
  isPublic: boolean          // 是否公开可加入（join_rules=public）
  encrypted: boolean         // 是否端到端加密
  creator: string | null     // 创建者 user_id
}

/**
 * 拉全服房间列表（Admin API v1 /rooms，自动翻页取完）。
 * 默认按成员数倒序，人多的群排前面。
 */
export async function listAdminRooms(): Promise<AdminRoom[]> {
  const out: AdminRoom[] = []
  let from = 0
  const limit = 100
  for (let guard = 0; guard < 100; guard++) {
    const data = await adminFetch(
      `/_synapse/admin/v1/rooms?from=${from}&limit=${limit}&order_by=joined_members&dir=b`,
    )
    for (const r of data.rooms || []) {
      // 工作区(Space)在 Matrix 里本质也是房间,Admin API 会一并返回——但它不是"频道",
      // 混进后台频道列表会误导管理(负责人报的)。按 room_type 剔除。
      if (r.room_type === 'm.space') continue
      out.push({
        id: r.room_id,
        name: r.name || r.canonical_alias || r.room_id,
        alias: r.canonical_alias || null,
        members: r.joined_members ?? 0,
        localMembers: r.joined_local_members ?? 0,
        // join_rules 为 "public" 即公开；其余（invite/knock…）按私有处理
        isPublic: r.join_rules === 'public',
        encrypted: !!r.encryption,
        creator: r.creator || null,
      })
    }
    // Admin rooms API 用 next_batch 翻页；没有就取完了
    if (data.next_batch === undefined || data.next_batch === null) break
    from = Number(data.next_batch)
  }
  return out
}

/** 查 Synapse 服务端版本（数据概览页展示用）。失败返回空串、不阻断页面。 */
export async function getServerVersion(): Promise<string> {
  try {
    const data = await adminFetch('/_synapse/admin/v1/server_version')
    return data.server_version || ''
  } catch {
    return ''
  }
}

/** 查某频道的「真正主人」= power_levels 里 power≥100 的**真人**(排除主 AI 与傀儡)。
 * AI 代建的专班 creator 是 @guduu,按 creator 分组会把全部专班堆到主 AI 名下(负责人指正);
 * 真人群主才是"这个频道是谁的"的正确口径。无真人 100 → 回退真人 creator → 空串。 */
export async function getRoomOwner(roomId: string, creator?: string | null): Promise<string> {
  try {
    const data = await adminFetch(`/_synapse/admin/v1/rooms/${encodeURIComponent(roomId)}/state`)
    const pl = (data.state || []).find((e: any) => e.type === 'm.room.power_levels' && !e.state_key)
    const users: Record<string, number> = pl?.content?.users || {}
    const humans = Object.entries(users)
      .filter(([uid, lv]) => typeof lv === 'number' && !uid.startsWith('@guduu:') && !isAiWorkerId(uid))
      .sort((a, b) => (b[1] as number) - (a[1] as number))
    const owner = humans.find(([, lv]) => (lv as number) >= 100)
    if (owner) return owner[0]
    // 无真人 100:退而取权限最高的真人管理员(≥50)——AI 代管群里他就是实际负责人
    const admin = humans.find(([, lv]) => (lv as number) >= 50)
    if (admin) return admin[0]
  } catch { /* 拉不到就走 creator 回退 */ }
  const c = creator || ''
  if (c && !c.startsWith('@guduu:') && !isAiWorkerId(c)) return c
  return ''
}

/** 查某房间的已加入成员 id 列表（Admin API）。 */
export async function getRoomMembers(roomId: string): Promise<string[]> {
  const data = await adminFetch(
    `/_synapse/admin/v1/rooms/${encodeURIComponent(roomId)}/members`,
  )
  return (data.members || []) as string[]
}

/**
 * 删除（并清除）一个房间。
 * @param block true=封禁该房间，禁止任何人重新加入/重建（用于违规群）；false=仅删除。
 * Synapse 会把所有本服成员踢出、purge 历史。该操作不可逆，调用前务必确认。
 */
export async function deleteRoom(roomId: string, block = false): Promise<void> {
  // 防呆(#11)：控制室(#cosmac-ctrl)承载全部平台配置——AI配置/技能/智能体/会员/门控/配额/套餐/
  // 入驻模板/工作流/页面内容都只存在这一个房间的 state event 里。删掉不可恢复、整个平台瘫痪。
  // 这里是删除的**唯一收口**，任何入口(含误点)都在此被挡住。
  if (await isControlRoom(roomId)) {
    throw new Error('这是 GuDuu OS 控制室，删除会清空全部平台配置，已阻止此操作。')
  }
  await adminFetch(`/_synapse/admin/v1/rooms/${encodeURIComponent(roomId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ block, purge: true }),
  })
}

/** 某房间是否是 GuDuu OS 控制室（按别名解析出的 room_id 比对）。解析不到/出错返回 false（不误拦）。 */
export async function isControlRoom(roomId: string): Promise<boolean> {
  if (!roomId) return false
  try {
    const ctrl = await resolveControlRoom()
    return !!ctrl && ctrl === roomId
  } catch {
    return false
  }
}

/* =====================================================================
 *  管理后台 · AI 配置（运行时下发给主 AI bot）
 *  存储：一个"控制室"（别名 #cosmac-ctrl:<server>）里的 state event
 *  `cosmac.ai.config`。管理后台（管理员）写，bot 运行时读并热应用。
 *  走标准 Matrix C-S API（不是 Admin API）：管理员是房间创建者，有权写 state。
 * ===================================================================== */

/** 控制室里 AI 配置 state event 的类型（与 bot 端 AI_CONFIG_EVENT_TYPE 一致）。 */
const AI_CONFIG_EVENT_TYPE = 'cosmac.ai.config'
/** 控制室里「期望服务器管理员集」state event 的类型（与 bot 端 CONTROL_ADMINS_EVENT_TYPE 一致）。
 *  浏览器写期望（管理员 power=50 够写 state），主 AI(power=100) 读到后对齐成员、踢出被撤销者。 */
const CONTROL_ADMINS_EVENT_TYPE = 'cosmac.ctrl.admins'
/** 控制室别名 localpart（#cosmac-ctrl:<server>）。 */
const CONTROL_ROOM_LOCALPART = 'cosmac-ctrl'
/** 控制室里「全局技能」state event 的类型（与 bot 端 SKILLS_EVENT_TYPE 一致）。
 *  管理后台写、主 AI 读；应用于所有群。群级/个人技能走聊天命令存 cosmac DB，不在这。 */
const SKILLS_EVENT_TYPE = 'cosmac.skills'
/** 控制室里「全局智能体(Agent)」state event 的类型（与 bot 端 AGENTS_EVENT_TYPE 一致）。 */
const AGENTS_EVENT_TYPE = 'cosmac.agents'
/** 控制室里「全局规则(Rule)」state event 的类型（与 bot 端 RULES_EVENT_TYPE 一致）。 */
const RULES_EVENT_TYPE = 'cosmac.rules'
/** 控制室里「工作流连接器」state event 的类型（与 bot 端 WORKFLOWS_EVENT_TYPE 一致）。 */
const WORKFLOWS_EVENT_TYPE = 'cosmac.workflows'
const PEOPLE_EVENT_TYPE = 'cosmac.people'
/** 旧版会员聚合事件，仅用于读取已有数据。 */
const MEMBERS_EVENT_TYPE = 'cosmac.members'
/** 新版单用户会员事件：state_key=userId，避免并发覆盖和事件容量上限。 */
const MEMBER_EVENT_TYPE = 'cosmac.member'

/** 主 AI 可用工具目录（工具开关 UI 用；name 要与 bot 端 Toolbox 注册的一致）。 */
export const AI_TOOL_CATALOG: { name: string; label: string }[] = [
  { name: 'create_room', label: '建群/开专班' },
  { name: 'send_message_to_room', label: '往房间发消息' },
  { name: 'list_room_members', label: '查看房间成员' },
  { name: 'get_recent_messages', label: '读取聊天记录' },
  { name: 'run_workflow', label: '跑外部工作流(n8n/Make 等)' },
]

/** 可选的模型后端目录（管理后台「AI 配置」的 provider 下拉用）。
 *  value '' = 用服务器环境变量启动配置（不在网页改 provider）。
 *  其余四家：填对应 API Key + 模型 id 即可在网页切换、热生效。 */
export const AI_PROVIDERS: {
  value: string
  label: string
  keyLabel: string
  modelPlaceholder: string
}[] = [
  { value: '', label: '默认（用服务器配置）', keyLabel: '', modelPlaceholder: '留空＝服务器默认' },
  { value: 'deepseek', label: 'DeepSeek（火山方舟）', keyLabel: '方舟 API Key', modelPlaceholder: '如 deepseek-v3.2 或 ep-… 接入点' },
  { value: 'claude', label: 'Claude（Anthropic）', keyLabel: 'Anthropic API Key', modelPlaceholder: '默认 claude-opus-4-8' },
  { value: 'openai', label: 'ChatGPT（OpenAI）', keyLabel: 'OpenAI API Key', modelPlaceholder: '默认 gpt-4o' },
  { value: 'gemini', label: 'Gemini（Google）', keyLabel: 'Google API Key', modelPlaceholder: '默认 gemini-2.0-flash' },
]

/** 管理后台编辑的 AI 配置。provider='' 表示用服务器环境变量；enabled_tools=null=全部启用。
 *  注意：**不含 API Key**——密钥只在服务端配（环境变量/Secret Manager），绝不写进
 *  Matrix 事件（state event 无法加密，会明文进 DB/历史/被全员可读）。 */
export interface AiConfig {
  provider: string
  model: string
  system_prompt: string
  enabled_tools: string[] | null
}

/** 解析控制室别名 → room_id；不存在返回 null。 */
async function resolveControlRoom(): Promise<string | null> {
  if (!mx) return null
  const alias = `#${CONTROL_ROOM_LOCALPART}:${serverName()}`
  try {
    const r = await (mx as any).getRoomIdForAlias(alias)
    return r?.room_id || null
  } catch (e: any) {
    if (e?.errcode === 'M_NOT_FOUND') return null // 明确不存在，才允许后续创建
    throw e // 网络/权限/服务器错误不能伪装成“不存在”
  }
}

/**
 * 服务器管理员登录后：确保自己已「加入」控制室（接受所有者发来的邀请）。
 *
 * 为什么必须做这步——否则新管理员的权限会「差一点」：
 *   - 主 AI(bot) 判定平台管理员只看控制室 power≥50（所有者提权时就写好了），**不看是否 join**，
 *     所以 bot 侧已认他为管理员；
 *   - 但新管理员要**从后台亲自写** AI 配置 / 门控这类 state event 时，Matrix 要求发事件者
 *     必须是该房间的 **join 成员**——光被 invite(邀请) 还发不了。所有者建房/对齐时已把新管理员
 *     邀请进来并给了 power=50，这里由新管理员自己**接受邀请**即补齐，权限与所有者完全一致
 *     （唯一有意的差别：所有者 100、普通管理员 50，仅影响能否互相降权/踢人，功能能力等价）。
 * 幂等且宽容：已加入 / 尚未被邀请 / 无权限，一律安全忽略，下次登录再试。
 */
export async function ensureControlRoomMembership(): Promise<void> {
  if (!mx) return
  try {
    const alias = `#${CONTROL_ROOM_LOCALPART}:${serverName()}`
    await mx.joinRoom(alias) // 接受控制室邀请；已在房则等价 no-op
  } catch {
    /* 已在房 / 未被邀请 / 无权限：忽略 */
  }
}

// —— 控制室权限模型 ——
// 只保留**一个所有者**（建房者）= 100，独一份；普通服务器管理员 = ADMIN（50）：
// 足够写 AI 配置 state event（state_default=50），又能被所有者降权/踢出。两个 100 的
// 用户在 Matrix 里通常互相无法降权，所以普通管理员不能给 100，否则撤销后降不下来。
// bot 是受信基础设施（只读配置、从不被管理），给 100 无妨。
const CONTROL_OWNER_PL = 100
const CONTROL_ADMIN_PL = 50

/**
 * 确保控制室存在：解析不到就新建（带别名、私有）。返回 room_id。
 *
 * 邀请对象不只是主 AI bot，还包括**所有服务器管理员**——否则只有创建者一人是房间成员，
 * 其他管理员虽能看到 /admin 入口，却读不到/写不了 AI 配置 state event。普通管理员给
 * CONTROL_ADMIN_PL(50)：够写配置，又能被所有者(100)管理（撤销时降权/踢出）。
 */
export async function ensureControlRoom(): Promise<string> {
  if (!mx) throw new Error('未登录')
  const me = mx.getUserId() || ''
  // 拉服务器管理员名单（需管理员 token；能进到这步的本就是管理员）。
  // 失败就退化为"只有创建者"——至少自己能用，不阻塞。
  let admins: string[] = []
  try {
    admins = (await listUsers())
      .filter((u) => u.admin && !u.deactivated)
      .map((u) => u.id)
  } catch {
    /* 拉不到名单：仅创建者可用 */
  }
  // 除创建者外的其他管理员（创建者建房自动入群，无需 invite）
  const others = admins.filter((a) => a && a !== me)

  const existing = await resolveControlRoom()
  if (existing) {
    // #2 修复：已存在的控制室也要补齐管理员的成员与权限——早先（多管理员逻辑之前）
    // 建的房只有创建者一人，后加的服务器管理员既进不来也没权限写 AI 配置。
    await reconcileControlRoomAdmins(existing, others)
    return existing
  }

  // 初始权限：所有者(创建者) + bot = 100；其他管理员 = 50（够写配置、可被所有者管理）
  const users: Record<string, number> = { [me]: CONTROL_OWNER_PL, [botId()]: CONTROL_OWNER_PL }
  for (const a of others) users[a] = CONTROL_ADMIN_PL

  try {
    const res: any = await (mx as any).createRoom({
      name: 'GuDuu OS 控制室',
      room_alias_name: CONTROL_ROOM_LOCALPART,
      preset: 'private_chat',
      invite: [botId(), ...others], // 主 AI + 其他管理员
      topic: 'GuDuu OS 管理后台 · 主 AI 运行时配置（请勿删除/退出）',
      power_level_content_override: { users },
    })
    return res.room_id
  } catch (e: any) {
    // TOCTOU：resolve 与 create 之间，另一个 tab/管理员已抢先建好同别名房间 → 别名冲突。
    // 此时不该报错，重新解析复用那个房间（并补齐管理员）即可。
    if (e?.errcode === 'M_ROOM_IN_USE') {
      const raced = await resolveControlRoom()
      if (raced) {
        await reconcileControlRoomAdmins(raced, others)
        return raced
      }
    }
    throw e
  }
}

/**
 * 对**已存在**的控制室补齐其他管理员的权限与成员资格（幂等、尽力而为）。
 * ① 把 power < 50 的管理员提到 CONTROL_ADMIN_PL(50)（够写 AI 配置 state event）；
 *    **只升不降**——不动已是 100 的所有者，也不会把谁降下来。
 * ② 邀请还没在房里（join/invite 都不算在）的管理员。
 * 仅当当前用户在该房有改 power_levels 的权限（所有者=100）时才生效；没权限就静默跳过，
 * 绝不阻塞「保存 AI 配置」主流程。
 */
async function reconcileControlRoomAdmins(roomId: string, admins: string[]): Promise<void> {
  if (!mx) return
  const room = mx.getRoom(roomId)
  try {
    // ① 提权：**只有真正读到 power_levels 时才动它**。
    //    若房间没同步进本地（pl 读不到），绝不用空对象去 sendStateEvent——否则会把
    //    events_default/state_default/创建者自己的 100 等全部抹掉，造成自我锁权。
    const pl: any = (room as any)?.currentState
      ?.getStateEvents?.('m.room.power_levels', '')
      ?.getContent?.()
    if (pl && typeof pl === 'object') {
      const users: Record<string, number> = { ...(pl.users || {}) }
      let changed = false
      // 各管理员要到 50（够写配置）；**bot 要到 100**——否则它没法执行成员对齐
      // （降权/踢出被撤销的管理员）。老控制室里 bot 可能还是默认 0，这里由所有者补上。
      const want: Record<string, number> = { [botId()]: CONTROL_OWNER_PL }
      for (const a of admins) want[a] = CONTROL_ADMIN_PL
      for (const [uid, lvl] of Object.entries(want)) {
        if ((users[uid] ?? 0) < lvl) {
          users[uid] = lvl // 只升不降：不动已 ≥ 目标的（含所有者 100）
          changed = true
        }
      }
      if (changed) {
        // 保留原事件全部字段，只覆盖 users
        await (mx as any).sendStateEvent(roomId, 'm.room.power_levels', { ...pl, users }, '')
      }
    }
    // ② 邀请还不在房里的管理员（房间没同步时 present 为空，invite 已在者会被忽略）
    const present = new Set(
      ((room as any)?.getMembers?.() || [])
        .filter((m: any) => m.membership === 'join' || m.membership === 'invite')
        .map((m: any) => m.userId),
    )
    for (const a of admins) {
      if (!present.has(a)) {
        try {
          await mx.invite(roomId, a)
        } catch {
          /* 已在房/无权限：忽略 */
        }
      }
    }
  } catch {
    /* 无权限或读取失败：静默跳过，不影响保存 */
  }
}

/** 读取当前 AI 配置；控制室或配置不存在时返回 null（前端用默认值兜底）。 */
export async function getAiConfig(): Promise<AiConfig | null> {
  if (!mx) return null
  const rid = await resolveControlRoom()
  if (!rid) return null
  try {
    const ev = await (mx as any).getStateEvent(rid, AI_CONFIG_EVENT_TYPE, '')
    return {
      provider: ev?.provider || '',
      model: ev?.model || '',
      system_prompt: ev?.system_prompt || '',
      enabled_tools: Array.isArray(ev?.enabled_tools) ? ev.enabled_tools : null,
    }
  } catch {
    return null // 房间在但还没写过配置
  }
}

/**
 * 写入 AI 配置（必要时先建控制室）。bot 会在 ~20s 内读到并热应用。
 *
 * 安全：**不写 api_key**——密钥只在服务端配（环境变量/Secret Manager）。这里用不含
 * api_key 的内容**整体覆盖**旧事件，顺带抹掉历史上可能存过的明文 key（注：Matrix
 * 旧版本事件仍留在房间历史里，曾经存过的 key 仍需在服务端轮换才算彻底作废）。
 */
export async function setAiConfig(cfg: AiConfig): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(
    rid,
    AI_CONFIG_EVENT_TYPE,
    {
      provider: cfg.provider,
      model: cfg.model,
      system_prompt: cfg.system_prompt,
      enabled_tools: cfg.enabled_tools,
    },
    '',
  )
}

/* =====================================================================
 *  管理后台 · 会员等级（账号权限分层）
 *  存储：控制室 state event `cosmac.members`，{ members: { userId: {tier,...} } }。
 *  未列出的用户 = 免费会员（只存非免费的覆盖）。管理员手动调整；未来支付(模块4)由 bot 写。
 *  「服务器管理员」是另一套（独立于会员等级），仍走 Synapse admin 标志。
 * ===================================================================== */

/** 会员等级目录（与 bot 端 cosmac.members 的 MEMBER_TIERS 一致；slug 稳定、label 可改）。 */
export const MEMBER_TIERS: { slug: string; label: string }[] = [
  { slug: 'free', label: '免费会员' },
  { slug: 'paid', label: '付费会员' },
  { slug: 'creator', label: '创作者会员' },
]

/** 会员等级 slug → 中文标签（未知回落到「免费会员」）。 */
export function memberTierLabel(tier: string | undefined): string {
  return MEMBER_TIERS.find((t) => t.slug === tier)?.label || '免费会员'
}

/** 会员 map：userId → 等级 slug。只含非免费的；查不到即免费。 */
export type MemberMap = Record<string, string>

/**
 * 读控制室会员 map（管理员用）。控制室不存在返回空；其它读取错误向上抛。
 * 普通用户读不到控制室——他们查自己等级走「DM 问 bot：会员」。
 */
export async function getMembers(): Promise<MemberMap> {
  if (!mx) return {}
  const rid = await resolveControlRoom()
  if (!rid) return {}
  const events: any[] = await (mx as any).roomState(rid)
  const out: MemberMap = {}
  // 先兼容旧聚合事件；随后单用户事件覆盖，free tombstone 可撤销旧等级。
  for (const event of events || []) {
    const type = event?.getType?.() ?? event?.type
    const stateKey = event?.getStateKey?.() ?? event?.state_key
    const content = event?.getContent?.() ?? event?.content ?? {}
    if (type === MEMBERS_EVENT_TYPE && stateKey === '') {
      for (const [uid, rec] of Object.entries(content?.members || {})) {
        const tier = (rec as any)?.tier
        if (tier !== 'free' && MEMBER_TIERS.some((t) => t.slug === tier)) out[uid] = tier
      }
    }
  }
  for (const event of events || []) {
    const type = event?.getType?.() ?? event?.type
    if (type !== MEMBER_EVENT_TYPE) continue
    const sk = event?.getStateKey?.() ?? event?.state_key ?? ''
    const content = event?.getContent?.() ?? event?.content ?? {}
    // 真实 user_id 以 content.uid 为准（state_key 去了 @）；兼容旧数据
    let uid = content?.uid
    if (typeof uid !== 'string' || !uid) uid = sk.startsWith('@') ? sk : (sk ? '@' + sk : '')
    if (typeof uid !== 'string' || !uid.startsWith('@') || !uid.includes(':')) continue
    const tier = content?.tier
    if (tier === 'free') delete out[uid]
    else if (MEMBER_TIERS.some((t) => t.slug === tier)) out[uid] = tier
  }
  return out
}

/**
 * 单用户会员事件的 state_key：**去掉开头的 @**。
 * Matrix 规定 state_key 以 @ 开头的事件只有本人能写，否则 403——管理员/bot 给别人开会员会被拦。
 * 去 @ 后任何有写权限的人都能写；真实 user_id 存进 content.uid。
 */
function memberStateKey(userId: string): string {
  return userId.startsWith('@') ? userId.slice(1) : userId
}

/**
 * 设/调某用户的会员等级（必要时先建控制室）。每个用户独立 state_key，互不覆盖。
 * tier='free' 作为 tombstone，既是撤销，也会覆盖旧聚合事件里的历史记录。
 */
export async function setMemberTier(userId: string, tier: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  if (!MEMBER_TIERS.some((t) => t.slug === tier)) throw new Error('未知会员等级')
  const rid = await ensureControlRoom()
  const content = { uid: userId, tier, source: 'admin', updated_ts: Math.floor(Date.now() / 1000) }
  // state_key 去掉 @（见 memberStateKey）——否则管理员给别人设等级会被 Matrix 403 拦
  await (mx as any).sendStateEvent(rid, MEMBER_EVENT_TYPE, content, memberStateKey(userId))
}

/* =====================================================================
 *  管理后台 · 功能门控（按会员等级限制能力）
 *  存储：控制室 state event `cosmac.gating`，{ gates: { capabilityKey: levelSlug } }。
 *  管理员逐项配「能力→最低等级」，bot 读取并**服务端强制**（前端只做展示/配置）。
 *  未配置的能力取目录里的 default。新增可门控能力 = 往 GATE_CATALOG 加一条（前后端各加）。
 * ===================================================================== */

/** 控制室里「功能门控策略」state event 的类型（与 bot 端 GATING_EVENT_TYPE 一致）。 */
const GATING_EVENT_TYPE = 'cosmac.gating'

/** 门槛阶梯（下拉可选项；与 bot 端 GATE_LEVELS 一致）。free<paid<creator<admin。 */
export const GATE_LEVELS: { slug: string; label: string }[] = [
  { slug: 'free', label: '免费可用（所有人）' },
  { slug: 'paid', label: '付费会员及以上' },
  { slug: 'creator', label: '创作者会员' },
  { slug: 'admin', label: '仅平台管理员' },
]

/** 可门控能力目录（与 bot 端 GATE_CATALOG 一致；key 稳定、default 为未配置时的默认门槛，group 用于后台分组展示）。 */
export const GATE_CATALOG: { key: string; label: string; default: string; group: string }[] = [
  { key: 'ai_chat', label: '基础 AI 对话（@中枢AI / 私聊回复）', default: 'free', group: 'AI 对话与检索' },
  { key: 'knowledge', label: '知识库（RAG 检索 + 知识命令）', default: 'free', group: 'AI 对话与检索' },
  { key: 'memory', label: '长期记忆（AI 跨多轮/跨天记得你）', default: 'paid', group: 'AI 对话与检索' },
  { key: 'web_search', label: '联网搜索（外部 API、共享凭据有成本）', default: 'paid', group: 'AI 对话与检索' },
  { key: 'custom_skill', label: '自定义技能（用聊天命令建/管理自己的技能）', default: 'paid', group: 'AI 对话与检索' },
  { key: 'custom_agent', label: '自建智能体（我的AI工坊创建 Agent）', default: 'paid', group: 'AI 对话与检索' },
  { key: 'create_room', label: '建群 / 频道', default: 'free', group: '任务编排与协作' },
  { key: 'task_board', label: 'AI 拆解任务到看板', default: 'paid', group: '任务编排与协作' },
  { key: 'assemble_team', label: '一键建专班（AI 组队 + 派单）', default: 'paid', group: '任务编排与协作' },
  { key: 'people_manage', label: '个人协作人名册（给常合作的人加能力，供 AI 派单）', default: 'paid', group: '任务编排与协作' },
  { key: 'workflow_run', label: '跑工作流（外部/付费、共享凭据）', default: 'admin', group: '自动化' },
  { key: 'doc_read', label: '图文教程（查看平台图文内容）', default: 'paid', group: '内容' },
  { key: 'market_acquire', label: 'AI Agent 商城（获取技能/智能体到工坊）', default: 'free', group: '商城与资源' },
  // 人事/员工（HR）数据查询：涉及薪资、绩效等敏感信息，默认仅平台管理员可查（可在后台调低）。
  { key: 'hr_data', label: '人事数据查询（花名册/薪酬/绩效/考勤·敏感）', default: 'admin', group: '数据智能' },
  // 销售业绩数据查询：销售额/签单/完成率等经营敏感信息，默认仅平台管理员可查。
  { key: 'sales_data', label: '销售业绩查询（销售额/签单/完成率·敏感）', default: 'admin', group: '数据智能' },
]

/** 门控策略 map：能力 key → 门槛 slug。 */
export type GatingMap = Record<string, string>

/* ===== 用量配额（变现第二步；与 bot 端 cosmac/quotas.py QUOTA_CATALOG 一致）===== */
const QUOTAS_EVENT_TYPE = 'cosmac.quotas'
/** 计量项目录：每项按会员等级配上限，-1=不限。group 用于分组展示。 */
export const QUOTA_CATALOG: { key: string; label: string; unit: string; group: string; defaults: Record<string, number> }[] = [
  { key: 'ai_msg_daily', label: 'AI 对话（每天）', unit: '条/天', group: 'AI', defaults: { free: 30, paid: -1, creator: -1 } },
  { key: 'storage_mb', label: '存储空间', unit: 'MB', group: '存储', defaults: { free: 100, paid: 1024, creator: 5120 } },
  { key: 'kb_docs', label: '知识库文档数', unit: '篇', group: '知识库', defaults: { free: 5, paid: 200, creator: -1 } },
  { key: 'teams', label: '专班数（一键建专班）', unit: '个', group: '任务编排', defaults: { free: 1, paid: 20, creator: -1 } },
  { key: 'workflow_runs', label: '工作流运行（每月）', unit: '次/月', group: '自动化', defaults: { free: 0, paid: 200, creator: -1 } },
]

/** 我的用量（前端「我的额度」展示）：各计量项的 已用/上限。失败/未登录返回 []。 */
export interface UsageItem { key: string; label: string; unit: string; group: string; used: number; limit: number }
export async function getMyUsage(): Promise<UsageItem[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/usage/mine`, { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.usage) ? j.usage : []
  } catch {
    return []
  }
}
/** 用户给主 AI 的个人偏好画像（About me / Outputs）。 */
export interface MyAiProfile {
  about: string   // 我是谁（背景/职业/在做什么）
  style: string   // 希望 AI 怎么回答（语气/长度/语言/格式）
  extra: string   // 自由补充
  enabled: boolean // 总开关：关掉则主 AI 不注入
}

/** 读本人的 AI 偏好画像（bot 端点，前端够不到 cosmac DB）。失败/未设过 → 空白默认。 */
export async function getMyProfile(): Promise<MyAiProfile> {
  const empty: MyAiProfile = { about: '', style: '', extra: '', enabled: true }
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return empty
  try {
    const r = await fetch(`${payBase()}/cosmac/profile/me`, { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) return empty
    const j = await r.json().catch(() => ({}))
    const p = j?.profile || {}
    return {
      about: String(p.about || ''),
      style: String(p.style || ''),
      extra: String(p.extra || ''),
      enabled: p.enabled !== false,
    }
  } catch {
    return empty
  }
}

/** 保存本人的 AI 偏好画像。成功返回保存后的值；失败抛出带文案的错误。 */
export async function saveMyProfile(p: MyAiProfile): Promise<MyAiProfile> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('未登录')
  const r = await fetch(`${payBase()}/cosmac/profile/me`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      about: String(p.about || '').slice(0, 2000),
      style: String(p.style || '').slice(0, 2000),
      extra: String(p.extra || '').slice(0, 2000),
      enabled: p.enabled !== false,
    }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '保存失败')
  const sp = j?.profile || {}
  return {
    about: String(sp.about || ''),
    style: String(sp.style || ''),
    extra: String(sp.extra || ''),
    enabled: sp.enabled !== false,
  }
}

/** 配额 map：计量项 → 等级 → 上限（-1=不限）。 */
export type QuotaLimits = Record<string, Record<string, number>>

/** 读用量配额（控制室 state event，合并默认）；不存在→默认。 */
export async function getQuotas(): Promise<QuotaLimits> {
  const out: QuotaLimits = {}
  for (const q of QUOTA_CATALOG) out[q.key] = { ...q.defaults }
  if (!mx) return out
  const rid = await resolveControlRoom()
  if (!rid) return out
  try {
    const ev = await (mx as any).getStateEvent(rid, QUOTAS_EVENT_TYPE, '')
    const raw = (ev?.limits && typeof ev.limits === 'object') ? ev.limits : {}
    for (const q of QUOTA_CATALOG) {
      const cfg = raw[q.key] || {}
      for (const tier of Object.keys(out[q.key])) {
        if (typeof cfg[tier] === 'number') out[q.key][tier] = cfg[tier]
      }
    }
    return out
  } catch (e: any) {
    if (e?.errcode === 'M_NOT_FOUND') return out
    throw new Error('读取配额失败，请重试')
  }
}

/** 整体写入用量配额（必要时先建控制室）。 */
export async function setQuotas(limits: QuotaLimits): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, QUOTAS_EVENT_TYPE, { limits }, '')
}

/**
 * 读门控策略（合并默认）。控制室不存在 / 事件不存在(404) → 返回纯默认（合法）。
 * #3：**瞬时读失败（网络/权限）会抛异常**，绝不伪装成"默认配置"——否则管理员在默认值上
 * 一保存，就把真实付费策略覆盖没了。调用方（AdminView）catch 后应提示失败、禁止保存。
 */
export async function getGating(): Promise<GatingMap> {
  // 先铺默认
  const merged: GatingMap = {}
  for (const g of GATE_CATALOG) merged[g.key] = g.default
  if (!mx) return merged
  const rid = await resolveControlRoom()
  if (!rid) return merged
  try {
    const ev = await (mx as any).getStateEvent(rid, GATING_EVENT_TYPE, '')
    const gates = ev?.gates
    if (gates && typeof gates === 'object') {
      for (const g of GATE_CATALOG) {
        const v = gates[g.key]
        if (typeof v === 'string' && GATE_LEVELS.some((l) => l.slug === v)) merged[g.key] = v
      }
    }
    return merged
  } catch (e: any) {
    // 事件不存在(404)=还没配过门控 → 返回默认（合法）。其余=瞬时读失败 → 抛，别伪装成默认。
    if (e?.errcode === 'M_NOT_FOUND') return merged
    throw new Error('读取门控策略失败，请重试（避免在读取失败时把默认值覆盖真实策略）')
  }
}

/** 写门控策略（必要时先建控制室）。只写目录里的已知能力、合法门槛。bot ~15s 内读到生效。 */
export async function setGating(gates: GatingMap): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  const clean: GatingMap = {}
  for (const g of GATE_CATALOG) {
    const v = gates[g.key]
    if (typeof v === 'string' && GATE_LEVELS.some((l) => l.slug === v)) clean[g.key] = v
  }
  await (mx as any).sendStateEvent(rid, GATING_EVENT_TYPE, { gates: clean }, '')
}

/** 一条「全局技能」定义（管理后台编辑、主 AI 注入）。slug 在全局内唯一。 */
export interface GlobalSkill {
  slug: string
  name: string
  description: string
  instructions: string
  enabled: boolean
  /** 可用范围(资源级权限,bot 服务端强制):''=所有人;paid/creator=该会员等级及以上;
   *  admin=仅平台管理员;'tpl:slugA,slugB'=仅选了这些入驻模板的用户。 */
  access?: string
  /** 生效方式:'global'(默认)=每轮对话全局注入(慎用,占 6000 字符预算);
   *  'agent'=只在被绑定的 AI 同事(Agent)激活时注入,平时零干扰。 */
  inject?: string
  /** 仅预置技能带:true=平台内置(代码里),后台展示但不可删,可"覆盖为自定义"。 */
  preset?: boolean
  /** 仅预置技能带:绑了这个技能的 AI 同事名(展示"随【文案】激活")。 */
  agents?: string[]
}

/** 读全局技能列表（控制室 state event）；房间/事件不存在时返回 []。 */
export async function getGlobalSkills(): Promise<GlobalSkill[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, SKILLS_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.skills) ? ev.skills : []
    return arr.map((s: any) => ({
      slug: String(s?.slug || ''),
      name: String(s?.name || ''),
      description: String(s?.description || ''),
      instructions: String(s?.instructions || ''),
      enabled: s?.enabled !== false, // 缺省视为启用
      access: String(s?.access || ''),
      inject: String(s?.inject || ''),
    })).filter((s: GlobalSkill) => s.slug)
  } catch (e: any) {
    // 事件不存在(404)=还没写过技能 → []（合法）。瞬时读失败必须抛——否则上层会在空列表上
    // 保存、把真实技能覆盖没了（同 gating/plans 的保护）。
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取技能列表失败，请重试')
  }
}

/** 读**内置预置技能库**（走 bot 端点；代码内置，控制室读不到）。失败/未登录返回 []。
 *  这些技能标 preset=true / inject='agent'（随绑定的 AI 同事激活，不全局注入）。 */
export async function getPresetSkills(): Promise<GlobalSkill[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/skills/presets`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    const arr = Array.isArray(j?.skills) ? j.skills : []
    return arr.map((s: any) => ({
      slug: String(s?.slug || ''),
      name: String(s?.name || ''),
      description: String(s?.description || ''),
      instructions: String(s?.instructions || ''),
      enabled: s?.enabled !== false,
      access: String(s?.access || ''),
      inject: String(s?.inject || 'agent'),
      preset: true,
      agents: Array.isArray(s?.agents) ? s.agents.map(String) : [],
    })).filter((s: GlobalSkill) => s.slug)
  } catch {
    return []
  }
}

// 全局技能容量上限（与 bot 端 skill_cmd 一致；防刷爆模型上下文 / state event 过大）
const MAX_GLOBAL_SKILLS = 50
const MAX_SKILL_INSTRUCTIONS = 2000
const MAX_SKILL_NAME = 80
const MAX_SKILL_SLUG = 64

/**
 * 整体写入全局技能列表（必要时先建控制室）。主 AI 约 20 秒内读到并热生效。
 * 写前**校验 + 规范化**：数量/正文长度上限，且把每个字段强制成字符串——脏数据
 * （如 name 是数字）从源头就写不进去，bot 渲染时也不会因此崩/不回复。
 */
export async function setGlobalSkills(skills: GlobalSkill[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  if (skills.length > MAX_GLOBAL_SKILLS) {
    throw new Error(`全局技能最多 ${MAX_GLOBAL_SKILLS} 个（当前 ${skills.length}）`)
  }
  const clean = skills.map((s) => {
    const slug = String(s.slug ?? '').trim().slice(0, MAX_SKILL_SLUG)
    if (!slug) throw new Error('技能标识（slug）不能为空')
    const instructions = String(s.instructions ?? '')
    if (instructions.length > MAX_SKILL_INSTRUCTIONS) {
      throw new Error(
        `技能「${slug}」正文超长（最多 ${MAX_SKILL_INSTRUCTIONS} 字，当前 ${instructions.length}）`,
      )
    }
    const inject = String(s.inject ?? '').trim()
    return {
      slug,
      name: String(s.name ?? '').trim().slice(0, MAX_SKILL_NAME),
      description: String(s.description ?? '').trim(),
      instructions,
      enabled: s.enabled !== false,
      access: String(s.access ?? '').trim().slice(0, 256),
      // 只存 'agent'(随AI同事激活);'global'/空都视为全局注入,存空省字节且兼容旧数据
      inject: inject === 'agent' ? 'agent' : '',
    }
  })
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, SKILLS_EVENT_TYPE, { skills: clean }, '')
}

/** 一个「智能体(Agent)」定义 = 一套人设 + 模型覆盖 + 绑定的技能集。slug 全局唯一。 */
export interface GlobalAgent {
  slug: string
  name: string
  description: string
  system_prompt: string
  model: string
  skill_slugs: string[]
  enabled: boolean
  /** 可用范围(同 GlobalSkill.access):''=所有人;paid/creator=等级及以上;admin;tpl:slug列表。 */
  access?: string
  /** 预置库专用:true=平台内置(代码);division=分组(营销/销售…,空=通用班底)。 */
  preset?: boolean
  division?: string
}

/** 列内置预置 Agent 库(原生班底+agency 引入,后台「智能体」页只读展示)。失败返回 []。 */
export async function getPresetAgents(): Promise<GlobalAgent[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/agents/presets`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.agents) ? j.agents : []
  } catch { return [] }
}

/* —— AI Agent 商城：平台真实资源目录（走 bot 端点 /cosmac/market/catalog）——
 *  普通用户读不了控制室 state，由 bot 代读并按发起人标注解锁状态（access/门控在服务端裁决）。
 *  「获取」状态存本人 account data（每账号轻量配置的标准位置，刷新/换端不丢）。 */

/** 商城里的一条资源（后端只下发橱窗字段，人设/技能正文/工作流 url 等敏感内容拿不到）。 */
export interface MarketCatalogItem {
  kind: 'agent' | 'skill' | 'workflow' | 'knowledge'
  slug: string
  name: string
  description: string
  /** 解锁要求：''=免费；paid/creator=该会员等级及以上；tpl:…=指定入驻模板；admin=仅管理员 */
  access: string
  /** 服务端按发起人（等级/模板/管理员）算好的：当前用户现在就能用吗 */
  unlocked: boolean
  /** 本人是否已「获取」（存 cosmac DB，主 AI 名册据此优先派单） */
  acquired: boolean
  /** true=平台内置（官方），false=平台运营在后台配置的 */
  official: boolean
  division?: string
  skill_count?: number
  /** 技能专用：随哪些 AI 同事激活（使用指引用） */
  agents?: string[]
  inject?: string
  platform?: string
  input_hint?: string
}

export interface MarketCatalog {
  items: MarketCatalogItem[]
  tier: string
  tierLabel: string
  isAdmin: boolean
}

/** 拉商城目录。未登录/失败返回 null（前端显示重试，绝不回落假数据）。 */
export async function fetchMarketCatalog(): Promise<MarketCatalog | null> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return null
  try {
    const r = await fetch(`${payBase()}/cosmac/market/catalog`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return null
    const j = await r.json().catch(() => ({}))
    const arr = Array.isArray(j?.items) ? j.items : []
    return {
      items: arr.map((i: any) => ({
        kind: String(i?.kind || '') as MarketCatalogItem['kind'],
        slug: String(i?.slug || ''),
        name: String(i?.name || ''),
        description: String(i?.description || ''),
        access: String(i?.access || ''),
        unlocked: !!i?.unlocked,
        acquired: !!i?.acquired,
        official: !!i?.official,
        division: String(i?.division || ''),
        skill_count: Number(i?.skill_count || 0),
        agents: Array.isArray(i?.agents) ? i.agents.map(String) : [],
        inject: String(i?.inject || ''),
        platform: String(i?.platform || ''),
        input_hint: String(i?.input_hint || ''),
      })).filter((i: MarketCatalogItem) => i.slug && i.kind),
      tier: String(j?.tier || 'free'),
      tierLabel: String(j?.tier_label || '免费会员'),
      isAdmin: !!j?.is_admin,
    }
  } catch { return null }
}

// 插件安装记录的 account data 类型（cc.* 前缀=GuDuu OS 客户端自定义，非协议字段）
const MARKET_ACCOUNT_DATA = 'cc.cosmac.market' // 旧版「获取」存这里,现已迁 cosmac DB(仅迁移时读)
const PLUGINS_ACCOUNT_DATA = 'cc.cosmac.plugins'

/** 已获取列表里的一条（服务端已对照货架补全名称/描述；stale=资源已下架）。 */
export interface AcquiredItem {
  kind: MarketCatalogItem['kind']
  slug: string
  name: string
  description: string
  unlocked: boolean
  stale: boolean
  agents: string[]
}

/** 拉本人全部「已获取」（我的AI工坊「已获取」区用）。未登录/失败返回 null。 */
export async function fetchMarketAcquired(): Promise<AcquiredItem[] | null> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return null
  try {
    const r = await fetch(`${payBase()}/cosmac/market/acquired`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return null
    const j = await r.json().catch(() => ({}))
    const arr = Array.isArray(j?.items) ? j.items : []
    return arr.map((i: any) => ({
      kind: String(i?.kind || 'agent') as AcquiredItem['kind'],
      slug: String(i?.slug || ''),
      name: String(i?.name || ''),
      description: String(i?.description || ''),
      unlocked: !!i?.unlocked,
      stale: !!i?.stale,
      agents: Array.isArray(i?.agents) ? i.agents.map(String) : [],
    })).filter((i: AcquiredItem) => i.slug)
  } catch { return null }
}

/** 获取 / 移除获取 某个商城资源（写 cosmac DB，主 AI 名册立刻感知）。
 *  返回空串=成功，否则是给用户看的错误文案。 */
export async function setMarketItemAcquired(
  kind: string, slug: string, acquired: boolean,
): Promise<string> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return '登录已失效，请重新登录'
  try {
    const r = await fetch(`${payBase()}/cosmac/market/acquire`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ kind, slug, acquired }),
    })
    const j = await r.json().catch(() => ({}))
    return r.ok ? '' : String(j?.error || '操作失败，请稍后重试')
  } catch { return '网络异常，请稍后重试' }
}

/** 一次性迁移：把旧版存在 account data 里的「已获取」搬进服务端（幂等，尽力而为）。
 *  旧版只上线过很短时间；迁完打标记不再重复跑。 */
export async function migrateLegacyAcquired(): Promise<void> {
  try {
    const c = (mx as any)?.getAccountData?.(MARKET_ACCOUNT_DATA)?.getContent?.() || {}
    if (c?.migrated) return
    const ids: string[] = Array.isArray(c?.acquired) ? c.acquired.map(String) : []
    for (const id of ids) {
      const [kind, slug] = id.split(':', 2)
      if (kind && slug) await setMarketItemAcquired(kind, slug, true)
    }
    if (ids.length) await (mx as any)?.setAccountData?.(MARKET_ACCOUNT_DATA, { migrated: true })
  } catch { /* 迁不动就算了,用户重新点一次获取即可 */ }
}

/** 读本人在「插件商城」装过的插件 id 列表（刷新/换端恢复插件栏用）。 */
export function getInstalledPlugins(): string[] {
  try {
    const c = (mx as any)?.getAccountData?.(PLUGINS_ACCOUNT_DATA)?.getContent?.() || {}
    return Array.isArray(c?.installed) ? c.installed.map(String) : []
  } catch { return [] }
}

/** 整体写回已装插件列表（失败静默，最多退化成"刷新后要重装"）。 */
export async function setInstalledPlugins(ids: string[]): Promise<void> {
  try { await (mx as any)?.setAccountData?.(PLUGINS_ACCOUNT_DATA, { installed: ids }) } catch { /* 忽略 */ }
}

/** 读全局智能体列表（控制室 state event）；房间/事件不存在时返回 []。 */
export async function getGlobalAgents(): Promise<GlobalAgent[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, AGENTS_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.agents) ? ev.agents : []
    return arr.map((a: any) => ({
      slug: String(a?.slug || ''),
      name: String(a?.name || ''),
      description: String(a?.description || ''),
      system_prompt: String(a?.system_prompt || ''),
      model: String(a?.model || ''),
      skill_slugs: Array.isArray(a?.skill_slugs) ? a.skill_slugs.map(String) : [],
      enabled: a?.enabled !== false,
      access: String(a?.access || ''),
    })).filter((a: GlobalAgent) => a.slug)
  } catch (e: any) {
    // 同 getGlobalSkills：404=未配置→[]；瞬时失败抛，防空列表覆盖真实智能体。
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取智能体列表失败，请重试')
  }
}

/** 整体写入全局智能体列表（必要时先建控制室）。 */
export async function setGlobalAgents(agents: GlobalAgent[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, AGENTS_EVENT_TYPE, { agents }, '')
}

/** 一条「人员能力」名册项：admin 给真人成员登记能力备注，主 AI 拆任务时据此匹配（模块3.5）。 */
export interface Person {
  user_id: string
  name: string
  role: string
  expertise: string
  note: string
  enabled: boolean
  /** 休假/暂不可用：为 true 时主 AI 不派单给 TA，逾期提醒会升级给下达者建议改派 */
  unavailable?: boolean
}

/** 读人员能力名册（控制室 state event）；不存在时返回 []。 */
export async function getPeople(): Promise<Person[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, PEOPLE_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.people) ? ev.people : []
    return arr.map((p: any) => ({
      user_id: String(p?.user_id || ''),
      name: String(p?.name || ''),
      role: String(p?.role || ''),
      expertise: String(p?.expertise || ''),
      note: String(p?.note || ''),
      enabled: p?.enabled !== false,
    })).filter((p: Person) => p.user_id)
  } catch (e: any) {
    // 同 getGlobalAgents：404=未配置→[]；瞬时失败抛，防空列表覆盖真实名册。
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取人员能力名册失败，请重试')
  }
}

/** 整体写入人员能力名册（必要时先建控制室）。user_id 必填，其余可空。 */
export async function setPeople(people: Person[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const clean = people
    .map((p) => ({
      user_id: String(p.user_id || '').trim(),
      name: String(p.name || '').trim().slice(0, 64),
      role: String(p.role || '').trim().slice(0, 64),
      expertise: String(p.expertise || '').trim().slice(0, 500),
      note: String(p.note || '').trim().slice(0, 500),
      enabled: p.enabled !== false,
    }))
    .filter((p) => p.user_id)
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, PEOPLE_EVENT_TYPE, { people: clean }, '')
}

/** 一条「全局规则」：平台级硬约束，主 AI 在所有群都须遵守。 */
export interface GlobalRule {
  text: string
  enabled: boolean
}

/** 读全局规则列表（控制室 state event）；不存在时返回 []。 */
export async function getGlobalRules(): Promise<GlobalRule[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, RULES_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.rules) ? ev.rules : []
    return arr
      .map((r: any) => ({ text: String(r?.text || ''), enabled: r?.enabled !== false }))
      .filter((r: GlobalRule) => r.text.trim())
  } catch (e: any) {
    // 404=未配置→[]；瞬时失败抛，防空列表覆盖真实规则。
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取全局规则失败，请重试')
  }
}

/** 整体写入全局规则列表（必要时先建控制室）。 */
export async function setGlobalRules(rules: GlobalRule[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, RULES_EVENT_TYPE, { rules }, '')
}

/** 一个「工作流连接器」定义（对接 n8n/Make/Dify/Coze 等外部平台）。 */
export interface WorkflowDef {
  slug: string
  name: string
  platform: string          // webhook（n8n/Make/自建） | dify | coze
  url: string
  method: string            // POST/GET（webhook 用）
  cred: string              // 凭据名（真值在服务端 env COSMAC_WF_<CRED>；这里只放名字）
  input_hint: string
  enabled: boolean
  mode: string              // dify: workflow|chat
  ref_id: string            // coze: workflow_id
  input_key: string         // dify/coze: 输入变量名（默认 input）
  graph: string             // comfyui: API 格式工作流 JSON，用 {{input}} 占位
  async: boolean            // webhook: 长任务异步——提交后等平台回调，不同步等结果
}

/** 读工作流连接器列表（控制室 state event）；不存在返回 []。 */
export async function getWorkflows(): Promise<WorkflowDef[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, WORKFLOWS_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.workflows) ? ev.workflows : []
    return arr.map((w: any) => ({
      slug: String(w?.slug || ''),
      name: String(w?.name || ''),
      platform: String(w?.platform || 'webhook'),
      url: String(w?.url || ''),
      method: String(w?.method || 'POST'),
      cred: String(w?.cred || ''),
      input_hint: String(w?.input_hint || ''),
      enabled: w?.enabled !== false,
      mode: String(w?.mode || 'workflow'),
      ref_id: String(w?.ref_id || ''),
      input_key: String(w?.input_key || ''),
      graph: String(w?.graph || ''),
      async: w?.async === true,
    })).filter((w: WorkflowDef) => w.slug)
  } catch (e: any) {
    // 404=未配置→[]；瞬时失败抛，防空列表覆盖真实工作流连接器。
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取工作流列表失败，请重试')
  }
}

/** 整体写入工作流连接器列表（必要时先建控制室）。 */
export async function setWorkflows(workflows: WorkflowDef[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, WORKFLOWS_EVENT_TYPE, { workflows }, '')
}

/* =====================================================================
 *  管理后台 · 入驻模板（注册引导可选的「方案」）
 *  管理员在后台定义一组模板，每个打包：模型/人设/RULE/技能/知识库/频道/工作流/所需会员等级。
 *  前台首次引导读它、用户选一个 → 实例化成工作区（P2 做）。存控制室 state event
 *  `cosmac.onboarding_templates`（管理员写、引导读，同 skills/agents/workflows 套路）。
 * ===================================================================== */
const ONBOARDING_TEMPLATES_EVENT_TYPE = 'cosmac.onboarding_templates'

/** 入驻模板定义（后台配置）。 */
export interface OnboardingTemplateDef {
  key: string            // 稳定标识（程序引用，建后不改）
  label: string          // 展示名（如「影视 / 内容工作室」）
  icon: string           // emoji 图标
  desc: string           // 一句话说明
  model: string          // 模型 id（空 = 跟随全局 AI 配置）
  persona: string        // AI 人设（system prompt）
  rules: string          // 基础 RULE（平台硬约束，多行文本）
  skillSlugs: string[]   // 绑定的技能 slug（从技能库选）
  kbDocs: { title: string; content: string }[] // 预置知识库文档
  channels: string[]     // 初始频道名
  workflowSlugs: string[] // 默认工作流 slug
  tier: string           // 所需最低会员等级 slug（free/paid/creator）
  enabled: boolean       // 是否上架（可在引导里被选）
}

/** 读后台入驻模板列表（首次引导用）。
 *
 * #9：模板存**私有控制室**，普通用户直接读 state 必 403 → 后台配的模板对新注册用户永远失效。
 * 改走 bot 端点 /cosmac/onboarding/templates（bot 是控制室成员、代读并只返回已上架模板）。
 * 未登录/未配置/读失败返回 []（调用方据此回退内置模板）。 */
export async function getOnboardingTemplates(): Promise<OnboardingTemplateDef[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/onboarding/templates`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    const arr = Array.isArray(j?.templates) ? j.templates : []
    return arr.map((t: any) => ({
      key: String(t?.key || ''),
      label: String(t?.label || ''),
      icon: String(t?.icon || '🧩'),
      desc: String(t?.desc || ''),
      model: String(t?.model || ''),
      persona: String(t?.persona || ''),
      rules: String(t?.rules || ''),
      skillSlugs: Array.isArray(t?.skillSlugs) ? t.skillSlugs.map(String) : [],
      kbDocs: Array.isArray(t?.kbDocs)
        ? t.kbDocs.map((d: any) => ({ title: String(d?.title || ''), content: String(d?.content || '') }))
        : [],
      channels: Array.isArray(t?.channels) ? t.channels.map(String) : [],
      workflowSlugs: Array.isArray(t?.workflowSlugs) ? t.workflowSlugs.map(String) : [],
      tier: String(t?.tier || 'free'),
      enabled: t?.enabled !== false,
    })).filter((t: OnboardingTemplateDef) => t.key && t.label)
  } catch {
    return []
  }
}

/** 写后台入驻模板列表（整体覆盖；需管理员）。 */
export async function setOnboardingTemplates(templates: OnboardingTemplateDef[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  await (mx as any).sendStateEvent(rid, ONBOARDING_TEMPLATES_EVENT_TYPE, { templates }, '')
}

/* =====================================================================
 *  管理后台 · 会员套餐（模块4 交易系统）
 *  存储：控制室 state event `cosmac.plans`，{ plans: [{slug,name,tier,period_days,prices,enabled}] }。
 *  价格按货币存**最小单位整数(分/cent)**；前端编辑用元、保存时 ×100 取整。
 * ===================================================================== */

const PLANS_EVENT_TYPE = 'cosmac.plans'

/** 套餐支持的货币（与后端解析一致；prices 的 key 用小写 code）。 */
export const PLAN_CURRENCIES: { code: string; label: string }[] = [
  { code: 'usd', label: 'USD($)' },
  { code: 'cny', label: 'CNY(¥)' },
  { code: 'usdt', label: 'USDT' },
]

/** 一个会员套餐（管理后台编辑）。prices：货币 code → **分**(整数)。 */
export interface PlanDef {
  slug: string
  name: string
  tier: string                 // paid | creator（不能是 free）
  period_days: number
  prices: Record<string, number>  // 货币 → 分(cent)
  enabled: boolean
}

/**
 * 读套餐列表（控制室 state event）。事件不存在(404)→[]；**瞬时读失败抛异常**——
 * 否则管理员会在空列表上保存、把真实套餐覆盖没了（同 gating 的保护）。
 */
export async function getPlans(): Promise<PlanDef[]> {
  if (!mx) return []
  const rid = await resolveControlRoom()
  if (!rid) return []
  try {
    const ev = await (mx as any).getStateEvent(rid, PLANS_EVENT_TYPE, '')
    const arr = Array.isArray(ev?.plans) ? ev.plans : []
    return arr.map((p: any) => {
      const prices: Record<string, number> = {}
      if (p?.prices && typeof p.prices === 'object') {
        for (const [cur, cents] of Object.entries(p.prices)) {
          const c = Math.trunc(Number(cents))
          if (Number.isFinite(c) && c > 0) prices[String(cur).toLowerCase()] = c
        }
      }
      return {
        slug: String(p?.slug || ''),
        name: String(p?.name || ''),
        tier: p?.tier === 'creator' ? 'creator' : 'paid',
        period_days: Math.max(1, Math.trunc(Number(p?.period_days) || 30)),
        prices,
        enabled: p?.enabled !== false,
      }
    }).filter((p: PlanDef) => p.slug)
  } catch (e: any) {
    if (e?.errcode === 'M_NOT_FOUND') return []
    throw new Error('读取套餐失败，请重试（避免在读取失败时把空列表覆盖真实套餐）')
  }
}

/* —— 用户侧「升级会员」：调 bot 的 /cosmac/pay/* 端点（前端够不到 cosmac DB）——
 *  base = homeserver(hs.cosmac.cc)，nginx 已把 /cosmac/ 代理给 bot。 */

function payBase(): string {
  return String((mx as any)?.baseUrl || '').replace(/\/$/, '')
}

/* —— 自建邮箱验证码注册：调 bot 的 /cosmac/register/* 端点 ——
 *  注意：注册发生在**登录前**，此时 mx 还没建，拿不到 baseUrl，
 *  所以这两个函数必须由调用方传入 homeserver 基址（前端的 HS 常量）。 */

/** 请求把验证码发到邮箱。返回 {ok} 或抛出带后端文案的错误。 */
/** 拿认证前端配置（是否启用 Turnstile + site key）。失败/未启用返回关闭态,不影响现有流程。 */
export async function getAuthConfig(baseUrl: string): Promise<{ turnstile: boolean; siteKey: string }> {
  try {
    const base = baseUrl.replace(/\/$/, '')
    const r = await fetch(`${base}/cosmac/auth/config`)
    if (!r.ok) return { turnstile: false, siteKey: '' }
    const j = await r.json()
    return { turnstile: !!j?.turnstile, siteKey: j?.turnstile_site_key || '' }
  } catch { return { turnstile: false, siteKey: '' } }
}

export async function registerRequestCode(baseUrl: string, email: string, turnstile = ''): Promise<number> {
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/register/request-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, turnstile }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e: any = new Error(j?.error || '发送验证码失败')
    // 后端在"发送太频繁"时会带 cooldown 剩余秒数,透传给调用方去走按钮倒计时
    if (typeof j?.cooldown === 'number') e.cooldown = j.cooldown
    throw e
  }
  return typeof j?.cooldown === 'number' ? j.cooldown : 60
}

/** 验码 + 建号。成功返回后端 body（含 user_id）；失败抛出带文案的错误。 */
export async function registerVerify(
  baseUrl: string,
  args: { email: string; code: string; username: string; password: string },
): Promise<Record<string, any>> {
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/register/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '注册失败')
  // L18：注册接口已返回可用会话(access_token/user_id/device_id)——直接用它引导会话，避免调用方
  // 再 loginNoStart 多建一个 device/token。老后端若没回 token，调用方据返回值回退到登录。
  if (j?.access_token && j?.user_id) saveSession(baseUrl, j)
  return j
}

/* —— 找回密码：调 bot 的 /cosmac/reset/* 端点（同样登录前调，需传 HS 基址）—— */

/** 请求把找回密码验证码发到邮箱。防枚举：未注册也回成功（不报错）。 */
export async function resetRequestCode(baseUrl: string, email: string, turnstile = ''): Promise<number> {
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/reset/request-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, turnstile }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e: any = new Error(j?.error || '发送验证码失败')
    if (typeof j?.cooldown === 'number') e.cooldown = j.cooldown
    throw e
  }
  return typeof j?.cooldown === 'number' ? j.cooldown : 60
}

/** 入驻引导：把模板预置文档灌进本人个人知识库（引导是登录后跑的，用当前会话 token）。
 *  best-effort：返回入库篇数；失败返回 0、不抛错（不阻断引导）。 */
export async function onboardIngestKb(
  docs: { title: string; content: string }[],
): Promise<number> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token || !docs.length) return 0
  try {
    const r = await fetch(`${payBase()}/cosmac/onboard/ingest-kb`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ docs }),
    })
    const j = await r.json().catch(() => ({}))
    return Number(j?.ingested) || 0
  } catch {
    return 0
  }
}

/** 列本人个人知识库文档（给 AI 侧栏「项目文件」展示 + 知识库管理）。失败/未登录返回 []。 */
export async function kbListMine(): Promise<{ id: number; title: string; source: string }[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/kb/list`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.docs) ? j.docs : []
  } catch {
    return []
  }
}

/** 给本人个人知识库添加一篇文档（标题+正文）。成功返回切块数；失败抛出带文案的错误。 */
export async function kbAddMine(title: string, content: string): Promise<number> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/kb/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ title, content }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '入库失败')
  return Number(j?.chunks) || 0
}

/** 删除本人个人知识库里的一篇文档（按 id）。失败抛出带文案的错误。 */
export async function kbDeleteMine(id: number): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/kb/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ id }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '删除失败')
}

/** 上传前的存储空间预检(软管控:附件直连 Synapse,bot 不在链路上,前端配合把关)。
 *  返回 {ok, used_mb, limit_mb, error?};查询失败按放行处理(别因网络抖动拦住正常上传)。 */
export async function storageCheck(addBytes: number): Promise<{ ok: boolean; error?: string }> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return { ok: true }
  try {
    const r = await fetch(`${payBase()}/cosmac/usage/storage-check?bytes=${Math.max(0, Math.floor(addBytes))}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return { ok: true }
    const j = await r.json().catch(() => ({}))
    return { ok: j?.ok !== false, error: j?.error }
  } catch { return { ok: true } }
}

/* ===== 用户自建 智能体/技能(我的AI工坊;归属本人账号,计入存储空间) ===== */

export interface MyAgent {
  slug: string; name: string; description: string; system_prompt: string
  model?: string; enabled: boolean
}
export interface MySkill {
  slug: string; name: string; description: string; instructions: string; enabled: boolean
}

async function _myGet(path: string, key: string): Promise<any[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}${path}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.[key]) ? j[key] : []
  } catch { return [] }
}
async function _myPost(path: string, body: any): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || j?.ok === false) throw new Error(j?.error || '操作失败')
}

export const myAgentsList = () => _myGet('/cosmac/my/agents', 'agents') as Promise<MyAgent[]>
export const myAgentSave = (a: MyAgent) => _myPost('/cosmac/my/agents/save', a)
export const myAgentDelete = (slug: string) => _myPost('/cosmac/my/agents/delete', { slug })
export const mySkillsList = () => _myGet('/cosmac/my/skills', 'skills') as Promise<MySkill[]>
export const mySkillSave = (s: MySkill) => _myPost('/cosmac/my/skills/save', s)
export const mySkillDelete = (slug: string) => _myPost('/cosmac/my/skills/delete', { slug })

/* ===== 频道知识库（SCOPE_ROOM：频道管理面板「知识库」页上传的文档，本频道 AI 检索自动命中）===== */

/** 列本频道已上传的知识库文档。失败/无权返回 []。 */
export async function kbRoomList(roomId: string): Promise<{ id: number; title: string; source: string }[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token || !roomId) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/kb/room/list?room_id=${encodeURIComponent(roomId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.docs) ? j.docs : []
  } catch {
    return []
  }
}

/** 给本频道知识库添加一篇文档（标题+正文）。成功返回切块数；失败抛出带文案的错误。 */
export async function kbRoomAdd(roomId: string, title: string, content: string): Promise<number> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/kb/room/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ room_id: roomId, title, content }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '入库失败')
  return Number(j?.chunks) || 0
}

/** 删本频道知识库里的一篇文档（按 id）。失败抛出带文案的错误。 */
export async function kbRoomDelete(roomId: string, id: number): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/kb/room/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ room_id: roomId, id }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '删除失败')
}

/* ===== 平台共享知识库（阶段2：管理员后台维护，任何专班可绑 knowledge=['platform']）===== */

/** 列平台共享知识库文档（仅管理员）。失败/无权返回 []。 */
export async function platformKbList(): Promise<{ id: number; title: string; source: string }[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/platform-kb/list`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.docs) ? j.docs : []
  } catch {
    return []
  }
}

/** 给平台共享知识库添加一篇文档。成功返回切块数；失败抛出带文案的错误。 */
export async function platformKbAdd(title: string, content: string): Promise<number> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/platform-kb/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ title, content }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '入库失败')
  return Number(j?.chunks) || 0
}

/** 删除平台共享知识库一篇文档（按 id）。失败抛出带文案的错误。 */
export async function platformKbDelete(id: number): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/platform-kb/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ id }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '删除失败')
}

/* ===== 个人协作人能力名册（模块3.5：普通用户在前台维护，主 AI 派单时合并进名册）===== */
export interface MyPerson {
  user_id: string; name: string; role: string; expertise: string; note: string; enabled: boolean
  source?: string   // 'global'=管理员后台全局名册叠加来的(平台预设,本人保存后转为个人记录)
  /** true=这条个人记录**覆盖**了平台预设(同一人后台也设了能力);global_* 为被覆盖的平台值 */
  overrides_global?: boolean
  global_role?: string
  global_expertise?: string
}

/** 列本人维护的协作人；失败/未登录返回 []。 */
export async function myPeopleList(): Promise<MyPerson[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/people/mine`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json().catch(() => ({}))
    return Array.isArray(j?.people) ? j.people : []
  } catch {
    return []
  }
}

/** 新增/更新一个协作人的能力备注。失败抛出带文案的错误。 */
export async function myPeopleAdd(p: {
  person_id: string; name?: string; role?: string; expertise?: string; note?: string; enabled?: boolean
}): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/people/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(p),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '保存失败')
}

/** 从本人名册删除某协作人（按完整 user_id）。失败抛出带文案的错误。 */
export async function myPeopleDelete(personId: string): Promise<void> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) throw new Error('登录已失效，请重新登录')
  const r = await fetch(`${payBase()}/cosmac/people/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ person_id: personId }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok || !j?.ok) throw new Error(j?.error || '删除失败')
}

/** 验码 + 重置密码。成功无返回；失败抛出带文案的错误。 */
export async function resetVerify(
  baseUrl: string,
  args: { email: string; code: string; password: string },
): Promise<void> {
  const base = baseUrl.replace(/\/$/, '')
  const r = await fetch(`${base}/cosmac/reset/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '重置失败')
}

export interface PayPlan {
  slug: string; name: string; tier: string; period_days: number
  prices: Record<string, number>
}

/** 公开读上架套餐（给「升级会员」面板展示）。 */
export async function payGetPlans(): Promise<PayPlan[]> {
  const r = await fetch(`${payBase()}/cosmac/pay/plans`)
  if (!r.ok) throw new Error('读取套餐失败')
  const j = await r.json().catch(() => ({}))
  return Array.isArray(j?.plans) ? j.plans : []
}

export interface PayMe { tier: string; tier_label: string; expires_ts: number }

/** 查"我当前的会员状态"（升级弹窗顶部展示）。未登录/失败返回 null。 */
export async function payGetMe(): Promise<PayMe | null> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return null
  try {
    const r = await fetch(`${payBase()}/cosmac/pay/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return null
    return await r.json()
  } catch { return null }
}

/** 平台真实运营指标（数据看板用；GuDuu OS 真正拥有的数据）。 */
export interface PlatformStats {
  members_paid: number; members_creator: number
  workflow_runs: number; orders_paid: number; kb_docs: number
}

export async function getPlatformStats(): Promise<PlatformStats | null> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return null
  try {
    const r = await fetch(`${payBase()}/cosmac/stats`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return null
    return await r.json()
  } catch { return null }
}

/** 员工花名册的一条（组织/人事页）。字段与后端 cosmac_employee 表英文键一致。 */
export interface Employee {
  emp_no: string; name: string; gender: string
  department: string; title: string; level: string; manager: string
  hire_date: string; status: string; resign_date: string
  city: string; salary: number; perf_rating: string
  annual_leave_total: number; annual_leave_used: number
  leave_days_month: number; overtime_hours_month: number
  education: string; birth_date: string
}

/** 人事页整包数据：公司名 + 概览 + 部门分组 + 员工列表。 */
export interface HrData {
  company: string
  summary: Record<string, any>
  departments: { 名称: string; 人数: number }[]
  employees: Employee[]
}

/** 拉人事花名册（仅平台管理员可读；非管理员/未登录返回 null，前端回退占位）。 */
export async function getHrEmployees(): Promise<HrData | null> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return null
  try {
    const r = await fetch(`${payBase()}/cosmac/hr/employees`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return null
    return await r.json()
  } catch { return null }
}

/** 任务看板的一条任务（AI 任务编排）。executor_kind/ref 是档2 的类型化执行者。 */
export interface TaskItem {
  id: number; title: string; assignee: string
  status: string; progress: number; goal: string; result: string
  executor_kind?: string; executor_ref?: string
  room_id?: string   // 所属频道(删频道前统计未完成任务用)
  space_id?: string  // 所属工作区(Space id)：看板按工作区过滤；空=存量无归属任务
  sender?: string    // 下达人 user_id：前端按工作区过滤时判断"我下达的"，别弄丢(L11)
  due_ts?: number | null   // 截止时间(epoch 秒,可空)——看板显示"还剩几天/已逾期"
}

export async function getTasks(): Promise<TaskItem[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return []
  try {
    const r = await fetch(`${payBase()}/cosmac/tasks`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) return []
    const j = await r.json()
    return Array.isArray(j?.tasks) ? j.tasks : []
  } catch { return [] }
}

/** 改任务状态/进度（看板手动操作）。返回是否成功。 */
export async function updateTask(
  id: number, patch: { status?: string; progress?: number },
): Promise<{ ok: boolean; error?: string }> {
  const token = (mx as any)?.getAccessToken?.() || ''
  if (!token) return { ok: false, error: '登录已失效，请重新登录' }
  try {
    const r = await fetch(`${payBase()}/cosmac/tasks/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ id, ...patch }),
    })
    if (r.ok) return { ok: true }
    // 把后端真实报错(如 401「登录已失效，请重新登录」/403「无权操作此任务」)带给 UI——
    // 旧版只回 boolean,点「开始」失败毫无反应,用户以为按钮坏了(线上实测:账号被停用后)。
    const j = await r.json().catch(() => ({}))
    return { ok: false, error: j?.error || `操作失败（${r.status}）` }
  } catch { return { ok: false, error: '网络异常，请稍后重试' } }
}

/* ===== 文档教学频道（类云文档）=====
 * 频道类型标记走 cosmac.channel_config.kind='doc'（侧栏据此识别）；页面正文存 cosmac DB，
 * 走 bot 的 /cosmac/doc/* 端点（带本人 token，写权限服务端按房间 power≥50 强制）。
 */

/** 文档频道里的一个页面（树节点）。content 仅在读单页时返回。 */
export interface DocPage {
  id: number
  parent_id: number | null
  title: string
  cover?: string        // 封面图(mxc:// 或 http(s) URL)；空=无封面
  published?: boolean   // 是否已发布(草稿=false，仅后台可见)
  sort: number
  updated_by: string
  excerpt?: string      // 列表卡片摘要(类公众号)
  updated_ts?: number   // 最后更新 unix 秒
  content_md?: string
}

/** 把封面值解析成可显示的 http 地址（mxc:// 走媒体代理；http(s) 原样）。 */
export function docCoverUrl(cover?: string, size = 600): string {
  if (!cover) return ''
  return cover.startsWith('mxc://') ? mxcToHttp(cover, size) : cover
}

function authHeaders(json = false): Record<string, string> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const h: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (json) h['Content-Type'] = 'application/json'
  return h
}

/** 读全局图文页面树（不含正文）+ 当前用户能否编辑。locked=被付费门控拦下(非付费会员)。 */
export async function docTree(): Promise<{ pages: DocPage[]; canWrite: boolean; locked: boolean }> {
  try {
    const r = await fetch(`${payBase()}/cosmac/doc/tree`, { headers: authHeaders() })
    if (r.status === 403) return { pages: [], canWrite: false, locked: true }
    if (!r.ok) return { pages: [], canWrite: false, locked: false }
    const j = await r.json()
    return {
      pages: Array.isArray(j?.pages) ? j.pages : [],
      canWrite: !!j?.can_write, locked: false,
    }
  } catch { return { pages: [], canWrite: false, locked: false } }
}

/** 读单页（含 Markdown 正文）。失败返回 null。 */
export async function docGetPage(id: number): Promise<DocPage | null> {
  try {
    const r = await fetch(`${payBase()}/cosmac/doc/page?id=${id}`, { headers: authHeaders() })
    if (!r.ok) return null
    return await r.json()
  } catch { return null }
}

/** 新建页面（写进全局图文）。需平台管理员。返回新页面（含正文）或抛错。 */
export async function docCreatePage(
  opts: { title?: string; parent_id?: number | null; content_md?: string; cover?: string } = {},
): Promise<DocPage> {
  const r = await fetch(`${payBase()}/cosmac/doc/page`, {
    method: 'POST', headers: authHeaders(true),
    body: JSON.stringify(opts),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '新建失败')
  return j
}

/** 改页面标题/正文。需 power≥50。 */
export async function docUpdatePage(
  id: number, patch: { title?: string; content_md?: string; cover?: string; published?: boolean },
): Promise<DocPage> {
  const r = await fetch(`${payBase()}/cosmac/doc/page/update`, {
    method: 'POST', headers: authHeaders(true),
    body: JSON.stringify({ id, ...patch }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '保存失败')
  return j
}

/** 删页面（连同子树）。需 power≥50。 */
export async function docDeletePage(id: number): Promise<boolean> {
  try {
    const r = await fetch(`${payBase()}/cosmac/doc/page/delete`, {
      method: 'POST', headers: authHeaders(true), body: JSON.stringify({ id }),
    })
    return r.ok
  } catch { return false }
}

/** 让 AI 按主题写一篇图文草稿（Markdown）。需平台管理员。existing=在已有正文上改进。 */
export async function docDraft(topic: string, existing = ''): Promise<string> {
  const r = await fetch(`${payBase()}/cosmac/doc/draft`, {
    method: 'POST', headers: authHeaders(true),
    body: JSON.stringify({ topic, existing }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || 'AI 生成失败')
  return String(j?.markdown || '')
}

/** 移动页面到新父级/改排序。需 power≥50。 */
export async function docMovePage(
  id: number, opts: { parent_id?: number | null; sort?: number },
): Promise<boolean> {
  try {
    const r = await fetch(`${payBase()}/cosmac/doc/page/move`, {
      method: 'POST', headers: authHeaders(true), body: JSON.stringify({ id, ...opts }),
    })
    return r.ok
  } catch { return false }
}

/** 确保主 AI bot 在某工作区(Space)里（文档按 Space 存，鉴权要 bot 能读 Space 成员状态）。
 *  bot 收到邀请会自动加入。已在/无权限都静默忽略。给老 Space 兜底（新 Space 建时已邀请）。 */
export async function ensureBotInSpace(spaceId: string): Promise<void> {
  if (!mx || !spaceId) return
  const bot = botId()
  const m = mx.getRoom(spaceId)?.getMember?.(bot)
  if (m && (m.membership === 'join' || m.membership === 'invite')) return
  try { await mx.invite(spaceId, bot) } catch { /* 已在/无权限忽略 */ }
}

export interface CheckoutResp {
  order_no: string; amount_cents: number; currency: string
  tier: string; period_days: number
  checkout: { kind: string; url: string; address: string; extra: any }
}

/** 下单：带上自己的 access token，bot 验明身份后建订单、返回支付方式。 */
export async function payCheckout(
  planSlug: string, currency: string, provider = 'manual',
): Promise<CheckoutResp> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/pay/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan_slug: planSlug, currency, provider }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || '下单失败')
  return j
}

/** 测试通道：模拟支付成功（manual）。需服务端开 COSMAC_PAY_ALLOW_MANUAL=1。 */
export async function payManualConfirm(orderNo: string, token: string): Promise<void> {
  const r = await fetch(`${payBase()}/cosmac/pay/callback/manual`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_no: orderNo, token }),
  })
  if (!r.ok) {
    throw new Error(
      r.status === 403
        ? '测试支付通道未开启（需服务端设 COSMAC_PAY_ALLOW_MANUAL=1）'
        : '确认失败，请重试',
    )
  }
}

/** 整体写入套餐列表（必要时先建控制室）。只写合法项。 */
export async function setPlans(plans: PlanDef[]): Promise<void> {
  if (!mx) throw new Error('未登录')
  const rid = await ensureControlRoom()
  const clean = plans
    .filter((p) => p.slug && (p.tier === 'paid' || p.tier === 'creator'))
    .map((p) => ({
      slug: p.slug, name: p.name || p.slug, tier: p.tier,
      period_days: Math.max(1, Math.trunc(p.period_days) || 30),
      prices: p.prices, enabled: p.enabled !== false,
    }))
  await (mx as any).sendStateEvent(rid, PLANS_EVENT_TYPE, { plans: clean }, '')
}

/** 读某个频道当前时间线的消息（含发送者昵称与 cosmac.card 富卡）。 */
export function listMessages(roomId: string): LiveMsg[] {
  const room = mx?.getRoom(roomId)
  if (!room) return []
  return room
    .getLiveTimeline()
    .getEvents()
    .filter((e) => e.getType() === 'm.room.message')
    // 编辑事件(m.replace)本身也留在时间线里(matrix-js-sdk 不聚合掉它)，其 fallback 正文是
    // "* 新内容"。原事件已由下面 replacingEvent() 取到最新内容并标 edited，这里必须**排除编辑
    // 事件本身**，否则消息流会多出一条以"* "开头的重复消息(#10)。
    .filter((e) => e.getContent()?.['m.relates_to']?.['rel_type'] !== 'm.replace')
    // 已撤回(redacted)的消息 content 为空，跳过 → 不再显示空气泡
    .filter((e) => !(e as any).isRedacted?.() && Object.keys(e.getContent() || {}).length > 0)
    .map((e) => {
      const sender = e.getSender() || ''
      // 编辑：若有替换事件，取最新内容并标记 edited
      const replacing = (e as any).replacingEvent?.()
      const c: any = replacing
        ? (replacing.getContent()['m.new_content'] || replacing.getContent())
        : e.getContent()
      // 回复：读 m.in_reply_to → 解析被回复消息的名字/正文预览
      const inReplyTo = e.getContent()?.['m.relates_to']?.['m.in_reply_to']?.event_id
      let replyToSender: string | undefined
      let replyToName: string | undefined
      let replyToBody: string | undefined
      if (inReplyTo) {
        const re = room.findEventById?.(inReplyTo)
        if (re) {
          replyToSender = re.getSender() || ''
          replyToName = room.getMember(replyToSender)?.name || replyToSender
          const reIsReply = !!re.getContent()?.['m.relates_to']?.['m.in_reply_to']?.event_id
          replyToBody = stripReplyFallback(re.getContent()?.body || '', reIsReply).slice(0, 80)
        }
      }
      return {
        id: e.getId() || '',
        sender,
        senderName: room.getMember(sender)?.name || sender,
        // 只有本条确实是回复(inReplyTo 存在)才剥 "> " fallback，普通消息里的引用行原样保留(M9)
        body: stripReplyFallback(c.body || '', !!inReplyTo),
        ts: e.getTs(),
        card: c['cosmac.card'],
        attachment: parseAttachment(c),
        edited: !!replacing,
        replyToId: inReplyTo,
        replyToSender,
        replyToName,
        replyToBody,
      }
    })
}

/** 从消息 content 解析图片/文件附件。非附件消息返回 undefined。
 *  m.image/m.video/m.audio → 图片位(视频/音频暂统一按"文件"下载,至少可取);m.file → 文件。
 *  只认 mxc:// 的 url(加密房的 file.url 另说,本产品未开端到端加密,普通 url 即可)。 */
function parseAttachment(c: any): MsgAttachment | undefined {
  const t = c?.msgtype
  const mxc = c?.url
  if (!mxc || typeof mxc !== 'string' || !mxc.startsWith('mxc://')) return undefined
  const info = c?.info || {}
  const base = { mxc, name: String(c?.body || '文件'), mimetype: info.mimetype, size: info.size }
  if (t === 'm.image') return { ...base, kind: 'image', w: info.w, h: info.h }
  if (t === 'm.video') return { ...base, kind: 'video' }
  if (t === 'm.audio') return { ...base, kind: 'audio' }
  if (t === 'm.file') return { ...base, kind: 'file' }
  return undefined
}

/** 把 mxc:// 拉成可用于 <img>/<video>/<a download> 的地址：新版 Synapse 强制**已认证媒体**，
 *  <img> 等标签带不了 Authorization 头，故这里带 token fetch 成 blob 再转 object URL；老版/失败
 *  回退到未认证 http URL（老服务器 <img> 能直接用）。异步，失败返回 ''。调用方用完记得 revokeObjectURL。 */
export async function mxcToObjectUrl(mxc: string, mime?: string): Promise<string> {
  if (!mx || !mxc?.startsWith('mxc://')) return ''
  const rest = mxc.slice('mxc://'.length)
  const slash = rest.indexOf('/')
  if (slash < 0) return ''
  const server = rest.slice(0, slash)
  const mediaId = rest.slice(slash + 1)
  if (!server || !mediaId) return ''
  const token = (mx as any).getAccessToken?.() || ''
  const base = ((mx as any).getHomeserverUrl?.() || (mx as any).baseUrl || '').replace(/\/$/, '')
  // 先试已认证媒体端点(Synapse 1.100+ 强制)
  const authed = `${base}/_matrix/client/v1/media/download/${encodeURIComponent(server)}/${encodeURIComponent(mediaId)}`
  try {
    const r = await fetch(authed, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (r.ok) {
      let b = await r.blob()
      // 可选校正 MIME:服务器常回 application/octet-stream,浏览器新标签打开这种 blob 只会
      // 再弹下载;按消息里记录的类型重包,PDF/文本才能用浏览器内置查看器"在线预览"。
      if (mime && b.type !== mime) b = new Blob([b], { type: mime })
      return URL.createObjectURL(b)
    }
  } catch { /* 回退 */ }
  // 回退：老版未认证 URL(直接给 <img>；若服务器只认证媒体,这条会 401、由组件显示"打不开")
  return (mx as any).mxcUrlToHttp?.(mxc) || ''
}

/** 上传并发送一张图片到房间（m.image）。尽力附带宽高(缩略图渲染需要)。 */
export async function sendImageFile(roomId: string, file: File): Promise<void> {
  if (!mx) throw new Error('未登录')
  const url = await uploadMedia(file)
  if (!url) throw new Error('上传失败')
  const info: Record<string, any> = { mimetype: file.type, size: file.size }
  try {
    const dim = await readImageSize(file)
    if (dim) { info.w = dim.w; info.h = dim.h }
  } catch { /* 读宽高失败不阻断发送 */ }
  await (mx as any).sendEvent(roomId, 'm.room.message', {
    msgtype: 'm.image', body: file.name, url, info,
  })
}

/** 上传并发送一个附件到房间：按 MIME 选 m.video / m.audio / m.file，让视频/音频能在聊天里直接播放。 */
export async function sendFileAttachment(roomId: string, file: File): Promise<void> {
  if (!mx) throw new Error('未登录')
  const url = await uploadMedia(file)
  if (!url) throw new Error('上传失败')
  const mime = file.type || 'application/octet-stream'
  const msgtype = mime.startsWith('video/') ? 'm.video'
    : mime.startsWith('audio/') ? 'm.audio' : 'm.file'
  await (mx as any).sendEvent(roomId, 'm.room.message', {
    msgtype, body: file.name, url,
    info: { mimetype: mime, size: file.size },
  })
}

/** 读一张图片文件的像素宽高（best-effort，读不出返回 null）。 */
function readImageSize(file: File): Promise<{ w: number; h: number } | null> {
  return new Promise((resolve) => {
    const u = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => { resolve({ w: img.naturalWidth, h: img.naturalHeight }); URL.revokeObjectURL(u) }
    img.onerror = () => { resolve(null); URL.revokeObjectURL(u) }
    img.src = u
  })
}

/** 去掉富回复正文里 "> <@x> 引用..." 的 fallback 前缀，只留用户真正打的内容。 */
function stripReplyFallback(body: string, isReply: boolean): string {
  // M9：本产品自己的回复不写 "> " fallback（回复关系只存 m.relates_to.m.in_reply_to），但别的
  // 客户端(Element)发的回复会在正文前塞 "> 引用" fallback 行。只有**确实是回复**的消息才剥离，
  // 否则用户自己写的、以 "> " 开头的正常引用会被整段吞掉（composer「引用」按钮就会踩到）。
  if (!isReply) return body
  // fallback 形如：连续若干 "> ..." 行 + 一个空行，之后才是正文
  const m = body.match(/^(> .*\n)+\n?/)
  return m ? body.slice(m[0].length) : body
}

/** 读某频道所有消息的反应聚合：{ 目标eventId: [{key,count,mine,myId}] }。 */
export function listReactions(roomId: string): Record<string, ReactionAgg[]> {
  const room = mx?.getRoom(roomId)
  if (!room) return {}
  const me = mx?.getUserId()
  const grouped: Record<string, Record<string, ReactionAgg>> = {}
  for (const e of room.getLiveTimeline().getEvents()) {
    if (e.getType() !== 'm.reaction' || (e as any).isRedacted?.()) continue
    const rel = e.getContent()?.['m.relates_to']
    if (!rel || rel.rel_type !== 'm.annotation' || !rel.event_id || !rel.key) continue
    const tgt = rel.event_id as string
    const key = rel.key as string
    grouped[tgt] ||= {}
    const agg = (grouped[tgt][key] ||= { key, count: 0, mine: false })
    agg.count++
    if (e.getSender() === me) { agg.mine = true; agg.myId = e.getId() || undefined }
  }
  const out: Record<string, ReactionAgg[]> = {}
  for (const tgt in grouped) out[tgt] = Object.values(grouped[tgt])
  return out
}

/** 给某条消息加一个 emoji 反应（m.reaction 注解）。 */
export async function react(roomId: string, targetEventId: string, key: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).sendEvent(roomId, 'm.reaction', {
    'm.relates_to': { rel_type: 'm.annotation', event_id: targetEventId, key },
  })
}

/** 取消我的某条反应（redact 那条 reaction 事件）。 */
export async function unreact(roomId: string, reactionEventId: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await mx.redactEvent(roomId, reactionEventId)
}

/** 编辑自己的某条消息（m.replace），消息会显示"已编辑"。 */
export async function editMessage(roomId: string, eventId: string, body: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).sendEvent(roomId, 'm.room.message', {
    msgtype: 'm.text',
    body: `* ${body}`, // 旧客户端 fallback
    'm.new_content': { msgtype: 'm.text', body },
    'm.relates_to': { rel_type: 'm.replace', event_id: eventId },
  })
}

/** 回复某条消息（m.in_reply_to）。 */
export async function sendReply(roomId: string, body: string, replyToEventId: string): Promise<void> {
  if (!mx) throw new Error('未登录')
  await (mx as any).sendEvent(roomId, 'm.room.message', {
    msgtype: 'm.text',
    body,
    'm.relates_to': { 'm.in_reply_to': { event_id: replyToEventId } },
  })
}

/** 往频道发一条纯文本消息（真发到 Synapse）。 */
export async function sendText(
  roomId: string, body: string, extra?: Record<string, any>,
): Promise<void> {
  if (!mx) return
  if (extra && Object.keys(extra).length) {
    // 带自定义字段时走 sendEvent 自己拼 content（sendTextMessage 不支持附加字段）。
    // 用于给中枢 AI 捎上「当前工作区」(cosmac.doc_space)，让它基于该工作区文档答疑。
    await (mx as any).sendEvent(roomId, 'm.room.message', {
      msgtype: 'm.text', body, ...extra,
    })
  } else {
    await mx.sendTextMessage(roomId, body)
  }
}

/** 主 AI 的 localpart（用户名部分，固定）；完整 id 的域名按当前登录服务器动态拼。 */
const BOT_LOCALPART = 'guduu'
/**
 * 主 AI 的完整用户 id（私聊它 = 右侧"中枢 AI"面板）。
 * 按当前登录服务器域名动态拼（@guduu:<serverName>），不写死 cosmac.cc——
 * 否则本地 guduu.local 环境会去邀请一个不存在的账号，AI 进不了群。
 * 必须在登录后调用（serverName() 取自当前用户 id）。
 */
export function botId(): string {
  return `@${BOT_LOCALPART}:${serverName()}`
}

/** 该 MXID 是否为「AI 同事傀儡账号」(方案B:@guduu-ai-<slug>:域,appservice 名下)。 */
export function isAiWorkerId(userId: string): boolean {
  return String(userId || '').startsWith('@guduu-ai-')
}

/** 傀儡 MXID → 智能体 slug(@guduu-ai-copywriter:域 → copywriter);非傀儡返回空串。 */
export function aiWorkerSlug(userId: string): string {
  const uid = String(userId || '')
  if (!uid.startsWith('@guduu-ai-')) return ''
  return uid.slice('@guduu-ai-'.length).split(':')[0]
}

/** 找到我和主 AI 的私聊房间（仅两人）；没有返回 null。 */
export function findBotDm(): string | null {
  if (!mx) return null
  for (const r of mx.getRooms()) {
    const ids = r.getJoinedMembers().map((m) => m.userId)
    if (ids.length <= 2 && ids.includes(botId())) return r.roomId
  }
  return null
}

/** 确保有一个"中枢 AI"私聊房间：先复用已存在的（按名字），没有才新建。 */
// —— 主 AI「多会话」：每个会话 = 一个与 bot 的独立私聊房间 ——
// 为什么这样设计：bot 端的对话历史/上下文/记忆本就**按 room_id 隔离**，所以「一个房间
// = 一段独立会话」是天然映射——新会话 AI 从零开始、互不串味，历史会话随时切回继续。
const AI_SESSION_STATE = 'cosmac.ai_session' // 会话房标记 state event（稳定识别，不依赖房名）
const DM_STATE = 'cosmac.dm'                 // 真人一对一私信房标记(与 AI 会话房、普通频道区分)

/** 判定某房间是否「真人私信(DM)」。已加入的房认 cosmac.dm 标记;**被邀请阶段**读不到
 * 自定义 state(Matrix 邀请只下发 stripped state 白名单,自定义事件不在内),退回原生
 * is_direct 判定——createRoom({is_direct:true}) 会把它写进被邀者的 membership 事件,
 * SDK 的 getDMInviter 据此识别。缺这层曾导致:接收方私信列表看不到新私信、该房还被
 * 误当频道漏进频道列表(QA)。 */
function isDmRoom(r: any): boolean {
  try {
    if (!r) return false
    if (r.currentState?.getStateEvents?.(DM_STATE, '')) return true      // 我们自己的标记
    if (directRoomIds().has(r.roomId)) return true                        // Matrix 标准 m.direct
    if (typeof r.getDMInviter === 'function' && r.getDMInviter()) return true  // 邀请阶段
    // 兜底启发式:**无房名 + 恰好两人 + 不是 AI 会话房** → 真人一对一私信。
    // 为什么需要它:上面三条都可能失效——老私信没有 cosmac.dm 标记,而 getDMInviter 只在**邀请态**
    // 有值;一旦接受邀请入房,该私信就没有任何信号了,会被误当成频道(头部出现"频道设置/私密",
    // 输入框写"发送到 #对方名",实测踩过)。本产品的频道**一律有名字**(前端建频道必填、后端建房
    // 默认"新群"),所以"无名的两人房"只可能是私信。
    if (isAiSessionRoom(r)) return false
    if (r.isSpaceRoom?.()) return false
    // 控制室(平台配置房)可能也是"两人、无名",显式排除,别把它渲染进私信区
    if ((r.getCanonicalAlias?.() || '').startsWith('#cosmac-ctrl:')) return false
    const named = !!r.currentState?.getStateEvents?.('m.room.name', '')?.getContent?.()?.name
    if (named) return false
    // 算**全部成员**(含已离开的):对方被停用/退出后 joined 只剩我一人,但它依然是那段私信
    // (房名会变成 "Empty room (was xxx)"),按 2 人算才认得出来。
    if ((r.getMembers?.() || []).length === 2) return true
  } catch { /* 读不出一律当非 DM */ }
  return false
}

/** 读 `m.direct` 账号数据 → 私信房间 id 集合（Matrix 标准私信标记，跨客户端/跨设备通用）。 */
function directRoomIds(): Set<string> {
  const out = new Set<string>()
  try {
    const c: any = (mx as any)?.getAccountData?.('m.direct')?.getContent?.() || {}
    for (const uid of Object.keys(c)) {
      for (const rid of (c[uid] || [])) out.add(rid)
    }
  } catch { /* 读不出就空集 */ }
  return out
}

/** 把某房间登记进 `m.direct`（标准私信标记）——让"是不是私信"在接受邀请入房后依然成立。
 *  幂等；失败静默（顶多退回启发式判定）。 */
export async function markAsDirect(roomId: string, peerId: string): Promise<void> {
  if (!mx || !roomId || !peerId) return
  try {
    const cur: any = (mx as any).getAccountData?.('m.direct')?.getContent?.() || {}
    const next = { ...cur }
    const arr: string[] = Array.isArray(next[peerId]) ? [...next[peerId]] : []
    if (arr.includes(roomId)) return   // 已登记
    arr.push(roomId)
    next[peerId] = arr
    await (mx as any).setAccountData('m.direct', next)
  } catch { /* 忽略 */ }
}

/** 供视图判定"当前打开的房是不是私信"(私信头部/输入框走简化样式,不按频道渲染)。 */
export function isDirectRoom(roomId: string): boolean {
  const r = mx?.getRoom(roomId)
  return r ? isDmRoom(r) : false
}

/** 点开被邀请的房间时先接受邀请(join)——否则读不到历史、发不了消息。已加入则无操作。 */
export async function acceptRoomInvite(roomId: string): Promise<void> {
  if (!mx) return
  const r = mx.getRoom(roomId)
  if (r && (r as any).getMyMembership?.() === 'invite') {
    // ⚠️ 入房**之前**先把"这是私信"记进 m.direct：getDMInviter 只在邀请态有值,一旦 join 就没了,
    // 而对方建的私信房在被邀阶段读不到我们的 cosmac.dm 标记(邀请只下发 stripped state)。
    // 不在这里记下来,接受邀请后这个私信就会失去全部信号、被误当成频道。
    let inviter = ''
    try { inviter = (r as any).getDMInviter?.() || '' } catch { /* ignore */ }
    try { await mx.joinRoom(roomId) } catch { /* 已加入/权限问题都不阻断打开 */ }
    if (inviter) await markAsDirect(roomId, inviter)
  }
}
const AI_SESSION_NAME = '中枢 AI'

/** 是否「主 AI 会话房」：认标记 state；兼容旧的仅靠房名叫「中枢 AI」的历史房。 */
function isAiSessionRoom(r: any): boolean {
  try {
    if (r?.currentState?.getStateEvents?.(AI_SESSION_STATE, '')) return true
  } catch { /* 读不到 state 就退回名字判断 */ }
  return r?.name === AI_SESSION_NAME
}

/** 全部主 AI 会话房 id 集合——供频道/工作区列表**排除**它们（会话不该混进频道列表）。 */
export function aiSessionRoomIds(): Set<string> {
  if (!mx) return new Set()
  return new Set(mx.getRooms().filter(isAiSessionRoom).map((r: any) => r.roomId))
}

/** 一个主 AI 会话的列表项：房间 id + 标题（首条消息摘要，无则「新会话」）+ 最近活跃时间。 */
export interface AiSession { roomId: string; title: string; ts: number }

/** 列出全部主 AI 会话，按最近活跃**倒序**（最新在上，同 Claude 的 Recents）。 */
export function listAiSessions(): AiSession[] {
  if (!mx) return []
  const me = mx.getUserId() || ''
  return mx.getRooms()
    .filter(isAiSessionRoom)
    // 只认**我自己建的**会话房。历史 bug 曾把成员误邀进别人的 AI 私聊(邀请又会被自动
    // 接受),被邀者的面板若把那个房当自己的会话,多人的"私人会话"就汇进同一个房——
    // 消息互串、AI 回复看着"时有时无"(QA 实测:A 发的指令,回复出现在 B 的面板里)。
    .filter((r: any) => {
      try {
        const cr = r.currentState?.getStateEvents?.('m.room.create', '')
        const creator = cr?.getSender?.() || cr?.getContent?.()?.creator || ''
        return creator === me
      } catch { return false }
    })
    .map((r: any) => {
      const msgs = listMessages(r.roomId)
      // 标题取「我」发的第一句话的前 24 字（最能代表这段会话聊了啥）；没说过话就叫「新会话」
      const firstMine = msgs.find((m) => m.sender === me && !m.card && (m.body || '').trim())
      const title = (firstMine?.body || '').trim().replace(/\s+/g, ' ').slice(0, 24) || '新会话'
      const ts = r.getLastActiveTimestamp?.() || (msgs.length ? msgs[msgs.length - 1].ts : 0)
      return { roomId: r.roomId, title, ts }
    })
    .sort((a, b) => b.ts - a.ts)
}

/** 新建一个主 AI 会话房（邀请 bot + 打会话标记），返回 room_id。 */
export async function createAiSession(): Promise<string> {
  if (!mx) throw new Error('未登录')
  const res: any = await mx.createRoom({
    name: AI_SESSION_NAME,
    preset: 'trusted_private_chat' as any,
    invite: [botId()],
    is_direct: true,
    // 打个标记 state：以后靠它稳定识别"这是主 AI 会话房"，与普通频道/专班区分开
    initial_state: [{ type: AI_SESSION_STATE, state_key: '', content: { v: 1 } }],
  })
  return res.room_id
}

/** 与某个用户开一个一对一私信(DM)。已有和 TA 的 DM 就复用,不重复建;返回 room_id。 */
/** 查找与某人**已存在**的私信房，返回 roomId（没有则空串）。
 * 用统一判定(isDmRoom):对方发起、我还没接受的邀请房也要算——否则"TA 邀我未接受 +
 * 我又主动发起"会算成两个 DM。发起私信弹窗用它区分"新邀请"和"重复邀请"给不同提示。 */
export function findExistingDm(userId: string): string {
  if (!mx) return ''
  const uid = normalizeUserId(userId)
  if (!uid) return ''
  for (const r of mx.getRooms()) {
    try {
      if (!isDmRoom(r) || isAiSessionRoom(r)) continue
      const members = r.getJoinedMembers?.() || []
      const invited = (r as any).getMembersWithMembership?.('invite') || []
      if ([...members, ...invited].some((m: any) => m.userId === uid)) return r.roomId
    } catch { /* 读不到就当没有 */ }
  }
  return ''
}

export async function createDirectMessage(userId: string): Promise<string> {
  if (!mx) throw new Error('未登录')
  const uid = normalizeUserId(userId)
  if (!uid) throw new Error('请填写有效的用户名或用户 id')
  if (uid === (mx as any).getUserId?.()) throw new Error('不能和自己私信')
  // 复用已存在的 DM:避免同一个人建出一堆重复私信房。
  const existed = findExistingDm(uid)
  if (existed) return existed
  const res: any = await mx.createRoom({
    preset: 'trusted_private_chat' as any,
    invite: [uid],
    is_direct: true,
    // 标记这是真人 DM(稳定识别,不依赖房名);渲染在"私信"区、并从"频道"列表排除
    initial_state: [{ type: DM_STATE, state_key: '', content: { v: 1 } }],
  })
  // 同时登记进 Matrix 标准的 m.direct(跨客户端/跨设备通用),双保险
  await markAsDirect(res.room_id, uid)
  return res.room_id
}

/** 列出我的真人私信(DM)。排除主 AI 会话房。每项含对方的显示名/头像用于列表展示。
 * pending=true 表示这是**别人发起、我还没接受**的私信邀请(点开即自动接受)。
 * fromPeer=true 表示这间房是**对方发起**的(新私信通知据此只提醒接收方,不提醒发起方)。
 * 同一个对方若有多间房(历史重复 DM 的存量),**按对方去重**只留最近活跃的那间——
 * 否则列表出现两条同名项/点开旧空房,观感就是"对方发的消息我没收到"(QA 实测)。 */
/** 自算某房未读消息数(对方发的、在我"已读位"之后的 m.room.message)。不依赖服务端 push 计数，
 *  比 getUnreadNotificationCount 更可靠(那个要 push rules 配置正确)。读不出返回 0。 */
function roomUnreadCount(r: any, myId: string): number {
  try {
    const events = r.getLiveTimeline?.()?.getEvents?.() || []
    const readUpTo = r.getEventReadUpTo?.(myId, false) || ''
    let count = 0
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i]
      if (ev.getId?.() === readUpTo) break   // 到达我已读位，之前的都读过
      if (ev.getType?.() !== 'm.room.message') continue
      // 编辑事件(m.replace)不是新消息，不该计入未读——否则对方编辑一条旧消息就让红点+1(#10)
      if (ev.getContent?.()?.['m.relates_to']?.['rel_type'] === 'm.replace') continue
      if (ev.getSender?.() === myId) continue // 自己发的不算未读
      count++
    }
    return count
  } catch {
    return 0
  }
}

/** 专班归档记录(管理后台「归档记录」页;bot 代读 cosmac DB,仅平台管理员)。 */
export interface AdminArchive {
  id: number
  room_id: string
  goal: string
  summary: string
  tasks: any[]
  done_count: number
  total_count: number
  archived_by: string
  archived_at: string
}

export async function fetchAdminArchives(): Promise<AdminArchive[]> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/admin/archives`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || `读取归档失败(${r.status})`)
  return (j.archives || []) as AdminArchive[]
}

/** 后台「频道管理·详情」:某频道的 RULE/知识库/技能/智能体/记忆(仅平台管理员)。 */
export interface AdminRoomDetail {
  rules: { label: string; desc: string }[]
  task_rule: string
  persona: { aiName: string; prompt: string }
  agents: { slug: string; name: string }[]
  kb_sources: string[]
  kb_docs: { id: number; title: string; source: string }[]
  skills: { slug: string; name: string; enabled: boolean }[]
  memory: string
}
/** 读本频道某篇知识库文档全文(频道成员;右侧「关于此频道」点开查看)。 */
export async function fetchRoomKbDoc(roomId: string, id: number): Promise<{ title: string; text: string }> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/kb/room/doc?room_id=${encodeURIComponent(roomId)}&id=${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || `读取文档失败(${r.status})`)
  return j
}

/** 频道规则文档「AI 一键写」:按频道上下文生成 Markdown 工作规范草稿(频道管理员)。 */
export async function fetchRuleDocDraft(roomId: string, notes = '', existing = ''): Promise<string> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/channel/ruledoc_draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ room_id: roomId, notes, existing }),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || `AI 生成失败(${r.status})`)
  return String(j.markdown || '')
}

/** 后台「频道详情」:读某篇知识库文档全文(仅平台管理员)。 */
export async function fetchAdminKbDoc(id: number): Promise<{ title: string; source: string; text: string }> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/admin/kb_doc?id=${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || `读取文档失败(${r.status})`)
  return j
}

export async function fetchAdminRoomDetail(roomId: string): Promise<AdminRoomDetail> {
  const token = (mx as any)?.getAccessToken?.() || ''
  const r = await fetch(`${payBase()}/cosmac/admin/room_detail?room_id=${encodeURIComponent(roomId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error || `读取频道详情失败(${r.status})`)
  return j as AdminRoomDetail
}

/* —— 联系人备注(私信管理):存本人 account data(每账号轻量配置的标准位置,多端同步)。
 *    形如 { aliases: { "@peer:host": "备注名" } };备注只影响自己看到的显示,对方无感。 */
const CONTACTS_ACCOUNT_DATA = 'cc.cosmac.contacts'

/** 读某联系人的备注名;没设过返回空串。 */
export function contactAlias(userId: string): string {
  try {
    const c = (mx as any)?.getAccountData?.(CONTACTS_ACCOUNT_DATA)?.getContent?.() || {}
    return String((c.aliases || {})[userId] || '')
  } catch { return '' }
}

/** 设置/清除某联系人的备注名(空串=清除,恢复对方原显示名)。 */
export async function setContactAlias(userId: string, alias: string): Promise<void> {
  if (!mx || !userId) return
  const c = (mx as any)?.getAccountData?.(CONTACTS_ACCOUNT_DATA)?.getContent?.() || {}
  const aliases: Record<string, string> = { ...(c.aliases || {}) }
  const v = alias.trim().slice(0, 40)
  if (v) aliases[userId] = v
  else delete aliases[userId]
  await (mx as any).setAccountData(CONTACTS_ACCOUNT_DATA, { aliases })
}

export function listDirectMessages(): { id: string; name: string; avatar: string; peerId?: string; fav?: boolean; pending?: boolean; fromPeer?: boolean; unread?: number }[] {
  if (!mx) return []
  const myId = (mx as any).getUserId?.() || ''
  const out: {
    id: string; name: string; avatar: string
    pending?: boolean; fromPeer?: boolean; unread?: number; peerId: string; ts: number
    fav?: boolean
  }[] = []
  for (const r of mx.getRooms()) {
    try {
      // 用统一判定(含被邀请阶段的 is_direct):否则接收方在接受邀请前根本看不到新私信
      if (!isDmRoom(r)) continue
      // 防御:主 AI 会话房也是 is_direct 建的(createAiSession),显式排除,绝不混进真人私信
      if (isAiSessionRoom(r)) continue
      const myMembership = (r as any).getMyMembership?.() || ''
      if (myMembership !== 'join' && myMembership !== 'invite') continue // 已退出的不列
      // 对方 = 房里除我之外的第一个成员(DM 只有两人;被邀阶段"已加入的"就是发起者)
      const others = (r.getJoinedMembers?.() || []).filter((m: any) => m.userId !== myId)
      const invited = ((r as any).getMembersWithMembership?.('invite') || []).filter((m: any) => m.userId !== myId)
      const peer = others[0] || invited[0]
      // 备注名优先(用户给联系人设的,只影响自己这端的显示)
      const name = contactAlias(peer?.userId || '') || peer?.name || peer?.userId || r.name || '私信'
      // 发起方 = 房间创建者;不是我建的就是对方发起的(通知只发给接收方)
      let fromPeer = false
      try {
        const cr = r.currentState?.getStateEvents?.('m.room.create', '')
        const creator = cr?.getSender?.() || cr?.getContent?.()?.creator || ''
        fromPeer = !!creator && creator !== myId
      } catch { /* 读不出按我发起处理(不弹通知,保守) */ }
      // 头像列表里用首字母渲染,这里不取 avatar url(SDK 签名各版本不一,省依赖)
      out.push({
        id: r.roomId, name, avatar: '',
        pending: myMembership === 'invite' || undefined,
        fromPeer: fromPeer || undefined,
        unread: roomUnreadCount(r, myId) || undefined,
        peerId: peer?.userId || '',
        // 收藏(m.favourite 标签):私信分组里收藏的联系人置顶+标 ⭐——此前收藏对
        // 私信完全无可见效果(收藏分组只收频道),负责人报"收藏无效"。
        fav: isFavourite(r.roomId) || undefined,
        ts: r.getLastActiveTimestamp?.() || 0,
      })
    } catch { /* 跳过读不出的房 */ }
  }
  // 收藏的联系人置顶;组内按最近活跃排(有新消息的房 ts 最大,自然赢过历史空房)
  out.sort((a, b) => (Number(!!b.fav) - Number(!!a.fav)) || (b.ts - a.ts))
  const seen = new Set<string>()
  const deduped = out.filter((d) => {
    if (!d.peerId) return true
    if (seen.has(d.peerId)) return false
    seen.add(d.peerId)
    return true
  })
  // peerId 保留给调用方(私信管理:改备注/删除会话要知道对方是谁)
  return deduped.map(({ ts, ...rest }) => rest)
}

/** 打开会话时标记已读(发已读回执 → 清未读)。best-effort，失败不影响使用。 */
export async function markRoomRead(roomId: string): Promise<void> {
  if (!mx || !roomId) return
  try {
    const room = mx.getRoom(roomId)
    const events = room?.getLiveTimeline?.()?.getEvents?.() || []
    const last = events[events.length - 1]
    if (last) await (mx as any).sendReadReceipt(last)
  } catch { /* 已读回执失败不影响使用 */ }
}

/** 删除（离开并遗忘）一个主 AI 会话房。 */
export async function deleteAiSession(roomId: string): Promise<void> {
  if (!mx) return
  try {
    await mx.leave(roomId)
    ;(mx as any).forget?.(roomId)
  } catch { /* 离开失败不阻塞 UI */ }
}

/**
 * 确保有一个可用的主 AI 会话房，返回其 room_id。
 * 复用**最近活跃**的那个会话；一个都没有才新建（首次进入）。
 */
export async function ensureBotDm(): Promise<string> {
  if (!mx) throw new Error('未登录')
  const sessions = listAiSessions()
  if (sessions.length) return sessions[0].roomId
  return await createAiSession()
}
