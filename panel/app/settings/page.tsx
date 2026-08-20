'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { SETTINGS } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Btn, Chip, Fa, Input, Select } from '@/components/ui'

/**
 * ۰۷ SETTINGS — ‏۶۷ کلیدِ زمانِ‌اجرا، گروه‌بندی‌شده.
 *
 * شکلِ صفحه از یک تصمیم می‌آید: این‌جا **دامپِ پیکربندی** است نه فرمِ وب.
 * پس هر ردیف `key = value` است با پیش‌فرض کنارش، و کلیدِ عوض‌شده با یک
 * نشانگرِ سبز و رنگِ روشن‌تر خودش را نشان می‌دهد — چون سؤالِ همیشگیِ اپراتور
 * «چه چیزی را دست زده‌ام؟» است، نه «این کلید چه می‌کند؟».
 *
 * `bool` تاگل نیست، `on`/`off` است: تاگل حالتِ سوم (پیش‌فرض) را پنهان
 * می‌کند، و در پنلی که «reset به پیش‌فرض» یک کنشِ واقعی است این پنهان‌کاری
 * گران است.
 */
export default function Page() {
  const [q, setQ] = useState('')
  const groups = SETTINGS.map((g) => ({
    ...g,
    rows: g.rows.filter((r) => !q || r.key.includes(q.toLowerCase())),
  })).filter((g) => g.rows.length)

  const changed = SETTINGS.flatMap((g) => g.rows).filter((r) => r.val !== r.def).length
  const total = SETTINGS.flatMap((g) => g.rows).length

  return (
    <Shell active="07" cmd="./ctl config --edit" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="grep key…"
          style={{ width: 220 }}
        />
        <Chip color="var(--zone)" border={C.edgeChip}>
          {changed} changed
        </Chip>
        <Chip>{total} keys</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, letterSpacing: '.1em', color: C.inkDim }}>
          live · no restart · cross-process via redis
        </span>
      </div>

      {groups.map((g) => (
        <Section key={g.title} label={g.title} sigil="⛭" right={`${g.rows.length} keys · ${g.tag}_*`} pad="22px 14px 12px">
          {g.rows.map((r, i) => {
            const dirty = r.val !== r.def
            return (
              <div
                key={r.key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '7px 0',
                  borderBottom: i === g.rows.length - 1 ? undefined : `1px solid ${C.edgeRow}`,
                  fontSize: 11,
                }}
              >
                <span style={{ width: 3, alignSelf: 'stretch', background: dirty ? 'var(--zone)' : 'transparent', flexShrink: 0 }} />
                <span style={{ width: 210, color: dirty ? C.inkHi : C.inkMid, flexShrink: 0 }}>{r.key}</span>

                {r.kind === 'enum' ? (
                  <Select defaultValue={r.val} style={{ width: 130 }}>
                    {r.enum!.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </Select>
                ) : r.kind === 'bool' ? (
                  <Select defaultValue={r.val} style={{ width: 130 }}>
                    <option value="on">on</option>
                    <option value="off">off</option>
                  </Select>
                ) : (
                  <Input
                    defaultValue={r.val}
                    placeholder={r.kind === 'str' ? '(empty)' : ''}
                    style={{ width: 130, textAlign: r.kind === 'int' ? 'right' : 'left' }}
                  />
                )}

                <span style={{ width: 34, color: C.inkFaint, fontSize: 10 }}>{r.unit ?? ''}</span>

                <span style={{ width: 96, color: C.inkFaint, fontSize: 10, flexShrink: 0 }}>
                  def {r.def === '' ? '—' : r.def}
                </span>

                <Fa style={{ flex: 1, minWidth: 0, color: C.inkDim, fontSize: 10.5 }}>{r.note}</Fa>

                {dirty && (
                  <button
                    type="button"
                    className="ghost-btn"
                    style={{
                      border: `1px solid ${C.edgeBtn}`,
                      background: 'transparent',
                      color: C.inkDim,
                      fontFamily: 'inherit',
                      fontSize: 9.5,
                      padding: '3px 7px',
                      cursor: 'pointer',
                      flexShrink: 0,
                    }}
                  >
                    RESET
                  </button>
                )}
              </div>
            )
          })}
        </Section>
      ))}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Btn solid>APPLY</Btn>
        <Btn>REVERT</Btn>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkFaint, letterSpacing: '.1em' }}>
          bounds enforced in settings_store, not here
        </span>
      </div>
    </Shell>
  )
}
