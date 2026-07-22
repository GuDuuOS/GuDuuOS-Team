import { reactive, ref } from 'vue'
import { workspaceDataMap } from '@/data/channels'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import type { ChannelItem } from '@/types/channel'

export type CliTab = 'cloud' | 'local'
export type CloudStatus = 'idle' | 'installing' | 'installed'
export interface CloudApp {
  key: string
  name: string
  initial: string
  color: string
  /** 安装后是否在 GuDuu 建立消息桥接频道 */
  bridge?: boolean
  status: CloudStatus
}

export type CliLineType = 'in' | 'out' | 'ok' | 'sys' | 'err'
export interface CliLine { type: CliLineType; text: string }

const visible = ref(false)
const tab = ref<CliTab>('cloud')

/* ===== 界面一：云端应用（安装在云端电脑，装好即用）===== */
const cloudApps = reactive<CloudApp[]>([
  { key: 'wecom',    name: '企业微信',     initial: '企',  color: '#2f9e44', bridge: true, status: 'idle' },
  { key: 'dingtalk', name: '钉钉',         initial: '钉',  color: '#1677ff', bridge: true, status: 'idle' },
  { key: 'feishu',   name: '飞书',         initial: '飞',  color: '#3370ff', bridge: true, status: 'idle' },
  { key: 'email',    name: '邮件',         initial: '@',   color: '#d9480f', bridge: true, status: 'idle' },
  { key: 'slack',    name: 'Slack',        initial: '#',   color: '#4a154b', bridge: true, status: 'idle' },
  { key: 'teams',    name: 'Teams',        initial: 'T',   color: '#5059c9', bridge: true, status: 'idle' },

  { key: 'office',   name: 'Office',       initial: 'O',   color: '#c43e1c', status: 'idle' },
  { key: 'wps',      name: 'WPS Office',   initial: 'W',   color: '#d9480f', status: 'idle' },
  { key: 'tdocs',    name: '腾讯文档',     initial: '文',  color: '#2f9e44', status: 'idle' },
  { key: 'chrome',   name: '浏览器',       initial: 'C',   color: '#4a7a8c', status: 'idle' },
  { key: 'meeting',  name: '腾讯会议',     initial: '会',  color: '#2d8cf0', status: 'idle' },
  { key: 'drive',    name: '企业网盘',     initial: '盘',  color: '#4a7a8c', status: 'idle' },

  { key: 'python',   name: 'Python 环境',  initial: 'Py',  color: '#3776ab', status: 'idle' },
  { key: 'jupyter',  name: 'Jupyter',      initial: 'Jp',  color: '#e8702a', status: 'idle' },
  { key: 'node',     name: 'Node.js',      initial: 'N',   color: '#3c873a', status: 'idle' },
  { key: 'docker',   name: 'Docker',       initial: 'Dk',  color: '#1d63ed', status: 'idle' },
  { key: 'vscode',   name: 'VS Code',      initial: '<>',  color: '#1f6feb', status: 'idle' },
  { key: 'db',       name: '数据库客户端', initial: 'DB',  color: '#6b8e4e', status: 'idle' },
  { key: 'bi',       name: 'BI 报表',      initial: 'BI',  color: '#b58932', status: 'idle' },

  { key: 'sap',      name: 'SAP ERP',      initial: 'SAP', color: '#0a6ed1', status: 'idle' },
  { key: 'crm',      name: 'CRM 系统',     initial: 'CRM', color: '#6b8e4e', status: 'idle' },
  { key: 'dw',       name: '数据仓库',     initial: 'DW',  color: '#005f9e', status: 'idle' },
  { key: 'api',      name: 'API 网关',     initial: 'API', color: '#cc4125', status: 'idle' },
  { key: 'rpa',      name: 'RPA 自动化',   initial: 'RPA', color: '#e16737', status: 'idle' },
  { key: 'design',   name: '设计工具',     initial: 'PS',  color: '#8a6a8a', status: 'idle' }
])

const { activeId } = useActiveWorkspace()

function addBridgeChannel(app: CloudApp) {
  const ws = workspaceDataMap[activeId.value] ?? workspaceDataMap['hq']
  const id = 'bridge-' + app.key
  if (!ws.channels.some((c) => c.id === id)) {
    const ch: ChannelItem = { id, label: `${app.name}-接入`, routeName: 'ops', routeParams: { id }, visibility: 'public', emphasized: true }
    ws.channels.push(ch)
  }
}

