'use client'

import { C } from '@/lib/theme'
import { COOKIE_STATUS } from '@/lib/pages'
import { usePageData, type CookieAccount, type CookiesPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Bar, Btn, Chip, Cmd, Flag, Head, Input, Row, Select } from '@/components/ui'

/** پرچمِ وضعیت؛ وضعیتِ ناشناخته بنفش می‌گیرد، نه رنگِ «عادی» — §۷. */
const flagOf = (s: string) =>
  COOKIE_STATUS[s as keyof typeof COOKIE_STATUS] ?? { flag: '[ ?? ]', color: C.violet }

/**
 * ۰۶ COOKIES — استخرِ سشن.
 *
 * سه چیز که از پنلِ فارسی منتقل شد چون هرکدام یک درسِ ثبت‌شده‌اند:
 *
 * • **سطلِ خالی «سوخته» نیست.** هشت پلتفرمِ پشتیبانی‌شده اصلاً اکانت
 *   نمی‌گیرند؛ نمایششان به‌شکلِ «۰ سالم» همان زنگِ خطای کاذبی است که
 *   ماه‌ها هر ۶ ساعت DM می‌فرستاد. این‌جا صریح «no session needed» است.
 * • **روالِ استخراجِ یوتیوب** از هر منطقِ استخری مهم‌تر است و روی صفحه
 *   چاپ می‌شود، نه در مستندات.
 * • **سهمیهٔ ساعتی و گرم‌شدن** کنارِ هر اکانت است، چون سؤالِ اپراتور
 *   «چرا این اکانت انتخاب نشد؟» است و جوابش معمولاً سقف است نه سلامت.
 */
