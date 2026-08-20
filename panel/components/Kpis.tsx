import { C } from '@/lib/theme'

/**
 * چهار کاشیِ KPI.
 *
 * دو ریزه‌کاری که ظاهر را می‌سازند و در بازسازیِ اول هر دو از قلم افتادند:
 * فاصلهٔ کاشی‌ها **خطِ مو** است نه فاصلهٔ خالی (`gap:1px` روی زمینهٔ
 * `--edge`)، و اسپارک‌لاین یک رشتهٔ **نویسه‌ای** است با درخشش، نه میله‌های
 * DOM — همان چیزی که به بلوک بافتِ ترمینال می‌دهد.
 */
export function Kpis({
  kpis,
}: {
  kpis: {
    label: string
    value: string
    unit: string
    delta: string
    foot: string
    tag: string
    spark: string
    dc: string
    db: string
  }[]
}) {
  return (
    <div
      className="mx-kpis"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4,minmax(0,1fr))',
        gap: 1,
        background: C.edge,
        border: `1px solid ${C.edge}`,
      }}
    >
      {kpis.map((k) => (
        <div
          key={k.label}
          style={{
            background: C.panelTile,
            padding: '13px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            position: 'relative',
          }}
        >
          <span style={{ position: 'absolute', top: 5, right: 7, fontSize: 9, color: C.accFaint }}>+</span>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 9.5, letterSpacing: '.18em', color: C.inkLo }}>{k.label}</span>
            <span
              style={{
                marginLeft: 'auto',
                fontSize: 10.5,
                color: k.dc,
                border: `1px solid ${k.db}`,
                padding: '1px 5px',
              }}
            >
              {k.delta}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span
              style={{
                fontSize: 25,
                fontWeight: 700,
                color: C.inkHi,
                letterSpacing: '-.02em',
                textShadow: '0 0 14px rgba(0,229,153,.14)',
              }}
            >
              {k.value}
            </span>
            <span style={{ fontSize: 10.5, color: C.inkDim }}>{k.unit}</span>
          </div>

          <div
            style={{
              fontSize: 12,
              letterSpacing: '.04em',
              color: C.acc,
              lineHeight: 1,
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              textShadow: '0 0 10px rgba(0,229,153,.3)',
            }}
          >
            {k.spark}
          </div>

          <div style={{ display: 'flex', gap: 8, fontSize: 9.5, color: C.inkDim }}>
            <span>{k.foot}</span>
            <span style={{ marginLeft: 'auto', color: C.inkFaint }}>{k.tag}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
