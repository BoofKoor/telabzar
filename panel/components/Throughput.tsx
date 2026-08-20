import { C } from '@/lib/theme'
import { Section } from './Section'

/**
 * نمودارِ گذردهی.
 *
 * سه چیزِ باربر: میله‌ها **راه‌راه**‌اند (`repeating-linear-gradient` با
 * دورهٔ ۶ پیکسل) نه توپُر؛ زمینهٔ ناحیهٔ رسم خودش خط‌های افقیِ ۴۳پیکسلی
 * دارد که نقشِ شبکهٔ راهنما را بازی می‌کند؛ و محورِ عمودی یک ستونِ متنیِ
 * جدا با `justify-content:space-between` است، نه برچسبِ داخلِ نمودار.
 */
export function Throughput({
  rangeLabel,
  trend,
  peak,
  avg,
  axis,
  latSpark,
  latNow,
}: {
  rangeLabel: string
  trend: { fh: number; oh: number; eh: number; label: string; tip: string }[]
  peak: string
  avg: string
  axis: { a: string; b: string; c: string }
  latSpark: string
  latNow: number
}) {
  return (
    <Section label={`THROUGHPUT · ${rangeLabel}`} sigil="▲" right={`peak ${peak} · avg ${avg}`} pad="24px 14px 12px">
      <div style={{ display: 'flex', gap: 10 }}>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            height: 176,
            fontSize: 9,
            color: C.inkDim,
            textAlign: 'right',
            paddingBottom: 2,
          }}
        >
          <span>{axis.a}</span>
          <span>{axis.b}</span>
          <span>{axis.c}</span>
          <span>0</span>
        </div>

        <div
          style={{
            flex: 1,
            minWidth: 0,
            position: 'relative',
            height: 176,
            background: `repeating-linear-gradient(180deg,transparent 0 43px,${C.plotGrid} 43px 44px)`,
            borderBottom: `1px solid ${C.edgeAxis}`,
          }}
        >
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'flex-end', gap: 4 }}>
            {trend.map((d, i) => (
              <div
                key={i}
                title={d.tip}
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: 'flex',
                  alignItems: 'flex-end',
                  justifyContent: 'center',
                  gap: 2,
                  height: '100%',
                }}
              >
                <i
                  style={{
                    display: 'block',
                    width: '38%',
                    maxWidth: 14,
                    background: `repeating-linear-gradient(180deg,${C.acc} 0 3px,transparent 3px 6px)`,
                    boxShadow: '0 0 10px rgba(0,229,153,.25)',
                    height: d.fh,
                  }}
                />
                <i
                  style={{
                    display: 'block',
                    width: '38%',
                    maxWidth: 14,
                    background: `repeating-linear-gradient(180deg,${C.accDim} 0 3px,transparent 3px 6px)`,
                    height: d.oh,
                  }}
                />
                <i
                  style={{ display: 'block', width: '14%', maxWidth: 6, background: C.warn, opacity: 0.75, height: d.eh }}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 4, marginTop: 7, paddingLeft: 34 }}>
        {trend.map((d, i) => (
          <span
            key={i}
            style={{
              flex: 1,
              minWidth: 0,
              textAlign: 'center',
              fontSize: 9,
              color: C.inkDim,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            {d.label}
          </span>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          gap: 14,
          marginTop: 9,
          paddingTop: 9,
          borderTop: `1px solid ${C.edgeHair}`,
          fontSize: 9.5,
          letterSpacing: '.1em',
          color: C.inkLo,
          flexWrap: 'wrap',
        }}
      >
        <span>
          <i style={{ display: 'inline-block', width: 9, height: 9, background: C.acc, marginRight: 5 }} />
          FILES
        </span>
        <span>
          <i style={{ display: 'inline-block', width: 9, height: 9, background: C.accDim, marginRight: 5 }} />
          OPS
        </span>
        <span>
          <i style={{ display: 'inline-block', width: 9, height: 9, background: C.warn, marginRight: 5 }} />
          ERR
        </span>
        <span style={{ marginLeft: 'auto', color: C.inkDim }}>
          latency <span style={{ color: C.acc }}>{latSpark}</span> {latNow}ms
        </span>
      </div>
    </Section>
  )
}
