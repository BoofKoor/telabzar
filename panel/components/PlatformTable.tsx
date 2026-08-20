import { C } from '@/lib/theme'
import { Section } from './Section'

/** جدولِ پلتفرم‌ها؛ ستونِ ۷D یک اسپارک‌لاینِ نویسه‌ای است. */
export function PlatformTable({
  rows,
}: {
  rows: { name: string; n: string; spark: string; ok: string; okColor: string; hue: string }[]
}) {
  return (
    <Section label="PLATFORM TABLE" sigil="⌗" pad="22px 0 0">
      <div
        style={{
          display: 'flex',
          gap: 10,
          padding: '6px 14px',
          fontSize: 9,
          letterSpacing: '.14em',
          color: C.inkDim,
          borderBottom: `1px solid ${C.edgeHair}`,
        }}
      >
        <span style={{ width: 74 }}>HOST</span>
        <span style={{ flex: 1 }}>7D</span>
        <span style={{ width: 34, textAlign: 'right' }}>OK%</span>
        <span style={{ width: 48, textAlign: 'right' }}>N</span>
      </div>

      {rows.map((p) => (
        <div
          key={p.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 14px',
            borderBottom: `1px solid ${C.edgeRow}`,
            fontSize: 11,
          }}
        >
          <span
            style={{ width: 74, color: p.hue, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {p.name}
          </span>
          <span
            style={{ flex: 1, color: p.hue, fontSize: 11.5, letterSpacing: '.02em', overflow: 'hidden', whiteSpace: 'nowrap' }}
          >
            {p.spark}
          </span>
          <span style={{ width: 34, textAlign: 'right', color: p.okColor }}>{p.ok}</span>
          <span style={{ width: 48, textAlign: 'right', color: C.inkLo }}>{p.n}</span>
        </div>
      ))}
    </Section>
  )
}
