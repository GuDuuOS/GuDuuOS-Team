import { reactive, ref } from 'vue'
import { pluginItems, type PluginStoreItem } from '@/data/pluginStore'
import { usePlugins } from '@/composables/usePlugins'

/** 独立「插件商城」弹窗的可见状态 */
const visible = ref(false)
/** 安装状态副本（可切换）*/
const items = reactive<PluginStoreItem[]>(pluginItems.map((i) => ({ ...i })))

export function usePluginStore() {
  const { add: addPlugin, remove: removePlugin } = usePlugins()

  return {
    visible,
    items,
    open: () => { visible.value = true },
    close: () => { visible.value = false },

    /** 获取 / 卸载：同步到右侧插件栏 */
    toggle(it: PluginStoreItem) {
      // 内置插件（如主 AI）：始终已安装，不可卸载
      if (it.builtinPluginId) {
        it.installed = true
        return
      }
      it.installed = !it.installed
      const pid = 'ps-' + it.id
      if (it.installed) {
        addPlugin({ id: pid, label: it.icon, title: it.name, color: it.color })
      } else {
        removePlugin(pid)
      }
    }
  }
}
