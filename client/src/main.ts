import { createApp } from 'vue'
// 应用根改为 App.vue（承载 <router-view>）：/login 独立登录页，其余进主应用 LiveView。
// 之前是 main.ts 直接挂 LiveView（登录也塞在里面）；抽出独立 AuthView 后统一走路由出口。
import App from './App.vue'
// 全局样式：暖色 tokens + reset（沿用原有；不引入演示组件的全量 CSS，以免撞色污染皮肤）。
import './styles/tokens.css'
import './styles/reset.css'
import { router } from './router'
import { loadInstanceConfig } from './config/instance'
import { installDesktopDeepLinkNavigation } from './platform/desktopDeepLinks'
import { loadSessionVault } from './platform/sessionVault'

async function bootstrap() {
  // Electron 先解密当前会话，defaultHsUrl 才能用受 safeStorage 保护的
  // OEM homeserver 加载品牌；Web 端则仍是原有 localStorage 同步路径。
  try { await loadSessionVault() } catch { /* 路由守卫会显示安全存储错误 */ }
  // 在挂载登录页前先取一次公开品牌，避免默认 Logo/名称闪烁。
  await loadInstanceConfig().catch(() => undefined)
  // 深链监听挂在窗口级而非 LiveView，这样登录页、激活页和工作台之间
  // 切换时不会丢掉操作系统送来的邀请。Web 端没有 Electron 桥时这是 no-op。
  void installDesktopDeepLinkNavigation(router)
  createApp(App).use(router).mount('#app')
}

void bootstrap()
