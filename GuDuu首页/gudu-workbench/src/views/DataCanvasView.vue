<template>
  <div class="data-studio">
    <header class="studio-topbar">
      <div class="studio-brand">
        <RouterLink :to="{ name: 'website' }" class="studio-back" aria-label="返回官网">←</RouterLink>
        <div ref="productSwitcher" class="studio-product-switcher">
          <button
            class="studio-brand-button"
            :class="{ open: productMenuOpen }"
            aria-haspopup="menu"
            :aria-expanded="productMenuOpen"
            @click.stop="productMenuOpen = !productMenuOpen"
          >
            <svg class="studio-apps-icon" width="16" height="16" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true">
              <circle cx="3" cy="3" r="1.5" /><circle cx="9" cy="3" r="1.5" /><circle cx="15" cy="3" r="1.5" />
              <circle cx="3" cy="9" r="1.5" /><circle cx="9" cy="9" r="1.5" /><circle cx="15" cy="9" r="1.5" />
              <circle cx="3" cy="15" r="1.5" /><circle cx="9" cy="15" r="1.5" /><circle cx="15" cy="15" r="1.5" />
            </svg>
            <img src="/gudu-logo.svg" alt="" />
            <span class="studio-product-name">GuDuu OS <b>Data Intelligence</b></span>
            <span class="studio-brand-chevron" aria-hidden="true">⌄</span>
          </button>

          <div v-if="productMenuOpen" class="studio-product-menu" role="menu" @click.stop>
            <button role="menuitem" @click="goToGuDuuOs">
              <span class="studio-product-icon os">
                <img src="/gudu-logo.svg" alt="" />
              </span>
              <span><b>GuDuu OS</b><small>企业智能协作工作台</small></span>
              <i>打开</i>
            </button>
            <div class="studio-product-separator"></div>
            <button class="active" role="menuitem" @click="productMenuOpen = false">
              <span class="studio-product-icon intelligence">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <ellipse cx="12" cy="5" rx="8" ry="3" />
                  <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
                  <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
                </svg>
              </span>
              <span><b>Data Intelligence</b><small>企业数据智能与语义建模</small></span>
              <svg class="studio-product-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>
            </button>
          </div>
        </div>
      </div>
      <nav class="studio-main-nav" aria-label="数据智能导航">
        <button :class="{ active: studioSection === 'home' }" @click="studioSection = 'home'">首页</button>
        <button :class="{ active: studioSection === 'modeling' }" @click="studioSection = 'modeling'">建模</button>
        <button :class="{ active: studioSection === 'knowledge' }" @click="studioSection = 'knowledge'">知识</button>
        <button :class="{ active: studioSection === 'api' }" @click="studioSection = 'api'">API</button>
      </nav>
      <div class="studio-actions">
        <div class="studio-project">
          <span class="project-status"></span>
          <span>{{ currentProject }}</span>
        </div>
        <button class="agentic-toggle" :class="{ active: agenticMode }" @click="toggleAgenticMode">
          ✦ {{ agenticMode ? '智能体模式' : '交互模式' }}
        </button>
        <span v-if="studioSection !== 'modeling'" class="credits">企业版</span>
        <template v-if="studioSection === 'modeling'">
          <span class="studio-action-divider"></span>
          <button class="studio-ghost studio-icon-btn" :disabled="!canUndo" title="撤销" aria-label="撤销" @click="undo">↩</button>
          <button class="studio-ghost studio-icon-btn" :disabled="!canRedo" title="重做" aria-label="重做" @click="redo">↪</button>
          <button class="studio-ghost" @click="validateModel">校验</button>
          <button class="studio-ghost" @click="saveProject">保存</button>
          <button class="studio-publish" @click="publishToOs">部署模型</button>
        </template>
        <span class="studio-avatar" data-avatar="林">林</span>
      </div>
    </header>

    <div v-if="studioSection === 'modeling'" class="studio-body" :class="{ 'query-closed': !queryPanelOpen }">
      <aside class="asset-panel">
        <div class="model-panel-head">
          <div class="mp-title"><strong>模型</strong><span>（{{ nodes.length }}/10）</span></div>
          <div class="mp-actions">
            <button class="mp-refresh" aria-label="刷新模型" title="刷新模型" @click="refreshModels">⟳</button>
            <button class="mp-new" @click="openCreateDialog('model')">＋ 新的</button>
          </div>
        </div>

        <div class="mtree">
          <section v-for="node in nodes" :key="node.id">
            <div class="mtree-model" :class="{ active: selectedNode === node.id }">
              <button class="mtree-caret" :aria-label="expandedModels.has(node.id) ? '收起字段' : '展开字段'" @click="toggleTree(node.id)">{{ expandedModels.has(node.id) ? '▾' : '▸' }}</button>
              <button class="mtree-name" @click="focusNode(node.id)"><i>⬡</i><b>{{ node.title }}</b></button>
              <button class="asset-row-menu" aria-label="模型操作" @click.stop="openNodeMenu(node.id, $event)">⋮</button>
            </div>
            <div v-if="expandedModels.has(node.id) && node.fields" class="mtree-fields">
              <button v-for="field in node.fields" :key="field.name" class="mtree-field" @click="focusNode(node.id)">
                <i class="ft-badge">{{ typeIcon(field.type) }}</i>
                <span>{{ field.name }}</span>
                <em v-if="field.key" title="主键">⚿</em>
              </button>
            </div>
          </section>
        </div>

        <div class="views-block">
          <div class="mp-title-row">
            <strong>浏览量</strong><span>（{{ savedViews.length }}）</span>
            <button class="mp-new" @click="createView">＋ 新的</button>
          </div>
          <button v-for="view in savedViews" :key="view" class="mtree-field view-item" @click="showToast(`已打开浏览量视图：${view}`)">
            <i class="ft-badge">◫</i><span>{{ view }}</span>
          </button>
          <p v-if="!savedViews.length">暂无浏览量</p>
        </div>

        <div class="side-foot">
          <button title="设置" aria-label="设置" @click="showToast('建模设置即将上线，当前为演示项目')">⚙</button>
          <button title="联系支持" aria-label="联系支持" @click="showToast('已为你接通 GuDuu 支持团队（演示）')">✆</button>
          <button title="文档" aria-label="文档" @click="showToast('建模文档：语义模型 / 关系 / 计算字段')">▤</button>
          <button title="新手引导" aria-label="新手引导" @click="showToast('提示：点击卡片「人际关系 ＋」可在画布上连线建立关系')">✧</button>
        </div>
      </aside>

      <main class="canvas-workspace">
        <div class="canvas-float-bar">
          <div class="model-assistant-wrap">
            <button class="model-assistant" :class="{ open: assistantOpen }" @click.stop="assistantOpen = !assistantOpen">✦ 建模 AI 助手 ⌄</button>
            <div v-if="assistantOpen" class="assistant-menu" @click.stop>
              <button @click="assistantAction('validate')"><b>校验模型口径</b><small>检查模型字段与关系完整性</small></button>
              <button @click="assistantAction('relation')"><b>补全「顾客 → 订单付款」关系</b><small>基于订单号为顾客关联付款数据</small></button>
              <button @click="assistantAction('metric')"><b>生成指标建议</b><small>基于现有字段预填「平均客单价」</small></button>
            </div>
          </div>
          <div class="deploy-pill" :class="{ clean: !dirty }">
            <span>{{ dirty ? '⚠ 检测到未部署的更改' : '✓ 当前模型已部署' }}</span>
            <button v-if="dirty" @click="publishToOs">立即更新模型</button>
          </div>
          <button
            class="query-panel-toggle"
            :class="{ active: queryPanelOpen }"
            :title="queryPanelOpen ? '关闭 AI 问数侧栏' : '打开 AI 问数侧栏'"
            @click="queryPanelOpen = !queryPanelOpen"
          >✦ AI 问数</button>
        </div>

        <div
          ref="canvasEl"
          class="semantic-canvas"
          :class="{ panning: isCanvasPanning }"
          @click.self="selectedNode = ''"
          @pointerdown="startCanvasPan"
          @wheel.prevent="handleCanvasWheel"
        >
          <div class="canvas-grid"></div>
          <div class="canvas-label">
            {{ mode === 'link' ? (linkStart ? `请选择目标模型 · 起点：${nodeById(linkStart)?.title}` : '连线模式 · 请选择起点模型') : '语义关系画布 · 拖动卡片调整布局' }}
          </div>

          <div
            ref="viewportEl"
            class="canvas-viewport"
            :style="{ transform: `translate(${canvasPan.x}px, ${canvasPan.y}px) scale(${zoom / 100})` }"
          >
            <svg class="relation-lines" viewBox="0 0 1500 1330" preserveAspectRatio="none" aria-hidden="true">
              <path
                v-for="connection in connections"
                :key="`${connection.from}-${connection.to}`"
                :class="[connection.kind, { selected: selectedConnection === connection.id }]"
                :d="connectionPath(connection.from, connection.to)"
                @click.stop="selectConnection(connection.id)"
              />
            </svg>

            <article
              v-for="node in nodes"
              :key="node.id"
              class="model-node"
              :class="[node.kind, { selected: selectedNode === node.id, 'link-start': linkStart === node.id }]"
              :style="{ left: `${node.x}px`, top: `${node.y}px` }"
              @pointerdown="startDrag($event, node)"
              @click.stop="selectNode(node.id)"
            >
              <header>
                <i>{{ node.kind === 'entity-node' ? '⬡' : node.icon }}</i>
                <b v-if="node.kind === 'entity-node'" class="ent-title">{{ node.title }}</b>
                <span v-else><b>{{ node.title }}</b><small>{{ node.subtitle }}</small></span>
                <button class="node-menu" aria-label="节点操作" @click.stop="openNodeMenu(node.id, $event)">⋮</button>
              </header>
              <template v-if="node.kind === 'entity-node'">
                <div class="ent-label">列</div>
                <div class="ent-fields">
                  <div v-for="field in node.fields" :key="field.name">
                    <i class="ft-badge">{{ typeIcon(field.type) }}</i>
                    <span>{{ field.name }}</span>
                    <em v-if="field.key" title="主键">⚿</em>
                  </div>
                </div>
                <button class="ent-row" title="添加计算字段" @pointerdown.stop @click.stop="addCalcField(node)"><span>计算场</span><i>＋</i></button>
                <button class="ent-row" title="从此模型连线建立关系" @pointerdown.stop @click.stop="startLinkFrom(node.id)"><span>人际关系</span><i>＋</i></button>
                <div v-if="relationsOf(node.id).length" class="ent-rels">
                  <button v-for="rel in relationsOf(node.id)" :key="rel.id" @pointerdown.stop @click.stop="focusNode(rel.id)">
                    <i>⬡</i><span>{{ rel.title }}</span><em>⋮</em>
                  </button>
                </div>
              </template>
              <div v-else-if="node.fields" class="node-fields">
                <div v-for="field in node.fields" :key="field.name">
                  <span><i :class="{ key: field.key }">{{ field.key ? '◆' : '·' }}</i>{{ field.name }}</span>
                  <small>{{ field.type }}</small>
                </div>
              </div>
              <div v-if="node.kind === 'metric-node'" class="metric-body">
                <small>METRIC</small>
                <strong>{{ node.metricValue || '¥ 12.86M' }}</strong>
                <span>{{ node.expression || 'SUM(order_amount)' }}</span>
              </div>
              <div v-if="node.kind === 'agent-node-canvas'" class="agent-body">
                <span><i></i> 服务已发布</span>
                <b>经营分析分身</b>
                <small>可调用 4 个模型 · 6 个指标</small>
              </div>
              <span class="node-port port-left"></span>
              <span class="node-port port-right"></span>
            </article>
          </div>

          <div class="zoom-rail">
            <button title="放大" aria-label="放大" @click="zoomIn">＋</button>
            <button title="缩小" aria-label="缩小" @click="zoomOut">−</button>
            <button title="适应画布" aria-label="适应画布" @click="resetCanvas">⛶</button>
            <button title="重置布局" aria-label="重置布局" @click="resetLayout">⟳</button>
          </div>

          <div class="canvas-minimap">
            <div class="minimap-view"></div>
            <span v-for="node in nodes" :key="node.id" :style="{ left: `${node.x / 8.4}px`, top: `${node.y / 12.1}px` }"></span>
          </div>
        </div>
      </main>

      <aside v-show="queryPanelOpen" class="query-panel">
        <div class="query-tabs">
          <button :class="{ active: queryTab === 'ask' }" @click="queryTab = 'ask'">AI 问数</button>
          <button :class="{ active: queryTab === 'detail' }" @click="queryTab = 'detail'">模型详情</button>
          <button :class="{ active: queryTab === 'history' }" @click="queryTab = 'history'">历史</button>
          <button class="query-close" aria-label="关闭 AI 问数侧栏" @click="queryPanelOpen = false">×</button>
        </div>

        <template v-if="queryTab === 'ask'">
          <div class="query-intro">
            <span class="query-spark">✦</span>
            <div><strong>向企业数据提问</strong><p>基于当前语义模型生成可信答案</p></div>
          </div>

          <div class="query-box">
            <textarea v-model="question" aria-label="数据问题"></textarea>
            <div>
              <span>客户经营分析 · 6 个指标</span>
              <button :disabled="querying || !question.trim()" @click="runQuery">{{ querying ? '分析中...' : '运行分析 ↵' }}</button>
            </div>
          </div>

          <div class="suggestions">
            <span>试试这样问</span>
            <button v-for="item in suggestions" :key="item" @click="question = item">{{ item }}</button>
          </div>

          <div v-if="hasResult" class="query-result">
            <div class="result-head">
              <span><i></i> 已基于可信模型生成</span>
              <button @click="showSql = !showSql">{{ showSql ? '隐藏 SQL' : '查看 SQL' }}</button>
            </div>
            <div class="result-answer">
              <p>本季度客户增长放缓主要来自<strong>华东区域新客转化率下降</strong>，较上季度降低 8.4%。同时，高价值客户续约周期平均延长 6 天。</p>
              <div class="result-metrics">
                <div><small>客户增长率</small><b>12.6%</b><em>↓ 3.8%</em></div>
                <div><small>新客转化率</small><b>18.2%</b><em>↓ 8.4%</em></div>
                <div><small>平均客单价</small><b>¥ 42.8k</b><em class="up">↑ 5.1%</em></div>
              </div>
              <div class="mini-chart">
                <span v-for="(bar, index) in chartBars" :key="index" :style="{ height: `${bar}%` }"></span>
              </div>
            </div>
            <pre v-if="showSql" class="sql-preview"><code>SELECT region,
  COUNT(DISTINCT customer_id) AS new_customers,
  SUM(order_amount) AS revenue
