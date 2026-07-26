# GuDuu OS — 待办事宜(Backlog)

> 未完成事项的唯一清单。做完就删行;新欠账随手加。大方向以 CLAUDE.md §4 路线图为准。
> 更新:2026-07-27(大屏成功率/延迟/峰值/地域数据源已补齐;新增「存量实例可升级性」)

## A. 主线大项(路线图欠账)

- [ ] **agency-agents 引入**(负责人定流程:清单归类→分批逐个中文化改造入库)
  - [x] 全量清单+归类:见 docs/agency-agents-import.md(242 个;A 强对口 82/B 可选 68/C 不引入 92)
  - [x] 第一批 A 档 75 个已入库(2026-07-11):中文名+中文备注+浓缩中文人设,走预置库(agency_agents.py),
    后台「智能体→预置智能体库」可见、同 slug 覆盖可编辑;名册上限 50→200+描述截 60 字
  - [x] 第二批 B 档 47 个已入库(2026-07-11):财务5+学术6+医疗1+专项35;总预置 130(8原生+122引入)
  - [ ] 收尾:负责人在后台过目,不要的「智能体」页同 slug 覆盖停用即可;C 档维持不引入
  - [x] 清单 242 条已全部落状态(2026-07-11):入库117/转技能5/否决120,永久留档

- [ ] **模块4 · 真实支付**(最大欠账,现在只有 mock 通道能收"假钱")
  - 2026-07-23 定调:**国内市场,渠道=支付宝+微信,Stripe/PayPal 不做**
  - [x] 业务链路已全通(1.6.0~1.6.3):会员套餐 / token 充值 / 创作者认证费 三类订单共用
    交易骨架(可插拔 PaymentProvider + 幂等回调 + 失败回滚),mock 通道全链路实测通过
  - [ ] **只差 adapter**:AlipayProvider / WechatProvider 的 create_checkout(下单+签名)
    与 parse_callback(回调验签)→ 真钱联调。**前置:负责人支付宝/微信 API 凭据(2026-07-27 到手)**
  - [ ] 支付接通后**顺带接大屏营收面板**:现在恒显示 ¥0 +「支付未接入」,有真实订单后
    接 `nexus_order` 已支付金额(今日收入/本月预估/24h 趋势/环比)——见模块6 大屏缺数据源清单
  - [ ] 对账 / 退款流程
