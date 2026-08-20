/**
 * دادهٔ نمایشیِ صفحاتِ غیرِداشبورد.
 *
 * **این‌ها شکلِ واقعیِ دادهٔ تل‌ابزارند، نه lorem ipsum:** نامِ کلیدها از
 * `settings_store.RUNTIME_KEYS` می‌آید، وضعیت‌های کوکی از `cookies.status_of`،
 * نقش‌های نود از `nodes.ROLES`، و متن‌ها از `locales/fa.py`. دلیلش این است که
 * یک طرح فقط وقتی قابلِ تأیید است که با **طولِ واقعیِ** داده رندر شده باشد —
 * صفحه‌ای که با نامِ کوتاهِ ساختگی زیبا به‌نظر می‌رسد، روی
 * `dl_ig_anon_enabled` یا یک برچسبِ فارسیِ بلند می‌شکند.
 *
 * وقتی `/api/console` ساخته شود، همین شکل‌ها از سرور می‌آیند و این فایل فقط
 * fallbackِ حالتِ خطا می‌شود.
 */
import { C } from './theme'

/* ── ۰۷ SETTINGS ─────────────────────────────────────────────────── */
export interface SettingRow {
  key: string
  val: string
  def: string
  kind: 'bool' | 'int' | 'str' | 'enum'
  enum?: string[]
  unit?: string
  note: string
}
export interface SettingGroup {
  title: string
  tag: string
  rows: SettingRow[]
}

