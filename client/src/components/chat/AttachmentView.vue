<!--
  聊天消息里的附件展示：图片缩略图 / 视频播放器 / 音频播放器 / 文件下载卡片。
  关键：新版 Synapse 强制「已认证媒体」，<img>/<video> 直接引用媒体 URL 会 401 裂图，所以这里统一
  用 mxcToObjectUrl(带 token 拉成 blob) 得到 object URL 再喂给标签。组件卸载时回收 object URL。
-->
<template>
  <div class="att">
    <!-- 加载中 -->
    <div v-if="loading" class="att-loading">
      <span class="att-spin" /> 加载{{ kindLabel }}…
    </div>

    <!-- 加载失败 -->
    <div v-else-if="failed" class="att-failed" :title="att.name">
      ⚠ {{ kindLabel }}打不开（{{ att.name }}）
    </div>

    <!-- 图片：点击开新标签看原图 -->
    <a v-else-if="att.kind === 'image'" class="att-img" :href="src" target="_blank" rel="noopener" :title="att.name">
      <img :src="src" :alt="att.name" loading="lazy" />
    </a>

    <!-- 视频：内嵌播放器 -->
    <video v-else-if="att.kind === 'video'" class="att-video" :src="src" controls preload="metadata" />

    <!-- 音频：内嵌播放器 -->
    <audio v-else-if="att.kind === 'audio'" class="att-audio" :src="src" controls preload="metadata" />

    <!-- 文件：可在线预览的(PDF/文本类)点击新标签打开浏览器内置查看器;其余(Office/压缩包等
         浏览器渲染不了)保持点击下载。预览页里浏览器自带"下载"按钮,不另占一个位。 -->
    <a v-else class="att-file" :href="src" :download="previewable ? undefined : att.name"
       :target="previewable ? '_blank' : undefined" rel="noopener"
       :title="previewable ? att.name : `${att.name}（此格式暂不支持在线预览）`">
      <span class="att-file-ic">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
      </span>
      <span class="att-file-meta">
        <span class="att-file-name">{{ att.name }}</span>
        <span class="att-file-size">{{ sizeText }} · {{ previewable ? '点击在线预览' : '点击下载' }}</span>
      </span>
    </a>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { mxcToObjectUrl, type MsgAttachment } from '@/matrix/client'

const props = defineProps<{ att: MsgAttachment }>()

const src = ref('')
const loading = ref(true)
const failed = ref(false)
let objUrl = ''   // 若解析出的是 blob object URL，卸载时回收

const kindLabel = computed(() => ({ image: '图片', video: '视频', audio: '音频', file: '文件' }[props.att.kind] || '文件'))

// 可在线预览的类型:PDF(浏览器内置查看器) + 文本类(txt/md/csv/json/log…按纯文本内联显示)。
// Office(doc/pptx/xlsx)浏览器渲染不了——公网 viewer 拿不到我们的认证媒体,自托管 OnlyOffice 是
// 后话——先老实标"点击下载"。text/html 刻意**不**按 html 预览(blob 与本页同源,渲染用户上传的
// HTML 会执行其脚本=XSS),统一降级为纯文本。
const mime = computed(() => (props.att.mimetype || '').toLowerCase())
const previewable = computed(() =>
  props.att.kind === 'file'
  && (mime.value === 'application/pdf' || mime.value.startsWith('text/') || mime.value === 'application/json'))
/** 预览时喂给 blob 的 MIME:PDF 原样;文本类一律 text/plain(必内联显示,且杜绝 html 脚本执行) */
function previewMime(): string | undefined {
  if (!previewable.value) return props.att.mimetype
  return mime.value === 'application/pdf' ? 'application/pdf' : 'text/plain'
}
const sizeText = computed(() => {
  const n = props.att.size || 0
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
})

function revoke() {
  if (objUrl) { URL.revokeObjectURL(objUrl); objUrl = '' }
}

async function load(mxc: string) {
  revoke()
  loading.value = true; failed.value = false; src.value = ''
  try {
    const url = await mxcToObjectUrl(mxc, previewMime())
    if (!url) { failed.value = true; return }
    if (url.startsWith('blob:')) objUrl = url
    src.value = url
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

watch(() => props.att.mxc, (m) => { if (m) load(m) }, { immediate: true })
onBeforeUnmount(revoke)
</script>

<style scoped>
.att { margin: 4px 0 2px; }
.att-loading, .att-failed { font-size: 12px; color: var(--text-2); padding: 8px 10px; background: var(--bg-hover); border-radius: 8px; display: inline-flex; align-items: center; gap: 6px; }
.att-failed { color: #b94a4a; }
.att-spin { width: 12px; height: 12px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; display: inline-block; animation: att-spin 0.7s linear infinite; }
@keyframes att-spin { to { transform: rotate(360deg); } }
.att-img { display: inline-block; max-width: 320px; max-height: 320px; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
.att-img img { display: block; max-width: 320px; max-height: 320px; object-fit: contain; background: var(--bg-hover); }
.att-video { max-width: 360px; max-height: 300px; border-radius: 10px; background: #000; display: block; }
.att-audio { width: 300px; max-width: 100%; }
.att-file { display: inline-flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px; text-decoration: none; color: var(--text); max-width: 320px; }
.att-file:hover { background: var(--bg-hover); }
.att-file-ic { color: var(--accent); flex-shrink: 0; display: inline-flex; }
.att-file-meta { display: flex; flex-direction: column; min-width: 0; }
.att-file-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-file-size { font-size: 11px; color: var(--text-2); }
</style>
