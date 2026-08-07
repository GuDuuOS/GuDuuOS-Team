<script setup lang="ts">
import { computed } from 'vue'

import { instanceBrand, instanceWebsite } from '@/config/instance'

const year = new Date().getFullYear()
const ownerName = computed(() => instanceBrand.companyName || instanceBrand.productName)
const footerLine = computed(() => instanceWebsite.footerText || `© ${year} ${ownerName.value}`)
const emailHref = computed(() => instanceWebsite.contactEmail
  ? `mailto:${instanceWebsite.contactEmail}` : '')
const phoneHref = computed(() => instanceWebsite.contactPhone
  ? `tel:${instanceWebsite.contactPhone.replace(/[^+\d]/g, '')}` : '')
</script>

<template>
  <main class="site-shell">
    <header class="site-nav">
      <router-link class="site-brand" to="/" aria-label="官网首页">
        <img v-if="instanceBrand.logoUrl" :src="instanceBrand.logoUrl" alt="" />
        <span v-else class="brand-mark">{{ instanceBrand.productName.slice(0, 1) }}</span>
        <strong>{{ instanceBrand.productName }}</strong>
      </router-link>
      <nav>
        <a href="#capabilities">产品能力</a>
        <a href="#contact">联系我们</a>
        <router-link class="nav-login" to="/login">登录</router-link>
      </nav>
    </header>

    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">智能协作 · 团队沟通 · 私有部署</span>
        <h1>{{ instanceWebsite.headline }}</h1>
        <p>{{ instanceWebsite.description }}</p>
        <div class="hero-actions">
          <router-link class="primary" to="/login">进入 {{ instanceBrand.productName }}</router-link>
          <a class="secondary" href="#capabilities">了解产品能力</a>
        </div>
        <small v-if="instanceBrand.companyName">由 {{ instanceBrand.companyName }} 提供</small>
      </div>
      <div class="product-preview" aria-label="产品界面示意">
        <div class="preview-top"><i /><i /><i /><span>{{ instanceBrand.productName }}</span></div>
        <div class="preview-body">
          <aside><b /><b /><b /><b /></aside>
          <section>
            <div class="preview-title">团队工作台</div>
            <div class="preview-cards"><i /><i /><i /></div>
            <div class="preview-lines"><b /><b /><b /><b /></div>
          </section>
        </div>
      </div>
    </section>

    <section id="capabilities" class="capabilities">
      <div class="section-head"><span>PRODUCT</span><h2>一个入口，连接团队的日常工作</h2></div>
      <div class="feature-grid">
        <article><i>01</i><h3>统一沟通</h3><p>频道、群组与私信集中管理，让信息始终留在团队上下文中。</p></article>
        <article><i>02</i><h3>智能协作</h3><p>主 AI、知识与任务协同工作，帮助团队把讨论更快变成行动。</p></article>
        <article><i>03</i><h3>企业自主</h3><p>独立部署、品牌定制与可选 API 接入，让企业掌握自己的配置与数据。</p></article>
      </div>
    </section>

    <section class="cta">
      <div><span>READY TO START</span><h2>从今天开始使用 {{ instanceBrand.productName }}</h2></div>
      <router-link to="/login">登录工作台</router-link>
    </section>

    <footer id="contact" class="site-footer">
      <div class="footer-brand">
        <div>
          <img v-if="instanceBrand.logoUrl" :src="instanceBrand.logoUrl" alt="" />
          <span v-else class="brand-mark">{{ instanceBrand.productName.slice(0, 1) }}</span>
          <strong>{{ instanceBrand.productName }}</strong>
        </div>
        <p v-if="instanceBrand.companyName">{{ instanceBrand.companyName }}</p>
      </div>
      <div class="contacts">
        <h3>联系我们</h3>
        <a v-if="instanceWebsite.contactEmail" :href="emailHref">{{ instanceWebsite.contactEmail }}</a>
        <a v-if="instanceWebsite.contactPhone" :href="phoneHref">{{ instanceWebsite.contactPhone }}</a>
        <span v-if="instanceWebsite.contactAddress">{{ instanceWebsite.contactAddress }}</span>
        <span v-if="!instanceWebsite.contactEmail && !instanceWebsite.contactPhone && !instanceWebsite.contactAddress">联系方式暂未填写</span>
      </div>
      <div class="footer-links">
        <h3>服务</h3>
        <a v-if="instanceWebsite.supportUrl" :href="instanceWebsite.supportUrl">帮助中心</a>
        <a v-if="instanceWebsite.privacyUrl" :href="instanceWebsite.privacyUrl">隐私政策</a>
        <router-link to="/login">登录</router-link>
      </div>
      <p class="copyright">{{ footerLine }}</p>
    </footer>
  </main>
</template>

