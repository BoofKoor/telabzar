import { C } from '@/lib/theme'

/** نوارِ تک‌خطیِ اعدادِ لحظه‌ای، درست زیرِ سربرگ. */
export function StatusBits({ bits }: { bits: { k: string; v: string; c: string }[] }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        flexWrap: 'wrap',
        border: `1px solid ${C.edge}`,
        background: C.panelTile,
        fontSize: 10.5,
        letterSpacing: '.08em',
      }}
    >
      {bits.map((s) => (
        <span key={s.k} style={{ padding: '7px 14px', borderRight: `1px solid ${C.edge}`, color: C.inkLo }}>
          {s.k} <b style={{ color: s.c, fontWeight: 700 }}>{s.v}</b>
        </span>
      ))}
    </div>
  )
}
