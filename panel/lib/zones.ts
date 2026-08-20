import { C } from './theme'

/**
 * رنگِ ناحیه‌ای — لهجهٔ هر گروهِ منو.
 *
 * **چرا رنگ اضافه شد، و چرا این‌طور:** نسخهٔ اول تک‌رنگ بود (سبز، به‌علاوهٔ
 * چهار رنگِ وضعیت). با ده صفحه، تک‌رنگ یعنی هر صفحه شبیهِ بقیه است و
 * اپراتور باید عنوان را بخواند تا بفهمد کجاست. رنگ این‌جا **مکان** را
 * می‌گوید، نه تزئین می‌کند: SYSTEM سبز، CONTROL فیروزه‌ای، PIPE بنفش.
 *
 * سه‌تا، نه ده‌تا — یک رنگ به‌ازای هر صفحه یعنی هیچ رنگی معنا ندارد. و
 * سبز عمداً مالِ SYSTEM ماند چون هویتِ کلِ کنسول است و OVERVIEW جایی است
 * که بیشترین وقت آن‌جا می‌گذرد.
 *
 * **قیدِ سخت:** رنگِ ناحیه هرگز جای رنگِ **وضعیت** را نمی‌گیرد. قرمز/کهربایی
 * همه‌جا و در هر ناحیه‌ای همان معنا را دارند، وگرنه «قرمز» می‌شود چیزی که
 * باید تفسیر شود نه چیزی که دیده شود.
 */
export interface Zone {
  /** لهجهٔ اصلیِ ناحیه. */
  acc: string
  /** نسخهٔ کم‌رنگ، برای کادر و خطِ راهنما. */
  dim: string
  /** رنگِ درخشش (rgba)، چون `text-shadow` نمی‌تواند از hex بسازدش. */
  glow: string
  name: string
}

export const ZONES: Record<string, Zone> = {
  SYSTEM: { acc: C.acc, dim: C.accDim, glow: 'rgba(0,229,153,.45)', name: 'SYSTEM' },
  CONTROL: { acc: '#4CC9F0', dim: '#2A6F87', glow: 'rgba(76,201,240,.45)', name: 'CONTROL' },
  PIPE: { acc: '#C77DFF', dim: '#6E4488', glow: 'rgba(199,125,255,.45)', name: 'PIPE' },
}

/** ناحیهٔ هر شمارهٔ منو. */
export function zoneOf(n: string): Zone {
  const i = Number(n)
  if (i <= 4) return ZONES.SYSTEM
  if (i <= 8) return ZONES.CONTROL
  return ZONES.PIPE
}

/**
 * رنگِ هر پلتفرم — رادار، جدولِ پلتفرم و نرخِ دانلود از یک نگاشت می‌خوانند.
 *
 * تا پیش از این همه‌شان سبز بودند، یعنی رادارِ هفت‌ضلعی هفت رأسِ هم‌رنگ
 * داشت و «کدام رأس مالِ کیست؟» فقط از برچسب خوانده می‌شد. رنگ این‌جا
 * هم تزئین است هم داده.
 */
export const PLATFORM_HUE: Record<string, string> = {
  YOUTUBE: '#FF5C5C',
  INSTAGRAM: '#FF6FD8',
  SOUNDCLOUD: '#FF9F1C',
  X: '#D6E5DD',
  TIKTOK: '#4CC9F0',
  APARAT: '#C77DFF',
  OTHER: '#7C9189',
}

export const hueOf = (name: string) => PLATFORM_HUE[name.toUpperCase()] ?? C.acc