FROM semantic_orders
WHERE order_date &gt;= DATE_TRUNC('quarter', CURRENT_DATE)
GROUP BY region
ORDER BY revenue DESC;</code></pre>
            <div class="result-actions">
              <button @click="saveAnalysis">保存为分析</button>
              <button class="send-agent" @click="sendToAgent">交给 GuDuu 分身推进</button>
            </div>
          </div>
        </template>

        <template v-else-if="queryTab === 'detail'">
          <div v-if="activeNode" class="node-detail">
            <div class="detail-icon">{{ activeNode?.icon || '◇' }}</div>
            <label><span>名称</span><input v-model="activeNode.title" @focus="pushSnapshot" @change="commitEdit" /></label>
            <label><span>描述</span><input v-model="activeNode.subtitle" @focus="pushSnapshot" @change="commitEdit" /></label>
            <template v-if="activeNode.kind === 'metric-node'">
              <label><span>指标表达式</span><textarea v-model="activeNode.expression" @focus="pushSnapshot" @change="commitEdit"></textarea></label>
              <label><span>展示值</span><input v-model="activeNode.metricValue" @focus="pushSnapshot" @change="commitEdit" /></label>
            </template>
            <div v-if="activeNode.fields" class="field-editor">
              <div class="detail-section-title"><b>字段</b><button @click="addField(activeNode)">＋ 添加</button></div>
              <div v-for="(field, index) in activeNode.fields" :key="`${field.name}-${index}`" class="field-edit-row">
                <input v-model="field.name" @focus="pushSnapshot" @change="commitEdit" />
                <select v-model="field.type" @focus="pushSnapshot" @change="commitEdit">
                  <option>STRING</option><option>DECIMAL</option><option>INTEGER</option><option>DATE</option><option>BOOLEAN</option>
                </select>
                <button @click="removeField(activeNode, index)">×</button>
              </div>
            </div>
            <div class="detail-meta">
              <span>节点 ID</span><code>{{ activeNode.id }}</code>
              <span>入站关系</span><b>{{ connectionCount(activeNode.id, 'in') }}</b>
              <span>出站关系</span><b>{{ connectionCount(activeNode.id, 'out') }}</b>
            </div>
            <button class="detail-delete" @click="deleteSelectedNode">删除此节点</button>
          </div>
          <div v-else-if="activeConnection" class="node-detail">
            <div class="detail-icon">⌁</div>
            <strong>{{ nodeById(activeConnection.from)?.title }} → {{ nodeById(activeConnection.to)?.title }}</strong>
            <label><span>关系类型</span>
              <select v-model="activeConnection.relation" @focus="pushSnapshot" @change="commitEdit">
                <option>一对一</option><option>一对多</option><option>多对一</option>
              </select>
            </label>
            <label><span>连接条件</span><input v-model="activeConnection.condition" @focus="pushSnapshot" @change="commitEdit" /></label>
            <button class="detail-delete" @click="deleteSelectedConnection">删除此关系</button>
          </div>
          <div v-else class="detail-empty">
            <div class="detail-icon">◇</div>
            <strong>选择画布节点</strong>
            <p>在画布中选择模型、指标、关系或服务，查看并编辑详细信息。</p>
          </div>
        </template>

        <template v-else>
          <div class="history-panel">
            <div class="history-heading"><strong>问数与分析历史</strong><button @click="clearHistory">清空</button></div>
            <button v-for="item in queryHistory" :key="item.id" class="history-item" @click="loadHistory(item)">
              <span>✦</span>
              <div><b>{{ item.question }}</b><small>{{ item.time }} · {{ item.saved ? '已保存' : '临时分析' }}</small></div>
            </button>
            <div v-if="!queryHistory.length" class="history-empty">暂无问数历史</div>
          </div>
        </template>
      </aside>
    </div>

    <div v-else-if="studioSection === 'home'" class="saas-page">
      <aside class="saas-sidebar">
        <button class="folder-switcher" :class="{ active: workspaceMenuOpen }" @click="workspaceMenuOpen = !workspaceMenuOpen">
          ♙ {{ currentWorkspace }}⌄
        </button>
        <div v-if="workspaceMenuOpen" class="workspace-menu">
          <button
            v-for="workspace in workspaces"
            :key="workspace"
            :class="{ active: currentWorkspace === workspace }"
            @click="selectWorkspace(workspace)"
          >{{ workspace }}<span>{{ currentWorkspace === workspace ? '✓' : '' }}</span></button>
        </div>
        <section>
          <div><strong>经营仪表板</strong><button @click="createDashboard">＋ 新建</button></div>
          <button v-for="item in dashboards" :key="item.id" class="saas-list-item" @click="activeDashboardId = item.id">
            <i>◔</i><span>{{ item.name }}</span><small>{{ item.widgets }} 个组件</small>
          </button>
        </section>
        <section>
          <div><strong>分析表格</strong><button @click="createSpreadsheet">＋ 新建</button></div>
          <button v-for="item in spreadsheets" :key="item.id" class="saas-list-item" @click="openSpreadsheet(item)">
            <i>▦</i><span>{{ item.name }}</span><small>{{ item.rows }} 行</small>
          </button>
        </section>
        <section>
          <div><strong>问数线程</strong><button @click="startNewThread">＋ 新建</button></div>
          <button v-for="item in queryHistory.slice(0, 4)" :key="item.id" class="saas-list-item" @click="openThread(item)">
            <i>◌</i><span>{{ item.question }}</span><small>{{ item.time }}</small>
          </button>
        </section>
        <div class="connected-apps">
          <strong>已连接企业系统</strong>
          <span v-for="source in enterpriseSources" :key="source.name"><i :class="source.status"></i>{{ source.name }}<small>{{ source.type }}</small></span>
        </div>
      </aside>

      <main class="saas-main">
        <div v-if="activeDashboard" class="dashboard-view">
          <div class="saas-page-heading">
            <div><span>ENTERPRISE DASHBOARD</span><h1>{{ activeDashboard.name }}</h1><p>汇总 SaaS、OA 与企业数据库的实时经营数据。</p></div>
            <div><button @click="studioSection = 'modeling'">编辑数据模型</button><button class="primary" @click="shareDashboard">分享</button></div>
          </div>
          <div class="dashboard-kpis">
            <article v-for="kpi in dashboardKpis" :key="kpi.label"><span>{{ kpi.label }}</span><b>{{ kpi.value }}</b><small :class="{ down: kpi.down }">{{ kpi.change }}</small></article>
          </div>
          <div class="dashboard-grid">
            <article class="dashboard-chart">
              <header><b>收入与回款趋势</b><span>近 12 个月⌄</span></header>
              <div class="large-bar-chart"><i v-for="(bar, index) in chartBars" :key="index" :style="{ height: `${bar}%` }"></i></div>
              <div class="chart-labels"><span v-for="month in months" :key="month">{{ month }}</span></div>
            </article>
            <article class="dashboard-alerts">
              <header><b>AI 经营洞察</b><span>实时</span></header>
              <button v-for="insight in insights" :key="insight.title" @click="question = insight.question; activeDashboardId = ''">
                <i :class="insight.level">✦</i><span><b>{{ insight.title }}</b><small>{{ insight.desc }}</small></span><em>→</em>
              </button>
            </article>
          </div>
        </div>

        <div v-else class="ask-home">
          <div class="ask-hero"><img src="/gudu-logo.svg" alt="" /><h1>了解你的企业数据</h1><p>跨 CRM、OA、ERP 与企业数据库提问</p></div>
          <div class="ask-suggestions">
            <button v-for="suggestion in homeSuggestions" :key="suggestion.question" @click="question = suggestion.question; runHomeQuery()">
              <small>{{ suggestion.type }}</small><b>{{ suggestion.question }}</b><span>{{ suggestion.sources }}</span>
            </button>
          </div>
          <div v-if="querying || homeHasResult" class="home-query-result">
            <span v-if="querying">正在理解业务口径并查询多个系统...</span>
            <template v-else><strong>✦ 已完成跨系统分析</strong><p>华东区域增长放缓主要来自 CRM 新客转化下降，同时 OA 审批周期延长影响了部分项目交付。</p><button @click="studioSection = 'modeling'">查看数据模型与血缘 →</button></template>
          </div>
          <div class="home-query-box">
            <div v-if="dirty" class="undeployed-warning">△ 存在未部署的模型变更，提问时将自动使用最新版本。</div>
            <div><textarea v-model="question" placeholder="向企业数据提问"></textarea><button @click="runHomeQuery">↑</button></div>
            <footer><span>客户经营分析模型</span><button @click="toggleAgenticMode">{{ agenticMode ? '智能体模式' : '交互模式' }}⌄</button></footer>
          </div>
        </div>
      </main>
    </div>

    <div v-else-if="studioSection === 'knowledge'" class="saas-page">
      <aside class="knowledge-sidebar">
        <button :class="{ active: knowledgeTab === 'pairs' }" @click="knowledgeTab = 'pairs'">ƒ 问题-SQL 样例</button>
        <button :class="{ active: knowledgeTab === 'rules' }" @click="knowledgeTab = 'rules'">✣ 业务规则</button>
        <button :class="{ active: knowledgeTab === 'glossary' }" @click="knowledgeTab = 'glossary'">▤ 业务术语</button>
      </aside>
      <main class="knowledge-main">
        <template v-if="knowledgeTab === 'pairs'">
          <div class="saas-page-heading"><div><span>KNOWLEDGE</span><h1>管理问题-SQL 样例</h1><p>通过企业认可的问法和 SQL，持续提升自然语言问数的准确度。</p></div><button class="primary" @click="addSqlPair">＋ 添加样例</button></div>
          <table class="knowledge-table"><thead><tr><th>业务问题</th><th>SQL 摘要</th><th>数据来源</th><th>创建时间</th><th></th></tr></thead>
            <tbody><tr v-for="pair in sqlPairs" :key="pair.id"><td>{{ pair.question }}</td><td><code>{{ pair.sql }}</code></td><td>{{ pair.source }}</td><td>{{ pair.time }}</td><td><button @click="deleteSqlPair(pair.id)">×</button></td></tr></tbody>
          </table>
        </template>
        <template v-else-if="knowledgeTab === 'rules'">
          <div class="saas-page-heading"><div><span>INSTRUCTIONS</span><h1>企业业务规则</h1><p>为 AI 明确指标口径、数据权限与回答原则。</p></div><button class="primary" @click="addBusinessRule">＋ 新建规则</button></div>
          <div class="rule-grid"><article v-for="rule in businessRules" :key="rule.id"><header><i :class="{ enabled: rule.enabled }"></i><b>{{ rule.name }}</b><button :class="{ active: rule.enabled }" @click="rule.enabled = !rule.enabled">{{ rule.enabled ? '启用' : '停用' }}</button></header><p>{{ rule.content }}</p><footer>{{ rule.scope }}</footer></article></div>
        </template>
        <template v-else>
          <div class="saas-page-heading"><div><span>GLOSSARY</span><h1>企业业务术语</h1><p>将数据库字段翻译成全公司一致的业务语言。</p></div><button class="primary" @click="addGlossaryTerm">＋ 添加术语</button></div>
          <div class="glossary-grid"><article v-for="term in glossary" :key="term.id"><b>{{ term.name }}</b><p>{{ term.definition }}</p><span>{{ term.field }}</span></article></div>
        </template>
      </main>
    </div>

    <div v-else class="saas-page">
      <aside class="knowledge-sidebar">
        <button :class="{ active: apiTab === 'overview' }" @click="apiTab = 'overview'">⌁ API 概览</button>
        <button :class="{ active: apiTab === 'keys' }" @click="apiTab = 'keys'">⚿ API 密钥</button>
        <button :class="{ active: apiTab === 'logs' }" @click="apiTab = 'logs'">▤ 调用日志</button>
        <button :class="{ active: apiTab === 'reference' }" @click="apiTab = 'reference'">▣ 接口文档</button>
      </aside>
      <main class="knowledge-main">
        <template v-if="apiTab === 'overview'">
          <div class="saas-page-heading"><div><span>ENTERPRISE API</span><h1>把可信数据能力嵌入企业应用</h1><p>让 GuDuu OS、OA、企业 SaaS 与内部系统调用统一语义模型。</p></div><button class="primary" @click="apiTab = 'keys'">管理密钥</button></div>
          <div class="api-overview-grid"><article><span>本月调用</span><b>12,846</b><small>↑ 18.6%</small></article><article><span>成功率</span><b>99.92%</b><small>稳定</small></article><article><span>平均响应</span><b>428 ms</b><small>↓ 36 ms</small></article></div>
          <div class="endpoint-list"><h2>常用接口</h2><div v-for="endpoint in endpoints" :key="endpoint.path"><code :class="endpoint.method.toLowerCase()">{{ endpoint.method }}</code><b>{{ endpoint.path }}</b><span>{{ endpoint.desc }}</span><button @click="copyEndpoint(endpoint.path)">复制</button></div></div>
        </template>
        <template v-else-if="apiTab === 'keys'">
          <div class="saas-page-heading"><div><span>SECURITY</span><h1>API 密钥</h1><p>管理企业系统访问数据智能服务的身份凭证。</p></div><button class="primary" @click="createApiKey">＋ 创建密钥</button></div>
          <table class="knowledge-table"><thead><tr><th>名称</th><th>密钥</th><th>权限</th><th>最后调用</th><th>状态</th></tr></thead><tbody><tr v-for="key in apiKeys" :key="key.id"><td>{{ key.name }}</td><td><code>{{ key.masked }}</code></td><td>{{ key.scope }}</td><td>{{ key.lastUsed }}</td><td><button class="status-chip" :class="{ active: key.active }" @click="key.active = !key.active">{{ key.active ? '启用' : '停用' }}</button></td></tr></tbody></table>
        </template>
        <template v-else-if="apiTab === 'logs'">
          <div class="saas-page-heading"><div><span>OBSERVABILITY</span><h1>API 调用日志</h1><p>追踪 OA、SaaS 与 GuDuu OS 的每一次数据调用。</p></div><button @click="exportLogs">导出日志</button></div>
          <table class="knowledge-table"><thead><tr><th>时间</th><th>调用方</th><th>接口</th><th>状态</th><th>耗时</th></tr></thead><tbody><tr v-for="log in apiLogs" :key="log.id"><td>{{ log.time }}</td><td>{{ log.caller }}</td><td><code>{{ log.path }}</code></td><td><span class="api-status">{{ log.status }}</span></td><td>{{ log.duration }}</td></tr></tbody></table>
        </template>
        <template v-else>
          <div class="saas-page-heading"><div><span>REFERENCE</span><h1>接口文档</h1><p>标准 REST API，也可通过企业连接器和智能分身直接调用。</p></div></div>
          <div class="api-doc"><aside><button v-for="endpoint in endpoints" :key="endpoint.path" :class="{ active: activeEndpointPath === endpoint.path }" @click="activeEndpointPath = endpoint.path">{{ endpoint.path }}</button></aside><pre><code>{{ activeEndpoint.method }} {{ activeEndpoint.path }}
