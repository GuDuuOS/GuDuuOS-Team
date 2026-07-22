/** 频道项可见性：公开 / 私密 */
export type ChannelVisibility = 'public' | 'private'

export interface ChannelItem {
  id: string
  label: string
  routeName: string
  /** 动态路由参数（如 { id: 'dcs-coord' }）*/
  routeParams?: Record<string, string>
  visibility?: ChannelVisibility
  unread?: number
  warn?: boolean
  /** 是否粗体加重 */
  emphasized?: boolean
}

/** 频道头里的成员堆叠头像 */
export interface StackAvatar {
  label: string
  bot?: boolean
  color?: string
}

/** Ops 场景频道的元数据（在频道头展示）*/
export interface OpsChannelMeta {
  title: string
  topic: string
  memberCount: number
  stack: StackAvatar[]
}

export interface DmItem {
  id: string
  label: string
  routeName: string
  avatar: string
  avatarColor?: string
  bot?: boolean
  online?: boolean
  unread?: number
}

export interface PinnedItem {
  id: string
  label: string
  routeName: string
  /** lucide-style 图标关键字，由 ChannelSidebar 映射成 SVG */
  icon: 'topic' | 'draft'
  badge?: number
}

export interface Member {
  name: string
  role: string
  avatar: string
  bot?: boolean
  online?: boolean
  color?: string
}
