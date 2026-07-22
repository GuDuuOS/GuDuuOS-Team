<template>
  <!-- 官网 · 个人版（默认首页）。企业版（含 DI 演示）在 /enterprise。
       风格沿用 website.css 的暗色橙体系；本页新版式用 scoped 样式补充。 -->
  <div ref="siteShell" class="site-shell" @scroll.passive="updateScroll">
    <header class="site-nav" :class="{ scrolled }">
      <a class="site-brand" href="#top" aria-label="GuDuu OS 首页" @click.prevent="scrollToSection('top')">
        <img src="/gudu-logo.svg" alt="" />
        <span>GuDuu OS</span>
      </a>

      <!-- 个人版 / 企业版 切换器 -->
      <nav class="edition-switch" aria-label="版本切换">
        <span class="edition-on">个人版</span>
        <RouterLink class="edition-off" :to="{ name: 'enterprise' }">企业版</RouterLink>
      </nav>

      <nav class="site-nav-links" aria-label="官网导航">
        <a href="#dna" @click.prevent="scrollToSection('dna')">特性</a>
        <a href="#collab" @click.prevent="scrollToSection('collab')">协作</a>
        <a href="#build" @click.prevent="scrollToSection('build')">搭建</a>
        <a href="#future" @click.prevent="scrollToSection('future')">未来</a>
      </nav>

      <div class="nav-actions">
        <a class="site-nav-login" :href="appHref">登录 / 注册</a>
      </div>
    </header>

    <main id="top">
      <!-- ===== Hero ===== -->
      <section class="hero-section p-hero">
        <div class="hero-aurora hero-aurora-one"></div>
        <div class="hero-aurora hero-aurora-two"></div>
        <div class="hero-grid"></div>

        <div class="hero-copy">
          <div class="hero-kicker reveal reveal-1">
            <span class="status-pulse"></span>
            个人 AI 操作系统 · 开放注册
          </div>
          <h1 class="reveal reveal-2">
            把 AI 装进<br />
            <span class="gradient-text">你自己的<br />操作系统</span>
          </h1>
          <p class="hero-lead reveal reveal-3">
            独立的账号与空间，数据主权归你。
            在这里，你和 AI 聊天，AI 和 AI 协作，真人伙伴随时加入——
            一个属于你自己的 AI 工作系统。
          </p>
          <div class="hero-actions reveal reveal-4">
            <a class="primary-button" :href="appHref">
              免费开始使用
              <span class="button-arrow">→</span>
            </a>
            <RouterLink class="ghost-button" :to="{ name: 'enterprise' }">
              看企业版演示
              <span class="button-arrow">→</span>
            </RouterLink>
          </div>
          <div class="hero-proof reveal reveal-5">
            <span>开放标准</span>
            <i></i>
            <span>数据主权</span>
            <i></i>
            <span>人机协同</span>
          </div>
        </div>

        <!-- 右侧：人与 AI / AI 与 AI 的聊天示意 -->
        <div class="p-chat reveal reveal-3" aria-hidden="true">
          <div class="p-chat-head">
            <span class="p-chat-dot"></span>
            <b># 我的工作区 · 中枢 AI</b>
            <em>LIVE</em>
          </div>
          <div class="p-chat-body">
            <div class="p-msg me">
              <div class="p-bubble">帮我把这周的灵感整理成一篇选题清单</div>
              <span class="p-ava you">我</span>
            </div>
            <div class="p-msg">
              <span class="p-ava ai">智</span>
              <div class="p-bubble">收到。我读取了你的知识库与本周对话记忆，正在整理……已生成 8 条选题，放进「选题策划」频道了。</div>
            </div>
            <div class="p-a2a">
              <span class="p-a2a-line"></span>
              <span class="p-a2a-tag">AI × AI 协作</span>
              <span class="p-a2a-line"></span>
            </div>
            <div class="p-msg">
              <span class="p-ava agent">文</span>
              <div class="p-bubble small">@数据分身 需要近 30 天的互动数据来排序选题</div>
            </div>
            <div class="p-msg">
              <span class="p-ava agent2">数</span>
              <div class="p-bubble small">已完成分析并回传，Top3 选题置信度 92%。</div>
            </div>
          </div>
          <div class="p-chat-foot">
            <span>✦</span> 一句话下达目标，剩下交给你的 AI 们
          </div>
        </div>
      </section>

      <!-- ===== 数据主权 ===== -->
      <section id="dna" class="p-section p-light">
        <div class="section-eyebrow">YOUR DATA, YOUR RULES</div>
        <h2 class="p-h2">数据主权，<br />从第一天就归你。</h2>
        <div class="p-cards3">
          <article class="p-card">
            <span class="p-card-no">01</span>
            <h3>开放通信标准</h3>
            <p>不是又一个封闭 App。GuDuu OS 构建在开放的通信标准之上，账号、消息、频道都可迁移、可互通——你不会被任何一家平台锁死。</p>
          </article>
          <article class="p-card">
            <span class="p-card-no">02</span>
            <h3>数据主权</h3>
            <p>你的账号与数据存放在独立空间，不与他人混用。团队与企业还可以选择私有化独立部署，把整套系统放进自己的服务器。</p>
          </article>
          <article class="p-card">
            <span class="p-card-no">03</span>
            <h3>真·即时通讯</h3>
            <p>它首先是一个完整的 IM：和真人好友、伙伴实时聊天，建频道、拉成员、发文件——AI 就工作在你们的对话里，而不是另一个孤立窗口。</p>
          </article>
        </div>
      </section>

      <!-- ===== 人与 AI · AI 与 AI ===== -->
      <section id="collab" class="p-section p-dark">
        <div class="section-eyebrow">HUMAN × AI × AI</div>
        <h2 class="p-h2">你和 AI 对话，<br />AI 和 AI 协作。</h2>
        <div class="p-cards2">
          <article class="p-bigcard">
            <div class="p-bigcard-tag">人 ↔ AI</div>
            <h3>一句话下达目标</h3>
            <p>中枢 AI 常驻在你的每个频道：@ 它提问、让它建群拉人、跑任务、查数据。它带着你的三层记忆工作——听得懂上下文，不用每次从头解释。</p>
            <ul>
              <li>频道里 @AI 即时应答</li>
              <li>私人会话一对一深聊</li>
              <li>建专班、派任务、盯进度</li>
            </ul>
          </article>
          <article class="p-bigcard">
            <div class="p-bigcard-tag">AI ↔ AI</div>
            <h3>多智能体一起干活</h3>
            <p>不止一个 AI。你可以创建多个分身智能体，它们各带人设与技能，在频道里互相 @、互相派单、交叉核对，像一个小团队那样把事情做完。</p>
            <ul>
              <li>多分身分工：策划、数据、执行</li>
              <li>AI 之间对话、协商、回填结果</li>
              <li>关键节点由你审批，人始终在环上</li>
            </ul>
          </article>
        </div>
      </section>

      <!-- ===== 搭建你自己的 OS ===== -->
      <section id="build" class="p-section p-cream">
        <div class="section-eyebrow">BUILD YOUR OWN OS</div>
        <h2 class="p-h2">不是用一个工具，<br />是搭一个属于你的系统。</h2>
        <div class="p-cards4">
          <article class="p-card">
            <h3>🧠 AI 三层记忆</h3>
            <p>对话记忆、长期记忆、知识库三层叠加——你的 AI 越用越懂你，而不是每次都失忆重来。</p>
          </article>
          <article class="p-card">
            <h3>🤖 自建 AI Agent</h3>
            <p>在「我的 AI 工坊」创建你自己的智能体：起名字、定人设、选模型、绑技能，让它进驻任何频道。</p>
          </article>
          <article class="p-card">
            <h3>⚡ 技能 Skill 装配</h3>
            <p>把可复用的方法论装成技能，给不同 Agent 装配不同技能组合——像给系统装应用一样扩展 AI 的能力。</p>
          </article>
          <article class="p-card">
            <h3>🗂 工作区与频道</h3>
            <p>职能工作区 + 受众社区分开组织，频道各有自己的 AI 边界与知识库——秩序，是系统的第一能力。</p>
          </article>
        </div>
      </section>

      <!-- ===== 未来 ===== -->
      <section id="future" class="p-section p-orange">
        <div class="section-eyebrow">WHAT'S NEXT</div>
        <h2 class="p-h2">这是一个正在生长的 AI 系统。</h2>
        <div class="p-cards2">
          <article class="p-bigcard p-soon">
            <div class="p-bigcard-tag">即将到来</div>
            <h3>⌘ CLI 与本地 Agent</h3>
            <p>让 GuDuu OS 连接你的电脑：命令行入口、本地文件与应用的安全访问，把你的本地世界接进你的 AI 系统。</p>
          </article>
          <article class="p-bigcard p-soon">
            <div class="p-bigcard-tag">在路上</div>
            <h3>◈ AI 硬件</h3>
            <p>面向未来的 AI 硬件形态正在规划中——让你的操作系统走出屏幕，进入真实世界。</p>
          </article>
        </div>
      </section>

      <!-- ===== 结尾 CTA ===== -->
      <section class="closing-section">
        <div class="closing-orb"></div>
        <img src="/gudu-logo.svg" alt="" />
        <div class="section-eyebrow">YOUR OS, YOUR AI</div>
        <h2>现在就开始，<br />搭一个你自己的 AI 操作系统。</h2>
        <a class="primary-button light-button" :href="appHref">
          免费注册 GuDuu OS
          <span class="button-arrow">→</span>
        </a>
      </section>
    </main>

    <footer class="site-footer">
      <a class="site-brand footer-brand" href="#top" @click.prevent="scrollToSection('top')">
        <img src="/gudu-logo.svg" alt="" />
        <span>GuDuu OS</span>
      </a>
      <p>AI-native operating system for everyone.</p>
      <span>© {{ new Date().getFullYear() }} GuDuu</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { appUrl } from '@/config/app'

