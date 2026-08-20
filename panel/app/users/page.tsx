'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { usePageData, type UsersPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Btn, Chip, Head, Input, Row, Scroll } from '@/components/ui'

/**
 * ۰۵ USERS — فهرست، جست‌وجو، بلاک.
 *
 * ادمین‌ها ردیفِ کنش ندارند و این باگ نیست: `middlewares` هرگز ادمین را
 * بلاک نمی‌کند، پس دکمه‌ای که کاری نمی‌کند دروغ است.
 *
 * جست‌وجو **سمتِ سرور** است نه فیلترِ کلاینتی: صفحه‌بندی می‌شود، پس فیلترِ
 * محلی فقط صفحهٔ جاری را می‌گردد و کاربری که در صفحهٔ دوم است «پیدا نشد»
 * می‌گیرد — بدترین شکلِ نتیجهٔ غلط، چون شبیهِ جوابِ درست است.
 */
export default function Page() {
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const state = usePageData<UsersPage>('users', applied ? `q=${encodeURIComponent(applied)}` : '')
  const d = state.data

  return (
    <Shell active="05" cmd="./ctl users --list" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setApplied(q)}
          placeholder="tg id…"
          inputMode="numeric"
          style={{ width: 190 }}
        />
        <Btn onClick={() => setApplied(q)}>SEARCH</Btn>
        {applied && (
          <Btn
            onClick={() => {
              setQ('')
              setApplied('')
            }}
          >
            CLEAR
          </Btn>
        )}
        <Chip color="var(--zone)">{(d?.total ?? 0).toLocaleString('en-US')} total</Chip>
        <Chip color={d?.blocked ? C.warn : C.inkLo} border={d?.blocked ? '#3A2E14' : C.edgeChip}>
          {d?.blocked ?? 0} blocked
        </Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          page {(d?.page ?? 0) + 1}/{d?.pages ?? 1} · ix_users_last_seen
        </span>
      </div>

      <Section label="USERS" sigil="⧉" corners right={`${d?.rows.length ?? 0} shown`} pad="22px 14px 12px">
        <PageState state={state}>
          <Scroll>
            <div style={{ minWidth: 720 }}>
              <Head
                cols={[
                  { w: 108, label: 'TG ID' },
                  { w: 62, label: 'ROLE' },
                  { w: 62, label: 'FILES', right: true },
                  { w: 96, label: 'JOINED' },
                  { w: 118, label: 'LAST SEEN' },
                  { w: 78, label: 'STATE' },
                  { label: 'ACTION', right: true },
                ]}
              />
              {d?.rows.map((u, i) => (
                <Row key={u.tg} last={i === d.rows.length - 1}>
                  <span style={{ width: 108, color: C.inkHi }}>
                    {u.tg}
                    {u.admin && <span style={{ color: C.acc, marginLeft: 6, fontSize: 9 }}>◂adm</span>}
                  </span>
                  <span style={{ width: 62 }}>
                    <Chip color={u.admin ? C.acc : C.inkLo}>{u.role}</Chip>
                  </span>
                  <span style={{ width: 62, textAlign: 'right', color: C.inkLo }}>
                    {u.files.toLocaleString('en-US')}
                  </span>
                  <span style={{ width: 96, color: C.inkDim }}>{u.created}</span>
                  <span style={{ width: 118, color: C.inkDim }}>{u.seen}</span>
                  <span style={{ width: 78, color: u.blocked ? C.bad : C.acc }}>
                    {u.blocked ? '[BLOCKED]' : '[ ACTIVE]'}
                  </span>
                  <span style={{ flex: 1, textAlign: 'right' }}>
                    {u.admin ? (
                      <span style={{ color: C.inkFaint }}>—</span>
                    ) : (
                      <form method="post" action="/users/block" style={{ display: 'inline' }}>
                        <input type="hidden" name="id" value={u.id} />
                        <input type="hidden" name="action" value={u.blocked ? 'unblock' : 'block'} />
                        <Btn type="submit" danger={!u.blocked} style={{ padding: '3px 9px', fontSize: 9.5 }}>
                          {u.blocked ? 'UNBLOCK' : 'BLOCK'}
                        </Btn>
                      </form>
                    )}
                  </span>
                </Row>
              ))}
              {d && !d.rows.length && (
                <div style={{ padding: '18px 0', textAlign: 'center', color: C.inkFaint, fontSize: 10.5 }}>
                  NO MATCH
                </div>
              )}
            </div>
          </Scroll>
        </PageState>
      </Section>

      <div style={{ fontSize: 9.5, color: C.inkFaint, letterSpacing: '.06em' }}>
        blocking invalidates userscache:ver — the list you see after the redirect is fresh
      </div>
    </Shell>
  )
}
