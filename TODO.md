# GuDuu OS — 待办事宜(Backlog)

> 未完成事项的唯一清单。做完就删行;新欠账随手加。大方向以 CLAUDE.md §4 路线图为准。
> 更新:2026-07-26(创作者市场已完成划掉;模块4 只差支付宝/微信 adapter)

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
    与 parse_callback(回调验签)→ 真钱联调。**前置:负责人支付宝/微信 API 凭据(预计 2026-07-27 到手)**
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
- [ ] **凭据轮换**:COSMAC_ADMIN_TOKEN / REGISTRATION_SHARED_SECRET / SMTP 密码 / AS·HS token / ARK key
  曾在 SSH 截图(systemctl show)中整屏暴露于聊天记录,建议统一换一轮(DEPLOY.md 记新值)
- [ ] 异地登录**放行**场景的提醒邮件(现在只有"挑战"场景发码;放行时不提醒"有新地点登录了")
- [ ] 确认生产 COSMAC_SDK_API_KEY 用的是**重置后**的 DeepSeek key(旧 key 曾贴进聊天)

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
- [ ] **增长机制**(邀请码/推荐奖励/免费额度策略;个人产品冷启动标配,现在没有)
  - 可挂现有配额引擎(quotas):邀请成功双方加额度;注册引导/入驻模板可埋钩子
