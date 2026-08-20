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
  sigil,
  right,
  rightColor = C.inkLo,
  /**
   * پیش‌فرض `var(--zone)` است نه یک hex: پوسته آن متغیر را روی ریشهٔ صفحه
   * می‌گذارد، پس **یک** خط در `Shell` رنگِ همهٔ سکشن‌های آن صفحه را عوض
   * می‌کند. جایگزینش پاس‌دادنِ رنگ به ده‌ها فراخوانی بود، یعنی همان
   * «قاعده‌ای که در N نقطه دست‌نویس شده».
   */
  labelColor,
  corners = false,
  edge = C.edge,
  bg = C.panel,
  pad = '22px 14px 12px',
  style,
  children,
}: {
  label: string
  /** نویسهٔ نشانه، پیش از نامِ سکشن. */
  sigil?: string
  right?: ReactNode
  rightColor?: string
  labelColor?: string
  /** گوشه‌های براکتیِ `◤◥◣◢` — فقط برای کارتِ کانونیِ هر صفحه. */
  corners?: boolean
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
          color: labelColor ?? 'var(--zone)',
        }}
      >
        [{' '}
        {sigil && (
          // سیجیل `span`ِ خودش را دارد چون در برچسبِ ۹٫۵پیکسلی با
          // `letter-spacing: .2em` گم می‌شود: نویسه‌های یونیکد از fallbackِ
          // سیستم می‌آیند و در آن اندازه ریز و بی‌وزن‌اند. کمی بزرگ‌تر و
          // بدونِ فاصله‌گذاری، هم دیده می‌شود هم ردیفِ برچسب را به هم نمی‌زند.
          <span style={{ fontSize: 11.5, letterSpacing: 0, verticalAlign: '-1px', marginInlineEnd: 5 }}>
            {sigil}
          </span>
        )}
        {label} ]
      </div>
      {corners && <Corners color={labelColor ?? 'var(--zone)'} />}
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

/**
 * گوشه‌های براکتی.
 *
 * عمداً فقط روی **کارتِ کانونیِ** هر صفحه: اگر همه بگیرند، دیگر هیچ‌کدام
 * برجسته نیست و فقط نویز اضافه شده. همان استدلالِ رنگِ ناحیه‌ای — نشانه
 * وقتی کار می‌کند که کمیاب باشد.
 */
function Corners({ color }: { color: string }) {
  const base = { position: 'absolute' as const, fontSize: 9, lineHeight: 1, color, opacity: 0.75 }
  return (
    <>
      <span style={{ ...base, top: 3, left: 3 }}>◤</span>
      <span style={{ ...base, top: 3, right: 3 }}>◥</span>
      <span style={{ ...base, bottom: 3, left: 3 }}>◣</span>
      <span style={{ ...base, bottom: 3, right: 3 }}>◢</span>
    </>
  )
}
