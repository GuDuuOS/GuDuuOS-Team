<template>
  <div class="doc">
    <!-- 左：页面树 -->
    <aside class="doc-side">
      <div class="doc-side-head">
        <span class="doc-side-title"><Icon name="tutorial" :size="14" /> 图文教程</span>
        <button v-if="canWrite" class="doc-mini" title="新建顶级页面" @click="createPage(null)">＋</button>
      </div>
      <div v-if="!flatTree.length" class="doc-empty-tree">
        还没有页面{{ canWrite ? '，点 ＋ 新建' : '' }}
      </div>
      <ul class="doc-tree">
        <li
          v-for="n in flatTree" :key="n.id"
          class="doc-node" :class="{ active: n.id === currentId }"
          :style="{ paddingLeft: 8 + n.depth * 14 + 'px' }"
        >
          <span class="doc-node-title" @click="select(n.id)">
            <span v-if="!n.published" class="doc-draft-tag">草稿</span>{{ n.title || '未命名页面' }}
          </span>
          <span v-if="canWrite" class="doc-node-ops">
            <button class="doc-mini" title="置顶(移到最前)" @click.stop="pinTop(n)"><Icon name="pin" :size="14" /></button>
            <button class="doc-mini" title="上移" @click.stop="moveUp(n)">↑</button>
            <button class="doc-mini" title="下移" @click.stop="moveDown(n)">↓</button>
            <button class="doc-mini" title="新建子页" @click.stop="createPage(n.id)">＋</button>
            <button class="doc-mini danger" title="删除(含子页)" @click.stop="removePage(n)">×</button>
          </span>
        </li>
      </ul>
    </aside>

    <!-- 右：页面正文 -->
    <section class="doc-main">
      <div v-if="loading" class="doc-hint">加载中…</div>
      <div v-else-if="!currentId" class="doc-hint">
        {{ flatTree.length ? '选择左侧一个页面编辑' : (canWrite ? '点左上 ＋ 新建第一个页面' : '还没有内容') }}
      </div>
      <template v-else>
        <header class="doc-head">
          <input
            v-if="editing" v-model="editTitle" class="doc-title-input" placeholder="页面标题"
          />
          <h1 v-else class="doc-title">{{ current?.title || '未命名页面' }}</h1>
          <div class="doc-head-ops" v-if="canWrite">
            <template v-if="editing">
              <button class="doc-btn ghost" :disabled="aiBusy || saving" @click="aiWrite"><Icon name="sparkle" :size="13" /> {{ aiBusy ? 'AI 写作中…' : 'AI 写' }}</button>
              <button class="doc-btn ghost" :class="{ pubon: editPublished }" :disabled="saving" @click="editPublished = !editPublished" :title="editPublished ? '点此改为草稿' : '点此设为发布'">{{ editPublished ? '已发布 ●' : '草稿 ○' }}</button>
              <button class="doc-btn" :disabled="saving || aiBusy" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
              <button class="doc-btn ghost" :disabled="saving" @click="cancelEdit">取消</button>
            </template>
            <template v-else>
              <span class="doc-status" :class="{ on: current?.published }">{{ current?.published ? '已发布' : '草稿' }}</span>
              <button class="doc-btn ghost" @click="startEdit">编辑</button>
            </template>
          </div>
        </header>
        <div v-if="err" class="doc-err">{{ err }}</div>
        <!-- 编辑态：封面上传 -->
        <div v-if="editing" class="doc-cover-row">
          <img v-if="editCover" class="doc-cover-thumb" :src="coverUrl(editCover)" alt="封面" />
          <div v-else class="doc-cover-ph">无封面</div>
          <div class="doc-cover-ops">
            <label class="doc-btn ghost sm">
              {{ coverUploading ? '上传中…' : (editCover ? '更换封面' : '上传封面') }}
              <input type="file" accept="image/*" hidden :disabled="coverUploading" @change="onPickCover" />
            </label>
            <button v-if="editCover" class="doc-btn ghost sm" :disabled="coverUploading" @click="editCover = ''">移除</button>
          </div>
        </div>
        <!-- 编辑态：左写 Markdown 右实时预览 -->
        <div v-if="editing" class="doc-editor">
          <textarea v-model="editBody" class="doc-textarea" placeholder="用 Markdown 写教程…&#10;# 标题  - 列表  **加粗**  `代码`  ![图](http url)"></textarea>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div class="doc-preview md" v-html="renderMarkdown(editBody)"></div>
        </div>
        <!-- 阅读态 -->
        <template v-else>
          <img v-if="current?.cover" class="doc-cover-banner" :src="coverUrl(current.cover)" alt="封面" />
          <!-- eslint-disable-next-line vue/no-v-html -->
          <article class="doc-body md" v-html="renderMarkdown(current?.content_md || '')"></article>
        </template>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { onMounted, ref } from 'vue'
