# CosMac OS — 开发日志 (Dev Log)

> 按时间倒序的开发流水：**每次 commit 前**在顶部加一条。
> 记「哪天 / 哪个模块 / 做了什么 / 关键决策与为什么」，不记文件级细节（那是 git log 的活），
> 也**不记敏感信息**（key/口令/线上 IP 进本机已 gitignore 的 `DEPLOY.md`）。
> 长期有用的事实进 memory；这里只是流水账。

---

## 2026-07-04 — 技能库试点(ECC移植第1件)+ 后台按钮竖排错位修复
- 试点: ECC 的 marketing-campaign 技能完成中文译写+本土化(渠道换成公众号/朋友圈/小红书/抖音,
  依赖内联,压至~950字),经 AS token 直写生产控制室 cosmac.skills(安全合并,同slug覆盖)。
  后台技能库已可见/可编辑/可停用;enabled 全局热生效。出处已标注(ECC·MIT)。
- 修后台错位: .adm-btn/.adm-badge/.adm-row-actions 无 nowrap,窄列里两字中文按钮("编辑/停用/删除")
  和"启用"徽章被折成竖排——加 white-space:nowrap+flex-shrink:0+badge inline-block,全后台通用类
  一次治所有页。build过。**部署: 仅前端 dist。**
- 待负责人验证试点效果后,批量移植剩余8件+原创行业件(届时做"代码预置打底"正式架构)。

## 2026-07-04 — 组班链路完善:资源缺口提醒 + 任务RULE保底(双层作用域·第三步)
- 负责人设计补全: 全局助理接单→拆解→组班时,人/AI/技能必须**从库里调取**;库里没有的要**提醒**
  而非静默失效;专班建成后频道主AI必须受**按任务定制的RULE**约束。
- ①资源存在性校验: Toolbox 加 known_agents/known_skills 注入点(bot 注入全局清单);assemble_team
  对 lead/workers/skills 逐个校验——库里没有的从绑定剔除(防写进配置查无此物悄悄失效),并在
  **工具返回+频道开班消息**双处提示缺口("可到管理后台→智能体/技能添加后再补绑")。校验回调
  未注入/失败则跳过(优雅降级)。
- ②任务RULE保底: 模型没给 task_rule 时自动生成基础版(目标+任务节点+审核/归档约束)——专班
  频道绝不"裸奔";返回文案区分"自动生成(可修改)/按你的要求"。
- ③提示词: 全局助理加组班链路规矩(先看名册→拆解→assemble_team 一并带资源与RULE→缺口如实转告);
  assemble_team 描述强化"绝不编造名册外资源"。
- 测试 AssembleTeamGapsTest 3用例(FakeClient 补 invite/set_state/send_card);全量364过+ruff过。
- **部署: 重启 guduu-bot(纯后端)。**

## 2026-07-03 — AI双层作用域·第二步:全局助理的"眼睛"(list_my_rooms+跨频道调取指引)
- 新工具 list_my_rooms: 列出**发起人**所在的频道(名+room_id)。只在全局模式(私聊)可用,频道模式
  自动拒绝并引导;排除AI会话房/私信/控制室(房间类型按建房标记判定,永久缓存 _room_kind_cache);
  只列发起人自己在的房(不暴露TA不在的群)。进 _ALWAYS_ON 防旧配置禁用。
- 全局模式系统提示强化: 明确指引"先 list_my_rooms 再 get_recent_messages(room_id) 调取;用户问
  某频道近况/汇总各频道进展时主动调取,别说看不到"。
- 测试: FakeClient加joined_rooms;两种模式各1用例;runtime_config计数15→16+白名单3处。
  全量361过+ruff过。**部署: 重启 guduu-bot(纯后端)。**
- 未竟(记TODO): 全局模式跨频道**知识库**聚合检索(现在KB仍按房间检索)。

## 2026-07-03 — AI双层作用域·第一步:频道模式隔离墙(全局大脑+频道分身)
- 负责人设计: 主AI一套引擎两种上下文——右侧私聊=全局助理(看所有频道,以本人权限为界);
  频道里@AI=频道分身(同样聪明能拆任务/建专班,但记忆/知识/派单的人只限本频道)。用现有 is_dm 区分。
- 墙一(核心): _check_room_access 模式感知。频道模式(is_dm=False)访问任何别的房间一律拒绝
  (即便用户是那房成员——分身只服务本频道);全局模式(is_dm=True)按发起人成员身份放行跨房。
- 墙二: 能力名册(_list_capabilities_for_tool)真人在频道模式只保留本频道成员(get_members过滤);
  全局模式给全量名册。
- 墙三: _scope_directive 分模式系统提示,告诉AI当前身份/边界(频道分身 vs 全局助理),两模式智能相同。
- 测试 RoomAccessScopeTest 4用例 + 更新旧跨房测试为新语义;全量359过+ruff过。
- **部署: 重启 guduu-bot(纯后端)。** 第二步(全局模式加"跨频道调取"的眼睛:list_my_rooms等)随后做。

## 2026-07-03 — 频道删除:未完成任务软提醒(方案1) + 措辞诚实化
- 现状: deleteChannel 无任何限制,只 leaveAndForget(其实是"你退出",频道仍在、他人不受影响),
  叫"删除"误导。
- 改(方案1软提醒,不硬拦): 删前查本频道未完成任务(room_id匹配且 status!=done),>0 则弹黄色
  提醒条+"仍要退出"二次确认(给知情权,不因一条遗留任务锁死)。后端 /cosmac/tasks 返回加 room_id
  (前端按房间统计用)。措辞"删除频道"→"退出频道",toast 说明"频道本身仍在,其他成员不受影响"。
- 全量355过+ruff+build过。**部署: 前端dist + 重启bot(后端加了room_id字段)。**

## 2026-07-03 — 修:私信区「邀请成员」错位——建成真正的一对一私信(DM)
- 现象: 侧栏"私信"区下的「+邀请成员」按钮,点了却把人邀进了**当前选中频道**(如痞幼粉丝群)。
- 根因: 该按钮绑的是 openMembers(邀请进 memberTarget=当前频道/工作区),放在私信区纯属错位+
  误导;系统里根本没有"和真人开私信"的能力(私信区只硬编码了中枢AI)。
- 修(建成真功能): client.ts createDirectMessage(建/复用一对一DM,cosmac.dm标记,is_direct)+
  listDirectMessages(列我的真人私信)+ listRooms 排除DM(不混进频道列表)。LiveView 私信区渲染DM
  列表(点开在主区聊天,复用openRoom)+ 按钮改"发起私信"弹窗(输用户名→建DM→打开)。
- 与"邀请进频道"彻底分开: 弹窗文案明确"这不是邀请进频道"。纯前端build过。
- **部署: 仅前端 dist。**

## 2026-07-03 — 工作区分享:公开前二次确认 + 私密态引导(防误开泄露全部频道)
- 负责人洞察: 分享工作区链接=对方自动进入本工作区**全部频道**(joinSpaceByLink 会逐个join子频道);
  且公开=无审批。误开即整区泄露,必须有防呆。
- 改: ①私密时分享区不再直接给链接,而是提示"要生成链接需先公开;精确控制请用成员管理逐个邀请";
  ②点"公开"不再立即执行,先弹后果确认(无审批/全部频道/关闭后已入成员不移除三条);确认才真开;
  ③关闭公开是低风险,直接执行。文案从"开放加入"改为"公开分享",私密/公开态说明动态切换。
- 纯前端;build过。**部署: 仅前端 dist。**

