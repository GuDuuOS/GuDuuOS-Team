<template>
  <div v-if="visible" class="mp-overlay" @click.self="close">
    <div class="mp-modal" role="dialog" aria-modal="true">
      <div class="mp-head">
        <div class="mp-title-wrap">
          <span class="mp-title">我的协作人</span>
          <span class="mp-sub">这里是你的联系人（共处一群/私信的人）· 给 TA 补上"擅长什么"，主 AI 拆任务时按能力派给 TA</span>
        </div>
        <button class="mp-close" title="关闭" @click="close">×</button>
      </div>

      <div ref="bodyEl" class="mp-body">
        <!-- 编辑能力：给已有联系人(user_id 固定) 或 手动添加新人(user_id 可编辑) -->
        <div v-if="editing" class="mp-edit">
          <input v-if="adding" v-model.trim="form.user_id" class="mp-input"
            placeholder="用户名或 @用户名（如 wenan / @wenan:cosmac.cc）" />
          <div v-else class="mp-edit-who">{{ form.name || form.user_id }} <span class="mp-uid">{{ form.user_id }}</span></div>
          <div class="mp-row">
            <input v-model.trim="form.name" class="mp-input" placeholder="显示名（可空）" />
            <input v-model.trim="form.role" class="mp-input" placeholder="角色 / 岗位" />
          </div>
          <textarea v-model="form.expertise" class="mp-textarea" rows="3"
            placeholder="擅长什么（主 AI 据此匹配），如：小红书种草文案、爆款标题…" />
          <input v-model.trim="form.note" class="mp-input" placeholder="补充备注（可空）" />
          <label class="mp-chk"><input type="checkbox" v-model="form.enabled" /> 启用（参与 AI 派单）</label>
          <p v-if="errText" class="mp-err">{{ errText }}</p>
          <div class="mp-bar">
            <button class="mp-btn ghost" :disabled="busy" @click="editing = false">取消</button>
            <button class="mp-btn" :disabled="busy" @click="save">{{ busy ? '保存中…' : '保存' }}</button>
          </div>
        </div>

        <template v-else>
          <div class="mp-toolbar">
            <span class="mp-hint">{{ rows.length }} 位联系人</span>
            <button class="mp-btn" @click="startAdd">＋ 添加协作人</button>
          </div>
          <div v-if="loading" class="mp-empty">加载联系人…</div>
          <ul v-else-if="rows.length" class="mp-list">
            <li v-for="r in rows" :key="r.id" class="mp-item">
              <div class="mp-item-main">
                <div class="mp-item-top">
                  <b>{{ r.name }}</b>
                  <span v-if="r.role" class="mp-role">{{ r.role }}</span>
                  <span class="mp-badge" :class="{ on: r.hasProfile && r.enabled, global: r.isGlobal }">
                    {{ r.hasProfile ? (r.isGlobal ? '平台已设' : r.enabled ? '已设能力' : '停用') : '未设能力' }}
                  </span>
                  <!-- 同一人后台也设了平台能力,但你的个人备注优先生效——标出来,别让人以为"两边不同步" -->
                  <span v-if="r.overridesGlobal" class="mp-badge override" :title="`平台设置:${r.globalRole || '—'}｜${r.globalExpertise || '—'}。点「清除」可恢复用平台设置`">已覆盖平台设置</span>
                </div>
                <div class="mp-item-uid">{{ r.id }}</div>
                <div v-if="r.expertise" class="mp-item-exp">擅长：{{ r.expertise }}</div>
                <div v-if="r.overridesGlobal" class="mp-item-gl">平台设置：{{ r.globalRole || '—' }}｜{{ r.globalExpertise || '—' }}（你的备注优先生效，点「清除」恢复平台设置）</div>
              </div>
              <div class="mp-item-act">
                <button class="mp-mini" :disabled="busy" @click="startEdit(r)">{{ r.hasProfile ? '编辑能力' : '设置能力' }}</button>
                <!-- 方案B:管理员把个人标注提升为平台能力(全平台可见)。仅对「已设且非平台来源」的条目显示 -->
                <button v-if="amAdmin && r.hasProfile && !r.isGlobal" class="mp-mini sync" :disabled="busy"
                        title="把这条能力同步到平台名册，全平台可见（管理员）" @click="keepScroll(() => promote(r.id))">同步到平台</button>
                <button v-if="r.hasProfile" class="mp-mini danger" :disabled="busy" @click="keepScroll(() => remove(r.id))">清除</button>
              </div>
            </li>
          </ul>
          <div v-else class="mp-empty">还没有联系人。先和别人建群/私信（或被拉进专班），TA 们会自动出现在这里。</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useMyPeople } from '@/composables/useMyPeople'
const { visible, rows, loading, busy, editing, adding, errText, form, amAdmin, close, startEdit, startAdd, save, remove, promote } = useMyPeople()

