import { reactive, ref } from 'vue'
import { pluginItems, type PluginStoreItem } from '@/data/pluginStore'
import { usePlugins } from '@/composables/usePlugins'
import { getInstalledPlugins, setInstalledPlugins } from '@/matrix/client'

/** 独立「插件商城」弹窗的可见状态 */
const visible = ref(false)
/** 安装状态副本（可切换）*/
const items = reactive<PluginStoreItem[]>(pluginItems.map((i) => ({ ...i })))

export function usePluginStore() {
  const { add: addPlugin, remove: removePlugin } = usePlugins()

  /** 把当前安装集写进本人 account data（内置插件不记——它们永远在）。 */
  function persist() {
    void setInstalledPlugins(
      items.filter((i) => i.installed && !i.builtinPluginId).map((i) => i.id)
    )
  }

  /** 按商城条目把插件挂上/摘下右侧插件栏（安装状态的唯一落地动作）。 */
  function apply(it: PluginStoreItem) {
    const pid = 'ps-' + it.id
    if (it.installed) {
      addPlugin({ id: pid, label: it.icon, title: it.name, color: it.color })
    } else {
      removePlugin(pid)
    }
  }

  return {
    visible,
    items,
    open: () => { visible.value = true },
    close: () => { visible.value = false },

    /** 登录后从 account data 恢复安装状态（幂等，可重复调用）。
     *  没有它,「获取即用」只活到刷新——这正是之前商城是假功能的表现之一。 */
    restore() {
      const saved = new Set(getInstalledPlugins())
      for (const it of items) {
        if (it.builtinPluginId) continue
        const want = saved.has(it.id)
        if (want === !!it.installed) continue
        it.installed = want
        apply(it)
      }
    },

    /** 获取 / 卸载：同步到右侧插件栏，并持久化到账号（刷新/换端不丢） */
    toggle(it: PluginStoreItem) {
      // 内置插件（如主 AI）：始终已安装，不可卸载
      if (it.builtinPluginId) {
        it.installed = true
        return
      }
      it.installed = !it.installed
      apply(it)
      persist()
    }
  }
}
