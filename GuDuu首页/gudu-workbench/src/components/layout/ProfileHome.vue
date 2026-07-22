<template>
  <div v-if="visible" class="ph-overlay" @click.self="close">
    <div class="ph-modal" :class="{ expanded }">
      <!-- 悬浮控制：分享 / 设置 / 放大 / 关闭 -->
      <div class="ph-controls">
        <button class="ph-ctl-btn" title="分享主页" @click="notify('🔗', '分享主页', '主页链接已复制到剪贴板（演示）。')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/></svg>
        </button>
        <button class="ph-ctl-btn" title="账号设置" @click="openSettings()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
        </button>
        <button class="ph-ctl-btn" :title="expanded ? '还原' : '放大'" @click="expanded = !expanded">
          <svg v-if="!expanded" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3"/></svg>
        </button>
        <button class="ph-ctl-btn" title="关闭" @click="close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>

      <div class="ph-scroll">
      <!-- 封面 -->
      <div class="ph-banner">
        <div class="ph-banner-brand-wrap">
          <span class="ph-banner-brand">GuDuu OS</span>
          <button class="ph-banner-edit" title="编辑封面">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
          </button>
        </div>
      </div>

      <div class="ph-body">
        <!-- 左：资料卡 -->
        <aside class="ph-side">
          <div class="ph-avatar" :data-avatar="user.avatar">{{ user.avatar }}</div>
          <div class="ph-name">{{ user.name }}</div>
          <div class="ph-handle">{{ user.handle }}</div>
          <div class="ph-bio">这里是介绍</div>

          <div class="ph-stats">
            <div><b>0</b> <span>关注者</span></div>
            <div><b>0</b> <span>关注中</span></div>
          </div>

          <div class="ph-links">
            <button v-for="l in socialLinks" :key="l" class="ph-link">
              <span class="ph-link-ic">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
              </span>
              添加 {{ l }} 链接
            </button>
          </div>

          <button class="ph-cc">设置版权许可</button>
        </aside>

        <!-- 右：内容 -->
        <main class="ph-main">
          <div class="ph-tabs">
            <button v-for="t in tabs" :key="t" class="ph-tab" :class="{ active: tab === t }" @click="tab = t">{{ t }}</button>
          </div>

          <div class="ph-panel">
            <!-- My Listings -->
            <template v-if="tab === '我的上架'">
              <div class="ph-panel-top">
                <div class="ph-seg">
                  <button class="ph-seg-btn" :class="{ active: listMode === 'now' }" @click="listMode = 'now'">上架中</button>
                  <button class="ph-seg-btn" :class="{ active: listMode === 'removed' }" @click="listMode = 'removed'">已下架</button>
                </div>
                <button class="ph-add">＋ 上架</button>
              </div>
              <div v-if="listMode === 'now'" class="ph-grid">
                <div v-for="it in listings" :key="it.title" class="ph-card">
                  <div class="ph-card-img" :style="{ background: it.bg }">
                    <span class="ph-card-badge">{{ it.cat }}</span>
                  </div>
                  <div class="ph-card-info">
                    <div class="ph-card-title">{{ it.title }}</div>
                    <div class="ph-card-sub">{{ it.sub }}</div>
                  </div>
                  <div class="ph-card-price">{{ it.price }}</div>
                </div>
              </div>
              <div v-else class="ph-empty">暂无下架内容</div>
            </template>

            <!-- 我的购买 -->
            <template v-else-if="tab === '我的购买'">
              <div class="ph-grid">
                <div v-for="it in purchases" :key="it.title" class="ph-card">
                  <div class="ph-card-img" :style="{ background: it.bg }"><span class="ph-card-badge">{{ it.cat }}</span></div>
                  <div class="ph-card-info">
                    <div class="ph-card-title">{{ it.title }}</div>
                    <div class="ph-card-sub">{{ it.sub }}</div>
                  </div>
                  <div class="ph-card-price done">已拥有</div>
                </div>
              </div>
            </template>

            <!-- 我的团队 -->
            <template v-else-if="tab === '我的团队'">
              <div class="ph-team">
                <div v-for="m in team" :key="m.name" class="ph-team-row">
                  <span class="ph-team-ava" :data-avatar="m.avatar" :style="m.color ? { background: m.color } : undefined">{{ m.avatar }}</span>
                  <span class="ph-team-name">{{ m.name }}</span>
                  <span class="ph-team-role">{{ m.role }}</span>
                </div>
              </div>
            </template>

            <!-- My Earnings -->
            <template v-else>
              <div class="ph-earn">
                <div class="ph-earn-card"><div class="ph-earn-v">¥ 12,480</div><div class="ph-earn-l">累计收益</div></div>
                <div class="ph-earn-card"><div class="ph-earn-v">¥ 2,360</div><div class="ph-earn-l">本月收益</div></div>
                <div class="ph-earn-card"><div class="ph-earn-v">86</div><div class="ph-earn-l">总销量</div></div>
                <div class="ph-earn-card"><div class="ph-earn-v">¥ 1,920</div><div class="ph-earn-l">可提现</div></div>
              </div>
            </template>
          </div>
        </main>
      </div>
      </div><!-- /ph-scroll -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useProfileHome } from '@/composables/useProfileHome'