export const SETTINGS: SettingGroup[] = [
  {
    title: 'DOWNLOADER',
    tag: 'dl',
    rows: [
      { key: 'downloader_enabled', val: 'on', def: 'on', kind: 'bool', note: 'کلیدِ اصلیِ دانلود از لینک' },
      { key: 'dl_allow_unknown', val: 'on', def: 'on', kind: 'bool', note: 'هاستِ ناشناخته به موتور برسد' },
      { key: 'dl_default_ux', val: 'quick', def: 'quick', kind: 'enum', enum: ['quick', 'probe'], note: 'منوی کیفیت یا بهترین' },
      { key: 'dl_ux_youtube', val: 'probe', def: 'quick', kind: 'enum', enum: ['quick', 'probe'], note: 'تنها کلیدِ غیرپیش‌فرضِ تولید' },
      { key: 'dl_max_size_mb', val: '2000', def: '2000', kind: 'int', unit: 'MB', note: 'سقفِ حجم پیش از آپلود' },
      { key: 'dl_max_duration_min', val: '0', def: '0', kind: 'int', unit: 'min', note: '۰ = بی‌سقف' },
      { key: 'dl_concurrency', val: '5', def: '3', kind: 'int', note: 'دانلودِ هم‌زمان' },
      { key: 'dl_max_cookie_tries', val: '5', def: '5', kind: 'int', note: 'سقفِ چرخشِ اکانت' },
      { key: 'dl_ig_anon_enabled', val: 'on', def: 'off', kind: 'bool', note: 'مسیرِ ناشناسِ اینستاگرام' },
      { key: 'dl_direct_enabled', val: 'on', def: 'on', kind: 'bool', note: 'موتورِ لینکِ مستقیم' },
      { key: 'dl_cache_enabled', val: 'on', def: 'on', kind: 'bool', note: 'تحویلِ آنی از file_id' },
      { key: 'proxy_url', val: '', def: '', kind: 'str', note: 'خروجیِ تمیز؛ خالی = مستقیم' },
    ],
  },
  {
    title: 'SESSION POOL',
    tag: 'ck',
    rows: [
      { key: 'ck_cap_instagram', val: '12', def: '12', kind: 'int', unit: '/h', note: 'سخت‌گیرترین سطل' },
      { key: 'ck_cap_youtube', val: '40', def: '40', kind: 'int', unit: '/h', note: '۰ = بی‌سقف' },
      { key: 'ck_min_gap_sec', val: '45', def: '45', kind: 'int', unit: 's', note: 'فاصلهٔ دو استفادهٔ یک اکانت' },
      { key: 'ck_warmup_days', val: '5', def: '5', kind: 'int', unit: 'd', note: 'اکانتِ تازه پله‌پله' },
      { key: 'ck_warmup_pct', val: '25', def: '25', kind: 'int', unit: '%', note: 'کفِ ظرفیتِ روزِ اول' },
      { key: 'ck_invalid_at', val: '3', def: '3', kind: 'int', note: 'شکستِ پیاپی تا «باطل»' },
      { key: 'cookie_alert_min', val: '2', def: '2', kind: 'int', note: 'زیرِ این عدد به ادمین DM' },
    ],
  },
  {
    title: 'ADULT CONTENT FILTER',
    tag: 'safety',
    rows: [
      { key: 'safety_enabled', val: 'on', def: 'on', kind: 'bool', note: 'کلیدِ اصلیِ فیلتر' },
      { key: 'safety_scan_pixels', val: 'on', def: 'on', kind: 'bool', note: 'لایهٔ سومِ NudeNet' },
      { key: 'safety_threshold', val: '62', def: '60', kind: 'int', unit: '%', note: 'آستانهٔ قطعیت' },
      { key: 'safety_video_frames', val: '5', def: '5', kind: 'int', note: 'نمونه در طولِ کلیپ' },
      { key: 'safety_strikes', val: '3', def: '0', kind: 'int', note: '۰ = مسدودیِ خودکار خاموش' },
    ],
  },
  {
    title: 'PROCESSING',
    tag: 'proc',
    rows: [
      { key: 'video_encoder', val: 'libx264', def: 'libx264', kind: 'enum', enum: ['libx264', 'h264_nvenc'], note: 'انکودرِ ویدیو' },
      { key: 'compress_speed', val: 'medium', def: 'medium', kind: 'enum', enum: ['fast', 'medium', 'slow'], note: 'preset' },
      { key: 'whisper_model', val: 'small', def: 'base', kind: 'enum', enum: ['tiny', 'base', 'small', 'medium', 'large-v3'], note: 'مدلِ رونویسی' },
      { key: 'max_file_mb', val: '2000', def: '2000', kind: 'int', unit: 'MB', note: 'سقفِ عملیات روی فایلِ دریافتی' },
      { key: 'daily_op_quota', val: '80', def: '50', kind: 'int', note: 'عملیاتِ روزانهٔ هر کاربر' },
    ],
  },
  {
    title: 'MATCHER',
    tag: 'match',
    rows: [
      { key: 'match_source', val: 'ytmusic', def: 'ytmusic', kind: 'enum', enum: ['ytmusic', 'youtube'], note: 'کاتالوگِ جست‌وجو' },
      { key: 'match_min', val: '55', def: '55', kind: 'int', unit: '/100', note: 'آستانهٔ پذیرش' },
      { key: 'match_max_tracks', val: '20', def: '20', kind: 'int', note: 'سقفِ ترکِ پلی‌لیست' },
      { key: 'match_meta', val: 'on', def: 'on', kind: 'bool', note: 'تگ‌گذاریِ خروجی' },
    ],
  },
]

