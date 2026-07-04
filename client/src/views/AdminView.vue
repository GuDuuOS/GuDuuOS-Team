<template>
  <div class="admin-view channel-view">
    <!-- 关闭管理后台，回到工作台 -->
    <button class="adm-close" title="关闭" @click="emit('close')">✕</button>
    <!-- 左侧管理菜单（用户管理已就绪，其余占位，后续逐块填） -->
    <aside class="adm-nav">
      <div class="adm-brand">
        <span class="adm-logo">⚙</span>
        <div>
          <div class="adm-title">管理后台</div>
          <div class="adm-sub">CosMac Star 运营控制台</div>
        </div>
      </div>
      <nav class="adm-menu">
        <button class="adm-mi" :class="{ active: tab === 'users' }" @click="tab = 'users'">
          <span class="adm-mi-ic">👤</span> 用户管理
        </button>
        <button class="adm-mi" :class="{ active: tab === 'rooms' }" @click="switchToRooms">
          <span class="adm-mi-ic">＃</span> 频道管理
        </button>
        <button class="adm-mi" :class="{ active: tab === 'ai' }" @click="switchToAi">
          <span class="adm-mi-ic">🤖</span> AI 配置
        </button>
        <button class="adm-mi" :class="{ active: tab === 'skills' }" @click="switchToSkills">
          <span class="adm-mi-ic">🛠</span> 技能库
        </button>
        <button class="adm-mi" :class="{ active: tab === 'agents' }" @click="switchToAgents">
          <span class="adm-mi-ic">🧑‍🚀</span> 智能体
        </button>
        <button class="adm-mi" :class="{ active: tab === 'people' }" @click="switchToPeople">
          <span class="adm-mi-ic">🧑‍💼</span> 人员能力
        </button>
        <button class="adm-mi" :class="{ active: tab === 'templates' }" @click="switchToTemplates">
          <span class="adm-mi-ic">🧰</span> 入驻模板
        </button>
        <button class="adm-mi" :class="{ active: tab === 'rules' }" @click="switchToRules">
          <span class="adm-mi-ic">⚖️</span> 规则
        </button>
        <button class="adm-mi" :class="{ active: tab === 'workflows' }" @click="switchToWorkflows">
          <span class="adm-mi-ic">🔗</span> 工作流
        </button>
        <button class="adm-mi" :class="{ active: tab === 'gating' }" @click="switchToGating">
          <span class="adm-mi-ic">🔐</span> 会员权限
        </button>
        <button class="adm-mi" :class="{ active: tab === 'quotas' }" @click="switchToQuotas">
          <span class="adm-mi-ic">📈</span> 用量配额
        </button>
        <button class="adm-mi" :class="{ active: tab === 'plans' }" @click="switchToPlans">
          <span class="adm-mi-ic">💳</span> 会员套餐
        </button>
        <button class="adm-mi" :class="{ active: tab === 'docs' }" @click="switchToDocs">
          <span class="adm-mi-ic">📰</span> 图文教程
        </button>
        <button class="adm-mi" :class="{ active: tab === 'overview' }" @click="switchToOverview">
          <span class="adm-mi-ic">📊</span> 数据概览
        </button>
      </nav>
    </aside>

    <!-- 右侧内容区 -->
    <section class="adm-main">
      <!-- 1) 权限校验中 -->
      <div v-if="state === 'checking'" class="adm-center">
        <div class="adm-spin" /> 正在校验管理员权限…
      </div>

      <!-- 2) 无权限 -->
      <div v-else-if="state === 'denied'" class="adm-center adm-denied">
        <div class="adm-denied-ic">🔒</div>
        <div class="adm-denied-t">无法进入管理后台</div>
        <div class="adm-denied-d">
          可能原因：① 当前账号不是服务器管理员（请用 <code>@admin</code> 登录）；
          ② 服务器未对管理接口 <code>/_synapse/admin</code> 开放跨域（CORS），
          导致浏览器无法调用。若你确认是管理员，多半是第 ② 种，需在 hs 的 nginx 放开 CORS。
        </div>
        <button class="adm-btn" @click="check">重新校验</button>
      </div>

      <!-- 3) 已是管理员：按 tab 显示用户管理 / 频道管理 -->
      <template v-else-if="tab === 'users'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">用户管理</h1>
            <p class="adm-hint">
              共 {{ users.length }} 个账号 ·
              管理员 {{ users.filter(u => u.admin).length }} ·
              已停用 {{ users.filter(u => u.deactivated).length }}
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="loading" @click="loadUsers">
              {{ loading ? '刷新中…' : '刷新' }}
            </button>
            <button class="adm-btn" @click="showCreate = true">＋ 新建用户</button>
          </div>
        </header>

        <div v-if="loading" class="adm-center"><div class="adm-spin" /> 加载用户列表…</div>

        <template v-else>
          <!-- 搜索 + 筛选（用户多了能快速定位）-->
          <div class="adm-filters">
            <input v-model.trim="userSearch" class="adm-search" placeholder="🔍 搜索用户名 / ID…" />
            <select v-model="filterRole" class="adm-fsel">
              <option value="all">全部角色</option>
              <option value="admin">管理员</option>
              <option value="member">成员</option>
            </select>
            <select v-model="filterTier" class="adm-fsel">
              <option value="all">全部会员</option>
              <option v-for="t in MEMBER_TIERS" :key="t.slug" :value="t.slug">{{ t.label }}</option>
            </select>
            <select v-model="filterStatus" class="adm-fsel">
              <option value="all">全部状态</option>
              <option value="ok">正常</option>
              <option value="off">已停用</option>
            </select>
            <span class="adm-filter-n">{{ filteredUsers.length }} / {{ users.length }}</span>
          </div>

          <!-- 会员等级读取失败提示：用户列表照常显示，但等级列不可信、已禁用改档，
               避免管理员在"全员误显示免费"的错数据上操作。多为尚未加入控制室，刷新即好。 -->
          <div v-if="membersLoadFailed" class="adm-warnbar">
            ⚠️ 会员等级暂时读取失败（通常是你刚被设为管理员、还没加入控制室）。用户列表正常，
            但“会员等级”列不准确、已暂时禁用修改。请点上方「刷新」重试一次即可恢复。
          </div>

        <table class="adm-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>会员等级</th>
              <th>状态</th>
              <th class="adm-ops-h">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredUsers.length"><td colspan="5" class="adm-empty-row">没有匹配的用户，换个筛选条件试试。</td></tr>
            <tr v-for="u in filteredUsers" :key="u.id" :class="{ off: u.deactivated }">
              <td>
                <div class="adm-user">
                  <span class="adm-ava">{{ avatarOf(u) }}</span>
                  <div class="adm-u-id">
                    <div class="adm-u-name">
                      {{ u.name }}
                      <span v-if="u.isBot" class="adm-tag bot">中枢AI</span>
                    </div>
                    <div class="adm-u-handle">{{ u.id }}</div>
                    <div class="adm-u-email" v-if="u.email">✉ {{ u.email }}</div>
                  </div>
                </div>
              </td>
              <td>
                <span class="adm-tag" :class="u.admin ? 'admin' : 'member'">
                  {{ u.admin ? '管理员' : '成员' }}
                </span>
              </td>
              <td>
                <!-- 等级下拉：免费/付费/创作者 + 管理员（最高档）。选管理员=授服务器管理员；
                     选会员档时若原是管理员则先撤管理员。中枢AI 不显示。 -->
                <select
                  v-if="!u.isBot"
                  class="adm-tier"
                  :class="u.admin ? 'admin' : memberTier(u.id)"
                  :value="u.admin ? 'admin' : memberTier(u.id)"
                  :disabled="tierBusy === u.id || busy === u.id || membersLoadFailed"
                  @change="onLevelChange(u, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="t in MEMBER_TIERS" :key="t.slug" :value="t.slug">
                    {{ t.label }}
                  </option>
                  <option value="admin">管理员</option>
                </select>
                <span v-else class="adm-muted">—</span>
              </td>
              <td>
                <span class="adm-tag" :class="u.deactivated ? 'off' : 'ok'">
                  {{ u.deactivated ? '已停用' : '正常' }}
                </span>
              </td>
              <td class="adm-ops">
                <button class="adm-op" :disabled="u.isBot || busy === u.id" @click="toggleAdmin(u)">
                  {{ u.admin ? '撤销管理员' : '设为管理员' }}
                </button>
                <button class="adm-op" :disabled="busy === u.id" @click="doResetPassword(u)">
                  重置密码
                </button>
                <button
                  v-if="!u.deactivated"
                  class="adm-op danger"
                  :disabled="u.isBot || busy === u.id"
                  @click="doDeactivate(u)"
                >停用</button>
                <button v-else class="adm-op" :disabled="busy === u.id" @click="doReactivate(u)">
                  恢复
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        </template>
      </template>

      <!-- 频道管理面板 -->
      <template v-else-if="tab === 'rooms'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">频道管理</h1>
            <p class="adm-hint">
              全服共 {{ rooms.length }} 个频道 ·
              公开 {{ rooms.filter(r => r.isPublic).length }} ·
              加密 {{ rooms.filter(r => r.encrypted).length }}
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="roomsLoading" @click="loadRooms">
              {{ roomsLoading ? '刷新中…' : '刷新' }}
            </button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="chSearch" class="adm-search" placeholder="🔍 搜索频道名 / ID…" />
          <select v-model="chType" class="adm-fsel"><option value="all">全部类型</option><option value="public">公开</option><option value="private">私有</option></select>
          <span class="adm-filter-n">{{ chFiltered.length }} / {{ rooms.length }}</span>
        </div>
        <div v-if="roomsLoading" class="adm-center"><div class="adm-spin" /> 加载频道列表…</div>

        <table v-else class="adm-table">
          <thead>
            <tr>
              <th>频道</th>
              <th>成员</th>
              <th>类型</th>
              <th class="adm-ops-h">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!chFiltered.length" class="adm-empty-tr"><td colspan="99" class="adm-empty-row">没有匹配的频道。</td></tr>
            <tr v-for="r in chFiltered" :key="r.id">
              <td>
                <div class="adm-user">
                  <span class="adm-ava">{{ (r.name || '#').charAt(0).toUpperCase() }}</span>
                  <div class="adm-u-id">
                    <div class="adm-u-name">{{ r.name }}</div>
                    <div class="adm-u-handle">{{ r.alias || r.id }}</div>
                  </div>
                </div>
              </td>
              <td>{{ r.members }}<span class="adm-dim"> / 本服 {{ r.localMembers }}</span></td>
              <td>
                <span class="adm-tag" :class="r.isPublic ? 'admin' : 'member'">
                  {{ r.isPublic ? '公开' : '私有' }}
                </span>
                <span v-if="r.encrypted" class="adm-tag bot" title="端到端加密">🔒 加密</span>
              </td>
              <td class="adm-ops">
                <button class="adm-op" :disabled="roomBusy === r.id" @click="viewMembers(r)">
                  查看成员
                </button>
                <button class="adm-op danger" :disabled="roomBusy === r.id" @click="doDeleteRoom(r)">
                  删除
                </button>
              </td>
            </tr>
            <tr v-if="!rooms.length"><td colspan="4" class="adm-empty">暂无频道</td></tr>
          </tbody>
        </table>
      </template>

      <!-- AI 配置面板 -->
      <template v-else-if="tab === 'ai'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">AI 配置</h1>
            <p class="adm-hint">
              改主 AI 的人设/模型/工具开关 · 保存后写入控制室，bot 约 20 秒内热生效（无需重启）
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="aiLoading || aiSaving" @click="loadAi">
              {{ aiLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="aiLoading || aiSaving" @click="saveAi">
              {{ aiSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </header>

        <div v-if="aiLoading" class="adm-center"><div class="adm-spin" /> 加载配置…</div>

        <div v-else class="adm-form">
          <!-- 模型后端：选 provider + 模型 id。API Key 不在网页配，只在服务端 -->
          <label class="adm-field">
            <span>模型后端</span>
            <select v-model="aiForm.provider">
              <option v-for="p in AI_PROVIDERS" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
            <em class="adm-note">选「默认」= 用服务器配置的后端；选某家则切到它（需服务器已配好它的 API Key）。</em>
          </label>

          <template v-if="aiForm.provider">
            <label class="adm-field">
              <span>模型 id</span>
              <input v-model.trim="aiForm.model" :placeholder="providerMeta.modelPlaceholder" />
              <em class="adm-note">⚠️ 填错会让 AI 回话报错；DeepSeek/Gemini 填方舟/Google 的模型 id 或接入点。</em>
            </label>
            <em class="adm-note">🔒 出于安全，<b>API Key 不在网页配置</b>——密钥只在服务器环境变量/Secret&nbsp;Manager 里设（平台事件无法加密，存进去会明文泄露）。切到服务器没配 key 的后端，AI 将无法回话。</em>
          </template>

          <label class="adm-field">
            <span>主 AI 人设（system prompt）</span>
            <textarea v-model="aiForm.system_prompt" rows="5"
              placeholder="留空 = 用服务器默认人设" />
          </label>

          <div class="adm-field">
            <span>工具开关（关掉的工具主 AI 将无法调用）</span>
            <div class="adm-tools">
              <label v-for="t in AI_TOOL_CATALOG" :key="t.name" class="adm-tool">
                <input type="checkbox" :checked="isToolOn(t.name)" @change="toggleTool(t.name, ($event.target as HTMLInputElement).checked)" />
                <span class="adm-tool-l">{{ t.label }}</span>
                <code>{{ t.name }}</code>
              </label>
            </div>
            <em class="adm-note">全部勾选 = 不限制（默认）。</em>
          </div>
        </div>
      </template>

      <!-- 技能库面板：编辑全局技能（写控制室 state event，主 AI 注入到所有群）-->
      <template v-else-if="tab === 'skills'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">技能库</h1>
            <p class="adm-hint">
              全局技能 · 主 AI 在所有群回话时按需运用 · 保存后约 20 秒内热生效（无需重启）
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="skLoading || skSaving" @click="loadSkills">
              {{ skLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="skLoading || skSaving" @click="startAddSkill">＋ 新建技能</button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="skSearch" class="adm-search" placeholder="🔍 搜索技能名 / slug / 说明…" />
          <select v-model="skEn.mode.value" class="adm-fsel"><option value="all">全部状态</option><option value="on">启用</option><option value="off">停用</option></select>
          <span class="adm-filter-n">{{ skFiltered.length }} / {{ skills.length }}</span>
        </div>
        <div v-if="skLoading" class="adm-center"><div class="adm-spin" /> 加载技能…</div>

        <div v-else class="adm-form">
          <!-- 编辑/新建表单 -->
          <div v-if="skEditing" class="adm-skill-edit">
            <label class="adm-field">
              <span>标识 slug（英文/数字/-，全局唯一）</span>
              <input v-model.trim="skForm.slug" :disabled="skForm._isEdit" placeholder="weekly-report" />
            </label>
            <label class="adm-field">
              <span>名称</span>
              <input v-model.trim="skForm.name" placeholder="周报" />
            </label>
            <label class="adm-field">
              <span>一句话说明</span>
              <input v-model.trim="skForm.description" placeholder="生成本周数据周报" />
            </label>
            <label class="adm-field">
              <span>技能正文（喂给主 AI 的提示/步骤）</span>
              <textarea v-model="skForm.instructions" rows="5" placeholder="按…步骤生成…" />
            </label>
            <label class="adm-field">
              <span>可用范围（谁能使用此技能；平台管理员始终可用，服务端强制）</span>
              <select v-model="skAccessKind" class="adm-fsel">
                <option value="">所有人</option>
                <option value="paid">付费会员及以上</option>
                <option value="creator">创作者及以上</option>
                <option value="admin">仅平台管理员</option>
                <option value="tpl">指定入驻模板</option>
              </select>
            </label>
            <div v-if="skAccessKind === 'tpl'" class="adm-field">
              <span>可用的入驻模板（选这些模板注册的用户可用）</span>
              <label v-for="t in templates" :key="t.key" class="adm-tool">
                <input type="checkbox" :checked="skAccessTpls.includes(t.key)" @change="toggleAccessTpl(skAccessTpls, t.key)" />
                <span class="adm-tool-l">{{ t.icon }} {{ t.label || t.key }}</span>
              </label>
              <p v-if="!templates.length" class="adm-hint">还没有入驻模板——先到「入驻模板」页创建，再回来指定。</p>
            </div>
            <label class="adm-field">
              <span>生效方式（决定这个技能怎么被主 AI 用到）</span>
              <select v-model="skForm.inject" class="adm-fsel">
                <option value="agent">随绑定的 AI 同事激活（推荐 · 平时不占用上下文）</option>
                <option value="">全局注入（每轮对话都带上 · 占 6000 字预算，慎用）</option>
              </select>
              <p class="adm-hint">「全局注入」会让每次对话都带上此技能，适合极通用的少数几个；方法论类建议「随 AI 同事激活」，绑到智能体后 @ 它才生效。</p>
            </label>
            <label class="adm-tool">
              <input type="checkbox" v-model="skForm.enabled" />
              <span class="adm-tool-l">启用</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="skSaving" @click="skEditing = false">取消</button>
              <button class="adm-btn" :disabled="skSaving || !skForm.slug" @click="saveSkill">
                {{ skSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <!-- 预置技能库（平台内置，随对应 AI 同事激活；可覆盖为自定义）-->
          <div v-if="presetSkills.length" class="adm-preset-block">
            <div class="adm-preset-h">
              <span>🧩 预置技能库</span>
              <span class="adm-preset-sub">平台内置 · 已绑给对应 AI 同事，@ 或指派它时自动激活，不占每轮上下文</span>
            </div>
            <table class="adm-table">
              <thead>
                <tr><th>标识</th><th>名称</th><th>说明</th><th>随谁激活</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="s in presetSkills" :key="'p-' + s.slug">
                  <td class="adm-nowrap"><code>{{ s.slug }}</code></td>
                  <td class="adm-nowrap">
                    {{ s.name || '—' }}
                    <span v-if="overriddenSlugs.has(s.slug)" class="adm-badge" title="已在下方自定义覆盖">已自定义</span>
                  </td>
                  <td class="adm-skill-desc">{{ s.description || '—' }}</td>
                  <td class="adm-nowrap">{{ (s.agents && s.agents.length) ? s.agents.join('、') : '—' }}</td>
                  <td class="adm-row-actions">
                    <button class="adm-btn ghost sm" :disabled="skSaving || overriddenSlugs.has(s.slug)" @click="overridePreset(s)">
                      {{ overriddenSlugs.has(s.slug) ? '已覆盖' : '覆盖为自定义' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 自定义技能列表（控制室 state event，可编辑/删除）-->
          <div class="adm-preset-h" style="margin-top:16px">
            <span>✏️ 自定义技能</span>
            <span class="adm-preset-sub">你在后台建的技能（覆盖预置或全新）</span>
          </div>
          <p v-if="!skills.length" class="adm-hint">还没有自定义技能。点右上「新建技能」加一个，或从上方预置技能「覆盖为自定义」。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>标识</th><th>名称</th><th>说明</th><th>可用范围</th><th>生效</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in skFiltered" :key="s.slug">
                <td class="adm-nowrap"><code>{{ s.slug }}</code></td>
                <td class="adm-nowrap">{{ s.name || '—' }}</td>
                <td class="adm-skill-desc">{{ s.description || '—' }}</td>
                <td class="adm-nowrap">{{ accessLabel(s.access) }}</td>
                <td class="adm-nowrap">{{ s.inject === 'agent' ? '随AI同事' : '全局' }}</td>
                <td>
                  <span class="adm-badge" :class="{ on: s.enabled }">{{ s.enabled ? '启用' : '停用' }}</span>
                </td>
                <td class="adm-row-actions">
                  <button class="adm-btn ghost sm" :disabled="skSaving" @click="startEditSkill(s)">编辑</button>
                  <button class="adm-btn ghost sm" :disabled="skSaving" @click="toggleSkill(s)">{{ s.enabled ? '停用' : '启用' }}</button>
                  <button class="adm-btn ghost sm danger" :disabled="skSaving" @click="removeSkill(s)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 智能体面板：编辑全局 Agent（人设+模型+绑定技能，写控制室 state event）-->
      <template v-else-if="tab === 'agents'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">智能体</h1>
            <p class="adm-hint">
              定义可复用的 AI 角色（人设 + 模型 + 绑定技能）· 后续可把某群绑定到一个智能体
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="agLoading || agSaving" @click="loadAgents">
              {{ agLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="agLoading || agSaving" @click="startAddAgent">＋ 新建智能体</button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="agSearch" class="adm-search" placeholder="🔍 搜索智能体名 / slug / 说明…" />
          <select v-model="agEn.mode.value" class="adm-fsel"><option value="all">全部状态</option><option value="on">启用</option><option value="off">停用</option></select>
          <span class="adm-filter-n">{{ agFiltered.length }} / {{ agents.length }}</span>
        </div>
        <div v-if="agLoading" class="adm-center"><div class="adm-spin" /> 加载智能体…</div>

        <div v-else class="adm-form">
          <!-- 编辑/新建表单 -->
          <div v-if="agEditing" class="adm-skill-edit">
            <label class="adm-field">
              <span>标识 slug（英文/数字/-，全局唯一）</span>
              <input v-model.trim="agForm.slug" :disabled="agForm._isEdit" placeholder="planner" />
            </label>
            <label class="adm-field">
              <span>名称</span>
              <input v-model.trim="agForm.name" placeholder="策划助手" />
            </label>
            <label class="adm-field">
              <span>一句话说明</span>
              <input v-model.trim="agForm.description" placeholder="负责选题与排期" />
            </label>
            <label class="adm-field">
              <span>人设（system prompt）</span>
              <textarea v-model="agForm.system_prompt" rows="4" placeholder="你是…，说话风格…" />
            </label>
            <label class="adm-field">
              <span>模型覆盖（留空 = 跟随全局 AI 配置）</span>
              <input v-model.trim="agForm.model" placeholder="如 claude-opus-4-8（可留空）" />
            </label>
            <div class="adm-field">
              <span>绑定技能（勾选全局技能库里的技能）</span>
              <div v-if="!skills.length" class="adm-note">技能库为空，可先去「技能库」建技能。</div>
              <div v-else class="adm-tools">
                <label v-for="s in skills" :key="s.slug" class="adm-tool">
                  <input type="checkbox" :checked="agForm.skill_slugs.includes(s.slug)"
                    @change="toggleAgentSkill(s.slug, ($event.target as HTMLInputElement).checked)" />
                  <span class="adm-tool-l">{{ s.name || s.slug }}</span>
                  <code>{{ s.slug }}</code>
                </label>
              </div>
            </div>
            <label class="adm-field">
              <span>可用范围（谁能使用此智能体；平台管理员始终可用，服务端强制）</span>
              <select v-model="agAccessKind" class="adm-fsel">
                <option value="">所有人</option>
                <option value="paid">付费会员及以上</option>
                <option value="creator">创作者及以上</option>
                <option value="admin">仅平台管理员</option>
                <option value="tpl">指定入驻模板</option>
              </select>
            </label>
            <div v-if="agAccessKind === 'tpl'" class="adm-field">
              <span>可用的入驻模板（选这些模板注册的用户可用）</span>
              <label v-for="t in templates" :key="t.key" class="adm-tool">
                <input type="checkbox" :checked="agAccessTpls.includes(t.key)" @change="toggleAccessTpl(agAccessTpls, t.key)" />
                <span class="adm-tool-l">{{ t.icon }} {{ t.label || t.key }}</span>
              </label>
              <p v-if="!templates.length" class="adm-hint">还没有入驻模板——先到「入驻模板」页创建，再回来指定。</p>
            </div>
            <label class="adm-tool">
              <input type="checkbox" v-model="agForm.enabled" />
              <span class="adm-tool-l">启用</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="agSaving" @click="agEditing = false">取消</button>
              <button class="adm-btn" :disabled="agSaving || !agForm.slug" @click="saveAgent">
                {{ agSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <!-- 智能体列表 -->
          <p v-if="!agents.length" class="adm-hint">还没有智能体。点右上「新建智能体」加一个。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>标识</th><th>名称</th><th>模型</th><th>技能</th><th>可用范围</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in agFiltered" :key="a.slug">
                <td><code>{{ a.slug }}</code></td>
                <td>{{ a.name || '—' }}</td>
                <td>{{ a.model || '默认' }}</td>
                <td class="adm-skill-desc">{{ a.skill_slugs.length ? a.skill_slugs.join('、') : '—' }}</td>
                <td class="adm-nowrap">{{ accessLabel(a.access) }}</td>
                <td><span class="adm-badge" :class="{ on: a.enabled }">{{ a.enabled ? '启用' : '停用' }}</span></td>
                <td class="adm-row-actions">
                  <button class="adm-btn ghost sm" :disabled="agSaving" @click="startEditAgent(a)">编辑</button>
                  <button class="adm-btn ghost sm" :disabled="agSaving" @click="toggleAgent(a)">{{ a.enabled ? '停用' : '启用' }}</button>
                  <button class="adm-btn ghost sm danger" :disabled="agSaving" @click="removeAgent(a)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 人员能力面板（模块3.5）：直接同步「用户管理」的真实账号，给每个人补能力备注（无需重建人）-->
      <template v-else-if="tab === 'people'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">人员能力</h1>
            <p class="adm-hint">
              给「用户管理」里的真实账号补上"擅长什么" · 主 AI 拆任务时据此把活派给最合适的人（无需重新建人）
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="plLoading || plSaving" @click="loadPeople">
              {{ plLoading ? '加载中…' : '重新加载' }}
            </button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="peopleSearch" class="adm-search" placeholder="🔍 搜索用户名 / ID / 角色 / 擅长…" />
          <select v-model="peopleCap" class="adm-fsel"><option value="all">全部</option><option value="set">已设能力</option><option value="unset">未设能力</option></select>
          <span class="adm-filter-n">{{ peopleFiltered.length }} / {{ peopleRows.length }}</span>
        </div>
        <div v-if="plLoading" class="adm-center"><div class="adm-spin" /> 加载用户与能力…</div>

        <div v-else class="adm-form">
          <!-- 编辑某账号的能力（user_id 固定来自真实账号、不可改） -->
          <div v-if="plEditing" class="adm-skill-edit">
            <label class="adm-field">
              <span>用户（来自用户管理，不可改）</span>
              <input :value="plForm.user_id + (plForm.name ? '（' + plForm.name + '）' : '')" disabled />
            </label>
            <label class="adm-field">
              <span>角色 / 岗位</span>
              <input v-model.trim="plForm.role" placeholder="文案 / 剪辑 / 客户对接" />
            </label>
            <label class="adm-field">
              <span>擅长（能力备注，主 AI 据此匹配）</span>
              <textarea v-model="plForm.expertise" rows="3" placeholder="如：小红书种草文案、爆款标题、竞品分析…" />
            </label>
            <label class="adm-field">
              <span>补充备注（可空）</span>
              <input v-model.trim="plForm.note" placeholder="如：负责美妆线客户、时区 GMT+8" />
            </label>
            <label class="adm-tool">
              <input type="checkbox" v-model="plForm.enabled" />
              <span class="adm-tool-l">启用（参与 AI 派单）</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="plSaving" @click="plEditing = false">取消</button>
              <button class="adm-btn" :disabled="plSaving" @click="savePerson">
                {{ plSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <p v-if="!peopleRows.length" class="adm-hint">还没有用户。先去「用户管理」建账号，这里会自动同步。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>用户</th><th>角色</th><th>擅长</th><th>能力</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in peopleFiltered" :key="r.id" :class="{ off: r.deactivated }">
                <td>
                  <code>{{ r.id }}</code><template v-if="r.name"> · {{ r.name }}</template>
                  <span v-if="r.deactivated" class="adm-tag off">已停用</span>
                </td>
                <td>{{ r.role || '—' }}</td>
                <td class="adm-skill-desc">{{ r.expertise || '—' }}</td>
                <td>
                  <span class="adm-badge" :class="{ on: r.hasProfile && r.enabled }">
                    {{ r.hasProfile ? (r.enabled ? '已设' : '停用') : '未设' }}
                  </span>
                </td>
                <td class="adm-row-actions">
                  <!-- 停用账号灰显且不可设置能力（账号都停了，没必要再给它配派单能力）-->
                  <button class="adm-btn ghost sm" :disabled="plSaving || r.deactivated" @click="startEditPersonForUser(r)">
                    {{ r.hasProfile ? '编辑能力' : '设置能力' }}
                  </button>
                  <button v-if="r.hasProfile" class="adm-btn ghost sm danger" :disabled="plSaving" @click="removePersonById(r.id)">清除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 入驻模板面板:管理员定义注册引导可选的「方案」(模型/人设/RULE/技能/知识库/频道/工作流/会员等级) -->
      <template v-else-if="tab === 'templates'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">入驻模板</h1>
            <p class="adm-hint">
              定义注册引导里可选的「方案」· 每个打包 模型/人设/RULE/技能/知识库/初始频道/默认工作流/所需会员等级 · 前台注册时用户选一个再微调（P2 接入）
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="tpLoading || tpSaving" @click="loadTemplates">
              {{ tpLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="tpLoading || tpSaving" @click="startAddTemplate">＋ 新建模板</button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="tpSearch" class="adm-search" placeholder="🔍 搜索模板名 / key / 描述…" />
          <select v-model="tpEn.mode.value" class="adm-fsel"><option value="all">全部状态</option><option value="on">启用</option><option value="off">停用</option></select>
          <span class="adm-filter-n">{{ tpFiltered.length }} / {{ templates.length }}</span>
        </div>
        <div v-if="tpLoading" class="adm-center"><div class="adm-spin" /> 加载模板…</div>

        <div v-else class="adm-form">
          <!-- 编辑/新建表单 -->
          <div v-if="tpEditing" class="adm-skill-edit">
            <div class="adm-grid2">
              <label class="adm-field">
                <span>标识 key（英文/数字/-，唯一，建后不改）</span>
                <input v-model.trim="tpForm.key" :disabled="tpForm._isEdit" placeholder="film" />
              </label>
              <label class="adm-field">
                <span>所需会员等级（低于此等级的用户选不了）</span>
                <select v-model="tpForm.tier">
                  <option v-for="t in MEMBER_TIERS" :key="t.slug" :value="t.slug">{{ t.label }}</option>
                </select>
              </label>
              <label class="adm-field">
                <span>展示名</span>
                <input v-model.trim="tpForm.label" placeholder="影视 / 内容工作室" />
              </label>
              <label class="adm-field">
                <span>图标 emoji</span>
                <input v-model.trim="tpForm.icon" placeholder="🎬" />
              </label>
            </div>
            <label class="adm-field">
              <span>一句话说明</span>
              <input v-model.trim="tpForm.desc" placeholder="剧集/短视频制作、虚拟明星、粉丝运营" />
            </label>
            <label class="adm-field">
              <span>模型（留空 = 跟随全局 AI 配置）</span>
              <input v-model.trim="tpForm.model" placeholder="如 claude-opus-4-8（可留空）" />
            </label>
            <label class="adm-field">
              <span>AI 人设（system prompt）</span>
              <textarea v-model="tpForm.persona" rows="3" placeholder="你是这家影视工作室的制作中枢助手…" />
            </label>
            <label class="adm-field">
              <span>基础 RULE（平台硬约束，多行）</span>
              <textarea v-model="tpForm.rules" rows="3" placeholder="如：不得泄露内部报价；输出需符合平台规范…" />
            </label>
            <label class="adm-field">
              <span>初始频道（一行一个）</span>
              <textarea v-model="tpChannelsText" rows="3" placeholder="制作中心&#10;分镜与脚本&#10;粉丝社区" />
            </label>
            <div class="adm-field">
              <span>绑定技能（勾选技能库里的技能）</span>
              <div v-if="!skills.length" class="adm-note">技能库为空，可先去「技能库」建技能。</div>
              <div v-else class="adm-tools">
                <label v-for="s in skills" :key="s.slug" class="adm-tool">
                  <input type="checkbox" :checked="tpForm.skillSlugs.includes(s.slug)"
                    @change="toggleTplSkill(s.slug, ($event.target as HTMLInputElement).checked)" />
                  <span class="adm-tool-l">{{ s.name || s.slug }}</span><code>{{ s.slug }}</code>
                </label>
              </div>
            </div>
            <div class="adm-field">
              <span>默认工作流（勾选工作流连接器）</span>
              <div v-if="!workflows.length" class="adm-note">还没有工作流连接器，可先去「工作流」建。</div>
              <div v-else class="adm-tools">
                <label v-for="w in workflows" :key="w.slug" class="adm-tool">
                  <input type="checkbox" :checked="tpForm.workflowSlugs.includes(w.slug)"
                    @change="toggleTplWorkflow(w.slug, ($event.target as HTMLInputElement).checked)" />
                  <span class="adm-tool-l">{{ w.name || w.slug }}</span><code>{{ w.slug }}</code>
                </label>
              </div>
            </div>
            <div class="adm-field">
              <span>预置知识库文档（每个模板的 AI 知识不同）</span>
              <div v-for="(d, i) in tpForm.kbDocs" :key="rowKey(d)" class="adm-kbdoc">
                <input v-model.trim="d.title" class="adm-kbdoc-t" placeholder="文档标题（如 平台规则与避雷）" />
                <textarea v-model="d.content" rows="2" placeholder="文档内容…" />
                <button class="adm-btn ghost sm danger" @click="removeTplDoc(i)">删除</button>
              </div>
              <button class="adm-btn ghost sm" @click="addTplDoc">＋ 加一篇文档</button>
            </div>
            <label class="adm-tool">
              <input type="checkbox" v-model="tpForm.enabled" />
              <span class="adm-tool-l">上架（注册引导里可被选）</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="tpSaving" @click="tpEditing = false">取消</button>
              <button class="adm-btn" :disabled="tpSaving || !tpForm.key || !tpForm.label" @click="saveTemplate">
                {{ tpSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <!-- 模板列表 -->
          <p v-if="!templates.length" class="adm-hint">还没有入驻模板。点右上「新建模板」加一个。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>标识</th><th>展示名</th><th>会员等级</th><th>模型</th><th>频道/技能</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in tpFiltered" :key="t.key">
                <td><code>{{ t.key }}</code></td>
                <td>{{ t.icon }} {{ t.label }}</td>
                <td>{{ memberTierLabel(t.tier) }}</td>
                <td>{{ t.model || '默认' }}</td>
                <td class="adm-skill-desc">{{ t.channels.length }} 频道 · {{ t.skillSlugs.length }} 技能 · {{ t.kbDocs.length }} 文档</td>
                <td><span class="adm-badge" :class="{ on: t.enabled }">{{ t.enabled ? '上架' : '下架' }}</span></td>
                <td class="adm-row-actions">
                  <button class="adm-btn ghost sm" :disabled="tpSaving" @click="startEditTemplate(t)">编辑</button>
                  <button class="adm-btn ghost sm" :disabled="tpSaving" @click="toggleTemplate(t)">{{ t.enabled ? '下架' : '上架' }}</button>
                  <button class="adm-btn ghost sm danger" :disabled="tpSaving" @click="removeTemplate(t)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 规则面板:平台级硬约束(写控制室 state event,主 AI 所有群都注入、优先级最高) -->
      <template v-else-if="tab === 'rules'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">规则</h1>
            <p class="adm-hint">
              平台级硬约束 · 主 AI 在所有群都须遵守、优先级高于人设/技能 · 保存后约 20 秒热生效
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="ruLoading || ruSaving" @click="loadRules">
              {{ ruLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="ruLoading || ruSaving || !ruLoaded" @click="saveRules">
              {{ ruSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </header>

        <div v-if="ruLoading" class="adm-center"><div class="adm-spin" /> 加载规则…</div>

        <div v-else class="adm-form">
          <p class="adm-hint">每条一行规则;停用的不注入。例:「对外报价/发布等动作必须先经负责人确认」「不得编造数据,引用须标注来源」。</p>
          <div v-for="(r, i) in rules" :key="rowKey(r)" class="adm-rule-row">
            <input type="checkbox" v-model="r.enabled" title="启用" />
            <textarea v-model="r.text" rows="2" class="adm-rule-text" placeholder="写一条主 AI 必须遵守的规则…" />
            <button class="adm-btn ghost sm danger" @click="rules.splice(i, 1)">删除</button>
          </div>
          <button class="adm-btn ghost sm" @click="rules.push({ text: '', enabled: true })">＋ 加一条规则</button>
        </div>
      </template>

      <!-- 工作流面板:配置外部连接器(n8n/Make 等),写控制室 state event -->
      <template v-else-if="tab === 'workflows'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">工作流</h1>
            <p class="adm-hint">
              对接 n8n / Make 等外部平台 · 群里发「工作流 跑 &lt;slug&gt;」或直接让主 AI 触发 · 保存后约 20 秒热生效
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="wfLoading || wfSaving" @click="loadWorkflows">
              {{ wfLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="wfLoading || wfSaving" @click="startAddWorkflow">＋ 新建连接器</button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="wfSearch" class="adm-search" placeholder="🔍 搜索工作流名 / slug / 平台…" />
          <select v-model="wfEn.mode.value" class="adm-fsel"><option value="all">全部状态</option><option value="on">启用</option><option value="off">停用</option></select>
          <span class="adm-filter-n">{{ wfFiltered.length }} / {{ workflows.length }}</span>
        </div>
        <div v-if="wfLoading" class="adm-center"><div class="adm-spin" /> 加载连接器…</div>

        <div v-else class="adm-form">
          <div v-if="wfEditing" class="adm-skill-edit">
            <label class="adm-field">
              <span>标识 slug（英文/数字/-，全局唯一）</span>
              <input v-model.trim="wfForm.slug" :disabled="wfForm._isEdit" placeholder="cover-gen" />
            </label>
            <label class="adm-field">
              <span>名称</span>
              <input v-model.trim="wfForm.name" placeholder="封面生成" />
            </label>
            <label class="adm-field">
              <span>平台</span>
              <select v-model="wfForm.platform" class="cam-select">
                <option value="webhook">Webhook（n8n / Make / 自建）</option>
                <option value="dify">Dify</option>
                <option value="coze">Coze</option>
                <option value="comfyui">ComfyUI（图/视频）</option>
              </select>
            </label>
            <label class="adm-field">
              <span>{{ wfForm.platform === 'webhook' ? 'Webhook URL' : '服务地址（base url）' }}</span>
              <input v-model.trim="wfForm.url" :placeholder="wfUrlPlaceholder" />
            </label>
            <label v-if="wfForm.platform === 'webhook'" class="adm-field">
              <span>请求方法</span>
              <select v-model="wfForm.method" class="cam-select">
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </label>
            <label v-if="wfForm.platform === 'dify'" class="adm-field">
              <span>Dify 应用类型</span>
              <select v-model="wfForm.mode" class="cam-select">
                <option value="workflow">workflow（工作流应用）</option>
                <option value="chat">chat（对话应用）</option>
              </select>
            </label>
            <label v-if="wfForm.platform === 'coze'" class="adm-field">
              <span>Coze workflow_id</span>
              <input v-model.trim="wfForm.ref_id" placeholder="如 7401234567890" />
            </label>
            <label v-if="wfForm.platform === 'dify' || wfForm.platform === 'coze'" class="adm-field">
              <span>输入变量名（可选）</span>
              <input v-model.trim="wfForm.input_key" placeholder="默认 input（要与平台里定义的输入变量名一致）" />
            </label>
            <label v-if="wfForm.platform === 'comfyui'" class="adm-field">
              <span>工作流图（API 格式 JSON）</span>
              <textarea v-model="wfForm.graph" rows="6" class="adm-rule-text"
                placeholder='把 ComfyUI 导出的"API 格式"工作流 JSON 粘进来，要被用户输入替换的地方写成 {{input}}' />
              <em class="adm-note">ComfyUI 菜单「Save (API Format)」导出；把提示词节点的文本改成 <code v-pre>{{input}}</code> 占位。生成的图会自动发回触发的群。</em>
            </label>
            <label class="adm-field">
              <span>凭据名（可选）</span>
              <input v-model.trim="wfForm.cred" placeholder="如 n8n_main（可留空）" />
              <em class="adm-note">🔒 这里只填"名字"。真密钥在服务器环境变量 <code>COSMAC_WF_&lt;大写名字&gt;</code> 里配，不进网页或聊天数据。留空=URL 自带令牌/无需鉴权。</em>
            </label>
            <label class="adm-field">
              <span>输入提示（给用户看的，可选）</span>
              <input v-model.trim="wfForm.input_hint" placeholder="如 描述要生成的封面" />
            </label>
            <label v-if="wfForm.platform === 'webhook'" class="adm-tool">
              <input type="checkbox" v-model="wfForm.async" />
              <span class="adm-tool-l">异步(长任务)</span>
              <em class="adm-note">勾上=提交后不等结果,平台跑完反向回调再把结果发回群(需服务端配 COSMAC_PUBLIC_URL + nginx 放行 /cosmac/)。</em>
            </label>
            <label class="adm-tool">
              <input type="checkbox" v-model="wfForm.enabled" />
              <span class="adm-tool-l">启用</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="wfSaving" @click="wfEditing = false">取消</button>
              <button class="adm-btn" :disabled="wfSaving || !wfForm.slug || !wfForm.url" @click="saveWorkflow">
                {{ wfSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <p v-if="!workflows.length" class="adm-hint">还没有连接器。点右上「新建连接器」加一个(先在 n8n/Make 建好 webhook,把 URL 填进来)。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>标识</th><th>名称</th><th>平台</th><th>URL</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="w in wfFiltered" :key="w.slug">
                <td><code>{{ w.slug }}</code></td>
                <td>{{ w.name || '—' }}</td>
                <td>{{ w.platform }}</td>
                <td class="adm-skill-desc">{{ w.url }}</td>
                <td><span class="adm-badge" :class="{ on: w.enabled }">{{ w.enabled ? '启用' : '停用' }}</span></td>
                <td class="adm-row-actions">
                  <button class="adm-btn ghost sm" :disabled="wfSaving" @click="startEditWorkflow(w)">编辑</button>
                  <button class="adm-btn ghost sm" :disabled="wfSaving" @click="toggleWorkflow(w)">{{ w.enabled ? '停用' : '启用' }}</button>
                  <button class="adm-btn ghost sm danger" :disabled="wfSaving" @click="removeWorkflow(w)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 会员权限(功能门控)面板:逐项配「能力→最低会员等级」,写控制室 cosmac.gating,bot 服务端强制 -->
      <template v-else-if="tab === 'gating'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">会员权限</h1>
            <p class="adm-hint">
              给每项能力设一个最低会员等级 · 主 AI 在服务端强制(客户端只是配置) · 保存后约 15 秒热生效
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="gateLoading || gateSaving" @click="loadGating">
              {{ gateLoading ? '加载中…' : '重新加载' }}
            </button>
            <!-- #3：加载失败(gateLoaded=false)时禁止保存——否则会把默认值覆盖真实付费策略 -->
            <button class="adm-btn" :disabled="gateLoading || gateSaving || !gateLoaded" @click="saveGating">
              {{ gateSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </header>

        <div v-if="gateLoading" class="adm-center"><div class="adm-spin" /> 加载门控策略…</div>

        <!-- #3：读取失败时不渲染可编辑表（避免在默认值上误保存覆盖真实策略），只提示重试 -->
        <div v-else-if="!gateLoaded" class="adm-center adm-denied">
          <div class="adm-denied-ic">⚠️</div>
          <div class="adm-denied-t">门控策略加载失败</div>
          <div class="adm-denied-d">为避免把默认值误存、覆盖真实付费策略，已暂不显示配置。请点「重新加载」重试。</div>
        </div>

        <div v-else class="adm-form">
          <p class="adm-hint">
            「免费」= 不限制,人人可用;选更高等级则低于该等级的用户被挡并提示升级。
            「仅平台管理员」用于高危/付费共享凭据的能力(如跑工作流)。
            管理员永远不受会员等级门控限制。以后新增功能会出现在这张表里。
          </p>
          <table class="adm-table">
            <thead>
              <tr><th>能力</th><th>最低会员等级</th></tr>
            </thead>
            <tbody>
              <template v-for="grp in gateGroups" :key="grp.group">
                <tr class="adm-grp-row"><td colspan="2">{{ grp.group }}</td></tr>
                <tr v-for="g in grp.items" :key="g.key">
                  <td>{{ g.label }}</td>
                  <td>
                    <select class="adm-tier" :class="gates[g.key]" v-model="gates[g.key]">
                      <option v-for="lv in GATE_LEVELS" :key="lv.slug" :value="lv.slug">
                        {{ lv.label }}
                      </option>
                    </select>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 用量配额面板(变现第二步):给每个计量项按会员等级配上限,写控制室 cosmac.quotas,bot 服务端计数+强制 -->
      <template v-else-if="tab === 'quotas'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">用量配额</h1>
            <p class="adm-hint">给每个计量维度按会员等级设上限 · 填 -1 = 不限 · bot 服务端计数 + 强制 · 约 20 秒热生效</p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="quotaLoading || quotaSaving" @click="loadQuotas">
              {{ quotaLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="quotaLoading || quotaSaving || !quotaLoaded" @click="saveQuotas">
              {{ quotaSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </header>

        <div v-if="quotaLoading" class="adm-center"><div class="adm-spin" /> 加载配额…</div>
        <div v-else-if="!quotaLoaded" class="adm-center adm-denied">
          <div class="adm-denied-ic">⚠️</div>
          <div class="adm-denied-t">配额加载失败</div>
          <div class="adm-denied-d">为避免把默认值误存覆盖真实配置，已暂不显示。请点「重新加载」重试。</div>
        </div>

        <div v-else class="adm-form">
          <p class="adm-hint">免费版很快撞墙→提示升级，这是订阅的主要付费驱动。-1=不限（多给付费/创作者）。管理员永远不受配额限制。</p>
          <table class="adm-table">
            <thead>
              <tr>
                <th>计量项</th>
                <th v-for="t in MEMBER_TIERS" :key="t.slug">{{ t.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="q in QUOTA_CATALOG" :key="q.key">
                <td>{{ q.label }}<span class="adm-muted">（{{ q.unit }}）</span></td>
                <td v-for="t in MEMBER_TIERS" :key="t.slug">
                  <input type="number" class="adm-qnum" v-model.number="quotas[q.key][t.slug]" min="-1" />
                  <span v-if="quotas[q.key][t.slug] < 0" class="adm-muted">不限</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 会员套餐面板:配置可购买的会员套餐(tier/时长/各币种价),写控制室 cosmac.plans -->
      <template v-else-if="tab === 'plans'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">会员套餐</h1>
            <p class="adm-hint">
              配置用户「升级会员」时可买的套餐 · 价格按货币填(留空=该货币不售) · 保存后下单即用
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="planLoading || planSaving" @click="loadPlans">
              {{ planLoading ? '加载中…' : '重新加载' }}
            </button>
            <button class="adm-btn" :disabled="planLoading || planSaving || !planLoaded" @click="startAddPlan">＋ 新建套餐</button>
          </div>
        </header>

        <div class="adm-filters">
          <input v-model.trim="plSearch" class="adm-search" placeholder="🔍 搜索套餐名 / slug…" />
          <select v-model="plEn.mode.value" class="adm-fsel"><option value="all">全部状态</option><option value="on">启用</option><option value="off">停用</option></select>
          <span class="adm-filter-n">{{ plFiltered.length }} / {{ plans.length }}</span>
        </div>
        <div v-if="planLoading" class="adm-center"><div class="adm-spin" /> 加载套餐…</div>

        <!-- 读取失败不渲染可编辑区(避免空列表误存覆盖真实套餐) -->
        <div v-else-if="!planLoaded" class="adm-center adm-denied">
          <div class="adm-denied-ic">⚠️</div>
          <div class="adm-denied-t">套餐加载失败</div>
          <div class="adm-denied-d">为避免把空列表误存、覆盖真实套餐，已暂不显示。请点「重新加载」重试。</div>
        </div>

        <div v-else class="adm-form">
          <div v-if="planEditing" class="adm-skill-edit">
            <label class="adm-field">
              <span>标识 slug（英文/数字/-，全局唯一）</span>
              <input v-model.trim="planForm.slug" :disabled="planForm._isEdit" placeholder="paid-monthly" />
            </label>
            <label class="adm-field">
              <span>名称</span>
              <input v-model.trim="planForm.name" placeholder="付费会员 · 月卡" />
            </label>
            <label class="adm-field">
              <span>会员等级</span>
              <select v-model="planForm.tier" class="cam-select">
                <option value="paid">付费会员</option>
                <option value="creator">创作者会员</option>
              </select>
            </label>
            <label class="adm-field">
              <span>有效期（天）</span>
              <input v-model.number="planForm.period_days" type="number" min="1" placeholder="30" />
            </label>
            <div class="adm-field">
              <span>价格（按货币填，留空=不售该货币）</span>
              <div v-for="c in PLAN_CURRENCIES" :key="c.code" class="plan-price-row">
                <span class="plan-price-cur">{{ c.label }}</span>
                <input v-model.trim="planForm.priceText[c.code]" type="text" inputmode="decimal"
                  :placeholder="c.code === 'cny' ? '如 68' : '如 9.99'" />
              </div>
              <em class="adm-note">填用户看到的金额（元/美元），保存自动转成最小单位(分)存储。</em>
            </div>
            <label class="adm-tool">
              <input type="checkbox" v-model="planForm.enabled" />
              <span class="adm-tool-l">上架（可购买）</span>
            </label>
            <div class="adm-actions">
              <button class="adm-btn ghost" :disabled="planSaving" @click="planEditing = false">取消</button>
              <button class="adm-btn" :disabled="planSaving || !planForm.slug" @click="savePlan">
                {{ planSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <p v-if="!plans.length" class="adm-hint">还没有套餐。点右上「新建套餐」加一个(如「付费月卡 / paid / 30天 / $9.99」)。</p>
          <table v-else class="adm-table">
            <thead>
              <tr><th>标识</th><th>名称</th><th>等级</th><th>时长</th><th>价格</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in plFiltered" :key="p.slug">
                <td><code>{{ p.slug }}</code></td>
                <td>{{ p.name || '—' }}</td>
                <td>{{ p.tier === 'creator' ? '创作者' : '付费' }}</td>
                <td>{{ p.period_days }}天</td>
                <td class="adm-skill-desc">{{ planPriceText(p) }}</td>
                <td><span class="adm-badge" :class="{ on: p.enabled }">{{ p.enabled ? '上架' : '下架' }}</span></td>
                <td class="adm-row-actions">
                  <button class="adm-btn ghost sm" :disabled="planSaving" @click="startEditPlan(p)">编辑</button>
                  <button class="adm-btn ghost sm" :disabled="planSaving" @click="togglePlan(p)">{{ p.enabled ? '下架' : '上架' }}</button>
                  <button class="adm-btn ghost sm danger" :disabled="planSaving" @click="removePlan(p)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 图文教程：编辑全平台图文内容(前台只读·类公众号；付费会员可见) -->
      <template v-else-if="tab === 'docs'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">图文教程</h1>
            <p class="adm-hint">编辑全平台图文内容（全平台一份）；前台「图文教程」只读展示，付费会员可见。</p>
          </div>
        </header>
        <div class="adm-doc-edit">
          <DocChannelView />
        </div>
      </template>

      <!-- 数据概览面板 -->
      <template v-else-if="tab === 'overview'">
        <header class="adm-head">
          <div>
            <h1 class="adm-h1">数据概览</h1>
            <p class="adm-hint">
              平台实时概况 · 数据来自服务器管理接口
              <span v-if="ov.version"> · 服务端 {{ ov.version }}</span>
            </p>
          </div>
          <div class="adm-actions">
            <button class="adm-btn ghost" :disabled="ovLoading" @click="loadOverview">
              {{ ovLoading ? '刷新中…' : '刷新' }}
            </button>
          </div>
        </header>

        <div v-if="ovLoading" class="adm-center"><div class="adm-spin" /> 统计中…</div>

        <template v-else>
          <!-- KPI 卡片 -->
          <div class="adm-kpis">
            <div class="adm-kpi">
              <div class="adm-kpi-v">{{ ov.userTotal }}</div>
              <div class="adm-kpi-l">账号总数</div>
              <div class="adm-kpi-s">管理员 {{ ov.adminCount }} · 停用 {{ ov.deactivated }}</div>
            </div>
            <div class="adm-kpi">
              <div class="adm-kpi-v">{{ ov.roomTotal }}</div>
              <div class="adm-kpi-l">频道总数</div>
              <div class="adm-kpi-s">公开 {{ ov.publicRooms }} · 加密 {{ ov.encryptedRooms }}</div>
            </div>
            <div class="adm-kpi">
              <div class="adm-kpi-v">{{ ov.memberSum }}</div>
              <div class="adm-kpi-l">成员人次合计</div>
              <div class="adm-kpi-s">平均每频道 {{ ov.avgMembers }}</div>
            </div>
            <div class="adm-kpi">
              <div class="adm-kpi-v">{{ ov.activeRooms }}</div>
              <div class="adm-kpi-l">活跃频道</div>
              <div class="adm-kpi-s">成员 ≥ 2 的频道数</div>
            </div>
          </div>

          <!-- 最活跃频道 Top -->
          <h2 class="adm-h2">最活跃频道 Top {{ ov.topRooms.length }}</h2>
          <table class="adm-table">
            <thead>
              <tr><th>频道</th><th>成员</th><th>类型</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in ov.topRooms" :key="r.id">
                <td>
                  <div class="adm-user">
                    <span class="adm-ava">{{ (r.name || '#').charAt(0).toUpperCase() }}</span>
                    <div class="adm-u-id">
                      <div class="adm-u-name">{{ r.name }}</div>
                      <div class="adm-u-handle">{{ r.alias || r.id }}</div>
                    </div>
                  </div>
                </td>
                <td>{{ r.members }}</td>
                <td>
                  <span class="adm-tag" :class="r.isPublic ? 'admin' : 'member'">
                    {{ r.isPublic ? '公开' : '私有' }}
                  </span>
                </td>
              </tr>
              <tr v-if="!ov.topRooms.length"><td colspan="3" class="adm-empty">暂无数据</td></tr>
            </tbody>
          </table>
        </template>
      </template>
    </section>

    <!-- 新建用户弹窗 -->
    <div v-if="showCreate" class="adm-mask" @click.self="showCreate = false">
      <div class="adm-modal">
        <div class="adm-modal-h">新建用户</div>
        <label class="adm-field">
          <span>用户名</span>
          <input v-model.trim="form.username" placeholder="如 alice（自动补 :{{ domain }}）" />
        </label>
        <label class="adm-field">
          <span>显示名（可选）</span>
          <input v-model.trim="form.displayname" placeholder="如 爱丽丝" />
        </label>
        <label class="adm-field">
          <span>初始密码</span>
          <input v-model="form.password" type="password" autocomplete="new-password" placeholder="至少 8 位" />
        </label>
        <div class="adm-modal-f">
          <button class="adm-btn ghost" @click="showCreate = false">取消</button>
          <button class="adm-btn" :disabled="!canCreate || busy === 'create'" @click="doCreate">
            {{ busy === 'create' ? '创建中…' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 频道成员弹窗 -->
    <div v-if="membersOf" class="adm-mask" @click.self="membersOf = null">
      <div class="adm-modal">
        <div class="adm-modal-h">{{ membersOf.name }} · 成员</div>
        <div class="adm-mlist">
          <div v-if="membersLoading" class="adm-center"><div class="adm-spin" /> 加载中…</div>
          <template v-else>
            <div v-for="m in memberList" :key="m" class="adm-mrow">
              <span class="adm-ava sm">{{ m.replace(/^@/, '').charAt(0).toUpperCase() }}</span>
              <span class="adm-mid">{{ m }}</span>
            </div>
            <div v-if="!memberList.length" class="adm-empty">没有成员</div>
          </template>
        </div>
        <div class="adm-modal-f">
          <button class="adm-btn ghost" @click="membersOf = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { rowKey } from '@/utils/rowKey'
import {
  isServerAdmin,
  listUsers,
  createUser,
  deactivateUser,
  reactivateUser,
  resetPassword,
  setUserAdmin,
  ensureControlRoomMembership,
  serverName,
  listAdminRooms,
  getRoomMembers,
  deleteRoom,
  getServerVersion,
  getAiConfig,
  setAiConfig,
  getGlobalSkills,
  getPresetSkills,
  setGlobalSkills,
  getGlobalAgents,
  setGlobalAgents,
  getPeople,
  setPeople,
  type Person,
  getGlobalRules,
  setGlobalRules,
  getWorkflows,
  setWorkflows,
  getOnboardingTemplates,
  setOnboardingTemplates,
  type OnboardingTemplateDef,
  getPlans,
  setPlans,
  PLAN_CURRENCIES,
  type PlanDef,
  getMembers,
  setMemberTier,
  memberTierLabel,
  MEMBER_TIERS,
  type MemberMap,
  getGating,
  setGating,
  GATE_CATALOG,
  GATE_LEVELS,
  type GatingMap,
  getQuotas,
  setQuotas,
  QUOTA_CATALOG,
  type QuotaLimits,
  AI_TOOL_CATALOG,
  AI_PROVIDERS,
  type AdminUser,
  type AdminRoom,
  type GlobalSkill,
  type GlobalAgent,
  type GlobalRule,
  type WorkflowDef,
} from '@/matrix/client'
import DocChannelView from '@/components/doc/DocChannelView.vue'
import { useToast } from '@/composables/useToast'
import { useListSearch, useEnabledFilter } from '@/composables/useListSearch'

// 作为覆盖层使用：关闭时通知父组件（LiveView）收起
const emit = defineEmits<{ (e: 'close'): void }>()

const { success, warn } = useToast()

// 当前管理模块：用户/频道/AI配置/技能库/智能体/规则/工作流/数据概览
const tab = ref<'users' | 'rooms' | 'ai' | 'skills' | 'agents' | 'people' | 'templates' | 'rules' | 'workflows' | 'gating' | 'quotas' | 'plans' | 'docs' | 'overview'>('users')

/* —— 图文教程（后台编辑全平台图文；前台只读·付费可见）—— */
function switchToDocs() { tab.value = 'docs' }

// 页面状态机：checking 校验中 / denied 无权限 / ok 已是管理员
const state = ref<'checking' | 'denied' | 'ok'>('checking')
const loading = ref(false)
const users = ref<AdminUser[]>([])
// busy 存"正在操作的用户 id"或 'create'，用于禁用对应按钮、防重复点击
const busy = ref<string | null>(null)
// 会员等级 map（userId→slug，只含非免费的）+ 正在调整的用户 id（禁用对应下拉防抖）
const members = ref<MemberMap>({})
const tierBusy = ref<string | null>(null)
// 会员等级读取是否失败（读控制室 state event，需已加入控制室）。为真时：等级列不可信，
// 禁用等级下拉 + 顶部提示，**绝不**把读不到伪装成"全员免费"让管理员在错数据上误操作。
const membersLoadFailed = ref(false)

/** 取某用户的会员等级 slug（map 里没有即免费）。 */
function memberTier(userId: string): string {
  return members.value[userId] || 'free'
}

// —— 用户管理：搜索 + 筛选（用户多了能快速定位）——
const userSearch = ref('')
const filterRole = ref<'all' | 'admin' | 'member'>('all')
const filterTier = ref('all')   // 'all' 或某会员等级 slug
const filterStatus = ref<'all' | 'ok' | 'off'>('all')
const filteredUsers = computed(() => {
  const q = userSearch.value.toLowerCase()
  return users.value
    .filter((u) => {
      if (q && !(u.id.toLowerCase().includes(q) || (u.name || '').toLowerCase().includes(q))) return false
      if (filterRole.value === 'admin' && !u.admin) return false
      if (filterRole.value === 'member' && u.admin) return false
      if (filterTier.value !== 'all' && memberTier(u.id) !== filterTier.value) return false
      if (filterStatus.value === 'ok' && u.deactivated) return false
      if (filterStatus.value === 'off' && !u.deactivated) return false
      return true
    })
    .sort((a, b) => Number(a.deactivated) - Number(b.deactivated))  // 在用在前、停用在后
})

const domain = computed(() => serverName())

// 新建用户表单
const showCreate = ref(false)
const form = reactive({ username: '', displayname: '', password: '' })
const canCreate = computed(
  () => form.username.length > 0 && form.password.length >= 8,
)

/** 取头像首字（显示名首字，没有就用 id 首字母） */
function avatarOf(u: AdminUser): string {
  const s = u.name || u.id.replace(/^@/, '')
  return s.charAt(0).toUpperCase()
}

/** 进页面先校验管理员；是管理员才拉用户列表 */
async function check() {
  state.value = 'checking'
  const ok = await isServerAdmin()
  if (!ok) { state.value = 'denied'; return }
  state.value = 'ok'
  await loadUsers()
}

async function loadUsers() {
  loading.value = true
  try {
    // ① 用户列表是关键数据（走 /_synapse/admin，服务器管理员就能读）——失败=真错误。
    //    **必须与会员等级解耦**：以前用 Promise.all 一起读，getMembers 一失败就整张列表变空，
    //    这正是"第二个管理员看得到频道、看不到用户"的根因（他还没加入控制室、读不了会员事件）。
    const list = await listUsers()
    users.value = list
    // ② 会员等级单独读：它读的是控制室 state event，需要"已加入控制室"。
    membersLoadFailed.value = false
    try {
      members.value = await getMembers()
    } catch {
      // 多半是还没加入控制室 → 自愈：接受控制室邀请并重试一次
      await ensureControlRoomMembership()
      try {
        members.value = await getMembers()
      } catch {
        members.value = {}
        membersLoadFailed.value = true // 等级不可信：禁用下拉 + 顶部提示，绝不伪装成"全员免费"
      }
    }
  } catch (e: any) {
    warn('加载失败', e?.message || '无法获取用户列表')
  } finally {
    loading.value = false
  }
}

/** 下拉切换会员等级：即时写控制室 cosmac.members；失败回滚 UI。 */
async function onTierChange(u: AdminUser, tier: string) {
  const prev = memberTier(u.id)
  if (tier === prev) return
  tierBusy.value = u.id
  // 乐观更新（select 已显示新值）；失败再回滚
  if (tier === 'free') delete members.value[u.id]
  else members.value = { ...members.value, [u.id]: tier }
  try {
    await setMemberTier(u.id, tier)
    success('已更新会员等级', `${u.name} 现在是「${memberTierLabel(tier)}」`)
  } catch (e: any) {
    // 回滚
    if (prev === 'free') delete members.value[u.id]
    else members.value = { ...members.value, [u.id]: prev }
    warn('设置失败', e?.message || '无法写入会员等级')
  } finally {
    tierBusy.value = null
  }
}

// 等级下拉统一处理：免费/付费/创作者会员 + 管理员（最高档）。
async function onLevelChange(u: AdminUser, level: string) {
  const cur = u.admin ? 'admin' : memberTier(u.id)
  if (level === cur) return
  if (level === 'admin') {
    // 升为管理员（会员档保留在 cosmac.members，管理员本就不受会员门控）
    if (!confirm(`确认把 ${u.name} 设为管理员？`)) return
    busy.value = u.id
    try {
      const synced = await setUserAdmin(u.id, true)
      u.admin = true
      if (synced) {
        // synced=true：服务器管理员标志 + 控制室"期望集"都已写好，权限与你完全一致
        success('已设为管理员', `${u.name} 现已拥有与你一致的完整管理员权限。请让 TA 刷新页面（或退出重新登录）后生效。`)
      } else {
        // 服务器管理员标志已生效（不回滚），但控制室同步没成——写 AI 配置的资格可能未对齐
        warn('已设为管理员（控制室同步未完成）', `${u.name} 已是服务器管理员，但"写 AI 配置/门控"的权限可能未对齐。请重试一次「设为管理员」，并让 TA 刷新页面。`)
      }
    } catch (e: any) {
      warn('操作失败', e?.message || '权限修改失败')
    } finally { busy.value = null }
    return
  }
  // 选了某会员档：若原是管理员，先撤管理员，再设会员等级
  if (u.admin) {
    if (!confirm(`确认把 ${u.name} 从管理员改为「${memberTierLabel(level)}」？（会撤销其管理员权限）`)) return
    busy.value = u.id
    try {
      const synced = await setUserAdmin(u.id, false)
      u.admin = false
      if (!synced) warn('已撤管理员，但控制室同步失败', `请重试，否则 ${u.name} 可能仍能写 AI 配置`)
    } catch (e: any) {
      warn('撤管理员失败', e?.message || '权限修改失败')
      busy.value = null
      return
    } finally { busy.value = null }
  }
  await onTierChange(u, level)  // 复用：写会员等级
}

async function toggleAdmin(u: AdminUser) {
  const next = !u.admin
  if (!confirm(`确认${next ? '把' : '撤销'} ${u.name} ${next ? '设为管理员' : '的管理员权限'}？`)) return
  busy.value = u.id
  try {
    const synced = await setUserAdmin(u.id, next)
    u.admin = next // 服务器管理员身份已改成功（无论控制室是否同步）
    if (next) {
      success('已更新', `${u.name} 现在是管理员`)
    } else if (synced) {
      success('已撤为普通成员', `${u.name} 的控制室写权限将由主 AI 同步移除`)
    } else {
      // 控制室同步没成功 → 不能假装撤干净了，明确提示重试
      warn('已撤管理员，但控制室同步失败', `请重试，否则 ${u.name} 可能仍能写 AI 配置`)
    }
  } catch (e: any) {
    warn('操作失败', e?.message || '权限修改失败')
  } finally {
    busy.value = null
  }
}

async function doResetPassword(u: AdminUser) {
  const pwd = prompt(`给 ${u.name} 设置新密码（至少 8 位，会同时踢下线所有设备）：`)
  if (!pwd) return
  if (pwd.length < 8) { warn('密码太短', '至少 8 位'); return }
  busy.value = u.id
  try {
    await resetPassword(u.id, pwd)
    success('密码已重置', `${u.name} 需用新密码重新登录`)
  } catch (e: any) {
    warn('重置失败', e?.message || '无法重置密码')
  } finally {
    busy.value = null
  }
}

async function doDeactivate(u: AdminUser) {
  if (!confirm(`确认停用 ${u.name}？停用后该账号无法登录（可恢复）。`)) return
  busy.value = u.id
  try {
    await deactivateUser(u.id)
    u.deactivated = true
    success('已停用', `${u.name} 已无法登录`)
  } catch (e: any) {
    warn('停用失败', e?.message || '无法停用账号')
  } finally {
    busy.value = null
  }
}

async function doReactivate(u: AdminUser) {
  const pwd = prompt(`恢复 ${u.name} 需同时设新密码（服务器要求，至少 8 位）：`)
  if (!pwd) return
  if (pwd.length < 8) { warn('密码太短', '至少 8 位'); return }
  busy.value = u.id
  try {
    await reactivateUser(u.id, pwd)
    u.deactivated = false
    success('已恢复', `${u.name} 可用新密码登录了`)
  } catch (e: any) {
    warn('恢复失败', e?.message || '无法恢复账号')
  } finally {
    busy.value = null
  }
}

async function doCreate() {
  busy.value = 'create'
  try {
    const uid = await createUser(form.username, form.password, form.displayname || undefined)
    success('已创建', uid)
    showCreate.value = false
    form.username = ''; form.displayname = ''; form.password = ''
    await loadUsers()
  } catch (e: any) {
    warn('创建失败', e?.message || '无法创建账号')
  } finally {
    busy.value = null
  }
}

/* —— 频道管理 —— */
const rooms = ref<AdminRoom[]>([])
const roomsLoading = ref(false)
const roomsLoaded = ref(false)        // 懒加载：首次切到频道 tab 才拉
const roomBusy = ref<string | null>(null)
// 成员弹窗：membersOf 为当前查看的房间，null 表示关闭
const membersOf = ref<AdminRoom | null>(null)
const memberList = ref<string[]>([])
const membersLoading = ref(false)

/** 切到频道 tab；首次进入时懒加载列表 */
function switchToRooms() {
  tab.value = 'rooms'
  if (!roomsLoaded.value) loadRooms()
}

async function loadRooms() {
  roomsLoading.value = true
  try {
    rooms.value = await listAdminRooms()
    roomsLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法获取频道列表')
  } finally {
    roomsLoading.value = false
  }
}

async function viewMembers(r: AdminRoom) {
  membersOf.value = r
  membersLoading.value = true
  memberList.value = []
  try {
    memberList.value = await getRoomMembers(r.id)
  } catch (e: any) {
    warn('加载失败', e?.message || '无法获取成员')
  } finally {
    membersLoading.value = false
  }
}

async function doDeleteRoom(r: AdminRoom) {
  // 删除不可逆，二次确认；并询问是否一并封禁（禁止重建/重新加入）
  if (!confirm(`确认删除频道「${r.name}」？\n将踢出所有成员并清除历史，不可恢复。`)) return
  const block = confirm('是否同时【封禁】此频道？\n确定 = 封禁（禁止任何人再加入/重建，用于违规群）\n取消 = 仅删除')
  roomBusy.value = r.id
  try {
    await deleteRoom(r.id, block)
    rooms.value = rooms.value.filter(x => x.id !== r.id)
    success('已删除', `频道「${r.name}」已${block ? '删除并封禁' : '删除'}`)
  } catch (e: any) {
    warn('删除失败', e?.message || '无法删除频道')
  } finally {
    roomBusy.value = null
  }
}

/* —— AI 配置 —— */
const aiLoading = ref(false)
const aiSaving = ref(false)
const aiLoaded = ref(false)
// enabled_tools=null 表示全开；UI 里用一个集合表示"当前开启的工具"
const aiForm = reactive<{
  provider: string
  model: string
  system_prompt: string
  tools: Set<string>
}>({
  provider: '',
  model: '',
  system_prompt: '',
  tools: new Set(AI_TOOL_CATALOG.map((t) => t.name)), // 默认全开
})

// 当前选中 provider 的元信息（模型占位符等）
const providerMeta = computed(
  () => AI_PROVIDERS.find((p) => p.value === aiForm.provider) || AI_PROVIDERS[0],
)

function isToolOn(name: string): boolean {
  return aiForm.tools.has(name)
}
function toggleTool(name: string, on: boolean) {
  if (on) aiForm.tools.add(name)
  else aiForm.tools.delete(name)
}

function switchToAi() {
  tab.value = 'ai'
  if (!aiLoaded.value) loadAi()
}

async function loadAi() {
  aiLoading.value = true
  try {
    const cfg = await getAiConfig()
    aiForm.provider = cfg?.provider || ''
    aiForm.model = cfg?.model || ''
    aiForm.system_prompt = cfg?.system_prompt || ''
    const all = AI_TOOL_CATALOG.map((t) => t.name)
    aiForm.tools = new Set(cfg?.enabled_tools ?? all)
    aiLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取 AI 配置')
  } finally {
    aiLoading.value = false
  }
}

async function saveAi() {
  // 选了某家 provider → 提醒「key 在服务器配」（网页不再收 key）
  if (aiForm.provider) {
    if (!confirm(`已选「${providerMeta.value.label}」。请确认服务器已为它配好 API Key（环境变量/Secret Manager），否则 AI 无法回话。仍要保存吗？`)) return
  }
  aiSaving.value = true
  try {
    const all = AI_TOOL_CATALOG.map((t) => t.name)
    // 全开 → 存 null（表示不限制）；否则存当前集合
    const enabled = all.every((n) => aiForm.tools.has(n)) ? null : [...aiForm.tools]
    await setAiConfig({
      provider: aiForm.provider,
      model: aiForm.model,
      system_prompt: aiForm.system_prompt,
      enabled_tools: enabled,
    })
    success('已保存', '主 AI 约 20 秒内热生效')
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
  } finally {
    aiSaving.value = false
  }
}

/* —— 技能库（全局技能，写控制室 state event）—— */
const skills = ref<GlobalSkill[]>([])
const presetSkills = ref<GlobalSkill[]>([])  // 内置预置技能库(只读展示,可覆盖为自定义)
const skLoading = ref(false)
const skSaving = ref(false)
const skLoaded = ref(false)
const skEditing = ref(false)
// _isEdit=true 表示编辑已有技能（slug 锁定不可改）
const skForm = reactive<GlobalSkill & { _isEdit: boolean }>({
  slug: '', name: '', description: '', instructions: '', enabled: true, inject: '', _isEdit: false,
})
// 预置技能里已被控制室"覆盖"的 slug（覆盖后以自定义那份为准，预置区标记"已自定义"）
const overriddenSlugs = computed(() => new Set(skills.value.map((s) => s.slug)))

function switchToSkills() {
  tab.value = 'skills'
  if (!skLoaded.value) loadSkills()
}

async function loadSkills() {
  skLoading.value = true
  try {
    // 并行:控制室技能(可编辑) + 内置预置技能(只读展示)。预置失败不阻断主列表。
    const [ctrl, preset] = await Promise.all([
      getGlobalSkills(),
      getPresetSkills().catch(() => [] as GlobalSkill[]),
    ])
    skills.value = ctrl
    presetSkills.value = preset
    skLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取技能')
  } finally {
    skLoading.value = false
  }
}

// "覆盖为自定义":把预置技能复制进编辑表单(inject 默认保持 agent,不变全局注入),
// 管理员改完保存到控制室后即以自定义那份为准(同 slug 覆盖预置)。
function overridePreset(s: GlobalSkill) {
  Object.assign(skForm, {
    slug: s.slug, name: s.name, description: s.description,
    instructions: s.instructions, enabled: true,
    access: s.access || '', inject: 'agent', _isEdit: false,
  })
  skAccessKind.value = ''
  skAccessTpls.value = []
  if (!tpLoaded.value) loadTemplates()
  skEditing.value = true
}

/* —— 资源「可用范围」(access)：技能/智能体共用的解析/构造/展示 ——
 * 取值：''=所有人；paid/creator=该会员等级及以上；admin=仅平台管理员；
 * 'tpl:keyA,keyB'=仅选了这些入驻模板注册的用户。bot 服务端按此强制过滤（注入/名册）。 */
function parseAccess(a?: string): { kind: string; tpls: string[] } {
  const v = String(a || '').trim()
  if (!v || v === 'public') return { kind: '', tpls: [] }
  if (v.startsWith('tpl:')) return { kind: 'tpl', tpls: v.slice(4).split(',').filter(Boolean) }
  return { kind: v, tpls: [] }
}
function buildAccess(kind: string, tpls: string[]): string {
  if (kind === 'tpl') return tpls.length ? 'tpl:' + tpls.join(',') : ''
  return kind
}
function accessLabel(a?: string): string {
  const { kind, tpls } = parseAccess(a)
  if (!kind) return '所有人'
  if (kind === 'paid') return '付费+'
  if (kind === 'creator') return '创作者+'
  if (kind === 'admin') return '仅管理员'
  if (kind === 'tpl') return '模板 ' + (tpls.join('、') || '—')
  return kind
}
function toggleAccessTpl(list: string[], key: string) {
  const i = list.indexOf(key)
  if (i >= 0) list.splice(i, 1)
  else list.push(key)
}
const skAccessKind = ref('')
const skAccessTpls = ref<string[]>([])
const agAccessKind = ref('')
const agAccessTpls = ref<string[]>([])

function startAddSkill() {
  Object.assign(skForm, {
    slug: '', name: '', description: '', instructions: '', enabled: true, inject: '', _isEdit: false,
  })
  skAccessKind.value = ''
  skAccessTpls.value = []
  if (!tpLoaded.value) loadTemplates()  // 「指定模板」选项需要模板列表
  skEditing.value = true
}

function startEditSkill(s: GlobalSkill) {
  Object.assign(skForm, { ...s, inject: s.inject || '', _isEdit: true })
  const p = parseAccess(s.access)
  skAccessKind.value = p.kind
  skAccessTpls.value = p.tpls
  if (!tpLoaded.value) loadTemplates()
  skEditing.value = true
}

/** 把当前 skills 列表整体写回控制室（全局技能是一个 state event 里的数组）。 */
async function persistSkills(next: GlobalSkill[], okMsg: string) {
  // 加载失败(skLoaded=false)时拒绝写：此刻 skills 可能是空/旧值，整体覆盖会抹掉线上真实技能。
  if (!skLoaded.value) {
    warn('请先成功加载', '技能列表尚未加载成功，无法保存（避免覆盖线上配置）')
    throw new Error('技能未加载')
  }
  skSaving.value = true
  try {
    await setGlobalSkills(next)
    skills.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    skSaving.value = false
  }
}

async function saveSkill() {
  const slug = skForm.slug.trim()
  if (!slug) return
  const item: GlobalSkill = {
    slug,
    name: skForm.name.trim(),
    description: skForm.description.trim(),
    instructions: skForm.instructions,
    enabled: skForm.enabled,
    access: buildAccess(skAccessKind.value, skAccessTpls.value),
    inject: skForm.inject === 'agent' ? 'agent' : '',
  }
  // 已有同 slug → 覆盖；否则追加
  const next = skills.value.slice()
  const i = next.findIndex((s) => s.slug === slug)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistSkills(next, '主 AI 约 20 秒内热生效')
    skEditing.value = false
  } catch { /* persistSkills 已提示 */ }
}

async function toggleSkill(s: GlobalSkill) {
  const next = skills.value.map((x) =>
    x.slug === s.slug ? { ...x, enabled: !x.enabled } : x,
  )
  try { await persistSkills(next, s.enabled ? '已停用' : '已启用') } catch { /* 已提示 */ }
}

async function removeSkill(s: GlobalSkill) {
  if (!confirm(`确认删除技能「${s.name || s.slug}」？`)) return
  const next = skills.value.filter((x) => x.slug !== s.slug)
  try { await persistSkills(next, '已删除') } catch { /* 已提示 */ }
}

/* —— 智能体（全局 Agent，写控制室 state event）—— */
const agents = ref<GlobalAgent[]>([])
const agLoading = ref(false)
const agSaving = ref(false)
const agLoaded = ref(false)
const agEditing = ref(false)
const agForm = reactive<GlobalAgent & { _isEdit: boolean }>({
  slug: '', name: '', description: '', system_prompt: '', model: '',
  skill_slugs: [], enabled: true, _isEdit: false,
})

function switchToAgents() {
  tab.value = 'agents'
  if (!agLoaded.value) loadAgents()
  if (!skLoaded.value) loadSkills() // 绑定技能用的勾选列表
}

async function loadAgents() {
  agLoading.value = true
  try {
    agents.value = await getGlobalAgents()
    agLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取智能体')
  } finally {
    agLoading.value = false
  }
}

function startAddAgent() {
  Object.assign(agForm, {
    slug: '', name: '', description: '', system_prompt: '', model: '',
    skill_slugs: [], enabled: true, _isEdit: false,
  })
  agAccessKind.value = ''
  agAccessTpls.value = []
  if (!tpLoaded.value) loadTemplates()  // 「指定模板」选项需要模板列表
  agEditing.value = true
}

function startEditAgent(a: GlobalAgent) {
  Object.assign(agForm, { ...a, skill_slugs: [...a.skill_slugs], _isEdit: true })
  const p = parseAccess(a.access)
  agAccessKind.value = p.kind
  agAccessTpls.value = p.tpls
  if (!tpLoaded.value) loadTemplates()
  agEditing.value = true
}

function toggleAgentSkill(slug: string, on: boolean) {
  const i = agForm.skill_slugs.indexOf(slug)
  if (on && i < 0) agForm.skill_slugs.push(slug)
  else if (!on && i >= 0) agForm.skill_slugs.splice(i, 1)
}

async function persistAgents(next: GlobalAgent[], okMsg: string) {
  if (!agLoaded.value) {
    warn('请先成功加载', '智能体列表尚未加载成功，无法保存（避免覆盖线上配置）')
    throw new Error('智能体未加载')
  }
  agSaving.value = true
  try {
    await setGlobalAgents(next)
    agents.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    agSaving.value = false
  }
}

async function saveAgent() {
  const slug = agForm.slug.trim()
  if (!slug) return
  const item: GlobalAgent = {
    slug,
    name: agForm.name.trim(),
    description: agForm.description.trim(),
    system_prompt: agForm.system_prompt,
    model: agForm.model.trim(),
    skill_slugs: [...agForm.skill_slugs],
    enabled: agForm.enabled,
    access: buildAccess(agAccessKind.value, agAccessTpls.value),
  }
  const next = agents.value.slice()
  const i = next.findIndex((a) => a.slug === slug)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistAgents(next, '已保存智能体')
    agEditing.value = false
  } catch { /* 已提示 */ }
}

async function toggleAgent(a: GlobalAgent) {
  const next = agents.value.map((x) =>
    x.slug === a.slug ? { ...x, enabled: !x.enabled } : x,
  )
  try { await persistAgents(next, a.enabled ? '已停用' : '已启用') } catch { /* 已提示 */ }
}

async function removeAgent(a: GlobalAgent) {
  if (!confirm(`确认删除智能体「${a.name || a.slug}」？`)) return
  const next = agents.value.filter((x) => x.slug !== a.slug)
  try { await persistAgents(next, '已删除') } catch { /* 已提示 */ }
}

/* —— 人员能力（模块3.5：直接同步「用户管理」真实账号，给每人补能力备注，不重建人）—— */
const people = ref<Person[]>([])          // 能力名册（cosmac.people）
const peopleUsers = ref<AdminUser[]>([])  // 真实账号（来自 listUsers，排除中枢AI）
const plLoading = ref(false)
const plSaving = ref(false)
const plLoaded = ref(false)
const plEditing = ref(false)
const plForm = reactive<Person>({
  user_id: '', name: '', role: '', expertise: '', note: '', enabled: true,
})

function switchToPeople() {
  tab.value = 'people'
  if (!plLoaded.value) loadPeople()
}

async function loadPeople() {
  plLoading.value = true
  try {
    // 同时拉真实账号 + 能力名册，合并展示——账号是主体，能力是叠加上去的备注
    const [reg, us] = await Promise.all([getPeople(), listUsers()])
    people.value = reg
    peopleUsers.value = us.filter((u) => !u.isBot)  // 排除中枢 AI
    plLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取用户/能力')
  } finally {
    plLoading.value = false
  }
}

// user_id → 能力备注
const peopleMap = computed(() => {
  const m: Record<string, Person> = {}
  for (const p of people.value) m[p.user_id] = p
  return m
})
// 表格行 = 真实账号 + 叠加其能力（没设的 hasProfile=false）。
// 与用户管理对齐：带 deactivated（停用账号灰显、不可设置）；排序「在用在前、停用在后」。
const peopleRows = computed(() =>
  peopleUsers.value
    .map((u) => {
      const p = peopleMap.value[u.id]
      return {
        id: u.id,
        name: p?.name || u.name || '',
        role: p?.role || '',
        expertise: p?.expertise || '',
        enabled: p ? p.enabled : true,
        hasProfile: !!p,
        deactivated: u.deactivated,
      }
    })
    .sort((a, b) => Number(a.deactivated) - Number(b.deactivated)),  // 停用排后
)
const peopleSearch = ref('')
const peopleCap = ref<'all' | 'set' | 'unset'>('all')  // 按是否已设能力筛
const peopleFiltered = computed(() => {
  const q = peopleSearch.value.trim().toLowerCase()
  return peopleRows.value.filter((r) => {
    if (q && !`${r.name} ${r.id} ${r.role} ${r.expertise}`.toLowerCase().includes(q)) return false
    if (peopleCap.value === 'set' && !r.hasProfile) return false
    if (peopleCap.value === 'unset' && r.hasProfile) return false
    return true
  })
})

function startEditPersonForUser(r: { id: string; name: string; deactivated?: boolean }) {
  if (r.deactivated) return  // 停用账号不可设置能力（防御：按钮已禁用）
  const ex = peopleMap.value[r.id]
  Object.assign(plForm, {
    user_id: r.id,
    name: ex?.name || r.name || '',
    role: ex?.role || '',
    expertise: ex?.expertise || '',
    note: ex?.note || '',
    enabled: ex ? ex.enabled : true,
  })
  plEditing.value = true
}

async function persistPeople(next: Person[], okMsg: string) {
  if (!plLoaded.value) {
    warn('请先成功加载', '尚未加载成功，无法保存（避免覆盖线上配置）')
    throw new Error('未加载')
  }
  plSaving.value = true
  try {
    await setPeople(next)
    people.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    plSaving.value = false
  }
}

async function savePerson() {
  const uid = plForm.user_id.trim()
  if (!uid) return
  const item: Person = {
    user_id: uid,
    name: plForm.name.trim(),
    role: plForm.role.trim(),
    expertise: plForm.expertise.trim(),
    note: plForm.note.trim(),
    enabled: plForm.enabled,
  }
  const next = people.value.slice()
  const i = next.findIndex((p) => p.user_id === uid)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistPeople(next, '已保存能力')
    plEditing.value = false
  } catch { /* 已提示 */ }
}

async function removePersonById(uid: string) {
  if (!confirm('清除该成员的能力备注？（不会删除账号，只是从 AI 派单名册移除）')) return
  const next = people.value.filter((p) => p.user_id !== uid)
  try { await persistPeople(next, '已清除') } catch { /* 已提示 */ }
}

/* —— 入驻模板（管理员定义注册引导可选的「方案」，写控制室 state event）—— */
const templates = ref<OnboardingTemplateDef[]>([])
const tpLoading = ref(false)
const tpSaving = ref(false)
const tpEditing = ref(false)
const tpLoaded = ref(false)
const tpChannelsText = ref('') // 频道编辑用文本（一行一个），保存时拆成数组
function tplDefaults(): OnboardingTemplateDef & { _isEdit: boolean } {
  return {
    key: '', label: '', icon: '🧩', desc: '', model: '', persona: '', rules: '',
    skillSlugs: [], kbDocs: [], channels: [], workflowSlugs: [], tier: 'free', enabled: true, _isEdit: false,
  }
}
const tpForm = reactive<OnboardingTemplateDef & { _isEdit: boolean }>(tplDefaults())

function switchToTemplates() {
  tab.value = 'templates'
  if (!tpLoaded.value) loadTemplates()
  if (!skLoaded.value) loadSkills()       // 技能勾选列表
  if (!wfLoaded.value) loadWorkflows()    // 工作流勾选列表
}

async function loadTemplates() {
  tpLoading.value = true
  try {
    templates.value = await getOnboardingTemplates()
    tpLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取入驻模板')
  } finally {
    tpLoading.value = false
  }
}

function startAddTemplate() {
  Object.assign(tpForm, tplDefaults())
  tpChannelsText.value = ''
  tpEditing.value = true
}

function startEditTemplate(t: OnboardingTemplateDef) {
  Object.assign(tpForm, {
    ...t,
    skillSlugs: [...t.skillSlugs],
    workflowSlugs: [...t.workflowSlugs],
    channels: [...t.channels],
    kbDocs: t.kbDocs.map((d) => ({ ...d })),
    _isEdit: true,
  })
  tpChannelsText.value = t.channels.join('\n')
  tpEditing.value = true
}

function toggleTplSkill(slug: string, on: boolean) {
  const i = tpForm.skillSlugs.indexOf(slug)
  if (on && i < 0) tpForm.skillSlugs.push(slug)
  else if (!on && i >= 0) tpForm.skillSlugs.splice(i, 1)
}
function toggleTplWorkflow(slug: string, on: boolean) {
  const i = tpForm.workflowSlugs.indexOf(slug)
  if (on && i < 0) tpForm.workflowSlugs.push(slug)
  else if (!on && i >= 0) tpForm.workflowSlugs.splice(i, 1)
}
function addTplDoc() { tpForm.kbDocs.push({ title: '', content: '' }) }
function removeTplDoc(i: number) { tpForm.kbDocs.splice(i, 1) }

async function persistTemplates(next: OnboardingTemplateDef[], okMsg: string) {
  if (!tpLoaded.value) {
    warn('请先成功加载', '入驻模板尚未加载成功，无法保存（避免覆盖线上配置）')
    throw new Error('模板未加载')
  }
  tpSaving.value = true
  try {
    await setOnboardingTemplates(next)
    templates.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    tpSaving.value = false
  }
}

async function saveTemplate() {
  const key = tpForm.key.trim()
  if (!key || !tpForm.label.trim()) return
  const channels = tpChannelsText.value.split('\n').map((s) => s.trim()).filter(Boolean)
  const kbDocs = tpForm.kbDocs
    .map((d) => ({ title: d.title.trim(), content: d.content }))
    .filter((d) => d.title)
  const item: OnboardingTemplateDef = {
    key,
    label: tpForm.label.trim(),
    icon: tpForm.icon.trim() || '🧩',
    desc: tpForm.desc.trim(),
    model: tpForm.model.trim(),
    persona: tpForm.persona,
    rules: tpForm.rules,
    skillSlugs: [...tpForm.skillSlugs],
    kbDocs,
    channels,
    workflowSlugs: [...tpForm.workflowSlugs],
    tier: tpForm.tier,
    enabled: tpForm.enabled,
  }
  const next = templates.value.slice()
  const i = next.findIndex((t) => t.key === key)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistTemplates(next, '已保存模板')
    tpEditing.value = false
  } catch { /* 已提示 */ }
}

async function toggleTemplate(t: OnboardingTemplateDef) {
  const next = templates.value.map((x) => (x.key === t.key ? { ...x, enabled: !x.enabled } : x))
  try { await persistTemplates(next, t.enabled ? '已下架' : '已上架') } catch { /* 已提示 */ }
}

async function removeTemplate(t: OnboardingTemplateDef) {
  if (!confirm(`确认删除模板「${t.label || t.key}」？`)) return
  const next = templates.value.filter((x) => x.key !== t.key)
  try { await persistTemplates(next, '已删除') } catch { /* 已提示 */ }
}

/* —— 规则（全局硬约束，写控制室 state event）—— */
const rules = ref<GlobalRule[]>([])
const ruLoading = ref(false)
const ruSaving = ref(false)
const ruLoaded = ref(false)

function switchToRules() {
  tab.value = 'rules'
  if (!ruLoaded.value) loadRules()
}

async function loadRules() {
  ruLoading.value = true
  try {
    rules.value = await getGlobalRules()
    ruLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取规则')
  } finally {
    ruLoading.value = false
  }
}

async function saveRules() {
  // 加载失败时拒绝写：rules 可能是空/旧值，整体覆盖会抹掉线上真实规则。
  if (!ruLoaded.value) {
    warn('请先成功加载', '全局规则尚未加载成功，无法保存（避免覆盖线上配置）')
    return
  }
  ruSaving.value = true
  try {
    // 去掉空行后保存（空文本规则没意义）
    const clean = rules.value
      .map((r) => ({ text: r.text.trim(), enabled: r.enabled }))
      .filter((r) => r.text)
    await setGlobalRules(clean)
    rules.value = clean
    success('已保存', '主 AI 约 20 秒内热生效')
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
  } finally {
    ruSaving.value = false
  }
}

/* —— 会员权限（功能门控，写控制室 cosmac.gating）—— */
const gates = ref<GatingMap>({})
// 按 group 分组展示能力目录（保持目录里的出现顺序）
const gateGroups = computed(() => {
  const order: string[] = []
  const map: Record<string, typeof GATE_CATALOG> = {}
  for (const g of GATE_CATALOG) {
    const k = g.group || '其他'
    if (!map[k]) { map[k] = []; order.push(k) }
    map[k].push(g)
  }
  return order.map((group) => ({ group, items: map[group] }))
})
const gateLoading = ref(false)
const gateSaving = ref(false)
const gateLoaded = ref(false)

function switchToGating() {
  tab.value = 'gating'
  if (!gateLoaded.value) loadGating()
}

async function loadGating() {
  gateLoading.value = true
  try {
    gates.value = await getGating() // 已合并默认，目录每项都有值
    gateLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取门控策略')
  } finally {
    gateLoading.value = false
  }
}

async function saveGating() {
  gateSaving.value = true
  try {
    await setGating(gates.value)
    success('已保存', '主 AI 约 15 秒内热生效')
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
  } finally {
    gateSaving.value = false
  }
}

/* —— 用量配额（写控制室 cosmac.quotas；变现第二步）—— */
const quotas = ref<QuotaLimits>({})
const quotaLoading = ref(false)
const quotaSaving = ref(false)
const quotaLoaded = ref(false)

function switchToQuotas() {
  tab.value = 'quotas'
  if (!quotaLoaded.value) loadQuotas()
}
async function loadQuotas() {
  quotaLoading.value = true
  try {
    quotas.value = await getQuotas() // 已合并默认，每项每等级都有值
    quotaLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取配额')
  } finally {
    quotaLoading.value = false
  }
}
async function saveQuotas() {
  if (!quotaLoaded.value) { warn('请先成功加载', '配额尚未加载成功，无法保存（避免覆盖线上配置）'); return }
  quotaSaving.value = true
  try {
    // 规范化成整数（-1=不限），避免空/小数写进去
    const clean: QuotaLimits = {}
    for (const q of QUOTA_CATALOG) {
      clean[q.key] = {}
      for (const t of MEMBER_TIERS) {
        const v = Number(quotas.value[q.key]?.[t.slug])
        clean[q.key][t.slug] = Number.isFinite(v) ? Math.trunc(v) : (q.defaults[t.slug] ?? -1)
      }
    }
    await setQuotas(clean)
    quotas.value = clean
    success('已保存', '主 AI 约 20 秒内热生效')
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
  } finally {
    quotaSaving.value = false
  }
}

/* —— 会员套餐（写控制室 cosmac.plans；模块4 交易系统）—— */
const plans = ref<PlanDef[]>([])
const planLoading = ref(false)
const planSaving = ref(false)
const planLoaded = ref(false)
const planEditing = ref(false)
// priceText：编辑态用「元」字符串(便于输入)，保存时 ×100 转「分」存进 prices。
const planForm = reactive<{
  slug: string; name: string; tier: string; period_days: number
  priceText: Record<string, string>; enabled: boolean; _isEdit: boolean
}>({ slug: '', name: '', tier: 'paid', period_days: 30, priceText: {}, enabled: true, _isEdit: false })

/** 把套餐价格(分)拼成给人看的文案，如 "USD $9.99 · CNY ¥68"。 */
function planPriceText(p: PlanDef): string {
  const parts: string[] = []
  for (const c of PLAN_CURRENCIES) {
    const cents = p.prices[c.code]
    if (cents && cents > 0) parts.push(`${c.label} ${(cents / 100).toFixed(2)}`)
  }
  return parts.join(' · ') || '（未定价）'
}

function switchToPlans() {
  tab.value = 'plans'
  if (!planLoaded.value) loadPlans()
}

async function loadPlans() {
  planLoading.value = true
  try {
    plans.value = await getPlans()
    planLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取套餐')
  } finally {
    planLoading.value = false
  }
}

function startAddPlan() {
  Object.assign(planForm, {
    slug: '', name: '', tier: 'paid', period_days: 30,
    priceText: {}, enabled: true, _isEdit: false,
  })
  planEditing.value = true
}

function startEditPlan(p: PlanDef) {
  const priceText: Record<string, string> = {}
  for (const c of PLAN_CURRENCIES) {
    const cents = p.prices[c.code]
    if (cents && cents > 0) priceText[c.code] = String(cents / 100)
  }
  Object.assign(planForm, {
    slug: p.slug, name: p.name, tier: p.tier, period_days: p.period_days,
    priceText, enabled: p.enabled, _isEdit: true,
  })
  planEditing.value = true
}

async function persistPlans(next: PlanDef[], okMsg: string) {
  planSaving.value = true
  try {
    await setPlans(next)
    plans.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    planSaving.value = false
  }
}

async function savePlan() {
  const slug = planForm.slug.trim()
  if (!slug) return
  // 元→分：每种货币 parseFloat 后 ×100 取整；非正/非法的丢弃
  const prices: Record<string, number> = {}
  for (const c of PLAN_CURRENCIES) {
    const v = parseFloat((planForm.priceText[c.code] || '').trim())
    if (Number.isFinite(v) && v > 0) prices[c.code] = Math.round(v * 100)
  }
  if (!Object.keys(prices).length) { warn('保存失败', '至少填一种货币的价格'); return }
  const item: PlanDef = {
    slug, name: planForm.name.trim() || slug,
    tier: planForm.tier === 'creator' ? 'creator' : 'paid',
    period_days: Math.max(1, Math.trunc(planForm.period_days) || 30),
    prices, enabled: planForm.enabled,
  }
  const next = plans.value.slice()
  const i = next.findIndex((p) => p.slug === slug)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistPlans(next, '已保存套餐')
    planEditing.value = false
  } catch { /* 已提示 */ }
}

async function togglePlan(p: PlanDef) {
  const next = plans.value.map((x) => x.slug === p.slug ? { ...x, enabled: !x.enabled } : x)
  try { await persistPlans(next, p.enabled ? '已下架' : '已上架') } catch { /* 已提示 */ }
}

async function removePlan(p: PlanDef) {
  if (!confirm(`确认删除套餐「${p.name || p.slug}」？`)) return
  const next = plans.value.filter((x) => x.slug !== p.slug)
  try { await persistPlans(next, '已删除') } catch { /* 已提示 */ }
}

/* —— 工作流连接器（写控制室 state event）—— */
const workflows = ref<WorkflowDef[]>([])
const wfLoading = ref(false)
const wfSaving = ref(false)

// —— 各列表页 搜索 + 筛选（用户管理另有角色/会员/状态筛选）——
// 频道：按类型（全部/公开/私有）筛
const chType = ref<'all' | 'public' | 'private'>('all')
const chPred = computed(() => (r: AdminRoom) => chType.value === 'all' || (chType.value === 'public' ? r.isPublic : !r.isPublic))
const { query: chSearch, filtered: chFiltered } = useListSearch(rooms, (r) => `${r.name} ${r.id} ${r.alias || ''} ${r.creator || ''}`, chPred)
// 技能 / 智能体 / 模板 / 工作流 / 套餐：按 启用/停用 筛
const skEn = useEnabledFilter<GlobalSkill>()
const { query: skSearch, filtered: skFiltered } = useListSearch(skills, (s) => `${s.name} ${s.slug} ${s.description}`, skEn.predicate)
const agEn = useEnabledFilter<GlobalAgent>()
const { query: agSearch, filtered: agFiltered } = useListSearch(agents, (a) => `${a.name} ${a.slug} ${a.description}`, agEn.predicate)
const tpEn = useEnabledFilter<OnboardingTemplateDef>()
const { query: tpSearch, filtered: tpFiltered } = useListSearch(templates, (t) => `${t.label} ${t.key} ${t.desc}`, tpEn.predicate)
const wfEn = useEnabledFilter<WorkflowDef>()
const { query: wfSearch, filtered: wfFiltered } = useListSearch(workflows, (w) => `${w.name} ${w.slug} ${w.platform || ''}`, wfEn.predicate)
const plEn = useEnabledFilter<PlanDef>()
const { query: plSearch, filtered: plFiltered } = useListSearch(plans, (p) => `${p.name} ${p.slug} ${p.tier}`, plEn.predicate)
const wfLoaded = ref(false)
const wfEditing = ref(false)
const wfForm = reactive<WorkflowDef & { _isEdit: boolean }>({
  slug: '', name: '', platform: 'webhook', url: '', method: 'POST',
  cred: '', input_hint: '', enabled: true,
  mode: 'workflow', ref_id: '', input_key: '', graph: '', async: false, _isEdit: false,
})

const wfUrlPlaceholder = computed(() => ({
  webhook: 'https://n8n.example.com/webhook/xxx',
  dify: 'https://api.dify.ai（或自建 Dify 地址）',
  coze: 'https://api.coze.cn（国际版 https://api.coze.com）',
  comfyui: 'http://你的ComfyUI地址:8188',
}[wfForm.platform] || ''))

function switchToWorkflows() {
  tab.value = 'workflows'
  if (!wfLoaded.value) loadWorkflows()
}

async function loadWorkflows() {
  wfLoading.value = true
  try {
    workflows.value = await getWorkflows()
    wfLoaded.value = true
  } catch (e: any) {
    warn('加载失败', e?.message || '无法读取连接器')
  } finally {
    wfLoading.value = false
  }
}

function startAddWorkflow() {
  Object.assign(wfForm, {
    slug: '', name: '', platform: 'webhook', url: '', method: 'POST',
    cred: '', input_hint: '', enabled: true,
    mode: 'workflow', ref_id: '', input_key: '', graph: '', async: false, _isEdit: false,
  })
  wfEditing.value = true
}

function startEditWorkflow(w: WorkflowDef) {
  Object.assign(wfForm, { ...w, _isEdit: true })
  wfEditing.value = true
}

async function persistWorkflows(next: WorkflowDef[], okMsg: string) {
  if (!wfLoaded.value) {
    warn('请先成功加载', '工作流列表尚未加载成功，无法保存（避免覆盖线上配置）')
    throw new Error('工作流未加载')
  }
  wfSaving.value = true
  try {
    await setWorkflows(next)
    workflows.value = next
    success('已保存', okMsg)
  } catch (e: any) {
    warn('保存失败', e?.message || '无法写入控制室')
    throw e
  } finally {
    wfSaving.value = false
  }
}

async function saveWorkflow() {
  const slug = wfForm.slug.trim()
  if (!slug || !wfForm.url.trim()) return
  const item: WorkflowDef = {
    slug, name: wfForm.name.trim(), platform: wfForm.platform,
    url: wfForm.url.trim(), method: wfForm.method, cred: wfForm.cred.trim(),
    input_hint: wfForm.input_hint.trim(), enabled: wfForm.enabled,
    mode: wfForm.mode, ref_id: wfForm.ref_id.trim(), input_key: wfForm.input_key.trim(),
    graph: wfForm.graph,
    // #3：只有 webhook 支持异步回调；切到 dify/coze/comfyui 时 async 复选框是隐藏的，
    // 这里强制清成 false，免得残留 async=true 让后端挂一个永远等不到回调的 pending。
    async: wfForm.platform === 'webhook' ? wfForm.async : false,
  }
  const next = workflows.value.slice()
  const i = next.findIndex((w) => w.slug === slug)
  if (i >= 0) next[i] = item
  else next.push(item)
  try {
    await persistWorkflows(next, '已保存连接器')
    wfEditing.value = false
  } catch { /* 已提示 */ }
}

async function toggleWorkflow(w: WorkflowDef) {
  const next = workflows.value.map((x) =>
    x.slug === w.slug ? { ...x, enabled: !x.enabled } : x,
  )
  try { await persistWorkflows(next, w.enabled ? '已停用' : '已启用') } catch { /* 已提示 */ }
}

async function removeWorkflow(w: WorkflowDef) {
  if (!confirm(`确认删除连接器「${w.name || w.slug}」？`)) return
  const next = workflows.value.filter((x) => x.slug !== w.slug)
  try { await persistWorkflows(next, '已删除') } catch { /* 已提示 */ }
}

/* —— 数据概览 —— */
const ovLoading = ref(false)
const ovLoaded = ref(false)
const ov = reactive({
  version: '',
  userTotal: 0, adminCount: 0, deactivated: 0,
  roomTotal: 0, publicRooms: 0, encryptedRooms: 0,
  memberSum: 0, avgMembers: 0, activeRooms: 0,
  topRooms: [] as AdminRoom[],
})

function switchToOverview() {
  tab.value = 'overview'
  if (!ovLoaded.value) loadOverview()
}

/** 聚合统计：复用 listUsers + listAdminRooms + getServerVersion，前端算汇总 */
async function loadOverview() {
  ovLoading.value = true
  try {
    const [us, rs, ver] = await Promise.all([listUsers(), listAdminRooms(), getServerVersion()])
    ov.version = ver
    ov.userTotal = us.length
    ov.adminCount = us.filter((u) => u.admin).length
    ov.deactivated = us.filter((u) => u.deactivated).length
    ov.roomTotal = rs.length
    ov.publicRooms = rs.filter((r) => r.isPublic).length
    ov.encryptedRooms = rs.filter((r) => r.encrypted).length
    ov.memberSum = rs.reduce((sum, r) => sum + r.members, 0)
    ov.avgMembers = rs.length ? Math.round((ov.memberSum / rs.length) * 10) / 10 : 0
    ov.activeRooms = rs.filter((r) => r.members >= 2).length
    // 客户端按成员数降序取前 8（不依赖接口排序——实测 Admin API 的 dir=b 在本版未降序）
    ov.topRooms = [...rs].sort((a, b) => b.members - a.members).slice(0, 8)
    ovLoaded.value = true
  } catch (e: any) {
    warn('统计失败', e?.message || '无法获取概览数据')
  } finally {
    ovLoading.value = false
  }
}

onMounted(check)
</script>

<style scoped>
/* 全屏覆盖层：盖住整个工作台，自带关闭按钮 */
.admin-view {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  min-height: 0;
  background: var(--bg);
  color: var(--text);
  animation: adm-fade 0.15s ease;
}
@keyframes adm-fade { from { opacity: 0; } to { opacity: 1; } }

.adm-close {
  position: absolute;
  top: 14px; right: 18px;
  z-index: 3;
  width: 30px; height: 30px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  color: var(--text-3);
  font-size: 15px; cursor: pointer;
  transition: background 0.1s ease, color 0.1s ease;
}
.adm-close:hover { background: var(--bg-soft); color: var(--text); }

/* —— 左侧菜单 —— */
.adm-nav {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  gap: 18px;
}
.adm-brand { display: flex; align-items: center; gap: 10px; padding: 4px; }
.adm-logo {
  width: 34px; height: 34px; border-radius: 9px;
  background: var(--accent); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 17px;
}
.adm-title { font-size: var(--fs-200); font-weight: var(--fw-bold); }
.adm-sub { font-size: var(--fs-75); color: var(--text-3); margin-top: 1px; }
.adm-menu { display: flex; flex-direction: column; gap: 2px; }
.adm-mi {
  display: flex; align-items: center; gap: 9px;
  padding: 9px 10px; border: none; border-radius: 8px;
  background: transparent; color: var(--text-2);
  font-size: var(--fs-100); text-align: left; cursor: pointer;
  transition: background 0.1s ease;
}
.adm-mi:hover:not(:disabled) { background: var(--bg-soft); color: var(--text); }
.adm-mi.active { background: var(--accent-soft); color: var(--accent); font-weight: var(--fw-bold); }
.adm-mi:disabled { color: var(--text-3); cursor: default; }
.adm-mi-ic { width: 18px; text-align: center; }
.adm-soon {
  margin-left: auto; font-size: 10px; color: var(--text-3);
  background: var(--bg-soft); padding: 1px 6px; border-radius: 8px;
}

/* —— 右侧内容 —— */
.adm-main { flex: 1; min-width: 0; overflow-y: auto; padding: 22px 26px; }
.adm-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; padding-right: 44px; }
.adm-h1 { font-size: 20px; font-weight: var(--fw-bold); }
.adm-hint { font-size: var(--fs-75); color: var(--text-3); margin-top: 4px; }
/* 技能库:预置区块标题 */
.adm-preset-block { margin-bottom: 8px; }
.adm-preset-h { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.adm-preset-h > span:first-child { font-weight: var(--fw-bold); font-size: var(--fs-100); color: var(--text); }
.adm-preset-sub { font-size: var(--fs-75); color: var(--text-3); }
/* 会员等级读取失败的警示条：橙黄底、不刺眼但明显，提示数据不可信 */
.adm-warnbar {
  margin: 0 0 12px; padding: 10px 14px; border-radius: 8px;
  background: rgba(201, 100, 66, 0.1); border: 1px solid rgba(201, 100, 66, 0.3);
  color: var(--text-2); font-size: var(--fs-75); line-height: 1.5;
}
.adm-actions { display: flex; gap: 8px; }

.adm-btn {
  border: none; border-radius: 8px; cursor: pointer;
  white-space: nowrap; flex-shrink: 0;
  padding: 8px 14px; font-size: var(--fs-100);
  background: var(--accent); color: #fff; font-weight: var(--fw-bold);
  transition: opacity 0.1s ease;
}
.adm-btn:hover:not(:disabled) { opacity: 0.88; }
.adm-btn:disabled { opacity: 0.5; cursor: default; }
.adm-btn.ghost { background: var(--bg-soft); color: var(--text-2); font-weight: 400; }
.adm-btn.sm { padding: 5px 10px; font-size: var(--fs-75); border-radius: 7px; }
.adm-btn.danger { color: var(--danger); }
.adm-btn.danger:hover:not(:disabled) { background: #fee2e2; opacity: 1; }

/* 技能库 */
.adm-row-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: nowrap; white-space: nowrap; }
.adm-rule-row { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.adm-rule-row input[type=checkbox] { margin-top: 10px; flex-shrink: 0; }
.adm-rule-text { flex: 1; resize: vertical; }
.adm-rule-row .adm-btn { flex-shrink: 0; margin-top: 4px; }
.adm-skill-desc { color: var(--text-2); }
.adm-skill-desc, .adm-table { /* 说明列吃满剩余宽;表格强制满宽 */ }
.adm-table { table-layout: auto; }
/* 短内容列(标识/名称等)禁折行——两三个字/带连字符的 slug 不许竖排 */
.adm-nowrap { white-space: nowrap; }
/* 入驻模板表单：两列网格 + 知识库文档行 */
.adm-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.adm-kbdoc { display: grid; grid-template-columns: 1fr; gap: 6px; padding: 10px; margin-bottom: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel, #fff); }
.adm-kbdoc .adm-kbdoc-t { font-weight: 600; }
.adm-skill-edit {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  background: var(--bg-soft);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.adm-badge {
  font-size: var(--fs-75);
  padding: 2px 9px;
  white-space: nowrap;
  display: inline-block;
  border-radius: 999px;
  background: var(--bg-soft);
  color: var(--text-3);
  border: 1px solid var(--border);
}
.adm-badge.on {
  color: var(--ok, #2e7d32);
  border-color: color-mix(in srgb, var(--ok, #2e7d32) 40%, var(--border));
  background: color-mix(in srgb, var(--ok, #2e7d32) 10%, transparent);
}

/* 表格 */
.adm-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
.adm-search { flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg-soft); color: var(--text); font-size: var(--fs-100); }
.adm-search:focus { outline: none; border-color: var(--accent); }
.adm-fsel { padding: 8px 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg-soft); color: var(--text); font-size: var(--fs-75); cursor: pointer; }
.adm-filter-n { font-size: var(--fs-75); color: var(--text-3); margin-left: auto; }
.adm-empty-row { text-align: center; color: var(--text-3); padding: 24px 0; font-size: var(--fs-75); }
.adm-grp-row td { padding-top: 16px; font-size: var(--fs-75); font-weight: var(--fw-bold); color: var(--text-2); border-bottom: 1px solid var(--border); }
.adm-table { width: 100%; border-collapse: collapse; font-size: var(--fs-100); }
.adm-table th {
  text-align: left; font-size: var(--fs-75); color: var(--text-3); font-weight: 400;
  padding: 8px 10px; border-bottom: 1px solid var(--border);
}
.adm-ops-h { text-align: right; }
.adm-table td { padding: 11px 10px; border-bottom: 1px solid var(--border-soft); vertical-align: middle; }
.adm-table tr.off td { opacity: 0.55; }

.adm-user { display: flex; align-items: center; gap: 10px; }
.adm-ava {
  width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0;
  background: var(--accent); color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 600;
}
.adm-u-name { font-weight: var(--fw-bold); display: flex; align-items: center; gap: 6px; }
.adm-u-handle { font-size: var(--fs-75); color: var(--text-3); font-family: var(--mono); margin-top: 1px; }
.adm-u-email { font-size: var(--fs-75); color: var(--text-3); margin-top: 1px; }

.adm-tag { font-size: 11px; padding: 2px 8px; border-radius: 8px; }
.adm-tag.admin { color: var(--accent); background: var(--accent-soft); }
.adm-tag.member { color: var(--text-3); background: var(--bg-soft); }
.adm-tag.ok { color: var(--ok); background: color-mix(in srgb, var(--ok) 14%, transparent); }
.adm-tag.off { color: var(--danger); background: #fee2e2; }
.adm-tag.bot { color: #fff; background: var(--accent); }

/* 会员等级下拉：免费=低调，付费/创作者=带强调色，一眼可辨 */
.adm-tier {
  font-size: 11px; padding: 3px 8px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2);
}
.adm-tier:disabled { opacity: 0.5; cursor: default; }
.adm-tier.paid {
  color: var(--accent); border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  background: var(--accent-soft);
}
.adm-tier.creator {
  color: #b45309; border-color: #f59e0b;
  background: color-mix(in srgb, #f59e0b 14%, transparent);
}
.adm-tier.admin {
  color: #7c3aed; border-color: #7c3aed;
  background: color-mix(in srgb, #7c3aed 14%, transparent);
}
.adm-muted { color: var(--text-3); }
.adm-qnum { width: 72px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg-soft); color: var(--text); font-size: var(--fs-75); }
.adm-qnum:focus { outline: none; border-color: var(--accent); }

.adm-ops { text-align: right; white-space: nowrap; }
.adm-op {
  border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2);
  font-size: var(--fs-75); padding: 5px 9px; border-radius: 7px; margin-left: 6px; cursor: pointer;
  transition: background 0.1s ease;
}
.adm-op:hover:not(:disabled) { background: var(--bg-soft); color: var(--text); }
.adm-op:disabled { opacity: 0.4; cursor: default; }
.adm-op.danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
.adm-op.danger:hover:not(:disabled) { background: #fee2e2; }

/* 居中态（loading / denied） */
.adm-center {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 60px 0; color: var(--text-3); font-size: var(--fs-100);
}
.adm-spin {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--accent);
  animation: adm-rot 0.7s linear infinite;
}
@keyframes adm-rot { to { transform: rotate(360deg); } }

/* 图文教程后台编辑：给内嵌的 DocChannelView 一块定高区域(它内部 height:100%) */
.adm-doc-edit { height: calc(100vh - 160px); min-height: 420px; border: 1px solid var(--line, #eae6df); border-radius: 12px; overflow: hidden; }
.adm-denied { flex-direction: column; gap: 8px; text-align: center; padding-top: 80px; }
.adm-denied-ic { font-size: 40px; }
.adm-denied-t { font-size: 17px; font-weight: var(--fw-bold); color: var(--text); }
.adm-denied-d { max-width: 380px; line-height: 1.6; }
.adm-denied-d code { font-family: var(--mono); color: var(--accent); }

/* 新建弹窗 */
.adm-mask {
  position: fixed; inset: 0; z-index: 80;
  background: rgba(0, 0, 0, 0.28);
  display: flex; align-items: center; justify-content: center;
}
.adm-modal {
  width: 380px; background: var(--bg-panel);
  border: 1px solid var(--border); border-radius: 14px; padding: 20px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.18);
}
.adm-modal-h { font-size: var(--fs-200); font-weight: var(--fw-bold); margin-bottom: 14px; }
.adm-field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.adm-field span { font-size: var(--fs-75); color: var(--text-3); }
.adm-field input {
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px;
  font-size: var(--fs-100); background: var(--bg); color: var(--text);
}
.adm-field input:focus { outline: none; border-color: var(--accent); }
.adm-modal-f { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }

/* 频道管理补充 */
.adm-dim { color: var(--text-3); font-size: var(--fs-75); }
.adm-empty { text-align: center; color: var(--text-3); padding: 24px 0; }
.adm-tag.bot { margin-left: 6px; }

/* AI 配置表单 */
.adm-form { max-width: 640px; display: flex; flex-direction: column; gap: 18px; }
/* 真凶修复(浏览器实测定位):技能库等面板把「列表表格」也包进了 adm-form,表格被 640px
   限宽压扁(表格 width:100% = 640 的 100%,右侧大片空白)。含表格的 adm-form 解除限宽,
   纯表单面板(AI配置等)维持 640 的舒适阅读宽。 */
.adm-form:has(.adm-table) { max-width: none; }
.adm-form .adm-field textarea,
.adm-form .adm-field input,
.adm-form .adm-field select {
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px;
  font-size: var(--fs-100); background: var(--bg); color: var(--text);
  font-family: inherit; resize: vertical; line-height: 1.5;
}
/* select 高度按内容自适应：覆盖全局 .cam-select 的固定 height:34px——
   它与本表单更高内边距(9px)叠加会把选项文字竖直切掉(34-18<行高)。 */
.adm-form .adm-field select { height: auto; resize: none; }
.adm-form .adm-field textarea:focus,
.adm-form .adm-field input:focus,
.adm-form .adm-field select:focus { outline: none; border-color: var(--accent); }
.adm-note { font-size: var(--fs-75); color: var(--text-3); font-style: normal; line-height: 1.5; }
.plan-price-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.plan-price-cur { flex: 0 0 84px; font-size: var(--fs-85); color: var(--text-2); }
.plan-price-row input { flex: 1; }
.adm-tools { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.adm-tool {
  display: flex; align-items: center; gap: 9px; cursor: pointer;
  padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel);
}
.adm-tool input { width: 16px; height: 16px; accent-color: var(--accent); }
.adm-tool-l { font-size: var(--fs-100); color: var(--text); }
.adm-tool code { margin-left: auto; font-family: var(--mono); font-size: var(--fs-75); color: var(--text-3); }

/* 数据概览 KPI 卡片 */
.adm-kpis {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 24px;
}
.adm-kpi {
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-panel); padding: 16px 18px;
}
.adm-kpi-v { font-size: 30px; font-weight: var(--fw-bold); color: var(--accent); line-height: 1.1; }
.adm-kpi-l { font-size: var(--fs-100); color: var(--text); margin-top: 4px; }
.adm-kpi-s { font-size: var(--fs-75); color: var(--text-3); margin-top: 2px; }
.adm-h2 { font-size: var(--fs-200); font-weight: var(--fw-bold); margin: 4px 0 12px; }

/* 成员弹窗列表 */
.adm-mlist { max-height: 320px; overflow-y: auto; margin-bottom: 12px; }
.adm-mrow { display: flex; align-items: center; gap: 9px; padding: 6px 2px; }
.adm-ava.sm { width: 26px; height: 26px; font-size: 12px; border-radius: 7px; }
.adm-mid { font-family: var(--mono); font-size: var(--fs-75); color: var(--text-2); }
</style>
