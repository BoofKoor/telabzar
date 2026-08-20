'use client'

import { useState } from 'react'
import { C } from '@/lib/theme'
import { KEYBOARD, KINDS, STYLE_HEX, WIDTH_CAP, type KbButton } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Btn, Chip, Fa, Input, Select } from '@/components/ui'

/**
 * ۰۹ KEYBOARD — چیدمانِ منوی کارتِ فایل.
 *
 * پیش‌نمایش از **همان** فهرست ساخته می‌شود که فرم ویرایشش می‌کند، پس
 * نمی‌تواند از آن واگرا شود. این عمدی است: Open Questions ثبت کرده که در
 * پنلِ فارسی قراردادِ کیبورد **هشت** کپیِ دست‌نویس بینِ JS و پایتون دارد و
 * هیچ تستی دو طرف را گره نمی‌زند. این‌جا دستِ‌کم سمتِ کلاینت یک منبع دارد.
 *
 * الگوریتمِ بسته‌بندی همان `keyboards._rows_from_widths` است: دکمه‌ها به
 * ترتیب پر می‌شوند و ردیف وقتی می‌شکند که ظرفیتِ عرض پر شود **یا** عرضِ
 * دکمهٔ بعدی فرق کند.
 */
function pack(items: KbButton[]): KbButton[][] {
  const vis = items.filter((b) => !b.hidden)
  const out: KbButton[][] = []
  let i = 0
  while (i < vis.length) {
    const cap = WIDTH_CAP[vis[i].width] ?? 3
    let j = i
    while (j < vis.length && j - i < cap && vis[j].width === vis[i].width) j++
    out.push(vis.slice(i, j))
    i = j
  }
  return out
}

