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

// 在挂载登录页前先取一次同域公开品牌，避免页面先闪出默认 Logo/名称再替换。
loadInstanceConfig().finally(() => {
  // 深链监听挂在窗口级而非 LiveView，这样登录页、激活页和工作台之间
  // 切换时不会丢掉操作系统送来的邀请。Web 端没有 Electron 桥时这是 no-op。
  void installDesktopDeepLinkNavigation(router)
  createApp(App).use(router).mount('#app')
})
