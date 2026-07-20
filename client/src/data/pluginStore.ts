/** 独立「插件商城」目录——停靠在右侧插件栏的工具 / 应用，区别于 AI Agent 商城 */

export type PluginCat = 'ai' | 'monitor' | 'board' | 'collab' | 'flow'

export interface PluginStoreItem {
  id: string
  name: string
  cat: PluginCat
  author: string
  desc: string
  installs: string
  /** 价格（元）；0 表示免费 */
  price: number
  /** 插件栏图标文字（单字）*/
  icon: string
  /** 插件栏图标底色 */
  color: string
  /** 角标，如「内置」*/
  tag?: string
  /** 对应插件栏里已有的内置插件 id（如 'ai'）；有则不可卸载 */
  builtinPluginId?: string
  installed?: boolean
}

/** 分类元信息：标签 + 主题色 */
export const PLUGIN_CAT_META: Record<PluginCat, { label: string; color: string }> = {
  ai:      { label: 'AI 工具', color: '#c96442' },
  monitor: { label: '监控',    color: '#5b6fb8' },
  board:   { label: '看板',    color: '#4a7a8c' },
  collab:  { label: '协作',    color: '#6b8e4e' },
  flow:    { label: '流程',    color: '#b58932' }
}

export const pluginItems: PluginStoreItem[] = [
  /* AI 工具 */
  { id: 'main-ai', name: 'CosMac 主 AI', cat: 'ai', author: 'CosMac 官方', desc: '右侧栏常驻主控 AI，可建群、自动拉人、查询工作区任务状态', installs: '12k', price: 0, icon: 'AI', color: '#c96442', tag: '内置', builtinPluginId: 'ai', installed: true },
  { id: 'voice-note', name: '语音速记', cat: 'ai', author: 'CosMac 官方', desc: '灵感 / 口播语音转文字，自动生成脚本草稿', installs: '1.4k', price: 9.9, icon: '记', color: '#c96442' },

  /* 监控 */
  { id: 'trend-radar', name: '热点雷达', cat: 'monitor', author: 'CosMac 官方', desc: '全网热榜实时扫描，AI 圈出适合你的选题', installs: '1.6k', price: 0, icon: '热', color: '#5b6fb8' },
  { id: 'comment-center', name: '舆情中心', cat: 'monitor', author: '社区', desc: '全平台评论聚合、情绪分级与预警', installs: '1.2k', price: 0, icon: '评', color: '#5b6fb8' },

  /* 看板 */
  { id: 'data-board', name: '全平台数据看板', cat: 'board', author: 'CosMac 官方', desc: '播放 / 涨粉 / 变现等 KPI 实时大屏，可钉在侧栏', installs: '2.3k', price: 0, icon: '看', color: '#4a7a8c' },
  { id: 'growth-board', name: '增长驾驶舱', cat: 'board', author: '社区', desc: '涨粉来源与增长机会实时呈现', installs: '880', price: 19.9, icon: '涨', color: '#4a7a8c' },

  /* 协作 */
  { id: 'whiteboard', name: '协作白板', cat: 'collab', author: '第三方', desc: '多人实时白板，画分镜脚本、内容矩阵', installs: '780', price: 19.9, icon: '板', color: '#6b8e4e' },
  { id: 'calendar', name: '内容日历', cat: 'collab', author: 'CosMac 官方', desc: '选题 / 拍摄 / 发布日程，与频道联动提醒', installs: '1.0k', price: 0, icon: '历', color: '#6b8e4e' },

  /* 流程 */
  { id: 'e-sign', name: '电子签约', cat: 'flow', author: 'CosMac 官方', desc: '商单合同在侧栏一键签署留痕', installs: '1.1k', price: 29, icon: '签', color: '#b58932' },
  { id: 'task-center', name: '任务中心', cat: 'flow', author: 'CosMac 官方', desc: '选题 / 拍摄 / 剪辑任务的创建、派发与跟踪', installs: '940', price: 0, icon: '单', color: '#b58932' }
]
