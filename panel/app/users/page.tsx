'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { USERS } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Btn, Chip, Head, Input, Row, Scroll } from '@/components/ui'

/**
 * ۰۵ USERS — فهرست، جست‌وجو، بلاک.
 *
 * ادمین‌ها ردیفِ کنش ندارند و این باگ نیست: `middlewares` هرگز ادمین را
 * بلاک نمی‌کند، پس دکمه‌ای که کاری نمی‌کند دروغ است.
 *
 * دو عددِ سربرگ (کل و بلاک‌شده‌ها) در پنلِ واقعی ~۹۶٪ هزینهٔ صفحه‌اند و
 * برای همین کش می‌شوند؛ این‌جا فقط نشان داده می‌شوند تا جای واقعی‌شان در
 * طرح معلوم باشد.
 */
export default function Page() {
  const [q, setQ] = useState('')
  const rows = USERS.filter((u) => !q || u.tg.includes(q))
  const blocked = USERS.filter((u) => u.blocked).length

  return (
    <Shell active="05" cmd="./ctl users --list" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="tg id…" inputMode="numeric" style={{ width: 190 }} />
        <Btn>SEARCH</Btn>
        {q && <Btn onClick={() => setQ('')}>CLEAR</Btn>}
        <Chip color="var(--zone)">{USERS.length.toLocaleString('en-US')} total</Chip>
        <Chip color={C.warn} border="#3A2E14">
          {blocked} blocked
        </Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          page 1/1 · ix_users_last_seen
        </span>
      </div>

      <Section label="USERS" sigil="⧉" corners right={`${rows.length} shown`} pad="22px 14px 12px">
        <Scroll>
          <div style={{ minWidth: 720 }}>
            <Head
              cols={[
                { w: 108, label: 'TG ID' },
                { w: 62, label: 'ROLE' },
                { w: 62, label: 'FILES', right: true },
                { w: 96, label: 'JOINED' },
                { w: 96, label: 'LAST SEEN' },
                { w: 78, label: 'STATE' },
                { label: 'ACTION', right: true },
              ]}
            />
            {rows.map((u, i) => (
              <Row key={u.tg} last={i === rows.length - 1}>
                <span style={{ width: 108, color: C.inkHi }}>
                  {u.tg}
                  {u.admin && <span style={{ color: C.acc, marginLeft: 6, fontSize: 9 }}>◂adm</span>}
                </span>
                <span style={{ width: 62 }}>
                  <Chip color={u.admin ? C.acc : C.inkLo}>{u.role}</Chip>
                </span>
                <span style={{ width: 62, textAlign: 'right', color: C.inkLo }}>{u.files.toLocaleString('en-US')}</span>
                <span style={{ width: 96, color: C.inkDim }}>{u.created}</span>
                <span style={{ width: 96, color: C.inkDim }}>{u.seen}</span>
                <span style={{ width: 78, color: u.blocked ? C.bad : C.acc }}>
                  {u.blocked ? '[BLOCKED]' : '[ ACTIVE]'}
                </span>
                <span style={{ flex: 1, textAlign: 'right' }}>
                  {u.admin ? (
                    <span style={{ color: C.inkFaint }}>—</span>
                  ) : (
                    <Btn danger={!u.blocked} style={{ padding: '3px 9px', fontSize: 9.5 }}>
                      {u.blocked ? 'UNBLOCK' : 'BLOCK'}
                    </Btn>
                  )}
                </span>
              </Row>
            ))}
          </div>
        </Scroll>
      </Section>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10.5, color: C.inkDim }}>
        <Btn style={{ opacity: 0.4 }}>◂ PREV</Btn>
        <span style={{ letterSpacing: '.1em' }}>page 1 of 1</span>
        <Btn style={{ opacity: 0.4 }}>NEXT ▸</Btn>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkFaint }}>
          blocking invalidates userscache:ver — the list you see after the redirect is fresh
        </span>
      </div>
    </Shell>
  )
}
