import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import DashboardView from '@/views/DashboardView.vue'
import SafetyView from '@/views/SafetyView.vue'
import EnergyView from '@/views/EnergyView.vue'
import OfficeView from '@/views/OfficeView.vue'
import DuuChatView from '@/views/DuuChatView.vue'
import TodoView from '@/views/TodoView.vue'
import OpsChannelView from '@/views/OpsChannelView.vue'
import WebsiteHomeView from '@/views/WebsiteHomeView.vue'
import DataCanvasView from '@/views/DataCanvasView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/',          name: 'website',   component: WebsiteHomeView, meta: { website: true } },
  { path: '/data-canvas', name: 'data-canvas', component: DataCanvasView, meta: { website: true } },
  { path: '/case',      name: 'dashboard', component: DashboardView },
  { path: '/safety',    name: 'safety',    component: SafetyView },
  { path: '/energy',    name: 'energy',    component: EnergyView },
  { path: '/office',    name: 'office',    component: OfficeView },
  { path: '/duu',       name: 'duu',       component: DuuChatView },
  { path: '/todo',      name: 'todo',      component: TodoView },
  { path: '/ops/:id',   name: 'ops',       component: OpsChannelView },
  { path: '/:pathMatch(.*)*', redirect: { name: 'website' } }
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})
