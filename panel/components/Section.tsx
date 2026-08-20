import type { CSSProperties, ReactNode } from 'react'
import { C } from '@/lib/theme'

/**
 * جعبهٔ سکشن با برچسبِ **روی خطِ کادر**.
 *
 * این همان جزئیاتی است که پاسِ قبل کاملاً از قلم افتاد و صفحه را از
 * «کنسول» به «کارتِ معمولی» تبدیل کرد: برچسب یک `<div>`ِ مطلق است که
 * `top:-8px` می‌نشیند و زمینه‌اش **رنگِ صفحه** است، پس خطِ ۲پیکسلیِ کادر را
 * دقیقاً پشتِ خودش می‌بُرد. کادر هم ۲ پیکسل است نه ۱ — کلِ وزنِ بصریِ طرح
 * از همین دو چیز می‌آید.
 */
export function Section({
  label,
  right,
  rightColor = C.inkLo,
  labelColor = C.acc,
  edge = C.edge,
  bg = C.panel,
  pad = '22px 14px 12px',
  style,
  children,
}: {
  label: string
  right?: ReactNode
  rightColor?: string
  labelColor?: string
  edge?: string
  bg?: string
  pad?: string
  style?: CSSProperties
  children: ReactNode
}) {
  return (
    <section
      style={{ position: 'relative', border: `2px solid ${edge}`, background: bg, padding: pad, ...style }}
    >
      <div
        style={{
          position: 'absolute',
          top: -8,
          left: 12,
          background: C.bg,
          padding: '0 8px',
          fontSize: 9.5,
          letterSpacing: '.2em',
          color: labelColor,
        }}
      >
        [ {label} ]
      </div>
      {right !== undefined && (
        <div
          style={{
            position: 'absolute',
            top: -8,
            right: 12,
            background: C.bg,
            padding: '0 8px',
            fontSize: 9.5,
            color: rightColor,
          }}
        >
          {right}
        </div>
      )}
      {children}
    </section>
  )
}