import {
  docTree, docGetPage, docCreatePage, docUpdatePage, docDeletePage, docMovePage,
  docCoverUrl, uploadMedia, docDraft,
  type DocPage,
} from '@/matrix/client'
import { renderMarkdown } from '@/utils/md'

const coverUrl = docCoverUrl

const pages = ref<DocPage[]>([])
const canWrite = ref(false)
const currentId = ref<number | null>(null)
const current = ref<DocPage | null>(null)
const loading = ref(false)
const err = ref('')

const editing = ref(false)
const saving = ref(false)
const editTitle = ref('')
const editBody = ref('')
const editCover = ref('')        // 封面(mxc:// 或 url)
const coverUploading = ref(false)
const aiBusy = ref(false)        // AI 写作中
const editPublished = ref(false) // 编辑中的发布状态(草稿/已发布)

// 扁平化成「带层级深度」的有序列表（按 parent + sort 组织），避免递归组件。
interface FlatNode extends DocPage { depth: number }
const flatTree = ref<FlatNode[]>([])
function rebuildTree() {
  const byParent = new Map<number | null, DocPage[]>()
  for (const p of pages.value) {
    const k = p.parent_id ?? null
    if (!byParent.has(k)) byParent.set(k, [])
    byParent.get(k)!.push(p)
  }
  for (const arr of byParent.values()) arr.sort((a, b) => a.sort - b.sort || a.id - b.id)
  const out: FlatNode[] = []
  const walk = (parent: number | null, depth: number) => {
    for (const p of byParent.get(parent) || []) {
      out.push({ ...p, depth })
      walk(p.id, depth + 1)
    }
  }
  walk(null, 0)
  flatTree.value = out
}

async function loadTree(selectFirst = true) {
  loading.value = true
  try {
    const res = await docTree()
    pages.value = res.pages
    canWrite.value = res.canWrite
    rebuildTree()
    // 当前选中页若已被删，或首次进入，挑第一页
    if (currentId.value && !pages.value.some((p) => p.id === currentId.value)) {
      currentId.value = null; current.value = null
    }
    if (selectFirst && !currentId.value && flatTree.value.length) {
      await select(flatTree.value[0].id)
    }
  } finally {
    loading.value = false
  }
}

async function select(id: number) {
  if (editing.value) return  // 编辑中不切页，避免丢未保存内容
  currentId.value = id
  current.value = await docGetPage(id)
}

async function createPage(parentId: number | null) {
  err.value = ''
  try {
    const p = await docCreatePage({ title: '新页面', parent_id: parentId })
    await loadTree(false)
    await select(p.id)
    startEdit()  // 新建后直接进编辑
  } catch (e: any) {
    err.value = e?.message || '新建失败'
  }
}

// 同一父级下的兄弟（按 sort,id 升序）——排序/置顶在兄弟范围内进行
function siblingsOf(n: FlatNode): FlatNode[] {
  const pid = n.parent_id ?? null
  return flatTree.value
    .filter((p) => (p.parent_id ?? null) === pid)
    .sort((a, b) => a.sort - b.sort || a.id - b.id)
}