import { useUserProfile } from '@/composables/useUserProfile'
import { notify } from '@/composables/useDemoHeartbeat'
import { currentUser, channelMembers } from '@/data/channels'

const { visible, close } = useProfileHome()
const { openSettings } = useUserProfile()

const user = { name: currentUser.name, handle: '@lin_mgr', avatar: currentUser.avatar }

const expanded = ref(false)
const tabs = ['我的上架', '我的购买', '我的团队', '我的收益']
const tab = ref('我的上架')
const listMode = ref<'now' | 'removed'>('now')

const socialLinks = ['Lark', '网站', 'Discord', 'Twitter', 'Facebook', 'Telegram']

const listings = [
  { title: '数据分析 Agent', sub: 'AI Agent · 已上架', cat: 'Agent', price: '¥199', bg: 'linear-gradient(135deg,#f59e0b,#ea580c)' },
  { title: '日报模板', sub: 'Prompt · 已上架', cat: 'Prompt', price: '免费', bg: 'linear-gradient(135deg,#4a7a8c,#2f5a6b)' },
  { title: '客服助手 Agent', sub: 'AI Agent · 已上架', cat: 'Agent', price: '¥99', bg: 'linear-gradient(135deg,#6b8e4e,#3f5a2e)' },
  { title: '合规审查 Agent', sub: 'AI Agent · 已上架', cat: 'Agent', price: '免费', bg: 'linear-gradient(135deg,#8a6a8a,#5a4060)' }
]
const purchases = [
  { title: '知识库问答检索', sub: 'Skill · /kb', cat: 'Skill', bg: 'linear-gradient(135deg,#4a7a8c,#33606f)' },
  { title: 'CRM 连接器', sub: 'MCP 连接器', cat: 'MCP', bg: 'linear-gradient(135deg,#5a7a8a,#3a5560)' },
  { title: '制度与流程库', sub: '知识库', cat: 'KB', bg: 'linear-gradient(135deg,#b58932,#8a6622)' }
]
const team = channelMembers

function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && visible.value) close() }
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.ph-overlay {
  position: fixed;
  inset: 0;
  z-index: 220;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: ph-fade 0.16s ease;
}
@keyframes ph-fade { from { opacity: 0 } to { opacity: 1 } }

.ph-modal {
  position: relative;
  width: min(1120px, 94vw);
  height: min(760px, 90vh);
  display: flex;
  flex-direction: column;
  background: #f4f5f7;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.28);
  animation: ph-pop 0.16s ease;
}
@keyframes ph-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }
.ph-modal.expanded {
  width: 100vw;
  height: 100vh;
  border-radius: 0;
}
.ph-scroll { flex: 1; min-height: 0; overflow-y: auto; }