## 2026-07-03 — 清理三连:控制室隐藏 + LiveView旧登录死代码删除(含直连Synapse旧路径本体)
- **控制室误删事故**: 负责人把「CosMac 控制室」当普通频道从列表删除(孤儿房放行的副作用暴露了它)。
  房间与配置数据无损(bot仍是成员),已给 AS token 邀请回归命令。**根治**: listRooms 按 canonical
  alias(#cosmac-ctrl)把控制室从频道列表排除——它是配置数据库不是聊天频道,不该被看见。
- **LiveView 旧认证死代码删除**(审查遗留): 删 doLogin/sendCode/doRegister/doResetPassword/
  switchAuthMode 函数块(~93行)+ 8个死refs + 6个死import;**连根拔掉 client.ts 的 login()/
  loginWithEmail() 函数本体**——它们直连Synapse绕过登录收口(限频/审计/异地检测),是被审查点名
  的风险路径。全仓确认零调用后删除。build过。
- 重复「新品发布会专班」群: 负责人已手动删除。TODO.md 三项勾销。
- **部署: 仅前端 dist。**

## 2026-07-03 — 引擎回退告警(欠费/CLI坏不再无声)
- 问题: SDK引擎失败自动回退 legacy 是无声的——DeepSeek 欠费/CLI 坏了没人发现"高级引擎"早停了。
- 修: bot._alert_engine_fallback——回退发生时向控制室发告警(错误摘要+常见原因+排查命令),
  1小时节流防刷屏;告警本身 best-effort 绝不影响用户回复。355测试+ruff过。
- **部署: 重启 guduu-bot(纯后端)。**

## 2026-07-03 — AI引擎·生产部署完成(SDK+DeepSeek 已在线上运行)
- 生产服务器(Ubuntu24.04/py3.12)装齐: Node v22.23.1 + Claude Code CLI 2.1.199(npm -g)+
  claude-agent-sdk(装进 /opt/guduu/bot-venv);drop-in agent-engine.conf 配 COSMAC_AGENT_ENGINE=
  claude_sdk + SDK_BASE_URL(DeepSeek anthropic端点)+ SDK_API_KEY(已轮换的新key)+ SDK_MODEL。
- 线上实测: "建一个叫『引擎测试』的群"→ 6秒完成 create_room,无回退日志 → SDK 引擎实锤生效。
- 观察项: 回复延迟+3~8s(子进程冷启动);内存3.8G偏小,并发多时留意;DeepSeek官方账户余额。
  关闭=删 agent-engine.conf 里 COSMAC_AGENT_ENGINE 行(或整个文件)+ daemon-reload + 重启。
- 遗留小项: 主service文件27行 COSMAC_SMTP_FROM_NAME=CosMac Star 没加引号,systemd 丢弃"Star",
  邮件发件人名一直是"CosMac"——已给负责人修复命令,待确认执行。

## 2026-07-03 — AI引擎升级P0+P1:Claude Agent SDK 引擎(可插拔,DeepSeek驱动实测通过)
- 目标"更聪明/更像Claude Code"。评估否决 ruflo(宣称与实际严重不符,300+工具290个是壳);选
  **官方 Claude Agent SDK**(=Claude Code 同款 harness)。关键洞察:SDK 认的是 Anthropic **协议**
  而非 Claude 本尊——DeepSeek 官方有 Anthropic 兼容端点(api.deepseek.com/anthropic),测试环境
  DeepSeek 驱动、生产改两个 env 即切 Claude。
- **P0 验证**(全通过): CLI+DeepSeek端点纯对话✓;多步工具链(Bash算数→Write写文件)✓。
  坑1: 本机已登录的 Claude OAuth 凭据优先级盖过 env → 401;解法=隔离 HOME(引擎固定用
  /tmp/cosmac-sdk-home)。坑2: 本地 venv 是 py3.9,SDK 要 3.10+ → brew 装 python3.12,建 .venv312
  (已 gitignore;装了 claude-agent-sdk 0.2.110 + cosmac requirements)。
- **P1 落地**: cosmac/ai/engine.py——ClaudeSdkEngine 与 legacy Agent.run 同签名;Toolbox 全部工具
  自动桥接成 SDK in-process MCP 工具(执行仍走 Toolbox.execute,**门控/配额/越权/私聊防呆全复用**);
  history 拼文本注入;env 组装(BASE_URL/KEY/MODEL);每 run 新建实例防并发串味。bot 接线
  _run_agent_engine:开关开→SDK引擎,**任何失败自动回退 legacy**(增强绝不搞挂问答)。
- 配置(默认关,零部署风险): COSMAC_AGENT_ENGINE=claude_sdk + COSMAC_SDK_BASE_URL/API_KEY/MODEL/MAX_TURNS。
- **E2E 冒烟**(正式引擎代码+真DeepSeek): 工具调用参数精确;history 上下文推断("这个群"→从历史
  推出群名)✓。单测 test_engine.py(开关/历史转换/无SDK失败路径);全量 355 过+ruff 过。
- **生产启用要求**(暂不部署,本地已验证): 服务器 Python3.10+、Node+claude CLI
  (npm i -g @anthropic-ai/claude-code)、pip 装 claude-agent-sdk、配 COSMAC_SDK_* env。
- 已知取舍: SDK 每请求拉 CLI 子进程,冷启动 3~8 秒(比 legacy 慢;换完整 harness);cost 字段按
  Claude 牌价估算不可信;DeepSeek 驱动下工具调用可靠性略逊 Claude 驱动(协议兼容、为Claude调优)。

## 2026-07-03 — AI 私人会话里可按**群名**邀人(invite_to_room 支持 room_name)
- 现象: 频道里@AI邀人已通,但右侧私人会话里邀不了——防呆拒绝"本群"是对的,可用户就算说清
  "邀请xx加入暑期研学活动",AI 也办不到:工具只认 room_id,没有"按群名找群"的能力。
- 修: matrix_client 加 joined_rooms();invite_to_room 加 room_name 参数——在 bot 已加入的群里按
  m.room.name 解析(精确唯一→直接邀;重名→列候选让用户挑,顺带提示清理;无命中→引导)。房名带
  5 分钟缓存。私聊防呆文案同步引导"说出群名即可"。
- 348测试+ruff过。**部署: 重启 guduu-bot(纯后端)。**

## 2026-07-03 — 频道类型角标(私密/公开)+ AI面板"私人会话"标识
- 来由: 用户分不清"在私聊还是群里/这群外人进得来吗",曾把邀请发错进AI私聊(见上条)。
- 频道头名字旁加角标: **私密**(灰,仅邀请可进)/**公开**(绿,本服务器任何人可自行加入),读房间
  m.room.join_rules(spaceJoinRule 对任意房间通用);悬停有完整说明。
- 右侧AI面板标题旁加**私人会话**角标,悬停提示"邀请成员请到目标频道里@AI操作"(防再犯)。
- 纯前端;build过。**部署: 仅前端 dist。**

## 2026-07-03 — 修两个AI会话语义坑(私聊邀人闯私聊 + 会话房被拉人后AI装聋)
- 实测复盘(bot日志): 群主在**AI私聊**里说"邀请xx加入本群"→AI把"本群"解析为当前房=私聊房,
  三位成员被邀进群主的**AI私聊**而非目标群;私聊房因此>2人→bot按"群聊需@"判定→群主后续不带@
  的消息全部无响应(用户以为放大AI坏了,其实是同一个会话房变多人了)。
- 修①(防呆): ToolContext 加 is_dm;invite_to_room 在私聊/AI会话房且未显式给 room_id 时**拒绝**并
  引导指明目标群(工具描述同步说明"私聊房绝不能拉人")。
- 修②(免@): is_dm 判定从"人数<=2"改为"带 cosmac.ai_session 标记 or 人数<=2"(带永久缓存)——
  AI会话房被误拉人后 bot 依然每句都回,不再莫名装聋。
- 全量348过+ruff过。**部署: 重启 guduu-bot(纯后端)。**
- 残局: 三位成员已被邀进群主AI私聊(前端自动接受会让他们真进来)——建议群主新建一个AI会话当
  主会话,并在**暑期研学活动群里**@AI重新邀请四人;后续可考虑给AI加"移出成员"工具(暂未做)。

## 2026-07-03 — 修:被邀成员仍进不了群(自动接受邀请两处失效)
- 现象: invite_to_room 已能正确邀请,但被邀账号登录后左侧仍看不到群。
- 根因①: acceptPendingInvites 防垃圾邀请的判定**过严**——invite 态房间客户端常只有精简状态
  (stripped state),读不出邀请人 → `if(!inviter) continue` 把**本服正常邀请也挡了**(上轮修
  bug10 引入的 fail-closed)。改: 读不到邀请人时**默认接受**,只有明确确证是外部服务器的邀请才跳过
  (当前联邦无外人,风险极低)。
- 根因②: 只在 afterLogin 查一次——在线期间收到的邀请没人处理,必须重登才有机会(还会撞根因①)。
  改: maybeAcceptInvites(防重入)挂进 refresh 循环(sync 驱动)——邀请一到**实时自动入群**,
  新群立刻出现在左侧(孤儿房上一批已放行显示)。
- build 过。**部署: 仅前端 dist(不用重启 bot)。**

## 2026-07-03 — 修两个群问题:AI邀人重复建同名群 + 孤儿群在有工作区的账号下不可见
- 问题1(重复建群): 主AI工具清单里**没有**"邀请进已有群"的工具,用户说"把xx拉进群"时模型只能误用
  create_room(带invitees) → 生成同名新群。修: 注册 invite_to_room 工具(user_id必填/room_id默认当前房,
  过 _check_room_access 防越权,底层复用 client.invite_user);create_room 描述加"邀请人绝不要再建新群"
  警告;加进 _ALWAYS_ON(否则线上旧AI配置白名单会把新工具当未勾选禁用,模型又退回误用 create_room)。
- 问题2(孤儿群不可见): 左侧频道列表按当前工作区过滤(spaceChildIds),AI建的群/被邀进的群不挂任何
  Space → 有工作区的成员在任何工作区下都看不到入口、进不了群(没工作区的账号显示全部所以能看到)。
  修: refresh 时重算**所有工作区子频道并集**(allSpaceChildIds),filteredRooms 放行"不属于任何工作区
  的孤儿房"——任何工作区下都可见。
- 测试: test_runtime_config 3处工具白名单断言+计数更新(新工具进列表);全量348过+ruff+build过。
- **部署两步: 前端dist + 重启bot。**

## 2026-07-03 — auth 安全增强阶段2:异地登录检测 + 邮箱验证码二次验证(step-up)
- 流程: 登录密码验证成功后,比对当前IP与该用户历史成功登录IP(阶段0审计表 recent_success_ips)。
  网段级比对(_ip_bucket: IPv4取/16、IPv6取前4组,近似"地区"粒度——手机换IP不误报;将来换GeoIP只动
  此函数)。命中历史网段/无历史(冷启动)→放行;换了地区→**不发token**(刚拿的token立即撤销):给绑定
  邮箱发登录验证码(新邮件模板kind=login,含"若非本人请立即改密码"),前端提示"新设备/新地点登录,
  码已发至 g***@gmail.com",输码后带code重试→验码通过才真正登录。没绑邮箱的老账号→放行+审计留痕
  (stepup_skipped_no_email),不锁死。
- **env 开关 COSMAC_LOGIN_STEPUP=1,默认关**(部署零风险,同Turnstile模式;想开在bot服务env加一行)。
- 实现: registration(_stepup_enabled/_ip_bucket/_login_risky/_email_for_login/_mask_email/_revoke_token/
  _stepup_gate;login_account/login_email加code参数,验码在Synapse登录之前);email_repo加
  get_email_by_username;bot透传code;前端 LoginResult{stepUp,emailHint}+AuthView输码UI(切页清态)。
- 安全要点: 挑战时token绝不给前端且尽力撤销;验证码purpose=login独立分桶;审计全链路
  (stepup_challenge/stepup_bad_code/ok_stepup)。
- 测试 StepUpTest 6用例(桶判定/冷启动/挑战验码全流程/错码/无邮箱放行/默认关);全量348过+ruff+build过。
- **部署: 前端dist+重启bot;启用还需 env COSMAC_LOGIN_STEPUP=1(建议开Turnstile时一起配)。**

## 2026-07-03 — 二轮审查(阶段0/1新代码):修8项(2高)
- 2代理审阶段0/1新增auth代码,逐条核实后修。
- 【高①·我上步收口引入的回归】登录收口后所有登录从bot(127.0.0.1)打Synapse,Synapse rc_login按来源IP
  限频→全平台共享bot单IP额度(默认burst5),几个用户同时登录第N个就被429;且 login_account 把
  Synapse 非200一律误报"用户名或密码错误"。修:抽 _proxy_synapse_login——带 X-Forwarded-For 转发真实IP
  (Synapse client监听已开x_forwarded)让Synapse按真实IP限频;区分状态码(429→429/5xx→502,只401/403→凭据错)。
  login_email 同修 + 审计subject统一用username(异地检测不把同一人当多主体)。
- 【前端高①】Turnstile token一次性:首次发码后token作废,60s后重发必失败且挂件仍显示已通过。修:每次
  请求后 turnstile.reset+清token。【前端高②】脚本加载失败→发码永久死锁+existing分支永久悬挂。修:
  onerror移除死标签+标失败,给可行动提示并重试;existing分支同挂error。
- 中③ 限频命中审计写放大(超限请求不消耗计数却每条入库)→按IP窗口采样,同IP 600s只入库首条。
  中④ Turnstile校验挪到IP限频/邮箱校验之后(假token不再空耗Cloudflare调用+占共享线程池)。
- 前端:密码强度用Unicode类别对齐后端(修"前端说合格后端拒");doRegister提交前用强度拦;倒计时interval
  统一管理+卸载清理;getAuthConfig失败时按后端报错自愈重拉+渲染挂件;nextTick显式保证挂件容器就位。
- 低⑤类型归一(username传非字符串不再掐连接) 低⑥超长密码(>512提前拦) 低⑦site key走_env(前缀回退)。
- 证伪:X-Real-IP(生产已核实有)、审计敏感信息、/auth/config泄露面。测试+3高①用例;全量342过+ruff+build过。
- **部署: 前端dist + 重启bot。** ⚠️高①的X-Forwarded-For生效前提: Synapse client监听 x_forwarded:true(需确认homeserver.yaml)。

## 2026-07-03 — 修:发验证码"太频繁"时前端按钮不走倒计时
- 现象: 点发码被后端限频拦(429"发送太频繁请X秒后再试"),前端只显示错误、按钮仍"发送验证码"可点,
  再点又撞。根因: 发码函数丢了后端返回的 cooldown 字段,倒计时只在发码成功后才启动。
- 修: registerRequestCode/resetRequestCode 改 Promise<number> 返回 cooldown;失败时把 cooldown 挂到
  错误对象抛出。sendCode 抽 startCodeCooldown(sec):成功用后端cooldown、被限频用剩余秒数,两种都走
  按钮倒计时。纯前端;build 过。

## 2026-07-03 — auth 安全增强阶段1(下):Turnstile 人机验证(注册/找回发码前)
- 防机器人批量注册/刷验证码。**env 可插拔**:后端配了 COSMAC_TURNSTILE_SECRET 才启用,没配则整段
  跳过(不破坏现有流程)。site key 走 COSMAC_TURNSTILE_SITE_KEY(公开)。
- 后端 registration._verify_turnstile()(向 Cloudflare siteverify 校验;没配secret放行;网络异常保守拒)
  接进 request_code/reset_request_code(发码前,IP限频之前);新增公开端点 GET /cosmac/auth/config
  (前端拿"要不要显示挂件+site_key",secret绝不出现);CORS 白名单加 /cosmac/auth/。
- 前端 client.ts getAuthConfig() + 发码带 turnstile token;AuthView 按需注入 Turnstile 脚本、注册/找回
  模式渲染挂件、拿到 token 才让发码,登录模式不显示。
- Site key(公开): 0x4AAAAAADulch6YiMNXKDh8。**Secret key 待配进服务器 env(负责人另发,不进git)**。
- 测试 TurnstileTest(未启用放行/启用空token拦/发码被拦);全量 339 过 + ruff + build 过。
- **部署: 前端 dist + 重启 bot。启用人机验证还需在 bot 服务 env 配 COSMAC_TURNSTILE_SECRET +
  COSMAC_TURNSTILE_SITE_KEY;不配则功能静默关闭。**

## 2026-07-02 — auth 安全增强阶段1(上):密码强度(前端即时提示 + 后端弱密码拦截)
- 规则按 NIST 思路(长度优先,不强制大小写符号组合):>=8位 + 至少两类字符(字母/数字/符号)+
  不在常见弱密码表(30个高频泄露密码,不引 zxcvbn 重依赖)+ 不含用户名(>=4位才启用)。
- 后端 registration.password_problem() 接进 注册/重置 两处(**真防线**,防绕过前端直调API);
  重置处只做纯计算规则(不带含用户名检查——那要查DB反查用户名,不能放在IP限频之前)。
- 前端 AuthView 密码框下加强度条(弱红/中橙/强绿)+ 与后端同规则的即时文案,弱密码提前告知。
- 老账号既有密码不受影响(只管新设密码)。阶段1(下)= Turnstile 图形验证,需负责人去 Cloudflare
  申请 site key/secret(免费),届时做成 env 可插拔、没 key 自动跳过。
- 测试 PasswordStrengthTest(规则矩阵+注册拦截);全量 336 过 + ruff + build 过。
- **部署两步: 前端 dist + 重启 guduu-bot。**

## 2026-07-02 — auth 安全增强阶段0:登录收口 + 认证审计日志
- roadmap 阶段0(异地检测/二次验证/防多号的地基)。纯技术、不涉及付费策略。
- **登录收口**: 账号登录原来前端直连 Synapse /_matrix/client/v3/login,后端看不到→IP限频/审计/异地
  检测全插不进。新增 registration.login_account(限频+代理Synapse登录+记审计)+ bot handle_login_account
  + POST /cosmac/login/account;前端 loginNoStart 改走后端(镜像 loginWithEmailNoStart)。账号登录现
  与邮箱登录同一道防线。**权衡**: 账号登录now依赖bot在线(bot挂则登录不可用),这是收口的固有代价、
  符合"认证统一经我们这层"的设计。
- **认证审计日志**: 新表 cosmac_auth_event(kind=login/register/reset, subject, ip, ok, detail;绝不存
  密码/码/token)+ auth_event_repo(record/recent_by_subject/recent_success_ips)。登录/注册/找回各处
  记一条(成功+失败+限频)。create_all 自动建表,重启bot即生效。recent_success_ips 已为阶段2异地检测
  预留("本次IP不在历史成功IP里=可疑")。
- 测试: 新增 LoginAccountTest(成功/凭据错/空输入 + 审计断言);全量 334 过 + ruff + build 过。
- **部署两步: 前端 dist + 重启 guduu-bot**(新表自动建)。

## 2026-07-02 — 全仓代码审查:修复 12 项(3 代理并行扫 + 逐条人工核实)
- 负责人要求全面查还有什么 bug。3 个审查代理分区扫(认证HTTP/前端重构区/AI工具业务层),16 项发现、
  逐条核实后修 12 项,2 项按"够用即止"口径不修(配额竞态/事务重放),1 项待线上核实(nginx X-Real-IP),
  1 项设计如此(协作人=付费门控)。
- **前端**: ①restoreSession 只在确定鉴权失效(M_UNKNOWN_TOKEN/停用)才删会话,网络抖动/超时保留——
  弱网刷新不再被踢回登录页;同步超时 15s→60s(大账号误杀) ②startFrom 覆盖单例前 stopClient——
  "添加账号"往返不再泄漏幽灵 sync ③频道配置 persist 700ms 窗口累积合并+inflight 串行化——连改
  人设+模型不再丢前者 ④频道配置内存 key 改 roomId——同名频道跨工作区不再串味;加载先重置基线
  ⑤自动接受邀请限定**本服邀请人**(联邦垃圾邀请不再强制入群)+永久失败(403/404)自动拒邀
  ⑥会话失效跳登录带 redirect,深链不丢。
- **后端**: ⑦配额改 check(只拦)/consume(成功才扣)分离——建专班失败不再吃掉终身配额,run_workflow
  纯列表查询不再扣次数 ⑧工作流幂等键拼 slug——一句话跑 A、B 两个工作流不再互踩 ⑨「建专班」命令
  补 assemble_team 门控+teams 配额(堵付费墙旁路) ⑩用户名占用判定改按 errcode M_USER_IN_USE
  (Synapse 1.141 文案不含 in use,原判定是死代码) ⑪建号 5xx/超时=结果未知不再回滚邮箱占位
  (防孤儿账号永失邮箱登录/找回;claim 改三态 claimed/existing/taken) ⑫pay_me 过期不再返回旧到期时间;
  reset_password user_id 补 quote。
- 测试: test_quota/test_registration 更新到新契约,新增 2 用例(结果未知不回滚/existing 不回滚)。
  全量 331 测试过 + ruff 过 + build 过。
- **部署两步: 前端 dist + 重启 guduu-bot。**

## 2026-07-02 — bug14 平台管理员可管理所有频道 + 顺带修好后台邮箱显示
- bug14 根因: 频道配置是 state event,写它需房间 power>=50;服务器管理员≠房间管理员,在别人建的频道
  power=0 → 写被拒。且 bot 自己也只是被邀请(power=0),不能代写。
- 修法: 用 Synapse 管理 API make_room_admin(借频道内已有房间管理员把请求者提成 power=100),复用
  COSMAC_ADMIN_TOKEN。registration.make_room_admin + bot handle_channel_claim_admin + POST /cosmac/channel/claim-admin(仅平台管理员)。
  前端 claimChannelAdmin;useChannelAdmin 保存被拒时自动接管+重试一次(非管理员 claim 返回false、退回错误提示)。
- **顺带修好管理后台邮箱不显示**: CORS 预检白名单缺 /cosmac/admin/(GET 带 Authorization 也要预检)
  → 之前 /cosmac/admin/emails 被浏览器拦、前端拿不到数据。本次把 /cosmac/admin/ 和 /cosmac/channel/ 加进白名单。
- 全栈: registration.py/appservice_bot.py(后端)+ client.ts/useChannelAdmin.ts(前端)。329测试+ruff+build 过。
- **部署两步: 前端 dist + 重启 guduu-bot。**

## 2026-07-02 — 修 bug12 任务派发不通知被指派者
- 根因: _tool_create_tasks 只把任务写看板+回文字给AI,从不通知被指派的真人 → 任务躺看板、当事人不知道。
- 修法: 拆完任务后按人聚合,给每个真人被指派者(id以@开头)在群里发一条 @提及消息;Matrix 默认推送规则
  正文含对方用户名即触发通知。best-effort、一人一条、发失败不影响任务已登记。
- 后端(cosmac/ai/tools.py);329测试+ruff过。**部署需重启 guduu-bot**。

## 2026-07-02 — 修登录页两个 QA bug（报错友好化 + 切页清空表单）
- QA 报了 5 个 bug。分诊：bug1(验证码限频)、bug2(一邮一号)= 之前已修并上线；bug3/bug4 本次修；
  bug5(会员开通失败)= 交易模块未实现真实支付、非代码 bug（见下）。
- **bug3 登录报错不友好**：AuthView 加 `friendlyLoginError()`，把账号登录直连 Synapse 的原始
  errcode/网络错误映射成中文（M_FORBIDDEN→用户名或密码错误；M_LIMIT_EXCEEDED→尝试过于频繁；
  网络错→网络异常）。邮箱登录走后端本就中文，不受影响。
- **bug4 用户名跨页残留**：`switchAuthMode` 原来只清 password2/emailCode，改为清空**全部**字段
  （user/password/email/…），避免登录页填的用户名被带进注册页。
- **bug8 刷新登录页被弹去首页**（第二批 QA）：路由守卫原来把"已登录"用户从 /login 弹回首页 →
  已登录用户在登录页想切账号、正输账号时一刷新就被打断。改为**登录页始终可达**（正常登录后仍由
  proceed() 主动跳转，不依赖弹走逻辑）。router/index.ts 守卫简化。
- **bug5 会员开通失败**：不是可 patch 的 bug——"升级会员"只接了 `manual`(模拟)支付通道，而该通道按
  安全红线生产必关（`COSMAC_PAY_ALLOW_MANUAL`，防自助白嫖）；真实支付(Stripe/PayPal/…)从未接通。
  要让自助开通生效=实现真实支付(模块4，大工程)；当前可由管理员在后台手动授予会员等级。待负责人拍板。
- **bug9/10/11 邀请成员不生效**（第二批 QA）：根因=CosMac 客户端在"被邀请方"这侧没有接受邀请的
  机制——被邀请的人停在 Matrix `invite` 态、永不 join，于是邀请方显示"已邀请/待接受"、被邀请方看不到
  也没真加入、成员数里外对不上。修法：登录后 `acceptPendingInvites()` **自动接受所有待接受邀请**（join），
  贴合 CosMac"AI/管理员把你拉进项目频道、邀请即入群"的工作台模型（像 Slack）。best-effort、不阻断登录、
  有新入群就刷新列表。注：bug9 的成员在**自己下次登录时**才入群（Matrix 无法强制把离线用户拉进房，
  这是协议约束）；主 AI 邀请的"成功"= 邀请已发。
- 纯前端；build 通过。部署只需前端 dist（无需重启 bot）。

## 2026-07-02 — 管理后台用户列表显示邮箱地址
- 需求：管理后台用户列表要能看到每个账号的注册邮箱。
- 数据链路：邮箱只在 cosmac DB 的 `RegisteredEmail`（Synapse 不存），而管理后台是浏览器、够不到
  DB → 必须经 bot 的 HTTP 端点拿。
- 后端 `appservice_bot.py`：新增 `handle_admin_emails(token)` + `GET /cosmac/admin/emails`。**仅平台
  管理员**（whoami → `_is_platform_admin`，非管理员 403——邮箱是个人敏感信息、且是全平台一次性
  拉取，普通用户不该看别人邮箱）。读 `RegisteredEmail` 返回 `{用户名localpart: 邮箱}`；读失败返回空表
  优雅降级。照抄 `handle_stats` 的鉴权模式。
- 前端：`client.ts` 加 `listUserEmails()`（走 `/cosmac/admin/emails`）+ `AdminUser` 加 `email?` 字段 +
  `listUsers()` 拉完用户后按 localpart 合并邮箱；`AdminView.vue` 在用户 id 下显示 `✉ 邮箱`。
- 验证：`npm run build` 通过；全量 329 测试过 + ruff 过；preview 登录页无回归无报错。真实"管理员进
  后台看到邮箱列"需线上用管理员账号验（本地无 admin 会话）。
- ⚠️ **全栈改动，部署要两步**：① 前端 dist → `/var/www/cosmac-app`；② **重启 guduu-bot**（后端加了端点）。

## 2026-07-01 — 登录注册抽成独立页面（方案A：治"不流畅"+ 给安全增强铺路）
- 背景：负责人反馈登录注册"太不流畅"。查明根因：认证 UI 原来是塞在 **199KB 的巨石 LiveView.vue**
  里一段 `v-if="!loggedIn"`——登录页必须先加载整个 app 才显示、已登录用户刷新还"闪一下登录框"、
  登录/登出/切号是整页 reload、且没有独立地址。（之前抽风期误报的"AuthView.vue"其实不存在。）
- 方案A（独立 AuthView + 路由架构）：
  · 新建 `views/AuthView.vue`：独立登录/注册/找回页，视觉与原登录块**完全一致**（搬同一套 class/CSS），
    自包含（内联提示替代 toast）。
  · `matrix/client.ts` 加 `loginNoStart/loginWithEmailNoStart`（只认证+saveSession、不 startClient）。
  · 根架构改回 `App.vue`(`<router-view>`)：`main.ts` 挂 App；`/login`→AuthView，其余→LiveView，
    **两者懒加载**（登录页从"要载 286KB"变成独立 **~7KB chunk**，秒开）。router 加 `beforeEach`
    认证守卫（未登录→`/login?redirect=`；已登录访 /login→`/`，`?add=1` 除外）。
  · LiveView **最小 3 处改动**：删登录模板块→换 `.live-splash` 占位；`onMounted` 无会话→`router.push('/login')`；
    「添加账号」→`router.push('/login?add=1')`。旧认证函数留作无害死代码（noUnusedLocals=false）。
- 交接机制：AuthView 认证成功→saveSession→`router.push('/')`→LiveView 挂载 `restoreSession` **只同步一次**，
  **连整页 reload 都不用**，比原设想更流畅。更新 memory `client-root-is-liveview`。
- 验证：`npm run build` 通过（AuthView 6.94KB / LiveView 286KB 独立 chunk）；本地 preview 全绿——
  根路径未登录自动跳 `/login?redirect=/`、登录页渲染与原一致零报错、登录/邮箱登录/注册/找回四模式字段
  全对（含确认密码）、守卫拦截 `/admin`、`?add=1` 显示「返回当前账号」。
- ⚠️ **未端到端测真实登录**（本地无测试账号）：认证成功→进主应用的交接是按现有会话模型构造的、逻辑自洽，
  但没跑通真号。建议部署前在本地 preview 用真账号登一次确认。**改了 `client/`，需重建 dist + 部署。**

## 2026-07-01 — 修复注册/登录两处安全问题（IP 限频可绕过 + 一邮一号没兜住）
- 问题一「IP 限频能被绕过」：`_Handler._client_ip()` 原来取 `X-Forwarded-For` **首段**——XFF 是
  普通请求头、客户端能随便塞，nginx 用 `$proxy_add_x_forwarded_for` 会把客户端伪造值保留在前、
  真实 IP 追加在末尾，所以首段最不可信；攻击者每次换个假 IP 就能让限频器把每个请求当"新 IP"、
  绕过全部按 IP 的发码/验码/登录限频。**修法**：优先信 nginx 注入的 `X-Real-IP`（客户端伪造不了）
  → 其次取 XFF **最后一段**（可信跳）→ 兜底 socket 地址。⚠️ 上线前确认服务器 nginx 反代
  `/cosmac/auth/` 配了 `proxy_set_header X-Real-IP $remote_addr;`（没配也能靠"取 XFF 末段"兜底，
  前提是反代把真实 IP append 到了 XFF）。
- 问题二「同邮箱多账号只重置部分」：根因是注册"先查后建"有 TOCTOU 竞态、且映射写库是**覆盖**语义
  → 历史上同邮箱能建出多个 Synapse 账号、映射只留最后一个 → 找回密码只重置得到那一个。负责人拍板
  **坚持一邮一号（方案A）**、不做绑定/解绑系统。**修法**：`verify_and_register` 改成 **claim-first**
  ——验码通过后、建号**之前**先占位（`_claim_email` 靠邮箱唯一约束原子占位），邮箱已被占直接 409、
  **根本不建号**；建号失败再 `_release_email` 回滚占位。`email_repo.set_email` 从"覆盖"改成**拒绝改绑**
  （已绑别的账号抛 `EmailAlreadyBound`，绝不挤走先注册的），新增 `clear_email`。cosmac DB 异常时
  fail-closed 回 503（该 DB 与 Synapse 同实例，它挂了注册本就走不通）。
- 关键决策：注册撞邮箱的 409 仍放在**验码之后**（防邮箱枚举，不变）；存量历史多号无法自动反查清理
  （老账号没绑 3pid、映射表没记），个别人工处理，本次只保证"从现在起不再产生"。
- 测试：`test_email_repo.py`(拒绝改绑/幂等/新建/回滚) + `test_registration.py` 新增(撞库 409/DB 异常 503/
  建号失败回滚) + 新 `test_client_ip.py`(伪造 XFF 首段不污染取值)。全量 329 测试通过、ruff 通过。
- **纯后端改动，无需部署**（没动 `client/`）；生效于 bot 进程重启。

## 2026-07-01 — 主AI放大态改造成「多会话」界面(参考 Claude)
- 需求：主 AI 放大后要像 Claude——左侧 Recents 历史会话列表 + New session 新建会话；负责人拍板
  「三栏·保留特色」：左 Recents / 中 当前对话 / 右 任务进度+知识库(保留现有增值栏)。
- 架构关键：bot 端的对话历史/上下文/记忆本就**按 room_id 隔离**，所以「一个与 bot 的私聊房 = 一段
  独立会话」是天然映射——新会话 AI 从零开始、互不串味，历史会话随时切回继续。**bot 无需改动**。
- 前端 client.ts 新增多会话 API：会话房用 state event `cosmac.ai_session` 稳定标记(兼容旧的靠房名
  「中枢 AI」的历史房)；`listAiSessions`(按最近活跃倒序、标题取首条我方消息摘要/否则「新会话」)、
  `createAiSession`(建房+邀 bot+打标记)、`deleteAiSession`(leave+forget)、`aiSessionRoomIds`(供
  频道列表排除)、`ensureBotDm` 改为复用最近活跃会话、否则新建。`listRooms` 排除所有会话房。
- LiveView：放大态左栏(复用现成 Cowork `.ai-cw-*` 样式)渲染 Recents + 新建会话按钮；
  `switchAiSession`/`newAiSession`/`removeAiSession`；refresh 与进入放大态时刷新会话列表。
- 验证：`npm run build` 通过、preview 无报错；多会话交互需登录态,线上硬刷新验证。

## 2026-07-01 — 规范：全程中文沟通(写进 CLAUDE.md §6 第0条)
- 负责人要求：跟他的一切沟通(对话/思考过程叙述/汇报/报错解读/部署说明)一律用中文，
  不要用英文/日文写"给他看的过程"。专有名词可保留英文原词、但句子必须中文。
- 落地：CLAUDE.md §6 新增第0条(强制项)；纯文档改动、无需部署。

## 2026-07-01 — 修复"添加账号后看不到之前的账号(切换列表为空)"
- 现象：加了新账号后，"切换账号"里没有之前的账号，无法一键切回。
- 根因：`restoreSession`（页面刷新复活会话时）**没把当前账号写进多账号缓存 ACCOUNTS**——
  只有"新鲜登录/注册"(saveSession) 才写。于是靠 restore 活着的账号(功能上线前就登录过的、
  或只有 SESSION_KEY 的)永远进不了缓存；再加个新号 → 缓存只有新号 → 过滤掉当前 → 列表空。
- 修法：抽出 `upsertAccount()`（同号覆盖、保留原显示名），`saveSession` 与 `restoreSession` 都调用。
  这样**每次刷新都会把当前账号补进缓存**，加了新号后旧号必然可见、可免密切回。
- 用户侧一次性补救：旧号若从没进过缓存，用「添加账号」重登一次即可，此后两边都在、不再复发。

## 2026-07-01 — 修复"第二管理员看得到频道、看不到用户列表"
- 现象：新升的管理员进后台能看频道，却看不到用户列表。
- 根因：`loadUsers` 用 `Promise.all([listUsers(), getMembers()])` 把两件事绑死。`getMembers()` 读的是
  **控制室 state event**，需已加入控制室；新管理员还没 join → 读取抛错 → Promise.all 整体失败 →
  用户列表变空。频道列表不读控制室，所以照常显示。
- 修法：**解耦**。先 `listUsers()`（走 /_synapse/admin，服务器管理员就能读）拿到用户列表并渲染；
  会员等级 `getMembers()` 单独读，失败先 `ensureControlRoomMembership()` 自愈(接受控制室邀请)再重试一次，
  仍失败则标记 `membersLoadFailed`：等级列禁用改档 + 顶部警示条，**绝不**伪装成"全员免费"让人误操作。
- 效果：即便控制室还没对齐，管理员也能正常看/管用户；等级读不到时明确提示而非静默出错。

## 2026-07-01 — 新增管理员权限与所有者"完全一致"
- 背景：后台把某用户升为「管理员」后，对方反馈"看不到用户数据"。排查：升管理员走 `setUserAdmin`
  已正确写入 **Synapse 服务器管理员**标志——权限本就与所有者一致(管理员是二元、无高低级)。
  两个真实问题：
  1) **会话未刷新**：后台入口/用户数据靠前端 `isAdmin` 放行，而它只在**登录那一刻**探测一次。
     升权时对方已登录 → 旧值 false → 看不到。→ 升管理员成功的提示改为"请让 TA 刷新页面(或重登)生效"。
  2) **写 AI 配置差一点**：主 AI 判平台管理员只看控制室 power≥50(所有者提权时已写)，不看 join；
     但对方要**亲自写** AI 配置/门控 state event 时，Matrix 要求必须是控制室 **join 成员**——光被邀请发不了。
     → 新增 `ensureControlRoomMembership()`：管理员登录时自动接受控制室邀请并 join，补齐这份资格。
     LiveView `afterLogin` 检测到管理员即调用(幂等、失败静默)。
- 关键决策：普通管理员保持控制室 power=50、所有者 100——这是**有意**差别，只影响能否互相降权/踢人，
  功能能力(看用户/改会员/门控/AI 配置/发通知)完全等价；不给普通管理员 100，否则撤销时降不下来。
- 无新增依赖；`npm run build` 通过。

## 2026-07-01 — 清理写死演示数据(会误导用户的那批)
- 审计前端后修 A 类(写死身份/数字被当真实数据展示):
  - 个人主页(ProfileHome):「我的收益」四个假金额、「我的上架/购买」假商品卡 → 空态("功能开发中/你还没有…");
    「我的团队」写死的安其团队 → 改读**当前登录者真实协作人名册**(useMyPeople)。
  - 个人设置弹窗(UserSettingsModal)身份头显示 安其/@xiaoyu → useUserProfile 改读 myProfileInfo()真身份(切账号即刷新);
    权限/数据授权开关的影视特化文案 → 通用文案。
  - 工作区名回退 tenant.hqTitle(安其影视工作室) → 中性「我的工作区」(没工作区/未 sync 时不再显示租户名)。
  - 品牌漏字:插件商城「主 AI · 安其」→「主 AI」;CLI 面板「安其-MBP」→「我的电脑」。
- 保留(B类·有意占位,非 bug):AI Agent 商城/插件商城的目录 demo、社媒数据源"待接入"、频道管理 !isLive 兜底——功能未接后端,后续按需接真数或隐藏(待负责人定)。
- 纯前端。build + preview 干净重启无 console 报错。只发 dist。

## 2026-07-01 — 修个人主页显示写死演示人物(不是本人)
- Bug:个人主页(ProfileHome)身份写死成演示人物(currentUser=安其 / handle=@xiaoyu / 演示头像)→ 换任何账号
  登录看到的都是同一个"安其",被误当成"管理员账号的主页"。
- 修:ProfileHome 改用**当前登录者本人**资料——client.ts 加 myProfileInfo()(读 mx 的 显示名/头像/uid);
  面板打开(watch visible)时刷新;头像有图显示 img、无图回退首字母。去掉 currentUser 依赖。
- 纯前端。build + preview 无 console 报错。只发 dist。

## 2026-07-01 — 多账号：切换账号(缓存免密切换)
- 用户菜单加「切换账号」：列出所有登录过的账号，点一下免密切到那个账号；「添加账号」进登录页登另一个
  (当前账号已缓存不丢，可「← 返回当前账号」取消)。
- client.ts:SESSION_KEY 存活动会话、ACCOUNTS_KEY 存全部账号(saveSession 顺带 upsert)；listCachedAccounts/
  currentUserId/switchToAccount/removeCachedAccount。切账号=写活动会话+整页 reload(复用 restoreSession)。
- 退出登录只移除当前账号(其它缓存保留)。纯前端。build + preview 无 console 报错。只发 dist。

## 2026-07-01 — 社区服务器 P3：封禁 / 解封
- 成员管理弹窗加「封禁」(kick 只是移出、还能再来；ban 移出且**不能再加入**直到解封) + 「已封禁」区(仅管理员可见)+「解封」。
- client.ts:banFromSpace/unbanFromSpace(Space+其下频道 ban/unban)、listBannedMembers(membership=ban)。ban 权限同 kick(power≥50 且高于对方)。
- 纯前端。build + preview 无 console 报错。只发 dist。

## 2026-07-01 — 社区服务器 P2：成员列表 + 角色管理
- 工作区设置里加「👥 成员与角色管理」→ 成员弹窗：列出服务器(Space)全部成员+角色(群主/管理员/成员，
  由 Matrix power level 推)+头像+待接受标记。
- 操作(权限内)：群主(power≥100)可「设为管理员/取消管理员」(setMemberPower 改 Space power_levels，
  保留其它字段只改 users)；管理员+(power≥50)可「移出」(kickFromSpace 踢 Space+其下频道)。
  只能管 power 比自己低的、非本人、非 bot。
- 复用已有 listChannelMembers(带 role/power)；新增 myPowerIn/setMemberPower/kickFromSpace。纯前端。
- 顺带修 P1「复制链接」按钮换行错位(flex-shrink/nowrap)。验证:build + preview 无 console 报错。只发 dist。

## 2026-07-01 — 工作区→社区服务器 P1：开放加入 + 可分享邀请链接
- 负责人定:工作区(左侧服务器栏 制作/运营/明星…)要做成"真社区"——外人凭链接就能加入(像 Discord)。
  底层无需重建:工作区本就是 Matrix Space = Discord 服务器;只加"社区"功能。
- P1(纯前端,用 Matrix state event + joinRoom):
  - `setSpaceOpenJoin(spaceId, open)`:把 Space 的 join_rules 设 public/invite,并同步其下频道(否则加入
    服务器却进不去频道);`spaceJoinRule` 读当前;`spaceJoinLink` 生成 `/#/join/:space` 链接;
    `joinSpaceByLink` 加入 Space + 轮询其子频道逐个 join(Matrix 加入 Space 不自动进子频道)。
  - 工作区设置弹窗加「🌐开放加入」开关 + 邀请链接复制框(仅开放时显示)。
  - 路由 `/join/:space`:已登录点开→直接加入并切过去;未登录→记下 pendingJoinSpace,登录/注册
    (afterLogin/doRegister)后自动加入。冷启动/会话内(applyFromRoute)都覆盖。
- 权限:开放加入需在该 Space 有改 join_rules 权限(创建者天然有)。关闭=恢复仅邀请(老成员留存)。
- 验证:build + preview 无 console 报错。纯前端→只发 dist。
- P2 待做(按需):成员列表/角色管理、链接有效期/吊销、公开发现页。

## 2026-07-01 — 内置预置 AI Agent 库(拆任务/专班开箱即有"AI 班底")
- 痛点:拆任务"分配到人"依赖能力名册有数据;真人只能客户自己加、平台预置不了 → 新租户名册空、
  拆出来全是 none、显得不智能。决策:**平台预置一队通用 AI Agent**(代码内置、通用创作/运营方向)。
- 为什么是 Agent 不批量预置 Skill:全局 Skill **每轮注入 system**、预置多了撑爆上下文/乱带节奏;
  Agent 只在被指派/@/绑群时激活,安全;且拆任务的"执行者"正是 Agent。
- 落地:`cosmac/ai/presets.py` 预置 8 个(文案/选题策划/校对润色/数据分析/客服/翻译/调研/社媒),
  每个自带完整人设。`_global_agent_items` 改为「预置打底 + 控制室配置按 slug 覆盖/追加/停用」;
  `_find_global_agent` 改走它 → 能力名册(list_capabilities)、@专班路由、绑群都能解析预置。
  预置是代码内置、不写进控制室,管理员后台保存不会污染;同 slug 可覆盖、enabled=false 可停用。
- 注意(不误导):指派给 Agent ≠ 自动执行;价值是"分配有对象 + 可 @它真干活",自动派单执行仍不做。
- 更新 2 个旧测试(空名册→现含预置)。全量 317 单测通过、ruff 全绿。纯后端→重启 bot。

## 2026-06-30 — 主AI「交互行为准则」基线(让它对含糊指令更聪明)
- 需求:主AI对"建群"这类含糊指令应"先推断+直接做+说假设+给下一步",而不是反问"建什么群"干等。
  这类问题(信息不全)统一靠**行为准则**解决,不是逐个写代码。
- 做法:内置常量 `_INTERACTION_POLICY`,在 `_skill_addendum` **最前段**每轮注入(在管理员人设/RULE
  之上做底;平台硬规则随后注入、优先级更高,不冲突)。准则=①推断意图给默认并直接执行+说假设+给下一步
  ②仅高代价/不可逆/真歧义才问一个问题 ③轻量可撤销动作先做不追问 ④能用工具就调用 ⑤每次给下一步。
- 选码内置而非控制室RULE:控制室只有浏览器管理员能写,这里改不到生产;内置基线则始终生效、可部署可测。
- 更新 2 个旧测试(原假设"无配置 addendum 为空""规则在最前")为新顺序。全量 317 单测通过、ruff 全绿。纯后端→重启 bot。

## 2026-06-30 — 修主AI「建群显示成功却看不到」
- 现象:主 AI 建群回「已成功创建」,但用户频道树里没有新群。根因:`create_room` 工具建房后
  ① 用户只是被 invite(没自动 join) ② 新房没挂进任何工作区(Space);前端频道树按「当前工作区
  的子房间(m.space.child)」过滤——所以服务端房间确实建了(bot 是成员),用户却看不到。
- 修:`_tool_create_room` 成功后复用 `team_created` 信号卡(同 assemble_team)。前端 processTeamCards
  收到会自动 join 新房 + linkRoomToSpace 挂进当前工作区,频道树立刻出现。bot 无权写 Space 的
  m.space.child,故由客户端补这一步(既有机制)。
- 纯后端(tools.py);全量 317 单测通过、ruff 全绿。**只需重启 bot,无需发 dist**。

## 2026-06-30 — 用户「AI 偏好画像」(About me / Outputs)：每个用户自己设置，主 AI 注入
- **背景/需求**:负责人提出要不要给主 AI 做 About_me/Outputs/Templates。核对存量——AI **人设**(控制室/群级 Agent)、模板(onboarding_templates/skills/workflows)都已有；真缺口是**人端**画像：主 AI 对话时并不知道「现在面对的是谁、TA 希望怎样的回答」。定调：只补这一块，且**每个用户自管**。
- **关键架构决策**:画像**不进** per-user account data。原因——bot 注入时要读**别人的**画像，而 Matrix per-user account data 是用户私有、appservice 读不到他人的。故走「浏览器够不到 DB → 经 bot HTTP 端点写、bot 直接读 DB」这套（与个人协作人名册 `cosmac_person` 同套路）。
- **后端**:新表 `cosmac_user_profile`(user_id 唯一 + about/style/extra/enabled)+ `user_profile_repo`(CRUD+渲染，各字段 2000 字硬截断)。bot 端点 `GET/POST /cosmac/profile/me`(本人 token，个人设置不走门控)。注入点 `_skill_addendum`：顺序「平台规则→任务RULE→人设→**用户偏好**→记忆→技能→KB→工作流」，画像**优先级最低**且渲染文案显式声明「仅影响表达、不得违反上述约束」——防 Outputs 字段写「忽略前面规则」式提示注入。跟人走、不分群（与群级 Agent 跟群走正交）。
- **前端**:个人设置弹窗加「AI 偏好」tab(关于我/期望回答方式/补充/总开关)，经 `getMyProfile/saveMyProfile` 真存取。原 mock 的「我的权限/可调用数据」tab 不动（仍是 demo，超出本次范围）。
- **校验**:新增 `test_user_profile`(6 例：repo/截断/渲染/端点鉴权/注入隔离/停用) + 相关回归共 35 例全过；ruff 干净；client `vue-tsc` build 零报错。**端到端（真登录→存→主 AI 真用上）需线上 bot 跑新端点+DB，本地 preview 够不到，靠部署后验证。**

## 2026-06-30 — 撤回客户端换肤，恢复原版 UI
- **背景**:此前一版「GuDuu OS 暖中性换肤」(putty+炭色+lime+Manrope)被另一会话 `git add -A` 连同「图文教程·文章排序/置顶」一起打包进提交 `9d7e8db` 并部署上线。负责人决定撤回换肤、回到原版橙色 UI。
- **做法**:纯换肤文件整体回退到换肤前(`tokens.css`/`reset.css`/`index.html`/`LiveView.vue`/`AdminView.vue`/`CliConsole`/`ProfileHome`/`MembershipModal`/`OnboardingWizard`/`DocReader`)；`DocChannelView.vue` 是混合文件，**只回退 2 行配色、文章排序/置顶功能原样保留**。
- **校验**:源码已无任何换肤残留(Manrope/putty/lime 全清)；`npm run build` 重建 dist 回原版、零报错。
- 待 push + 重新部署 dist 到 `app.cosmac.cc` 后线上恢复原样。

## 2026-06-27 — 修 bot 显示名设置失败(500)
- **现象**:每次 bot 启动日志 `设置显示名失败：500 M_UNKNOWN`;线上查 `@guduu:cosmac.cc` profile 返回 404「No row found」→ 显示名从没设上(客户端里 bot 显示成原始 id 而非「CosMac Star」)。非阻塞、老问题。Synapse 1.153.0。
- **根因判断**:`MatrixClient._url` 给每个请求都追加 `?user_id=@guduu` 伪装参数(代发/建群需要),但**设自己 profile** 走伪装路径在新 Synapse(1.15x) 上会 500;设本人 profile 应直接用 as_token 本体身份、不带 user_id。
- **改法(纯后端)**:`set_displayname` 改为拼裸 URL(不经 `_url`、不带 user_id),仅 Authorization 头鉴权。test_matrix_client.py 加回归(profile PUT 不含 user_id=)。全套 301 通过。
- **真根因(抓 Synapse 端 Traceback 锤定)**:不是 bot 的事。Synapse 1.153 `profile.py::_check_profile_size` 假设 `profiles` 表有该用户行、直接 `row[0]`;但 appservice 用户 `@guduu` **在 `profiles` 表无行** → `row=None` → `TypeError` → 500。去 user_id 那个改动无关(任何走 set_profile_displayname 的请求都撞此崩点,Admin API 也一样)。
- **真修法(一次性 DB,已验证)**:给 `@guduu` 补一条空 profile 行,让 Synapse 正常设名:`INSERT INTO profiles (user_id, full_user_id) VALUES ('guduu','@guduu:cosmac.cc') ON CONFLICT (user_id) DO NOTHING;` → 重启 bot → 日志变 INFO `已设置主 AI 显示名: CosMac Star`,外部 `curl …/profile/@guduu/displayname` 返回 `{"displayname":"CosMac Star"}`(修前 404)。详见 memory `bot-displayname-500-fix`。

## 2026-06-27 — 专班归档前端收尾：已归档频道灰显排后
- 接上昨天后端写的 `cosmac.project.archived` 标记：client.ts 加 `isProjectArchived(roomId)`；LiveView 频道列表把已归档专班**灰显 + 🗄 角标 + 排到最后**（仍可点开查留档）。`channelRooms` 按归档状态排序（在用在前）。
- 纯前端;build 零报错。新 hash index-C_bvJRDB.js。**只发 dist**。
- 顺带核查 P3「看板按模板渲染」:发现看板早已非演示——下排会员/工作流/订单/知识库是 getPlatformStats **真实**数据、社媒区按工作区 `cosmac.social_sources` 配置渲染;唯一占位是社媒卡的粉丝/播放/互动「待接入」,**卡在社媒采集器(需平台 key,同 Stripe 类阻塞)**,非写死 demo 可换。P3 实质已随真实化完成,待采集器再补真数。

## 2026-06-27 — 入驻模板 P2 引导接入：模板真生效（含默认工作流）
- **背景**:核查发现 P2 大部分早已落地——引导向导(`useOnboarding`)选模板后已真建工作区+频道、把人设/RULE/模型/技能写进每个频道 `cosmac.channel_config.persona`、灌知识库；bot 的 `_group_context` 也已读 persona.prompt/model/skill_slugs（之前标 P2b 其实已实现）。**唯一没绑的字段是模板的「默认工作流 workflowSlugs」**。
- **本次补齐**:
  - 前端 `useOnboarding`:OnbPickTemplate/OnbAnswers 加 `workflowSlugs`，fromBackend 映射，pickTemplate 预填，runCreate 把它写进 channel_config 顶层 `workflowSlugs`。
  - bot `_group_context` 读 `cfg.workflowSlugs`→`workflow_slugs`；新 `_preset_workflows_text()` 把 slug 经 `_workflow_defs()` 解析成名字，在 `_skill_addendum` 末尾注入「本工作区预置的工作流，可用 run_workflow 调用」引导（不改权限，只是告知）。
  - 引导确认页加 模型/技能/知识库/工作流 概览行，让用户看清模板真在配东西。
- test_onboarding_binding.py（model/skill/workflow 读取 + 预置工作流解析/跳过缺失 + addendum 注入）。全套 300 测试通过、ruff 干净、前端 build 零报错。新 hash index-YuazBr7J.js。**改了前端+bot → 发 dist + 重启 bot**。

## 2026-06-27 — 专班收尾闭环：节点审核 + 完成度 + 归档关闭 + 清记忆
- **需求**:专班建好后，频道里的项目主AI 要逐个审核每个成员/AI 完成的任务节点，盯住整体完成度；全部完成后提醒是否归档关闭频道，并把项目存进记录、清掉频道的 AI 长期记忆（不浪费 Agent 记忆）。
- **做法(纯后端)**:
  - 新表 `cosmac_project_archive`（goal/summary/任务快照JSON/done·total/archived_by）+ `archive_repo`（create/list，带房间作用域越权防护）。
  - `memory_repo.clear_summary()` 删频道滚动长期记忆，归档后调用。
  - 新工具 `archive_project`（always-on）:汇总本频道任务→落归档记录→清频道记忆→写 `cosmac.project.archived` state 标记→群里贴收尾通知。
  - `list_room_tasks` 加「完成度 X/N」抬头，全完成时提示走归档。
  - 内置项目主AI 人设强化:① 逐个审核节点（update_task 通过/打回）② 盯完成度 ③ 全完成→ask_user_choice 征询→archive_project。
- 新增 test_archive.py（repo/clear/工具全流程）;全套 297 测试通过、ruff 干净。**只重启 bot，无需发 dist**。


## 2026-06-26 — 人员能力对齐用户管理（停用灰显不可设 + 排序）
- **反馈**:人员能力要和用户管理状态对齐；停用账号灰显且不能设置能力；两页默认「在用在前、停用在后」。
- **改法(纯前端)**:peopleRows 带 `deactivated`(来自 listUsers) + 行 `.off` 灰显 + 「已停用」标 + 「设置/编辑能力」按钮对停用账号禁用(startEditPersonForUser 加防御 guard);peopleRows 与用户管理 filteredUsers 都加 `.sort(在用在前、停用在后)`。
- client build OK、preview 零报错。新 hash index-DWpvyZaU.js。**只发 dist**。

## 2026-06-26 — 配额增强·更多计量项 + 我的额度展示
- **增强1·更多计量项**:QUOTA_CATALOG 加 `teams`「专班数」(免费1/付费20/创作者不限,单调计数)、`workflow_runs`「工作流运行/月」(免费0/付费200/不限)。加 track 字段(usage 走计数表 / existing 数存量)。强制:Toolbox 加 `quota_check` 钩子(execute 门控后调)，bot `_tool_quota_check`(assemble_team→teams、run_workflow→workflow_runs)注入。
- **增强2·我的额度**:bot 端点 `/cosmac/usage/mine`(各计量项 已用/上限,usage 类查计数表、existing 类数知识库存量)。前端 client.ts `getMyUsage` + `useMyUsage` + `MyUsageModal.vue`(进度条,超额标红,-1 显示"不限");入口用户菜单「我的额度」。QUOTA_CATALOG 前端补齐 4 项(后台「用量配额」也自动多出 teams/workflow_runs 可配)。
- **测试**:test_quota 加 工具配额(teams 撞墙)/usage 端点 用例。292 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**。新 hash index-DzPJ7XX-.js。

## 2026-06-26 — 变现第二步·用量配额系统（订阅真引擎）
- **背景**:门控管"能不能用",配额管"能用多少"——免费版撞墙才升级,这是订阅主要付费驱动。开工第二步。
- **引擎**:新建 `cosmac/quotas.py`(QUOTA_CATALOG 计量目录 + `QuotaStore` 读控制室 cosmac.quotas 配额配置,带 TTL 缓存,-1=不限) + 新表 `cosmac_usage`(user+metric+周期键累计) + `db/quota_repo.py`(period_key/get_count/incr)。两类指标:rate(按天/月计数)、total(数现有存量)。
- **强制**(bot `_quota_limit`/`_rate_quota_blocked`,管理员永远不限):
  - `ai_msg_daily`「AI 对话/天」(默认免费 30、付费/创作者不限):`_handle_event` AI 路径超额停在这、不耗 LLM、提示升级。
  - `kb_docs`「知识库文档数」(免费 5、付费 200、创作者不限):`handle_kb_add` 按 tier 限(替换原硬上限,留系统硬顶兜底)。
- **后台 UI**:新增「用量配额」tab(计量项×等级 数字表,-1=不限,写控制室 cosmac.quotas);client getQuotas/setQuotas + QUOTA_CATALOG。
- **测试**:新增 test_quota.py(repo 增计/周期键 + QuotaStore 默认/覆盖 + bot 强制:撞墙拦/管理员不限/付费不计)。290 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**(新表 create_all 自动建)。新 hash index-Dw-PoBVt.js。
- **后续**:更多计量项(专班数/工作流次数/工作区·成员数)按引擎补;前端"今日额度 X/Y"展示按需加。

## 2026-06-26 — 变现第一步续·个人协作人设为付费
- 新增权限 `people_manage`「个人协作人名册」默认付费 + 在 `handle_people_add` 强制(查看/删除自己数据不拦，同知识库做法，只对"添加/更新"增值动作收费)。前后端 GATE_CATALOG 各加。test_person 加门控用例。
- 283 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**。新 hash index-BmIJJRfR.js。

## 2026-06-26 — 变现第一步续·自定义技能设为付费
- 又找到一个高价值未门控功能：`技能 添加/删除…` 聊天命令(用户建自己的 AI 技能)。新增权限 `custom_skill`「自定义技能」默认付费 + 在 `_try_handle_command` 技能命令分支强制(低于门槛提示升级)。前后端 GATE_CATALOG 各加。
- 282 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**。新 hash index-B0m_Ftj3.js。

## 2026-06-26 — 会员变现第一步·功能分层（付费才有意义）
- **背景**:负责人指出"权限太少、用户没理由付费"。讨论定两条腿:① 把值钱功能设付费(本次)② 用量配额(下一步待定)。
- **第一步(本次)·把头牌功能设成付费**:
  - 改默认:`assemble_team`(一键建专班)、`task_board`(AI 拆任务)、`web_search`(联网) → **付费**;免费版保留 ai_chat/knowledge/create_room。
  - 新增权限项 `memory`「长期记忆（AI 跨多轮/跨天记得你）」**默认付费 + 服务端强制**:`_memory_context`/`_maybe_update_memory` 按 sender 过 memory 门控——低于门槛不注入也不积累长期记忆。
  - 价值主张:**付费 = AI 帮你组队建专班 + 拆任务 + 联网 + 记得你**;免费=基础对话/建频道/知识库。admin 可在后台逐项再拨。
- **测试**:test_memory 适配签名(+sender)+ 放行门控 + 加"免费用户不注入记忆"用例;282 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**。新 hash index-x6FD3W2t.js。
- **下一步(第二步,待负责人定)**:用量配额系统(计数+按 tier 强制+撞墙提示)——真正的订阅引擎。

## 2026-06-26 — 会员权限扩充 + 分类（覆盖新功能）
- **需求**:做了这么多功能，会员权限要增项 + 分类。
- **改法**:GATE_CATALOG 给每项加 `group` 分类字段，并补 2 个新权限项（覆盖本期任务编排功能）：
  - `task_board`「AI 拆解任务到看板」(默认免费)、`assemble_team`「一键建专班（AI 组队+派单）」(默认免费，原合并在 create_room 下、现独立)。
  - 分类：**AI 对话与检索**(ai_chat/knowledge/web_search)、**任务编排与协作**(create_room/task_board/assemble_team)、**自动化**(workflow_run)。
- **后端强制**:`_TOOL_GATE_MAP` 改 assemble_team→assemble_team(独立)、create_tasks→task_board(新);默认免费=零回归，admin 可在后台调成付费/创作者/仅管理员。前后端 GATE_CATALOG 各加一份(同步)。
- **后台 UI**:会员权限表按 group 分组展示(加分类标题行)。
- **测试**:281 通过、ruff 全绿、client build OK。**发 dist + 重启 bot**。新 hash index-CEt96ewb.js。

## 2026-06-26 — 会员等级下拉加「管理员」最高档
- **需求**:会员等级下拉里加上「管理员」(Admin=管理员)。
- **改法(纯前端)**:用户管理「会员等级」下拉做成统一等级选择器 免费<付费<创作者<**管理员**。下拉值:是服务器管理员→显示管理员，否则显示会员档。`onLevelChange`:选「管理员」→ setUserAdmin(true);选某会员档→若原是管理员先撤管理员(setUserAdmin false)再写会员等级。复用现有 setMemberTier/setUserAdmin;角色列+设/撤管理员按钮保留(与下拉同步)。加 .adm-tier.admin 紫色样式。
- client build OK、preview 零报错。新 hash index-BjIEvRjz.js。**只发 dist**。

## 2026-06-26 — 后台列表页补上筛选（不只搜索）
- **反馈**:上一条只做了搜索、没做筛选。
- **改法(纯前端)**:`useListSearch` 扩展支持可选 `extraFilter` 判定;新增 `useEnabledFilter`(启用/停用通用筛)。各列表页加对应筛选下拉：频道=类型(公开/私有)、技能/智能体/模板/工作流/套餐=启用/停用、人员能力=已设/未设能力。搜索 + 筛选叠加生效。用户管理本就有角色/会员/状态筛。
- client build OK、preview 零报错。新 hash index-JXyXakee.js。**只发 dist**。

## 2026-06-26 — 后台所有列表页都加搜索（不只用户管理）
- **反馈**:后台几个列表页都要能搜，不只用户管理。
- **改法(纯前端)**:抽通用 composable `useListSearch(source, textOf)`(query ref + filtered 计算)，给后台 **7 个列表页**都加搜索框 + "N/总M"计数：用户管理(已有搜+角色/会员/状态筛)、频道管理、技能库、智能体、人员能力、入驻模板、工作流、会员套餐。各页按各自字段搜(名/slug/key/说明/平台等)。AI配置/规则/会员权限是配置页、非长列表，不加。
- client build OK、preview 零报错。新 hash index-BvQ7BHfU.js。**只发 dist**。

## 2026-06-26 — 后台用户管理加搜索+筛选（用户多了能定位）
- **反馈**:用户多了后台「用户管理」没法搜/筛，找不到人。
- **改法(纯前端)**:用户管理表上方加筛选条——搜索框(匹配用户名/ID) + 角色(全部/管理员/成员) + 会员等级(全部/各档) + 状态(全部/正常/已停用) 三个下拉，`filteredUsers` 计算属性即时过滤;显示"N/总M"计数;无匹配给空态提示。筛选维度就是表里已有的"标签"(角色/会员/状态)。
- 后端不变。client build OK、preview 零报错。新 hash index-cSPG55GE.js。**只发 dist**。
- 备注:自定义标签(admin 给用户打任意 tag)是更大改动(要存储)，本次用现成属性筛选覆盖"找不到人"的核心需求；真要自定义 tag 再单做。

## 2026-06-26 — 「我的协作人」补回手动添加（已有联系人直接设/新人也能加）
- **反馈**:同步联系人之外，还要能手动「添加」一个还不是联系人的新人。
- **改法(纯前端)**:useMyPeople 加 `adding` 标志 + `startAdd()`：新增模式下 user_id 可编辑(走 normalizeUserId 容错)，编辑已有联系人则 user_id 固定。MyPeopleModal 列表上方加「＋ 添加协作人」按钮；编辑表单按模式显示可编辑输入或固定标签。两条路并存。
- 后端不变。client build OK、preview 零报错。新 hash index-CX8cSBqj.js。**发 dist**(后端无变化、bot 已是最新可不重启)。

## 2026-06-26 — 改进·「我的协作人」同步联系人（不再单独敲 id）
- **反馈**:我的协作人不该单独拉人/敲 id，应从"已加的朋友/联系人"里自动出现，只补能力。
- **改法(纯前端)**:client.ts 加 `listMyContacts()` —— 遍历 `mx.getRooms()` 收集与本人**共处一群/私信**的所有人(去重、排除自己和中枢AI、排除 Space)，这就是"已加的朋友"。`useMyPeople` 改为合并 `listMyContacts()`(联系人) + `myPeopleList()`(已填能力)：表格**列出所有联系人**，每行叠加其能力(已设/未设)，编辑时 user_id 固定取自联系人。已填能力但已不在联系人里的也补显示，避免看不到。去掉自由敲 id 的"添加协作人"，改成每个联系人"设置能力"。
- 后端不变(仍 cosmac_person + /cosmac/people/* + list_capabilities 合并)。
- **测试**:client build OK、preview 零 console 报错。新 hash index-BK6OIqZB.js。**发 dist + 重启 bot**(配合上一条的后端端点)。

## 2026-06-26 — 新增·普通用户的「我的协作人」能力名册（个人级）
- **需求**:普通用户(非 admin)也想给自己常合作的人加能力备注，但 admin 的「人员能力」写控制室、普通用户够不到。负责人定**个人级 v1**:每人维护自己的协作人名册。
- **后端**:新表 `cosmac_person`(按 owner 隔离, create_all 自动建);`db/person_repo.py`(list/upsert/delete);bot 3 个端点 `/cosmac/people/{mine,add,delete}`(本人 token 鉴权、owner=本人);`_personal_people_items(owner)` 读 DB;`list_capabilities` 把 **admin 全局名册 + 下达者个人名册合并去重** —— 主AI 给某用户拆任务时就能用上 TA 自己加的人。**隔离**:A 的个人协作人 B 看不到(单测验证)。
- **前端**:client.ts `myPeopleList/Add/Delete`;`useMyPeople` 单例 + `MyPeopleModal.vue`(列表/增改删, 用户名走 normalizeUserId 容错);入口在**用户菜单「我的协作人」**(普通用户可见, 非 admin 后台)。
- **测试**:新增 test_person.py(repo 增改删/owner隔离 + 端点鉴权/合并/跨用户隔离);281 通过、ruff 全绿、client build OK。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。新 hash index-XgaFVwzP.js。

## 2026-06-26 — 改进·人员能力页同步真实账号（不再重敲 user_id）
- **反馈**:人员能力页让你重新敲一遍 user_id 填备注，应该直接同步「用户管理」的真实账号。
- **改法(纯前端)**:人员能力页改为 `listUsers()`(真实账号) + `getPeople()`(能力名册) 合并展示——**表格列出所有真实账号**(排除中枢AI)，每行叠加其能力备注(角色/擅长)，未设的标"未设"。编辑时 **user_id 固定取自账号、只读不可改**，只填 角色/擅长/备注/启用;保存写回 cosmac.people。去掉了"添加成员"(自由敲 user_id)，改成每个账号"设置能力/编辑能力";"清除"只移除能力备注、不删账号。
- 数据格式不变(仍 cosmac.people {user_id,name,role,expertise,note,enabled})，bot 读取逻辑零改动。
- **测试**:client build OK、preview 零 console 报错。**纯前端**——只发 dist。新 hash index-CI1XrAjW.js。

## 2026-06-26 — 修复·后台新建用户输入 @ 前缀建不了账号
- **问题**:后台「用户管理→新建用户」输入 `@wenan`(带@)建不了账号。根因:`normalizeUserId` 逻辑是"以 @ 开头就原样返回"，于是 `@wenan`(缺 `:域名`)被原样当成完整 id → 非法 Matrix ID → Synapse Admin API 400。
- **修法(纯前端)**:`normalizeUserId` 改为容错——去前导 @ → 没冒号补本服务器域名 → 补回 @。`@wenan`/`wenan`/`@wenan:cosmac.cc` 都规范成 `@wenan:cosmac.cc`。顺带 createUser 默认显示名用干净 localpart(不再是 `@wenan`)。影响所有 normalizeUserId 调用方(建用户/邀请成员)，都变更健壮。
- **测试**:client build OK、preview 零 console 报错。**纯前端**——只发 dist,不用重启 bot。新 hash index-DuE3bPaw.js。

## 2026-06-26 — 修复·bot 建的专班挂进当前工作区（频道树可见）
- **问题**:线上实测——中枢AI 确实建了专班，但**左侧工作区里看不到这个频道**。根因:bot 建的是裸房间，没写 `m.space.child`(频道挂工作区的关系);而写它要在「工作区房间」里有权限，**bot(@guduu) 不在用户的 Space 里、写不了**;客户端(用户)在 Space 里有权限。
- **修法(bot 发信号 + 客户端补挂)**:
  - **后端**:assemble_team 建完专班，往发起人所在房间(DM)发一张 `cosmac.card{kind:'team_created', team_room, project}` 信号卡。
  - **前端**:client.ts 加 `linkRoomToSpace(spaceId, roomId)`(join + 写 m.space.child/parent);LiveView `processTeamCards()` 在 refresh 时扫到 team_created 卡 → 把新专班**自动挂进当前工作区**(linkedTeams 去重)→ 刷新使其出现在频道树;并渲染"✅ 专班已建好，进入专班 →"卡片(enterTeam 按钮兜底再挂一次+打开)。
- **顺带说明**(非本次改):线上"选择卡没弹"是因为**人员能力名册还没人**——AI 没东西可选只能打字问"邀请谁";后台加了人之后,AI 调 ask_user_choice 才有内容可弹。
- **测试**:test_assemble_team 加 team_created 卡断言;278 通过、ruff 全绿、client build OK。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。新 hash index-BkFIHbPb.js。

## 2026-06-26 — 健壮性·建专班邀请尽力而为（坏 id 不搞崩）
- **背景**:测试时发现——assemble_team 把所有成员一股脑塞进 createRoom 的 invite，万一某个 user_id 不存在(如还没注册的测试人员)，整个建房可能失败、专班建不出来。
- **修法**:`invite_user` 改为**返回 bool + 吞网络异常**(不抛);`assemble_team` 改为**只用发起人(必然存在)建房，其余成员逐个 invite_user 尽力邀请**——某个邀不到只记进 failed、不影响专班建成;开班消息与回灌**如实**告知"邀到 N 人 / X 人没邀到(账号可能不存在)"，不假装都拉进来了。
- **副作用收益**:这样名册里即便有还没注册的人(纯画像)，也能正常建专班测试；生产上用户填错一个 id 也不至于整件事崩。
- **测试**:test_assemble_team 改邀请断言 + 加 test_failed_invite_does_not_break_team;278 通过、ruff 全绿。**纯后端**——无需发 dist,只 `restart guduu-bot`。

## 2026-06-26 — 收口·create_tasks/assemble_team 分工（防任务重复登记）
- **背景**:完整流程模拟暴露——主AI 若先 create_tasks(任务落原对话)再 assemble_team 带 tasks(任务落专班)，会**重复登记两份**、一份成孤儿。
- **修法(方案A,纯提示词)**:改两个工具的 description 把分工讲清——要拉团队/建专班的目标**直接用 assemble_team**(tasks 一并带上)，create_tasks 只用于"不开专班的轻量待办"，且两者互相点名"别对同一目标都调"。零代码风险、零回归。
- **测试**:相关套件 36 通过、ruff 全绿。**纯后端**——无需发 dist,只 `restart guduu-bot`。

## 2026-06-26 — 验证编排链 + 交互增强·选择卡 ask_user_choice
- **验证结论（已留档、测试脚本已删）**:
  - **逻辑层**:写了 e2e 脚本(假 client+真内存DB)模拟主AI 走完整链，6 阶段全对(名册→拆解+类型化指派→建专班+写channel_config→审核回填→任务RULE注入→多AI@名路由)。脚本验证完已删(run/ 本是 gitignored)。
  - **智能层(线上真模型 DeepSeek)**:负责人在线上 bot 实测——一句"办新品发布会，要文案/设计/现场统筹，把团队拉起来分任务"，bot **真建出「新品发布会专班」频道 + 拆出 3 个对口任务**(文案/设计/现场统筹)，且**没瞎编不存在的人**(名册空→克制地反问邀请谁)。证明：真模型会主动调编排工具、理解到位、不臆造。✅ 真智能、非背稿。
  - 全量单测 277 通过(需 COSMAC_PAY_MANUAL_SECRET 才跑 trading 那批)。
- **交互增强·选择卡**(负责人反馈"该让用户点选而非打字"):
  - **后端**:新增主AI 工具 `ask_user_choice(question, options[], multi)` → 发 cosmac.card{kind:'choice'} 富卡(纯文本兜底);_ALWAYS_ON。
  - **前端**:新组件 `components/chat/ChoiceCard.vue`(单选点即发 / 多选选完点"确定");LiveView 频道与中枢AI 面板的卡片渲染都加 `kind==='choice'` 分支;`pickChoice` 把选择作为用户消息发回房间、对话继续(同打字效果)。
  - 已知小边界:频道里点选发的是普通消息(bot 仅被 @ 才答);主用例是 DM 中枢AI 编排，正常生效。
- **测试**:test_agent_tools 加 ask_user_choice(发 choice 卡/选项正确);工具集断言 12→13。277 通过、ruff 全绿、client build OK。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。新 hash index-CauOMoIi.js。

## 2026-06-26 — 模块3.5 档3b·专班多AI 的 @名路由（纯后端，模块3.5 收官）
- **做了什么**:让"拉多个AI 进专班"真正生效——专班里点名某个绑定的协作 Agent（按 slug 或显示名匹配正文），就由该 worker 以自己的人设/技能/模型接这条；没点名则维持 lead（项目主AI）。这样编剧Agent/分镜Agent 能在同一专班各自接活。
- **实现**:`_group_context` 多带 `worker_slugs`(频道 channel_config.agentSlugs);`_apply_worker_routing(text, gctx)` 在正文里匹配 worker 名/slug，命中就换其人设/技能/模型回这条，**任务RULE 不变**(worker 仍受专班约束);`_handle_event` 在算 addendum 前调一次。方案A(单 bot 多人设，worker 非独立 Matrix 账号)。
- **决定不做 档4b(workflow 自动回填)**:项目主AI 已能用 `run_workflow` + `update_task` 两步手动闭环(跑工作流→拿结果→回填任务)，自动链接属过度设计(够用即止)，需要时让 AI 组合现有工具即可。
- **测试**:TestWorkerRouting(点名换人设/没点名维持lead/非专班不路由)。276 通过、ruff 全绿;10 失败仍是 manual 支付缺 env、无关。
- **部署**:**纯后端**——无需发 dist,只 `restart guduu-bot`。
- **🎉 模块3.5「AI 任务编排 + 能力名册」全部完成**:档1能力名册 / 档2类型化执行者 / 档3一键建专班(任务RULE约束项目主AI) / 档4派单+审核回填 / 档3b多AI@名路由。下一步可选:部署端到端验证 或 回补模块4 真实支付。

## 2026-06-26 — 模块3.5 档4·派单+审核回填（编排闭环收尾，纯后端）
- **做了什么**:给项目主AI 两个工具来跑"跟踪 + 审核回填"，**编排核心闭环到此完整**(拆解→匹配→建专班→跟踪+审核回填)。
- **`list_room_tasks`**:列当前频道的任务(含编号id/状态/执行者/结果)，项目主AI 跟踪进度或审核前先看清有哪些任务、到哪一步。
- **`update_task`**:更新当前频道某任务的 status/result/progress，用于推进与**审核回填**——执行者交付→done+result填交付;审核通过→done;审核打回→doing+result写打回原因。**越权防护**:只能改 room_id==当前频道 的任务(项目主AI 碰不到别的专班看板)。
- 两个工具 _ALWAYS_ON、无单独门控(走 ai_chat 入口闸);复用现有 task_repo.get_task/update_task(done 自动补进度100)。
- **审核终审权**:这版是 AI 用 update_task 直接判;人终审仍可在看板手动拖卡覆盖(memory 记的"AI初审+人终审"默认靠看板兜底,需要更强的"待人确认"态再加状态值)。
- **未做(档4b,可选)**:executor=workflow 的自动回填(run_workflow 跑完回调直接写对应 task，需让 run_workflow 带 task_id 链接)。
- **测试**:test_assemble_team.py 加 TestTaskReviewTools(列任务/审核通过done补满/打回doing+批注/**跨频道越权被拒**);工具集断言 10→12。273 通过、ruff 全绿;10 失败仍是 manual 支付缺 env、无关。
- **部署**:**纯后端**——无需发 dist,只 `restart guduu-bot`。
- **模块3.5 进度**:档1能力名册✅ 档2类型化执行者✅ 档3一键建专班✅ 档4审核回填✅(核心闭环完整);仅可选 档3b(worker @名路由)/档4b(workflow自动回填) 待定。

## 2026-06-26 — 模块3.5 档3·一键建专班 assemble_team（纯后端）
- **做了什么**:把"建频道+拉人+绑AI+装任务RULE/技能+派单"串成主AI 的**一个工具调用**——拆完任务后真的把团队拉起来。这是编排"动起来"的关键一刀。
- **assemble_team 工具**:① create_room(项目名,邀请发起人+成员) → ② 写 channel_config:persona(给了 lead_agent 用其 agentSlug,否则用内置"项目主AI 编排人设")+ agentSlugs(协作 Agent)+ taskRule + skill_slugs → ③ create_tasks 把子任务派进新专班(作用域=新房间) → ④ 发开班消息。门控走 create_room、_ALWAYS_ON 默认常开。成员/Agent/技能都来自 list_capabilities。
- **任务RULE 真生效（项目主AI 的缰绳）**:`_group_context` 读频道 `cfg.taskRule`;`_skill_addendum` 注入顺序改为 平台规则→**本专班任务RULE**→人设→长期记忆→技能→知识库(任务RULE 优先级高于人设)。这样专班里的项目主AI 被频道任务RULE 约束、围绕本项目分配与审核——正是负责人要的"群里有主AI、但只围绕这个任务的RULE 行事"。
- **未做(记为档3b)**:协作 worker Agent 的 @名路由——现在只有 lead(项目主AI)接话;worker agents 已存进 channel_config.agentSlugs,但响应时还不会按 @名切换到对应 worker 人设。留待档4 或单独做(方案A 路由)。
- **测试**:新增 test_assemble_team.py(全量装配/无lead用内置人设/缺名字拒绝/group_context读taskRule/addendum注入且优先级高于人设);工具集断言 9→10。269 通过、ruff 全绿;10 失败仍是 manual 支付缺 env、无关。
- **部署**:**纯后端**(只动 cosmac/)——**无需发 dist**,只 `restart guduu-bot`。
- **下一步**:档4 派单+审核回填(执行者交结果→项目主AI 按任务RULE 审核→通过/打回;工作流复用异步回调;update_task 回填) + 可选档3b worker @名路由。

## 2026-06-26 — 模块3.5 档2·拆任务的类型化执行者匹配
- **做了什么**:把拆出来的子任务从"自由文本负责人"升级成**类型化执行者**——主AI 读能力名册(档1)后，给每条子任务标清"谁来干、怎么干"，为档3 派发铺路。
- **后端**:Task 模型加 `executor_kind`(human/agent/workflow/none) + `executor_ref`(@user/agent-slug/workflow-slug) 两列;engine `_heal_business_schema` 给旧 cosmac_task 补这两列(非破坏);task_repo.create_tasks 收并校验(非法 kind/none 一律回落 none 且清空 ref，防悬空引用);create_tasks 工具 schema 加这两字段 + 说明"**先调 list_capabilities** 看有谁可用再按能力指派，拿不准用 none 别臆造";handle_tasks_list 返回 executor。
- **前端**:TaskItem 加 executor 字段;任务看板卡片显示执行者小标签(👤真人/🤖AI/⚙工作流)。
- **边界提醒**:档2 只是"**记录**指派"(任务卡知道该派给谁)，真正"**派出去执行 + 审核回填**"是档3(一键建专班 assemble_team)/档4。
- **测试**:新增 test_task_repo.py(类型化存取/非法回落/none清ref/旧式兼容)。264 通过、ruff 全绿;10 失败仍是 manual 支付缺 env、无关。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。新 hash index-Dso5cHq8.js。新列靠 _heal_business_schema 自动补、无需手动迁移。
- **下一步**:档3 一键建专班 `assemble_team`(建项目频道→拉人+绑多Agent(lead=项目主AI)→装 room 级任务RULE/Skill→关联KB→派单)。

## 2026-06-26 — 模块3.5 开工·能力名册（档1；AI 任务编排地基）
- **背景/设计**:负责人敲定模块3.5「AI 任务编排 + 能力名册」(企业通用,非影视)。主AI 拆任务→读"能力名册"匹配执行者→一键建专班(项目级频道+拉人+多AI+room级RULE/KB/Skill)→派单+审核回填。**两层主AI**:全局中枢AI 拆解+建专班;每专班的项目主AI 被频道任务RULE约束、只做分配+审核。完整设计基线 + 进度追踪存 memory `task-orchestration-design`。
- **本次做了档1「能力名册」**(地基:让主AI 拆任务时"知道找谁",不再凭空编负责人):
  - **后端**:新增 `cosmac.people` state event(admin 写、bot 读,同 skills/agents 套路);bot `_people_items`/`_global_agent_items`/`_kb_doc_titles` 读四类资源;`_list_capabilities_for_tool` 聚合 真人+AI Agent+Skill+知识库(各带能力备注)成名册文本;主AI 新工具 **`list_capabilities`**(注入 Toolbox、_ALWAYS_ON 默认常开),工具说明要求"拆任务/分配前先调它"。
  - **后台 UI**:AdminView 新增「人员能力」tab——admin CRUD 成员能力备注(用户ID/显示名/角色/擅长/备注/启用),client `getPeople/setPeople` 写 `cosmac.people`。
- **决策记录**:①一个项目一个专班频道 ②真人profile由admin填存cosmac.people ③一频道可多AI(路由方案A:@Agent名,不点名 lead接话) ④审核终审权默认"AI初审+人终审"。暂缓:方案B(每Agent独立账号)、持续编排DAG。
- **测试**:新增 test_capabilities.py(名册聚合/停用过滤/空名册)+ test_agent_tools(工具转发/降级/默认常开);更新 runtime_config 工具集断言(8→9)。260 通过、ruff 全绿;10 失败仍是 manual 支付缺 env 既有问题、无关。
- **部署**:动了 client(AdminView+client.ts)+ cosmac → **发 dist + 重启 bot**。新 hash index-CJKTruqG.js。
- **下一步**:档2 匹配(拆解时主AI 读名册标 executor_kind+ref,assignee 升类型化)→ 档3 一键建专班 assemble_team → 档4 派单+审核回填。

## 2026-06-26 — 模块2增强·流式体感「正在输入…」（增量③，typing 方案）
- **背景**:③ 之前因"自研客户端没有 typing 渲染"暂缓;既然 ⑤a 已在动客户端,顺手用 typing 方案把 ③ 收掉(非编辑流打字机——那个刷屏留痕、性价比差)。
- **做了什么**:主 AI 回复慢路径(LLM 生成/工具调用可达数秒)期间显示"正在输入…"三点跳动气泡,长回复不再死寂。
- **后端**:matrix_client 加 `set_typing(room, bool)`(带 30s timeout,崩了也自动过期);`_handle_event` 的 Agent 慢路径用 **try/finally** 包起来——进生成前开、发完/异常都关,绝不卡住输入中状态(命令快路不显示、无谓)。
- **前端**:client.ts 加 `onTyping`(监听 matrix-js-sdk 'RoomMember.typing')+ `roomTyping(roomId)`(房间内有别人在输入;中枢 AI 私聊里=bot 在输入);LiveView 订阅(afterLogin 挂、onBeforeUnmount 解绑)→ `botTyping` ref → AI 面板渲染跳动三点气泡 + 出现时滚到底。
- **关键决策**:只在中枢 AI 面板(1:1 等回复最焦虑处)渲染;频道里的 typing 留作易扩展的后续(roomTyping 已通用)。typing 是 best-effort 体验增强,失败只记日志、绝不影响回复。
- **测试**:新增 `test_typing.py` 2 个(正常路径先开后关 + **生成抛异常也靠 finally 关掉**);客户端 build 通过(新 hash index-C64yVQ1L.js)、preview 零 console 报错。255 通过、ruff 全绿;10 失败仍是 manual 支付缺 env 既有问题、无关。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。
- **路线收官**:问答智能增强 5 项落 5 项(① 检索工具化 ② 联网搜索 ③ 流式体感 ④ 长期记忆 ⑤a 上传UI);仅 ⑤b pgvector 按规模暂缓。

## 2026-06-26 — 模块2增强·知识库上传 UI（增量⑤a；⑤b pgvector 暂缓）
- **做了什么**:之前知识库只能靠聊天命令「知识 添加/删除」维护;现在给个**界面**——AI 侧栏「知识库」面板加「管理」按钮,打开弹窗可贴标题+正文入库、列出、删除(个人库 scope=user,bot 在该用户任何房间检索 RAG 都会带上)。
- **后端**:个人库 CRUD 端点 `/cosmac/kb/{add,delete}`(list 已有、补返回 id);`handle_kb_add`(knowledge 门控+字数/数量上限+真实成功失败)、`handle_kb_delete`(**越权防护**:只能删 scope=user 且本人的文档,删不到群库/别人的);OPTIONS 预检放开 `/cosmac/kb/`。
- **前端**:`client.ts` 加 kbAddMine/kbDeleteMine(kbListMine 补 id);新 composable `useKnowledge`(模块级单例,docs 是「项目文件」面板与管理弹窗**共用的唯一来源**,增删两处同步);新组件 `KnowledgeModal.vue`(贴文本入库+列表+删除);LiveView 接进去(面板「管理」按钮、挂载弹窗、kbDocsMine 改用单例)。
- **关键决策**:v1「上传」=贴标题+正文文本(文件解析 PDF/docx 留后续);删自己的数据不设门控(用户随时能清理);⑤b pgvector **暂缓**——当前几篇文档 Python 余弦完全够用,pgvector 是过早优化,等知识库真上量再做(同其它"已知边界")。
- **测试**:新增 5 个 HTTP handler 测试(登录/空正文/带id列表/越权删除404/门控403);客户端 build 通过(新 hash index-Dq2-3nAk.js)、preview 启动零 console 报错。253 通过、ruff 全绿;10 失败仍是 manual 支付缺 env 既有问题、无关。
- **部署**:动了 client + cosmac → **发 dist + 重启 bot**。

## 2026-06-26 — 模块2增强·群级长期记忆（增量④，跳过③）
- **为什么跳过③流式回复**:查了自研客户端——**没有 typing 渲染**(发输入信号只有 Element 能看到、自家客户端看不到),而**编辑流打字机**(m.replace)会刷屏+时间线永久留 N 个编辑事件+"已编辑"标记,性价比差。负责人拍板:跳过③先做④;③留到下次顺手碰客户端时用 typing 方案(需给客户端加 typing 渲染)。
- **做了什么(增量④)**:给主 AI **群级长期记忆**——短期记忆只读最近 ~12 条,跨多轮/跨天就"忘了";现在每个房间存一份**滚动摘要**,每轮回复注入 system(AI 就"记得"),**每 8 轮后台用 LLM 重摘要一次**(攒一批再摘、省调用)。
- **实现**:① 新表 `cosmac_conversation_memory`(派生数据,原始聊天记录仍在 Synapse 不重存;create_all 自动建表、无需迁移);② `db/memory_repo.py`(get_summary/bump_and_check/save_summary,**计数到阈值当场清零**保证并发只触发一次);③ bot 侧 `_memory_context` 注入(顺序 规则→人设→**长期记忆**→技能→知识库)+ 回复发完调 `_maybe_update_memory`,到阈值就 `submit_background`(fast 池)后台摘要,**绝不阻塞回复**;④ echo 占位后端跳过摘要(回显摘不出东西、反污染)。
- **关键决策**:摘要走后台线程不阻塞用户回复;摘要器用全局 LLM(非 per-group 模型);全程兜异常+DB 懒导入,没装 DB/出错静默跳过、绝不影响回话。**无新门控、无客户端改动**(属 ai_chat 体验)。
- **测试**:新增 `test_memory.py` 10 个(repo 计数/清零/写回 + bot 注入/echo跳过/后台摘要落库,后台池同步化后断言)。248 通过、ruff 全绿;10 失败仍是 manual 支付缺 env 的既有问题、无关。**纯后端、无需发 dist;部署=重启 bot**。
- 下一步:⑤ 知识库上传UI + pgvector(需 pgvector,涉及客户端上传界面)。

## 2026-06-26 — 模块2增强·联网搜索工具 web_search（增量②）
- **做了什么**:给主 AI 加"会上网查"的 `web_search` 工具——问到知识截止之后/需要最新外部信息时，模型自己联网检索，返回标题+链接+摘要据此作答。
- **可插拔 + 无 key 自动降级**(照搬 LLM/embeddings 一贯做法,所以**不需要预先拍板服务商**):新建 `cosmac/ai/websearch.py` 抽象,内置 **Tavily**(默认,专为 Agent 设计)+ **Brave** 两家;`COSMAC_SEARCH_PROVIDER` 选家、`COSMAC_SEARCH_API_KEY`(或各家专用 TAVILY/BRAVE_API_KEY)给 key;没 key → `DisabledSearcher`,工具明确回"未配置"、绝不报错。新增一家只需加个子类。
- **门控**:联网搜索走外部 API、共享凭据有成本,新增 `web_search` 能力,**默认仅管理员**(同 run_workflow 思路);GATE_CATALOG 前后端各加一条(members.py + client.ts);_TOOL_GATE_MAP 映射 + 工具 `_ALWAYS_ON` 默认常开(门控+降级双保险,不靠工具开关拦)。
- **激活方式**(上线后按需):服务端设 `COSMAC_SEARCH_API_KEY`(Tavily 注册即得免费额度) → 后台「会员权限」把 web_search 门槛按需下调 → 主 AI 即可联网。
- **测试**:新增 `test_websearch.py`(provider 选择/无 key 降级/Tavily+Brave 解析/错误兜底)+ 工具默认常开/未配置降级;更新 runtime_config 工具集断言(7→8)。228 通过、ruff 全绿;10 个失败仍是 manual 支付缺 env 的既有问题、无关。
- **部署**:动了 client.ts(GATE_CATALOG)→ **需发 dist**(新 hash index-9QDMrb4b.js)+ 重启 bot。
- 下一步:③ 流式回复。

## 2026-06-26 — 模块2增强·知识库检索工具化（search_knowledge）
- **背景**:核对"注册后 AI 能否像 Claude Code 那样问答"——链路已通(注册→引导写频道人设→bot 读人设回应)、真·ReAct Agent、短期记忆、RAG 自动注入都在;线上模型已接 **DeepSeek(走方舟/ARK)**、非 echo。负责人定下一步"问答智能增强"逐项推,先做最高性价比且零新依赖的一项。
- **做了什么(增量①)**:把知识库 RAG 从"每轮盲塞参考资料"升级为**模型可主动调用的 `search_knowledge` 工具**——AI 自己决定何时查、用什么词查、可多次深挖(Claude-Code 式问答的核心手感)。**保留**原自动注入做 baseline,二者互补(自动给底、工具深挖)。
- **实现**:① bot 抽出共享检索 `_kb_retrieve`(本群+个人库、session 内物化 title/text 防惰性加载报错),`_kb_context`(自动注入)与 `_kb_search_for_tool`(工具)都复用它,避免两份逻辑漂移;② 仿 `dispatch_async`/`gate_check` 注入模式,新增 `Toolbox.kb_search` 回调(检索逻辑/embedder/DB 留 bot 侧、Toolbox 保持薄);③ 注册只读工具 `search_knowledge`,挂 `knowledge` 门控(与「知识」命令、RAG 同闸),设为 `_ALWAYS_ON` 默认常开(旧 AI 配置白名单没有它、不放这会被当禁用)。
- **关键决策**:不删自动注入——DeepSeek 工具调用可靠性未实测,留 baseline 防"模型不调工具→KB 失灵";门控集中在 execute 的 gate_check、工具执行体不重复判。
- **测试**:新增 5 个(工具转发/未注入兜底/默认常开 + bot 侧检索命中/无命中);更新 3 个 runtime_config 工具集断言(多了 search_knowledge)。相关套件全过、ruff 全绿。trading 9 错是缺 env 的既有问题、无关。**纯后端、无需发 dist;部署=重启 bot**。
- **下一步队列**(都属模块2增强,逐个推):② 联网搜索 `web_search`(需选搜索服务商+key)③ 流式回复 ④ 长期记忆/对话摘要 ⑤ 知识库上传UI+pgvector。

## 2026-06-26 — 代码审查·第五批（私聊装哑 / 事务重发二重回复 / 工作流池满残留）
- 又一轮整体审查(后端 bot/AI + DB/交易 + 前端三路并行评审)后，挑出 3 个**真实 bug** 修掉（其余命中的 SSRF·DNS-rebinding / SQLite 回退幂等 / manual 支付 = 既定"够用即止"边界，不动；见 memory wf-reliability-scope、trading-payment-status）：
  - **私聊里 bot 临时装哑(可用性)**:`joined_member_count` 查不到成员数时直接 fail-open 返回 99→私聊被误判群聊→没被 @ 就彻底沉默(最难排查的"bot 不回话")。改成**每房间缓存上次成功值 + 一次重试**:瞬时抖动靠重试吸收;仍失败回退缓存(私聊见过就是 2、不会被误判);从没查到过的才保守按群聊。
  - **事务重发导致 AI 回复二重投递**:一个事务里任一事件失败→Synapse 重发**整批**,已成功的 AI 回复没有 event 级幂等会被重发。改成回复用 `event_id` 派生的**固定 txn_id** 发送,让 Synapse 去重(复用 orphan 通知同款手法)。
  - **run_workflow 池满残留 pending→永久卡死**:先按 source_key 建 queued 占位再提交线程池,池满提交失败时没回滚占位→同一事件重试被 `find_by_source_key` 误判"已触发过"、永不执行(要等 1 小时遗孤回收还误报"提交队列中断")。新增 `wf_repo.release_pending_source`(只删 queued),池满失败时回滚预约让重试能真正提交。
- 关键决策:#2 不去阻止"重跑 LLM",只保证**群里不冒第二条**——按本仓既有 txn_id 去重思路,代价最小、与崩溃恢复一致。
- 测试:新增 5 个回归(成员数缓存/重试/兜底 3 个 + 池满回滚/已外呼不删 2 个);相关 4 套件 69 通过、ruff 全绿。trading 9 个失败是**缺 `COSMAC_PAY_MANUAL_SECRET` 环境变量**的既有问题、与本次无关(已在干净树复现)。**纯后端、无需发 dist;部署=重启 bot**。

## 2026-06-26 — 图文教程：排序 / 置顶
- 后台编辑器页面树每个节点加 📌置顶 / ↑上移 / ↓下移：在兄弟范围内调顺序，复用已有 move 端点
  （前端交换 sort/设最小 sort 实现，无需新后端、写权限仍后端 power 强制）。前台按 sort 展示即生效。
- 纯前端（含一批设计 token/CSS 正规化的并行改动一起构建进 dist）。验证:build + preview 无 console 报错。只发 dist。

## 2026-06-26 — 图文教程自检：修两个上线必崩/缺失项
- 自查发现并修：
  - **(严重)Postgres 上 published 补列会失败**:`ADD COLUMN published BOOLEAN NOT NULL DEFAULT 1`
    在 Postgres 报错(boolean 列不接受整数 1 作默认)→ heal 静默失败 → published 列不存在 → 图文
    所有读写 SELECT published 全崩。改成 `DEFAULT TRUE`(Postgres/SQLite 都支持,已用本机 sqlite3.51 验证)。
    本机 SQLite 没暴露是因为本地表由 create_all 直接建、不走 heal。
  - **前端 GATE_CATALOG 缺 doc_read**:后台「会员权限」页看不到「图文教程」这条、无法在线调门槛
    (后端默认 paid 仍强制)。补上(default paid, group「内容」),前后端目录对齐。
- 验证:ruff + 后端 311 单测 + 前端 build + preview 无报错。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 图文教程：草稿/发布状态
- 新建文章默认**草稿**:只有后台(管理员)能看到,前台付费用户看不到、也不进 AI 知识库;
  在编辑器点「草稿○/已发布●」切换+保存才发布。发布后才前台可见 + 入库供 AI 答疑。
  - DB:`cosmac_doc_page` 加 `published`(旧库补列 DEFAULT 1 保历史可见;新建 ORM 默认 False=草稿)。
  - doc_repo:list_pages 加 published_only;create 默认草稿;update 可切 published;page_to_dict 回 published。
  - 后端:tree/page 对非管理员只给已发布(草稿 404);update 按发布状态同步 KB(发布→入库,草稿→移除);新建不入库。
  - 前端:编辑器发布开关 + 阅读态状态标签 + 树「草稿」标;前台 DocReader 天然只拿到已发布(后端过滤)。
- 验证:新增 publish_filter 单测 + 后端 311 单测 + ruff + 前端 build + preview 无报错。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 图文教程后台：一键「AI 写文章」
- 后台编辑器加「✨ AI 写」按钮:输入主题→AI 生成整篇 Markdown 填入正文(已有正文作为改进基础),
  并自动用首个 # 标题填到标题框。省去去别处让 AI 写再复制粘贴。
  - 后端 `POST /cosmac/doc/draft`(仅平台管理员):用后台下发的运行时模型 self.llm.complete 生成,
    系统提示设定为"公众号图文作者、输出 Markdown 正文"。
  - 前端 `docDraft(topic, existing)`;DocChannelView aiWrite()。
- 验证:ruff 全绿 + 后端 310 单测 + 前端 build + preview 无 console 报错。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 图文教程前台：图文(HTML)/Markdown 视图切换
- 后台编辑本就是 Markdown(可让 AI 写文章直接贴);前台默认渲染成 HTML 图文。
- 前台文章详情加「图文 / Markdown」切换:Markdown 态显示原文(可一键复制)——这份 MD 就是
  AI 知识库(RAG)用的内容,等于把"AI 能调用的知识"显式暴露出来。
- 纯前端;AI 答疑(MD→KB→RAG)早已生效。验证:build + preview 无 console 报错。**只发 dist、无需重启 bot**。

## 2026-06-26 — 图文教程：文章封面图
- 后台编辑可给每篇图文加**封面**(类公众号):上传图片→存 Matrix 媒体库(mxc://)。
  - DB:`cosmac_doc_page` 加 `cover` 列(engine `_heal_business_schema` 给旧库补列);doc_repo create/update 接 cover、page_to_dict 回 cover。
  - 后端 handler 透传 cover;前端 docCreatePage/docUpdatePage 接 cover + `docCoverUrl`(mxc→媒体代理 http,http(s) 原样)。
  - 编辑器(DocChannelView):封面上传行(上传/更换/移除,uploadMedia 存 mxc);阅读态顶部横幅。
  - 前台 DocReader:卡片右侧封面缩略图 + 详情顶部横幅。
- 验证:ruff 全绿 + 后端 310 单测 + 前端 build + preview 无 console 报错。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 图文教程改：全平台一份 + 付费会员可见
- 负责人定:图文教程**不分工作区**(全平台一份)、且**付费会员才能看**。改:
  - **全局存储**:所有页面存固定作用域 `_GLOBAL_DOC_ROOM`(不再按 Space)。读端点去掉 room_id 入参。
  - **付费门控**:gating 新增能力 `doc_read`(默认 TIER_PAID,后台「会员权限」可调);读端点(tree/page)过 `_gate_allows(doc_read)`,非付费回 403+locked;前台 DocReader 显示「🔒 付费会员专享」。
  - **编辑=平台管理员**:写端点(建/改/删/移)只许平台管理员;后台「图文教程」去掉工作区选择器,直接编辑全局一份。
  - **AI 答疑**:`_kb_context` 对付费用户(doc_read)自动把全局图文纳入 RAG(不再靠前端传作用域),中枢 AI 即可基于图文答疑。
  - 前端 docTree()/docCreatePage() 去掉 roomId;DocReader/DocChannelView 去掉 roomId/spaceName 改全局;LiveView 图文教程视图直接 `<DocReader/>`;撤掉 per-Space 的 ensureBotInSpace 调用(createSpace 邀 bot 保留、无害)。
- 验证:ruff 全绿 + 后端 310 单测通过 + 前端 build + preview 无 console 报错。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 改名「图文教程」+ 前台只读(类公众号)/后台编辑 分离
- 负责人反馈:前台应是**查看**(类公众号:文章列表→点开看详情)、**编辑放管理后台**;「文档」改成 4 个字。
- 改:
  - 改名 **图文教程**(侧栏置顶项 + 后台菜单 + 视图标题)。
  - **前台只读** `DocReader.vue`:文章卡片列表(标题+摘要+日期)→点开看详情(渲染 Markdown)+返回;不放任何编辑入口。`page_to_dict` 加 `excerpt`(去 markdown 的摘要)/`updated_ts` 给卡片用。
  - **后台编辑**:把原编辑器 `DocChannelView.vue` 移进**管理后台**新增「图文教程」标签:选工作区(下拉)→ 编辑该工作区的图文(树/新建/编辑/删除,左写右预览)。选工作区时 ensureBotInSpace。
  - LiveView 的「图文教程」视图改用 DocReader;复用 docTree/docGetPage 端点(只读),编辑走原 create/update/delete(后台,仍 power≥50 强制)。
- 验证:前端 build + preview 干净无 console 报错;后端 310 单测全绿。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 文档 P2：中枢 AI 基于工作区文档答疑(RAG)
- 让主 AI 能基于教学文档答疑(负责人定:走中枢 AI,不在文档里另开聊天框):
  - **入库**:文档页保存/删除时同步进知识库(按工作区 Space room 作用域),source=`docpage:<id>`;更新先按 source 清旧再重灌(kb 新增 `delete_by_source`)。
  - **文档感知 RAG**:中枢 AI 是全局 DM、本身不在工作区,前端提问时捎上「当前工作区」(`cosmac.doc_space` 自定义字段,sendText 加 extra→sendEvent);bot 读它,把该 Space 的文档纳入本轮 RAG(`_kb_retrieve` 加 extra_scopes,经 _kb_context/_skill_addendum 透传)。
  - 受 knowledge 门控(同其它 RAG);best-effort,入库失败不影响保存。
- 验证:新增 `delete_by_source` 单测 + 全量 311 测试通过、ruff 全绿;前端 build + preview 无 console 报错。前后端都变→发 dist + 重启 bot。
- 注:文档「频道(channel)」内自动 RAG(读 m.space.parent)未做,本期靠中枢 AI 显式带工作区即够用。

## 2026-06-26 — 文档改版：从「频道类型」改成与看板同级的顶部视图
- 负责人反馈:文档应和**数据看板/任务看板同级**(顶部视图),不是侧栏里的频道类型。改:
  - **撤掉**频道类型那套(新建频道的 💬/📄 选择、侧栏 📄、isDocChannel、LiveRoom.kind、createDocChannel)。
  - **新增** `docs` 顶部视图:侧栏置顶项「📄 文档」与数据看板/任务看板并列;主区 v-else-if="docs" 渲染 DocChannelView;独立地址 `/s/:space/docs`(接入 computePath/applyFromRoute/watch + router 占位)。
  - **数据模型**:文档树按**工作区(Space)**存,即 DocChannelView 传 `roomId=activeSpace`。后端不变(本就按 room_id 存)。读=Space 成员、写=Space power≥50(创建者天然有)。
  - **bot 必须在 Space**(鉴权要 bot 读 Space 成员状态):createSpace 建时邀请 bot;`ensureBotInSpace` 给老 Space 兜底,openDocs 时调;DocChannelView 首读若鉴权未就绪(bot 刚邀请还没 join)自动重试一次。
- 验证:前端 build + preview 干净重启无 console 报错;后端 309 单测仍绿。前后端都变→发 dist + 重启 bot。

## 2026-06-26 — 文档教学频道(类云文档) · P1 前端(端到端可用)
- 接上条后端地基,补齐前端,P1 端到端跑通:
  - `client.ts`:6 个文档 API(docTree/docGetPage/docCreatePage/docUpdatePage/docDeletePage/docMovePage) + `createDocChannel`(建房+标记 kind='doc'+挂工作区);LiveRoom 加 `kind`、listRooms 从 channel_config 读。
  - 共享 `utils/md.ts`:安全 Markdown 渲染(沿用聊天版加固:先转义含引号、抠存代码块、URL 限 http(s)、剥 \x00),比聊天版多支持标题/列表/引用/图片——教学文档要用。
  - `components/doc/DocChannelView.vue`:左侧多层嵌套页面树(扁平化带深度,非递归组件) + 右侧 Markdown 阅读/编辑(编辑态左写右实时预览);power≥50 者可新建子页/删(含子树)/编辑,成员只读。
  - LiveView 集成:`isDocChannel`(按当前房 kind)→ 主区渲染 DocChannelView 而非聊天流;新建频道弹窗加「频道类型」选择(💬聊天/📄文档,仅平台管理员可见);侧栏文档频道显 📄。
  - 路由:文档频道复用 `/s/:space/c/:roomId`(也是 Matrix 房间,openRoom→kind 驱动渲染,深链/刷新/后退既有逻辑覆盖),不单开路由降风险。
- 决策:P2 才接 AI 答疑(保存即入 KB + 中枢 AI 文档感知 RAG);本地图片上传 P3。
- 验证:前端 build(`index-Bh3lTzPT.js`)通过 + preview 登录页正常渲染无 console 报错;后端 309 单测全绿(上条)。**前后端都变 → 发 dist + 重启 bot**。

## 2026-06-26 — 文档教学频道(类云文档) · P1 后端地基
- 新模块:独立「文档频道」类型,主区=多层嵌套页面树(类 Notion)+Markdown 页面。负责人拍板:仅平台管理员可建、有权限者(房间 power≥50)编辑·非实时、成员只读、内容 Markdown+图片(P1 用链接)、AI 答疑走中枢 AI(文档感知 RAG, P2)。
- 后端地基(本次):
  - DB 模型 `cosmac_doc_page`(room_id/parent_id/title/content_md/sort/updated_by) + `doc_repo`(树查询/CRUD/移动防环/级联删子树) + 8 单测。
  - 频道类型标记走 Matrix `cosmac.channel_config.kind='doc'`(前端不查 DB 就知道怎么渲染);正文存 cosmac DB(state event 存不下、要喂 KB)。
  - 6 个 bot HTTP 端点:GET /cosmac/doc/tree?room_id= 与 /cosmac/doc/page?id=;POST /cosmac/doc/page(建)//update//delete//move。鉴权复用任务看板那套:读=is_joined_member、写=房间 power≥50,服务端强制。
- 验证:全量 309 测试通过、ruff 全绿。**纯后端、未接前端,无需单独部署**;等 P1 前端(侧栏识别+文档视图+建频道入口+路由)齐了一起发。

## 2026-06-26 — 代码审查·收尾（引导诚实反馈 + 脏数据校验）
- **引导不再"假装搭好了"**:useOnboarding.runCreate 里频道是逐个建、失败被吞的;原来无论建成几个都提示"🎉搭好了"。改成按实际结果反馈——全建失败→明确告知"频道没建上、进去手动补",部分失败→报"建成 X/N 个"。工作区本身建成才进入。
- **useCustomAssets 加载逐项校验**:localStorage 可被手改/旧版遗留,sanitizeAsset 规范化每条(cat 白名单/字段强转字符串/补 id),脏记录不再渗进 UI。
- 验证:前端 build 通过 + preview 登录页正常渲染。纯前端,**发 dist**。

## 2026-06-26 — 代码审查·第三批（登出状态泄露/竞态/并发守卫）
- **登出单例状态泄露(systemic·共享浏览器)**:很多 composable 用模块级单例(CLI 历史/频道配置/插件/自定义资产)，doLogout 原来只清几个 ref、不 reload → 换人登录能看到上个人的数据。改成 doLogout 清掉 customAssets 本机存储(`clearCustomAssetsStorage`)再**整页 reload**，一次全清(含未来新增的任何单例)。
- **debounce 换工作区数据串台**:useSocialSources/useBoardSources 的 setSpace 切 space 前没取消在途防抖保存，persist 用执行时的 spaceId → 旧 space 内容被写进新 space。setSpace 顶部 clearTimeout 修掉。
- **引导重复建工作区**:useOnboarding.runCreate 入口加 busy 重入守卫(防双击建俩工作区);OnboardingWizard 的 done 定时器在卸载时清理(防卸载后 emit)。
- **频道管理并发**:ChannelAdminModal.doRemoveLive 加 liveBusy 守卫 + 按钮禁用(防连点并发 kick)。
- **控制室 TOCTOU**:ensureControlRoom 的 createRoom 撞 M_ROOM_IN_USE(并发建房)时重 resolve 复用，不再报错。
- **小修**:joined_member_count 查不到补 debug 日志(便于排查"bot 私聊不回话")。
- 测试:全量 216 通过、ruff 全绿、前端 build + preview 无 console 报错。**部署:发 dist + 重启 bot**。

## 2026-06-26 — 代码审查·第二批（中低危健壮性/泄露/内存泄漏）
- 接着上一批继续清剩余项:
  - **后端**:工具异常文本不再原样回灌模型(信息泄露)、best-effort 落库 except 补 debug 日志;`cosine` 维度不一致返回 0.0+告警(不再 min(len) 算错值);邮箱映射 `set_email` 加 SAVEPOINT 抗并发唯一约束撞车、注册成功但映射失败提到 error 级+重试一次(否则用户无法邮箱登录/找回);bot 启动时若 `COSMAC_PAY_ALLOW_MANUAL` 开着就大声告警(生产红线)。
  - **前端**:`onUpdate` 返回解绑函数、LiveView 在 onBeforeUnmount/重登时解绑(防监听器累积重复触发);`restoreSession` 校验 localStorage 的 baseUrl(https+host 白名单)防被篡改把 token 发往攻击者主机;新建用户密码框 `type=text→password`;内联 `:style` 的 `m.color` 改对象式(防 CSS 注入);MembershipModal 价格 `Number.isFinite` 守卫;可删列表 `:key` 用 WeakMap 稳定行 key(`utils/rowKey.ts`)替下标(防删中间行 v-model 错位)。
- 测试:全量 216 通过、ruff 全绿、前端 build + preview 加载无 console 报错。
- **部署**:前端发 dist + **重启 bot**(后端也变了)。

## 2026-06-26 — 全量代码审查 + 按优先级修一批安全/健壮性问题
- 起因:负责人要求「整体代码检查」。5 个领域并行审(认证/支付/工作流/AI·DB/前端),逐条裏取り后按优先级修。
- **高危(已修)**:
  - **任务看板越权**:`task_repo.list_tasks/update_task` 加 room_id/sender 作用域;`handle_tasks_list/handle_task_update` 按「本人下达 ∪ 本人所在房间 ∪ 平台管理员」校验(`_can_access_task`,用 `is_joined_member` fail-closed)。之前任意登录用户可遍历 id 读写全平台任务。
  - **前端 renderMd XSS**:`escapeHtml` 补转义 `"`/`'`(链接 href 属性击穿),渲染前剥 `\x00` 哨兵(占位符注入)。node 验证三个向量均封堵。
  - **注册/找回密码限频**:registration.py 叠加按 IP 滑窗限频(发码 20/时、验码/登录尝试 30/15分),堵「换邮箱绕过 + 重发刷新尝试计数」爆破;username 正则去 `/`、加 64 长度上限;运算符优先级加括号。bot 经 `_client_ip()`(X-Forwarded-For)透传。
  - **支付**:`on_payment_success` 加金额/货币二次校验(防少付拿全权益,P2 接 Stripe 前必须);续费按 user 串行锁(`_user_lock`)防并发回调叠加;`manual._secret()` 去掉公开默认密钥改 **fail-closed**(没配密钥 manual 不可用)。
- **中危(已修)**:`handle_stats` 全平台运营指标限平台管理员(非管理员 403,前端优雅回退);`members._as_int` 安全转 expires_ts(脏 state 不再让整批读崩成全员免费)。
- **澄清(经裏取り为误检/已安全,未改)**:工作流门控 `workflow_run` 默认本就 = admin、GatingStore 读失败 fail-closed(前后端一致);`OpenAIProvider` 类是**死代码**(build_provider 实际走支持工具的 `OpenAICompatProvider`)→ 删掉该文件除混淆。
- 测试:新增支付金额/货币拒绝用例 + stats 限管理员用例;全量 216 测试通过、ruff 全绿、前端 build 通过。
- **部署**:前端发 dist;**后端(cosmac/)需重启 bot 服务**(注册限频/支付校验/任务越权/stats 都在 bot 进程)。

## 2026-06-25 — AI 侧栏放大态右栏接真实数据（替掉写死演示）
- 放大态右栏原是写死的 Progress(5/8 热点选题…) + 项目文件(xlsx/pdf)。改成真实:
  - **进度** = 任务看板真实任务(taskList)，标题+完成数 doneCount/总数，done 划线、doing 显进度%。
  - **项目文件** = 真实**个人知识库**文档(新后端 GET `/cosmac/kb/list` 列 scope=USER 文档标题 → client.ts `kbListMine`)。
  - 没数据各自显空态提示(去下达目标 / 去加知识库)。进放大态时拉一次。
- (个人主页:负责人要重做成「可分享个人名牌·手机端」,本次先不动。)
- 验证:ruff + 前端 build(`index-CWGgAV14.js`)。**发 dist + 重启 bot**(新增端点)。

## 2026-06-25 — P3 数据看板按「接入数据源」配置渲染（去掉写死的安其演示）
- 负责人定:看板社媒区跟工作区「接入数据源」配置(cosmac.social_sources)走。
- 看板社媒区重做:没配数据源→空态(引导去接入);配了→每个平台一张卡(平台/账号/模式/状态),指标显示「待接入」(等社媒采集器 P2~P4 接上变真数)。平台运营(真实 KPI)那组保留。
- **彻底删掉安其演示数据**:dashboards.ts(银河谣/墨白/抖音占位)、PanelChart.vue、UnitGrid.vue、useChart.ts 全删(已无引用)。看板不再有任何安其专属内容。
- 验证:build(`index-DjZF4N9m.js`)。看板在登录后,需眼验。纯前端,**发 dist**。
- 注:社媒数值仍是占位,真实数要等社媒采集器(social-data-source P2~P4)。

## 2026-06-25 — 修生产知识库入库失败(cosmac_kb_chunk 缺 embed_tag 列)
- 自测 P2c 入驻知识库入库返回 ingested:0。查 bot 日志:`UndefinedColumn: column "embed_tag" of relation "cosmac_kb_chunk" does not exist`。
- 根因:旧生产库建 cosmac_kb_chunk 时还没 embed_tag 列(后加的向量空间标识),create_all 只建表不补列 → 入库 INSERT 报错、整个 KB 写入失效(pgvector 本身没问题,embedding 列在)。
- 修:`engine.py _heal_business_schema` 加非破坏性补列(同 cosmac_workflow_run 套路)——表缺 embed_tag 就 `ALTER TABLE cosmac_kb_chunk ADD COLUMN embed_tag VARCHAR(64) NOT NULL DEFAULT ''`。bot 重启自动补。
- 验证:ruff + 本地 SQLite init+入库 OK。**重启 bot 即生效**(纯后端,可不发 dist)。
- 自测记录:人设/模型/技能链路线上实测**通过**(测试房间+测试号已清理)。

## 2026-06-25 — 入驻模板边角①：付费模板门控
- 之前付费模板只显示角标、不拦截。现在引导加门控:进来查当前会员等级(payGetMe)→付费模板(tier 高于用户等级)**锁住**,卡片显示「🔒 付费」+置灰,点了提示「X 是付费专享,先选免费的或升级」、不放行。
- 等级比较按 MEMBER_TIERS 顺序(free<paid<creator)。UI 级门控(够用即止/单实例,符合 [[wf-reliability-scope]] 口径);彻底服务端强制(模板配置是客户端写 state event 应用的)是已知边界、本期不做。
- 验证:build(`index-iBwVINmc.js`)。纯前端,**发 dist**。

## 2026-06-25 — 入驻模板 P2c：模板预置知识库灌进新用户
- 模板的预置知识库文档在注册时灌进新用户。KB 要写 cosmac DB+向量化,前端做不了,加后端端点。
- 后端 `/cosmac/onboard/ingest-kb`(带本人 token):whoami→把 docs 灌进**本人个人知识库**(scope=USER,kb.ingest_document)。选个人库是因为 bot `_kb_context` 检索时会带上发送人个人库→模板知识在该用户**任何频道**都可用,免去按频道重复入库。一次最多50篇、受 MAX_DOCS_PER_SCOPE(200) 限。best-effort 失败回200不阻断。
- 前端:client.ts `onboardIngestKb`(引导登录后跑、用当前 token);OnbPickTemplate/answers 加 kbDocs;runCreate 建完工作区后灌库。
- 至此模板的 **人设/RULE/模型/技能/知识库** 全部随注册落地生效。
- **留**:默认工作流绑定(概念待定)、tier 门控强制、KB 改群级共享(现在是个人库)。注:服务端 embedder 若无 API 走哈希兜底,检索质量一般但能用。
- 验证:ruff + 34 单测(group_agent/registration/kb)全过;前端 build(`index-Cb8DAKae.js`)。**发 dist + 重启 bot**。

## 2026-06-25 — 入驻模板 P2b：模型 + 技能也按工作区生效
- 接着 P2(人设)，让模板的**模型/技能**也在新工作区生效，且不绑全局智能体、尊重用户改的人设。
- bot 小改:`_group_context` 自定义人设路径也读 `persona.model` + `persona.skill_slugs`(skill_slugs 经 `_agent_skill_items` 解析技能库全局技能)。+1 单测。
- 前端:OnbPickTemplate/answers 加 model/skillSlugs;引导创建时把 model+skill_slugs 一起写进每频道 `channel_config.persona`。
- 至此模板的 **人设/RULE/模型/技能** 都按工作区生效(房间级、普通用户有权限写)。
- **留 P2c**:知识库文档入库(要写 cosmac DB + pgvector,需后端端点)、默认工作流绑定(概念待定)、tier 门控强制。
- 验证:ruff + group_agent 10 单测全过;前端 build(`index-C7alqq42.js`)。纯前端+bot小改,**发 dist + 重启 bot**。

## 2026-06-25 — 入驻模板 P2：引导接后台模板 + 人设真生效
- 引导从写死模板改成**读后台** `cosmac.onboarding_templates`（getOnboardingTemplates，过滤已上架）；后台没配则回退内置 ONBOARDING_TEMPLATES。模板卡显示「付费」角标(tier≠free)。
- **修人设没生效**：创建时不再写全局 setAiConfig(管理员级、普通用户静默失败)，改成给**每个频道**写 `channel_config.persona.prompt`(=人设+RULE)。bot 的 `_group_context` 读它→在该工作区以此人设回应，**房间级、用户自己有权限写→普通用户真生效**。
- 已知机制(探明)：bot `_group_context(room_id)` 读 `cosmac.channel_config.persona`，agentSlug 绑全局智能体(人设+技能+模型) 或 prompt 自定义人设。我们走 prompt 路径(人设+RULE)。
- **留 P2b**：模板的模型/技能/知识库/默认工作流绑定（要写 cosmac DB 或建全局智能体）;tier 门控强制(现在只显示角标不拦截)。
- 验证:`npm run build`(产物 `index-BYejdJSy.js`)+ 隔离测试页确认模板加载/选择/流程正常。引导真建需新号眼验。纯前端,**发 dist**。

## 2026-06-25 — 入驻模板体系 P1：后台「入驻模板」管理页 + 存储
- 方向(负责人定):后台 Admin 定义一组「入驻模板/方案」,前台注册引导让用户选一个再微调。每个模板打包:模型/AI人设/基础RULE/技能(从技能库选)/预置知识库文档/初始频道/默认工作流/**所需会员等级**(免费/付费,接现有会员+门控)。
- **P1(本次)**:Admin 加「入驻模板」页(增删改查,照智能体页套路),全字段表单(含技能/工作流多选、知识库文档增删、tier 下拉);存控制室 state event `cosmac.onboarding_templates`(client.ts get/setOnboardingTemplates)。CLAUDE.md 存储表已登记。
- 这也是解决"引导AI人设没生效"的正路:P2 会把引导从写死模板改成读后台模板,并**按工作区绑 per-group Agent**(room级、用户有权限写)让人设/模型/技能真生效。
- 分期:P2 引导接入+绑Agent+关联知识库;P3 看板按模板渲染(替 dashboards.ts 写死)。知识库配额(免费vs付费数量/空间)等配会员时再做。
- 验证:`npm run build`(vue-tsc 严格通过,产物 `index-BuU5XEL1.js`)。Admin 页需管理员登录眼验。纯前端(P1 bot 不读),**发 dist**。

## 2026-06-25 — 修「新工作区名不生效、界面仍显示安其影视」
- 现象:引导建了叫"咕嘟"的工作区,进去顶栏/看板标题仍显示"安其影视"。
- 根因:三处写死租户名,没跟随工作区——顶栏 `tenant.topbarSuffix`、看板大标题 `dash.brand`(新工作区回退演示看板)、AI侧栏"安其影视·本周专班"。全改成 `activeSpaceName`。
- 另修时序:`onOnboardingDone` 加轮询(最多12×300ms),等新 Space sync 进房间列表再设 active,否则 activeSpaceName 短暂回退到租户默认名"安其影视工作室"。
- 注:看板**演示图表内容**(银河谣/墨白/抖音等)仍是安其样板(负责人定的"保留演示数据"),与工作区名无关;要去掉是另一档"替换演示数据"的活。
- 验证:build(`index-C0m6PXEk.js`)。登录后界面,需新号眼验。纯前端,**发 dist**。

## 2026-06-25 — 首次引导浮层改毛玻璃（背景数据虚化）
- 注册后弹的「主 AI 问答」首次引导(OnboardingWizard)遮罩原是不透明底色、挡死后面应用。改成毛玻璃:半透明 `rgba(245,243,238,.5)` + `backdrop-filter: blur(12px)`,让后面的数据/界面透出但虚化,聚焦在 AI 引导卡片。
- 验证:build(`index-CJ701QTK.js`)。引导仅新账号登录后弹、无法本地 preview,效果需负责人用新号眼验。纯前端,**发 dist**。

## 2026-06-25 — 登录加「邮箱登录」（账号/邮箱二选一）
- 登录模式加子切换「账号登录 / 邮箱登录」，丰富界面。
- 后端 `registration.login_email`（端点 `/cosmac/login/email`）：按邮箱反查用户名(复用 email_repo)→ 用账号密码登 Synapse → 原样回登录响应；失败统一回「邮箱或密码错误」防枚举。**无需管理员令牌**(普通登录)。
- 前端 `loginWithEmail()`(拿后端登录响应→saveSession+startFrom，复用 login 后半程)；`loginBy` ref 切换，doLogin 分支。
- 注意：邮箱登录只对**有邮箱映射的账号**(注册时存的)有效，老账号用账号登录。
- 验证：ruff + 13 单测过；build(`index-Dmc7Ql88.js`)+ preview 切换字段确认。
- 部署：发 dist + 重启 bot。

## 2026-06-25 — 登录卡片内容三段式分布 + 放大控件
- 上一版等高用 justify-content:center → 登录内容挤成一团浮中间、上下大白边。改三段式:模板拆 `.auth-top`(品牌+tab)/`.auth-fields`(字段)/`.auth-bottom`(按钮+链接),卡片 `justify-content:space-between` 把多余高度分配到段间,内容均匀填满。
- 控件放大适配宽卡片:输入框 padding 13×15、字号 15;按钮 padding 14、字号 15 加粗;tab 加大。
- 验证:build(`index-N8sk2W1x.js`)+ preview 截图登录/注册都填满匀称。纯前端,**发 dist**。

## 2026-06-25 — 登录/注册卡片加宽一倍 + 三模式等高
- 鉴权卡片 `.login-card` 宽 320→640px（+ max-width:92vw 防小屏溢出，padding 略增）。
- 三模式等高：加 `min-height:502px`(以最高的注册为准) + `justify-content:center`(内容垂直居中) + box-sizing。登录/注册/找回切换时卡片不再跳高（实测都 502px）。纯 CSS。
- 验证：build(`index-BQjwQXvV.js`)+ preview 量高度三模式一致。纯前端，**发 dist**。

## 2026-06-25 — 找回密码（忘记密码）
- 需求:登录页加「忘记密码」→ 发邮箱验证码 → 验码后输新密码(带确认)。
- 后端(`cosmac/registration.py`):复用注册那套发码/验码（码按**用途分桶** register/reset，注册码不能拿去重置）。新增 `reset_request_code`(防邮箱枚举:未注册也回成功但不发信)、`reset_verify`(验码→反查账号→管理员令牌重置密码并登出所有设备)。重置走 `/_synapse/admin/v1/reset_password/<user_id>`，**需服务器管理员 access token**(env `COSMAC_ADMIN_TOKEN`，as_token 权限不够)。
- 邮箱→账号映射:新表 `cosmac_registered_email`(注册成功时 upsert)+ `db/email_repo.py`。老账号注册时没存这条→暂不能用邮箱找回(目前账号极少可接受)。
- 邮件:`_build_email(code, kind)` 复用模板,reset 文案「重置你的密码」+ 主题「【CosMac Star】重置密码验证码 <code>」。
- 前端:鉴权页加第三态 `reset`;登录页「忘记密码？」入口;复用邮箱+发码+验证码,字段改新密码/确认新密码,成功后回登录。
- 验证:ruff + 13 单测(7注册+6找回)全过;build(`index-DGlLnslK.js`)+ preview 截图确认。
- 部署:发 dist + **加 env COSMAC_ADMIN_TOKEN**(管理员令牌) + 重启 bot。

## 2026-06-25 — 验证码邮件去掉 logo 图 + 投递排查
- 邮件进 Gmail 垃圾箱。查 guduu.co DNS:SPF(spf.onlarksuite.com -all)✅、DMARC(p=reject)✅、MX(larksuite)✅,但**DKIM 没查到**(常见 selector 无记录)——这是主因之一;加上新域名无信誉、跨域外链图(logo 来自 app.cosmac.cc 而发件人 guduu.co)拉低评分。
- 处理:① 去掉邮件 logo 图,抬头改纯文字标识「✦ CosMac Star」(文字字符、不外链图、不受远程图拦截、利于投递);删 `email-logo.png` 资产 + `_email_logo_url`。② DKIM 需负责人去 Lark 后台域名管理补 DKIM 记录;建议用 mail-tester.com 精确诊断。
- 验证:ruff + 7 单测过;`_build_email` 产出无 img、有 ✦ 文字标识;preview 真实渲染截图确认。
- 部署:发 dist + 重启 bot。

## 2026-06-25 — 验证码邮件品牌化（HTML 模板 + logo + 纯文本兜底）
- 把验证码邮件从纯文本升级成品牌化 HTML：吉祥物 logo + 「CosMac Star」抬头 + 大号验证码（陶土橙 #993c1d 底框）+ 有效期 + 安全提示 + 页脚。负责人预览确认。
- 邮件安全写法：表格布局 + 全内联样式（Gmail/Outlook 剥 <style>、不支持 flex）。`registration.py` 加 `_build_email()` 返回 (主题/纯文本/HTML)，`_send_email` 用 set_content(纯文本)+add_alternative(html)。
- 主题 `【CosMac Star】注册验证码 <code>`（码放标题方便看）。
- logo：邮件不能内联打包图，走公网 URL `https://app.cosmac.cc/email-logo.png`(env `COSMAC_EMAIL_LOGO_URL` 可覆盖)。优化版 logo(694KB→17KB,120px)放 `client/public/email-logo.png`→构建复制到 dist 根。
- 验证：ruff + 7 单测过；`_build_email` 产出主题/logo/code 正确；preview 真实渲染截图确认外观。
- 部署：发 dist(含 email-logo.png) + 重启 bot(邮件模板在后端)。

## 2026-06-25 — 注册页修浏览器自动填充串味 + 验证码框文案
- 现象:注册时输入邮箱后,验证码框被浏览器自动填成邮箱(autofill 启发式把相邻框也塞了)。
- 修:给各框加 autocomplete 语义——邮箱=email、验证码=one-time-code(+inputmode=numeric+maxlength6)、用户名=username、密码=new-password。验证码框声明 one-time-code 后浏览器不再填邮箱。验证码框占位改「6 位验证码（填邮件里的数字）」更清楚。
- 线上已确认:邮箱验证码注册整条链路打通(收到验证码邮件)。SMTP(Lark)+ 共享密钥建号 OK。
- 验证:build(`index-zGE1DsHc.js`)+ preview 确认各框 autocomplete 属性正确。纯前端,**发 dist**。
- 仍待办:关 Synapse 开放注册(enable_registration:false)收尾。

## 2026-06-25 — 自建「邮箱验证码」注册（前端 + cosmac 后端）
- 需求(负责人定):注册走邮箱验证码(非链接)。Synapse 原生只发验证链接,故自建。
- 后端 `cosmac/registration.py`:发码→验码→用 registration_shared_secret 调 Synapse `/_synapse/admin/v1/register` 建号(该端点不受 enable_registration 影响)。码存内存(TTL+锁)、限频(同邮箱冷却60s/每小时5次)、验码尝试上限5、一次性作废。SMTP 走 smtplib(SSL465/STARTTLS587),密钥全从 env 读。
- bot 加端点 `/cosmac/register/request-code` + `/cosmac/register/verify`(公开+CORS,复用现有 /cosmac/ 那套;nginx 已代理无需改)。前端 client.ts `registerRequestCode/registerVerify`(登录前 mx 还没建,显式传 HS 基址)。
- 前端注册页:邮箱+发送验证码(60s倒计时)+验证码+用户名+密码(≥8)+确认密码;注册成功即用同账号 login→触发首次引导。删掉旧的 Matrix dummy `register()`(已废)。
- 测试:`cosmac/tests/test_registration.py` 7 用例(happy/错码/一次性/冷却/坏邮箱/弱密码/坏用户名)全过;ruff 过;前端 build(`index-L8bn7JHY.js`)+ preview 截图确认注册页字段正确。
- ⚠️ 部署依赖(见下条说明):bot 需配 env(COSMAC_SMTP_* + COSMAC_REGISTRATION_SHARED_SECRET)并重启;且应把 Synapse 开放注册**关掉**(enable_registration:false),强制注册都走邮箱验证。密钥细节进 DEPLOY.md。

## 2026-06-25 — 登录/注册去掉默认 admin
- 用户名输入框默认值从 `'admin'` 改空,占位文案「用户名（如 admin）」改「用户名」。避免新用户/注册时误带 admin。
- 验证:build(`index-DihDBZx8.js`)+ 本地 preview 确认输入框空。纯前端,**发 dist**。
- (邮箱注册+验证是另一档讨论中:需服务端 SMTP + 前端多步验证流,见对话。)

## 2026-06-25 — 鉴权页加「注册」（退出后可注册/登录）
- 需求:退出登录后只到登录页、没有注册入口;应是「注册 + 登录」界面。
- 加:① client.ts `register(baseUrl,user,password)`——走 Matrix 标准注册 + dummy UIA(开放注册无验证码场景);M_USER_IN_USE/M_FORBIDDEN/需额外验证 都给友好中文错误。② 登录页改成「登录/注册」分段切换:注册模式多「确认密码」(校验一致)、按钮「注册并进入」、底部互切链接。注册成功即登录→自动触发首次引导。
- 验证:`npm run build`(产物 `index-f7_AexYR.js`);本地 preview 截图确认两种模式 UI 正确(登录=用户名+密码;注册=多确认密码)。纯前端,**发 dist**。
- ⚠️ 依赖服务端:注册要 Synapse `enable_registration: true`,否则前端报「服务器未开放注册」。开放注册有刷号风险,建议配注册令牌/验证码(届时前端 register() 需扩展处理对应 UIA 步骤)。服务端开关细节记 DEPLOY.md。

## 2026-06-25 — 注册后「主 AI 问答」首次引导（前端脚本化向导）
- 需求:新用户注册后进设置界面,以主 AI 问答形式自定义工作区名(左上角)/初始频道/AI人设,而非直接进满是演示数据的界面。
- 机制(负责人定):**前端脚本化对话向导**(聊天 UI 按固定步骤问,像在跟中枢 AI 聊),答完直接调现有 Matrix 接口真建。零后端、可部署、可控;以后可升级接真 LLM。
- 步骤:选行业模板(影视/电商/自媒体/教育/通用,预填频道+AI人设)→ 工作区名 → 频道增删 → 主 AI 人设 → 确认 → 真建(createSpace+createChannelInSpace+setAiConfig)→ 标记完成 → 切进新工作区。
- 文件:`useOnboarding.ts`(状态机+聊天日志+建库逻辑)、`OnboardingWizard.vue`(全屏聊天式 UI)、`onboardingTemplates.ts`(行业模板)、client.ts `isOnboarded/setOnboarded`(account data `cosmac.onboarding` 标记首次)。
- 触发:首屏 sync 就绪后,**无引导记录 且 无任何工作区**才弹(双保险,不打扰已有频道的老用户);可「跳过」(也标记已引导)。
- 决策:① 首次标记用 account data(比"无工作区"可靠、每账号多端同步、零基建)。② AI 人设走控制室 setAiConfig 是管理员级——非管理员写失败时 try/catch 静默跳过,不阻断引导。③ 保留演示数据作样板(负责人定):新建工作区 id 不在 dashboardMap→看板仍回退演示图,作参考;左上角工作区名已随真实 Space 名自定义。
- 验证:`npm run build`(产物 `index-C0novC9i.js`)。引导在登录后/新账号触发,画面需负责人用新号眼验。纯前端,**发 dist**。

## 2026-06-25 — 社媒数据源「官方 API」按平台分别认证（修一刀切）
- 负责人指出:官方 API 不能用一个笼统「凭据名」字段——每个平台认证/要填的东西都不同。属实,之前是占位错误。
- 重做:加 `SOCIAL_API_SPECS` 准确规格表(每平台:是否真有可用公开指标 API / 申请门槛 / 该配哪些服务端 env 密钥 / 哪些非密定位参数 / 官方文档)。
  - YouTube=API Key+频道ID(门槛低);X=Bearer Token(付费)+用户名;Instagram=Graph长期令牌+商业号UserID(高门槛,个人号无API);Facebook=主页令牌+PageID;Threads=令牌+UserID。
  - TikTok/抖音/B站/微博/小红书=**无可用官方公开指标 API**→标记 supported:false,弹窗提示「请用爬取」,并自动把模式切到爬取。
- 弹窗按所选平台**动态渲染**:支持的平台显示「①服务端 env 配哪个密钥(前端不碰真值)+②非密参数输入」;不支持的显示警示。schema 把 `credName` 换成 `apiParams`(各平台非密参数)。
- 验证:`npm run build`(产物 `index-I78If7ok.js`)。纯前端,**发 dist**。

## 2026-06-25 — 社媒数据源 P1 微调：海外平台 + N8N/Coze 接法说明
- 平台列表海外优先:加 Instagram/TikTok/Facebook/Threads(YouTube/X 已有),国内(抖音/B站/小红书/微博)保留在后。
- 负责人要用 N8N/Coze 对接爬取。安全决策:**不在 social_sources 里直接粘 webhook URL**(URL/密钥含 token,会泄进 Matrix state event)——按铁律走「管理后台·工作流面板」建 N8N(webhook 类型)/Coze 连接器(URL+密钥进服务端 env),这里爬取模式只引用连接器 slug。弹窗加了指向工作流面板的醒目说明 + 字段改「连接器 slug」。
- 验证:`npm run build`(产物 `index-CCs2fl5d.js`)。纯前端,**发 dist**。

## 2026-06-25 — 数据看板「接入社媒数据源」P1（前端配置 UI）
- 需求:看板社媒数据要接真实源——配各平台账号 API,或挂 AI Agent 爬。要按钮 + 逻辑设计。
- **设计**(写进 CLAUDE.md 存储表):两种取数模式 api(官方平台 API)/crawl(AI Agent 走模块3 工作流爬公开主页);与工作流连接器同构——定义存控制室·按工作区 state event `cosmac.social_sources`,凭据只放「名」、真值进服务端 env `COSMAC_SOCIAL_*`;取回指标进 cosmac DB `cosmac_social_metric`。数据流:配置+env凭据 → bot 采集器(定时/手动) → API直调 或 run_workflow → 归一化写 DB → 新 REST 端点回看板。
- **本次落地 P1(纯前端、可交付)**:看板「社媒数据」组旁加 **🔌 接入数据源** 按钮 → 配置弹窗(`SocialSourceModal.vue` + `useSocialSources.ts` + client.ts get/setSocialSources)。可增删数据源:平台(抖音/B站/YouTube/小红书/微博/X)、账号、模式(api/crawl)、凭据名 或 工作流名、同步间隔、启用开关;按工作区存 `cosmac.social_sources`、多端同步。配置结构即最终版。
- **暂未接(P2~P4,标记清楚)**:后端采集器/真实调 API/AI 爬取/写 DB/看板读真值。弹窗「立即同步」先占位提示;凭据真值永不进前端。
- 关键决策:先交付配置 UI 把数据结构钉死,后端分期接(涉及平台开发者资质/爬取合规,需负责人定先接哪个平台)。建议 P2 先接 YouTube Data API(最开放)。
- 验证:`npm run build`(产物 `index-DqzQTPqI.js`)。弹窗在登录后看板可见,画面需负责人眼验。纯前端,**发 dist**。

## 2026-06-25 — 左侧栏新增「粉丝社区」分组
- 需求:侧栏现有「频道」「私信」两组,再加一个「粉丝社区」分组。
- 实现:纯前端名称启发式,零后端。房间名带 后援会/歌迷会/粉丝/应援/社区/fans 等关键词的归「粉丝社区」组,其余留「频道」组(`channelRooms`/`fanRooms` 两个 computed 从 `filteredRooms` 派生)。新组带独立折叠态 `fanCommunityOpen` + 「添加粉丝频道」入口(复用新建频道弹窗,名字带粉丝关键词即自动归此组)。
- 关键决策:先用名称归类(影视场景里后援会/歌迷会本就这么命名),够用且即时生效;以后要精确归类再改成读房间 cosmac.* 状态事件标签。
- 验证:`npm run build`(产物 `index-DmnjiiyT.js`)。侧栏在登录后显示,画面需负责人眼验。纯前端,**发 dist**。

## 2026-06-24 — 数据看板改回社媒数据（演示）+ 社媒/平台运营 KPI 混排
- 需求:数据看板应是社媒数据(粉丝增长、播放量等)。负责人拍板:**先用演示数据铺满**、KPI **社媒在上 + 平台运营在下 混排**。
- 恢复之前「去 Demo」时删掉的看板图表组件(从 git 历史捞回并精简,去掉无用的 chartId/chartFactories 依赖):`useChart.ts`、`PanelChart.vue`、`UnitGrid.vue`。
- 看板上排 📈 **社媒数据(演示)**:KPI=今日播放/全网粉丝/本周新增粉丝/平均互动率;图表=近24h播放趋势(LIVE)、各周新增粉丝、剧集/明星/平台状态网格、各平台粉丝分布饼图(数据全来自 `dashboards.ts` 占位值)。
- 下排 ⚙️ **平台运营(真实)**:会员/工作流/订单/知识库,来自后端 `getPlatformStats`,拿不到时整组不渲染。两组用带「演示/真实」角标的小标题分开,避免假数据被当真。
- 关键决策:社媒数字 CosMac 不拥有,本轮只铺演示值;待负责人定真实源(后台手填 / 平台 API)再替换。
- 验证:`npm run build`(vue-tsc 严格类型检查 + vite 均通过,产物 `index-Juf0E12I.js`)。看板在 Matrix 登录后才出现、连生产 hs,登录后画面需负责人自行眼验。纯前端,**发 dist**。

## 2026-06-24 — 安全与可靠性复查修复：AI 工具权限 / appservice 重试 / 工作流幂等
- 修复 AI 工具跨房间越权：模型显式传其它 `room_id` 时，先确认发起人也是目标房间 joined 成员；否则拒绝读成员/历史/代发消息。
- appservice 事务改为“任一事件异常即不标记 done”，让 Synapse 重试，避免单事件失败被整批确认后永久丢失。
- 工作流按 Matrix `event_id` 登记 `source_key`，提交外部平台前先 reserve；事务重放时复用已有 run，不重复提交/扣费。老 `cosmac_workflow_run` 表缺列时用非破坏性 ALTER 补 `token/source_key/status`。
- 前端 Matrix 首次同步增加 ERROR/STOPPED/15s 超时处理；退出登录改为尽力调用服务端 `logout()` 撤销 access token，再清本地会话。
- 验证：聚焦单测、ruff、前端 build 通过；完整单测需允许本机测试 HTTP server 绑定端口。

## 2026-06-23 — 任务看板加「项目/剧集进度」（参考演示版剧集 Tab，用真实数据）
- 需求:任务看板要有剧集进度,参考之前演示版的剧集 Tab。
- **零后端改动**:任务本就带 `goal`(拆解时的总目标,如"做一条爆款短视频")——这就是天然的"项目/剧集"分组维度。
- 前端:`projects` 按 `goal` 分组,算每个项目的完成度(已完成算100%、其余按各自 progress 平均);看板顶部加**项目进度条**(每个项目一张卡:名称 + 渐变进度条 + 完成数/总数 + %),点卡过滤下面看板到该项目,「全部项目」看全部。
- 验证:build(`index-Ch14waf_.js`)。纯前端,**发 dist**。
- 说明:分组按用户下达目标的原文。把目标说成剧集(如"《夜航星》第3集…拆任务")即按剧集分组。

## 2026-06-23 — 任务看板再美化 + 修两侧顶边
- create_tasks 已验证可用(现场拆出 编剧/分镜/配音 3 卡)。本轮纯视觉:
- **两侧顶边**:任务看板内容直接贴容器边。加 `.kan-wrap` 包一层(padding `var(--content-pad-x)`、max-width 1180 居中),与数据看板留白一致。
- **更好看**:列顶加 3px 主题色条 + 圆点(待办灰/进行中橙/已完成绿)、计数胶囊加粗;卡片圆角更大+悬停上浮高亮、负责人改成**彩色头像 chip**(首字圆形头像 + 角色名)、进度条改渐变、空态图标更大。
- 验证:build(`index-L0mO4Bp5.js`)。纯前端,**发 dist**。

## 2026-06-23 — 任务编排 P1 修复：create_tasks 没被启用 + 看板美化
- 现场实测"让 AI 拆任务"**没反应**。根因:后台 AI 配置存的 `enabled_tools` 是"勾选的工具名列表",`create_tasks` 是新加的、不在旧配置里 → 被当成"未勾选=禁用",AI 调不了它(前端工具目录也没它)。
- 修:`create_tasks` 列为 **always-on 核心工具**(`Toolbox._ALWAYS_ON`,不受后台工具开关约束)——这类核心、低风险工具新增后不该被旧配置一存就关掉。**无需重存配置即生效**。改了 2 个相关单测断言。
- **看板美化**:三列加主题色圆点(待办灰/进行中橙/已完成绿)、卡片加阴影+悬停、进度条、完成卡置灰划线、空态带图标。
- 验证:**195 单测过**、ruff、build(`index-BWIOfi5H.js`)。需发 dist + 重启 bot。重启后再让中枢 AI "拆成几个任务"应能上板。

## 2026-06-23 — AI 任务编排 P1：主 AI 拆任务 → 真实任务看板（Kanban + 手动改状态）
- 负责人定的任务看板新形态(AI 任务调度中枢)开工。**P1 地基**:主 AI 拆解目标→落库→真实看板→手动改状态。派发执行/结果回填(P2)后续。
- **后端**:`cosmac_task` 表 + `db/task_repo.py`(create/list/update)+ 主 AI 新工具 **`create_tasks`**(`ai/tools.py`,把目标拆成子任务、每条带负责人、写库)+ bot 端点 `GET /cosmac/tasks`、`POST /cosmac/tasks/update`(whoami 校验 + CORS)。
- **前端**:任务看板从影视流水线 mock 换成**真实 Kanban**(待办/进行中/已完成三列,读 `/cosmac/tasks`)+ 卡片按钮改状态(`updateTask`);数据看板"一句话下达目标"→中枢 AI→AI 调 `create_tasks`→任务出现在看板。
- 验证:加 任务流 用例(拆解工具→列表→改状态、done 自动补满进度、空标题丢弃、无 token 401);**195 单测过**、ruff、build 通过。需发 dist + 重启 bot。
- **遗留**:P2 做派发(发频道@人/交AI/跑工作流)+结果回填。
- (同日续)清掉 LiveView 里旧影视流水线 mock:productionTabs(三部剧假数据)+甘特图弹窗+任务详情弹窗+一堆 helper(mkStages/epTasks/activeProd/statusLabel…),约 140 行死 mock 删净;残留引用 0、build 通过(`index-BFCB3x2T.js`)。任务看板至此**全真实无 mock**。

## 2026-06-22 — 去 Demo（第3刀·收尾）：看板"一句话下达目标"接真实中枢 AI（方案A）
- 负责人"继续"→ 走方案 A：把看板招牌交互"一句话下达创意"从 mock(`CommandCenter`+`useAiAgent` 假卡片)改成**真的驱动中枢 AI**。
- LiveView 新增 `askFromBoard()`:输入 → 设 `aiDraft` + 打开中枢 AI 面板 + 复用真实 `aiSend()` 发给 bot 的 DM 房间,结果在右侧面板真实显示。删 `CommandCenter`,换成简洁 hero 输入框。
- 级联删 6 个死文件:`CommandCenter` + `useAiAgent`(大块 mock 卡片生成器) + `useAiPanel` + `data/command.ts` + `data/todos.ts` + `useLiveChannels`。
- **数据看板至此全真实**:品牌标题 + "一句话下达目标"(真 AI) + 4 张真实 KPI 卡。build 通过(`index-Dv4_56u-.js`)。纯前端,**发 dist**。
- 剩余 demo(独立任务,非看板):任务看板(`productionTabs` 内联 mock 剧集数据,要做需任务后端)、ProfileHome(个人主页=模块5)。业务图表如需回来再定数据源。

## 2026-06-22 — 去 Demo（第3刀·续）：移除看板影视业务假图表（方案C）
- 负责人"继续"→ 走方案 C（只留真实平台数据）。把看板里剩下的**影视业务假图表**全部移除:播放趋势/制作量双图(grid-2)、剧集列表 UnitGrid + 饼图(grid-3)、BizPanels——这些是 CosMac 不拥有的业务数据。
- 级联删 5 个死文件:`PanelChart/UnitGrid/BizPanels` 组件 + `useChart` + `data/charts.ts`（build 验证无 live 引用）。
- 现在数据看板 = 品牌标题 + AI 指令中枢(`CommandCenter`) + **4 张真实 KPI 卡**。干净、真实。
- build 通过(`index-B3fs1BNA.js`)。纯前端,**发 dist**。
- **剩最后一处看板 demo**:`CommandCenter`（"一句话下达创意"→出选题/脚本/方案卡，走 `useAiAgent` mock）。它是真·中枢 AI 侧栏的演示重复版。待负责人定:接真实 AI / 移除 / 保留。业务图表若要回来,定数据源(后台手填 or 外部API)。

## 2026-06-22 — 去 Demo（第3刀·起步）：数据看板 headline KPI 接真实平台数据
- 看板原来 4 个大数字是影视业务假数据(剧集播放/粉丝数/AI制作)——这些 CosMac 不拥有(要工作室填或接外部API)。先把它们换成 **CosMac 真正拥有的平台运营指标**。
- **后端** `GET /cosmac/stats`(带本人 token,whoami 校验)：付费会员/创作者数(控制室)+ 工作流运行/完成订单/知识库文档数(cosmac DB)。每项独立兜底,缺 DB 不报错;CORS 预检放行。
- **前端**：`getPlatformStats()` + 看板 headline KPI 改用 `boardKpis`(真实数据→「付费会员/工作流运行/完成订单/知识库文档」;没拿到时回退占位防空屏)。
- 验证：加 stats 端点用例;**194 单测过**、ruff、build(`index-CcOREdpx.js`)。需发 dist + 重启 bot。
- **诚实边界**：只换了 **headline KPI 4 卡**;看板下面的图表/单元格(播放趋势/剧集列表等)仍是占位——那些是**影视业务数据,CosMac 不拥有**。要真实化需负责人定数据源:① 后台手填业务数据 ② 接抖音/B站等外部 API ③ 砍掉只留平台运营数。

## 2026-06-22 — 去 Demo（第2刀）：清占位按钮 + 删更多死组件
- 续上一刀。本轮发现 TopBar/Composer/ChannelSidebar/PluginRail/WorkspaceRail/DepartmentCreateModal 等组件**也从不被 import**（orphan 扫描此前被 CSS/注释里的同名字符串误判成"还在用"）——它们携带的占位按钮随组件一并删除。
- 又删一批死组件/composable/data（级联孤儿，build 全程绿验证无 live 引用）：上述组件 + ToastHost/TopUserMenu/TopAppSwitcher/ChannelHeader/ChartCard/RichCard/DocPreview/ChannelTitleMenu/CCTVFrame + useComposerAi/useDepartmentCreate/useCardAction/useFocusMode + data/messages/{safety,ops,energy,office,duu}。
- **LiveView 里真·live 的占位按钮**：移除全局搜索框、提及、收藏、附件(×2)、表情、放大态"Cowork 风"演示左栏(模式切换/项目/产物/定时任务/派发/最近)——都未接后端、点了只弹"(演示)"。频道检索本就有左侧栏「查找频道」真功能,保留。
- **唯一保留的占位**：`ProfileHome.vue`(个人主页)——负责人要把它做成模块5,整面保留待重写,不在本轮动。
- 本轮共删 **27 个文件**;build 通过(`index-CyB2NomE.js`)。**需发 dist**(产物继续变小)。
- 至此 live 用户可见层除"个人主页(模块5)+数据看板/任务看板(mock数据待接真)"外,占位假按钮已清干净。

## 2026-06-22 — 去 Demo（第1刀）：删除死代码（演示稿 App.vue 整棵树 + 路由视图）
- 负责人要求"代码里不能有 demo、要真实落地"。第一步**清死代码**:本应用根是 `LiveView.vue`(main.ts 直挂)、不走 `<router-view>`,所以演示稿的 `App.vue` 整棵组件树 + 路由整页视图**从不渲染=死代码**。
- 删除 **18 个死文件**(build 验证全程绿,确认无 live 引用):`App.vue`、`AiChatPanel.vue`(demo AI 面板)、7 个路由视图(`DashboardView/SafetyView/EnergyView/OfficeView/DuuChatView/TodoView/OpsChannelView`)、及级联孤儿(`SystemAiModal/TypeOut/MessageStream/MessageItem/CardActionModal`、`useSystemAi/useDashboardDetail/useClock/useAutoHideScrollbar`)。
- `router/index.ts`:移除死视图 import,`/` 等路由改指 `Blank`(保持 hash 合法;只有 `name:'dashboard'` 被 live 代码引用,已保留)。
- **对用户零影响**(这些本就不渲染);纯清理代码里的 demo。build 通过(`index-Lu8l49N_.js`)。**需发 dist**(产物变小)。
- **下一步(去 demo 第2/3刀)**:① 清 live 组件里的占位按钮(TopBar/Composer/ChannelSidebar/ProfileHome 里点了弹"(演示)"的);② 把 live 的「数据看板/任务看板」从 mock 数据(`canvas/*`+`data/*`+`useAiAgent`)接真实数据。

## 2026-06-22 — 体验：中枢 AI 对话区自动滚到底部
- 反馈:在右侧真·中枢 AI 面板聊天时,bot 回复出现在视口下方、不自动滚动,要手动下拉才看得到。
- 修(`LiveView.vue`):给 `.ai-body` 加 ref,`watch(aiMsgs)` 来新消息 + `watch(aiOpen)` 打开面板时 `nextTick` 滚到底。沿用 `AiChatPanel.vue` 既有同款逻辑(`.ai-body` 本就 overflow-y:auto)。
- 验证:build 通过(`index-BnHEoYzu.js`)。纯前端,**发 dist** 即可。

## 2026-06-22 — 关键修复：会员 state_key 不能用 @user_id（Matrix 403 "set others state"）
- 现场实测「模拟支付」最终卡在开会员：bot 写 `cosmac.member@<room>` 403 `M_FORBIDDEN "You are not allowed to set others state"`。
- 根因:per-user 会员事件用了 **state_key = 用户 @id**。但 **Matrix 硬规则:state_key 以 `@` 开头的事件只有该用户本人能写**——bot(@guduu)/管理员根本无权给"别人"开会员。单测的假 client 没模拟这条规则,所以一直没暴露(我的疏漏)。**注:那套"已支付但开通失败→回滚订单"的保护真生效了,没产生扣款脏数据。**
- 修:state_key 改用**去掉开头 @** 的形式(`@a:host`→`a:host`),不触发该规则;真实 user_id 存进 `content.uid`,读取以 uid 为准(兼容旧数据 state_key)。前后端一致(`members.py` + `client.ts`)。同样修好了**管理后台给别的用户设会员等级**(之前也会 403)。
- 防回归:测试假 client 现在**模拟 Matrix 这条规则**(@开头 state_key 写入返 False),`test_plans_checkout_manual_grant`(支付给别人开会员)等用例据此校验。**全量 193 单测过**、ruff、build(`index-CCXR1XCG.js`)。
- 无需数据迁移:之前的 @key 写入全是 403 失败、没落任何脏数据。**需发 dist + 重启 bot。**

## 2026-06-22 — 模块4 修复：manual 回调缺 CORS 头导致前端 Failed to fetch
- 现场实测「模拟支付成功」报 `Failed to fetch`。根因:`/cosmac/pay/callback/<provider>` 的响应**漏了 CORS 头**(给 plans/checkout/me 都加了、唯独漏这个)。manual 测试通道是**浏览器**调的,响应无 `Access-Control-Allow-Origin` → 浏览器直接拦下、连状态码都读不到。
- 修:回调所有响应加 `cors=True`(真实渠道是服务端调用、带了也无害)。HTTP 集成测试补断言"回调响应带 CORS"防回归。
- 验证:`test_pay_http` 5 例过、ruff 过。**后端 only → 只重启 bot,不发 dist**。
- (注:修完后若点「模拟支付」显示"测试支付通道未开启",是 manual 默认禁用,需 `COSMAC_PAY_ALLOW_MANUAL=1`,与本 bug 无关。)

## 2026-06-22 — 模块4 P2b+：会员状态展示 + 端到端 HTTP 模拟测试（⚠️真实付款未测）
- 负责人定：暂不接 Stripe（账号未开），**先用 mock(manual)通道**跑通业务、继续开发，并**明确记录真实付款尚未测试**。
- **端到端 HTTP 模拟测试**（`test_pay_http.py`）：起真实 bot HTTP server，用 requests 打 `/cosmac/pay/*`，验证路由 / CORS 预检 / Authorization 头 / body 解析 / manual 回调分发全对。**证明 mock 链路 HTTP 层端到端跑通**。
- **会员状态展示**：新增 `GET /cosmac/pay/me`（带本人 token→当前生效等级+到期）；升级弹窗顶部显示"你当前是付费会员·到期X"，按钮按是否已会员显示「续费/升级」或「立即开通」，开通后刷新状态。
- 验证：**全量 193 单测过**（含 5 个 HTTP 集成）、ruff、build(`index-bt-Ew52q.js`)。需发 dist + 重启 bot。
- ⚠️ **真实付款测试状态（重要·待办）**：**从未做过任何真实支付渠道(Stripe/PayPal/USDT/支付宝/微信)的端到端测试**。当前唯一可用的"支付"是 manual 测试通道(HMAC 验签、不收款，默认禁用、需 `COSMAC_PAY_ALLOW_MANUAL=1` 才生效)。业务链(下单/幂等开通/续费顺延/到期)已单测+HTTP集成测试覆盖，但**钱真正怎么进来 = 未验证**。开通真实渠道后必须：① 实现对应 adapter 的 `create_checkout`/`parse_callback`(验签)；② test mode 端到端走一遍(下单→真支付→webhook→开会员)；③ 上线前关掉 manual 通道。

## 2026-06-22 — 模块4 P2b：用户侧「升级会员」打通(bot 支付端点 + 前端弹窗 + manual 端到端)
- 让顶栏「✦ 升级会员」真正能用。前端够不到 cosmac DB,所以走 bot 的 HTTP 端点:
- **bot 支付端点**(`appservice_bot.py`):`GET /cosmac/pay/plans`(公开读上架套餐)、`POST /cosmac/pay/checkout`(带用户 access token,bot `whoami` 验明身份→建订单→返回支付方式)、`POST /cosmac/pay/callback/<provider>`(平台验签→幂等开会员)。加 **CORS**(app.cosmac.cc→hs.cosmac.cc 跨源,含 OPTIONS 预检);复用既有 body 限长/超时/有界连接防护。
- **身份校验**:`matrix_client.whoami(token)` 用用户自己的 token 调 Synapse whoami 拿 user_id,只校验不存储。
- **安全闸**:manual(测试/线下确认)渠道**默认禁用**——回调返回 403,防任何人自助白嫖会员;测试整条链时临时设 `COSMAC_PAY_ALLOW_MANUAL=1`,**上线前务必关掉、改用真实渠道**。
- **前端**:`MembershipModal.vue`(套餐卡片+货币切换+下单+测试通道模拟支付+开通提示);`client.ts` 加 `payGetPlans/payCheckout/payManualConfirm`(fetch bot 端点、带 access token);顶栏「升级会员」从弹 toast 改成开这个弹窗。
- 验证:`test_members.py` 加 PayEndpoint 用例(公开读套餐/下单 whoami 校验/manual 默认403→开关后开通);**全量 188 单测过**、ruff、build(前端)通过。**后端+前端都改,需发 dist + 重启 bot**。
- **遗留/下一步**:① 要在后台先配至少一个套餐;② 测试 manual 通道要设 `COSMAC_PAY_ALLOW_MANUAL=1`;③ 确认 nginx 把 **`/cosmac/`(整段)** 代理给 bot(不只 `/cosmac/wf/`),否则 `/cosmac/pay/` 404;④ P2c 接 Stripe(test mode)替掉 manual。

## 2026-06-22 — 模块4 P2a：后台「会员套餐」配置页(写 cosmac.plans)
- 负责人指出"升级会员"该和支付一起做(对)。P2 拆三块,先做 P2a：管理员能配套餐(否则没东西可买)。
- **后台「会员套餐」页**(`AdminView.vue` 新 tab,💳)：套餐 CRUD——slug/名称/等级(付费/创作者)/有效期(天)/各币种价格/上下架。价格编辑用「元」、保存 ×100 转「分」存,展示再 /100。写控制室 `cosmac.plans` state event(bot 端 P1 的 `OrderService.list_plans` 已能读)。
- **数据层** `client.ts`：`getPlans/setPlans` + `PlanDef` + `PLAN_CURRENCIES`(USD/CNY/USDT)。getPlans **读失败抛异常**(404→[])、后台加载失败禁用新建/不渲染可编辑区,杜绝空列表覆盖真实套餐(同 gating 保护)。
- 架构说明(写进回复):前端是 Matrix 客户端、够不到 cosmac DB,所以购买流程(下单/支付)要走 bot 的 HTTP 端点——P2b 做(套餐列表公开读 + 下单 Matrix 鉴权 + 支付 webhook + 前端「升级会员」面板 + manual 渠道端到端),P2c 接 Stripe。
- 验证:client build 通过(`index-BlTrGUgp.js`);纯前端(后端 P1 已能读 plans)。**需发 dist**。

## 2026-06-22 — 模块4(交易系统·会员订阅)开工：P1 地基(支付抽象+订单+会员到期)
- 负责人拍板:主线=**会员订阅/充值**,多渠道(Stripe/PayPal/USDT/支付宝/微信)按 IP 地理路由,范围"较完整"。先落**与支付商无关的地基**(纯业务逻辑、mock 支付、单测验证,不需商户密钥):
- **套餐定义**:控制室 `cosmac.plans` state event(后台配,同 workflows/gating 套路);`trading/plans.py` 强校验解析(免费等级/无价/非正时长/重复 slug 全丢)。价格用最小货币单位整数(分)。
- **订单**:DB `cosmac_order`(`db/models.py` + `db/order_repo.py`);`mark_paid` 用原子 CAS(created→paid)做**恰好一次**闸,重复 webhook 不重复开通;开通失败可 `revert_to_created` 待重试,避免收钱没开会员。
- **支付抽象**:`trading/base.py` 的 `PaymentProvider`(create_checkout/parse_callback),像多模型 AI 那样可插拔各渠道;**密钥只进服务端 env**。P1 实现 `trading/manual.py`(HMAC 验签的手动/测试确认渠道)。
- **订单服务** `trading/service.py`:下单(校验套餐/货币/渠道→建单→出支付方式)+ 支付成功(幂等置 paid→开/续会员)。**续费从原到期日顺延**(还在有效期内续费不亏天数)。
- **会员到期**:扩 `members.py`——`grant` 带 `expires_ts`(0=永久)、新增 `active_tier`(到期回落免费)/`get_record`(续费取当前到期日);`get_tier`/`get_all` 全部到期感知。
- 验证:新增 `test_trading.py` 9 例(套餐解析/算价建单/开通到期/**幂等不重复续期**/**续费顺延**/手动验签);**全量 186 单测过**、ruff 通过。**纯后端地基、未接入 bot/HTTP 运行路径**,不改现网行为,无需部署(bot 下次重启 create_all 自动建 `cosmac_order` 表)。
- **下一步(P2)**:Stripe adapter(test mode)+ 公开 webhook 端点(验签→`on_payment_success`)+ 前端套餐页/下单/支付方式选择。需要负责人提供 Stripe 测试密钥。

