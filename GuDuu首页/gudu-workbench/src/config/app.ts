/**
 * 主站应用地址 —— 不写死域名，按当前访问域名的主域自动推导。
 * --------------------------------------------------------------
 * 为什么不写死：正式机从 GitHub 自动拉代码部署，同一份官网代码会同时
 * 落到「预览环境」和「正式环境」。若把 https://cs.guduuos.com 写死，
 * 两个环境的「登录/注册」都会跳到同一个地址、串环境。
 *
 * 规则：主站固定是当前主域下的 `cs` 子域（这是产品约定，主站永远叫 cs.*）：
 *   - 官网在 dev24601.guduuos.com → 主站 https://cs.guduuos.com
 *   - 官网在 guduuos.com（正式）   → 主站 https://cs.guduuos.com
 *   - 将来主域换成任意域名 X       → 主站 https://cs.X（自动适配，无需改码）
 *
 * 代码里唯一的约定是 `cs` 这个子域前缀（主站的角色标识，非地址）；
 * 具体域名一律从 window.location 运行时取，杜绝环境串味。
 */
export function appUrl(): string {
  // SSR/构建期无 window 时返回空串（模板里 href 为空即不可点，运行时会重算）
  if (typeof window === 'undefined') return ''
  const parts = window.location.hostname.split('.')
  // 取注册主域（最后两段，如 guduuos.com）；本地 localhost 等单段则原样用
  const root = parts.length >= 2 ? parts.slice(-2).join('.') : window.location.hostname
  return `${window.location.protocol}//cs.${root}`
}
