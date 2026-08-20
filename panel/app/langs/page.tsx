'use client'

import { C } from '@/lib/theme'
import { usePageData, type LangsPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Bar, Btn, Chip, Cmd, Fa, Head, Input, Row } from '@/components/ui'

/**
 * ۱۰ LANGS — افزودنِ زبان **داده** است، نه کد.
 *
 * حلقهٔ کار روی صفحه نوشته شده چون کلِ قابلیت همان است: export → ترجمه در
 * بیرون → import. و دو چیزی که به آن گره خورده‌اند و پنهان‌کردنشان گران است:
 *
 * • **پوششِ ناقص به انگلیسی می‌افتد، نه فارسی.** زبانِ ۹۰٪‌ترجمه‌شده ۱۰٪
 *   انگلیسی نشان می‌دهد؛ برای مخاطبی که خطِ فارسی نمی‌خواند این از فارسی
 *   بی‌فایده‌تر نیست، بلکه تنها چیزِ خواندنی است. پس ستونِ پوشش عددِ اصلیِ
 *   این صفحه است.
 * • **حذفِ زبان کاربرانش را بی‌صدا انگلیسی می‌کند** و `users.lang` روی کدِ
 *   مرده می‌ماند. تنها راهِ خروجشان منوی تنظیماتِ ربات است — پس حذف هشدار
 *   می‌گیرد، نه یک دکمهٔ ساده.
 */
export default function Page() {
  const state = usePageData<LangsPage>('langs')
  const rows = state.data?.rows ?? []
  const builtin = rows.filter((l) => l.builtin).length
  return (
    <Shell active="10" cmd="./ctl langs --list" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Chip color="var(--zone)">{rows.length} languages</Chip>
        <Chip>{builtin} built-in</Chip>
        <Chip>{state.data?.total ?? 0} keys each</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          adding a language is data — zero lines of code
        </span>
      </div>

      <Section label="LANGUAGES" sigil="⟐" corners right="ordered by name, code" pad="22px 14px 12px">
        <PageState state={state}>
        <Head
          cols={[
            { w: 70, label: 'CODE' },
            { w: 150, label: 'NAME' },
            { w: 70, label: 'SOURCE' },
            { label: 'COVERAGE' },
            { w: 74, label: 'KEYS', right: true },
            { w: 62, label: 'USERS', right: true },
            { w: 148, label: '', right: true },
          ]}
        />
        {rows.map((l, i) => {
          const pct = l.total ? Math.round((l.keys / l.total) * 100) : 0
          const col = pct === 100 ? C.acc : pct >= 90 ? C.warn : C.bad
          return (
            <Row key={l.code} last={i === rows.length - 1}>
              <span style={{ width: 70, color: C.inkHi }}>{l.code}</span>
              <span style={{ width: 150 }}>
                <Fa style={{ color: C.inkMid, fontSize: 12.5 }}>{l.name}</Fa>
              </span>
              <span style={{ width: 70 }}>
                <Chip color={l.builtin ? C.info : C.inkLo}>{l.builtin ? 'code' : 'pack'}</Chip>
              </span>
              <span style={{ flex: 1 }}>
                <Bar pct={pct} width={16} color={col} />
                <span style={{ color: col, marginLeft: 8 }}>{pct}%</span>
              </span>
              <span style={{ width: 74, textAlign: 'right', color: C.inkLo }}>
                {l.keys}/{l.total}
              </span>
              <span style={{ width: 62, textAlign: 'right', color: C.inkLo }}>{l.users.toLocaleString('en-US')}</span>
              <span style={{ width: 148, textAlign: 'right', display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                <Btn
                  type="button"
                  onClick={() => {
                    window.location.href = `/langs/export?lang=${encodeURIComponent(l.code)}`
                  }}
                  style={{ padding: '3px 9px', fontSize: 9.5 }}
                >
                  EXPORT
                </Btn>
                {!l.builtin && (
                  <form method="post" action="/langs/delete" style={{ display: 'inline' }}>
                    {/* هندلر `code` می‌خواند نه `lang` — با ممیزیِ فرم‌به‌هندلر
                        پیدا شد، نه با بازخوانی. */}
                    <input type="hidden" name="code" value={l.code} />
                    <Btn type="submit" danger style={{ padding: '3px 9px', fontSize: 9.5 }}>
                      DELETE
                    </Btn>
                  </form>
                )}
              </span>
            </Row>
          )
        })}
        </PageState>
      </Section>

      <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
        <Section label="IMPORT A PACK" sigil="⇩" right="export == import" pad="22px 14px 12px">
          <form method="post" action="/langs/import">
            <div style={{ display: 'flex', gap: 8, marginBottom: 9, flexWrap: 'wrap', alignItems: 'center' }}>
              <Input name="lang" placeholder="code (e.g. es, pt-BR)" style={{ width: 170 }} />
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: C.inkLo }}>
                <input type="checkbox" name="replace" /> replace instead of merge
              </label>
            </div>
            <textarea
              dir="ltr"
              name="pack"
              placeholder={'{\n  "lang": "es",\n  "name": "Español",\n  "texts": { "btn_compress": "Comprimir", … }\n}'}
              style={{
                width: '100%',
                height: 148,
                border: `1px solid ${C.edgeSoft}`,
                background: C.panelDeep,
                color: C.inkHi,
                fontFamily: 'inherit',
                fontSize: 10.5,
                lineHeight: 1.7,
                padding: '8px 10px',
                outline: 'none',
                resize: 'vertical',
              }}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 9, alignItems: 'center' }}>
              <Btn type="submit" solid>
                REVIEW
              </Btn>
              <span style={{ fontSize: 9.5, color: C.inkDim }}>
                nothing is written before you confirm the diff
              </span>
            </div>
          </form>
        </Section>

        <Section label="THE LOOP" sigil="⟳" right="one file, one chat-bot" pad="22px 14px 12px">
          <Cmd>{`1  EXPORT fa      → telabzar-fa.json  (17,691 B)
2  paste into any LLM with the
   instruction that ships inside
   the file itself
3  IMPORT the result under a new
   code — review, then confirm`}</Cmd>
          <div style={{ marginTop: 11, fontSize: 10, color: C.ink, lineHeight: 1.9 }}>
            The envelope&apos;s <span style={{ color: C.accHi }}>lang</span> field is compared, never
            trusted: the form&apos;s code wins. A model can silently change it and the translation would
            land under the wrong language.
          </div>
          <div
            style={{
              borderTop: `1px solid ${C.edgeHair}`,
              marginTop: 11,
              paddingTop: 10,
              fontSize: 9.5,
              color: C.warn,
              lineHeight: 1.8,
            }}
          >
            deleting a language does not migrate its users — they fall back to English and can only get
            out through the bot&apos;s own settings menu.
          </div>
        </Section>
      </div>
    </Shell>
  )
}