## 2026-06-21 — 权限与工作流可靠性复查修复
- **门控 fail-closed + 退避**：控制室首次读取失败时临时收紧为仅管理员；已有成功缓存继续沿用。失败后短暂退避，避免 Synapse 故障时每条消息重复请求。
- **会员按用户拆分 state**：新写入改用 `cosmac.member`，以 user_id 为 state_key；旧 `cosmac.members` 聚合事件只读兼容，free tombstone 可覆盖旧记录。消除并发整表覆盖和单事件容量上限。
- **前端严格区分错误**：控制室别名只有 `M_NOT_FOUND` 才视为不存在；网络/权限错误向上抛。后台会员读取失败不再伪装成“全员免费”。
- **工作流可靠状态**：采用 `queued -> pending -> processing`。只安全回收未开始外呼的 queued；网络超时/5xx 保留 pending/token，避免平台已接单后诱导重试。pending 默认 7 天超时（`COSMAC_WF_CALLBACK_TIMEOUT` 可调），到期提示先核对外部平台。
- 验证：`ruff` 通过；CosMac 后端 **177 单测全过**；client build 通过（JS hash `index-BXhjDtJk.js`）。本次前后端均有改动，需部署 dist 并重启 `guduu-bot`。

## 2026-06-21 — 修复：管理后台「工作流」平台下拉框文字被竖直裁切
- 现象：工作流连接器表单里 `平台/请求方法/Dify应用类型` 等 select，选中项文字下半截被切掉。
- 根因：两套样式叠加打架——全局 `.cam-select` 给了**固定 `height:34px`**，而 `AdminView` 的 `.adm-form .adm-field select`(优先级更高)又把 `padding` 设成 `9px 11px`+`line-height:1.5`。34px 固定高 − 上下 18px 内边距 = 仅 16px 容文字 < 行高 ~21px → 裁切。
- 修法：给 `.adm-form .adm-field select` 加 `height:auto`(scoped 选择器优先级更高，覆盖固定高)，按内容自适应。只影响本表单，其它地方的 `.cam-select` 不动。**需部署前端 dist**（纯前端、无需重启 bot）。