function installCloud(app: CloudApp) {
  if (app.status === 'installing') return
  if (app.status === 'installed') return
  app.status = 'installing'
  // 模拟云端电脑安装
  setTimeout(() => {
    app.status = 'installed'
    if (app.bridge) addBridgeChannel(app)
  }, 1400)
}

/* ===== 界面二：本地连接（终端，连接本地电脑）===== */
const lines = reactive<CliLine[]>([])
const localConnected = ref(false)

/** 本地连接面板右侧的快捷操作 */
export interface LocalShortcut { label: string; cmd: string }
export const localShortcuts: LocalShortcut[] = [
  { label: '连接本地电脑', cmd: 'connect' },
  { label: '浏览本地文件', cmd: 'ls' },
  { label: '打开本地终端', cmd: 'shell' },
  { label: '调用本地浏览器', cmd: 'browser' },
  { label: '屏幕截图', cmd: 'screenshot' },
  { label: '连接状态', cmd: 'status' }
]

function out(type: CliLineType, text: string) { lines.push({ type, text }) }
function welcome() {
  if (lines.length) return
  out('sys', 'GuDuu CLI — 本地连接')
  out('sys', '安装本地 Agent 后，GuDuu 可访问本地电脑的文件 / 应用 / 终端')
  out('sys', '输入 connect 连接本地电脑，help 查看命令')
}

function run(raw: string) {
  const text = raw.trim()
  if (!text) return
  out('in', text)
  const cmd = text.split(/\s+/)[0].toLowerCase()
  switch (cmd) {
    case 'help':
      out('out', '  connect        连接本地电脑（安装本地 Agent）')
      out('out', '  ls             列出本地文件')
      out('out', '  shell          打开本地终端会话')
      out('out', '  browser        调用本地浏览器')
      out('out', '  screenshot     截取本地屏幕')
      out('out', '  status         查看连接状态')
      out('out', '  disconnect     断开本地连接')
      out('out', '  clear          清屏')
      break
    case 'connect':
      if (localConnected.value) { out('out', '本地电脑已连接'); break }
      out('ok', '✓ 已安装本地 Agent (macOS)')
      out('ok', '✓ 建立端到端安全隧道')
      out('ok', '✓ 已连接本地电脑：GD-PC-01')
      out('sys', '— 可用能力 —')
      out('out', '· 读写本地文件 / 文件夹')
      out('out', '· 调用本地应用与浏览器')
      out('out', '· 执行本地命令（需逐次授权）')
      out('ok', '本地连接就绪，主 AI 现可操作本机。')
      localConnected.value = true
      break
    case 'ls':
      if (!localConnected.value) { out('err', '请先 connect 连接本地电脑'); break }
      ;['~/Documents/工作报表/', '~/Downloads/项目文档/', '~/Desktop/会议纪要.xlsx', '~/操作手册.pdf'].forEach((f) => out('out', '  ' + f))
      break
    case 'shell':
      if (!localConnected.value) { out('err', '请先 connect 连接本地电脑'); break }
      out('ok', '✓ 已打开本地终端会话 (zsh @ GD-PC-01)')
      out('out', '· 主 AI 可执行本地命令，每次执行前需你授权')
      break
    case 'browser':
      if (!localConnected.value) { out('err', '请先 connect 连接本地电脑'); break }
      out('ok', '✓ 已调起本地浏览器 Chrome')
      out('out', '· 主 AI 可代你浏览网页 / 填表 / 取数')
      break
    case 'screenshot':
      if (!localConnected.value) { out('err', '请先 connect 连接本地电脑'); break }
      out('ok', '✓ 已截取当前屏幕并回传 GuDuu')
      out('out', '  screen_2026-05-24_1530.png')
      break
    case 'status':
      out('out', localConnected.value ? '● 本地电脑 GD-PC-01 已连接' : '○ 未连接，使用 connect 连接')
      break
    case 'disconnect':
      localConnected.value = false
      out('ok', '已断开本地电脑')
      break
    case 'clear':
      lines.splice(0, lines.length)
      welcome()
      break
    default:
      out('err', `未知命令：${cmd}（输入 help）`)
  }
}

export function useCli() {
  return {
    visible,
    tab,
    cloudApps,
    lines,
    localConnected,
    installCloud,
    run,
    open: () => { welcome(); visible.value = true },
    close: () => { visible.value = false }
  }
}
