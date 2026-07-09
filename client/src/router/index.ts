// 路由：/login 独立登录页（AuthView），其余全部指向主应用 LiveView。
// LiveView 仍靠内部 computePath/applyFromRoute 解析 window.location 决定显示什么
// （频道/看板/后台/个人主页），故这些路由都用同一个 LiveView 组件；换页由 LiveView 内部状态驱动。
// 两个视图都懒加载：登录页因此不再被 199KB 的 LiveView 拖累，可独立秒开。
// 详见 memory `client-root-is-liveview`（已随本次「独立 AuthView」重构更新）。
import { createRouter, createWebHashHistory } from 'vue-router'
import { currentUserId } from '@/matrix/client'

const LiveView = () => import('@/views/LiveView.vue')
const AuthView = () => import('@/views/AuthView.vue')

const routes = [
  { path: '/login', component: AuthView },
  { path: '/', component: LiveView },
  { path: '/s/:space/board', component: LiveView },
  { path: '/s/:space/tasks', component: LiveView },
  { path: '/s/:space/org', component: LiveView },
  { path: '/s/:space/c/:roomId', component: LiveView },
  { path: '/admin', component: LiveView },
  { path: '/me', component: LiveView },
  { path: '/join/:space', component: LiveView },
  { path: '/:pathMatch(.*)*', component: LiveView },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 认证守卫：未登录访问任何非 /login 页 → 跳登录并用 redirect 记下目标。
// authed 只看 localStorage 是否有会话；会话是否**真有效**由 LiveView 挂载时 restoreSession 兜底
// 校验（失效则它再跳回 /login）。
// 注（bug8）：登录页**始终可达**——不再把"已登录"用户从 /login 弹回首页。否则已登录用户在登录页
// 想切换账号、正输账号时一刷新就被弹去首页（"账号没输完就跳首页"）。正常登录后仍由 proceed()
// 主动 push 到目标页，不依赖这个弹走逻辑。
router.beforeEach((to) => {
  const authed = !!currentUserId()
  if (to.path === '/login') return true
  if (!authed) return { path: '/login', query: { redirect: to.fullPath } }
  return true
})
