"""GuDuu OS —— 基于 Synapse/Matrix 的海外版 IM 的自有扩展层。

本包（cosmac）放置 GuDuu OS 所有自己的业务代码，与上游 ``synapse/`` 源码完全分离：
所有 AI、Bot、记忆、工作流等逻辑都在这里实现，尽量不改 Synapse 核心。

详见项目根目录的 CLAUDE.md（项目规范）。
"""

# 发行版版本号：OEM 实例心跳会把它上报给 GuDuu Nexus（大屏版本分布/催升级用）。
# 发新版发行版时同步 bump。
__version__ = "1.11.0"