/* 悬浮控制按钮（放大 / 关闭）*/
.ph-controls {
  position: absolute;
  top: 14px; right: 14px;
  z-index: 5;
  display: flex;
  gap: 8px;
}
.ph-ctl-btn {
  width: 32px; height: 32px;
  border: none; border-radius: 8px;
  background: rgba(255, 255, 255, 0.85);
  color: var(--text-2);
  cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  backdrop-filter: blur(2px);
  transition: background 0.12s ease, color 0.12s ease;
}
.ph-ctl-btn:hover { background: #fff; color: var(--text); }

/* 封面 */
.ph-banner {
  position: relative;
  height: 240px;
  background: linear-gradient(120deg, #e0a06f 0%, var(--accent) 55%, #a4492c 100%);
}
.ph-banner-brand-wrap {
  position: absolute; right: 40px; bottom: 56px;
  display: flex; align-items: center; gap: 14px;
}
.ph-banner-brand {
  color: #fff; font-family: var(--font-heading); font-weight: 800;
  font-size: 40px; letter-spacing: -1px;
  text-shadow: 0 2px 8px rgba(0,0,0,0.18);
}
.ph-banner-edit {
  width: 34px; height: 34px; border-radius: 8px;
  border: none; background: rgba(255,255,255,0.85); color: var(--accent); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(2px);
  transition: background 0.12s ease;
  flex-shrink: 0;
}
.ph-banner-edit:hover { background: #fff; }

/* body：整块白色内容面板（圆角顶 + 上浮压住封面）*/
.ph-body {
  display: flex; gap: 0;
  margin: -28px auto 0;
  padding: 0 32px 40px;
  position: relative; z-index: 1;
  background: var(--bg-panel);
  border-radius: 28px 28px 0 0;
}

/* 左侧资料 */
.ph-side {
  width: 300px; flex-shrink: 0;
  padding-right: 28px;
}
/* 头像嵌入白色面板的圆形凹槽 */
.ph-avatar {
  position: relative; z-index: 2;
  width: 120px; height: 120px; border-radius: 50%;
  margin-top: -62px;
  background: #5a7a8a; color: #fff; border: 7px solid var(--bg-panel);
  display: flex; align-items: center; justify-content: center;
  font-size: 42px; font-weight: 700; font-family: var(--font-heading);
}
/* 两侧凹弧：把头像白圈平滑过渡到面板顶边 */
.ph-avatar::before,
.ph-avatar::after {
  content: '';
  position: absolute;
  bottom: 7px;
  width: 26px; height: 26px;
}
.ph-avatar::before {
  left: -25px;
  background: radial-gradient(circle at top right, transparent 25px, var(--bg-panel) 25px);
}
.ph-avatar::after {
  right: -25px;
  background: radial-gradient(circle at top left, transparent 25px, var(--bg-panel) 25px);
}
.ph-name { font-family: var(--font-heading); font-weight: 800; font-size: var(--fs-500); color: var(--text); margin-top: 14px; }
.ph-handle { color: var(--text-3); font-size: var(--fs-100); }
.ph-bio { color: var(--text-2); font-size: var(--fs-100); margin: 18px 0; }
.ph-stats { display: flex; gap: 28px; margin-bottom: 20px; }
.ph-stats b { font-size: var(--fs-300); color: var(--text); }
.ph-stats span { color: var(--text-3); font-size: var(--fs-100); }
.ph-links { display: flex; flex-direction: column; gap: 4px; }
.ph-link {
  display: flex; align-items: center; gap: 12px;
  border: none; background: transparent; cursor: pointer;
  color: var(--text-3); font-size: var(--fs-100); padding: 9px 0; text-align: left;
}
.ph-link:hover { color: var(--text); }
.ph-link-ic { color: var(--text-3); display: inline-flex; }
.ph-cc {
  margin-top: 22px; width: 100%;
  border: 1.5px solid var(--accent); background: var(--bg-panel); color: var(--accent);
  font-weight: var(--fw-bold); font-size: var(--fs-100); padding: 12px; border-radius: 999px; cursor: pointer;
}
.ph-cc:hover { background: var(--accent-soft); }

/* 右侧内容 */
.ph-main { flex: 1; min-width: 0; padding-top: 28px; }
.ph-tabs { display: flex; gap: 30px; border-bottom: 1px solid var(--border); padding-bottom: 0; }
.ph-tab {
  border: none; background: transparent; cursor: pointer;
  font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-300); color: var(--text-3);
  padding-bottom: 14px; position: relative;
}
.ph-tab.active { color: var(--text); }
.ph-tab.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 3px; background: var(--accent); border-radius: 2px; }

.ph-panel { border: 1px solid var(--border); border-radius: 16px; margin-top: 22px; padding: 22px; min-height: 320px; background: var(--bg-panel); }
.ph-panel-top { display: flex; align-items: center; justify-content: center; position: relative; margin-bottom: 22px; }
.ph-seg { display: inline-flex; background: var(--bg-soft); border-radius: 999px; padding: 3px; }
.ph-seg-btn { border: none; background: transparent; cursor: pointer; padding: 7px 18px; border-radius: 999px; font-size: var(--fs-100); color: var(--text-3); }
.ph-seg-btn.active { background: var(--text); color: #fff; }
.ph-add { position: absolute; right: 0; border: none; background: var(--accent); color: #fff; font-weight: var(--fw-bold); padding: 10px 20px; border-radius: 999px; cursor: pointer; }
.ph-add:hover { filter: brightness(1.05); }

.ph-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 18px; }
.ph-card { border: 1px solid var(--border-soft); border-radius: 14px; overflow: hidden; background: var(--bg-panel); transition: box-shadow 0.15s ease, transform 0.15s ease; }
.ph-card:hover { box-shadow: 0 8px 24px rgba(0,0,0,0.08); transform: translateY(-2px); }
.ph-card-img { height: 150px; position: relative; }
.ph-card-badge { position: absolute; left: 12px; top: 12px; background: rgba(0,0,0,0.35); color: #fff; font-size: 11px; padding: 3px 9px; border-radius: 999px; }
.ph-card-info { padding: 12px 14px 4px; }
.ph-card-title { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-200); color: var(--text); }
.ph-card-sub { font-size: var(--fs-75); color: var(--text-3); margin-top: 2px; }
.ph-card-price { margin: 8px 14px 14px; display: inline-block; background: var(--accent-soft); color: var(--accent); font-weight: 800; font-size: var(--fs-100); padding: 4px 14px; border-radius: 999px; }
.ph-card-price.done { background: #ecfdf5; color: var(--ok); }

.ph-empty { text-align: center; color: var(--text-3); padding: 80px 0; }

.ph-team { display: flex; flex-direction: column; }
.ph-team-row { display: flex; align-items: center; gap: 12px; padding: 12px 4px; border-bottom: 1px solid var(--border-soft); }
.ph-team-ava { width: 34px; height: 34px; border-radius: 9px; background: #5a7a8a; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.ph-team-name { font-weight: var(--fw-bold); color: var(--text); }
.ph-team-role { margin-left: auto; color: var(--text-3); font-size: var(--fs-75); font-family: var(--font-mono); }

.ph-earn { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.ph-earn-card { border: 1px solid var(--border-soft); border-radius: 14px; padding: 22px; background: var(--bg-panel); }
.ph-earn-v { font-family: var(--font-heading); font-weight: 800; font-size: var(--fs-600); color: var(--text); }
.ph-earn-l { color: var(--text-3); font-size: var(--fs-75); margin-top: 6px; }
</style>
