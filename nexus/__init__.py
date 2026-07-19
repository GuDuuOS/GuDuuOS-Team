"""GuDuu Nexus —— OEM 体系的母舰控制平面（模块6 P1）。

与 ``cosmac/``（实例内的主 AI 服务）完全独立的一套服务：部署在**你自己的**
Nexus 小 VM 上，管理散布在各 OEM 服务器上的 CosMac 发行版实例。

包结构：
    nexus/db.py      —— 独立数据库（KEY / 实例 / token 钱包 / 用量 / 心跳）
    nexus/keys.py    —— OEM 授权码（KEY）的生成 / 哈希 / 校验
    nexus/fleet.py   —— 业务逻辑（签发 / 兑换 / 心跳 / 充值 / 扣费）
    nexus/service.py —— HTTP 服务（实例回连端点 + 管理端点）
    nexus/gateway.py —— LLM 网关（下一阶段接入；原厂 key 只存在于这里）

安全基线（模块6 拍板结论，别破坏）：
    - 原厂 LLM key 永不出现在实例侧，只进网关进程的 env；
    - KEY 在库里只存 sha256 哈希，明文仅签发那一刻显示一次；
    - 管理端点必须带 Bearer NEXUS_ADMIN_TOKEN（env 注入，无默认值）。
"""
