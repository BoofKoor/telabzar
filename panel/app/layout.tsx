import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'telabzar · console',
  description: 'پنلِ مدیریتِ تل‌ابزار',
}

export const viewport: Viewport = {
  themeColor: '#04070A',
  width: 'device-width',
  initialScale: 1,
}

/**
 * `dir="ltr"` عمدی است و از طرح می‌آید: این صفحه یک کنسولِ عملیاتی است و
 * محتوایش (مسیرها، نامِ سرویس، هگز، شناسه) تماماً لاتین است. صفحاتِ فارسیِ
 * پنل جداگانه‌اند و RTLِ خودشان را دارند.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body>{children}</body>
    </html>
  )
}
