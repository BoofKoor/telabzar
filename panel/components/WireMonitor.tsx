import { C } from '@/lib/theme'
import { Section } from './Section'

/**
 * دامپِ هگزِ گیت‌وی، به شکلِ `xxd`.
 *
 * سه ستون با سه رنگِ متفاوت: آدرس آبی، بایت‌ها خاکستری، و ستونِ ASCII سبز
 * داخلِ `|…|`. `white-space:nowrap` + `overflow:hidden` باربر است — بدونش
 * خطِ هگز می‌شکند و کلِ حسِ «دامپِ خام» از بین می‌رود.
 */
export function WireMonitor({ lines }: { lines: { addr: string; hex: string; ascii: string }[] }) {
  return (
    <Section label="WIRE MONITOR" right="xxd · gateway :2096" pad="22px 14px 14px">
      {lines.map((h) => (
        <div
          key={h.addr}
          style={{ display: 'flex', gap: 14, fontSize: 11, lineHeight: 1.85, whiteSpace: 'nowrap', overflow: 'hidden' }}
        >
          <span style={{ color: C.info }}>{h.addr}</span>
          <span style={{ color: C.inkLo, flex: 1, minWidth: 0, overflow: 'hidden' }}>{h.hex}</span>
          <span style={{ color: C.acc }}>|{h.ascii}|</span>
        </div>
      ))}
    </Section>
  )
}
