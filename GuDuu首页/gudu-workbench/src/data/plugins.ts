export interface PluginItem {
  id: string
  /** 1 字 / emoji 简标识（image 为空时回退）*/
  label: string
  /** 鼠标悬浮 tooltip */
  title: string
  /** 头像图片路径（放在 public/ 下，例如 '/ai-assistant.png'）*/
  image?: string
  /** 圆形图标底色（无 image 时生效，用于商城获取的 Agent）*/
  color?: string
}

/** 顶部插件列表 */
export const plugins: PluginItem[] = [
  {
    id: 'ai',
    label: 'AI',
    title: 'AI 助手',
    image: '/gudu-logo.svg'
  }
]
