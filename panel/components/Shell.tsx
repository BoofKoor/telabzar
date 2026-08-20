'use client'

import { useState, type ReactNode } from 'react'
import { C } from '@/lib/theme'
import { zoneOf } from '@/lib/zones'
import { useConsole } from '@/lib/useConsole'
import { useConsoleData, type ApiState } from '@/lib/api'
import { Rail } from './Rail'
import { Header } from './Header'
import { Footer, Scanlines } from './Chrome'
import { StatusBits } from './StatusBits'
import { ApiBanner } from './ApiBanner'
import type { Range } from '@/lib/types'

/**
 * پوستهٔ مشترکِ همهٔ صفحاتِ کنسول: ریل + سربرگ + نوارِ اعداد + پاورقی + روکش.
 *
 * **چرا پوسته خودش `useConsole` را صدا می‌زند و صفحه به آن دست نمی‌زند:**
 * ساعت، نوارِ متحرک، بارشِ آنتروپی و نوارِ وضعیت روی **هر** صفحه زنده‌اند و
 * همه از یک حلقه می‌آیند. اگر هر صفحه تایمرهای خودش را می‌ساخت، ده صفحه
 * می‌شد ده جفت تایمرِ دست‌نویس که فردا از هم واگرا می‌شوند — همان الگوی
 * «قاعده‌ای که در N نقطه کپی شده» که §۷ بارها ثبتش کرده. صفحه فقط
 * `children` می‌دهد و در صورتِ نیاز بازه را می‌گیرد.
 */
export interface ShellCtx {
  vals: ReturnType<typeof useConsole>['vals']
  setRange: ReturnType<typeof useConsole>['setRange']
  setHover: ReturnType<typeof useConsole>['setHover']
  /** حالتِ `/api/console` — صفحه باید هر سه حالت را متفاوت رندر کند. */
  api: ApiState
}

export function Shell({
  active,
  cmd,
  ranges,
  onRangeChange,
  headerExtra,
  bits = true,
  children,
}: {
  active: string
  cmd: string
  /** اگر صفحه بازهٔ زمانی دارد، دکمه‌هایش را در سربرگ نشان بده. */
  ranges?: boolean
  onRangeChange?: (r: Range) => void
  headerExtra?: ReactNode
  /** نوارِ اعدادِ بالای صفحه؛ صفحاتِ فرم‌محور لازمش ندارند. */
  bits?: boolean
  /**
   * تابع می‌گیرد نه فقط گره، تا صفحه بتواند از **همان** حلقهٔ زندهٔ پوسته
   * بخواند. اگر صفحه `useConsole` خودش را صدا می‌زد، دو حلقهٔ مستقل می‌شد و
   * عددِ صف در نوارِ بالا با عددِ همان صف در بدنهٔ صفحه فرق می‌کرد — یعنی
   * کنسول به خودش دروغ می‌گفت.
   */
  children: ReactNode | ((ctx: ShellCtx) => ReactNode)
}) {
  // ترتیب باربر است: اول بازه از حلقه خوانده می‌شود، بعد داده برای همان بازه
  // گرفته می‌شود، بعد همان داده به حلقه برمی‌گردد. یک `useConsole()`ِ دوم
  // این‌جا یعنی نوارِ بالا و بدنه دو عدد بدهند.
  const [range, setRangeLocal] = useState<Range>('7D')
  const api = useConsoleData(range)
  const { vals, setRange, setHover } = useConsole({ api: api.data })
  const z = zoneOf(active)

  return (
    <div
      dir="ltr"
      className="mx-shell"
      style={{
        display: 'grid',
        gridTemplateColumns: '226px minmax(0,1fr)',
        minHeight: '100vh',
        background: C.bg,
        color: C.ink,
        fontFamily: "'JetBrains Mono',ui-monospace,monospace",
        fontSize: 12,
        position: 'relative',
        // لهجهٔ ناحیه به‌شکلِ متغیر، تا سکشن‌ها بدونِ propـکشی برش دارند.
        ['--zone' as string]: z.acc,
        ['--zone-dim' as string]: z.dim,
        ['--zone-glow' as string]: z.glow,
      }}
    >
      <Rail rain={vals.rain} active={active} mesh={vals.mesh} generated={vals.generated} />

      <main style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Header
          cmd={cmd}
          ranges={ranges ? vals.ranges : undefined}
          range={vals.range}
          onRange={(r) => {
            setRange(r)
            setRangeLocal(r)
            onRangeChange?.(r)
          }}
          clock={vals.clock}
          ticker={vals.ticker}
          extra={headerExtra}
          accent={z.acc}
          glow={z.glow}
        />

        <div className="mx-pad" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 18 }}>
          {bits && <StatusBits bits={vals.statusBits} />}
          <ApiBanner state={api} />
          {typeof children === 'function' ? children({ vals, setRange, setHover, api }) : children}
        </div>

        <Footer statusLine={vals.statusLine} />
      </main>

      {vals.scanlines && <Scanlines />}
    </div>
  )
}

/** بازهٔ جاری، برای صفحاتی که خودشان هم به آن نیاز دارند. */
export { useConsole }
