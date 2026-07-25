<template>
  <div v-if="visible" class="km-overlay" @click.self="close">
    <div class="km-modal" role="dialog" aria-modal="true">
      <div class="km-head">
        <div class="km-title-wrap">
          <span class="km-title">知识库 · 我的文档</span>
          <span class="km-sub">贴入标题与正文即可入库；主 AI 回话时会自动检索并参考（个人库，全工作区可用）</span>
        </div>
        <button class="km-close" title="关闭" @click="close">×</button>
      </div>

      <div class="km-body">
        <!-- 添加表单 -->
        <div class="km-add">
          <input v-model="title" class="km-input" placeholder="标题（可空，便于以后查找）" maxlength="200" />
          <textarea
            v-model="content"
            class="km-textarea"
            placeholder="把要让 AI 记住/参考的资料正文贴这里：规范、报价、产品资料、历史结论…"
            rows="6"
          />
          <div class="km-add-bar">
            <span class="km-hint">{{ content.length }} 字</span>
            <button class="km-btn" :disabled="busy || !content.trim()" @click="add">
              {{ busy ? '处理中…' : '＋ 添加到知识库' }}
            </button>
          </div>
        </div>

        <!-- 列表 -->
        <div class="km-list-h">
          <span>已收录 {{ docs.length }} 篇</span>
          <button class="km-refresh" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
        </div>
        <ul v-if="docs.length" class="km-list">
          <li v-for="d in docs" :key="d.id" class="km-doc">
            <span class="km-doc-ic"><Icon name="pages" :size="14" /></span>
            <span class="km-doc-title">{{ d.title || '(无标题)' }}</span>
            <span class="km-doc-src">{{ srcLabel(d.source) }}</span>
            <button class="km-del" title="删除" :disabled="busy" @click="remove(d.id)">
              <Icon name="trash" :size="14" />
            </button>
          </li>
        </ul>
        <div v-else class="km-empty">还没有文档。在上面贴一段资料试试，或在频道里发「知识库 添加 标题|内容」。</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useKnowledge } from '@/composables/useKnowledge'

// 共用模块级单例：与 AI 侧栏「项目文件」面板同一份 docs，增删后两处同步
const { visible, docs, loading, busy, title, content, close, load, add, remove } = useKnowledge()

// 文档来源本地化(负责人报:文档行右侧显示英文原值 upload,和删除图标混在一起像两个操作按钮)。
// 后端 source 取值:upload(手动/粘贴/上传)、onboarding(引导)、platform/global(平台)、docpage(文档页)。
function srcLabel(src: string): string {
  const s = String(src || '')
  if (s.startsWith('docpage')) return '文档'
  return ({ upload: '上传', onboarding: '引导', platform: '平台', global: '平台', manual: '手动' } as Record<string, string>)[s] || s
}
</script>

<style scoped>
.km-overlay {
  position: fixed; inset: 0; z-index: 210;
  background: rgba(0, 0, 0, 0.34);
  display: flex; align-items: center; justify-content: center;
  animation: km-fade 0.14s ease;
}
@keyframes km-fade { from { opacity: 0 } to { opacity: 1 } }

.km-modal {
  width: min(720px, 94vw); height: min(680px, 90vh);
  display: flex; flex-direction: column;
  background: var(--bg-panel); border-radius: 16px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.24), 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden; animation: km-pop 0.16s ease;
}
@keyframes km-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }

.km-head {
  display: flex; align-items: center; gap: 16px;
  padding: 16px 20px; border-bottom: 1px solid var(--border);
}
.km-title-wrap { display: flex; flex-direction: column; gap: 2px; }
.km-title { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-400); color: var(--text); }
.km-sub { font-size: var(--fs-75); color: var(--text-3); }
.km-close {
  margin-left: auto; width: 30px; height: 30px;
  border: none; background: transparent; font-size: 22px; line-height: 1;
  color: var(--text-3); cursor: pointer; border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
}
.km-close:hover { background: var(--bg-hover); color: var(--text); }

.km-body { flex: 1; overflow-y: auto; padding: 16px 20px; }

.km-add { display: flex; flex-direction: column; gap: 8px; }
.km-input, .km-textarea {
  width: 100%; box-sizing: border-box;
  padding: 9px 12px; border: 1px solid var(--border); border-radius: 9px;
  background: var(--bg-soft); color: var(--text);
  font-size: var(--fs-100); font-family: inherit;
}
.km-textarea { resize: vertical; min-height: 96px; line-height: 1.5; }
.km-input:focus, .km-textarea:focus { outline: none; border-color: var(--accent); }
.km-add-bar { display: flex; align-items: center; justify-content: space-between; }
.km-hint { font-size: var(--fs-75); color: var(--text-3); }
.km-btn {
  padding: 7px 16px; border: none; border-radius: 8px;
  background: var(--accent); color: #fff; cursor: pointer;
  font-size: var(--fs-75); font-weight: var(--fw-bold);
  transition: opacity 0.12s ease;
}
.km-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.km-list-h {
  display: flex; align-items: center; justify-content: space-between;
  margin: 18px 0 8px; font-size: var(--fs-75); color: var(--text-2);
}
.km-refresh {
  border: 1px solid var(--border); background: transparent; color: var(--text-2);
  padding: 3px 10px; border-radius: 999px; cursor: pointer; font-size: var(--fs-75);
}
.km-refresh:hover { background: var(--bg-soft); }

.km-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.km-doc {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border: 1px solid var(--border); border-radius: 9px;
  background: var(--bg-soft);
}
.km-doc-ic { flex-shrink: 0; }
.km-doc-title { flex: 1; color: var(--text); font-size: var(--fs-100); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 来源做成低调的胶囊标签:明确它是"来源"元信息、不是操作按钮(负责人报的文字/图标混用观感) */
.km-doc-src { flex-shrink: 0; font-size: var(--fs-75); color: var(--text-3); background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }
.km-del {
  flex-shrink: 0; width: 28px; height: 28px;
  border: none; background: transparent; color: var(--text-3);
  cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center;
  transition: background 0.12s ease, color 0.12s ease;
}
.km-del:hover:not(:disabled) { background: var(--bg-hover); color: #c0392b; }
.km-del:disabled { opacity: 0.4; cursor: not-allowed; }

.km-empty { padding: 20px; text-align: center; color: var(--text-3); font-size: var(--fs-75); }
</style>
