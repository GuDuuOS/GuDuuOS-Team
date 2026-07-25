<script setup lang="ts">
/**
 * 统一图标组件 —— 全项目 UI 图标出口(替代此前散落的彩色 emoji)。
 *
 * 为什么这么做(负责人拍板换成 Lucide 线性图标):
 *  - emoji 各平台/系统渲染不一致、大小色彩不可控(之前出现过"同排图标大小不一");
 *  - 线性图标单色、继承文字颜色(currentColor),深色模式自动适配,还能按状态染色;
 *  - 统一从这里出:模板里只写 <Icon name="settings" />,图标源(Lucide)与命名集中管理,
 *    以后换图标/加图标只改这一个文件。
 *
 * 用法:<Icon name="settings" />、<Icon name="logout" :size="16" />
 * 底层用 lucide-vue-next(tree-shake,只打包这里 import 的图标)。
 */
import { computed } from 'vue'
import {
  LayoutDashboard, ClipboardList, Newspaper, Users, UsersRound, Star,
  Clapperboard, Search, Settings, CircleUser, Drama, TrendingUp, Lock,
  ShieldCheck, Bell, LogOut, Plus, Bot, Archive, Wrench, Scale, Workflow,
  LayoutTemplate, Library, FileText, Plug, Puzzle, CreditCard, Crown,
  Store, Globe, SquarePen, X, Pin, Brain, Clock, Flame, Zap, Music, Image,
  Tv, Smartphone, Camera, Sparkles, Check, RefreshCw, ChevronRight,
  ChevronDown, Upload, Download, Trash2, Link, Folder, MessageSquare,
  ChartColumnBig, KeyRound, Rocket, Hash, Building2, Palette, Eye,
  House, Calendar, Inbox,
} from 'lucide-vue-next'

// 语义名 → Lucide 组件。命名按"这个图标在产品里代表什么"取,不按图形取,
// 换图标时只改右侧、模板不动。
const MAP: Record<string, any> = {
  dashboard: LayoutDashboard,   // 数据看板
  tasks: ClipboardList,         // 任务看板
  tutorial: Newspaper,          // 图文教程
  org: Users,                   // 组织/人事
  people: UsersRound,           // 人员能力/协作人
  star: Star,                   // 收藏
  film: Clapperboard,           // 影视类频道
  search: Search,               // 搜索
  settings: Settings,           // 管理后台/设置
  profile: CircleUser,          // 个人资料
  studio: Drama,                // 我的AI工坊/智能体
  usage: TrendingUp,            // 用量/额度
  lock: Lock,                   // 我的权限(账号级)
  gating: ShieldCheck,          // 会员权限/门控
  bell: Bell,                   // 通知/数据调用授权
  logout: LogOut,               // 退出登录
  plus: Plus,                   // 新建/添加
  bot: Bot,                     // 中枢 AI / AI 配置
  archive: Archive,             // 归档记录
  skills: Wrench,               // 技能库
  rules: Scale,                 // 规则
  workflow: Workflow,           // 工作流
  templates: LayoutTemplate,    // 入驻模板
  knowledge: Library,           // 知识库
  pages: FileText,              // 页面内容/文档
  plug: Plug,                   // 连接器
  puzzle: Puzzle,               // 插件
  plan: CreditCard,             // 会员套餐
  members: Crown,               // 会员等级
  marketplace: Store,           // 市场/商城
  web: Globe,                   // 网络/公开
  edit: SquarePen,              // 编辑
  close: X,                     // 关闭
  pin: Pin,                     // 置顶
  memory: Brain,                // 记忆
  clock: Clock,                 // 时间
  flame: Flame,                 // 热门
  zap: Zap,                     // 快捷/闪电
  music: Music,                 // 音频
  image: Image,                 // 图片
  video: Tv,                    // 视频
  phone: Smartphone,            // 移动端
  camera: Camera,               // 拍摄
  sparkle: Sparkles,            // 升级/AI 亮点
  check: Check,                 // 勾选/完成
  refresh: RefreshCw,           // 刷新
  'chevron-right': ChevronRight,
  'chevron-down': ChevronDown,
  upload: Upload,
  download: Download,
  trash: Trash2,                // 删除
  link: Link,
  folder: Folder,               // 项目/全部项目
  message: MessageSquare,       // 会话/私信
  data: ChartColumnBig,         // 数据统计
  key: KeyRound,                // 密钥/授权码
  rocket: Rocket,               // 上线/启动
  hash: Hash,                   // 频道
  building: Building2,          // 工作区/组织
  palette: Palette,             // 皮肤/主题
  eye: Eye,                     // 查看
  home: House,                  // 个人主页
  calendar: Calendar,           // 截止日期
  inbox: Inbox,                 // 待办空态
}

const props = withDefaults(defineProps<{
  name: string
  size?: number | string
  strokeWidth?: number | string
}>(), { size: 18, strokeWidth: 2 })

// 找不到的名字兜底成 puzzle(不至于渲染空白/报错),开发期能一眼看出漏配了映射。
const comp = computed(() => MAP[props.name] || Puzzle)
</script>

<template>
  <!-- 线性图标继承 currentColor:随文字颜色走,深色模式与状态染色自动生效 -->
  <component :is="comp" :size="Number(size)" :stroke-width="Number(strokeWidth)" class="app-icon" />
</template>

<style scoped>
/* 与文字基线对齐,避免图标偏上/偏下;不设颜色(继承 currentColor) */
.app-icon { display: inline-block; vertical-align: -0.15em; flex-shrink: 0; }
</style>