Authorization: Bearer gd_live_xxx
Content-Type: application/json

{
  "model": "customer_operations",
  "question": "本季度客户增长放缓的原因",
  "response_format": "analysis"
}</code></pre></div>
        </template>
      </main>
    </div>

    <div v-if="toast" class="studio-toast">
      <span>✓</span>
      {{ toast }}
    </div>

    <div v-if="published" class="publish-modal" @click.self="published = false">
      <div>
        <span class="publish-check">✓</span>
        <h2>已发布到 GuDuu OS</h2>
        <p>“客户经营分析”已成为企业智能服务，销售、运营与管理分身现在可以在权限范围内调用它。</p>
        <div class="publish-route">
          <span>企业数据</span><i>→</i><span>语义模型</span><i>→</i><b>GuDuu OS</b>
        </div>
        <button @click="published = false">完成</button>
      </div>
    </div>

    <div v-if="createDialog" class="publish-modal asset-dialog" @click.self="createDialog = ''">
      <form @submit.prevent="createAsset">
        <h2>{{ createDialogTitle }}</h2>
        <p>{{ createDialogDescription }}</p>
        <label><span>名称</span><input v-model="newAsset.name" required autofocus /></label>
        <label v-if="createDialog === 'source'"><span>连接类型</span>
          <select v-model="newAsset.connector"><option>PostgreSQL</option><option>MySQL</option><option>REST API</option><option>SaaS Connector</option></select>
        </label>
        <label v-if="createDialog === 'metric'"><span>计算表达式</span><input v-model="newAsset.expression" placeholder="SUM(order_amount)" required /></label>
        <label><span>说明</span><input v-model="newAsset.description" placeholder="用于企业语义模型" /></label>
        <div class="dialog-actions"><button type="button" @click="createDialog = ''">取消</button><button type="submit">创建并添加到画布</button></div>
      </form>
    </div>

    <div v-if="activeSheet" class="studio-modal sheet-modal" @click.self="activeSheet = null">
      <div>
        <div class="sheet-modal-head">
          <div><span>分析表格</span><h2>{{ activeSheet.name }}</h2></div>
          <button class="sheet-close" aria-label="关闭" @click="activeSheet = null">×</button>
        </div>
        <p class="sheet-modal-sub">共 {{ activeSheet.rows }} 行 · 预览前 {{ sheetPreview(activeSheet.id).rows.length }} 行</p>
        <div class="sheet-table-wrap">
          <table class="sheet-table">
            <thead><tr><th v-for="col in sheetPreview(activeSheet.id).columns" :key="col">{{ col }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, ri) in sheetPreview(activeSheet.id).rows" :key="ri">
                <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="sheet-modal-actions">
          <button @click="activeSheet = null">关闭</button>
          <button class="primary" @click="exportSheet">导出 CSV</button>
        </div>
      </div>
    </div>

    <div v-if="newKeyReveal" class="publish-modal key-modal" @click.self="newKeyReveal = ''">
      <div>
        <span class="publish-check key-check">⚿</span>
        <h2>API 密钥已创建</h2>
        <p>请立即复制并妥善保管，完整密钥仅在本次显示一次。</p>
        <div class="key-reveal-value"><code>{{ newKeyReveal }}</code><button @click="copyNewKey">复制</button></div>
        <button @click="newKeyReveal = ''">完成</button>
      </div>
    </div>

    <div v-if="nodeMenuId" class="node-context-menu" :style="{ left: `${nodeMenuPos.x}px`, top: `${nodeMenuPos.y}px` }">
      <button @click="openDetail(nodeMenuId)">查看详情</button>
      <button @click="duplicateNode(nodeMenuId)">复制模型</button>
      <button @click="startLinkFrom(nodeMenuId)">从此模型连线</button>
      <button class="danger" @click="deleteNode(nodeMenuId)">删除模型</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

