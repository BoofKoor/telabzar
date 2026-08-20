import { C } from './theme'

/**
 * ناوبریِ ریل — **اعلانی**، تنها منبعِ ترتیب و شماره‌ها.
 *
 * ده آیتم، و این عدد تصادفی نیست: پنل دقیقاً ده صفحهٔ واقعی دارد
 * (داشبورد + ۹ تا)، پس ریلِ ده‌تاییِ طرح بدونِ اختراعِ صفحه یا پنهان‌کردنِ
 * یکی، مو‌به‌مو رویشان می‌نشیند. `QUEUE`/`CACHE`ِ ماکت صفحهٔ مستقل نبودند —
 * محتوایشان داخلِ HEALTH و TRAFFIC زندگی می‌کند و همان‌جا هم ماند.
 *
 * `href` به مسیرِ **کنسول** اشاره می‌کند نه صفحهٔ Jinja؛ `legacy` صفحهٔ
 * فارسیِ متناظر است تا تا وقتی فرم‌ها منتقل نشده‌اند راهِ برگشت باز بماند.
 */
export interface NavItem {
  n: string
  /**
   * سیجیلِ آیتم — یک نویسهٔ یونیکد که شکلش با کارِ صفحه می‌خواند.
   *
   * تزئین نیست: در ریلِ ده‌ردیفه چشم اول **شکل** را می‌گیرد و بعد متن را
   * می‌خواند، پس یک نشانهٔ متمایز جست‌وجوی خطی را به تشخیصِ آنی تبدیل
   * می‌کند. عمداً نویسهٔ متنی است نه SVG — همان فونتی که کلِ کنسول با آن
   * کشیده شده، بدونِ یک بایتِ اضافه.
   */
  sig: string
  label: string
  href: string
  legacy: string
  badge?: string
  badgeColor?: string
}

export interface NavGroup {
  group: string
  items: NavItem[]
}

export const NAV: NavGroup[] = [
  {
    group: 'SYSTEM',
    items: [
      { n: '01', sig: '◈', label: 'OVERVIEW', href: '/console/', legacy: '/' },
      { n: '02', sig: '⌁', label: 'TRAFFIC', href: '/console/traffic/', legacy: '/stats' },
      { n: '03', sig: '⏣', label: 'HEALTH', href: '/console/health/', legacy: '/health', badge: '5/6', badgeColor: C.warn },
      { n: '04', sig: '⎔', label: 'NODES', href: '/console/nodes/', legacy: '/nodes', badge: '1↓', badgeColor: C.bad },
    ],
  },
  {
    group: 'CONTROL',
    items: [
      { n: '05', sig: '⧉', label: 'USERS', href: '/console/users/', legacy: '/users' },
      { n: '06', sig: '⌬', label: 'COOKIES', href: '/console/cookies/', legacy: '/cookies', badge: '2!', badgeColor: C.warn },
      // پنلِ Jinja فرمِ تنظیمات را روی **خودِ `/`** رندر می‌کند (کارت‌های سلامت
      // بالای همان صفحه)، پس `legacy` این ردیف `/` است نه `/settings`. اولین
      // نسخهٔ همین فایل `/settings` نوشته بود و گاردِ ناوبری گرفتش.
      { n: '07', sig: '⛭', label: 'SETTINGS', href: '/console/settings/', legacy: '/' },
      { n: '08', sig: '⌸', label: 'STRINGS', href: '/console/strings/', legacy: '/texts' },
    ],
  },
  {
    group: 'PIPE',
    items: [
      { n: '09', sig: '⌘', label: 'KEYBOARD', href: '/console/keyboard/', legacy: '/buttons' },
      { n: '10', sig: '⟐', label: 'LANGS', href: '/console/langs/', legacy: '/langs', badge: '3', badgeColor: C.info },
    ],
  },
]
