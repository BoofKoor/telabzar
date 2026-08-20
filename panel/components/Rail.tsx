'use client'

import { C } from '@/lib/theme'
import { NAV } from '@/lib/nav'

/**
 * ریلِ چپ: نامِ بلوکیِ ASCII، ناوبریِ شماره‌دارِ گروه‌بندی‌شده، درختِ WG،
 * بارشِ آنتروپی و پاورقیِ منابع.
 *
 * برندْ یک `<pre>` است نه یک `<h1>` — طرح آن را با نویسه‌های نیم‌بلوکِ
 * یونیکد می‌کشد و درخششش از `text-shadow` می‌آید. هر تلاشی برای
 * جایگزینی‌اش با متنِ ساده دقیقاً همان چیزی است که صفحه را از طرح دور کرد.
 */

const MESH = [
  { tree: 'master ─┬─', name: 'dl-fra', color: C.acc, meta: '42ms' },
  { tree: '├─', name: 'proc-hel', color: C.acc, meta: '31ms' },
  { tree: '└─', name: 'edge-thr', color: C.bad, meta: 'down' },
]

const groupLabel = { color: C.inkFaint, fontSize: 9, letterSpacing: '.22em' } as const

export function Rail({ rain, active }: { rain: { chars: string; dur: string }[]; active: string }) {
  return (
    <aside
      className="mx-rail"
      style={{
        borderRight: `2px solid ${C.edge}`,
        position: 'sticky',
        top: 0,
        height: '100vh',
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
        background: `linear-gradient(180deg,${C.panelRail},${C.bg})`,
      }}
    >
      <div style={{ padding: '14px 12px 12px', borderBottom: `1px solid ${C.edgeHair}` }}>
        <pre
          style={{
            fontFamily: 'inherit',
            fontSize: 9,
            lineHeight: 1.15,
            color: C.acc,
            textShadow: '0 0 9px rgba(0,229,153,.45)',
            letterSpacing: 0,
          }}
        >{`▀█▀ █▀▀ █   ▄▀█ █▄▄ ▀█ ▄▀█ █▀█
 █  ██▄ █▄▄ █▀█ █▄█ █▄ █▀█ █▀▄`}</pre>
        <div style={{ display: 'flex', gap: 6, marginTop: 9, fontSize: 9.5, letterSpacing: '.1em', color: C.inkDim }}>
          <span style={{ border: `1px solid ${C.edgeChip}`, padding: '1px 5px', color: C.acc }}>v1.0</span>
          <span style={{ border: `1px solid ${C.edgeChip}`, padding: '1px 5px' }}>D3</span>
          <span style={{ border: `1px solid ${C.edgeChip}`, padding: '1px 5px' }}>73988dc</span>
        </div>
      </div>

      <div className="mx-railnav" style={{ display: 'flex', flexDirection: 'column', gap: 1, padding: 8 }}>
        {NAV.map((g, gi) => (
          <div key={g.group} style={{ display: 'contents' }}>
            <div style={{ ...groupLabel, padding: gi === 0 ? '6px 7px 5px' : '12px 7px 5px' }}>▚ {g.group}</div>
            {g.items.map((it) => {
              const on = it.n === active
              return (
                <a
                  key={it.n}
                  href={it.href}
                  className={on ? undefined : 'nav-link'}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 7,
                    padding: '6px 7px',
                    fontSize: 11.5,
                    ...(on
                      ? {
                          color: C.bg,
                          background: C.acc,
                          fontWeight: 700,
                          boxShadow: '0 0 14px rgba(0,229,153,.28)',
                        }
                      : { color: C.ink, borderLeft: '2px solid transparent' }),
                  }}
                >
                  <span style={on ? undefined : { color: C.inkFaint }}>{it.n}</span>
                  {it.label}
                  {on && <span style={{ marginLeft: 'auto' }}>◂</span>}
                  {!on && it.badge && (
                    <span style={{ marginLeft: 'auto', color: it.badgeColor, fontSize: 10 }}>{it.badge}</span>
                  )}
                </a>
              )
            })}
          </div>
        ))}
      </div>

      <div className="mx-railextra" style={{ padding: '10px 12px', borderTop: `1px solid ${C.edgeHair}` }}>
        <div style={{ fontSize: 9, letterSpacing: '.2em', color: C.inkFaint, marginBottom: 7 }}>▚ WG MESH</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 9.5 }}>
          {MESH.map((m) => (
            <div key={m.name} style={{ display: 'flex', gap: 6 }}>
              <span style={{ width: 64, textAlign: 'right', color: C.inkDim }}>{m.tree}</span>
              <span style={{ color: m.color }}>{m.name}</span>
              <span style={{ marginLeft: 'auto', color: C.ink }}>{m.meta}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mx-railextra" style={{ padding: '10px 12px', borderTop: `1px solid ${C.edgeHair}` }}>
        <div style={{ fontSize: 9, letterSpacing: '.2em', color: C.inkFaint, marginBottom: 7 }}>▚ ENTROPY</div>
        <div style={{ height: 96, overflow: 'hidden', position: 'relative' }}>
          <div style={{ display: 'flex', gap: 5, position: 'absolute', inset: 0 }}>
            {rain.map((r, i) => (
              <pre
                key={i}
                style={{
                  fontFamily: 'inherit',
                  fontSize: 9,
                  lineHeight: 1.35,
                  color: '#1E6B54',
                  animation: `mx-rain ${r.dur}s linear infinite`,
                  whiteSpace: 'pre',
                }}
              >
                {r.chars}
              </pre>
            ))}
          </div>
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: `linear-gradient(180deg,${C.panelRail} 0%,transparent 30%,transparent 60%,${C.panelRail} 100%)`,
              pointerEvents: 'none',
            }}
          />
        </div>
      </div>

      <div
        style={{
          marginTop: 'auto',
          padding: '11px 12px',
          borderTop: `1px solid ${C.edgeHair}`,
          fontSize: 9.5,
          color: C.inkDim,
          lineHeight: 1.9,
        }}
      >
        <div>
          UPTIME <span style={{ color: C.inkMid }}>41d 06:12</span>
        </div>
        <div>
          LOAD <span style={{ color: C.inkMid }}>0.42 0.51 0.47</span>
        </div>
        <div>
          MEM <span style={{ color: C.inkMid }}>11.4/31.3G</span>
        </div>
      </div>
    </aside>
  )
}
