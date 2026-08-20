import type { CSSProperties, ReactNode } from 'react'
import { C } from '@/lib/theme'

/**
 * قطعاتِ مشترکِ صفحاتِ کنسول.
 *
 * **قاعدهٔ فارسی، و چرا اجباری است:** محتوایِ خودِ ربات فارسی است (برچسبِ
 * دکمه‌ها، متن‌های رابط، توضیحِ تنظیمات) در حالی که خودِ کنسول LTR و مونو
 * است. فارسی داخلِ فونتِ مونو **حروفش به هم نمی‌چسبد**، و داخلِ یک جعبهٔ
 * `direction:ltr` هم ترتیبِ کلماتش برعکس می‌شود. پس هر جا دادهٔ فارسی رندر
 * می‌شود باید از `<Fa>` رد شود: فونتِ متنی + `dir="rtl"` + ایزولهٔ bidi.
 * این تنها راهِ داشتنِ یک کنسولِ لاتین با payloadِ فارسیِ درست است.
 */
export function Fa({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <bdi
      dir="rtl"
      style={{
        fontFamily: "'Vazirmatn','Segoe UI',Tahoma,sans-serif",
        unicodeBidi: 'isolate',
        ...style,
      }}
    >
      {children}
    </bdi>
  )
}

/** رشتهٔ لاتینِ خالص (مسیر، شناسه، نسخه) — ایزوله و LTR. */
export function Ltr({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <bdi style={{ direction: 'ltr', unicodeBidi: 'isolate', ...style }}>{children}</bdi>
}

/** ردیفِ ساده با خطِ جداکنندهٔ پایین — واحدِ تکرارشوندهٔ بیشترِ کارت‌ها. */
export function Row({
  children,
  gap = 9,
  pad = '5px 0',
  last = false,
  bg,
}: {
  children: ReactNode
  gap?: number
  pad?: string
  last?: boolean
  bg?: string
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap,
        padding: pad,
        borderBottom: last ? undefined : `1px solid ${C.edgeRow}`,
        fontSize: 11,
        background: bg,
      }}
    >
      {children}
    </div>
  )
}

/** سربرگِ ستون‌ها. */
export function Head({ cols }: { cols: { w?: number | string; label: string; right?: boolean }[] }) {
  return (
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
      {cols.map((c, i) => (
        <span
          key={i}
          style={{ width: c.w === undefined ? undefined : c.w, flex: c.w === undefined ? 1 : undefined, textAlign: c.right ? 'right' : 'left' }}
        >
          {c.label}
        </span>
      ))}
    </div>
  )
}

/** نوارِ نویسه‌ایِ `[███░░]` — همان چیزی که کلِ کنسول به‌جای progress bar دارد. */
export function Bar({ pct, width = 13, color = C.acc }: { pct: number; width?: number; color?: string }) {
  const on = Math.max(0, Math.min(width, Math.round((pct / 100) * width)))
  return (
    <span style={{ letterSpacing: '.04em', color: C.edgeGauge, whiteSpace: 'nowrap' }}>
      [<span style={{ color }}>{'█'.repeat(on)}</span>
      <span style={{ color: C.edgeGauge }}>{'█'.repeat(width - on)}</span>]
    </span>
  )
}

/** پرچمِ هم‌عرضِ `[ OK ]` — ستون می‌ماند چون فونت مونو است. */
export function Flag({ text, color }: { text: string; color: string }) {
  return <span style={{ color, width: 46, flexShrink: 0 }}>{text}</span>
}

/** تراشهٔ کوچکِ کادردار. */
export function Chip({ children, color = C.inkLo, border = C.edgeChip }: { children: ReactNode; color?: string; border?: string }) {
  return (
    <span style={{ border: `1px solid ${border}`, color, padding: '1px 5px', fontSize: 10, whiteSpace: 'nowrap' }}>
      {children}
    </span>
  )
}

/** دکمهٔ کنسول: پر (کنش اصلی) یا توخالی. */
export function Btn({
  children,
  solid = false,
  danger = false,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { solid?: boolean; danger?: boolean }) {
  const fg = danger ? C.bad : solid ? C.bg : C.ink
  return (
    <button
      type="button"
      className={solid ? undefined : 'ghost-btn'}
      {...rest}
      style={{
        border: solid ? 0 : `1px solid ${danger ? '#4A2020' : C.edgeBtn}`,
        background: solid ? C.acc : 'transparent',
        color: fg,
        fontFamily: 'inherit',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '.14em',
        padding: '6px 12px',
        cursor: 'pointer',
        ...rest.style,
      }}
    >
      {children}
    </button>
  )
}

/** ورودیِ متنی با ظاهرِ ترمینال. */
export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      style={{
        border: `1px solid ${C.edgeSoft}`,
        background: C.panelDeep,
        color: C.inkHi,
        fontFamily: 'inherit',
        fontSize: 11,
        padding: '5px 8px',
        outline: 'none',
        ...props.style,
      }}
    />
  )
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      style={{
        border: `1px solid ${C.edgeSoft}`,
        background: C.panelDeep,
        color: C.inkHi,
        fontFamily: 'inherit',
        fontSize: 11,
        padding: '4px 6px',
        outline: 'none',
        ...props.style,
      }}
    />
  )
}

/** جعبهٔ فرمانِ کپی‌کردنی. */
export function Cmd({ children }: { children: ReactNode }) {
  return (
    <pre
      dir="ltr"
      style={{
        fontFamily: 'inherit',
        fontSize: 10.5,
        lineHeight: 1.8,
        color: C.accHi,
        background: C.panelDeep,
        border: `1px solid ${C.edgeSoft}`,
        padding: '9px 11px',
        overflowX: 'auto',
        whiteSpace: 'pre',
      }}
    >
      {children}
    </pre>
  )
}

/** پیامِ «چیزی این‌جا نیست» — به‌جای کارتِ خالیِ گیج‌کننده. */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: '18px 0', textAlign: 'center', color: C.inkFaint, fontSize: 10.5, letterSpacing: '.1em' }}>
      {children}
    </div>
  )
}

/** جدولی که در عرضِ کم به‌جای شکستن، اسکرول می‌خورد. */
export function Scroll({ children }: { children: ReactNode }) {
  return <div style={{ overflowX: 'auto' }}>{children}</div>
}
