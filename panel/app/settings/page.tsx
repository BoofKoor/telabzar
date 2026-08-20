'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { usePageData, type SettingsPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
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
  const state = usePageData<SettingsPage>('settings')
  const all = state.data?.groups ?? []
  const groups = all
    .map((g) => ({ ...g, rows: g.rows.filter((r) => !q || r.key.includes(q.toLowerCase())) }))
    .filter((g) => g.rows.length)

  const changed = all.flatMap((g) => g.rows).filter((r) => r.val !== r.def).length
  const total = state.data?.total ?? 0

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

      <PageState state={state}>
      <form method="post" action="/save" style={{ display: 'contents' }}>
      {groups.map((g) => (
        <Section key={g.title} label={<Fa>{g.title}</Fa>} sigil="⛭" right={`${g.rows.length} keys`} pad="22px 14px 12px">
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
                  <Select name={r.key} defaultValue={r.val} style={{ width: 150 }}>
                    {/* مقدارِ خالی یک گزینهٔ **واقعی** است (یعنی «تنظیم
                        نشده، از پیش‌فرض پیروی کن») ولی بدونِ برچسب، دراپ‌داون
                        خالی و شکسته به‌نظر می‌رسد. */}
                    {(r.enum ?? []).map((o) => (
                      <option key={o} value={o}>
                        {o === '' ? '— unset' : o}
                      </option>
                    ))}
                  </Select>
                ) : r.kind === 'bool' ? (
                  <Select name={r.key} defaultValue={r.val} style={{ width: 150 }}>
                    <option value="on">on</option>
                    <option value="off">off</option>
                  </Select>
                ) : (
                  <Input
                    name={r.key}
                    defaultValue={r.val}
                    placeholder={r.kind === 'str' ? '(empty)' : ''}
                    style={{ width: 150, textAlign: r.kind === 'int' ? 'right' : 'left' }}
                  />
                )}

                <span style={{ width: 110, color: C.inkFaint, fontSize: 10, flexShrink: 0 }}>
                  def {r.def === '' ? '—' : r.def}
                </span>

                <Fa style={{ flex: 1, minWidth: 0, color: C.inkDim, fontSize: 10.5 }}>{r.note}</Fa>

                {/* «برگرداندن به پیش‌فرض» یعنی خالی‌کردنِ فیلد و ذخیره؛
                    هندلرِ `save` مقدارِ برابرِ پیش‌فرض را reset می‌کند. */}
                {dirty && <span style={{ color: 'var(--zone)', fontSize: 9.5, flexShrink: 0 }}>◂ changed</span>}
              </div>
            )
          })}
        </Section>
      ))}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Btn type="submit" solid>
          APPLY
        </Btn>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkFaint, letterSpacing: '.1em' }}>
          bounds enforced in settings_store · the form is atomic — one bad value rejects the save
        </span>
      </div>
      </form>
      </PageState>
    </Shell>
  )
}
