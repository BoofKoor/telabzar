'use client'

import type { ReactNode } from 'react'
import { C } from '@/lib/theme'
import type { Range } from '@/lib/types'

/**
 * سربرگِ چسبان: خطِ فرمان با مکان‌نمای چشمک‌زن، کنترل‌های صفحه، نشانگرِ
 * LIVE، ساعت، و نوارِ متحرکِ رویدادها.
 *
 * مکان‌نما یک `<span>`ِ رنگی با `mx-blink` است، نه یک نویسه — چون نویسهٔ
 * `_` در فونتِ مونو ارتفاعِ ثابت ندارد و درخششِ `box-shadow` هم نمی‌گیرد.
 * نوارِ متحرک متن را **دو بار** رندر می‌کند و ۵۰٪ جابه‌جا می‌شود، وگرنه سرِ
 * حلقه یک پرشِ دیدنی می‌دهد.
 *
 * `cmd` خطِ فرمانِ هر صفحه است — همان چیزی که به کنسول حسِ «یک ابزار، چند
 * زیرفرمان» می‌دهد به‌جای «چند صفحهٔ بی‌ربط».
 */
export function Header({
  cmd,
  ranges,
  range,
  onRange,
  clock,
  ticker,
  extra,
}: {
  cmd: string
  ranges?: Range[]
  range?: Range
  onRange?: (r: Range) => void
  clock: string
  ticker: string
  extra?: ReactNode
}) {
  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 8,
        background: '#04070AF2',
        backdropFilter: 'blur(8px)',
        borderBottom: `2px solid ${C.edge}`,
      }}
    >
      <div style={{ padding: '11px 18px', display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 0, minWidth: 0, fontSize: 12 }}>
          <span style={{ color: C.acc, textShadow: '0 0 8px rgba(0,229,153,.4)' }}>root@telabzar</span>
          <span style={{ color: C.inkFaint }}>:</span>
          <span style={{ color: C.inkLo }}>/opt/telabzar</span>
          <span style={{ color: C.inkFaint }}>$&nbsp;</span>
          <span style={{ color: C.inkHi }}>{cmd}&nbsp;</span>
          <span
            style={{
              width: 7,
              height: 14,
              background: C.acc,
              display: 'inline-block',
              animation: 'mx-blink 1s step-end infinite',
              boxShadow: '0 0 8px rgba(0,229,153,.6)',
            }}
          />
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          {extra}

          {ranges && (
            <div style={{ display: 'flex', gap: 2 }}>
              {ranges.map((r) => {
                const on = r === range
                return (
                  <button
                    key={r}
                    type="button"
                    className="range-btn"
                    onClick={() => onRange?.(r)}
                    style={{
                      border: `1px solid ${on ? C.acc : C.edgeBtn}`,
                      background: on ? C.acc : 'transparent',
                      color: on ? C.bg : C.ink,
                      fontFamily: 'inherit',
                      fontSize: 10.5,
                      letterSpacing: '.12em',
                      padding: '5px 10px',
                      cursor: 'pointer',
                    }}
                  >
                    {r}
                  </button>
                )
              })}
            </div>
          )}

          <span
            className="mx-hide-s"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 10.5,
              letterSpacing: '.14em',
              color: C.acc,
            }}
          >
            <i
              style={{
                width: 6,
                height: 6,
                background: C.acc,
                display: 'inline-block',
                animation: 'mx-pulse 1.4s infinite',
                boxShadow: `0 0 7px ${C.acc}`,
              }}
            />
            LIVE
          </span>

          <span style={{ fontSize: 12, color: C.inkHi, letterSpacing: '.05em' }}>{clock}</span>
          <a
            href="/logout"
            className="mx-hide-s"
            style={{ fontSize: 10.5, color: C.inkLo, border: `1px solid ${C.edgeChip}`, padding: '3px 7px' }}
          >
            uid:10345298
          </a>
        </div>
      </div>

      <div
        style={{
          borderTop: `1px solid ${C.edgeHair}`,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          background: C.panelBar,
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            animation: 'mx-marquee 34s linear infinite',
            fontSize: 10.5,
            letterSpacing: '.06em',
            padding: '5px 0',
          }}
        >
          <span style={{ paddingRight: 40, color: C.inkDim }}>{ticker}</span>
          <span style={{ paddingRight: 40, color: C.inkDim }}>{ticker}</span>
        </div>
      </div>
    </header>
  )
}