/* ── ۰۵ USERS ────────────────────────────────────────────────────── */
export const USERS = [
  { tg: '10345298', role: 'admin', files: 1284, created: '2026-02-14', seen: '12:41:02', blocked: false, admin: true },
  { tg: '88210447', role: 'user', files: 412, created: '2026-03-02', seen: '12:38:55', blocked: false, admin: false },
  { tg: '50219933', role: 'user', files: 388, created: '2026-03-19', seen: '12:31:07', blocked: false, admin: false },
  { tg: '77410028', role: 'user', files: 209, created: '2026-04-08', seen: '11:58:44', blocked: false, admin: false },
  { tg: '21903355', role: 'user', files: 174, created: '2026-04-21', seen: '10:22:10', blocked: true, admin: false },
  { tg: '64100872', role: 'user', files: 151, created: '2026-05-03', seen: '09:47:32', blocked: false, admin: false },
  { tg: '39558120', role: 'user', files: 96, created: '2026-05-30', seen: '08:12:55', blocked: false, admin: false },
  { tg: '55120983', role: 'user', files: 74, created: '2026-06-11', seen: 'd-2 19:04', blocked: false, admin: false },
  { tg: '70023441', role: 'user', files: 41, created: '2026-07-02', seen: 'd-4 22:18', blocked: true, admin: false },
  { tg: '12907755', role: 'user', files: 12, created: '2026-08-09', seen: 'd-6 07:40', blocked: false, admin: false },
]

/* ── ۰۶ COOKIES ──────────────────────────────────────────────────── */
export interface CookieAcct {
  file: string
  label: string
  status: 'healthy' | 'unproven' | 'suspect' | 'cooldown' | 'frozen' | 'invalid' | 'disabled'
  used: number
  cap: number
  lastOk: string
  err: string
  warm?: string
}
export const COOKIE_STATUS: Record<CookieAcct['status'], { flag: string; color: string }> = {
  healthy: { flag: '[ OK ]', color: C.acc },
  unproven: { flag: '[  ? ]', color: C.info },
  suspect: { flag: '[WARN]', color: C.warn },
  cooldown: { flag: '[COOL]', color: C.warn },
  frozen: { flag: '[HOLD]', color: C.violet },
  invalid: { flag: '[FAIL]', color: C.bad },
  disabled: { flag: '[ -- ]', color: C.inkFaint },
}
export const COOKIE_POOL: { platform: string; accounts: CookieAcct[] }[] = [
  {
    platform: 'instagram',
    accounts: [
      { file: 'cookies_instagram_main.txt', label: 'main', status: 'healthy', used: 7, cap: 12, lastOk: '02:41 ago', err: '' },
      { file: 'cookies_instagram_alt.txt', label: 'alt', status: 'cooldown', used: 12, cap: 12, lastOk: '18:20 ago', err: 'rate limited (429)' },
      { file: 'cookies_instagram_new.txt', label: 'new-3', status: 'healthy', used: 1, cap: 3, lastOk: '41:02 ago', err: '', warm: 'day 2/5 · 25%' },
    ],
  },
  {
    platform: 'twitter',
    accounts: [
      { file: 'cookies_twitter_a.txt', label: 'a', status: 'suspect', used: 4, cap: 20, lastOk: '1d 04:11 ago', err: 'JSONDecodeError - Expecting value' },
      { file: 'cookies_twitter_b.txt', label: 'b', status: 'invalid', used: 0, cap: 20, lastOk: '3d 12:40 ago', err: 'redirect to login page' },
    ],
  },
  {
    platform: 'youtube',
    accounts: [
      { file: 'cookies_youtube_1.txt', label: 'primary', status: 'healthy', used: 22, cap: 40, lastOk: '00:31 ago', err: '' },
      { file: 'cookies_youtube_2.txt', label: 'backup', status: 'unproven', used: 3, cap: 40, lastOk: '06:12 ago', err: 'The page needs to be reloaded.' },
      { file: 'cookies_youtube_old.txt', label: 'old', status: 'disabled', used: 0, cap: 40, lastOk: '14d ago', err: '' },
    ],
  },
  { platform: 'tiktok', accounts: [] },
  { platform: 'pinterest', accounts: [] },
  { platform: 'other', accounts: [] },
]

/* ── ۰۴ NODES ────────────────────────────────────────────────────── */
export const NODE_ROWS = [
  { id: 'n-dlfra', name: 'dl-fra', role: 'download', ip: '10.51.0.2', up: true, rtt: '42ms', jobs: 8, done: 12480, seen: 'now' },
  { id: 'n-prochel', name: 'proc-hel', role: 'processing', ip: '10.51.0.3', up: true, rtt: '31ms', jobs: 12, done: 4102, seen: 'now' },
  { id: 'n-edgethr', name: 'edge-thr', role: 'gateway', ip: '10.51.0.4', up: false, rtt: '—', jobs: 0, done: 880, seen: '14m ago' },
]