interface CanvasNode {
  id: string
  title: string
  subtitle: string
  icon: string
  kind: string
  x: number
  y: number
  fields?: Array<{ name: string; type: string; key?: boolean }>
  expression?: string
  metricValue?: string
}

interface Connection {
  id: string
  from: string
  to: string
  kind: string
  relation: string
  condition: string
}

interface QueryHistoryItem {
  id: number
  question: string
  time: string
  saved: boolean
}

const studioSection = ref<'home' | 'modeling' | 'knowledge' | 'api'>('home')
const route = useRoute()
const router = useRouter()
const productMenuOpen = ref(false)
const productSwitcher = ref<HTMLElement | null>(null)
const currentProject = ref('默认企业项目')
const agenticMode = ref(true)
const queryPanelOpen = ref(false)
const workspaceMenuOpen = ref(false)
const currentWorkspace = ref('企业工作区')
const workspaces = ['企业工作区', '销售经营空间', '供应链数据空间']
const activeDashboardId = ref('')
const activeSheet = ref<{ id: string; name: string; rows: number } | null>(null)
const assistantOpen = ref(false)
const newKeyReveal = ref('')
const homeHasResult = ref(false)
const knowledgeTab = ref<'pairs' | 'rules' | 'glossary'>('pairs')
const apiTab = ref<'overview' | 'keys' | 'logs' | 'reference'>('overview')
const queryTab = ref<'ask' | 'detail' | 'history'>('ask')
const mode = ref<'select' | 'link'>('select')
const zoom = ref(80)
const selectedNode = ref('')
const expandedModels = ref<Set<string>>(new Set(['customer']))
const savedViews = ref<string[]>([])
const selectedConnection = ref('')

function goToGuDuuOs() {
  productMenuOpen.value = false
  router.push({ name: 'dashboard' })
}

function closeProductMenu(event: MouseEvent) {
  if (productMenuOpen.value && productSwitcher.value && !productSwitcher.value.contains(event.target as Node)) {
    productMenuOpen.value = false
  }
  const target = event.target as HTMLElement
  if (nodeMenuId.value && !target.closest('.node-context-menu')) nodeMenuId.value = ''
  if (assistantOpen.value && !target.closest('.model-assistant-wrap')) assistantOpen.value = false
}
const linkStart = ref('')
const question = ref('分析本季度订单增长放缓的原因')
const querying = ref(false)
const hasResult = ref(true)
const showSql = ref(false)
const toast = ref('')
const published = ref(false)
const dirty = ref(true)
const lastSavedAt = ref<Date | null>(null)
const createDialog = ref<'' | 'source' | 'model' | 'metric'>('')
const nodeMenuId = ref('')
const nodeMenuPos = ref({ x: 0, y: 0 })
const newAsset = ref({ name: '', connector: 'PostgreSQL', expression: '', description: '' })
const queryHistory = ref<QueryHistoryItem[]>([
  { id: 1, question: '分析本季度订单增长放缓的原因', time: '今天 10:32', saved: false },
  { id: 2, question: '各州订单量与支付金额有什么变化？', time: '昨天 16:08', saved: true }
])
const canvasEl = ref<HTMLElement | null>(null)
const viewportEl = ref<HTMLElement | null>(null)
const canvasPan = ref({ x: 0, y: 0 })
const isCanvasPanning = ref(false)
let toastTimer: number | undefined
let dragState: { node: CanvasNode; offsetX: number; offsetY: number } | null = null
let canvasPanState: { startX: number; startY: number; originX: number; originY: number; pointerId: number } | null = null
let dragged = false
const historyCursor = ref(-1)
const editHistory: string[] = []
const projectName = '电商经营分析模型'

