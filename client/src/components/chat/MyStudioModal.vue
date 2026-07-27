<!--
  「我的AI工坊」——用户自建 智能体 / 技能(归属本人账号、计入存储空间;负责人需求)。
  · 智能体:私人 AI 同事——出现在你的派单名册(标「我的·」),任意频道输入它的名字即由它应答。
  · 技能:随你每轮对话自动生效的方法论(精简为宜,占每轮注入预算)。
  数据走 bot 端点(/cosmac/my/*),服务端按 owner 隔离 + 存储配额硬管控。
-->
<template>
  <div v-if="visible" class="cam-overlay" @click.self="close">
    <div class="cam-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <div>
          <div class="cam-title">我的AI工坊</div>
          <div class="cam-sub">自建你的专属 智能体 与 技能 · 归属你的账号 · 计入存储空间</div>
        </div>
        <!-- 用共享样式表里的 cam-close(靠右+悬停态);此前误写成不存在的 cam-x,渲染成原生按钮挤在标题旁 -->
        <button class="cam-close" title="关闭" @click="close">×</button>
      </div>

      <div class="cam-tabs">
        <button class="cam-tab" :class="{ active: tab === 'agents' }" @click="tab = 'agents'">我的智能体 <i>{{ agents.length }}</i></button>
        <button class="cam-tab" :class="{ active: tab === 'skills' }" @click="tab = 'skills'">我的技能 <i>{{ skills.length }}</i></button>
        <button class="cam-tab" :class="{ active: tab === 'acquired' }" @click="tab = 'acquired'">已获取 <i>{{ acquired.length }}</i></button>
        <button v-if="pubData?.wallet_enabled" class="cam-tab" :class="{ active: tab === 'publish' }" @click="switchPublish">上架·收益 <i>{{ pubData?.items?.length || 0 }}</i></button>
      </div>

      <div class="cam-body">
        <div v-if="errText" class="cam-help cam-help-top" style="color:#b94a4a">{{ errText }}</div>

        <!-- ═══ 智能体 ═══ -->
        <template v-if="tab === 'agents'">
          <div class="cam-help cam-help-top">它会出现在主 AI 的派单名册里（标「我的·」）；在任意频道输入它的名字，就由它来应答。</div>
          <div v-for="a in agents" :key="a.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">我的·{{ a.name }} <code class="ms-slug">{{ a.slug }}</code>
                <span v-if="a.source_url" class="cam-tag ms-src" :title="'从这里导入：' + a.source_url">导入</span>
                <span v-if="!a.enabled" class="cam-tag" style="background:#eee;color:#888">停用</span>
              </div>
              <div class="cam-row-desc">{{ a.description }}</div>
            </div>
            <button class="cam-mini" @click="editAgent(a)">编辑</button>
            <button class="cam-del" title="删除" @click="delAgent(a.slug)">×</button>
          </div>
          <p v-if="!agents.length && !editing" class="cam-row-desc" style="padding:8px 2px">还没有自建智能体。点下方「＋ 新建智能体」造一个专属 AI 同事。</p>

          <template v-if="editing && tab === 'agents'">
            <div class="ms-form">
              <input v-model.trim="agForm.slug" class="cam-input" :disabled="agForm._edit" placeholder="标识 slug(小写字母/数字/中划线,如 my-writer)" />
              <input v-model.trim="agForm.name" class="cam-input" placeholder="名称(如 小说写手)" />
              <input v-model.trim="agForm.description" class="cam-input" placeholder="备注:它是干嘛的、什么时候找它(主 AI 派单就看这句)" />
              <div class="ms-persona-h">
                <span class="ms-persona-label">人设（system prompt）</span>
                <button type="button" class="cam-mini" @click="applyPersonaTemplate">套用结构模板</button>
              </div>
              <textarea v-model="agForm.system_prompt" class="cam-input ms-ta ms-persona" rows="12" maxlength="4000" placeholder="你是…擅长…工作方式…输出…（可点上方「套用结构模板」按推荐结构写）" />
              <span class="ms-hint">按 角色定位 / 擅长 / 工作方式 / 输出要求 / 注意事项 五段写更专业；智能体只在被 @/点名时激活、不占日常上下文，可以写详细些（上限 4000 字）。</span>
              <input v-model.trim="agForm.model" class="cam-input" placeholder="模型(可选,留空跟随全局)" />
              <div class="ms-wf">
                <span class="ms-persona-label">绑定工作流（让它能真的动手，而不只是会说话）</span>
                <p v-if="!bindableWfs.length" class="ms-hint">
                  平台还没接入工作流连接器。接入后（n8n / Coze / Dify / ComfyUI）这里就能勾选。
                </p>
                <template v-else>
                  <label v-for="w in bindableWfs" :key="w.slug" class="ms-check">
                    <input type="checkbox" :checked="(agForm.workflow_slugs || []).includes(w.slug)"
                      @change="toggleAgWorkflow(w.slug, ($event.target as HTMLInputElement).checked)" />
                    {{ w.name || w.slug }}<code class="ms-wf-slug">{{ w.slug }}</code>
                  </label>
                  <span class="ms-hint">
                    勾选后，这个智能体被派活时会知道可以调用它们。
                    ⚠️ 能不能真的跑，仍取决于你自己的「工作流运行」权限——绑定不会额外提权。
                  </span>
                </template>
              </div>
              <label class="ms-check"><input v-model="agForm.enabled" type="checkbox" /> 启用</label>
              <div class="ms-actions">
                <button class="cam-mini" @click="editing = false">取消</button>
                <button class="cam-add-btn" :disabled="busy" @click="saveAgent">{{ busy ? '保存中…' : '保存' }}</button>
              </div>
            </div>
          </template>
          <div v-else class="cam-add">
            <button class="cam-add-btn" @click="newAgent">＋ 新建智能体</button>
            <button class="cam-mini" @click="openImport('agent')">从链接导入</button>
          </div>
        </template>

        <!-- ═══ 技能 ═══ -->
        <template v-else-if="tab === 'skills'">
          <div class="cam-help cam-help-top">技能随你的每轮对话自动生效（也可在私聊里用「技能」命令管理，同一份数据）。精简为宜，太长会占对话预算。</div>
          <div v-for="s in skills" :key="s.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ s.name || s.slug }} <code class="ms-slug">{{ s.slug }}</code>
                <span v-if="s.source_url" class="cam-tag ms-src" :title="'从这里导入：' + s.source_url">导入</span>
                <span v-if="!s.enabled" class="cam-tag" style="background:#eee;color:#888">停用</span>
              </div>
              <div class="cam-row-desc">{{ s.description || (s.instructions || '').slice(0, 60) }}</div>
            </div>
            <button class="cam-mini" @click="editSkill(s)">编辑</button>
            <button class="cam-del" title="删除" @click="delSkill(s.slug)">×</button>
          </div>
          <p v-if="!skills.length && !editing" class="cam-row-desc" style="padding:8px 2px">还没有自建技能。</p>

          <template v-if="editing && tab === 'skills'">
            <div class="ms-form">
              <input v-model.trim="skForm.slug" class="cam-input" :disabled="skForm._edit" placeholder="标识 slug(如 daily-recap)" />
              <input v-model.trim="skForm.name" class="cam-input" placeholder="名称(如 每日复盘)" />
              <input v-model.trim="skForm.description" class="cam-input" placeholder="备注(一句话说明,可选)" />
              <textarea v-model="skForm.instructions" class="cam-input ms-ta" rows="4" maxlength="2000" placeholder="技能正文:方法论/格式/清单,喂给 AI 的指令" />
              <label class="ms-check"><input v-model="skForm.enabled" type="checkbox" /> 启用</label>
              <div class="ms-actions">
                <button class="cam-mini" @click="editing = false">取消</button>
                <button class="cam-add-btn" :disabled="busy" @click="saveSkill">{{ busy ? '保存中…' : '保存' }}</button>
              </div>
            </div>
          </template>
          <div v-else class="cam-add">
            <button class="cam-add-btn" @click="newSkill">＋ 新建技能</button>
            <button class="cam-mini" @click="openImport('skill')">从链接导入</button>
          </div>
        </template>

        <!-- ═══ 上架·收益（创作者商城 P2/P3）═══ -->
        <template v-else-if="tab === 'publish'">
          <!-- 非创作者：认证申请流程（P3 类公众号：提交资料→付认证费→平台审核） -->
          <template v-if="!pubData?.is_creator">
            <div class="cam-help cam-help-top">把你的自建智能体上架到商城、按次收 token，需要先<b>申请成为创作者</b>：提交资料 → 支付认证费{{ certFeeText }} → 平台审核通过即获得创作者资格。审核不通过不退费，但可免费修改资料重新提交。</div>

            <!-- 审核中 -->
            <div v-if="certApp?.status === 'pending_review'" class="ms-cert-status">
              ⏳ 你的认证申请<b>审核中</b>——平台会尽快审核，通过后这里自动解锁上架功能。
            </div>
            <!-- 被拒：展示原因 + 重新提交表单 -->
            <template v-else-if="certApp?.status === 'rejected' && !certEditing">
              <div class="ms-cert-status rejected">
                ❌ 上次申请未通过：{{ certApp.reason || '未说明原因' }}
              </div>
              <div class="ms-actions"><button class="cam-add-btn" @click="startCertEdit">修改资料重新提交（免费）</button></div>
            </template>
            <!-- 待付费：已提交资料、还没付 -->
            <template v-else-if="certApp?.status === 'pending_payment' && !certOrder && !certEditing">
              <div class="ms-cert-status">资料已提交，还差最后一步：支付认证费{{ certFeeText }}。</div>
              <div class="ms-actions">
                <button class="cam-add-btn" :disabled="busy" @click="certPay">{{ busy ? '下单中…' : `支付认证费${certFeeText}` }}</button>
                <button class="cam-mini" @click="startCertEdit">修改资料</button>
              </div>
            </template>
            <!-- 申请表单（新申请 / 修改资料） -->
            <template v-else-if="certEditing || !certApp">
              <div class="ms-form">
                <input v-model.trim="certForm.name" class="cam-input" placeholder="称呼 / 机构名（必填）" />
                <input v-model.trim="certForm.contact" class="cam-input" placeholder="联系方式：手机 / 微信 / 邮箱（必填，审核联系用）" />
                <textarea v-model="certForm.intro" class="cam-input ms-ta" rows="3" maxlength="2000" placeholder="自我介绍 / 资质说明（必填）：你是谁、擅长什么领域" />
                <textarea v-model="certForm.portfolio" class="cam-input ms-ta" rows="3" maxlength="4000" placeholder="作品 / 能力证明（选填）：代表作、账号链接、案例说明等" />
                <div class="ms-actions">
                  <button v-if="certApp" class="cam-mini" @click="certEditing = false">取消</button>
                  <button class="cam-add-btn" :disabled="busy || !certForm.name || !certForm.contact || !certForm.intro" @click="certSubmit">
                    {{ busy ? '提交中…' : '提交申请' }}
                  </button>
                </div>
              </div>
            </template>
            <!-- 认证费订单：测试通道确认 -->
            <template v-if="certOrder">
              <div class="ms-cert-status">订单 <code>{{ certOrder.order_no }}</code> 已创建（测试通道，不收款）</div>
              <div class="ms-actions">
                <button class="cam-add-btn" :disabled="busy" @click="certConfirmPay">{{ busy ? '确认中…' : '模拟支付成功（测试）' }}</button>
                <button class="cam-mini" @click="certOrder = null">取消</button>
              </div>
            </template>
          </template>
          <template v-else>
            <!-- 收益汇总 -->
            <div class="ms-earn-sum">
              <div class="ms-earn-num">{{ (pubData?.summary?.total_net || 0).toLocaleString() }}<span>token 累计收益</span></div>
              <div class="ms-earn-sub">被使用 {{ pubData?.summary?.count || 0 }} 次 · 平台抽成 {{ pubData?.fee_pct ?? 10 }}%（你得 {{ 100 - (pubData?.fee_pct ?? 10) }}%）· 收益已充入你的 token 钱包</div>
            </div>

            <!-- 我的上架列表 -->
            <div v-for="li in (pubData?.items || [])" :key="li.id" class="cam-row">
              <div class="cam-row-main">
                <div class="cam-row-label">{{ li.name }} <code class="ms-slug">{{ li.agent_slug }}</code>
                  <span class="cam-tag" :style="li.kind === 'skill' ? 'background:#e6efe9;color:#3f6b53' : 'background:#e6ecf3;color:#3c5a78'">{{ li.kind === 'skill' ? '技能·买断' : '智能体·按次' }}</span>
                  <span v-if="li.status === 'banned'" class="cam-tag" style="background:#f6e3e3;color:#b94a4a">平台下架</span>
                  <span v-else-if="li.status === 'pending'" class="cam-tag" style="background:#f4ead9;color:#9a6b1f">审核中</span>
                  <span v-else-if="li.status === 'rejected'" class="cam-tag" style="background:#f6e3e3;color:#b94a4a">未通过</span>
                  <span v-else-if="li.status === 'off'" class="cam-tag" style="background:#eee;color:#888">已下架</span>
                  <span v-else class="cam-tag" style="background:#e5efe0;color:#4a7b42">在售</span>
                </div>
                <div class="cam-row-desc">{{ li.price_tokens > 0 ? `${li.price_tokens.toLocaleString()} token${li.kind === 'skill' ? ' 买断' : '/次'}` : '免费' }} · {{ li.kind === 'skill' ? '已售' : '被使用' }} {{ li.uses }} 次 · 已赚 {{ li.earned.toLocaleString() }} token</div>
                <div v-if="li.status === 'rejected' && li.review_reason" class="cam-row-desc" style="color:#b94a4a">拒绝原因：{{ li.review_reason }}（可在下方重新提交，将再次审核）</div>
              </div>
              <button v-if="li.status === 'on'" class="cam-mini" :disabled="busy" @click="setListing(li.id, 'off')">下架</button>
              <button v-else-if="li.status === 'off' || li.status === 'rejected'" class="cam-mini" :disabled="busy" @click="republish(li)">重新提交审核</button>
            </div>
            <p v-if="!(pubData?.items || []).length" class="cam-row-desc" style="padding:8px 2px">还没有上架。选一个你的智能体、定个价提交审核，通过后即可售卖。</p>

            <!-- 上架表单：Agent 按次计费 / Skill 一次性买断 -->
            <div class="ms-form">
              <div class="ms-kind-pick">
                <label><input type="radio" value="agent" v-model="pubForm.kind" @change="pubForm.agent_slug = ''" /> 智能体（按次收费）</label>
                <label><input type="radio" value="skill" v-model="pubForm.kind" @change="pubForm.agent_slug = ''" /> 技能（一次性买断）</label>
              </div>
              <select v-model="pubForm.agent_slug" class="cam-input">
                <option value="" disabled>{{ pubForm.kind === 'skill' ? '选择要上架的技能…' : '选择要上架的智能体…' }}</option>
                <option v-for="a in publishablePool" :key="a.slug" :value="a.slug">{{ a.name }}（{{ a.slug }}）</option>
              </select>
              <input v-model.number="pubForm.price" class="cam-input" type="number" min="0"
                :placeholder="pubForm.kind === 'skill' ? '买断价（token，一次性，0=免费）' : '每次使用价（token，0=免费）'" />
              <span class="ms-hint">
                提交后进入<b>平台审核</b>，通过才在售（任何修改都会重新审核，审核期间暂不可售）。上架是「引用」：内容仍归你、不会公开给用户；平台抽成后其余实时充进你的钱包。
                <template v-if="pubForm.kind === 'skill'"><br>技能是每轮对话自动生效的，所以按<b>一次性买断</b>卖：用户获取时付清、之后永久可用。</template>
                <template v-else><br>智能体按<b>次</b>卖：用户获取免费，每次 @ 使用时才扣你定的价。</template>
              </span>
              <div class="ms-actions">
                <button class="cam-add-btn" :disabled="busy || !pubForm.agent_slug" @click="publish">{{ busy ? '提交中…' : '提交上架审核' }}</button>
              </div>
            </div>

            <!-- 收益明细（最近） -->
            <template v-if="earnItems.length">
              <div class="cam-help" style="margin-top:10px">最近收益明细</div>
              <div v-for="e in earnItems" :key="e.id" class="ms-earn-row">
                <span class="ms-earn-what">{{ e.agent_slug }} · {{ shortUser(e.buyer) }} 使用</span>
                <span class="ms-earn-net">+{{ e.net.toLocaleString() }}</span>
                <span class="ms-earn-time">{{ new Date(e.created_at).toLocaleString() }}</span>
              </div>
            </template>
          </template>
        </template>

        <!-- ═══ 已获取（AI Agent 商城）═══ -->
        <template v-else>
          <div class="cam-help cam-help-top">你从「AI Agent 商城」获取的资源。主 AI 派单时会优先考虑你获取的 AI 同事（名册里标 ★）。</div>
          <div v-for="it in acquired" :key="it.kind + ':' + it.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">
                <span class="ms-kind" :style="{ background: CAT_META[it.kind]?.color || '#888' }">{{ CAT_META[it.kind]?.label || it.kind }}</span>
                {{ it.name }}
                <span v-if="it.stale" class="cam-tag" style="background:#f6e3e3;color:#b94a4a">已下架</span>
                <span v-else-if="!it.unlocked" class="cam-tag" style="background:#f4ead9;color:#9a6b1f">需升级会员</span>
              </div>
              <div class="cam-row-desc">
                {{ it.description || '（该资源已不在商城货架上，可移除）' }}
                <template v-if="it.kind === 'skill' && it.agents.length"> · 随【{{ it.agents.join('/') }}】激活</template>
              </div>
            </div>
            <button class="cam-del" title="移除（不影响使用权限，只是不再优先派单）" @click="removeAcquired(it)">×</button>
          </div>
          <p v-if="!acquired.length" class="cam-row-desc" style="padding:8px 2px">还没有获取过商城资源。</p>
          <div class="cam-add"><button class="cam-add-btn" @click="goMarket"><Icon name="marketplace" :size="14" /> 去 AI Agent 商城逛逛</button></div>
        </template>

        <!-- 底部提示按 tab 给准确口径(负责人报:已获取 57 个却写着"每类上限 50")——
             50 是**自建**内容的上限(服务端强制);「已获取」只是给平台资源打优先派单标记,
             不占存储、不限个数,写同一句话会让人以为获取超限了。 -->
        <div v-if="tab === 'agents' || tab === 'skills'" class="cam-help">自建内容计入你的存储空间（见「我的额度」）。每类上限 50 个。</div>
        <div v-else-if="tab === 'acquired'" class="cam-help">
          获取＝给平台资源打「优先派单」标记（★），不占存储空间。
          <template v-if="acquiredLimit !== null && acquiredLimit >= 0">
            按会员等级限量：已用 <b>{{ acquired.length }}/{{ acquiredLimit }}</b> 个；
            额度不够时移除不常用的，或升级会员扩容。
          </template>
          <template v-else-if="acquiredLimit === -1">你的会员等级不限获取数量。</template>
        </div>
      </div>
    </div>
  
      <!-- ═══ 从链接导入(manifest) ═══
           两步走:预览只取回不落库,让用户**读完人设/正文全文**再决定。
           第三方人设会作为系统提示注入给 AI,而主 AI 手里有建群/发消息/查知识库等工具,
           静默导入等于把一部分控制权交给素未谋面的作者。 -->
      <div v-if="importOpen" class="ms-import-mask" @click.self="closeImport">
        <div class="ms-import">
          <div class="ms-import-h">
            <strong>从链接导入{{ importKind === 'agent' ? '智能体' : '技能' }}</strong>
            <button class="cam-mini" @click="closeImport">关闭</button>
          </div>

          <template v-if="!importPv">
            <input v-model.trim="importUrl" class="cam-input"
              placeholder="粘贴 manifest 地址，如 https://github.com/用户/仓库/blob/main/guduu-agent.json" />
            <span class="ms-hint">
              目前支持 GitHub / Gist 上的 JSON 定义文件。导入的是<b>定义</b>（人设、技能正文、
              引用关系），不会下载或运行任何代码。
            </span>
            <p v-if="importErr" class="ms-import-err">{{ importErr }}</p>
            <div class="ms-actions">
              <button class="cam-add-btn" :disabled="importBusy || !importUrl" @click="doPreview">
                {{ importBusy ? '读取中…' : '预览' }}
              </button>
            </div>
          </template>

          <template v-else>
            <div class="ms-import-sum">
              <div><b>{{ importPv.item.name }}</b><code class="ms-wf-slug">{{ importPv.item.slug }}</code></div>
              <div class="ms-hint">{{ importPv.item.description }}</div>
              <div v-if="importPv.item.author || importPv.item.license" class="ms-hint">
                作者：{{ importPv.item.author || '未标注' }} · 许可：{{ importPv.item.license || '未标注' }}
              </div>
            </div>
            <ul v-if="importPv.notes.length" class="ms-import-notes">
              <li v-for="(n, i) in importPv.notes" :key="i">{{ n }}</li>
            </ul>
            <p v-if="importMissing" class="ms-import-err">
              ⚠️ 缺依赖：它引用了{{ importMissing }}，而你手上没有。
              装了也用不上这部分能力——可以先装，之后再补齐。
            </p>
            <p v-if="importPv.exists" class="ms-import-err">
              你已有同名 {{ importPv.item.slug }}，导入会<b>覆盖</b>它。
            </p>
            <div class="ms-persona-label">
              {{ importPv.item.kind === 'agent' ? '人设全文（请通读后再确认）' : '技能正文（请通读后再确认）' }}
            </div>
            <pre class="ms-import-body">{{ importPv.item.system_prompt || importPv.item.instructions }}</pre>
            <p v-if="importErr" class="ms-import-err">{{ importErr }}</p>
            <div class="ms-actions">
              <button class="cam-mini" @click="importPv = null">重新填地址</button>
              <button class="cam-add-btn" :disabled="importBusy" @click="doConfirm">
                {{ importBusy ? '导入中…' : '我已读过，确认导入' }}
              </button>
            </div>
          </template>
        </div>
      </div>
</div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed, reactive, ref, watch } from 'vue'
import '@/styles/admin-modal.css'
import {
  myAgentsList, myAgentSave, myAgentDelete, myWorkflowsList,
  importPreview, importConfirm, type ImportPreview,
  mySkillsList, mySkillSave, mySkillDelete,
  fetchMarketAcquired, setMarketItemAcquired, getMyUsage,
  creatorListings, creatorPublish, creatorSetStatus, creatorEarnings,
  creatorApplyGet, creatorApplySubmit, payManualConfirm,
  type MyAgent, type MySkill, type AcquiredItem,
  type CreatorListingsResp, type CreatorEarningItem, type CreatorApplication,
  type CreatorListing,
} from '@/matrix/client'
import { CAT_META } from '@/data/marketplace'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'market'): void }>()
function close() { emit('close') }

const tab = ref<'agents' | 'skills' | 'acquired' | 'publish'>('agents')
const agents = ref<MyAgent[]>([])
const skills = ref<MySkill[]>([])
const acquired = ref<AcquiredItem[]>([])
const editing = ref(false)
const busy = ref(false)
const errText = ref('')
const agForm = reactive<MyAgent & { _edit: boolean }>({ slug: '', name: '', description: '', system_prompt: '', model: '', workflow_slugs: [], enabled: true, _edit: false })
// ── 从链接导入(manifest) ──
// 刻意做成两步:预览(只取回不落库) → 用户读完全文 → 确认。
// sha256 由预览返回、确认时回传:服务端会**重新拉取并比对**,防"预览时良性、
// 确认时被换成恶意版本"(TOCTOU)。前端不做校验,也不该被信任。
const importOpen = ref(false)
const importKind = ref<'agent' | 'skill'>('agent')
const importUrl = ref('')
const importPv = ref<ImportPreview | null>(null)
const importBusy = ref(false)
const importErr = ref('')

function openImport(kind: 'agent' | 'skill') {
  importKind.value = kind
  importUrl.value = ''
  importPv.value = null
  importErr.value = ''
  importOpen.value = true
}
function closeImport() { importOpen.value = false; importPv.value = null; importErr.value = '' }

/** 把缺失的依赖拼成一句人话；都不缺则为空串（模板据此决定要不要显示）。 */
const importMissing = computed(() => {
  const m = importPv.value?.missing
  if (!m) return ''
  const parts: string[] = []
  if (m.skills?.length) parts.push(`技能 ${m.skills.join('、')}`)
  if (m.workflows?.length) parts.push(`工作流 ${m.workflows.join('、')}`)
  return parts.join('；')
})

async function doPreview() {
  importBusy.value = true; importErr.value = ''
  try {
    const pv = await importPreview(importUrl.value)
    // 类型对不上就别让用户在"技能"页装进来一个智能体(反之亦然),避免困惑
    if (pv.item.kind !== importKind.value) {
      importErr.value = `这个链接里是${pv.item.kind === 'agent' ? '智能体' : '技能'}定义，`
        + `请到「我的${pv.item.kind === 'agent' ? '智能体' : '技能'}」页导入。`
      return
    }
    importPv.value = pv
  } catch (e: any) {
    importErr.value = e?.message || '预览失败'
  } finally { importBusy.value = false }
}

async function doConfirm() {
  if (!importPv.value) return
  importBusy.value = true; importErr.value = ''
  try {
    await importConfirm(importUrl.value, importPv.value.sha256)
    importOpen.value = false
    importPv.value = null
    await load()
  } catch (e: any) {
    importErr.value = e?.message || '导入失败'
  } finally { importBusy.value = false }
}

// 可绑定的工作流清单(服务端只下发 slug/name/输入提示,不含 url 与凭据名)
const bindableWfs = ref<{ slug: string; name: string; input_hint?: string }[]>([])
function toggleAgWorkflow(slug: string, on: boolean) {
  if (!agForm.workflow_slugs) agForm.workflow_slugs = []
  const i = agForm.workflow_slugs.indexOf(slug)
  if (on && i < 0) agForm.workflow_slugs.push(slug)
  else if (!on && i >= 0) agForm.workflow_slugs.splice(i, 1)
}
const skForm = reactive<MySkill & { _edit: boolean }>({ slug: '', name: '', description: '', instructions: '', enabled: true, _edit: false })

// 「已获取」额度(按会员等级,服务端强制):-1=不限;null=还没拉到
const acquiredLimit = ref<number | null>(null)
// 上架·收益（创作者商城 P2）：钱包总开关关着时后端回 wallet_enabled=false → 页签隐藏
const pubData = ref<CreatorListingsResp | null>(null)
const pubForm = reactive<{ kind: 'agent' | 'skill'; agent_slug: string; price: number | '' }>(
  { kind: 'agent', agent_slug: '', price: '' },
)
/** 可上架的资源池：按选中的类型给智能体或技能（都只列启用的）。 */
const publishablePool = computed(() =>
  pubForm.kind === 'skill'
    ? skills.value.filter((x) => x.enabled).map((x) => ({ slug: x.slug, name: x.name || x.slug }))
    : agents.value.filter((x) => x.enabled).map((x) => ({ slug: x.slug, name: x.name || x.slug })),
)
const earnItems = ref<CreatorEarningItem[]>([])

async function load() {
  errText.value = ''
  const [a, s, g, usage, pub, wfs] = await Promise.all([
    myAgentsList(), mySkillsList(), fetchMarketAcquired(), getMyUsage(),
    creatorListings(), myWorkflowsList(),
  ])
  bindableWfs.value = wfs || []
  agents.value = a
  skills.value = s
  acquired.value = g || []
  // 额度展示口径与服务端同源(都读 acquired_items 这项配额),避免前后端各写一份而跑偏
  acquiredLimit.value = usage.find((u) => u.key === 'acquired_items')?.limit ?? null
  pubData.value = pub
}

/* —— 创作者认证申请（P3）—— */
const certApp = ref<CreatorApplication | null>(null)
const certFee = ref(0)                     // 认证费（分）
const certEditing = ref(false)             // 是否在编辑申请表单
const certForm = reactive({ name: '', contact: '', intro: '', portfolio: '' })
const certOrder = ref<{ order_no: string; checkout?: any } | null>(null)
const certFeeText = computed(() => certFee.value > 0 ? `（¥${(certFee.value / 100).toFixed(2)}）` : '（当前免费）')

/** 切到「上架·收益」时顺带拉最近收益明细 + 认证申请状态（懒加载）。 */
async function switchPublish() {
  tab.value = 'publish'
  const [e, ap] = await Promise.all([creatorEarnings(20), creatorApplyGet()])
  earnItems.value = e?.items || []
  if (ap) {
    certApp.value = ap.application
    certFee.value = ap.cert_fee_cents || 0
    if (ap.application) Object.assign(certForm, {
      name: ap.application.name, contact: ap.application.contact,
      intro: ap.application.intro, portfolio: ap.application.portfolio,
    })
  }
}

function startCertEdit() { certEditing.value = true }

/** 提交/重新提交认证申请；后端待付费时会带回订单。 */
async function certSubmit() {
  busy.value = true; errText.value = ''
  try {
    const r = await creatorApplySubmit({ ...certForm })
    certEditing.value = false
    if (r.status === 'pending_payment' && r.order_no) {
      certOrder.value = { order_no: r.order_no, checkout: r.checkout }
    }
    const ap = await creatorApplyGet()
    if (ap) certApp.value = ap.application
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** 已提交待付费：单独点「支付认证费」（重进页面时表单不重填）。 */
async function certPay() {
  busy.value = true; errText.value = ''
  try {
    const r = await creatorApplySubmit({ ...certForm })
    if (r.status === 'pending_payment' && r.order_no) {
      certOrder.value = { order_no: r.order_no, checkout: r.checkout }
    }
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** 认证费测试通道确认 → 申请进入待审核。 */
async function certConfirmPay() {
  if (!certOrder.value) return
  busy.value = true; errText.value = ''
  try {
    await payManualConfirm(certOrder.value.order_no, certOrder.value.checkout?.extra?.confirm_token || '')
    certOrder.value = null
    const ap = await creatorApplyGet()
    if (ap) certApp.value = ap.application
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** off/rejected 条目重新提交审核（P3：重新上架必经审核，走 publish 而非直接置 on）。 */
async function republish(li: CreatorListing) {
  busy.value = true; errText.value = ''
  try {
    await creatorPublish(
      li.agent_slug, li.price_tokens, li.name, li.description,
      (li.kind === 'skill' ? 'skill' : 'agent'),
    )
    pubData.value = await creatorListings()
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** 上架/更新价格。 */
async function publish() {
  if (!pubForm.agent_slug) return
  busy.value = true; errText.value = ''
  try {
    await creatorPublish(
      pubForm.agent_slug, Math.max(0, Math.trunc(Number(pubForm.price) || 0)),
      '', '', pubForm.kind,
    )
    pubForm.agent_slug = ''; pubForm.price = ''
    pubData.value = await creatorListings()
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** 上/下架自己的 listing。 */
async function setListing(id: number, status: 'on' | 'off') {
  busy.value = true; errText.value = ''
  try {
    await creatorSetStatus(id, status)
    pubData.value = await creatorListings()
  } catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}

/** @carol:xx → carol（收益明细里买家短显示）。 */
function shortUser(uid: string): string {
  const m = /^@([^:]+):/.exec(uid || '')
  return m ? m[1] : (uid || '')
}

/** 移除一条「已获取」——只是不再优先派单/收藏,不影响资源本身的使用权限。 */
async function removeAcquired(it: AcquiredItem) {
  errText.value = ''
  const err = await setMarketItemAcquired(it.kind, it.slug, false)
  if (err) { errText.value = err; return }
  acquired.value = acquired.value.filter((x) => !(x.kind === it.kind && x.slug === it.slug))
}

/** 「去商城逛逛」:交给父级(LiveView)接线——关工坊、带「返回工坊」回调打开商城
 *  (负责人报:跳过去后回不来;回调由父级闭包重开工坊)。 */
function goMarket() { emit('market') }
watch(() => props.visible, (v) => { if (v) { editing.value = false; load() } })

function newAgent() { Object.assign(agForm, { slug: '', name: '', description: '', system_prompt: '', model: '', workflow_slugs: [], enabled: true, _edit: false }); editing.value = true; errText.value = '' }

// 结构化人设模板(与后台建智能体同一套五要素骨架)：引导用户写出更专业的自建智能体人设。
const PERSONA_TEMPLATE = `【角色定位】你是……（一句话说清身份与核心职责）
【擅长】
- ……（列 3~5 项具体能力，越具体越好）
- ……
【工作方式】拿到任务先……，再……，最后……（你的思考与执行步骤）
【输出要求】……（输出的格式、结构，必须包含什么；举例更好）
【注意事项】……（红线/禁忌，如：不编造数据、信息不足先追问）`

function applyPersonaTemplate() {
  if (agForm.system_prompt.trim()
      && !confirm('人设框已有内容，套用模板会替换掉它，确定吗？')) return
  agForm.system_prompt = PERSONA_TEMPLATE
}
function editAgent(a: MyAgent) { Object.assign(agForm, { ...a, model: a.model || '', workflow_slugs: [...(a.workflow_slugs || [])], _edit: true }); editing.value = true; errText.value = '' }
async function saveAgent() {
  busy.value = true; errText.value = ''
  try { await myAgentSave({ ...agForm }); editing.value = false; await load() }
  catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}
async function delAgent(slug: string) {
  errText.value = ''
  try { await myAgentDelete(slug); await load() } catch (e: any) { errText.value = e?.message || String(e) }
}
function newSkill() { Object.assign(skForm, { slug: '', name: '', description: '', instructions: '', enabled: true, _edit: false }); editing.value = true; errText.value = '' }
function editSkill(s: MySkill) { Object.assign(skForm, { ...s, _edit: true }); editing.value = true; errText.value = '' }
async function saveSkill() {
  busy.value = true; errText.value = ''
  try { await mySkillSave({ ...skForm }); editing.value = false; await load() }
  catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}
async function delSkill(slug: string) {
  errText.value = ''
  try { await mySkillDelete(slug); await load() } catch (e: any) { errText.value = e?.message || String(e) }
}
</script>

<style scoped>
.ms-slug { font-size: 11px; color: var(--text-3); background: var(--bg-hover); border-radius: 4px; padding: 1px 5px; margin-left: 6px; }
/* 「已获取」行的资源类型小徽章(颜色跟商城分类一致) */
.ms-kind { font-size: 10px; color: #fff; padding: 1px 7px; border-radius: 999px; margin-right: 4px; font-weight: 600; }
.ms-form { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-soft); }
.ms-ta { resize: vertical; font-family: inherit; }
/* 人设编辑器：更大、等宽，写结构化人设更顺手 */
.ms-persona-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ms-persona-label { font-size: 12px; color: var(--text-2, var(--text)); }
.ms-persona { min-height: 220px; font-family: var(--mono, ui-monospace, "SF Mono", Menlo, monospace); font-size: 13px; line-height: 1.6; tab-size: 2; }
.ms-src { background: rgba(80, 130, 220, .14); color: #3a63a8; cursor: help; }
.ms-import-mask {
  position: absolute; inset: 0; z-index: 5;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, .28);
}
.ms-import {
  display: flex; flex-direction: column; gap: 10px;
  width: min(560px, 92%); max-height: 86%; overflow-y: auto;
  padding: 16px; border-radius: 12px;
  background: var(--panel, #fff); box-shadow: 0 18px 50px rgba(0, 0, 0, .18);
}
.ms-import-h { display: flex; align-items: center; justify-content: space-between; }
.ms-import-sum { display: flex; flex-direction: column; gap: 4px; }
.ms-import-notes {
  margin: 0; padding: 10px 12px 10px 26px;
  border-radius: 8px; background: var(--warn-bg, rgba(240, 170, 60, .12));
  font-size: 12px; line-height: 1.6;
}
.ms-import-body {
  max-height: 260px; overflow: auto; margin: 0;
  padding: 10px 12px; border-radius: 8px;
  background: var(--code-bg, rgba(0, 0, 0, .04));
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}
.ms-import-err { margin: 0; font-size: 12px; color: var(--danger, #c0392b); }
.ms-wf {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--line, rgba(0,0,0,.08));
  border-radius: 10px;
}
.ms-wf-slug {
  margin-left: 6px;
  opacity: .68;
  font-size: 11px;
}
.ms-hint { font-size: 12px; color: var(--text-3, var(--text-2)); line-height: 1.5; }
.ms-check { font-size: 13px; color: var(--text-2); display: inline-flex; gap: 6px; align-items: center; }
.ms-actions { display: flex; justify-content: flex-end; gap: 8px; }
.cam-mini { border: 1px solid var(--border); background: var(--bg-panel); border-radius: 7px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.cam-mini:hover { background: var(--bg-hover); }
/* —— 上架·收益（创作者商城）—— */
.ms-earn-sum { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.ms-earn-num { font-size: 24px; font-weight: 800; color: var(--accent, #c96442); }
.ms-earn-num span { font-size: 12px; font-weight: 400; color: var(--text-3); margin-left: 6px; }
.ms-earn-sub { font-size: 12px; color: var(--text-2); margin-top: 4px; }
.ms-kind-pick { display: flex; gap: 16px; font-size: 13px; color: var(--text-2); }
.ms-kind-pick label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.ms-cert-status { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin: 8px 0; font-size: 13px; line-height: 1.6; }
.ms-cert-status.rejected { background: #fdf3f3; border-color: #e8c9c9; color: #8a3b3b; }
.ms-earn-row { display: flex; align-items: baseline; gap: 8px; padding: 6px 2px; border-bottom: 1px dashed var(--border); font-size: 12.5px; }
.ms-earn-what { flex: 1; color: var(--text); }
.ms-earn-net { font-weight: 700; color: #2c9a5b; }
.ms-earn-time { color: var(--text-3); font-size: 11px; }
</style>
