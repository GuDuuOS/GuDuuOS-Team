import { reactive } from 'vue'
import { plugins as seed, type PluginItem } from '@/data/plugins'

/** 插件栏的图标列表（模块级单例，跨组件共享、可增删）*/
const list = reactive<PluginItem[]>(seed.map((p) => ({ ...p })))

/** 内置插件不允许被移除 */
const LOCKED = new Set(['ai'])

export function usePlugins() {
  return {
    plugins: list,
    has: (id: string) => list.some((p) => p.id === id),
    add(item: PluginItem) {
      if (!list.some((p) => p.id === item.id)) list.push(item)
    },
    remove(id: string) {
      if (LOCKED.has(id)) return
      const i = list.findIndex((p) => p.id === id)
      if (i >= 0) list.splice(i, 1)
    }
  }
}