const dashboards = ref([
  { id: 'executive', name: '集团经营驾驶舱', widgets: 8 },
  { id: 'sales', name: '客户与销售分析', widgets: 6 }
])
const spreadsheets = ref([
  { id: 'pipeline', name: '销售机会明细', rows: 1284 },
  { id: 'approval', name: 'OA 审批效率', rows: 326 }
])
const enterpriseSources = [
  { name: 'Salesforce CRM', type: 'SaaS · 实时', status: 'online' },
  { name: '钉钉 OA', type: 'OA · 5 分钟', status: 'online' },
  { name: '金蝶 ERP', type: 'SaaS · 15 分钟', status: 'online' },
  { name: 'PostgreSQL 数仓', type: '数据库 · 实时', status: 'online' },
  { name: '企业微信', type: 'SaaS · 已授权', status: 'warning' }
]
const dashboardKpis = [
  { label: '本月营业收入', value: '¥ 12.86M', change: '↑ 12.8%', down: false },
  { label: '有效客户数', value: '2,418', change: '↑ 6.2%', down: false },
  { label: 'OA 平均审批时长', value: '18.4h', change: '↓ 3.6h', down: false },
  { label: '项目按期交付率', value: '91.6%', change: '↓ 2.1%', down: true }
]
const months = ['7月', '8月', '9月', '10月', '11月', '12月', '1月', '2月', '3月', '4月', '5月', '6月']
const insights = [
  { title: '华东新客转化下降', desc: 'CRM 转化率较上月下降 8.4%', level: 'warn', question: '分析华东新客转化下降的原因' },
  { title: '审批周期影响交付', desc: 'OA 中 6 个项目等待审批超过 24 小时', level: 'danger', question: '哪些 OA 审批正在影响项目交付？' },
  { title: '高价值客户续约窗口', desc: '12 家客户将在 30 天内进入续约期', level: 'ok', question: '列出未来 30 天需要续约的高价值客户' }
]
const homeSuggestions = [
  { type: '经营分析', question: '本季度客户增长放缓的原因是什么？', sources: 'CRM + ERP + 数仓' },
  { type: '流程洞察', question: '哪些 OA 审批正在影响项目交付？', sources: 'OA + 项目系统' },
  { type: '风险识别', question: '未来 30 天有哪些重点客户续约风险？', sources: 'CRM + 合同库' }
]
const sqlPairs = ref([
  { id: 1, question: '本季度各区域销售收入是多少？', sql: 'SELECT region, SUM(amount)...', source: 'ERP / 订单', time: '今天 09:42' },
  { id: 2, question: '审批超过 24 小时的项目有哪些？', sql: 'SELECT project_id FROM oa_tasks...', source: '钉钉 OA', time: '昨天 16:20' }
])
const businessRules = ref([
  { id: 1, name: '营业收入统一口径', content: '营业收入仅统计已确认且未退款的订单，不包含税费。', scope: '全局 · 财务指标', enabled: true },
  { id: 2, name: '客户隐私保护', content: '普通员工查询客户时隐藏手机号、邮箱和证件信息。', scope: 'CRM · 权限规则', enabled: true },
  { id: 3, name: 'OA 审批超时标准', content: '审批停留超过 24 小时定义为超时，节假日不计入。', scope: 'OA · 流程规则', enabled: true }
])
const glossary = ref([
  { id: 1, name: '高价值客户', definition: '过去 12 个月累计收入超过 50 万元的客户。', field: 'customer_ltv' },
  { id: 2, name: '有效商机', definition: '已完成需求确认且预计成交时间在 90 天内的商机。', field: 'qualified_opportunity' },
  { id: 3, name: '项目交付率', definition: '按计划完成里程碑的项目数占全部到期项目数的比例。', field: 'delivery_rate' }
])
const endpoints = [
  { method: 'POST', path: '/v1/query', desc: '自然语言查询企业数据' },
  { method: 'GET', path: '/v1/models', desc: '获取可用语义模型' },
  { method: 'POST', path: '/v1/agent/context', desc: '为 GuDuu 分身提供业务上下文' }
]
const activeEndpointPath = ref(endpoints[0].path)
const apiKeys = ref([
  { id: 1, name: 'GuDuu OS 生产环境', masked: 'gd_live_••••••8K2P', scope: '查询 + Agent', lastUsed: '2 分钟前', active: true },
  { id: 2, name: 'OA 流程助手', masked: 'gd_live_••••••4M7Q', scope: '只读查询', lastUsed: '1 小时前', active: true }
])
const apiLogs = [
  { id: 1, time: '10:42:18', caller: 'GuDuu 销售分身', path: '/v1/query', status: '200', duration: '382 ms' },
  { id: 2, time: '10:38:02', caller: '钉钉 OA 助手', path: '/v1/agent/context', status: '200', duration: '516 ms' },
  { id: 3, time: '10:31:44', caller: '管理驾驶舱', path: '/v1/models', status: '200', duration: '128 ms' }
]
const activeDashboard = computed(() => dashboards.value.find(item => item.id === activeDashboardId.value))
const activeEndpoint = computed(() => endpoints.find(endpoint => endpoint.path === activeEndpointPath.value) || endpoints[0])

const DEFAULT_POSITIONS: Record<string, { x: number; y: number }> = {
  customer: { x: 40, y: 120 },
  orderItems: { x: 360, y: 40 },
  orders: { x: 670, y: 40 },
  payments: { x: 980, y: 40 },
  products: { x: 360, y: 540 },
  reviews: { x: 670, y: 560 },
  geo: { x: 980, y: 540 },
  sellers: { x: 1265, y: 540 },
  categoryI18n: { x: 360, y: 1020 }
}

const nodes = ref<CanvasNode[]>([
  {
    id: 'customer',
    title: '顾客',
    subtitle: '语义模型 · 顾客主数据',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.customer.x,
    y: DEFAULT_POSITIONS.customer.y,
    fields: [
      { name: '客户城市', type: 'STRING' },
      { name: '客户ID', type: 'STRING', key: true },
      { name: '客户状态', type: 'STRING' },
      { name: '客户唯一标识符', type: 'STRING' },
      { name: '客户邮政编码前缀', type: 'STRING' }
    ]
  },
  {
    id: 'orderItems',
    title: '订单项',
    subtitle: '语义模型 · 订单明细行',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.orderItems.x,
    y: DEFAULT_POSITIONS.orderItems.y,
    fields: [
      { name: '运费价值', type: 'DECIMAL' },
      { name: '订单号', type: 'STRING' },
      { name: '订单项 ID', type: 'INTEGER', key: true },
      { name: '价格', type: 'DECIMAL' },
      { name: '产品 ID', type: 'STRING' },
      { name: '卖家ID', type: 'STRING' },
      { name: '发货限制日期', type: 'DATE' }
    ]
  },
  {
    id: 'orders',
    title: '订单',
    subtitle: '语义模型 · 订单主表',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.orders.x,
    y: DEFAULT_POSITIONS.orders.y,
    fields: [
      { name: '客户ID', type: 'STRING' },
      { name: '订单已获批准', type: 'DATE' },
      { name: '订单已送达承运商日期', type: 'DATE' },
      { name: '订单已送达客户日期', type: 'DATE' },
      { name: '订单预计送达日期', type: 'DATE' },
      { name: '订单号', type: 'STRING', key: true },
      { name: '订单购买时间戳', type: 'DATE' },
      { name: '订单状态', type: 'STRING' }
    ]
  },
  {
    id: 'payments',
    title: '订单付款',
    subtitle: '语义模型 · 支付流水',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.payments.x,
    y: DEFAULT_POSITIONS.payments.y,
    fields: [
      { name: '订单号', type: 'STRING', key: true },
      { name: '分期付款', type: 'INTEGER' },
      { name: '付款顺序号', type: 'INTEGER' },
      { name: '付款方式', type: 'STRING' },
      { name: '支付金额', type: 'DECIMAL' }
    ]
  },
  {
    id: 'products',
    title: '产品',
    subtitle: '语义模型 · 产品主数据',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.products.x,
    y: DEFAULT_POSITIONS.products.y,
    fields: [
      { name: '产品类别名称', type: 'STRING' },
      { name: '产品描述长度', type: 'INTEGER' },
      { name: '产品高度（厘米）', type: 'DECIMAL' },
      { name: '产品 ID', type: 'STRING', key: true },
      { name: '产品长度（厘米）', type: 'DECIMAL' },
      { name: '产品名称长度', type: 'INTEGER' },
      { name: '产品照片数量', type: 'INTEGER' },
      { name: '产品重量（克）', type: 'DECIMAL' },
      { name: '产品宽度（厘米）', type: 'DECIMAL' }
    ]
  },
  {
    id: 'reviews',
    title: '订单审核',
    subtitle: '语义模型 · 订单评价',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.reviews.x,
    y: DEFAULT_POSITIONS.reviews.y,
    fields: [
      { name: '订单号', type: 'STRING' },
      { name: '评论答案时间戳', type: 'DATE' },
      { name: '评论留言', type: 'STRING' },
      { name: '评论标题', type: 'STRING' },
      { name: '评论创建日期', type: 'DATE' },
      { name: '评论 ID', type: 'STRING', key: true },
      { name: '评分', type: 'INTEGER' }
    ]
  },
  {
    id: 'geo',
    title: '地理位置',
    subtitle: '语义模型 · 地理维度',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.geo.x,
    y: DEFAULT_POSITIONS.geo.y,
    fields: [
      { name: '地理位置城市', type: 'STRING' },
      { name: '地理位置纬度', type: 'DECIMAL' },
      { name: '地理位置经度', type: 'DECIMAL' },
      { name: '地理位置状态', type: 'STRING' },
      { name: '地理位置邮政编码前缀', type: 'STRING' }
    ]
  },
  {
    id: 'sellers',
    title: '卖家',
    subtitle: '语义模型 · 卖家主数据',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.sellers.x,
    y: DEFAULT_POSITIONS.sellers.y,
    fields: [
      { name: '卖家城市', type: 'STRING' },
      { name: '卖家ID', type: 'STRING', key: true },
      { name: '卖方州', type: 'STRING' },
      { name: '卖家邮政编码前缀', type: 'STRING' }
    ]
  },
  {
    id: 'categoryI18n',
    title: '产品类别名称翻译',
    subtitle: '语义模型 · 类别多语言',
    icon: '⬡',
    kind: 'entity-node',
    x: DEFAULT_POSITIONS.categoryI18n.x,
    y: DEFAULT_POSITIONS.categoryI18n.y,
    fields: [
      { name: '产品类别名称（葡萄牙语）', type: 'STRING' },
      { name: '产品类别名称（英文）', type: 'STRING' }
    ]
  }
])

interface MetricAsset {
  id: string
  nodeId: string
  name: string
  expression: string
  format: string
}

const metrics = ref<MetricAsset[]>([])

const suggestions = [
  '各州订单量与支付金额有什么变化？',
  '哪些产品类别的差评率最高？',
  '生成本周订单经营简报'
]