/* ── ۰۸ STRINGS ──────────────────────────────────────────────────── */
export interface StringRow {
  key: string
  fa: string
  en: string
  overridden: boolean
}
export const STRING_GROUPS: { title: string; n: number; rows: StringRow[] }[] = [
  {
    title: 'btn_*  ·  دکمه‌های کارت',
    n: 38,
    rows: [
      { key: 'btn_compress', fa: 'فشرده‌سازی', en: 'Compress', overridden: false },
      { key: 'btn_convert', fa: 'تبدیل فرمت', en: 'Convert', overridden: true },
      { key: 'btn_trim', fa: 'برش', en: 'Trim', overridden: false },
      { key: 'btn_watermark', fa: 'واترمارک', en: 'Watermark', overridden: false },
      { key: 'btn_transcribe', fa: 'رونویسی صوت', en: 'Transcribe', overridden: true },
    ],
  },
  {
    title: 'dl_*  ·  مسیرِ دانلود',
    n: 41,
    rows: [
      { key: 'dl_failed', fa: '❌ دانلود ناموفق بود', en: '❌ Download failed', overridden: false },
      { key: 'dl_retry_account', fa: 'اکانتِ دیگری را امتحان می‌کنم…', en: 'Trying another account…', overridden: false },
      { key: 'dl_login_unsupported', fa: 'این سرویس ورود لازم دارد و پشتیبانی نمی‌شود', en: 'This service needs a login we do not support', overridden: false },
      { key: 'dl_bad_link', fa: 'این لینک را نمی‌شناسم', en: 'I do not recognise this link', overridden: true },
    ],
  },
  {
    title: 'nsfw_*  ·  فیلترِ محتوا',
    n: 6,
    rows: [
      { key: 'nsfw_blocked', fa: 'این محتوا مجاز نیست 🔞', en: 'This content is not allowed 🔞', overridden: false },
      { key: 'nsfw_admin_report', fa: 'گزارشِ مسدودی برای ادمین', en: 'Block report for admin', overridden: false },
    ],
  },
]

/* ── ۰۹ KEYBOARD ─────────────────────────────────────────────────── */
export const KINDS = ['video', 'audio', 'image', 'document', 'pdf', 'archive'] as const
export interface KbButton {
  op: string
  text: string
  style: '' | 'primary' | 'success' | 'danger'
  width: 'full' | 'half' | 'third'
  hidden: boolean
  emoji: string
}
export const KEYBOARD: KbButton[] = [
  { op: 'compress', text: 'فشرده‌سازی', style: 'primary', width: 'half', hidden: false, emoji: '' },
  { op: 'convert', text: 'تبدیل فرمت', style: '', width: 'half', hidden: false, emoji: '5271604874419647061' },
  { op: 'trim', text: 'برش', style: '', width: 'third', hidden: false, emoji: '' },
  { op: 'speed', text: 'سرعت', style: '', width: 'third', hidden: false, emoji: '' },
  { op: 'resize', text: 'تغییر ابعاد', style: '', width: 'third', hidden: false, emoji: '' },
  { op: 'watermark', text: 'واترمارک', style: 'success', width: 'half', hidden: false, emoji: '' },
  { op: 'screenshot', text: 'اسکرین‌شات', style: '', width: 'half', hidden: false, emoji: '' },
  { op: 'transcribe', text: 'رونویسی صوت', style: '', width: 'full', hidden: false, emoji: '' },
  { op: 'link', text: 'لینکِ دانلود', style: 'danger', width: 'half', hidden: false, emoji: '' },
  { op: 'rename', text: 'تغییر نام', style: '', width: 'half', hidden: false, emoji: '' },
  { op: 'scan', text: 'اسکنِ ویروس', style: '', width: 'full', hidden: true, emoji: '' },
]
export const WIDTH_CAP: Record<KbButton['width'], number> = { full: 1, half: 2, third: 3 }
export const STYLE_HEX: Record<string, string> = { primary: '#3b82f6', success: '#22c55e', danger: '#ef4444' }

