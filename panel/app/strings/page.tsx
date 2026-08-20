'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { usePageData, type StringsPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
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
  const [applied, setApplied] = useState('')
  const [lang, setLang] = useState('fa')
  // جست‌وجو **سمتِ سرور** است، مثلِ صفحهٔ فارسی: `_texts_groups` روی کلید،
  // پیش‌فرض و مقدارِ جاری می‌گردد؛ فیلترِ کلاینتی فقط گروه‌های بارگذاری‌شده
  // را می‌بیند و همان تفاوت است که «پیدا نشد»ِ غلط می‌سازد.
  const state = usePageData<StringsPage>(
    'strings',
    [`lang=${encodeURIComponent(lang)}`, applied && `q=${encodeURIComponent(applied)}`]
      .filter(Boolean)
      .join('&'),
  )
  const groups = state.data?.groups ?? []
  const overridden = state.data?.edited ?? 0
  // حالتِ باز فقط **انحراف** از تصمیمِ سرور را نگه می‌دارد، نه کلِ وضعیت:
  // با عوض‌شدنِ جست‌وجو سرور دوباره تصمیم می‌گیرد کدام باز باشد، و یک
  // حالتِ کاملِ کلاینتی آن تصمیم را خنثی می‌کرد.
  const [flipped, setFlipped] = useState<Record<string, boolean>>({})
  const isOpen = (g: { title: string; open: boolean }) =>
    flipped[g.title] === undefined ? g.open : flipped[g.title]
  const toggle = (title: string) =>
    setFlipped((f) => ({ ...f, [title]: !(f[title] ?? groups.find((g) => g.title === title)?.open ?? false) }))

  return (
    <Shell active="08" cmd="./ctl strings --edit" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setApplied(q)}
          placeholder="grep key or text…"
          style={{ width: 240 }}
        />
        <Btn onClick={() => setApplied(q)}>SEARCH</Btn>
        <Select value={lang} onChange={(e) => setLang(e.target.value)} style={{ width: 150 }}>
          {(state.data?.langs ?? []).map((l) => (
            <option key={l.code} value={l.code}>
              {l.code} · {l.name}
            </option>
          ))}
        </Select>
        <Chip color="var(--zone)">{overridden} overridden</Chip>
        <Chip>{state.data?.total ?? 0} keys</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          in-process dict · reloaded on the redis txtver counter
        </span>
      </div>

      <PageState state={state}>
      {groups.map((g) => (
        <Section
          key={g.title}
          label={<Fa>{g.title}</Fa>}
          sigil="⌸"
          right={
            <button
              type="button"
              onClick={() => toggle(g.title)}
              style={{
                border: 0,
                background: 'transparent',
                color: 'inherit',
                font: 'inherit',
                cursor: 'pointer',
                padding: 0,
              }}
            >
              {g.n} keys · {g.edited} edited · {isOpen(g) ? '▾ close' : '▸ open'}
            </button>
          }
          pad="22px 14px 12px"
        >
        {isOpen(g) &&
          g.rows.map((r, i) => (
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

              <form
                method="post"
                action="/texts/save"
                style={{ flex: 1, minWidth: 0, maxWidth: 620, display: 'flex', flexDirection: 'column', gap: 5 }}
              >
                <input type="hidden" name="lang" value={lang} />
                <input type="hidden" name="key" value={r.key} />
                <input type="hidden" name="q" value={applied} />
                <textarea
                  name="value"
                  defaultValue={r.val}
                  dir="auto"
                  rows={r.val.length > 90 ? 3 : 1}
                  style={{
                    border: `1px solid ${C.edgeSoft}`,
                    background: C.panelDeep,
                    color: C.inkHi,
                    // فارسی داخلِ مونو حروفش نمی‌چسبد — همان قاعدهٔ `<Fa>`،
                    // این‌بار روی یک فیلدِ ورودی که نمی‌تواند داخلش بنشیند.
                    fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
                    fontSize: 12.5,
                    lineHeight: 1.7,
                    padding: '6px 9px',
                    outline: 'none',
                    resize: 'vertical',
                    width: '100%',
                  }}
                />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 9.5, color: C.inkFaint }}>
                  <Btn type="submit" solid style={{ padding: '3px 10px', fontSize: 9.5 }}>
                    SAVE
                  </Btn>
                  <span>default:</span>
                  <Fa style={{ fontSize: 11, flex: 1, minWidth: 0 }}>{r.def}</Fa>
                </div>
              </form>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, flexShrink: 0 }}>
                {r.overridden && (
                  <form method="post" action="/texts/reset">
                    <input type="hidden" name="lang" value={lang} />
                    <input type="hidden" name="key" value={r.key} />
                    <input type="hidden" name="q" value={applied} />
                    <Btn type="submit" style={{ padding: '4px 10px', fontSize: 9.5 }}>
                      RESET
                    </Btn>
                  </form>
                )}
              </div>
            </div>
          ))}
        </Section>
      ))}
      </PageState>

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