## 2026-06-21 — 账号权限分层：功能门控（按会员等级限制能力，后台可配）
- 接上一条会员等级地基，做**功能门控**。负责人定调：后台加一个设置页，把现有功能都列进去**逐项人工配置**所需会员等级；以后新增功能也在后台目录里加。
- 机制（沿用全项目套路）：控制室 **state event `cosmac.gating`** 存「能力→最低门槛」，bot **服务端强制**（客户端只配置、挡不住绕过）。门槛 4 级阶梯 **免费 < 付费 < 创作者 < 仅平台管理员**；**平台管理员永远不受会员等级门控**（staff 用一切，免得给自己开会员），`仅平台管理员`门槛用于高危/共享付费凭据能力。
- 能力目录（`cosmac/members.py` GATE_CATALOG，前后端各一份）：`ai_chat` 基础AI对话、`knowledge` 知识库(RAG+命令)、`create_room` 建群/开专班、`workflow_run` 跑工作流。**默认**前三项免费(不限制)、`workflow_run`=仅管理员(**维持原行为、零回归**)。
- 强制点（bot）：① `ai_chat` 在对话回复入口(命令如 会员/技能/知识/工作流不受影响、保证随时能查/升级)；② `knowledge` 在知识命令 + RAG 注入；③ `create_room` 在「建专班」命令 + create_room 工具；④ `workflow_run` 在「工作流 跑」命令 + run_workflow 工具。**工具层也堵**：Toolbox 加 `gate_check` 钩子，防「让 AI 帮我建群/跑工作流」绕过命令门控。
- 后台 UI：AdminView 新增「🔐 会员权限」tab，一张表逐项下拉选门槛，写 `cosmac.gating`。
- 验证：`test_members.py` 增门控测试(阶梯/解析/Store/裁决/工具映射/命令门控)，全模块 170 例过、ruff 干净；前端 `vue-tsc` 严格类型检查 + build 通过、preview 加载无 console 错误（后台交互需登录态 Synapse，未现场点测）。**需部署前端 dist**。