<style scoped>
.site-shell{height:100vh;overflow:auto;background:#fbf7f0;color:#241b14;font-family:var(--font-body);scroll-behavior:smooth}.site-nav{height:76px;display:flex;align-items:center;justify-content:space-between;padding:0 max(5vw,28px);position:sticky;top:0;z-index:5;background:#fbf7f0e8;backdrop-filter:blur(18px);border-bottom:1px solid #4a2b1515}.site-brand,.site-brand+nav{display:flex;align-items:center}.site-brand{gap:11px}.site-brand img,.footer-brand img{width:38px;height:38px;object-fit:contain;border-radius:10px}.brand-mark{width:38px;height:38px;display:grid;place-items:center;border-radius:10px;background:#ef7d25;color:white;font-weight:800}.site-brand strong{font-family:var(--font-heading);font-size:18px}.site-nav nav{gap:28px;color:#6e5d50;font-size:14px}.nav-login{padding:9px 18px;border:1px solid #d9b99d;border-radius:999px;color:#8e4210}.hero{min-height:680px;padding:88px max(5vw,28px);display:grid;grid-template-columns:minmax(320px, .92fr) minmax(440px, 1.08fr);align-items:center;gap:7vw;background:radial-gradient(circle at 85% 15%,#ffd9b86b,transparent 34%),linear-gradient(145deg,#fffaf3,#f6ede2)}.hero-copy{max-width:650px}.eyebrow,.section-head span,.cta span{font-size:12px;letter-spacing:.19em;color:#d5681c;font-weight:800}.hero h1{font-family:var(--font-heading);font-size:clamp(46px,5vw,76px);line-height:1.08;letter-spacing:-.045em;margin:22px 0}.hero-copy>p{font-size:18px;line-height:1.8;color:#6f5b4d;max-width:600px}.hero-actions{display:flex;gap:12px;margin:32px 0 18px}.hero-actions a,.cta>a{padding:13px 22px;border-radius:10px;font-weight:750}.primary,.cta>a{background:#e96f1d;color:#fff;box-shadow:0 12px 28px #b84d152e}.secondary{border:1px solid #d8c2b0;background:#fff9}.hero-copy small{color:#9b8170}.product-preview{border:1px solid #ead5c2;background:#fff;box-shadow:0 35px 90px #68401b24;border-radius:20px;overflow:hidden;transform:rotate(1deg)}.preview-top{height:52px;display:flex;align-items:center;gap:7px;padding:0 18px;background:#2d211a;color:#ddcfc5}.preview-top i{width:9px;height:9px;border-radius:50%;background:#ef7d25}.preview-top i:nth-child(2){opacity:.6}.preview-top i:nth-child(3){opacity:.3}.preview-top span{margin-left:8px;font-size:12px}.preview-body{height:390px;display:grid;grid-template-columns:92px 1fr}.preview-body aside{background:#f3e9de;padding:32px 18px;display:grid;align-content:start;gap:22px}.preview-body aside b{height:9px;border-radius:8px;background:#d5bdab}.preview-body section{padding:38px}.preview-title{font:700 24px var(--font-heading)}.preview-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:27px 0}.preview-cards i{height:86px;border-radius:12px;background:linear-gradient(145deg,#fff3e7,#f2e3d5);border:1px solid #efdfd0}.preview-lines{display:grid;gap:17px}.preview-lines b{height:12px;border-radius:10px;background:#eee5dd}.preview-lines b:nth-child(2){width:72%}.preview-lines b:nth-child(3){width:88%}.preview-lines b:nth-child(4){width:58%}.capabilities{padding:110px max(5vw,28px);background:#fff}.section-head h2{font:700 clamp(32px,4vw,50px)/1.2 var(--font-heading);margin:14px 0 48px;max-width:680px}.feature-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}.feature-grid article{padding:30px;border:1px solid #eaded3;border-radius:16px;background:#fffdf9}.feature-grid i{font-style:normal;color:#e36c1d;font-weight:800}.feature-grid h3{font:700 22px var(--font-heading);margin:26px 0 12px}.feature-grid p{color:#756457;line-height:1.75}.cta{margin:0 max(5vw,28px);padding:55px 60px;border-radius:22px;background:#2b1e17;color:#fff;display:flex;align-items:center;justify-content:space-between;gap:30px}.cta h2{font:700 clamp(28px,3vw,42px)/1.25 var(--font-heading);margin-top:12px}.site-footer{margin-top:90px;padding:62px max(5vw,28px) 28px;display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:50px;border-top:1px solid #dfd0c2}.footer-brand>div{display:flex;align-items:center;gap:11px}.footer-brand p,.contacts span,.contacts a,.footer-links a{display:block;color:#79695d;margin-top:10px;line-height:1.5}.contacts h3,.footer-links h3{font-size:14px;margin-bottom:14px}.copyright{grid-column:1/-1;border-top:1px solid #e4d7cb;padding-top:22px;margin-top:20px;color:#9a887a;font-size:12px}@media(max-width:900px){.hero{grid-template-columns:1fr;padding-top:62px}.product-preview{transform:none}.feature-grid{grid-template-columns:1fr}.cta{padding:40px;align-items:flex-start;flex-direction:column}.site-footer{grid-template-columns:1fr 1fr}.footer-brand{grid-column:1/-1}}@media(max-width:640px){.site-nav{height:66px}.site-nav nav>a:not(.nav-login){display:none}.site-nav nav{gap:8px}.hero{padding:55px 20px;grid-template-columns:1fr}.hero h1{font-size:43px}.hero-copy>p{font-size:16px}.hero-actions{flex-direction:column;align-items:stretch;text-align:center}.product-preview{display:none}.capabilities{padding:78px 20px}.cta{margin:0 20px;padding:32px 24px}.site-footer{padding:50px 20px 24px;grid-template-columns:1fr;gap:30px}.footer-brand{grid-column:auto}.copyright{grid-column:auto}.site-brand strong{max-width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
</style>