// 与相邻兄弟交换 sort 实现上/下移；置顶=把 sort 设到比所有兄弟都小。写权限走后端 move 端点强制。
async function swapWith(a: FlatNode, b: FlatNode) {
  // 两个兄弟的 sort 互换（保持各自 parent 不变）
  await docMovePage(a.id, { parent_id: a.parent_id, sort: b.sort })
  await docMovePage(b.id, { parent_id: b.parent_id, sort: a.sort })
  await loadTree(false)
}
async function moveUp(n: FlatNode) {
  const sibs = siblingsOf(n); const i = sibs.findIndex((s) => s.id === n.id)
  if (i > 0) await swapWith(n, sibs[i - 1])
}
async function moveDown(n: FlatNode) {
  const sibs = siblingsOf(n); const i = sibs.findIndex((s) => s.id === n.id)
  if (i >= 0 && i < sibs.length - 1) await swapWith(n, sibs[i + 1])
}
async function pinTop(n: FlatNode) {
  const sibs = siblingsOf(n)
  if (sibs[0]?.id === n.id) return  // 已在最前
  const minSort = Math.min(...sibs.map((s) => s.sort))
  await docMovePage(n.id, { parent_id: n.parent_id, sort: minSort - 1 })
  await loadTree(false)
}

async function removePage(n: FlatNode) {
  if (!confirm(`删除「${n.title || '未命名页面'}」及其所有子页？此操作不可撤销。`)) return
  const ok = await docDeletePage(n.id)
  if (!ok) { err.value = '删除失败'; return }
  if (currentId.value === n.id) { currentId.value = null; current.value = null }
  editing.value = false
  await loadTree()
}

function startEdit() {
  if (!current.value) return
  editTitle.value = current.value.title
  editBody.value = current.value.content_md || ''
  editCover.value = current.value.cover || ''
  editPublished.value = current.value.published ?? false
  editing.value = true
}
function cancelEdit() { editing.value = false; err.value = '' }

async function onPickCover(e: Event) {
  const file = (e.target as HTMLInputElement)?.files?.[0]
  if (!file) return
  coverUploading.value = true; err.value = ''
  try {
    editCover.value = await uploadMedia(file)  // 上传到 Matrix 媒体库，存 mxc://
  } catch (ex: any) {
    err.value = ex?.message || '封面上传失败'
  } finally {
    coverUploading.value = false
    ;(e.target as HTMLInputElement).value = ''  // 允许重复选同一文件
  }
}

