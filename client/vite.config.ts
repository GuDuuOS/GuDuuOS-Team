import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    open: false,
    // 本地全链路联调（可选）：设 VITE_HS_URL=http://localhost:<port> 走同源模式时，
    // 由 dev server 把 Matrix / bot 请求代到本机服务——模拟生产 nginx/Caddy 的路由，
    // 前端代码零改动即可连本地 Synapse(8008) + cosmac bot(9000)。不设该变量时这些
    // 代理路径不会被前端请求命中，线上行为不受任何影响。
    proxy: {
      '/_matrix': { target: 'http://127.0.0.1:8008', changeOrigin: true },
      '/_synapse': { target: 'http://127.0.0.1:8008', changeOrigin: true },
      '/cosmac': { target: 'http://127.0.0.1:9000', changeOrigin: true }
    }
  }
})
