'use client'

/**
 * لایهٔ دادهٔ **واقعیِ** کنسول — `/api/console`.
 *
 * **قاعدهٔ سختِ این فایل: هیچ سقوطِ بی‌صدا به دادهٔ نمایشی.** اگر fetch
 * بیفتد، صفحه باید بلند بگوید — نه اینکه «۲۷٬۴۱۰ فایل» را نشان بدهد که
 * عددِ فیکسچر است. §۷ همین رده را ثبت کرده («fallbackی که بی‌صدا به دادهٔ
 * بی‌مصرف تنزل کند از خطا بدتر است، چون هنوز چیزی برمی‌گرداند و کسی دنبالش
 * نمی‌گردد») و در یک کنسولِ عملیاتی گران‌تر هم هست: اپراتور روی این عددها
 * تصمیم می‌گیرد.
 *
 * پس سه حالتِ **صریح** داریم و صفحه هر سه را متفاوت رندر می‌کند:
 * `loading` · `ready` (با `data`) · `error` (با علت).
 */
import { useEffect, useState } from 'react'
import type { Range } from './types'

export interface ApiKpi {
  value: number | string | null
  foot: string
}

export interface ApiFlagRow {
  name: string
  meta: string
  flag: string
}

export interface ApiNode extends ApiFlagRow {
  role: string
  ip: string
  up: boolean
  done: number
}

export interface ApiBar {
  /** کلیدِ خام (`youtube`, `instagram`, …) — مبنای رنگ و برچسبِ لاتین. */
  key: string
  /** برچسبِ فارسیِ همان کلید؛ برای رندر در `<Fa>`. */
  label: string
  n: number
  pct: number
  /** نرخِ موفقیتِ **امروز**، یا `null` اگر امروز داده‌ای نبوده. */
  ok: number | null
}

export interface ConsoleData {
  range: Range
  generated: string
  /** پنل‌هایی که منبعِ واقعی ندارند — کلید → علت. صفحه متن را نشان می‌دهد. */
  gaps: Record<string, string>
  kpis: Record<'users' | 'files' | 'success' | 'storage', ApiKpi>
  trend: { day: string; f: number; o: number; u: number }[]
  platforms: ApiBar[]
  queues: { main: number; proc: number; dl: number; active: number }
  resources: { label: string; pct: number; meta: string }[]
  services: ApiFlagRow[]
  cookies: ApiFlagRow[]
  nodes: ApiNode[]
  /** آخرین جاب‌ها از جدولِ `jobs` — **بدونِ دانلودها** (که ردیفِ Job نمی‌سازند). */
  jobs: {
    id: number
    op: string
    status: string
    error: string
    at: string
    name: string
    size: string
    uid: string
  }[]
  /** ۷×۲۴ شمارشِ فایل؛ ردیفِ ۰ = قدیمی‌ترین روز از `heatStart`. */
  heat: number[][]
  heatStart: string
  errors: { msg: string; n: number }[]
  hosts: { name: string; ok: number; fail: number; rate: number }[]
  engines: { who?: string; ytdlp?: string; gallerydl?: string }[]
}

export type ApiState =
  | { status: 'loading'; data: null; error: null }
  | { status: 'ready'; data: ConsoleData; error: null }
  | { status: 'error'; data: null; error: string }

const LOADING: ApiState = { status: 'loading', data: null, error: null }

/**
 * دادهٔ کنسول برای بازهٔ داده‌شده.
 *
 * `401` جدا از بقیهٔ خطاها هندل می‌شود چون تنها حالتی است که **کنشِ** روشنی
 * دارد: نشست تمام شده، برو به `/login`. بقیه فقط گزارش می‌شوند.
 */
export function useConsoleData(range: Range): ApiState {
  const [state, setState] = useState<ApiState>(LOADING)

  useEffect(() => {
    let alive = true
    setState(LOADING)
    const ctl = new AbortController()

    fetch(`/api/console?range=${encodeURIComponent(range)}`, {
      signal: ctl.signal,
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    })
      .then(async (r) => {
        if (r.status === 401) {
          // نشست تمام شده — تنها خطایی که کاربر می‌تواند دربارهٔ آن کاری کند.
          window.location.href = '/login'
          throw new Error('session expired')
        }
        if (!r.ok) throw new Error(`/api/console → HTTP ${r.status}`)
        return (await r.json()) as ConsoleData
      })
      .then((data) => {
        if (alive) setState({ status: 'ready', data, error: null })
      })
      .catch((e: unknown) => {
        if (!alive || (e instanceof DOMException && e.name === 'AbortError')) return
        setState({ status: 'error', data: null, error: e instanceof Error ? e.message : String(e) })
      })

    return () => {
      alive = false
      ctl.abort()
    }
  }, [range])

  return state
}
