<template>
  <aside class="right">
    <div class="right-head">
      关于此频道
      <span class="close" title="关闭" @click="hide">×</span>
    </div>
    <div class="right-body">
      <div class="pinned">
        <div class="ph">📌 PINNED</div>
        <div class="pc">
          本频道由 <b>GuDuu</b> 7×24 实时维护。所有 KPI、模块状态、Agent 消息均来自接入的
          CRM / BI / ERP / OA 系统。
        </div>
      </div>

      <div class="pinned">
        <div class="ph">👥 人员 · 频道成员 ({{ members.length }})</div>
        <div class="members-list">
          <div v-for="m in members" :key="m.name" class="m">
            <div class="a" :class="{ bot: m.bot }" :data-avatar="m.avatar" :style="m.color ? `background:${m.color}` : undefined">
              {{ m.avatar }}
            </div>
            <div v-if="m.online" class="presence" />
            <div class="n">{{ m.name }}</div>
            <div class="r">{{ m.role }}</div>
          </div>
        </div>
      </div>

      <div class="pinned">
        <div class="ph">⚡ SKILL · 技能</div>
        <div class="info-list">
          <div v-for="s in skills" :key="s.label" class="info-item">
            <div class="info-main">
              <span class="info-label">{{ s.label }}</span>
              <span v-if="s.tag" class="info-tag">{{ s.tag }}</span>
            </div>
            <div v-if="s.desc" class="info-desc">{{ s.desc }}</div>
          </div>
        </div>
      </div>

      <div class="pinned">
        <div class="ph">📚 知识库 · KNOWLEDGE</div>
        <div class="info-list">
          <div v-for="k in knowledge" :key="k.label" class="info-item">
            <div class="info-main">
              <span class="info-label">{{ k.label }}</span>
            </div>
            <div v-if="k.desc" class="info-desc">{{ k.desc }}</div>
          </div>
        </div>
      </div>

      <div class="pinned">
        <div class="ph">📐 RULE · 规则</div>
        <div class="info-list">
          <div v-for="r in rules" :key="r.label" class="info-item">
            <div class="info-main">
              <span class="info-label">{{ r.label }}</span>
            </div>
            <div v-if="r.desc" class="info-desc">{{ r.desc }}</div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRightPanel } from '@/composables/useRightPanel'
import { useChannelAdmin } from '@/composables/useChannelAdmin'

// 与「频道管理」弹窗共享同一份数据，增删会同步反映
const { state } = useChannelAdmin()
const members = computed(() => state.members)
const skills = computed(() => state.skills)
const knowledge = computed(() => state.knowledge)
const rules = computed(() => state.rules)
const { hide } = useRightPanel()
</script>
