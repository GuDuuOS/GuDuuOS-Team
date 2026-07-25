<template>
  <aside class="right" v-if="panelOpen">
    <div class="right-head">
      数据源 · {{ boardLabel }}
      <span class="close" title="关闭" @click="closeSourcePanel">×</span>
    </div>
    <div class="right-body">
      <!-- 当前数据源列表 -->
      <div class="pinned">
        <div class="ph"><Icon name="archive" :size="13" /> 数据源（{{ list.length }}）</div>
        <div class="info-list">
          <div v-for="(s, i) in list" :key="rowKey(s)" class="bsp-row">
            <div class="info-main">
              <span class="info-label">{{ s.name }}<span class="info-tag">{{ s.type }}</span></span>
              <div v-if="s.note" class="info-desc">{{ s.note }}</div>
            </div>
            <button class="bsp-del" title="移除" @click="removeSource(panelBoard, i)">×</button>
          </div>
          <p v-if="!list.length" class="info-desc" style="padding:4px 0">还没有数据源 —— 在下方添加。</p>
        </div>
      </div>

      <!-- 添加数据源 -->
      <div class="pinned">
        <div class="ph">＋ 添加数据源</div>
        <input v-model="nName" class="bsp-input" placeholder="名称（如 抖音创作者后台）" @keyup.enter="doAdd" />
        <select v-model="nType" class="bsp-input">
          <option v-for="t in BOARD_SOURCE_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
        <input v-model="nNote" class="bsp-input" placeholder="连接说明 / 备注（可选）" @keyup.enter="doAdd" />
        <button class="bsp-add" :disabled="!nName.trim()" @click="doAdd">添加</button>
        <div class="bsp-hint" :style="saveHintStyle">{{ saveHint }}</div>
        <div class="bsp-hint">数据源目前是配置占位（名称 / 类型 / 备注），按本工作区保存、多端同步。真实取数以后接。</div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed, ref } from 'vue'
import { rowKey } from '@/utils/rowKey'
// 复用「关于此频道」右面板那套 .right / .pinned / .info-* 样式
import '@/styles/right.css'
import {
  useBoardSources,
  BOARD_SOURCE_TYPES,
  BOARD_LABELS,
} from '@/composables/useBoardSources'

const {
  sources, saveState, panelOpen, panelBoard, closeSourcePanel, addSource, removeSource,
} = useBoardSources()

const list = computed(() => sources[panelBoard.value])
const boardLabel = computed(() => BOARD_LABELS[panelBoard.value])

const nName = ref('')
const nType = ref(BOARD_SOURCE_TYPES[0])
const nNote = ref('')
function doAdd() {
  if (!nName.value.trim()) return
  addSource(panelBoard.value, { name: nName.value, type: nType.value, note: nNote.value })
  nName.value = ''
  nNote.value = ''
}

const saveHint = computed(() => ({
  idle: '编辑后自动保存到本工作区 · 多端同步',
  saving: '保存中…',
  saved: '✓ 已保存到本工作区 · 多端同步',
  error: '保存失败：你可能没有本工作区修改配置的权限',
}[saveState.value]))
const saveHintStyle = computed(() => (saveState.value === 'error' ? 'color:#b94a4a' : ''))
</script>

<style scoped>
.bsp-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.bsp-row .info-main { flex: 1; min-width: 0; }
.bsp-del { width: 22px; height: 22px; flex-shrink: 0; border: none; background: transparent; color: var(--text-3); border-radius: 5px; cursor: pointer; font-size: 16px; line-height: 1; }
.bsp-del:hover { background: var(--bg-hover); color: #b94a4a; }
.bsp-input { width: 100%; box-sizing: border-box; margin-top: 6px; padding: 7px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg-input, var(--bg-panel)); color: var(--text); font-size: 13px; }
.bsp-input:focus { outline: none; border-color: var(--accent); }
.bsp-add { width: 100%; margin-top: 8px; padding: 8px; border: none; border-radius: 7px; background: var(--accent); color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; }
.bsp-add:disabled { opacity: .5; cursor: not-allowed; }
.bsp-hint { margin-top: 8px; font-size: 11px; color: var(--text-3); line-height: 1.5; }
</style>
