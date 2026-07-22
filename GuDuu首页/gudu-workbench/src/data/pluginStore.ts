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
  { id: 'main-ai', name: 'Guduu Main AI · 小蓝', cat: 'ai', author: 'GuDuu 官方', desc: '右侧栏常驻总控分身，可建群、自动拉人、查询各环节分身任务状态', installs: '12k', price: 0, icon: 'AI', color: '#c96442', tag: '内置', builtinPluginId: 'ai', installed: true },
  { id: 'voice-note', name: '语音速记', cat: 'ai', author: 'GuDuu 官方', desc: '语音转文字，海上 / 车间免打字上报', installs: '1.4k', price: 9.9, icon: '记', color: '#c96442' },

  /* 监控 */
  { id: 'cctv-wall', name: '实时监控墙 CCTV', cat: 'monitor', author: 'GuDuu 官方', desc: '码头 / 车间摄像头分屏监控，AI 框选异常并联动告警', installs: '1.6k', price: 0, icon: '监', color: '#5b6fb8' },
  { id: 'alarm-center', name: '风险预警中心', cat: 'monitor', author: '总控中心', desc: '天气海况 / 设备 / 冷链预警聚合、分级与一键派单', installs: '1.2k', price: 0, icon: '警', color: '#5b6fb8' },

  /* 看板 */
  { id: 'prod-board', name: '产销数据看板', cat: 'board', author: '总控中心', desc: '订单 / 货源 / 产能 / 物流 KPI 实时大屏', installs: '2.3k', price: 0, icon: '看', color: '#4a7a8c' },
  { id: 'energy-board', name: '冷链温控驾驶舱', cat: 'board', author: '仓储物流', desc: '冷库 / 冷链车厢温实时曲线与越限提醒', installs: '880', price: 19.9, icon: '温', color: '#4a7a8c' },

  /* 协作 */
  { id: 'whiteboard', name: '协作白板', cat: 'collab', author: '第三方', desc: '多人实时白板，画流程图、方案部署', installs: '780', price: 19.9, icon: '板', color: '#6b8e4e' },
  { id: 'calendar', name: '出海排班日历', cat: 'collab', author: 'GuDuu 官方', desc: '渔船排班 / 出塘计划，与频道联动提醒', installs: '1.0k', price: 0, icon: '历', color: '#6b8e4e' },

  /* 流程 */
  { id: 'e-sign', name: '电子签批', cat: 'flow', author: 'GuDuu 官方', desc: '出海审批 / 出塘报备在侧栏一键签批留痕', installs: '1.1k', price: 29, icon: '签', color: '#b58932' },
  { id: 'work-order', name: '工单中心', cat: 'flow', author: '总控中心', desc: '设备检修 / 异常处置工单的创建、派发与跟踪', installs: '940', price: 0, icon: '单', color: '#b58932' }
]
