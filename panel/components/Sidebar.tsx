import { C } from '@/lib/theme'
import { Section } from './Section'
import type { AuditRow, ErrRow, FlagRow, Gauge } from '@/lib/types'

/** صف‌ها + منابع؛ هر دو با همان نوارِ نویسه‌ای `[███░░]`. */
export function Queue({
  queues,
  resources,
}: {
  queues: { label: string; n: number; color: string; bar: Gauge }[]
  resources: { label: string; meta: string; color: string; bar: Gauge }[]
}) {
  return (
    <Section label="QUEUE" pad="22px 14px 13px">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {queues.map((q) => (
          <div key={q.label} style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 11 }}>
            <span style={{ width: 70, color: C.ink }}>{q.label}</span>
            <span style={{ flex: 1, letterSpacing: '.04em', color: C.edgeGauge }}>
              [<span style={{ color: q.color }}>{q.bar.on}</span>
              <span style={{ color: C.edgeGauge }}>{q.bar.off}</span>]
            </span>
            <span style={{ width: 24, textAlign: 'right', color: C.inkHi }}>{q.n}</span>
          </div>
        ))}
      </div>

      <div
        style={{
          borderTop: `1px solid ${C.edgeHair}`,
          marginTop: 11,
          paddingTop: 11,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          fontSize: 11,
        }}
      >
        {resources.map((r) => (
          <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <span style={{ width: 70, color: C.ink }}>{r.label}</span>
            <span style={{ flex: 1, letterSpacing: '.04em', color: C.edgeGauge }}>
              [<span style={{ color: r.color }}>{r.bar.on}</span>
              <span style={{ color: C.edgeGauge }}>{r.bar.off}</span>]
            </span>
            <span style={{ color: C.inkLo, fontSize: 10, width: 58, textAlign: 'right' }}>{r.meta}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}

/**
 * فهرستِ پرچم‌دار — سرویس‌ها، استخرِ کوکی و نودها همه یک شکل‌اند.
 *
 * پرچم `[ OK ]`/`[WARN]`/`[FAIL]` عمداً **هم‌عرض** نوشته شده (فاصله‌های
 * داخلی) تا در فونتِ مونو ستون بماند؛ همین است که به فهرست حسِ خروجیِ
 * یک ابزارِ خط‌فرمان می‌دهد به‌جای بجِ رنگی.
 */
export function FlagList({
  label,
  right,
  rightColor,
  rows,
  truncate = false,
  footer,
}: {
  label: string
  right?: string
  rightColor?: string
  rows: FlagRow[]
  truncate?: boolean
  footer?: React.ReactNode
}) {
  return (
    <Section label={label} right={right} rightColor={rightColor} pad={footer ? '22px 14px 12px' : '22px 14px 11px'}>
      {rows.map((s) => (
        <div
          key={s.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 9,
            padding: '5px 0',
            fontSize: 11,
            borderBottom: `1px solid ${C.edgeRow}`,
          }}
        >
          <span style={{ color: s.color, width: 46 }}>{s.flag}</span>
          <span
            style={
              truncate
                ? { color: C.inkMid, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                : { color: C.inkMid }
            }
          >
            {s.name}
          </span>
          <span style={{ marginLeft: 'auto', color: C.inkLo, fontSize: 10 }}>{s.meta}</span>
        </div>
      ))}
      {footer}
    </Section>
  )
}

/** پاورقیِ کارتِ نودها: وضعیتِ تونلِ WireGuard. */
export function WgFooter() {
  return (
    <pre
      style={{
        fontFamily: 'inherit',
        fontSize: 9.5,
        lineHeight: 1.75,
        color: C.inkDim,
        marginTop: 10,
        paddingTop: 10,
        borderTop: `1px solid ${C.edgeHair}`,
      }}
    >
      {'wg0 10.8.0.1/24 · mtu 1420\nrx '}
      <span style={{ color: C.acc }}>4.81 GB</span>
      {' · tx '}
      <span style={{ color: C.acc }}>17.2 GB</span>
      {'\nhandshake '}
      <span style={{ color: C.inkMid }}>00:00:41</span>
      {' ago'}
    </pre>
  )
}

/** خطاهای ۲۴ ساعت — تنها کارتی که کادر و زمینهٔ قرمز دارد. */
export function Errors({ rows }: { rows: ErrRow[] }) {
  return (
    <Section label="ERRORS · 24H" labelColor={C.bad} edge={C.errEdge} bg={C.errBg} pad="22px 14px 11px">
      {rows.map((e) => (
        <div
          key={e.msg}
          style={{
            display: 'flex',
            gap: 9,
            padding: '5px 0',
            fontSize: 10.5,
            borderBottom: `1px solid ${C.errRow}`,
            alignItems: 'baseline',
          }}
        >
          <span style={{ color: C.badSoft, width: 26 }}>{e.n}×</span>
          <span style={{ color: C.errInk, flex: 1, minWidth: 0, wordBreak: 'break-word', whiteSpace: 'normal' }}>
            {e.msg}
          </span>
          <span style={{ color: C.inkLo, fontSize: 9.5 }}>{e.host}</span>
        </div>
      ))}
    </Section>
  )
}

/** ردِ تغییراتِ ادمین — کادرِ کهربایی. */
export function Audit({ rows }: { rows: AuditRow[] }) {
  return (
    <Section label="AUDIT TRAIL" labelColor={C.warn} edge={C.auditEdge} bg={C.auditBg} pad="22px 14px 11px">
      {rows.map((a) => (
        <div
          key={a.t}
          style={{
            display: 'flex',
            gap: 9,
            padding: '5px 0',
            fontSize: 10.5,
            borderBottom: `1px solid ${C.auditRow}`,
            alignItems: 'baseline',
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ color: C.auditTime }}>{a.t}</span>
          <span style={{ color: C.warn, width: 52 }}>{a.who}</span>
          <span style={{ color: C.auditInk, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {a.act}
          </span>
          <span style={{ color: C.ink }}>{a.val}</span>
        </div>
      ))}
    </Section>
  )
}
