export type Sender = {
  type: 'bot' | 'human'
  name: string
  avatar: string
  /** 头像底色（人类成员才需要） */
  color?: string
}

export type RichVariant = 'alert' | 'warn' | 'ok' | 'info'

export interface KV { k: string; v: string }

export interface ActionBtn {
  label: string
  primary?: boolean
}

export interface CCTVBox {
  label: string
  /** 百分比定位（相对 .cctv），形如 "56%" / "24%" */
  left: string
  top: string
  width: string
  height: string
}

export interface CCTVFrameData {
  timestamp: string
  camera: string
  boxes?: CCTVBox[]
}

export interface DocSection {
  title: string
  body?: string
  /** 可选表格 */
  table?: {
    headers: string[]
    rows: (string | { text: string; color?: string })[][]
  }
}

export interface DocPreviewData {
  title: string
  subtitle: string
  sections: DocSection[]
  footer?: string
  actions?: ActionBtn[]
}

export interface ChartCardData {
  /** 同一频道内唯一 */
  chartId: string
  title: string
}

export interface RichCardData {
  variant: RichVariant
  tag: string
  title: string
  meta?: string
  paragraph?: string
  kv?: KV[]
  actions?: ActionBtn[]
  cctv?: CCTVFrameData
  /** 终态标记：批准/驳回等处理后写入，按钮区变为"已处理"提示，防止重复操作 */
  handled?: string
}

export interface MessageData {
  id: string
  sender: Sender
  time: string
  /** 支持 <b> / <code> 等内联标签 */
  html?: string
  rich?: RichCardData
  doc?: DocPreviewData
  chartCard?: ChartCardData
  /** 末尾追加段落 */
  trailingHtml?: string
}

export interface DayMessages {
  daySep: string
  messages: MessageData[]
}
