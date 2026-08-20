'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { STRING_GROUPS } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Btn, Chip, Fa, Input, Select } from '@/components/ui'

/**
 * ۰۸ STRINGS — هر رشتهٔ رابطِ ربات، قابلِ ویرایش بدونِ ری‌استارت.
 *
 * **این‌جا جایی است که کنسولِ لاتین با دادهٔ فارسی روبه‌رو می‌شود، و قاعده
 * سخت است:** متنِ فارسی از `<Fa>` رد می‌شود (فونتِ متنی + `dir=rtl` +
 * ایزوله). فارسی داخلِ فونتِ مونو حروفش نمی‌چسبد و داخلِ جعبهٔ LTR ترتیبش
 * برعکس می‌شود — هر دو در پنلِ فارسی یک‌بار اتفاق افتاده‌اند.
 *
 * ستونِ «override» نشانگرِ سبز می‌گیرد چون سؤالِ اپراتور «کدام رشته را
 * دست زده‌ام؟» است؛ رشتهٔ دست‌نخورده باید بی‌صدا باشد.
 */
export default function Page() {
  const [q, setQ] = useState('')
  const [lang, setLang] = useState('fa')
  const groups = STRING_GROUPS.map((g) => ({
    ...g,
    rows: g.rows.filter((r) => !q || r.key.includes(q) || r.fa.includes(q) || r.en.toLowerCase().includes(q.toLowerCase())),
  })).filter((g) => g.rows.length)

  const overridden = STRING_GROUPS.flatMap((g) => g.rows).filter((r) => r.overridden).length

  return (
    <Shell active="08" cmd="./ctl strings --edit" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="grep key or text…" style={{ width: 240 }} />
        <Select value={lang} onChange={(e) => setLang(e.target.value)} style={{ width: 120 }}>
          <option value="fa">fa · فارسی</option>
          <option value="en">en · English</option>
          <option value="ar">ar · العربية</option>
        </Select>
        <Chip color="var(--zone)">{overridden} overridden</Chip>
        <Chip>214 keys</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          in-process dict · reloaded on the redis txtver counter
        </span>
      </div>

      {groups.map((g) => (
        <Section key={g.title} label={g.title.split('·')[0].trim()} sigil="⌸" right={`${g.n} keys in group`} pad="22px 14px 12px">
          {g.rows.map((r, i) => (
            <div
              key={r.key}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 12,
                padding: '8px 0',
                borderBottom: i === g.rows.length - 1 ? undefined : `1px solid ${C.edgeRow}`,
                fontSize: 11,
              }}
            >
              <span style={{ width: 3, alignSelf: 'stretch', background: r.overridden ? 'var(--zone)' : 'transparent', flexShrink: 0 }} />
              <span style={{ width: 180, color: r.overridden ? C.inkHi : C.inkMid, flexShrink: 0, paddingTop: 5 }}>
                {r.key}
              </span>

              <div style={{ flex: 1, minWidth: 0, maxWidth: 620, display: 'flex', flexDirection: 'column', gap: 5 }}>
                <div
                  style={{
                    border: `1px solid ${C.edgeSoft}`,
                    background: C.panelDeep,
                    padding: '6px 9px',
                    minHeight: 30,
                  }}
                >
                  {lang === 'en' ? (
                    <span style={{ color: C.inkHi, fontSize: 11 }}>{r.en}</span>
                  ) : (
                    <Fa style={{ color: C.inkHi, fontSize: 12.5, lineHeight: 1.7 }}>{r.fa}</Fa>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 9.5, color: C.inkFaint }}>
                  <span>default:</span>
                  {lang === 'en' ? (
                    <span>{r.en}</span>
                  ) : (
                    <Fa style={{ fontSize: 11 }}>{r.fa}</Fa>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, flexShrink: 0 }}>
                <Btn solid style={{ padding: '4px 10px', fontSize: 9.5 }}>
                  SAVE
                </Btn>
                {r.overridden && <Btn style={{ padding: '4px 10px', fontSize: 9.5 }}>RESET</Btn>}
              </div>
            </div>
          ))}
        </Section>
      ))}

      <Section label="PLACEHOLDER CONTRACT" sigil="⌘" right="validated on write" pad="22px 14px 12px">
        <div style={{ fontSize: 10.5, color: C.ink, lineHeight: 1.9 }}>
          An override keeps the source string&apos;s placeholders. An <b style={{ color: C.warn }}>unknown</b>{' '}
          placeholder is rejected here; a <b style={{ color: C.warn }}>missing</b> one is allowed on this page
          (the admin knows what they are doing) but rejected on language import, because dropping{' '}
          <span style={{ color: C.accHi }}>{'{mb}'}</span> is the most likely machine-translation error and
          completely silent — the text still reads fine and the number simply never reaches the user.
        </div>
      </Section>
    </Shell>
  )
}