// 滚动位置保持(负责人报:列表滑到中间,进「编辑能力」再取消,滚回顶部还得重新找人)。
// 列表与编辑视图在同一滚动容器 .mp-body 里 v-if 切换——进编辑时列表销毁、返回时重建,
// scrollTop 归零。进编辑前记下位置,退出编辑后 nextTick(DOM 重建完)恢复。
const bodyEl = ref<HTMLElement>()
let savedScroll = 0
watch(editing, (v) => {
  if (v) {
    savedScroll = bodyEl.value?.scrollTop || 0
  } else {
    nextTick(() => { if (bodyEl.value) bodyEl.value.scrollTop = savedScroll })
  }
})

// 「同步到平台」/「清除」这类操作内部会 load() 全量重拉、列表重渲染,scrollTop 归零
// (负责人报:列表滑到中间点「同步到平台」,页面弹回顶部还得重新找人)。包一层:操作前记下
// 滚动位置,重渲染后 nextTick 恢复。
async function keepScroll(fn: () => Promise<unknown>) {
  const y = bodyEl.value?.scrollTop || 0
  try { await fn() } finally {
    nextTick(() => { if (bodyEl.value) bodyEl.value.scrollTop = y })
  }
}
</script>

<style scoped>
.mp-overlay { position: fixed; inset: 0; z-index: 210; background: rgba(0,0,0,0.34); display: flex; align-items: center; justify-content: center; }
.mp-modal { width: min(560px, 94vw); height: min(660px, 90vh); display: flex; flex-direction: column; background: var(--bg-panel); border-radius: 16px; box-shadow: 0 28px 72px rgba(0,0,0,0.24); overflow: hidden; }
.mp-head { display: flex; align-items: center; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.mp-title-wrap { display: flex; flex-direction: column; gap: 2px; }
.mp-title { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-400); color: var(--text); }
.mp-sub { font-size: var(--fs-75); color: var(--text-3); }
.mp-close { margin-left: auto; width: 30px; height: 30px; border: none; background: transparent; font-size: 22px; color: var(--text-3); cursor: pointer; border-radius: 6px; }
.mp-close:hover { background: var(--bg-hover); color: var(--text); }
.mp-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
.mp-edit { display: flex; flex-direction: column; gap: 8px; }
.mp-edit-who { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); }
.mp-edit-who .mp-uid { font-size: var(--fs-75); font-weight: 400; color: var(--text-3); margin-left: 6px; }
.mp-row { display: flex; gap: 8px; }
.mp-input, .mp-textarea { width: 100%; box-sizing: border-box; padding: 9px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg-soft); color: var(--text); font-size: var(--fs-100); font-family: inherit; }
.mp-textarea { resize: vertical; line-height: 1.5; }
.mp-input:focus, .mp-textarea:focus { outline: none; border-color: var(--accent); }
.mp-chk { font-size: var(--fs-75); color: var(--text-2); display: flex; align-items: center; gap: 6px; }
.mp-err { margin: 0; padding: 8px 12px; border-radius: 8px; background: rgba(192,57,43,0.08); color: #c0392b; font-size: var(--fs-75); line-height: 1.5; }
.mp-bar { display: flex; justify-content: flex-end; gap: 8px; }
.mp-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mp-hint { font-size: var(--fs-75); color: var(--text-3); }
.mp-btn { padding: 7px 16px; border: none; border-radius: 8px; background: var(--accent); color: #fff; cursor: pointer; font-size: var(--fs-75); font-weight: var(--fw-bold); }
.mp-btn.ghost { background: transparent; color: var(--text-2); border: 1px solid var(--border); }
.mp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.mp-item { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-soft); }
.mp-item-main { flex: 1; min-width: 0; }
.mp-item-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mp-role { font-size: var(--fs-75); color: var(--accent); background: var(--bg-panel); border-radius: 999px; padding: 1px 8px; }
.mp-badge { font-size: var(--fs-75); color: var(--text-3); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }
.mp-badge.on { color: #2f7d4f; border-color: #2f7d4f; }
.mp-badge.global { color: var(--accent); border-color: var(--accent); }
.mp-badge.override { color: #8a6a3a; border-color: #d9b877; background: #faf3e3; }
.mp-item-gl { font-size: var(--fs-75); color: var(--text-3); margin-top: 3px; line-height: 1.4; }
.mp-item-uid { font-size: var(--fs-75); color: var(--text-3); margin-top: 2px; }
.mp-item-exp { font-size: var(--fs-75); color: var(--text-2); margin-top: 4px; line-height: 1.4; }
.mp-item-act { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
.mp-mini { border: 1px solid var(--border); background: transparent; color: var(--text-2); padding: 3px 10px; border-radius: 6px; cursor: pointer; font-size: var(--fs-75); }
.mp-mini.danger:hover { color: #c0392b; }
.mp-mini.sync { color: var(--accent); border-color: var(--accent); }
.mp-mini.sync:hover { background: var(--bg-soft); }
.mp-empty { padding: 30px 12px; text-align: center; color: var(--text-3); font-size: var(--fs-75); line-height: 1.6; }
</style>
