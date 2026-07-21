<template>
  <div v-if="visible" class="ph-overlay" @click.self="close">
    <div class="ph-modal" :class="{ expanded }">
      <!-- 悬浮控制：分享 / 设置 / 放大 / 关闭 -->
      <div class="ph-controls">
        <button class="ph-ctl-btn" title="分享" @click="onShare">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/></svg>
        </button>
        <button class="ph-ctl-btn" title="设置" @click="onSettings">
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
          <button class="ph-banner-edit" title="编辑封面" @click="toast('🖼 编辑封面', '上传 / 更换主页封面图（演示）')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
          </button>
        </div>
      </div>

      <div class="ph-body">
        <!-- 左：资料卡 -->
        <aside class="ph-side">
          <div class="ph-avatar">
            <img v-if="user.avatar" :src="user.avatar" alt="" class="ph-avatar-img" />
            <template v-else>{{ (user.name[0] || '我') }}</template>
          </div>
          <div class="ph-name">{{ user.name }}</div>
          <div class="ph-handle">{{ user.handle }}</div>
          <div class="ph-bio">这里是介绍</div>

          <div class="ph-stats">
            <div><b>0</b> <span>关注者</span></div>
            <div><b>0</b> <span>关注中</span></div>
          </div>

          <div class="ph-links">
            <button v-for="l in socialLinks" :key="l" class="ph-link" @click="toast('打开链接', `${l}（演示）`)">
              <span class="ph-link-ic">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
              </span>
              添加 {{ l }} 链接
            </button>
          </div>

          <button class="ph-cc" @click="toast('版权许可', '为作品设置授权方式（演示）')">设置版权许可</button>
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
                <button class="ph-add" @click="success('新增上架', '把你的模板 / 服务 / 课程上架到主页（演示）')">＋ 上架</button>
              </div>
              <div v-if="listMode === 'now' && listings.length" class="ph-grid">
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
              <div v-else class="ph-empty">你还没有上架任何内容（模板/服务/课程上架功能开发中）</div>
            </template>

            <!-- 我的购买 -->
            <template v-else-if="tab === '我的购买'">
              <div v-if="purchases.length" class="ph-grid">
                <div v-for="it in purchases" :key="it.title" class="ph-card">
                  <div class="ph-card-img" :style="{ background: it.bg }"><span class="ph-card-badge">{{ it.cat }}</span></div>
                  <div class="ph-card-info">
                    <div class="ph-card-title">{{ it.title }}</div>
                    <div class="ph-card-sub">{{ it.sub }}</div>
                  </div>
                  <div class="ph-card-price done">已拥有</div>
                </div>
              </div>
              <div v-else class="ph-empty">你还没有购买任何内容</div>
            </template>

            <!-- 我的团队 = 真实协作人名册 -->
            <template v-else-if="tab === '我的团队'">
              <div v-if="team.length" class="ph-team">
                <div v-for="m in team" :key="m.name" class="ph-team-row">
                  <span class="ph-team-ava" :style="m.color ? { background: m.color } : undefined">{{ m.avatar }}</span>
                  <span class="ph-team-name">{{ m.name }}</span>
                  <span class="ph-team-role">{{ m.role }}</span>
                </div>
              </div>
              <div v-else class="ph-empty">还没有协作人。去「我的协作人」里添加常合作的人，AI 派单时能用上。</div>
            </template>

            <!-- 我的收益（交易/分成后端未接，先不显示假数据）-->
            <template v-else>
              <div class="ph-empty">收益统计功能开发中，敬请期待。</div>
            </template>
          </div>
        </main>
      </div>
      </div><!-- /ph-scroll -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useProfileHome } from '@/composables/useProfileHome'
import { useUserProfile } from '@/composables/useUserProfile'
import { useMyPeople } from '@/composables/useMyPeople'
import { useToast } from '@/composables/useToast'
import { myProfileInfo } from '@/matrix/client'

const { visible, close } = useProfileHome()
const { openSettings } = useUserProfile()
const { load: loadPeople, rows: peopleRows } = useMyPeople()
const { success, toast } = useToast()

// 个人主页展示**当前登录者本人**的资料（名/句柄/头像），而不是写死的演示人物。
// 面板打开(visible=true)时刷新——此时 Matrix 已登录、能拿到真实信息。
const user = ref<{ name: string; handle: string; avatar: string }>({ name: '我', handle: '', avatar: '' })
function loadUser() {
  const info = myProfileInfo()
  user.value = {
    name: info.name || '我',
    handle: info.userId,               // @user:cosmac.cc
    avatar: info.avatarUrl,            // 有头像=http 地址；没有=空串(模板回退首字母)
  }
}
watch(visible, (v) => { if (v) { loadUser(); loadPeople() } }, { immediate: true })

const expanded = ref(false)
const tabs = ['我的上架', '我的购买', '我的团队', '我的收益']
const tab = ref('我的上架')
const listMode = ref<'now' | 'removed'>('now')

const socialLinks = ['Lark', '网站', 'Discord', 'Twitter', 'Facebook', 'Telegram']

// 上架/购买/收益对应的市场·交易后端还没接（模块5），先不放假数据 → 空态，等接了再填真数。
const listings: { title: string; sub: string; cat: string; price: string; bg: string }[] = []
const purchases: { title: string; sub: string; cat: string; bg: string }[] = []
// 我的团队 = 当前登录者真实的「协作人名册」（cosmac DB），不再用写死的演示团队。
const team = computed(() => peopleRows.value.map((p: any) => ({
  name: p.name || p.id,
  role: p.role || p.expertise || '协作人',
  avatar: (p.name || p.id || '?').replace(/^@/, '')[0] || '?',
  color: undefined as string | undefined,
})))

function onShare() {
  success('已复制主页链接', '链接已复制到剪贴板（演示）')
}
function onSettings() {
  openSettings('profile')
}

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
.ph-avatar-img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
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