- [ ] **模块6 · OEM 体系**(方案定稿 2026-07-18;全貌见 CLAUDE.md §4 模块6 行 + memory oem-nexus-plan)
  - [x] **P0 发行版**已完成(2026-07-19,干净 VM 实测通过,样板间 oem1.cosmac.cc):
    整栈容器化(distro/ 四容器 compose,Caddy 自动 HTTPS 弃 nginx+certbot)+install.sh+
    bootstrap 引导+doctor.sh+update.sh;主站迁入实例#0 未做(非阻塞,P1 顺带评估)
  - [ ] **P1 母舰+网关+皮肤**(进行中:①fleet ✅ ②LLM 网关 ✅ ④a 大屏接真数据 ✅
    ③实例侧接线 ✅ 2026-07-21 线上实测=cs.guduuos.com 实例#0 心跳上大屏(真兑码/
    心跳/AI 通道预填网关/真管理员令牌修 P0 遗留);
    待续:④b 皮肤系统(实例内 cosmac.brand 换 logo/色)+console 管理页(KEY 签发/充值
    UI,现靠 curl);大屏"模型分布/实时动态/配额"三面板仍演示、P2 真实化;
    ⚠️ **实测状态更正**(2026-07-26 查生产 env,原记录已过时):主站实例的 AI **早已是
    deepseek、不是 echo**,但 `COSMAC_SDK_BASE_URL=https://api.deepseek.com/anthropic`
    = **直连原厂、没走母舰网关**(`COSMAC_NEXUS_URL` 虽已配)。后果:网关的逐请求计量/
    扣钱包/限流对主站**不生效**,大屏的"模型分布/用量"也拿不到主站数据。要么把主站
    SDK_BASE_URL 指向母舰网关(需母舰侧配好 ARK/DeepSeek key),要么明确"实例#0 作为原厂
    自留地不受缰绳"并在大屏上单列——**这是个待你拍板的口径,不是纯技术活**):
    fleet 服务(KEY 签发/兑换 API/实例注册/心跳)+ LLM 网关
    (平台 key 鉴权/逐请求计量/token 钱包扣费/限流)+ console 独立前端基础版(实例列表/详情/
    KEY 管理/手动充值)+ 实例内运行时皮肤(控制室 cosmac.brand + 免登录 GET /cosmac/brand +
    client tenant.ts 运行时化 + 预设主题,logo 只收 png/jpg 禁 SVG)+ 自助下载页(凭 KEY 放行)
  - [ ] **大屏"缺数据源"清单**（2026-07-26 逐面板审计，1.6.9 已把这些从"编的数字"改成诚实的
    0/—，但**数据源本身还得补**）：
    - [ ] **收入**（营收轮播页现恒为 ¥0、标"支付未接入"）：等支付宝/微信接通后，接
      `nexus_order` 已支付金额 → 今日收入/本月预估/24h 收入趋势/环比。**明天随支付一起做**。
    - [x] ~~**成功率 / 延迟 / 峰值 req/min**~~：1.6.10 已接真值——网关逐请求打点（成败都记，
      含上游不可达）+ 分钟桶聚合表 `nexus_request_stat`。无请求时返回 null、前端显示「—」，
      **不落 0%**。
    - [x] ~~**实例区域（底部 Region）**~~：1.6.10 已按已定位实例的地域聚合显示。
    - [ ] **网关健康/探活**：底部「API Gateway」1.6.10 起改按**今日真实成功率**分档
      （≥99% Normal / ≥95% Degraded / 更低 Unstable），比原先"有无在线实例"准，
      但仍**不是主动探活**。要真探活需网关自检端点 + 定时拨测。
  - [ ] **存量实例的「可升级性」**(2026-07-27 负责人提出:已经装出去的 OEM 需要有更新功能)
    - **问题**:`update.sh` 只做 `git pull` + `docker compose build` + `up -d`,**不重新渲染
      已生成的配置文件**(`distro/data/caddy/Caddyfile` 由 install.sh 按 OEM 域名渲染一次,
      之后再不更新)。后果:凡是**配置类修复**,存量实例一律拿不到,只有新装的才有。
    - **已踩实例**(2026-07-27):前端缓存策略修复(commit 1046dd1)——`index.html` 缺
      `Cache-Control` + `try_files` 对 `/assets/*` 也回退,导致浏览器缓存旧 index.html 后
      请求已删除的 chunk 被回退成 200 的 HTML,动态 import **静默失败**(表现为"点了没反应",
      控制台无红字、只有装着旧缓存的浏览器才复现)。模板已修,但**已部署实例需手改**,
      dev-cs 这台是我 ssh 上去手动打的补丁。将来每多一台 OEM,这种手改就多一份。
    - **要做什么**(方案待定,负责人拍板):
      - [ ] `update.sh` 增加**幂等的配置升级**:比对模板与已渲染文件,发现旧写法→备份→升级。
        难点:OEM 可能手改过配置(自定义域名/额外反代),不能盲目覆盖——考虑给模板打版本号
        (如 `# tpl-version: 3`),只在"未被手改过"时自动升,否则打印 diff 让 OEM 自己决定。
      - [ ] **怎么触达存量实例**:实例不会自己跑 update.sh。要么母舰下发升级通知(心跳返回
        里带"有新版本/有必须升级的配置")+ 实例侧提示管理员,要么做成自动更新(风险高、
        需负责人明确授权)。与 P2「网关最低兼容版本强制」是同一个抓手,可一起设计。
      - [ ] 升级失败要能**回滚**:配置备份已有(`.bak.*`),但容器镜像回滚、升级中断的恢复
        路径还没有。上百家规模下,一次坏升级批量打挂的代价很大。
    - **优先级建议**:P1 尾/P2 头。现在只有个位数实例,手改还扛得住;**铺开前必须做掉**,
      否则每个配置类修复都要 ssh 上百台。

  - [ ] **P2 规模化**:数据大屏(实时树状图:母舰→OEM→实例,节点大小=用户数/颜色=健康度 +
    增长面板)+ 联邦生态白名单下发(federation whitelist,只通生态不接公网 Matrix)+
    余额/健康告警 + 网关双活 + 网关最低兼容版本强制(催升级抓手)
  - [ ] **P3 接钱**(2026-07-23 负责人定调:**国内市场,渠道=支付宝+微信,Stripe/PayPal 不做**):
    - [x] 非 API 部分已全落地(c16220e):定价(nexus_setting,超管UI即改即生效)+订单
      (nexus_order,金额单位分)+渠道抽象(alipay 页面跳转/wechat Native 扫码占位,
      env 凭据配齐自动亮)+mock 渠道(NEXUS_PAY_MOCK=1)线上全链路实测通过
      (下单→模拟支付→出码→自动归属→订单表;充值→钱包到账)
    - [ ] 等负责人支付宝/微信 API 凭据(预计 1~2 天)→ 只差两处:AlipayProvider/
      WechatProvider 的 create(下单参数+签名)与 verify_notify(回调验签)→ 真钱联调
  - ~~⚠️ 连锁:模块4 P2 Stripe 优先级被拉高~~(国内定调后 Stripe 缓;会员订阅支付渠道后续同用支付宝/微信评估)
