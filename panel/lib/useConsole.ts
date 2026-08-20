'use client'

/**
 * حلقهٔ زندهٔ کنسول — پورتِ کلاسِ `Component` طرح به هوک.
 *
 * دو تایمر، دقیقاً مثلِ طرح: یکی ثانیه‌شمار (۱ ثانیه) و یکی ضربانِ داده
 * (۳ ثانیه). **هیچ‌کدام تا mount شروع نمی‌شوند**، و حالتِ اولیه هم کاملاً
 * قطعی است — وگرنه خروجیِ استاتیک با اولین رندرِ کلاینت فرق می‌کرد و React
 * هشدارِ hydration می‌داد. ساعتِ صفحه هم عمداً از `sec` ساخته می‌شود نه از
 * `Date`، به همان دلیل.
 */
import { useEffect, useMemo, useState } from 'react'
import { C } from './theme'
import { hueOf } from './zones'
import {
  AUDIT, DATA, DAYS, ERRORS, JOB_POOL, PLATFORMS, RANGES,
  bigRows, fmt, gauge, hex, noise, pad2, rainColumns, spark,
} from './data'
import type { ErrRow, FlagRow, LogRow, Range } from './types'

const INITIAL_PCT = [68, 41, 84, 100, 100, 0, 100, 22, 55]
const INITIAL_ST: LogRow['st'][] = ['RUN', 'RUN', 'RUN', 'DONE', 'DONE', 'WAIT', 'FAIL', 'RUN', 'RUN']

export interface ConsoleOptions {
  defaultRange?: Range
  liveStream?: boolean
  scanlines?: boolean
}