const chartBars = [42, 58, 53, 72, 66, 81, 76, 68, 62, 57, 51, 47]
const connections = ref<Connection[]>([
  { id: 'c1', from: 'customer', to: 'orders', kind: 'line-model', relation: '一对多', condition: '客户ID = 客户ID' },
  { id: 'c2', from: 'customer', to: 'geo', kind: 'line-model', relation: '多对一', condition: '客户邮政编码前缀 = 地理位置邮政编码前缀' },
  { id: 'c3', from: 'orderItems', to: 'orders', kind: 'line-model', relation: '多对一', condition: '订单号 = 订单号' },
  { id: 'c4', from: 'orderItems', to: 'products', kind: 'line-model', relation: '多对一', condition: '产品 ID = 产品 ID' },
  { id: 'c5', from: 'orderItems', to: 'sellers', kind: 'line-model', relation: '多对一', condition: '卖家ID = 卖家ID' },
  { id: 'c6', from: 'orders', to: 'reviews', kind: 'line-model', relation: '一对多', condition: '订单号 = 订单号' },
  { id: 'c7', from: 'orders', to: 'payments', kind: 'line-model', relation: '一对多', condition: '订单号 = 订单号' },
  { id: 'c8', from: 'sellers', to: 'geo', kind: 'line-model', relation: '多对一', condition: '卖家邮政编码前缀 = 地理位置邮政编码前缀' },
  { id: 'c9', from: 'products', to: 'categoryI18n', kind: 'line-model', relation: '多对一', condition: '产品类别名称 = 产品类别名称（葡萄牙语）' }
])

const activeNode = computed(() => nodes.value.find(node => node.id === selectedNode.value))
const activeConnection = computed(() => connections.value.find(connection => connection.id === selectedConnection.value))
const canUndo = computed(() => historyCursor.value > 0)
const canRedo = computed(() => historyCursor.value >= 0 && historyCursor.value < editHistory.length - 1)
const createDialogTitle = computed(() => createDialog.value === 'source' ? '连接企业数据源' : createDialog.value === 'model' ? '创建语义模型' : '创建业务指标')
const createDialogDescription = computed(() => createDialog.value === 'source' ? '创建一个演示连接，并将数据表添加到语义画布。' : createDialog.value === 'model' ? '定义企业可理解的业务实体、字段与关系。' : '创建具有统一口径、可供 Agent 调用的可信指标。')

function nodeById(id: string) {
  return nodes.value.find(node => node.id === id)
}

function typeIcon(type: string) {
  switch (type) {
    case 'STRING': return 'A-Z'
    case 'DECIMAL':
    case 'INTEGER': return '123'
    case 'DATE': return '📅'
    case 'BOOLEAN': return '0/1'
    case 'CALC': return 'ƒ'
    case 'TABLE': return '▦'
    default: return '·'
  }
}

function relationsOf(id: string) {
  const related: CanvasNode[] = []
  connections.value.forEach(connection => {
    const otherId = connection.from === id ? connection.to : connection.to === id ? connection.from : ''
    if (!otherId) return
    const other = nodeById(otherId)
    if (other && !related.some(node => node.id === other.id)) related.push(other)
  })
  return related
}

function cardHeight(node: CanvasNode) {
  if (node.kind === 'metric-node') return 150
  if (node.kind === 'agent-node-canvas') return 160
  const fieldCount = node.fields?.length || 0
  const relCount = relationsOf(node.id).length
  return 34 + 22 + fieldCount * 26 + 60 + (relCount ? relCount * 26 + 10 : 0)
}

function toggleTree(id: string) {
  if (expandedModels.value.has(id)) expandedModels.value.delete(id)
  else expandedModels.value.add(id)
}

function openDetail(id: string) {
  nodeMenuId.value = ''
  focusNode(id)
  queryPanelOpen.value = true
}

function refreshModels() {
  showToast(`模型元数据已刷新 · ${nodes.value.length}/10`)
}

function createView() {
  savedViews.value.push(`订单经营视图 ${savedViews.value.length + 1}`)
  showToast('浏览量视图已创建')
}

function addCalcField(node: CanvasNode) {
  pushSnapshot()
  node.fields ||= []
  node.fields.push({ name: `计算字段_${node.fields.filter(field => field.type === 'CALC').length + 1}`, type: 'CALC' })
  dirty.value = true
  replaceCurrentSnapshot()
  showToast(`已为「${node.title}」添加计算字段，可在右侧详情中编辑`)
}

function resetLayout() {
  pushSnapshot()
  nodes.value.forEach(node => {
    const position = DEFAULT_POSITIONS[node.id]
    if (position) {
      node.x = position.x
      node.y = position.y
    }
  })
  zoom.value = 80
  canvasPan.value = { x: 0, y: 0 }
  replaceCurrentSnapshot()
  showToast('画布布局已重置为默认排列')
}

function selectNode(id: string) {
  nodeMenuId.value = ''
  if (mode.value === 'link') {
    if (!linkStart.value) {
      linkStart.value = id
      selectedNode.value = id
      return
    }
    if (linkStart.value === id) {
      linkStart.value = ''
      return
    }
    createConnection(linkStart.value, id)
    return
  }
  selectedNode.value = id
  selectedConnection.value = ''
  queryTab.value = 'detail'
}

function focusNode(id: string) {
  selectedNode.value = id
  selectedConnection.value = ''
  queryTab.value = 'detail'
}

function selectConnection(id: string) {
  selectedConnection.value = id
  selectedNode.value = ''
  queryTab.value = 'detail'
}

function setMode(nextMode: 'select' | 'link') {
  mode.value = nextMode
  linkStart.value = ''
  showToast(nextMode === 'link' ? '连线模式：依次选择起点和目标节点' : '已切换到选择模式')
}

function toggleAgenticMode() {
  agenticMode.value = !agenticMode.value
  showToast(agenticMode.value ? '智能体模式已开启，将主动规划分析步骤' : '已切换为交互模式')
}

function zoomIn() {
  zoom.value = Math.min(130, zoom.value + 10)
}

function zoomOut() {
  zoom.value = Math.max(50, zoom.value - 10)
}

function resetCanvas() {
  zoom.value = 80
  canvasPan.value = { x: 0, y: 0 }
  showToast('画布已适应当前窗口')
}

function startCanvasPan(event: PointerEvent) {
  const target = event.target as HTMLElement
  if (mode.value !== 'select' || target.closest('.model-node, .canvas-float-bar, .zoom-rail, .canvas-label, .canvas-minimap')) return
  const canvas = event.currentTarget as HTMLElement
  canvas.setPointerCapture(event.pointerId)
  canvasPanState = {
    startX: event.clientX,
    startY: event.clientY,
    originX: canvasPan.value.x,
    originY: canvasPan.value.y,
    pointerId: event.pointerId
  }
  isCanvasPanning.value = true
  selectedNode.value = ''
  selectedConnection.value = ''
}

function handleCanvasWheel(event: WheelEvent) {
  if (event.ctrlKey || event.metaKey) {
    const direction = event.deltaY > 0 ? -1 : 1
    zoom.value = Math.max(60, Math.min(130, zoom.value + direction * 5))
    return
  }
  canvasPan.value = {
    x: canvasPan.value.x - event.deltaX,
    y: canvasPan.value.y - event.deltaY
  }
}

function startDrag(event: PointerEvent, node: CanvasNode) {
  if (mode.value !== 'select') return
  const target = event.currentTarget as HTMLElement
  const viewport = viewportEl.value?.getBoundingClientRect()
  if (!viewport) return
  const scale = zoom.value / 100
  target.setPointerCapture(event.pointerId)
  pushSnapshot()
  dragged = false
  dragState = {
    node,
    offsetX: (event.clientX - viewport.left) / scale - node.x,
    offsetY: (event.clientY - viewport.top) / scale - node.y
  }
}

function moveDrag(event: PointerEvent) {
  if (canvasPanState) {
    canvasPan.value = {
      x: canvasPanState.originX + event.clientX - canvasPanState.startX,
      y: canvasPanState.originY + event.clientY - canvasPanState.startY
    }
    return
  }
  const viewport = viewportEl.value?.getBoundingClientRect()
  if (!dragState || !viewport) return
  const scale = zoom.value / 100
  dragged = true
  dirty.value = true
  dragState.node.x = Math.max(8, Math.min(1278, (event.clientX - viewport.left) / scale - dragState.offsetX))
  dragState.node.y = Math.max(8, Math.min(1240, (event.clientY - viewport.top) / scale - dragState.offsetY))
}

function endDrag() {
  if (dragState && dragged) replaceCurrentSnapshot()
  dragState = null
  canvasPanState = null
  isCanvasPanning.value = false
  dragged = false
}

const CARD_W = 222

function connectionPath(fromId: string, toId: string) {
  const from = nodes.value.find(node => node.id === fromId)
  const to = nodes.value.find(node => node.id === toId)
  if (!from || !to) return ''
  const fromY = from.y + 16
  const toY = to.y + 16
  if (to.x >= from.x + CARD_W + 24) {
    const startX = from.x + CARD_W
    const midX = (startX + to.x) / 2
    return `M${startX} ${fromY} L${midX} ${fromY} L${midX} ${toY} L${to.x} ${toY}`
  }
  if (from.x >= to.x + CARD_W + 24) {
    const endX = to.x + CARD_W
    const midX = (from.x + endX) / 2
    return `M${from.x} ${fromY} L${midX} ${fromY} L${midX} ${toY} L${endX} ${toY}`
  }
  const fromCenter = from.x + CARD_W / 2
  const toCenter = to.x + CARD_W / 2
  if (to.y >= from.y) {
    const startY = from.y + cardHeight(from)
    const midY = (startY + to.y) / 2
    return `M${fromCenter} ${startY} L${fromCenter} ${midY} L${toCenter} ${midY} L${toCenter} ${to.y}`
  }
  const endY = to.y + cardHeight(to)
  const midY = (from.y + endY) / 2
  return `M${fromCenter} ${from.y} L${fromCenter} ${midY} L${toCenter} ${midY} L${toCenter} ${endY}`
}