- [ ] **模块5 · 个人主页**(未开工;需要客户端 UI 设计配合)
- [ ] **模块R · 品牌化**(持续:碰到呈现层 Matrix/Synapse 字样顺手改)

- [ ] **主站(正式机)接上真 AI + 接进母舰**（负责人 2026-07-27 给 SSH 后做）
  - 现状：主站 `guduuos.com` = **正式机 8.140.250.163**（从 GitHub 拉代码），其 `.env` 没配 LLM key
    → bot 自动降级 **echo**（设计内的降级，非 bug）。**我一直部署的 `guduu-cn`(218) 是开发机
    = dev-cs.guduuos.com**，两者不会互相同步。
  - 待办①：正式机 `.env` 补上 dev 上验证可用的那套（`COSMAC_LLM_PROVIDER=deepseek` /
    `COSMAC_AGENT_ENGINE=claude_sdk` / `COSMAC_SDK_BASE_URL=https://api.deepseek.com/anthropic` /
    `ARK_BASE_URL=https://api.deepseek.com` / `COSMAC_SDK_MODEL`=`COSMAC_LLM_MODEL`=`deepseek-v4-pro`
    + DeepSeek key 填 `COSMAC_SDK_API_KEY` 与 `ARK_API_KEY`）→ `docker compose up -d bot`
    → 启动日志出现 `模型后端=deepseek` 即成。
  - 待办②：正式机配 `COSMAC_NEXUS_URL` + `COSMAC_OEM_KEY` 并兑码注册，**否则大屏上看不到主节点**
    （地域功能做完后，期望大屏能同时看到「开发节点 + 主节点」两个点）。
  - 前置：**负责人提供正式机 SSH**（我目前只有 guduu-cn / guduu / Guduu-dev 三台，没有正式机）。

## B. 安全

- [ ] **新域名配 Cloudflare Turnstile 人机验证**(负责人实报:新域名下获取验证码的人机验证消失,
      防机器人恶意刷验证码/注册)。**阻塞中**:负责人暂时拿不到公司 Cloudflare 域名解析账号,拿到后再弄。
  - 代码侧透传管道**已修好**(1.5.11:distro compose 补 `COSMAC_TURNSTILE_SITE_KEY`/`COSMAC_TURNSTILE_SECRET`)
  - 待办:Cloudflare→Turnstile 建 Widget,Hostname 加 `dev-cs.guduuos.com`→取 Site Key+Secret
    →填进新服务器 `/opt/cosmac/.env`→`docker compose up -d bot`
  - 验证:`curl https://dev-cs.guduuos.com/cosmac/auth/config` 返回 `"turnstile": true`
  - 注:老站 cosmac.cc 的 key 绑旧域名,新域名不可用,须为新域名重拿一套