## 2026-06-21 — 账号权限分层：会员等级（免费/付费/创作者）地基
- 需求：在「服务器管理员」之外，给普通用户叠一层**会员身份**：免费 / 付费 / 创作者会员。负责人拍板的关键决策：
  - **靠购买获得**，后台也能**手动调整**；本期先做地基 + 后台调整，**购买预留接口**（真实支付是模块4，未开工，不做假支付）。
  - 存控制室 **state event `cosmac.members`**（与 `cosmac.ctrl.admins` 等同套路：管理员浏览器写、bot 读；权威数据、用户不可自改，付费门槛才靠得住）。
  - **管理员身份独立于会员等级**（正交）——管理员仍走 Synapse admin 标志，会员等级是另一维。
- 实现：
  - 后端：新建 `cosmac/members.py`（等级枚举/标签/校验 + `MembersStore` 读写控制室 + `grant` 预留授予入口）；`config.py` 加 `MEMBERS_EVENT_TYPE`；`matrix_client.py` 加通用 `set_state_event`；`appservice_bot.py` 加「会员」命令（人人可查自己 `会员`/`我的会员`；平台管理员可 `会员 列表/设置/撤销`）+ `grant_member_tier`（**预留给模块4支付**，source=purchase）。
  - 前端：`client.ts` 加 `MEMBER_TIERS/getMembers/setMemberTier/memberTierLabel`；`AdminView.vue` 用户表加「会员等级」列（行内下拉即时调整，乐观更新+失败回滚，付费/创作者带强调色）。
- **已知边界**：appservice 命名空间是 `@guduu.*`，bot 无法代写普通用户 account data，故普通用户查自己等级走「DM 问 bot」而非个人主页徽章（个人主页徽章需另建读路径，按需再补）。门控（不同等级能用哪些功能）本期不做。
- 验证：新增 `test_members.py` 15 例全过；后端全量 160 例过、ruff 干净；前端 `vue-tsc` 严格类型检查 + build 通过，preview 加载无 console 错误（管理后台交互需登录态 Synapse，未现场点测）。**需部署前端 dist**。

## 2026-06-21 — 会员/门控 收口（评审5项）：读失败不清空/门控不失效开放/启动不误杀/文档同步
- 评审命中模块4预热(会员/门控)的几处真 bug，修掉 4 项真·廉价正确的，第 5 项(单 state event)记为模块4正式开工时做的架构边界：
- **#2【P1 读失败清空其他会员】**：`grant()` 用会吞异常的 `get_all()` 读当前 map，瞬时读失败→空表→写回**清空所有其他会员**。修：新增 `_read_all_strict`(404→空合法、瞬时错→抛)，grant **读失败即放弃写入**。前端 `setMemberTier` 同理：区分 `M_NOT_FOUND`(从空开始) vs 瞬时失败(抛错中止)。
- **#3【P1 门控首读失败失效开放】**：bot 无缓存时读失败→回落默认(AI/知识库/建群默认免费)→管理员配的付费门控被绕过。修：读失败**不刷新 cache_ts**(下次立即重试，不把失败缓存一个 TTL) + 启动 `gating.warm()` 预热把窗口压到极小。前端 `getGating` 读失败**抛异常**(不再伪装默认)，后台加载失败则**禁用保存 + 显示错误态**，杜绝"默认值覆盖真实策略"。
- **#1【P1 启动恢复误杀在跑的异步任务】**：`reclaim_orphans` 无条件把全部 pending 标 error+清 token，但 webhook 可能已提交成功、外部仍在跑会回调→误杀+用户重试双扣费。修：加**1h 宽限期**，只回收久未更新的遗孤，新近 pending 留着等回调正常完成。
- **#5【P2 AGENTS.md 未同步】**：同步 AGENTS.md+CLAUDE.md 路线图——模块3 标 ✅、模块4 标「⬜ 预热」(会员/门控地基已立，本体未做)。
- **#4【P2 全部会员存单个 state event】**：读改写后写覆盖前写、量大碰事件大小上限。**#2 的 abort-on-read-failure 已堵住数据丢失**；并发/容量属架构层，**记为模块4正式开工时迁「每用户独立 state key 或 DB」**(已写进路线图「已知边界」)。
- 验证：加 读失败不覆盖/门控重试/warm/启动宽限期 等用例；**175 单测全过**、ruff、build(`index-CFHDiDiH.js`)通过。**需部署 dist + restart guduu-bot**。

## 2026-06-21 — 品牌化清理（R·彻底清除 demo 人设"筱雨" + Matrix/Synapse 复查）
- 负责人改定：**全删 筱雨 demo**。把全客户端 ~60 处硬编码"筱雨"统一脚本重命名为真实租户 **安其/安其影视工作室**（保留 demo 结构、避免删数组破坏 fallback 渲染；真实后端下这些 mock 本就不显示）：
  - `筱雨中枢 AI→安其中枢 AI`、`筱雨工作室→安其影视工作室`、`筱雨-MBP→安其-MBP`、人名 `筱雨→安其`、头像 `雨→安`。
  - 覆盖 `useAiAgent`(演示团队/派单/卡片)、`data/messages/*`(模拟聊天)、`data/channels|todos|dashboards|pluginStore`、`useCli|useCardAction|useDashboardDetail|useChannelAdmin`、`SystemAiModal|AiChatPanel`、注释与 CSS。grep 复核 **0 处筱雨残留**。
- **Matrix/Synapse 复查**：客户端 70 处命中，分类后——**55 处是协议/SDK/内部标识**(`matrix-js-sdk`/`/_matrix`/`/_synapse`/`m.room.*`/`MatrixClient`/`.well-known`，① 协议层+③ 内部，**绝不能改**)，**15 处是开发者代码注释**(准确描述"接 Matrix/Synapse 真后端"，非用户可见、§7 ② 不含注释)。**用户可见层 0 处 Matrix/Synapse 泄漏**（已在上一刀清掉）。结论：保留这两类是对的，强行改注释/SDK 反而错。
- 验证：client build 通过（新 hash `index-CZ4rOlxp.js`）；纯字符串重命名。**需部署前端 dist**。

## 2026-06-21 — 品牌化清理（R·demo 人设"筱雨"残留→tenant 配置，只修常显文案）
- 发现 demo 人设"筱雨工作室"半迁移：`tenant.ts` 已配真实租户**安其影视工作室**（且其 docstring 明令"不可在源码写死主理人标识"），但 ~20 处仍写死"筱雨"。负责人拍板**只修常显文案**（任何后端下都显示的地方），demo/mock 数据保留作示意。
- 改（路由到 tenant 配置，符合换皮设计）：
  - `useCustomAssets.ts`：建 Agent/工作流的**表单占位符** + 默认种子资产"你是筱雨工作室的…"→`${tenant.name}`、"通知筱雨确认"→`${tenant.shortName}`（导入 tenant）。
  - `useSystemAi.ts`：中枢 AI 默认名"筱雨中枢 AI"→`${tenant.shortName}中枢 AI`；默认 prompt"经筱雨确认"→`${tenant.shortName}`。
  - `useChannelAdmin.ts`：频道默认 AI prompt"经筱雨确认"→`${tenant.shortName}`。
  - `AiChatPanel.vue`：AI 头像 `alt="筱雨工作室"`→`中枢 AI`。
- **保留**（demo/mock 示意数据，真实后端下不显示）：`useAiAgent` 演示团队(老周/阿杰/小鹿/筱雨)与派单消息、`useCli` 筱雨-MBP、`data/messages/*` 模拟聊天、mock 成员/卡片/待办。
- 验证：client build 通过（新 hash `index-BLY_ujTj.js`）；纯静态配置/文案改动。**需部署前端 dist**。

## 2026-06-21 — 品牌化清理（R·呈现层去 Matrix/Synapse 字样）
- 按 §7 三层红线，**只改 ② 呈现层**（用户/管理员可见字样），不碰 ① 协议层、③ 内部标识符：
- 核对后发现主品牌面**已全是 CosMac Star**（登录页/顶栏/中枢AI/页面标题），唯一残留 `guduu` 是 `BOT_LOCALPART='guduu'`（bot 账号身份，负责人已决定不迁移）→ 保留。
- 清掉**面向用户的技术品牌词**：频道成员帮助文案去掉"来自 Matrix/标准 Matrix 邀请/kick"→中性表达；成员管理提示"Synapse Admin API 不对外开放"→"后端管理接口"；数据概览"数据来自 Synapse Admin API"→"服务器管理接口"；恢复账号密码提示"Synapse 要求"→"服务器要求"；AI/工作流密钥说明里"Matrix 事件无法加密/不进网页Matrix"→"平台事件/聊天数据"。
- **刻意保留**：`/_synapse/admin`、`/_matrix/...` 等**字面协议路径**（① 不改，且管理员配 nginx CORS 时真要用到）；开发者代码注释里准确描述 Matrix/Synapse 技术栈的字样（非用户可见，不属 ②）。
- 验证：client build 通过（新 hash `index-DnhZRWB9.js`）；纯静态文案改动、无逻辑。**需部署前端 dist**。

## 2026-06-21 — 模块3（工作流引擎）收尾打 ✅
- 核对全链路后确认**模块3已功能完整**，最后一块"后台编排 UI"其实早在前几轮就建好了：
- **后台编排 UI**（`AdminView.vue` 工作流面板）：4 平台（webhook/Dify/Coze/ComfyUI）连接器的列表/新建/编辑/启停/删除；平台相关字段按需显隐（webhook 的 method+async / Dify 的 mode / Coze 的 ref_id / ComfyUI 的 graph）；凭据**只填名**（真值在服务端 env `COSMAC_WF_<CRED>`，不进网页/Matrix）；保存写控制室 `cosmac.workflows` state event。
- **全链路自洽**：UI→`setWorkflows`→控制室 state event→bot 读(`appservice_bot.py` get_state_event)→`run_connector` 按平台分发（wf.py 消费 mode/input_key/ref_id/graph，键名与 `WorkflowDef` 完全对齐）。
- 至此模块3全件齐活：引擎(4平台)+聊天命令+`run_workflow`工具+异步回调+运行记录+后台UI+安全(够用即止)。durable队列/fencing/精确一次=已知边界本期不做。
- 验证：代码层核对全链路键名一致 + client build 通过；UI 是前几轮已提交进 dist 的产物，本次**无代码改动**（仅文档），**无需部署**。增强项(更多适配器/graph 上传)按需再补。

## 2026-06-19 — 工作流安全（收口·只做零downside的对的修法 + 架构边界说清楚）
- 评审又报 5 项。其中 3 项是真·廉价正确修法，已做；另 2 项（durable队列/多实例fencing）是**架构级**、单实例下属过度设计，已在回复里和负责人确认停止线，不再无限打补丁：
- **#1【P1 内存LRU提前标完成】**：`_remember_txn` 原在处理**前**写入→处理途中重试命中内存快路回200，原处理若崩 DB 的 processing 再没机会重抢→永久丢。修：移到 `_finish_txn` **之后**，内存只记真正处理完的。
- **#2【P1 后台任务不抗重启】**：进程内线程池不跨重启，async 运行会永久停在 pending。修（可见性，非恢复执行）：启动时 `reclaim_orphans` 把遗留 pending/processing 结清为 error 并通知群"因重启中断、请重试"。真正的不丢任务需 durable 队列（见架构说明，本期不做）。
- **#3【P1 无并发连接上限】**：ThreadingHTTPServer 每连接一线程，洪泛仍能堆线程。修：`_BoundedThreadingHTTPServer` 用 BoundedSemaphore(128) 卡并发连接，超限直接关连接不开线程。
- **#4（多实例 fencing）/#5（单事件异常整批仍done）**：单实例部署下 #4 的"另一实例重抢"不会发生；#5 的"重试整批"会重新触发已成功的付费工作流，真正修需 per-event 幂等键——两者都属 durable/exactly-once 架构，单bot小规模属过度设计，**记为已知边界**。
- 验证：加 启动结清中断运行 用例；**145 单测全过**、ruff 通过。纯后端，仅 `restart guduu-bot`。