function runQuery() {
  if (querying.value) return
  querying.value = true
  hasResult.value = false
  window.setTimeout(() => {
    querying.value = false
    hasResult.value = true
    queryHistory.value.unshift({
      id: Date.now(),
      question: question.value.trim(),
      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      saved: false
    })
    persist()
  }, 850)
}

function runHomeQuery() {
  if (!question.value.trim() || querying.value) return
  querying.value = true
  homeHasResult.value = false
  window.setTimeout(() => {
    querying.value = false
    homeHasResult.value = true
    queryHistory.value.unshift({
      id: Date.now(),
      question: question.value.trim(),
      time: '刚刚',
      saved: false
    })
  }, 900)
}

function createDashboard() {
  const id = `dashboard-${Date.now()}`
  dashboards.value.push({ id, name: `新建经营仪表板 ${dashboards.value.length + 1}`, widgets: 0 })
  activeDashboardId.value = id
  showToast('新仪表板已创建')
}

function createSpreadsheet() {
  const id = `sheet-${Date.now()}`
  spreadsheets.value.push({ id, name: `新建分析表格 ${spreadsheets.value.length + 1}`, rows: 0 })
  showToast('分析表格已创建')
}

const sheetPreviews: Record<string, { columns: string[]; rows: string[][] }> = {
  pipeline: {
    columns: ['商机名称', '客户', '阶段', '预计金额', '负责人'],
    rows: [
      ['华东智能制造平台', '远洋集团', '商务谈判', '¥ 1,280,000', '周专员'],
      ['冷链数据中台', '蓝湾食品', '方案确认', '¥ 860,000', '孙助理'],
      ['ERP 升级项目', '金辉贸易', '需求确认', '¥ 540,000', '钱专员'],
      ['客户经营分析订阅', '海纳科技', '已赢单', '¥ 320,000', '周专员'],
      ['供应链可视化', '盛通物流', '初步接触', '¥ 210,000', '赵主管']
    ]
  },
  approval: {
    columns: ['审批单号', '类型', '发起人', '当前节点', '停留时长'],
    rows: [
      ['OA-20260613-014', '采购合同', '钱专员', '财务复核', '26 小时'],
      ['OA-20260612-209', '用印申请', '孙助理', '法务审核', '8 小时'],
      ['OA-20260612-188', '报销单', '周专员', '部门主管', '3 小时'],
      ['OA-20260611-156', '项目立项', '赵主管', '总经理审批', '31 小时'],
      ['OA-20260611-132', '请假申请', '林经理', '已完成', '—']
    ]
  }
}

function sheetPreview(id: string) {
  return sheetPreviews[id] || {
    columns: ['维度', '指标值', '环比', '更新时间'],
    rows: [
      ['示例维度 A', '1,024', '↑ 6.2%', '刚刚'],
      ['示例维度 B', '768', '↓ 1.4%', '刚刚'],
      ['示例维度 C', '512', '↑ 3.8%', '刚刚']
    ]
  }
}

function openSpreadsheet(item: { id: string; name: string; rows: number }) {
  activeSheet.value = item
}

function exportSheet() {
  if (!activeSheet.value) return
  const preview = sheetPreview(activeSheet.value.id)
  const lines = [preview.columns.join(','), ...preview.rows.map(row => row.join(','))]
  downloadFile(`${activeSheet.value.name}.csv`, lines.join('\n'), 'text/csv')
  showToast(`已导出「${activeSheet.value.name}」为 CSV`)
}

function selectWorkspace(workspace: string) {
  currentWorkspace.value = workspace
  workspaceMenuOpen.value = false
  activeDashboardId.value = ''
  showToast(`已切换到${workspace}`)
}

function startNewThread() {
  activeDashboardId.value = ''
  question.value = ''
  homeHasResult.value = false
}

function openThread(item: QueryHistoryItem) {
  activeDashboardId.value = ''
  question.value = item.question
  homeHasResult.value = true
}

function addSqlPair() {
  sqlPairs.value.unshift({
    id: Date.now(),
    question: '新增企业认可问题',
    sql: 'SELECT ... FROM semantic_model',
    source: '待配置',
    time: '刚刚'
  })
  showToast('问题-SQL 样例已添加')
}

function deleteSqlPair(id: number) {
  sqlPairs.value = sqlPairs.value.filter(pair => pair.id !== id)
}

function addBusinessRule() {
  businessRules.value.unshift({
    id: Date.now(),
    name: '新建业务规则',
    content: '请编辑企业指标口径、权限或回答原则。',
    scope: '全局',
    enabled: true
  })
}

function addGlossaryTerm() {
  glossary.value.unshift({
    id: Date.now(),
    name: '新业务术语',
    definition: '请补充企业内部统一定义。',
    field: 'semantic_field'
  })
}

async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall through to legacy path */
  }
  try {
    const helper = document.createElement('textarea')
    helper.value = text
    helper.style.position = 'fixed'
    helper.style.opacity = '0'
    document.body.appendChild(helper)
    helper.select()
    document.execCommand('copy')
    document.body.removeChild(helper)
    return true
  } catch {
    return false
  }
}

function downloadFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type: `${type};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

async function copyEndpoint(path: string) {
  const url = `https://api.guduu.cloud${path}`
  const ok = await copyText(url)
  showToast(ok ? `接口地址已复制：${url}` : '复制失败，请手动复制接口地址')
}

function exportLogs() {
  const header = '时间,调用方,接口,状态,耗时'
  const rows = apiLogs.map(log => `${log.time},${log.caller},${log.path},${log.status},${log.duration}`)
  downloadFile(`guduu-api-logs-${apiLogs.length}.csv`, [header, ...rows].join('\n'), 'text/csv')
  showToast(`已导出 ${apiLogs.length} 条调用日志为 CSV`)
}

async function shareDashboard() {
  const link = `https://os.guduu.cloud/di/dashboard/${activeDashboard.value?.id || 'executive'}`
  const ok = await copyText(link)
  showToast(ok ? '仪表板分享链接已复制，可发送给管理团队' : '生成分享链接失败，请稍后重试')
}

function createApiKey() {
  const suffix = Math.random().toString(36).slice(2, 10).toUpperCase()
  apiKeys.value.unshift({
    id: Date.now(),
    name: `企业应用 ${apiKeys.value.length + 1}`,
    masked: `gd_live_••••••${suffix.slice(-4)}`,
    scope: '只读查询',
    lastUsed: '尚未调用',
    active: true
  })
  newKeyReveal.value = `gd_live_${suffix}${apiKeys.value.length}K`
}

async function copyNewKey() {
  const ok = await copyText(newKeyReveal.value)
  showToast(ok ? 'API 密钥已复制到剪贴板' : '复制失败，请手动复制密钥')
}

function assistantAction(kind: 'validate' | 'relation' | 'metric') {
  assistantOpen.value = false
  if (kind === 'validate') {
    validateModel()
    return
  }
  if (kind === 'relation') {
    const customer = nodes.value.find(node => node.id === 'customer')
    const payments = nodes.value.find(node => node.id === 'payments')
    if (customer && payments && !connections.value.some(c => (c.from === customer.id && c.to === payments.id) || (c.from === payments.id && c.to === customer.id))) {
      createConnection(customer.id, payments.id)
      showToast('建模助手已补充「顾客 → 订单付款」关系')
    } else {
      showToast('建模助手：顾客与订单付款的关系已完整，无需补充')
    }
    return
  }
  createDialog.value = 'metric'
  newAsset.value = { name: '平均客单价', connector: 'PostgreSQL', expression: '支付金额 / 订单数', description: '建模助手建议指标' }
  showToast('建模助手已预填「平均客单价」指标，确认后加入画布')
}

function showToast(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2600)
}

function sendToAgent() {
  showToast('分析已交给经营分析分身，并创建后续任务')
}

function publishToOs() {
  const validation = getValidationIssues()
  if (validation.length) {
    showToast(`发布前需处理：${validation[0]}`)
    return
  }
  saveProject()
  published.value = true
}

function validateModel() {
  const issues = getValidationIssues()
  showToast(issues.length ? `发现 ${issues.length} 项问题：${issues[0]}` : `模型校验通过 · ${nodes.value.length} 个模型 · ${connections.value.length} 条关系`)
}

function getValidationIssues() {
  const issues: string[] = []
  if (!nodes.value.length) issues.push('画布中还没有模型')
  nodes.value.filter(node => node.kind === 'entity-node' && !(node.fields && node.fields.length)).forEach(node => issues.push(`模型“${node.title}”缺少字段`))
  nodes.value.filter(node => node.kind === 'metric-node' && !node.expression?.trim()).forEach(node => issues.push(`指标“${node.title}”缺少表达式`))
  nodes.value.filter(node => !connections.value.some(connection => connection.from === node.id || connection.to === node.id)).forEach(node => issues.push(`模型“${node.title}”尚未建立关系`))
  return issues
}

function createConnection(from: string, to: string) {
  if (connections.value.some(connection => connection.from === from && connection.to === to)) {
    showToast('这两个节点已经存在关系')
    linkStart.value = ''
    return
  }
  pushSnapshot()
  connections.value.push({
    id: `c-${Date.now()}`,
    from,
    to,
    kind: nodeById(from)?.kind === 'source-node' ? 'line-source' : nodeById(to)?.kind === 'agent-node-canvas' ? 'line-metric' : 'line-model',
    relation: '多对一',
    condition: '请配置连接条件'
  })
  dirty.value = true
  linkStart.value = ''
  selectedConnection.value = connections.value.at(-1)?.id || ''
  selectedNode.value = ''
  queryTab.value = 'detail'
  replaceCurrentSnapshot()
  showToast('关系已创建，可在右侧配置连接条件')
}

