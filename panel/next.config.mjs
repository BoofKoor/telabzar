/**
 * چرا `export` و نه سرورِ Node.
 *
 * قیدِ استقرار عوض نمی‌شود: `docker/admin.Dockerfile` فقط `COPY app` و
 * `COPY node` دارد و پنل یک پروسهٔ aiohttp است. اگر این اپ یک سرویسِ Node
 * جدا می‌شد، هم `docker-compose.yml` عوض می‌شد هم یک رانتایمِ تازه به
 * استقرار اضافه می‌شد — برای چیزی که در عمل یک داشبوردِ کلاینت-ساید است.
 *
 * پس خروجی **استاتیک** است: `next build` یک `out/` می‌دهد که عیناً زیرِ
 * `app/static/console/` می‌نشیند و همان aiohttp سرو می‌کند. یعنی صفر Node
 * در تولید، صفر تغییرِ compose، و احرازِ هویتِ فعلی (کوکیِ Fernet) دست‌نخورده
 * می‌ماند چون درخواستِ صفحه هم از همان میدل‌ورِ پنل رد می‌شود.
 *
 * `basePath`/`assetPrefix` روی `/console` است تا لینک‌های `_next/...` با
 * مسیرِ سرو یکی باشند؛ `images.unoptimized` لازم است چون بهینه‌سازِ تصویرِ
 * Next رانتایمِ Node می‌خواهد و ما نداریم.
 */
const basePath = process.env.PANEL_BASE_PATH ?? '/console'

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath,
  assetPrefix: basePath,
  trailingSlash: true,
  reactStrictMode: true,
  images: { unoptimized: true },
  // خروجیِ استاتیک نامِ فایلِ هش‌دار می‌دهد؛ این فقط برای خوانا ماندنِ دیف است.
  productionBrowserSourceMaps: false,
}

export default nextConfig
