// 路由：/login 独立登录页（AuthView），其余全部指向主应用 LiveView。
// LiveView 仍靠内部 computePath/applyFromRoute 解析 window.location 决定显示什么
// （频道/看板/后台/个人主页），故这些路由都用同一个 LiveView 组件；换页由 LiveView 内部状态驱动。
// 两个视图都懒加载：登录页因此不再被 199KB 的 LiveView 拖累，可独立秒开。
// 详见 memory `client-root-is-liveview`（已随本次「独立 AuthView」重构更新）。
import { createRouter, createWebHashHistory } from 'vue-router'
import { storedCurrentUserId } from '@/platform/sessionVault'
import { loadInstanceConfig } from '@/config/instance'

const LiveView = () => import('@/views/LiveView.vue')
const AuthView = () => import('@/views/AuthView.vue')
const ActivationView = () => import('@/views/ActivationView.vue')
const SetupView = () => import('@/views/SetupView.vue')

const routes = [
  { path: '/login', component: AuthView },
  { path: '/activate', component: ActivationView },
  { path: '/setup', component: SetupView },
  { path: '/', component: LiveView },
  { path: '/s/:space/board', component: LiveView },
  { path: '/s/:space/tasks', component: LiveView },
  { path: '/s/:space/org', component: LiveView },
  { path: '/s/:space/c/:roomId', component: LiveView },
  { path: '/admin', component: LiveView },
  // 后台各菜单独立地址(刷新留在原菜单/可后退/深链);菜单名由 LiveView 的 applyFromRoute 校验
  { path: '/admin/:tab', component: LiveView },
  { path: '/me', component: LiveView },
  { path: '/join/:space', component: LiveView },
  { path: '/:pathMatch(.*)*', component: LiveView },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 认证守卫：未登录访问任何非 /login 页 → 跳登录并用 redirect 记下目标。
// Electron 必须先异步读取 safeStorage，不能相信可篡改的公开元数据；会话是否**真有效**仍由
// LiveView 挂载时 restoreSession 启动 Matrix 同步后兜底校验（失效则再跳回 /login）。
// 注（bug8）：登录页**始终可达**——不再把"已登录"用户从 /login 弹回首页。否则已登录用户在登录页
// 想切换账号、正输账号时一刷新就被弹去首页（"账号没输完就跳首页"）。正常登录后仍由 proceed()
// 主动 push 到目标页，不依赖这个弹走逻辑。
router.beforeEach(async (to) => {
  // 仅 Vite 开发态允许无会话预览向导布局；生产构建会编译掉此分支，保存接口仍有管理员鉴权。
  if (import.meta.env.DEV && to.path === '/setup' && to.query.preview === '1') return true
  if (to.path === '/login') return true
  let userId = ''
  try {
    userId = await storedCurrentUserId()
  } catch {
    // 钥匙串锁定或密文损坏时安全回到登录页，不信任公开元数据，也不删除仍可恢复的密文。
    return { path: '/login', query: { redirect: to.fullPath, storage: 'unavailable' } }
  }
  if (!userId) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.path !== '/setup') {
    const config = await loadInstanceConfig()
    // 新安装只有 bootstrap 的 @admin 账号；仅把它强制送入向导。这样旧 OEM 节点
    // 升级到 1.24.0 时，普通成员不会在管理员尚未补配置前被一并挡在向导外。
    const localpart = userId.replace(/^@/, '').split(':')[0]
    if (!config.setup_completed && localpart === 'admin') return { path: '/setup' }
  }
  return true
})