function deleteSelectedConnection() {
  if (!selectedConnection.value) return
  pushSnapshot()
  connections.value = connections.value.filter(connection => connection.id !== selectedConnection.value)
  selectedConnection.value = ''
  dirty.value = true
  replaceCurrentSnapshot()
  showToast('关系已删除')
}

function deleteSelectedNode() {
  if (selectedNode.value) deleteNode(selectedNode.value)
}

function deleteNode(id: string) {
  const node = nodeById(id)
  if (!node) return
  pushSnapshot()
  nodes.value = nodes.value.filter(item => item.id !== id)
  connections.value = connections.value.filter(connection => connection.from !== id && connection.to !== id)
  metrics.value = metrics.value.filter(metric => metric.nodeId !== id)
  expandedModels.value.delete(id)
  selectedNode.value = ''
  nodeMenuId.value = ''
  dirty.value = true
  replaceCurrentSnapshot()
  showToast(`已删除“${node.title}”及其关系`)
}

function duplicateNode(id: string) {
  const source = nodeById(id)
  if (!source) return
  pushSnapshot()
  const clone = structuredClone(source)
  clone.id = `${source.id}-${Date.now()}`
  clone.title = `${source.title} 副本`
  clone.x += 35
  clone.y += 35
  nodes.value.push(clone)
  selectedNode.value = clone.id
  nodeMenuId.value = ''
  dirty.value = true
  replaceCurrentSnapshot()
  showToast('节点副本已创建')
}

function openNodeMenu(id: string, event?: MouseEvent) {
  if (nodeMenuId.value === id) {
    nodeMenuId.value = ''
    return
  }
  if (event) {
    const menuWidth = 150
    const menuHeight = 132
    nodeMenuPos.value = {
      x: Math.min(event.clientX, window.innerWidth - menuWidth - 12),
      y: Math.min(event.clientY + 6, window.innerHeight - menuHeight - 12)
    }
  }
  nodeMenuId.value = id
  selectedNode.value = id
}

function startLinkFrom(id: string) {
  nodeMenuId.value = ''
  mode.value = 'link'
  linkStart.value = id
  showToast(`已选择起点“${nodeById(id)?.title}”，请选择目标节点`)
}

function connectionCount(id: string, direction: 'in' | 'out') {
  return connections.value.filter(connection => direction === 'in' ? connection.to === id : connection.from === id).length
}

function addField(node: CanvasNode) {
  pushSnapshot()
  node.fields ||= []
  node.fields.push({ name: `new_field_${node.fields.length + 1}`, type: 'STRING' })
  dirty.value = true
  replaceCurrentSnapshot()
}

function removeField(node: CanvasNode, index: number) {
  pushSnapshot()
  node.fields?.splice(index, 1)
  dirty.value = true
  replaceCurrentSnapshot()
}

function commitEdit() {
  dirty.value = true
  replaceCurrentSnapshot()
}

function openCreateDialog(type: 'source' | 'model' | 'metric') {
  createDialog.value = type
  newAsset.value = { name: '', connector: 'PostgreSQL', expression: '', description: '' }
}

function createAsset() {
  const name = newAsset.value.name.trim()
  if (!name) return
  pushSnapshot()
  const id = `${createDialog.value}-${Date.now()}`
  const offset = nodes.value.length * 18
  let node: CanvasNode
  if (createDialog.value === 'source') {
    node = {
      id, title: name, subtitle: `${newAsset.value.connector} · 新连接`, icon: 'DB', kind: 'source-node',
      x: 40 + offset % 120, y: 80 + offset % 380,
      fields: [{ name: 'sample_table', type: 'TABLE' }]
    }
  } else if (createDialog.value === 'model') {
    node = {
      id, title: name, subtitle: newAsset.value.description || '语义模型 · 自定义实体', icon: '⬡', kind: 'entity-node',
      x: 60 + offset % 200, y: 760 + offset % 300,
      fields: [{ name: 'ID', type: 'STRING', key: true }]
    }
    expandedModels.value.add(id)
  } else {
    node = {
      id, title: name, subtitle: newAsset.value.description || '统一业务口径', icon: 'ƒ', kind: 'metric-node',
      x: 640 + offset % 120, y: 180 + offset % 300,
      expression: newAsset.value.expression, metricValue: '待计算'
    }
    metrics.value.push({ id: `asset-${id}`, nodeId: id, name, expression: newAsset.value.expression, format: 'AUTO' })
  }
  nodes.value.push(node)
  selectedNode.value = id
  selectedConnection.value = ''
  queryTab.value = 'detail'
  createDialog.value = ''
  dirty.value = true
  replaceCurrentSnapshot()
  showToast(`“${name}”已添加到画布`)
}

function saveAnalysis() {
  const item = queryHistory.value.find(entry => entry.question === question.value)
  if (item) item.saved = true
  else queryHistory.value.unshift({ id: Date.now(), question: question.value, time: '刚刚', saved: true })
  persist()
  showToast('分析已保存到企业知识库')
}

function loadHistory(item: QueryHistoryItem) {
  question.value = item.question
  hasResult.value = true
  queryTab.value = 'ask'
}

function clearHistory() {
  queryHistory.value = []
  persist()
  showToast('问数历史已清空')
}

function snapshot() {
  return JSON.stringify({
    nodes: nodes.value,
    connections: connections.value,
    metrics: metrics.value
  })
}

function restore(serialized: string) {
  const state = JSON.parse(serialized)
  nodes.value = (state.nodes || []).map((node: CanvasNode) => {
    const migratedNode = node.id === 'agent' && node.x > 550
      ? { ...node, x: 350, y: 570 }
      : node
    return {
      ...migratedNode,
      expression: migratedNode.kind === 'metric-node' ? (migratedNode.expression || 'SUM(order_amount)') : migratedNode.expression,
      metricValue: migratedNode.kind === 'metric-node' ? (migratedNode.metricValue || '¥ 12.86M') : migratedNode.metricValue
    }
  })
  connections.value = (state.connections || []).map((connection: Partial<Connection>, index: number) => ({
    id: connection.id || `migrated-${index}`,
    from: connection.from || '',
    to: connection.to || '',
    kind: connection.kind || 'line-model',
    relation: connection.relation || '多对一',
    condition: connection.condition || '请配置连接条件'
  }))
  metrics.value = (state.metrics || []).map((metric: { id?: string; nodeId?: string; name: string; expression: string; format: string }, index: number) => ({
    ...metric,
    id: metric.id || `migrated-metric-${index}`,
    nodeId: metric.nodeId || 'revenue'
  }))
  selectedNode.value = ''
  selectedConnection.value = ''
}

function pushSnapshot() {
  const current = snapshot()
  if (editHistory[historyCursor.value] === current) return
  editHistory.splice(historyCursor.value + 1)
  editHistory.push(current)
  historyCursor.value = editHistory.length - 1
}

function replaceCurrentSnapshot() {
  const current = snapshot()
  if (historyCursor.value < 0) {
    editHistory.push(current)
    historyCursor.value = 0
  } else {
    editHistory.splice(historyCursor.value + 1)
    editHistory.push(current)
    historyCursor.value = editHistory.length - 1
  }
}

function undo() {
  if (!canUndo.value) return
  historyCursor.value -= 1
  restore(editHistory[historyCursor.value])
  dirty.value = true
  showToast('已撤销上一步操作')
}

function redo() {
  if (!canRedo.value) return
  historyCursor.value += 1
  restore(editHistory[historyCursor.value])
  dirty.value = true
  showToast('已重做操作')
}

function persist() {
  localStorage.setItem('guduu-data-canvas', JSON.stringify({
    project: snapshot(),
    queryHistory: queryHistory.value,
    savedAt: new Date().toISOString()
  }))
}

function saveProject() {
  persist()
  lastSavedAt.value = new Date()
  dirty.value = false
  showToast('项目已保存到本机')
}

function loadPersisted() {
  const raw = localStorage.getItem('guduu-data-canvas')
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (saved.project) restore(saved.project)
    if (saved.queryHistory) queryHistory.value = saved.queryHistory
    if (saved.savedAt) lastSavedAt.value = new Date(saved.savedAt)
  } catch {
    localStorage.removeItem('guduu-data-canvas')
  }
}

function handleShortcut(event: KeyboardEvent) {
  const modifier = event.metaKey || event.ctrlKey
  if (modifier && event.key.toLowerCase() === 's') {
    event.preventDefault()
    saveProject()
  } else if (modifier && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    if (event.shiftKey) redo()
    else undo()
  } else if (event.key === 'Escape') {
    productMenuOpen.value = false
    createDialog.value = ''
    nodeMenuId.value = ''
    linkStart.value = ''
    mode.value = 'select'
  } else if ((event.key === 'Delete' || event.key === 'Backspace') && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement)) {
    if (selectedConnection.value) deleteSelectedConnection()
    else if (selectedNode.value) deleteSelectedNode()
  }
}

onMounted(() => {
  document.title = 'GuDuu Data Intelligence · 企业数据智能画布'
  if (route.query.section === 'modeling') studioSection.value = 'modeling'
  loadPersisted()
  pushSnapshot()
  window.addEventListener('pointermove', moveDrag)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('keydown', handleShortcut)
  document.addEventListener('click', closeProductMenu)
})

onBeforeUnmount(() => {
  if (dirty.value) persist()
  window.removeEventListener('pointermove', moveDrag)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('keydown', handleShortcut)
  document.removeEventListener('click', closeProductMenu)
  if (toastTimer) window.clearTimeout(toastTimer)
})
</script>
