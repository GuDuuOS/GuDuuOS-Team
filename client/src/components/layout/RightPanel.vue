<template>
  <aside class="right">
    <div class="right-head">
      关于此频道
      <span class="close" title="关闭" @click="hide">×</span>
    </div>
    <div class="right-body">
      <div class="pinned">
        <div class="ph">📌 关于</div>
        <div v-if="isLive" class="pc">
          <b>{{ groupName }}</b> · 频道成员、技能、知识库与规则的总览。配置在「频道管理」里维护，本面板实时同步。
        </div>
        <div v-else class="pc">
          本频道由 <b>CosMac</b> 7×24 实时维护。所有数据、账号状态、Agent 消息均来自接入的
          抖音 / 小红书 / 视频号 / 公众号 等平台。
        </div>
      </div>

      <div class="pinned">
        <div class="ph">👥 人员 · 频道成员 ({{ members.length }})</div>
        <div class="members-list">
          <div v-for="m in members" :key="m.name" class="m">
            <div class="a" :class="{ bot: m.bot }" :style="m.color ? { background: m.color } : undefined">
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
          <div v-for="k in knowledge" :key="k.label" class="info-item" :class="{ clickable: k.docId != null }" @click="k.docId != null && toggleDoc(k.docId)">
            <div class="info-main">
              <span class="info-label">{{ k.label }}</span>
              <span v-if="k.docId != null" class="info-doc-hint">{{ docOpen === k.docId ? '收起 ▲' : '查看 ▼' }}</span>
            </div>
            <div v-if="k.desc" class="info-desc">{{ k.desc }}</div>
            <pre v-if="k.docId != null && docOpen === k.docId" class="info-doc-text">{{ docLoading ? '加载中…' : docText }}</pre>
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
import { computed, ref } from 'vue'
import { useRightPanel } from '@/composables/useRightPanel'
import { fetchRoomKbDoc } from '@/matrix/client'
import { useChannelAdmin } from '@/composables/useChannelAdmin'
// .right 面板样式来自全局 right.css；真实客户端(main.ts)只加载 tokens/reset，故组件自带样式
import '@/styles/right.css'

// 与「频道管理」弹窗共享同一份数据，增删会同步反映
const { state, isLive, liveMembers, groupName, roomKbDocs } = useChannelAdmin()
// 成员：真实频道用真实 Matrix 成员（映射成本面板的展示形状），demo 回退 mock
const members = computed(() => {
  if (isLive.value) {
    return liveMembers.value.map((m) => ({
      name: m.name,
      role: m.pending ? `${m.roleLabel} · 待接受` : m.roleLabel,
      avatar: m.isBot ? '智' : [...m.name][0] || '?',
      bot: m.isBot,
      color: undefined as string | undefined,
      online: !m.pending,
    }))
  }
  return state.members
})
// 技能/知识库/规则：真实频道下已是真实持久化数据（loadConfigFromRoom 填充）
const skills = computed(() => state.skills)
// 知识库 = 「来源」条目 + **真实上传入库的文档**(roomKbDocs,与频道管理弹窗共享同一份,
// 弹窗里上传/删除后这里即时同步——负责人报的"维护知识库后右侧未同步")
const knowledge = computed(() => [
  ...state.knowledge.map((k) => ({ ...k, docId: null as number | null })),
  // 真实入库文档带 docId → 条目可点击展开全文(负责人报的"无法点击查看")
  ...roomKbDocs.value.map((d) => ({ label: d.title, desc: '已入库文档 · 本频道 AI 可检索', docId: d.id as number | null })),
])
// 点开某篇文档看全文(频道成员端点,懒加载)
const docOpen = ref<number | null>(null)
const docText = ref('')
const docLoading = ref(false)
async function toggleDoc(id: number) {
  if (docOpen.value === id) { docOpen.value = null; return }
  docOpen.value = id
  docLoading.value = true
  docText.value = ''
  try {
    const rid = (useChannelAdmin().roomId as any).value as string
    docText.value = (await fetchRoomKbDoc(rid, id)).text || '(空文档)'
  } catch (e: any) {
    docText.value = `读取失败:${e?.message || e}`
  } finally {
    docLoading.value = false
  }
}
const rules = computed(() => state.rules)
const { hide } = useRightPanel()
</script>
