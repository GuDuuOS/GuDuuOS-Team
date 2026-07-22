import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { setupAutoHideScrollbar } from './composables/useAutoHideScrollbar'
import './styles/index.css'

setupAutoHideScrollbar()
createApp(App).use(router).mount('#app')