- [ ] **auth 阶段3**:短信验证码 + 手机号防多号(要接短信服务商,花钱,上量前不急)
- [ ] 🔴 **作废并重发 GitHub PAT（新增·优先）**:`/opt/nexus/app` 的 git remote URL 里**内嵌明文
  PAT**(`ghp_...`),2026-07-26 排查时被打印进聊天记录 → **该 token 已泄露,必须去 GitHub 立即
  revoke 并换新**;换完把服务器上内嵌它的 remote 一并改掉(`/opt/nexus/app`,以及 `/root/cosmac`
  若同样内嵌)。**更好的做法**:改用 deploy key(只读 SSH key)或 git credential store——
  别把 token 写进 remote URL,那玩意儿任何一句 `git remote -v` 都会原样打出来。
- [ ] **凭据轮换**:COSMAC_ADMIN_TOKEN / REGISTRATION_SHARED_SECRET / SMTP 密码 / AS·HS token / ARK key
  曾在 SSH 截图(systemctl show)中整屏暴露于聊天记录,建议统一换一轮(DEPLOY.md 记新值)
- [ ] 异地登录**放行**场景的提醒邮件(现在只有"挑战"场景发码;放行时不提醒"有新地点登录了")
- [ ] 确认生产 COSMAC_SDK_API_KEY 用的是**重置后**的 DeepSeek key(旧 key 曾贴进聊天)

- [ ] **服务器拉代码不可靠**(2026-07-26 又踩):`guduu-cn` → GitHub 的 fetch 连续 8 次全失败
  (TLS 挂起/超时),1.6.5 部署因此静默没上去。**当时的绕行办法**:本地 `git bundle create` →
  `scp` 到服务器 → `git fetch /tmp/x.bundle main:refs/remotes/origin/main` → reset,完全避开
  GitHub。可考虑固化成一个 `deploy-bundle.sh`,或给服务器配国内 Git 镜像/代理。

## C. 功能补全 / 增强

- [x] **群级模型联动**已完成(2026-07-11):SDK 引擎按"群绑定的智能体模型"选大脑(ClaudeSdkEngine
  加 model_override,群绑定+专班@Agent 两路都走 gctx.model;端点不认的模型自动回退 legacy 原生跑)
- [ ] **接 Claude 做付费权益**:配 Anthropic key 后全局/按群启用(前置:负责人提供 key)
- [ ] ~~**引擎冷启动提速**:每条回复慢 3~8 秒 → 用 ClaudeSDKClient 长连接复用消除~~
  **2026-07-26 生产实测,原前提不成立、方案有安全雷,建议暂缓**(数据见下,别再按老前提开工):
  - 实测(prod 容器, SDK 0.2.126):`connect()` **0.7s** / 首次 query **3.27s** / 同 client 后续 query **1.40s**
    → 可省的固定开销 ≈ **2.6 秒/条**(不是 3~8 秒;"3~8秒"是当初写在 engine.py docstring 里的估计值,从未实测)
  - 🚨 **`query(session_id=...)` 并不隔离上下文**:实测同一 client 上 sessionA 存的暗号,
    sessionB 直接读得到 → **naive 复用 client 服务不同用户 = 跨用户信息泄露**,该路线直接毙
  - 复用/预热还有硬约束:`system_prompt` 只能在 connect 时定,而我们每轮都不同
    (人设/平台RULE/频道RULE/任务RULE/技能/知识库RAG/用户画像)→ 要复用就得把这些从 system
    位挪进 user 轮,**有规则遵守度回归风险**(负责人多次报过"AI 不遵守规则"类 bug,主链路不宜冒险)
  - 若将来仍要做:唯一安全形态=**一客户端只服务一次请求后销毁 + 后台预热下一个**(预热需先发一次
    丢弃的 LLM 调用来吃掉 1.9s 暖机,每条多花约 50~100 token),且必须先解决 system_prompt 静态化
  - **更优替代已做**:✅ **流式输出**已上线(1.6.4,2026-07-26)——边生成边原地更新草稿消息,
    体感提速远超 2.6 秒;`COSMAC_STREAM_REPLY=0` 可一键关