## 2026-06-19 — 工作流安全（四收口·这次动真格的并发/时限语义）：绝对时限 / 原子抢占 / 崩溃不丢 / 回调400 / 三池
- 上一轮的修法被指出**仍可绕过**，这次从语义层重做：
- **#1【P1 Slowloris 仍可绕过】**：`socket timeout` 只约束单次 recv，攻击者每 19s 挤一字节即不断重置 20s 计时器，请求行/头/体都能被无限拖住。修：新增 `_DeadlineSocket` 包住读端 socket，把**整次请求的绝对时限下沉到每次 recv**（每次读前把超时设为"距 deadline 的剩余时间"，随墙钟单调缩到 0，与对端是否还发字节无关）；在 `setup()` 装一处即覆盖请求行+头+体。
- **#2【P1 持久去重非原子】**：先 `txn_seen()` 再 `mark_txn()`，并发同 txn 都查不到→各自处理→双触发付费。修：`claim_txn` 改**一次原子写决定归属**——新事务原子 INSERT(主键冲突即让位)、processing 残留用带条件 UPDATE+rowcount 抢占。
- **#3【P1 先标记后处理永久丢】**：标记 done 后、处理前崩溃 → 重试被当已完成跳过 → 整批永久丢。修：两阶段 `processing→done`，崩在中途留 processing，过期(`_STALE_SECONDS`)后可被重新抢占(at-least-once)；do_PUT 对 INFLIGHT 回 **503 让 Synapse 重试**，不再无条件 200。
- **#4【P2 非法回调 JSON 当成功】**：JSON 解析失败用 `{}` → 发"无内容"并结清 → 平台收 200 无法重投。修：解析失败/非对象 → 回 **400 且不动 pending**。
- **#5【P2 异步提交与快任务共池】**：提交仍排在 webhook/Dify/Coze 后。修：拆 **submit/fast/slow 三池**，异步"提交"独占 submit 池绝不被堵。
- 附：`cosmac_seen_txn` 加 `done`/`claimed_at` 列；无 alembic，新增 `_heal_ephemeral_schema` 对这张**7天TTL缓存表**做自愈(老库缺列→DROP重建，仅限缓存表)，prod 重启即生效。
- 验证：加 原子抢占/过期重抢/跨重启识别/schema自愈/async非webhook/提交异常结清 等用例；**144 单测全过**、ruff、build 通过。
- 部署：**纯后端**(无前端改动，dist 不变) → 仅 `restart guduu-bot`，无需发 dist。

## 2026-06-19 — 工作流安全（再再收口）：Slowloris / 事务去重持久化 / 异步只限webhook / 提交异常结清 / 双池
- **#1【P1 Slowloris 打满线程】**：ThreadingHTTPServer 每请求开线程，回调按 Content-Length 阻塞读、无 socket/read deadline——攻击者慢发/不发正文即占住线程，512KB 上限无效。修：Handler 设 `timeout=20`（socket 级超时）+ 新增 `_read_body` **按总时限分块读**（慢速 drip 也被 deadline 卡死），回调和事务端点都用，超时回 408。
- **#2【P1 事务去重只在内存】**：`_seen_txns` 重启即丢→Synapse 重放可再触发付费工作流，且无限增长。修：内存改**有界 LRU**(4096)；新增 `cosmac_seen_txn` 表 + `db/dedup.py`，**先记后处理**（at-most-once）持久化去重，重启后识别重放；DB 不可用则退回内存（不阻断收消息）。
- **#3【P2 非 webhook 被存为异步】**：切到 Dify/Coze/ComfyUI 时 async 复选框隐藏但值没清→后端挂永远等不到回调的 pending。修：前端保存时 `platform!=webhook` 强制 `async=false`；后端 `supports_async_callback` 双保险（只 webhook 走回调，其余即便 async=true 也按后台跑）。
- **#4【P2 异步提交异常留永久 pending】**：`_submit` 捕获异常只记日志，不结清/通知。修：异常也 `complete_run(error)` + 通知群。
- **#5【P2 单池队头阻塞】**：4 个长 ComfyUI 占满 worker，异步 webhook 的"提交"只能排队。修：拆 **fast/slow 两个池**——ComfyUI 走 slow，提交/快连接器走 fast，互不堵。
- 验证：加 持久化去重/LRU上界/async非webhook不挂pending/提交异常结清 等用例；cosmac **141 单测全过**、ruff、build 通过。
- 部署：改了 `cosmac/`+前端 → 发 dist + `restart guduu-bot`。⚠️ 建议 nginx 给回调端点也加 `limit_req`/`limit_conn`（应用层挡住单连接慢占线程，海量连接仍靠网关限流）。

## 2026-06-19 — 工作流模块**彻底自审**（主动一次挖完，不再被动挤牙膏）
- 不再等审查工具一批批喂：把整个工作流链路（HTTP 入口 + 鉴权 + 回调 + 后台池 + 4 连接器 + 凭据 + DB）系统性对抗性过了一遍。结论 + 这次主动补的：
- **自审确认无问题的**：① 全工作流外呼**只此 `wf.py` 一处**（grep 确认无散落的 requests 调用），SSRF/凭据绑定/响应限流覆盖完整；② 无死代码（`_sender_can_run_workflow` 已清）；③ gzip 解压炸弹被 `_fetch` 的**累计字节封顶**接住（cap 在解压后字节上）；④ 凭据/密钥无日志泄露；⑤ ComfyUI 图注入已 json 转义、图数/单图都限。
- **主动补的 2 处**：
  - **`_check_auth` 改常数时间比较**（`hmac.compare_digest`）：原 `==` 比 hs_token 有时序侧信道，可被逐字节猜。
  - **事务端点 `do_PUT` 也限请求体**（≤8MB、拒负数/非法 Content-Length）：和回调端点对齐，纵深防御 + 防 `int()` 崩。
- **一个明确的已知残留（暂不修，记着）**：SSRF 的 **DNS-rebinding** 窗口——`getaddrinfo` 校验与 `requests` 实连各解析一次。彻底修需把校验过的 IP 钉死再连（涉及 TLS SNI/证书，改动大、边界多）。实际利用门槛高（需控 DNS + 卡请求窗口重绑），当前挡住所有直球 SSRF。
- 验证：cosmac **137 单测全过**、ruff、build 通过。纯后端 → `restart guduu-bot`。

## 2026-06-19 — 工作流安全（封口）：AI工具异步协议 / 内网开关收紧 / 提交全后台 / 回调幂等txn / 消息截断
- 又 5 个边界，修完：
- **#1【P1 AI 工具不支持异步协议】**：工具把所有连接器当普通后台任务，async=true 也不生成 callback——自然语言触发的异步工作流收不到回调。Toolbox 加 `dispatch_async` 钩子（bot 注入 `_dispatch_async`），async 连接器经工具也走"登记 pending+回调地址"。
- **#2【P1 内网开关放公网明文】**：`COSMAC_WF_ALLOW_INTERNAL=1` 后只校验域名匹配，公网 HTTP 也能带 Bearer。改成：开关放行 HTTP 还要**解析 IP 确属私网/环回**(`_host_is_internal`)，公网即使开开关也强制 HTTPS。
- **#3【P2 异步提交仍阻塞事务】**：`_dispatch_async` 同步调 webhook 提交(可能 30s)。改成登记 pending 后**提交也进后台池**、立即返回；提交失败后台结清 + 通知群。
- **#4【P2 崩溃恢复重复发】**：Matrix 消息发出后、complete_run 前崩溃，5 分钟后重发——`send_text` 每次新 txn id、Matrix 去不了重。改成回调消息用**固定 txn id `cosmac-wf-<run_id>`**，Synapse 据此去重。
- **#5【P2 大结果无限重试】**：回调体 512KB 但消息正文没截断，超 Matrix 事件大小→send 持续失败→无限回 pending。消息正文按 4000 字截断（完整结果在 DB run 记录）。
- 验证：加 AI工具异步分派 / 公网HTTP拒绝 / 环回放行 等用例；cosmac **137 单测全过**、ruff、build 通过。纯后端 → `restart guduu-bot`。

## 2026-06-19 — 工作流安全（再收口）：AI工具全后台 / processing不卡死 / 凭据强制HTTPS / 整体deadline / 轮询异常接住
- 又一轮复查的 5 个异常路径，全修 + 补测试：
- **#1【P1 AI 工具未全后台】**：`run_workflow` 工具之前只后台化 ComfyUI，webhook/dify/coze 仍同步阻塞 Agent+事务。改成**所有连接器都进有界后台池**、立即返回"已开始"、跑完发回群。
- **#2【P1 回调永久卡 processing】**：抢占成 processing 后若 `send_text` 抛异常/DB 失败/进程重启，只回 500、不恢复 pending，重试得 404、结果永久丢。修：① `send_text` 包 try/except，失败（抛或假值）都回滚 pending；② `claim_pending` 支持**重抢卡死(processing 超 5 分钟)的运行**（崩溃恢复），并显式刷新 updated_at 防刚抢的被立刻重抢；③ 已 ok/error 的回调幂等返回 200。
- **#3【P1 凭据走明文 HTTP】**：`credential_for` 只校验了域名、没要求 HTTPS——Bearer 可能被网络窃听。改成**带密钥必须 HTTPS**，内网 HTTP 须显式 `COSMAC_WF_ALLOW_INTERNAL=1`。
- **#4【P2 流式无整体时限】**：`requests timeout` 只管单次读；慢速持续小块发送能长期占住 worker。`_fetch` 加**整体 deadline**（总读时长 ≤ timeout），超了掐断回收。
- **#5【P2 ComfyUI 轮询静默失败】**：`_comfy_poll` 只接 `RequestException`，`_fetch` 抛的 `_TooBig` 会冒泡成静默失败。改成一并接住、当一次失败轮询、优雅超时。
- 验证：加 凭据明文HTTP拒绝 / 卡死可重抢 / 重放幂等 / AI工具全后台 等用例；cosmac **135 单测全过**、ruff、build 通过。纯后端 → `restart guduu-bot`。

## 2026-06-19 — 工作流安全（深修·收口）：凭据域名绑定 + token 离开 URL + 原子回调 + 全后台 + 响应限流
- 再一轮复查抓出的 5 个更深残留，一次修到底：
- **#1【P1 凭据可被导出】**：管理员能把任意 cred 绑到自己控制的公网 URL，SSRF 只挡内网、不挡公网，服务端就把 Bearer 密钥发过去了。新增 `credential_for(cred,url)`：密钥的**允许域名也由服务端 env 固定**(`COSMAC_WF_<CRED>_HOST`)——未绑定或 URL 主机不匹配则**拒绝外发密钥**。webhook/dify/coze/comfyui 四连接器都走它。
- **#2【P2 token 仍在 URL】**：路径段也进 nginx 日志。改成回调 URL **完全不含 token**；token 放进我们 POST 给平台的 payload(`callback_token`)，平台回传 `X-Cosmac-Token` 头鉴权——token 不进任何 URL。DB 仍只存哈希、单次用完即废。
- **#3【P2 并发回调重复发】**：两个回调能同时读到 pending 各发一遍。`wf_repo.claim_pending` 用 `UPDATE...WHERE status='pending'` **原子 CAS** 抢占成 processing，只有一个成功，其余幂等返回 200。
- **#4【P2 同步连接器阻塞事务】**：上次只把 ComfyUI 放后台。改成**所有同步连接器**(webhook/dify/coze≤30s 也算)都进有界后台池，立即返回"已开始"、跑完发回群。
- **#5【P2 响应无大小限制】**：新增 `_fetch`(`stream=True` + 累计字节封顶 + 看 Content-Length)，普通响应 ≤2MB、ComfyUI 单图 ≤16MB，超限拒绝。四连接器全部响应读取都过它。
- 验证：`test_wf` 加凭据未绑定/域名不匹配用例、`test_wf_cmd` 加原子抢占/后台结果/token 离开 URL 用例；cosmac **133 单测全过**、ruff、build 通过。
- 部署：纯后端 → `restart guduu-bot`。⚠️ **破坏性**：带凭据的连接器现在**必须**在服务端配 `COSMAC_WF_<CRED>_HOST=<允许域名>`，否则拒绝外发密钥（安全要求）。

## 2026-06-19 — 工作流安全（补漏）：复查抓出的 6 个绕过/残留全修
- 上一轮修复有真实漏洞，逐个补：
- **#1【P1 DM 绕过越权】**：上次"群里要管理员、DM 放行"——任何人和 bot 开个两人 DM 就能跑全部共享凭据/付费工作流。改成**只许平台管理员**(控制室 power≥50)触发，**不分 DM/群**（新增 `_is_platform_admin`，聊天命令 + AI 工具两路都换）。
- **#2【P1 ComfyUI 重定向绕 SSRF】**：上次只给 webhook/dify/coze 加了 `allow_redirects=False`，ComfyUI 的提交/轮询/下载三处漏了——补齐。
- **#3【P1 回调 DoS 负数绕过】**：`Content-Length:-1` 不命中上限、`read(-1)` 读到 EOF（无界），非整数还抛 ValueError。改成 `0≤length≤512KB`、解析异常一律拒。
- **#4【P2 token 仍进 URL】**：生成的回调地址从 `?token=` 查询参数改成**路径段** `/callback/<id>/<token>`（能配头的平台改发 `X-Cosmac-Token`、token 完全不进 URL）；DB 仍只存哈希。
- **#5【P2 后台无并发限制】**：每次 ComfyUI 都新建 daemon 线程→可无限堆。改用 `wf.submit_background` 的**有界线程池**(4 并发/12 在途上限)，满了拒绝并提示"系统繁忙"。
- **#6【P2 回调先结清后发消息】**：发消息失败时 run 已完成、token 已清，平台重试得 404、结果永久丢。改成**先发、确认发出去了再结清**；发失败回 500、保持 pending 等重试。
- 验证：`test_wf_cmd` 加越权(不分 DM)/token 路径/回调发失败保持 pending 用例；cosmac **130 单测全过**、ruff 通过。纯后端 → `restart guduu-bot`。

## 2026-06-19 — 工作流安全（下）：越权/DoS/回调token/同步阻塞
- **#2【P1 越权】普通群成员能跑所有工作流**（触发付费生成/外部写、用服务端共享凭据）：聊天命令 `工作流 跑` 与 AI 工具 `run_workflow` 都加权限闸——群里要求发送者是房间管理员(power≥50)，普通成员只能「列表」；DM(1:1) 放行。
- **#3【P1 DoS】公开回调端点无认证读全 body**：验证 run_id/token 前就按 `Content-Length` 把请求体读进内存。改成先按上限(512KB)挡，超了直接 413、不读 body。
- **#4【P2 回调 token】**：① token 改优先从请求头 `X-Cosmac-Token` 取（不进 URL/日志），兼容老 `?token=`；② DB **只存 token 哈希**(sha256)、不存明文，比对用 `hmac.compare_digest` 防时序侧信道。
- **#5【P2 同步阻塞】ComfyUI 等到 120s 卡住 appservice 事务**：把 ComfyUI（慢）放**后台线程**跑、立即返回"已开始"，它自己把图发回群；webhook/dify/coze(≤30s) 仍同步。聊天命令和 AI 工具两条路径都改。
- 验证：`test_wf_cmd` 加越权闸 + token 哈希用例；cosmac **129 单测全过**、ruff、client build 通过。纯后端 → 部署 `restart guduu-bot`。

## 2026-06-19 — 工作流安全（上）：SSRF 防护 + AGENTS.md 状态同步
- **#1【P1 SSRF/凭据外泄】**：管理员可在连接器填任意 URL，服务端带 `COSMAC_WF_*` Bearer 去打它——能借此打内网/`localhost`/云元数据 `169.254.169.254`。新增 `wf.check_outbound_url`：只允许 http/https；把主机名解析成 IP，链路本地/保留/组播**永远拒绝**，私网/环回默认拒绝（自建内网可设 `COSMAC_WF_ALLOW_INTERNAL=1`）。webhook/dify/coze/comfyui 四个连接器外呼前都校验，并 `allow_redirects=False` 防重定向绕过。
- **#6【P2 规范】**：AGENTS.md 路线图同步 CLAUDE.md（模块2 ✅ / 模块3 🟡，原来停在模块2 进行中）。
- 验证：`test_wf` 加 SSRF 用例（环回/元数据/私网/非 http/公网放行/内网开关），22 例全过、ruff 通过。
- 余下工作流安全项（普通成员越权执行 / 回调端点 DoS / 回调 token 进 URL / 同步调用阻塞事务）下一条处理。

## 2026-06-19 — 知识库(RAG)健壮性修复（向量空间隔离 + 复用查询向量 + key 兜底）
- **#1【P1 安全】方舟 key 误发 OpenAI**：`get_embedder` 主路径已由并行会话改掉（不再自动挪用 `ARK_API_KEY`）。再补一道兜底：若有人把 `ark-…` key 配进 `COSMAC_EMBED_API_KEY` 却没给 `base_url`，强制指向方舟端点——绝不让 ark key 默认连 `api.openai.com`。
- **#2【P1 正确性】换 embedder 后旧向量污染检索**：`KnowledgeChunk` 只存了向量、没存"用哪个 embedder/维度"。从哈希兜底切到真嵌入后，新查询向量与旧哈希向量在不同空间里算余弦 = 乱序/失真。修：embedder 加 `tag`（如 `hash:256`/`oai:openai:text-embedding-3-small`），分块新增 `embed_tag` 列入库记下，`search` **只比同 tag** 的分块。旧数据需重新入库才会被检索。
- **#3【P2 性能/费用】一次回复 embed 两遍 query**：bot 的 `_kb_context` 分别搜群库/个人库，各 `embed_one(query)` 一次。修：查询向量**只算一次**，`search` 加 `qvec` 入参，群库/个人库共用，省一半嵌入请求。（pgvector 近邻索引仍是后续：v1 全量扫描是 §3 既定的，规模化再换，接口不变。）
- 验证：`test_kb` 加 3 例（embed_tag 入库 / 跨 embedder 不混 / qvec 复用）；cosmac **123 单测全过**、ruff 通过。
- 部署：改了 `cosmac/` → `restart guduu-bot`。⚠️ **新增 DB 列 `embed_tag`**：知识库表是新建的、create_all 不会给已存在的表加列——若服务器已建过 `cosmac_kb_chunk`，需 **drop 重建知识库表**（数据本就要按 #2 重新入库）；本地删 `run/cosmac.db` 即可。

## 2026-06-19 — 模块3 P4：工作流异步回调(长任务跑完反向通知回群)
- 长任务(ComfyUI 出视频、n8n 长流程)同步等不现实——加异步回调:提交后即返回,平台跑完反向 POST 回 bot,再把结果发回原群。
- **链路**:`WorkflowRun` 加 `token`(一次性)+ status `pending`;`wf_repo` 加 create_pending/get_run/complete_run;config 加 `public_url`。连接器(webhook)勾 `async` → bot `_dispatch_async` 建 pending+token、拼回调 URL `{public_url}/cosmac/wf/callback/<id>?token=` 塞进 webhook payload、提交即回"⏳ 已提交"。
- **入站端点**:`_Handler.do_POST` 处理 `/cosmac/wf/callback/<id>`(**不**用 hs_token,用每次运行的 token 校验)→ `handle_wf_callback` 验 token+pending → 把 `{output|error}` 发回原群 → complete_run 清 token(防重放,重复回调→404)。
- 后台:连接器加「异步(长任务)」开关(webhook);WorkflowDef 加 `async`。
- 验证:`test_wf_cmd` 加 4 例(异步提交建 pending+带回调URL / 回调发结果并结清+重放404 / 错token 403 / 未知run 404);cosmac **120 单测全过、ruff 通过**、client build 通过;preview 确认异步开关渲染、无报错。
- 部署:发 dist + restart guduu-bot + **配 `COSMAC_PUBLIC_URL`** + **nginx 放行 `/cosmac/` → bot:9000**(见 DEPLOY.md);否则异步连接器不启用、退回提示。
- 待续:定时触发(cron)、插件市场接真。

## 2026-06-19 — 模块3 P3：ComfyUI 适配器(图/视频:提交→轮询→回传媒体)
- 把外部平台连接器最后一档 ComfyUI 接上(影视场景):提交工作流图 → 轮询完成 → 把产出的图回传到触发的群。
- **matrix_client** 加 `upload_media`(POST /_matrix/media/v3/upload→mxc)+ `send_image`(发 m.image 消息)。
- **wf.py `run_comfyui`**:连接器存"API 格式工作流图模板",用 `{{input}}` 占位、安全注入用户输入 → `POST /prompt` → `_comfy_poll` 轮询 `/history/{id}`(上限 120s)→ `_comfy_download` 从 `/view` 取图 → upload_media + send_image 发回群。需在群里触发(要 client+room_id)。`run_connector` 加 client/room_id 参数,bot 命令路径与 run_workflow 工具路径都传入。
- **后台**:平台加 ComfyUI 选项 + 工作流图 textarea(`graph`);WorkflowDef 加 `graph` 字段。
- 说明:轮询是同步阻塞(MVP),超长生成需异步回调(后续);本机无真 ComfyUI,靠单测覆盖。
- 验证:`test_wf` 加 3 例(完整流程 mock HTTP+假client、缺房间、坏图 JSON);cosmac **116 单测全过、ruff 通过**、client build 通过(修了模板里 `{{input}}` 嵌套 mustache 解析报错→ `v-pre`);preview 直连生产:ComfyUI 连接器 graph 字段渲染 + round-trip + 清理,无报错。
- 部署:发 dist + restart guduu-bot。至此工作流连接器支持 **webhook/dify/coze/comfyui** 四档。
- 待续:异步回调入站端点(长任务)、定时触发、插件市场接真。

## 2026-06-19 — 模块3 P2：Dify / Coze 专用适配器
- 在通用 webhook 之上加两个平台适配器(REST+key):
  - **Dify**:`run_dify`——mode=workflow 走 `/v1/workflows/run`(inputs[input_key]=用户输入)、mode=chat 走 `/v1/chat-messages`(query);抽 `data.outputs` 或 `answer`。
  - **Coze**:`run_coze`——`/v1/workflow/run`(workflow_id=ref_id, parameters[input_key]=输入);认业务码 code==0,取 data。
  - `run_connector` 按 platform 分派 webhook/dify/coze;缺凭据/缺 workflow_id 友好报错。密钥仍只走服务端 env `COSMAC_WF_<CRED>`。
- 连接器定义加可选字段 `mode`/`ref_id`/`input_key`;后台「工作流」表单按平台条件显示(Dify→应用类型+输入变量名;Coze→workflow_id+输入变量名;webhook→请求方法)。
- 验证:`test_wf` 加 6 例(Dify workflow/chat/缺凭据、Coze 成功/缺id/业务错);cosmac **113 单测全过、ruff 通过**、client build 通过;preview 直连生产:Dify 连接器条件字段渲染 + round-trip + 清理,无残留无报错。
- 部署:发 dist + restart guduu-bot。用 Dify/Coze 时在服务端配 `COSMAC_WF_<CRED>`=该平台 key。
- 待续:ComfyUI(图/视频:提交→轮询→回传媒体)、异步回调入站端点、定时触发。

## 2026-06-19 — 模块3 P1 闭环：工作流后台 UI + 主 AI 工具 run_workflow
- 把 P1 闭环补齐:① 后台能配连接器;② 主 AI 能自然语言触发。
- **主 AI 工具 `run_workflow`**:`Toolbox` 加该工具(读控制室连接器定义→跑→尽力入库),`Toolbox(client, control_room_alias=...)` 注入控制室别名;bot 构造时传入。不带 slug 调用→返回可用列表。也加进 `AI_TOOL_CATALOG`(后台工具开关可控)。
- **后台「工作流」tab**:`client.ts` 加 `getWorkflows/setWorkflows` + `WorkflowDef` 类型;`AdminView` 加 CRUD(slug/名称/平台/URL/方法/凭据名/输入提示/启用)。凭据名旁明示"真密钥在服务端 env `COSMAC_WF_<CRED>`、不进网页"。
- 验证:`test_wf_cmd` 加 run_workflow 工具例;`test_runtime_config` 工具数 4→5;cosmac **107 单测全过、ruff 通过**、client build 通过;**preview 直连生产**:工作流连接器 round-trip + 清理,生产无残留、无控制台报错。
- 部署:**发 dist + restart guduu-bot**(前端加 tab、后端加工具)。端到端:后台配 n8n/Make webhook → 群里 `工作流 跑 <slug>` 或让主 AI 触发 → 结果回群。平台需鉴权时在服务端配 `COSMAC_WF_<CRED>`。
- 待续:Dify/Coze/ComfyUI 专用适配器、异步回调入站端点、定时触发。

## 2026-06-19 — 模块3 开工：外部工作流连接器(P1 通用 webhook 引擎 + 命令)
- **定调(负责人拍板)**:模块3 不自建工作流引擎,而是**对接 n8n/Make/Coze/ComfyUI/Dify** 等现成平台;P1 先做**通用 webhook 连接器**(覆盖 n8n/Make/任意自建端点),配置式后台编排,同步执行。
- **架构**:连接器**定义**走控制室 state event `cosmac.workflows`(浏览器够不到 DB,同 Skill/Agent);**密钥绝不进 Matrix**——定义里只放凭据名 `cred`,真值在服务端 env `COSMAC_WF_<CRED>`(同 LLM key 策略);**运行记录**进 cosmac DB。
- 本次实现(纯后端):
  - `cosmac/wf.py`:`run_connector/run_webhook`——同步 POST `{input,source}`、规范化结果(命中常见输出字段)、Bearer 鉴权(env)、全程兜异常不抛;平台分派(目前 webhook,Dify/Coze/ComfyUI 留后)。
  - `cosmac/db/models.py` 加 `WorkflowRun` + `cosmac/db/wf_repo.py`(record_run/recent_runs)。
  - `appservice_bot`:`工作流 列表/跑 <slug> <输入>` 命令(读控制室定义→跑→结果发频道→尽力入库),全程懒导入+兜异常。
- 验证:新增 `test_wf.py`(8 例:输出抽取/Bearer/非2xx/网络错/缺URL/非JSON/未知平台)+ `test_wf_cmd.py`(6 例:检测/列表/跑成功入库/失败记error/未知slug/空)。cosmac **106 单测全过、ruff 通过**。
- 部署:**仅 `restart guduu-bot`**(纯后端;新表 cosmac_workflow_run 由 create_all 自动建)。要真跑还需在「管理后台→工作流」配连接器(UI 下一轮)+ 服务端配 `COSMAC_WF_<CRED>`(如平台需鉴权)。
- 待续:① 后台工作流编排 UI;② 注册主 AI 工具 `run_workflow`(自然语言触发);③ Dify/Coze/ComfyUI 适配器 + 异步回调。

## 2026-06-19 — 模块2：模型按群覆盖（Agent.model 接活，智能体功能补齐）
- 补上 Agent 最后没接的点:智能体定义里的 `model` 字段(UI 早能填、bot 一直忽略)现在生效——某群绑定的智能体若指定模型,主 AI 在该群就用那个模型回话。
- **顺手做了读优化**:把"本群人设/绑定技能/模型"收敛成 `_group_context(room_id)` **一次读**(原 `_group_persona` 拆成它),`_handle_event` 读一次、传给 addendum 复用,少几次 Synapse state 读。
- **按群模型**:`_agent_for_model(model)` 同 provider 换 model 构建 Agent 并缓存(`_model_agents`);全局配置(provider/人设)变更时清缓存。没覆盖/与当前一致→用默认 Agent;构建失败→回退默认,绝不阻断回复。人设仍走 addendum、不在此设。
- 验证:`test_group_agent` 加模型覆盖例(取到 model、拿到不同且被缓存的 Agent、无覆盖用默认);cosmac **92 单测全过、ruff 通过**。
- 部署:**仅 `restart guduu-bot`**(纯后端、无前端)。

## 2026-06-19 — 模块2：主 AI 短期记忆（带最近对话上文，治"失忆")
- **修缺口**:此前 `agent.run` 每条消息只喂 `[system, 当前用户话]`,主 AI 记不住同群/私聊里刚说过什么(连 DM 都没上下文)。
- **做法(贴 §3:聊天记录在 Synapse、不重存)**:bot 回话前用 `client.get_messages` **实时读本房间最近 N 条**,映射成对话历史(bot 自己发的→assistant,其它人→user),喂给模型;**不进 cosmac DB**。
- `agent.run` 加 `history` 参数:消息序列变 `system → 最近历史 → 当前 user`。bot 加 `_recent_history`(窗口 12 条、单条截断 600 字、排除当前触发消息、全程兜异常)。
- 长期记忆(超窗口的滚动摘要)留作后续 DB 派生数据。
- 验证:`test_agent_tools` 加 history 顺序例 + `test_group_agent` 加 _recent_history 角色映射/排除当前例;cosmac **91 单测全过、ruff 通过**。
- 部署:**仅 `restart guduu-bot`**(纯后端、无前端改动,不必发 dist)。

## 2026-06-19 — 模块2：Rule 规则引擎（平台级硬约束，全局注入、优先级最高）
- 模块2「记忆/知识库/Rule/Skill」补上最后一块 **Rule**:平台级硬约束(如"对外报价/发布须经确认""不得编造数据"),无论群里用哪个智能体都注入,且**放 addendum 最前、优先级最高**。
- 沿用已验证套路(同技能/智能体):全局规则存控制室 state event `cosmac.rules`,浏览器(管理后台)写、bot 读。
- 后端:`config.py` 加 `RULES_EVENT_TYPE`;`appservice_bot._global_rules_text` 读规则渲染成「必须严格遵守」块,拼进 `_skill_addendum`(规则→人设→技能→知识库)。
- 前端:`client.ts` 加 `getGlobalRules/setGlobalRules` + `GlobalRule` 类型;`AdminView` 加「规则」tab(行内编辑列表:勾选启用/文本/删除/加一条/保存)。
- 验证:`test_group_agent` 加规则注入例(启用过滤 + 排在最前);cosmac **89 单测全过、ruff 通过**、client build 通过;**preview 直连生产**:规则新建→重新加载读回(round-trip)→清理,生产无残留、无控制台报错。
- 部署:发 dist + `restart guduu-bot`(bot 改了注入)。

## 2026-06-19 — 模块2 上线：cosmac DB 接生产 Postgres + 修嵌入挪用 ARK key 的坑
- **DB 上线**:服务器给 cosmac 单开 Postgres 库(cosmac_user/cosmac),`COSMAC_DATABASE_URL` 写进 guduu-bot.service,重启后 bot 连上并建好四表(cosmac_skill/agent/kb_doc/kb_chunk)。至此命令建技能、知识库、RAG 在生产真正可用(此前只有 state event 的全局技能/智能体能用)。具体连接信息进本机 DEPLOY.md。
- **修坑(P1)**:`get_embedder()` 原把 `ARK_API_KEY` 也当嵌入 key→去调 `text-embedding-3-small`,但方舟没这模型、会报错拖垮知识库入库/检索。改为**只认显式 `COSMAC_EMBED_API_KEY`/`OPENAI_API_KEY`**,不挪用 ARK;没配就用哈希词袋(词法检索)。要在方舟做嵌入需显式配 COSMAC_EMBED_API_KEY+BASE_URL+MODEL。
- 验证:cosmac 88 单测全过、ruff 通过。服务器侧:`init_engine` 列出四表通过。
- 部署:`restart guduu-bot`(已含连接串);本次嵌入修复需再 `git pull` + restart。无前端改动。

## 2026-06-19 — 模块2：知识库接活（bot RAG 注入 + 入库聊天命令）
- 把上一步的知识库引擎接进主 AI，端到端闭环：群里加文档 → 主 AI 据此回答。
- **入库命令** `cosmac/db/kb_cmd.py`（同 skill_cmd 套路）：`知识 列表/添加/删除/搜`；`添加 <标题> ｜ <正文>`。作用域:群=本群库 / 私聊=个人库;写操作群里需管理员;容量护栏(单篇≤20000字、每作用域≤200篇);删除只能删本作用域、按编号。
- **bot RAG**：`_skill_addendum` 现按用户这句话检索本群+个人知识库 top-K 片段(余弦、min_score 过滤)，作为「参考资料」块注入(人设→技能→知识库)。bot 加 `_is_kb_command`/`_run_kb_command`(懒导入+兜异常+管理员闸,同技能命令)。
- 验证：新增 `test_kb_cmd.py`(7 例)+ `test_group_agent` 加 RAG 注入例;cosmac **88 单测全过、ruff 通过**。修了一个测试隔离坑:KB 测试会因机器上真有 OPENAI/ARK key 而走真实网络——setUp 里清掉 embedding key、强制哈希兜底。
- 部署：发 dist 不需要(无前端改动);**要 `restart guduu-bot`**(bot 改了命令分发+注入)。**前提**:服务器装 SQLAlchemy + 配 cosmac DB,知识库命令/RAG 才真正生效(否则优雅降级);要好的语义检索还需配 embedding key(OPENAI_API_KEY/方舟),否则用哈希词袋(仅词法相似)。
- 待续:① 后台/上传式入库(大文档);② pgvector 提速;③ 模型按群覆盖;④ Rule。

## 2026-06-19 — 模块2：知识库引擎(嵌入抽象 + 入库/检索, 本地可验、零基建)
- 开工知识库(模块2 最重一块)。**关键取舍**:检索 v1 用 **Python 余弦相似度**(在该作用域分块上排序),SQLite/PG 都能跑、本地可验,**绕开 pgvector 依赖**;pgvector 留作规模化优化。嵌入走多模型抽象:有 OpenAI 兼容 key 用真嵌入(默认 text-embedding-3-small),无 key 自动降级**哈希词袋向量**(确定性、给词法相似度)。
- 新增:`cosmac/ai/embeddings.py`(Embedder 抽象 + HashingEmbedder 兜底 + OpenAICompatEmbedder + get_embedder 按 env 选 + cosine);`cosmac/db/models.py` 加 **KnowledgeDoc / KnowledgeChunk**(embedding 存 JSON 浮点数组、跨后端通用;删文档级联删分块);`cosmac/db/kb.py`(chunk_text 带重叠切块 + ingest_document 切块·嵌入·落库 + search 余弦 top-K + list/delete)。作用域沿用 room/user/global。
- 验证:新增 `test_kb.py` 8 例(切块/嵌入自相似/入库/检索排序/作用域隔离/删除级联);cosmac **80 单测全过、ruff 通过**。本地 e2e 冒烟(无 key→哈希):"商单怎么报价"→《商单报价》、"什么时候发布最好"→《发布排期》,路由正确。
- **本次无需部署**:纯后端引擎、bot 还没用它(下一步接 RAG 注入 + 入库入口)。
- 待续:① bot RAG——回话前检索本群知识库、把 top-K 片段注入上下文;② 入库入口(聊天命令 `知识 添加` / 后台上传);③ 规模化上 pgvector;④ 真嵌入 key(服务器配 OPENAI_API_KEY/方舟)。

## 2026-06-19 — 模块2：群绑定智能体 + bot 应用（人设+技能；智能体真正"活"起来）
- 让 Agent 真正生效:某群在「频道管理 → 角色」选一个**本群智能体**,主 AI 在该群就以它的人设回应、并自动启用它绑定的技能。
- **前端**:`useChannelAdmin` 的 `ChannelPersona` 加 `agentSlug`(随既有 persona 自动存进频道 state event `cosmac.channel_config`,零新机制);`ChannelAdminModal` 角色 tab 加「本群智能体」下拉(选项来自 `getGlobalAgents`)。
- **后端**:`config.py` 加 `CHANNEL_CONFIG_EVENT_TYPE`;`appservice_bot._skill_addendum` 扩展——读本群频道配置:① 绑了智能体→注入它的人设 + 绑定技能;② 否则用自定义人设 `persona.prompt`。技能按 slug **去重**(全局已注入的不重复)。模型覆盖(agent.model)本期先不做,留待下一步。全程兜异常,任何读取失败都只是少注入、不阻断回复。
- 验证:新增 `test_group_agent.py` 5 例(绑定注入人设+技能 / 停用回退 / 自定义人设 / 无配置空 / 无绑定时全局技能照常);cosmac **72 单测全过**、ruff 通过、client build 通过;preview:频道管理→角色 tab 出现「本群智能体」下拉、无控制台报错。
- 部署:发 dist + `restart guduu-bot`(bot 改了注入逻辑)。
- 待续:① 模型按群覆盖(agent.model→per-room llm);② 知识库(pgvector·RAG)。

