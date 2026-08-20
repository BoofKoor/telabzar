/**
 * دادهٔ نمایشی + ریاضیِ خالصِ کنسول.
 *
 * هرچه این‌جاست **قطعی** است: `noise()` یک شبه‌تصادفِ بذرمحور است نه
 * `Math.random`، پس رندرِ سرور و اولین رندرِ کلاینت بیت‌به‌بیت یکی درمی‌آیند
 * و React خطای hydration نمی‌دهد. تنها جایی که تصادفِ واقعی هست، حلقهٔ
 * زندهٔ `useConsole` است که فقط **بعد از** mount می‌دود.
 */
import { BLOCKS, GLYPHS } from './theme'
import type { AuditRow, ErrRow, Job, Platform, Range, RangeData } from './types'

export const RANGES: Range[] = ['TODAY', '7D', '30D']

export const PLATFORMS: Platform[] = [
  { name: 'YOUTUBE', n: 18420, ok: 97 },
  { name: 'INSTAGRAM', n: 11780, ok: 88 },
  { name: 'SOUNDCLOUD', n: 5640, ok: 99 },
  { name: 'X', n: 4010, ok: 74 },
  { name: 'TIKTOK', n: 3120, ok: 93 },
  { name: 'APARAT', n: 1980, ok: 98 },
  { name: 'OTHER', n: 1090, ok: 81 },
]

export const DATA: Record<Range, RangeData> = {
  TODAY: {
    kpis: [
      { label: 'ACTIVE UID', value: '612', unit: 'users', delta: '+4.1%', up: true, foot: '83 new', tag: '24h', seed: 3 },
      { label: 'FILES', value: '3,940', unit: 'processed', delta: '+9.6%', up: true, foot: '1,210 via link', tag: 'pipe', seed: 7 },
      { label: 'SUCCESS', value: '97.2', unit: '%', delta: '+0.8', up: true, foot: '112 errors', tag: 'ops', seed: 11 },
      { label: 'EGRESS', value: '118', unit: 'GB', delta: '-2.3%', up: false, foot: 'avg 30MB', tag: 'net', seed: 5 },
    ],
    n: 24,
    base: 190,
    label: (i) => (i % 4 === 0 ? String(i).padStart(2, '0') : ''),
  },
  '7D': {
    kpis: [
      { label: 'ACTIVE UID', value: '4,182', unit: 'users', delta: '+6.4%', up: true, foot: '514 new', tag: '7d', seed: 13 },
      { label: 'FILES', value: '27,410', unit: 'processed', delta: '+12.1%', up: true, foot: '9,040 via link', tag: 'pipe', seed: 17 },
      { label: 'SUCCESS', value: '96.7', unit: '%', delta: '+1.3', up: true, foot: '904 errors', tag: 'ops', seed: 19 },
      { label: 'EGRESS', value: '812', unit: 'GB', delta: '+8.2%', up: true, foot: '310h media', tag: 'net', seed: 23 },
    ],
    n: 7,
    base: 1400,
    label: (i, n) => 'd-' + (n - 1 - i),
  },
  '30D': {
    kpis: [
      { label: 'ACTIVE UID', value: '12,880', unit: 'users', delta: '+18.5%', up: true, foot: '2,390 new', tag: '30d', seed: 29 },
      { label: 'FILES', value: '128,940', unit: 'processed', delta: '+21.4%', up: true, foot: '44,100 via link', tag: 'pipe', seed: 31 },
      { label: 'SUCCESS', value: '95.9', unit: '%', delta: '-0.4', up: false, foot: '5,280 errors', tag: 'ops', seed: 37 },
      { label: 'EGRESS', value: '3.4', unit: 'TB', delta: '+15.9%', up: true, foot: '1,240h media', tag: 'net', seed: 41 },
    ],
    n: 30,
    base: 1250,
    label: (i, n) => ((n - 1 - i) % 6 === 0 ? 'd-' + (n - 1 - i) : ''),
  },
}

export const JOB_POOL: Job[] = [
  { tag: 'COMPRESS', user: '10345298', msg: 'video 1080p → 720p · vbv crf23 maxrate 2M', size: '412MB', node: 'hel', sev: 'INFO' },
  { tag: 'WHISPER', user: '88210447', msg: 'transcribe fa+en · model=small · vad on', size: '38MB', node: 'master', sev: 'INFO' },
  { tag: 'GALLERY', user: '50219933', msg: 'instagram carousel · 7 media · cookie=main', size: '96MB', node: 'fra', sev: 'INFO' },
  { tag: 'RMBG', user: '77410028', msg: 'background removal · u2net · alpha matte', size: '6MB', node: 'hel', sev: 'INFO' },
  { tag: 'PDF', user: '21903355', msg: 'docx → pdf · libreoffice headless', size: '14MB', node: 'master', sev: 'INFO' },
  { tag: 'YTDLP', user: '64100872', msg: 'soundcloud audio · quick-grab · m4a 256k', size: '22MB', node: 'fra', sev: 'INFO' },
  { tag: 'MARK', user: '39558120', msg: 'watermark overlay · bottom-right · 40% op', size: '8MB', node: 'hel', sev: 'INFO' },
  { tag: 'OCR', user: '55120983', msg: 'tesseract fa+en · 3 pages · psm 6', size: '4MB', node: 'master', sev: 'INFO' },
  { tag: 'SCAN', user: '70023441', msg: 'clamav signature scan · daily.cvd 27311', size: '61MB', node: 'master', sev: 'WARN' },
  { tag: 'MERGE', user: '12907755', msg: 'pdf merge · 4 documents · 88 pages', size: '19MB', node: 'master', sev: 'INFO' },
  { tag: 'COBALT', user: '44810922', msg: 'extractor fallback · yt-dlp 403 → cobalt', size: '74MB', node: 'fra', sev: 'WARN' },
]

