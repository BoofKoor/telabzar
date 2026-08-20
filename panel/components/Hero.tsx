import { C } from '@/lib/theme'

/**
 * اسلبِ کانونی + کارتِ وضعیت.
 *
 * عدد یک **فرمِ رسم‌شده** است نه یک فونت‌سایزِ بزرگ: هر سلول یک `<i>`ِ
 * ۸×۱۳ پیکسلی است (مستطیل، نه مربع) با فاصلهٔ ۲ پیکسل. سلولِ خاموش هم
 * رندر می‌شود و رنگش `rgba(4,7,10,.12)` است — همان چیزی که رویِ زمینهٔ
 * سبز بافتِ شبکه‌ای می‌سازد. مربع‌کردنِ سلول یا حذفِ سلولِ خاموش، دقیقاً
 * همان دو اشتباهی است که این بلوک را به یک عددِ ساده تبدیل می‌کند.
 */
export function Hero({
  rangeLabel,
  rows,
  sub,
  value,
}: {
  rangeLabel: string
  rows: { cells: { color: string }[] }[]
  sub: string
  value: string
}) {
  return (
    <div
      style={{
        background: C.acc,
        color: C.bg,
        padding: '16px 18px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        boxShadow: '0 0 32px rgba(0,229,153,.18)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10, letterSpacing: '.24em', fontWeight: 700 }}>
        <span>FILES PROCESSED · {rangeLabel}</span>
        <span style={{ marginLeft: 'auto', background: C.bg, color: C.acc, padding: '2px 8px', letterSpacing: '.16em' }}>
          ▲ TRENDING
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, overflow: 'hidden' }}>
        {rows.map((r, ri) => (
          <div key={ri} style={{ display: 'flex', gap: 2 }}>
            {r.cells.map((c, ci) => (
              <i key={ci} style={{ display: 'block', width: 8, height: 13, background: c.color }} />
            ))}
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          fontSize: 10.5,
          fontWeight: 600,
          borderTop: '1px solid rgba(4,7,10,.28)',
          paddingTop: 9,
          flexWrap: 'wrap',
        }}
      >
        <span>{sub}</span>
        <span style={{ marginLeft: 'auto', fontSize: 22, fontWeight: 800, letterSpacing: '-.02em' }}>{value}</span>
      </div>
    </div>
  )
}

/**
 * وضعیتِ کلیِ سیستم.
 *
 * عمداً **هیچ متنِ هاردکدی** ندارد: «ALL CORE SYSTEMS NOMINAL» روی سیستمی که
 * دو سرویسش خواب است، بدترین شکلِ دروغِ کنسول است — چون دقیقاً همان جمله‌ای
 * است که اپراتور با گوشهٔ چشم می‌خواند و رد می‌شود.
 */
export function Posture({ headline, lines, ok }: { headline: string; lines: string[]; ok: boolean }) {
  return (
    <div
      style={{
        border: `2px solid ${C.edge}`,
        background: C.panel,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 11,
      }}
    >
      <div style={{ fontSize: 9.5, letterSpacing: '.2em', color: C.inkLo }}>▚ POSTURE</div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 700,
          color: ok ? C.acc : C.warn,
          textShadow: ok ? '0 0 12px rgba(0,229,153,.45)' : '0 0 12px rgba(255,209,102,.4)',
          lineHeight: 1.35,
        }}
      >
        {headline.split('\n').map((l) => (
          <div key={l}>{l}</div>
        ))}
      </div>
      <div style={{ fontSize: 10.5, color: C.ink, lineHeight: 1.9 }}>
        {lines.map((l) => (
          <div key={l}>{l}</div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
        <button
          type="button"
          style={{
            flex: 1,
            border: 0,
            background: C.acc,
            color: C.bg,
            fontFamily: 'inherit',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '.14em',
            padding: '7px 0',
            cursor: 'pointer',
          }}
        >
          FREEZE
        </button>
        <button
          type="button"
          className="ghost-btn"
          style={{
            flex: 1,
            border: `1px solid ${C.edgeBtn}`,
            background: 'transparent',
            color: C.ink,
            fontFamily: 'inherit',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '.14em',
            padding: '7px 0',
            cursor: 'pointer',
          }}
        >
          EXPORT
        </button>
      </div>
    </div>
  )
}
