<template>
  <template v-if="isWebsite">
    <router-view />
  </template>
  <template v-else>
    <TopBar />
    <div class="layout" :class="{ focused }">
      <WorkspaceRail v-if="!focused" />
      <ChannelSidebar v-if="!focused" />
      <main class="main">
        <router-view />
      </main>
      <RightPanel v-if="rightPanelVisible && !focused" />
      <AiChatPanel v-if="aiPanelVisible" />
      <PluginRail v-if="!focused" />
    </div>
    <ChannelAdminModal />
    <CardActionModal />
    <DepartmentCreateModal />
    <SystemAiModal />
    <UserSettingsModal />
    <MarketplaceModal />
    <PluginStoreModal />
    <CliConsole />
    <ProfileHome />
    <DemoToasts />
    <SetupWizard />
    <CommandPalette />
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import TopBar from '@/components/layout/TopBar.vue'
import WorkspaceRail from '@/components/layout/WorkspaceRail.vue'
import ChannelSidebar from '@/components/layout/ChannelSidebar.vue'
import RightPanel from '@/components/layout/RightPanel.vue'
import PluginRail from '@/components/layout/PluginRail.vue'
import AiChatPanel from '@/components/layout/AiChatPanel.vue'
import ChannelAdminModal from '@/components/channel/ChannelAdminModal.vue'
import CardActionModal from '@/components/channel/CardActionModal.vue'
import DepartmentCreateModal from '@/components/layout/DepartmentCreateModal.vue'
import SystemAiModal from '@/components/layout/SystemAiModal.vue'
import UserSettingsModal from '@/components/layout/UserSettingsModal.vue'
import MarketplaceModal from '@/components/layout/MarketplaceModal.vue'
import PluginStoreModal from '@/components/layout/PluginStoreModal.vue'
import CliConsole from '@/components/layout/CliConsole.vue'
import ProfileHome from '@/components/layout/ProfileHome.vue'
import DemoToasts from '@/components/layout/DemoToasts.vue'
import SetupWizard from '@/components/layout/SetupWizard.vue'
import CommandPalette from '@/components/layout/CommandPalette.vue'
import { useRightPanel } from '@/composables/useRightPanel'
import { useAiPanel } from '@/composables/useAiPanel'
import { useFocusMode } from '@/composables/useFocusMode'

const { visible: rightPanelVisible } = useRightPanel()
const { visible: aiPanelVisible } = useAiPanel()
const { focused } = useFocusMode()
const route = useRoute()
const isWebsite = computed(() => route.meta.website === true)
</script>

<style>
/* 路由视图切换时的淡入（纯 CSS 动画，不依赖 Vue <transition> 生命周期）*/
.main > .channel-view {
  animation: view-fade-in 0.18s ease;
}
@keyframes view-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
