"""GuDuu OS Bot 层 —— 主 AI 与 IM（Synapse）之间的桥梁。

包含：
  - matrix_client: 封装对 Synapse 的调用（加入房间、发消息等）。
  - appservice_bot: 接收 Synapse 推送的事件，驱动主 AI 做出反应。
"""
