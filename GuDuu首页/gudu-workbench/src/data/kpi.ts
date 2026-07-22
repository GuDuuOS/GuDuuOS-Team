export interface KpiCardData {
  label: string
  /** 目标值（数字滚动到此） */
  target: number
  unit: string
  delta: string
}

export interface UnitStatus {
  name: string
  status: string
  warn?: boolean
}
