import { ref, reactive, computed } from 'vue'
import { myPeopleList, myPeopleAdd, myPeopleDelete, listMyContacts, normalizeUserId, type MyPerson } from '@/matrix/client'
import { useToast } from '@/composables/useToast'

/**
 * 「我的协作人」能力名册（模块3.5：普通用户在前台维护）。
 *
 * 直接**同步我的联系人**（跟我共享房间/私信的人 = 已加的朋友），不用单独敲 id；
 * 用户只给联系人补"擅长什么"。能力备注存 cosmac DB（按本人隔离，后端 owner=本人）。
 * 主 AI 给本人拆任务时把 admin 全局名册 + 这份合并、据此派单。模块级单例。
 */

const visible = ref(false)
const profiles = ref<MyPerson[]>([])           // 已填的能力备注（cosmac_person）
const contacts = ref<{ id: string; name: string }[]>([])  // 我的联系人
const loading = ref(false)
const busy = ref(false)
const editing = ref(false)
const adding = ref(false)   // true=手动添加新人(user_id 可编辑)；false=给已有联系人设能力(user_id 固定)
const errText = ref('')     // 保存失败的内联提示(会员门槛这类要"去做别的事"的错误,toast 一闪即逝不够)
const form = reactive<MyPerson>({ user_id: '', name: '', role: '', expertise: '', note: '', enabled: true })

export function useMyPeople() {
  const { success, warn } = useToast()

  async function load() {
    loading.value = true
    try {
      profiles.value = await myPeopleList()
      contacts.value = listMyContacts()
    } finally { loading.value = false }
  }

  function open() { visible.value = true; editing.value = false; load() }
  function close() { visible.value = false; editing.value = false }

  // user_id → 能力备注
  const profileMap = computed(() => {
    const m: Record<string, MyPerson> = {}
    for (const p of profiles.value) m[p.user_id] = p
    return m
  })
  // 表格行 = 我的联系人 + 叠加能力；已填能力但已不在联系人里的也补进来（避免"看不到已填的"）
  const rows = computed(() => {
    const byId = new Map<string, { id: string; name: string }>()
    for (const c of contacts.value) byId.set(c.id, c)
    for (const p of profiles.value) if (!byId.has(p.user_id)) byId.set(p.user_id, { id: p.user_id, name: p.name || p.user_id })
    return Array.from(byId.values()).map((c) => {
      const p = profileMap.value[c.id]
      return {
        id: c.id,
        name: p?.name || c.name || c.id,
        role: p?.role || '',
        expertise: p?.expertise || '',
        enabled: p ? p.enabled : true,
        hasProfile: !!p,
        isGlobal: p?.source === 'global',  // 管理员后台设的平台预设(用户保存即覆盖为个人记录)
      }
    })
  })

  function startEdit(r: { id: string; name: string }) {
    const ex = profileMap.value[r.id]
    Object.assign(form, {
      user_id: r.id,
      name: ex?.name || r.name || '',
      role: ex?.role || '',
      expertise: ex?.expertise || '',
      note: ex?.note || '',
      enabled: ex ? ex.enabled : true,
    })
    adding.value = false
    editing.value = true
    errText.value = ''
  }

  // 手动添加一个还不是联系人的新人（user_id 可编辑）
  function startAdd() {
    Object.assign(form, { user_id: '', name: '', role: '', expertise: '', note: '', enabled: true })
    adding.value = true
    editing.value = true
    errText.value = ''
  }

  async function save() {
    if (busy.value) return
    // 新增模式：容错规范化 user_id（@bob / bob 都补成 @bob:本服务器）；已有联系人则 user_id 固定
    const pid = adding.value ? normalizeUserId(form.user_id) : form.user_id
    if (!pid || !pid.includes(':')) { warn('请填写用户名（如 bob 或 @bob:cosmac.cc）'); return }
    busy.value = true
    errText.value = ''
    try {
      await myPeopleAdd({
        person_id: pid, name: form.name.trim(), role: form.role.trim(),
        expertise: form.expertise.trim(), note: form.note.trim(), enabled: form.enabled,
      })
      editing.value = false
      await load()
      success('已保存能力')
    } catch (e: any) {
      // 弹 toast + 表单内联双提示:403 会员门槛这类要引导用户去升级,内联的不会一闪而过
      errText.value = e?.message || '保存失败'
      warn(e?.message || '保存失败')
    } finally { busy.value = false }
  }

  async function remove(personId: string) {
    if (busy.value) return
    if (!confirm('清除 TA 的能力备注？（不影响联系人关系）')) return
    busy.value = true
    try { await myPeopleDelete(personId); await load(); success('已清除') }
    catch (e: any) { warn(e?.message || '删除失败') }
    finally { busy.value = false }
  }

  return { visible, rows, loading, busy, editing, adding, errText, form, open, close, load, startEdit, startAdd, save, remove }
}