export const ERRORS: ErrRow[] = [
  { n: 41, msg: 'instagram: rate limited (429) · cookie rotated', host: 'fra' },
  { n: 18, msg: 'yt-dlp: nsig extraction failed · pot retry', host: 'fra' },
  { n: 9, msg: 'ffmpeg: moov atom not found · remux skipped', host: 'hel' },
  { n: 4, msg: 'gateway: range request aborted by peer', host: 'master' },
]

export const AUDIT: AuditRow[] = [
  { t: '12:38:02', who: 'admin', act: 'set dl_concurrency', val: '3 → 5' },
  { t: '12:22:47', who: 'admin', act: 'cookie disable', val: 'twitter_b.txt' },
  { t: '11:58:13', who: 'system', act: 'node join', val: 'proc-hel' },
  { t: '11:41:09', who: 'admin', act: 'set whisper_model', val: 'base → small' },
  { t: '10:07:55', who: 'system', act: 'wg peer sync', val: '3 peers' },
]

export const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] as const

/* ── ریاضیِ خالص ─────────────────────────────────────────────────── */

/** شبه‌تصادفِ بذرمحور. قطعی است، پس hydration امن است. */
export function noise(seed: number, i: number): number {
  const x = Math.sin((seed + 1) * 12.9898 + i * 78.233) * 43758.5453
  return x - Math.floor(x)
}

/** نوارِ متنیِ `[████░░░]` — طرح نوارها را با نویسه می‌کشد نه با DOM. */
export function gauge(pct: number, width: number) {
  const on = Math.max(0, Math.min(width, Math.round((pct / 100) * width)))
  return { on: '█'.repeat(on), off: '█'.repeat(width - on) }
}

export const pad2 = (v: number | string) => String(v).padStart(2, '0')
export const hex = (n: number, w: number) => n.toString(16).toUpperCase().padStart(w, '0')

/** اسپارک‌لاینِ نویسه‌ای — همان چیزی که در KPI و جدولِ پلتفرم دیده می‌شود. */
export function spark(seed: number, len: number, lo = 0.22, amp = 0.55, ramp = 0.22): string {
  let s = ''
  for (let i = 0; i < len; i++) {
    const v = lo + noise(seed, i) * amp + (i / (len - 1)) * ramp
    s += BLOCKS[Math.max(1, Math.min(8, Math.round(v * 8)))]
  }
  return s
}

/** ستون‌های بارشِ آنتروپی. */
export function rainColumns(cols = 7, rows = 40) {
  const out: { chars: string; dur: string }[] = []
  for (let c = 0; c < cols; c++) {
    let s = ''
    for (let i = 0; i < rows; i++) s += GLYPHS[Math.floor(noise(c * 13 + 2, i) * GLYPHS.length)] + '\n'
    out.push({ chars: s, dur: (5 + c * 1.7).toFixed(1) })
  }
  return out
}

/** فونتِ بلوکیِ ۳×۵ برای عددِ کانونیِ اسلب. */
const BIG: Record<string, string[]> = {
  '0': ['███', '█ █', '█ █', '█ █', '███'],
  '1': ['  █', '  █', '  █', '  █', '  █'],
  '2': ['███', '  █', '███', '█  ', '███'],
  '3': ['███', '  █', '███', '  █', '███'],
  '4': ['█ █', '█ █', '███', '  █', '  █'],
  '5': ['███', '█  ', '███', '  █', '███'],
  '6': ['███', '█  ', '███', '█ █', '███'],
  '7': ['███', '  █', '  █', '  █', '  █'],
  '8': ['███', '█ █', '███', '█ █', '███'],
  '9': ['███', '█ █', '███', '  █', '███'],
  ',': ['   ', '   ', '   ', '  █', ' █ '],
  '.': ['   ', '   ', '   ', '   ', '  █'],
  '%': ['█ █', '  █', ' █ ', '█  ', '█ █'],
}

/** `[{cells:[{color}]}]` — پنج ردیف، هر سلول یک `<i>` ۸×۱۳ پیکسلی. */
export function bigRows(str: string, ink: string, blank: string) {
  const rows: { cells: { color: string }[] }[] = []
  for (let r = 0; r < 5; r++) {
    const cells: { color: string }[] = []
    for (const ch of str.split('')) {
      const g = BIG[ch] ?? ['   ', '   ', '   ', '   ', '   ']
      for (const c of g[r].split('')) cells.push({ color: c === '█' ? ink : blank })
      cells.push({ color: blank })
    }
    rows.push({ cells })
  }
  return rows
}

export const fmt = (n: number) => n.toLocaleString('en-US')