/* ── ۱۰ LANGS ────────────────────────────────────────────────────── */
export const LANGS = [
  { code: 'fa', name: 'فارسی', builtin: true, keys: 214, total: 214, users: 1623 },
  { code: 'en', name: 'English', builtin: true, keys: 214, total: 214, users: 93 },
  { code: 'ar', name: 'العربية', builtin: false, keys: 198, total: 214, users: 41 },
  { code: 'tr', name: 'Türkçe', builtin: false, keys: 214, total: 214, users: 12 },
  { code: 'pt-BR', name: 'Português (BR)', builtin: false, keys: 121, total: 214, users: 2 },
]

/* ── ۰۲ TRAFFIC ──────────────────────────────────────────────────── */
export const OP_PERF = [
  { op: 'compress', n: 4820, ok: 98, p50: '22s', p95: '2m41s' },
  { op: 'convert', n: 3140, ok: 96, p50: '11s', p95: '1m18s' },
  { op: 'transcribe', n: 1290, ok: 91, p50: '1m04s', p95: '6m22s' },
  { op: 'trim', n: 1108, ok: 99, p50: '4s', p95: '19s' },
  { op: 'watermark', n: 902, ok: 99, p50: '7s', p95: '31s' },
  { op: 'zip_many', n: 611, ok: 97, p50: '9s', p95: '55s' },
  { op: 'rmbg', n: 388, ok: 94, p50: '14s', p95: '48s' },
]
export const TOP_ERRORS = [
  { n: 214, msg: 'instagram: rate limited (429) · cookie rotated' },
  { n: 118, msg: 'yt-dlp: Sign in to confirm you are not a bot' },
  { n: 74, msg: 'The page needs to be reloaded.' },
  { n: 51, msg: 'ffmpeg: moov atom not found · remux skipped' },
  { n: 22, msg: 'spotify: no YouTube match above threshold' },
]
export const FORMATS = [
  { ext: 'mp4', n: 12480, pct: 46 },
  { ext: 'mp3', n: 7120, pct: 26 },
  { ext: 'jpg', n: 3940, pct: 14 },
  { ext: 'pdf', n: 1880, pct: 7 },
  { ext: 'zip', n: 1090, pct: 4 },
  { ext: 'other', n: 900, pct: 3 },
]

/* ── ۰۳ HEALTH ───────────────────────────────────────────────────── */
export const ENGINES = [
  { who: 'master', gdl: '1.29.7', ytdlp: '2026.07.04', fresh: true },
  { who: 'dl-fra', gdl: '1.29.7', ytdlp: '2026.07.04', fresh: true },
  { who: 'proc-hel', gdl: '1.28.1', ytdlp: '2026.05.22', fresh: false },
]
export const DL_RATE = [
  { platform: 'youtube', ok: 41, fail: 6 },
  { platform: 'instagram', ok: 28, fail: 0 },
  { platform: 'soundcloud', ok: 11, fail: 1 },
  { platform: 'twitter', ok: 7, fail: 4 },
  { platform: 'tiktok', ok: 5, fail: 0 },
  { platform: 'castbox', ok: 3, fail: 0 },
]
export const STUCK = [
  { id: 1042, op: 'transcribe', status: 'running', age: '4d 02:11', file: 'lecture-07.m4a' },
  { id: 1188, op: 'compress', status: 'running', age: '2d 18:40', file: 'wedding-4k.mov' },
  { id: 1206, op: 'zip_many', status: 'queued', age: '1d 09:02', file: '— (collection)' },
]
