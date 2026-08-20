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

/* ── دادهٔ اختصاصیِ هر صفحه ─────────────────────────────────────── */

export interface PageState<T> {
  status: 'loading' | 'ready' | 'error'
  data: T | null
  error: string | null
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

/**
 * دادهٔ یک **صفحه**.
 *
 * جدا از `useConsoleData` است چون دامنه‌شان فرق دارد: پیلودِ مشترک روی هر
 * صفحه لازم است (نوارِ اعداد، مشِ ریل)، ولی دادهٔ STRINGS را فقط STRINGS
 * می‌خواهد. همان قاعدهٔ «هیچ سقوطِ بی‌صدا» این‌جا هم برقرار است — `data`ی
 * `null` یعنی صفحه باید حالتِ خودش را نشان بدهد، نه دادهٔ نمایشی.
 */
export function usePageData<T>(page: string, query = ''): PageState<T> {
  const [state, setState] = useState<PageState<T>>({ status: 'loading', data: null, error: null })

  useEffect(() => {
    let alive = true
    setState({ status: 'loading', data: null, error: null })
    const ctl = new AbortController()

    fetch(`/api/console/${page}${query ? `?${query}` : ''}`, {
      signal: ctl.signal,
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    })
      .then(async (r) => {
        if (r.status === 401) {
          window.location.href = '/login'
          throw new Error('session expired')
        }
        if (!r.ok) throw new Error(`/api/console/${page} → HTTP ${r.status}`)
        return (await r.json()) as T
      })
      .then((data) => {
        if (alive) setState({ status: 'ready', data, error: null })
      })
      .catch((e: unknown) => {
        if (!alive || (e instanceof DOMException && e.name === 'AbortError')) return
        setState({
          status: 'error',
          data: null,
          error: e instanceof Error ? e.message : String(e),
        })
      })

    return () => {
      alive = false
      ctl.abort()
    }
  }, [page, query])

  return state
}

/* شکلِ دادهٔ هر صفحه — آینهٔ `_page_*` در `admin_web.py`. */

export interface UsersPage {
  total: number
  blocked: number
  page: number
  pages: number
  q: string
  rows: {
    /** کلیدِ اصلیِ ردیف — چیزی که `/users/block` می‌خواهد، نه `tg`. */
    id: number
    tg: string
    role: string
    files: number
    created: string
    seen: string
    blocked: boolean
    admin: boolean
  }[]
}

export interface CookieAccount {
  file: string
  label: string
  status: string
  used: number
  cap: number
  lastOk: string
  err: string
  warming: boolean
  cooldown: number
}

export interface CookiesPage {
  groups: { platform: string; accounts: CookieAccount[] }[]
  /** سطل‌هایی که فرمِ افزودن می‌سازد — نه فقط آن‌هایی که پر شده‌اند. */
  platforms: string[]
  unstocked: string[]
  attention: string[]
}

export interface NodesPage {
  rows: { id: string; name: string; role: string; ip: string; up: boolean; jobs: number; done: number; ver: string }[]
  roles: string[]
  reaped: number
  master_ready: boolean
  wg: { subnet: string; master: string }
}

export interface HealthPage {
  health: {
    postgres: boolean
    redis: boolean
    pot: boolean | string | null
    disk_total: number
    disk_used: number
    disk_pct: number
    engines: { who?: string; ytdlp?: string; gallerydl?: string }[]
  }
  hosts: { name: string; ok: number; fail: number; rate: number }[]
  pool: { platform: string; live: number; cd: number; bad: number; total: number }[]
  /** جابی که از هر `job_timeout`ی پیرتر است و هنوز تمام نشده. */
  stuck: { id: number; op: string; status: string; age: string; file: string }[]
  stuckAfter: number
}

export interface SettingsPage {
  total: number
  groups: {
    title: string
    rows: { key: string; val: string; def: string; kind: string; enum: string[] | null; note: string; long: boolean }[]
  }[]
}

export interface StringsPage {
  lang: string
  langs: { code: string; name: string }[]
  q: string
  total: number
  edited: number
  groups: {
    title: string
    n: number
    edited: number
    /** باز یا بسته — از `_texts_groups`، نه یک قاعدهٔ کلاینتی. */
    open: boolean
    rows: { key: string; val: string; def: string; overridden: boolean }[]
  }[]
}

export interface KeyboardPage {
  kind: string
  kinds: { key: string; label: string }[]
  lang: string
  langs: { code: string; name: string }[]
  items: { op: string; text: string; style: string; icon: string; width: string }[]
  /** بسته‌بندیِ ردیف از خودِ `keyboards._rows_from_widths` — نه یک کپیِ JS. */
  rows: number[]
  hidden: { op: string; text: string }[]
  closeLabel: string
  styleHex: Record<string, string>
  /** عرض→ظرفیتِ ردیف، از `keyboards._WIDTH_CAP` — نه یک کپیِ JS. */
  widthCap: Record<string, number>
  widths: string[]
  styles: string[]
}

export interface LangsPage {
  total: number
  rows: { code: string; name: string; builtin: boolean; keys: number; total: number; users: number }[]
}

export interface TrafficPage {
  range: string
  files: number
  dl_files: number
  users_new: number
  users_active: number
  users_blocked: number
  ops: number
  done: number
  err: number
  queued: number
  success_rate: number | null
  storage_h: string
  media_h: string
  avg_op_h: string
  src_up_pct: number
  cache_rows: number
  cache_hits: number
  cache_saved_h: string
  by_kind: Bar[]
  by_op: Bar[]
  by_ext: Bar[]
  by_size: Bar[]
  by_res: Bar[]
  by_lang: Bar[]
  by_platform: Bar[]
  op_perf: { op: string; n: number; rate: number | null; bad: number; avg: string; p95: string }[]
  errors: { msg: string; n: number }[]
  top_users: { tg: number; files: number; size: string }[]
}

export interface Bar {
  key: string
  k: string
  n: number
  pct: number
}
