import { C } from '@/lib/theme'
import { Section } from './Section'

/** `tail -f` — ردیفِ اول زمینهٔ سبزِ کم‌رنگ می‌گیرد تا «تازه‌ترین» دیده شود. */
export function JobStream({
  rows,
}: {
  rows: {
    key: string
    time: string
    pid: string
    sev: string
    sevColor: string
    tag: string
    tagColor: string
    user: string
    msg: string
    size: string
    node: string
    bar: { on: string; off: string }
    barColor: string
    state: string
    rowBg: string
  }[]
}) {
  return (
    <Section label="JOB STREAM" right="tail -f /var/log/telabzar/jobs.ndjson" pad="22px 0 0">
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {rows.map((l) => (
          <div
            key={l.key}
            className="log-row"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 11,
              padding: '6px 14px',
              borderTop: `1px solid ${C.edgeRow}`,
              fontSize: 11,
              whiteSpace: 'nowrap',
              background: l.rowBg,
            }}
          >
            <span style={{ color: C.inkDim }}>{l.time}</span>
            <span className="mx-hide-m" style={{ color: C.inkFaint }}>
              {l.pid}
            </span>
            <span style={{ color: l.sevColor, width: 42 }}>{l.sev}</span>
            <span style={{ color: l.tagColor, width: 64 }}>{l.tag}</span>
            <span className="mx-hide-s" style={{ color: C.inkLo, width: 70, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {l.user}
            </span>
            <span style={{ color: C.inkHi, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {l.msg}
            </span>
            <span className="mx-hide-s" style={{ color: C.inkLo, width: 52, textAlign: 'right' }}>
              {l.size}
            </span>
            <span className="mx-hide-m" style={{ color: C.inkFaint, width: 44 }}>
              {l.node}
            </span>
            <span style={{ letterSpacing: '.02em', color: C.edgeGauge }}>
              [<span style={{ color: l.barColor }}>{l.bar.on}</span>
              <span style={{ color: C.edgeGauge }}>{l.bar.off}</span>]
            </span>
            <span style={{ color: l.barColor, width: 48, textAlign: 'right' }}>{l.state}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}
