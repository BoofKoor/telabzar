import { C } from '@/lib/theme'

/** پاورقیِ کلیدهای میان‌بر. */
export function Footer({ statusLine }: { statusLine: string }) {
  const keys: [string, string][] = [
    ['1-10', 'SECTION'],
    ['R', 'RANGE'],
    ['/', 'FILTER'],
    ['F', 'FREEZE'],
    ['Q', 'LOGOUT'],
  ]
  return (
    <footer
      style={{
        marginTop: 'auto',
        borderTop: `2px solid ${C.edge}`,
        background: C.panelBar,
        padding: '9px 18px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        flexWrap: 'wrap',
        fontSize: 10,
        letterSpacing: '.1em',
        color: C.inkLo,
      }}
    >
      {keys.map(([k, v]) => (
        <span key={k}>
          <b style={{ color: C.bg, background: C.acc, padding: '1px 5px' }}>{k}</b> {v}
        </span>
      ))}
      <span style={{ marginLeft: 'auto', color: C.ink }}>{statusLine}</span>
    </footer>
  )
}

/**
 * دو لایهٔ روکش: خط‌های افقیِ CRT و درخششِ سوسوزن.
 *
 * `mix-blend-mode:multiply` روی لایهٔ اول باربر است — بدونش خط‌ها به‌جای
 * تیره‌کردن، روی محتوا خاکستری می‌کشند و کلِ صفحه مه‌آلود می‌شود.
 */
export function Scanlines() {
  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 30,
          background: 'repeating-linear-gradient(180deg,rgba(0,0,0,.26) 0 1px,transparent 1px 3px)',
          mixBlendMode: 'multiply',
        }}
      />
      <div
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 31,
          background: 'radial-gradient(120% 90% at 50% 45%,rgba(0,229,153,.05),transparent 60%)',
          animation: 'mx-flicker 5s infinite',
        }}
      />
    </>
  )
}