// 主站地址：运行时按当前域名推导（dev 子域→dev-cs，正式→cs），零硬编码
const appHref = appUrl()

const scrolled = ref(false)
const siteShell = ref<HTMLElement | null>(null)

function updateScroll() {
  scrolled.value = (siteShell.value?.scrollTop || 0) > 24
}
function scrollToSection(id: string) {
  const shell = siteShell.value
  if (!shell) return
  if (id === 'top') { shell.scrollTo({ top: 0, behavior: 'smooth' }); return }
  const el = shell.querySelector(`#${id}`) as HTMLElement | null
  if (!el) return
  const shellTop = shell.getBoundingClientRect().top
  const targetTop = el.getBoundingClientRect().top
  shell.scrollTo({ top: shell.scrollTop + targetTop - shellTop - 64, behavior: 'smooth' })
}

onMounted(() => { document.title = 'GuDuu OS · 你的个人 AI 操作系统' })
onBeforeUnmount(() => { document.title = 'GuDuu 工作台 · 蓝湾渔业' })
</script>

<style scoped>
/* ===== Hero 右侧聊天示意 ===== */
.p-hero { align-items: center; }
.p-chat { justify-self: stretch; max-width: 560px; border: 1px solid rgba(255,255,255,.12); border-radius: 16px; background: rgba(20,17,15,.72); backdrop-filter: blur(6px); overflow: hidden; box-shadow: 0 30px 80px rgba(0,0,0,.35); }
.p-chat-head { display: flex; align-items: center; gap: 10px; padding: 13px 16px; border-bottom: 1px solid rgba(255,255,255,.08); color: rgba(255,255,255,.85); font-size: 13px; }
.p-chat-dot { width: 8px; height: 8px; border-radius: 50%; background: #57e6a5; box-shadow: 0 0 8px #57e6a5; }
.p-chat-head em { margin-left: auto; font: 600 10px/1 var(--font-mono, monospace); color: #ffb65c; letter-spacing: .12em; }
.p-chat-body { padding: 18px 16px; display: flex; flex-direction: column; gap: 12px; }
.p-msg { display: flex; gap: 10px; align-items: flex-end; }
.p-msg.me { justify-content: flex-end; }
.p-ava { flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; color: #fff; }
.p-ava.ai { background: linear-gradient(145deg, #f39a4b, #d66d20); }
.p-ava.you { background: #6d5bb7; }
.p-ava.agent { background: #b0552f; }
.p-ava.agent2 { background: #5ca8ff; }
.p-bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px; background: rgba(255,255,255,.09); color: rgba(255,255,255,.92); font-size: 13.5px; line-height: 1.6; }
.p-msg.me .p-bubble { background: #e88533; color: #fff; }
.p-bubble.small { font-size: 12.5px; color: rgba(255,255,255,.78); }
.p-a2a { display: flex; align-items: center; gap: 10px; margin: 2px 0; }
.p-a2a-line { flex: 1; height: 1px; background: linear-gradient(90deg, transparent, rgba(232,133,51,.5), transparent); }
.p-a2a-tag { font: 600 10px/1 var(--font-mono, monospace); letter-spacing: .14em; color: #e88533; }
.p-chat-foot { padding: 12px 16px; border-top: 1px solid rgba(255,255,255,.08); font-size: 12.5px; color: rgba(255,255,255,.55); }
.p-chat-foot span { color: #e88533; }

/* ===== 通用板块 ===== */
/* 板块配色完全对齐企业版的明暗节奏(website-fashion.css 同源取色):
   米白 #fbf5ed(manifesto) → 暖黑 #211d1a(bridge) → 浅米 #f5eee6(advantages) → 橙渐变(case) */
.p-section { padding: 110px 6vw; }
.p-light { color: #24211f; background: #fbf5ed; }
.p-cream { color: #24211f; background: #f5eee6; }
.p-dark  { color: #fff8f1; background: radial-gradient(circle at 72% 30%, rgba(109,91,183,.18), transparent 30%), #211d1a; }
.p-orange { color: #fff; background: radial-gradient(circle at 80% 18%, rgba(109,91,183,.3), transparent 31%), linear-gradient(135deg, #d66d20 0%, #e88533 48%, #bd5630 100%); }
.p-light :deep(.section-eyebrow), .p-cream :deep(.section-eyebrow) { color: #b65b20; }
.p-dark :deep(.section-eyebrow) { color: #efaa70; }
.p-orange :deep(.section-eyebrow) { color: rgba(255,255,255,.85); }
.p-h2 { margin: 14px 0 44px; font-size: clamp(26px, 3.4vw, 40px); line-height: 1.3; font-weight: 650; }
.p-light .p-h2, .p-cream .p-h2 { color: #24211f; }
.p-dark .p-h2, .p-orange .p-h2 { color: #fff; }
.p-cards3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.p-cards4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; }
.p-cards2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
/* 卡片双态:浅段=白卡暖描边(企业版 advantages 取色);暗/橙段=半透明白 */
.p-card { padding: 26px 24px; border-radius: 14px; transition: transform .25s ease, border-color .25s ease, background .25s ease; }
.p-light .p-card, .p-cream .p-card { border: 1px solid #e7dcd1; background: #fffdf9; }
.p-light .p-card:hover, .p-cream .p-card:hover { transform: translateY(-4px); border-color: #e88533; }
.p-card-no { font: 600 11px/1 var(--font-mono, monospace); color: #b65b20; letter-spacing: .12em; }
.p-light .p-card h3, .p-cream .p-card h3 { color: #24211f; }
.p-card h3 { margin: 12px 0 10px; font-size: 16.5px; }
.p-light .p-card p, .p-cream .p-card p { color: #746b64; }
.p-card p { font-size: 13.5px; line-height: 1.75; }
.p-bigcard { padding: 32px 30px; border-radius: 16px; }
.p-dark .p-bigcard { border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.04); }
.p-orange .p-bigcard { border: 1px solid rgba(255,255,255,.32); background: rgba(255,255,255,.12); backdrop-filter: blur(4px); }
.p-bigcard-tag { display: inline-block; padding: 5px 12px; border-radius: 999px; font: 600 11px/1 var(--font-mono, monospace); letter-spacing: .1em; }
.p-dark .p-bigcard-tag { color: #efaa70; border: 1px solid rgba(239,170,112,.5); }
.p-orange .p-bigcard-tag { color: #fff; border: 1px solid rgba(255,255,255,.55); }
.p-bigcard h3 { margin: 16px 0 12px; font-size: 20px; color: #fff; }
.p-bigcard p { font-size: 14px; line-height: 1.8; color: rgba(255,255,255,.78); }
.p-bigcard ul { margin: 14px 0 0; padding: 0; list-style: none; }
.p-bigcard li { position: relative; padding: 6px 0 6px 20px; font-size: 13.5px; color: rgba(255,255,255,.85); }
.p-bigcard li::before { content: ''; position: absolute; left: 0; top: 13px; width: 8px; height: 8px; border-radius: 2px; background: #efaa70; }
.p-orange .p-bigcard li::before { background: #fff; }
.p-soon { border-style: dashed; }

/* ===== 响应式 ===== */
@media (max-width: 1080px) {
  .p-cards3, .p-cards4 { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 900px) {
  .p-chat { display: none; }           /* 手机端 hero 只留文案,示意卡收起 */
  .edition-switch { order: 3; }
}
@media (max-width: 640px) {
  .p-cards2, .p-cards3, .p-cards4 { grid-template-columns: 1fr; }
  .p-section { padding: 72px 6vw; }
}
</style>
