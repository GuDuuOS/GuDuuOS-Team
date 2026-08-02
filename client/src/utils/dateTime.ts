/**
 * 把服务端时间转换为浏览器/操作系统所在时区的可读文本。
 *
 * 新版 API 会返回带 `Z` 或偏移量的 ISO 8601；兼容旧版时，数据库的 naive 字符串实际
 * 也是 UTC，因此缺少时区后缀时要主动补 `Z`。不能固定加八小时，否则海外用户仍会错。
 *
 * @param value 服务端时间，例如 `2026-07-27T02:34:37Z`。
 * @returns 按用户系统区域与时区格式化的文本；空值返回空串，非法值保留原文便于排查。
 */
export function formatServerDateTime(value: string | null | undefined): string {
  const raw = String(value || '').trim()
  if (!raw) return ''

  // ISO 尾部已有 Z 或 ±hh:mm 时不改；历史流水没有后缀，但按后端约定实际保存的是 UTC。
  const hasTimeZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const parsed = new Date(hasTimeZone ? raw : `${raw}Z`)
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString()
}
