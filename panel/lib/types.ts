/** شکلِ داده‌ای که کنسول می‌خورد — همان چیزی که `/api/console` باید بدهد. */

export type Range = 'TODAY' | '7D' | '30D'

export interface Kpi {
  label: string
  value: string
  unit: string
  delta: string
  up: boolean
  foot: string
  tag: string
  /** بذرِ اسپارک‌لاین؛ خروجیِ ثابت به‌ازای ورودیِ ثابت، پس رندرِ سرور و کلاینت یکی است. */
  seed: number
}

export interface RangeData {
  kpis: Kpi[]
  /** تعدادِ ستون‌های نمودارِ گذردهی. */
  n: number
  /** مقیاسِ پایهٔ ستون‌ها. */
  base: number
  /** برچسبِ محورِ افقی. */
  label: (i: number, n: number) => string
}

export interface Platform {
  name: string
  n: number
  ok: number
}

export interface Job {
  tag: string
  user: string
  msg: string
  size: string
  node: string
  sev: 'INFO' | 'WARN' | 'ERR'
}

export type JobState = 'RUN' | 'DONE' | 'WAIT' | 'FAIL'

export interface LogRow {
  j: Job
  pct: number
  st: JobState
}

export interface ErrRow {
  n: number
  msg: string
  host: string
}

export interface AuditRow {
  t: string
  who: string
  act: string
  val: string
}

export interface FlagRow {
  name: string
  meta: string
  flag: string
  color: string
}

export interface Gauge {
  on: string
  off: string
}
