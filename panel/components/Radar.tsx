'use client'

import { C } from '@/lib/theme'
import { Section } from './Section'

/**
 * رادارِ منابع — همان ماژولی که کاربر مشخصاً نامش را برد و در بازسازیِ
 * اول اصلاً ساخته نشده بود.
 *
 * هندسه دقیقاً از طرح می‌آید و هیچ‌کدام از این عددها دلخواه نیستند:
 *   • بوم `0 0 320 268`، مرکز `(160,128)`.
 *   • چهار حلقه: `r=86` توپر با `#16332C`، و `64.5/43/21.5` نقطه‌چین با
 *     `stroke-dasharray="1 6"` — یعنی نقطه، نه خط‌چین.
 *   • ۳۶ تیکِ محیطی که هر سومی بلندتر است (شعاعِ ۹۷ در برابرِ ۹۳٫۵).
 *   • دو چندضلعی: دورهٔ قبل خط‌چینِ `4 4` با سبزِ کم‌رنگ، و دورهٔ جاری
 *     پرشده با `rgba(0,229,153,.13)`.
 *   • رأس‌ها **مربع** (`<rect>`) اند نه دایره؛ روی هاور از ۵ به ۸ می‌روند.
 *   • جاروبِ چرخان یک `conic-gradient` است روی `mix-blend-mode:screen` —
 *     نه یک خطِ چرخان، وگرنه دنبالهٔ محوشونده‌اش را از دست می‌دهد.
 */
export function Radar({
  radar,
  ticks,
  poly,
  prevPoly,
  foot,
  footColor,
  onHover,
}: {
  radar: {
    idx: number
    name: string
    n: string
    ax: string
    ay: string
    rx: string
    ry: string
    rs: number
    dotColor: string
    hue: string
    left: string
    top: string
    fill: string
    chipBg: string
    spoke: string
  }[]
  ticks: { x1: string; y1: string; x2: string; y2: string; stroke: string }[]
  poly: string
  prevPoly: string
  foot: string
  footColor: string
  onHover: (i: number | null) => void
}) {
  return (
    <Section label="SOURCE RADAR" sigil="⊚" pad="22px 14px 12px">
      <div style={{ position: 'relative', maxWidth: 400, margin: '0 auto' }}>
        <svg viewBox="0 0 320 268" style={{ width: '100%', height: 'auto', display: 'block' }}>
          <circle cx="160" cy="128" r="86" fill="none" stroke={C.ringSolid} strokeWidth="1" />
          <circle cx="160" cy="128" r="64.5" fill="none" stroke={C.ringDash} strokeWidth="1" strokeDasharray="1 6" />
          <circle cx="160" cy="128" r="43" fill="none" stroke={C.ringDash} strokeWidth="1" strokeDasharray="1 6" />
          <circle cx="160" cy="128" r="21.5" fill="none" stroke={C.ringDash} strokeWidth="1" strokeDasharray="1 6" />

          {ticks.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke={t.stroke} strokeWidth="1" />
          ))}

          {radar.map((a) => (
            <line key={a.name} x1="160" y1="128" x2={a.ax} y2={a.ay} stroke={a.spoke} strokeWidth="1" />
          ))}

          {/*
            پرکردنِ چندضلعی با گرادیانِ زاویه‌ای، تا سهمِ هر پلتفرم رنگِ
            خودش را داشته باشد. `gradientUnits="userSpaceOnUse"` لازم است
            وگرنه مختصاتِ گرادیان به bounding boxِ چندضلعی نسبی می‌شود و با
            تغییرِ داده جابه‌جا می‌شود.
          */}
          <defs>
            <radialGradient id="radar-fill" gradientUnits="userSpaceOnUse" cx="160" cy="128" r="86">
              <stop offset="0%" stopColor="rgba(255,255,255,.10)" />
              <stop offset="55%" stopColor="rgba(0,229,153,.16)" />
              <stop offset="100%" stopColor="rgba(199,125,255,.10)" />
            </radialGradient>
          </defs>

          <polygon points={prevPoly} fill="none" stroke={C.accDim} strokeWidth="1" strokeDasharray="4 4" />
          <polygon points={poly} fill="url(#radar-fill)" stroke={C.acc} strokeWidth="1.5" />

          {radar.map((a) => (
            <rect
              key={a.name}
              x={a.rx}
              y={a.ry}
              width={a.rs}
              height={a.rs}
              fill={C.bg}
              stroke={a.dotColor}
              strokeWidth="1.4"
            />
          ))}

          <line x1="153" y1="128" x2="167" y2="128" stroke={C.accDim} strokeWidth="1" />
          <line x1="160" y1="121" x2="160" y2="135" stroke={C.accDim} strokeWidth="1" />
        </svg>

        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '47.8%',
            width: '53.7%',
            aspectRatio: '1',
            borderRadius: '50%',
            pointerEvents: 'none',
            mixBlendMode: 'screen',
            background:
              'conic-gradient(from 0deg,rgba(0,229,153,0) 0deg,rgba(0,229,153,0) 268deg,rgba(0,229,153,.06) 334deg,rgba(0,229,153,.34) 358deg,rgba(0,229,153,0) 360deg)',
            animation: 'mx-sweep 5s linear infinite',
            transform: 'translate(-50%,-50%)',
          }}
        />

        {radar.map((a) => (
          <div
            key={a.name}
            onMouseEnter={() => onHover(a.idx)}
            onMouseLeave={() => onHover(null)}
            style={{
              position: 'absolute',
              transform: 'translate(-50%,-50%)',
              textAlign: 'center',
              whiteSpace: 'nowrap',
              cursor: 'crosshair',
              padding: '2px 4px',
              left: `${a.left}%`,
              top: `${a.top}%`,
              background: a.chipBg,
            }}
          >
            <div style={{ fontSize: 9.5, letterSpacing: '.12em', lineHeight: 1.5, color: a.fill }}>{a.name}</div>
            <div style={{ fontSize: 9, color: C.inkDim, lineHeight: 1.4 }}>{a.n}</div>
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          borderTop: `1px solid ${C.edgeHair}`,
          marginTop: 8,
          paddingTop: 8,
          fontSize: 9.5,
          letterSpacing: '.08em',
          color: C.inkLo,
        }}
      >
        <span>
          <i
            style={{ display: 'inline-block', width: 10, borderTop: `1px solid ${C.acc}`, marginRight: 5, verticalAlign: 'middle' }}
          />
          NOW
        </span>
        <span>
          <i
            style={{ display: 'inline-block', width: 10, borderTop: `1px dashed ${C.accDim}`, marginRight: 5, verticalAlign: 'middle' }}
          />
          PREV
        </span>
        <span style={{ marginLeft: 'auto', color: footColor }}>{foot}</span>
      </div>
    </Section>
  )
}