export function useConsole(opts: ConsoleOptions = {}) {
  const { defaultRange = '7D', liveStream = true, scanlines = true } = opts

  const [range, setRange] = useState<Range>(RANGES.includes(defaultRange) ? defaultRange : '7D')
  const [hover, setHover] = useState<number | null>(null)
  const [sec, setSec] = useState(0)
  const [tick, setTick] = useState(0)
  const [queues, setQueues] = useState({ main: 7, proc: 3, dl: 12, active: 5 })
  const [load, setLoad] = useState(62)
  const [mem, setMem] = useState(36)
  const [net, setNet] = useState(48)
  const [logs, setLogs] = useState<LogRow[]>(() =>
    JOB_POOL.slice(0, 9).map((j, i) => ({ j, pct: INITIAL_PCT[i], st: INITIAL_ST[i] })),
  )

  useEffect(() => {
    const c = setInterval(() => setSec((s) => s + 1), 1000)
    return () => clearInterval(c)
  }, [])

  useEffect(() => {
    if (!liveStream) return
    const step = (v: number, lo: number, hi: number, amp = 4) =>
      Math.max(lo, Math.min(hi, v + Math.round((Math.random() - 0.5) * amp)))

    const t = setInterval(() => {
      setTick((x) => x + 1)
      setLogs((prev) => {
        const bumped = prev.map((l) =>
          l.st === 'RUN' ? { ...l, pct: Math.min(100, l.pct + 4 + Math.round(Math.random() * 9)) } : l,
        )
        const settled = bumped.map((l) =>
          l.st === 'RUN' && l.pct >= 100 ? { ...l, st: (Math.random() > 0.12 ? 'DONE' : 'FAIL') as LogRow['st'] } : l,
        )
        if (Math.random() > 0.35) {
          settled.unshift({
            j: JOB_POOL[Math.floor(Math.random() * JOB_POOL.length)],
            pct: 2 + Math.round(Math.random() * 14),
            st: 'RUN',
          })
          settled.pop()
        }
        return settled
      })
      setLoad((v) => step(v, 38, 94, 9))
      setMem((v) => step(v, 24, 78, 6))
      setNet((v) => step(v, 12, 96, 14))
      setQueues((q) => ({
        main: step(q.main, 0, 22),
        proc: step(q.proc, 0, 14),
        dl: step(q.dl, 0, 30),
        active: step(q.active, 0, 9),
      }))
    }, 3000)
    return () => clearInterval(t)
  }, [liveStream])

  const vals = useMemo(() => {
    const cfg = DATA[range]

    /* ── KPI ─────────────────────────────────────────────── */
    const kpis = cfg.kpis.map((k) => ({
      ...k,
      spark: spark(k.seed, 24),
      dc: k.up ? C.acc : C.bad,
      db: k.up ? C.edgeChip : '#3A1E1E',
    }))

    /* ── نمودارِ گذردهی ───────────────────────────────────── */
    const raw: { f: number; o: number; e: number }[] = []
    for (let i = 0; i < cfg.n; i++) {
      const f = Math.round(cfg.base * (0.55 + noise(cfg.n, i) * 0.65))
      raw.push({
        f,
        o: Math.round(f * (0.5 + noise(cfg.n + 9, i) * 0.5)),
        e: Math.round(f * (0.02 + noise(cfg.n + 21, i) * 0.06)),
      })
    }
    const max = Math.max(...raw.map((r) => r.f))
    const avg = Math.round(raw.reduce((t, r) => t + r.f, 0) / raw.length)
    const trend = raw.map((r, i) => ({
      fh: Math.max(3, Math.round((r.f / max) * 172)),
      oh: Math.max(3, Math.round((r.o / max) * 172)),
      eh: Math.max(2, Math.round((r.e / max) * 172)),
      label: cfg.label(i, cfg.n),
      tip: `files ${r.f} · ops ${r.o} · err ${r.e}`,
    }))

    /* ── رادار ───────────────────────────────────────────── */
    const rMax = PLATFORMS[0].n
    const total = PLATFORMS.reduce((t, p) => t + p.n, 0)
    const prevPts: string[] = []
    const radar = PLATFORMS.map((p, i) => {
      const ang = -Math.PI / 2 + (i * 2 * Math.PI) / PLATFORMS.length
      const cos = Math.cos(ang)
      const sin = Math.sin(ang)
      const rr = 86 * (0.32 + 0.68 * (p.n / rMax))
      const pr = rr * (0.72 + noise(97, i) * 0.24)
      const on = hover === i
      const px = 160 + rr * cos
      const py = 128 + rr * sin
      const rs = on ? 8 : 5
      prevPts.push(`${(160 + pr * cos).toFixed(1)},${(128 + pr * sin).toFixed(1)}`)
      return {
        name: p.name,
        n: fmt(p.n),
        ax: (160 + 86 * cos).toFixed(1),
        ay: (128 + 86 * sin).toFixed(1),
        px: px.toFixed(1),
        py: py.toFixed(1),
        rx: (px - rs / 2).toFixed(1),
        ry: (py - rs / 2).toFixed(1),
        rs,
        hue: hueOf(p.name),
        dotColor: on ? C.inkHi : hueOf(p.name),
        left: (((160 + 116 * cos) / 320) * 100).toFixed(2),
        top: (((128 + 110 * sin) / 268) * 100).toFixed(2),
        fill: on ? C.inkHi : hueOf(p.name),
        chipBg: on ? 'rgba(0,229,153,.12)' : 'transparent',
        spoke: on ? 'rgba(0,229,153,.5)' : C.ringDash,
        idx: i,
      }
    })

    const ticks: { x1: string; y1: string; x2: string; y2: string; stroke: string }[] = []
    for (let i = 0; i < 36; i++) {
      const a = (i * Math.PI) / 18
      const long = i % 3 === 0
      ticks.push({
        x1: (160 + 90 * Math.cos(a)).toFixed(1),
        y1: (128 + 90 * Math.sin(a)).toFixed(1),
        x2: (160 + (long ? 97 : 93.5) * Math.cos(a)).toFixed(1),
        y2: (128 + (long ? 97 : 93.5) * Math.sin(a)).toFixed(1),
        stroke: long ? C.tickLong : C.tickShort,
      })
    }
    const hp = hover === null ? null : PLATFORMS[hover]

    /* ── جدولِ پلتفرم ─────────────────────────────────────── */
    const platformRows = PLATFORMS.map((p, pi) => ({
      name: p.name,
      n: fmt(p.n),
      spark: spark(pi * 7 + 5, 14, 0.25, 0.7, 0),
      hue: hueOf(p.name),
      ok: `${p.ok}%`,
      okColor: p.ok >= 90 ? C.acc : p.ok >= 80 ? C.warn : C.bad,
    }))

    /* ── صف و منابع ──────────────────────────────────────── */
    const q = queues
    const queueRows = [
      { label: 'proc', n: q.main, pct: (q.main / 22) * 100, color: q.main > 15 ? C.warn : C.acc },
      { label: 'node.proc', n: q.proc, pct: (q.proc / 14) * 100, color: C.acc },
      { label: 'download', n: q.dl, pct: (q.dl / 30) * 100, color: q.dl > 20 ? C.warn : C.acc },
      { label: 'dl.active', n: q.active, pct: (q.active / 9) * 100, color: C.acc },
    ].map((x) => ({ ...x, bar: gauge(x.pct, 13) }))

    const resources = [
      { label: 'cpu', pct: load, meta: `${load}%`, color: load > 85 ? C.warn : C.acc },
      { label: 'mem', pct: mem, meta: `${(11.4 + mem / 12).toFixed(1)}G`, color: C.acc },
      { label: 'net eth0', pct: net, meta: `${(net * 4.2).toFixed(0)}Mb`, color: C.info },
      { label: 'disk /work', pct: 46, meta: '412/900G', color: C.acc },
    ].map((x) => ({ ...x, bar: gauge(x.pct, 13) }))

    /* ── جریانِ جاب ───────────────────────────────────────── */
    const logRows = logs.map((l, li) => {
      const t = 45660 + sec - li * 43
      const color =
        l.st === 'RUN' ? C.acc : l.st === 'DONE' ? C.inkLo : l.st === 'WAIT' ? C.inkDim : C.bad
      const pct = l.st === 'WAIT' ? 0 : l.st === 'FAIL' ? 100 : l.pct
      const sev = l.st === 'FAIL' ? 'ERR' : l.j.sev
      return {
        key: `${li}-${l.j.tag}`,
        time: `${pad2(Math.floor(t / 3600) % 24)}:${pad2(Math.floor(t / 60) % 60)}:${pad2(t % 60)}`,
        pid: `[${2100 + ((li * 37 + tick) % 800)}]`,
        sev,
        sevColor: sev === 'ERR' ? C.bad : sev === 'WARN' ? C.warn : C.info,
        tag: l.j.tag,
        user: `uid:${l.j.user.slice(0, 5)}`,
        msg: l.j.msg,
        size: l.j.size,
        node: l.j.node,
        tagColor: l.st === 'FAIL' ? C.badSoft : C.accHi,
        bar: gauge(pct, 9),
        barColor: color,
        state: l.st === 'RUN' ? `${pct}%` : l.st,
        rowBg: li === 0 ? 'rgba(0,229,153,.045)' : 'transparent',
      }
    })

    /* ── دامپِ سیم ───────────────────────────────────────── */
    const hexlines: { addr: string; hex: string; ascii: string }[] = []
    for (let i = 0; i < 6; i++) {
      let hx = ''
      let as = ''
      for (let b = 0; b < 12; b++) {
        const v = Math.floor(noise(i * 31 + tick, b) * 255)
        hx += hex(v, 2) + ' '
        as += v > 32 && v < 127 ? String.fromCharCode(v) : '.'
      }
      hexlines.push({ addr: '0x' + hex(0x7f3a0000 + i * 12 + tick * 12, 8), hex: hx.trim(), ascii: as })
    }

    /* ── نقشهٔ فعالیت ─────────────────────────────────────── */
    const heat: { day: string; cells: { bg: string; tip: string }[] }[] = []
    for (let d = 0; d < 7; d++) {
      const cells: { bg: string; tip: string }[] = []
      for (let h = 0; h < 24; h++) {
        const day = 0.35 + 0.65 * Math.sin(((h - 4) / 24) * Math.PI)
        const v = Math.max(0, Math.min(0.999, day * (0.45 + noise(d * 17 + 11, h) * 0.85)))
        cells.push({ bg: C.heat[Math.floor(v * 5)], tip: `${DAYS[d]} ${pad2(h)}:00 · ${Math.round(v * 340)} jobs` })
      }
      heat.push({ day: DAYS[d], cells })
    }

    /* ── خطِ لولهٔ پردازش ─────────────────────────────────── */
    const pipeline = [
      { name: 'LINK IN', v: '12/min', meta: 'router', color: C.info },
      { name: 'FETCH', v: String(q.dl), meta: 'yt-dlp·gdl', color: C.acc },
      { name: '/work', v: '412G', meta: 'fs cache', color: C.violet },
      { name: 'TRANSCODE', v: String(q.main), meta: 'ffmpeg', color: C.acc },
      { name: 'DELIVER', v: '17/min', meta: 'bot-api', color: C.warn },
    ].map((p, i) => ({ ...p, step: '0' + (i + 1) }))

    const latSpark = spark(71 + tick, 16, 0.2, 0.7, 0)

    const services: FlagRow[] = [
      { name: 'postgres', meta: '4ms · 38 conn', flag: '[ OK ]', color: C.acc },
      { name: 'redis', meta: '1ms · 12k keys', flag: '[ OK ]', color: C.acc },
      { name: 'bot-api', meta: '12ms · local', flag: '[ OK ]', color: C.acc },
      { name: 'pot-provider', meta: '88ms · bgutil', flag: '[ OK ]', color: C.acc },
      { name: 'gateway', meta: 'range · 2096', flag: '[ OK ]', color: C.acc },
      { name: 'clamav', meta: 'db update', flag: '[WARN]', color: C.warn },
    ]

    const cookies: FlagRow[] = [
      { name: 'instagram_main.txt', meta: 'healthy · 412 hits', flag: '[ OK ]', color: C.acc },
      { name: 'instagram_alt.txt', meta: 'cooldown 12m', flag: '[COOL]', color: C.warn },
      { name: 'twitter_a.txt', meta: 'suspect · 3 fails', flag: '[WARN]', color: C.warn },
      { name: 'twitter_b.txt', meta: 'invalid · 401', flag: '[FAIL]', color: C.bad },
      { name: 'youtube_1.txt', meta: 'healthy · 1.2k', flag: '[ OK ]', color: C.acc },
    ]

    const nodes: FlagRow[] = [
      { name: 'dl-fra', meta: '42ms · 8 jobs', flag: '[ UP ]', color: C.acc },
      { name: 'proc-hel', meta: '31ms · 12 cores', flag: '[ UP ]', color: C.acc },
      { name: 'edge-thr', meta: 'last seen 14m', flag: '[DOWN]', color: C.bad },
    ]

    const errors: ErrRow[] = ERRORS

    return {
      range,
      ranges: RANGES,
      kpis,
      trend,
      trendPeak: fmt(max),
      trendAvg: fmt(avg),
      axis: { a: fmt(max), b: fmt(Math.round(max * 0.66)), c: fmt(Math.round(max * 0.33)) },
      radar,
      ticks,
      radarPoly: radar.map((a) => `${a.px},${a.py}`).join(' '),
      radarPrevPoly: prevPts.join(' '),
      radarFoot: hp
        ? `${hp.name} ${Math.round((hp.n / total) * 100)}% · ${fmt(hp.n)}`
        : `TOTAL ${fmt(total)}`,
      radarFootColor: hp ? C.acc : C.inkLo,
      platformRows,
      queueRows,
      resources,
      logRows,
      hexlines,
      rain: rainColumns(),
      heat,
      pipeline,
      audit: AUDIT,
      heroRows: bigRows(cfg.kpis[1].value, C.bg, 'rgba(4,7,10,.12)'),
      heroValue: cfg.kpis[1].value,
      heroSub: `${cfg.kpis[1].foot} · ${cfg.kpis[2].value}% success · peak ${fmt(max)}/d`,
      services,
      cookies,
      nodes,
      errors,
      latSpark,
      latNow: 60 + Math.round(noise(3, tick % 40) * 90),
      statusBits: [
        { k: 'QUEUE', v: String(q.main + q.dl), c: C.acc },
        { k: 'ACTIVE', v: String(q.active), c: C.acc },
        { k: 'CPU', v: `${load}%`, c: load > 85 ? C.warn : C.acc },
        { k: 'CACHE HIT', v: '91%', c: C.info },
        { k: 'ERR RATE', v: '0.31%', c: C.warn },
        { k: 'NODES', v: '2/3', c: C.bad },
      ],
      ticker:
        '▚ dl.instagram cookie rotated → instagram_alt  ▚  proc-hel picked 4 jobs  ▚  cache hit 91% (saved 41m cpu)  ▚  edge-thr offline 14m — links served from master  ▚  clamav db 27311 updating  ▚  bot-api local mode · 2GB cap  ▚',
      clock: `${pad2(12 + Math.floor((41 * 60 + sec) / 3600))}:${pad2(Math.floor(sec / 60 + 41) % 60)}:${pad2(sec % 60)}`,
      statusLine: `queue ${q.main + q.dl} · active ${q.active} · uptime 41d · ${range.toLowerCase()}`,
      scanlines,
    }
  }, [range, hover, sec, tick, queues, load, mem, net, logs, scanlines])

  return { vals, setRange, setHover }
}

export type ConsoleVals = ReturnType<typeof useConsole>['vals']