- [ ] **切/混用 Claude 大脑**:配 Anthropic key,全局或按群启用(与群级联动同批)
- [ ] 入驻模板 **P3**:数据看板按模板渲染(P1 后台管理、P2 注册引导已完成)
- [ ] AI双层作用域·增强:全局助理跨频道检索**知识库**(现在能列频道/调聊天记录;各频道绑定的
  知识库还只在频道内检索,全局模式暂不聚合)
- [ ] 社媒数据源 **P2~P4**:采集器(api/crawl 两模式)→ 指标写 cosmac DB → 看板真实取数
  (P1 配置 UI 已完成;看板目前仍是演示数据)

## D. 清理 / 技术债(小,抽空即可)

- [ ] 存储配额**硬管控**附件上传:现为前端软管控(可直调 Matrix API 绕过);要硬拦需 Synapse Module
  (媒体 spam-checker 回调查 cosmac 配额)。上量/发现滥用再做

- [ ] AuthEvent 审计表加 90 天保留期清理(表会一直增长;当前量级无压力)
- [ ] 登录/验码共享 attempt 限频桶按端点分桶(公司/运营商 NAT 出口用户多时会互相误伤;上量再做)

## E. 明确暂缓(有结论,别重复评估)

- Office 附件(doc/pptx/xlsx)在线预览:负责人拍板暂不做(2026-07-11)。现状=点击下载;
  已有 PDF/文本/图片/视频/音频 在线预览覆盖日常场景。将来要做的两条路线已评估:
  ①前端库(docx-preview+SheetJS,轻量但 pptx/老格式不支持) ②自托管 OnlyOffice(全格式,
  需 Docker+约2GB内存)。公网 Office viewer 行不通(拿不到认证媒体)。
- pgvector 向量检索:等知识库规模上来(现在 LIKE 检索够用)
- 工作流 durable 队列/多实例 fencing/精确一次:单实例过度设计(负责人拍板"够用即止")
- 任务编排档4b(workflow 自动回填):决定不做,run_workflow+update_task 手动够用
- ruflo 等第三方 agent 框架:已评估否决,引擎已用官方 Claude Agent SDK
- ECC(affaan-m/ECC):已评估——其**开发者技能**(代码审查/PR/调试)对 GuDuu OS 产品无用、不引入;
  但**借鉴其「技能=结构化方法论清单」形式**做了 9 个面向营销/内容/运营的预置技能库
  (cosmac/ai/preset_skills.py,绑预置 Agent 激活)。后续要加方法论技能沿用此模式,别做全局注入

## F. 市场盲区补缺(2026-07-23 新增;TODO 此前未覆盖的产品级缺口,由负责人排期)

> 来源:与企业版(Mattermost 版)对标梳理时,按「个人版产品的市场标准」盘出的盲区,均为本清单原先没有的条目。
> 优先级建议:真实支付(A 节已有)→ 凭据轮换(B 节已有,立即做)→ 移动端 → GDPR/i18n → 其余。

- [ ] **移动端 App**(最大产品级缺口:个人 IM 没有手机端难以成立;现仅 Web)
  - 三条路线待评估拍板:①fork 成熟 Matrix 客户端(Element X / FluffyChat)换皮+接 /cosmac 端点
    ②企业版 guduu-mobile(RN/鸿蒙)改接 Matrix 协议(工作量大,不推荐先做)
    ③PWA 过渡(最快:可安装到桌面+基础 Web Push,先解决"离开页面即失联")
  - 前置:推送通道(见下条);品牌皮肤可复用模块R成果
