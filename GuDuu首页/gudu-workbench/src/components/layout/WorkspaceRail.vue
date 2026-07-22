<template>
  <div class="ws-rail">
    <div
      v-for="ws in workspaces"
      :key="ws.id"
      class="ws-icon"
      :class="{ active: ws.id === activeId }"
      :data-workspace="ws.id"
      :title="ws.title"
      @click="selectWorkspace(ws.id)"
    >
      {{ ws.label }}
    </div>
    <div class="ws-icon plus" title="新建部门" @click="openCreateDept">+</div>

    <!-- 底部工具组（自上而下）：商城 / CLI / 个人主页 -->
    <div class="ws-sep" />

    <div class="ws-icon ws-tool" title="AI Agent 商城" @click="openMarket">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" />
        <path d="M3 6h18" />
        <path d="M16 10a4 4 0 0 1-8 0" />
      </svg>
    </div>
    <div class="ws-icon ws-tool" title="CLI" @click="openCli">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="4 17 10 11 4 5" />
        <line x1="12" x2="20" y1="19" y2="19" />
      </svg>
    </div>
    <div class="ws-icon ws-tool" title="个人主页" @click="openProfile">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        <polyline points="9 22 9 12 15 12 15 22" />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { workspaces } from '@/data/channels'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { useMarketplace } from '@/composables/useMarketplace'
import { useCli } from '@/composables/useCli'
import { useProfileHome } from '@/composables/useProfileHome'
import { useDepartmentCreate } from '@/composables/useDepartmentCreate'

const { activeId, setActive } = useActiveWorkspace()
const { open: openMarket } = useMarketplace()
const { open: openCli } = useCli()
const { open: openProfile } = useProfileHome()
const { open: openCreateDept } = useDepartmentCreate()
const router = useRouter()

/** 切换部门：落地到该部门的「工作台总览」(dashboard)，再激活工作区 */
async function selectWorkspace(id: string) {
  if (id === activeId.value) return
  await router.push({ name: 'dashboard' })
  setActive(id)
}
</script>
