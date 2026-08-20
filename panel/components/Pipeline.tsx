import { C } from '@/lib/theme'
import { Section } from './Section'

/** خطِ لولهٔ پردازش: پنج گامِ خنثی + گامِ آخر که معکوس (سبزِ پر) است. */
export function Pipeline({
  steps,
}: {
  steps: { name: string; v: string; meta: string; color: string; step: string }[]
}) {
  return (
    <Section
      label="PIPELINE" sigil="⚡"
      right="end-to-end p50 41s"
      pad="24px 14px 16px"
      style={{ background: `linear-gradient(90deg,${C.panel},#06110E,${C.panel})` }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit,minmax(146px,1fr))',
          gap: 8,
          alignItems: 'stretch',
        }}
      >
        {steps.map((p) => (
          <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
            <div
              style={{
                flex: 1,
                minWidth: 0,
                border: `1px solid ${C.edgeSoft}`,
                background: C.panelDeep,
                padding: '9px 11px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 9, letterSpacing: '.18em', color: C.inkLo }}>{p.name}</span>
                <span style={{ marginLeft: 'auto', fontSize: 9, color: C.accMid }}>{p.step}</span>
              </div>
              <div style={{ fontSize: 17, fontWeight: 700, color: p.color, marginTop: 4, lineHeight: 1 }}>{p.v}</div>
              <div style={{ fontSize: 9, color: C.inkDim, marginTop: 4 }}>{p.meta}</div>
            </div>
          </div>
        ))}

        <div
          style={{
            border: `1px solid ${C.acc}`,
            background: C.acc,
            color: C.bg,
            padding: '9px 11px',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 9, letterSpacing: '.18em', fontWeight: 700 }}>USER</span>
            <span style={{ marginLeft: 'auto', fontSize: 9, fontWeight: 700, opacity: 0.6 }}>06</span>
          </div>
          <div style={{ fontSize: 17, fontWeight: 800, marginTop: 4, lineHeight: 1 }}>17/min</div>
          <div style={{ fontSize: 9, marginTop: 4, fontWeight: 600, opacity: 0.72 }}>telegram</div>
        </div>
      </div>
    </Section>
  )
}