export default function Page() {
  const state = usePageData<CookiesPage>('cookies')
  const stocked = state.data?.groups ?? []
  const all: CookieAccount[] = stocked.flatMap((p) => p.accounts)
  const usable = all.filter((a) => ['healthy', 'unproven'].includes(a.status)).length
  const degraded = all.length - usable
  const attention = all.filter((a) => ['frozen', 'invalid'].includes(a.status))
  const empty = state.data?.unstocked ?? []

  return (
    <Shell active="06" cmd="./ctl cookies --pool" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Chip color="var(--zone)">{usable} usable</Chip>
        <Chip>{all.length} accounts</Chip>
        <Chip color={degraded ? C.warn : C.inkLo} border={degraded ? '#3A2E14' : C.edgeChip}>
          {degraded} degraded
        </Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          mirrored to redis for the download node · ckfiles
        </span>
      </div>

      {attention.length > 0 && (
        <Section
          label="NEEDS A HUMAN" sigil="☠"
          labelColor={C.bad}
          edge={C.errEdge}
          bg={C.errBg}
          right={`${attention.length} waiting`}
          rightColor={C.bad}
          pad="22px 14px 12px"
        >
          {attention.map((a, i) => (
            <Row key={a.file} last={i === attention.length - 1}>
              <Flag text={flagOf(a.status).flag} color={flagOf(a.status).color} />
              <span style={{ color: C.inkMid, width: 210, overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.file}</span>
              <span style={{ flex: 1, color: C.errInk, fontSize: 10.5, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {a.err}
              </span>
              <form method="post" action="/cookies/unfreeze" style={{ display: 'inline' }}>
                <input type="hidden" name="name" value={a.file} />
                <Btn type="submit" style={{ padding: '3px 9px', fontSize: 9.5 }}>
                  HANDLED
                </Btn>
              </form>
            </Row>
          ))}
        </Section>
      )}

      {stocked.map((p) => (
        <Section
          key={p.platform}
          label={p.platform.toUpperCase()}
          sigil="⌬"
          right={`${p.accounts.length} accounts`}
          pad="22px 14px 12px"
        >
          {(
            <>
              <Head
                cols={[
                  { w: 46, label: '' },
                  { w: 210, label: 'FILE' },
                  { w: 70, label: 'LABEL' },
                  { w: 116, label: 'HOURLY' },
                  { w: 96, label: 'LAST OK' },
                  { label: 'LAST ERROR' },
                ]}
              />
              {p.accounts.map((a, i) => {
                const st = flagOf(a.status)
                const pct = a.cap ? (a.used / a.cap) * 100 : 0
                return (
                  <Row key={a.file} last={i === p.accounts.length - 1}>
                    <Flag text={st.flag} color={st.color} />
                    <span style={{ width: 210, color: C.inkMid, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {a.file}
                    </span>
                    <span style={{ width: 70, color: C.inkDim }}>{a.label}</span>
                    <span style={{ width: 116, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Bar pct={pct} width={8} color={pct >= 100 ? C.warn : C.acc} />
                      <span style={{ color: C.inkLo, fontSize: 10 }}>
                        {a.used}/{a.cap}
                      </span>
                    </span>
                    <span style={{ width: 96, color: C.inkDim, fontSize: 10 }}>{a.lastOk}</span>
                    <span
                      style={{
                        flex: 1,
                        minWidth: 0,
                        color: a.err ? C.badSoft : C.inkFaint,
                        fontSize: 10,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {a.warming ? <span style={{ color: C.info }}>warming up</span> : a.err || '—'}
                    </span>
                  </Row>
                )
              })}
            </>
          )}
        </Section>
      ))}

      {/*
        سطل‌های خالی **یک** سکشن می‌شوند، نه شش‌تا.
        این آرایش خودش یک ادعاست: «هرگز پر نشده» با «سوخته» یکی نیست، و
        دادنِ یک کارتِ تمام‌قد به هر کدام دقیقاً همان زنگِ خطای کاذبی را
        بازتولید می‌کند که ماه‌ها هر ۶ ساعت DM می‌فرستاد. یک خط کافی است.
      */}
      {empty.length > 0 && (
        <Section label="UNSTOCKED BUCKETS" sigil="○" right={`${empty.length} · not an alarm`} pad="22px 14px 12px">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 9 }}>
            {empty.map((p) => (
              <Chip key={p} color={C.inkFaint}>
                {p}
              </Chip>
            ))}
          </div>
          <div style={{ fontSize: 10, color: C.inkDim, lineHeight: 1.8 }}>
            these have never been stocked and cannot be: `COOKIE_PLATFORMS` builds six buckets while
            `_cookie_platform` can ask for fourteen. anonymous access works for them, so silence here
            is the correct state — a &quot;0 healthy&quot; alarm would be false on day one.
          </div>
        </Section>
      )}

      <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
        <Section label="ADD ACCOUNT" sigil="✚" right="paste, not upload" pad="22px 14px 12px">
          <form method="post" action="/cookies/add">
            <div style={{ display: 'flex', gap: 8, marginBottom: 9, flexWrap: 'wrap' }}>
              <Select name="platform" defaultValue="instagram" style={{ width: 140 }}>
                {(state.data?.platforms ?? []).map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
              <Input name="label" placeholder="label (e.g. main)" style={{ width: 150 }} />
            </div>
            <textarea
              dir="ltr"
              name="text"
              placeholder={'# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t…\tsessionid\t…'}
              style={{
                width: '100%',
                height: 132,
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
                ADD
              </Btn>
              <span style={{ fontSize: 9.5, color: C.inkDim }}>Netscape or Cookie-Editor JSON</span>
            </div>
          </form>
        </Section>

        <Section label="YOUTUBE EXPORT PROCEDURE" sigil="⚠" right="matters more than pool logic" rightColor={C.warn} pad="22px 14px 12px">
          <div style={{ fontSize: 10.5, color: C.ink, lineHeight: 2 }}>
            YouTube <b style={{ color: C.warn }}>rotates</b> cookies on a still-open session, so an
            export from a normal window dies within hours.
          </div>
          <Cmd>{`1  open an incognito window
2  log in to youtube.com
3  SAME TAB → youtube.com/robots.txt
4  export cookies here
5  close the window — do NOT log out`}</Cmd>
          <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.8 }}>
            step 5 is the one everyone skips; logging out invalidates the cookie you just exported.
          </div>
        </Section>
      </div>
    </Shell>
  )
}