## 2026-06-19 — 模块2：管理后台「智能体」UI + §3 架构定调
- 继「技能库」之后,管理后台加 **智能体** tab:定义可复用 AI 角色(人设 + 模型覆盖 + 绑定技能集),全局 Agent 同样存控制室 state event `cosmac.agents`。CRUD/启停齐活,绑定技能用技能库里的勾选列表。
- **§3 架构定调(负责人拍板,解决上一条 DEVLOG 里 #3 待定项)**:全局 Skill/Agent 定义**走 Matrix state event**(浏览器够不到 DB),与「全局 AI 配置」同套路;DB 留给知识库(pgvector)/记忆/聊天命令建的群级·个人技能。已更新 CLAUDE.md §3 数据分层表。
- 后端:`config.py` 加 `AGENTS_EVENT_TYPE`(bot 暂未消费——下一步做"群绑定 Agent + bot 应用其人设/模型/技能")。前端:`client.ts` 加 `getGlobalAgents/setGlobalAgents` + `GlobalAgent` 类型;`AdminView.vue` 加智能体 tab。
- 验证:client build 通过;**preview 直连生产**:智能体新建写控制室→重新加载读回(round-trip)→删除清理,生产无残留、无控制台报错。
- 部署:**仅发 dist**(后端只加了个常量、bot 还没用 Agent → 无需 restart)。
- 待续:① 群绑定 Agent + bot 应用;② 知识库(pgvector·RAG)。

## 2026-06-19 — 全局技能健壮性修复（脏数据不致哑 + 首条也限长 + 写校验）
- **#1【P1】坏技能能让 bot 不回话**：`skills_text.render_skills` 假设字段是字符串、直接 `.strip()`，`name:123` → AttributeError；且 bot 的 `_skill_addendum` 兜了两个数据源、却**没兜最后的 render 调用**，于是整条消息收不到回复（与 docstring 承诺相反）。修：render 里字段一律 `str()` 安全转换 + 非 dict 跳过；bot 把 `render_skills` 也包进 try/except。
- **#2【P2】6000 字上限被第一条绕过**：`used>0` 判断让首条技能永不截断，单条 12000 字直接全量注入。修：改成"预算用尽即停 + 单条超长就**截断这一条**（含第一条）"，总长度恒 ≤ 上限。`db/service.render_skill_prompt` 改为**委托** `render_skills`（两份渲染合一，不再各踩各的坑；`MAX_TOTAL_PROMPT_CHARS` 单一来源）。前端 `setGlobalSkills` 加**写校验+规范化**：数量 ≤50、正文 ≤2000、字段强制转字符串——脏数据从源头就写不进去。
- 验证：新增 `test_skills_text.py`（脏类型不崩 / 首条超长被截 / 多条总预算）；cosmac **64 单测全过**、ruff 通过、client build 通过。
- 部署：改了 `cosmac/`+前端 → 发 dist + `restart guduu-bot`。
- **#3【P1 架构】待负责人定**：全局技能/Agent 现存控制室 **state event**（`cosmac.skills`/`cosmac.agents`），与 §3「Skill/Agent 定义存 CosMac DB」冲突。并行会话选 state event 是因"浏览器够不到 DB"。两条路：(a) 保留 state event 并把 §3 加一条例外（像 AI 配置那样）；(b) 移到 DB + bot 开一个鉴权 REST 端点给浏览器 CRUD。见下方讨论，未动。

## 2026-06-19 — 模块2：管理后台「技能库」UI（全局技能，走控制室 state event）
- 让技能"可视":管理后台加 **技能库** tab,增删改/启停全局技能,**主 AI 在所有群回话时注入**。
- **架构定调（负责人选 Matrix state event 方案）**:浏览器够不到 cosmac 的 DB(bot 进程私有、没开 API),所以全局技能跟「AI 配置」同套路——存控制室 state event `cosmac.skills`,浏览器写、bot 读。零新基建、立刻可视。群级/个人技能仍走聊天命令存 DB,bot 注入时两边合并。
- 后端:`config.py` 加 `SKILLS_EVENT_TYPE`;新增 `cosmac/skills_text.py`(纯渲染、**不依赖 DB/SQLAlchemy**,带总长上限);`appservice_bot._skill_addendum` 重写为 **全局(控制室 state event) + 群/个人(DB) 合并渲染**,两来源各自兜异常、互不拖累——全局技能纯 Matrix 读,服务器没装 SQLAlchemy 也能用。
- 前端:`client.ts` 加 `getGlobalSkills/setGlobalSkills`(读写控制室 state event,同 getAiConfig 套路)+ `GlobalSkill` 类型;`AdminView.vue` 加技能库 tab(表格 + 新建/编辑表单 + 启停/删除)。
- 验证:cosmac **63 单测全过、ruff 通过**;client build 通过;**preview 直连生产**:技能库渲染→新建写入控制室→重新加载读回(round-trip)→删除清理,生产无残留、无控制台报错。
- 部署:**前端发 dist + 后端 restart guduu-bot**(bot 改了注入逻辑;全局技能只读 state event、不需要 SQLAlchemy)。

## 2026-06-19 — 品牌清理 GuDuu→CosMac（stage1：环境变量 + 注释/文档，零停机）
- 背景：负责人指出项目叫 CosMac，但服务器/运维层到处是 GuDuu（env 变量名、bot 账号、service 名）。当初 guduu→cosmac 改名没做干净。决定**彻底**改，但分两阶段保证不挂线上 bot。
- **stage1（本次，代码层零停机）**：
  - **环境变量 `GUDUU_*`→`COSMAC_*`**：`config.py` 加 `_env()`（先查 `COSMAC_` 再回退 `GUDUU_`），`from_env` 全改走它；`db/engine.py` 的 `database_url()` 同样支持两前缀。**向后兼容**——生产 systemd 里现有的 `GUDUU_*` 仍生效，可从容迁移。
  - **注释/文档/README**：`GuDuu`/`guduu` 品牌字样、stale 模块路径（`guduu.bots`/`guduu.ai`/`guduu.tests`/`本包（guduu）`）、txn id 前缀、CLAUDE.md/AGENTS.md 的 env 示例、`client/package.json` 的 name/description（`gudu-workbench`/`GuDuu·…`→`cosmac-workbench`/`CosMac·…`，含 package-lock 同步）→ 全改 CosMac/`COSMAC_*`。（全仓库复扫确认：剩余 `guduu` 仅 = 故意保留的 stage2 标识符 + DEVLOG 历史流水，不再有漏网的品牌字样。）
  - **刻意保留**（属 stage2，和**线上 bot 账号强耦合**，改了会找不到账号）：bot id `@guduu`、本地域名 `guduu.local`、注册文件名 `guduu-bot.yaml`、前端 `BOT_LOCALPART='guduu'`、localStorage key。已在 config.py 加注释标明。
- **stage2（待负责人择期，服务器侧迁移）**：把线上 bot `@guduu`→`@cosmac`（重注册 appservice + 重邀进所有房间）+ 改 systemd 用 `COSMAC_*` + 同步翻 `BOT_LOCALPART`。给 runbook。
- 验证：cosmac 63 单测全过、ruff 通过；`from_env` 本地仍从 yaml 读到 token（不回归）。纯后端+文档，**无需发 dist**；prod 行为不变（GUDUU_* 仍认），重启可选。

## 2026-06-19 — 模块2 技能：加群级写权限闸 + 容量上限（防 prompt 注入/上下文炸）
- **#1【P1】群内任何成员都能改群级技能**：群级技能会作为 system prompt 注入**所有群成员**的 AI 请求 → 等于持久化 prompt injection。`handle_skill_command` 加 `can_write`：群级写操作（添加/删除/停用/启用）要求发送者是房间管理员（bot 端 `_is_room_admin` 读 power_levels，power≥50），普通成员只能「技能 列表」；个人技能（私聊/USER 作用域）不受限。
- **#2【P2】技能数量/正文无限制**：`skill_cmd` 加上限——单作用域 ≤50 个、正文 ≤2000 字、标识 ≤64、名称 ≤80；`service.render_skill_prompt` 再兜一层**总注入长度 ≤6000 字**，超了停止注入剩余并提示，避免技能一多撑爆模型上下文/费用。
- **#3【P1 迁移风险】遗留 power=100 管理员**：已是“告警不移除”（Matrix 约束，bot=100 动不了≥100 的人）。**操作建议**：部署前审计控制室 `m.room.power_levels`，确认 ≥100 的只有 owner(@admin)+bot；线上当前单管理员、无此类遗留。
- 验证：`test_skill_cmd`/`test_skill_service` 加权限闸 + 容量 + 总长度截断用例；cosmac **63 单测全过**、ruff 通过。纯后端（cosmac/），**部署只需 `restart guduu-bot`，无需发 dist**。

## 2026-06-19 — 路线图：模块1（主 AI 控制层）收尾标 ✅，专注模块2
- 负责人决定：模块1 地基已齐（消息感知/自动进群/回复、多模型可配、AI 工具调用、控制室热下发 + 管理员↔成员联动），标 **✅ 完成**；模块2（群级 记忆/知识库/Rule/Skill）保持 🟡。
- 解除上一条 DEVLOG 里提的「模块1+2 都进行中」与「一次只推进一个模块」铁律的冲突——现在只有模块2 在推。CLAUDE.md / AGENTS.md 路线图同步更新。后续主 AI 的增量工具按需补，不再算"开工中"。纯文档改动，无需部署。

## 2026-06-19 — 控制室对账复查再修 3 项（失败不再谎报成功 / 遗留 100 告警 / AGENTS.md 同步）
- **#1【P1】历史遗留 power=100 管理员永不被撤权**：bot(=100) 在 Matrix 里无法降权/踢出 ≥ 自己等级的人，旧 bug 曾把管理员设成 100 才会出现。无法自动修——`_reconcile_control_members` 现对「≥100 且已非管理员」的成员单独 **warning**（提示需重建控制室），不再静默当 owner 跳过。（注：going-forward 已不会再产生——新管理员只给 50；真实不变式下 owner 是服务器管理员、在期望集里、不会误报。）
- **#2【P1】降权/踢出失败仍报成功**：`_reconcile_control_members` 之前忽略 `set_power_levels`/`kick` 的布尔返回、无条件 log「已移除」。改成**检查结果**：失败报 `error`（被撤销者仍能写配置是安全问题），只对真正踢成功的报成功。前端 `setUserAdmin` 改成返回「控制室是否同步成功」，`AdminView` 撤管理员时同步失败则 **warn 提示重试**，不再静默报全成。
- **#3【P1 项目规范】AGENTS.md 未跟 CLAUDE.md**：模块2 开工后只更新了 CLAUDE.md（§3 数据存储分层 + 路线图 module2🟡）。把这两块同步进 `AGENTS.md`，两份「宪法」一致。
- 验证：`test_control_members.py` +2 例（踢出失败报 error / 遗留 100 告警）；cosmac 50 单测全过、ruff 通过、client build 通过。
- 部署：改了 `cosmac/` → `restart guduu-bot`；改了前端 → 发 dist。
- ⚠️ **留给负责人决策**：CLAUDE.md/AGENTS.md 现在模块1 与模块2 都标 🟡进行中，与「一次只推进一个模块」铁律冲突。要么把模块1 收尾标 ✅、要么暂停模块2——这是产品节奏决定，按 §6.6 该由你定。

## 2026-06-19 — 模块2：技能聊天命令（建/列/删/启停），闭环打通
- 给 Skill 加「创建/管理入口」——按负责人选择：**先做聊天命令（后端，不碰客户端、不与并行会话撞车）**。
- 新增 `cosmac/db/skill_cmd.py`（纯逻辑、吃 session、返回回复文本，好测）：`技能 列表/添加/删除/停用/启用`；`添加 <slug> ｜ <名称> ｜ <正文>`（分隔符兼容半/全角，更新时不空串覆盖未传字段）。`looks_like_skill_command` 做不连 DB 的前缀闸（中文直接前缀、英文要词边界）。
- **作用域**：私聊 bot（≤2 人）建的是**个人技能**(user)，群里建的是**本群技能**(room)——直觉对齐"每账号 / 群级"。
- `appservice_bot` 接入：`_try_handle_command` 命中技能前缀就执行；`_is_skill_command` 纯字符串判断、`_run_skill_command` 懒导入 cosmac.db + 全程兜异常（服务器没装 SQLAlchemy → 回"功能暂不可用"，不崩不哑）。
- 验证：新增 `test_skill_cmd.py` 8 例（检测/帮助/增改不覆盖/启停删/DM作用域/缺slug/未知子命令）；cosmac **58 单测全过、ruff 通过**。本地端到端冒烟：`技能 添加` → `effective_skill_prompt` 真注入、别的群隔离为空。
- 部署（可选，要让线上生效才做）：`git pull` → `pip install -r cosmac/requirements.txt`（装 SQLAlchemy）→ `restart guduu-bot`。默认用 SQLite `run/cosmac.db`；要用 Postgres 则在 systemd 配 `GUDUU_DATABASE_URL`。不部署则零回归（懒导入失败即降级）。

## 2026-06-19 — 模块2：Skill 接进主 AI（按 房间+发起人 注入技能提示，零回归）
- 把上一步建好的数据层用起来：主 AI 每处理一条消息，按 (本群, 发起人) 算出**当前生效的启用技能**，作为 system addendum 临时注入这一轮——不污染常驻人设。
- 新增 `cosmac/db/service.py`（纯函数胶水层）：`effective_skills(room_id,user_id)` 按 **global→room→user** 顺序汇总启用技能；`render_skill_prompt` 渲染成提示文本；`effective_skill_prompt` 便捷组合。
- `Agent.run` 加 `extra_system` 参数：与常驻人设**合并成单条 system 消息**（兼容 Claude 等只认一个 system 的 provider）。
- `appservice_bot._skill_addendum`：取技能拼 addendum。**全程 try/except + cosmac.db 懒导入**——生产服务器还没装 SQLAlchemy 时 import 失败也只是退化成「无技能」，bot 照常回话，零回归。没技能时 addendum 为空、行为与现状完全一致。
- 验证：新增 `test_skill_service.py`(4 例：作用域顺序/过滤/渲染/空) + `test_agent_tools` 加 1 例(extra_system 合并进单条 system)；cosmac 48 单测全过、ruff 通过。
- 部署：**暂不需要**——纯后端、且当前无任何技能数据→零可见变化。等下一步加了「建技能」的入口（后台 UI 或命令）并在服务器 `pip install -r cosmac/requirements.txt` 后，再 `restart guduu-bot` 才会真正生效。
- 待续：还**没有创建技能的入口**（UI/命令/seed），端到端闭环留作下一步。

## 2026-06-19 — 模块2 开工：cosmac 数据层骨架（Skill/Agent，PG/本地 SQLite 双跑）
- **背景**：讨论"每账号配置/Skill/Agent/知识库/聊天记录要不要数据库"。结论先写进 CLAUDE.md 新增「数据存储分层」：**Synapse 已存的（聊天记录/成员/房间状态）绝不重存**；AI 层自己的结构化/派生数据（Skill/Agent/知识库/记忆/工作流…）才进 cosmac 自己的 DB。全局 AI 配置仍走控制室 state event，每账号轻量配置优先用 Matrix account data。
- **基建决策**：复用生产现成 PostgreSQL，给 cosmac 单开 database/schema，知识库按需装 pgvector。走 §2 第 3 条路径，不碰 Synapse 核心。
- **本次实现**（`cosmac/db/`，纯新增、未接进 bot 运行路径，零行为变化）：SQLAlchemy **同步**（bot 是同步的）。`engine.py` 连接由 `GUDUU_DATABASE_URL` 决定，生产指向 Postgres、本地默认回退 SQLite `run/cosmac.db`（含内存库 StaticPool 处理）；`models.py` 两张表 **Skill / Agent**，带 **scope/scope_id/slug** 作用域三元组（user/room/global，同时覆盖"每账号"和"群级"），Agent 用 JSON 存 skill_slugs 暂不建多对多；`repo.py` upsert(部分更新+字段白名单)/get/list(作用域+启用过滤)/delete。
- **决策**：第一批只做 Skill/Agent（纯关系型、立刻有用）；知识库(pgvector·RAG)、群级记忆、Rule 是后续切片；建表暂用 create_all，以后上 alembic 迁移。
- 验证：新增 `test_db.py` 6 例（内存 SQLite，建/改/查/删/作用域隔离/字段护栏）全过；cosmac 43 单测全过、ruff 通过。`SQLAlchemy>=2.0` 进 requirements（生产另需 `psycopg`）。
- 部署：**本次无需部署**——纯后端新增、bot 还没用它。等接进 bot 时再 `pip install -r cosmac/requirements.txt` + `restart guduu-bot`。

## 2026-06-19 — 控制室成员对齐改由主 AI(power 100)执行（撤销管理员真正失权）
- **问题(P1)**：普通管理员都是 power 50，A(50) 撤销 B(50) 时 Matrix 不允许同级降权/踢出，前端 `removeFromControlRoom` 两个操作都静默失败，UI 却报成功——B 撤销后仍能写 AI 配置。只有唯一的 100 所有者撤权才真生效。
- **修法（按 reviewer 方向：让 power 100 的 bot 执行成员同步，浏览器只提交期望）**：
  - 新增 state event `cosmac.ctrl.admins`（前端写「期望服务器管理员集」，管理员 50 够写）。`setUserAdmin` 改成 `syncControlRoomAdmins()`：ensureControlRoom 尽力即时邀请/提权 + 写期望集。删掉做不可靠的 `removeFromControlRoom`。
  - **bot 端 `_reconcile_control_members`**：收到控制室的 `cosmac.ctrl.admins` 事件即对齐——把 power<100、不在期望集里的成员降权(从 power_levels.users 删)+ 踢出。bot=100 能踢同级 50，绕过前端做不到的约束。
  - **安全护栏**：① 只在 room_id == 别名解析出的控制室才动手（防有人塞事件借 bot 踢人）；② 绝不动 owner(100) 和 bot 自己；③ 任何异常只记日志不抛。`matrix_client` 加 `set_power_levels`/`kick`。
  - UI 文案改诚实：撤管理员提示「控制室写权限将由主 AI 同步移除」，不再静默报全成。
- 验证：新增 `test_control_members.py`（撤销者被移除 / owner·bot 永不被动 / 非控制室不动手 / 无需移除则不写）；cosmac 37 单测全过、ruff 通过、client build 通过。
- **补**：老控制室（早先建的）里 bot 可能还是默认 power 0，那样它没法执行降权/踢出。`reconcileControlRoomAdmins` 改成顺手把 bot 提到 100（由所有者执行；下次 @admin 存 AI 配置或改管理员时即补上），并去掉「无其他管理员就 return」的早退，确保单管理员场景也能补 bot 权限。
- 部署：改了 `cosmac/` → 要 `restart guduu-bot`；改了前端 → 发 dist。

## 2026-06-19 — 主 AI：右侧中枢 AI 面板加「放大」按钮 → Cowork 式全屏弹窗
- **需求**：右侧主 AI 顶栏加放大按钮，点开后是一个和 Claude Cowork 一致的弹窗。
- **关键定位**：真正渲染的右侧主 AI 是**写死在 `LiveView.vue` 里的内联 `aside.ai-panel`**（`aiOpen` 控制），不是 `components/layout/AiChatPanel.vue`（那套连同 App.vue 是未挂载的演示稿，main.ts 只挂 LiveView）。一开始误改了 AiChatPanel，已回滚，改在 LiveView 内联面板上做。
- **做法**：新增 `aiMax` 态 + 顶栏「放大/还原」图标按钮；放大态下 `.ai-panel.maximized` 脱离 dock、近全屏居中（inset 2.5vh/2.5vw）+ 半透明遮罩（点空白还原）。面板主体重构成 `ai-main`（默认单列 / 放大态三栏）：左栏**完整还原 Cowork 左导航**（对话·协作·代码 分段 → ＋新任务 → 项目/产物/定时任务/派发·Beta → 最近列表 → 底部用户），中栏复用原对话+输入，右栏 Progress 清单 + 项目文件。全部 scoped 在 LiveView，未碰未挂载的 AiChatPanel/ai-panel.css。
- **决策**：线上面板原本只有关闭按钮，这次只加「放大↔还原」一个新态，最简且贴合需求；演示稿里的展开/浮窗多态不照搬。左栏导航项为演示态（toast 占位），「新任务」清空当前对话。
- 验证：preview 直连，放大→三栏弹窗布局正确、还原回 360px dock、遮罩开合正常、无控制台报错。

## 2026-06-19 — 再复查修 3 项（token 进 URL / 新管理员卡住 / 文档过时）
- **#1【P1 安全】as_token 拼进每个 URL 查询参数**：`matrix_client._url` 把高权限 as_token 放进 `?access_token=…`，会进 nginx/代理/错误日志。改用 `requests.Session` + `Authorization: Bearer <token>` 头，URL 里只留 `user_id`（身份标识、非密钥）；11 处请求调用全改走 session。新增 `test_matrix_client.py` 守这条红线。
- **#2【P2】已有控制室的权限修复无法由受影响的新管理员触发**：reconcile 只有「已在房、有 power 的人」能跑，新管理员自己进不去也修不了。改法：在 `setUserAdmin(uid, true)`（把人提成管理员）成功后，趁**当前操作者**（已在控制室、power 100）在线，顺手 `ensureControlRoom()` 幂等对账，把新管理员邀进去并提权。尽力而为、失败不回滚提权。（残留极端态：控制室里有权限的人全不可用时仍需 Synapse 侧手工介入，可接受。）
- **#3【P3】文档与实际安全策略冲突**：`ai/__init__.py`、`ark.py`、`claude.py`、`openai_compat.py` 的注释仍称「管理后台可下发 key」，但 bot 已明确忽略控制室 key。注释统一改成「key 只走服务端环境变量/Secret Manager，后台只选 provider/模型」。
- 验证：MatrixClient 冒烟（token 不在 URL、Bearer 头就位）、cosmac 单测全过（含新增 2 条）、ruff 通过、client build 通过。
- 部署：#1 改了 `cosmac/` → 要 `restart guduu-bot`；#2 改了前端 → 发 dist。（dist 顺带并行会话的 `useAiPanel.ts` 改动。）

## 2026-06-19 — 复查修 1 个真 bug：控制室对账会自我锁权
- 对「多模型 + 后台 provider + 控制室」一轮复查，发现并修掉一个潜伏 bug。
- **bug**：`reconcileControlRoomAdmins`（#2 给已有控制室补管理员权限那段）在控制室**没同步进本地**时，`pl` 退化成 `{}`，而传入的管理员列表不含创建者，于是 `sendStateEvent('m.room.power_levels', { users })` 会**抹掉 events_default/state_default 等全部字段、并丢掉创建者自己的 100 权限 → 自我锁权**。
- **修法**：只有**真正读到** power_levels（房间已同步、事件存在）才提权；读不到就跳过，绝不用空对象覆盖。邀请那步不受影响。
- 触发面：当前仅 1 个管理员 → `others` 为空、reconcile 直接 return，故线上未触发；加第二个管理员前修掉。
- 复查同时确认多模型四家代码（build_provider/openai_compat/claude/ark）无问题。client build 通过、preview 无报错。
- （本次 dist 还顺带带上并行会话给 `onUpdate` 加的 80ms 防抖：初始同步的历史消息整批一次渲染、不再逐条蹦。）

## 2026-06-19 — 多模型四家 + 后台可选 provider/模型（密钥仍走服务端，安全加固）
- 多模型扩成四家：新增通用 `cosmac/ai/openai_compat.py`（OpenAI 兼容，参数化 api_key/base_url/model，含工具调用）；`ark.py` 改薄成它的子类；`claude.py` 加 api_key 参数。`ai/__init__.py` 加 **build_provider**（claude / openai / deepseek·ark / **gemini**，key 缺则降级 echo，gemini 走 Google 的 OpenAI 兼容端点）。
- 管理后台「AI 配置」加 **模型后端下拉**（默认/DeepSeek/Claude/ChatGPT/Gemini）+ 模型 id；bot 从控制室读 `provider/model` 热切（按签名重建）。
- **关键安全决策（推翻"密钥填后台"的初版）**：API Key **绝不进 Matrix**。state event 无法加密、会明文进 DB/历史/同步给全员，所以密钥只走**服务端环境变量/Secret Manager**；后台只选 provider+模型，UI 明示"切到服务器没配 key 的后端 AI 将无法回话"。`appservice_bot._read_overrides` 不读 api_key、`build_provider(api_key="")` 让各 SDK 自己读环境变量。
- 验证：新增 `test_build_provider.py`（4 家分派 + base_url + 缺 key 降级 + 未知报错）；cosmac 31 单测全过、ruff 通过、client build 通过；preview 直连生产验证后台选 DeepSeek+模型写读 round-trip、provider 热切（测试数据已清回默认）。
- 启用某后端：仍在服务器 systemd 配该家的 key 环境变量（ARK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY），后台只管"用哪家+哪个模型"。

## 2026-06-19 — 多模型新增 DeepSeek（走火山引擎方舟，OpenAI 兼容）
- 接入 DeepSeek：方舟 Chat Completions 与 OpenAI 完全兼容，所以新增 `cosmac/ai/ark.py`（`ArkProvider`），复用 `openai` SDK，只把 base_url 指向方舟、key 用 `ARK_API_KEY`。实现 `complete` + `complete_with_tools`（OpenAI 工具格式：tools/tool_calls/tool 角色），所以 DeepSeek 也能用主 AI 的工具调用。
- `get_provider` 注册 `deepseek` / `ark` 两个名（deepseek 是 ark 别名）；无 `ARK_API_KEY` 自动降级 echo。模型 id 用 `GUDUU_LLM_MODEL` 填方舟的 Model ID 或 Endpoint ID(ep-...)，默认 `deepseek-v3.2`；可选 `ARK_BASE_URL` 换区域。
- system 提示去重：`_build_messages` 仅在历史无 system 消息时才用构造人设兜底，避免和 Agent 传入的 system 重复。
- 验证：新增 `test_ark_provider.py`（选 provider 回退 + 消息/工具翻译，构造 client 不联网）；cosmac 21 单测全过、ruff 通过。`openai>=1.50` 已在 requirements。CLAUDE.md/AGENTS.md §9 补 DeepSeek 启用说明。
- 启用：服务器 `Environment=GUDUU_LLM_PROVIDER=deepseek` + `Environment=ARK_API_KEY=...` + `Environment=GUDUU_LLM_MODEL=<方舟模型id>`，daemon-reload+restart。

## 2026-06-19 — 代码审查修复（6 项：安全/正确性/工具友好性）
- 对一轮代码审查发现的 6 个问题逐条核实后全部修复。
- **#1【P1 安全】appservice 密钥硬编码进 git**：`config.py` 的 `as_token`/`hs_token` 默认值改空串；`from_env` 按「环境变量 → 注册文件 `run/synapse/guduu-bot.yaml`(已 gitignore)」优先级注入；新增 `require_tokens()` 启动校验，缺失即报错，不再静默用泄露的旧 key。⚠️ **旧 token 仍在 git 历史，必须在服务器侧轮换**。
- **#2【P1】`BOT_ID` 写死 `cosmac.cc`**：本地 `guduu.local` 下会邀请不存在的账号。改为函数 `botId()`=`@guduu:${serverName()}`，按当前登录服务器动态拼（登录后求值，避开模块加载期 mx 未就绪）。
- **#3【P1】控制室只有创建者可访问**：`ensureControlRoom` 现邀请**全部服务器管理员**并把他们的房间权限提到 100（否则受 state_default=50 限制，写不了 `cosmac.ai.config`）。
- **#4【P1】配置读失败"失效开放"**：`get_state_event`/`resolve_alias` 现在区分 404(确实没有→None) 与 403/网络错(抛异常)；`_read_overrides` 仅在读成功时更新缓存，读失败保留上次成功配置——一次抖动不再把管理员设的工具限制清空。
- **#5【P2】控制室 room_id 永久缓存**：别名改为每轮（20s 缓存窗口）重解析，控制室重建/重指向后能跟上。
- **#6【P3】Vue 源混入 4 个 NUL 字节**：`LiveView.vue` 的 markdown 占位哨兵由字面 NUL 字节改为转义序列 `\x00`（运行时等价），文件恢复为纯文本，`rg`/`file`/diff 不再当二进制。
- 验证：`test_runtime_config.py` 加 2 个回归测试（抖动不失效开放 / 缺密钥报错），cosmac 单测全过、ruff 通过、client `npm run build` 通过；`from_env` 本地能从 yaml 读到密钥（本地开发不回归）。

## 2026-06-19 — 管理后台入口改回「仅管理员可见」
- 之前为破 CORS 鸡生蛋把入口改成常显；现 CORS 已通、`isServerAdmin()` 探测正常，按用户要求改回：登录后探测是服务器管理员才显示「管理后台」入口，普通用户菜单里看不到（手敲 /#/admin 仍被 AdminView "无权限"闸 + Admin API 403 双重挡回）。
- LiveView：恢复 isAdmin ref + afterLogin 里 isServerAdmin 探测 + 入口 v-if=isAdmin。preview 验证 @admin 登录可见入口、isAdmin=true。

## 2026-06-19 — 管理后台④：AI 配置（人设/模型/工具开关，控制室热下发）
- 管理后台最后一块**AI 配置**：网页改主 AI 的人设(system prompt)/模型 id/工具开关，保存后 ~20s 内**热生效、无需重启 bot**。管理后台四块(用户/频道/数据/AI)全齐。
- 架构(守 CLAUDE.md：Matrix 原生、不另起服务、不动 nginx)：配置存进一个**控制室**(别名 `#cosmac-ctrl:<server>`)的 state event `cosmac.ai.config`。前端(管理员=房间创建者，有权写 state)写、bot 运行时读。
- **零回归设计**：bot 读配置全程 try/except + 20s 缓存 + 按 (provider,model,system_prompt) 签名才热重建 llm/agent；控制室不存在/未加入/读失败 → 完全回退启动时的环境变量配置。provider 本期前端**只读不可改**(避免切到没 key 的后端→静默降级 echo)。工具开关：Toolbox 加 `set_enabled`，specs/execute 都按启用集过滤。
- 后端：`config.py` 加 control_room_alias + AI_CONFIG_EVENT_TYPE；`matrix_client` 加 resolve_alias/get_state_event；`appservice_bot` 加 _read_overrides/_apply_runtime_config。前端：`client.ts` 加 ensureControlRoom/getAiConfig/setAiConfig；AdminView 加 ai tab。
- 验证：新增 `test_runtime_config.py`(假 client 验证人设热应用/工具过滤/缓存/读失败回退)，cosmac 14 单测全过、ruff 通过。前端**直连生产**验证：保存自动建控制室 `!sQjaKThqehKUaCojUV`、写读 `cosmac.ai.config` round-trip(st 200)。⚠️ bot 端读取本机无法验，需上线点验。

## 2026-06-19 — 管理后台③：数据概览（KPI + 最活跃频道）
- 管理后台第三块**数据概览**：AdminView 加 `overview` tab。4 张 KPI 卡(账号总数/管理员/停用、频道总数/公开/加密、成员人次合计/平均、活跃频道≥2 人) + 服务端版本 + 最活跃频道 Top 8。
- 低风险：基本是**复用**已有 `listUsers`+`listAdminRooms` 前端聚合，仅 client.ts 新增轻量 `getServerVersion()`。
- 踩坑：Synapse Admin rooms API 的 `order_by=joined_members&dir=b` 在本版(1.153.0)**没按预期降序**(返回升序)，所以"最活跃 Top"改为**客户端按成员数降序**，不依赖接口排序。
- preview 直连生产验证：1 账号 / 38 频道 / 54 成员人次(均1.4) / 18 活跃 / 服务端 1.153.0；Top 8 按成员降序正确。build 通过。管理后台四块只剩 AI 配置(后端重活)未做。

## 2026-06-18 — 个人主页接入 URL（/me）；其余覆盖层确认保持弹窗
- 路由覆盖审计：主导航(board/tasks/频道/admin)已全覆盖；临时态(菜单/各设置弹窗/侧栏折叠/AI侧栏/专注模式)按惯例不接。剩 5 个页面级覆盖层(个人主页/市场/插件商城/资产/CLI)原本无地址。
- 按负责人选择：只给**个人主页**接 `/me`(它最像页面、该能刷新留存/分享)；市场/商城/资产/CLI 保持弹窗(刷新落在工具弹窗里体验怪)。
- 实现：`useProfileHome().visible` 接进集中同步——`computePath` 加 `/me` 分支、`applyFromRoute` 把 admin/profile 两个全屏覆盖层按地址互斥开关、watch 数组加 `profileVisible`；router 补 `/me`→Blank。
- preview 验证：开个人主页→`#/me`、后退→关闭回 board、**刷新 `/me`→直达个人主页**。build 通过。

## 2026-06-18 — 工作台接入 URL 路由（每个视图有独立地址 + 后退/刷新/深链）
- 问题：整个 app 是单个 `LiveView` 根组件、用内部状态切视图，点来点去 **URL 从不变**——刷新回默认页、不能分享链接、浏览器后退无效。
- 方案：**集中式双向 URL 同步**，不动任何点击 handler（导航本就收敛在 `selectSpace/openBoard/openTasks/openRoom + adminOpen`）。状态变→`router.push` 写地址；地址变(后退/前进/手改/深链)→还原状态；首屏按地址恢复一次(深链到频道要等房间加载)。用 hash history(已有)，无需改 nginx。
- 地址方案：`/admin`、`/s/:space/board`、`/s/:space/tasks`、`/s/:space/c/:roomId`。`router/index.ts` 补这些路由(指向空 `Blank` 组件——LiveView 不走 `<router-view>`，路由仅为让 hash 合法、不被 catch-all 重定向回 /)。
- preview 直连生产验证全过：登录自动 `/s/x/board`、看板/任务切换、频道 `/c/room`、后退前进、**频道深链刷新直达**、切工作区更新地址、`/admin` 开关。build(vue-tsc) 通过。

## 2026-06-18 — 管理后台②：频道/群管理 + admin 接口 CORS 打通
- 管理后台第二块**频道管理**：AdminView 加 tab 切换（用户管理/频道管理）；频道面板列出**全服所有房间**（不同于侧栏只列"我加入的"）：名/别名、成员数(总/本服)、类型(公开/私有 + 加密锁)、操作(查看成员弹窗 / 删除)。删除带二次确认 + 是否封禁(block，禁止重建)。
- client.ts 补 admin 房间接口：`listAdminRooms`(v1 /rooms 自动翻页,按成员数倒序) / `getRoomMembers` / `deleteRoom(block,purge)`。沿用 `adminFetch` 那套。
- 本地 preview 直连生产验证：拉到 36 个真实房间(GuDuu测试群/《银河谣》制作专班/明星·粉丝…)、查看成员弹窗正常(GuDuu测试群→@guduu)。删除是破坏性操作,未拿真房间测(逻辑已接)。小修:标题栏右边距避让关闭✕。
- **关键卡点(服务器侧,无需改代码)**：admin 接口浏览器调用一直 `Failed to fetch`。根因有三层——① hs 的 nginx 转发正则 `^(/_matrix|/_synapse/client)` **漏了 `/_synapse/admin`**,请求落到兜底 200 文本;② 自己加 CORS 头与 Synapse 自带的 `ACAO:*` **重复**(浏览器拒绝双 ACAO);③ OPTIONS 预检 Synapse 对 admin 接不住。**最终方案**:nginx 只拦 `/_synapse/admin` 的 OPTIONS 预检(回 204),其余转发给 Synapse、用它单个 ACAO,不再自加头。（详见 DEPLOY.md 待补的踩坑条）

## 2026-06-18 — 管理后台①：用户管理（MVP，覆盖层集成进 LiveView）
- 新模块：平台管理后台。按"一次只推一个"先做**用户管理**：列表 / 新建 / 停用 / 恢复 / 重置密码 / 设撤管理员。
- 关键架构发现：真实 app 的根组件是 `views/LiveView.vue`（`main.ts` 挂它），**不是** App.vue —— `<router-view>` 不渲染，所以加 `/admin` 路由没用。改成把 `AdminView.vue` 作为**全屏覆盖层**集成进 LiveView：用户菜单加「管理后台」入口（仅管理员 `isServerAdmin()` 探测为真才显示），点开覆盖层、× 关闭。（已存 memory: client-root-is-liveview）
- 后端复用 Synapse Admin API（`/_synapse/admin/...`），用登录管理员 token：`client.ts` 补 `isServerAdmin/listUsers/deactivateUser/reactivateUser/resetPassword/setUserAdmin` + `adminFetch` 封装。
- **本地验证发现真问题**：浏览器从 app 源直连 hs 的 `/_synapse/admin/*` 被 **CORS 拦**（`/_matrix/*` 200、admin 路径 Failed to fetch）—— Synapse 只给 `/_matrix` 发跨域头。即原有 `createUser` 跨域下也不通。解决要在 hs 的 nginx 给 `/_synapse/admin/` 放开 CORS（限 app 源 + 允许 Authorization + 处理 OPTIONS 预检）。否则连真 @admin 也进不去（已把权限闸文案改成同时提示这两种原因）。
- 已验证：AdminView 覆盖层 + 左侧菜单（用户管理 active，频道/AI/数据「敬请期待」占位）+ 权限闸渲染正常；build/类型通过。happy path（列表/操作）待 nginx 放 CORS 后线上点验。
- 仅做只读验证（未对生产执行任何停用/改密/建号）。

## 2026-06-18 — 主 AI 控制层②：LLM 工具调用（AI 真能动手了）
- 模块 1 后半段落地：主 AI 从「只会聊天」升级到「会调用 IM 能力动手」。整条链路：用户自然语言 → 模型决定调工具 → 真执行（建群/发消息/查成员/读记录）→ 结果回灌 → 给最终回复。
- 关键设计（守 CLAUDE.md：厂商差异只锁在抽象层）：
  - `ai/base.py` 新增厂商中立的 `ToolSpec/ToolCall/TurnResult`，`Message` 扩展 tool_calls/tool_call_id；`LLMProvider.complete_with_tools` 默认退回 `complete`（echo/openai 不支持工具也照常跑）。
  - `ai/claude.py` 实现工具调用：中立结构 ↔ anthropic `tool_use`/`tool_result` 互转，所有 anthropic 专有格式只此一处。
  - 新增 `ai/tools.py` 工具箱：`create_room`/`send_message_to_room`/`list_room_members`/`get_recent_messages`，转发到 `MatrixClient`；用 `ToolContext` 注入「当前房间/发起人」，建群默认拉发起人进群。`matrix_client.py` 补 `get_members`/`get_messages`（读聊天记录的"眼睛"）。
  - 新增 `ai/agent.py` ReAct 循环（max_steps=5 防死循环）；`appservice_bot.py` 把纯 `complete` 路径换成 `agent.run`。旧「专班」关键词快路保留做富卡派单演示。
- 验证：新增 `tests/test_agent_tools.py`（假大脑+假client 端到端验证「决定调工具→真执行→回灌→最终回复」、建群自动邀请发起人、max_steps 兜底），9 个单测全过；ruff（行宽88）通过；bot 构造冒烟通过（4 工具就位，echo 退化为纯文本不报错）。
- 待办：线上配 `GUDUU_LLM_PROVIDER=claude`+`ANTHROPIC_API_KEY` 后做真·Element 自然语言建群点验；前端 AI 面板接到真 bot（下一步把"演示"打通成"产品"）。

## 2026-06-18 — 修复数据看板「横向拖移」BUG
- 现象：数据看板画布在窗口偏窄时可被横向拖动/平移，标题被推出左缘（用户反馈）。
- 根因：`.board-scroll` 与 `.canvas` 都只写了 `overflow-y: auto`；按 CSS 规范，另一轴若仍是 visible 会被隐式算成 `auto`，于是内容略宽时整块就能横向滚动/拖移。
- 改法：两处显式补 `overflow-x: hidden`（LiveView.vue 的 .board-scroll + styles/canvas.css 的 .canvas），只保留纵向滚动，彻底禁掉横向拖动。本地 preview 1440/1180 宽验证：ofx=hidden、无横向滚动、看板渲染正常、无报错。

## 2026-06-18 — 任务行可点开看详情（负责人/进度/做到什么程度/子步骤）
- 每条任务补字段 progress + detail + steps[]（子步骤 checklist）；任务行加 clickable + 悬停箭头。
- 新增任务详情弹窗(.td-*)：状态点 + 标题 + 状态/负责人/截止 chips + 进度条% + 当前进展说明 + 子步骤勾选。
- taskDetail 弹窗状态 + openTaskDetail。本地验证：点「主角配音+配乐」→ 负责配音Agent/65%/4 子步骤(2✓2○)；无报错。

## 2026-06-18 — 制作流水线改为 AI 影视 7 阶段
- 用户校正流程：AI 影视不是传统拍摄。阶段定为 **剧本 / 服化道 / 分镜 / AI生成 / 配音配乐 / 剪辑 / 成片**（7 步）。
- PROD_STAGES 改 7 项；各集 current 重映射(夜航星第6集→配音配乐4、银河谣第12集→分镜2、墨白MV→剪辑5)；甘特条改 ganttBarStyle(i) 按阶段数均分(不再写死 18%/22%，7 阶段不溢出)。
- 本地验证：卡内 7 步流水线 + 甘特 7 行(剧本✓…AI生成✓→配音配乐●→剪辑/成片)排布正常；无报错。

## 2026-06-18 — 每集卡下面跟「这一集的任务」，逐集排列
- 用户要：每集卡下面是这一集的任务，然后才是下一集（卡+任务）。改成：每集 = .ep-block（流水线卡 + 该集任务时间线），逐集往下堆。
- 数据：每个 episode 加 tasks[]（自带任务，按集分）；新增 epTasks(ep) 排序、activeTaskTotal、showCount 改为按集任务数求和。Tab 角标=该剧所有在制集任务数(夜航星6/银河谣3/墨白6)。
- 移除原来跨集的单条时间线 + 旧 todos 过滤(taskItems/taskCols/showTimeline)。整部进度仍在顶部、点卡仍开甘特。
- 本地验证：夜航星 第6集(4任务)+第7集(2任务) 各自归位；无报错。

## 2026-06-18 — 多集同时在制 + 点开看甘特弹窗；去掉看板
- 升级：一部剧支持**多集同时在制**——每集一张流水线卡（可多张，flex-wrap）；**点单集卡 → 弹甘特图**（该集 5 阶段在日期轴上的排期，done绿/current橙/todo灰 + 图例）。
- 按用户决定**去掉最下面的看板**；保留 整部进度 + 多集卡 + 时间线。show-band 改为可滚动。
- 数据：productionTabs 每剧 episodes[] 多集（夜航星 第6集/第7集、墨白 MV/专辑企划…）；新增 ganttEp 弹窗状态 + GANTT_DATES + mkStages 复用。
- 本地验证：夜航星 2 张在制卡、点开第6集甘特(剧本✓分镜✓配音●剪辑成片)、看板已移除、时间线仍在；无报错。

## 2026-06-18 — 剧集顶部再加「整部进度」（分段条：每段一集）
- 用户指出现有流水线卡是"单集"进度，上面还应有"整部剧"进度。加一条**分段式整部进度条**(每段=一集：已完成绿/当前集橙/未做灰) + "已完成 M/N 集 · X%"，放在本集流水线卡上方。
- productionTabs 每剧补 series{done,total,unit,pct}；.series-bar/.series-seg 样式。夜航星 5/12集48%、银河谣 11/12集95%、墨白 4/8首58%。
- 本地验证：切 Tab 整部进度+本集卡同步；无报错。

## 2026-06-18 — 剧集 Tab 点开后：制作流水线卡 + 时间线 + 看板（顶部换成流水线卡）
- 顶部从"朴素进度条"换成用户要的**制作流水线卡**：剧本→分镜→配音→剪辑→成片(✓完成/●当前发光/数字未到，连接线 done 段绿) + 进度条 + 页脚(负责人头像 + 排期 + 还剩N天)。下面接 时间线 + 待办/进行中/已完成 看板。
- productionTabs 每部剧补流水线 demo 数据(project/current/percent/assignee/排期)；activeProd 渲染流水线卡；恢复 PROD_STAGES/mkStages 与 .prod-* 卡样式(改为整宽单卡)。
- 本地验证：墨白卡=剪辑阶段/55%/剪辑Agent·6/16→6/24·还剩4天，与用户给的样图一致；时间线4行+看板4卡；切 Tab 同步；无报错。

## 2026-06-18 — 剧集 Tab 点开后(旧)：进度条 + 时间线 + 看板
- (此版顶部为朴素进度条，已被上一条的"制作流水线卡"替代)

## 2026-06-18 — 任务看板加「剧集 Tab」：3 部剧切换，各看各的任务
- 需求几轮对齐后定稿：任务看板标题栏加 **3 个剧集 Tab**（夜航星/银河谣/墨白），点哪个看板就只显示那部剧的 待办/进行中/已完成。
- todos.ts：TodoItem 加 `show` 字段，把 11 个 demo 任务按剧集打标（夜航星3/银河谣4/墨白4）。
- LiveView：productionTabs + activeShow + showCount(角标) + taskItems 按 activeShow 过滤；header 加 .prod-tab 胶囊(头像+名+数量，选中橙边)；board-sub 改显当前剧任务数。
- （撤掉了上一版误做的"剧集制作卡大卡片+流水线"，那不是用户要的。）
- 本地验证：3 Tab 计数正确(3/4/4)，点银河谣→看板只剩银河谣 4 条；无报错。

## 2026-06-18 — 数据源改为单按钮 → 右侧面板；去掉看板头 ℹ(中枢AI开关)
- 用户要：数据源按钮移到 ℹ 的位置(最右)；ℹ 图标+功能整个去掉；点数据源 → 右侧出现面板。
- 数据看板头现在只剩一个「数据源」按钮(圆柱图标+数量角标)，点开右侧 `BoardSourcePanel`(复用 .right 样式)：展示数据源列表 + 内联增删 + 自动保存。下拉小卡片和铅笔编辑弹窗合并进这个右面板，删掉 BoardSourceModal。
- 去掉数据看板头的 ℹ(中枢 AI 开关)——中枢 AI 仍可从插件竖栏「智」/顶栏开。
- 三个右面板互斥扩展：关于此频道 / 中枢 AI / 数据源 同时只开一个。
- 任务看板头同样：board-sub + 单个数据源按钮。
- useBoardSources 加 panelOpen/panelBoard/toggleSourcePanel/closeSourcePanel。本地验证：点数据源→右面板出现、中枢AI收起；加「抖音创作者后台」保存→删除复位，无脏数据；无报错。

## 2026-06-18 — 数据源控件从侧栏挪到看板头（用户要放标题栏）
- 用户要把数据源「展示+编辑」放到 数据看板/任务看板 的**标题栏**(ℹ 左边)，不是侧边栏。
- 侧栏两行恢复成原来的纯图标+文字；看板头 ch-actions 加：①数据源按钮(圆柱图标+数量角标)→点开下拉列表(展示当前源 + 「编辑数据源」入口)；②铅笔「编辑数据源」→开 BoardSourceModal。两个看板头都加。
- 下拉用绝对定位 .bs-pop；点外面关闭(接进 onDocClick，识别 .bs-hdr)。数据/持久化逻辑不变(useBoardSources)。
- 本地 preview 验证：数据看板/任务看板头显示 数据源(N)+编辑+ℹ，下拉正常，无报错。

## 2026-06-18 — 修：数据源「编辑」铅笔图标改常显
- 上一版铅笔图标 opacity:0 只在 hover 行时显示，用户反馈"没看到按键"。改为常显(opacity .65，hover 升到 1)，两个看板行的"编辑数据源"图标一眼可见。

## 2026-06-18 — 数据看板/任务看板：数据源「展示 + 编辑」+ 持久化
- 需求：两个看板行的图标改成「数据源展示」，再加一个「数据源编辑」图标。数据源先当配置占位、做 UI + 持久化。
- 左侧图标改为数据源图标：点击展开该看板的数据源列表（cs-src-list，显示 类型+名称，空则提示点 ✎ 添加）。
- 行右侧加铅笔「编辑数据源」图标(hover 显示)：开 `BoardSourceModal` 弹窗增删数据源(名称/类型[频道聚合/外部平台/API接口/手动录入]/备注)。
- 持久化：按当前工作区(Space)存一条 `cosmac.board_sources` state event(内容 {dashboard:[],tasks:[]})。matrix/client.ts 加 get/setBoardSources；新建 useBoardSources composable(防抖自动保存) + BoardSourceModal(复用 .cam-* 样式)。
- 坑：activeSpace 变化时 Space 房间 state 可能还没 sync → 首次读为空。修复：openEditor/togglePopover 时再 load() 一遍(同 liveMembers 的 refresh-on-open)。
- 验证(连生产 hs)：制作工作区加「抖音创作者后台」数据源 → 刷新仍在 → 删除复位，未留脏数据。数据源真实取数留待后续(配置占位)。

## 2026-06-18 — 右侧「关于此频道」与「中枢 AI」面板互斥
- 需求：开「关于此频道」就收起中枢 AI，开中枢 AI 就收起「关于此频道」（右侧同时只留一个）。
- 实现：LiveView 加两个 watcher —— `watch(rightPanelVisible→aiOpen=false)` / `watch(aiOpen→hideRightPanel())`。用 watcher 而非改每个按钮，自动覆盖所有入口(ℹ/顶栏/插件栏/输入条)。
- 验证：点 ℹ 开关于面板→AI 收起；点插件栏「智」开 AI→关于面板收起。无报错。

## 2026-06-18 — 频道头 ℹ 按钮 → 复刻 DEMO「关于此频道」右面板（真实数据）
- 频道头 ℹ(info) 按钮原本是「开关中枢 AI」；改为**复刻 DEMO**：开/关右侧「关于此频道」信息面板（RightPanel）。中枢 AI 仍可从顶栏/插件竖栏/输入条 AI 键开。
- RightPanel 做成**真实**：人员用真实 Matrix 成员(liveMembers，映射成面板形状，群主/管理员/成员/待接受)；技能/知识库/规则沿用已真实持久化的频道配置(空就空)；PINNED 块真实频道改为中性总览文案(去掉抖音/小红书等假平台claim)。
- RightPanel 自带 `import '@/styles/right.css'`(同 admin-modal：main.ts 不加载整包 index.css，组件自包含样式)。
- LiveView：导入 RightPanel + useRightPanel；onMounted hideRightPanel 默认收起；`<RightPanel v-if="rightPanelVisible && currentRoom && !focused">` 作为中枢 AI 面板左侧的信息列。
- 本地 preview 验证：夜航星点 ℹ → 弹出「关于此频道」(300px 列)，人员显示真实 2 人(admin 群主/guduu 成员)，与「频道管理」同源数据；无 console 报错。

## 2026-06-18 — 频道管理「技能/知识库/规则/数据权限」4 个列表标签 → 真实持久化（配置全标签页完成）
- 把最后 4 个列表型标签接通持久化，至此**频道管理 8 个标签全部去 mock**（人员真实成员 + 7 个配置标签真持久化）。
- 策略：**手动维护 + 自动保存**。真实频道**从空开始**（loadConfigFromRoom 把列表一律以"已存为准、没存就空"，清掉 seedConfig 的 demo mock）；用户在面板加/删/改，深度 watch 防抖整列表写回 cosmac.channel_config。
- 各列表加空状态提示 + 保存状态提示。标签数字用真实列表长度。
- 本地 preview 验证（连生产 hs）：夜航星技能从 0 → 加「生成分镜脚本」→ 刷新仍在；银河谣技能仍 0（隔离成立）；测试技能已删除复位，未留生产脏数据。
- **频道管理面板真实化全部完成。** 余下大头是任务#3：让中枢 AI bot 真按这些配置（人设/模型/规则）回复（动 cosmac/ 后端）。

## 2026-06-18 — 频道管理「模型 + 记忆审计」标签 → 真实持久化
- 复用上一条建好的 state event 机制，把**模型**(模型/Token预算/速率限制)和**记忆审计**(长期记忆/上下文范围/留存天数/审计日志)也接通自动保存。
- `useChannelAdmin`：loadConfigFromRoom 增读 model/memory；新增两个深度 watch → 改动防抖写回 cosmac.channel_config。`ChannelAdminModal` 模型页、记忆页加保存状态提示。
- 本地 preview 验证（连生产 hs）：夜航星改 Token 预算 507 + 关长期记忆 → 刷新后仍在；测试值已复位(预算500/长期记忆开)，未留生产脏数据。
- TODO：模型档位 MODEL_OPTIONS 仍是品牌占位名(CosMac Star-Pro/Lite)，要让 bot 真按它跑(任务#3)需映射到真实 provider/model。
- 已真实持久化的标签页：角色 / 模型 / 记忆审计。余下 技能/知识库/规则/数据权限(列表型，待确认真实内容来源)。

## 2026-06-18 — 频道管理「角色(人设)」标签 → 真实持久化（配置存进房间 state event）
- 建好配置持久化地基并接通**角色标签**：人设（AI 名称/语气/System Prompt）改一下就自动存进频道。
- `matrix/client.ts`：新增 `getChannelConfig`/`setChannelConfig`，存成每频道一条自定义 state event `cosmac.channel_config`（与 cosmac.workspace 同命名）。选 state event 而非 account data：群级共享、多端一致、留在房间、不改 Synapse 核心。写需房间发状态事件权限（一般管理员）。
- `useChannelAdmin`：`setCurrent(name, roomId)` 时从房间读已存配置 merge 进内存；深度 watch 人设 → 防抖 700ms 自动 `setChannelConfig`；`saveState`(idle/saving/saved/error) 给 UI 提示；加载期 suppress 防回声；demo 无 roomId 不写。
- `ChannelAdminModal` 角色页加保存状态提示「✓ 已保存到本频道 · 多端同步 / 保存失败(无权限)」。
- 本地 preview 验证（dev 客户端连的是**生产** hs.cosmac.cc）：夜航星改 AI 名 → 刷新后仍在（真存进 state event）；银河谣仍是默认「CosMac Star」→ **每频道隔离**成立。测试marker已清回默认，未留生产脏数据。
- 余下 model/memory/skills/knowledge/rules/dataScopes 标签页沿用同一持久化机制，按用户逐个确认再接。

## 2026-06-18 — 频道管理「人员」标签 → 真实 Matrix 成员（去 mock 第一步）
- 开始把「频道管理」面板从 DEMO mock 改成真实数据（路线图 #2 群级智能）。本轮先做**人员标签**。
- `matrix/client.ts`：新增 `listChannelMembers(roomId)` 返回真实成员（真名/头像 mxc→http/角色按 m.room.power_levels 推 群主≥100·管理员≥50·成员/join+invite 状态）；新增 `kickFromRoom`（真移除）。没设昵称的成员退回显示 id 的 localpart（如 bot 显 "guduu"）。
- `useChannelAdmin`：跟当前频道 roomId（`setCurrent(name, roomId)` / `open(name, roomId)`），暴露 `isLive`/`liveMembers`/真 `inviteLiveMember`/`removeLiveMember`；有 roomId 走真后端，无则回退 demo mock。
- `ChannelAdminModal` 人员标签：`isLive` 时渲染真实成员（头像/角色标签/APP 标/待接受标）+ 真邀请框 + 真移除；标签数字 `人员 N` 用真实人数；打开弹窗 watch 刷新防 sync 漂移。
- LiveView 传 `currentRoom`(真实 room id) 给面板。本地 preview 验证：夜航星频道显示真实 2 人（@admin 群主、@guduu 中枢AI APP·成员），与频道头 "A 智 2" 一致。
- **待补真实数据（已记 TODO）**：成员「可调取数据」无来源已移除；bot 没设 displayname/头像 → 退回 localpart+首字母；真人头像待用户上传后自动显示。
- **决策**：配置存哪？定为 **Matrix 自定义 state event**（不改 Synapse 核心、原生、多端同步），下一轮（人设等）落地。

## 2026-06-18 — 客户端：频道头「成员」按钮接 DEMO 的「频道管理」富面板
- 真实客户端（LiveView）频道头成员堆叠按钮原本只开简单「邀请成员」弹窗；改为**复刻 DEMO 逻辑**：点了打开 DEMO 同款 `ChannelAdminModal`「频道管理」富面板（角色/人员/技能/知识库/数据权限/规则/模型/记忆审计 多标签页，群级 AI 隔离配置）。
- 按既有「常驻挂载 + composable.open()」模式接入：导入 `ChannelAdminModal` 常驻挂载、按钮调 `useChannelAdmin().open(currentName)`；并 `watch(currentName)` → `setCurrent`，让面板跟着当前频道切到对应群配置（每群一份、互不影响）。
- 真实「邀请已有用户」入口保留在左侧频道栏「邀请成员」项，未丢功能。
- **关键修复**：`main.ts` 故意不加载整包 `styles/index.css`（防 DEMO CSS 串扰），导致 `.cam-*` 弹窗样式缺失、面板裸奔。让 `ChannelAdminModal.vue` 自带 `import '@/styles/admin-modal.css'`，组件自包含样式，DEMO/真实端两边都成型。本地 preview 已验证：居中卡片 720×660、遮罩、各标签页、成员头像齐全，无 console 报错。

## 2026-06-18 — 客户端：回复连接线竖线不连头像、留空隙
- 连接线 ::before bottom -13→-2px，竖线停在头像上方留空隙，不再连到头像。

## 2026-06-18 — 客户端：回复连接线弯角上移对齐文字
- 连接线弯角 ::before top 11→4px，弯角与回复文字对齐、竖线落到头像，更顺。

## 2026-06-18 — 客户端：回复预览往上提、与消息拉开间距
- 回复行与下方头像几乎贴着 → margin-bottom 2→7px，连接线 bottom 拉长到头像，回复行到头像顶约 7px 间距，更分明。

## 2026-06-18 — 客户端：回复预览补被引用人小头像（Discord 三行结构）
- 回复预览第一行补上**被引用人的小圆头像**（+ bot 显 APP 标），结构=被引用人头像/名字/预览 → 自己名字/时间 → 内容。
- `client.ts` LiveMsg 加 `replyToSender`，listMessages 带出被回复发送者 id（判断 bot + 取头像）。

## 2026-06-18 — 客户端：回复预览只留一个连接线 + 消息上方留空行
- 之前同时有「↩ 图标」和「弯角连接线」两个箭头 → 去掉 ↩ 图标，只留连接线。
- 每条消息上方加空行（`.msg:not(.grouped)` margin-top 8→18px；有回复的 22px），给连接线腾空间、不再贴着上一条、对齐。

## 2026-06-18 — 客户端：修回复预览错位（整行浮头像上方）
- 之前回复放在头像右侧同行 → 连接线对不上(错位)。改成 Discord 结构：`.msg` 改 column，回复预览**整行浮在头像上方**，下面 `.msg-main` 才是 头像+内容。
- 连接线 ::before 重新定位：从回复行中部**下探到下方头像**、顶部弧向右接到回复文字。加 **↩ 小箭头**图标。

## 2026-06-18 — 客户端：回复预览对齐 Discord（连接线 + 着重/配色）
- "↳" 箭头 → 改成 Discord 风**弯角连接线**（CSS ::before：border-left+border-top+圆角，从头像处弧连到回复预览）。
- 回复预览文字：对方名 **@xxx 上色加重**（nameColor），正文用**淡灰色**(text-3)区分。
- 修双 @ bug（bot 名本身以 @ 开头，渲染前 strip 一个 @）。

## 2026-06-18 — 客户端：聊天再对齐 Discord 观感（4 项）
- **消息行样式**：头像方块→正圆(40px)；去掉每条"成员/AI"小标签 → 名字按发送者确定性上色 + bot 才显"APP"标。
- **日期分隔线**：按天分组，中间横线显"今天/昨天/X 年 X 月 X 日"。
- **emoji 选择器面板**：点工具条表情/反应＋弹出 32 个常用 emoji 网格，点选即反应、点外面关。
- **悬停工具条扩展**：表情(开选择器)/回复/编辑(仅自己,非卡片)/复制。
- **编辑消息**：编辑自己的消息(m.replace)，输入框上方"编辑中"横幅、Esc 取消；消息显示"已编辑"。`client.ts` 加 `editMessage`。
- 说明：只采用通用聊天约定、不克隆 Discord 私有设计/图标。端到端验证(圆头像/日期线/APP/emoji面板32格/编辑载入)，未产生测试数据。

## 2026-06-18 — 客户端：聊天 Discord 化（分组/反应/回复/提及/编辑）
- **消息分组**：同发送者、5 分钟内、非回复 → 折叠头像/名字（左槽分组内悬停显时间）。
- **悬停工具条**：消息右上角悬停出现 👍/❤️/😂/回复。
- **表情回应**：真实 `m.reaction`，反应条显示 emoji+计数，点击切换（我的高亮），＋ 快捷加。`client.ts` 加 `listReactions/react/unreact`。
- **回复引用**：悬停"回复"→ composer 上方回复横幅 → 发送带 `m.in_reply_to`；消息上方显示"↳ 对方名 + 正文预览"。`client.ts` 加 `sendReply`，`listMessages` 解析 in_reply_to + 去 fallback。
- **@提及高亮**（renderMd 里 @用户 加底色）+ **编辑标记**（读 `replacingEvent` 显示"已编辑"，取最新内容）。
- 全部是 Matrix 原生能力、不依赖后台。端到端验证(墨白后援会)：反应👍1、回复预览、提及高亮、markdown 都正常 → 已撤回 6 条测试消息+1 反应清理干净。

## 2026-06-18 — 客户端：消息渲染 Markdown（输入/发送本就是真的）
- 澄清：输入框+发送一直是**真实**的（`send`→`sendTextMessage`→Synapse，持久化、bot 真回）。半 DEMO 的是 Markdown 工具条只插符号、消息却原样显示。
- 接通：消息流 + AI 面板的正文改用 `renderMd()` 渲染 Markdown（加粗/斜体/删除线/行内码/代码块/链接），工具条终于有效果。
- **安全**：先 HTML 转义再替换（`<script>` 变纯文本、防 XSS）；链接仅放行 http/https/mailto；代码内容用 \x00 占位隔离、不与"第 12 集"这类文本撞。已验证渲染+XSS。
- 顺带：`listMessages` 过滤掉**已撤回(redacted)/空 content** 的事件 → 不再显示空气泡。
- 附件/表情：按负责人意见，**等后台管理做好再接**（附件需上传媒体+渲染图片消息）。

## 2026-06-18 — 客户端：清掉工作区/频道剩余 DEMO + ★收藏接真
- 删掉已死的 DEMO 弹窗：`DepartmentCreateModal`(被真实新建工作区表单取代)、`ChannelAdminModal`(被真实成员弹窗取代) + 连带 import/composable/死函数(onAddWorkspace 等) + admin-modal.css。
- **★收藏接真**：原来只本地切换、且所有频道共用一个状态(bug) → 改成 Matrix 标准 `m.favourite` 标签，**按频道独立、跨设备同步**。`client.ts` 加 `isFavourite`/`setFavourite`。
- **频道筛选漏斗**去占位：点击从弹 toast → 聚焦"查找频道"输入框。
- 验证：收藏夜航星→银河谣不受影响→切回仍收藏→取消还原；漏斗聚焦输入框。
- 仍是占位（DEMO 本身也是、需较大改动，留着）：Composer 的**附件/表情**(要真做=上传媒体+渲染图片消息)。其余商城/CLI/插件等是"工具"不属工作区/频道范围。

## 2026-06-18 — 客户端：频道头真实成员 + 删除频道 + 清理
- **频道头真实成员**：成员数/头像堆叠改为读真实成员（`listRoomMembers` = `room.getJoinedMembers()`），不再硬编码"2"。
- **成员弹窗接真**：频道头"成员"按钮 → 真实成员弹窗（列出当前真实成员 + 邀请已有用户）；不再开 DEMO 的假管理面板（ChannelAdminModal 仍挂载、留作将来技能/知识库）。
- **删除频道**：频道设置加"删除频道"按钮（二次确认，leave+forget）——和工作区对称。
- 清理死代码 `onAddChannel`/`onInvite`/`onMembers`（已被 openNewChannel/openMembers 取代）。
- `client.ts` 加 `listRoomMembers`。
- ⚠️ 测试事故：自动化测删除频道时脚本没建出临时频道、误删了真实《银河谣》制作专班 → 已用应用"添加频道"在制作中心重建(同名+同简介+开场消息)，room_id 变。教训：测删除务必先确认目标是临时频道。

## 2026-06-18 — 客户端：新建工作区弹窗重排版
- 简称/可见性 从挤在一起的两列 → 改为**竖向全宽**字段（类型→名称→简称→可见性→预览），不再换行/拥挤。
- 简称标签精简成一行：「简称 + 淡色内联提示(左栏图标·最多2字·可留空)」。可见性两个按钮等宽。

## 2026-06-18 — 客户端：工作区简称统一限 2 个字符（多语言）
- 简称（新建工作区 + 工作区设置 两处）统一限制 **2 个字符**，按**码点**算 → 中/英/日/韩/混排/emoji 都是上限 2（emoji 代理对正确算 1 个）。
- 实现：去掉 HTML `maxlength`（按 UTF-16 单位、对 emoji 不准），改用 `watch` + `clamp2`(=`[...s].slice(0,2)`) 截断；label 文案改"最多 2 字"。
- 验证：制作中心→制作 / ABCD→AB / あいうえ→あい / 가나다→가나 / 😀😀😀→😀😀。

## 2026-06-18 — 修复：改工作区名后会跳到最后（排序 bug）
- 根因：之前用「按固定名字 WS_ORDER 排序」，靠名字匹配 → 一改名就掉出固定顺序排到末尾。
- 改为**和名字无关的稳定排序**：`cosmac.workspace.order` 显式序号，`listSpaces` 按 order 排（无 order 排后）。改名只动名字、不动 order → 位置不变。
- `updateSpace` 支持 order 并与 label **合并写**（不互相覆盖）；`createSpace` 新工作区 order=现有最大+1（排末尾）；移除 LiveView 里的 WS_ORDER。
- 回填：4 个基础工作区 order=制作0/运营1/明星2/外部3（用浏览器 admin 客户端写；CLI query-param 写 state 报 403，客户端 sendStateEvent 正常）。
- 端到端验证：排序仍为制作/运营/明星/外部；改名后位置不动；改回正常。

## 2026-06-18 — 客户端：工作区图标支持上传图片 + 简称限 2 字
- 工作区设置：简称 maxlength 3→**2**；简称下方加**上传图片**做工作区图标（上传/更换/移除），有图用图、无图回退简称文字。
- 头像走 Matrix 标准：`uploadContent` → mxc → 存 `m.room.avatar`；显示用 `mxcUrlToHttp`(走 /_matrix/media，已代理)。左栏图标、设置弹窗预览都识别。
- `client.ts` 加 `uploadMedia` / `mxcToHttp` / `spaceAvatar`，`updateSpace` 支持 avatar(undefined不动/''清空/mxc设置)，`LiveSpace.avatarUrl`。
- 端到端验证：上传测试图→左栏图标变图片→移除→回退文字，无残留。

## 2026-06-18 — 客户端：工作区"删除"改成按钮（UI 细节）
- 「删除工作区」从上方红色小字 → 改为底部页脚**左侧的红框按钮**（取消/保存在右侧）；点一下变「确认删除（含 N 频道）」+「×」二次确认。更符合"按钮"直觉。

## 2026-06-18 — 客户端：登录页去技术提示 + 工作区可删除
- 登录页删掉「连接后端 https://hs.cosmac.cc」这行（开发期提示，对用户太技术化、且暴露后端地址）。
- 工作区设置加「删除工作区」：二次确认（提示连同 N 个频道一起删、不可撤销）→ 退出该 Space 下所有频道 + 退出 Space 本身，自动切回数据看板。
- `client.ts` 加 `leaveAndForget(roomId)`。
- 端到端验证：建临时工作区→删除→工作区+其频道消失、切回制作中心、无残留。
- **决策**：客户端"删除"= leave+forget（admin 退出）；真正 purge 房间需 Admin API（后端）。

## 2026-06-18 — 客户端：频道设置（点频道头标题可编辑）
- 点频道头标题（带 ⌄）→ 打开「频道设置」弹窗，改**名称**和**简介**，实时写进 Matrix 房间（`m.room.name` + `m.room.topic`）。工作区可编辑的频道版。
- `client.ts` 加 `updateRoom(roomId,{name,topic})`。
- 端到端验证：改《银河谣》制作专班简介→频道头实时更新→改回，round-trip 正常、无残留。

## 2026-06-18 — 客户端：工作区设置（点工作区名可编辑）
- 点侧栏工作区名（"制作中心 ⌄"）→ 打开「工作区设置」弹窗，可改**名称**和**左栏简称**，实时写进 Matrix Space（名称→`m.room.name`，简称→`cosmac.workspace`）。
- `client.ts` 加 `updateSpace(spaceId,{name,label})`。
- 端到端验证：改简称→左栏图标实时更新→改回，round-trip 正常、无残留。

## 2026-06-18 — 客户端：成员管理（邀请已有用户）+ 一个重要发现
- 「邀请成员」接真：弹窗输入用户名 → 把已有用户邀请进当前频道/工作区（标准 Matrix invite，走 `/_matrix`，已验证：邀请 bot 进它已在的群返回正确的 `403 already in room`，证明链路通）。
- **关键发现/决策**：**「新建账号」从客户端做不了**——hs.cosmac.cc 的 nginx 只代理 `/_matrix/`，`/_synapse/admin/*` 返回静态页（不可达）；且本就不该把 admin token 暴露到浏览器。故账号创建 / 邀请链接**留给后端（业务后台）**，弹窗里已注明。这印证了「成员体系需要后端」。
- `client.ts` 加 `inviteToRoom` / `normalizeUserId` / `serverName`；`createUser`(Admin API) 先留作将来后端代理用。
- 未产生测试数据（建账号失败=没建出用户，已确认 404；邀请是对已在群的 bot 的 no-op）。

## 2026-06-18 — 客户端：频道彩色图标（产品形态）
- 频道列表 + 频道头用「彩色头像方块（代表字）」取代统一地球图标，明星/剧集频道一眼可辨。
- 颜色按频道名确定性哈希取自 8 色调色板；代表字优先「·」后一段 / 《》内首字。
- **决策**：颜色纯客户端计算、不写后端 → 所有现有频道立即生效、零成本；将来要自定义颜色再存 `cosmac.channel` 状态覆盖。

## 2026-06-18 — 客户端：频道简介（模块 R/产品形态）
- 「新建频道」加「简介」字段 → 存为 Matrix `m.room.topic`；频道头标题右侧展示简介（带分隔线）。
- `client.ts`：`LiveRoom` 加 `topic`、`listRooms` 读 topic、`createChannelInSpace` 支持 topic 入参。
- **决策**：用 Matrix 原生 `m.room.topic` 存简介（标准字段、Element 等也能读），不自造状态事件。
- 端到端验证：建了带简介的测试频道→频道头正确显示→清理掉。颜色/图标(封面)留作后续。

## 2026-06-18 — 客户端：工作区 / 频道创建链路接真（产品形态）
- 工作区固定顺序 制作/运营/明星/外部，默认落制作中心。
- 「新建工作区」完整版：类型(制作/运营/明星·粉丝/外部)+名称+简称(存 `cosmac.workspace` 状态)+可见性(公开/私密)+按类型自动建默认频道（明星类建 `虚拟明星·X`+`X后援会` 等）。
- 「添加频道」接真：在当前工作区(Space)下真建房间+拉主 AI+挂接，自动打开。
- 后端整理：真建 6 个影视主题频道(剧集/虚拟明星/粉丝)，清理 9 个旧创作者频道+无名残留，只留营销 5 个。
- 看板：加「数据看板」(制作驾驶舱) +「任务看板」(待办/进行中/已完成三列)，数据全换安其影视主题；登录后第一屏=数据看板。
- 品牌：`tenant` 改安其影视工作室；顶栏/侧栏统一。
- **决策**：工作区=Matrix Space，频道=挂 Space 下的房间(m.space.child)；简称/类型这类业务属性存自定义状态事件 `cosmac.*`，不碰协议层。

## 2026-06-18 — 客户端：界面对齐演示版 + DEMO 按键真功能（产品形态）
- LiveView 1:1 对齐筱雨演示版布局/尺寸/按键（顶栏/工作区栏/频道栏/频道头/Composer/插件栏/AI面板），暖色皮肤。
- 复刻 DEMO 弹窗真功能：商城/插件商城/资产/用户设置/个人主页/新建工作区/CLI/频道管理，按键接 composable。
- **决策**：`main.ts` 只载 tokens+reset 隔离演示组件全局 CSS（避免和 LiveView scoped 同名类撞、旧蓝色泄漏）；装 router 让 DepartmentCreateModal 的 useRouter 可用。

## 2026-06-18 — 宪法整理（CLAUDE.md / AGENTS.md）
- 修 `AGENTS.md` 被「Claude→Codex」盲替换搞坏的技术标识符：provider 值改回 `claude`、模型名改回 `claude-opus-4-8`、模型后端列表改回 Claude（这几处是会让人照抄后跑不起来的真 bug）。
- 品牌对齐：`AGENTS.md` 正文从旧品牌 **GuDuu** 同步到 **CosMac OS / CosMac Star**，错路径 `guduu/` 全部改为真实路径 `cosmac/`。
- **决策**：`CLAUDE.md`（给 Claude）与 `AGENTS.md`（给 Codex）双份同源——正文必须完全一致，**唯一允许的差异**是「AI 助手名字」（Claude vs Codex）和 §6.5 自引用指向各自文件名。注意区分：作为「AI 助手名」的 Claude 可换 Codex，作为「模型/provider」的 `claude` 绝不能换。
- 新增本 `DEVLOG.md`，并在两份宪法 §6.7 加规则：提交前更新本日志。