- [ ] **推送通知**(APNs/FCM/Web Push + 邮件摘要兜底;现在用户不在页面上就收不到任何消息)
  - Matrix 有标准 Push Gateway(sygnal)可自托管;Web Push 可先行,App 推送随移动端一起做
- [ ] **多语言 i18n**(定位「海外版」而 UI 现为中文,自相矛盾;至少中/英)
  - client 用 vue-i18n;先盘点硬编码文案量再排期;后端 bot 回复文案也要过一遍
- [ ] **GDPR 合规**(海外运营的法律硬要求,现完全没有)
  - 数据导出(账号数据全量打包)、账号注销(Synapse 自带 GDPR erase API + 级联清理 cosmac DB)、
    隐私政策/ToS 页面、Cookie 同意条
- [ ] **E2EE 端到端加密**(Matrix 原生支持而自研客户端未实现;海外隐私敏感用户的核心卖点)
  - 大活:client 需接 olm/megolm(matrix-js-sdk 内置);先出可行性评估,可先只覆盖 1v1 私聊
  - ⚠️ 与主 AI 的边界要先定产品规则:开 E2EE 的房间 bot/appservice 读不到消息,AI 功能如何降级/提示
- [x] ~~**创作者市场**(Agent/技能 上架→定价→分成 的交易闭环)~~ **已完成**(1.6.0~1.6.3,2026-07-26):
  Token 经济(钱包/真实计量/充值)+ 创作者认证(申请→付认证费→审核授资格)+ 上架审核(任何修改都重审)
  + 售卖分成(Agent 按次 / Skill 买断,平台 10%/创作者 90%)+ 收益账本。详见 CLAUDE.md §4 模块4。
  - [ ] 尾巴①:**创作者提现出金**——本期只做账本可见,真实出金待合规评估(大概率走持牌第三方分账/劳务代发)
  - [ ] 尾巴②:充值/认证费目前走 mock 测试通道,等支付宝/微信凭据(同 A 节模块4)接真钱
- [ ] **对标 Claude Cowork：让 AI 能产出可下载的办公文档**（2026-07-26 负责人提出,已调研）
  - Cowork = Anthropic 2026-01 推出的**独立产品**,定位"给非开发者的 Claude Code":本地文件
    自主读写 / 多步任务拆解 / 经 MCP 接 Slack·Drive·Gmail·Notion / **产出带公式的 Excel、
    格式化 Word、PPT**。面向知识工作者。**没有 Cowork 专属 API**——第三方要做类似的,官方
    构件就是 **Agent SDK + MCP**(我们已经在用 Agent SDK)。
  - **能力对照**:多步拆解✅ / 多工具调用✅ / 外部集成✅(工作流连接器,方向同 MCP) /
    多 Agent 协作✅(还比它强,AI 同事有独立身份能在频道各自发言) → **唯一大缺口 = 产出文件**。
    现在 AI 只能"说",给不出一个能下载的交付物;而我们定位"个人创业者 AI 工作台",
    交付不出文件等于少半条腿。
  - **切入点(链很短)**:加 `create_document` 工具(openpyxl/python-docx/python-pptx)→
    生成文件 → 传 Matrix 媒体库 → 当附件发进频道。媒体库/附件预览/存储配额都是现成的。
  - ⚠️ **必须先设计租户隔离**:Cowork 的"本地文件自主读写"在我们这是**服务端沙箱**,
    绝不能让 A 的 AI 读到 B 的文件。动手前先定沙箱边界与路径白名单。
- [ ] **增长机制**(邀请码/推荐奖励/免费额度策略;个人产品冷启动标配,现在没有)
  - 可挂现有配额引擎(quotas):邀请成功双方加额度;注册引导/入驻模板可埋钩子
