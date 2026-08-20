import { C } from '@/lib/theme'
import { Section } from './Section'

/** نقشهٔ حرارتیِ ۷ روز × ۲۴ ساعت، با راهنمای پنج‌پله‌ای در پاورقی. */
export function ActivityMap({ heat }: { heat: { day: string; cells: { bg: string; tip: string }[] }[] }) {
  return (
    <Section label="ACTIVITY MAP · 7D × 24H" sigil="▦" pad="24px 14px 14px">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {heat.map((row) => (
          <div key={row.day} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ width: 30, fontSize: 9, letterSpacing: '.1em', color: C.inkLo }}>{row.day}</span>
            <div style={{ flex: 1, display: 'flex', gap: 2 }}>
              {row.cells.map((c, i) => (
                <i key={i} title={c.tip} style={{ flex: 1, height: 13, display: 'block', background: c.bg }} />
              ))}
            </div>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 5 }}>
          <span style={{ width: 30 }} />
          <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: 9, color: C.inkDim }}>
            {['00', '04', '08', '12', '16', '20', '23'].map((h) => (
              <span key={h}>{h}</span>
            ))}
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginTop: 11,
          paddingTop: 10,
          borderTop: `1px solid ${C.edgeHair}`,
          fontSize: 9.5,
          color: C.inkLo,
        }}
      >
        <span>less</span>
        {C.heat.map((h) => (
          <i key={h} style={{ width: 13, height: 13, background: h, display: 'block' }} />
        ))}
        <span>more</span>
        <span style={{ marginLeft: 'auto', color: C.ink }}>
          peak window <b style={{ color: C.acc, fontWeight: 700 }}>18:00–23:00</b>
        </span>
      </div>
    </Section>
  )
}