export default function Page() {
  const [kind, setKind] = useState<(typeof KINDS)[number]>('video')
  const [items, setItems] = useState<KbButton[]>(KEYBOARD)

  const set = (op: string, patch: Partial<KbButton>) =>
    setItems((xs) => xs.map((b) => (b.op === op ? { ...b, ...patch } : b)))

  const move = (idx: number, dir: -1 | 1) =>
    setItems((xs) => {
      const j = idx + dir
      if (j < 0 || j >= xs.length) return xs
      const c = xs.slice()
      ;[c[idx], c[j]] = [c[j], c[idx]]
      return c
    })

  const rows = pack(items)
  const hidden = items.filter((b) => b.hidden)

  return (
    <Shell active="09" cmd={`./ctl keyboard --kind ${kind}`} bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            style={{
              border: `1px solid ${k === kind ? C.acc : C.edgeBtn}`,
              background: k === kind ? C.acc : 'transparent',
              color: k === kind ? C.bg : C.ink,
              fontFamily: 'inherit',
              fontSize: 10.5,
              letterSpacing: '.12em',
              padding: '5px 12px',
              cursor: 'pointer',
            }}
          >
            {k.toUpperCase()}
          </button>
        ))}
        <Chip color={C.acc} border={C.edgeChip}>
          {items.length - hidden.length} shown
        </Chip>
        {hidden.length > 0 && <Chip color={C.inkFaint}>{hidden.length} hidden</Chip>}
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          live · no restart
        </span>
      </div>

      <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 18, alignItems: 'start' }}>
        <Section label="LAYOUT" right="order · style · width · visibility" pad="22px 14px 12px">
          <div
            style={{
              display: 'flex',
              gap: 10,
              padding: '6px 0',
              fontSize: 9,
              letterSpacing: '.14em',
              color: C.inkDim,
              borderBottom: `1px solid ${C.edgeHair}`,
            }}
          >
            <span style={{ width: 40 }}>MOVE</span>
            <span style={{ width: 92 }}>OP</span>
            <span style={{ flex: 1 }}>LABEL</span>
            <span style={{ width: 96 }}>STYLE</span>
            <span style={{ width: 92 }}>WIDTH</span>
            <span style={{ width: 130 }}>EMOJI ID</span>
            <span style={{ width: 44 }}>SHOW</span>
          </div>

          {items.map((b, i) => (
            <div
              key={b.op}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 0',
                borderBottom: i === items.length - 1 ? undefined : `1px solid ${C.edgeRow}`,
                fontSize: 11,
                opacity: b.hidden ? 0.45 : 1,
              }}
            >
              <span style={{ width: 40, display: 'flex', gap: 2 }}>
                <button
                  type="button"
                  onClick={() => move(i, -1)}
                  style={{ border: 0, background: 'transparent', color: C.inkDim, cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
                >
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => move(i, 1)}
                  style={{ border: 0, background: 'transparent', color: C.inkDim, cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
                >
                  ▼
                </button>
              </span>
              <span style={{ width: 92, color: C.accHi }}>{b.op}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <input
                  value={b.text}
                  onChange={(e) => set(b.op, { text: e.target.value })}
                  dir="rtl"
                  style={{
                    width: '100%',
                    border: `1px solid ${C.edgeSoft}`,
                    background: C.panelDeep,
                    color: C.inkHi,
                    fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
                    fontSize: 12,
                    padding: '4px 8px',
                    outline: 'none',
                  }}
                />
              </span>
              <Select value={b.style} onChange={(e) => set(b.op, { style: e.target.value as KbButton['style'] })} style={{ width: 96 }}>
                <option value="">—</option>
                <option value="primary">primary</option>
                <option value="success">success</option>
                <option value="danger">danger</option>
              </Select>
              <Select value={b.width} onChange={(e) => set(b.op, { width: e.target.value as KbButton['width'] })} style={{ width: 92 }}>
                <option value="full">full</option>
                <option value="half">half</option>
                <option value="third">third</option>
              </Select>
              <Input
                value={b.emoji}
                onChange={(e) => set(b.op, { emoji: e.target.value })}
                placeholder="—"
                inputMode="numeric"
                style={{ width: 130, fontSize: 10 }}
              />
              <span style={{ width: 44 }}>
                <input type="checkbox" checked={!b.hidden} onChange={(e) => set(b.op, { hidden: !e.target.checked })} />
              </span>
            </div>
          ))}

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <Btn solid>SAVE LAYOUT</Btn>
            <Btn>RESET TO DEFAULT</Btn>
          </div>
        </Section>

        <Section label="TELEGRAM PREVIEW" right="as the user sees it" pad="22px 14px 14px">
          <div style={{ background: '#17212B', padding: 12, border: `1px solid ${C.edgeSoft}` }}>
            <div
              style={{
                background: '#182533',
                color: '#E9EDF0',
                padding: '9px 11px',
                fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
                fontSize: 12.5,
                marginBottom: 9,
              }}
              dir="rtl"
            >
              🎬 <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>clip-2026-08-20.mp4</bdi>
              <br />
              <span style={{ opacity: 0.7, fontSize: 11 }}>
                📦 <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>412 MB</bdi> · 🎞{' '}
                <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>1080p</bdi> · ⏱{' '}
                <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>04:12</bdi> ·{' '}
                <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate' }}>mp4</bdi>
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {rows.map((row, ri) => (
                <div key={ri} style={{ display: 'flex', gap: 4 }}>
                  {row.map((b) => (
                    <span
                      key={b.op}
                      dir="rtl"
                      style={{
                        flex: 1,
                        textAlign: 'center',
                        background: STYLE_HEX[b.style] || '#2B5278',
                        color: '#fff',
                        fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
                        fontSize: 12,
                        padding: '7px 4px',
                        borderRadius: 4,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {b.text}
                    </span>
                  ))}
                </div>
              ))}
              <div style={{ display: 'flex', gap: 4 }}>
                <span
                  dir="rtl"
                  style={{
                    flex: 1,
                    textAlign: 'center',
                    background: '#2B5278',
                    color: '#fff',
                    fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
                    fontSize: 12,
                    padding: '7px 4px',
                    borderRadius: 4,
                  }}
                >
                  بستن
                </span>
              </div>
            </div>
          </div>

          {hidden.length > 0 && (
            <div style={{ marginTop: 11, fontSize: 10, color: C.inkFaint, lineHeight: 1.8 }}>
              hidden and therefore not sent:{' '}
              {hidden.map((b) => (
                <Fa key={b.op} style={{ marginLeft: 6 }}>
                  {b.text}
                </Fa>
              ))}
            </div>
          )}

          <div
            style={{
              borderTop: `1px solid ${C.edgeHair}`,
              marginTop: 11,
              paddingTop: 10,
              fontSize: 9.5,
              color: C.inkDim,
              lineHeight: 1.8,
            }}
          >
            premium emoji ids need the bot owner&apos;s account to have Telegram Premium; a wrong id
            makes Telegram reject the whole keyboard.
          </div>
        </Section>
      </div>
    </Shell>
  )
}