async function aiWrite() {
  const topic = window.prompt('给 AI 一个主题/要求，它会写成 Markdown 填入正文（已有正文会作为改进基础）：')
  if (!topic || !topic.trim()) return
  aiBusy.value = true; err.value = ''
  try {
    const md = await docDraft(topic.trim(), editBody.value)
    editBody.value = md
    // 标题还空着/还是默认「新页面」→ 用正文首个一级标题自动填
    if (!editTitle.value.trim() || editTitle.value === '新页面') {
      const m = md.match(/^#\s+(.+)$/m)
      if (m) editTitle.value = m[1].trim()
    }
  } catch (e: any) {
    err.value = e?.message || 'AI 生成失败'
  } finally {
    aiBusy.value = false
  }
}

async function save() {
  if (!currentId.value) return
  saving.value = true; err.value = ''
  try {
    const updated = await docUpdatePage(currentId.value, {
      title: editTitle.value.trim() || '未命名页面',
      content_md: editBody.value,
      cover: editCover.value,
      published: editPublished.value,
    })
    current.value = updated
    editing.value = false
    await loadTree(false)  // 标题/封面可能变，刷新树
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(loadTree)
</script>

<style scoped>
.doc { display: flex; height: 100%; min-height: 0; background: #fff; }
.doc-side {
  width: 240px; flex-shrink: 0; border-right: 1px solid #eae6df;
  display: flex; flex-direction: column; background: #faf9f6; overflow-y: auto;
}
.doc-side-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 12px 8px; font-size: 13px; color: #6b665e;
}
.doc-side-title { font-weight: 600; }
.doc-empty-tree { padding: 12px; font-size: 12px; color: #ada699; }
.doc-tree { list-style: none; margin: 0; padding: 0 4px 12px; }
.doc-node {
  display: flex; align-items: center; justify-content: space-between;
  border-radius: 6px; padding-right: 4px; cursor: default;
}
.doc-node:hover { background: #f1efe9; }
.doc-node.active { background: #faece7; }
.doc-node-title {
  flex: 1; padding: 6px 4px; font-size: 13px; color: #2c2a26; cursor: pointer;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.doc-node-ops { display: none; gap: 2px; }
.doc-node:hover .doc-node-ops { display: inline-flex; }
.doc-mini {
  border: none; background: transparent; color: #8a8378; cursor: pointer;
  font-size: 14px; line-height: 1; padding: 4px 6px; border-radius: 4px;
}
.doc-mini:hover { background: #e8e3da; color: #2c2a26; }
.doc-mini.danger:hover { background: #f6d9cf; color: #993c1d; }

.doc-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.doc-hint { padding: 40px; color: #ada699; font-size: 14px; }
.doc-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 20px 32px 8px;
}
.doc-title { font-size: 24px; font-weight: 700; color: #2c2a26; margin: 0; }
.doc-title-input {
  flex: 1; font-size: 22px; font-weight: 700; color: #2c2a26;
  border: none; border-bottom: 1px solid #eae6df; padding: 4px 0; outline: none;
}
.doc-head-ops { display: flex; gap: 8px; flex-shrink: 0; }
.doc-btn {
  border: 1px solid #c96442; background: #c96442; color: #fff; border-radius: 8px;
  padding: 6px 14px; font-size: 13px; cursor: pointer;
}
.doc-btn.ghost { background: #fff; color: #6b665e; border-color: #d8d2c8; }
.doc-btn.ghost.pubon { color: #3a7a3a; border-color: #bcdcbc; background: #f0f7f0; }
.doc-status { font-size: 12px; color: #b58932; align-self: center; }
.doc-status.on { color: #3a7a3a; }
.doc-draft-tag {
  display: inline-block; font-size: 11px; color: #b58932; background: #fbf2dd;
  border-radius: 4px; padding: 0 4px; margin-right: 4px;
}
.doc-btn:disabled { opacity: .6; cursor: default; }
.doc-err { margin: 0 32px; color: #993c1d; font-size: 13px; }

/* 封面：编辑态的上传行 + 阅读态横幅 */
.doc-cover-row { display: flex; align-items: center; gap: 12px; padding: 4px 32px 8px; }
.doc-cover-thumb { width: 120px; height: 68px; object-fit: cover; border-radius: 8px; border: 1px solid #eae6df; }
.doc-cover-ph {
  width: 120px; height: 68px; border-radius: 8px; border: 1px dashed #d8d2c8;
  display: flex; align-items: center; justify-content: center; color: #ada699; font-size: 12px;
}
.doc-cover-ops { display: flex; gap: 8px; }
.doc-btn.sm { padding: 4px 10px; font-size: 12px; cursor: pointer; }
.doc-cover-banner { display: block; max-width: 100%; max-height: 320px; object-fit: cover; border-radius: 10px; margin: 0 0 14px; }

.doc-editor { flex: 1; display: flex; min-height: 0; gap: 1px; background: #eae6df; margin-top: 8px; }
.doc-textarea {
  flex: 1; border: none; outline: none; padding: 20px 32px; font-size: 14px;
  line-height: 1.7; resize: none; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #fff;
}
.doc-preview { flex: 1; overflow-y: auto; padding: 20px 32px; background: #fff; }
.doc-body { flex: 1; overflow-y: auto; padding: 8px 32px 40px; }

/* Markdown 渲染样式 */
.md { font-size: 15px; line-height: 1.8; color: #2c2a26; }
.md :deep(h1) { font-size: 22px; margin: 20px 0 10px; }
.md :deep(h2) { font-size: 18px; margin: 18px 0 8px; }
.md :deep(h3) { font-size: 16px; margin: 16px 0 6px; }
.md :deep(p) { margin: 8px 0; }
.md :deep(ul), .md :deep(ol) { margin: 8px 0; padding-left: 24px; }
.md :deep(li) { margin: 4px 0; }
.md :deep(blockquote) {
  margin: 10px 0; padding: 6px 14px; border-left: 3px solid #d8d2c8;
  color: #6b665e; background: #faf9f6;
}
.md :deep(.md-pre) {
  background: #2c2a26; color: #f1efe9; border-radius: 8px; padding: 12px 14px;
  overflow-x: auto; font-size: 13px; line-height: 1.5;
}
.md :deep(.md-code) {
  background: #f1efe9; border-radius: 4px; padding: 1px 5px; font-size: 13px;
}
.md :deep(.md-img) { max-width: 100%; border-radius: 8px; margin: 8px 0; }
.md :deep(a) { color: #c96442; }
.md :deep(.mention) { color: #4a7a8c; font-weight: 600; }
</style>
