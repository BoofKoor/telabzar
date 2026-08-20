'use client'

import { C } from '@/lib/theme'
import type { ApiState } from '@/lib/api'

/**
 * وضعیتِ اتصالِ کنسول به `/api/console`.
 *
 * **چرا این کامپوننت اصلاً وجود دارد:** بدونش، شکستِ fetch یعنی صفحه اعدادِ
 * فیکسچر را نشان بدهد و اپراتور رویشان تصمیم بگیرد. §۷ همین رده را ثبت کرده
 * («fallbackی که بی‌صدا به دادهٔ بی‌مصرف تنزل کند از خطا بدتر است») و مصداقِ
 * ثبت‌شده‌اش هفته‌ها زنده ماند چون «هنوز چیزی برمی‌گرداند».
 *
 * پس سه حالت سه رندرِ متفاوت دارند و حالتِ `loading` هم عمداً دیده می‌شود:
 * صفحه‌ای که بی‌سروصدا عددِ نمایشی نشان بدهد و بعد یواشکی جایش را عوض کند،
 * همان ابهام را در پنجرهٔ کوتاه‌تری بازمی‌سازد.
 */
export function ApiBanner({ state }: { state: ApiState }) {
  if (state.status === 'ready') return null

  const loading = state.status === 'loading'
  const color = loading ? C.info : C.bad
  const edge = loading ? '#14303A' : '#3A1E1E'
  const bg = loading ? 'rgba(76,201,240,.06)' : 'rgba(255,92,92,.07)'

  return (
    <div
      role="status"
      style={{
        border: `1px solid ${edge}`,
        background: bg,
        color,
        padding: '9px 13px',
        fontSize: 10.5,
        letterSpacing: '.08em',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <span style={{ fontWeight: 700 }}>{loading ? '[ ···· ]' : '[ FAIL ]'}</span>
      {loading ? (
        <span>LOADING LIVE DATA — figures below are placeholders until this clears</span>
      ) : (
        <>
          <span>LIVE DATA UNAVAILABLE — every figure below is a placeholder, not your system</span>
          <span style={{ marginLeft: 'auto', color: C.inkDim, letterSpacing: 0 }}>{state.error}</span>
        </>
      )}
    </div>
  )
}

/**
 * سه حالتِ دادهٔ یک **صفحه**، در یک جا.
 *
 * همان قاعدهٔ بنر، یک پله پایین‌تر: تا داده نرسیده چیزی رندر نمی‌شود و روی
 * شکست، علت نوشته می‌شود — نه اینکه جدول با ردیف‌های نمایشی پر شود.
 */
export function PageState<T>({
  state,
  children,
}: {
  state: { status: string; data: T | null; error: string | null }
  children: React.ReactNode
}) {
  if (state.status === 'loading') {
    return (
      <div style={{ padding: '20px 0', textAlign: 'center', color: C.inkDim, fontSize: 10.5, letterSpacing: '.14em' }}>
        [ ···· ] LOADING
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div style={{ padding: '18px 0', textAlign: 'center', color: C.bad, fontSize: 10.5, lineHeight: 1.9 }}>
        <div style={{ letterSpacing: '.14em', fontWeight: 700 }}>[ FAIL ] COULD NOT LOAD</div>
        <div style={{ color: C.inkDim, fontSize: 10 }}>{state.error}</div>
      </div>
    )
  }
  return <>{children}</>
}

/**
 * نشانگرِ «این کارت منبعِ واقعی ندارد».
 *
 * برای پنلی است که در `gaps` نام برده شده — یعنی چیزی برای نشان‌دادن نیست و
 * کارت باید **علتش** را بگوید نه یک عددِ ساختگی. متن از خودِ سرور می‌آید تا
 * علت یک جا نوشته شود، نه یک کپیِ دومِ دست‌نویس در کلاینت.
 */
export function NoSource({ why }: { why: string }) {
  return (
    <div
      style={{
        padding: '14px 0',
        textAlign: 'center',
        color: C.inkFaint,
        fontSize: 10,
        lineHeight: 1.9,
        letterSpacing: '.06em',
      }}
    >
      <div style={{ color: C.inkDim, marginBottom: 3 }}>[ NO SOURCE ]</div>
      {why}
    </div>
  )
}
