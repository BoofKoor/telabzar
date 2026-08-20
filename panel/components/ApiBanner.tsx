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
