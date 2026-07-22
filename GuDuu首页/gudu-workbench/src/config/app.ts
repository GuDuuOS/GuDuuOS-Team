/**
 * 主站应用地址 —— 不写死域名，按当前访问域名的主域自动推导。
 * --------------------------------------------------------------
 * 为什么不写死：正式机从 GitHub 自动拉代码部署，同一份官网代码会同时
 * 落到「预览环境」和「正式环境」。若把 https://cs.guduuos.com 写死，
 * 两个环境的「登录/注册」都会跳到同一个地址、串环境。
 *
 * 规则（按当前访问域名区分开发/正式，主站前缀是产品约定）：
 *   - 官网子域以 dev 开头（dev24601 / dev-home…）= 开发环境 → 开发主站 dev-cs.<主域>
 *   - 其它（guduuos.com / www.guduuos.com…）    = 正式环境 → 正式主站 cs.<主域>
 * 例：
 *   dev24601.guduuos.com → https://dev-cs.guduuos.com（218 开发主站）
 *   guduuos.com          → https://cs.guduuos.com（正式主站）
 *   将来主域换成任意 X    → 自动 cs.X / dev-cs.X，无需改码
 *
 * 代码里只有 `cs` / `dev-cs` 两个角色前缀约定，具体域名全从 window.location
 * 运行时取——正式机自动拉代码，登录永远指向当前环境的主站，绝不串味。
 */
export function appUrl(): string {
  // SSR/构建期无 window 时返回空串（模板里 href 为空即不可点，运行时会重算）
  if (typeof window === 'undefined') return ''
  const parts = window.location.hostname.split('.')
  // 注册主域（最后两段，如 guduuos.com）；本地 localhost 等单段则原样用
  const root = parts.length >= 2 ? parts.slice(-2).join('.') : window.location.hostname
  // 子域（最左一段）以 dev 开头 = 开发环境，登录进开发主站；否则进正式主站
  const sub = parts.length > 2 ? parts[0] : ''
  const prefix = sub.startsWith('dev') ? 'dev-cs' : 'cs'
  return `${window.location.protocol}//${prefix}.${root}`
}
