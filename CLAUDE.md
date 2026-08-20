# CLAUDE.md

## MANDATORY WORKFLOW FOR ALL SESSIONS
1. Read this file completely before writing or modifying any code.
2. Read the linked files in docs/ when your task touches those areas.
3. After ANY change to code, dependencies, roles, schema, or commands,
   update the relevant section of this file in the SAME session,
   before considering the task complete.
4. Add a dated line to the Changelog section at the bottom of this file
   describing what changed and why.
5. If you find a discrepancy between this file and the actual code,
   the CODE is the truth — fix this file and flag it to the user.
6. Never delete existing sections; extend or correct them.

---

## 1. Project Overview
Telabzar (تل‌ابزار) is a bilingual (Persian default / English) Telegram file-toolbox bot.
Send a file → it detects the type and re-sends the file as a "card" with an inline op-menu
(compress, convert, watermark, trim, OCR, transcribe, merge, zip, …). Send a URL → it downloads
(yt-dlp / gallery-dl / Spotify→YouTube-match) and the result enters the **same** pipeline.
It runs against a self-hosted **local Bot API server** (files live on disk, ~2 GB upload ceiling),
with ARQ/Redis job queues, Postgres, ClamAV, and a web admin panel. Comments/docstrings are Persian;
all identifiers are English.

## 2. Architecture
Multiple processes over shared Redis + Postgres. Entry points:
- **Bot** (`python -m app`) — long-polling vs the local Bot API server (`app/__main__.py`).
- **Main worker** (`arq app.worker.WorkerSettings`) — queue `arq:queue`, runs `run_op`; also runs the orphan-job **reaper** (drains `arq:queue:proc` back to master when no processing node is live).
- **Download worker** — master runs `MasterDownloadWorkerSettings` (queue `arq:queue:dl:master`, via the compose `command:`); a **download node** runs `DownloadWorkerSettings` (queue `arq:queue:dl`). `routers/download.py:_dl_queue` sends `run_download` to `arq:queue:dl` when a download node is live (so it runs on the node's **clean IP**), else `arq:queue:dl:master`. No node → master does all downloads (zero regression). Both run `run_download`.
- **Gateway** (`python -m app.gateway`) — aiohttp file server for `/dl` + `/s` (stream) links.
- **Admin panel** (`python -m app.admin_web`) — aiohttp web panel, Telegram-code login.
- **Node** (optional, remote) — a **worker on another machine**, joined over WireGuard, consuming one of the master's queues and heartbeating to the master's Redis. Three roles today: **download** (`arq:queue:dl`, `DownloadWorkerSettings`), **processing** (`arq:queue:proc`, `ProcessingWorkerSettings` = `run_op` on a dedicated queue), and **gateway** (a public `/dl` + `/s` reverse proxy, `python -m app.gateway_node` — **not** an ARQ worker). Download/processing are workers run with `NODE_ROLE` set (`bot.py` flips to `is_local=False`; `worker.py` spawns a heartbeat); the gateway node runs `gateway_node.py` (its own heartbeat). Heavy CPU ops route to a live processing node at enqueue time (`ops._op_queue` + `nodes.OFFLOAD_OPS`); link/stream traffic points at a gateway node via the `stream_base` setting; no node → everything stays on the master (zero regression). Master-side glue in `app/nodes.py` + panel; see §Nodes below.

Request path: intake (`routers/files.py` file, `routers/download.py` URL) → card (`cards.py` +
`keyboards.py` + `callbacks.py` + FSM `states.py`) → enqueue ARQ (`routers/ops.py:_enqueue`,
`routers/download.py`) → worker (`tasks.py:run_op`→`_do_op`, `tasks_download.py:run_download`) →
processing (`processing.py`, `downloader.py`) → delivery (`cards.py`, or `gateway.py` for links).

| Module | Responsibility |
|---|---|
| `app/__main__.py` | Entry: DB wait, ARQ pool, long-polling; sets only `/start` visible |
| `app/bot.py` | `Bot`/`Dispatcher` factories; router order **start → admin → ops → download → files** |
| `app/config.py` | `Settings` (pydantic-settings) — all env vars; `admin_id_set` property |
| `app/db.py` | Async engine/sessionmaker; `init_models()` = `create_all` + lightweight `_MIGRATIONS` (no Alembic) |
| `app/models.py` | ORM: `User`, `File` (+`post_caption` = متنِ خامِ پستِ مبدأ، `platform` = پلتفرمِ مبدأ), `Setting`, `DownloadCache`, `Job`, `TextOverride`, `ButtonStyle`, `MenuButton`, `Node`, `Language` (زبانِ **افزوده‌شده** — فقط نامِ نمایشی؛ fa/en ردیف ندارند). `LANG_LEN = 16` = عرضِ **هر سه** ستونِ کدِ زبان (`User.lang`, `TextOverride.lang`, `Language.code`) |
| `app/middlewares.py` | `DataMiddleware`: per-update DB session, get/create user, inject `lang`+`is_admin`, block-gate |
| `app/routers/start.py` | `/start`، انتخابِ زبان، و منوهای کاربر (خوش‌آمد ↔ تنظیمات ↔ آموزش ↔ زبان). فهرستِ زبان از `i18n.available_languages()` می‌آید نه هاردکد؛ تفکیکِ «انتخابِ اول» از «تغییر از تنظیمات» از **حالتِ** `user.lang` مشتق می‌شود نه از callback |
| `app/routers/admin.py` | `/admin` (list/get/set/reset/health) + `/panel`, admin-only |
| `app/routers/files.py` | `on_file` intake → `File` row → card; text fallback |
| `app/routers/ops.py` | All op button/FSM handlers; `_enqueue`; `_op_queue` (routes heavy ops to a live processing node's `arq:queue:proc`); limits; collection (zip/merge/img_pdf/vjoin) flow |
| `app/routers/download.py` | URL intake, platform UX (probe/quick), dl limits, `Dl` menu |
| `app/keyboards.py` | `OPS_BY_KIND` menus, card/collection/download keyboards; `file_card_kb` applies the admin menu layout (order + hidden + per-button width→rows via `_rows_from_widths`); منوهای کاربر از دو فهرستِ **اعلانیِ** `HOME_ITEMS`/`SETTINGS_ITEMS` ساخته می‌شوند (`home_kb`/`settings_kb`/`back_kb` روی `_nav_kb`)، و `lang_keyboard(langs, lang, …)` فهرست را **پارامتر** می‌گیرد تا sync بماند |
| `app/callbacks.py` | Typed `CallbackData` factories (<64 B): `Act,Conv,Meta,Cmp,Wm,Rsz,Rot,Spd,Tr,Dl,Lang,Nav` |
| `app/states.py` | FSM states (rename, meta edit, watermark, trim, screenshot, collect, …) |
| `app/cards.py` | Send/update the card (file + keyboard), spawn new cards, progress note; **two caption views** — `card_caption()` (open: plain name + info line, no wrapper quote) and `post_view()` (collapsed: the source post's own text in a closed `<blockquote expandable>`), picked by `view_caption(collapsed=…)`; `_video_extra()` forwards duration/dims/cover to Telegram |
| `app/tasks.py` | `run_op` (ARQ) + `_do_op` op dispatch; live status ticker; `_localize()` resolves every input to a local path — disk path on the master, HTTP download on a remote node (the only remote-input seam); `_outgoing_paths()`+`_too_big_to_send()` = the upload-ceiling gate, one check ahead of all four delivery branches |
| `app/tasks_download.py` | `run_download` (ARQ): probe→menu / fetch→size-check→spawn; rich-post/album delivery |
| `app/processing.py` | ffmpeg/Pillow ops; `_run` subprocess contract (progress/cancel/`ProcessingCancelled`); `start_cancel_watcher`/`CancelWatch` = the **single** cancel-polling mechanism, shared with `downloader._run_dl` |
| `app/downloader.py` | Engine routing (`platform_of`/`engine_for`), yt-dlp/gallery-dl/cobalt, and the shared **match** path for DRM platforms (`download_matched` + `_resolve_reference` → `spotify_resolve` / `apple_resolve`), YT-match scorer; **direct-file engine** (`probe_direct`/`download_direct`/`is_direct_response`/`direct_filename`, `DirectTooLarge`) for plain download links; **کست‌باکس** (`castbox_ids`/`castbox_target` خالص و بی‌شبکه + `resolve_castbox` که گاردِ SSRF را سوار می‌کند) |
| `app/settings_store.py` | Runtime config: Postgres (durable) + Redis (live, read-through); `RUNTIME_KEYS`/`ENUM_VALUES` |
| `app/textstore.py` | Runtime UI overrides: bot texts/labels, per-op button `style`+`icon_emoji_id`, **and per-kind card menu layout** (`TextOverride`/`ButtonStyle`/`MenuButton`, Postgres) via one in-process dict reloaded on the Redis `txtver` counter; `validate(…, require_all_placeholders=)`, `clean_button()`, `get_menu_layout()`; **نوشتنِ دسته‌ای** `set_texts(lang, mapping, replace=)` (یک تراکنش، **یک** bump — نه `set_text` در حلقه)، `lang_texts()`, `drop_lang()`, و ثبتِ زبان (`languages`/`add_language`/`remove_language`) |
| `app/admin_web.py` | Web panel: settings/texts/buttons/health/users/stats/cookies/**nodes**/**langs**; `_languages()` = پوستهٔ نازک روی `i18n.available_languages()` (فقط `refresh_if_stale` را اضافه می‌کند؛ **سازنده از فاز C به `i18n` منتقل شد** چون ربات هم همان فهرست را می‌خواهد و نمی‌تواند این ماژول را import کند) + `_pick_lang()`؛ `/langs` + `/langs/{export,import,delete}`; `_rate_limit`/`_client_ip` = سقفِ نرخِ مسیرِ لاگین (per-admin **و** per-IP)؛ `_pot_health`/`_pot_refresh` = سلامتِ pot-provider از کش، با تازه‌سازیِ پس‌زمینه (هرگز روی مسیرِ درخواست)؛ `_users_cached` + شمارندهٔ نسخهٔ `userscache:ver`; `GROUPS` = ردیف‌های **برچسب‌خوردهٔ** فرمِ تنظیمات و `_setting_groups()` = همان به‌علاوهٔ گروهِ خودکارِ ته‌مانده‌های `RUNTIME_KEYS` (تنها منبعِ **هم** رندر **هم** `save()`); `_badge_of()` = کلاسِ بجِ وضعیتِ اکانت، تنها جایی که پیش‌فرضِ ناشناخته تعریف می‌شود; `_CSS` = فقط **خواندنِ** `app/static/css/panel.css` (طراحی آن‌جاست، نه این‌جا — §Panel UI)؛ `_TEMPLATE_DIR`/`_STATIC_DIR` هر دو به `__file__` لنگر می‌خورند و `..` ندارند; node join API (`/node/join`) + install-script (`/node/install.sh`) + `/node/peers` (WG peer config for host `wg-sync`, gated by `NODE_SECRET`); `console_page` + `_CONSOLE_DIR` = سرو کردنِ کنسولِ Next از `app/static/console/` (فقط HTML گِیتِ نشست دارد، دارایی‌ها نه)؛ `console_api` = دادهٔ **واقعیِ** کنسول روی `/api/console` (۴۰۱ می‌دهد نه ریدایرکت، و محاسبه را از `_stats_cached`/`_health` **قرض می‌گیرد** نه اینکه تکرار کند) + `_CONSOLE_GAPS` = فهرستِ **نام‌بردهٔ** پنل‌هایی که منبعِ واقعی ندارند، که در payload می‌رود تا صفحه به‌جای عددِ ساختگی علتش را نشان بدهد؛ `console_page_api` + `_CONSOLE_PAGES` = دادهٔ اختصاصیِ نُه صفحهٔ دیگر روی `/api/console/<page>` (نگاشتِ **صریح** است نه `getattr` روی نامِ صفحه، وگرنه یک مسیرِ کاربر هر تابعی را در ماژول صدا می‌زند)، و هر سازنده از همان تابعی می‌خواند که صفحهٔ Jinja می‌خواند — `_page_keyboard` مشخصاً `keyboards._resolved_menu`/`_rows_from_widths` را صدا می‌زند تا **کپیِ نهمِ** قراردادِ کیبورد ساخته نشود. **Preloads + per-page-refreshes `textstore`** so a restart never shows/saves defaults over real overrides |
| `panel/` (Next.js) | کنسولِ `/console` — **ده صفحه** به زبانِ طراحیِ واحد. `lib/nav.ts` تنها منبعِ ناوبری (و `legacy` هر ردیف به صفحهٔ Jinja متناظر گره خورده، با گاردِ دوطرفه)، `lib/zones.ts` سه لهجهٔ رنگیِ **مکان‌محور** (SYSTEM سبز / CONTROL آبی / PIPE بنفش) که پوسته به‌شکلِ `--zone` روی ریشه می‌گذارد و همه از همان می‌خوانند — به‌علاوهٔ `PLATFORM_HUE` که رنگِ هر پلتفرم را در رادار و جدول یکی نگه می‌دارد؛ **قیدِ سخت: رنگِ ناحیه هرگز جای رنگِ وضعیت را نمی‌گیرد** (خوب/هشدار/بد همیشه سبز/زرد/قرمز می‌مانند، وگرنه صفحهٔ بنفش خطا را بنفش نشان می‌دهد)، `lib/theme.ts` تنها منبعِ رنگ (عیناً از سورسِ طرح)، `lib/data.ts` ریاضیِ **قطعیِ** `noise/gauge/spark/bigRows`، `lib/pages.ts` دادهٔ نمایشیِ صفحاتِ دیگر، `lib/useConsole.ts` حلقهٔ زنده (دو تایمر، فقط بعد از mount)، `components/Shell.tsx` پوستهٔ مشترک که **تنها** حلقهٔ زنده را دارد و با render-prop به صفحه می‌دهد (دو حلقه یعنی عددِ نوارِ بالا با بدنه فرق کند)، `components/Section.tsx` جعبهٔ کادرِ ۲پیکسلی با برچسبِ **روی خط**، `components/ui.tsx` قطعاتِ مشترک — از جمله `<Fa>` که **هر** دادهٔ فارسی باید از آن رد شود (فونتِ متنی + `dir=rtl` + ایزوله؛ فارسیِ داخلِ مونو حروفش نمی‌چسبد). خروجی `output: 'export'` است، پس **صفر Node در تولید** — مرحلهٔ Node فقط در `docker/admin.Dockerfile` می‌دود |
| `app/nodes.py` | Distributed **master-side** node layer: `ROLES` (download, processing, gateway), `OFFLOAD_OPS`, `role_online()`, `reap_orphan_jobs()` (proc→master when no proc node) + `note_job_done()`/`reaped_count()` counters, signed one-time WireGuard join token, WG-IP allocation, live registry (Redis `node:{id}` heartbeat, 45 s TTL), WG peer add/remove + `render_peers()` (declarative peer config from the `Node` table), `node_config()` (join reply — worker roles carry `queue`+`settings`, service roles carry `command`) |
| `app/instagram_anon.py` | **مسیرِ ناشناسِ اینستاگرام — وصل، پشتِ `dl_ig_anon_enabled` (پیش‌فرض خاموش).** دو نیمه. **resolve** (فاز ۱، بی‌حالت و بدونِ کوکی): `resolve()` → رسانه یا `None`؛ `resolve_detailed()` همان به‌علاوهٔ `RungReport` هر رده و یک `verdict` (`ok`/`unsupported`/`blocked`/`network`). نردبون: oEmbed (تشخیصی، پیش‌فرض خاموش) → صفحهٔ `/embed/captioned/` با **دو زیرشاخهٔ ترتیبی** — `contextJSON.gql_data` و در صورتِ تهی‌بودن `<img class="EmbeddedMediaImage" srcset>`. **fetch** (فاز ۲): `download_anonymous()` → `InstagramAnonFetch(paths, caption, bucket)` — بایت‌ها را `downloader.download_direct` می‌کشد (ارثِ SSRF/پروکسی/سقفِ دولایه/cancel و بی‌اعتنا به `opts["cookies"]`)، هر آیتم در `<workdir>/igan/<NN>/`، ترتیب از **ساختِ** فهرست، سقفِ **تجمعی** و بودجهٔ زمانیِ `ANON_FETCH_BUDGET`. `BUCKETS` = چهار verdict + `skipped` + `fetch_failed`. سشن/SSRF از `downloader._direct_connector` می‌آید (یک سیاست، نه دو کپی) |
| `app/gateway.py` | `/dl` + `/s` file serving (Range, faststart-friendly, token→path cache) |
| `app/gateway_node.py` | **Gateway-node** (Phase N3): a public reverse proxy that forwards `/dl` + `/s` to the master's gateway over WG (streams body + Range/Content-Range/status), giving a clean streaming IP off the master. Needs no DB/bot (token resolves on master); own heartbeat (role `gateway`) |
| `app/security.py` | ClamAV INSTREAM scan |
| `app/safety.py` | فیلترِ محتوای بزرگسال — سه لایه: `check_url` (دامنه/TLD/کلیدواژه)، `check_meta`/`check_text` (`age_limit`ِ yt-dlp + عنوان/توضیحات/تگ/نامِ فایل)، `scan_file` (NudeNet روی onnxruntime؛ ویدیو = نمونهٔ چند فریم). `Policy`/`load_policy()` عکسِ فوریِ تنظیماتِ پنل، `report_block()` شمارش + گزارشِ ادمین + مسدودیِ خودکار |
| `app/filetypes.py` | `detect()` message→`FileInfo`; kind = image/video/audio/document/pdf/archive/app |
| `app/i18n.py` + `app/locales/{fa,en}.py` | `t(lang, key, **kw)` + message tables (keys must stay in parity). `CATALOG` = دو زبانِ **داخلی**؛ هر کدِ زبانِ دیگری هم کار می‌کند و فقط از `text_overrides` می‌آید. `default_text(lang, key)` = **تنها** پیاده‌سازیِ زنجیرهٔ fallback (کاتالوگِ خودِ زبان → `FALLBACK`=en → `DEFAULT`=fa → خودِ کلید) و پنل هم از همین می‌خواند؛ `BUILTIN_NAMES` = نامِ نمایشیِ fa/en؛ `available_languages()` (async) = **تنها سازندهٔ** فهرستِ «همهٔ زبان‌های در دسترس» (داخلی + افزوده) که هم ربات و هم `admin_web._languages` از آن می‌خوانند — خانه‌اش با جهتِ وابستگی تعیین شد، چون `routers/` نمی‌تواند `admin_web` را import کند و `textstore` نمی‌تواند `i18n` را |
| `app/langpack.py` | بستهٔ زبان (export/import): `normalize_code` (BCP 47، فرمت‌محور نه طول‌محور، با شکلِ کانونیک)، `TEXT_KEYS` (تنها فهرستِ کلیدها)، `effective_texts`, `build_pack`/`parse_pack` (پاکتِ JSON + بردباری نسبت به فنس/BOM)، `review()` → `Review` (خطای per-key، پوشش، شمارشِ changed/same). **خالص و بی‌دیتابیس**، تا jobِ اصلیِ تست بتواند بسنجدش (مثلِ `cookies.py` و `dl_active.py`) |
| `app/cookies.py` | استخرِ اکانتِ کوکی + **ورودیِ پیست** (`_normalize_cookie_text`/`_check_required`/`_save_cookie` — از پنل به این‌جا منتقل شدند تا رباتْ هم بتواند کوکی بپذیرد)؛ `classify_error()`/`needs_human()`، وضعیتِ `frozen` + `unfreeze()`/`needs_attention()`: محتوا روی دیسکِ مستر + آینهٔ Redis (نود)، متادیتا در Redis (`ckmeta:`), وضعیت (`healthy/suspect/invalid/cooldown/disabled`), `pick()` (اولویت + LRU + exclude برای چرخش), `materialize()`, `mark_ok/mark_fail` (کول‌داونِ پلکانی), `healthy_count`؛ **سهمیه** — `Limits`/`default_limits()`/`load_limits()` (عکسِ فوریِ مقادیرِ پنل) + ریاضیِ همگامِ `hourly_cap`/`warmup_factor`/`budget_of`/`over_budget`؛ **خواندنِ دسته‌ای** `_mget`/`get_metas`/`cooldowns` (تعدادِ فرمانِ `pick()` مستقل از تعدادِ اکانت) |
| `app/dl_active.py` | شمارشِ **خودترمیمِ** دانلودهای هم‌زمان: ZSETِ `dl:active:z` با مهرِ زمانِ سرورِ Redis + `enter`/`leave`/`keepalive`/`count`. عمداً بی‌وابستگیِ سنگین، چون هم ورکرِ دانلود و هم پروسهٔ پنل از آن می‌خوانند |
| `app/dl_cache.py` | کشِ تحویلِ آنی: `_cache_url()` (نرمال‌سازیِ URL) + `cache_key`/`_legacy_key`، `put_cached` (**هر نوع فایل**)، `put_album_cached`/`collect_album_items` (کاروسل)، `deliver_from_cache` → bool (False = file_idِ باطل، ردیف پاک شد) |
| `app/probe_stats.py` | شمارندهٔ فازِ probe — هفت سطل زیرِ `dlstat:probe:<bucket>:<day>` با همان TTLِ دوروزهٔ `_metric`، به‌علاوهٔ نشانگرِ گذرای `probemenu:{ref}` که pick را dedupe می‌کند و cancelِ منو را از cancelِ فازِ fetch جدا می‌کند. عمداً **بی‌وابستگی** (مثلِ `dl_active.py`): هم ورکرِ دانلود می‌نویسد هم پروسهٔ ربات، و `routers/download.py` نمی‌تواند از `tasks_download` قرض بگیرد چون آن ماژول سرِ import `processing`/`instagram_anon` می‌آورد |
| `app/crud.py`, `app/exceptions.py` | DB helpers; `ProcessingCancelled` |

## 3. User Role Hierarchy
Two effective tiers only. There is **no** `owner`/`reseller` in code (see Open Questions).

| Role | Determined by | Can do | Enforced in |
|---|---|---|---|
| **admin** | `tg_user_id ∈ ADMIN_IDS` (env), surfaced as `is_admin` | everything a user can + `/admin`, `/panel`, web panel; never blocked | `middlewares.py:50`; `routers/admin.py:65,77`; `admin_web.py:_session_admin` (`admin_web.py:134`) |
| **user** | everyone else (default) | `/start`; send files → op card; send URLs → download | default path |
| *(blocked)* | `User.is_blocked = true` | nothing — no reply (admins are never blocked) | `middlewares.py:53`; set via web panel users page (`admin_web.py:858`) |

- `User.role` (`models.py:27`) exists but is **only ever set to `"user"`** (`middlewares.py:23`); no other value is written or read anywhere.
- **Commands:** `/start` (all; the only command registered via `set_my_commands`, `__main__.py:52`). `/admin` and `/panel` are admin-only and hidden (silent for non-admins, `routers/admin.py:65,77`). No other slash commands — everything else is file/URL messages + inline buttons.
- **Web panel auth:** login by entering an admin `tg_user_id`; a one-time code is DM'd via the bot; session is a Fernet cookie; every request re-checks membership in `admin_id_set`.

## 4. Tech Stack & Dependencies
Versions are read from the requirements files; do not edit from memory. Python (async) throughout.

**Base — `requirements.txt`** (all processes):
| Package | Pin | Why |
|---|---|---|
| aiogram | `>=3.30,<4` | Telegram bot framework (routers, FSM, CallbackData, local-server session) |
| SQLAlchemy[asyncio] | `>=2.0,<2.1` | Async ORM |
| asyncpg | `>=0.30,<0.32` | Postgres async driver |
| redis | `>=5.2,<6` | ARQ broker, FSM storage, settings live-store |
| pydantic-settings | `>=2.5,<3` | Env config (`config.Settings`) |
| arq | `>=0.26,<1` | Redis job queues (two workers) |

**Main worker — `requirements-worker.txt`** (base +):
| Package | Pin | Why |
|---|---|---|
| Pillow | `>=10,<12` | Image ops / dims |
| nudenet | `>=3.4,<4` | Adult-content detection (ONNX model, `app/safety.py`) |
| clamd | `>=1.0,<2` | ClamAV client |
| arabic-reshaper | `>=3.0,<4` | Persian text shaping (text watermark) |
| python-bidi | `>=0.4,<1` | RTL ordering |
| rembg | `>=2.0,<3` | Image background removal (u2net) |
| onnxruntime | `>=1.16,<2` | rembg model + whisper VAD (CPU) |
| faster-whisper | `>=1.0,<2` | Audio transcription (Whisper on CTranslate2) |

**Download worker — `requirements-worker-dl.txt`** (base +, slim image, no heavy processing stack):
| Package | Pin | Why |
|---|---|---|
| yt-dlp[default] | (unpinned) | Video/audio downloader + yt-dlp-ejs JS runtime |
| gallery-dl | (unpinned) | Image galleries/carousels (Instagram/Pinterest) |
| bgutil-ytdlp-pot-provider | (unpinned) | YouTube PO-token plugin |
| nudenet + onnxruntime | `>=3.4,<4` / `>=1.16,<2` | Adult-content scan must run where the download happens |
| aiohttp | (unpinned) | Spotify Web API + Cobalt HTTP |
| ytmusicapi | `>=1.8,<2` | YouTube Music "songs" search for precise Spotify matching |

**Admin panel — `requirements-admin.txt`** (base +): `jinja2 >=3.1,<4` (templates), `cryptography >=42,<46` (Fernet session).

**Infra images (`docker-compose.yml`):** `aiogram/telegram-bot-api:10.2` (pinned), `postgres:16-alpine`,
`redis:7-alpine`, `clamav/clamav:latest`, `brainicism/bgutil-ytdlp-pot-provider:latest`. The download-worker
image also installs **Deno** (yt-dlp JS runtime) + ffmpeg. See `docs/telegram-api.md` for Bot API version notes.

## 5. Conventions
- **Language:** English identifiers; Persian comments/docstrings. HTML parse mode (`bot.py:31`); escape user text with `html.escape`.
- **Handlers:** one aiogram `Router` per concern (`app/routers/`); register order in `bot.py:39` is load-bearing (ops text handlers are FSM-state-bound, so a pasted URL mid-FSM stays in the FSM; the URL front door sits after ops, before the `files` fallback).
- **Callbacks:** typed `CallbackData` factories in `callbacks.py`, kept **<64 bytes**; long option lists live in Redis and the callback carries only a short token (`ref`/`sel`).
- **The card is the file:** intake re-sends the file with an inline keyboard; the worker owns message mutation (edits caption/note via `cards.py`). Producing a new file spawns a new card (`tasks.py` spawn block).
- **Runtime config:** never read `settings.X` directly for a tunable value — read via `settings_store.get_int/str/bool(key, default)` so the admin panel/`/admin` take effect live (cross-process via read-through Redis). A panel-exposed key must appear in `settings_store.RUNTIME_KEYS` (and `ENUM_VALUES` if constrained) **and** in `admin_web.GROUPS`.
- **Errors:** best-effort side paths use `except Exception:  # noqa: BLE001`; cancellation raises `ProcessingCancelled` (poll a Redis `cancel:*` key); surface the real error tail to the user, never a bare traceback.
- **Adding an op (end-to-end):**
  1. `keyboards.py` → add `(op, "btn_label")` to `OPS_BY_KIND[kind]`; add `btn_label` (+ any strings) to **both** `locales/fa.py` and `locales/en.py`.
  2. `routers/ops.py` → handler: direct `_enqueue`, or a submenu (new `CallbackData` in `callbacks.py`), or an FSM flow (new state in `states.py`).
  3. `tasks.py:_do_op` → add the `if op == "…":` branch; return `{"path","filename","label","kind"}`. Resolve **every** input file_id via `_localize(bot, fid, workdir)` (never `get_file().file_path` directly) so the op runs on a remote node too. Reusing one of the four existing result shapes (`path`/`spawn`/`send_media`/`files`) is free — the upload-ceiling gate already covers it. Inventing a **new** shape that carries a file path means adding it to `tasks._BYTE_KEYS` **and** `tasks._outgoing_paths`, or the op skips that gate; `tests/test_upload_ceiling.py` discovers the shape set and goes red so this cannot happen quietly.
  4. `processing.py` → implement the work via the `_run` contract (`progress`, `cancel`, `ProcessingCancelled`).
  5. If tunable → `config.py` default + `settings_store.RUNTIME_KEYS` (+`ENUM_VALUES`) + `admin_web.GROUPS` row; read via `settings_store`.
  6. If it is CPU-heavy → add the op to `nodes.OFFLOAD_OPS` so it offloads to a live processing node (skip for light ops and anything needing a master-only service, e.g. `scan`/ClamAV).
- **Schema changes:** add the column to `models.py` **and** an idempotent `ALTER … IF NOT EXISTS` to `db.py:_MIGRATIONS` (no Alembic). A brand-new **table** needs no migration line — `create_all` creates it.
- **Panel UI — قالب‌ها در `app/templates/*.html` و طراحی در `app/static/css/panel.css`** (از ۲۰۲۶-۰۸-۱۹؛ پیش از آن رشته‌های پایتونی در `admin_web.py` بودند). CSS از فایل خوانده می‌شود ولی **همچنان درون‌خطی تزریق می‌شود** — رفتن به `<link>` هم بایتِ HTML را عوض می‌کند و هم سه خوانندهٔ `<style>`ِ همان پاسخ را می‌شکند (اندازه‌گیری‌شده ۱۵ تا ۱۹ شکست)، پس تغییرِ جداست. **هر دو زیرِ `app/` می‌مانند — قیدِ سخت:** `docker/admin.Dockerfile` فقط `COPY app` و `COPY node` دارد، پس دارایی بیرونِ `app/` در ایمیج نیست و پنل ۵۰۰ می‌دهد در حالی که CI سبز است (تست از ریشهٔ ریپو می‌دود). **و Jinja دقیقاً یک خطِ جدیدِ پایانی را می‌خورد**، پس فایلی با دو تا یک `\n` به هر صفحه اضافه می‌کند — هر دو گارد دارند (`tests/panel/test_template_files.py`). every class a template uses **must** exist in `panel.css` —
  an undefined class fails silently as an unstyled, zero-padding element (this is how `.pad`/`.hint`/`.tabs` shipped
  broken, and later `.err`/`.mute`/`.s-unproven`). **این قاعده از ۲۰۲۶-۰۸-۱۸ گارد دارد:**
  `tests/panel/test_panel_css_classes.py` هر ۹ صفحهٔ GET را با داده رندر می‌کند و هر کلاسِ خروجی را
  در `<style>`ِ همان پاسخ دنبال می‌کند — پس کلاسِ مردهٔ بعدی بدونِ یک خط تغییر در آن فایل گرفته
  می‌شود. کلاسِ **پویا** (مقداری که از پایتون می‌آید، مثلِ `_badge_of`) فقط وقتی پوشش دارد که
  تست شاخه‌اش را واقعاً بکارد؛ به همین دلیل fixtureِ `seeded` یک اکانت به‌ازای هر هفت وضعیت
  می‌سازد و تستِ جدا شاخهٔ **ناشناخته** را با وصلهٔ `status_of` می‌زند.
  Layout primitives: `.card` (+ `.card h3` header) with **either** `.rows` (list rows) or `.pad` (free content)
  as the body wrapper — never raw children, they go edge-to-edge. Vertical rhythm is **16px** (`.grid2`/`.col` gap,
  `.body>.card+.card`, `form>.card+.card`); horizontal card padding is **18px** everywhere. Shared chips/controls:
  `.tag`, `.chip`, `.badge`, `.tabs`/`.tab`, `.hint`, `.btn-sm`, `.btn-go` (primary), `.save`/`.save-sm`, `.inp`/`.sel`
  (both 160px). Responsive: the sidebar becomes a top nav under 860px; wide tables go in `.tbl-wrap`.
- **RTL is the default (`<html dir=rtl>`) — isolate every Latin/numeric run.** A date, size, IP, version or shell
  command dropped raw into RTL text gets **reordered** by the bidi algorithm (`2026-07-24 22:12` → `22:12 2026-07-24`,
  `975.0 MB` → `MB 975.0`). Wrap it in `<bdi>`, or use `.mono`/`.num`/`.ltr` (all `unicode-bidi:isolate`; `.num` and
  `.ltr` also force `direction:ltr`). **`.num`/`.ltr` are only for a *pure* LTR run** — putting mixed Persian+number
  text in them reorders the Persian instead. Code textareas (`.ta`, `.cmd`) additionally set `dir=ltr`.
- **User-facing strings are runtime-editable:** every string lives in `locales/{fa,en}.py` as the default and is overridable per-(lang,key) from the panel `/texts` page (`textstore`). Keep placeholders (`{n}`, …) stable when adding/renaming a string — the override validator rejects unknown placeholders, and `t()` silently falls back to the default if an override fails to format.
- **Adding a *language* is data, not code.** فقط `fa`/`en` کاتالوگِ کد دارند؛ هر زبانِ دیگری از پنل (`/langs`) import می‌شود و **صفر خطِ کد** لازم دارد — `t()` هیچ عضویت‌سنجی‌ای نمی‌کند و هر `(lang, key)`ی که override داشته باشد را می‌دهد. پس فهرستِ زبان‌ها باید همیشه از **`i18n.available_languages()`** بیاید، نه یک تاپلِ تازه — از فاز C این هم شاملِ **ربات** است (`routers/start.py`)، نه فقط پنل. **افزودنِ کلیدِ متن** همچنان کارِ کد است (`locales/{fa,en}.py`، با پاریتیِ کامل) و کلیدِ تازه برای زبان‌های افزوده خودبه‌خود **انگلیسی** رندر می‌شود تا وقتی بستهٔ تازه import شود.
- **هر رشتهٔ تازهٔ ربات باید در **هر دو** کاتالوگ باشد، و از ۲۰۲۶-۰۸-۱۹ گارد دارد.** پیش از آن هیچ assertی روی برابریِ مجموعهٔ کلیدها نبود و ادعای «۲۱۴ کلید، صفر یک‌طرفه» یک **اندازه‌گیریِ یک‌باره** بود. شکستش خاموش است: `langpack.TEXT_KEYS` **اجتماعِ** دو کاتالوگ است، پس کلیدِ یک‌طرفه رد نمی‌شود بلکه از زنجیرهٔ `en → FALLBACK → DEFAULT` رد می‌شود و **متنِ فارسی را داخلِ بستهٔ انگلیسی‌مبدأ** export می‌کند (اجراشده). `tests/test_locale_parity.py` سه چیز را کشف‌محور می‌سنجد: مجموعهٔ کلیدها (هر دو جهت)، مجموعهٔ placeholderها per-key، و توالیِ تگ‌های HTML per-key.

## 6. Environment & Deployment
**Env vars** (names only; source of truth = fields of `app/config.py:Settings`, env name = UPPER_SNAKE of each field):
- Required: `BOT_TOKEN`. Common: `ADMIN_IDS`, `DEFAULT_LANG`, `MAX_FILE_MB`, `LOCAL_API_BASE`, `REDIS_URL`, `POSTGRES_DSN`, `WORK_DIR`.
- **`.env.example` is a curated subset, not a dump, and it is test-guarded in both directions**
  (`tests/test_repo_hygiene.py`, phase 3a): every key in it must be either a `Settings` field or a var
  `docker-compose*.yml` actually consumes — the same rule applies to the `.env` that `install.sh`
  writes, so a dead key cannot come back through the installer either. In the other direction, every
  `Settings` field with **no default** must appear (discovered automatically; today only `BOT_TOKEN`),
  plus a deliberately short list of keys that do have defaults but without which a real deployment
  misbehaves: `PROXY_URL`, `ADMIN_SECRET`, `NODE_SECRET`, `PUBLIC_BASE`, `TLS_CERT`, `TLS_KEY`. Two
  keys were removed as dead: `WEBHOOK_SECRET` (nothing reads it — the bot long-polls) and `DOMAIN`
  (**an input to `install.sh` only**, used to build `PUBLIC_BASE` and the cert paths; the prompt stays,
  only the `.env` write is gone). A third was removed in phase 3ث for a different reason —
  `COOKIES_DIR=` was present with an **empty value**, and an empty value is not the same as an absent
  key: pydantic reads `""` and overrides the code default, so the file every new deployment copies
  re-armed the exact landmine the default fix had just removed. Compose sets `/cookies` explicitly on
  every service that reads or writes cookies, so the key was inert where it was set and harmful where
  it was not. The guard test now also fails if it comes back. The ~90 remaining fields are deliberately absent: they have sane
  defaults and are edited live from the panel (`settings_store.RUNTIME_KEYS`), not from this file.
- Processing: `VIDEO_ENCODER`, `COMPRESS_SPEED`, `COMPRESS_TINY_TARGET_MB`, `COMPRESS_TINY_HEIGHT`, `VJOIN_MAX_MB`, `WHISPER_MODEL`.
- Security/limits: `CLAMAV_HOST`, `CLAMAV_PORT`, `MAX_EXTRACT_FILES`, `MAX_EXTRACT_MB`, `DAILY_OP_QUOTA`, `RATE_PER_MIN`.
- Gateway: `PUBLIC_BASE`, `GATEWAY_PORT`, `TLS_CERT`, `TLS_KEY`, `STREAM_BASE` (runtime-tunable — when set, `/dl` `/s` links point at a gateway node instead of `PUBLIC_BASE`).
- Downloader: `DL_MAX_COOKIE_TRIES`, `DL_EXIT_COOLDOWN_MIN`, `DOWNLOADER_ENABLED`, `DL_ALLOW_UNKNOWN`, `DL_RICH_POSTS`, `PROXY_URL`, `COOKIES_DIR`, `POT_PROVIDER_URL`, `DL_POT_ENABLED`, `DL_DEFAULT_UX`, `DL_MAX_SIZE_MB`, `DL_MAX_DURATION_MIN`, `DL_DAILY_COUNT`, `DL_DAILY_MB`, `DL_CONCURRENCY`, `DL_COOLDOWN_SEC`, `DL_OP_DAILY_MIN`, `DL_MIN_FREE_GB`, `DL_DIRECT_ENABLED`, `DL_DIRECT_MAX_MB`, `DL_SPONSORBLOCK`, `DL_SUBS`, `COBALT_URL`, `COBALT_API_KEY`, `DL_IG_ANON_ENABLED`.
- Adult-content filter (all runtime-tunable, panel group «🔞 فیلترِ محتوای بزرگسال»): `SAFETY_ENABLED`, `SAFETY_SCAN_PIXELS`, `SAFETY_THRESHOLD` (percent), `SAFETY_VIDEO_FRAMES`, `SAFETY_NOTIFY_ADMIN`, `SAFETY_STRIKES` (`0` = off) + the panel-only `safety_block_domains` / `safety_allow_domains` lists.
- Session pool (all runtime-tunable, panel group «🧬 سهمیهٔ استخرِ سشن»): `COOKIE_ALERT_MIN`, `CK_CAP_INSTAGRAM`, `CK_CAP_YOUTUBE`, `CK_CAP_TWITTER`, `CK_CAP_TIKTOK`, `CK_CAP_DEFAULT` (hourly uses per account, `0` = uncapped), `CK_MIN_GAP_SEC`, `CK_WARMUP_DAYS`, `CK_WARMUP_PCT`, `CK_COOLDOWN_MIN`, `CK_RATE_COOLDOWN_MIN`, `CK_INVALID_AT`.
- DRM platforms (Spotify, Apple Music): `SPOTIFY_ENABLED`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `APPLE_ENABLED`. **`SPOTIFY_CLIENT_ID`/`SECRET` stay empty on purpose** — see the "Spotify Web API is closed to us" gotcha in §7 before spending time trying to obtain them. Apple needs no credential at all (`itunes.apple.com/lookup` is public).
- Matcher — **shared by every match platform**, which is why they are `MATCH_*` and no longer `SPOTIFY_*`: `MATCH_META`, `MATCH_MAX_TRACKS`, `MATCH_SOURCE`, `MATCH_MIN`, `MATCH_YT_FALLBACK`. A value stored under the old name **migrates itself** on first read (`settings_store._RENAMED`): it is written under the new name and the old row is deleted, so the warning fires once per key and then stops — a warning that never ends is one nobody reads. **That map is deletable once every live deployment has booted on this code**; until then every read of an *unset* renamed key costs one extra Redis GET, because the migrate path deliberately writes no negative cache (see §7).
- Panel: `ADMIN_PORT`, `ADMIN_BASE`, `ADMIN_SECRET`.
- Nodes — master side (one-time WG setup): `NODE_SECRET` (HMAC key for join tokens; falls back to `BOT_TOKEN`), `WG_INTERFACE` (`wg0`), `WG_SUBNET` (`10.51.0.0/24`), `WG_MASTER_IP` (`10.51.0.1`), `WG_MASTER_PUBKEY`, `WG_ENDPOINT` (`host:51820`), `WG_CONFIG_PATH` (`/etc/wireguard/wg0.conf`), and the internal addresses handed to nodes (`NODE_REDIS_URL`, `NODE_POSTGRES_DSN`, `NODE_API_BASE`, `NODE_POT_PROVIDER_URL`, `NODE_GATEWAY_URL` — all on the master's WG IP; the last is the master gateway a gateway node reverse-proxies to).
- Nodes — node side (set by `node/install.sh`, not by humans): `NODE_ROLE` (presence = "I am a node" → `is_local=False` + heartbeat), `NODE_ID`, `NODE_NAME`.
- Nodes — **master auto-provisioning**: don't hand-edit the WG/NODE vars — `node/master-setup.sh` (via `telabzar nodes-enable` or the installer prompt) generates the WG keypair, brings up `wg0`, autodetects the public IP, and **writes `WG_MASTER_PUBKEY`/`WG_ENDPOINT`/`WG_MASTER_IP`/`WG_CONFIG_PATH`/`NODE_SECRET` + all `NODE_*` (incl. `NODE_GATEWAY_URL`) into `.env`** automatically.
- The runtime-tunable subset (editable live via `/admin` or the web panel, no restart) = keys in `settings_store.RUNTIME_KEYS`.

**Run:** `docker compose up -d` (services: `local-bot-api`, `postgres`, `redis`, `clamav`, `bot`, `worker`,
`download-worker`, `gateway`, `admin`, `bgutil-pot-provider`; volumes: `tg-bot-api-data`, `pg-data`,
`redis-data`, `work-data`, `clamav-data`). Dockerfiles in `docker/`. Adding a Python dep to the download path
requires rebuilding **`download-worker`** (`docker compose build download-worker && docker compose up -d download-worker`).

**Master node infra (auto):** `install.sh` offers it at the end, or run `telabzar nodes-enable` (= `sudo node/master-setup.sh`) any time. It sets up WireGuard on the host + installs a `telabzar-wg-sync` systemd timer that reconciles WG peers from the `Node` table (declarative, self-healing — the panel just writes `Node` rows; the host timer applies them via `/node/peers`), and applies **`docker-compose.nodes.yml`** (overlay that publishes redis/postgres/local-bot-api/pot/gateway on `${WG_MASTER_IP}` — WG-only, not the public IP). The `telabzar` CLI auto-adds the overlay (`-f docker-compose.yml -f docker-compose.nodes.yml`) whenever `.nodes-enabled` exists, so `telabzar update` keeps the WG exposure. Standalone (no overlay) is unchanged — everything runs on the master.

**Tests:** `tests/` (pytest, committed) + `requirements-dev.txt` + `pytest.ini`. Run with
`pip install -r requirements-dev.txt && pytest`. `asyncio_mode = auto`, so `async def test_…` needs no
decorator. Conventions: **real over mock** — a real aiohttp server, a real `yt-dlp` stub script on `PATH`,
real subprocesses, `fakeredis` (real ZSET/TIME semantics). Only DNS records are faked, because an attacker's
A-record is not reproducible in a test. A test that needs ffmpeg/ffprobe is marked `@pytest.mark.ffmpeg`
and **skipped** when they are absent (`conftest.pytest_runtest_setup`). `tests/test_phase2b.py` is where
that marker finally earns its keep — from 2026-07 until phase 2b **no committed test carried it**, so the
hook protected nothing for months and nobody noticed. Two rules keep it honest. The marker goes on
**individual tests**, never on a module: the phase-2b tests that patch `_run` need no binary, and marking
the module would make the subtlest coverage vanish the day an ffmpeg install breaks. And the guard against
the marker going dead again is a **test** (`test_the_ffmpeg_marker_is_not_dead_weight`), not a CI step.
The reason recorded at the time was that with zero marked tests `pytest -m ffmpeg` deselects everything and
exits **0**, since exit code 5 meant "nothing collected", not "everything deselected". **That is no longer
true and the correction is worth more than the original claim:** measured on **pytest 9.1.1** (2026-08-17),
deselect-to-zero also exits **5**. The decision still stands — a test runs locally and a CI step does not —
but the premise moved under it, which is the general lesson: *pytest's exit-code semantics are a convention,
not a contract*, so anything load-bearing that rests on them needs its own pin. `tests/test_panel_path_is_alive.py`
does exactly that for the one this repo now depends on. `conftest.py` sets `BOT_TOKEN` at
module level — `config.Settings` requires it *at import time*, so a fixture would be too late. Every fix
should land with a test that fails on the pre-fix source.

**پوششِ رفتاریِ پنل یک مسیرِ جدا دارد، چون `app/admin_web.py` در محیطِ تست
import‌شدنی نیست.** آن ماژول سرِ import به `cryptography` و `jinja2` نیاز دارد که
فقط در `requirements-admin.txt`اند، و `requirements-dev.txt` عمداً ندارتشان. پس
`tests/panel/` تنها جایی است که اجازهٔ importشان را دارد و سه بندِ **مستقل** آن را
نگه می‌دارند: `addopts = --ignore=tests/panel` در `pytest.ini` (تا `pytest`ِ خالی و
jobِ اصلی سبز بمانند)، jobِ **موازیِ** `panel` در `tests.yml` که هر دو فایلِ
requirements را نصب و همان پوشه را اجرا می‌کند، و معافیتِ `_PANEL_DIR` در گاردِ
`_ADMIN_ONLY`. هر سه با `tests/test_panel_path_is_alive.py` به هم گره خورده‌اند —
که عمداً **بیرونِ** آن پوشه است، وگرنه با حذفِ jobِ پنل خودِ نگهبان هم می‌مرد.
دو قیدِ اندازه‌گیری‌شده که هارنس بر آن‌ها بنا شده: DSN از env قابلِ هدایت **نیست**
(`tests/conftest.py:17` زودتر ستش می‌کند و `app/db.py:53` موتور را سرِ import
می‌سازد)، پس نامِ `Sessionmaker` در **چهار** ماژولِ اندازه‌گیری‌شده وصله می‌شود؛ و
`settings.admin_id_set` یک propertyِ فقط‌خواندنی است، پس باید `admin_ids` ست شود.
مارکر جای این را نمی‌گیرد: `-m "not panel"` باز هم ماژول را import می‌کند و کلِ
ران با `Interrupted: 1 error during collection` می‌میرد.

**A sabotage run has two indistinguishable green outcomes, so the patch must assert that it
applied.** «Break the fix, run the suite, watch the right test fail» is the standard check here, and
its failure mode is that "20 passed" means either *the tests are worthless* or *the sabotage never
landed* — and from outside they look identical. The second happened twice: on `trim_video`/`trim_audio`,
whose shared *seek fragment* occurs twice so a `str.replace(..., 1)` edited the earlier one; and on
`del_meta`, whose target string had moved a few edits earlier. Both were reported green. A rule
forgotten twice will be forgotten a third time, so it is now structural rather than disciplinary:
`tests/sabotage.py` raises `SabotageError` unless the pattern matches **exactly** the expected number
of times, and restores the file in `finally`. It is self-tested (`tests/test_sabotage_helper.py`) —
a guard that cannot itself fail is the thing it exists to prevent. Nothing in the suite calls it
except that self-test; the suite must never rewrite source.
**And a sabotage is recorded as data, not run once and forgotten**, because a test proven
non-vacuous today can become vacuous tomorrow — which is exactly what happened to the `del_meta`
pattern. `tests/sabotage.CASES` holds each one (file, pattern, replacement, target test, the test
that must fail) and `python -m tests.sabotage [substring]` replays them all; a rotted pattern
surfaces as a loud `SabotageError` rather than a silent pass. It is **manual, never CI** — it
rewrites source, so a parallel run cannot be trusted. An entry with `expect: None` is a reverse
control: that sabotage must *not* fail the named test, which is how the trim case proves the
structural test targets `trim_video` and not its neighbour.
**The registry matches the failing test by name, so a `parametrize` id containing a space makes a
successful sabotage report itself as a miss.** `_run_case` reads pytest's summary and splits it on
whitespace, and pytest's *auto-generated* ids are built from the parameter values — so a case
parametrized over engine error strings produced ids like
`test_x[An unexpected error occurred: JSONDecodeError - …]`, which the splitter chopped at the
first space and could never match against `expect`. Measured on the first replay of the probe
cases: the sabotage landed, all five parametrizations failed exactly as intended, and the notebook
printed «نگرفت». The fix belongs in the **test**, not in the registry — pass explicit, space-free
`ids=[…]` — because a name that survives being split is also the name you grep for in CI output.
Note what class of error this is: not a weak assertion and not a sabotage that failed to apply
(the two failure modes above), but the **validation tool misreading a correct result** — and its
symptom is indistinguishable from "the tests are worthless", which is precisely the reading that
would make someone weaken a good test. When a case is parametrized, name it explicitly and point
`expect` at one specific id, the way the ig-anon story-link case already does.
**Two more instances of that same class, both found on 2026-08-18, and both were in the notebook
rather than in any test.** First: `_run_case` read only lines starting with `FAILED`, so a target
that **could not run at all** reported zero failures — indistinguishable from "the sabotage was not
caught". It fires on any panel-targeted case replayed from a venv without `requirements-admin.txt`:
`tests/panel/test_save_failures.py` produced **31 `ERROR` lines and zero `FAILED`**, and the
notebook printed «نگرفت» for a case that is perfectly healthy. "Could not run" is now a **third**
outcome with its own message, not a miss. Second, and it is the funnier one: the first fix for that
checked `"no tests ran" in r.stdout` as a plain substring, and a test that passes that very string
as *input* prints it inside pytest's traceback — so a completely healthy run was read as "the target
was empty". Both checks now match at **line start**, the same shape the `FAILED`/`ERROR` scan
already used. The general rule this hardens: **a harness that classifies another run's output must
key on that runner's own summary grammar, never on text that could have come from the payload** —
and the notebook needs its own reverse control (`test_a_genuine_miss_is_still_reported_as_a_miss`),
because a fix that translates every failure into "invalid" would silently retire the whole tool.
**And a case whose pattern appears in the registry entry itself matches twice.** Both new
notebook-targeting cases patch `tests/sabotage.py`, so their `old` string occurs once in `_run_case`
and once in the `CASES` literal a few hundred lines below. `count=1` caught it immediately —
the same self-reference that once made an AST guard match its own docstring. The fix is a
**two-line** pattern: the registry's copy stores `\n` as an escape, so only the real source carries
an actual newline and the anchor becomes unique.

**Every guard that scans text will eventually scan its own explanation of itself — three instances
now, in three different languages, and the general rule is worth more than any of them.** A guard
reads a file looking for evidence; prose *about* that evidence lives in the same file; so unless the
guard strips the commentary first, the guard's own documentation becomes the thing it counts.
Measured instances: `test_the_7z_gate_is_not_dead_weight` was a regex and matched the `@needs_7z`
written inside its **own docstring**, so removing the real decorator still passed; the same shape
recurred on a second AST guard; and on 2026-08-18 the panel's CSS-class guard read `.err` out of the
**Persian comment** written directly above the `.err` rule, because CSS comments ship inside
`<style>` and the checker was scanning raw stylesheet text. Note the third one is *not* a Python
problem — which is precisely why "use AST instead of regex" is the wrong lesson to draw. The right
one is about the input: **whatever language a guard scans, its input must be stripped of that
language's "text about code" — docstrings and comments for Python, `/* … */` for CSS, `{# … #}` for
Jinja, `<!-- … -->` for HTML — before a single pattern is applied.** AST parsing happens to satisfy
this for Python by accident (it hands you a tree, not the source text), which is why the first two
fixes looked like they were about parsers.
The failure mode is what makes this expensive rather than merely untidy: a self-matching guard is
**silently permanent-green**, and its sabotage reports "not caught" — indistinguishable from a weak
assertion, which is exactly the reading that gets a good guard deleted. So the negative control must
test the self-reference directly, not the feature: feed the checker a payload whose only mention of
the forbidden thing is inside a comment, and assert it is still reported missing
(`test_a_class_named_only_inside_a_css_comment_does_not_count`). A control that merely proves "the
checker can fail" does not cover this — the checker *can* fail; it just cannot fail on the one input
that its own source guarantees exists.
**A killed notebook run leaves the source patched, and every later measurement is then taken on a
corrupted tree.** §7 already says not to read `git status` *while* the notebook runs; this is the
harder version and it was learned by doing it. The first full replay of 2026-08-18 was started
through a tool call with a 10-minute cap, the cap killed the process mid-case, and `finally` never
ran — so `app/admin_web.py` kept a sabotage's replacement text (`for k in rendered:` instead of
`for k in sorted(rendered):`). The next full run then executed **125 cases against that corrupted
file**, which is why its result should have been thrown away rather than read. Two tells, and
neither is obvious: the corrupted case reports itself as a **rotted pattern** («الگو ۰ بار پیدا شد»)
because the source now holds the *replacement*, and everything else just quietly measures the wrong
tree. So: run the notebook **detached**, never under a timeout that can kill it; if a run is
interrupted for any reason, `git diff` the source tree and restore before believing anything; and
treat a lone "rotted pattern" on a case nobody edited as evidence of exactly this, not of drift.
**There is a third layer, and it is the subtlest: the helper proves the patch *applied*, not that
it broke what you meant to break.** Verifying the trim claim, the first sabotage moved `-ss`/`-to`
after `-i` but left a leading `-ss` in place; `patch_source` was satisfied, the file really did
change, and the structural test — which reads the *first* index of each flag — was still correct
to pass. Reported as "not caught" it would have looked like a weak assertion. So the three layers
of the same problem, in order of how hard they are to see: a test that asserts nothing; a sabotage
that never lands; and a sabotage that lands but breaks something adjacent. The first two now have
mechanisms (controls, `SabotageError`); the third has none and probably cannot — the only defence
is to assert the sabotaged state directly (`assert OUT in p.read_text()`), which is why the
registry's reverse-control entries matter: a case that is *expected* to leave a test green is the
one where a mis-aimed patch is indistinguishable from a correct one.
**And there is a fourth layer, distinct from all three: a sabotage that lands, breaks exactly what
it aimed at, and is *still* uncatchable — because a second defence covers the same path.** Where two
independent guards protect one route, a single-layer sabotage is inherently unprovable by an
end-to-end test: the end-to-end claim ("no job was created", "no request went out") stays true
because the surviving guard makes it true. From outside, that "not caught" is indistinguishable from
a weak assertion — which is exactly the reading that would make someone delete a good test. Seen
twice now. Instagram phase 1: breaking the `if cj` check failed nothing, because `isinstance(cj, str)`
independently stops `json.loads(None)`. Castbox: removing the URL **rebuild** failed nothing, because
`is_safe_url_resolved` rejected the payload anyway. The fix is not a better sabotage but a different
test shape — **prove each defence in isolation, at the level where it alone decides**, and keep the
end-to-end test as a third, separate claim whose sabotage removes *both* layers. Castbox does this
explicitly: `test_the_rebuild_alone_rejects_the_payloads` calls the pure function with no guard in
play, `test_the_guard_rejects_a_castbox_that_resolves_internal` poisons DNS so only the guard can
save it, and `test_the_ssrf_payloads_never_reach_the_engine` asserts the user-visible outcome. Three
sabotage entries, one per claim. The general rule: **defence in depth requires testing in depth** —
layered guards make an end-to-end suite feel strong while leaving each individual layer unproven, and
the day someone refactors one away, nothing goes red.

**پوششِ یک قالب را با **درشتیِ** سابوتاژ بسنج، وگرنه عددی می‌گیری که خوش‌بینانه
است — و اولین چیزی که باید از آن عدد کم کنی کفِ ضدِتوخالیِ گاردهای دیگر است.**
اندازه‌گیریِ ۲۰۲۶-۰۸-۱۹ روی پنل، پیش از هر بازآراییِ قالب. **(۱)** «بدنهٔ قالب را
کاملاً خالی کن» درشت‌ترین ویرایشِ ممکن است: تستی که آن را نگیرد قطعاً بی‌ارزش
است، ولی تستی که بگیرد لزوماً یک **بازآرایی** را نمی‌گیرد. سنجشِ **ریزدانه** —
یک واقعیتِ رندرشده را بردار — همان سوییت را از «۹ قالب همه نگهبان دارند» به
**۱۲ از ۱۳ حذفِ خاموش** برد: کلِ فهرستِ نودها، کلِ فهرستِ متن‌ها، کلِ ردیفِ
opها و کلِ کارتِ خطاها می‌توانستند ناپدید شوند و سوییت سبز بماند. ریسکِ واقعیِ
یک بازطراحی همین است، نه حذفِ کلِ بدنه. **(۲) و بخشی از عددِ درشت اصلاً پوششِ
محتوا نیست.** گاردِ کلاسِ CSS روی **هر هشت** صفحه با بدنهٔ خالی دقیقاً ۱۳ کلاس
(کلِ chromeِ قالبِ پایه) رندر می‌کند و روی `len(used) >= 15` می‌افتد، **هرگز**
روی `assert not missing` — یعنی یک چکِ «صفحه اصلاً ساخته شد؟» است و دربارهٔ
محتوا هیچ نمی‌گوید. شمردنش به‌عنوان نگهبانِ قالب پوشش را بیش از آنچه هست نشان
می‌دهد؛ کارِ واقعی‌اش (کلاسِ بی‌قاعده) جای خودش سرِ جایش است. قاعدهٔ عام: **پیش
از اینکه «این قالب N نگهبان دارد» را باور کنی، بپرس آن N تا روی چه چیزی
می‌افتند** — روی محتوا، یا روی کفِ ضدِتوخالیِ خودشان.

**و همان «گارد سرانجام توضیحاتِ خودش را می‌خواند» یک پله بالاتر هم اتفاق
می‌افتد: نثرِ خودِ *صفحه*.** سه نمونهٔ ثبت‌شدهٔ قبلی همه در **سورسِ** گارد بودند
(داکس‌استرینگ، کامنتِ CSS). نمونهٔ چهارم در **داده** بود: تستی که ادعا می‌کرد
کارتِ «پرکاربردترین عملیات» نامِ opها را می‌دهد، با خالی‌شدنِ کاملِ آن کارت هم
سبز ماند — چون متنِ توضیحیِ خودِ صفحه («عملیات یعنی کاری که روی یک فایل اجرا
شده (فشرده‌سازی، تبدیل، برش، …)») همان واژه‌ها را به‌عنوان **مثال** می‌نویسد، و
جدولِ همسایه هم همان برچسب‌ها را دارد. یعنی سه منبع برای یک توکن. **دور
ریختنِ کامنت کافی نیست؛ ادعا باید به ناحیه‌ای محدود شود که واقعاً دربارهٔ آن
است** — این‌جا کارت. هم‌ردهٔ آن، و اندازه‌گیری‌شده در همان پاس: متنِ یک دکمه در
`/buttons` **دو بار** رندر می‌شود (جعبهٔ ویرایش و پیش‌نمایشِ زنده)، پس سابوتاژِ
هر لایه به‌تنهایی هیچ ادعای انتها‌به‌انتهایی را نمی‌اندازد و «نگرفت»ش از بیرون
شبیهِ تستِ ضعیف است. هر دو با تفکیکِ لایه بسته شدند، یک سابوتاژ برای هرکدام.

**و نمونهٔ پنجم، که شکلِ تازه‌ای از همان است و در ۲۰۲۶-۰۸-۱۹ روی کدِ خودم
افتاد: تستی که انتظارش را از همان داده‌ای می‌سازد که سابوتاژ ویرایشش
می‌کند.** چهار نمونهٔ قبلی همه از جنسِ «متنِ توضیحی وارد ورودیِ گارد شد»
بودند؛ این یکی هیچ نثری در کار ندارد. منوهای کاربر از یک فهرستِ **اعلانی**
(`keyboards.HOME_ITEMS`) ساخته می‌شوند و تست نوشته بود
`assert got == [(FA[k], f"nv:{to}") for to, k in HOME_ITEMS]` — که برای
«برچسب از کاتالوگ می‌آید» و «ترتیب از فهرست می‌آید» ادعای درستی است و در
برابرِ بازچینش مقاوم، ولی وقتی سابوتاژ یک **آیتم را حذف** می‌کند، طرفِ
انتظار هم دقیقاً به‌اندازهٔ طرفِ واقعی کوچک می‌شود و تست سبز می‌ماند.
سابوتاژ گرفتش (چهار تستِ **دیگر** افتادند و تستِ نام‌برده نه)، نه بازخوانی.
**قاعدهٔ عام: هر ادعایی که از یک منبعِ اعلانی مشتق شود، *تغییرِ* آن منبع را
می‌گیرد ولی *کوچک‌شدنش* را نه — پس در کنارش یک ادعای لفظیِ جدا لازم است که
بگوید امروز چه چیزی باید باشد.** دو ادعا، دو کار: یکی «از کجا و به چه
ترتیبی»، دیگری «چه چیزی». همان تفکیکِ لایه‌ای که بندِ بالا برای `/buttons`
لازم داشت، این‌بار بینِ «مکانیزم» و «قرارداد» به‌جای بینِ دو رندر.

**و یک درسِ عملیاتی که §۷ نسخهٔ ملایم‌ترش را دارد: `nohup … &` را با اجرای
پس‌زمینهٔ هارنس ترکیب نکن.** پوستهٔ لفافه بلافاصله بیرون می‌آید، هارنس «تمام
شد» گزارش می‌کند، و پروسهٔ واقعی هنوز وسطِ کار است. نتیجه‌اش این شد که یک
`git status`ِ «بعد از اتمام» در واقع وسطِ اجرا گرفته شد و یک `git checkout`
سابوتاژِ در جریان را برداشت — دقیقاً همان چیزی که §۷ می‌گوید نکن. **و نکتهٔ
اصلی این است که از بیرون نمی‌شد فهمید کدام موردْ آلوده شده**، پس تنها کارِ
درست دورانداختنِ کلِ اجرا و تکرارِ آن بود؛ اجرای دوم هر ۹ عدد را عیناً
بازتولید کرد. کارِ پس‌زمینه را به خودِ هارنس بسپار تا واقعاً ردیابی‌اش کند.

**A timing or concurrency measurement means nothing until its harness is shown to be able to
fail — and sabotage cannot catch this class of error.** Sabotage asks "does my assertion notice a
broken implementation?"; it is silent when the *harness* is the thing that is broken, because there
the sabotaged run merely reports "not caught" and looks like a weak assertion rather than a dead
bench. What catches it is a **negative control**: run the unprotected version on the *same* harness
and show it actually fails. If it doesn't, the harness is not exercising the mechanism and every
green number it produced is worthless. Learned twice in one session from
`sqlite+aiosqlite:///:memory:`, which SQLAlchemy backs with a **single shared connection**, so
concurrent sessions multiplex onto one transaction and no write race can occur. It invented a
failure that did not exist (a `set()` retry "breaking at four writers") *and* hid a real one (the
same retry failing at two), and it wrongly convicted `textstore.set_menu_layout`, which on a
file-backed database never fails at all. Generalise past SQLite: any test backend that does not
model the mechanism under test — a fake clock for a timeout, a single-threaded executor for a
thread race, an in-process queue for a cross-process one — yields **both** false passes and false
failures, and only a negative control tells you which you are holding.

**و واگراییِ سندباکس از رانر فقط سرِ *بودن یا نبودنِ* یک بسته نیست — سرِ
**extra**هایش هم هست.** `requirements-worker-dl.txt` از `yt-dlp[default]` استفاده
می‌کند و `mutagen` عضوِ همان extra است، ولی یک `pip install yt-dlp`ِ ساده در
سندباکس آن را نمی‌آورد. نتیجه: هر اندازه‌گیریِ محلی دربارهٔ زنجیرهٔ
`EmbedThumbnailPP` (که برای `ogg/opus/flac` بی‌mutagen raise می‌کند و برای
`m4a` لایهٔ mutagen را اول امتحان می‌کند) در سندباکس **پاسخِ متفاوتی از تولید**
می‌دهد. **و این ردهٔ تازه‌ای است، نه نمونهٔ دیگری از `cryptography`:** پکیجِ
**غایب** پرصداست — `ModuleNotFoundError` دقیقاً همان لحظه می‌ترکد و خودش
می‌گوید چه کم است، و گاردِ ASTیِ
`test_no_test_imports_a_module_the_ci_runner_does_not_have` هم روی همین بنا
شده. ولی **extraیِ غایب بی‌صداست**: `import
yt_dlp` موفق می‌شود، هیچ استثنایی بالا نمی‌آید، و فقط یک شاخهٔ درونی سکوت
می‌کند یا مسیرِ دیگری می‌رود. یعنی هیچ مکانیزمی — نه import، نه گاردِ فعلی —
نمی‌تواند بگیردش، و تنها راهِ فهمیدنش **خواندنِ فایلِ requirements** است نه
اجرای محلی. قاعدهٔ عملی: پیش از هر ادعایی دربارهٔ رفتارِ **درونیِ** یک کتابخانه،
اول ببین تولید با کدام extra نصبش می‌کند؛ «همان پکیج را دارم» کافی نیست.

**و یک هارنسِ ناقص می‌تواند یک مشکلِ *خیالی* بسازد، نه فقط یک مشکلِ واقعی را پنهان
کند — این نیمهٔ گمشدهٔ درسِ بالاست.** همهٔ نمونه‌های قبلی از جنسِ **false pass**
بودند (`:memory:` که رقابت را مدل نمی‌کرد، `cryptography` که سندباکس تصادفاً
داشت). کست‌باکس نمونهٔ **false fail** داد و شکلش خطرناک‌تر است، چون خروجی‌اش
«یک باگ پیدا کردم» است نه «همه‌چیز سبز». سنجشِ انتخابگرِ yt-dlp با
`incomplete_formats: False` هاردکدشده اجرا شد و نشان داد `bv*+ba/b` روی منبعِ
فقط‌صوتی **هیچ فرمتی برنمی‌دارد** — نتیجه‌ای تمیز، بازتولیدپذیر، و کاملاً غلط:
`YoutubeDL._select_formats` آن فلگ را **خودش** از فرمت‌ها می‌سازد
(`all(vcodec == 'none')` → `True`) و شاخهٔ `format_fallback` بهترین صوت را
برمی‌دارد. یعنی هارنس یک نقصِ تولیدیِ ساختگی اختراع کرد که نزدیک بود واردِ نقشهٔ
رفع شود و کدِ سالم را «تعمیر» کند. **سابوتاژ این رده را نمی‌گیرد** — سابوتاژ
می‌پرسد «آیا assertم خرابی را می‌بیند؟» و این‌جا خودِ اندازه‌گیری خراب بود. آنچه
گرفتش، خواندنِ **نحوهٔ محاسبهٔ ورودیِ هارنس در سورسِ کتابخانه** بود، نه اعتماد به
عددی که هارنس داد. قاعده: وقتی داکلی یک `ctx`/`config`/`state` به کدِ بیرونی
می‌دهد، آن ساختار باید از **همان جایی که تولید می‌سازدش** ساخته شود؛ هر فیلدی که
دستی مقدار بگیرد یک فرضِ نانوشته است، و هر عددی که آن هارنس بدهد — سبز یا قرمز —
فقط به‌اندازهٔ آن فرض معتبر است. گاردش هم یک **تست** است نه یادداشت
(`test_the_harness_computes_the_flag_like_yt_dlp_does`)، با موردِ سابوتاژِ خودش.

**Two rules about what makes an assertion real, both learned by writing tests that were not.**
**(1) A test that asserts "the thing is gone" is only valid if the thing cannot end on its own — a
time bound is never a substitute for that.** The orphan-process tests waited N seconds and asserted
"no ffmpeg left", which silently became a tautology when the wait grew past the encode's own runtime:
measured, a 30 s source encoded in 5.5 s, so the process died ~4 s after the cancel *by finishing*, and
a 5 s wait saw zero without any kill having happened. Verified by sabotaging the fix — all four tests
stayed green. The earlier 2 s bound was correct but by luck, not design. The fix is structural, not a
smaller number: give the subprocess an input with **no duration** (`lavfi` without `duration=`, a
`while True` writer) so "it stopped" can only mean "it was killed". The same trap applies to any
"the file stops growing", "the counter stops rising", "the queue drains" assertion.
**(2) Where a race is the subject, force the interleaving; do not wait for it.** `tests/test_collect_race.py`
puts an `asyncio.Barrier` at the exact `await` the bug lives behind, so both handlers are guaranteed to
be past the stale read before either continues — the pre-fix failure is then deterministic on fast and
slow machines alike. Where ordering is the subject, the same idea applies as a delay injected into the
*first* operation only (`FakeBot.delay_first`): with the work outside the lock a later caller overtakes
the earlier one and the stale value lands last, while with it inside the lock that ordering is
impossible. A race test that merely runs things concurrently and hopes proves nothing when it passes.
**(3) When the code under test swallows its own exceptions, an environment failure becomes a silent
pass — so assert that the work *ran*, separately from what it produced.** `run_screen` wraps everything
in `except Exception` by design (the filter must fail open, never break the bot). The phase-3c tests
created a directory under `settings.work_dir`, which defaults to `/work`: creatable in the dev sandbox
because it runs as **root**, not on the CI runner. There `os.makedirs` raised `PermissionError`, the
handler swallowed it exactly as designed, and screening never ran at all — which made
"a fast screen produces no edits" **trivially true**. Two of the tests were green on CI while proving
nothing, and no local run could ever have shown it. The fix has two halves and both matter: point
`work_dir` at `tmp_path` so the real path is exercised anywhere, **and** have the stage doubles record
that they were called, so silence is only accepted when there was something to be silent about.
Generalise it: a fail-open code path converts *any* environment difference into a passing test, so
`root`-vs-not, a missing binary, or an unwritable directory can all hide behind it. This is the class
of bug CI exists to find, and the reason the runner must not be assumed to resemble the dev box.
**(4) A double that declares its own signature hides the shape of the API — build what the real code
builds.** This is a distinct way to be vacuous from (1) and (3), and it cost a shipped feature. `FakeBot`
declared `async def edit_message_text(self, text, chat_id=None, message_id=None)`, so the production call
`bot.edit_message_text(text, chat_id, note_mid)` bound happily in tests. In aiogram the **second**
positional of `edit_message_text` is `business_connection_id`, not `chat_id` — the only two methods
shaped that way are `edit_message_text` and `edit_message_caption`, while `send_message`,
`delete_message` and the `send_*` family are all intuitive, which is exactly why the eye slides over it.
In production that call raised `ValidationError` **before any network I/O**, both call sites swallowed it
in an `except Exception`, and so the 3c progress ticker never fired once and — for three weeks before
that — a user whose upload was rejected by the safety filter was told *nothing at all*. CI was green the
whole time. The fix is `tests/aiogram_double.py`: the double binds arguments with
`inspect.signature(aiogram.Bot.<method>)` and then constructs the same method model aiogram would, so
pydantic validates and a malformed call fails in the test exactly as in production. Paired with an AST
guard (`tests/test_aiogram_call_shape.py`) that discovers the trap methods from `Bot`'s own signatures
rather than a hand-list. Generalise: whenever a test double stands in for a typed third-party API, it
must derive its contract from that API, never restate it.

**و ردهٔ سومی که سابوتاژ می‌سازد و تا امروز نامش را نگذاشته بودیم: تستی که به‌جای
افتادن، *هنگ می‌کند*.** §۶ از قبل دو خروجیِ سبزِ تفکیک‌ناپذیر را ثبت کرده («تست بی‌ارزش
است» در برابرِ «سابوتاژ اعمال نشد»)؛ این سومی است و از هر دو بدتر، چون اصلاً خروجی
نمی‌دهد. مصداق (۲۰۲۶-۰۸-۱۸): تستی که ادعا می‌کرد `_on_cleanup` تسکِ پس‌زمینه را لغو
می‌کند، با `await task` نوشته شده بود؛ وقتی سابوتاژ لغو را برداشت، تسک هرگز تمام نشد و
`await` تا ابد ماند — پروب روی گِیتی می‌ایستاد که فقط teardown بازش می‌کند و teardown هم
تا تمام‌شدنِ بدنهٔ تست اجرا نمی‌شود. یعنی یک **قرمزِ تمیز** به یک jobِ گیرکرده تبدیل شد،
دقیقاً همان شکستی که `timeout-minutes` در `tests.yml` برایش گذاشته شد و همان‌جا نوشته
شده «بدترین شکلِ ممکن، چون چیزی برای نگاه‌کردن نیست». قاعدهٔ عام: **هر انتظاری در یک
تست باید کران داشته باشد** — نه به‌خاطرِ کندی، بلکه چون نسخهٔ خرابِ کد دقیقاً همان چیزی
است که ممکن است هرگز تمام نشود، و آن نسخه همان چیزی است که سابوتاژ می‌سازد. فرمِ درست
یک حلقهٔ کوتاهِ کران‌دار (یا `wait_for`) است، نه `await`ِ لخت.

**و برای سقفِ نرخ، `fakeredis` یک قیدِ اضافه می‌گذارد که راهِ حلِ درستش «ساعت را مدل کن»
است، نه «کلید را دستی پاک کن».** §۶ از قبل می‌گوید با fakeredis شمارشِ فرمان معتبر است
و زمان‌بندی نه؛ ولی کلِ ادعای یک سقفِ نرخ «چند تا در چند ثانیه» است، پس تستی که زمان را
مدل نکند دو راه بیشتر ندارد و هر دو بد است: `sleep`ِ واقعی (کُند و متزلزل)، یا تقلیدِ
پنجره با `DEL`ِ دستی — که یعنی همان مکانیزمی را که قرار است بسنجد جعل کند و تست دربارهٔ
انقضای Redis هیچ نگوید. راهِ سوم اجراشده و ارزان است: `fakeredis._basefakesocket.time`
یک پروکسیِ کنترل‌پذیر می‌گیرد، و آن‌وقت ریاضیِ انقضای **خودِ fakeredis**
(`db.time = time.time()` و بعد `key.expireat - db.time`) روی ساعتِ ما می‌دود — TTL و
انقضا واقعاً اجرا می‌شوند و فقط زمان را ما جلو می‌بریم. fixtureِ `clock` در
`tests/panel/conftest.py` همین است و **کنترلِ منفیِ خودش را دارد**
(`test_the_clock_fixture_really_drives_redis_expiry`): اگر تزریق وصل نباشد `advance`
بی‌اثر می‌شود و هر ادعای پنجره‌ای به دلیلِ غلط سبز می‌ماند — همان بنچِ مرده‌ای که سابوتاژ
نمی‌گیردش.

**CI:** `.github/workflows/tests.yml` — on every PR and on push to `main`, a clean `ubuntu-latest` runner
does `pip install -r requirements-dev.txt && pytest -q` on **Python 3.12** (matching `docker/*.Dockerfile`,
which are all `python:3.12-slim`; deliberately no version matrix — the target is production's environment,
not version coverage). Two things to know before changing it. The runner must build its environment **from
scratch**: the suite's one reproducible env failure was a Debian-packaged `cryptography` without
`_cffi_backend`, which broke collection — on a clean runner `cryptography` is not installed at all and
PyJWT runs with `has_crypto=False`, so the failure cannot occur. And **ffmpeg is installed explicitly** (phase 2b): the
`ubuntu-latest` image does not ship it — it is absent from the official runner-images software list — and
the media tests need the real binary. A `ffmpeg -version` step follows the install so the run itself
proves presence rather than trusting that README; without it a broken install would silently turn the
marked tests into skips and leave CI green.

**The corollary of "from scratch" is a whole class of green-locally/red-on-CI failures, and it has now
bitten once.** `requirements-dev.txt` deliberately excludes the admin stack (`jinja2`, `cryptography` —
they live in `requirements-admin.txt`), so **`app/admin_web.py` is not importable in the test
environment**, on CI or anywhere honest. A test that did `from app.admin_web import GROUPS` passed
locally purely because the dev sandbox happened to have `cryptography` installed — a leftover from
working around the Debian breakage above — and failed on the runner with `ModuleNotFoundError`. The
established workaround already existed (`tests/test_phase2a._func_src`: read the source with AST, never
import), and `test_no_test_imports_a_module_the_ci_runner_does_not_have` in `tests/test_repo_hygiene.py`
now enforces it by **discovery** over `tests/`, so the next such import fails locally at the same moment
it would fail on CI. Two general points. A dev sandbox drifts from the runner the instant you install
something to unstick yourself, and nothing warns you; the guard has to be a test, not a habit. And this
is the same shape as the `7z` marker and the `:memory:` harness — **local green is evidence about the
local environment, not about the code** — which is why the fix is always a mechanism that reproduces the
runner's constraint rather than a resolution to remember it.

**Those three are one class, and naming it is the point.** Within a single day, three separate green-locally
results turned out to be statements about the sandbox rather than about the code: `sqlite+aiosqlite:///:memory:`
backed every session with **one shared connection**, so a concurrency measurement could not fail (and both
invented a race and hid one); the `7z` marker was believed dead because nobody asked the runner (`ubuntu-latest`
ships `7z`, and the probe that "proved" absence was itself malformed); and `cryptography` was importable only
because it had been installed by hand earlier that session to unstick a broken Debian build. Different
mechanisms, one root: **the sandbox and the runner are different machines, and nothing reports the delta.**
So the rule is not "remember to check" — it is that any claim of the form *"the suite is green, therefore the
code is right"* is only as strong as the harness's ability to reproduce the runner, and where it cannot, the
guard must be a **test that fails locally at the same moment it would fail on CI**. Three such guards exist
today and each was written after being bitten: `test_no_test_imports_a_module_the_ci_runner_does_not_have`
(discovery over `tests/`), `test_the_ffmpeg_marker_is_not_dead_weight` and `test_the_7z_gate_is_not_dead_weight`
(both AST, both counting decorated functions rather than grepping). The still-open half is **transitive**
imports: the AST guard sees `import app.admin_web` written in a test, but not a test importing `app.foo`
which imports `app.admin_web`. The cheap mechanism for that is an import hook in `conftest.py` that makes the
admin/worker-only distributions unimportable for the whole session, with the deny-list **discovered** from
`requirements-admin.txt`/`requirements-worker*.txt` rather than hand-written — recorded in Open Questions,
not built.

Pin the quoted `'3.12'` — unquoted `3.10` becomes the float
`3.1`. **Still no lint config** (see Open Questions).

## 7. Known Gotchas
- **یک ریفکتورِ «فقط جابه‌جایی» می‌تواند گاردِ موجود را بی‌اثر کند، و آن گارد
  بی‌صدا برای همیشه سبز می‌ماند — اجراشده ۲۰۲۶-۰۸-۱۹ روی خودِ استخراجِ قالب‌ها.**
  `test_the_panel_has_no_external_resources_for_the_csp_to_break` دامنه‌اش
  **فقط `app/admin_web.py`** بود و دنبالِ `src=`/`href=`ِ `https?://` می‌گشت.
  اندازه‌گیری‌شده: **هر ۲۰** موردِ `href=`/`src=` داخلِ **ثابت‌های قالب** بود و
  **صفر** در بقیهٔ فایل. پس لحظه‌ای که قالب‌ها به `app/templates/` رفتند، آن تست
  فایلی را اسکن می‌کرد که هیچ‌کدام را ندارد، `assert not external` روی فهرستِ
  تهی پاس می‌شد، و از آن به بعد هر CDNی در هر قالبی بی‌صدا رد می‌شد.
  **نکتهٔ عام، و چرا از خودِ استخراج مهم‌تر است:** ردهٔ آشنای «گاردِ دائماً سبز»
  که §۶ چند نمونه‌اش را دارد، ولی این‌بار **نه از تغییرِ رفتار و نه از یک تستِ
  ضعیف** — از جابه‌جاکردنِ **داده‌ای که گارد رویش کار می‌کرد**. هیچ تستی قرمز
  نمی‌شود، هیچ رفتاری عوض نمی‌شود، و سوییتِ سبز دقیقاً همان چیزی است که انتظار
  داری ببینی. پس **هر بار که چیزی از یک فایل بیرون می‌رود باید پرسید کدام گارد
  دامنه‌اش آن فایل بود** — یک سرشماری، نه یک حدس. سرشماریِ همان روز: از ۱۰ تستی
  که `admin_web.py` را به‌عنوان **متن** می‌خوانند، ۹ تا تابع یا لیترالِ پایتونی
  را هدف می‌گیرند (زنده می‌مانند) و فقط همین یکی متنِ قالب را. رفع = دامنهٔ
  **کشف‌محور** (`admin_web.py` + `templates/*.html` + `static/css/*.css`) به‌علاوهٔ
  **دو** کنترل: یکی که CDNِ کاشته‌شده گرفته می‌شود، و یکی که خودِ دامنه واقعاً
  قالب‌ها را می‌بیند (وگرنه «صفر منبعِ خارجی» می‌تواند یعنی «صفر فایلِ اسکن‌شده»).
- **Jinja دقیقاً *یک* خطِ جدیدِ پایانی را می‌خورد، پس فایلِ قالب با دو تا یک
  `\n` به **هر صفحه** اضافه می‌کند.** اندازه‌گیری‌شده روی هر سه حالت (صفر / یک /
  دو خطِ پایانی): فقط سومی خروجی را عوض می‌کند. محتمل‌ترین تصادفِ ویرایشگر است و
  کاملاً بی‌صداست. گاردِ per-file دارد — و همان گارد یک آلودگیِ **واقعی** را
  همان روز گرفت: یک پروبِ دستی یک `\n` به `base.html` اضافه کرده بود و
  `git checkout` برنگرداندش، چون `app/templates/` هنوز **untracked** بود و
  `git checkout`ِ یک مسیرِ untracked بی‌صدا هیچ کاری نمی‌کند. **قاعدهٔ عملی:
  برای برگرداندنِ فایلِ untracked از `git checkout` استفاده نکن** — یا کپیِ
  پشتیبان بگیر یا از منبعِ اصلی بازتولیدش کن.
- **کلاسِ CSSِ تعریف‌نشده در پنل خطا نمی‌دهد و §۵ سه بار تکرارش را دیده — حالا
  گارد دارد، و نکتهٔ اصلی این است که گارد باید *رندرشده* را بسنجد.** §۵ از قبل
  می‌گفت «هر کلاسی که قالب استفاده می‌کند باید در `_CSS` باشد» و `.pad`/`.hint`/
  `.tabs` این‌طور خراب شیپ شدند؛ نوبتِ بعدی `.err`, `.mute`, `.s-unproven` بود
  (اندازه‌گیری‌شده روی هر ۹ صفحهٔ GET: **دقیقاً همین سه‌تا و همه فقط در
  `/cookies`** — بقیهٔ پنل تمیز بود). `.err` در `_LOGIN` **هست** ولی آن یک
  بلوکِ خطای صفحهٔ ورود است با padding/margin و اصلاً روی `/cookies` بار
  نمی‌شود؛ همین وجودِ همنامْ باعث شد سال‌ها به‌نظر برسد کلاس تعریف شده است.
  **تفکیکی که در صورتِ مسئله نبود:** نقطهٔ ۹پیکسلیِ `.s-invalid` قرمز بود و کار
  می‌کرد، پس «کوکیِ مرده کاملاً نامرئی است» اغراق بود — چیزی که بی‌رنگ می‌شد
  *متنِ* برچسب بود. **و مهم‌ترین چیزی که این کار یاد داد در خودِ گارد بود:**
  کامنتِ CSS داخلِ `<style>` **ارسال می‌شود**، پس چکی که متنِ خامِ CSS را اسکن
  کند نامِ کلاسی را که فقط در نثرِ کامنت آمده «تعریف‌شده» می‌خواند — اولین
  سابوتاژِ گارد به همین دلیل «نگرفت» داد در حالی که خرابکاری کاملاً اعمال شده
  بود. ردهٔ سومِ §۶ (ابزارِ سنجش نتیجهٔ درست را غلط می‌خواند) و سومین نمونهٔ
  «گارد خودش را می‌گیرد» بعد از دو گاردِ ASTی که داکس‌استرینگِ خودشان را
  می‌گرفتند. **قاعدهٔ عام: هر چکی که روی متنِ یک زبانِ دیگر کار می‌کند اول باید
  کامنت‌های آن زبان را دور بریزد، وگرنه توضیحاتِ خودت به داده تبدیل می‌شوند.**
- **`_STATUS_BADGE.get(status, «پیش‌فرض»)` دو کپیِ دست‌نویس داشت و هر دو به
  کلاسِ ناموجودِ `mute` می‌رفتند — و پیش‌فرض نباید با «غیرفعال» یکی شود.**
  «ادمین خودش خاموشش کرد» یک تصمیم است و «وضعیتی که نمی‌شناسیم» یک نقص؛
  یکی‌کردنشان یعنی حالتِ ناشناخته بی‌صدا شبیهِ حالتِ عادی رندر شود. حالا
  `_badge_of()` تنها جایی است که پیش‌فرض تعریف می‌شود و آن پیش‌فرض `unk` است
  (بنفش، عمداً بیرونِ خانوادهٔ سبز/زرد/قرمز/خاکستری). رنگِ پایهٔ `.sdot` هم
  همان بنفش است تا وضعیتِ بی‌`.s-*` نقطهٔ **نامرئی** نگیرد.
- **کارتِ «نرخِ موفقیتِ دانلود» پنجرهٔ ثابتِ یک‌روزهٔ UTC دارد و با `dlstat`ِ
  دوروزه قابلِ مقایسهٔ مستقیم نیست.** `_health` کلیدِ `dlstat:{p}:ok:{روزِ جاریِ
  UTC}` را می‌خواند، در حالی که `_metric` (`tasks_download.py`) با TTLِ **دو
  روز** می‌نویسد — پس یک `KEYS dlstat:*`ِ دستی می‌تواند تا دو برابرِ پنجرهٔ
  کارت را جمع کند. همین یک بار اپراتور را گمراه کرد: پنل برای ساندکلاد
  «۳۳٪ · ۱ از ۳» می‌داد و Redis «۱۱ موفق و ۷ ناموفق» — **دو پنجرهٔ متفاوت، نه
  دو منبعِ متفاوت**، و ربطی به شکافِ Job نداشت (بولتِ بعدی). برچسب از «امروز»
  به «امروز (UTC)» رفت، چون روزِ تهران با روزِ UTC یکی نیست و ساعت‌های اولِ شب
  از قبل فردای UTCاند. برای مقایسه، کلیدِ **همان روز** را بخوان:
  `GET dlstat:<platform>:ok:$(date -u +%Y%m%d)`.
- **جدولِ `jobs` هیچ دانلودی را نمی‌شمارد، و هشت سطحِ پنل روی آن سوارند.**
  `Job()` فقط در `routers/ops.py` ساخته می‌شود (دو نقطه) و
  `tasks_download.py:7` صریح می‌گوید «جابِ دانلود، رکوردِ File/Job از پیش
  ندارد» — یعنی **طراحیِ عمدی**، نه فراموشی. ولی نتیجه‌اش این است که «عملیات»،
  «٪موفق»، «در صف»، «میانگین/p95»، «پرکاربردترین عملیات»، «کارایی هر عملیات»،
  «پرتکرارترین خطاها» و سریِ «عملیات»ِ نمودار همگی صفر دانلود می‌بینند، در حالی
  که «فایل · N از لینک» و «پلتفرمِ دانلود» و «منبعِ فایل» از `files` می‌آیند و
  همه‌شان را دارند. اندازه‌گیری‌شده روی هارنس: ۱۰ دانلود + ۵ آپلودِ یک‌جابه →
  «فایل ۱۵ · ۱۰ از لینک» درست کنارِ «عملیات ۵». با اعدادِ تولید (۳۲۰۴ فایلِ
  دانلودی از ۴۰۵۰ در برابرِ ۱۰۱۶ جاب) یعنی ~۷۹٪ کار در کارتِ کناری نامرئی است.
  **تصمیم (اپراتور، ۲۰۲۶-۰۸-۱۸): برچسبِ صریح، نه ساختنِ Job** — مسئله گمراهی
  است نه نبودِ عدد؛ گزینهٔ ساختنِ Job با هزینه‌اش در Open Questions ثبت شد.
  مرزِ درست **منبعِ داده** است نه موضوع: هرچه از `files` می‌آید دانلودها را
  دارد، هرچه از `jobs` می‌آید ندارد.
- **مسیرِ لاگینِ پنل محدودیتِ نرخ **داشت** — فرضِ «ندارد» غلط بود، و عددِ واقعی
  ۳۰ حدس در ۶۰۰ ثانیه بود.** این را اول بخوان تا کسی دوباره از صفر شروع نکند.
  اندازه‌گیریِ ۲۰۲۶-۰۸-۱۸ روی هندلرهای واقعی با ساعتِ مدل‌شده: `panelreq:<id>`
  پنج درخواستِ کد در ۶۰۰ ثانیه (TTLِ سنجیده‌شده ۶۰۰) و `paneltry:<id>` شش حدس
  در ۳۰۰ ثانیه (TTLِ سنجیده‌شده ۳۰۰) — ولی `auth_request` شمارندهٔ حدس را **پاک
  می‌کرد**، پس بودجه‌ها در هم ضرب می‌شدند: ۵×۶ = **۳۰ حدس در هر پنجره**، و پس از
  گذشتنِ پنجره از نو. در برابرِ فضای ۱۰^۶ یعنی ~۴٫۳e-3 در روز، یعنی ~۷۹٪ تجمعی
  در یک سالِ حملهٔ پیوسته.
  **شکلِ رفع، و چرا این شکل و نه فرمِ بدیهی‌تر:** بودجهٔ حدس به **کد** بسته شد نه
  به اندپوینت — تمام‌شدنش کد را می‌کشد و کاربر کدِ تازه می‌گیرد. تنها به همین
  دلیل می‌شود سقف را ۶ → ۳ آورد؛ «حذفِ ریست» همان کار را نمی‌کند بلکه یک اهرمِ
  **قفلِ ادمین** می‌سازد (سه حدس در هر ۳۰۰ ثانیه و ورودِ ادمینِ واقعی برای همیشه
  بسته). سقفِ per-adminِ درخواست (۵) **عمداً دست‌نخورده** ماند: تنها اهرمی است
  که مهاجم علیهِ ادمینِ واقعی دارد، و پایین‌آوردنش حاشیهٔ brute-force را با یک
  قفلِ ارزان‌تر عوض می‌کند.
  **و سقفِ per-IP نرخِ مهاجمِ تک‌هدف/تک‌مبدأ را کم نمی‌کند** — آن‌جا سقفِ per-admin
  زودتر می‌بندد. چیزی که می‌خرد این است که کشتنِ بلاکِ اندپوینت حجمِ خامِ verify را
  بی‌کران می‌کرد، و برخلافِ سقفِ per-admin، بلاک‌شدنِ IPِ مهاجم قفلِ ادمین نیست.
  `_client_ip` عمداً `X-Forwarded-For` **نمی‌خواند**: آن هدر را کلاینت ست می‌کند،
  پس اعتماد به آن سقف را برای همان استقرارِ مستقیمِ روی اینترنت (که `install.sh`
  با TLSِ خودش می‌سازد) به no-op تبدیل می‌کند. بهایش این است که پشتِ پروکسیِ
  معکوس همه یک سطل می‌شوند، و به همین دلیل عددهای per-IP **بالاتر از** per-admin
  چیده شده‌اند.
  **بودجهٔ امروز ۱۵ حدس در ۶۰۰ ثانیه است، و اهرمِ واقعیِ بعدی طولِ کد است نه این
  شمارنده‌ها:** همان ۱۵ در برابرِ ۱۰^۸ به ~۰٫۵٪ در سال می‌رسد. **ثبت شد، ساخته
  نشد** — UXِ ورود را عوض می‌کند.
  **دو کرشِ عمومی که همان بررسی داد و هر دو اجرا شدند:** `int()` روی رشتهٔ بالای
  ۴۳۰۰ رقم `ValueError` می‌دهد در حالی که `str.isdigit()` از آن رد می‌شود (پس
  `admin_id`ِ بلند ۵۰۰ می‌داد)، و `secrets.compare_digest` روی strِ غیرASCII
  `TypeError` می‌دهد در حالی که `'۱۲۳۴۵۶'.isdigit()` صادق است — یعنی مقایسهٔ
  زمان‌ثابت **باید روی بایت** باشد، وگرنه کدِ با رقمِ فارسی ۵۰۰ می‌شود جایی که
  `!=`ِ قدیمی درست «کد نادرست» می‌داد.
- **`INCR` بعد `EXPIRE` دو فرمانِ جداست، و مرگِ بینشان یک شمارندهٔ جاودان می‌سازد.**
  فرمِ رایجِ `if n == 1: expire(...)` فقط روی اولین فراخوان TTL می‌گذارد، پس اگر
  پروسه دقیقاً همان‌جا بمیرد کلید بی‌انقضا می‌ماند و شمارنده تا ابد بالا می‌رود —
  برای یک سقفِ لاگین یعنی **قفلِ دائمیِ ورود که خودش ترمیم نمی‌شود** و فقط با
  پاک‌کردنِ دستیِ کلید باز می‌شود. دقیقاً همان شکستی که §۷ برای `dl:active` ثبت
  کرده. `admin_web._rate_limit` به‌جایش وقتی TTL گم باشد دوباره `expire` می‌زند:
  درخواستِ بعدی ترمیمش می‌کند و هزینه همان دو فرمان می‌ماند.
- **چکِ سلامتِ pot-provider تنها فراخوانیِ شبکهٔ بیرونیِ پنل است و نباید روی مسیرِ
  درخواست باشد.** اندازه‌گیری‌شده با سوکتی که accept می‌کند و هرگز جواب نمی‌دهد:
  `/` ۳۱۵۱ ms · `/health` ۳۰۲۳ ms · بدونِ pot ۲۱ ms. «گیرکرده» بدترین حالت است نه
  نادرترین — سرویسِ مرده اتصال را reject می‌کند و سریع برمی‌گردد، ولی کانتینرِ
  زنده‌ی بی‌پاسخ کلِ تایم‌اوتِ ۳ ثانیه را خرج می‌کند. **کوتاه‌کردنِ تایم‌اوت رفع
  نیست، فقط عدد را کم می‌کند**؛ نتیجه کش می‌شود و تازه‌سازی به پس‌زمینه می‌رود.
  **دو کلید لازم است نه یکی:** `potping:fresh` (با TTL) یعنی «تازه سنجیده‌ایم» و
  `potping:last` (بی‌انقضا) آخرین نتیجهٔ شناخته‌شده؛ با یک کلیدِ TTLدار، هر بار که
  کش می‌پرید بج «نامعلوم» می‌شد. و **«تنظیم‌شده ولی نسنجیده» با «پیکربندی‌نشده» یکی
  نیست** — یکی‌کردنشان یعنی پنل در پنجرهٔ کوتاهِ پس از ری‌استارت دربارهٔ سرویسی که
  پیکربندی **شده** دروغ بگوید؛ به همین خاطر یک شاخهٔ سومِ صریح در قالب هست.
- **در صفحهٔ کاربران آنچه گران است سورت نیست، `count(*)` است — و این تعیین می‌کند
  کدام رفع کدام مشکل را برمی‌دارد.** اندازه‌گیری‌شده روی Postgres 16.13 واقعی با
  ۲۰۰هزار ردیف، پس از افزودنِ ایندکسِ `last_seen`: `count(*)` ۱۲٫۵ ms ·
  `count(*)`ِ بلاک‌شده‌ها ۱۲٫۷ ms · کوئریِ خودِ صفحه **۰٫۴۵ ms** · شمارشِ فایل‌ها
  ۰٫۴۱ ms. یعنی دو شمارش ~۹۶٪ کارِ صفحه‌اند و **ایندکس کاری با آن‌ها ندارد**؛ کشِ
  صفحه همان‌هاست که برمی‌دارد، و ایندکس فقط `Sort` را به
  `Index Scan Backward` تبدیل می‌کند (۳۷ → ۰٫۴۵ ms برای همان کوئری).
  **و باطل‌سازیِ کش شرطِ درستی است نه بهینه‌سازی:** بدونش ادمین «بلاک» را می‌زند،
  به `/users` ریدایرکت می‌شود و همان کاربر را هنوز آزاد می‌بیند — یعنی کش صفحه را
  از «کند» به **غلط** می‌برد. باطل‌سازی با شمارندهٔ نسخه است (`userscache:ver`،
  همان الگوی `txtver`) نه پیمایش و حذفِ کلید: یک `INCR` همهٔ صفحه‌های کش‌شده را
  یتیم می‌کند بدونِ اینکه لازم باشد بدانیم کدام صفحه/جست‌وجو کش شده.
  **قید:** روی جدولِ **امروزِ** تولید (۱۶۶۸ ردیف) کلِ صفحه ~۲٫۷ ms است، پس هر دو
  نیمه بیمه برای رشدند نه رفعِ یک دردِ فعلی.
- **کاورِ صوتی: `--embed-metadata` تصویر را جاسازی نمی‌کند، و گیتِ `audio_only`
  جلوی یک شکستِ **پرصدا** را می‌گیرد نه یک زشتیِ کوچک.** خطِ فرمان
  `--write-thumbnail --convert-thumbnails jpg` داشت (کاور دانلود و روی دیسک
  می‌نشست) ولی `--embed-thumbnail` نداشت، و `--embed-metadata` فقط تگِ **متنی**
  می‌نویسد — پس تصویر دانلود می‌شد و دور ریخته می‌شد.
  **چرا فقط مسیرِ صوت (اجراشده از سورسِ yt-dlp):** `EmbedThumbnailPP` برای
  `ogg/opus/flac` **بدونِ mutagen** و برای هر پسوندِ ناشناخته بی‌قیدوشرط
  `PostProcessingError` می‌دهد؛ و چون `--ignore-errors` نمی‌فرستیم
  (`_common_flags`)، `YoutubeDL.run_pp` دوباره raise می‌کند و **کلِ دانلود
  می‌شکند**. مسیرِ ویدیو روی منبعِ فقط‌صوتی می‌تواند دقیقاً همان پسوندها را بدهد
  (کد خودش با `_newest(..., _MEDIA_EXTS)` برایش fallback دارد). پس گیت قیدِ
  درستی است، نه احتیاط.
  **و دو ادعای غلط که در بررسی تصحیح شد — هر دو دربارهٔ AtomicParsley.**
  (الف) «AtomicParsley نصب نیست پس m4a مشکل‌ساز است» — برای مسیرِ صوت **بی‌ربط**
  است: خروجی اثباتاً همیشه mp3 است (در `FFmpegExtractAudioPP.run` هم شاخهٔ copy
  و هم شاخهٔ تبدیل پسوندِ `mp3` می‌دهند)، و برای mp3 خودِ `EmbedThumbnailPP`
  مستقیم ffmpeg با `-c copy` می‌زند و اصلاً سراغِ AtomicParsley نمی‌رود. ضمناً
  برای m4a هم AtomicParsley لایهٔ **دوم از سه** است (mutagen → AtomicParsley →
  ffmpeg) و `mutagen` در تولید هست، چون `requirements-worker-dl.txt` از
  `yt-dlp[default]` استفاده می‌کند و mutagen عضوِ همان extra است.
  (ب) «شکستش خاموش است» — **برعکس**: پرصداست و دانلود را می‌شکند. همین است که
  دامنهٔ `audio_only` را لازم می‌کند.
- **درصدِ حجمِ کاور را با مدتِ نمونه بخوان، وگرنه تصمیمِ غلط می‌گیری.** اندازه‌گیریِ
  اپراتور روی یک اپیزودِ **۴٫۵ دقیقه‌ای** کست‌باکس `+۷۶۷KB` داد که `+۱۸٪` است و
  زیاد به‌نظر می‌رسد؛ ولی کاور حجمِ **ثابت** است و صوت با مدت بزرگ می‌شود:

  | مدت | صوت @128k | سهمِ کاورِ ۷۶۷KB |
  |---|---|---|
  | ۴٫۵ دقیقه (نمونه) | ۴٫۲MB | **۱۸٪** |
  | ۱ ساعت | ۵۶MB | ۱٫۳٪ |
  | ۳ ساعت | ۱۶۹MB | **۰٫۴۴٪** |

  پادکستِ واقعی ۱ تا ۳ ساعت است، پس آن ۱۸٪ آرتیفکتِ نمونهٔ غیرنماینده بود.
  **و کوچک‌کردنِ کاور بررسی و رد شد:** yt-dlp گزینهٔ resize ندارد، و
  `--ppa ThumbnailsConvertor:…` قابلِ‌اتکا نیست چون وقتی تامبنیلِ مبدأ از قبل
  jpg باشد `resolve_mapping` مقدارِ skip می‌دهد و `convert_thumbnail` **اصلاً
  اجرا نمی‌شود** (اجراشده). هر روشِ قابلِ‌اتکای دیگر یعنی re-embed بعد از
  yt-dlp، یعنی یک پاسِ کاملِ صوت، یعنی **خوردنِ بردِ بدونِ ترنسکدِ #۱۱۵**.
- **کارتِ صوتیِ تلگرام هرگز از ما تامبنیل نمی‌گیرد — روی هیچ پلتفرمی.** شاخهٔ
  `audio` در `cards._send_typed` پارامترِ `thumb` را **کاملاً نادیده می‌گیرد**
  (در حالی که `send_audio`ِ aiogram `thumbnail` و `performer`/`title` را
  می‌پذیرد)، و مسیرِ تحویل هم اصلاً آماده‌اش نمی‌کند چون گیتش
  `if kind == "video" and thumb_path` است. پس هر کاوری که روی کارتِ صوتی دیده
  شده **از کدِ ما نیامده** — تلگرام خودش از فایل خوانده. نتیجهٔ عملی: جاسازیِ
  کاور احتمالاً کارت را هم درست می‌کند، پس **اول جاسازی را مستقر کن و بعد کارت
  را دوباره ببین**؛ کدی که شاید لازم نباشد ننویس. اگر بعد از استقرار هنوز خالی
  بود، رفعش سه نقطه دارد (دو گیتِ `kind == "video"` و خودِ `send_audio`) و
  مسیرِ fallbackِ `send_card` را لمس می‌کند، پس تغییرِ جداست.
- **کست‌باکس: فرمِ کوتاه می‌شکند، فرمِ کامل از قبل کار می‌کند — و رفعش دو دفاعِ
  **مستقل** دارد که نباید با هم سنجیده شوند.** yt-dlp ۲۰۲۶.۰۷.۰۴ صفحهٔ اپیزود را با
  اکسترکتورِ `html5` می‌خواند (تگِ `<audio><source>` روی `sphinx.acast.com`)، پس
  `castbox.fm/ep/<eid>` **بدونِ هیچ کدی** کار می‌کرد — ماژولِ اختصاصی لازم نبود.
  ولی دکمهٔ Shareِ اپ فرمِ `/vb/<eid>` می‌دهد و yt-dlp روی صفحهٔ واسطهٔ
  `d.castbox.fm/dynamic-link/redirect?link=…` می‌ایستد («Unsupported URL»). لینکِ
  کانال (`/va/<cid>`) هم **همان‌جا** می‌ایستد و اصلاً به صفحهٔ کانال نمی‌رسد — که
  آن صفحه هم تگِ `<audio>` ندارد، پس چیزی برای برداشتن نیست و رد با پیامِ روشن
  تنها گزینهٔ صادقانه است.
  **دفاعِ اول، و مهم‌ترش:** `castbox_target` URL را **بازمی‌سازد**
  (`https://castbox.fm/ep/<digits>`) و هرگز مقداری را عبور نمی‌دهد. این تمامِ
  ماجرای SSRF است — چون `d.castbox.fm` **واقعاً** castbox.fm است، کاربر می‌تواند
  خودش `…/redirect?link=http://169.254.169.254/` را بسازد و درِ ورودی (که فقط
  هاستِ بیرونی را می‌سنجد) عبورش می‌دهد؛ اندازه‌گیری‌شده روی هر چهار payload.
  **پس گیت‌کردن به دامنهٔ castbox.fm جواب نیست.** با بازسازی، یک `link=`ِ خصمانه
  اصلاً با الگوی اپیزود/کانال جور نمی‌شود و همان‌جا `None` می‌گیرد.
  **دفاعِ دوم:** `resolve_castbox` خروجی را از `is_safe_url_resolved` رد می‌کند.
  ساختاراً زائد است (هاست هاردکد، شناسه `\d+`) و **یک** چیزِ واقعی می‌خرد که
  بازسازی نمی‌گیردش: اگر خودِ `castbox.fm` روزی به آدرسِ داخلی resolve شود. yt-dlp
  زیرفرایند است و رزولورِ وتوکننده نمی‌گیرد، پس این تنها لایه‌ای است که آن حالت را
  می‌بیند. دلیلِ دومش این است که یک نقطهٔ خروج با یک قرارداد بسازد به‌جای دو مسیر
  با دو سطحِ ایمنی — مسیرِ الگویی هم از همان رد می‌شود.
  **و این دو باید تستِ جدا داشته باشند، که با اجرا معلوم شد نه با استدلال:** اولین
  اجرای دفترچهٔ سابوتاژ نشان داد برداشتنِ دفاعِ اول، تستِ انتها‌به‌انتها را
  **نمی‌اندازد** — چون گارد payload را می‌گیرد و «هیچ جابی ساخته نشد» همچنان صادق
  است. یعنی یک سابوتاژِ کاملاً موفق «نگرفت» گزارش می‌شد. حالا سه تست در سه سطح
  هست: بازسازیِ ایزوله، گاردِ ایزوله، و ادعای انتها‌به‌انتها با سابوتاژی که **هر
  دو** را برمی‌دارد.
- **یک تمیزکنندهٔ مشترک به دو جمعیت سرویس می‌دهد، و رفعی که برای یکی درست است
  دیگری را خراب می‌کند — گیت بگذار، نه قاعدهٔ بی‌قید.** توضیحاتِ پادکست (کست‌باکس
  و هر منبعِ RSS-محورِ `html5`) **HTML** است و تگ‌هایش خام به کاربر می‌رسید؛
  `post_view` درست escape می‌کند و گامِ غایب **پاک‌کردن** بود. ولی `clean_caption`
  مشترک است و کپشنِ **سادهٔ** اینستاگرام هم از آن رد می‌شود، پس پاک‌سازیِ بی‌قید
  اندازه‌گیری شد و روی ۱۰ متنِ سادهٔ واقعی **۳ تا را خراب کرد**:
  `use --flag <value> here` → `use --flag  here`، `به <a@b.com> …` → `به  …`، و
  بدترینش `کد: if (a<b) return;` → **`کد: if (a`** چون `<b>` نامِ تگِ واقعی است و
  پارسر تا انتهای رشته را می‌بلعد. یعنی رفعِ بی‌قید یک **زشتیِ کوچک** در کست‌باکس
  را با یک **باگِ واقعی** در پرترافیک‌ترین مسیر عوض می‌کرد. رفع در جای عام
  می‌نشیند (`clean_caption`، یک نقطه، چهار مسیرِ رندر) ولی به `_HTML_GATE` گیت
  می‌خورد: فهرستِ **صریح و بستهٔ** تگ‌ها، و تگ باید با `>`/`/`/فاصله تمام شود —
  همان اصلِ `safety.STRONG_TOKENS`/`WORD_TOKENS`. اندازه‌گیری‌شده: ۱۲ از ۱۲ متنِ
  ساده ساکت، ۸ از ۸ متنِ HTMLدار شلیک. **قاعدهٔ عام:** پیش از افزودنِ هر تبدیلی
  به یک تابعِ مشترک، اول فهرست کن **چه کسانی دیگری** از آن رد می‌شوند؛ «عام بودنِ
  مسئله» با «امن بودنِ رفعِ بی‌قید» یکی نیست.
- **چهار ریزه‌کاریِ پاک‌سازیِ HTML که هرکدام یک باگِ خاموش‌اند** (همه اجراشده).
  **(۱)** `<[^>]+>` روی «اگر x < 5 باشد و y > 2» از `<` تا اولین `>` را می‌بلعد
  («اگر x  2»)؛ `html.parser` آن `< 5` را داده می‌بیند. **(۲)** ترتیب: تگ‌ها باید
  از متنِ **خام** شناخته شوند و بعد موجودیت‌ها باز شوند (`convert_charrefs=True`
  همین را می‌کند). برعکسش متنی را که مبدأ **عمداً** escape کرده می‌خورد —
  `&lt;script&gt;alert(1)&lt;/script&gt;` می‌شد `alert(1)`. با ترتیبِ درست متنِ
  لفظی می‌ماند و `post_view` دوباره escapeاش می‌کند، پس امنیت تضعیف نمی‌شود.
  **(۳)** تگِ بلوکی باید به `\n` تبدیل شود نه حذف، وگرنه `</p><p>` می‌شود
  «خط یکخط دو». **(۴)** `&nbsp;` می‌شود `\xa0` که `clean_caption` جمعش نمی‌کند
  (الگویش `[ \t]{2,}` است)، و فاصلهٔ **ابتدای** خط هم باید در `strip_html` جمع
  شود نه در مسیرِ مشترک — آن‌جا `ln.rstrip()` است و تبدیلش به `strip()` تورفتگیِ
  عمدیِ کپشنِ سادهٔ کاربر را می‌خورد.
  **و یک تصمیم که ثبت می‌شود چون بی‌صدا اطلاعات می‌برد:** `<a href>` فقط متنِ
  لنگر را نگه‌داشتن، آدرس را دور می‌ریزد و show-notesِ پادکست پر از لینکِ معنادار
  است؛ پس آدرس وقتی http(s) است و در متن نیست به‌شکلِ `متن (آدرس)` می‌ماند، و
  لنگرِ **خالی** خودِ آدرس را می‌دهد. `mailto:`/`javascript:` هیچ‌وقت وارد متن
  نمی‌شوند. سقفِ ۱۰۲۴ **آخر** اعمال می‌شود و `…` می‌گذارد، پس یک آدرس می‌تواند
  وسط بریده شود — پذیرفته‌شده و **علامت‌دار**؛ خودِ سقف عمداً دست‌نخورده ماند چون
  مسیرِ مشترکِ همهٔ پلتفرم‌هاست.
- **تلهٔ تستِ پذیرش: کپشن جزءِ کلیدِ کش نیست، پس ردیفِ کهنه رفعِ کپشن را پنهان
  می‌کند.** `File.post_caption` **داخلِ ردیفِ** `download_cache` ذخیره می‌شود ولی
  در ساختنِ کلید هیچ نقشی ندارد (`cache_key` فقط `(_cache_url, selector)` است).
  پس هر تغییری در `clean_caption`/`_post_text` ردیف‌های موجود را **باطل
  نمی‌کند**: لینکی که قبلاً دانلود شده از `deliver_from_cache` می‌آید و کپشنِ
  **قدیمیِ ذخیره‌شده** را نشان می‌دهد. نتیجهٔ عملی و آزاردهنده این است که تستِ
  پذیرش روی **همان لینکی که باگ را با آن دیدی** نسخهٔ کهنه را نشان می‌دهد و رفع
  را نه — یعنی رفعِ درست به‌شکلِ «کار نکرد» گزارش می‌شود. برای سنجش یا لینکِ
  **تازه** بفرست، یا آن ردیف را پاک کن، یا `dl_cache_enabled` را موقتاً خاموش کن.
  ردیف خودبه‌خود با دانلودِ بعدیِ همان لینک بازنویسی می‌شود، پس `DELETE`ِ گسترده
  لازم نیست. **هم‌ردهٔ همان درسِ اسپاتیفای** («ردیفِ کهنه سرو می‌شد و اسموک هیچ
  چیزی اندازه نمی‌گرفت») — با این تفاوت که آن‌جا نسخه‌دارکردنِ کلید حلش کرد و
  این‌جا نمی‌شود: کپشن بخشی از **هویتِ** محتوا نیست، پس واردکردنش به کلید یعنی
  دورانداختنِ ردیف‌های سالم برای چیزی که فقط نمایش است.
- **تلهٔ دو-شناسه‌ایِ کست‌باکس — یک رفعِ ظاهراً درست و عملاً غلط.** فرمِ کانونیکی
  که `webpage_url`ِ yt-dlp می‌دهد `‎/episode/<اسلاگِ فارسی>-id5174947-id798014224`
  است: **اول شناسهٔ کانال، بعد اپیزود**. الگوی طبیعیِ `id(\d+)` شناسهٔ **کانال** را
  برمی‌دارد (اجراشده روی همان رشتهٔ واقعی)، و چون هر دو عددند و هر دو در همان URL،
  خروجی کاملاً معقول به‌نظر می‌رسد و فقط با دانلود/کشِ فایلِ **غلط** معلوم می‌شود.
  لنگرِ `-id(\d+)$` تنها فرمِ درست است. هم‌خانوادهٔ تلهٔ `acodec`ِ ساندکلاود (که
  بی‌صدا AAC برمی‌داشت) و `srcset`ِ اینستاگرام (که عرض را از داخلِ URL می‌خواند):
  هر سه رفع‌هایی که فقط با **اجرا روی دادهٔ واقعی** غلط بودنشان دیده می‌شود، و هر
  سه کنترلِ معکوسِ اختصاصی دارند.
- **`dl_allow_unknown` پیش‌فرضش `True` است — سکوت فقط وقتی رخ می‌دهد که ادمین
  خودش خاموشش کند.** این را صریح می‌نویسم چون در بررسیِ کست‌باکس یک‌بار برعکس فرض
  شد و نزدیک بود «رفعِ یک باگِ فعال» خوانده شود. `config.py` مقدارش را `True`
  می‌گذارد و با صفر ردیفِ `settings` همان مؤثر است (اجراشده)، پس یک هاستِ ناشناخته
  **می‌رسد** به yt-dlp و کاربر روی شکست `dl_failed` + دُمِ stderr می‌گیرد، نه سکوت.
  یعنی افزودنِ کست‌باکس به `platform_of` رفعِ سکوت **نبود**؛ سه چیزِ دیگر خرید —
  UXِ قطعی (`_resolve_ux` برای `AUDIO_PLATFORMS` بی‌قیدوشرط `quick` می‌دهد، وگرنه
  با `dl_default_ux=probe` منوی کیفیتِ **خالی** درمی‌آمد چون `normalize_probe` روی
  منبعِ صوتی `options=[]` می‌دهد)، برچسب/متریکِ per-platform، و **بیمه** در برابرِ
  روزی که ادمین آن کلید را خاموش کند. هرکس این بولت را عوض می‌کند اول مقدارِ
  پیش‌فرض را از `config.py` بخواند، نه از حافظه.
- **resolve کردنِ لینکِ کست‌باکس عمداً رشته‌ای و بی‌شبکه است — محدودیتِ آگاهانه.**
  `/vb/<eid>` از شناسهٔ داخلِ **همان** URL به `/ep/<eid>` بازنویسی می‌شود و `link=`
  هم در رشته‌ای است که از قبل در دست داریم، پس هیچ ریدایرکتی دنبال نمی‌شود. سه
  دلیل: هیچ درخواستی به مسیرِ داغ اضافه نمی‌شود؛ رفتارِ ریدایرکت‌دنبال‌کن خودش یک
  سطحِ SSRF است و وارد نمی‌شود؛ و شکستش **پرصداست نه خاموش**. بهایش این است که
  اگر کست‌باکس فرمِ کوتاهِ تازه‌ای بسازد خودکار حل نمی‌شود — کاربر `dl_bad_link`
  می‌گیرد و ما یک خطِ الگو اضافه می‌کنیم. عمقِ بازکردنِ `link=` **یک** است و با
  ساختار تضمین شده نه با انضباط (`castbox_ids` هیچ بازگشتی ندارد، فقط دو تلاشِ
  `_castbox_direct_ids`).
- **ردیف‌های یتیمِ کشِ کست‌باکس بی‌خطرند و `DELETE` نمی‌خواهند — برخلافِ اسپاتیفای.**
  عضویت در `AUDIO_PLATFORMS` مقدارِ `quick_sel` را از `best` به `audio` می‌برد و
  selector جزءِ کلیدِ کش است، پس ردیف‌های قبلیِ `/ep/` زیرِ `…+best` یتیم می‌شوند.
  **تفاوتِ باربر با اسپاتیفای:** آن‌جا ردیفِ کهنه **سرو می‌شد** و فایلِ غلط می‌داد،
  پس `DELETE` لازم بود؛ این‌جا کلید عوض می‌شود و آن ردیف **هرگز خوانده نمی‌شود** —
  فقط یک ردیفِ بی‌مصرف می‌ماند (جدول eviction ندارد). هزینه‌اش چند ردیف است، نه
  یک جوابِ غلط.
- **ctxِ انتخابگرِ فرمت باید از `YoutubeDL._select_formats` بیاید — رفع شد
  ۲۰۲۶-۰۸-۱۷، و هر دو فلگش غلط بود نه یکی.** `tests/test_soundcloud_path._picked`
  در ctx مقدارِ `incomplete_formats: False` می‌گذاشت و `has_merged_format` را
  اصلاً نمی‌داد؛ اندازه‌گیری‌شده روی همان فیکسچر، yt-dlp مقدارِ **`True`** و
  **`False`** می‌سازد. **نتیجهٔ #۱۱۵ عوض نشد** (اجراشده: هر دو ctx همان
  `http_mp3_0_0` را می‌دهند، چون `ba` بی‌اعتنا به این فلگ‌ها جور می‌شود) — و آن
  ادعا حالا **کنترلِ معکوسِ ثبت‌شده** در دفترچهٔ سابوتاژ است، نه حافظه. ولی هر دو
  فلگ روی همین فیکسچر پیامدِ سنجش‌پذیر دارند: `b` و `bv*+ba/b` با ctxِ هاردکد
  **`None`** می‌دهند و با ctxِ درست `hls_aac_96k` — دقیقاً همان false failِ
  کست‌باکس؛ و `mp4` با ctxِ هاردکد **`KeyError`** می‌دهد، چون
  `build_format_selector` مقدارِ `ctx['has_merged_format']` را با **براکت**
  می‌خواند نه `.get()`.
  **و همین دومی قاعدهٔ عامِ این بولت است: کلیدِ غایب در یک ctx بی‌صدا falsy
  نیست.** غریزه می‌گوید «ندادنش یعنی `None` یعنی نادرست»، و آن غریزه فقط وقتی
  درست است که مصرف‌کننده `.get()` بزند — که این‌جا نمی‌زند. پس هارنسِ قدیمی
  **دو ردهٔ خرابیِ متفاوت** داشت، نه یکی: برای بعضی انتخابگرها یک **نتیجهٔ غلطِ
  خاموش** (`b` و `bv*+ba/b` → `None` به‌جای فرمتِ درست) و برای بعضی دیگر یک
  **کرشِ صریح** (`mp4` → `KeyError`). تفکیکشان مهم است چون فقط ردهٔ اول شبیهِ
  «تستِ ضعیف» به‌نظر می‌رسد؛ ردهٔ دوم اصلاً به assert نمی‌رسد و شبیهِ «تستِ خراب»
  دیده می‌شود. هر ctx/config/stateی که به کدِ بیرونی می‌دهی همین را دارد —
  **کلیدِ نداده‌شده هم یک تصمیم است، نه یک سکوت.**
  رفع: `_picked` حالا `ydl._select_formats(...)` را صدا می‌زند — همان متدی که
  `process_video_result` صدا می‌زند — پس فلگ‌ها از همان جایی می‌آیند که تولید
  می‌سازدشان، و تغییرِ نامش در yt-dlp `AttributeError`ِ بلند می‌دهد نه بازگشتِ
  خاموش. **هارنسِ کست‌باکس هم همان دو عبارت را دستی بازنویسی کرده بود** — باگ
  نبود (درست محاسبه می‌کرد) ولی کپیِ دومِ دست‌نویس از قاعده‌ای است که صاحبش
  yt-dlp است، پس آن هم از خودِ yt-dlp می‌پرسد و قاعده یک جا زندگی می‌کند.
- **`magic_filter.regexp` پیش‌فرضش `match` است نه `search` — و درِ ورودیِ لینک ماه‌ها روی
  همان لنگر بود.** `app/routers/download.py` هندلرِ لینک را با
  `F.text.regexp(r"https?://")` ثبت می‌کرد، و در `magic_filter/magic.py` شاخهٔ
  `if mode is None` مقدارِ `RegexpMode.MATCH` می‌گذارد، یعنی `pattern.match` که به
  **موقعیتِ صفر** لنگر می‌خورد. پس متن باید *با* `http` شروع می‌شد. اندازه‌گیری‌شده روی
  شیءِ واقعیِ فیلتر: متنِ دوخطیِ دکمهٔ Shareِ اپِ ساندکلاود
  («Listen to … on #SoundCloud\n<لینک>»)، اشتراکِ دوخطیِ یوتیوب، «اینو بگیر <لینک>» و
  حتی **یک فاصلهٔ** پیش از لینک همگی رد می‌شدند؛ لینکِ خامِ تک‌خطی — که مسیرِ دسکتاپ و
  کپیِ آدرس‌بار است — کار می‌کرد، و همین پنهانش کرد. چون ترتیبِ روترها
  `start → admin → ops → download → files` است، پیام به catch-allِ `files.py` می‌افتاد و
  کاربر در جوابِ یک لینکِ **معتبر** «یک فایل بفرست» می‌گرفت: جوابِ فعالانه گمراه‌کننده،
  نه سکوت. **نسخه‌محور نیست** — اندازه‌گیری‌شده روی magic-filter ۱.۰.۹ تا ۱.۰.۱۲ که هر
  چهارتا پیش‌فرضشان `match` است، و aiogram 3.30 هم overrideاش نمی‌کند
  (`aiogram/utils/magic_filter.py` فقط `as_` اضافه می‌کند) و `magic-filter>=1.0.12,<1.1`
  را پین می‌کند، پس `mode=` در دسترس است. رفع: `mode="search"`. گاردش **کشف‌محور** است
  نه فهرستِ دستی (`test_every_regexp_filter_states_its_mode_explicitly`): هر
  `regexp(` زیرِ `app/` باید `mode`/`search` صریح داشته باشد، چون این دامِ **پیش‌فرضِ
  کتابخانه** است و هندلرِ بعدی هم همان را می‌خورد.
  **دو چیزِ مربوط که باگ نیستند.** فیلتر (`https?://`) و `find_url`
  (`https?://[^\s<>()]+`) دو الگوی متفاوت برای یک سؤال‌اند و فیلتر می‌تواند جایی HIT
  بدهد که `find_url` چیزی برنگرداند — بی‌خطر، چون `on_link` خودش `if not url: return`
  دارد. و اثرِ جانبیِ `search` روی دستورها: `/start …` و `/admin …`ِ حاوی لینک حالا با
  فیلتر **جور می‌شوند** ولی هرگز به آن نمی‌رسند، چون روترِ دستورها قبل‌تر ثبت شده و
  `admin_cmd` برای غیرِادمین `return` می‌کند نه `SkipHandler`. **تنها هندلری در کلِ ریپو
  که `SkipHandler` می‌زند `cookie_paste` است** (`app/routers/admin.py`) — یعنی تنها درزی
  که پیام از آن به `download` می‌رسد، و رفتارش درست است (پیستِ در انتظار را خودش مصرف
  می‌کند). **کارِ بعدیِ ممکن، عمداً نساخته:** با `search`، لینکِ هاستِ ناشناخته وقتی
  `dl_allow_unknown` خاموش است (یا دانلودر خاموش است) به‌جای «یک فایل بفرست» **سکوت**
  می‌گیرد. سکوت از جوابِ غلط بهتر است، و پیامِ تازه یعنی رشتهٔ locale و شعاعِ بزرگ‌تر
  برای یک رفعِ فوری؛ مسیر هم نادر است. اگر روزی مهم شد، این‌جا ثبت است.
- **انتخابگرِ فرمتِ ساندکلاود: سه چیزِ اجراشده که هرکدام یک دامِ خاموش‌اند.**
  `ba/b`ِ عمومی روی یک ترکِ ساندکلاود `hls_aac_96k` را برمی‌داشت — ۹۶k، ۲۶ فرگمنتِ HLS،
  به‌علاوهٔ یک ترنسکدِ کاملِ AAC→MP3 — در حالی که `http_mp3_0_0` یک GETِ ساده و ۱۲۸k
  است (اندازه‌گیریِ اپراتور: ۱٫۳۹MB/۶ث در برابرِ ۴٫۰۲MB/۲ث). حجمِ ~سه‌برابر **آگاهانه
  پذیرفته شد**: ساندکلاود سرویسِ موسیقی است. **(الف) `acodec` تمایزدهنده نیست.** در
  `SoundcloudBaseIE` مقدارِ `'acodec': codec` از `codecs="…"`ِ داخلِ mime-type می‌آید و
  mp3 مایم‌تایپش `audio/mpeg` است که چنین attributeی **ندارد** → `acodec is None`. پس
  `ba[acodec^=mp3]` — طبیعی‌ترین چیزی که آدم می‌نویسد — **هیچ تطبیقی ندارد** و بی‌صدا به
  `ba` می‌افتد. تمایزدهندهٔ درست `ext` است (`mimetype2ext("audio/mpeg") → mp3`).
  **(ب) فرمِ ضمنی به ترتیبِ ورودی وابسته است.** `ba` آخرین گزینهٔ جورشده را برمی‌دارد، پس
  `ba[ext=mp3]/ba/b` بسته به ترتیبی که yt-dlp فرمت‌ها را می‌چیند می‌تواند `hls_mp3_0_0`
  بدهد (اجراشده، با جابه‌جاییِ فهرست). شرطِ صریحِ `[protocol^=http]` لازم است — همان درسِ
  لنگرِ `regexp`: به پیش‌فرضِ مرتب‌سازیِ کتابخانه تکیه نکن. **(پ) `--audio-format mp3`
  لازم نبود دست بخورد.** `FFmpegExtractAudioPP.run` وقتی `target_format == filecodec`
  باشد `acodec='copy'` می‌گذارد و با پیامِ `Not converting audio …; file is already in
  target format mp3` زودتر برمی‌گردد. پس کلِ مسئله در **انتخابگر** بود، نه در `-x`؛ یک
  خط عوض شد نه دو تا. زنجیره `ba[ext=mp3][protocol^=http]/ba[ext=mp3]/ba/b` است و دُمِ
  `ba/b` عمداً دست‌نخورده مانده تا وقتی ساندکلاود MP3 را حذف کند (اعلام کرده) خودش به
  AAC برگردد. فقط ساندکلاود گیت خورده: بقیهٔ `AUDIO_PLATFORMS` منظرِ فرمتشان اندازه‌گیری
  نشده و بیت‌به‌بیت همان `ba/b` را می‌گیرند.
  **و تلهٔ چهارم در خودِ تست بود، نه در کد:** چون `ba` آخرین را برمی‌دارد، ترتیبِ فهرستِ
  فیکسچر تعیین می‌کند انتخابگرِ **عمومی** چه بدهد — با AACِ اول، تستِ اصلی روی سورسِ
  پیش از رفع هم سبز می‌ماند. یعنی هارنس باید صریح ثابت کند رفتارِ تولید را بازتولید
  می‌کند (`ba/b` → `hls_aac_96k`) وگرنه هر سبزِ دیگری بی‌معناست. سابوتاژ گرفتش، نه
  بازخوانی.
- **`on.soundcloud.com` نرمال‌سازی‌شدنی نیست؛ کلیدِ دومِ کش از `webpage_url` می‌آید.**
  سه فرمِ یک ترک سه کلیدِ متفاوت می‌ساختند. `sc:<user>/<slug>` (هم‌شکلِ `sp:`/`am:`)
  فرم‌های `www.`/`m.`/کوئری‌دار را جمع می‌کند — ولی شورت‌لینک شناسهٔ محتوا نیست، یک
  توکنِ مبهمِ ریدایرکت است، پس **هیچ الگویی** نمی‌تواند جمعش کند. راهِ ارزان: yt-dlp
  خودش ریدایرکت را دنبال می‌کند و `webpage_url` فرمِ کانونیک را برمی‌گرداند، پس
  `put_cached` یک ردیفِ **دوم** زیرِ کلیدِ آن می‌نویسد — صفر درخواستِ شبکهٔ اضافه و صفر
  سطحِ SSRF، در برابرِ گزینهٔ resolve-پیش-از-enqueue که هر دو را می‌خرید. پوشش: تکرارِ
  همان شورت‌لینک · لینکِ کاملِ همان ترک. **شورت‌کدِ متفاوتِ همان ترک همچنان miss
  می‌خورد** و این حدِ روش است، نه باگ. دو قیدِ باربر: کلیدِ دوم باید از همان
  `cache_key` رد شود نه از URLِ خام (وگرنه ردیفِ دوم زیرِ یک شکلِ خاص می‌نشیند و شکلِ
  دیگر باز miss می‌خورد)؛ و نوشتنِ دوم به `platform not in _MATCH_PLATFORMS` گیت خورده،
  چون برای اسپاتیفای/اپل `webpage_url` آدرسِ **یوتیوب** است و ردیفِ یوتیوب‌کلید
  `_MATCH_VERSION` نمی‌گیرد — یعنی تغییرِ ماچر دیگر باطلش نمی‌کند، دقیقاً همان «جوابِ
  کهنه برای همیشه» که نسخه‌دارکردن برای بستنش ساخته شد.
- **سه پیامِ «سشن» برای سطلی که سشن ندارد و نمی‌تواند داشته باشد.** چون
  `_cookie_platform` چهارده سطل می‌خواهد و `admin_web.COOKIE_PLATFORMS` شش تا می‌سازد،
  ساندکلاود (و هفت پلتفرمِ دیگر) سطلی می‌خواهند که پرکردنی نیست — و هر سه پیام دربارهٔ
  سشن حرف می‌زدند: وسطِ حلقه «اکانتِ دیگری را امتحان می‌کنم» (وعده‌ای بی‌پشتوانه، چون
  `cookie_name` تهی است)، و در پایان یا «ادمین باید کوکی تنظیم کند» (دستورِ اجراناپذیر)
  یا «سشن دیگر معتبر نیست» (دربارهٔ سشنی که وجود ندارد). مرز همان تفکیکِ سه‌حالتهٔ
  `_alert_if_low` است — «۰ از N» و «۰ از ۰ ولی زمانی پر بوده» هر دو **واقعاً** دربارهٔ
  سشن‌اند و پیامِ قبلی را نگه می‌دارند. **و fail-safeاش یک `ping` لازم دارد نه فقط
  `try`:** هم `pool_counts` هم `was_stocked` خطای Redis را خودشان می‌بلعند و
  `(0, 0)`/`False` می‌دهند، پس «سطل خالی است» و «Redis خواب است» از بیرون یکی‌اند و
  `try`ِ بیرونی هرگز شلیک نمی‌کند؛ بدونِ پروب، یک قطعیِ گذرا به کاربر می‌گفت «این سرویس
  پشتیبانی نمی‌شود».
- **یک باگ در لایهٔ روتینگ در هیچ شمارنده‌ای دیده نمی‌شود — تله‌متری فقط چیزی را می‌بیند
  که وارد شده باشد.** این درسِ بزرگ‌ترِ باگِ بالاست و از خودش دوام بیشتری دارد. همهٔ
  سنجه‌های مسیرِ دانلود (`_metric` → `dlstat:<platform>:{ok,fail}`، `dlctx:`, `probe:`,
  `dl:active:z`, سطل‌های `ckuse:`) **داخلِ `run_download`** زندگی می‌کنند؛ وقتی فیلترِ
  روتر رد شود هیچ جابی ساخته نمی‌شود که چیزی بشمارد. یعنی هر کاربری که لینکش را با
  متنِ اپ فرستاد **در مخرج هم نبود**: پنل سالم به‌نظر می‌رسید و نرخِ موفقیت دربارهٔ
  «جاب‌هایی که اجرا شدند» حرف می‌زد، نه «لینک‌هایی که کاربر فرستاد». قاعدهٔ عملی: پیش
  از استدلال روی هر نرخی، اول بپرس **درِ ورودی چه چیزی را اصلاً وارد نکرده** — و برای
  درِ ورودی تنها سنجهٔ امروزی شکایتِ کاربر است، که یعنی این ردهٔ باگ می‌تواند ماه‌ها
  زنده بماند بی‌آنکه هیچ عددی تکان بخورد. همین رده است که تفکیکِ «۱ از ۳ لینکِ
  ساندکلاود» را هم بی‌معنا می‌کند: آن کسر فقط جاب‌های اجراشده را می‌شمارد، و
  `safety.check_url` هم که در روتر رد می‌کند هیچ `dlstat`ی نمی‌نویسد.
- **تا دفترچهٔ سابوتاژ می‌دود، `git status`/`git diff` وضعیتِ *گذرا* نشان می‌دهد — نه
  کارِ تو.** `python -m tests.sabotage` هر مورد را با بازنویسیِ **واقعیِ** فایلِ سورس
  اعمال می‌کند و در `finally` برمی‌گرداند (`tests/sabotage.py`)، و چون ۳۵ مورد هرکدام
  یک اجرای pytest می‌خواهند، پنجره چند دقیقه باز است. اتفاقی که افتاد: وسطِ همان اجرا
  `git diff` گرفتم و `app/instagram_anon.py` را «تغییرکرده» دیدم، فایلی که اصلاً لمسش
  نکرده بودم. این‌بار بی‌ضرر تمام شد چون `finally` کارش را کرد، ولی شکلِ خطرناکش این
  است که کسی آن تغییرِ موقت را **باگ** بخواند و دنبالش بگردد، یا بدتر، وسطِ همان پنجره
  `git add -A` بزند و یک سورسِ خراب‌شده را کامیت کند. قاعده: **وضعیتِ درخت را فقط
  بعد از تمام‌شدنِ دفترچه بسنج** — و اگر اجرا در پس‌زمینه است، اول تمام‌شدنش را تأیید
  کن، بعد `git status`. همین دلیلِ دیگری است بر اینکه دفترچه هرگز نباید در CI یا موازی
  اجرا شود، که §۶ از قبل می‌گوید.
- **یک فرمِ پنل که «ذخیره شد» بگوید و کاری نکرده باشد، از یک خطای صریح بدتر است — و
  چهار نمونه‌اش یک الگوی واحد داشتند.** هر چهار مورد ورودیِ نامعتبر را با یک `continue`
  یا یک `elif` بی‌صدا دور می‌ریختند و بعد **بی‌قیدوشرط** بنرِ سبز می‌دادند. از بیرون
  «ذخیره شد» و «ذخیره نشد» یکی‌اند، و همین است که این رده را ماه‌ها زنده نگه می‌دارد —
  هم‌ردهٔ «باگِ لایهٔ روتینگ در هیچ شمارنده‌ای دیده نمی‌شود»، با این تفاوت که این‌جا
  **کاربر هم** سیگنالِ غلط می‌گیرد نه صرفاً سکوت. `_result()` در `admin_web` تنها راهِ
  ساختنِ `ok=`/`err=` است و یک گاردِ ASTی
  (`test_the_panel_has_one_result_redirect`) کپیِ بعدی را می‌گیرد؛ **بدونِ فهرستِ
  استثنا**، که برای همین هر محلِ فراخوانی در همان کامیت تبدیل شد.
  **سه ریزه‌کاری که هرکدام یک تلهٔ مستقل‌اند.** (۱) **`buttons_save` اعتبارسنجی و نوشتن
  را در یک حلقه داشت**، پس شاخهٔ `elif` هر متنی را که `validate()` رد می‌کرد به «حذفِ
  override» ترجمه می‌کرد: یک تایپ در placeholder برچسبِ سالم را پاک می‌کرد.
  `texts_save` همین حالت را **درست** هندل می‌کرد — یعنی ناسازگاریِ دو صفحه بود نه
  محدودیتِ طراحی. (۲) **`isdigit()` معیارِ عددی‌بودن نیست، `int()` است** — چون
  `get_int()` بعداً همان را می‌زند. اندازه‌گیری‌شده: `--5` و `⑦` و `²` از `isdigit()`
  رد می‌شوند و `int()` رویشان می‌ترکد، پس ردیف در `settings` **نوشته می‌شد** و بعد
  هیچ‌جا بازتاب نداشت — `get_int()` به پیش‌فرض برمی‌گشت و `_effective()` هم که همان
  `except ValueError` را دارد در صفحه پیش‌فرض نشان می‌داد. ردیفِ زباله‌ای که نه اثری
  دارد نه دیده می‌شود. (۳) **`nodes_add` فیلدِ `name`ِ فرم را هرگز نمی‌خواند**؛ نامِ
  واقعی از `hostname -s`ِ خودِ نود می‌آمد و راهِ تغییرِ نام هم وجود ندارد.
- **کرانِ عددیِ تنظیمات فقط جایی هست که مشتق‌شدنی است — و بقیه عمداً بی‌کران‌اند.**
  `settings_store.BOUNDS` کف را برای **همهٔ** کلیدهای `int` صفر می‌گذارد (منفی هیچ‌جا
  معنا ندارد و فقط به یک مقایسهٔ همیشه‌غلط تبدیل می‌شود) و صفر مجاز می‌ماند چون در این
  پروژه معنیِ تثبیت‌شده دارد: «بی‌سقف/خاموش» (`ck_cap_*`، `safety_strikes`،
  `vjoin_max_mb`). سقف سه منبع دارد و هر سه در کد/مستند نوشته شده‌اند:
  `_UPLOAD_CEILING_MB = 2000`، ۱۰۰ برای دو کلیدی که `config.py` واحدشان را «درصد»
  اعلام کرده، و ۱۰۰ برای `match_min` که بازه‌اش در `config.py` نوشته شده.
  **و سقفِ ۲۰۰۰ فقط یک جهت را می‌بندد — این نکته‌ای است که نسخهٔ اولِ همین بولت را
  غلط کرد.** `--local` دو محدودیتِ متفاوت دارد، نه یکی: «دانلود **بدونِ محدودیتِ
  حجم**، آپلود **تا ۲۰۰۰ مگابایت**» (نقلِ مستقیم از READMEِ `tdlib/telegram-bot-api`).
  پس ۲۰۰۰ فقط به کلیدی می‌خورد که بایتِ تازه به تلگرام می‌فرستد، و روی کلیدِ سمتِ
  **دریافت** مسیری را می‌بندد که در تولید کار می‌کند — جدولِ `files` روی مستر ۴۴ ردیفِ
  بالای ۲۰۰۰ مگ دارد و بزرگ‌ترینش ۳۹۱۲ مگ است. طبقه‌بندی با **ردیابیِ محلِ خواندن**
  انجام شد نه شباهتِ نام:

  | کلید | خوانده می‌شود در | چه چیزی را می‌سنجد | جهت | سقف |
  |---|---|---|---|---|
  | `max_file_mb` | `ops.py:_max_mb` → `_too_large` | آیا روی فایلِ **از قبل دریافت‌شده** عملیات اجرا شود | دریافت (intake اصلاً چک نمی‌کند؛ کارت با `file_id` می‌رود) | **ندارد** |
  | `dl_max_size_mb` | `tasks_download.py` | حجمِ روی دیسک **پیش از آپلود** | آپلود | ۲۰۰۰ |
  | `dl_direct_max_mb` | `tasks_download.py` | دانلودِ موتورِ direct | آپلود | ۲۰۰۰ |
  | `vjoin_max_mb` | `ops.py:_vjoin_cap_mb` | مجموعِ حجمِ **ورودی‌ها** (پروکسیِ خروجی) | آپلود | ۲۰۰۰ |
  | `compress_tiny_target_mb` | `tasks.py` → `compress_video_tiny(target_mb=)` | حجمِ هدفِ **خروجی** | آپلود | ۲۰۰۰ |

  **`dl_direct_max_mb` برخلافِ شهود سمتِ آپلود است** و این با اجرا معلوم شد نه
  استدلال: انتظار این بود که از گیت‌وی `/dl` سرو شود و از تلگرام رد نشود، ولی
  `probe_direct` → `download_direct` → `_spawn`/`_deliver_single` →
  `_media_arg(f, path)` مقدارِ `FSInputFile` می‌دهد. `op_link` (تنها نویسندهٔ
  `dl_token`) مسیرِ دیگری است و روی فایلی کار می‌کند که **از قبل** کارت شده.
  و `tasks_download` خودش هم `dl_direct_max_mb` را با `dl_max_size_mb` `min` می‌کند —
  مگر وقتی `dl_max_size_mb = 0` باشد، که آن‌وقت این سقف تنها محافظ است.
  **مکانیزمِ همهٔ این‌ها یک نقطه است:** `cards._media_arg` — `path` بدهی
  `FSInputFile` می‌شود (بایت روی سیم)، ندهی `file_id` می‌ماند (صفر بایت). **بقیه سقف ندارند و این تصمیم است نه فراموشی**:
  `safety_video_frames = 9999` هنوز پذیرفته می‌شود، چون کرانِ قابلِ‌دفاعی برایش وجود
  ندارد و ثابتِ دستیِ ساختگی همان چیزی است که §۷ بارها ثبت کرده می‌پوسد.
  **اعتبارسنجی در `settings_store` است نه در پنل**، چون `routers/admin` نمی‌تواند
  `admin_web` را import کند (ایمیجِ ربات jinja2/cryptography ندارد) — همان قیدی که
  `cookies.py` و `dl_active.py` را سرِ جایشان نشانده؛ پیش از این هر دو مسیر تابعِ
  اعتبارسنجیِ **خودشان** را داشتند و هر دو بی‌کران بودند.
- **رقمِ غیرِASCII در تنظیمات از قبل کار می‌کرد و عمداً نرمال‌سازی نشد.** فرضِ طبیعی
  این است که `۲۰۰۰` رد می‌شود یا باید تبدیل شود؛ هر دو غلط‌اند. اندازه‌گیری‌شده:
  `'۲۰۰۰'.isdigit()` صادق است، `int('۲۰۰۰')` مقدار ۲۰۰۰ می‌دهد، و `_effective()` هم
  برای نمایش `int()` می‌زند — پس مقدارِ مؤثر **و** نمایشِ صفحه هر دو از قبل درست
  بودند و سوییچ از `isdigit()` به `int()` هم چیزی را عوض نمی‌کند (کنترل دارد).
  تنها ردِ باقی‌مانده این است که رشتهٔ ذخیره‌شده در `settings` غیرASCII می‌ماند و
  چون `changed` مقایسهٔ **رشته‌ای** است، مقداری که با پیش‌فرض برابر است به‌جای reset
  یک ردیفِ اضافه می‌نویسد. **صفر مصرف‌کننده‌ای این را می‌بیند** — سرشماری‌شده روی هر
  ۳۴ کلیدِ `int`: هیچ‌کدام با `get_str`/`get_bool` خوانده نمی‌شوند. پس نرمال‌سازی
  یک تغییرِ رفتار بود بدونِ هیچ سودِ اندازه‌گیری‌شده، و برای پنلی که کاملاً فارسی و
  `dir=rtl` است حتی بدترش می‌کرد. **ثبت شد، ساخته نشد.**
- **Local Bot API server**: files are on its disk; `bot.get_file(file_id)` can trigger a full download from Telegram DC on first call (slow) — workers/gateway use long `request_timeout` (600 s). **Upload ceiling is `settings_store.UPLOAD_CEILING_MB` (2000) and it is *not* `MAX_FILE_MB`** — the two were conflated here until 2026-08-18 and the old wording («upload ceiling ≈ `MAX_FILE_MB`; larger files can't be carded/served») was wrong in both halves: `--local` lifts the **download** limit entirely, and a file above 2000 MB **is** carded fine because the card goes out by `file_id` (production: 44 rows above 2000 MB in `files`, largest 3912 MB). What 2000 bounds is bytes *we* push — see the next bullet.
- **هر عملیاتی که خروجیِ تازه می‌سازد می‌تواند کارش را تمام کند و سرِ ارسال بشکند — گارد در `tasks.run_op` است، پیش از کلِ زنجیرهٔ تحویل.** دریافت سقف ندارد، آپلود دارد؛ پس `compress`/`convert`/`trim`/`zip`/`rename`/… خروجی‌ای می‌سازند که ممکن است از ۲۰۰۰ مگ رد کند و **بعد از** خرجِ CPU و دیسک در ارسال بشکند. `_too_big_to_send(_outgoing_paths(res))` روی حجمِ **روی دیسک** تصمیم می‌گیرد، هم‌شکلِ «چکِ قطعیِ حجم قبل از آپلود»ِ `tasks_download`.
  **چهار چیز که با اجرا معلوم شد و طراحی را ساخت.** **(۱) رفتارِ پیش از رفع دو شکل داشت، نه یک شکل:** شاخه‌های `path`/`send_media` مقدارِ `failed` می‌دادند با پیامِ عمومی و دُمِ خامِ انگلیسی، ولی `spawn`/`files` مقدارِ **`done`** می‌دادند و برچسب را در `changelog` می‌نوشتند در حالی که هیچ فایلی نرسیده بود — **موفقیتِ کاذب**، چون استثنا فقط `log.exception`/`log.warning` می‌شد. **(۲) شاخهٔ `spawn` ردیفِ `File` را پیش از آپلود commit می‌کند**، پس شکستِ ارسال یک ردیفِ یتیم با `file_id=""` در جدولِ `files` جا می‌گذاشت (اندازه‌گیری‌شده: ۲ ردیف در برابرِ ۱ برای سه شاخهٔ دیگر). گیتِ **واحد** پیش از کلِ زنجیره هر دو را رایگان می‌بندد؛ چهار چکِ پراکنده نمی‌بست. **(۳) اگر سرور به‌جای ۴۱۳ جوابِ ۴۰۰ بدهد، بایت‌ها سه بار می‌روند** — `update_card` روی `TelegramBadRequest` به `send_card` می‌افتد و آن به `send_document` (اندازه‌گیری‌شده روی `cards`ِ واقعی: ۱ آپلود با ۴۱۳، **۳** با ۴۰۰). کدامش را سرورِ محلی می‌دهد از سندباکس معلوم نیست و **برای رفع بی‌اهمیت است**، چون گارد اصلاً به آن‌جا نمی‌رسد. **(۴) `_too_large` بیشترِ opها را از قبل سپر می‌کند ولی نه همه** — گیت‌دار: compress, convert, resize, rotate, scan, transcribe, normalize, speed, direct, image_direct؛ **بی‌گیت**: `rename`, `collect_go` (zip_many/pdf_merge/video_concat/images_to_pdf), `meta_write`, `watermark`, `trim`, `screenshot`. پس در پیکربندیِ **پیش‌فرضِ امروز** پرتگاه از `rename` و `zip_many` باز است، نه از vjoin؛ و برای opهای گیت‌دار فقط وقتی که ورودی زیرِ ۲۰۰۰ باشد و خروجی رد کند (`convert` می‌تواند بزرگ کند).
  **چهار قیدِ طراحی که نباید عوض شوند.** `job.error` عمداً **حجم را حمل نمی‌کند** — صفحهٔ آمار خطاها را با متنِ دقیقشان گروه می‌کند (`admin_web`, حلقهٔ `err_rows`)، پس عددِ متغیر یعنی هر ردِ حجمی یک کلیدِ یکتا با شمارِ ۱ و این کلاس هرگز در «پرتکرارترین خطاها» بالا نمی‌آید؛ عدد در پیامِ کاربر و خطِ لاگ (که `job_id` هم دارد) می‌ماند. سقف **کلیدِ تنظیمات نیست** — حدِ پلتفرم است، و خاموش‌کردنش صرفاً یعنی برگشتن به شکستِ بعد از کار؛ به همین دلیل `settings_store.UPLOAD_CEILING_MB` **عمومی** شد به‌جای اینکه `2000` دوباره در `tasks.py` نوشته شود (همان دو کپیِ دست‌نویسِ `remove_cookie_file`). مقایسه روی **بایت** است و گرد کردن فقط برای نمایش، وگرنه فایلِ روی مرز به گردکردن باج می‌دهد. و هر آیتم **جدا** سنجیده می‌شود نه مجموع، چون شاخهٔ `files` هر فایل را با یک `send_document`ِ مستقل می‌فرستد — جمع‌زدن ده فایلِ ۳۰۰ مگی را به‌غلط رد می‌کرد.
  **و تخمینِ پیش‌از‌شروع بررسی و رد شد، جز دو حالت:** `rename` خروجی‌اش **عیناً** ورودی است (`_do_op` مقدارِ `{"path": inpath}` می‌دهد) پس دقیقاً معلوم است، و مجموعه‌ها (`zip`/`merge`/`img_pdf`/`vjoin`) مجموعِ `members[].size` را دارند که پروکسیِ خوبی است — ولی fallbackِ تک‌عضویِ `op_collect_go` کلیدِ `size` **ندارد**. برای بقیه پیش‌بینی‌پذیر نیست، و همین است که جای گارد را **بعد از تولید** تعیین می‌کند. خوش‌شانسی: `os.path.getsize(outpath)` از قبل دقیقاً همان‌جا محاسبه می‌شد.
- **Read-only `/cookies` mount**: yt-dlp/gallery-dl must copy the cookie to a writable temp first (`downloader._writable_cookie`), else `OSError: read-only file system`.
- **Updating a node ≠ `telabzar update`**: `telabzar update` on the master rebuilds only the master's containers. A **node runs its own separately-built image** (`telabzar-node:<role>`, built by `node/install.sh` on the node host), so any fix that changes code **running on the node** (`run_download`/`_pick_cookies`, `run_op`, `gateway_node`, …) does **not** reach the node until the node's image is rebuilt. Run `cd /opt/telabzar-node/repo && sudo git pull && sudo bash node/update.sh` on the node — it reads the running container's env/image/command, pulls, rebuilds the role's Dockerfile, and recreates the container (no re-join, same WG identity). Master-only changes (routing in `download.py`, compose, `nodes.py` reaper) need only the master update.
  **The Instagram anonymous path is a live instance of this, and it degrades quietly rather than failing.** `instagram_anon.py`/`tasks_download.py` run on the download node too, so a node still on pre-phase-2 code has no anonymous path at all: `dl_ig_anon_enabled` is read from shared settings but nothing on that node acts on it, and every Instagram download routed there goes straight to the cookie pool — exactly today's behaviour, no error, no user-visible symptom. The only signal is the telemetry: `dlstat:iganon:*` stays flat while Instagram downloads keep happening. So when a node is attached, run `node/update.sh` **before** reading those counters, or the numbers describe the master alone.
- **A failing cookie must roll over, not fail the user**: `run_download` (probe **and** fetch) wraps the engine call in a
cookie-retry loop — on a cookie-shaped error (`_is_cookie_error`: login/ban/checkpoint/YT bot-check) it marks the account
failed (escalating cooldown), excludes it, and retries with the **next** account from `cookies.pick()`. The user only sees
an error when the pool is exhausted. Non-cookie errors (404, too-large, private) do **not** roll over and do **not**
penalise the account — otherwise one bad URL would burn the whole pool. Alerts fire (once per 6 h per platform) when
usable accounts drop below `cookie_alert_min`.
- **🔴 فازِ probe از `_charge` رد نمی‌شود — این یک حفرهٔ سوءاستفاده است، نه یک ناکارآمدی. شناسایی‌شده ۲۰۲۶-۰۸-۱۷، رفع نشده.** بقیهٔ یافته‌های همان شناسایی («probe کوکی می‌خرد و در سطلِ ساعتی شمرده نمی‌شود»، «از `dl_active` رد می‌شود»، «کشِ آنی چک نمی‌شود») هزینه‌اند؛ **این یکی امنیتی است و باید جدا از آن‌ها دیده شود.** `_charge` در **روتر** زندگی می‌کند نه ورکر: شاخهٔ quick سرِ intake شارژ می‌کند (`routers/download.py:249`) ولی شاخهٔ probe **نمی‌کند** (`:253`) و شارژ به `on_dl_pick` موکول می‌شود (`:300`). و چون `dl_ux_youtube = probe` در تولید ست است، مسیرِ probe مسیرِ **پیش‌فرضِ یوتیوب** است. نتیجه، با اجرا تأییدشده روی `run_download`ِ واقعی: یک کاربر می‌تواند **۱۰۰ لینک بفرستد، ۱۰۰ منو بگیرد، ۱۰۰ کوکی خرج کند و صفر شارژ شود** — `dlq:cnt`/`dlq:cd`/`dlq:mb` هر سه دست‌نخورده می‌مانند، پس نه سقفِ روزانه اعمال می‌شود نه کول‌داونِ بینِ درخواست‌ها. یعنی گران‌ترین منبعِ پروژه (استخرِ سشن، §۷) پشتِ مسیری است که **هیچ سهمیه‌ای رویش نیست**، و چون probe هیچ `dlstat`ی هم نمی‌نویسد (`_metric` در آن شاخه فقط روی شکست است، `tasks_download.py:866`) این مصرف در هیچ شمارنده‌ای دیده نمی‌شود — همان ردهٔ «باگِ لایهٔ روتینگ در هیچ سنجه‌ای دیده نمی‌شود» که §۷ برای فیلترِ لینک ثبت کرده. **تلهٔ رفع:** شارژکردن سرِ intake یعنی کاربرِ عادی **دوبار** شارژ می‌شود (intake + pick)، پس رفع یا جابه‌جاییِ نقطهٔ شارژ است یا یک شمارندهٔ ارزان‌ترِ جدا برای probe؛ نه یک خطِ اضافه. **ترتیبِ توافق‌شده (اپراتور): اول شمارنده تا داده بسازد، بعد رفع** — همان الگویی که برای یوتیوب جواب داد (خطِ لاگ اول، تصمیم بعد)، چون امروز نمی‌دانیم نرخِ رهاشدنِ probe ۲٪ است یا ۶۰٪ و آن عدد شکلِ رفع را تعیین می‌کند. **شمارنده‌اش ۲۰۲۶-۰۸-۱۸ ساخته شد (`app/probe_stats.py`) — بولتِ بعدی. خودِ حفره همچنان باز است.**
- **شمارندهٔ فازِ probe: فرمول، و خطایی که باید کنارش خوانده شود.** هفت سطل زیرِ `dlstat:probe:<bucket>:<YYYYMMDD>` با همان `INCR`+`EXPIRE 172800`ِ `_metric` (زیرفضای نام‌دار، مثلِ `dlstat:iganon:*`؛ با کارتِ per-platformِ صفحهٔ سلامت تداخل ندارد چون آن حلقه روی `KNOWN_PLATFORMS` می‌گردد و `probe` عضوش نیست):

  | سطل | معنی |
  |---|---|
  | `attempt` | هر فراخوانِ موتور — روی سطلِ پرِ کوکی یعنی **مصرفِ اکانت** |
  | `fail` | probe چیزی نداد (حلقهٔ چرخش تمام شد) |
  | `blocked` | موفق، ولی سیاست (سنی/مدت) پیش از منو ردش کرد |
  | `menu` | منوی کیفیت به کاربر رسید |
  | `pick` / `repick` | انتخابِ کیفیت — اولین بار روی هر منو / بعدی‌ها |
  | `menucancel` | cancel روی منویی که هنوز pick نشده |

      probeهای اجراشده = fail + blocked + menu
      رهاشده           = menu − pick − menucancel

  **`blocked` جداست و این نکتهٔ کلِ طراحی است:** آن‌ها probeِ *موفق*اند که هرگز
  منو نمی‌بینند، پس هرگز pick‌شدنی نیستند؛ ریختنشان در یک سطلِ «ok» یعنی هر
  لینکِ سنی/بلند «رهاشده» شمرده شود. و **`attempt` جدا از تعدادِ probe است**،
  چون حلقهٔ چرخشِ کوکی تا `dl_max_cookie_tries` بار موتور را صدا می‌زند —
  سؤالِ واقعی مصرفِ منبع است و واحدش تلاش است نه جاب.
  **سه منبعِ خطا، و عددی که خطایش را ندانیم بدتر از نداشتنش است:**
  **(۱) مرزِ روزِ UTC** — منوی ۲۳:۵۸ و pickِ ۰۰:۰۳ در دو سطلِ روز می‌افتند؛
  کرانش TTLِ ۱۸۰۰ ثانیه‌ایِ نشانگر است، یعنی حداکثر ۳۰ دقیقه در هر مرز. پس
  **چندروزه بخوان، نه تک‌روز** — همان دلیلی که §۷ برای کارتِ سلامت ثبت کرده
  (پنجرهٔ یک‌روزهٔ کارت در برابرِ TTLِ دوروزهٔ `dlstat`).
  **(۲) `_edit` استثنا را می‌بلعد** (`tasks_download._edit`)، پس شاخهٔ منوی
  **متنی** می‌تواند «منو» بشمارد در حالی که کاربر چیزی ندیده — `menu` و در
  نتیجه «رهاشده» را بالا می‌برد. شاخهٔ عکسی این نقص را ندارد (استثنا آن‌جا به
  مسیرِ متنی سقوط می‌کند، پس منویی که شمرده شده واقعاً رفته).
  **(۳) `repick` دو چیز را قاطی می‌کند:** pickِ دومِ واقعی، و pick بعد از
  انقضای نشانگر (>۳۰ دقیقه). فرمولِ رهاشدن درست می‌ماند، ولی خودِ `repick` را
  خالص «چندبار زدن» نخوان.
  **و `probe:{ref}`ِ موجود عمداً بازاستفاده نشد** با اینکه هیچ‌جای ریپو خوانده
  نمی‌شود (فقط در شاخهٔ probe نوشته می‌شود): §۷ آن را به‌عنوان سنجهٔ اپراتوری
  ثبت کرده و پاک‌کردنش سرِ pick، آن نسبت را بی‌صدا از «سهمِ probe» به «سهمِ
  probeِ رهاشده» تغییرِ معنا می‌دهد — همان ردهٔ «معنای یک سنجه بی‌صدا عوض
  می‌شود». ضمناً آن کلید به ناتهی‌بودنِ `options` گیت خورده، پس منوی بی‌گزینه
  نشانگر نمی‌گرفت و کم‌شماری می‌کرد.
  **قیدِ نود:** `tasks_download` روی نودِ دانلود هم می‌دود، پس تا `node/update.sh`
  اجرا نشود این اعداد **فقط مسترند** — همان تلهٔ ثبت‌شده برای `dlstat:iganon:*`.
- **Cookies must reach the download node**: the panel writes cookie files to the master's `cookies_dir`, but a **download node has no such disk** (`node/install.sh` sets no `COOKIES_DIR`), so before the fix its `_pick_cookies` always returned `None` → Instagram/YT-with-cookies ran cookieless on the node → "admin must set cookies" even though a fresh cookie was uploaded. Fix: the panel **mirrors cookies into Redis** (`ckfiles` set + `ckfile:<name>` content) on upload/delete and reconciles on startup (`admin_web._mirror_all_cookies`); `tasks_download._pick_cookies(redis, platform, workdir)` reads local disk on the master, else the Redis mirror on the node (materialising into `workdir/ck/<name>`, cleaned with the workdir). Rotation/cooldown (`ckrot:`/`ckcd:` in shared Redis) work in both. The `_CK_SET`/`_CK_CONTENT` key names must stay in sync between `admin_web` and `tasks_download`. Any master-local state a node needs (cookies, later maybe more) has to be shared via Redis/Postgres — the node only reaches the master over WG.
- **The bot writes cookies too — not just the panel — and its container had nowhere to write them.** The
  Telegram-side paste flow (`routers/admin.py:224` → `cookies._save_cookie`, and the delete at `:195`)
  runs in the **bot** process, but the `bot` service had neither `COOKIES_DIR` nor the `./cookies` mount
  that `admin` and `download-worker` have. With the old empty default that meant
  `os.path.join("", name)` — a **relative** path — so the pasted cookie landed in the bot container's
  CWD, ephemeral and invisible everywhere it mattered. The Redis mirror did not save it, because
  `list_names` gives the **disk branch** priority whenever it actually finds `*.txt` files, and on the
  master it always does — so the panel never listed the pasted account and the master's own
  download-worker never used it. (Fixing the default alone would have converted this from silent to a
  plain «ذخیره نشد.», which is better but still broken.) Both the env var and the mount are now on the
  `bot` service, and a test reads `docker-compose.yml` **per service** — with a plain substring check the
  guard would pass on `admin`'s copy and prove nothing about `bot`, which is why `PyYAML` is now a test
  dependency. Rule: any process that calls a `cookies.py` write helper needs the shared dir mounted, and
  a compose guard must be scoped to the service it is about.
- **`settings_store.set()` was a check-then-act, and the `match_*` migration made it reachable from
  every process at once.** `SELECT` then `INSERT` means two processes writing the same *new* key both
  see `row is None`, and the second one dies on `UNIQUE constraint failed: settings.key`. That was
  harmless while the panel was the only writer — one process, low rate — but migration-on-read runs
  in **every** process on its first read, and after a `telabzar update` they all start together.
  Reproduced by running it, not by reading: two concurrent `get_int("match_min", …)` raised
  `IntegrityError`. Since `get()` sits in the hot path of `_dl_opts`, that is a failed download, not
  a cosmetic error. `set()` now retries once, where the second pass finds the row and updates it.
  **The migrate path also must not write a negative cache.** When it finds nothing under the old
  name it returns `None` without caching that fact, because another process may have just finished
  migrating and set `cfg:<key>` to the real value — writing `_MISSING` over it buries the admin's
  setting **permanently** (the negative key has no TTL), which is the exact silent degradation the
  migration exists to prevent. The window is narrow (the late reader must have missed the DB before
  the winner's `set()` and read the old name after its `reset()`), so the test **forces that
  interleaving** rather than running things concurrently and hoping: an earlier version did two
  ordinary reads, never reached the branch, and a sabotage proved it vacuous for that claim.
- **Cross-process settings staleness**: `settings_store` is read-through Redis (durable copy in Postgres), NOT an in-process TTL cache — so a panel change is seen instantly by bot **and** worker. Reading `settings.X` directly bypasses this and silently ignores the panel.
- **yt-dlp deps**: needs Deno (JS runtime) + `bgutil-pot-provider` for YouTube PO tokens. The pot plugin can crash yt-dlp → toggle `DL_POT_ENABLED` off and there is a retry-without-pot path. Datacenter IPs get blocked → route via `PROXY_URL` (your own clean exit). **ولی PO token روی این استقرار اثری ندارد — بولتِ بعدی را قبل از هر تصمیمی دربارهٔ pot بخوان.**
- **PO token روی این سرور بی‌اثر است — و این را باید با هر چهار حالت خواند، وگرنه «pot خراب بود»
  فهمیده می‌شود.** اندازه‌گیریِ زندهٔ اپراتور روی مستر (۲۰۲۶-۰۸-۱۶)، **یک** ویدیو، **چهار** حالت:

  | | با pot | بدونِ pot |
  |---|---|---|
  | **ناشناس** | bot-check | bot-check |
  | **با کوکی** | OK — ۵۹۱۴۵۶ بایت | OK — ۵۹۱۶۲۱ بایت |

  اختلافِ ۱۶۵ بایتِ دو خانهٔ پایین نویزِ متادیتاست، نه تفاوتِ کیفیت. **و کنترلِ سلامت بخشِ
  تصمیم‌کننده است:** `bgutil-pot-provider` در همان لحظه زنده و سالم بود (ping → نسخهٔ `1.3.1`،
  آپ‌تایم ~۶ روز)، پس این «سرویس خراب است» نیست. نتیجهٔ دوتایی و صریح: pot **نه** گیتِ ناشناس را
  باز می‌کند، **و نه** وقتی کوکی هست چیزی اضافه می‌کند. بدونِ خانهٔ «ناشناس بدونِ pot» می‌شد
  نتیجه گرفت pot کار نمی‌کند؛ بدونِ خانهٔ «کوکی با pot» می‌شد نتیجه گرفت pot مضر است؛ هر دو غلط
  بودند. **پیامدِ عملی:** مسیرِ «retryِ بدونِ pot» (`tasks_download.py`، شاخهٔ yt-dlpِ حلقهٔ fetch)
  روی این استقرار یک اجرای دومِ کاملِ yt-dlp خرج می‌کند که اثباتاً هیچ چیزی نمی‌خرد — و هزینه‌اش
  زمانِ ورکر نیست، یک **برخوردِ اضافه با یوتیوب** است که ریسکِ bot-check و مرگِ سشن را بالا می‌برد.
  دامنهٔ شاهد: یک ویدیو روی یک IP. برای «pot هرگز به‌درد نمی‌خورد» کافی نیست؛ برای «امروز روی این
  ماشین چیزی نمی‌خرد» کافی است، و تصمیم هم دربارهٔ همین است.
- **دانلودِ ناشناسِ یوتیوب حدود ۳۲٪ جواب می‌دهد — نه صفر، نه بیشتر.** دو اندازه‌گیریِ **مستقل** روی
  تولید (۲۰۲۶-۰۸-۱۶) هم‌گرا شدند: ۳۲ خطِ `anonymous attempt failed (bot_check)` در برابرِ ۴۷ جابِ
  یوتیوبِ آن روز (۴۱ ok + ۶ fail)؛ و یک تستِ مستقیمِ سه‌ویدیویی که **۱ از ۳** را ناشناس گرفت.
  **قیدِ پنجره بخشی از عدد است:** لاگ فقط از ۰۸:۱۸ همان روز است (ری‌استارتِ ورکر)، نه ۷ روز — پس
  این نرخِ **یک روزِ ناقص** است، نه نرخِ پایدار. معنیِ عملی‌اش برای طراحی این است که `_ANON_FIRST`
  برای یوتیوب **می‌ارزد** (یک‌سومِ دانلودها هیچ اکانتی لمس نمی‌کنند) ولی برخلافِ اینستاگرام
  (~۸۷٪) هرگز جای کوکی را نمی‌گیرد. هدفِ کارِ یوتیوب کاهشِ مصرفِ بی‌مورد است، نه حذفِ کوکی.
- **فرمِ خطای تازهٔ یوتیوب: «The page needs to be reloaded.» — ثبت شد، رفع نشد (۲۰۲۶-۰۸-۱۸).**
  متنِ کامل: `ERROR: [youtube] <id>: The page needs to be reloaded.` و
  `classify_error` آن را **`unrelated`** می‌خواند. در پنجرهٔ لاگِ **یک‌ساعتهٔ**
  اپراتور هر ۴ شکستِ یوتیوب همین بودند و **صفر** bot-check — یعنی برای آن ساعت
  جای فرمِ غالبِ قبلی را گرفته بود. سه چیزی که اندازه‌گیری شد و دامنه را تعیین
  می‌کند: **به نسخهٔ yt-dlp ربط ندارد** (۲۰۲۶.۰۷.۰۴ آخرین نسخهٔ منتشرشده است و
  upgrade همان را می‌دهد)، **به pot ربط ندارد**، و **گذراست** — همان ویدیو در
  یک بازه bot-check می‌داد و در بازهٔ دیگر این، و دو ویدیویی که در لاگ شکست
  خورده بودند بعداً **با همان کوکی** OK دادند.
  **چرا این‌جا و نه در فهرستِ کارها:** این خطا در فازِ **probe** هم می‌افتد، پس
  دقیقاً همان کلاسی است که سطلِ `fail`ِ شمارندهٔ تازه می‌شمارد — و چون
  `unrelated` است، امروز نه اکانتی می‌سوزاند نه چرخشی راه می‌اندازد.
  **سهمِ واقعی‌اش نامعلوم است:** نرخِ روزانهٔ یوتیوب همان روز به ۲۱٪ شکست رسید
  ولی پنجرهٔ لاگ فقط یک ساعت بود، پس «۴ از ۴» صورتِ کسر است بدونِ مخرج. فردا با
  مخرجِ کامل سنجیده می‌شود؛ **پیش از آن هیچ فهرستی (`_YT_BOTCHECK_HINTS`،
  `_CLASS_HINTS`، `_CONTENT_HINTS`) دست نخورد** — همان قاعدهٔ «اول عدد، بعد
  تصمیم» که برای خودِ فازِ probe هم اعمال شد.
- **فرم‌های خطایی که فهرست‌های واگرا نگرانشان بودند، در ترافیکِ واقعی وجود ندارند.** سرشماریِ کلِ
  پنجرهٔ لاگ (۲۰۲۶-۰۸-۱۶): **صفر** «members-only»، **صفر** «Music Premium»، **صفر** «not available
  on this app». تنها فرمِ خطای یوتیوب همان bot-checkِ استاندارد است، **۲۹ بار**. یک ریزه‌کاریِ
  شمارش که باید گفته شود وگرنه عدد سه‌برابر خوانده می‌شود: سه گرپِ `not a bot` /
  `cookies-from-browser` / `Sign in to confirm` **یک پیامِ واحد** را می‌شمارند، نه سه رخداد.
  **و یک قیدِ دامنه که بدونش این سرشماری اشتباه خوانده می‌شود: این آمارِ فازِ fetch است، نه
  فازِ probe.** تنها دو خطِ لاگ متنِ خطای موتور را حمل می‌کنند و **هر دو در حلقهٔ fetch**اند —
  `anonymous attempt failed (%s); retrying with a cookie` (که فقط `cls` را چاپ می‌کند) و
  `attempt %d failed (%s); rotating: %s` (که `str(exc)[:90]` را چاپ می‌کند). شاخهٔ probe فقط
  `probe: cookie %s failed, trying next` می‌زد — **نامِ اکانت، بدونِ پیام** — و شاخهٔ شکستِ
  نهایی‌اش اصلاً لاگ نمی‌کرد. پس **شکستِ probe در لاگ نامرئی بود و توزیعِ خطایش اندازه‌گیری
  نشده**؛ هر استدلالی که توزیعِ fetch را به probe تعمیم بدهد بی‌پشتوانه است. **۲۰۲۶-۰۸-۱۶
  خطِ `probe attempt %d failed (%s): %s` اضافه شد** (هم‌ریختِ خطِ fetch، تا یک گرپ هر دو فاز
  را بدهد)، پس از این به بعد قابلِ اندازه‌گیری است — ولی هر عددی که پیش از این تاریخ گرفته
  شده همچنان فقط دربارهٔ fetch است. این فرق عملی هم
  دارد: probe **همیشه با کوکی** می‌رود و طبقِ جدولِ چهارحالتهٔ بالا کوکی جواب می‌دهد، پس
  محتمل است probe عمدتاً **موفق** باشد — یعنی هزینهٔ قطعیِ فازِ probe «مصرفِ اکانت» است،
  و «سوزاندنِ اکانت» یک احتمالِ نسنجیده. برای سنجشش یک خطِ لاگ لازم است که امروز نیست.
  **نتیجه:** واگراییِ `downloader._YT_BOTCHECK_HINTS` با `cookies._CLASS_HINTS[BOT_CHECK]` — که
  باعث می‌شود گیتِ ارتقای anon→کوکی (`tasks_download.py`، شاخهٔ `if anon:` در حلقهٔ fetch، شرطِ
  `cls != ck.UNRELATED`) بعضی خطاها را رد کند — **واقعی ولی امروز بی‌هزینه** است: درستیِ نهفته،
  بدونِ فوریت. اگر روزی یکی از آن سه فرم در لاگ دیده شد، آن‌وقت فوری می‌شود.
- **پیکربندیِ یوتیوب در تولید: تنها کلیدِ غیرپیش‌فرض `dl_ux_youtube = probe` است.** `COBALT_URL`
  خالی است (پس شاخهٔ fallbackِ کوبالت **هرگز اجرا نمی‌شود** و نباید در هیچ تحلیلی حساب شود)،
  `PROXY_URL` خالی است (خروجیِ مستقیم از IPِ دیتاسنتر — همان چیزی که یوتیوب چالش می‌کند)، و هیچ
  نودی وصل نیست. **و همین یک کلید است که فازِ probe را روشن می‌کند**، که بارِ اصلیِ مصرفِ بی‌موردِ
  کوکیِ یوتیوب از آن می‌آید: شاخهٔ probe در `run_download` **بی‌قیدوشرط** کوکی برمی‌دارد — متغیرِ
  `anon` ده‌ها خط پایین‌تر و فقط برای فازِ fetch محاسبه می‌شود، پس قاعدهٔ anon-first برای خودِ
  دانلود سالم است ولی probe یک **درِ دومِ بی‌گارد** جلوی آن است. اندازه‌گیری‌شده در سندباکس با
  `run_download`ِ واقعی و `D.probe`ِ استاب‌شده: یک دانلودِ **کاملاً موفقِ** یوتیوب یک درخواستِ
  احرازشده در probe می‌زند و بعد fetch را ناشناس انجام می‌دهد؛ و پنج لینکِ پشتِ‌هم سه سشنِ متفاوت
  را لمس کردند در حالی که `ckuse:*` (سطلِ ساعتی) خالی ماند، `dl:active:z` صفر بود و هیچ‌کدام از
  `dlq:cnt`/`dlq:cd`/`dlq:mb` ست نشد — یعنی probe از **همهٔ** سقف‌ها و از حسابداریِ سهمیه بیرون
  است، چون `note_spend` فقط در مسیرِ fetch صدا زده می‌شود و `dl_active.enter` بعد از `return`ِ
  probe است. سنجهٔ در دسترس برای حجمِ probe: کلیدهای `probe:{ref}` (TTL ۱۸۰۰) در برابرِ
  `dlctx:{ref}` که برای **هر** لینک ست می‌شود — نسبتشان سهمِ probe در ۳۰ دقیقهٔ اخیر است. شمارندهٔ
  اختصاصی ندارد.
  **و حلقهٔ probe سقفِ تلاش نداشت — ۲۰۲۶-۰۸-۱۶ رفع شد؛ توصیفِ زیر وضعِ پیش از رفع است.**
  `dl_max_cookie_tries` فقط در حلقهٔ fetch چک می‌شد
  (`if max_tries and attempts >= max_tries`)، پس یک شکستِ کوکی‌محور در probe **کلِ استخر** را
  می‌پیمود و هیچ کلیدِ پنلی محدودش نمی‌کرد. با `ck_invalid_at=3` و کول‌داونِ پلکانی،
  اندازه‌گیری‌شده روی استخرِ سه‌تایی: سه استورمِ فاصله‌دار (t≈۰ / +۳۰د / +۹۰د) هر سه اکانت را به
  `fail_streak=3` یعنی «باطل» می‌رساند. این نتیجه **مشروط** است نه مشاهده‌شده — نرخِ شکستِ
  probe در تولید (بولتِ بالا) اندازه‌گیری نشده.
  **ساده‌ترین اهرم یک کلیدِ پنل است، نه کد:** `dl_ux_youtube = quick` کلِ این کلاس را حذف
  می‌کند — اندازه‌گیری‌شده روی `_resolve_ux` و تصمیمِ `quick` در `routers/download.py`:
  فاز به `fetch` می‌رود (پس anon-first اعمال می‌شود و مصرفِ کوکیِ probe **صفر** می‌شود)،
  کشِ آنی سرِ intake **چک می‌شود** (امروز با probe اصلاً چک نمی‌شود)، و `_charge` هم اعمال
  می‌شود (پس سقفِ روزانه و کول‌داونِ کاربر برمی‌گردند). بهایش تصمیمِ محصولی است: منوی کیفیت
  از بین می‌رود و کاربر «بهترین» می‌گیرد. **تصمیمِ اپراتور (۲۰۲۶-۰۸-۱۶): فعلاً نه —
  معلق تا چند روز دادهٔ لاگ.** آن هزینهٔ محصولی واقعی است و عددی که تصمیم را می‌سازد
  (توزیعِ خطای probe) هنوز وجود ندارد؛ خطِ لاگِ تازهٔ فازِ probe همان را می‌سازد.
- **واحدِ آسیب در فازِ probe «اکانت» نیست، «استخر» است — و همین جدولِ per-accountی را که
  اول کشیدم بی‌معنا می‌کند.** حلقهٔ probe سقفِ تلاش ندارد (بولتِ بالا)، پس یک خطای واحد
  تا **تهِ استخر** می‌رود و چون `mark_fail` بی‌کلاس صدا زده می‌شود، هر اکانتی که لمس شد
  ضربه و کول‌داون می‌گیرد. اندازه‌گیری‌شده روی استخرِ **۵تایی** با `run_download`ِ واقعی،
  یک استورمِ probe، «قابلِ‌استفاده از کل» پس از آن:

  | کلاسِ خطا | امروز | با پاس‌دادنِ `error_class` |
  |---|---|---|
  | `bot_check` | ۰ از ۵ | ۰ از ۵ — بی‌تفاوت |
  | **`transient`** | **۰ از ۵** | **۵ از ۵** |
  | `rate_limit` (متنِ ۴۲۹) | ۵ از ۵ | ۵ از ۵ — چون اصلاً به `mark_fail` نمی‌رسد |

  یعنی **یک `JSONDecodeError` کلِ استخر را با هم می‌خواباند** در حالی که `transient`
  دقیقاً کلاسی است که §۷ از قبل می‌گوید نباید اکانت را بسوزاند. و برعکسِ آنچه از جدولِ
  تک‌اکانتی برمی‌آمد، این نتیجه به توزیعِ **نسنجیدهٔ** خطای probe وابسته نیست: اگر
  bot-check باشد پاس‌دادنِ کلاس بی‌اثر است و اگر نباشد کلِ استخر را نجات می‌دهد — پس
  اکیداً بدتر نمی‌شود.
  **کرانِ بالای دفعات (اپراتور، ۲۰۲۶-۰۸-۱۶): `dlstat:youtube:fail` در دو روز ۷ و ۶
  بوده، پس شکستِ probe حداکثر ۷ در روز است.** و کران از این هم شل‌تر است: آن شمارنده
  **شش** محل دارد نه دو تا — `:781` (probe) و `:1100` (fetch) به‌علاوهٔ ردهای سیاستیِ
  `AgeRestricted`، «حجم زیاد» و «محتوای غیرمجاز». پس سهمِ probe از آن ۷ تا کمتر است.
  نتیجهٔ عملی که تصمیم را ساخت: سناریوی بنچِ کلِ استخر **ممکن ولی محدود** است —
  بیمهٔ ارزان (پاس‌دادنِ کلاس + سقفِ تلاش) توجیه دارد، بازآراییِ بزرگ نه.
- **`_is_cookie_error` و `classify_error` سومین فهرستِ واگرا را می‌سازند، و این یکی
  دربارهٔ «به استخر می‌رسد یا نه» است نه «چه کلاسی می‌گیرد».** `_BAN_HINTS` عبارتِ
  `rate limit`/`rate-limit` را دارد ولی `429` و `too many requests` را **ندارد**،
  در حالی که `_CLASS_HINTS[RATE_LIMIT]` هر دو را دارد. اندازه‌گیری‌شده:

  | خطای موتور | به `mark_fail` می‌رسد؟ | `classify_error` |
  |---|---|---|
  | `HTTP Error 429: Too Many Requests. Please wait a few minutes` | **نه** | `rate_limit` |
  | `rate limit exceeded, try again later` | بله | `rate_limit` |
  | `JSONDecodeError …` | بله | `transient` |
  | `connection reset` / `read timed out` | **نه** | `transient` |

  **و «نرسیدن» برای خودِ اکانت نتیجهٔ درستی می‌دهد** — محدودیتِ نرخ نباید اکانت را
  بسوزاند، و نرسیدن به `mark_fail` هم دقیقاً همان است. آنچه ممکن است غلط باشد
  **نچرخیدن به اکانتِ بعدی** است: با یک ۴۲۹ حلقه می‌شکند و کاربر خطا می‌گیرد در حالی
  که اکانتِ دیگری شاید جواب می‌داد. آن **تغییرِ جداست** (دست‌زدن به گاردِ `_is_cookie_error`
  در حلقهٔ probe) و عمداً با این کار قاطی نشد. ثبت شد، ساخته نشد.
- **بردنِ فازِ probe به `_resolve_blame` بررسی و رد شد — برچسبِ کلاس را خراب می‌کند.**
  ایده جذاب بود (همان تقصیرِ IP-محورِ مسیرِ fetch برای probe هم بیاید) و اندازه‌گیری هم
  نشان داد کار می‌کند: استورمِ سه‌اکانتی به‌جای «هر سه ضربه + کول‌داون» می‌شود «هیچ ضربه،
  خروجی کول‌داون». ولی شاخهٔ exit-blame در `_resolve_blame` عمداً
  `error_class=ck.TRANSIENT` می‌دهد و `cookies.py` همان را در `last_error` می‌نویسد،
  پس در موردِ **غالب** پنل `transient` نشان می‌دهد نه `bot_check` — یعنی سودِ تشخیصی‌اش
  تا حدی **معکوس** است. سه ایرادِ دیگر که ردیه پیدا کرد: مرزِ `>=2` اکانت (جایی که کلِ
  معنایش عوض می‌شود) هیچ‌وقت تست نشده؛ روی مسیرِ **برد** چیزی را نرم نمی‌کند (شکستِ قبلی
  همچنان ضربه می‌گیرد)؛ و `_alert_if_low` قبل از blame اجرا می‌شود و جابه‌جا کردنش هم
  برای `n>=2` جواب نمی‌دهد چون `UNPROVEN` عضوِ `USABLE` است. با کرانِ «حداکثر ۷ شکستِ
  probe در روز»، این شعاعِ انفجار توجیه ندارد. **ساخته نشد؛ اگر خطِ لاگِ تازه نشان داد
  شکستِ probe واقعاً IP-محور و پرتکرار است، دوباره باز شود.**
- **Spotify/Apple are DRM**: never downloaded directly — metadata is resolved then matched to a YouTube recording. Accurate matching needs `ytmusicapi` **installed in the download-worker image** and a proxy that can reach `music.youtube.com`; otherwise it falls back to raw `ytsearch` (less accurate). `SPOTIFY_SOURCE=youtube` forces the fallback.
- **The Spotify Web API is closed to us — design for the embed page, and stop looking for a key.**
  `spotify_resolve()` has two paths: the official API when `spotify_client_id`+`spotify_client_secret`
  are set, else scraping the public `/embed` page. **The API path is not available to this project and
  will not be**, decided 2026-08-12 by the operator against Spotify's February 2026 platform changes:
  using the Web API now requires the app owner to hold a **Spotify Premium** account, Development mode
  is capped at one Client ID and five users, Spotify is moving away from Client Credentials for
  metadata at all, and extended quota is granted only to organisations with ~250k monthly users. None
  of those are things a self-hosted bot can satisfy. So the API path stays in the code (it costs
  nothing and works for anyone who *can* satisfy them) but **no design may depend on it**.
  The consequence is concrete and shapes the matcher: the embed page yields **title, artist, duration,
  cover and year** — but **no album and no ISRC**. Therefore **ISRC is permanently unavailable in
  production**, which makes two pieces of `_gather_candidates`/`_match_score` dead in practice: the
  ISRC catalogue search and the `isrc_hit` **+20** bonus — the strongest signal the scorer has. Both
  are kept and commented; they cost nothing and work for anyone who *can* satisfy Spotify's terms.
  What is left to match on is **name (0.40), artist (0.25), duration (0.27)**; the album component
  (0.08) is always `None`, so those three re-normalise over 0.92, and `year` is metadata for tagging
  rather than a matching signal. The only remaining "this is the official recording" signal is
  `art_track` **+6** for YouTube Music `songs` results. Anyone tuning the matcher should start from
  that three-signal reality, not from the weights as written.
  **The verified embed schema** (captured from the master 2026-08-12; fixture at
  `tests/fixtures/spotify_embed_track.json`) — all under `props.pageProps.state.data.entity`:
  `title` (or `name`) · `artists[].name` (an **array of objects**, not a string) · `duration` in
  **milliseconds** · `releaseDate.isoString` · `visualIdentity.image[].url`. There is **no `album`**
  and **no `coverArt`**. Two details here have already cost us and will again: the **millisecond
  unit** (310973 read as seconds is 3.6 days, which makes `_duration_reject` throw out every
  candidate — a silent total failure, so a test pins the unit), and the fact that `artists` is a list.
  **A playlist dump (2026-08-12, 100 items) confirmed the `trackList` branch was never broken** — only
  the single-track link was — and it produced the two corrections that matter most here.
  **First, `subtitle` is not legacy, and it means three different things depending on where it sits:**

  | where | `subtitle` means | artist actually comes from |
  |---|---|---|
  | single-track entity | *(absent today)* | `artists[].name` — an **array** |
  | track inside `trackList` | **the artist** | `subtitle` — a plain **string** |
  | playlist/album entity itself | **the playlist owner** (e.g. `"Spotify"`) | — never an artist |

  Anyone removing `subtitle` as dead code breaks every playlist link, so the code, both fixtures and
  `test_both_live_artist_shapes_are_supported` say so explicitly. **Second, the owner/artist collision
  was a live silent bug**, found by running rather than reasoning: the single-track branch was taken on
  `not tl` rather than on `kind`, so a playlist whose `trackList` was empty or unreadable produced one
  fabricated track named after the playlist with `"Spotify"` as its artist — measured as
  `('Persian Essentials', 'Spotify', None)`. `reference_is_blind()` did **not** catch it, because
  `"Spotify"` is a non-empty artist, so the bot would have searched YouTube for
  "Spotify Persian Essentials" and delivered whatever came back. A collection whose track list cannot
  be read is now a **parse failure** (→ oEmbed → the loud warning), not one track. Playlist items
  additionally carry `duration` in milliseconds (so the rounding fix covers both paths), no cover of
  their own (only the collection-level one), and a `playabilityReason` that can be
  `COUNTRY_RESTRICTED` — irrelevant to us, since the audio comes from YouTube.
- **A fallback that silently degrades to useless data is worse than an error — this one hid a total
  parser failure for weeks.** `_spotify_scrape` tries `_parse_spotify_embed`, and on failure falls
  back to Spotify's oEmbed endpoint, which returns **title and cover art only**. Spotify changed the
  embed schema; `_find_spotify_entity` required `trackList` **or** `title`+`coverArt`, and the new
  schema has no `coverArt` at all, so it returned `None` for every track, `_parse_spotify_embed`
  returned `None` every time, and the oEmbed path quietly took over. Nothing errored. Downloads kept
  "working". The reference the matcher scored against was `{title, artist:"", duration:None}` — which
  disables **both** hard gates at once (`_artist_match` returns `None` when the reference has no
  artists and the gate reads `am is not None`; `_duration_reject` needs both durations), so every
  same-titled candidate tied on name alone and the winner was simply whichever came back first.
  Observed: eleven candidates at exactly 106.0 for «Jane Maryam», the correct Mohammad Nouri
  recording ninth in that list, and a random cover delivered. Three defences now: the fallback logs
  at **`log.warning`, not `log.info`** and says the schema has probably changed; `reference_is_blind()`
  flags a reference with neither artist nor duration (its user-facing consumer is the still-unbuilt
  threshold/warning work); and `_find_spotify_entity` **scores** candidates by completeness rather
  than hinging on one key, taking the most complete instead of the first match. Generalise it: any
  `try primary / except: use fallback` where the fallback yields *less* data needs a loud signal on
  the transition, because "it still returns something" is exactly what stops anyone from looking.
  A second, independent fragility surfaced while fixing this: the extraction regex was
  `>(\{.*?\})</script>`, which requires `}` **immediately** before the closing tag — a single newline
  or indent silently broke the whole parse. It is now `>(.*?)</script>` plus `.strip()`.
- **Do NOT clear the Spotify cache before a matcher smoke test any more — that instruction is now
  actively harmful.** It was the right advice while the key carried no version: the old row would have
  been served and the smoke test would have measured nothing. Since `_MATCH_VERSION` entered the key a
  matcher or parser change retires those rows by itself, so deleting them destroys the very evidence the
  smoke test exists to produce — whether the *new* logic coalesces the forms and starts serving hits.
  **The procedure that replaces it:** send the same track **twice, in two different URL forms** (a
  localised `intl-…` link and a plain one are the realistic pair, since Spotify hands non-English users
  the localised path), then count rows for the platform and read `hits`. One row with `hits` climbing
  means the version and the `sp:<kind>:<id>` normalisation are both doing their job; two rows means a
  form is still escaping normalisation.
  **First real run (2026-08-13, on the master):** one `DELETE` removed exactly **1** orphaned row — the
  entire pre-version legacy population, which also retires the "34 rows by hand" era for good — and then
  three real forms (localised `intl-fa`, plain, and a raw Copy-link carrying four params) all landed on
  **one** row, key `f66192b3`, `hits = 2`.
  **What that run does and does not prove — and being explicit about the gap is part of the procedure.**
  It confirms the **normaliser** directly: three genuinely different URL forms of one track produced one
  row and a climbing `hits`, which is exactly the thing no unit test can show about *real* links.
  It does **not** confirm the other two halves, and an earlier version of this note wrongly claimed it
  confirmed all three at once. The `DELETE` emptied the table first, so **no stale legacy row was in
  play**: the fallback skip had nothing to skip, and the version invalidated nothing, because the rows it
  would have retired had already been deleted by hand. For those two the run shows only that they did not
  break the happy path.
  **So the fallback skip and the version's invalidation ride on unit tests, not on this smoke.** Named
  rather than numbered, since line numbers rot: `test_a_stale_legacy_spotify_row_is_not_resurrected`
  seeds a stale legacy row and asserts it is neither served nor migrated;
  `test_a_row_from_an_older_version_is_ignored` and
  `test_bumping_the_version_moves_only_the_spotify_key` cover the invalidation and its scope; and
  `test_a_legacy_youtube_row_is_still_migrated` is the control that ordinary migration survives. All in
  `tests/test_cache_key_version.py`, on a real in-memory database.
  A future run *could* cover the fallback skip end to end — seed a row under the pre-version raw-URL key
  and request the track without deleting anything first — but that has not been done, and until it is,
  this bullet should not be read as claiming it.
  The one-time `DELETE FROM download_cache WHERE platform = 'spotify'` belongs to that deploy only,
  because the table has no eviction; it is not part of the smoke procedure and should not be repeated.
- **In a report or a review, cite the line number; in committed documentation, cite the symbol.** A line
  number is precisely what a reader needs while looking at a diff, and precisely what rots the moment
  anything upstream of it is edited. Learned the same day, from this file: adding an explanatory comment
  above `_MATCH_PLATFORMS` pushed it from line 46 to 53 and thereby invalidated **three** references
  written minutes earlier — the import comment in `dl_cache`, a §7 gotcha, and a changelog entry — none
  of which had anything to do with the edit. The `_DROP_PARAMS` entry for `si` moved the same way, so
  the same fact was correct as ":46" and as ":51" depending on which revision you opened. So write
  «`_MATCH_PLATFORMS` in `downloader.py`», not «`downloader.py:46`». Where a line reference is genuinely
  the point — pinning one statement inside a long function — name the enclosing symbol too, so the
  reference degrades into something still findable rather than into a wrong number.
- **A cache key must carry a version for whatever part of the answer *we* decide — and the legacy
  fallback is the half that gets forgotten.** `download_cache` stores a Telegram `file_id`, so a stale
  row costs no bandwidth and instead serves the **wrong file**; that makes it a correctness problem, and
  it is why the version is scoped rather than global. For a YouTube link the cached id is exactly what
  the URL names, with no decision of ours in it, so versioning those rows would discard healthy entries
  for a problem they never had. `downloader._MATCH_PLATFORMS` (`downloader.py:53`) is the single source
  of "we pick the target" — `engine_for`, the cache version and the fallback skip all read it, so a new
  match platform (Apple Music) must be added there or it inherits none of them. **Bumping the version
  alone is not enough:** `get_cached` falls back to `_legacy_key` and *migrates* the row forward, and
  for a Spotify URL those two keys already differ, so the stale row came back under the fresh key —
  the bump achieved nothing and renewed exactly what it meant to retire. And **a hand-bumped constant
  rots**, which is why it is pinned by a behavioural fingerprint over both the matcher and the parser:
  the URL does not change when the parser changes, so a matcher-only fingerprint would sit still
  through precisely the kind of failure that once went unnoticed for weeks. The table has no eviction
  (`created_at` exists, nothing implements a TTL), so any change of this shape needs a one-time
  `DELETE` for the platform whose rows it retires.
- **Score the candidate's claims, not the reference's coverage — and gate on substitution, not on how
  much matches.** Two rules share one insight. `_artist_match` averages, for each **candidate** artist,
  its best similarity to any reference artist; the old form took the best match for each *reference*
  artist and weighted the first 0.6, which for Iranian classical music weights the **composer** (Spotify
  lists him first) rather than the singer — so when YouTube listed only the singer, the *right* recording
  scored 50.0 and a *wrong* one by the same composer scored 68.0. And `_artist_contradiction` rejects on
  **missing *and* extra** rather than on a similarity floor, because a **subset** listing (YouTube naming
  only the lead) is not evidence against a candidate: every coverage-flavoured alternative rejected the
  correct «Get Lucky» Art Track. Three consequences worth keeping: a guest artist YouTube adds costs
  100 → 72.7, which is accepted; the numeric floor stays as a cheap second layer but **cannot** replace
  the contradiction rule, since the singer-substitution candidate scores 53.5, above the floor; and
  `Ebi` ↔ `Ebrahim Hamedi` (35.3) is a **stage name against a legal name**, a class fuzzy similarity
  cannot solve and which the 45 threshold is not expected to absorb.
- **Lifting the name gate for a different script only works when the artist can still be compared — and
  the score must stay honest.** For a *fully* non-Latin candidate, name **and** artist both collapse to
  0.0 (35.3 total against 106.0), so exempting the gate admits noise and wins nothing. The case that
  matters is **mixed**: a Persian title with a romanized artist, where the artist is healthy (88.9) and
  only the name gate kills it — that reaches 61.6 and clears the 55 threshold. So `_name_gate_exempt`
  requires the titles to differ in script *and* the artist score to clear 45. **Do not substitute a
  neutral value for the unusable name score**: it lifts target and decoy equally, buying no
  discrimination while weakening the threshold — measured, a same-composer decoy 20 s off stays at 36.2
  with the real value and reaches 55.9 with a neutral 50. And when the exemption fires, say so:
  `match_confidence_note()` is logged for the winner, because judging on fewer signals must not be
  silent. `_dominant_script` counts Latin against non-Latin letters instead of hardcoding one language's
  ranges, and ignores digits so `"311"` vs `"٣١١"` is not a script difference.
- **One normaliser cannot both strip noise and preserve markers — that is why there are two.** `_norm`
  is for fuzzy comparison and *must* strip brackets (otherwise «Faryad (Official Video)» stops matching
  «Faryad»); `_penalty_text` keeps them and exists only for the `_BAD_KW` search. Four rules hold this
  together, all established by measurement. **The marker search is word-bounded**, because unmasking
  bracketed text without boundaries activates a dormant bug — `(feat. Oliver)` → `live`,
  `(album Recovery)` → `cover`. **The inflected forms are an explicit list** (`_BAD_KW_EXTRA`), never a
  generic suffix rule: `(?:s|es|ed|ing)?` scored **10 false positives over 20 real titles, the same as
  the substring matching it was meant to improve on**, because `lives`/`covered`/`covering`/`reactions`
  are ordinary words (zipf 4.2–5.1). `_BAD_BASE` maps every form back to a base keyword so the score
  keeps its "one −12 per keyword" meaning. **Both sides of the comparison use the same normaliser** — the
  `kw in ct and kw not in tt` test was symmetric under `_norm`, so converting only the candidate side
  *introduces* a bug where a live reference wrongly penalises a live candidate. And **`_FEAT_RE` is not
  applied** in the penalty text, because it ends in `.*$` and swallows everything after a feat credit,
  markers included; the accepted cost is that a band literally named «Live Band» in a feat credit now
  takes −12, which is a 12-point penalty rather than a rejection.
  Note the boundary change also **removes** an existing defect rather than adding one: substring matching
  penalises «Nine Lives» today. `session` was already in `_BAD_KW`, so «Sessions of Love» matching is
  consistent with «Session of Love» matching today, not a new ambiguity.
- **The YouTube search query is `_search_queries()` and nowhere else — it used to be written twice, and
  the second copy fed the last resort.** The shapes are **first artist + title** and **last artist +
  title** (deduped, so a single-artist track is *one* query and costs exactly what it did before; only a
  multi-artist track costs two). Three things about this are easy to break. **First, the gate that adds
  the `videos` and `ytsearch` fallbacks reads the *merged* pool, not each shape** — put it per shape and
  every new shape drags its own fallbacks along, so the call count multiplies instead of adding; the
  fallbacks also stop the moment the pool reaches 3, so the worst case stays bounded. **Second, the
  searches are sequential on purpose**, and not for politeness: `_ytmusic_search` swallows its errors and
  returns `[]` (`downloader.py:1617-1620`), so a 429 against an unauthenticated endpoint with no
  documented quota is a **silent** failure, and doubling the instantaneous rate buys nothing because
  per-track latency is dominated by the yt-dlp download anyway. **Third — the trap that actually bit —
  `download_spotify` built the very same query a second time and independently**, and that copy is what
  `ytsearch1:` falls back to when no candidate survives. Changing the strategy in `_gather_candidates`
  alone therefore left the last resort searching the one shape measured *not* to return the target. Both
  now read `_search_queries()`; a test asserts the last-resort target, because this is the same
  "two hand-written copies of one rule will diverge" shape as `remove_cookie_file`.
  Merging candidates across shapes dedupes on `_cand_url` and **keeps the first** hit, which is
  load-bearing rather than arbitrary: `songs` runs before `videos`, so first-wins preserves
  `art_track=True` and its +6 bonus, and an ISRC hit keeps its flag.
- **A diagnostic that can mislead is worse than no diagnostic — the query probe reported the rank of a
  video it had never matched.** `hits()` returned matches in **pool order** while both callers take
  `[0]` as the target, so a duration-only false positive sitting earlier in the list shadowed a real
  name-and-duration match: the tool printed a confident rank for the wrong recording, and the merged
  path then measured *that* video's rank after ranking. This is the origin of the "rank 3" in the
  earlier write-up, which was a false positive. It now returns two **tiers** (name+duration, then
  duration-only) keeping pool order inside each tier; the duration-only criterion is deliberately kept,
  because it is what finds the target when the correct recording is listed under a **Persian** artist
  name. Two supporting rules came out of the same repair. The one-line summary must not render a weak
  hit as a plain tick — that phrasing is what made the false positive readable as success. And the
  winner must be printed with **id, full title, every artist and duration, untruncated**: the old line
  printed neither id nor duration and cut the artist list at 24 characters, which is precisely why
  "the 103.2 winner" could not be identified from the output and stayed an open question for a session.
  **A dry run then found a limit that no amount of reading would have:** the probe identifies its target
  by artist **and** duration, and a *remix by the same artist at the same length* satisfies both, so the
  tool cheerfully announced the correct recording had been found. The verdict now claims only what it
  compared, and titles carrying a version marker are flagged — on the **raw** title and with **word
  boundaries**, because the production `_BAD_KW` check is substring-matched and collides there
  (`Delivery`→`live`, `Recovery`→`cover`, `Sessions`→`session`, all measured). That collision is also a
  constraint on fixing the paren bug: unmasking the bracketed text without adding boundaries converts a
  dormant bug into an active one (`Faryad (feat. Oliver)` → −12).
- **Two things a matcher's name-splitting must never do, both learned from one regex.**
  `_ARTIST_SPLIT_RE` (`downloader.py`) splits the Spotify artist string into individual names, and it
  listed `feat\.?|ft\.?|featuring` **without word boundaries** while its three neighbours
  (`\bx\b`, `\bvs\b`, `\band\b`) had them — the inconsistency is exactly why it read as fine.
  (1) **Unbounded `ft` cuts inside ordinary names.** Measured: 14 of 40 real artist names were
  shredded, every one by that branch — `Daft Punk` → `['Da','Punk']`, and likewise Taylor Swift,
  Kraftwerk, Deftones, Soft Cell, Craft Spells, Shaft, Aftermath, Left Boy, Lifted, Gifted,
  Fifty Fifty, Aftertaste, Swift. Two consequences, and the *smaller-looking* one is the severe one:
  the artist component (weight 0.25, and **0.27 of the 0.92 that actually applies** on the embed path)
  is simply wrong — but worse, `_rank_candidates` **rejects** any candidate with an explicit artist
  list scoring under 40, so on a **multi-artist** track the corrupted primary plus diluting features
  fell to 32.3 and the *correct* Art Track was thrown out before scoring. Single-artist tracks stayed
  above 40 and were "only" mis-scored: measured, the margin between the right recording and a cover
  by someone else fell from ~26 to 15.4, i.e. the artist signal lost ~40% of its discriminating power.
  That distinction matters because the first version of this note claimed the bug flips single-artist
  results, and it does not — the corruption is common-mode when every candidate shares an artist.
  (2) **A leading `\b` alone is not the fix** — `\bfeat` still cuts "Feature Films". Both sides are
  bounded (`\bfeat\b\.?`), with `\.?` after the boundary so `feat.` still splits.
  A third bug fell out of the same line: with the old pattern the `feat` branch **shadowed**
  `featuring`, so `Drake featuring Rihanna` split into `['Drake', 'uring Rihanna']` — that separator
  had never worked. Any alternation of word-prefixes has this shape; bound them or order them.
- **"Unknown" must not score like "perfect" — a dropped component is an implicit full mark.**
  `_match_score` builds a weighted average from whichever components are available and re-normalises
  over their weights, so a candidate with **no duration** returned exactly the score of one with a
  *perfect* duration (both 106.00 measured) and beat a candidate 3 seconds off (99.00). That is the
  general trap with optional signals: omitting a term does not mean "no opinion", it means "this term
  cannot lower the average". `_TIME_UNKNOWN = 50.0` is now substituted instead — the midpoint of
  `_time_match`'s own 0..100 output, which on that curve is **6.9 s** of difference (`-ln(0.5)/0.1`),
  sitting between "same recording, different master" (0–3 s) and "different version" (20 s+).
  It is deliberately **not** a penalty: a penalty asserts that a missing duration is itself
  suspicious, and there is no evidence for that. One case keeps the old drop-the-component behaviour
  on purpose — when the **track's** own duration is unknown, the component is dropped as before. The
  reason is **not** ranking: within one track both choices rank identically, since injecting a
  constant is a monotonic transform when every candidate shares the same weight set. The reason is
  **score comparability across tracks**, which is what makes a global threshold mean anything at all.
  `match_min` is one number applied to every track, so if the scale shifts from track to
  track it stops measuring a fixed thing and cannot be calibrated — and injecting 50 where there is
  no information does exactly that, pulling a duration-less track onto a different scale from the
  rest. That distinction is worth keeping in mind for **any** future optional signal: a substituted
  neutral value is safe when it stands in for missing *candidate* data, and unsafe when it stands in
  for a missing *reference*, because the second kind silently re-scales the track as a whole.
- **A session is an identity, not a file: cookie + exit IP + User-Agent, always together.**
  Instagram treats the IP as identity, so moving one session between exits is the fastest route to a
  checkpoint. Each account carries `node_id` (pinned exit), `proxy` and `user_agent` in its meta;
  `cookies.pick(node_id=…)` **skips** an account pinned to a different exit and **prefers** one pinned
  to the current exit, and `_opts(identity=…)` lets the account's own proxy/UA override the global
  ones (`--user-agent` reaches yt-dlp and gallery-dl).
- **Pace each account, and warm new ones up.** Pushing 2× loses sessions ~4× faster, so every account
  has an hourly token bucket (`cookies.hourly_cap`, Instagram deliberately the tightest) plus a
  minimum-gap floor between two uses of the *same* account, both in Redis. A newly added account
  starts at a fraction of capacity and ramps to full over a few days — a brand-new account that
  suddenly runs at full rate is itself the detectable pattern. `pick()` skips over-budget accounts but
  falls back to `ignore_budget=True` when the whole pool is spent, so pacing never turns into a
  user-visible failure.
- **Every pool number is admin-tunable, and the tuning must not make the math async.** The caps,
  min-gap, warm-up, cooldowns and the fail-streak-to-invalid threshold live in `settings_store`
  (panel group «🧬 سهمیهٔ استخرِ سشن»), not in constants. `cookies.Limits` is a **snapshot** of them:
  `load_limits()` is the only async part and is called **once per operation** (`pick`, `accounts`,
  `mark_fail`, the cookies page), then passed down — so `hourly_cap`/`warmup_factor`/`budget_of` stay
  **sync** and testable without Redis, and a `pick()` over N accounts still does one settings read, not
  N. Every helper defaults to `default_limits()` (env values) when no `lim` is passed, so any older
  call site and any process without an initialized store still works. A cap of **`0` means uncapped**
  (`budget_of` → `0`, the pacer is off) — not "zero downloads"; the panel row renders «بی‌سقف».
  **The same rule now covers the per-account reads, and it was the settings read that was cheap all
  along.** `load_limits()` was already once-per-operation, but everything *else* `pick()` needed was
  still per account: a `GET` for the meta, an `EXISTS` for the cooldown, and — inside `_over_budget` —
  a `GET` for the hourly counter and a `GET` for the last-use stamp. That is **4N+2** commands, and on
  a download node every one of them is a WireGuard round trip inside the cookie-rotation loop, so it
  multiplied. `get_metas`/`cooldowns`/`_mget` batch them (one `MGET`, one `TTL` pipeline, two `MGET`s
  for the budget inputs) and `over_budget` is the **sync** twin of `_over_budget`, taking the already-read
  values — exactly the shape `Limits` established. Four details that are load-bearing: **`TTL` replaces
  both `EXISTS` and `TTL`** because it returns `-2` for a missing key, so the panel's remaining-seconds
  display comes free; candidates are **filtered before** the budget reads, so an excluded/frozen account
  costs nothing; the budget reads are skipped entirely under `ignore_budget`; and values coming back from
  a batch must go through `_int`, because the single-read helpers (`usage`) wrapped the whole read in a
  `try` while a bare `int()` in the batch path turns one corrupt key into a `pick()` that raises.
- **The bot is the distributor, so the filter runs before the card — and the mechanism is attribution,
  not bandwidth.** Every file the bot handles is **sent again by the bot**, which is what puts the bot's
  own account at risk, so `app/safety.py` gates *before* the card exists, not after. The earlier wording
  here said "re-upload", and that was wrong in a way worth correcting because future decisions rest on it:
  the card for an uploaded file goes out by **`file_id`** (`cards.py:188`), so Telegram copies it
  server-side and no bytes are uploaded. The risk survives the correction but changes shape — a message
  carrying that content was sent *from the bot's account*, and that is what moderation sees. Two
  consequences. The cost of screening is a **download** (the local Bot API server pulling from the DC),
  not an upload, which is why it is I/O-bound (see Open Questions). And the risk is far smaller in a
  private chat, where the card returns the user's own file to the same user, than in a group — a
  distinction neither this file nor the code makes, and which currently rests on Telegram-side privacy
  mode rather than on anything in the repo. Three layers, cheap first: the **domain**
  layer runs at link intake before a single byte is fetched; the **metadata** layer uses yt-dlp's own
  `age_limit` plus title/description/tags (free, still before download); the **pixel** layer (NudeNet
  on onnxruntime, video = several frames sampled across the clip) runs last, in the worker. Uploads
  route through `tasks.run_screen` rather than being scanned in the bot process — model inference is
  CPU work and must not block long-polling. Two rules the whole thing depends on: it **fails open**
  (no model, download error, exception → allowed), because a filter that breaks the bot is worse than
  one that misses; and only **explicit** NudeNet labels count — `BELLY/FEET/ARMPITS/FACE/*_COVERED`
  and `MALE_BREAST_EXPOSED` never block, or every beach and gym photo would be rejected.
- **Keyword matching needs two tiers, and the second one is the whole game.** Substring matching on
  `sex` blocks Sussex, Essex, Middlesex and (in Persian) سوسکس/اسکس; on `anal` it blocks *analysis*;
  on `pussy`, *Pussycat Dolls*; on `cum`, *Cumbria*; on `hardcore`, *hardcoregaming101*. Exact-token
  matching fixes those but then misses `freeporn-tube.example`, because adult domains concatenate.
  So `safety.STRONG_TOKENS` match as substrings (only stems with no innocent host word: `porn`,
  `hentai`, `xnxx`, …) while `WORD_TOKENS` match whole tokens only. A third tier, `HOST_TOKENS`,
  applies **only to hostnames** — `escort`/`adultvideo` are unambiguous inside a domain but not in a
  caption ("Ford Escorts", "adult education"). Every one of these collisions is a regression test;
  add to that list rather than widening a token.
- **چرخش را به کلیدواژه گره نزن؛ تقصیر را به متنِ خطا نسپار.** هر دو باگِ بزرگِ استخر از یک
  عادت آمدند: کد معنیِ شکست را با تطبیقِ **رشتهٔ خطا** تصمیم می‌گرفت. (۱) *چرخش* فقط وقتی
  انجام می‌شد که خطا در فهرستِ «کوکی‌محور» باشد — و آن فهرست هیچ‌وقت کامل نمی‌شود، پس یک
  خطای ناشناخته کلِ درخواست را با **یک** تلاش تمام می‌کرد («بارِ اول ارور، بارِ دوم اوکی»).
  حالا **پیش‌فرض می‌چرخد** و فقط `_CONTENT_HINTS` (۴۰۴/خصوصی/حذف‌شده) متوقفش می‌کند —
  فهرستی که برخلافِ قبلی کوتاه و پایدار است. (۲) *تقصیر* از متن درنمی‌آید، چون IPِ مسدود و
  سشنِ مرده **هر دو** `redirect to login page` می‌دهند؛ پس `_resolve_blame` در **پایانِ**
  درخواست از روی الگو تصمیم می‌گیرد: درخواست موفق شد → اکانت‌های افتاده واقعاً خراب‌اند؛
  درخواست شکست خورد و ≥۲ اکانتِ متفاوت امتحان شد → **مقصر خروجی است**، هیچ ضربه‌ای به هیچ
  اکانتی نمی‌خورد و به‌جایش خروجی کول‌داون می‌گیرد (`cool_exit`) و مسیریابی از آن عبور می‌کند.
  دو نکتهٔ ریز که مهم‌اند: `note_use` فقط مهرِ زمان می‌زند و سطلِ ساعتی با `note_spend` **بعد از**
  معلوم‌شدنِ نتیجه پر می‌شود (وگرنه یک خروجیِ مسدود سهمیهٔ کلِ استخر را می‌خورد)، و در `pick`
  هم‌رتبه‌ها چرخشی انتخاب می‌شوند وگرنه روی استخرِ تازه (`last_ok=0`) مرتب‌سازی به **نام**
  می‌افتد و همیشه یک اکانتِ ثابت قربانیِ اولین تلاش می‌شود.
- **بی‌کوکی‌رفتنِ یک پلتفرمِ کوکی‌لازم، خرابیِ سیستم است نه «ادمین کوکی نگذاشته».** اگر
  `_next_cookie` چیزی برنگرداند، `cookie_name` تهی می‌شود و آن‌وقت **هیچ شکستی روی هیچ
  اکانتی ثبت نمی‌شود** (شرطِ `if cookie_name and …`) — پس اینستاگرام پیاپی می‌افتد و پنل
  «سالم · خطا: ۰» می‌ماند. علتِ سمتِ نود هم ظریف بود: `list_names`/`materialize` صرفاً با
  **وجود داشتنِ** `COOKIES_DIR` شاخهٔ دیسک را می‌گرفتند، پس یک پوشهٔ خالی/اشتباه روی نود
  یعنی «هیچ اکانتی نیست» و آینهٔ Redis اصلاً خوانده نمی‌شد. حالا شاخهٔ دیسک فقط وقتی
  برنده است که **واقعاً فایل پیدا کند** و `materialize` هم روی نبودِ فایل به آینه برمی‌گردد؛
  و `_warn_cookieless` وقتی استخر اکانتِ قابلِ‌استفاده دارد ولی دانلود بی‌کوکی رفته، به
  ادمین DM می‌دهد (throttle ۳ ساعته) به‌جای پیامِ گمراه‌کنندهٔ «ادمین باید کوکی تنظیم کند».
- **سطلِ کوکیِ خالی «سوخته» نیست — و بیشترِ سطل‌ها ذاتاً خالی‌اند.** `_cookie_platform`
  می‌تواند **۱۴** سطلِ متفاوت بخواهد (۱۶ خروجیِ `platform_of` منهای اسپاتیفای و اپل که به
  youtube تا می‌خورند)، ولی `admin_web.COOKIE_PLATFORMS` فقط **۶** تا می‌سازد و
  `cookies.guess_platform` هم دقیقاً همان ۶ را می‌دهد. پس هشت پلتفرمِ **پشتیبانی‌شده** —
  ساندکلاود، آپارات، ویمئو، توییچ، دیلی‌موشن، بندکمپ، ردیت، استریمبل — سطلی می‌خواهند که
  از هیچ راهی پر نمی‌شود، و «other» (هاستِ ناشناخته) هم معمولاً خالی است. `_alert_if_low`
  این را «هیچ کوکیِ سالمی نمانده» می‌خواند و هر ۶ ساعت DMِ قرمز می‌فرستاد؛ برای این نُه
  سطل از روزِ اول کاذب بود. **گارد باید روی «کلِ اکانت‌ها» باشد نه روی «قابلِ‌استفاده‌ها»**،
  و این تفکیک تمامِ ماجراست: «۰ از ۳» یعنی استخر واقعاً سوخته و همان چیزی است که این تابع
  برایش هست، پس `if not healthy_count: return` رفع نیست — خفه‌کردنِ زنگِ خطر است.
  `cookies.pool_counts()` هر دو عدد را با **یک** پیمایش می‌دهد (روی نودِ دانلود هر پیمایش
  یک دسته رفت‌وبرگشتِ WireGuard است) و `healthy_count` حالا رویش سوار است.
  **ولی «۰ از ۰» خودش دو حالت است و شرط باید سه‌تایی باشد، نه دوتایی.** «هرگز پر نشده»
  (آپارات) و «پر بوده و اکانت‌هایش حذف شده» (اینستاگرام، بینِ پاک‌کردنِ سشن‌های مرده و
  چسباندنِ تازه‌ها) هر دو `total == 0` می‌خوانند — پس گاردِ دوحالتی نویزِ نُه سطل را
  می‌بندد و هم‌زمان سیگنالِ واقعیِ سطل‌های مهم را خاموش می‌کند. `cookies.was_stocked()`
  ردِ ماندگارِ `ckseen:<platform>` را می‌خواند که `set_meta` می‌نویسد و **`del_meta`
  عمداً پاک نمی‌کند**؛ قاعده می‌شود: «۰ از N» → هشدار · «۰ از ۰ ولی زمانی پر بوده» →
  هشدار · «۰ از ۰ و هرگز پر نشده» → سکوت. سه نکته که پشتِ این طراحی است. رد در
  `set_meta` نوشته می‌شود نه در مسیرِ افزودنِ پنل، چون آن‌جا تنها نقطه‌ای است که پلتفرمِ
  **صریح** را می‌بیند — نامِ فایل قابلِ‌اتکا نیست (اکانتِ «other» با برچسبِ
  `youtube-backup` فایلش `cookies_youtube-backup.txt` می‌شود و `guess_platform` سطلِ
  اشتباه را علامت می‌زند) و `admin_web` هم در محیطِ تست قابلِ import نیست. سیگنالِ
  **مشتق** بررسی و رد شد: `ckrot:<platform>` فقط وقتی زیاد می‌شود که **دو یا چند** نامزدِ
  هم‌رتبه باشند، پس سطلی که همیشه یک اکانت داشت هرگز آن را افزایش نمی‌دهد. و محدودیتِ
  شناخته‌شده: ساختنِ Redis از صفر این رد را می‌برد — روی مستر بی‌اثر است تا وقتی فایلی
  روی دیسک مانده باشد (`list_names` دیسک را مقدم می‌داند)، فقط «حذف شد **و بعد** Redis
  پاک شد» دوباره ساکت می‌شود.
  **و حذفِ واقعیِ اکانت سه گام است، نه دو:** فایل، `_unmirror_cookie`، `del_meta` — هر دو
  مسیرِ حذف (پنل و کال‌بکِ ربات) هر سه را دارند، **باگ نیست**؛ ولی تستی که فقط دو گامِ اول
  را بزند اکانت را حذف‌شده نمی‌بیند، چون `list_names` روی دیسکِ خالی به آینهٔ Redis
  برمی‌گردد. نسخهٔ اولِ کمکیِ تست دقیقاً همین را از قلم انداخت و تست شکست. هر سه گام حالا
  در `cookies.delete_account()` است (آینه → فایل → متا؛ عکسش یعنی حذفِ **آخرین** فایل
  `list_names` را به آینه می‌اندازد و اکانت لحظه‌ای «زنده» می‌شود) و یک گاردِ ASTی هر تابعی
  را که **دو یا چند** گام را دستی بنویسد می‌گیرد — معیار «ترکیب» است نه «هر گامی»، چون
  `_mirror_all_cookies` به‌درستی فقط `_unmirror_cookie` را صدا می‌زند و نسخهٔ اولِ گارد
  همان را مثبتِ کاذب گرفت؛ باریک‌کردنِ قاعده درست بود، نه استثنای دستی.
  **و خالی‌بودنِ سطل دانلود را متوقف نمی‌کند** — اندازه‌گیری‌شده با `run_download`ِ واقعی و
  yt-dlpِ جعلیِ **موفق**: پلتفرمی که `_ANON_FIRST` نیست و صفر اکانت دارد یک تلاشِ
  **بی‌کوکی** می‌زند (`_warn_cookieless` → `cookieless_used = True` → ادامه، نه `break`) و
  اگر سایت ناشناس جواب بدهد فایل تحویل می‌شود. پس آن هشت‌تا شکسته نبودند، فقط نویز
  می‌ساختند. نتیجهٔ عملی برای هرکسی که بخواهد «درستش کند»: عضویت در `_ANON_FIRST` روی
  سطلِ خالی **تقریباً** هیچ رفتاری را عوض نمی‌کند — با هر دو حالت و با هر دو موتورِ
  موفق/شکست، فراخوانیِ موتور، نبودِ کوکی، ضربه‌ها و DMها یکسان‌اند.
  **ولی «پیامِ کاربر یکسان است» غلط بود، و تصحیحش یک درسِ عام دارد** (۲۰۲۶-۰۸-۱۶، از
  ردیابیِ سورس): روی شکستِ **غیرِمحتوایی**، مسیرِ `anon=False` — یعنی همین هشت پلتفرم —
  به کاربر `dl_retry_account` («اکانتِ دیگری را امتحان می‌کنم») نشان می‌دهد، در حالی که
  آن سطل **هیچ اکانتی ندارد و نمی‌تواند داشته باشد**؛ بعد دورِ دوم `cookieless_used`
  حلقه را می‌شکند. مسیرِ `anon=True` به‌جایش بلافاصله `break` می‌کند، چون `ck.pick` روی
  سطلِ خالی چیزی نمی‌دهد. تعدادِ فراخوانیِ موتور در هر دو **۱** است — آن نیمهٔ ادعا درست
  بود. **درسِ عام:** «پیامِ کاربر» در یک جریانِ **ویرایشِ درجا** یعنی *دنبالهٔ* پیام‌ها،
  نه آخری‌اش؛ اندازه‌گیری‌ای که فقط پیامِ نهایی را ببیند هر ویرایشِ میانی را از دست
  می‌دهد، و این‌جا دقیقاً همان اتفاق افتاد. یعنی افزودنشان به `_ANON_FIRST` نویزِ لاگ و
  یک پیامِ گمراه‌کننده را کم می‌کند، و
  افزودنشان به `COOKIE_PLATFORMS` تصمیمِ محصولیِ جداست («آیا این سایت اصلاً لاگین لازم
  دارد؟») — هیچ‌کدام جایگزینِ گاردِ بالا نیست.
  **و همان تفکیک یک پله پایین‌تر هم لازم بود:** `_warn_cookieless` خطِ
  `log.error("cookieless attempt on …")` را **پیش از** گاردِ خروجش می‌زد، پس بعد از ساکت‌شدنِ
  DM هنوز هر دانلود از آن هشت پلتفرم یک ERRORِ دائمی برای مسیری می‌گذاشت که سالم است — و
  ERRORِ کاذبِ دائمی یعنی خطای واقعی لایش گم می‌شود. حالا سطلِ **بی‌اکانت** `log.info`
  می‌گیرد و سطلی که اکانت دارد ولی هیچ‌کدام قابلِ‌استفاده نیست **همچنان ERROR** است. مرز
  دقیقاً همان است: گاردِ نوشته‌شده روی `usable` به‌جای `total` این‌جا هم همان چیزی را خفه
  می‌کند که تابع برایش هست، و تستِ کنترلِ معکوس همان را می‌گیرد.
- **«سالم» یعنی «آخرین تلاش موفق بود»، نه «هیچ خطایی ثبت نشده».** وضعیتِ اکانت فقط از
  `fail_streak` می‌آمد، و `mark_fail` **تنها** برای خطاهای کوکی‌محور صدا زده می‌شد — پس یک
  خطای ناشناخته اصلاً به استخر نمی‌رسید و پنل تا ابد «سالم · خطا: ۰» نشان می‌داد در حالی که
  هیچ دانلودی موفق نبود. دو تغییر این را بست: (۱) `mark_fail` برای **هر** شکستی صدا زده
  می‌شود و دسته‌های بی‌ضربه (`transient`/`unrelated`) فقط `last_error` را ثبت می‌کنند؛
  (۲) وضعیتِ `UNPROVEN` («آخرین تلاش ناموفق») وقتی `last_error_at > last_ok` است. اکانت از
  چرخش بیرون نمی‌رود (در `USABLE` و در `_USE_ORDER` بعد از سالم است) — فقط دیگر سبز نیست.
  **دو تلهٔ همراهش:** `healthy_count` (که هشدارِ «کوکیِ سالم کم است» را می‌زند) باید
  `UNPROVEN` را هم بشمارد وگرنه یک شکستِ بی‌تقصیر هشدارِ الکی می‌فرستد؛ و `unfreeze`
  باید `last_error` را پاک کند، وگرنه بعد از «رسیدگی شد» اکانت با خطای منقضی سبز نمی‌شود.
- **آمارِ per-account به «سشن مرده یا IPِ مسدود؟» جواب نمی‌دهد.** وقتی *همهٔ* اکانت‌ها
  می‌افتند، مقصر معمولاً سشن‌ها نیستند بلکه IPی است که از آن بیرون می‌رویم. پس
  `cookies.note_exit()` موفقیت/شکست را به تفکیکِ **خروجی** هم می‌شمارد (`ckexit:<exit>:…`)
  و `exit_stats()` وقتی یک خروجی صفر موفقیت و ≥۳ شکست دارد `blocked=True` می‌دهد — پنل
  به‌جای متهم‌کردنِ کوکی‌ها می‌نویسد «IPِ این خروجی مسدود است». فقط شکستِ **واقعیِ شبکه‌ای**
  شمرده می‌شود، نه ردِ سیاستی (حجم/مدت/فیلترِ محتوا)، وگرنه سیگنال آلوده می‌شود.
- **An empty response is not a broken account.** gallery-dl reports a non-JSON/empty body as
  `An unexpected error occurred: JSONDecodeError - Expecting value: line 1 column 1 (char 0)`, which
  Instagram returns when it silently refuses the session or IP — but the *same* error appears when the
  extractor has fallen behind a site change. That ambiguity decides the handling: `cookies.TRANSIENT`
  makes `_is_cookie_error` **rotate to the next account** (a dead session is the common case) while
  `mark_fail` records nothing but `last_error` — **no fail streak and no cooldown**. Giving it a
  cooldown would take the entire pool out of service for a problem that may have nothing to do with
  the accounts. Because the admin cannot tell the two apart by eye, each download worker reports its
  `gallery-dl`/`yt-dlp` version to Redis at startup (`worker.startup_dl` → `dlver:<who>`) and `/health`
  shows them: old engine → `telabzar update` + `node/update.sh`, current engine → replace the session.
- **A dead Instagram session doesn't say "login".** gallery-dl answers a request made with an
  expired/invalidated cookie by following the redirect and reporting
  `[instagram][error] HTTP redirect to home page (https://www.instagram.com/)`. That string contains
  none of the usual markers, so it used to fall through `_is_cookie_error` as "unrelated": no rollover
  to the next account, no fail-streak on the dead one, and the user got a raw error even with healthy
  accounts in the pool. `redirect to home page` is now in both `tasks_download._LOGIN_HINTS` and
  `cookies._CLASS_HINTS[LOGIN_REQUIRED]`. When adding an engine, check what it says on *silent*
  auth failure — the loud errors are already covered.
- **A download link is not a video page — don't hand it to yt-dlp.** yt-dlp is built for pages it can
  extract; on a plain file URL it fails in ugly ways (a signed blob link with a GUID path and a long
  query made it crash writing its metadata JSON). So an unknown host now gets a **cheap HEAD** first
  (`downloader.probe_direct`, 15 s, manual redirects) and anything that isn't a page is streamed by
  `download_direct` instead: `text/html`, `application/json`/`xml`, and **HLS/DASH manifests** stay
  with yt-dlp; `application/*`, `image/*`, `video/*` and anything with `Content-Disposition:
  attachment` become a direct download. Four rules that matter: the **filename comes from
  `Content-Disposition`** (RFC 5987 `filename*` and plain), not the URL path — the path is often a
  GUID; the **cap is enforced twice** (`Content-Length` before starting, and a running byte count
  during, because servers omit or lie about it) and the partial file is deleted; **every redirect hop
  is re-checked with `is_safe_url`** (aiohttp's own redirect following would hide a hop into
  `169.254.169.254`); and the returned `info` carries `kind` (from `filetypes._document_kind`) and
  deliberately **no `title`**, so the card shows the technical view rather than a fake post caption.
  Runtime keys: `dl_direct_enabled`, `dl_direct_max_mb` (500; `dl_max_size_mb` still caps it, since
  the Telegram upload ceiling is not negotiable). Direct downloads never touch a cookie and never
  penalise the pool. Gated by `dl_allow_unknown` like any unknown host.
- **A hostname that isn't an IP literal is not automatically safe.** `is_safe_url` used to run
  `ipaddress.ip_address(host)` and treat `ValueError` as "so it's a hostname → allow". But
  `2130706433`, `0x7f000001`, `127.1` and `017700000001` **all** raise `ValueError` and **all**
  connect to `127.0.0.1` — `ipaddress` only accepts dotted-quad, while `getaddrinfo` (which is what
  the connection actually uses) understands every `inet_aton` form. So literal detection now goes
  through `socket.getaddrinfo(host, None, flags=AI_NUMERICHOST)`: libc semantics, no DNS, and it
  returns `gaierror` exactly when the host really is a name. Beyond the notation trap there were two
  more holes: `::ffff:127.0.0.1` has `is_loopback == False` (only `is_private` catches it, so unwrap
  `ipv4_mapped` explicitly), and `is_multicast`/`is_unspecified`/CGNAT `100.64.0.0/10` were not
  checked at all. **Names are a separate layer:** `is_safe_url_resolved()` (async, threaded
  `getaddrinfo`, 60 s cache, 2 s timeout) is what the link front door calls — without it, `evil.example`
  with an A-record of `169.254.169.254` sailed through. DNS failure is **conditional, not fail-open**:
  with `proxy_url` set the *proxy* resolves the name and our local view is irrelevant → allow; with no
  proxy (our default) the request leaves this machine, so a failed lookup has no excuse → reject + log.
  **`PROXY_URL` is empty in production (verified 2026-07-26 on the master) — egress is direct**, which
  is also the compose default and what `install.sh` leaves behind (it never prompts for it). That is
  the strict configuration: the veto resolver is attached and DNS failure is fail-closed, so there is
  no gap. The conditional fail-open matters only if `proxy_url` is ever pointed at an **internal**
  http(s) proxy — one that can reach postgres/redis/`admin:8080`/`10.51.0.1:8080`. If that day comes,
  the fail-open has to be inverted (DNS failure → reject) with an explicit allow-list for the hosts we
  define ourselves; re-read this bullet before changing `proxy_url`. Docker service names are not the
  hole: inside the containers Docker's own DNS resolves `admin`/`postgres` to `172.x`, so the resolve
  layer already rejects them. The gap would be names our container cannot resolve but the proxy can.
- **A check followed by a connect is a TOCTOU window; make the connect itself do the checking.** The
  syntactic check runs per redirect hop in `_follow`, but DNS rebinding can hand a different address to
  the actual connection. The `direct` engine's sessions therefore use
  `TCPConnector(resolver=_safe_resolver())` — aiohttp vetoes the address it is about to connect to, so
  every hop is covered with no window. This works only for what we connect to ourselves: **yt-dlp is a
  subprocess** and cannot be given a resolver, so there the front door is the whole defence. One
  residual channel is accepted on purpose and marked in the code: the `dl_failed` message shows
  `msg[:280]` of the engine's stderr, so an internal URL that reached yt-dlp could echo a fragment
  back — silence there would make every failed download undiagnosable.
  **The resolver must not be attached when a proxy is in use** (`_direct_connector`): aiohttp resolves
  the *proxy* host, not the destination, so the veto protects nothing there and only breaks the proxy
  hop — a `PROXY_URL` of `http://squid:3128` (a docker service name → `172.x`) counted as "internal"
  and every download died with `ClientConnectorDNSError`. A proxy given as a bare IP was unaffected,
  which is exactly what makes this the kind of regression a unit test doesn't find.
  **A socks proxy now goes through `aiohttp_socks.ProxyConnector`** (phase 3d). Before that,
  `_http_proxy` dropped it and the `direct` engine connected straight out of the master's IP while
  yt-dlp and gallery-dl used the exit — silently, and against our own documentation. Two things to
  know before touching it: the anti-TOCTOU resolver **cannot** be attached to `ProxyConnector`
  (`kwargs["resolver"] = NoResolver()` is unconditional), and pinning a vetted IP instead breaks TLS
  because python_socks builds `server_hostname` from the destination — so the front door is the
  defence, the same posture an http proxy already had. `socks5h://` is rewritten to `socks5://`
  (python_socks rejects the scheme and defaults to proxy-side DNS anyway). Switch: `dl_direct_proxy`.
- **`INCR` + `DECR`-in-`finally` is not a concurrency limiter.** `finally` does not run on OOM/kill, and
  `dl:active` had no TTL, so three ungraceful deaths permanently pinned the counter above
  `dl_concurrency` and **every** later download answered "busy" forever — self-inflicted, invisible, and
  only fixable by deleting the key by hand. `app/dl_active.py` replaces it with a ZSET scored by
  **Redis server time** (`TIME`, not the local clock — master and download node are two machines), a
  `keepalive` task that refreshes the live job's score for the whole job (upload phase included), and a
  prune-then-`ZCARD` count, so an orphaned entry evaporates after `ACTIVE_TTL`. Two traps: the member
  must be **per-job unique**, not `ref` — `ref` is shared between the probe and fetch phases and
  `on_dl_pick` can fire several quality picks from one menu, so two live jobs would overwrite and then
  delete each other's slot; and the keepalive task must be cancelled in `finally` or it outlives the job.
  The module deliberately has no heavy imports because **the admin panel reads it too** and the panel
  image has no Pillow — importing `tasks_download` there would crash the process.
- **A user-supplied number reaches ffmpeg; validate it where the loop is.** `Spd.rate` is a free-form
  `str` in the callback, and `_atempo_chain` looped `while r < 0.5: r /= 0.5` — which never terminates
  for a negative rate and never for `inf` either. The killer detail is that `_atempo_chain` is **sync
  and runs before any `await`**, so ARQ's asyncio `job_timeout` can never fire: one crafted callback
  froze the entire worker process (or the **processing node**, since `speed` is in `OFFLOAD_OPS`) and
  grew a list until OOM. Two guards, deliberately at different levels: `_do_op` accepts only rates the
  bot itself offers (`keyboards.AUDIO_SPEEDS`), and `_atempo_chain` itself rejects non-finite values and
  anything outside `SPEED_MIN..SPEED_MAX`. `op_speed_pick` also got the `kind != "audio"` guard its
  sibling `op_speed` already had — the *systematic* absence of ownership/validation guards in
  `routers/ops.py` is a separate, still-open problem.
- **`normalize_probe` is a filter, and the safety layer reads what it drops.** It returned only
  `{title, duration, kind, thumbnail, options}`, so `safety.check_meta()` on the probe result saw no
  `age_limit`, `description`, `tags`, `categories`, `uploader` or `channel` — the `age_limit >= 18`
  test, the cheapest and strongest signal we have, **never fired before a download**. (After the
  download it did work, because the fetch path passes yt-dlp's raw `.info.json`.) Those fields are now
  carried through, size-capped. For the quick path — which is the default (`dl_default_ux=quick`) and
  never probes — the gate rides on the download call itself via `--match-filter`, so it costs **zero**
  extra round trips and zero extra cookie-pool spend. **The comparison must be `age_limit<?18`, not
  `age_limit<18`:** in yt-dlp a plain numeric comparison on an **absent** field is False, and most
  extractors never set `age_limit`, so the strict form would have rejected almost every video. yt-dlp's
  rejection lands as `does not pass filter` in stdout and, depending on version, with either exit code,
  so `download_ytdlp` checks both the stdout tail and the raised error before turning it into
  `AgeRestricted` — which `run_download` handles *before* the cookie-rotation branch, since no other
  account would fare differently and none deserves a strike.
  **`--match-filter` reaches Spotify too, and there it is silent.** `download_spotify` matches each
  track to YouTube and calls `download_ytdlp` with the *same* `opts`, so an age-restricted track raises
  `AgeRestricted`, is swallowed by that loop's `except Exception: … continue`, and is **dropped from
  the playlist with no message** — the rest is delivered normally. That is the filter working as
  intended, but if *every* track is blocked the user sees `spotify: no YouTube match`, which names the
  wrong cause. Left as-is deliberately; fixing the message is a follow-up, not a security matter.
- **React to the *class* of a cookie error, not a single counter.** `cookies.classify_error()` maps an
  engine error to `rate_limit` / `checkpoint` / `login_required` / `bot_check` / `unrelated`, and
  `mark_fail(error_class=…)` reacts differently: a **rate limit costs the account nothing** (it means
  *we* pushed too hard — striking it throws away a healthy account), a **checkpoint freezes** it
  (`FROZEN` is never picked; more automatic retries only make it worse) and DMs the admin, and only
  login/bot-check increments the streak. `FROZEN`/`INVALID` accounts form the attention queue —
  `/cookies` shows it and the DM carries three buttons; the admin can paste a fresh cookie **inside
  Telegram** (the `Ck` callback carries a short Redis token, never the filename, because of the 64-byte
  callback cap). That paste handler lives in the **admin router** and `raise SkipHandler`s when no paste
  is pending, so ordinary long messages still reach the ops/download/files routers.
- **Attach a cookie only when the platform demands it.** YouTube serves ~300 videos/hour anonymously
  (~2000 authenticated), so cookie-on-every-download burned accounts for nothing. Platforms in
  `tasks_download._ANON_FIRST` try **anonymously first** and escalate to a cookie only when the error
  is cookie-shaped; Instagram has no anonymous access so it always uses one. Runtime key:
  `dl_cookie_when_needed`.
  **آن «~۳۰۰ در ساعت» عددِ ویکیِ yt-dlp است، نه عددِ ما — و روی این سرور اندازه‌گیری شد: ~۳۲٪.**
  IPِ دیتاسنتر است و یوتیوب چالشش می‌کند، پس نرخِ واقعیِ ناشناس یک‌سوم است نه نزدیکِ صد (بولتِ
  «دانلودِ ناشناسِ یوتیوب حدود ۳۲٪ جواب می‌دهد» بالاتر). قاعده عوض نمی‌شود — یک‌سوم دانلودها
  هیچ اکانتی لمس نمی‌کنند و همان می‌ارزد — ولی هر طراحی‌ای که فرض کند anon-first کوکی را
  **حذف** می‌کند غلط است. مقایسه: مسیرِ ناشناسِ اینستاگرام ~۸۷٪ است، یوتیوب هرگز آن نمی‌شود.
- **How the cookie is exported decides how long it lives.** YouTube **rotates** cookies on a still-open
  session, so an export from a normal browser window dies quickly. The working procedure (yt-dlp wiki)
  is: incognito window → log in → **same tab** → `youtube.com/robots.txt` → export → **close the window
  without logging out**. This is printed on the `/cookies` page because it matters more than any pool
  logic.
- **The download cache is an optimization that must never break a download.** It stores only the
  Telegram **`file_id`** (never bytes), so a repeat link is instant and costs zero bandwidth and zero
  disk. Three rules: the key is the **normalized** URL (`dl_cache._cache_url` → `yt:<id>`/`ig:<code>`/
  `x:<id>`, plus a **closed** denylist of tracking params — an unknown param is *kept*, because a miss
  is safe while dropping a meaningful param would serve the **wrong file**); `get_cached` falls back to
  the old raw-URL key and migrates the row, so changing normalization never voids the existing cache;
  and `deliver_from_cache` returns **False** on `TelegramBadRequest`, deleting the row so the caller
  falls through to a real download (`routers/download.py` reuses the already-sent status message as the
  anchor). Carousels live in the same row as an ordered `items` JSON list and are replayed with
  `send_media_group` over `file_id`s — `InputMedia*` models are **frozen** in aiogram, so the caption
  must be passed at construction, and it needs `html.escape` because `post_caption` is stored raw.
- **The stats page is historical, the health page is live — don't duplicate.** `/stats` answers
  "what happened over the last N days" (range tabs: 24h/7d/30d/all, `_RANGES`); `/health` answers
  "what is broken right now". `_stats(rng)` is one linear gather behind a **60 s Redis cache**
  (`_stats_cached`, key per range) because the page runs ~20 aggregate queries. Two portability rules:
  day bucketing happens **in Python** (`_bucket`/`_stacked_series`) because `date_trunc` is Postgres-only
  while the tests run on SQLite, and **p95 is computed in Python** over the last `_DUR_SAMPLE` jobs for
  the same reason (`percentile_cont` is Postgres-only). A multi-series chart must share **one** scale —
  normalising each series to its own max makes a day with 1 signup look identical to a day with 30
  files. Op duration comes from `Job.finished_at − created_at`, which the worker always sets.
- **An engine's output dir must contain only its output.** `download_gallerydl` writes into
  `workdir/gl/` and collects **only** from there. It used to write into `workdir` itself and walk the
  whole tree, which broke Instagram on a **download node**: `cookies.materialize()` puts the cookie in
  `workdir/ck/<name>` (the node has no `COOKIES_DIR`), so the walk counted it as a downloaded file — a
  **single** reel looked like 2 files, took the multi-item **album** branch, and therefore got no card
  and no post caption. It was invisible because `_deliver_album` filters by media extension and quietly
  dropped the `.txt`. The master was unaffected (its cookie path is outside the workdir), so this only
  ever reproduced with a node attached. Any future scratch file placed inside a job's workdir has the
  same trap — keep engine output in its own subdirectory.
- **مسیرِ ناشناسِ اینستاگرام: چهار چیزی که با دادهٔ واقعی سنجیده شد و هرکدام یک باگِ خاموش
  می‌سازد.** `app/instagram_anon.py` (فاز ۱، هنوز وصل نیست) رسانه را بی‌کوکی از صفحهٔ
  `/embed/captioned/` درمی‌آورد. فیکسچرها **ضبطِ واقعیِ مستر**اند
  (`tests/fixtures/ig_embed_{reel,carousel,photo}.html`، ۲۰۲۶-۰۸-۱۴) و همان‌ها این چهار تله را
  لو دادند. **(۱) `contextJSON` در فرمِ تک‌عکسی «غایب» نیست، `null` است** — پس چکِ «کلید موجود
  است» پارس را می‌ترکاند؛ و **گیت‌زدن روی `isRichEmbed`/`isSidecar` غلط است**، چون در همان
  فیکسچر `isRichEmbed=False` است در حالی که پست کاملاً سالم است. شکلِ داده تصمیم می‌گیرد، نه
  فلگ‌ها. **(۲) عرضِ `srcset` باید به انتهای توکن مقید باشد.** با `re.search(r"(\d+)w", tok)`
  اولین عدد از **داخلِ URLِ امضاشده** برداشته می‌شود: روی فیکسچرِ واقعی کاندیدِ `3072w` را `9`
  می‌خواند و در نتیجه **URLِ دیگری** برنده می‌شود — یعنی هم عرض هم فایل غلط. `\s(\d+)w$` به‌ازای
  **هر توکن**. زیرنکته‌ای که فرقِ گرفتن و نگرفتن است: `findall`+`max` روی کلِ رشته تصادفاً همان
  ۳۰۷۲ را می‌دهد، پس فقط شکلِ per-token این باگ را نشان می‌دهد و سابوتاژ فقط روی همان شکل
  می‌گیرد. **(۳) خروجیِ `srcset` باید `html.unescape` شود و خروجیِ `gql_data` نباید.** اولی
  داخلِ HTML است و `&` در آن `&amp;` نوشته شده (اندازه‌گیری‌شده)، پس بدونِ unescape پارامترهای
  امضا خراب به CDN می‌روند؛ دومی از `json.loads` آمده و entity ندارد. **(۴) هدف‌گیریِ
  `class="EmbeddedMediaImage"` لازم است، نه احتیاط:** در همان HTML دو `<img srcset>`ِ دیگر هم
  هست و **هر دو روی `scontent-…cdninstagram.com`**اند، پس فیلترِ هاست نمی‌گیردشان.
  به‌علاوه یک تفاوتِ عمدی با cobalt: فرزندی که `is_video` را ادعا کند ولی `video_url` نداشته
  باشد، آن‌جا بی‌صدا با `display_url` (یعنی **فریمِ پوستر**) جواب داده می‌شود
  (`instagram.js:307-316`)؛ این‌جا کلِ رده با `no_media` می‌افتد و کار به کوکی می‌رود، چون
  «فایلِ غلط» از «فایل نداریم» بدتر است. `RungReport.detail` علتِ **مشخص** را می‌برد (کدام
  فرزند)، نه یک `no_media`ِ ژنریک، تا تله‌متریِ فاز ۲ بتواند drift را از انتظارِ عادی جدا کند.
  **و آن قاعده تورِ ایمنی نیست — روزِ اولِ تولید شلیک کرد.** ادعای قبلیِ این‌جا (از
  کاروسلِ ترکیبیِ `Daq3IWJGIPG`، که هر **۶** فرزندِ ویدیویی‌اش `video_url` دادند و همه
  با `HTTP 206 video/mp4` آمدند) این بود که «`is_video` بدونِ `video_url`» در تولید
  **تورِ ایمنیِ drift** است نه مسیرِ رایج، و اگر دیده شد یعنی اینستاگرام عوض شده. آن
  ادعا با دادهٔ تولید **رد شد**: `Dbew2QJNYQx` یک `GraphVideo` با `is_video=True` و
  **بدونِ** `video_url` است، در حالی که `display_url` و تگِ `EmbeddedMediaImage` هر دو
  در همان صفحه حاضرند. یعنی دقیقاً بدترین شکل: **پوستر دمِ دست بود.** ماژول درست
  برنداشت و کلِ رده را به کوکی انداخت. پس این یک حالتِ **عادیِ** اینستاگرام است، نه
  خبرِ drift — و همان چیزی است که تفاوتِ عمدی با cobalt (`instagram.js:307-316`) برایش
  ساخته شد. `RungReport.detail` را به‌عنوان «کدام فرزند»، نه «اینستاگرام عوض شد»،
  بخوان. یک نمونه‌ای که این را نشان بدهد هرگز شرطِ کافی برای «نادر است» نبود؛ نمونهٔ
  `Daq3IWJGIPG` فقط نشان می‌داد که این حالت **همیشگی** نیست.
  **و یک ردهٔ شکستِ دوم که با اولی یکی نیست و باید نام داشته باشد — «قالبِ خالی».**
  `DajmNS3lMrK` و `Dbgyn2xyG_v` هر دو `contextJSON=null` **و** بدونِ
  `EmbeddedMediaImage` برگشتند، با حجمِ صفحهٔ **۲۰۹۸۵۸** و **۲۰۹۸۵۹** بایت — یک بایت
  اختلاف، یعنی یک قالبِ **یکسانِ** بی‌محتوا. اینستاگرام صفحه را ۲۰۰ می‌دهد ولی هیچ
  رسانه‌ای داخلش نمی‌گذارد. هر دو **بعدش با کوکی موفق دانلود شدند**، پس محتوا هست و
  فقط ناشناس سرو نمی‌شود. این `no_media`ِ **درست** است و رفع‌شدنی نیست: نه پارسر خراب
  است (چیزی برای پارس‌کردن نیست) و نه رده‌ای هست که بسازیمش. تفکیکش از ردهٔ اول مهم
  است چون آن یکی «داده هست، ما ردش کردیم» است و این یکی «داده نیست».
  **و ردهٔ GraphQL: ساخته نشد، و حالا REFUTED — نه «هنوز نساخته‌ایم».**
  نسخهٔ کاهش‌یافته‌اش اجرا شد (POST به `https://www.instagram.com/graphql/query` با
  `doc_id=8845758582119845` و هدرهای `X-IG-App-ID` + `X-FB-Friendly-Name:
  PolarisPostActionLoadPostQueryQuery` — از سورسِ cobalt، حدس نبود) روی **چهار**
  شورت‌کدِ واقعی: هر چهار `HTTP 403` با صفحهٔ `not-logged-in` و هر چهار **دقیقاً
  ۲۰۹۵۲ بایت**. و **کنترلِ منفی** بخشِ تصمیم‌کننده است: `DYiEBENOlT1` — که از مسیرِ
  embed **موفق** دانلود می‌شود — همان ۴۰۳ را گرفت. پس این خاصیتِ **اندپوینت برای
  درخواستِ ناشناس از این IP** است، نه خاصیتِ آن پست‌ها؛ بدونِ آن کنترل، چهار ۴۰۳
  می‌توانست «آن چهار پست خاص‌اند» خوانده شود. **نسخهٔ کاملِ توکن‌کِشی هم پیشنهاد
  نشود:** همان درخواست را می‌سازد و به همان گیت می‌خورد — تفاوتش در به‌دست‌آوردنِ
  توکن است، نه در چیزی که اندپوینت به یک درخواستِ بی‌سشن می‌دهد.
  دو چیزِ دیگر که همچنان ساخته نشده‌اند و دلیلشان عوض نشده: **استوری** اصلاً مسیرِ
  ناشناس ندارد (cobalt هم بی‌کوکی ردش می‌کند، `instagram.js:472`) پس همیشه باید به
  کوکی برود؛ و لینکِ `/share/<id>/` یک resolveِ ریدایرکت با
  `User-Agent: curl/7.88.1` می‌خواهد (`instagram.js:522-529`).
- **اتصالِ مسیرِ ناشناس: نقطهٔ اتصال قبل از `_next_cookie` است، و «قبل» این‌جا معنیِ
  دقیقی دارد.** گامِ ناشناس بینِ محاسبهٔ `anon` و حلقهٔ تلاش در `run_download` نشسته،
  نه داخلِ `download_gallerydl` — چون تا رسیدن به موتور، `_next_cookie` از قبل
  `cookies.pick` کرده (اکانت را از چرخه درآورده)، `materialize` فایل را روی دیسکِ نود
  نوشته و `note_use` مهرِ فاصلهٔ حداقلی زده. هر سه **بی‌بازگشت**اند حتی اگر آن کوکی
  هیچ‌وقت به موتور نرسد، پس «کوکی استفاده نشد» ادعای ضعیفی است؛ ادعای درست «کوکی
  انتخاب نشد» است و تستِ اصلی همان را با تریپ‌وایر می‌سنجد.
  **گیت روی شورت‌کد است نه پلتفرم:** `platform_of` برای `/stories/` و لینکِ پروفایل هم
  `instagram` می‌دهد، ولی آن‌ها مسیرِ ناشناس ندارند (cobalt هم استوری را بی‌کوکی رد
  می‌کند)، پس `shortcode_of` تصمیم می‌گیرد و آن‌ها **بدونِ هیچ درخواستِ شبکه‌ای** مستقیم
  به کوکی می‌روند.
  **`while not anon_won:` عمدی است و `while paths is None:` نیست.** `anon_won` داخلِ
  حلقه هرگز نوشته نمی‌شود، پس از داخلِ حلقه بایت‌به‌بایت همان `while True:`ِ قبلی است.
  فرمِ دیگر بی‌ضرر به‌نظر می‌رسد ولی یک رفتار را عوض می‌کند: `cookies.mark_ok`
  `get_meta`/`set_meta` را **بدونِ `try`** صدا می‌زند، پس یک خرابیِ Redis *بعد از*
  دانلودِ موفق با `paths`ِ ست‌شده به `except` می‌افتد — آن‌جا `while True` دوباره دانلود
  می‌کند و `while paths is None` تحویل می‌دهد. تغییرِ رفتار، هرچند در حالتی نادر.
  **جداسازیِ فایل شرطِ درستی است نه نظافت:** خروجی در `<workdir>/igan/<NN>/` می‌نشیند و
  در `finally` روی هر خروجی‌ای جز موفقیتِ کامل پاک می‌شود، وگرنه شکستِ نیمه‌کاره (۶ آیتم
  از ۱۱) workdirِ آلوده تحویلِ مسیرِ کوکی می‌دهد. تستش باید workdir را **در لحظهٔ
  فراخوانیِ `download_gallerydl`** بسنجد، نه بعد از `run_download` — آن‌جا `finally`ِ خودِ
  تابع کلِ workdir را پاک کرده و «چیزی نمانده» بی‌قیدوشرط صادق است، یعنی تستِ توخالی
  (نسخهٔ اولِ همین تست دقیقاً همین بود).
  **`engine` عمداً `gallerydl` می‌ماند:** شاخه‌های تحویل روی `engine` و `len(paths)`
  می‌چرخند، پس نگه‌داشتنش یعنی کاروسل همان Rich/آلبوم و تک‌آیتم همان کارت را می‌گیرد،
  بدونِ یک خطِ تغییر در پایین‌دست. کش هم بی‌اثر است چون `dl_cache.cache_key` فقط
  `(url, selector)` را می‌بیند و موتور در آن نیست — پس روشن/خاموش‌کردنِ فلگ ردیف‌های
  کش را باطل نمی‌کند.
  **بودجهٔ زمانی لازم است چون `download_direct` کرانِ کلی ندارد:**
  `ClientTimeout(total=None, connect=30, sock_read=120)` برای یک فایلِ تکی درست است ولی
  این‌جا در N آیتم ضرب می‌شود و تنها کرانِ باقی‌مانده `job_timeout`ِ ۵۴۰۰ ثانیه‌ای است.
  این پاس **گمانه‌زنی** است: اگر نگرفت باید سریع کنار برود تا مسیرِ کوکی وقت داشته
  باشد، نه اینکه اسلاتِ دانلود را یک ساعت نگه دارد و بعد تازه مسیرِ اصلی شروع شود. پس
  هر آیتم با `asyncio.wait_for` روی بودجهٔ **باقی‌مانده** اجرا می‌شود
  (`ANON_FETCH_BUDGET`، ۳۰۰ ثانیه؛ resolve جداست و خودش ۲۵ ثانیه سقف دارد).
  **و آن بودجه به بدترین حالت اضافه می‌شود، پس قاعده این است:
  `۳۲۵ + (تلاش‌های کوکی × ۱۸۰۰)` باید زیرِ `job_timeout`ِ ۵۴۰۰ بماند** — ۱۸۰۰ تایم‌اوتِ
  هر فراخوانیِ gallery-dl است (`download_gallerydl`) و ۵۴۰۰ مالِ
  `DownloadWorkerSettings`. **ولی قاعده را با عددِ سنجیده‌شده بخوان، وگرنه نفرِ بعد
  دنبالِ باگی می‌گردد که این تغییر نساخته:** با پیش‌فرضِ `dl_max_cookie_tries = 5` این
  نامساوی **از قبل** نقض بود — ۵×۱۸۰۰ = ۹۰۰۰، و با بودجه ۹۳۲۵. یعنی سقفِ واقعی را
  `job_timeout` تعیین می‌کند نه `dl_max_cookie_tries`، و سهمِ این تغییر **یک تلاشِ
  گیرکرده** است: پیش از آن ۳ تلاشِ ۱۸۰۰ثانیه‌ای دقیقاً جا می‌شد (۳×۱۸۰۰ = ۵۴۰۰) و حالا
  ۲ تا. عملاً این حالت نادر است — شکستِ عادیِ gallery-dl در چند ثانیه برمی‌گردد و ۱۸۰۰
  یعنی موتور هنگ کرده — ولی اگر روزی `dl_max_cookie_tries` یا `job_timeout` تنظیم شد،
  همین نامساوی است که باید حل شود، نه حدس.
  **`fetch_failed` نباید با `ok` جمع شود:** آن‌جا resolve موفق بوده ولی بایت نیامده،
  یعنی به مسیرِ کوکی افتاده‌ایم و کوکی سوخته — شمردنش به‌عنوان موفقیت ادعای «این‌قدر
  دانلود کوکی لمس نکرد» را دروغ می‌کند.
  **مبنای اولِ تولید (۱۴–۱۵ آگوست ۲۰۲۶)، تا نرخ‌های بعدی با چیزی مقایسه شوند:**
  ۱۵ آگوست `iganon:ok = 5` و **صفر** در هر چهار سطلِ دیگر — یعنی هر ۵ دانلودِ
  اینستاگرامِ آن روز بدونِ لمسِ هیچ اکانتی انجام شد. ۱۴ آگوست (بعد از روشن‌کردنِ فلگ)
  ۵ `ok` و ۳ `unsupported` از ۸ لینک. جمعاً **۱۰ از ۱۳ ≈ ۷۷٪**. مبنای پیش از فلگ:
  ۱۴ آگوست ۲۱ تا `dlstat:instagram:ok`، **همه با کوکی**.
  **این عدد را با قیدش بخوان:** نمونه کوچک است، و آن سه شکستِ ۱۴ آگوست همه در یک
  نشستِ **تستِ دستی** افتادند نه در توزیعِ طبیعیِ ترافیک — ۱۵ آگوست که ترافیکِ
  عادی‌تری بود ۵ از ۵ داد. نرخِ پایدار چند روز داده می‌خواهد؛ ۷۷٪ کفِ محتاطانه است و
  ۱۰۰٪ سقفِ خوش‌بینانه.
  **و ریسکِ اصلیِ روشن‌کردن سنجیده شد و رخ نداد:** نگرانی این بود که حجمِ درخواست به
  صفحهٔ embed اعتبارِ IPِ سرور را خراب کند و کلِ استخر را به دردسر بیندازد. ۱۵ آگوست
  `dlstat:instagram:fail = 0` است، به‌علاوهٔ **صفر** `blocked` و **صفر** `network` —
  یعنی نه اینستاگرام ما را محدود کرد و نه هیچ دانلودی شکست خورد. دامنهٔ این شاهد را
  هم بگو تا بیش از آنچه هست خوانده نشود: این در **حجمِ سنجیده‌شده** است (چند ده
  درخواست در روز)، پس شاهدِ «بی‌خطر است» برای همین مقیاس است نه برای مقیاسی چند برابر؛
  اگر ترافیک جهید، `blocked`/`network` همان دو سطلی‌اند که اول تکان می‌خورند.
- **ابزارِ `tools/ig_anon_probe.py` بدونِ تزریقِ ماژول کار نمی‌کند — و این محدودیتِ الگوی
  «`git show … | docker compose exec`» است، نه باگِ ابزار.** ایمیجِ `download-worker` یک
  عکسِ فوریِ `app/` در زمانِ build است، پس هر ماژولِ **تازه** تا rebuildِ بعدی داخلش نیست و
  ابزار با `ImportError: cannot import name 'instagram_anon' from 'app' (/srv/app/__init__.py)`
  می‌افتد. آن الگو تا امروز کار می‌کرد چون همهٔ ابزارهای قبلی (`spotify_embed_dump.py` و…)
  ماژول‌های **موجود** را صدا می‌زدند. راهِ حل یک خطِ تزریق پیش از اجراست:
  `git show origin/<branch>:app/instagram_anon.py | docker compose exec -T download-worker sh -c 'cat > /srv/app/instagram_anon.py'`.
  **خودکفا‌کردنِ ابزار بررسی و رد شد:** آن‌وقت نردبون دو بار نوشته می‌شد و ابزار یک
  **کپیِ** منطق را می‌سنجید نه تولید را — همان واگراییِ دو نسخهٔ دست‌نویس که برای
  `remove_cookie_file` ثبت است. به‌جایش خودِ ابزار `ImportError` را می‌گیرد و دستورِ لازم را
  چاپ می‌کند، چون خطای خام علت را نمی‌گوید. این همان ردهٔ «سندباکس در برابر محیطِ واقعی»
  است که §۶ سه نمونهٔ دیگرش را دارد؛ **قاعدهٔ عام: هر ابزارِ تازه‌ای که ماژولِ تازه‌ای را
  صدا بزند این گام را لازم دارد** تا وقتی merge و `telabzar update` انجام شود.
- **The card has two caption states, and the caption must follow the keyboard.** Collapsed
  (`collapsed_kb` — the default for `source="dl"` and what the «بازگشت» button restores) shows the
  **source post's own text** — Instagram/Twitter caption, or YouTube title+channel+description — in a
  closed `<blockquote expandable>` and nothing else. Open (full ops menu) shows the plain technical
  caption (`🎬 name` + `📦 size · 🎞 quality · ⏱ duration · format`) with **no wrapper quote**; only the
  changelog keeps its own small expandable quote. `cards.view_caption(file, lang, collapsed=…)` is the
  single switch — `set_card_note(..., collapsed=True)` is passed **only** by `op_collapse`; progress,
  error and limit notes stay technical because they are about the file being worked on. A post with no
  caption falls back to the technical view so a card is never empty. `File.post_caption` stores the
  **raw, HTML-free** text (`tasks_download._post_text` → `downloader.clean_caption`: hashtags stripped,
  1024-char Telegram cap) and `post_view()` escapes it at render — one unescaped `<` in a real caption
  breaks the whole message. Telegram media groups/albums deliberately keep their own caption path.
- **Telegram believes the metadata we send — it never measures the file.** `duration/width/height`
  passed to `sendVideo`/`InputMediaVideo` are displayed verbatim, so any op that changes them
  (trim/speed/compress/resize/convert/concat) **must** refresh the `File` row from the output, or the
  card shows the previous file's time and quality. `tasks._refresh_media_meta(file, path)` (backed by
  `processing.probe_media()`, the single ffprobe source of truth) is called after every media-producing
  op and on spawned cards; `tasks_download._media_meta()` does the same at the download door. A video
  with no `thumbnail` shows Telegram's own grey frame — generate a poster (`processing.video_poster`,
  ≤320 px) whenever the engine didn't give one.
- **Video must reach Telegram as MP4** — `sendVideo` only guarantees MP4; webm/mkv silently degrades to
  a document or loses the preview. `--merge-output-format mp4` is **not** enough: it only fires when
  yt-dlp actually merges two streams, so a pre-muxed pick (the `/b` branch — YouTube serves webm/VP9)
  or an mp4-incompatible codec pair (yt-dlp falls back to mkv with only a warning) both slip through.
  Defence is two-layer: `downloader._FORMAT_SORT` (`res,vcodec:h264,acodec:aac,ext:mp4:m4a`) prefers a
  compatible stream at the resolution the user picked, and `downloader._ensure_mp4()` container-remuxes
  (`-c copy`, no re-encode) anything that still isn't MP4, keeping the original if the remux fails.
  `_media_meta()` applies it to **every** engine, not just yt-dlp.
- **A model cached in the image is only cached for the model the image prefetched.** `worker.Dockerfile`
  bakes `WhisperModel('base')` into `HF_HOME=/opt/models/hf`, but the panel offers five whisper sizes,
  so any other pick is downloaded at **run time** into the container's writable layer — which
  `telabzar update` throws away. The result was a multi-GB re-download (`large-v3` ≈ 3 GB) after every
  update, in the middle of a user's job and holding one of the four op slots the whole time. The compose
  `worker` service now mounts the named volume `model-cache:/opt/models/hf`. Two consequences worth
  knowing before touching it: a named volume mounted over a **non-empty** image directory is seeded with
  that directory's content on first use, so the prefetched `base` is preserved rather than shadowed —
  **but from then on the volume no longer tracks the image**, so if the prefetched model is ever changed
  the volume has to be removed by hand. And this fixes the **master only**: `node/install.sh` runs the
  role's container with **no volumes at all** (verified — there is not a single `-v` in it), so a
  processing node still re-downloads a non-`base` model after every `node/update.sh`. Left as-is
  deliberately: there are no nodes attached today, and the node installer's volume story is its own
  change.
- **Apple Music hides the entity you want behind `?i=` — the path id is the *album*.** The Share
  button in the Apple app always produces the album form:
  `music.apple.com/us/album/faryaad-feat-karim-fakour/305568683?i=305568690&ls`. The id in the path
  (`305568683`) is the **album**; the track is the `?i=` parameter. A parser that takes the last path
  segment therefore looks up the wrong entity, gets a `collection` row back, and tells the user
  "not supported" for a link that was a perfectly ordinary track. `apple_id()` gives `?i=` precedence
  for exactly that reason, and `&ls` (and any other junk parameter) is tolerated. The **storefront**
  (`/us/`, `/gb/`) is Apple's `intl-fa`: it stays **out of the cache key** because the id is global
  (`country=gb` returned the same track, differing only in currency/prices/`*ViewUrl`), but it is
  passed to the lookup as `&country=` so a track missing from the default store still resolves.
  Note the three `*ViewUrl` fields just echo the storefront you asked for, so they are useless for
  inferring a canonical one — don't try.
- **Apple puts the guest artist in the title and Spotify puts it in the artist list, and that
  difference silently inverts the ranking.** For «Faryaad»: Apple gives
  `trackName = "Faryaad (feat. Karim Fakour)"` with `artistName = "Anoushirvan Rohani"` — the guest
  is *only* in the title. That is not a tidiness problem. `_artist_contradiction` rejects a candidate
  only when it is **missing** a reference artist **and** claims an **extra** one; with a
  single-artist reference "missing" can never happen, so the gate that exists precisely to catch
  singer-substitution is disarmed. Measured on real candidate shapes: the wrong-singer candidate
  scored **96.94** and the correct Art Track **96.04**, i.e. the wrong one ranked first, while the
  artist component fell from 100.0 to **63.3**. Extracting the guest into the artist list restores
  the correct candidate to 106.00 and gets the wrong one **rejected outright**.
  Two more things the extraction buys, both measured: `_search_queries` goes back to producing
  **two** shapes (with the guest hidden, `arts[0] == arts[-1]` collapses it to one — and the second
  shape is the one that finds the *singer* for Iranian classical music), and the false-penalty
  channel `"(feat. Session Band)"` → `{session}` closes.
  **The title clean is surgical, not "strip the parentheses".** Only a bracket whose content *starts
  with* `feat`/`ft`/`featuring` is removed; `[Daft Punk Remix]`, `(Radio Edit)`, `(Live)` and
  `[Extended Mix]` survive and `_version_markers` still sees them — otherwise the clean would destroy
  exactly what the version penalty exists to catch. **`with` is deliberately not a feat marker**:
  it eats `(With Strings)`, an arrangement marker, and would file "Strings" as an artist.
  And **Apple is not consistent** — «Get Lucky» puts all three artists in `artistName` with a clean
  title — so both shapes are tolerated and the merge de-duplicates via `_norm`.
- **In the real dump, one track has `collectionName` byte-identical to `trackName`.** F7 (the
  remix single) names the album exactly what it names the track, so the two only diverge *after* the
  feat clean shortens the title — meaning a mix-up of one for the other is invisible until then. The
  album is deliberately **not** cleaned: it is a product name, not a track title. Pinned by a test on
  the real row.
- **Apple's explicitness has two levels and they disagree in the wild.** F8 is
  `collectionExplicitness: "explicit"` with `trackExplicitness: "notExplicit"` — a clean track on an
  explicit compilation. **Not a bug today, because `apple_resolve` reads neither**; the content gate
  rides on the YouTube download (`--match-filter` → `AgeRestricted`). If anyone ever wires an Apple-side
  signal in, it must be the **track** field, or that clean track gets flagged. A test pins both the
  divergence and the fact that the resolver's output carries no explicitness key.
- **`collectionArtistName` is the *album* artist, not the track's.** For «Get Lucky» it is
  `"Daft Punk"` against the track's three. Using it as a fallback artist silently drops the guests.
  Not hypothetical: a test asserts it, and the first version of that test was **vacuous** because the
  fixture had the feat in the title too, so extraction put the missing artists back and the sabotage
  passed. The fixture now matches the shape the operator actually measured.
- **Every iTunes key is optional — read with `.get()`, and the guard's safety must not ride on
  evaluation order.** A `collection` row has no `kind`, no `trackId`, no `trackName` (it carries
  `amgArtistId` and `copyright` instead), a real *track* row can lack `collectionArtistName`, and a
  withdrawn id returns `resultCount: 0` where `results[0]` raises `IndexError`. Measured curiosity
  worth knowing: `r["wrapperType"] == "track" and r["kind"] == "song"` does **not** raise on a
  collection row, because `and` short-circuits — but that means its safety depends on which operand
  comes first, which is not a property to leave load-bearing. Reversing the order raises `KeyError`.
- **An unsupported Apple entity must bypass the cookie-rotation branch, like `AgeRestricted` does.**
  Apple downloads the audio from YouTube, so `_cookie_platform` asks for a **YouTube** cookie; without
  its own `except D.AppleUnsupported` before the generic handler, an album link would fall into the
  rotation loop and spend one attempt per account on a URL that can never work — the "one bad URL
  burns the whole pool" failure §7 already warns about for non-cookie errors. The user gets an
  explicit «only single-track links» message instead of the pre-fix `❌ dl_failed / <code>album</code>`.
- **`engine_for` returns the platform name for match platforms, not the literal `"spotify"`.**
  Spotify's value is unchanged (`"spotify"`), so this is a no-op there; Apple gets `"apple"`.
  Consumers must test `engine in _MATCH_PLATFORMS`, never string equality — `tasks_download` does.
- **Streaming**: browser playback needs the MP4 `moov` atom up front (`-movflags +faststart`) — applied to downloaded/processed videos, not to raw user uploads. Gateway caches token→path (120 s) so seek/Range requests don't re-hit DB+getFile each time. Keep the streaming subdomain **grey-cloud on Cloudflare** (CF ToS §2.8 restricts proxying video; also adds buffering).
- **Callback 64-byte cap**: never pack large data into `CallbackData`; store in Redis, pass a token.
- **افزودنِ فیلد به یک `CallbackData`ِ موجود، دکمه‌های **در پرواز** را سرِ استقرار می‌شکند — و مقدارِ پیش‌فرضِ پایتونی نجاتش نمی‌دهد.** اندازه‌گیری‌شده روی aiogram 3.30: کلاسی با فیلدِ دومِ دارای پیش‌فرض، روی payloadِ تک‌فیلدیِ قدیمی `TypeError: Callback data 'X' takes 2 arguments but 1 were given` می‌دهد. یعنی `unpack` شکست می‌خورد → `.filter()` جور نمی‌شود → **هیچ هندلری اجرا نمی‌شود** و کاربر یک دکمهٔ چرخانِ بی‌جواب می‌بیند. غریزه می‌گوید «پیش‌فرض یعنی سازگاریِ عقب‌رو»، و این‌جا غلط است. شعاعش هر کاربری است که لحظهٔ `telabzar update` یک منوی باز روی صفحه دارد. **راهِ درست: کلاسِ تازه با پیشوندِ تازه، یا مشتق‌کردنِ همان تفکیک از حالت.** فاز C دومی را گرفت: `Lang` تک‌فیلدی ماند و «انتخابِ اول» از «تغییر از تنظیمات» با نگاه‌کردن به `user.lang` **پیش از نوشتن** جدا می‌شود.
- **زبانی که از `/langs` حذف شود کاربرانش را بی‌صدا انگلیسی می‌کند — و تا فاز C راهِ برگشتی نداشتند.** `textstore.remove_language` ردیف‌های `TextOverride` را پاک می‌کند ولی `users.lang` دست‌نخورده روی همان کد می‌ماند؛ `t()` هیچ عضویت‌سنجی‌ای نمی‌کند پس نه کرش می‌شود نه فارسی، بلکه از زنجیرهٔ fallback به **انگلیسی** می‌افتد (اجراشده، با کنترلِ مثبت). تا پیش از فاز C این تله بود نه صرفاً تخریبِ ملایم: `cmd_start` چون `user.lang` ناتهی است منوی زبان نشان نمی‌دهد، پس کاربر در انگلیسی **گیر می‌افتاد**. منوی تنظیمات همین را می‌بندد — یعنی آن منو یک قابلیتِ تزئینی نیست، تنها راهِ خروج از این حالت است. اعتبارسنجیِ per-update عمداً **ساخته نشد**: یعنی یک خواندنِ فهرستِ زبان روی هر آپدیت، برای حالتی که خودش قابلِ‌ترمیم است.
- **`language_set` عمداً بی‌مصرف است و عمداً حذف نشده.** رشتهٔ لفظیِ per-language بود («زبان روی فارسی تنظیم شد» / «Language set to English») و برای زبانی که مترجمش این کلید را جا انداخته باشد به انگلیسی می‌افتد — یعنی به کسی که اسپانیایی زده «Language set to English» می‌گفت (اجراشده). از فاز C تأیید **بصری** است: منوی بعدی به زبانِ تازه رندر می‌شود و `cq.answer()` خالی فقط چرخشِ دکمه را می‌بندد. **حذفِ کلید بررسی و رد شد** چون بسته‌های ترجمهٔ **موجود** آن را دارند و حذفش یعنی همه‌شان یک کلیدِ اضافه پیدا کنند. جایگزینِ placeholder-دار هم رد شد: `require_all_placeholders` در مسیرِ import سخت‌گیر است، پس placeholderِ تازه هر بستهٔ موجود را رد می‌کرد.
- **No Alembic**: schema evolves via idempotent `ALTER … IF NOT EXISTS` in `db.py:_MIGRATIONS`.
- **عریض‌کردنِ یک `varchar` روی Postgres رایگان است؛ باریک‌کردنش نیست — و تفاوتشان اندازه‌گیری‌شده.** روی PostgreSQL 16.13، `ALTER COLUMN … TYPE VARCHAR(n)` با nِ **بزرگ‌تر** روی جدولِ **۲۰۰٬۴۲۸ ردیفی / ۵۸ مگابایتی** **۲٫۹ میلی‌ثانیه** گرفت و `pg_relation_filenode` هم برای جدول و هم برای **ایندکسِ PK** عوض نشد — یعنی catalog-only و مستقل از تعدادِ ردیف. کنترلِ منفی روی همان جدول: **باریک**‌کردنِ همان ستون **۲۰۵۱ میلی‌ثانیه** و filenodeِ هر دو عوض شد. پس هارنس بازنویسی را می‌بیند و آن یکی واقعاً بازنویسی نمی‌کند. اجرای دوباره هم امن است (۲٫۴ ms)، که **شرطِ لازم** است چون `_MIGRATIONS` سرِ **هر** استارتِ ربات/ورکر می‌دود. کلِ `init_models()` روی یک دیتابیسِ ۱۷۳۴کاربره ۷۷ ms است. قاعدهٔ عملی: عریض‌کردن را بی‌محابا در `_MIGRATIONS` بگذار؛ برای هر `ALTER … TYPE`ی که **باریک** یا **نوع‌عوض‌کن** باشد اول filenode را بسنج.
- **`String(n)` را Postgres اعمال می‌کند و SQLite نه — پس کرانِ رشته باید در پایتون باشد.** اندازه‌گیری‌شده روی هر دو: کدِ زبانِ ۵کاراکتری روی Postgres `StringDataRightTruncation` می‌دهد و روی SQLite **پذیرفته می‌شود**. چون `tests/panel` روی SQLite می‌دود، هر گاردی که به ستون تکیه کند تستِ سبز و تولیدِ ۵۰۰ می‌دهد — همان ردهٔ «سبزِ محلی، قرمزِ تولید» §۶. `langpack.normalize_code` برای همین در پایتون گارد می‌گذارد (روی **فرمتِ** BCP 47، به‌علاوهٔ یک کرانِ طول که به عرضِ ستون گره خورده و تستِ خودش را دارد تا کدِ مرده نشود).
- **Locale parity**: every key must exist in both `locales/fa.py` and `locales/en.py`. **از ۲۰۲۶-۰۸-۱۹ گارد دارد** (`tests/test_locale_parity.py`) — پیش از آن فقط یک **اندازه‌گیریِ یک‌باره** بود («۲۱۴ کلید، صفر یک‌طرفه») و صفر assert در کلِ `tests/`، که تفاوتشان همان تفاوتِ «امروز درست است» با «فردا هم درست می‌ماند» است. **شکستش خاموش است و همین گران می‌کندش:** `langpack.TEXT_KEYS` اجتماعِ دو کاتالوگ است، پس کلیدِ یک‌طرفه از بسته حذف نمی‌شود بلکه با متنِ **زبانِ اشتباه** واردش می‌شود — اجراشده، `default_text('en', <کلیدِ فقط-فارسی>)` متنِ فارسی می‌دهد، چون زنجیره `en → FALLBACK(en) → DEFAULT(fa)` است. سه ادعا، هر سه کشف‌محور روی کلِ کاتالوگ: مجموعهٔ کلیدها (**هر دو جهت**، با نام‌بردنِ کلیدِ متخلف)، مجموعهٔ placeholderها per-key، و توالیِ تگ‌های HTML per-key. دو تای آخر ادعاهایی بودند که §۷ فقط **اندازه‌شان** را گرفته بود.
- **کلیدِ ترجمه‌نشده به انگلیسی می‌افتد، نه فارسی — و این ۲۰۲۶-۰۸-۱۹ عوض شد.** پیش از آن `CATALOG.get(lang, FA)` بود، پس یک زبانِ ۹۰٪‌ترجمه‌شده ۱۰٪ **فارسی** نشان می‌داد؛ برای مخاطبی که خطِ فارسی را نمی‌خواند این از انگلیسی بی‌فایده‌تر است. زنجیره حالا کاتالوگِ خودِ زبان → `FALLBACK` → `DEFAULT` → خودِ کلید است. **برای fa/en بی‌اثر است** (پاریتی دقیق است) و تستِ کنترل همین را پین می‌کند؛ اثرش فقط روی زبانِ افزوده است. هر چهار حلقه در `tests/test_i18n_fallback.py` جدا پین شده‌اند، چون عوض‌شدنشان نه خطا می‌دهد نه تستِ دیگری را می‌شکند — فقط زبانِ خروجی را بی‌صدا عوض می‌کند.
- **`validate()` placeholderِ **جاافتاده** را نمی‌گیرد، و برای import این یک شکاف است.** اندازه‌گیری‌شده: `extra = vfields - _fields(default_text)` فقط placeholderِ **اضافه** را رد می‌کند، پس حذفِ کاملِ `{mb}` **مجاز** است — متن سالم می‌ماند و عدد هرگز به کاربر نمی‌رسد. برای ویرایشِ دستیِ `/texts` عمدی است (ادمین می‌داند چه می‌کند) و **دست‌نخورده ماند**؛ مسیرِ import با `require_all_placeholders=True` سخت‌گیر است، چون افتادنِ یک placeholder محتمل‌ترین خطای یک مترجمِ ماشینی است و کاملاً خاموش. **و قراردادِ placeholder از متنِ *مبدأ* می‌آید نه از کاتالوگِ کد** — ادمین ممکن است متنِ فارسی را از `/texts` ساده کرده باشد، و سنجیدن در برابرِ کاتالوگ آن‌وقت یک ترجمهٔ **درست** را رد می‌کرد.
- **دو رفتارِ متفاوتِ overrideِ خراب، هر دو اندازه‌گیری‌شده.** placeholderِ غلط + call site **با** kwargs → `_fmt` می‌ترکد و `t()` بی‌صدا به پیش‌فرض برمی‌گردد. placeholderِ غلط + call site **بدونِ** kwargs → `_fmt` روی `if not kwargs` زودتر برمی‌گردد و override **عیناً با براکتِ خام** به کاربر می‌رسد (`'Cupo {nope}'`). یعنی اعتبارسنجیِ سرِ نوشتن تنها دفاع است، نه یک لایهٔ اضافه.
- **`t()` is sync & hot**: text overrides live in an in-process dict, refreshed only when the Redis `txtver` counter changes (bumped on panel edit) — checked per-update in `DataMiddleware` and per-job in the workers. Do NOT make `t()` async or read the DB on every call. Button styles (`file_card_kb`, per-op via `textstore.get_button_style`) share the same dict + `txtver` reload.
- **The panel MUST reload `textstore`**: overrides are durable in Postgres, but each process holds its own in-process dict. Long-running processes with **no** `refresh_if_stale()` hook (the panel is one) start empty after a restart. `admin_web._on_startup` therefore calls `textstore.load()`, and `texts_page`/`buttons_page` call `refresh_if_stale()` per request — otherwise the panel shows defaults after `telabzar update`, and a `/buttons` **batch save from that stale view overwrites the real overrides with defaults** (silent data loss). Any new panel page that reads overrides must refresh first.
- **Premium/custom emoji**: `<tg-emoji emoji-id=…>` in text and `icon_custom_emoji_id` on buttons require the **bot owner's account to have Telegram Premium**; button `style` (`primary`/`success`/`danger`, the only 3 colors Telegram allows) does not. Only the card op-menu (`OPS_BY_KIND` ops) is styled today. A wrong `icon_emoji_id` can make Telegram reject the whole keyboard — the panel validates it is numeric, but existence isn't checked.
- **Nodes need `is_local=False`**: co-located workers read input straight off the shared Bot API disk (`bot.get_file().file_path`), which does **not** exist on a remote machine. `bot.py` therefore flips to `is_local=False` whenever `NODE_ROLE` is set, so aiogram downloads inputs over HTTP from the (WG-reachable) Bot API and uploads outputs by multipart. A node reaches Redis/Postgres/Bot API only over the WireGuard tunnel (`NODE_*` addresses = master's WG IP); those services must listen on the tunnel. The **input seam is `tasks._localize()`** (Phase N2): it returns the disk path when it exists (master) and otherwise `bot.download_file()`s into the workdir (node) — every `run_op` input now goes through it, so `run_op` is node-safe. Output was already node-safe (all delivery is `FSInputFile` multipart). Heavy ops (`nodes.OFFLOAD_OPS`) route to `arq:queue:proc` only when a **processing** node is live; `scan` stays on the master (it needs the master-side ClamAV service), and the whisper model downloads on the node's first transcribe. If a processing node dies with jobs still queued on `arq:queue:proc`, the master's **reaper** (`nodes.reap_orphan_jobs`, run every 30 s by the main worker via `startup_master`) moves them back to `arq:queue` so they never hang — it only fires when no processing node is live, and claims each job with `zrem` before re-adding (no double-run).
- **Gateway node is a reverse proxy, not a file host**: `gateway_node.py` forwards `/dl` `/s` to the master's gateway over WG and streams the response back (Range preserved) — the file bytes still traverse master→node→client, so the master's **uplink is unchanged**; what you gain is a clean/dedicated public streaming IP (grey-cloud it on Cloudflare, keep it off the master's IP) and TLS/DDoS surface off the master. Token resolution stays on the master, so the node needs **no** DB/Bot API — only HTTP to the master gateway (`NODE_GATEWAY_URL`) + Redis for its heartbeat. Point links at it with the runtime `stream_base` setting (empty → master `public_base`). The master gateway must listen on the WG IP. Public TLS on the node (streaming subdomain cert, or CF in front) is the admin's job — inherent to running a public service. A future download-once/serve-many local cache (cut repeat WG traffic + latency) is out of scope (N4).
- **Master WG/infra auto-provisioning is host-side & needs real-server testing**: `node/master-setup.sh` runs on the **host** (root), not in a container — it installs WireGuard, generates the master key, brings up `wg0`, writes the WG/`NODE_*` vars into `.env`, applies the `docker-compose.nodes.yml` overlay (services on the WG IP), and installs the `telabzar-wg-sync` systemd timer. **WG peer management is declarative**: the panel only writes `Node` rows; the host `wg-sync` (via `node/wg-sync.sh`) fetches the desired peers from the panel's `/node/peers` (gated by `NODE_SECRET`) and rebuilds `wg0.conf` = static `[Interface]` + `nodes.render_peers(...)`, then `wg syncconf` (no tunnel drop). This keeps the admin container **unprivileged** and is self-healing. The in-container `nodes.add_peer/remove_peer` remain best-effort (they log `wg config append failed` in the sandbox — expected). Pure logic (`render_peers`, `/node/peers` auth, the overlay YAML, all `bash -n`) is unit-tested; the real `wg`/multi-machine path must be verified **on the master server**. The master gateway/services must bind the WG IP (the overlay does this); `wg0` must come up before docker (the setup adds a systemd ordering drop-in). Join token is HMAC-signed + **one-time** (Redis `njoin:{jti}`, GETDEL) + 30-min TTL; the reply includes `BOT_TOKEN` (nodes are admin-provisioned & trusted, gated by the one-time token + WG).
- **Downloads must not split across master+node** (the YouTube "alternating bot-check" bug): both the master's download-worker and a download node used to consume the **same** `arq:queue:dl`, so ARQ split jobs ~50/50 — half ran on the master's flagged datacenter IP (YouTube bot-check → fail) and half on the node's clean IP (success), i.e. every-other-download failed. Fix: the **master** download-worker consumes `arq:queue:dl:master` (compose `command:`), the **node** still consumes `arq:queue:dl` (unchanged → no node re-install), and `download._dl_queue` routes to `arq:queue:dl` only when a download node is live, else `arq:queue:dl:master`. So with a node, **every** download runs on the node's clean IP. The reaper drains `arq:queue:dl` → `arq:queue:dl:master` if the download node dies.
- **No node → the master does everything** (verify before changing routing): the master's `download-worker` handles all downloads via `arq:queue:dl:master` when no download node is live (`download._dl_queue`); heavy ops route to `arq:queue:proc` only when a processing node is live, and the reaper drains it back otherwise; stream links use `stream_base` **only when a `gateway` node is online** (`ops._link_base` → `role_online("gateway")`), else the master's `public_base`. So a missing/dead node never breaks a path — it falls back to the master. The **reaper** (`nodes.reap_orphan_jobs`, `_REAP_MAP`) covers both offload queues: `arq:queue:proc`→`arq:queue` and `arq:queue:dl`→`arq:queue:dl:master`.
- **You cannot subclass an ARQ settings class — arq reads `__dict__`, which skips inheritance.** `arq.worker.get_kwargs` does `settings_cls.__dict__` (`arq/worker.py:889` in 0.28) and a class's `__dict__` contains **only its own** attributes. So `class MasterDownloadWorkerSettings(DownloadWorkerSettings)` handed arq exactly one key — `queue_name` — and nothing else: the worker died on `at least one function or cron_job must be registered` (`arq/worker.py:236`) in a crash loop and **no download ran at all**. Two things make this nasty. First, it is **silent by design**: the subclass looks correct, `MasterDownloadWorkerSettings.functions` works fine from Python, and only arq's `__dict__` read sees the gap. Second, `functions` is not the worst loss — **`redis_settings` disappears too**, so patching only `functions` yields a worker that starts happily and connects to `localhost:6379` instead of ours. `ProcessingWorkerSettings` (from Phase N2, `c445c63`) had the identical bug and therefore the **processing-node role never worked since the day it shipped**; the download bug arrived later (`c3dd2b0`) and stayed hidden while nodes existed, because jobs went to the node's queue — deleting the nodes moved them to `arq:queue:dl:master`, where no consumer existed. **No job was stranded by the processing half of this, and the reason is worth keeping:** arq raises inside `Worker.__init__` (`arq/worker.py:236`, within 187-305), i.e. *before* `on_startup` — and `on_startup` is what spawns the node heartbeat (`worker.py:39-40` → `_node_heartbeat`). No heartbeat means `nodes.role_online(redis, "processing")` is False, which is the **same gate** that `ops._op_queue` (`routers/ops.py:150-157`) consults before routing anything to `arq:queue:proc`. So a processing worker that cannot start also cannot attract work: the ops stayed on the master's `arq:queue` the whole time. The reaper is the second, independent safety net — `_REAP_MAP` (`nodes.py:181-184`) covers **both** offload queues, and it too fires only when the role is offline, so anything that had landed on `arq:queue:proc` would have been drained back within 30 s. Fix: the `_flatten_settings` decorator in `app/worker.py` copies inherited attributes into the subclass's own `__dict__` (its own values still win). **Every** ARQ settings subclass must carry it; `tests/test_worker_settings.py` auto-discovers each `*WorkerSettings` in the module and fails if one is missing. The same shape of bug — a rule enforced by a hand-maintained list — is why `tests/test_ssrf.py` discovers the direct-engine sessions instead of naming them.
- **A killed job must kill its subprocess — `finally` closing the watcher is not enough.** `_run` killed ffmpeg on the cancel button and on timeout, but on `CancelledError` (ARQ's `job_timeout`, worker shutdown) it only cancelled the watcher task and left the process running, burning CPU until it finished on its own. Reproduced directly: one live ffmpeg survives `task.cancel()`. An `except BaseException` branch now kills and re-raises. It deliberately does **not** `await proc.wait()` — on the cancellation path that await can take another `CancelledError` and undo the fix; SIGKILL ends the process and asyncio's child watcher reaps it, and a live process is what matters, not a momentary zombie.
- **`await`ing a helper task you just cancelled can swallow *your own* cancellation.** After `ticker.cancel()`, `await ticker` raises `CancelledError` for two indistinguishable reasons: the task you cancelled, or the job being cancelled around you. Both sites swallowed both — `except (asyncio.CancelledError, Exception)` in `tasks.py`, and the broader `except BaseException` in `tasks_download`, which also ate `SystemExit`. Measured, and it corrected the first reading: in the common case the cancel lands inside the work itself, `finally` merely passes through, and the old forms propagate fine. It is lost only when the cancel arrives **while awaiting the ticker** — a real window, since the ticker makes a Telegram HTTP call every few seconds and a worker shutdown cancels every running job at once. `processing.stop_task()` uses `Task.cancelling()` (3.11+) to tell them apart. Two alternatives were tried and rejected: `gather(..., return_exceptions=True)` swallows it too, and cancelling without awaiting does not help either.
- **Seek before `-i`, and move `-to` with it or the cut length is wrong.** `trim_video` had `-ss`/`-to` *after* `-i` (output seeking), so ffmpeg decoded and discarded every frame before `start`; the cost grew with how far into the file the cut began. Measured on a 180 s source cutting [170,174]: **1.47 s → 0.30 s**, with the first output frame **bit-identical** (PSNR `inf`) — modern ffmpeg decodes from the keyframe before `start` and drops the extra frames, so input seeking is fast *and* accurate when re-encoding. The trap is that moving only `-ss` is worse than not fixing it: with `-ss` before `-i`, input timestamps reset to zero, so a trailing `-to end` becomes an **output** option meaning "stop at `end` seconds of output" — a [3,7] cut yields **7 s instead of 4**. Both must precede `-i`, which is the shape `trim_audio` already had. Note this makes the two command lists byte-identical, so a `str.replace(..., 1)` aimed at one of them silently edits the other — that is exactly how a sabotage check in testing produced a false pass.
- **An orphaned yt-dlp does not just idle — it keeps downloading, and it spends the one resource we cannot buy back.** `_run_dl` had the identical `except BaseException` gap `_run` had (only `asyncio.TimeoutError` was caught), so on ARQ's `job_timeout` or a worker shutdown the yt-dlp child survived. The ffmpeg version of this bug burns CPU; this one is worse in kind. The orphan **continues the download** against the cookie account it was given, so it keeps consuming that account's hourly budget (`cookies.hourly_cap`) and keeps exposing the session to the platform — and it does so **invisibly**, because the job that owned it is dead: `mark_ok`/`mark_fail`/`note_spend` are never reached, so the pool's own bookkeeping shows nothing. The session pool is the most expensive operational resource in this project (see the pacing/warm-up bullets above), and this path burned it with no record. Fixed the same way as `_run` — kill and re-raise, deliberately without `await proc.wait()`. When adding any new subprocess that spends a cookie account, the `except BaseException` branch is not optional.
- **One cancel mechanism, not two: `processing.start_cancel_watcher` is shared by ffmpeg and yt-dlp.** `_run` (ffmpeg) and `downloader._run_dl` (yt-dlp/gallery-dl) both need "poll `cancel()` on a timer and kill the child", and they had drifted into two different answers — `_run` polled every `_CANCEL_POLL` on a separate task, while `_run_dl` checked once per stdout line. Both failure modes were real and symmetric: **too rarely** (a stalled yt-dlp emits no lines, so `async for` blocks and the cancel button did nothing until the 3000 s timeout) and **too often** (`--newline` plus `--concurrent-fragments 4` produces tens of lines a second, each one a Redis `EXISTS` — and on a download node that is a WireGuard round trip). Both now call the same helper. `downloader` imports `processing` **lazily inside the function**, matching the existing `_ffprobe_video` precedent — the dl-worker image does ship Pillow (`requirements-worker-dl.txt`), so a module-level import would work today, but keeping it lazy avoids welding this module's import graph to PIL. Same rule as `remove_cookie_file`: two hand-written copies of one rule will diverge.
- **و همان قاعده برای «یتیم نگذار» — که تا ۲۰۲۶-۰۸-۱۷ چهار کپیِ دست‌نویس بود و **دو تایش رفعِ قبلی را نگرفته بودند**.** `processing.kill_orphan` حالا تنها پیاده‌سازیِ آن است و هر چهار زیرفرایند از آن رد می‌شوند.
  **و همین توضیح می‌دهد چرا رفعِ قبلی ناقص ماند، که درسِ اصلیِ این بولت است.** رفعِ ۲-۲ (`_run`) و رفعِ `_run_dl` هرکدام **یک نقطه** را درست کردند، چون قاعده در همان نقطه نوشته شده بود؛ هیچ‌چیز نمی‌پرسید «این قاعده جای دیگری هم هست؟». با چهار کپیِ مستقل، «رفع شد» معنیِ **سراسری** ندارد و کسی هم متوجه نمی‌شود، چون سه کپیِ دیگر هیچ ارجاعی به رفع ندارند که کهنه به‌نظر برسد. یعنی وضعیتِ «۲ از ۴ رفع‌شده» از بیرون دقیقاً شبیهِ «رفع‌شده» است. و دقیقاً همین وضع بود که **کپیِ پنجم را دعوت می‌کرد**: نفرِ بعدی که زیرفرایندِ تازه‌ای اضافه کند، الگو را از نزدیک‌ترین همسایه کپی می‌کند و شانسی تعیین می‌کند نسخهٔ رفع‌شده را برمی‌دارد یا نسخهٔ بی‌رفع را. قاعدهٔ عام: **یک قاعدهٔ ایمنی که در N نقطه دست‌نویس شده، N نقطهٔ رفع می‌خواهد و هیچ‌کدام دیگری را خبر نمی‌کند** — پس استخراجش کارِ نظافتی نیست، تنها چیزی است که «رفع شد» را قابلِ اتکا می‌کند. هم‌ردهٔ `remove_cookie_file` و `_search_queries`، با این تفاوت که آن دو **واگراییِ رفتاری** دادند و این یکی **واگراییِ پوشش**.
  دو مسیری که جا مانده بودند هر دو yt-dlp اجرا می‌کنند و فقط `asyncio.TimeoutError` می‌گرفتند: **`downloader.probe`** (فازِ probe — و چون `dl_ux_youtube = probe` در تولید ست است، **هر** لینکِ یوتیوب از آن رد می‌شود) و **`downloader._yt_search_candidates`** (مسیرِ تطبیقِ اسپاتیفای/اپل، تا `match_max_tracks`=۲۰ بار × تا دو شکلِ کوئری در **یک** جاب). محرک `job_timeout` نیست، **خاموشیِ ورکر** است — یعنی هر `telabzar update`. و هر دو `--cookies` می‌فرستند (`_common_flags` برای probe، و شاخهٔ پرچم‌سازیِ خودش برای جست‌وجو — دو مسیرِ جدا، پس دو تستِ جدا)، پس یتیمشان همان چیزی را می‌سوزاند که یتیمِ `_run_dl` می‌سوزاند. **`_yt_search_candidates` عمداً `cancel` نگرفت و آن تغییرِ جداست:** رفعِ یتیم به آن نیازی ندارد (`except BaseException` مستقل از `cancel` است)، و افزودنش دکمهٔ لغو را حینِ «در حالِ تطبیق» **درست نمی‌کند** — هزینهٔ غالبِ `_gather_candidates` مالِ `_ytmusic_search` است که در `asyncio.to_thread` می‌دود و **اصلاً لغوشدنی نیست** (اجراشده: بعد از `task.cancel()` خودِ thread تا آخر ادامه داد). ضمناً `_yt_search_candidates` پشتِ گیتِ `len(cands) < 3` است، پس با `match_source=ytmusic` (پیش‌فرض) نادر است و عددِ «تا ۴۰ زیرفرایند» عمدتاً مالِ `match_source=youtube` یا کاتالوگِ کم‌عمق است.
- **`_run`'s cancel must not ride on the progress reader.** The cancel check lived inside the `-progress` parser, and `use_prog` requires *both* `progress` and `duration`; every call without them ran to completion no matter what the user pressed. That silently disabled the cancel button for the longest phase of `concat_videos` — its normalisation loop re-encodes every input and passes `cancel` but no progress. A separate watcher task now polls `cancel()` every `_CANCEL_POLL` seconds in **both** branches and is cancelled in `finally`, the same discipline the `dl_active` keepalive needs. Fixing `_run` alone was not enough: `mute_video` and `write_audio_metadata` never accepted a `cancel` argument at all, so they also had to take one and be passed `cancel=cancel` from `_do_op`.
- **A timeout is not an encoder failure — don't let it trigger a second full encode.** `compress_video` fell back from nvenc to x264 on `except RuntimeError`, and `_run` reported a timeout as exactly that. So an nvenc encode that ran out of time started a *complete* x264 encode, and the two together blew past ARQ's `job_timeout`. `ProcessingTimeout` (a **subclass** of `RuntimeError`, so every other `except RuntimeError` behaves exactly as before) is now re-raised ahead of the fallback branch. There are **two** such sites, not one — `compress_video` and `compress_video_tiny` — and they are easy to fix singly and forget.
- **Authorization belongs in the lookup, not in the handlers.** No handler in `routers/ops.py` ever compared `File.owner_id` to the acting user — 41 call sites did `get_file_by_ref(session, ref)` and trusted the `ref`. The fix puts the rule inside `crud.get_file_by_ref(session, ref, user)`, which now filters on `owner_id` and returns `None` when the user is not the owner; the ~41 call sites only pass `user`. Two properties make this work and are worth preserving: every handler **already** handled `file is None` (`await cq.answer(); return`), so the denial path needed no new branches anywhere; and `user` is a **required** parameter whose `None` means *deny*, not *skip* — a default of `None` would turn a forgotten argument into a silent authorization bypass, which is the exact failure this closes. `tests/test_ownership.py` discovers the call sites by AST and fails if any passes fewer than three arguments, so the next handler cannot quietly opt out. **`ref` being unguessable was never the defence:** it is 8 random chars (`routers/files.py:_new_ref`), but any leak — a log line, a forwarded card, a group chat — used to hand over every op on that file including `op_link`, which mints a public `/dl` URL. And one path needed no guessing at all: `op_cancel_job` took `Job.id`, a **sequential integer**, so counting 1, 2, 3… cancelled other users' jobs; it now checks ownership through `Job.file_id → File.owner_id` (`crud.get_owned_job`).
- **`7z x` already neutralises archive path attacks — the guard after it is a filter, not a defence.** `archive_extract` (`processing.py`) checks extracted paths *after* `7z` has run, so it can only decide what to return, never what gets written. That is acceptable only because the extractor itself is safe, which was verified against 7-Zip 23.01 rather than assumed: `../../x` lands inside the output dir, an absolute `/abs/x` is rebased under it, and symlink entries in both zip and tar are materialised as plain directories, leaving the target untouched. `tests/test_phase2a.py` pins exactly those behaviours, so swapping the binary or moving to `zipfile`/`tarfile` fails loudly instead of silently removing the real protection. The guard itself did have a genuine flaw: `realpath(p).startswith(real_ex)` is a **string** prefix, so a sibling `<outdir>/exfil` satisfies `<outdir>/ex`; it now compares against `real_ex + os.sep`. Not exploitable today — `os.walk` never leaves `exdir` — but the check was simply wrong as written.
- **A secret in a query string is a secret in every log.** `/node/peers` accepted `?key=<NODE_SECRET>`, which lands in the panel's access log and any intermediate proxy; it now reads only the `X-Node-Key` header (which the handler already supported). The half that matters for the next person: **this endpoint has exactly one client**, the host-side `node/wg-sync.sh`, and closing the server without switching the client would mean peers silently stop syncing the next time a node is added — a failure with no error and no test to catch it. Both sides move in the same commit, and a repo-wide test fails if `node/peers?key=` reappears anywhere under `app/` or `node/`. Note `node/install.sh` is **not** a client here: it POSTs its one-time join token in the body to `/node/join`, a different endpoint with a different mechanism.
- **Two hand-written copies of a safety check will diverge; the bot's copy had already lost.** Deleting a cookie file existed twice: the panel validated the name and confirmed the resolved path stayed inside `cookies_dir`, while the Telegram-side twin in `routers/admin.py` did `os.remove(os.path.join(settings.cookies_dir, name))` with neither guard. Not exploitable — `name` came from a system-written Redis key (`tasks_download.py` → `cktok:`) and the handler is admin-gated — but the divergence is the point. Both now call `cookies.remove_cookie_file()`. It lives in `cookies.py` and not in the panel because **`routers/admin.py` cannot import `admin_web`**: the bot image has no jinja2 or cryptography, so that import would break the bot at startup. This is the same constraint that put the cookie-paste helpers and `dl_active` where they are — anything both the bot and the panel need belongs in a module with no panel-only dependencies.
- **A cache keyed by chat id and never swept is a leak.** `ops._collect_locks` mapped `chat_id → asyncio.Lock` in a plain dict, so every chat that ever used a collection flow (zip/merge/img_pdf/vjoin) left a lock behind for the life of the process — which runs for months. It is now a `WeakValueDictionary`: the lock survives exactly as long as someone holds it. The correctness argument is what makes this safe rather than clever — any two genuinely concurrent users overlap, and the one inside `async with _collect_lock(...)` holds a strong reference for the whole block, so a contending caller always gets the *same* object. If the entry has been collected, nobody held the lock, and creating a fresh one cannot lose a race. There is no `await` between the `get` and the assignment, so the create path is atomic under asyncio.
- **`telabzar update` throws away local changes to tracked files — deploy local code with `telabzar up`.** The generated CLI's `update` runs `git fetch origin main && git checkout -f -B main origin/main` **before** `compose up -d --build` (`install.sh:185`). `-f` discards working-tree modifications to tracked files and `-B main` resets the branch to `origin/main`, so anything not pushed is gone — and because the discard happens before the build, the rebuilt image contains the *old* code while the edit appears to have simply "not worked". A hotfix patched straight onto the master was silently erased three times this way, and the resulting symptoms misdirected the diagnosis. `telabzar up` (`install.sh:180`) is plain `compose up -d --build` with **no** git operation, so it builds whatever is on disk. Rule: `update` = deploy what is merged on `origin/main`; `up` = deploy what is on this disk. Anything worth keeping must be committed and pushed, not left in the working tree.

## 8. Reference Docs
- `docs/telegram-api.md` — recent Telegram Bot API changelog (10.0→10.2), project-relevant, with sources.
- `docs/ADMIN_PANEL.md` — admin panel / runtime settings notes (pre-existing).

## Open Questions
- **پنج گروهِ CSSِ مرده — ثبت شد، عمداً حذف نشد (۲۰۲۶-۰۸-۱۹، تصمیمِ اپراتور).**
  اندازه‌گیری‌شده با رندرِ هر ۹ صفحهٔ GET + `/login` و تفکیکِ «تعریف‌شده منهای
  رندرشده»: `.bar-row` (`panel.css` — قواعدِ سه‌گانه)، `.hist` (+`.hist .b`,
  `i`, `em`, `span`)، `.kpi2` (+سه قاعده)، `.kpis` (+media query)، و
  `.nav a.soon`. به‌علاوهٔ **دو توکنِ مرده**: `--card` و `--red`، هر دو صفر
  استفاده، در حالی که `#fff` بیست‌وچهار بار و `#dc2626` مستقیم نوشته شده‌اند.
  **چرا حذف نشد:** حذفشان بایتِ `<style>` را عوض می‌کند و از اثباتِ
  بایت‌یکسانِ فاز بیرون می‌افتد — یعنی تنها چیزی که کلِ ارزشِ آن فاز رویش سوار
  است. و هر پنج‌تا در فازِ پوسته به‌هرحال دست‌کاری می‌شوند.
  **و جهتِ سنجش ناسالم است، این را هرکس ادامه می‌دهد باید بداند:** رندر فقط
  *حضور* را اثبات می‌کند نه *غیاب*. اجرای خام ۱۹ نامزد داد که ۱۴تایش غلط بود —
  `.dragging` را **JS** می‌گذارد (`buttons.html`)، `.woff2` اصلاً کلاس نیست
  (از `url('…Vazirmatn.woff2')` می‌آید و آرتیفکتِ استخراج‌کننده است)، و
  `.bad`/`.saved`/`.sent`/`.empty`/`.unk`/`.cmd`/`.ed`/`.tx-err`/`.hid`/
  `.muted`/`.tag2`/`.up` همه **شرطی**‌اند نه مرده. حذف بر پایهٔ خروجیِ خامِ آن
  تفکیک، شاخهٔ زنده را می‌کشد.
- **قراردادِ کیبورد **هشت** کپیِ دست‌نویس بینِ JS و پایتون دارد، نه دو تا —
  ثبت شد، دست نخورد (۲۰۲۶-۰۸-۱۹).** پیش‌نمایشِ زندهٔ `/buttons` یک پیاده‌سازیِ
  **دومِ کاملِ** همان قرارداد است: الگوریتمِ بسته‌بندیِ ردیف (`buttons.html`
  اسکریپت ↔ `keyboards._rows_from_widths`)، نگاشتِ عرض→ظرفیت (↔
  `keyboards._WIDTH_CAP`)، پیش‌فرضِ عرضِ ناشناخته `third` (↔ `keyboards.py` و
  `textstore.py`)، نگاشتِ سبک→هگز (↔ `admin_web._STYLE_HEX`)، واژگانِ
  `primary/success/danger` (↔ `textstore._BUTTON_STYLES`)، واژگانِ
  `full/half/third` (↔ `textstore.BUTTON_WIDTHS`)، «دکمهٔ بستن همیشه ردیفِ
  کامل» (↔ `keyboards.py`)، و «پنهان‌ها پیش از بسته‌بندی حذف» (↔ `admin_web`).
  سندِ بازطراحی فقط **یکی** از این هشت را دیده بود. امروز صفر اختلاف دارند
  (سندِ خودش روی ۱۰۹۳ دنباله سنجیده)، یعنی دقیقاً وضعیتِ «امروز یکی‌اند، فردا
  نه» — و **هیچ تستی دو طرف را گره نمی‌زند**. هم‌ردهٔ `remove_cookie_file` و
  `_search_queries` و `kill_orphan`، با این تفاوت که هشت‌برابر است.
- **برداشتنِ `script-src 'unsafe-inline'` هزینه‌اش ۸ نقطه در ۵ قالب است، نه
  یکی.** کامنتِ CSP این را دست‌کم گرفته بود و ۲۰۲۶-۰۸-۱۹ تصحیح شد. علاوه بر
  بلوکِ `<script>`ِ `buttons.html` (۴۸ خط)، **۷ هندلرِ رویدادِ درون‌خطی** هست:
  دو `onsubmit` و دو `onclick` در `cookies.html`، یک `onchange` در
  `texts.html`، یک `onchange` در `buttons.html`، و یک `onsubmit` در
  `nodes.html`. ضمناً آن بلوک **قالب‌شده** است (`{{ close_label|tojson }}`)، پس
  فایلِ استاتیک‌شدنش یک `data-*` هم لازم دارد.
- **`*{…font-family:…}` بلوکه‌کنندهٔ کلِ بُعدِ فونت است.** سلکتورِ سراسری در
  `panel.css` فونت را روی **هر عنصر** ست می‌کند، پس یک قاعدهٔ `body{font-family:…}`
  در فایلِ پوسته **هیچ اثری ندارد** (در Chromiumِ واقعی اندازه‌گیری شد). باید به
  `var(--font-ui)` تبدیل شود وگرنه هیچ پوسته‌ای نمی‌تواند فونت را عوض کند.
- **`999px` و `50%` شکل‌اند نه مقیاس.** از ۱۴ مقدارِ متمایزِ `border-radius`،
  این دو معنیِ «قرص» و «دایره» می‌دهند (`.pill`, `.tg`, `.meter`, `.dot`,
  `.tg::after`). یک پوستهٔ `radius: 0` که همه را یک‌کاسه کند، قرص و دایره را
  نابود می‌کند — توکنِ جدا می‌خواهند.
- **`.nav a.on{box-shadow:inset 3px 0 0 …}` تنها نشانگرِ آیتمِ فعالِ منوست.**
  از ۸ `box-shadow`، سه‌تا **معنایی**‌اند نه تزئینی. یک پوستهٔ `--shadow:none`
  بی‌صدا ناوبری را کور می‌کند: کاربر دیگر نمی‌بیند کدام صفحه باز است.
- **عددِ تاریخیِ یکپارچهٔ «کارِ انجام‌شده» وجود ندارد، چون دانلودها ردیفِ `Job`
  نمی‌سازند. برچسب‌گذاری شد، ساخته نشد (۲۰۲۶-۰۸-۱۸).** شرحِ خودِ شکاف در §۷
  است. سه گزینه با هزینه‌شان سنجیده شد و اپراتور **«پ»** را گرفت (برچسبِ صریح
  روی کارت‌های jobs-محور)، به این استدلال که «مسئله گمراهی است نه نبودِ عدد».
  دو گزینهٔ دیگر برای روزی که واقعاً عددِ یکپارچه لازم شود:

  | گزینه | کار | هزینه | چه چیزی نمی‌دهد |
  |---|---|---|---|
  | **الف — `Job` برای دانلودها** | `Job.file_id` یک FKِ **NOT NULL** است (`models.py`)، پس مهاجرتِ nullable + نوشتن در `run_download` | مهاجرتِ اسکیما · تغییر در مسیرِ داغِ دانلود · `tasks_download` روی نودِ دانلود می‌دود ⇒ `node/update.sh` هم لازم می‌شود | دادهٔ **گذشته** را نمی‌سازد؛ و بدونِ nullable شکستِ دانلود (که اصلاً File ندارد) هرگز شمرده نمی‌شود — یعنی همان چیزی که بیشتر از همه لازم است |
  | **ب — منبعِ کارت‌ها عوض شود** | نرخ از `dlstat`، حجم از `File.platform` | `dlstat` فقط **دو روز** TTL دارد و per-user/مدت ندارد | بازه‌های ۷/۳۰/کلِ صفحهٔ آمار ساختنی نیست |

  اگر روزی «الف» ساخته شد، `File.platform` (پوششِ اندازه‌گیری‌شده ۳۰۷۷ از ۳۲۰۴
  ≈ ۹۶٪، اولین برچسب ۲۵ جولای ۲۰۲۶) تنها منبعِ **تاریخیِ** per-platform است و
  فقط موفقیت‌ها را دارد؛ شکست‌ها هیچ ردِ ماندگاری ندارند.
- **جاب‌های گیرکرده برای همیشه «در صف» می‌مانند — ۱۷ آگوست ۱ تا بود، ۱۸ آگوست ۳ تا.
  رفع نشد؛ علتش اما دیگر حدس نیست و **به فازِ probe ربطی ندارد**.**
  **تصحیح روی نسخهٔ قبلیِ همین ورودی (قاعدهٔ ۵ — کد حقیقت است):** نوشته بود
  `s["queued"]` صرفاً `Job.status == "queued"` را می‌شمارد. کد
  (`admin_web.py`, ساختِ `s["queued"]`) مقدارِ **`queued + running`** است، پس
  جابِ **نیمه‌کاره** هم در همان عدد است — که مهم است، چون شایع‌ترین حالتِ
  گیرکردن دقیقاً `running` است نه `queued`.
  **علت، ساختاری:** `finished_at` فقط در دو نقطه نوشته می‌شود — خروجِ زودهنگامِ
  «فایل پیدا نشد» و `finally`ِ `run_op`. `finally` روی SIGKILL اجرا نمی‌شود، پس
  ورکری که بینِ `job.status = "running"` و آن `finally` کشته شود ردیف را برای
  همیشه با `running` + `finished_at = NULL` جا می‌گذارد؛ و جابی که هرگز برداشته
  نشود با `queued` می‌ماند. هیچ‌چیز اینها را جمع نمی‌کند: تنها نویسنده‌های
  `status` همان‌هایی‌اند که داخلِ `run_op` برای همان `job_id`اند، و هیچ کوئری‌ای
  بر اساسِ سن اسکن نمی‌کند. رشدِ ۱ → ۳ در دو روز با دو ری‌استارتِ کانتینرِ ورکر
  (`telabzar update`) می‌خواند.
  **ربطش به probe: هیچ — و این ساختاری اثبات می‌شود نه استنباطی.** ردیفِ `Job`
  فقط در `routers/ops.py` ساخته می‌شود (دو نقطه) و `tasks_download` هیچ‌وقت
  نمی‌سازد. پس هر جابِ گیرکرده یک **عملیاتِ سمتِ آپلود** است
  (compress/convert/trim/…)، نه دانلود و قطعاً نه probe.
  **یک احتمالِ دوم — حدس، اجرا نشده:** همان `finally` خودش
  `await session.commit()` دارد، و awaitِ داخلِ `finally` روی مسیرِ لغو می‌تواند
  دوباره لغو شود؛ اگر چنین باشد `job_timeout`ِ ARQ هم ردیف را جا می‌گذارد، نه
  فقط مرگِ ناگهانی. تأیید نشد — همان ردهٔ درسِ ۲-۷ در §۷ («awaitِ تسکِ کمکی
  می‌تواند لغوِ خودت را ببلعد»).
  به‌مرور به نویزِ دائمی تبدیل می‌شود («همیشه یکی هست» = «هیچ‌وقت نگاهش نکن»)،
  و دقیقاً همان چیزی را نشان می‌دهد که `/health` باید بگیرد: جابی که سنش از هر
  `job_timeout`ی گذشته. رفعش دو نیمه دارد — یک کارت/شمارنده بر اساسِ
  `created_at` کهنه، و تصمیم دربارهٔ اینکه چنین جابی `failed` علامت بخورد یا
  دست‌نخورده بماند.
- ~~**ربات فایلی را می‌پذیرد که نمی‌تواند خروجی‌اش را پس بدهد:**~~ **بسته شد ۲۰۲۶-۰۸-۱۸.** گاردِ بعد-از-تولید در `tasks.run_op` نشست (`_outgoing_paths` + `_too_big_to_send`، پیش از کلِ زنجیرهٔ تحویل). جزئیات در §۷. **سه تصحیح روی متنِ زیر که با اجرا معلوم شدند و برای هرکسی که این تاریخ را می‌خواند مهم‌اند:** (الف) بندِ **(۳)** غلط بود — `_vjoin_cap_mb()` با پیش‌فرض مقدارِ **۲۰۰۰** می‌دهد نه بی‌کران (اجراشده)، چون `_max_mb()` برابرِ `max_file_mb` است که پیش‌فرضش ۲۰۰۰ است؛ آنچه #۱۲۲ عوض کرد نبودِ **کرانِ `BOUNDS`** برای آن کلید است، پس لبه **نهفته** است و فقط وقتی مسلح می‌شود که ادمین `max_file_mb` را بالای ۲۰۰۰ ببرد. (ب) چیزی که **امروز با پیش‌فرض** به پرتگاه می‌خورد vjoin نیست، `rename` و `zip_many` است — چون `_too_large` هفت هندلر را گیت می‌کند و این‌ها را نمی‌کند (فهرست در §۷). (پ) رفع «یک گارد + یک رشتهٔ locale» نبود: چهار شاخهٔ تحویل وجود دارد و **دو تایشان** (`spawn`, `files`) شکستِ ارسال را به `done` + برچسبِ changelog ترجمه می‌کردند، یعنی موفقیتِ کاذب. متنِ اصلی برای تاریخ نگه داشته شد:

  **ربات فایلی را می‌پذیرد که نمی‌تواند خروجی‌اش را پس بدهد — هیچ گاردی نیست و پیامِ روشنی هم نمی‌آید.** `--local` دانلود را بی‌سقف می‌کند، پس کاربر می‌تواند ۳٫۹ گیگابایت بفرستد و کارت بگیرد (اندازه‌گیریِ تولید: ۴۴ ردیفِ بالای ۲۰۰۰ مگ در جدولِ `files`). ولی **هر عملیاتی که خروجیِ تازه می‌سازد** — `compress`, `convert`, `trim`, `zip`, `vjoin`, … — نتیجه را با `FSInputFile` آپلود می‌کند و آپلود سقفِ **۲۰۰۰ مگابایتی** دارد. اگر خروجی از آن رد شود، کار تمام می‌شود و بعد **در ارسال** می‌شکند: کاربر وقتِ پردازش را داده و یک خطای خام می‌گیرد، نه یک «این فایل بزرگ‌تر از آن است که بتوانم برگردانم». هیچ‌جا این را از قبل چک نمی‌کند. سه نکتهٔ لازم برای هرکسی که بسازدش. **(۱)** چکِ ورودی کافی نیست، چون رابطهٔ ورودی→خروجی به op بستگی دارد: `compress` کوچک می‌کند، `zip` روی مدیای فشرده تقریباً هم‌اندازه می‌ماند، و `convert` می‌تواند **بزرگ‌تر** کند. **(۲)** تنها نقطهٔ قطعی، **بعد از** تولید و **پیش از** ارسال است (همان جایی که `tasks_download` برای دانلود دارد: «چکِ قطعیِ حجم روی دیسک قبل از آپلود»)، پس رفعِ درست یک گاردِ هم‌شکل در `tasks.run_op` است به‌علاوهٔ یک رشتهٔ locale. **(۳)** یک تعاملِ ظریف که با همین کار وارد شد: `vjoin_max_mb = 0` (پیش‌فرض) به `_max_mb()` برمی‌گردد، و حالا که `max_file_mb` می‌تواند از ۲۰۰۰ رد شود، پیکربندیِ پیش‌فرضِ چسباندن یک سقفِ **بی‌کران** به ارث می‌برد — یعنی این مسیر از بقیه زودتر به آن می‌خورد. **ثبت شد، ساخته نشد** (رفتارِ امروز است، نه رگرسیونِ این PR).
- **`zip`/`merge`/`img_pdf` هیچ سقفِ ورودی ندارند — فقط `vjoin` دارد. ثبت شد، ساخته نشد (۲۰۲۶-۰۸-۱۸).** `collect_recv` مقدارِ `cap_mb` را فقط `if purpose == "vjoin"` می‌سازد، پس زیپِ سه فایلِ ۸۰۰ مگی بی‌مانع جمع می‌شود. **عمداً در همان PRِ گاردِ آپلود ساخته نشد** و دلیلش تصمیمِ اپراتور بود: گاردِ بعد-از-تولید روی **خروجی** است نه روی نوعِ عملیات، پس همین حالا این سه را هم می‌گیرد و یک سقفِ ورودیِ جدا کارِ تکراری است. آنچه سقفِ ورودی **اضافه** می‌کند فقط زمان‌بندیِ پیام است: کاربر به‌جای اینکه بعد از زیپ‌شدنِ ۲٫۴ گیگ رد شود، سرِ افزودنِ فایلِ سوم می‌فهمد. بعد از مستقرشدنِ گاردِ اصلی دوباره نگاه شود که آیا این تفاوت در عمل آزاردهنده هست یا نه.
- **`dl_max_size_mb = 0` گاردِ حجمِ مسیرِ دانلود را کاملاً خاموش می‌کند. ثبت شد، ساخته نشد (۲۰۲۶-۰۸-۱۸).** شرط `if max_mb and total > max_mb * 1024 * 1024` است، پس صفر یعنی «بی‌سقف» و همان پرتگاهِ آپلود در مسیرِ دانلود باز می‌شود. **امروز فعال نیست**: پیش‌فرض ۲۰۰۰ است و `BOUNDS` هم سقفش را ۲۰۰۰ بسته، پس ادمین فقط می‌تواند پایین‌تر بیاورد یا صفر کند. باگِ واقعی و جدایی است ولی به پرتگاهِ `run_op` ربطی ندارد؛ رفعش یک خط است (سقفِ فیزیکی بی‌قیدوشرط شود، جدا از سقفِ سیاستی) و باید با شواهدِ خودش تصمیم گرفته شود نه سوارِ این کار.
- **`rename` روی فایلِ بالای ۲۰۰۰ مگ هرگز نمی‌تواند موفق شود — و این نیمهٔ گمشدهٔ won't-fixِ «rename کلِ فایل را دوباره آپلود می‌کند» است.** آن ورودی (۲۰۲۶-۰۸-۱۱) درست ثابت کرد که نام به بخشِ حاملِ بایت جوش خورده و بنابراین آپلود اجتناب‌ناپذیر است، ولی نتیجه‌اش را کامل نگرفت: برای فایلی که از سقفِ آپلود بزرگ‌تر است، «اجتناب‌ناپذیر» یعنی **همیشه شکست**، نه «کند». `_do_op` مقدارِ `{"path": inpath}` برمی‌گرداند، پس گاردِ تازه دقیقاً همان حجمِ ورودی را می‌سنجد و پیشِ‌رو رد می‌کند. از ۲۰۲۶-۰۸-۱۸ کاربر پیامِ روشن می‌گیرد به‌جای خطای خام بعد از یک آپلودِ ۳٫۹ گیگیِ محکوم‌به‌شکست.
- **Roles:** the plan hypothesized `owner`/`reseller` tiers; **code has none** — only admin (env) vs user, plus `is_blocked`, and `User.role` is unused. Is a multi-tier/reseller hierarchy intended-but-unbuilt (should this file track it as a gap), or is the two-tier model final?
- ~~**Phase-3 item 2 — "rename re-uploads the whole file":**~~ **closed 2026-08-11 as won't-fix — this is a
  platform limitation, not our bug.** Proved from the wire format rather than from documentation, because
  the docs are ambiguous and `core.telegram.org` is unreachable from the dev sandbox. Building the actual
  multipart body aiogram sends: with `FSInputFile(path, filename="X")` there are **three** parts and the
  filename lives in the metadata of the one that carries bytes —
  `{'name': 'yZQ7…', 'filename': 'X'} | carries_bytes: True`. With a `file_id` string there are **two**
  parts, neither carries bytes, and there is nowhere a filename could go. So the name is structurally
  welded to the byte-carrying part: **you cannot have one without the other.** Exhaustive on the API
  surface too — no method in `aiogram.methods` exposes `filename`, none of the twelve `InputMedia*` types
  do, and no type in `aiogram.types` does; the only `filename` is the client-side `FSInputFile`
  constructor argument. `SendDocument.model_fields` (aiogram 3.30.0) has no such field. In the code the
  same duality is explicit: `cards.py:188` → `FSInputFile(path, filename=…) if path else file.file_id`,
  and rename returns `{"path": inpath, …}` (`tasks.py:178-182`), i.e. deliberately the upload branch.
  **Two things to know before anyone proposes this again.** The local Bot API server *does* support
  "upload files using their local path and the file URI scheme", so the **bot→local-server** hop could
  in principle be skipped — but not the **local-server→Telegram DC** upload, which is the one that
  actually costs, and which a new document requires by definition. And even that half-optimization is
  not simple here: `docker-compose.yml:65` mounts the bot-api volume `:ro` on the worker, so hardlinking
  the file under a new name where the server can read it does not work today. It would also apply to
  every file-producing op, not to rename specifically.
- ~~**Tests:**~~ **resolved 2026-07-26** — `tests/` + `requirements-dev.txt` + `pytest.ini` are committed (see §6). Coverage today is the security/correctness regressions of the phase-one bug audit, not the whole app; grow it fix-by-fix.
- ~~**Phase-3 item 11 — a socks `PROXY_URL` does not apply to the `direct` engine:**~~ **closed
  2026-08-12.** `_http_proxy` dropped every non-http(s) proxy, so with the `socks5h://` that
  `docs/ADMIN_PANEL.md` itself recommended, yt-dlp and gallery-dl went through the exit while the
  `direct` engine connected **straight out of the master's IP** — silently. The docs promised
  coverage the code did not deliver, and it blocked the mobile-exit plan. `_proxy_kind()` now
  classifies http/socks and `_direct_connector` routes socks through `aiohttp_socks.ProxyConnector`,
  gated by the runtime key `dl_direct_proxy` (default **on**: with an http proxy the direct engine
  always went through it, so on is the *consistent* setting, not a new behaviour; off means going back
  to leaking the master IP, and `dl_direct_max_mb` is the sharper lever for mobile-data cost).
  **Three facts that shaped it, all re-verified on aiohttp_socks 0.12.0 rather than inherited from the
  0.11.0 note.** (a) `ProxyConnector.__init__` does `kwargs["resolver"] = NoResolver()`
  unconditionally, so the anti-TOCTOU veto **cannot** be attached there — it disappears with no error.
  (b) Pinning a pre-vetted IP instead was investigated and **rejected**: python_socks derives TLS
  `server_hostname` from `dest_host` (`_stream.start_tls(hostname=…)`), so an IP would break
  certificate validation for every HTTPS host, and the v1 connector exposes no override. So the SSRF
  defence for socks is the **front door** — which is not a regression, because with an http proxy
  `_direct_connector` already omitted the resolver and relied on exactly that. (c) `socks5h://` is
  rejected by python_socks (`Invalid scheme component`) and is rewritten to `socks5://`; this is a
  pure scheme rewrite because `rdns` already defaults to True there (`if rdns is None: rdns = True`),
  i.e. `socks5://` in python_socks already means proxy-side DNS — unlike curl, where `socks5h` is the
  one that does. The `socks5h` recommendation in our docs was therefore correct and stays.
  **DNS failure is now fail-closed for both proxy kinds** (it used to be allowed whenever a proxy was
  set). The old rationale only holds for split-horizon DNS; our exit is external and the master is a
  normal VPS. Against that, a name that is NXDOMAIN for us but resolvable by the proxy walked straight
  past the front door — and in the proxy case the front door is the *only* defence, so the fail-open
  was weakest exactly where it mattered most.
- ~~**Phase-3 backlog — Spotify names the wrong cause when the age gate blocks everything:**~~
  **closed 2026-08-12 (phase 3ث).** `download_spotify` now counts dropped tracks and how many of
  those were `AgeRestricted`, and raises `AgeRestricted` instead of the generic
  `no YouTube match` when the two are equal — `run_download` already maps that to `nsfw_blocked`.
  Two details decided the shape. The condition is **all *dropped* tracks, not all tracks**: a
  playlist where one track is age-blocked and another simply had no candidate is a genuine
  matcher failure too, and the generic message is the honest one there. And the **pot-retry had
  to be excluded** — `download_spotify` retries once without the pot provider on any exception,
  but an age rejection is not a pot crash, so retrying spent a second yt-dlp run per blocked
  track and (worse) could bury the `AgeRestricted` under a different second-attempt error,
  losing the very signal the fix reads.
- **The Spotify matcher's remaining work, measured and ordered — read this before touching
  `_match_score`, `_norm` or the query.** Everything below was measured on 2026-08-12 against the
  reference track «Faryad» (Spotify: `Anoushirvan Rohani, Haydeh`, 311 s, 1980) after the embed-parser
  fix landed, plus a live query probe run on the master. **Agreed order: (1) query, (2) the paren bug,
  (3) the contradiction rule together with the script exemption.** They are listed in that order.

  ~~**(1) The query is the biggest single defect — the right recording is not even a candidate.**~~
  **CLOSED 2026-08-13 — fixed, and the fix was verified on the master before it was built.** The probe
  (repaired first, see the gotcha below) was run on both complained-about tracks. **Faryad:** the
  comma-joined shape returned only the duration-only false positive; **first-artist reached rank 1 and
  last-artist rank 2**, both on name *and* duration; the 61-candidate merge ranked the winner
  `WUxurPJmKXI` («Faryad» — `Anoushirvan Rohani, Haydeh` — 312 s — **103.2**) first, and the operator
  confirmed by eye that it is the correct recording. **Jane Maryam:** winner `OB8caWDe4mI`, Mohammad
  Nouri, 311 s, 106.0 — correct, and single-artist so it produced only 2 query shapes. So **merging
  alone closes both reported complaints**, which is why this shipped separately and ahead of items (2)
  and (3). `_search_queries()` is now the single source of the shapes: **first artist + title** and
  **last artist + title**, deduped. Three shapes were dropped on measurement, not taste — the
  comma-joined form and its no-comma variant never returned the target, and *title-only* did but at
  rank 16 (Faryad) and rank 10 (Jane Maryam), in both cases only after another shape had already found
  it. The reason both *ends* are kept rather than just the first is the convention split: Spotify lists
  the composer first for Iranian classical music, so the **last** artist is the singer — the thing that
  identifies a recording — while a Western release puts the main artist first.
  Everything below about (1) is the pre-fix measurement, kept because it is what the design rests on.

  `_gather_candidates` built `"{artist} {title}"` where `artist` is *every* artist joined by commas,
  which for Iranian music means `"composer, singer"` with the composer first. Measured, target =
  the Haydeh recording at ~311 s:

  | query shape | result |
  |---|---|
  | `"Anoushirvan Rohani, Haydeh Faryad"` (**today**) | **does not return it at all** — its apparent "rank 3" was a *false positive*, a different `Faryaad` at 312 s matched on duration only |
  | `"Anoushirvan Rohani Faryad"` (first artist) | **rank 1**, matched on name *and* duration |
  | `"Haydeh Faryad"` (last artist) | **rank 3**, matched on name *and* duration |
  | `"Faryad"` (title only) | rank 19, duration only |
  | Persian (`"فریاد هایده"`) | rank 19, duration only |

  Merging all six shapes gave **71 unique candidates** and a winner at **103.2**. Two cautions for
  whoever picks this up. The Persian query **cannot be built in production** — it was hand-supplied
  to the probe with `--fa`; Spotify only ever gives romanized names, so it presupposes
  transliteration (see (5)). And the sample is **one track**: `arts[0] + title` is byte-identical to
  today's query for a single-artist track, so dropping the comma-joined form only changes
  multi-artist behaviour, which is where it was measured to be broken.
  **Cost, measured:** today a track costs **1** YouTube Music call when the catalogue is rich and
  **3** when it is thin (`songs` → `videos` → `ytsearch`). Two query shapes cost 2 per track, and for
  single-artist tracks they dedupe back to 1. `match_max_tracks` defaults to **20**, so a playlist
  is 20–40 calls, not hundreds. `_ytmusic_search` already runs in `asyncio.to_thread`, so the shapes
  *could* be issued concurrently — but that doubles the instantaneous rate against an
  unauthenticated endpoint with no documented quota, and on a 429 `_ytmusic_search` swallows the
  error and returns `[]`, i.e. **silent failure**. Sequential is the safer default; per-track latency
  is dominated by the yt-dlp download, not the search.

  ~~**(2) `_norm` strips brackets before the keyword search, so the version penalty is mostly inert.**~~
  **CLOSED 2026-08-13.** Two normalisers now: `_norm` is unchanged and still strips brackets for fuzzy
  comparison (removing that would stop «Faryad (Official Video)» matching «Faryad»), while
  `_penalty_text` keeps them and is used *only* for the marker search. The remix therefore still scores
  **name 100** — deliberately — and what separates it is the penalty: measured, the original and the
  remix were **both exactly 106.0** and are now **106.0 vs 94.0**, with `(Live …)` `(Radio Edit)`
  `[Official Live Video]` also at 94.0, `(Slowed + Reverb)` at 82.0 (two markers stack, as before), and
  the controls `(Remastered)` and `(Official Video)` untouched at 106.0.
  **Three things `_penalty_text` deliberately does not do,** each measured: it keeps brackets; it does
  **not** apply `_FEAT_RE`, because that pattern ends in `.*$` and so «Faryad (Live) feat. Haydeh»
  collapsed to `'faryad'` and lost the marker entirely; and it does not apply `_NOISE_RE`.
  **The condition is symmetric and both sides had to move.** `kw in ct and kw not in tt` was symmetric
  under `_norm` (both sides lost their brackets), so changing only the candidate side *introduced* a
  bug: a reference that is itself a live recording gave `tt='faryad'` against
  `ct='faryad live in tehran'` and wrongly penalised `live`. Caught by measurement before it shipped.
  **The inflection rule is an explicit list, not a generic suffix — and this overturned the first
  design.** A generic `(?:s|es|ed|ing)?` was proposed to save `remixes`/`covers`/`sessions` from word
  boundaries, but measured over 20 real titles it produced **10 false positives, exactly as many as the
  substring matching it replaced**, because `lives` (zipf 5.1), `covered` (4.8), `covers` (4.5),
  `covering` (4.5), `performances` (4.3) and `reactions` (4.2) are ordinary English words: «Nine Lives»
  and «Covered in Rain» both took −12. Per-keyword suffixes still scored 2 errors (`covered`). The
  explicit list `remixes/remixed/covers/sessions/mashups` scored **0**. `_BAD_BASE` maps each form back
  to its base keyword so the penalty keeps its "one −12 per keyword" meaning. This is the same shape as
  `safety.STRONG_TOKENS`/`WORD_TOKENS`: an explicit list plus regression tests, never a rule that
  extends itself.
  **And word-boundary matching fixed a bug that already existed:** substring matching penalised all ten
  ordinary-word titles today, so «Nine Lives» loses 12 points in production right now. The false
  positives were never a risk this change introduced — they are the status quo it removes. One genuine
  ambiguity remains and is *not* new: `session` was already in `_BAD_KW`, so «Session of Love» is
  penalised today and «Sessions of Love» now matches it — consistent, not worse.
  Everything below about (2) is the pre-fix measurement.

  **`_norm` stripped brackets before the keyword search, so the version penalty was mostly inert.**
  `_PAREN_RE` (`[\(\[\{][^)\]\}]*[\)\]\}]`) removes parenthesised text, and that is exactly where
  YouTube puts version markers. Measured on real titles, **5 of 6 lose their penalty entirely**:
  `Faryad (DJ Fere Remix)`, `Jane Maryam (Piano Version - Slowed + Reverb)`,
  `Jane Maryam (Live at Vahdat Hall…)`, `Get Lucky (Radio Edit)`,
  `Get Lucky [Official Live Video]` → all `-0`. Only an unbracketed marker fires (`Faryad - Remix`
  → `-12`). **The second effect is worse than the first:** stripping the bracket also makes
  `_name_match("Faryad (DJ Fere Remix)", "Faryad")` = **100.0**, so a remix scores a *perfect* title
  match *and* takes no penalty — which is precisely the 80.2 the probe showed (name 100 · artist 100
  · duration 12 · `art_track` +6 · penalty 0). One normaliser is being asked to do two opposite jobs:
  strip noise for fuzzy comparison, and preserve markers for penalty detection. It cannot do both;
  the penalty needs the raw title.

  **(3)–(6) CLOSED 2026-08-13 — built together, since all four sit on the same function.**
  `_artist_match` is now `mean(cand-side)`: for each *candidate* artist, its best similarity to any
  reference artist, averaged. Picked by measuring five formulas against six scenarios; the requirement
  was that the **right** recording (YouTube listing only the singer — the common case) outscore the
  **wrong** one (same composer, different singers), while subset listings stayed high. Today's formula
  scored them **50.0 vs 68.0** — inverted; `max(ref-side)` tied at 100/100; `mean(ref-side)` was still
  inverted at 58.3/60.0 *and* dropped Get Lucky's correct Art Track to 39.1. Only `mean(cand-side)`
  (**100.0 vs 53.5**, margin 46.5) and a gentler blend (100.0 vs 76.8, margin 23.2) passed; the first
  was chosen for the margin and because it is conceptually the same as the contradiction rule's "extra"
  half. Accepted cost: a guest artist YouTube adds falls 100 → 72.7, still far above 53.5.
  `_artist_contradiction` (missing **and** extra, at 45) is the gate, keeping the numeric floor as a
  cheap second layer. **Two corrections to the recorded expectations:** on the eight scenarios the old
  40-gate scored **7/8, not 3/5** — its single failure is the singer-substitution case, which is
  precisely the reported bug; and **Hallelujah/Buckley is already rejected today** (am 16.0), so it is a
  **control** against regression rather than a failing case.
  **(5) shipped as a gated exemption, not a blanket one, and the first measurement was of the wrong
  case.** Measured on a *fully* Persian candidate, name **and** artist both collapse to 0.0 (total 35.3
  vs 106.0), so lifting the name gate there is a no-op that only admits noise — and neutral-substituting
  the name still only reaches 70.7. But the **mixed** case is real and came from our own candidate list:
  title `'قطعه فریاد'` (Persian) with artist `'Anushiravan Ruhani'` (Latin), where the artist is healthy
  (60.0 before, **88.9** with the new formula) and *only* the name gate kills it. `_name_gate_exempt`
  therefore lifts the gate when the **titles** are in different scripts and the artist score clears 45.
  Measured end to end: it reaches **61.6**, clearing the 55 threshold, and wins once the contradiction
  rule rejects the wrong romanized rival — while the correct romanized recording, when present, still
  wins at 103.2.
  **The name score is deliberately NOT replaced with a neutral value**, and this is the `_TIME_UNKNOWN`
  lesson running the other way: substituting raises target and decoy *equally*, so it buys no
  discrimination and only weakens the threshold. With the real value, a decoy (same composer, different
  Persian title) at +5/+10/+20/+35 s scores 50.0/43.0/36.2/33.1 — all below 55; with a neutral 50 the
  +20 s decoy reaches 55.9 and gets through.
  `_dominant_script` counts letters (Latin vs non-Latin) rather than hardcoding Arabic ranges, so
  Cyrillic and CJK behave the same and digits never read as a script difference.
  **A sabotage pass found a genuine design flaw, not just a test gap.** The first version also required
  the *artist* scripts to match. Removing it broke no test — because the artist **score** requirement
  already measures comparability — and in the one case it was reachable it was **wrong**: a bilingual
  listing `'هایده Haydeh'` against a Persian reference scores 58.8, i.e. the artist genuinely matches,
  yet the check called the scripts "different" and rejected it. Removed as redundant *and* harmful.
  The same pass caught a vacuous test: the contradiction rule was asserted only as a **function**, so
  deleting the gate from `_rank_candidates` failed nothing — and the numeric floor cannot stand in,
  since that candidate scores 53.5, above the 40 floor.
  Everything below about (3)–(6) is the pre-fix measurement.

  **`_artist_match` was a per-artist maximum, not coverage — and it weighted the wrong artist.**
  For each *reference* artist it takes the best similarity against *any* candidate artist, then
  weights the **first** reference artist 0.6 and the mean of the rest 0.4. Consequences: an extra
  artist on the candidate costs **nothing**, and Spotify lists the composer first for Iranian
  classical music, so the singer — the thing that actually identifies a recording — carries only 0.4.
  Measured: wrong Faryad (`Anoushirvan Rohani, Maziar, Kari`) scores `100×0.6 + 20×0.4` = **68.0** and
  sails through the gate; the right one scores 100.
  **Correction, re-measured 2026-08-13 — this is worse than written above, and the difference changes
  what kind of problem it is.** "The right one scores 100" holds *only* when the candidate lists **both**
  artists. When YouTube lists only the singer — `['Haydeh']`, the common case, and the same
  name-only-the-lead shape that item (4) is built around — the per-reference scores are `[16.7, 100.0]`,
  so `main` is the **composer** comparison and the result is `16.7×0.6 + 100×0.4` = **50.0**. Against the
  wrong recording's 68.0 that means the artist component **actively prefers the wrong recording by 18
  points**. So this is not a weighting nit to be tidied up alongside (4); it is a defect in its own
  right, and it should be treated with the same weight as the contradiction rule when (3) is built.

  **(4) A "contradiction" rule scored 7/7 where every simple criterion failed.** The distinguishing
  feature is not how many artists match but whether the candidate *claims someone else*: an artist
  present in the reference but absent from the candidate (**missing**) *and* an artist on the
  candidate absent from the reference (**extra**), both at a 45 fuzzy threshold. Subset listings —
  YouTube naming only the lead — are not contradictions. Measured against the alternatives, with the
  current 40 gate: current 3/5, `min` 3/5, mean 2/5, penalty-per-miss 3/5, best-only 3/5, and every
  coverage-flavoured rule **wrongly rejects the correct Art Track** for `Daft Punk, Pharrell
  Williams, Nile Rodgers` when YouTube lists only `Daft Punk` (`min` 7.7, mean 39.1, penalty 13.4 —
  all under 40). The contradiction rule got all seven scenarios right, including that one.
  **Unmeasured risk:** a romanization variant across the two services (`Hayedeh`/`Haydeh`) could read
  as "extra" — largely absorbed by the 45 fuzzy threshold, but not tested on Persian names.

  **(5) Persian-script titles are eliminated wholesale.** `_norm` deliberately preserves Unicode, so
  Persian survives normalisation — but `difflib` across two scripts is near zero: `قطعه فریاد` → **4.8**,
  `فریاد` → **0.0**, `جان مریم` → **10.5** (re-measured 2026-08-13; recorded as 5.0, and the other two
  reproduce exactly — the conclusion is unchanged since all three are far under the gate). All under the
  45 name gate.
  **And the romanization risk that item (4) recorded as unmeasured is now measured** — 15 same-artist
  spelling pairs, **14 clear the 45 threshold** (57.1–97.8): `Haydeh`/`Hayedeh` 92.3 ·
  `Googoosh`/`Gugush` 57.1 · `Shajarian`/`Shajaryan` 88.9 · `Moein`/`Mo'in` 80.0 ·
  `Dariush`/`Daryoush` 80.0 · `Anoushirvan Rohani`/`Anushirvan Rohani` 97.1. So the contradiction rule's
  stated risk is largely closed. The one failure is **`Ebi` ↔ `Ebrahim Hamedi` = 35.3**, which is not a
  romanization variant at all but a **stage name against a legal name** — a different problem class that
  fuzzy similarity cannot solve, and the one that is still open. For Iranian music this may be a
  large share of the catalogue. Options and costs: **script detection + exempting the name gate**
  (cheap, no dependency; risk: unrelated Persian candidates get in and duration has to carry the
  discrimination) · **transliteration** (expensive and *inherently ambiguous* — Persian omits short
  vowels, so «فریاد» maps to faryad/fryad/faryaad; needs a table or a new dependency in the
  download-node image) · **a parallel Persian query** (needs the Persian name, which Spotify does not
  give, so it collapses into transliteration).

  **(6) The 40 artist gate barely rejects anything.** Measured over unrelated name pairs, **3 of 9
  pass**: `Mohammad Nouri`↔`Sara Naeini` = **40.0** and `Shajarian`↔`Nazeri` = **40.0** (the gate is
  `< 40`, so exactly-40 survives), and `Vigen`↔`Viguen` = 90.9 (correctly, they are the same artist).
  The rest land 8.7–28.6. So today it is the **duration** gate doing the real work, not the artist
  gate — worth remembering before tuning the number rather than the criterion.
- ~~**The `download_cache` key carries no version — decided: version it, but only per-platform.**~~
  **CLOSED 2026-08-13.** `_MATCH_VERSION` enters the key only when
  `platform_of(url) in downloader._MATCH_PLATFORMS`, read from that set rather than a second
  hand-written list. **The half that actually mattered was the legacy fallback**, and without it the
  whole change is inert: measured, `cache_key` and `_legacy_key` *already* differ for a Spotify URL
  because `_cache_url` drops the scheme, so the path was versioned key → miss → hit on the stale
  raw-URL row → migrate it under the new key → the same wrong answer, now looking fresh. So
  `get_cached` skips the legacy fallback for match platforms, and a test seeds a stale legacy row and
  asserts it is neither served nor migrated.
  **The rot risk the note predicted is closed by a test, not by discipline.**
  `tests/test_spotify_match_fingerprint.py` hashes the chain's observable output and pins it, so any
  change that alters the delivered answer fails with a paste-ready new value and a message saying to
  bump `_MATCH_VERSION`. Two halves, and **the second is the one we were blind to**: the cache key is
  `(url, options, version)` and the URL does not move when the *parser* changes, so a
  `_parse_spotify_embed` fix would shift every reference — and therefore every target — while a
  matcher-only fingerprint (whose reference is a fixed fixture) stayed still. That is the same parser
  that was silently dead for weeks. Half two therefore runs the two **real recorded** `__NEXT_DATA__
  dumps through the parser and hashes the references it produces. Floats are `round(_, 3)` before
  hashing or the digest is not stable across environments. Verified both ways: moving one weight by
  0.01 or the penalty by 1 breaks it, while adding a comment and renaming local variables does not.
  **Scope, measured rather than assumed.** Only Spotify **single-track** links ever produce a versioned
  row. A multi-track playlist reaches `_spawn` with `url=None` (`tasks_download.py:1113`) and `_spawn`
  writes only `if url and f.file_id` (`:544`), so **no cache row is written at all** — the version
  question does not arise there. And `put_album_cached` sits behind `engine == "gallerydl"` (`:1072`),
  i.e. Instagram/Pinterest carousels only, which correctly stay unversioned because gallery-dl does not
  choose a target. `get_cached` is also the **only** key-resolving read path: the panel touches the
  table only through aggregates (`admin_web.py:1403-1407`) and the gateway never touches it at all
  (`/dl` resolves `File.dl_token`, `gateway.py:33`).
  The one-time cost of landing this: the pre-existing Spotify rows become permanently orphaned, because
  the table has **no eviction** — `created_at` exists (`models.py:165`) but nothing implements a TTL,
  and the only delete is `_drop` on an invalid `file_id`. So the deploy carries a single
  `DELETE FROM download_cache WHERE platform = 'spotify'`.
  Superseded reasoning is kept below.

  **The `download_cache` key carried no version — decided: version it, but only per-platform.**
  The key is `sha1(f"{_cache_url(url)}\n{selector}")[:64]` with nothing about our own logic in it, so
  every matcher or parser change leaves stale rows serving the previous answer forever; the operator
  had to clear 34 `platform = 'spotify'` rows by hand to make a smoke test meaningful. `_legacy_key`
  exists but does the opposite — it *migrates* an old key forward so the cache is not lost, never
  invalidates. Two facts shape the fix. The cache stores a Telegram **`file_id`, not bytes**, so a
  stale row costs no bandwidth — it serves the **wrong file**, making this a correctness problem
  rather than a storage one. And **most rows do not depend on our logic at all**: a YouTube link's
  cached id is exactly what the URL names, with no matching involved. Only the DRM-match platforms
  (Spotify, Apple) depend on decisions we make, so a global version would discard correct rows to fix
  a problem they never had. Decision (operator, 2026-08-12): include a version component **only for
  platforms where we choose the target**; the `platform` column already exists. Known trap: a
  hand-bumped constant is the same shape as `_KNOWN_UNREACHABLE` and the old hardcoded connector list,
  both of which rotted — but its failure mode is exactly today's status quo (clear by hand), so it is
  never worse than now. A cheaper 80% alternative that composes with it: a panel button that clears
  the Spotify cache, turning the manual SQL into a click.
- **Spotify's embed page hands us `isExplicit` and `isNineteenPlus` for free — recorded, not wired up.**
  Both appear on the track entity (`props.pageProps.state.data.entity`) and are captured in
  `tests/fixtures/spotify_embed_track.json`. They are a publisher-declared age/explicit signal
  arriving *before* any download, which is exactly the shape `app/safety.py`'s cheap metadata layer
  wants — today that layer relies on yt-dlp's `age_limit`, which Spotify links never carry because
  the match target is a YouTube video chosen by us, not the publisher's own record. Deliberately
  **not implemented** (operator's call, 2026-08-12): it needs a decision about whether "explicit"
  (profanity) should gate anything at all, versus `isNineteenPlus` alone, and that is a policy
  question rather than a code one. The anonymous `accessToken` also present on that page is
  deliberately ignored.
- ~~**The Spotify album/playlist branch is unverified against today's embed schema:**~~ **closed
  2026-08-12** — a playlist dump (100 items) showed `trackList` alive and matching, so that path had
  never broken; only single-track links were. It also corrected the schema note above: `subtitle` is
  the **live** artist shape for tracks inside `trackList`, not a legacy fallback. Fixture at
  `tests/fixtures/spotify_embed_playlist.json`. Still uncaptured, and deliberately not guessed at:
  the collection-level keys (playlist cover, year), so playlist tracks currently carry no cover.
- **`is_safe_url_resolved` rides the default `asyncio.to_thread` executor** (shared, `min(32, cpu+4)`
  threads). Each link intake parks one thread for up to 2 s on DNS. At today's traffic this is
  invisible and the 60 s cache absorbs repeats, but it is the saturation point if link volume grows —
  a dedicated small executor, or an async resolver, is the fix when that day comes. Recorded, not acted on.
- ~~**CI:**~~ **resolved 2026-08-10** — `.github/workflows/tests.yml` runs the suite on every PR and on push to `main` (see §6). **Lint is still open:** there is no ruff/flake8 config and nothing checks style or unused imports, so the CI job proves the tests pass and nothing else. Add ruff to the same workflow, or leave formatting to review?
- **The import-hook idea is REFUTED as specified, measured 2026-08-17 — the deny-list cannot be derived where it has to run.** The entry below proposed deriving the forbidden module names from `requirements-admin.txt`/`requirements-worker*.txt` via `packages_distributions()`. Run in a clean `requirements-dev.txt` environment, **every one of the 13 out-of-dev distributions resolves to nothing** — `cryptography`, `jinja2`, and all eleven worker-only ones come back `UNRESOLVABLE`. The mechanism is circular: `packages_distributions()` maps only what is **installed**, and the whole point is that these are absent. The mapping itself works fine on installed things (control: `Pillow`→`PIL`, `PyYAML`→`['_yaml','yaml']`, `yt-dlp`→`yt_dlp`), which is exactly what makes the failure easy to miss on paper. Every workaround puts back the thing it was meant to remove — a hand-written dist→module map, or `pip download --no-deps` plus wheel-metadata parsing at test time. So the hook is not "bigger than a one-liner", it is **the wrong shape**; the transitive gap stays open and is covered instead by the fact that panel imports now have a legal home (`tests/panel/`, see §6). Two *direct* blind spots in the existing guard were real and were closed the same day: it scanned only `test_*.py` (so any `conftest.py` slipped past entirely) and it caught `import app.admin_web` but not `from app import admin_web`. Original reasoning kept below.
- **The AST import guard is blind to *transitive* imports — an import hook would close it, and the deny-list should be discovered, not written.** `test_no_test_imports_a_module_the_ci_runner_does_not_have` reads every file under `tests/` with AST and fails on a direct `import app.admin_web` / `cryptography` / `jinja2`. It cannot see a test importing `app.foo` where `app/foo.py` imports `app.admin_web` — which fails on CI exactly the same way. The mechanism that would cover both is an import hook installed in `conftest.py` for the whole session, making the admin- and worker-only distributions unimportable in the test environment, i.e. reproducing the runner's constraint locally rather than asking anyone to remember it. Two design points, so whoever builds it does not start from zero. The deny-list must be **derived** from `requirements-admin.txt` and `requirements-worker*.txt` minus `requirements-dev.txt`, not hand-maintained — a hand-written list is the `_KNOWN_UNREACHABLE` rot shape, and it is what let `cryptography` slip in the first place. And distribution name ≠ module name (`Pillow`→`PIL`, `PyYAML`→`yaml`), so the mapping needs `importlib.metadata.packages_distributions()` rather than a string transform; that is precisely the part that makes this bigger than a one-liner and why it is recorded rather than bundled into an unrelated change. Note `PyYAML` **is** in `requirements-dev.txt` (the compose guard needs it) and must stay importable — the derivation handles that automatically, a hand-list would not. Deliberately not built: the direct-import guard already covers every occurrence seen so far, and this is CI topology that deserves its own reviewed change.
- **یک موردِ سابوتاژ فقط در **توالی** می‌افتد، نه تنها — و روی `origin/main`ِ تمیز هم بازتولید شد.** `orphan: the match search stops killing its child (pre-fix form)` وقتی جدا اجرا شود **۳ از ۳** سبز است، ولی وقتی چهار موردِ `orphan` پشتِ‌هم می‌دوند می‌افتد و به‌جای `test_the_match_search_does_not_leave_yt_dlp_running`، تستِ همسایه‌اش `test_probe_does_not_leave_yt_dlp_running_after_cancellation` قرمز می‌شود. اندازه‌گیری‌شده روی **هر دو درخت** (برنچِ فاز ۳ و worktreeی از `origin/main`ِ دست‌نخورده): هر دو `3/4`، هر دو ۲ از ۲ اجرا. پس **پیش‌موجود است و مالِ کارِ پنل نیست**. علتِ محتمل همان ردهٔ ثبت‌شدهٔ §۷ است: سابوتاژِ موردِ قبلی یک yt-dlpِ یتیم می‌گذارد و تستِ بعدی آن را می‌شمارد — یعنی تداخلِ بینِ کیس‌ها، نه ادعای غلط. دو نتیجهٔ عملی: عددِ «۸۵/۸۵» برای دفترچه فقط وقتی معنا دارد که این تداخل حل شود، و هر کسی که این را ببیند نباید دنبالِ باگ در کارِ جاری بگردد. رفعش احتمالاً «هر تستِ orphan فرایندِ خودش را قبل از خروج reap کند» است؛ **ثبت شد، ساخته نشد.** **۲۰۲۶-۰۸-۱۸: آن «علتِ محتمل» دیگر محتمل نیست — دیده شد.** در یک اجرای کاملِ دفترچه، وسطِ کارِ کیسی که ده‌ها موردْ بعدتر بود، `pgrep` ده فرایندِ زندهٔ `yt-dlp`ِ استابی را نشان داد که مسیرشان نامِ تستِ **قبلی** را داشت — از جمله `/tmp/pytest-of-root/pytest-107/test_probe_does_not_leave_yt_d0/yt-dlp` و `…/test_the_orphaned_probe_was_ho0/yt-dlp`، یعنی از دو رانِ pytestِ جدا. پس نشتِ فرایند **بینِ رانِ pytest** واقعاً رخ می‌دهد و شمارشِ کیسِ بعدی را آلوده می‌کند؛ فرضیه تأیید شد و رفعِ پیشنهادی (reap کردنِ فرایندِ خودِ هر تست) درست هدف‌گیری شده. هنوز ساخته نشد، ولی دیگر حدس نیست. **یک هشدارِ عملیاتی هم دارد:** این استاب‌ها عمداً تمام‌نشدنی‌اند (§۶ — «به بلاک‌کننده راهی برای تمام‌شدنِ خودبه‌خود نده»)، پس تا کشته نشوند در سندباکس می‌مانند و هر اندازه‌گیریِ بعدیِ «چند فرایند زنده است» را خراب می‌کنند.
  **۲۰۲۶-۰۸-۱۸ — نشت **زنده و کمّی** دیده شد، ولی *علتِ این مورد نیست*؛ و همین
  تفکیک کلِ ارزشِ این یادداشت است.** در اجرای کاملِ دفترچه (۱۷۷/۱۷۸، تنها ✗
  همین مورد با همان امضای ثبت‌شده: به‌جای `test_the_match_search_…` همسایه‌اش
  `test_probe_does_not_leave_yt_dlp_running_after_cancellation` قرمز شد)،
  `pgrep` **۱۱ استابِ زنده از سه اجرای متفاوتِ pytest** نشان داد
  (`pytest-of-root/pytest-48|50|51/…`) — یعنی نشت **بینِ اجراها** واقعی است و
  برای اولین بار عدد دارد. **ولی خوانشِ اولِ من از همین شاهد غلط بود و با تکرار
  رد شد:** فرض کردم آلودگی *علتِ* ✗ است، و یک اجرای ۴/۴ روی جدولِ تمیز آن را
  تأیید کرد؛ دو اجرای بعدیِ **روی همان جدولِ تمیز** ۳/۴ دادند. پس کشتنِ
  استاب‌ها این مورد را سبز نمی‌کند و آلودگی مکانیزمِ آن نیست — دو مسئلهٔ جدا
  که یکی‌گرفتنشان از هر دو استنتاجِ غلط می‌سازد. درسِ §۶ که این‌جا دوباره
  خرج داد: **از یک اجرای یک موردِ شناخته‌شده‌flaky نتیجه نگیر** — همان چیزی که
  «۴/۴» یک‌بار به من گفت و تکرار پس گرفت.
  **پیش‌موجود بودن این‌بار اثبات شد نه نقل:** روی worktreeی از **`origin/main`ِ
  دست‌نخورده (`ac315dd`)** — بدونِ `probe_stats.py`، بدونِ `__call__`ِ
  `aiogram_double`، بدونِ موردهای تازه — همان مورد با همان امضا ۳/۴ داد (و در
  اجرای دوم ۴/۴). پس نرخِ شکست روی هر دو درخت یکسان و متناوب است.
  **نتیجه برای رفعِ پیشنهادی:** «هر تستِ orphan فرایندِ خودش را قبل از خروج
  reap کند» همچنان درست است و حالا شاهدِ کمّی دارد (۱۱ استاب از ۳ اجرا)، ولی
  **به‌عنوان رفعِ نشت**، نه به‌عنوان رفعِ این ✗ — چون اندازه‌گیری نشان داد آن
  دو یکی نیستند. علتِ خودِ ✗ همچنان نامعلوم است و باید جدا شناسایی شود.
  **ساخته نشد؛ PRِ جدا** (تصمیمِ اپراتور، ۲۰۲۶-۰۸-۱۸).
- **The reaper reads "online" as "heartbeating", not as "working" — a wedged node is invisible to it.** `nodes.reap_orphan_jobs` skips a role's queue whenever `role_online()` is true (`nodes.py:210-211`), and `role_online` only asks whether a heartbeat key exists (`nodes.py:167-170` → `list_live`). The two are not the same thing. This cost nothing in the `ProcessingWorkerSettings` bug precisely because the crash killed the heartbeat too — arq raised inside `Worker.__init__`, before `on_startup` ever spawned `_node_heartbeat` — so the role read as offline and both the routing gate and the reaper did the right thing. Whether the gap can actually strand work depends on *how* a node fails, and the two cases differ:
  - **Event loop blocked** (a sync infinite loop — the `_atempo_chain` bug was exactly this shape): `_node_heartbeat` is an ordinary asyncio task on the *same* loop (`worker.py:40`), so it stops too, the 45 s TTL (`nodes.py:61`) lapses, the role reads offline and the reaper takes over. **Self-correcting — not the worrying case.**
  - **Loop alive but every job slot wedged** (all `max_jobs` occupied by jobs awaiting something that never returns): the heartbeat keeps ticking while the node consumes nothing, so the master keeps routing to a queue nobody drains and the reaper keeps skipping it. This one is real, but bounded — arq's `job_timeout` (2000 s processing, 5400 s download) eventually kills the stuck jobs and frees the slots, so the effect is a repeating stall, not permanent loss.

  Narrow, bounded, and not worth fixing blind — but it should be settled **before nodes come back**, since that is the only configuration where it arises. The likely fix is to make the heartbeat carry something the worker itself updates (last poll / last job picked up) and have `role_online` require it to be recent, rather than trusting the mere presence of the key.
- **`_ALBUM_UNKNOWN` was designed, measured, and deliberately NOT built — the number killed it.**
  The album component (weight 0.08) had never fired in production: the Spotify embed path hardcodes
  `"album": ""` in `_embed_track`, so `_album_match` always returned `None` and the component was
  dropped. Apple always sends `collectionName`, which wakes it up — and it wakes up with the exact
  defect `_TIME_UNKNOWN` was introduced to fix. Measured against an album-carrying reference: a
  candidate that states **no** album scores **106.00**, one that states a **disagreeing** album
  scores **99.94**. "Unknown" outscores "stated but different".
  The fix would be a neutral value substituted only for the *candidate*-side gap (safe by the
  optional-signal rule; substituting for a missing *reference* is the unsafe direction). **It was
  not built because the population it protects did not appear.** A probe run on the master
  (`tools/apple_album_probe.py`, 8 tracks) found **0 of 22 ranking survivors without an album**, and
  all 210 unique candidates came from the YT Music `songs` catalogue: zero `videos`, zero `ytsearch`.
  That is not a sampling artifact, and the distinction was checked by execution rather than argued:
  `videos` fires only when the merged `songs` pool is **under 3** (`_gather_candidates`), `ytsearch`
  only when the pool is still under 3 after that — a strictly stricter condition — and the probe's
  own gate was measured to be **looser** than production's, so it would have sampled `videos` in
  cases where production does not. Adding a constant we cannot calibrate, for a case we have never
  observed, is the hand-maintained-constant rot the whole exercise exists to avoid.
  **Reopen when the tail is actually reached**: obscure tracks where YT Music `songs` returns fewer
  than 3 results. Until then the defect is dormant and recorded, not fixed.
  Caveat on the sample, from the operator: two of the eight ids resolved to a different track than
  intended (an «ebi khodahafez» that came back as *Bi Khodahafezi*, a «googoosh man amadeam» that
  came back as a Fariborz Lachini piano cover). The data is real, so the numbers stand, but the
  sample is less representative of real traffic than its size suggests.
- **The album component is not a decisive signal anywhere, and in about a third of cases it
  penalises the *correct* recording — recorded, not fixed, and not to be bundled with Apple.**
  Reading all eleven "different" cases from that probe run: **four** are a compilation against the
  original album *on the same recording* (`The Essential Leonard Cohen` ↔ `Various Positions`, where
  Various Positions is the 1984 original and Apple's own reference is the compilation — so the right
  recording takes the penalty), **three** are live performances the version penalty already catches,
  and **four** are entirely different songs that name and artist had already rejected. So the
  component never decides anything it needed to, and costs points on the truth roughly a third of
  the time. Measured cost is bounded (a compilation scores ~20, which at weight 0.08 is ~6 points),
  and a Persian-script album title on the candidate side scores **14.8** — a penalty channel Spotify
  never had, and the reason the 0.08 weight should not be raised. This is its own class of problem;
  fix it on its own evidence, not as a rider on a platform change.
  **Whoever picks this up starts with a detector already in the data, not from zero.** The real
  lookup dump (`tests/fixtures/apple_lookup.json`, F8) shows a compilation announcing itself:
  `collectionArtistName` is `"Various Artists"` and it carries a `collectionArtistId` that no
  other row in the dump has. So "the reference's own album is a compilation and should not be
  taken seriously" is a cheap field read, not an inference — which is exactly the four
  compilation-vs-original cases that make the component penalise the correct recording.
  Recorded, deliberately not built.
- **Apple Music phase B — album and playlist links — deliberately not built.** Phase A takes
  single-track links only (`?i=` present, or a `/song/` path); anything else raises
  `AppleUnsupported` and the user gets an explicit message rather than a silently wrong answer. Two
  unknowns block it and neither may be guessed at: an album's tracks need `&entity=song` on the
  *album* id, which returns a differently shaped response nobody has dumped yet; and Apple playlist
  ids are **not numeric** (`pl.u-…`), so the numeric lookup probably cannot resolve them at all.
  The Share button produces the `?i=` track form, so phase A covers the common real case.
- **A track missing from the requested storefront has never actually been observed.** `country=zz`
  returns **HTTP 400** (not `resultCount: 0`), which is why the retry catches the exception and not
  just an empty result; `country=jp` returned the track fine. The second lookup without `country` is
  therefore justified by the 400 case and is an **assumption** for the missing-track case.
- **Two of `textstore`'s three write paths have the check-then-act bug; the third was wrongly
  accused and is fine.** The audit that followed the `settings_store.set()` fix ran the same probe
  over every read-then-write path in the settings layer, and the per-path numbers matter because a
  blanket label hid a real difference. Twenty runs each, four concurrent writers, **file-backed**
  SQLite: `set_text` raised `IntegrityError` 18/20 and `set_button_styles` 19/20 — both are
  `SELECT`-then-`INSERT` and both are genuinely broken. `set_menu_layout` raised **0/20**, and every
  result was a *complete* layout from a single writer, never a mixture and never a partial one: its
  delete-then-insert lives in **one transaction**, so it is atomic and last-writer-wins, which is
  exactly the semantics "replace the whole layout" wants. The earlier claim that all three raised
  came off the `:memory:` harness and was wrong. Note the 0/20 is only meaningful because the same
  harness produced 18/20 and 19/20 on its siblings — that is the negative control from §6 doing its
  job. `settings_store.reset()` is also fine (a concurrent double delete only emits SQLAlchemy's
  "expected to delete 1 row(s); 0 were matched" warning).
  **Pre-existing and unrelated to Apple Music, so recorded rather than bundled** — the same call as
  the `7z` marker and the `_MIGRATIONS`-in-CI gap. Narrower than the settings one was, too: the panel
  is a single process and a batch save is sequential within one request, so it needs two admins
  saving at the same moment rather than every worker starting at once. The fix for the two real ones
  is the shape `settings_store.set()` now uses — on conflict, write it as an `UPDATE`.
- **`fetch_failed` شمرده می‌شود ولی هیچ retryی ندارد — عمداً، تا عدد تصمیم بگیرد.**
  در پاسِ ناشناسِ اینستاگرام، `resolve` می‌تواند موفق باشد و بعد بایت‌ها نیایند: URLِ
  امضاشدهٔ CDN منقضی شده، سقفِ تجمعی وسطِ کاروسل تمام شده، قطعیِ شبکه، یا بودجهٔ زمانی.
  هر چهارتا امروز به یک سطلِ `dlstat:iganon:fetch_failed:<date>` می‌روند و کار به مسیرِ
  کوکی می‌افتد. **گزینهٔ روی میز یک retryِ تک‌بارهٔ per-item است** (فقط برای همان آیتمی
  که افتاد، نه کلِ پست)، ولی ساختنش قبل از دیدنِ عدد یعنی حدس‌زدن: اگر این سطل عملاً
  صفر بماند، retry پیچیدگیِ بی‌مصرف است؛ اگر پرشد، **اول باید تفکیک شود کدام‌یک از آن
  چهار علت** — چون retry فقط برای انقضای URL معنا دارد و برای سقف/بودجه اثباتاً بی‌فایده
  است (تلاشِ دوم همان سقف را می‌خورد). یعنی گامِ بعدی احتمالاً «سطل را بشکن» است نه
  «retry بساز». به‌عمد ساخته نشد؛ بعد از اولین دورهٔ روشن‌بودنِ فلگ تصمیم گرفته شود.
- **کپشنِ تک‌عکسی در مسیرِ ناشناس `None` می‌ماند** (`extract_from_img`). دو منبعِ **سنجیده‌شده**
  برایش هست و هیچ‌کدام ساخته نشد: متنِ `class="Caption"` در همان HTML (بدونِ رفت‌وبرگشتِ اضافه،
  ولی markupِ تودرتو دارد — `<a class="CaptionCommentsExpand">` و یک پیشوندِ `> username`)، و
  فیلدِ `title`ِ پاسخِ oEmbed که در هر سه دامپ **دقیقاً** کپشن بود — ولی رده A در تولید خاموش
  است، پس روشن‌کردنش یک رفت‌وبرگشت به هر دانلود اضافه می‌کند. فاز ۲ اگر `File.post_caption` را
  برای این حالت خواست، از این دو انتخاب کند؛ مسیرِ `gql_data` کپشن را از قبل دارد.
- **Contribution/git conventions** (branch naming, commit trailers) are session-injected, not repo facts — document them here or leave out?
- ~~**Systematic input/ownership validation in `routers/ops.py`:**~~ **resolved 2026-08-10 (phase 2a)** — the ownership half is closed centrally in `crud.get_file_by_ref`/`get_owned_job` (see §7). **What is still open is the *input* half:** handlers accept whatever a callback carries and mostly validate ad hoc. `op_speed_pick`/`op_speed` got a `kind` guard during the atempo fix, but there is still no systematic check that an op is legal for the file's `kind` — `OPS_BY_KIND` already encodes that rule for building the keyboard and nothing enforces it on the way back in. Now that ownership is settled, the natural next step is to reuse `OPS_BY_KIND` as the enqueue-time gate rather than adding more per-handler `if`s.
- ~~**2-6, the DB session held across the whole job:**~~ **closed 2026-08-10 as won't-fix — reopen only on the conditions below.** `run_op` does pin a Postgres connection from `tasks.py:500` to `746`, `_do_op` included, so on a large video one connection is held for tens of minutes. Measured on the production database, that is currently harmless: `idle_in_transaction_session_timeout = 0` (disabled), so the session is never killed mid-job and **no data can be lost**; and `max_connections = 100` against a baseline of 6, so four pinned connections are noise. Rewriting the function is riskier than the bug it fixes. **Three things must reopen it:** (1) `idle_in_transaction_session_timeout` becomes non-zero — then a long job's session is killed mid-flight and the final commit fails; (2) PgBouncer is added in **transaction** pooling mode, which hands the connection back between statements and breaks a session held across an await; (3) `max_jobs` is raised a lot, or many processing nodes are added, so pinned connections approach `max_connections`. **Keep this finding when reopening, so nobody starts from zero:** the obvious shortcut does not work. `await session.close()` before `_do_op` releases the connection and reads still succeed (`Sessionmaker` sets `expire_on_commit=False`, `db.py:45`), but a later mutation on the now-detached object is **silently dropped** — verified on a real session, the value stayed `before` after mutate + commit — which would quietly lose `job.status`, `job.finished_at` and every post-op `file` update. And passing plain values instead of the ORM object is not small either: `file` is a required `File` parameter of the whole card layer and of `_do_op`. The only correct shape is a three-phase split (load and mark running → no session across `_do_op` → write results), inside a 250-line function with 13 nested `try` blocks.
- **Screening the Telegram thumbnail instead of the file — investigated 2026-08-10 and REJECTED.** The idea was to gate on the video's `thumbnail` (tens of KB) at upload so the card appears in under a second, deferring the full frame scan to when the bytes are localized anyway. Three findings, in the order they matter. **Resolution is not the problem** — NudeNet ships `320n.onnx` and `_read_image(path, target_size=320)` rescales every input to 320×320, while Telegram thumbnails are ≤320px, so the model would see essentially the same pixel budget it sees today (the current pipeline already downscales frames to `min(640,iw)`). **Sampling is a real loss:** a thumbnail is one frame, while `_video_frames` deliberately samples five across 5%–95% for the reason its own comment gives — «نه فقط ابتدا — تیزرِ سالم رایج است». **And sender control is disqualifying:** `sendVideo`/`sendDocument`/`sendAnimation` all take a `thumbnail`, and Telegram clients let the uploader pick a video cover, so an attacker attaches an innocuous cover to explicit content and the gate passes every time. That turns a heuristic degradation into a deterministic bypass, in exactly the adversarial case the gate exists for. Two supporting facts: the thumbnail is optional, so a missing one forces a fallback that is either fail-open (trivially chosen by an attacker) or fail-closed (back to the full wait, again attacker-chosen); and `FileInfo` (`filetypes.py:44-53`) does not carry a thumbnail today, so intake would need a new field. It would work for **photos**, where `photo[0]` is a downscale of the same image — but photos are already fast, and the 10 s cost is entirely on large videos, so the idea helps where there is no problem and fails where there is. A cheap thumbnail *pre-filter* in front of the full scan was also considered and rejected: it does not reduce latency, since the full scan still has to finish before the card. Not measured: the numeric accuracy drop on real thumbnails, which would need an NSFW corpus.
- **`op_link` is the only path that really redistributes to third parties, and the only op that needs no bytes — gate it explicitly.** Everything else a user can do between upload and operation either stays in their own chat (the card, sent by `file_id` to the same `chat_id`) or goes through a worker job that localizes the file. `op_link` (`routers/ops.py:905`) does neither: it mints `file.dl_token = secrets.token_urlsafe(18)[:24]`, commits, and hands back public `/dl` + `/s` URLs the gateway serves to **anyone** — with no `_localize`, no enqueue, no bytes touched (`ops.py:913-916`). The consequence matters for any future change to the safety layer: a rule shaped as "screen when we need the bytes" walks straight past `op_link` and publishes unscreened content. Screening at upload (the current design) covers it only as a side effect of covering everything. If screening is ever moved or made lazy, `op_link` needs its own explicit gate, decided on the op, not on whether bytes are required.
- **Nothing in this repo restricts the bot to private chats — that protection lives in BotFather.** `FILE_FILTER` (`routers/files.py:20-23`) matches a file message in **any** chat type, and there is no `ChatType`/`F.chat` filter anywhere in `app/` (repo-wide grep). The code *assumes* a private chat without enforcing it: `routers/files.py:82-84` deletes the user's uploaded message with the comment «در چتِ خصوصی مجاز است», and `routers/ops.py:532,603,757,773` do the same in the FSM flows. In a group without admin rights those deletes simply fail into their `except`, so nothing breaks — but the assumption is not a guarantee. Verified with the operator (2026-08-10): **the bot's Telegram privacy mode is ON**, so a file posted in a group is never delivered to the bot and the group-redistribution concern is closed today. The exception to keep in mind: **privacy mode does not apply once the bot is made an admin in a group** — at that point group uploads reach it, the card is posted by the bot for every member to see, and the `message.delete()` above now *succeeds*, leaving the bot's copy as the only visible one. So this protection is entirely outside the repo and one BotFather toggle (or one group promotion) away from changing. If group support is ever wanted, the chat-type distinction has to be made in code first.
- **Screening is I/O-bound, runs before every card, and holds an op slot while it waits — a capacity ceiling, not a bug.** Every uploaded image/video goes through `run_screen` before the card exists. Measured on a 198 MB video (2026-08-10): **`get_file` 10.3 s, frame extraction 1.1 s, inference 0.3 s** — so ~88% of it is one network fetch and the scan itself is ~1.4 s and roughly constant. On a large video the whole thing reached 94 s; on a small one 1.4 s. ClamAV and queue saturation were both ruled out from the logs.
  The distinction that decides the remedy: the worker is **waiting on the network, not burning CPU** — but it still occupies one of `max_jobs=4`, and those are the *same* four slots `run_op` uses, so a burst of uploads starves ordinary operations. Three structural facts: `run_screen` is enqueued with **no `_queue_name`** (`routers/files.py:74`) so it always lands on the master's default queue; it therefore **cannot offload to a processing node** even though `ProcessingWorkerSettings` registers it via inherited `functions`; and the fetch is unavoidable for pixel scanning because the Bot API offers no ranged read — we pull the whole file to sample 5 frames.
  **A card for an uploaded file is sent by `file_id`** (`cards.py:188`), so without screening the bot never needs the bytes at all. For a user who uploads and never runs an op, that fetch is pure added cost on the master's uplink; for everyone else it moves a cost that `run_op` would have paid later.
  Directions, re-listed for an I/O-bound cost: **give screening its own queue and worker**, so a 10 s network wait cannot hold an op slot — this is the only option that addresses the actual bottleneck; or raise `max_jobs` on the existing worker, cheaper but it lets screening and CPU work contend. Two things that look attractive and are not: **routing `run_screen` to a processing node would make it worse**, because a node runs `is_local=False` and `_localize` would pull the bytes across WireGuard (master uplink pays twice); and **trimming `safety_video_frames` or disabling the pixel layer buys ~1 s and ~1.4 s** respectively, not the 10 s that actually hurts. Skipping the pixel scan above a size threshold would work but trades away exactly the coverage the layer exists for. **Settle before user growth.**
  **Two halves of this were closed in phase 3c; the queue gate is what remains.** The model no longer loads on the user's first upload — `worker._warm_safety_model` warms it at worker startup — and the wait is no longer silent: `run_screen` now labels its phase (fetch vs scan) with an elapsed second count. Neither touches the capacity ceiling, which is still the open decision, and one interaction matters when it is taken: a **dedicated screening worker would load its own copy of the model (~81 MB)**, so warm-up and the queue split should be decided together rather than in sequence. The warm-up's `node_role == "processing"` skip is written against today's routing (`run_screen` has no `_queue_name`, so it cannot reach `arq:queue:proc`) and has to be re-read if screening ever gets its own queue.
  **The queue split (13b) was deliberately NOT built — decided 2026-08-12 by the operator, recorded here so it is a decision and not an oversight.** Today there are no nodes attached, upload volume is low, and a dedicated screening worker means a **second ~81 MB copy of the model** resident for a contention problem that is not currently observed. Building it now would buy nothing measurable and cost memory on the one machine we have. **Reopen when either condition actually holds:** upload volume genuinely starves `run_op` slots (the symptom is ordinary ops queueing behind screening jobs on `arq:queue`, not merely a slow single upload — a slow upload is the 10 s fetch, which the split does not shorten), **or** nodes come back, since the routing facts above were all written against a node-less master. Until then the fix on the table stays the queue split, not `max_jobs`, for the reason already given: raising `max_jobs` lets screening and CPU work contend instead of separating them.
- ~~**The 4G/mobile-proxy plan is half-blocked — gallery-dl cannot do socks without PySocks:**~~
  **closed 2026-08-12, shipped with item 11 as planned** (it rebuilds the download-node image, so the
  two had to land in one deployment). The asymmetry is worth keeping: **yt-dlp** ships its own
  `yt_dlp.socks` and needs nothing, while **gallery-dl** runs on `requests`, whose socks support lives
  in the optional `PySocks` — and gallery-dl is what fetches **Instagram**, the exact platform the
  mobile exit exists to protect. Measured before the fix: `InvalidSchema: Missing dependencies for
  SOCKS support`; after installing it, the same call reaches a real connection attempt. So a socks
  `PROXY_URL` would have given working YouTube and a hard failure on Instagram.
- ~~**The `7z` skip marker is the ffmpeg trap all over again, and this time it is live.**~~
  **CLOSED 2026-08-13 — and the premise was wrong: `ubuntu-latest` *does* ship `7z`, so that test has
  been running in CI all along and the marker was never dead.** The worry was mine, and a CI step
  disproved it in one run rather than any amount of reading. Worth keeping as a method note: the honest
  move was to *ask CI* instead of guessing, and asking turned a confident open question into a
  five-minute non-issue.
  **The same run also corrected the probe itself, which is the more useful lesson.** `7z --version` is
  not valid syntax — 7-Zip answers `Unknown switch: --version` and exits **7**, so a step written that
  way reports "binary missing" when the binary is present and the *question* was malformed. (`7zz` is
  genuinely absent; `7z` and `7za` both exist.) The step is now `7z i`, which prints the version header
  and exits 0, written without a pipe so the exit code belongs to `7z` rather than to `head`. Generalise:
  a presence probe that can fail for a second reason — wrong flag, wrong name, pipe swallowing the
  status — is not a presence probe, and its failure is not evidence of absence.
  The durable half is kept regardless, because it protects against a different failure: the gated test
  being deleted. `test_the_7z_gate_is_not_dead_weight` counts `needs_7z`-decorated functions **via AST**.
  Its first version was a regex and matched the `@needs_7z` written inside its own docstring, so removing
  the decorator still passed — vacuous, and the **third** instance of that same trap in one session; AST
  fixed it, verified by removing the decorator. The original reasoning is kept below.

  **The `7z` skip marker was the ffmpeg trap all over again.** `needs_7z` in
  `tests/test_phase2a.py` gates exactly one test — the archive-extraction test that pins 7-Zip's own
  path-traversal behaviour, i.e. the thing the `archive_extract` guard *depends on* being safe. Two
  halves are verified: CI installs **only** ffmpeg (the `apt-get install` step in
  `.github/workflows/tests.yml` names ffmpeg and nothing else), and unlike the ffmpeg marker there is
  **no dead-weight guard** — `test_the_ffmpeg_marker_is_not_dead_weight` in `tests/test_phase2b.py` has
  no `7z` counterpart. So the marker can go dead exactly the way ffmpeg's did from 2026-07 until phase
  2b, silently, for months. **What is not verified is whether the `ubuntu-latest` image ships `7z` on
  its own**, and that is the whole question: if it does, the test runs in CI and only my sandbox skips
  it; if it does not, that test runs **nowhere** and the 7-Zip behaviour we rely on is pinned by
  something that never executes. Deliberately not guessed at — the answer is one `7z --version` step in
  the workflow, which is precisely the shape the ffmpeg install already uses to prove presence rather
  than trust the runner's README. Fix either way: install `p7zip-full` explicitly **and** add the
  dead-weight guard, so both failure modes (absent binary, vanished marker) become loud. Recorded rather
  than fixed because it is CI topology and deserves its own reviewed change, and because it is
  pre-existing and unrelated to the work that surfaced it.
- **Nothing exercises `_MIGRATIONS` **in CI** — و این هنوز باز است، ولی از ۲۰۲۶-۰۸-۱۸ دستِ‌کم
  یک‌بار روی Postgresِ واقعی اجرا شده.** افزودنِ `ix_users_last_seen` با یک کلاسترِ محلیِ
  **Postgres 16.13** سنجیده شد (همان نسخهٔ اصلیِ `postgres:16-alpine`ِ compose): `init_models()`
  کامل اجرا شد، ساختِ ایندکس روی ۱۶۶۸ ردیف **۲٫۳–۳٫۴ میلی‌ثانیه** گرفت و اجرای دومِ
  `IF NOT EXISTS` صفر کار کرد. پس این یک اندازه‌گیریِ **دستی** بود، نه پوششِ خودکار — شکاف
  همان است که بود و رفعش همان: یک سرویسِ Postgres در CI به‌علاوهٔ یک تست که `init_models()`
  را بزند. متنِ اصلی برای تاریخ نگه داشته شد:

  **Nothing exercises `_MIGRATIONS` until deployment — a typo in the next migration surfaces on the
  master, at startup, in production.** Found while closing phase-3 item 9 and worth more than item 9
  itself. `init_models()` is called from exactly two places (`__main__.py:31`, `worker.py:28`), both
  production entry points, and **no test calls it** (repo-wide grep). So the `_MIGRATIONS` list is
  executed for the first time when the bot or worker boots against the real Postgres. Today's list is
  fine, but the failure mode is the point: a malformed `ALTER` is not a test failure, it is a crash
  loop on the master after `telabzar update`. It is also invisible to the current suite by
  construction — tests build SQLite schemas directly and never take this path, and they *cannot* take
  it, since the statements are Postgres-only (see `db.py`). The likely fix is a **Postgres service
  container in CI** (`services: postgres:16-alpine` in `.github/workflows/tests.yml`) plus one test
  that runs `init_models()` against it — which would also prove `create_all` and the migrations agree
  with `models.py`, something nothing checks today. Deliberately **recorded, not implemented**: it
  changes CI topology and deserves its own reviewed change.
- ~~**A second dead op handler — `thumb`:**~~ **closed 2026-08-11 — deleted as redundant with
  `screenshot`.** The comparison that decided it is worth keeping, because the obvious guess was wrong.
  `thumb` was **not** a duplicate of the `cover` button: those run in opposite directions — `cover`
  (`ops.py:928-970`) takes a photo the user *sends* and sets `file.cover_id`, entirely in the router
  with no worker job, while `thumb` produced a JPG *out of* the video. The real overlap was with
  **`screenshot`** (`tasks.py:389-393`), which returns the identical `{"send_media": {"as": "photo"}}`
  shape; the only difference was frame selection — a user-picked timestamp versus ffmpeg's `thumbnail`
  filter choosing a representative frame automatically. With the video menu already at 11 buttons, one
  tap saved did not justify a twelfth. Removed: the `_do_op` branch, the `OFFLOAD_OPS` entry,
  `btn_thumb`/`cl_thumb` in both locales, and `processing.video_thumbnail` — whose only caller was that
  branch. The internal need it might look like it served is covered by `video_poster`, which uses the
  same `thumbnail` filter at ≤320px for auto-generated download covers. `_KNOWN_UNREACHABLE` is now
  empty, and the guard still fails on any newly dead op (verified by sabotage).
- **Why does `wg0` exist but carry no IP? — unknown, and it blocks bringing nodes back.** Observed on the master (2026-08-10): after the nodes were deleted from the panel, the stack would not come up because `.nodes-enabled` was still present, so the CLI kept applying `docker-compose.nodes.yml`, whose `local-bot-api` binds `${WG_MASTER_IP:-10.51.0.1}:8081:8081` (`docker-compose.nodes.yml:20-22`) — and that bind fails when `wg0` has no address. The interface existed; the address did not. **Nothing in this repo explains that state** — `node/master-setup.sh` is what assigns the WG address, and whether it never ran to completion, ran before a reboot, or had its address removed later is not something the code can tell us. This has to be answered on the master (`ip addr show wg0`, `wg show`, the `[Interface] Address` line in `/etc/wireguard/wg0.conf`, the `wg-quick@wg0` unit state, and the systemd ordering drop-in the setup installs) **before** re-enabling nodes, because re-enabling means re-applying the same overlay that failed. Related and separately confirmed: **`.nodes-enabled` is create-only.** `node/master-setup.sh:125` `touch`es it and **no code path anywhere removes it** (repo-wide grep), while the CLI gates the overlay on mere file presence (`install.sh:176`) with no check that a `Node` row still exists. So deleting every node from the panel leaves the master still configured for WG-bound services. Renaming it (`.nodes-enabled.off`) is the current workaround; the real fix is either to have the panel/`master-setup.sh` own the flag's lifecycle, or to gate the overlay on something that reflects reality rather than on a file that is never cleaned up.

## Changelog
- 2026-08-20 — **اتصالِ کنسول (فازِ ۲): نُه صفحهٔ دیگر + فرم‌هایی که واقعاً POST می‌کنند.** **(۱ چرا اندپوینتِ جدا.)** `/api/console/<page>` کنارِ پیلودِ مشترک نشست نه داخلش: پوسته روی **هر** صفحه پیلودِ مشترک را می‌خواهد (نوارِ اعداد، مشِ ریل)، ولی دادهٔ ۲۱۹ رشتهٔ STRINGS را فقط STRINGS لازم دارد — ریختنشان در یک پاسخ یعنی هر صفحه هزینهٔ همهٔ صفحه‌ها را بدهد. نگاشت **صریح** است نه `getattr` روی نامِ صفحه، وگرنه یک مسیرِ کاربر می‌تواند هر تابعی را در ماژول صدا بزند؛ تستش همین را با `/_page_health` می‌سنجد. **(۲ قاعدهٔ مرکزی: قرض بگیر، بازننویس.)** هر سازنده از **همان** تابعی می‌خواند که صفحهٔ Jinja می‌خواند — `_users_cached`, `ck_pool.accounts`, `node_mod.list_live`, `_setting_groups`, `_texts_groups`, `_stats_cached`, `_languages`. اگر کنسول فهرستِ خودش را می‌ساخت، کلیدِ تازه در یکی ظاهر می‌شد و در دیگری نه — دقیقاً همان یک‌طرفه‌بودنی که شش کلیدِ تنظیمات را ماه‌ها نامرئی نگه داشت؛ `test_settings_groups_come_from_the_panel_not_a_second_list` مجموعه را با `RUNTIME_KEYS` مقایسه می‌کند. **و مهم‌ترین مصداقش کیبورد است:** نسخهٔ اولِ من ترتیب/مخفی/عرض را **بازنویسی** کرده بود، در حالی که `keyboards._resolved_menu` همان قاعده را دارد (به‌علاوهٔ «opِ تازه ته می‌رود») و `_rows_from_widths` بسته‌بندیِ ردیف را — و CLAUDE.md ثبت کرده که این قرارداد از قبل **هشت** کپیِ دست‌نویس بینِ JS و پایتون دارد. حالا سرور از خودِ `keyboards` می‌خواند، `widthCap` را هم می‌فرستد تا پیش‌نمایشِ زندهٔ کلاینت جدولِ ظرفیت را بازننویسد، و تستی هر دو را به منبعِ واقعی گره می‌زند — یکی کمتر از هشت، و اولین تستی که دو طرف را می‌بندد. **(۳ سه شکلِ درونی را حدس زدم به‌جای اینکه بخوانم، و هر سه ۵۰۰ دادند.)** `_users_list` کلیدِ `tg` می‌دهد نه `tg_user_id`، `_texts_groups` کلیدِ `items`/`current` می‌دهد نه `rows`/`val`، و `get_menu_layout` یک **لیست** برمی‌گرداند نه دیکشنری (و `get_button_style` یک **تاپل**). یک اسموکِ پارامتریِ نُه‌تایی هر سه را در یک اجرا گرفت — که ارزانش همین است: پیش از نوشتنِ یک خط UI، اول همهٔ سازنده‌ها را صدا بزن. **(۴ چیزی که ساخته شد چون منبع داشت: کارتِ جابِ گیرکرده.)** Open Questions می‌خواستش («جابی که سنش از هر `job_timeout`ی گذشته») و دادهٔ لازمش در `jobs` هست: `status ∈ {queued, running}` و `created_at` کهنه‌تر از بلندترین `job_timeout` به‌علاوهٔ حاشیه. تا امروز این‌ها در «در صف» جمع می‌شدند و از یک صفِ واقعی تفکیک‌ناپذیر بودند — یعنی «همیشه یکی هست» که همان «هیچ‌وقت نگاهش نکن» است. با **کنترلِ معکوس**: سه جابِ تازهٔ fixture نباید گیرکرده خوانده شوند، وگرنه کارت هر صفِ سالمی را قرمز می‌کند. **(۵ فرم‌ها.)** همه به هندلرهای **موجودِ** Jinja پست می‌کنند (`/save`, `/users/block`, `/cookies/add`, `/cookies/unfreeze`, `/texts/save`, `/texts/reset`, `/buttons/save`, `/buttons/reset`, `/nodes/add`, `/langs/import`, `/langs/delete`) — صفر هندلرِ تازه، پس اعتبارسنجی و اتمیک‌بودنِ ثبت‌شده دست‌نخورده می‌ماند. **جست‌وجو سمتِ سرور است** (کاربران و رشته‌ها) نه فیلترِ کلاینتی: صفحه‌بندی می‌شود، پس فیلترِ محلی فقط صفحهٔ جاری را می‌گردد و کاربری که در صفحهٔ دوم است «پیدا نشد» می‌گیرد — بدترین شکلِ نتیجهٔ غلط، چون شبیهِ جوابِ درست است. **(۶ سه چیز که فقط رندر نشان داد.)** صفحهٔ STRINGS با ۲۱۹ کلید **۱۸٬۴۲۱ پیکسل** شد؛ صفحهٔ فارسی همین را با گروهِ تاشو حل کرده و `_texts_groups` از قبل فلگِ `open` را می‌سازد (هنگام جست‌وجو همه باز، وگرنه فقط اولی) — پس همان فلگ فرستاده شد نه یک قاعدهٔ کلاینتیِ دوم، و حالتِ محلی فقط **انحراف** از تصمیمِ سرور را نگه می‌دارد وگرنه با عوض‌شدنِ جست‌وجو آن تصمیم خنثی می‌شد. دراپ‌داونِ `dl_ux_*` **خالی** رندر می‌شد چون مقدارِ خالی یک گزینهٔ واقعی است («تنظیم نشده») ولی بدونِ برچسب شکسته به‌نظر می‌رسد. و کارتِ دیسک روی محیطی که `/work` ندارد به‌جای صفر، «WORK_DIR NOT READABLE» می‌دهد. **(۷ تفکیک‌های صادقانه که نگه داشته شدند.)** سطلِ سشنی که هرگز پر نشده «سوخته» نیست، ولی فرمِ افزودن باید **همهٔ** سطل‌ها را بدهد وگرنه اولین اکانتِ یک سطلِ خالی اضافه‌شدنی نیست (`platforms` جدا از `unstocked`)؛ نودِ بدونِ heartbeat `DOWN` است حتی با ردیفِ DB؛ «تازه یا کهنهٔ» موتور عمداً قضاوت نمی‌شود چون مقایسه با PyPI یک درخواستِ شبکه می‌خواهد و بجِ حدسی از نبودش بدتر است. **(۸ اعتبارسنجی.)** پنل ۲۹۴ → ۳۲۹، اصلی ۹۵۳ بی‌تغییر. هر ده صفحه از پنلِ **واقعی** رندر شد: صفر خطای کنسول، صفر درخواستِ شکست‌خورده، صفر پاسخِ غیرِ۲xx. **و یک انتظارِ غلط در تستِ خودم:** `op_perf` را ۳ خواسته بودم و ۲ بود — `n` برابرِ `done + failed` است و جابِ در صف شمرده نمی‌شود. کد درست بود؛ کارت دربارهٔ کارِ **انجام‌شده** است و ریختنِ صف در آن نرخِ موفقیت را رقیق می‌کند. **اعمال:** `telabzar update` روی مستر — بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.
- 2026-08-20 — **اتصالِ کنسول به دادهٔ واقعی (فازِ ۱): `/api/console` + قاعدهٔ «هیچ سقوطِ بی‌صدا».** تا این پاس، کنسول روی اعدادِ `lib/data.ts` می‌دوید. **(۱ اندپوینت.)** `console_api` محاسبه را از `_stats_cached` و `_health` **قرض می‌گیرد** نه اینکه تکرار کند — پس کنسول و پنلِ فارسی نمی‌توانند دو عددِ متفاوت بدهند؛ کپیِ دومِ دست‌نویس همان واگرایی است که §۷ برای `remove_cookie_file` ثبت کرده. روی نبودِ نشست **۴۰۱ JSON** می‌دهد نه ریدایرکت، چون `fetch` نمی‌تواند ریدایرکت به صفحهٔ HTMLِ ورود را به چیزِ مفیدی تبدیل کند: بدنهٔ HTML با ۲۰۰ برمی‌گردد و کنسول سرِ `JSON.parse` با پیامی می‌شکند که هیچ ربطی به «نشستت تمام شده» ندارد. **(۲ قاعدهٔ مرکزی، و دلیلِ اینکه این کار بیشتر از یک fetch است.)** §۷ ثبت کرده «fallbackی که بی‌صدا به دادهٔ بی‌مصرف تنزل کند از خطا بدتر است»؛ در یک کنسولِ **عملیاتی** بدتر هم هست، چون اپراتور روی همان عددها تصمیم می‌گیرد. پس صفحه سه حالتِ **صریح** دارد (`loading`/`ready`/`error`)، شکست یک بنرِ قرمزِ تمام‌عرض می‌گیرد که می‌گوید «هر عددِ زیر placeholder است، نه سیستمِ تو»، و هرچه منبع ندارد در `_CONSOLE_GAPS` **نام برده می‌شود** و به‌جای عدد، علتش رندر می‌شود. سه شکافِ نام‌برده: جدولِ audit (وجود ندارد — نه در `models.py` و نه هیچ‌جای ریپو)، درصدِ پیشرفتِ جاب (در ورکر زندگی می‌کند نه DB)، و cpu/mem/net (`psutil` در هیچ requirements نیست). **(۳ و همین قاعده بلافاصله یک باگ در کدِ خودم گرفت — با رندر، نه با خواندن.)** شرطِ merge را روی *طولِ* آرایه گذاشته بودم (`api.platforms.length`)، پس روی سیستمِ بی‌دانلود «فهرست خالی» با «داده نداریم» یکی می‌شد و به دادهٔ نمایشی سقوط می‌کرد: کنارِ «۰ فایل» یک رادارِ پر با «YOUTUBE ۱۸٬۴۲۰» می‌نشست. دقیقاً همان سقوطِ بی‌صدایی که این لایه برای بستنش ساخته شده بود. همین شکل در `heroSub` هم بود (`?? cfg.kpis[2].value` → سیستمِ بی‌کار «۹۶٫۷٪ موفقیت» گزارش می‌کرد). هر دو با کنترلِ معکوسِ `test_an_empty_system_reports_zero_not_a_placeholder` پین شدند. **قاعدهٔ عام: در هر merge از «واقعی بر نمایشی می‌چربد»، شرط باید روی *حضورِ* پاسخ باشد نه روی *ناتهی‌بودنِ* محتوایش** — وگرنه دقیقاً سیستمِ خالی (تازه‌نصب، یا خرابِ واقعی) است که دادهٔ ساختگی می‌بیند. **(۴ سه چیزِ دیگر که فقط رندر نشان داد.)** `_human_size` واحد را داخلِ رشته می‌گذارد، پس واحدِ جدا «5.7 GB GB» می‌داد؛ کارتِ POSTURE جملهٔ «ALL CORE SYSTEMS NOMINAL» را **هاردکد** داشت و روی سیستمی با دو نودِ خواب هم همان را می‌گفت (حالا از شمارشِ واقعیِ سرویس/نود/سشن ساخته می‌شود و می‌تواند `DEGRADED` بدهد)؛ و سربرگِ کارتِ سشن‌ها «2 degraded» ثابت بود. **(۵ آنچه واقعی شد.)** KPIها، نمودارِ گذردهی (با تاریخِ واقعی)، رادار و جدولِ پلتفرم (با کلیدِ **خام** از سرور — `PLATFORM_HUE` روی نامِ انگلیسی کلید می‌خورد و برچسبِ فارسی باید از `<Fa>` رد شود، پس `_bars` حالا `key` را هم می‌فرستد)، عمقِ صف، دیسک، سرویس‌ها، استخرِ سشن، نودها، خطاها، **جریانِ جابِ واقعی** از جدولِ `jobs`، و **نقشهٔ فعالیتِ ۷×۲۴** از `File.created_at` (سطل‌بندی در پایتون، چون `extract(hour)` پستگرس-محور است و تست‌ها روی SQLite می‌دوند). **(۶ دو مرزِ صادقانه که عمداً برچسب خوردند نه پنهان شدند.)** ستونِ `OK%` جدولِ پلتفرم **فقط امروز** را می‌بیند (`dlstat` روزانه است) در حالی که `N` بازه‌محور است — دو پنجرهٔ متفاوت در یک جدول، همان چیزی که §۷ برای کارتِ سلامت ثبت کرده، پس ستون صریحاً برچسب خورد و نبودِ داده `—` می‌دهد نه `0%`. و جریانِ جاب یادداشتِ «downloads excluded (they create no Job row)» گرفت، چون با اعدادِ تولید ~۷۹٪ کار در آن فهرست نیست. **(۷ سریِ سومِ نمودار.)** لِجند `ERR` بود ولی `_stats` شکستِ جاب را per-day سطل‌بندی نمی‌کند؛ ریختنِ «کاربرِ تازه» در جای «خطا» یک دروغِ تمام‌عیار بود، پس سری صریحاً به `new users` تغییرِ نام داد. **(۸ اعتبارسنجی.)** تست‌ها: اصلی ۹۵۳ بی‌تغییر، پنل ۲۷۸ → ۲۹۴ (۱۶ تستِ تازه، همه روی **HTTPِ واقعی** نه صداکردنِ تابع — ادعا دربارهٔ اتصال است نه تابعِ کمکی). عددها با ردیف‌های **کاشته‌شده** سنجیده می‌شوند نه صفرِ DBِ خالی، چون «صفر» با «نرسید» تفکیک‌ناپذیر است. تستِ عمقِ صف روی **تفاضل** است نه مقدارِ مطلق، چون fixture خودش صف‌ها را پر می‌کارد و عددِ هاردکد به دادهٔ fixture گره می‌خورد. و کلِ زنجیره از پنلِ **واقعیِ** aiohttp با CSPِ واقعی و دادهٔ کاشته‌شده رندر شد: یک فراخوانیِ ۲۰۰، صفر خطای کنسول، صفر درخواستِ شکست‌خورده، و عددهای صفحه دقیقاً همان‌هایی که کاشته شدند (۹۱ فایل، ۲۳ کاربر، ۷۱٪، پنج پلتفرم با شمارشِ درست). **(۹ آنچه هنوز وصل نیست، صریح.)** نُه صفحهٔ دیگر هنوز روی `lib/pages.ts` می‌دوند و فرم‌ها POST نمی‌کنند؛ `WIRE MONITOR` و بارشِ آنتروپی عمداً تزئینی‌اند. **اعمال:** `telabzar update` روی مستر — بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.
- 2026-08-20 — **چاشنیِ خلاقیت: رنگِ ناحیه‌ای، سیجیل، و رنگِ پلتفرم — با یک قیدِ سخت.** درخواستِ کاربر «از رنگ‌های دیگر و آیکون‌های هکری استفاده کن» بود، و کارِ اصلی این بود که آن آزادی به **معنا** گره بخورد نه تزئین. **(۱ رنگ = مکان، نه سلیقه.)** `lib/zones.ts` سه لهجه می‌سازد — SYSTEM سبز (۰۱–۰۴)، CONTROL آبی (۰۵–۰۸)، PIPE بنفش (۰۹–۱۰) — و پوسته آن را به‌شکلِ `--zone`/`--zone-dim`/`--zone-glow` روی ریشه می‌گذارد، پس هر برچسبِ سکشن، دکمهٔ اصلی، تراشه و ردیفِ فعالِ ریل بدونِ یک خطِ تغییر همرنگِ صفحهٔ خودش می‌شود. سودش عملیاتی است نه زیبایی‌شناختی: در کنسولی که همهٔ صفحاتش یک قالب دارند، رنگِ زمینهٔ چشم می‌گوید «کجا هستی» پیش از آنکه سربرگ خوانده شود. **و قیدِ سختی که کلِ ایده را قابلِ‌دفاع می‌کند: رنگِ ناحیه هرگز جای رنگِ *وضعیت* را نمی‌گیرد.** خوب/هشدار/بد همان سبز/زرد/قرمزِ همیشگی می‌مانند؛ اگر ناحیه بر آن سوار می‌شد، صفحهٔ LANGS خطایش را بنفش نشان می‌داد و کلِ زبانِ وضعیت — تنها چیزی که اپراتور واقعاً با گوشهٔ چشم می‌خواند — از بین می‌رفت. **(۲ سیجیل.)** هر آیتمِ ریل یک نویسهٔ یونیکد گرفت (`◈ ⌁ ⏣ ⎔ ⧉ ⌬ ⛭ ⌸ ⌘ ⟐`) که در برچسبِ سکشنِ همان صفحه تکرار می‌شود، پس شکل و متن یک چیز می‌گویند. عمداً **نویسهٔ متنی** است نه SVG — همان فونتی که کلِ کنسول با آن کشیده شده، صفر بایتِ اضافه و صفر درخواستِ شبکه (که با CSPِ بی‌هاستِ خارجی هم می‌خواند). **و رندر یک چیز نشان داد که خواندن نمی‌داد:** در ۹٫۵px با `letter-spacing: .2em` این گلیف‌ها **ناخواناند**، چون از fallbackِ سیستم می‌آیند نه از زیرمجموعهٔ Vazirmatn؛ هر کدام `<span>`ِ خودش را گرفت با ۱۱٫۵px و `letterSpacing: 0`. **(۳ رنگِ پلتفرم.)** `PLATFORM_HUE` به هر پلتفرم یک ته‌رنگ می‌دهد و **همان** رنگ هم رئوسِ رادار را می‌سازد هم اسپارک‌لاینِ جدول — یعنی «آن قلهٔ صورتی» بی‌آنکه چشم به legend برگردد اینستاگرام خوانده می‌شود. رادار هم یک `radialGradient` گرفت به‌جای پرکردنِ تخت. **(۴ براکتِ گوشه.)** `◤◥◣◢` روی **یک** کارتِ هر صفحه — کارتِ کانونی — نه روی همه، وگرنه تأکیدی که همه‌جا باشد تأکید نیست. **(۵ و رگرسیونی که همین پاس ساخت و گاردِ کشف‌محور گرفتش.)** افزودنِ فیلدِ `sig` بینِ `n` و `label` در `nav.ts` کافی بود تا پارسرِ **ترتیبیِ** `tests/panel/test_console_nav.py` هیچ‌چیز جور نکند و فهرستِ تهی بدهد — یعنی هر دو ادعای پوششِ ناوبری بی‌صدا صادق شوند. اندازه‌گیری‌شده روی `nav.ts`ِ امروز: پارسرِ ترتیبی **۰** ردیف، پارسرِ نام‌محور **۱۰**. کنترلِ ضدِتوخالیِ `test_the_parser_actually_finds_the_nav` گرفتش و دقیقاً برای همین نوشته شده بود؛ ولی رفعِ درست «tolerate کردنِ `sig`» نیست — پارسر حالا فیلدها را **با نام** می‌خواند و کلیدِ ناشناخته را دور می‌ریزد، به‌علاوهٔ یک تستِ تازه که همان ردهٔ خطا را به‌عنوان **ادعا** پین می‌کند (سه شکلِ یک ردیف: امروزی، با کلیدِ تازه در وسط، با ترتیبِ برهم‌خورده). قاعدهٔ عام، هم‌ردهٔ §۶: **هر گاردی که یک فایلِ اعلانی را پارس می‌کند نباید به ترتیبِ کلیدها بند باشد** — فیلدِ بعدی حتماً اضافه می‌شود، و شکستش خاموش است. **اعتبارسنجی:** هر ده صفحه از پنلِ **واقعیِ** aiohttp با CSPِ واقعی رندر شد — صفر خطای کنسول، صفر درخواستِ شکست‌خورده، صفر پاسخِ غیرِ۲xx. تست‌ها: اصلی ۹۵۳ بی‌تغییر، پنل ۲۷۷ → ۲۷۸. **اعمال:** هنوز هیچ — این پاس فقط `panel/` و `tests/panel/` را لمس می‌کند و مثلِ دو پاسِ قبل با `telabzar update` (که کانتینرِ `admin` را دوباره build می‌کند) اعمال می‌شود؛ بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale.
- 2026-08-20 — **بقیهٔ پنل هم به کنسول آمد: ده صفحه، یک زبانِ طراحی.** پاسِ قبل فقط `01 OVERVIEW` را ساخته بود و نُه صفحهٔ دیگر همچنان Jinjaی فارسی بودند. **(۰ نگاشت، که تصادفی نبود.)** ریلِ ماکت ده آیتم دارد و پنل هم دقیقاً **ده صفحهٔ واقعی**، پس مو‌به‌مو نشستند بدونِ اختراعِ صفحه یا پنهان‌کردنِ یکی؛ `QUEUE`/`CACHE`ِ ماکت صفحهٔ مستقل نبودند و محتوایشان همان‌جا که بود ماند (داخلِ HEALTH و TRAFFIC). **(۱ پوسته، و چرا render-prop.)** ساعت، نوارِ متحرک، بارشِ آنتروپی و نوارِ اعداد روی **هر** صفحه زنده‌اند. اگر هر صفحه `useConsole` خودش را صدا می‌زد، دو حلقهٔ مستقل می‌شد و **عددِ صف در نوارِ بالا با عددِ همان صف در بدنه فرق می‌کرد** — یعنی کنسول به خودش دروغ می‌گفت. پس `Shell` تنها صاحبِ حلقه است و با تابع به صفحه می‌دهدش. **(۲ فارسی، قیدِ سخت.)** دادهٔ ربات فارسی است و پوسته LTR و مونو؛ فارسی داخلِ فونتِ مونو **حروفش به هم نمی‌چسبد** و داخلِ جعبهٔ `direction:ltr` ترتیبِ کلماتش برعکس می‌شود. `<Fa>` (فونتِ متنی + `dir=rtl` + ایزوله) تنها راهِ عبور است، و همان `Vazirmatn.woff2`ی را می‌برد که پنلِ فارسی از قبل دارد. **(۳ سه چیزی که رندر پیدا کرد و خواندن نمی‌کرد.)** کپشنِ پیش‌نمایشِ تلگرام یک رشتهٔ **ترکیبی** در جعبهٔ RTL بود، پس `📦 412 MB` را الگوریتمِ دوجهته وسط پرتاب کرد و شد `mp4 412 📦` — همان تلهٔ §۵، این‌بار در کدِ خودم؛ هر دنبالهٔ لاتین/عددی حالا `<bdi>`ِ ایزوله دارد. ستونِ «OK / N» در ۸۸ پیکسل جا نمی‌شد و دوخطی می‌شکست. و شش سطلِ خالیِ کوکی شش کارتِ تمام‌قد می‌گرفتند — که خودش همان **زنگِ خطای کاذبی** را بازتولید می‌کند که ماه‌ها هر ۶ ساعت DM می‌فرستاد؛ حالا یک سکشنِ تک‌خطیِ «not an alarm»اند. **(۴ گاردِ ناوبری، که بلافاصله یک اشتباهِ من را گرفت.)** ناوبری در TypeScript است و ناوبریِ Jinja در پایتون — دو فهرستِ دست‌نویس برای یک واقعیت، همان الگوی `remove_cookie_file`. شکستش **خاموش** است: صفحهٔ تازه در کنسول نامرئی می‌ماند و هیچ‌چیز قرمز نمی‌شود. `tests/panel/test_console_nav.py` هر دو جهت را می‌بندد، و اولین اجرایش `legacy: '/settings'` را رد کرد — چون پنلِ Jinja فرمِ تنظیمات را روی **خودِ `/`** رندر می‌کند. دقیقاً کاری که گارد برایش هست. **(۵ سرو کردنِ زیرصفحه‌ها، که `add_static` نمی‌توانست.)** خروجیِ Next هر صفحه را `<slug>/index.html` می‌دهد و استاتیکِ aiohttp دایرکتوری را باز نمی‌کند، پس **هر صفحه‌ای جز خانه ۴۰۴ می‌شد** — کلاسی از شکست که فقط با کلیک روی منو دیده می‌شود. یک هندلر برای کلِ زیردرخت جایش را گرفت: گِیتِ نشست روی **نوعِ فایل** است نه مسیر (HTML گِیت دارد، دارایی نه)، و گاردِ پیمایش ساختاری است (`resolve` + `is_relative_to`) نه فیلترِ رشته‌ای. `mimetypes.add_type("font/woff2")` هم اضافه شد چون پایتون نمی‌شناسدش. **(۶ یک تستِ خودم که لایهٔ اشتباه را می‌سنجید.)** نسخهٔ اولِ تستِ پیمایش انتها‌به‌انتها بود و افتاد — ولی نه چون گارد خراب بود: **کلاینتِ aiohttp مسیر را پیش از ارسال نرمال می‌کرد**، پس درخواست اصلاً به هندلر نمی‌رسید و چیزی که سنجیده می‌شد نرمال‌سازیِ کلاینت بود. طبقِ §۶ به سطحی منتقل شد که خودش تصمیم می‌گیرد، با کنترلِ معکوسِ «گاردی که همه‌چیز را رد کند هم صفر پیمایش می‌دهد». **تست‌ها: اصلی ۹۵۳ (بی‌تغییر)، پنل ۲۶۲ → ۲۷۷.** هر ده صفحه از پنلِ **واقعی** با CSPِ واقعی رندر شد: صفر خطای کنسول، صفر درخواستِ شکست‌خورده، صفر پاسخِ غیرِ۲xx، و ریلِ ده‌آیتمی روی هر ده. **(۷ آنچه عمداً انجام نشد.)** فرم‌ها هنوز POST نمی‌کنند و داده نمایشی است — قدمِ بعد `/api/console` است به‌علاوهٔ هدایتِ POSTها به هندلرهای موجود؛ جدا نگه داشته شد تا اول خودِ طرح تأیید شود. صفحاتِ فارسیِ Jinja دست‌نخورده‌اند و هر ردیفِ ریل با `legacy` به آن‌ها گره خورده. **اعمال:** فقط کانتینرِ `admin` → `telabzar update`. بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.
- 2026-08-20 — **کنسولِ `/console` با Next.js — بازسازیِ طرحِ ارسالیِ کاربر، این‌بار از روی سورسش نه از روی تصویر.** **(۰ ریشهٔ اشتباهِ قبلی، چون بدونش این کار تکرار می‌شود.)** ماکت یک بستهٔ خودبازشوندهٔ Claude Design بود و من از **اسکرین‌شات** قضاوتش کردم در حالی که سورسِ کاملش را تمامِ مدت داشتم. نتیجه‌اش این شد که رادار، مانیتورِ سیم، نقشهٔ ۷×۲۴، جریانِ جاب، بلوکِ آنتروپی، درخشش، کادرِ ۲پیکسلی و برچسبِ **روی خطِ** سکشن هیچ‌کدام ساخته نشدند. این‌بار بسته باز شد (`__bundler/template` + `manifest`) و هر عدد از همان‌جا آمد. **(۱ فونت.)** شش زیرمجموعهٔ woff2 از خودِ بسته استخراج شد؛ دو تای latin/latin-ext نگه داشته شد (۵۵KB) و چهار تای سیریلیک/یونانی/ویتنامی دور ریخته شد. **CSP هیچ هاستِ بیرونی‌ای نمی‌دهد، پس فونت باید محلی باشد** و نویسه‌های بلوکی (`▀█▄▚▸◂▁▂▃`) عمداً از fallbackِ سیستم می‌آیند چون در هیچ‌کدام از این زیرمجموعه‌ها نیستند — همان چیزی که در خودِ ماکت هم می‌افتد. **(۲ چرا `output: 'export'` و نه سرویسِ Node.)** قیدِ استقرار عوض نشد: خروجی HTML+JSِ ایستاست و همان aiohttp سرو می‌کند، پس **صفر رانتایمِ Node**، صفر تغییرِ `docker-compose.yml`، و احرازِ هویتِ فعلی (کوکیِ Fernet) دست‌نخورده. Node فقط در **زمانِ build** لازم است و مرحلهٔ جدیدش در `docker/admin.Dockerfile` در ایمیجِ نهایی نمی‌ماند. بدیلِ «خروجیِ build را کامیت کن» رد شد (باندلِ هش‌دار دیف را بی‌معنا می‌کند) و به‌جایش gitignore + مرحلهٔ Node + jobِ CI. **(۳ هیدریشن، که شکلِ کدِ زنده را تعیین کرد.)** طرح یک کلاسِ React با `Math.random` و `setInterval` بود. در خروجیِ ایستا این یعنی HTMLِ سرور با اولین رندرِ کلاینت فرق کند و React هشدار بدهد. پس **حالتِ اولیه کاملاً قطعی است** (`noise()` بذرمحور، نه `Math.random`) و هر دو تایمر فقط بعد از mount شروع می‌شوند؛ ساعتِ صفحه هم از شمارندهٔ `sec` ساخته می‌شود نه از `Date`. **(۴ اثباتِ وفاداری — سنجیده، نه ادعا.)** هر دو صفحه با همان مرورگر، همان پهنا و `device_scale_factor=2` رندر و **پیکسل‌به‌پیکسل** مقایسه شدند: ارتفاعِ صفحه در هر سه بریک‌پوینت **دقیقاً یکی** (۱۶۰۰→۴۱۰۸px، ۱۲۸۰→۶۴۳۲، ۹۰۰→۸۸۶۲) و اختلاف **۰٫۱۸٪ / ۰٫۱۵٪ / ۰٫۱۱٪** از سلول‌های نمونه‌برداری‌شده. و مهم‌تر از خودِ عدد، **محلِ** اختلاف: هر سه باندِ متفاوت دقیقاً همان‌هایی‌اند که زنده‌اند — نوارِ متحرکِ سربرگ، اعدادِ صفِ خطِ لوله، و زاویهٔ جاروبِ رادار. یعنی صفر اختلافِ ساختاری. **(۵ اثباتِ اتصال، که تستِ روت نمی‌دهدش.)** پنلِ **واقعیِ** aiohttp با CSPِ واقعی بالا آمد و کنسول از مرورگر باز شد: صفر خطای کنسول، صفر درخواستِ شکست‌خورده، صفر پاسخِ غیرِ۲xx، React سوار (۲ چندضلعیِ رادار، ۹ ردیفِ جاب، ۱۶۸ سلولِ نقشه = ۷×۲۴)، و `document.fonts.check` مثبت. اولین اجرا یک ۴۰۴ داشت (`/favicon.ico`) که با `app/icon.svg` بسته شد — کوچک، ولی ۴۰۴ در کنسولی که قرار است سلامتِ سیستم را نشان بدهد پیامِ بدی می‌دهد. **(۶ گِیت روی HTML، نه روی دارایی‌ها.)** `/console` بی‌نشست به `/login` می‌رود، ولی `_next/*` گِیت ندارد: JS/CSS/فونتِ ایستا هیچ دادهٔ کاربری‌ای ندارند، پس گیت‌زدنشان امنیتی نمی‌خرد و کشِ مرورگر را می‌شکند — همان تفکیکی که `/static` از قبل دارد. ترتیبِ ثبتِ روت‌ها **باربر** است: `add_get("/console")` باید پیش از `add_static("/console")` بیاید. **(۷ نبودِ build حالتِ عادی است نه خطا.)** ۵۰۳ با دستورِ ساختن، نه ۵۰۰: توسعهٔ محلی و هر ایمیجی که مرحلهٔ Node را رد کند دقیقاً همین‌جا می‌رسند، و traceback آن‌جا اپراتور را دنبالِ باگی می‌فرستد که وجود ندارد. **تست‌ها: اصلی ۹۵۲ → ۹۵۳، پنل ۲۵۴ → ۲۶۲.** گاردها همان درسِ `node/install.sh` را می‌بندند — چیزی که پنل از دیسک سرو می‌کند باید در ایمیج باشد — و چون خروجی gitignore است، **در ریپو اصلاً وجود ندارد**، پس بدونِ گارد تنها نشانه‌اش ۵۰۳ روی تولید بود: `test_the_admin_image_builds_the_console_it_serves` (با کنترلِ خودارجاعی، چون خودِ Dockerfile کامنتِ فارسی دارد که همان واژه‌ها را نام می‌برد)، `test_the_console_build_output_is_not_committed` و کنترلِ معکوسش `test_the_console_source_is_committed`. jobِ **موازیِ** `console` در CI هم `npm ci && next build` می‌زند، چون بدونش یک خطای TypeScript تا لحظهٔ `telabzar update` پنهان می‌ماند. **(۸ آنچه عمداً انجام نشد.)** کنسول امروز روی دادهٔ **نمایشی** می‌دود، نه روی Postgres/Redisِ واقعی — قدمِ بعد یک `/api/console`ِ JSON است که همان شکلِ `lib/types.ts` را بدهد؛ عمداً جدا نگه داشته شد تا اول خودِ طرح تأیید شود. صفحاتِ فارسیِ فعلیِ پنل هم دست‌نخورده‌اند و RTLِ خودشان را دارند. **اعمال:** فقط کانتینرِ `admin` این کد را اجرا می‌کند → `telabzar update` روی مستر (ایمیج دوباره build می‌شود و مرحلهٔ Node کنسول را می‌سازد). بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.
- 2026-08-19 — **استخراجِ قالب‌ها و CSS از `admin_web.py` — «هیچ‌چیز عوض نشد» و اثباتش.** دو کامیت، صفر تغییرِ رفتاری: قالب‌ها به `app/templates/*.html` (۱۲ فایل، ۶۰٬۲۵۳ بایت) و استایل به `app/static/css/panel.css` (۱۲٬۷۰۸ بایت). `admin_web.py` از **۳۳۲۳** به **۲۲۷۶** خط رسید (−۳۲٪، دقیقاً همان سهمی که سرشماریِ ASTی پیش‌بینی کرد: ۹۲۷ خطِ قالب + ۱۳۵ خطِ CSS). **(۰ اثبات، و این کلِ ارزشِ فاز است.)** پیش از هر تغییری، HTMLِ رندرشدهٔ هر ۱۰ صفحه از یک worktreeِ دست‌نخوردهٔ `HEAD` snapshot شد (۴۱۲ KB)؛ بعد از هر دو کامیت دوباره، و `diff -r` صفر اختلاف داد. هارنس **بیرونِ ریپو** زندگی می‌کند و در هر دو درخت کپی می‌شود تا خودش نتواند منبعِ اختلاف باشد. **چهار پینِ لازم، هرکدام چون اندازه‌گیری نشان داد مقدار به HTML می‌رسد:** `datetime`ِ `admin_web` (تاریخ‌های `/stats`، کلیدِ `dlstat`ِ `/health`)، `time.time` (`_ago_fa` روی `/cookies` — و متاهای خودِ fixture هم از ساعتِ واقعی مهر می‌خوردند، پس هر دو سر پین شد)، `shutil.disk_usage` (که ضمناً شاخهٔ `{% if health.disk_total %}` را **اجرا** می‌کند — در سندباکس `/work` وجود ندارد و آن شاخه مرده بود)، و `last_seen` با مقادیرِ **متمایز** چون `ORDER BY last_seen` تای‌بریکر ندارد و مقدارِ یکسان ترتیب را به موتور می‌سپارد. کنترلِ منفی اثبات می‌کند پین‌ها باربرند (بدونشان `/users` می‌جنبد)، و جابه‌جاکردنِ پین به ۲۰۲۰-۰۱-۰۲ نشان داد **هر** تاریخِ رندرشده دنبالش می‌رود یعنی نشتِ ساعتِ دیوار صفر است. **(۱ مهم‌ترین یافتهٔ فاز، و ربطی به استخراج ندارد: کامیتِ خودم یک گاردِ موجود را بی‌اثر کرد.)** `test_the_panel_has_no_external_resources_for_the_csp_to_break` فقط `app/admin_web.py` را می‌خواند؛ اندازه‌گیری‌شده **هر ۲۰** موردِ `href=`/`src=` در ثابت‌های قالب بود و **صفر** در بقیهٔ فایل. یعنی با رفتنِ قالب‌ها، آن تست فایلی را اسکن می‌کرد که هیچ‌کدام را ندارد و **برای همیشه سبز** می‌ماند — هیچ تستی قرمز نمی‌شد و هیچ رفتاری عوض نمی‌شد. شبیه‌سازی شد: `assert not external` روی فهرستِ تهی پاس می‌شود. دامنه **کشف‌محور** شد و **دو** کنترل گرفت (CDNِ کاشته‌شده گرفته می‌شود؛ و دامنه واقعاً قالب‌ها را می‌بیند — وگرنه «صفر منبعِ خارجی» می‌تواند یعنی «صفر فایلِ اسکن‌شده»). **و سرشماری هم شد، نه فقط این یکی:** از ۱۰ تستی که `admin_web.py` را به‌عنوان متن می‌خوانند، ۹ تا تابع/لیترالِ پایتونی را هدف می‌گیرند و مکانیکی تأیید شد که روی فایلِ پس‌از‌استخراج زنده می‌مانند. **(۲ قیدِ بسته‌بندی، اجراشده نه استدلال‌شده.)** `docker/admin.Dockerfile` فقط `COPY app` و `COPY node` دارد. با ساختنِ چیدمانِ کانتینر: `app/templates` رندر می‌شود، `templates/`ِ ریشهٔ ریپو `TemplateNotFound` می‌دهد — یعنی **۵۰۰ روی هر صفحه با CIِ سبز**، چون تست از ریشهٔ ریپو می‌دود جایی که پوشه هست. همان حادثهٔ `node/install.sh`. گاردش ریشه‌های `COPY` را از خودِ Dockerfile کشف می‌کند و کامنتِ `#` را **قبل** از تطبیق دور می‌ریزد. **(۳ CSS از فایل خوانده می‌شود ولی همچنان inline تزریق می‌شود — تصمیم، نه نصفه‌کاری.)** `<link>` هم بایتِ HTML را عوض می‌کند و هم **سه** خوانندهٔ مستقلِ `<style>`ِ همان پاسخ را می‌شکند (`test_panel_css_classes`، `_rule_for`ِ `test_cookie_status_badges`، و پیش‌شرطِ `test_security_headers`): اندازه‌گیری‌شده ۱۵ شکست اگر فقط این برود و ۱۹ اگر تگ کلاً برود. طرحِ سند `<link>` بود؛ رد شد و صفر تست شکست. **(۴ سه چیزِ ریز که با اجرا پیدا شدند.)** Jinja **دقیقاً یک** خطِ پایانی می‌خورد، پس `_LANGS` که خودش با `\n` تمام می‌شد نباید یکی دیگر می‌گرفت — قاعده «اگر ندارد اضافه کن» شد و گاردِ per-file دارد؛ `_HEALTH_CARDS` که الحاقِ **رشته‌ایِ پایتون** در دو جا بود `{% include %}`ِ واقعی شد و `test_page_contract` از قبل هر دو صفحه را می‌سنجید؛ و کامنتِ CSP تصحیح شد چون می‌گفت script یک بلاکِ inline دارد در حالی که **۸ نقطه در ۵ قالب** است (بلاکِ `<script>` + ۷ هندلرِ رویدادِ درون‌خطی). **(۵ و گاردِ خطِ پایانی همان روز یک آلودگیِ واقعی گرفت — مالِ خودم.)** یک پروبِ دستی یک `\n` به `base.html` اضافه کرده بود و `git checkout` برنگرداندش، چون `app/templates/` هنوز **untracked** بود و `git checkout`ِ مسیرِ untracked بی‌صدا هیچ نمی‌کند. دفترچهٔ سابوتاژ لو داد (موردی که باید تستِ A را می‌انداخت، تستِ B را انداخت)، فایل از منبعِ اصلی بازتولید شد و اثباتِ بایت‌یکسان **دوباره** گرفته شد. **(۶ و یک کنترلِ منفیِ توخالیِ خودم، که سابوتاژ ردش کرد.)** کنترلِ «پارسر کامنت را نمی‌شمارد» با یک `# COPY ghost` نوشته شده بود — ولی `re.match` به ابتدای خط لنگر می‌خورد، پس آن خط از هر حال رد می‌شود و برداشتنِ حذفِ کامنت هیچ‌چیز را نمی‌شکست. سابوتاژ «نگرفت» داد و **درست می‌گفت**؛ کنترل به کامنتِ **انتهای خط** عوض شد که واقعاً به حذفِ کامنت بند است. **تست‌ها: پنل ۲۳۰ → ۲۵۲، سوییتِ اصلی ۹۶۲ بی‌تغییر. ۸ موردِ سابوتاژِ تازه، هر ۸ طبقِ ثبت.** **آنچه عمداً انجام نشد (تصمیمِ اپراتور):** حذفِ ۵ گروهِ CSSِ مرده و ۲ توکنِ مرده — بایتِ `<style>` را عوض می‌کند و از اثبات بیرون می‌افتد؛ در Open Questions با خطوطشان ثبت شد، به‌همراه ۸ کپیِ دست‌نویسِ قراردادِ کیبورد، ۷ هندلرِ inline، بلوکه‌کنندهٔ `*{font-family}`، شکل‌بودنِ `999px`/`50%`، و معناییِ `.nav a.on{box-shadow}`. **اعمال:** `cd /root/telabzar && telabzar update` — فقط کانتینرِ `admin` این کد را اجرا می‌کند. بدونِ مهاجرت، بدونِ کلیدِ runtime، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.
- 2026-08-19 — **فاز C: سمتِ ربات — انتخابِ زبان، منوی تنظیمات، آموزش. به‌علاوهٔ گاردِ پاریتیِ کاتالوگ، که یک باگِ **زندهٔ** فاز B بود.** فاز B زبان را در DB گذاشت و `t()` استفاده‌اش می‌کرد، ولی هیچ کاربری نمی‌توانست انتخابش کند. **(۰ شناسایی، و دو فرض با اجرا تصحیح شد.)** سرشماریِ نویسنده‌های `users.lang`: **دقیقاً یکی** (`routers/start.py`)، و `middlewares.py:24` ردیفِ کاربر را روی **هر آپدیتی** می‌سازد بدونِ ست‌کردنِ زبان — پس `lang=NULL` حالتِ عادیِ کسی است که هرگز `/start` نزده (تولید: **۵۵ از ۱۷۷۱ ≈ ۳٪**، fa=1623، en=93). و `start.py:32` آخرین تاپلِ هاردکدِ `("fa","en")` در کلِ `app/` بود؛ تنها تطبیقِ دیگر یک **کامنت** در `admin_web` است. **(۱ فهرستِ زبان، یک سازنده نه دو.)** `routers/` نمی‌تواند `admin_web` را import کند (ایمیجِ ربات jinja2/cryptography ندارد) و `textstore` نمی‌تواند `i18n` را import کند چون جهتِ وابستگی برعکس است — پس **تنها ماژولی که هر دو نیمه را می‌بیند `i18n` است** و سازنده به `i18n.available_languages()` رفت؛ `admin_web._languages()` حالا واگذار می‌کند و یک گاردِ ASTی بازسازی را می‌گیرد. خانه با جهتِ وابستگی تعیین شد نه سلیقه. `lang_keyboard` **sync ماند** و فهرست را پارامتر می‌گیرد — همان الگوی `cookies.Limits`: خواندنِ async یک‌بار در هندلر، عکسِ فوری به پایین. **(۲ `ORDER BY` — تصمیمِ اپراتور، و شرطِ درستی است نه آراستگی.)** `select(Language)` بی‌ترتیب بود، پس منویی که قرار است صد هزار کاربر ببینند می‌توانست بینِ دو رندر جابه‌جا شود. حالا `ORDER BY name, code`؛ dropdownهای `/texts` و `/buttons` هم از arbitrary به الفبایی رفتند — **تغییرِ اعلام‌شده، نه قاچاقی**. تست روی **DBِ واقعی** است با ردیف‌هایی که عمداً برعکسِ الفبا درج می‌شوند، نه grep روی سورس. **(۳ سازگاریِ عقب‌رو، که طرح را عوض کرد.)** وسوسه این بود که `Lang` یک فیلدِ `src` بگیرد. اندازه‌گیری‌شده روی aiogram 3.30: `unpack('lang:fa')` روی کلاسِ دوفیلدی **`TypeError`** می‌دهد **حتی با مقدارِ پیش‌فرضِ پایتونی**، پس هر کاربری که لحظهٔ استقرار منوی بازی روی صفحه دارد یک دکمهٔ چرخانِ بی‌جواب می‌گیرد. `Lang` تک‌فیلدی ماند و تفکیک از **حالت** مشتق شد (`user.lang` پیش از نوشتن تهی بود یا نه). سالم است چون تنها راهِ رسیدنِ کاربرِ زبان‌دار به آن منو تنظیمات است. **(۴ گزینهٔ (پ) — حذفِ یک دروغِ زنده.)** `language_set` لفظیِ per-language بود و برای زبانِ ترجمه‌نشده به انگلیسی می‌افتاد: `t('es','language_set')` عیناً «Language set to English ✅» می‌داد. تأیید **بصری** شد (منوی بعدی به زبانِ تازه). کلید **حذف نشد** — بسته‌های موجود دارندش و حذف یعنی همه یک کلیدِ اضافه پیدا کنند؛ و نسخهٔ placeholder-دار هم رد شد چون `require_all_placeholders` هر بستهٔ موجود را رد می‌کرد. تستِ کنترلِ معکوس خودِ دروغ را پین می‌کند تا اگر روزی صادق نبود، حذفِ تأییدیه بازبینی شود. **(۵ گاردِ پاریتی — مستقل از فاز C، باگِ زندهٔ فاز B.)** گرپ نشان داد **صفر** assert روی برابریِ کلیدها در کلِ `tests/`؛ ادعای §۷ یک اندازه‌گیریِ یک‌باره بود. شکست **خاموش** است: `TEXT_KEYS` اجتماعِ دو کاتالوگ است، پس کلیدِ یک‌طرفه حذف نمی‌شود بلکه با **متنِ زبانِ اشتباه** واردِ بسته می‌شود (اجراشده: `default_text('en', <کلیدِ فقط-فارسی>)` → متنِ فارسی). سه ادعای کشف‌محور، و کنترلِ منفیِ هرکدام جدا گرفته شد تا هر assert **فقط** حالتِ خودش را بگیرد، نه شات‌گان. **(۶ زبانِ حذف‌شده.)** اجراشده با **کنترلِ مثبت** (نسخهٔ اولِ پروب یک صفتِ ناموجود ست می‌کرد و بی‌صدا هیچ نمی‌کرد — همان بنچِ مرده‌ای که §۶ می‌گوید سابوتاژ نمی‌گیردش): کاربر بی‌صدا انگلیسی می‌شود و `users.lang` روی کدِ مرده می‌ماند. تا پیش از این **راهِ برگشتی نداشت**، چون `cmd_start` منو نشان نمی‌دهد — یعنی منوی تنظیمات تنها راهِ خروج است، نه یک قابلیتِ تزئینی. اعتبارسنجیِ per-update عمداً ساخته نشد. **تست‌ها (۹۲۳ → ۹۴۹؛ jobِ پنل ۲۳۰ بی‌تغییر):** هندلرها با `Message`/`CallbackQuery`ِ **واقعیِ** aiogram روی `ValidatingBot` رانده می‌شوند و DB واقعی است (SQLite)، چون ادعای «کاربرِ قدیمی دوباره پرسیده نمی‌شود» دربارهٔ یک **ردیفِ ذخیره‌شده** است. سوییت یک‌بار با استکِ پنلِ **غایب‌شده** هم اجرا شد (نزدیک‌ترین تقریبِ رانر) — ۹۴۹ سبز، و قلاب با کنترل اثبات شد که واقعاً `ModuleNotFoundError` می‌دهد. **۱۶ موردِ سابوتاژِ تازه + ۲ کنترلِ معکوس.** **و یکی از آن‌ها یک ضعفِ واقعی در تستِ خودم پیدا کرد که ارزشش از خودِ رفع بیشتر بود:** ادعای «کلیدهای خوش‌آمد از فهرستِ اعلانی می‌آیند» انتظارش را از همان `HOME_ITEMS` می‌ساخت که سابوتاژ ویرایشش می‌کند، پس با حذفِ یک آیتم **هر دو طرف** کوچک می‌شدند و سبز می‌ماند (چهار تستِ **دیگر** افتادند، نه آن یکی). نمونهٔ پنجمِ «گارد توضیحاتِ خودش را می‌خواند»، این‌بار بدونِ هیچ نثری — قاعده‌اش در §۶ ثبت شد: ادعای مشتق‌شده از یک منبعِ اعلانی، **تغییرِ** آن را می‌گیرد و **کوچک‌شدنش** را نه، پس یک ادعای لفظیِ جدا لازم دارد. **و یک رُتِ پیش‌موجود از #۱۲۹ که همین پاس لو داد:** الگوی موردِ `panel/users: the header stops counting` (`{{total}} کل`) با آمدنِ سربرگِ `{{total}} کلیدِ متن` در صفحهٔ `/langs` **پیشوند** شد و دو بار جور می‌شد. با مقایسه روی `origin/main` (که هنوز فاز B را ندارد) اثبات شد که مالِ من نیست: main یک تطبیق، مرجِ فاز B دو تا. لنگرِ `{%` یکتایش کرد. **اعمال:** `cd /root/telabzar && telabzar update` — **بدونِ مهاجرت** (`users.lang` از فاز B `String(16)` است و جدولِ `languages` هست)، بدونِ کلیدِ تنظیمات، بدونِ `node/update.sh` (رشته‌های تازه فقط از پروسهٔ ربات صدا زده می‌شوند)، و بدونِ تغییرِ رفتار برای کاربرِ زبان‌دار جز افزوده‌شدنِ کیبورد.
- 2026-08-19 — **فاز B: چندزبانه‌سازی از راهِ export/import — یک فایل، یک چت‌بات، یک زبانِ تازه.** صاحبِ پنل متن‌ها را برای فارسی ساخته و می‌خواهد فایل بگیرد، بیرون ترجمه کند و برگرداند. **(۰ صورتِ مسئله با اجرا تصحیح شد، و از خودِ کار مهم‌تر بود.)** فرض این بود که «افزودنِ زبان» یعنی دست‌زدن به `t()`؛ اندازه‌گیری خلافش را نشان داد: `i18n.py:25` override را با `(lang, key)` می‌خواند **بدونِ هیچ عضویت‌سنجی**، پس `t('es', …)` از قبل کار می‌کرد. آنچه واقعاً می‌بست، **۸ تاپلِ هاردکدِ `("fa","en")`** بود (کشفِ AST روی کلِ `app/`: ۷ در پنل، ۱ در `start.py`) به‌علاوهٔ `CATALOG` و دو جفت `<option>` در قالب‌ها. پس این PR هستهٔ ترجمه را لمس نکرد و فهرستِ زبان را **داده‌محور** کرد. اثرِ امروزِ آن گیت‌ها هم اندازه‌گیری شد نه استدلال: `?lang=es` بی‌صدا به fa **ریدایرکت** می‌شد و `POST /texts/save` با زبانِ ناشناخته «کلیدِ نامعتبر» می‌داد — پیامی که علتِ غلط را نام می‌برد. **(۱ fallback — تنها تغییرِ رفتار که همهٔ زبان‌ها را می‌گیرد.)** کلیدِ ترجمه‌نشده حالا به **انگلیسی** می‌افتد نه فارسی. اندازه‌گیریِ پیش از تصمیم: با ۲ کلید از ۲۱۴، `t('es','btn_convert')` مقدارِ `'تبدیل فرمت'` می‌داد. برای fa/en بی‌اثر است (پاریتی دقیق: ۲۱۴ کلید، صفر یک‌طرفه) و کنترل همین را پین می‌کند. **(۲ فایل.)** JSON با پاکت، و **export == import** پس اصلاحِ یک ترجمهٔ بد همان حلقه است. حجمِ سنجیده‌شده **۱۷٬۶۹۱ بایت** برای ۲۱۴ کلید؛ نامزدهای دیگر با عدد رد شدند (`{source,target}` دو برابر و یک حالتِ شکستِ اضافه؛ TSV چون ۱۲ رشته خط جدید دارند). دستورِ کار **داخلِ خودِ فایل** است چون مصرف‌کننده یک چت‌بات است، و خواندن نسبت به فنسِ ```` ```json ````/BOM/فاصله بردبار است. **کدِ فرم حاکم است و کدِ فایل فقط مقایسه می‌شود** — مدل می‌تواند `"lang"` را بی‌خبر عوض کند و ترجمه زیرِ زبانِ غلط بنشیند. **(۳ import: اتمیک، با فهرستِ کلید و دلیل)** — همان استدلالِ `buttons_save`. **و یک گاردِ تازه که از یک شکافِ اندازه‌گیری‌شده آمد:** `validate()` فقط placeholderِ **اضافه** را رد می‌کند، پس حذفِ کاملِ `{mb}` مجاز است و شکستش کاملاً خاموش — متن سالم می‌ماند و عدد هرگز نمی‌رسد. `require_all_placeholders=True` فقط در مسیرِ import روشن است؛ قاعدهٔ `/texts` عمداً دست‌نخورده ماند و **کنترلِ معکوس** همین را می‌سنجد. قرارداد از متنِ **مبدأ** می‌آید نه کاتالوگ، وگرنه ترجمهٔ درستِ یک مبدأِ ساده‌شده رد می‌شد. **(۴ تصمیم‌های اپراتور.)** ادغام پیش‌فرض، جایگزینیِ کامل پشتِ تیک؛ import روی `fa` مجاز ولی با **تأییدِ صریح** که می‌گوید چند کلید عوض می‌شود / چند تا همان است / چند تا در بسته نیست، و پیشِ تأیید **صفر ردیف** نوشته می‌شود (کنترلِ معکوس: زبانِ غیرپیش‌فرض تأیید نمی‌خواهد). **(۵ کدِ زبان: فرمت، نه طول — تغییرِ اپراتور در طرح.)** `String(2)` قفل نشد؛ هر سه ستون به `String(16)` رفتند و گارد روی الگوی BCP 47 است با شکلِ کانونیک (`pt-br` → `pt-BR`) — نرمال‌سازی شرطِ **درستی** است نه آراستگی، وگرنه دو زبانِ جدا می‌شوند و ترجمه نصف. **این تنها PRِ اخیر است که مهاجرت دارد**، و هزینه‌اش با اجرا سنجیده شد نه فرض: عریض‌کردنِ varchar روی ۲۰۰٬۴۲۸ ردیف / ۵۸ مگابایت **۲٫۹ ms** و filenodeِ جدول و ایندکسِ PK **عوض نشد** (catalog-only، مستقل از تعدادِ ردیف)؛ **کنترلِ منفی**: باریک‌کردنِ همان ستون **۲۰۵۱ ms** و filenodeِ هر دو عوض شد. رهرسالِ کاملِ استقرار روی Postgres 16.13 اجرا شد — schemaی قدیم ساخته شد، ۱۷۳۴ کاربر و ۲ override کاشته شد، `init_models()`ِ کدِ تازه در **۷۷ ms** هر سه ستون را عریض کرد و `languages` را ساخت، ردیف‌ها دست‌نخورده ماندند، `pt-BR` پذیرفته شد، و اجرای دوم no-op بود. **(۶ تلهٔ سکو، ثبت‌شده.)** Postgres کدِ بلند را رد می‌کند و **SQLite نه** — و `tests/panel` روی SQLite است، پس گاردِ طول/فرمت باید در پایتون باشد وگرنه تست سبز و تولید ۵۰۰ می‌دهد. **(۷ UI حداقلی، به‌قیدِ فازِ بعد.)** صفحهٔ خودبسندهٔ `/langs` + یک خطِ nav + ۴ مسیر؛ `/texts` — بزرگ‌ترین قالبِ پنل — دست نخورد. و روی هم HTMLِ هاردکد **کم** شد: دو جفت `<option>` به `{% for %}` تبدیل شد و `.ta` از بلاکِ per-pageِ کوکی‌ها به `_CSS` رفت (دو مصرف‌کننده). **گاردِ کلاسِ CSS همان اولین اجرا `.ta`ِ تعریف‌نشده را گرفت** — دقیقاً کاری که برایش هست. **(۸ تست: اصلی ۸۷۳ → ۹۲۳، پنل ۲۰۲ → ۲۳۰.)** و یک اجرای اضافه با استکِ پنل **غایب‌شده** (نزدیک‌ترین تقریبِ محلیِ رانر): ۹۲۳ سبز. کنترلِ آن هم گرفته شد — درختِ پیش از تغییر زیرِ همان قلاب ۸۷۳ می‌دهد، و خودِ قلاب زنده بودنش اثبات شد. **یک ریزه‌کاری که اولین تلاش را بی‌اعتبار کرد:** قلابِ اول `ImportError` می‌داد و PyJWT فقط `ModuleNotFoundError` را می‌گیرد، پس **۲۵ خطای collect** روی هر دو درخت داد — یعنی «تقریبِ رانر» باید ماژول را **غایب** کند نه **ممنوع**. منطقِ خالص عمداً در سوییتِ **اصلی** است نه `tests/panel`، چون jobِ پنل جداست و قاعده‌ای که فقط آن‌جا تست شود نصفِ CI را بی‌پوشش می‌گذارد. `/langs` به `PAGES` اضافه شد پس گاردِ کلاس و قراردادِ صفحه رایگان پوشش دادند. **۲۴ موردِ سابوتاژِ تازه، ۲۴/۲۴ طبقِ ثبت — ولی دو «نگرفت» سرِ راه آمد و هیچ‌کدام تستِ ضعیف نبود؛ هر دو ارزشِ ثبت دارند چون دو ردهٔ متفاوت‌اند.** **(الف) کنترلِ معکوسِ بدهدف:** آن را روی **همان فایلی** گذاشته بودم که تست‌های خودِ fallback در آن است، و `expect: None` یعنی «هیچ تستی در فایلِ هدف نیفتد» — پس سابوتاژی که عمداً آن سه تست را می‌اندازد کنترل را هم می‌انداخت. قاعده: **کنترلِ معکوس باید فایلی را هدف بگیرد که ادعایش واقعاً «بی‌اثر» است**، نه فایلی که ادعای اصلی هم در آن است. با هدف‌گرفتنِ `tests/test_langpack.py` (مبدأش fa است، پس هر دو زنجیره یک جواب می‌دهند) ادعا همانی شد که مقصود بود. **(ب) سابوتاژی که لایهٔ دیگری را زد:** موردِ «re-export از زبانِ پیش‌فرض شروع کند» **لینکِ ردیف** را در قالب عوض می‌کند، ولی تستِ من URL را **خودش می‌ساخت** — پس ادعا دربارهٔ هندلر بود و سابوتاژ دربارهٔ قالب، و «نگرفت» از بیرون شبیهِ تستِ ضعیف بود. رفع در **تست** است نه در دفترچه: لینک از خودِ صفحه برداشته و دنبال می‌شود، یعنی همان چیزی که ادمین می‌زند. این نسخهٔ وارونهٔ «سابوتاژی که می‌افتد ولی چیزِ همسایه را می‌شکند» است — این‌بار سابوتاژ درست بود و **ادعا** یک لایه آن‌طرف‌تر بود. **(۹ مرزِ فاز، صریح.)** بعد از این PR زبان در DB هست و `t()` استفاده‌اش می‌کند، ولی **کاربر نمی‌تواند انتخابش کند**: `routers/start.py:32` و `keyboards.py:90` عمداً دست‌نخورده‌اند. **اعمال:** `telabzar update` روی مستر؛ بدونِ `node/update.sh` (هیچ نودی `admin_web` را اجرا نمی‌کند) و بدونِ گامِ دستی — مهاجرت را `init_models()` سرِ استارتِ ربات/ورکر می‌زند. **قیدِ ترتیب:** `admin_web` مهاجرت اجرا **نمی‌کند**، پس اگر کسی فقط کانتینرِ `admin` را ری‌استارت کند و بلافاصله کدِ بلند import کند تا ری‌استارتِ ربات ۵۰۰ می‌گیرد؛ `telabzar update` همه را با هم بالا می‌آورد. **(flakeِ از‌قبل‌ثبت‌شده:** `test_settings_rename.py::…[16]` یک‌بار با `database is locked` افتاد و بعدش ۳ از ۳ منفرد و ۱ از ۱ کاملِ دوباره سبز بود؛ `settings_store.set()` در این برنچ لمس نشده.)
- 2026-08-19 — **پوششِ قالب‌های پنل، پیش از هر بازآرایی. صفر تغییر در `app/`.** گامِ ۲ از کارِ پنل: پیش از اینکه گامِ ۳ (بازطراحیِ `/health`) و گامِ ۵ (بازطراحیِ کامل) قالب‌ها را دست بزنند، اول سنجیده شد چه چیزی اصلاً نگهبان دارد. **(۱ اندازه‌گیری، نه حافظه)** بدنهٔ `{% block body %}`ِ هر قالب جدا خالی شد (برشِ کاراکتری از AST، نه رجکس) و سوییت اجرا شد؛ دو اجرای مستقل، هر ۹ عدد یکسان. نتیجه: `_TEXTS` **صفر** نگهبانِ محتوا داشت، و `_HEALTH` شش تست می‌انداخت که **پنج‌تایش عیناً همان پنج‌تای فرگمنتِ مشترکِ `_HEALTH_CARDS` بود** — یعنی بدنهٔ اختصاصیِ `/health` هم صفر بود، دقیقاً همان صفحه‌ای که گامِ بعد بازطراحی‌اش می‌کند. **(۲ و بخشی از آن عدد اصلاً پوششِ محتوا نبود)** گاردِ کلاسِ CSS روی **هر هشت** صفحه با بدنهٔ خالی دقیقاً **۱۳ کلاس** (کلِ chromeِ `_BASE`) رندر می‌کند و روی کفِ `len(used) >= 15` می‌افتد، **هرگز** روی `assert not missing`. پس یک چکِ «صفحه ساخته شد؟» است نه نگهبانِ محتوا؛ کارِ واقعی‌اش سرِ جایش است. **(۳ سابوتاژِ ریزدانه، که ریسکِ واقعی را نشان داد)** «بدنه را خالی کن» درشت‌ترین ویرایشِ ممکن است؛ ریسکِ یک بازطراحی افتادنِ **یک واقعیت** است. سیزده حذفِ واقع‌بینانه سنجیده شد و **۱۲ تا خاموش** بودند: کلِ فهرستِ نودها، کلِ فهرستِ متن‌ها، کلِ ردیفِ opها و کلِ کارتِ خطاها می‌توانستند ناپدید شوند و سوییت سبز بماند. **(۴ شکلِ ادعاها)** روی **مقدار** بسته شده‌اند نه مارک‌آپ، و مقدارِ انتظاری از همان تابعی می‌آید که هندلر صدا می‌زند (`_health`, `_stats`, `_texts_groups`, `cookies.accounts`, `OPS_BY_KIND`, `_KIND_TABS`) نه هاردکد — پس بازآراییِ کارت سبز می‌ماند و افتادنِ واقعیت قرمز می‌شود. وگرنه این تست‌ها به‌جای نگهبان، مالیاتِ گامِ ۵ می‌شدند. عددهای کاشته‌شده عمداً سه‌رقمی و متمایزند، چون در صفحه‌ای پر از نرخ و نسخه و گیگابایت «۲ در صفحه هست» ادعای ضعیفی است. **(۵ هلپرِ مشترک و تلهٔ خودارجاعی)** `pagefacts.page_text` سه کانالی را که ارسال می‌شوند ولی دیدنی نیستند دور می‌ریزد — `<style>` (و **۶ کامنتِ CSS**ِ داخلش)، `<script>`، و `<!-- -->` (امروز صفر، ولی بازطراحی می‌تواند اضافه کند). کنترل‌ها مستقیماً **خودارجاعی** را می‌زنند نه صرفاً «چک می‌تواند بیفتد» — که ادعای ضعیف‌تری است و همین تله را یک‌بار از کنترل رد کرد. **(۶ و همان تله یک پله بالاتر، که تازه است)** سه نمونهٔ قبلی همه در **سورسِ** گارد بودند؛ این‌بار در **داده**: تستِ کارتِ «پرکاربردترین عملیات» با خالی‌شدنِ کاملِ آن کارت هم سبز ماند، چون متنِ توضیحیِ خودِ صفحه همان واژه‌ها را به‌عنوان مثال می‌نویسد و جدولِ همسایه هم همان برچسب‌ها را دارد (`op_perf["op"]` از قبل فارسی است، `admin_web.py:1694` — تصحیحِ ادعای خودم که «خام» نوشته بودم). سه منبع برای یک توکن؛ رفع، محدودکردنِ ادعا به **کارت** است. **(۷ دو لایهٔ مستقل، اندازه‌گیری‌شده)** متنِ دکمه در `/buttons` دو بار رندر می‌شود (جعبهٔ ویرایش + پیش‌نمایشِ زنده)، پس سابوتاژِ هر لایه ادعای انتها‌به‌انتها را نمی‌انداخت و «نگرفت»ش شبیهِ تستِ ضعیف بود. هر دو با تفکیکِ لایه بسته شدند. **(۸ دو تستِ موجود که ضعیف‌تر از ادعایشان بودند)** `test_the_unproven_status_dot_is_visible` و `test_the_status_dot_stayed_red` روی بدنهٔ خالی سبز ماندند: `"s-unproven" in html` با قاعدهٔ `.s-unproven{…}`ِ داخلِ `<style>` جور می‌شود، پس هر دو روی صفحه‌ای **بدونِ هیچ ردیفِ اکانت** هم صادق‌اند. **باگ نبودند** — ادعایشان دربارهٔ تعریفِ کلاس درست است — ولی نیمهٔ «دیده می‌شود» اثبات نشده بود؛ `_dots_rendered` همان نیمه را می‌بندد و یک تستِ کشف‌محور وضعیتِ هشتمِ فردا را هم می‌گیرد. خواهرشان `_badge_class` از اول درست بود چون الگو را در **مارک‌آپ** می‌جوید. **نتیجهٔ سنجیده‌شده:** درشت `۲۵/۸/۶/۳/۶/۱/۶/۴/۵` → `۲۵/۱۱/۱۴/۸/۱۲/۸/۱۸/۸/۱۱`؛ ریزدانه **۱ از ۱۳ → ۱۳ از ۱۳**. تست‌های پنل ۱۳۱ → ۱۸۳، سوییتِ اصلی **بی‌تغییر** (۸۷۳، با مقایسهٔ مستقیم روی کامیتِ پایه تأیید شد نه با فرض). **۲۵ موردِ سابوتاژِ تازه در `tests/sabotage.CASES`، هر ۲۵ طبقِ ثبت** (شاملِ یک کنترلِ معکوس و سه مورد روی خودِ هلپر). **اعمال: هیچ‌چیز** — فقط `tests/`؛ بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ استقرار. **و یک درسِ عملیاتی:** `nohup … &` با اجرای پس‌زمینهٔ هارنس ترکیب شد، هارنس «تمام شد» گفت در حالی که پروسه هنوز می‌دوید، و یک `git checkout` سابوتاژِ در جریان را برداشت. چون از بیرون معلوم نبود کدام مورد آلوده شده، کلِ اجرا دور ریخته و تکرار شد — اجرای دوم هر ۹ عدد را عیناً بازتولید کرد. **(۹ تطبیق با §۴٫۵ سندِ بازطراحی، بعد از رسیدنِ سند)** اول یک قید: سند **پیش از PR #126** نوشته شده — §۴٫۶ باگِ بی‌رنگیِ `.err`/`.mute` را «زنده» می‌خواند و مبنایش «۹۴ تست» است، در حالی که #۱۲۶ همان را بست. پس از شش تستِ پیشنهادی‌اش: **#۳ (هر کلاسِ استفاده‌شده تعریف شده باشد) از قبل انجام شده** (`test_panel_css_classes`، #۱۲۶) — با یک تفاوتِ باقی‌مانده که ثبت می‌شود: نسخهٔ #۱۲۶ صفحهٔ **رندرشده** را می‌خواند، پس کلاسی که فقط در شاخهٔ اجرانشدهٔ یک `{% if %}` باشد از کنارش رد می‌شود؛ در عوض کلاسِ **پویا** (که از پایتون می‌آید، مثلِ `_badge_of`) را می‌گیرد و نسخهٔ قالب‌خوان نمی‌گرفت. **#۱ و #۵ واقعاً باز بودند و همین‌جا بسته شدند** — با اجرا تأیید شد نه با فرض: هر ۸ صفحه روی دادهٔ خالی از قبل ۲۰۰ می‌دادند و فرگمنتِ سلامت روی `/` هم رندر می‌شد، ولی **هیچ تستی هیچ‌کدام را assert نمی‌کرد**؛ `test_page_contract.py` هر دو را می‌بندد، به‌علاوهٔ یک کنترلِ معکوس که یک‌طرفه‌شدنِ فرگمنت را می‌گیرد. **#۲ و #۶ مالِ PRِ استخراج‌اند نه این یکی**: هر دو وضعیتِ **پس از** انتقال را توصیف می‌کنند (`/static/css/panel.css` امروز وجود ندارد و قالبی بیرونِ `app/` نیست)، پس نوشتنشان امروز یعنی یک تستِ همیشه‌قرمز یا یک تستِ توخالی. **#۴ (ایزولهٔ رشته‌های لاتین) باز ماند، با دلیلِ اندازه‌گیری‌شده:** نمونه ساخته و روی هر ۸ صفحه اجرا شد و ۲۴ مورد علامت زد که **بیشترشان مثبتِ کاذب‌اند** — و مهم‌ترین‌شان علت را نشان داد: چهار برچسبِ تاریخِ نمودارِ `/stats` واقعاً ایزوله‌اند، ولی نه با کلاس بلکه با قاعدهٔ `.ts-x span{…unicode-bidi:isolate}` (`admin_web.py:773`). یعنی گاردِ درست باید ایزوله‌بودن را از **استایل‌شیت** و با تطبیقِ سلکتور استنتاج کند، نه از فهرستِ کلاس‌های هاردکد؛ و تفکیکِ «دو توکنِ لاتین» از «عدد کنارِ حرف» هم لازم است، چون فقط دومی جابه‌جا می‌شود. کارِ مستقلی است با شواهدِ خودش، نه ضمیمهٔ این PR.
- 2026-08-18 — **شمارندهٔ فازِ probe — فقط اندازه‌گیری، صفر تغییرِ رفتاری.** فازِ probe گران است و در هیچ عددی دیده نمی‌شود؛ تصمیمِ اپراتور این بود که **اول شمارنده، بعد رفع**، چون شکلِ رفعِ حفرهٔ `_charge` به نرخِ رهاشدن بستگی دارد و ۲٪ یعنی تئوریک و ۶۰٪ یعنی فوری. **(۰ شناسایی)** هر چهار هزینهٔ ثبت‌شده روی `ac315dd` با AST تأیید شد نه با خواندنِ چشمی: بلوکِ probe `tasks_download.py:812–911`، تنها `_metric`ِ داخلش `:866` با `ok=False`، و پنج نقطهٔ خروج. **(۱ سه یافته که طراحیِ اولیه را عوض کردند.)** **الف — «موفق/ناموفق» دوتایی کافی نیست، سه‌تاست:** خروجی‌های ردِ سنی و «مدت زیاد» probeِ **موفق**اند که هرگز به منو نمی‌رسند، پس هرگز pick‌شدنی نیستند؛ ریختنشان در سطلِ «ok» یعنی هر لینکِ سنی/بلند «رهاشده» شمرده شود — یعنی دقیقاً عددی که کلِ تصمیم رویش بناست غلط دربیاید. سطلِ `blocked` جداست و کنترلِ اصلیِ سوییت همین است. **ب — «جاب» با «کوکی» یکی نیست:** حلقهٔ چرخش تا `dl_max_cookie_tries` بار موتور را صدا می‌زند، و سؤالِ واقعی مصرفِ منبع است، پس `attempt` سطلِ خودش را دارد (سؤال چهارتا بود نه سه‌تا). **پ — یک منو می‌تواند چند pick بدهد** (کامنتِ خودِ `run_download`)، پس تفاضلِ خام می‌تواند **منفی** شود. **(۲ نشانگر، و دو ابهامی که با هم حل می‌کند)** `probemenu:{ref}` با `DELETE`ِ یک‌بارمصرف: هم dedupe را دقیق می‌کند و هم — رایگان — ابهامِ cancel را می‌بندد. `Dl(sel="cancel")` **دو** تولیدکننده دارد (`download_menu_kb` و `download_cancel_kb`) و از روی callback تفکیک‌پذیر نیست، ولی cancelِ فازِ fetch نشانگر ندارد پس خودبه‌خود شمرده نمی‌شود. در مقابل `Dl`ِ **غیرِcancel** ابهام ندارد: `download_menu_kb` تنها تولیدکننده‌اش است و تنها محلِ فراخوانی‌اش شاخهٔ probe (هر دو با grep تأیید شد). **و `probe:{ref}` عمداً بازاستفاده نشد** با اینکه هیچ‌جای ریپو خوانده نمی‌شود: پاک‌کردنش سرِ pick، آن نسبتِ ثبت‌شده در §۷ را بی‌صدا از «سهمِ probe» به «سهمِ probeِ رهاشده» تغییرِ معنا می‌دهد. **(۳ جای شمارنده باربر است)** `pick` **پیش از** خواندنِ `dlctx` می‌نشیند، چون منقضی‌شدن/سقفِ روزانه/اصابتِ کش هر سه «کاربر دکمه را زد»اند و شمردنِ دیرتر همان‌ها را به «رهاشده» نشت می‌دهد؛ و در **روتر** است نه ورکر، چون pickِ کش‌خورده هیچ جابی نمی‌سازد. **(۴ خانهٔ هلپر یک قید است نه سلیقه)** `routers/download.py` نمی‌تواند از `tasks_download` قرض بگیرد (ایمیجِ ربات `processing`/`instagram_anon` ندارد) و کپیِ دومِ دست‌نویس همان واگراییِ `remove_cookie_file` است، پس `app/probe_stats.py` بی‌وابستگی ساخته شد — دقیقاً الگوی `dl_active.py`. **(۵ سه منبعِ خطا، صریح و ثبت‌شده)** مرزِ روزِ UTC با کرانِ ۳۰ دقیقه (پس **چندروزه** بخوان، نه تک‌روز — همان تلهٔ کارتِ سلامت) · `_edit` که استثنا را می‌بلعد و شاخهٔ منوی متنی را باد می‌کند (شاخهٔ عکسی این نقص را ندارد) · و `repick` که pickِ دوم را با pickِ پس از انقضا قاطی می‌کند. **تست‌ها (۸۵۶ → ۸۷۲):** ۱۶ تست، همه از **مسیرِ واقعی** — `run_download`ِ واقعی با `yt-dlp`ِ اجرایی روی PATH، و `on_dl_pick`ِ واقعی با `CallbackQuery`ِ واقعیِ aiogram؛ صداکردنِ مستقیمِ هلپر تابعِ کمکی را تست می‌کند و **اتصال** را نه، همان شکافی که `test_probe_cookie_blame` برای بستنش نوشته شد. **و همین یک شکاف در هارنسِ مشترک باز کرد:** `ValidatingBot` نمی‌توانست پشتِ یک `CallbackQuery`ِ واقعی بنشیند چون aiogram شیءِ متد را خودش می‌سازد و `bot(method)` می‌زند؛ `__call__` اضافه شد و آن مسیر از `bind_like_aiogram` **قوی‌تر** است، چون مدل را خودِ aiogram ساخته و اعتبارسنجی کرده. **تریپ‌وایرِ «فقط اندازه‌گیری»** هر چهار هزینهٔ probe را پین می‌کند (سطلِ ساعتی، `dl_active`، `dlq:cnt`/`dlq:cd`) تا «کمکِ» بعدی مجبور شود تصمیم را صریح بگیرد نه اینکه سوارِ یک PRِ اندازه‌گیری برود. **۱۱ موردِ سابوتاژِ تازه، ۱۱/۱۱ طبقِ ثبت**، شاملِ یک کنترلِ معکوس (برداشتنِ شمارندهٔ `menu` نباید ادعاهای سمتِ روتر را بیندازد) و یک سابوتاژ که خودِ تریپ‌وایر را می‌سنجد (افزودنِ `note_spend` به مسیرِ probe باید قرمز کند). **دو تستِ خودم اولش غلط بودند** و هر دو با اجرا معلوم شد نه بازخوانی: فیلترِ «منو» پیامِ «در حالِ بررسی…» را هم می‌گرفت، و تستِ شارژ روی مسیرِ **منقضی** می‌رفت که اصلاً به `_charge` نمی‌رسد. **یافتهٔ جانبیِ ثبت‌شده (رفع نشد):** فرمِ خطای تازهٔ یوتیوب «The page needs to be reloaded.» که `classify_error` آن را `unrelated` می‌خواند — در پنجرهٔ **یک‌ساعتهٔ** لاگ هر ۴ شکست همین بود و صفر bot-check، ولی آن کسر مخرج ندارد؛ به نسخهٔ yt-dlp و به pot ربط ندارد و گذراست (همان ویدیو بعداً با همان کوکی OK داد). در فازِ probe هم می‌افتد، پس همان کلاسی است که سطلِ `fail` می‌شمارد. **و یک تصحیحِ مستندات طبقِ قاعدهٔ ۵:** `s["queued"]` مقدارِ `queued + running` است نه فقط `queued`؛ به‌علاوهٔ تحلیلِ جاب‌های گیرکرده (علتِ ساختاری: `finally` روی SIGKILL اجرا نمی‌شود؛ و **به probe ربطی ندارد** چون ردیفِ `Job` فقط در `routers/ops.py` ساخته می‌شود) با احتمالِ دومش برچسب‌خورده «حدس، اجرا نشده». **اعمال:** `telabzar update` روی مستر. `tasks_download.py` روی نودِ دانلود هم می‌دود، پس اگر نودی وصل شد `node/update.sh` هم لازم است — و **تا آن لحظه این اعداد فقط مسترند**، همان تلهٔ ثبت‌شده برای `dlstat:iganon:*`. بدونِ مهاجرت، بدونِ کلیدِ تنظیمات، بدونِ رشتهٔ locale، بدونِ تغییرِ پنل.
- 2026-08-18 — **سه باگِ کوچکِ پنل در یک PR — و دو تا از سه صورتِ مسئله تصحیح شد پیش از رفع.** **(۱ بجِ بی‌رنگ)** `.mute` هیچ‌جا تعریف نشده بود و `.err` فقط در `_LOGIN` بود (آن هم یک **بلوکِ** خطا با padding، نه بج). اندازه‌گیری‌شده با رندرِ **هر ۹ صفحهٔ GET** و دنبال‌کردنِ هر کلاس در `<style>`ِ همان پاسخ: **دقیقاً سه کلاسِ بی‌تعریف، هر سه فقط در `/cookies`** — `err`, `mute`, و `s-unproven` که در گزارش نبود و همان سه‌خط CSS بود. بقیهٔ پنل تمیز بود، پس گاردِ کشف‌محور امروز صفر نویز دارد. **تصحیحِ صورتِ مسئله:** «ادمین کوکیِ مرده را نمی‌بیند» اغراق بود — نقطهٔ ۹پیکسلیِ `.s-invalid` قرمز است و کار می‌کرد؛ چیزی که بی‌رنگ بود *متنِ* برچسب بود، و یک تستِ اختصاصی همان تفکیک را نگه می‌دارد. رفع: `.err` (فقط رنگ، هم‌شکلِ `.ok`/`.warn`/`.dim` — نه بلوکِ لاگین، وگرنه بج padding ارث می‌برد؛ روی `/login` ترتیبِ `{{css}}`ِ اول یعنی نسخهٔ آن‌جا همچنان برنده و صفحهٔ ورود بی‌تغییر است)، `mute` → `dim` (کلاسِ موجود، واژگان بزرگ نمی‌شود)، و `.s-unproven`. **و قیدِ اپراتور که طراحی را عوض کرد:** `mute` هم به «غیرفعال» می‌رفت هم پیش‌فرضِ ناشناخته‌ها بود، پس یکی‌کردنِ هر دو با `dim` یعنی «ادمین عمداً خاموشش کرد» و «وضعیتی که نمی‌شناسیم» یک شکل شوند — پیش‌فرض `unk`ِ بنفش شد (عمداً بیرونِ خانوادهٔ سبز/زرد/قرمز/خاکستری)، رنگِ پایهٔ `.sdot` هم همان، و دو کپیِ دست‌نویسِ `.get(..., "mute")` در `_badge_of()` یکی شدند. **(۲ شش کلیدِ نامرئی)** از ۶۷ کلیدِ runtime، شش‌تا در هیچ صفحه‌ای نبودند: `proxy_url`, `dl_max_duration_min`, `dl_daily_mb`, `dl_cooldown_sec`, `dl_op_daily_min`, `dl_min_free_gb`. هر شش‌تا **زنده‌اند** (ردیابیِ محلِ خواندن: همه از `settings_store`، پس بدونِ ری‌استارت اثر دارند) و از `/admin`ِ تلگرام قابلِ تنظیم بودند — فقط پنل نمی‌دیدشان؛ و `git log -S` نشان داد هرگز در `GROUPS` نبوده‌اند، یعنی فراموشی نه حذف. **علت یک گاردِ یک‌طرفه بود:** `test_every_panel_row_is_a_real_runtime_key` فقط جهتِ GROUPS ⊆ RUNTIME_KEYS را می‌سنجد و جهتِ دیگر هرگز نوشته نشد. رفع سه لایه است چون فقط لایهٔ سوم دوام می‌آورد: ردیفِ برچسب‌دار برای همان شش‌تا، به‌علاوهٔ `_setting_groups()` که ته‌مانده‌ها را **خودکار** رندر می‌کند، به‌علاوهٔ اینکه **هم صفحه هم `save()`** از همان تابع بخوانند — وگرنه ردیفِ خودکار رندر می‌شود و بی‌صدا ذخیره نمی‌شود، همان «بنرِ سبز روی کاری که انجام نشد» که کلِ خوشهٔ B را ساخت. گروهِ خودکار امروز **خالی** است و متنش در UI نق می‌زند نه در CI. `proxy_url` سطحِ تازه‌ای باز نمی‌کند: `is_safe_url_resolved` از فاز ۳ت برای هر دو نوعِ پروکسی fail-closed است. **(۳ شمارشِ Job)** **صورتِ مسئله تصحیح شد و این مهم‌ترین بخشِ تشخیص بود:** «۳۳٪ · ۱ از ۳»ِ ساندکلاد از `Job` نمی‌آمد؛ تنها جایی که این شکل را رندر می‌کند کارتِ سلامت است که `dlstat` را **محدود به روزِ جاریِ UTC** می‌خواند، در حالی که `_metric` با TTLِ **دو روز** می‌نویسد — پس مقایسهٔ یک روز با دو روز بود، نه شکافِ Job (و `Job` اصلاً ستونِ platform ندارد، پس هیچ کارتی per-platform از آن نمی‌سازد). اپراتور تأیید کرد که `dlstat` را با پنجرهٔ دوروزه خوانده بود. **ولی شکافِ Job واقعی و جداست:** `Job()` فقط در `routers/ops.py` ساخته می‌شود و `tasks_download.py:7` صریح می‌گوید دانلود ردیفِ Job ندارد — یعنی طراحیِ عمدی، ولی نتیجه‌اش این است که هشت سطحِ `/stats` صفر دانلود می‌بینند در حالی که «فایل · N از لینک» روی همان نوار از `files` می‌آید و همه‌شان را دارد (اندازه‌گیری‌شده روی هارنس: «فایل ۱۵ · ۱۰ از لینک» کنارِ «عملیات ۵»؛ در تولید ۳۲۰۴ از ۴۰۵۰ در برابرِ ۱۰۱۶ جاب ⇒ ~۷۹٪ نامرئی). سه گزینه با هزینه روی میز رفت و **تصمیمِ اپراتور «برچسبِ صریح» بود** — «مسئله گمراهی است نه نبودِ عدد»؛ ساختنِ Job با هزینه‌اش (مهاجرتِ nullable، مسیرِ داغ، `node/update.sh`، و اینکه دادهٔ گذشته را نمی‌سازد) در Open Questions ثبت شد. برچسب‌ها روی مرزِ **منبعِ داده** نشستند نه موضوع، و برچسبِ کارتِ نرخِ دانلود هم به «امروز (UTC)» رفت چون روزِ تهران با روزِ UTC یکی نیست. **تست‌ها (پنل ۹۴ → ۱۳۰؛ سوییتِ اصلی ۸۵۶ بی‌تغییر):** چهار فایلِ تازه، همه روی **HTMLِ رندرشده** نه تابعِ کمکی — قیدِ اپراتور، و بجا: پیش از این `tests/panel` فقط `/`, `/nodes`, `/users`, `/buttons` را می‌زد و `/cookies`/`/stats`/`/texts` هرگز رندر نمی‌شدند. fixtureِ `seeded` یک ردیف به‌ازای **هر شاخهٔ رندر** می‌کارد، و یک تستِ جدا (`test_the_seeded_pages_really_carry_the_risky_markup`) صریح می‌سنجد که آن شاخه‌ها واقعاً ساخته شده‌اند — وگرنه «صفر کلاسِ تعریف‌نشده» می‌تواند صرفاً یعنی «صفر کلاس». `/login` **بدونِ کوکی** گرفته می‌شود، وگرنه به `/` ریدایرکت می‌شود و تست داشبورد را دوباره می‌سنجد (در پروبِ اول دقیقاً همین شد و فقط با شمردنِ کلاس‌ها معلوم شد). **۱۹ موردِ سابوتاژِ تازه، همه طبقِ ثبت**، از جمله چهار کنترلِ معکوس — مهم‌ترینش «گروهِ خودکار را بردار» که باید دو ادعای دوام را بیندازد و ادعای پوششِ امروز را **نه** (چون شش ردیفِ دستی جایش را پر می‌کنند)، و «یک کارتِ files-محور را اشتباهی برچسب بزن» که ثابت می‌کند تستِ برچسب «رشته هرجای صفحه هست» را نمی‌سنجد. **و بزرگ‌ترین چیزی که این کار یاد داد در خودِ گارد بود:** اولین سابوتاژِ گاردِ کلاس «نگرفت» داد در حالی که خرابکاری کاملاً اعمال شده بود — کامنتِ فارسی‌ای که خودم بالای `.err` نوشتم عبارتِ «`.err`» را دارد، کامنتِ CSS داخلِ `<style>` **ارسال می‌شود**، و چک آن را «تعریف‌شده» می‌خواند. نه تستِ ضعیف بود و نه سابوتاژِ ناموفق، بلکه ردهٔ سومِ §۶ (ابزارِ سنجش نتیجهٔ درست را غلط می‌خواند) و سومین نمونهٔ «گارد خودش را می‌گیرد» بعد از دو گاردِ ASTی که داکس‌استرینگِ خودشان را می‌گرفتند؛ رفعش (دور ریختنِ کامنت) کنترلِ منفیِ خودش را دارد و موردِ سابوتاژِ خودش را. **اعمال: `telabzar update` روی مستر.** فقط `app/admin_web.py` عوض شده (به‌علاوهٔ `tests/` و مستندات) — **بدونِ migration، بدونِ کلیدِ تنظیماتِ تازه، بدونِ رشتهٔ locale، بدونِ `node/update.sh`.** هیچ عددی جابه‌جا نشد: بخشِ ۳ فقط متن است و تستی صریح همین را قفل می‌کند.
- 2026-08-18 — **دستهٔ C و D از ممیزیِ پنل: سقفِ نرخِ لاگین، بلاک‌شدنِ داشبورد پشتِ pot-provider، و صفحهٔ کاربران.** سه کارِ مستقل در سه کامیت. **(۱ لاگین — تنها موردِ امنیتی)** اول اندازه گرفته شد، و فرضِ شروع غلط بود: محدودیت **وجود داشت** — ۵ درخواستِ کد در ۶۰۰ ثانیه و ۶ حدس در ۳۰۰ ثانیه — ولی `auth_request` شمارندهٔ حدس را پاک می‌کرد، پس بودجهٔ واقعی **۳۰ حدس در هر پنجره** بود (اندازه‌گیری‌شده، نه محاسبه‌شده)، یعنی ~۷۹٪ در یک سالِ حملهٔ پیوسته. سه نقصِ مشخصِ همان اجرا: `auth_verify` شناسه را با `admin_id_set` نمی‌سنجید (۲۰۰ شناسهٔ دلخواه از یک IP → ۲۰۰ کلیدِ `paneltry:` و صفر رد)، هیچ سقفی روی **مبدأ** نبود، و مقایسهٔ کد زمان‌ثابت نبود. **رفع، و چرا این شکل:** بودجهٔ حدس به **کد** بسته شد نه به اندپوینت — تمام‌شدنش کد را می‌کشد به‌جای اینکه مسیرِ verify را ۳۰۰ ثانیه ببندد، و **تنها به همین دلیل** می‌شود سقف را ۶ → ۳ آورد بدونِ ساختنِ اهرمِ قفلِ ادمین (فرمِ بدیهی‌ترِ «حذفِ ریست» دقیقاً همان اهرم را می‌ساخت). سقفِ per-adminِ درخواست عمداً دست‌نخورده ماند، چون تنها اهرمی است که مهاجم علیهِ ادمینِ واقعی دارد. سقفِ per-IP صریحاً **نرخِ مهاجمِ تک‌مبدأ را کم نمی‌کند** (آن‌جا per-admin زودتر می‌بندد)؛ چیزی که می‌خرد این است که کشتنِ بلاکِ اندپوینت حجمِ خامِ verify را بی‌کران می‌کرد. `_RL_VERIFY_PER_IP` **مشتق** است نه دلخواه (۱۰ درخواست × ۳ حدس)، و `_RL_REQ_PER_IP = 10` صریحاً دلخواه اعلام شده. بودجهٔ نهایی **۱۵ در ۶۰۰ ثانیه** از ۳۰؛ و اهرمِ بعدی طولِ کد است نه این شمارنده‌ها (۱۵ در برابرِ ۱۰^۸ → ~۰٫۵٪ در سال) — **ثبت شد، ساخته نشد**. `_client_ip` عمداً XFF نمی‌خواند. **دو کرشِ عمومی** هم سرِ راه بسته شد، هر دو اجراشده: `int()` روی رشتهٔ >۴۳۰۰ رقم و `compare_digest` روی strِ غیرASCII (که چون `'۱۲۳۴۵۶'.isdigit()` صادق است، مقایسه باید روی **بایت** باشد وگرنه رفع خودش یک ۵۰۰ می‌ساخت). و `_rate_limit` وقتی TTL گم باشد دوباره `expire` می‌زند — `INCR`+`EXPIRE` دو فرمانِ جداست و مرگِ بینشان یک شمارندهٔ جاودان یعنی قفلِ دائمیِ ورود، همان شکستِ `dl:active`. **(۲ C-3)** پروبِ pot درجا داخلِ `_health` بود؛ با سوکتی که accept می‌کند و جواب نمی‌دهد: `/` ۳۱۵۱ ms · `/health` ۳۰۲۳ ms · بدونِ pot ۲۱ ms. کش + تازه‌سازیِ پس‌زمینه، پس مسیرِ درخواست **صفر بایتِ شبکه** دارد (پس از رفع: ۱۹۳ ms بارِ اول که تقریباً همه‌اش گرم‌شدن است، و ۲۴ ms گرم). دو کلید نه یکی، و «نسنجیده» با «پیکربندی‌نشده» یکی نشد — **تنها HTMLِ این PR همان یک `elif` است**. **(۳ C-4)** ایندکسِ `last_seen` + کشِ صفحه، هر دو روی **Postgres 16.13 واقعی** سنجیده شدند نه SQLite. و تفکیکِ هزینه چیزی را نشان داد که یافته نمی‌گفت: در ۲۰۰هزار ردیف دو `count(*)` روی‌هم ۲۵٫۳ ms‌اند و کوئریِ صفحه ۰٫۴۵ ms، یعنی **۹۶٪ کارِ صفحه چیزی است که کش برمی‌دارد نه ایندکس**. باطل‌سازیِ کش با شمارندهٔ نسخه شرطِ **درستی** است نه بهینه‌سازی (وگرنه ادمین بعد از «بلاک» همان کاربر را آزاد می‌بیند). صریح ثبت شد که روی جدولِ امروز (۱۶۶۸ ردیف) کلِ صفحه ~۲٫۷ ms است، پس هر دو نیمه بیمهٔ رشدند نه رفعِ دردِ فعلی. **تست‌ها (۸۵۶ بی‌تغییر در jobِ اصلی، ۵۸ → ۹۴ در jobِ پنل)؛ ۲۳ موردِ سابوتاژِ تازه، همه طبقِ ثبت** (سه‌تایشان کنترلِ معکوس). **و سه نقصِ تستِ خودم را دفترچه پیدا کرد نه بازخوانی:** یک ادعای انتها‌به‌انتها که **دو** مکانیزم برآورده‌اش می‌کردند پس سابوتاژِ تک‌لایه نمی‌انداختش (لایه‌ای که فقط خودش تصمیم می‌گیرد حالا جدا تست دارد)؛ یک سابوتاژِ مسیرِ **نوشتن** که به ادعای مسیرِ **خواندن** وصل شده بود؛ و یک assertِ سست (`"block" in body`) که چون رشته در `action=` هم هست همیشه صادق بود. **و یک ردهٔ تازه که نام گرفت:** تستی که زیرِ سابوتاژ به‌جای افتادن **هنگ می‌کند** — `await task`ِ لخت روی تسکی که سابوتاژ لغوش را برداشته بود، یعنی تبدیلِ یک قرمزِ تمیز به jobِ گیرکرده؛ در §۶ ثبت شد به‌همراه قاعدهٔ «مدلِ ساعت برای سقفِ نرخ». **اعمال: `telabzar update` روی مستر — همه‌چیز پنل است و هیچ نودی این کد را اجرا نمی‌کند.** **کامیتِ سوم تنها کامیتِ دارای migration است** (`CREATE INDEX IF NOT EXISTS ix_users_last_seen`)، که `init_models()` سرِ استارتِ ربات/ورکر خودکار اعمالش می‌کند؛ روی ۱۶۶۸ ردیف ۲٫۳–۳٫۴ میلی‌ثانیه، پس بدونِ گامِ دستی و بدونِ پنجرهٔ توقف. بدونِ کلیدِ تنظیماتِ تازه و بدونِ رشتهٔ locale. **کامیتِ چهارمِ برنامه‌ریزی‌شده (D-3/B-2/C-1/D-2) انجام نشد** — فایلِ گزارش به سشن نرسید و بدونِ متنش قابلِ انجام نبود؛ به فاز بعد منتقل شد (تصمیمِ اپراتور).
- 2026-08-18 — **پرتگاهِ آپلود: عملیاتی که کارش را تمام می‌کند و بعد سرِ ارسال می‌شکند.** دریافت سقف ندارد (سرورِ محلیِ Bot API) ولی آپلود ۲۰۰۰ مگابایت است، پس هر opی که خروجیِ تازه می‌سازد می‌تواند بعد از خرجِ CPU و دیسک در تحویل بشکند. گارد در `tasks.run_op` نشست: `_too_big_to_send(_outgoing_paths(res))`، **یک** گیت پیش از کلِ زنجیرهٔ تحویل. **(۱ رفتارِ امروز، اجراشده نه توصیف‌شده)** با `run_op`ِ واقعی روی SQLite و باتی که مثلِ سرور ۴۱۳ می‌دهد، چهار شاخهٔ تحویل **دو** رفتارِ متفاوت داشتند نه یکی: `path`/`send_media` مقدارِ `failed` می‌دادند با پیامِ عمومی و دُمِ خامِ انگلیسی، ولی `spawn`/`files` مقدارِ **`done`** می‌دادند و برچسب را در `changelog` می‌نوشتند در حالی که هیچ فایلی نرسیده بود — موفقیتِ کاذب، چون استثنا فقط لاگ می‌شد. **(۲ دو چیزی که فقط با اجرا دیده شدند و در صورتِ مسئله نبودند)** شاخهٔ `spawn` ردیفِ `File` را **پیش از** آپلود commit می‌کند، پس شکستِ ارسال یک ردیفِ یتیم با `file_id=""` جا می‌گذاشت (اندازه‌گیری‌شده: **۲** ردیف در `files` در برابرِ ۱ برای سه شاخهٔ دیگر)؛ و اگر سرور به‌جای ۴۱۳ جوابِ **۴۰۰** بدهد، زنجیرهٔ fallbackِ `update_card`→`send_card`→`send_document` بایت‌های بیش‌ازحد را **سه بار** می‌فرستد (اندازه‌گیری‌شده روی `cards`ِ واقعی: ۱ در برابرِ ۳). کدامش را سرورِ محلی می‌دهد از سندباکس معلوم نیست و **برای رفع بی‌اهمیت است**، چون گارد اصلاً به آن‌جا نمی‌رسد. **(۳ گیتِ واحد، نه چهار چکِ پراکنده)** پیش از دست‌خوردنِ فیلدهای `file` اجرا می‌شود (پس rollback لازم ندارد) و پیش از `session.add(newf)` (پس ردیفِ یتیم ساخته نمی‌شود) — هر دو رایگان، که نسخهٔ پراکنده نمی‌داد. `job.status = "failed"` در هر چهار شاخه، طبقِ تصمیمِ اپراتور: کار به مقصد نرسیده و `done` یعنی changelog دروغ می‌گوید و هر منطقی که بعداً روی «کارهای موفق» حساب کند خراب می‌شود. **(۴ پیام)** سه جزء، و سومی از همه مهم‌تر است چون کاربری که ربع ساعت منتظر مانده اول فکر می‌کند فایلش از دست رفت: حجمِ **واقعیِ** خروجی (تفاوتِ ۲٫۱ گیگ با ۵ گیگ برای تصمیمش مهم است)، سقفِ ارسالِ تلگرام، و «فایلِ اصلی دست‌نخورده است» + کاری که می‌تواند بکند. **(۵ سه تصحیح روی فرضِ ورودی، همه با اجرا)** لبهٔ vjoin **نهفته** است نه فعال — `_vjoin_cap_mb()` با پیش‌فرض ۲۰۰۰ می‌دهد نه بی‌کران، چون `_max_mb()` برابرِ `max_file_mb=2000` است؛ آنچه #۱۲۲ عوض کرد نبودِ **کرانِ `BOUNDS`** است، پس فقط با بالابردنِ `max_file_mb` مسلح می‌شود. چیزی که **امروز با پیش‌فرض** به پرتگاه می‌خورد `rename` و `zip_many` است، چون `_too_large` یازده هندلر را گیت می‌کند و شش‌تا را نمی‌کند (فهرست در §۷). و `rename` روی فایلِ بالای سقف **هرگز نمی‌تواند موفق شود** (`_do_op` مقدارِ `{"path": inpath}` می‌دهد) — نیمهٔ گمشدهٔ won't-fixِ ۲۰۲۶-۰۸-۱۱. **(۶ تخمینِ پیش‌از‌شروع بررسی و رد شد)** فقط `rename` (دقیق) و مجموعه‌ها (مجموعِ `members[].size`، با این نقص که fallbackِ تک‌عضویِ `op_collect_go` کلیدِ `size` ندارد) پیش‌بینی‌پذیرند؛ `convert` می‌تواند بزرگ کند و بقیه اصلاً. پس جای گارد بعد از تولید است — و `os.path.getsize(outpath)` از قبل دقیقاً همان‌جا محاسبه می‌شد. **(۷ ثابت عمومی شد)** `_UPLOAD_CEILING_MB` → `UPLOAD_CEILING_MB`: دو مصرف‌کننده دارد و زیرخط یعنی «مالِ من»، که دعوتِ نوشتنِ `2000` در ماژولِ دوم است — همان دو کپیِ دست‌نویسِ `remove_cookie_file`. **تست‌ها (۸۲۷ → ۸۵۶: ۲۳ برای گارد و ۶ برای سلف‌تستِ دفترچه؛ پنل بی‌تغییر ۵۸).** فایلِ بزرگ **sparse** است (`truncate`): `getsize` حجمِ کامل می‌دهد و صفر بلوک می‌گیرد، پس سقفِ **واقعی** سنجیده می‌شود نه عددِ کوچکِ وصله‌شده. **کنترلِ منفی روی سورسِ پیش از رفع: ۱۴ افتاد، ۹ سبز ماند** — و آن ۹ دقیقاً کنترل‌اند: مسیرِ سالم ×۴ (گاردِ «همه‌چیز را رد نکن»)، سه شاخه‌ای که هرگز یتیم نمی‌ساختند، گاردِ کشف‌محورِ شکل، و ادعای پایداریِ `job.error` که پیش از رفع بی‌موضوع است (سابوتاژ غیرِتوخالی بودنش را ثابت می‌کند، نه اجرای pre-fix). از آن ۱۴، **۱۰ رفتاری**‌اند و **۴** به‌خاطرِ نبودِ خودِ تابع‌اند که ادعای رفتاری نیست (درسِ `raising=False`). **۱۰ موردِ سابوتاژِ تازه برای گارد (۱ کنترلِ معکوس) + ۴ برای خودِ دفترچه؛ اجرای کاملِ دفترچه روی درختِ تمیز ۱۲۵ از ۱۲۶، و تنها شکستش همان flakeِ `orphan`ِ **از قبل ثبت‌شده** است (امضای یکسان: به‌جای `test_the_match_search_…` همسایه‌اش `test_probe_…` قرمز می‌شود) که Open Questions می‌گوید روی `origin/main`ِ دست‌نخورده هم بازتولید می‌شود.** **(۸ و سه نقصِ خودِ دفترچه که همین کار پیدا کرد — هر سه از یک ریشه)** `_run_case` فقط خطوطِ `FAILED` را می‌خواند، پس هدفی که سرِ collect می‌ترکید (موردِ پنلی از venvِ بدونِ jinja2: **۳۱ `ERROR` و صفر `FAILED`**) «نگرفت» گزارش می‌شد — یعنی ابزارِ سنجش یک نتیجهٔ **درست** را غلط می‌خواند، همان ردهٔ ثبت‌شدهٔ §۶. حالا حالتِ سومِ «اجرا نشد» دارد. **و دو نسخهٔ اولِ همین رفع خودشان همان باگ را داشتند**، که نکتهٔ اصلی است: اول `"no tests ran" in stdout`ِ زیررشته‌ای با متنِ خودِ تست برخورد کرد، و بعد `startswith("ERROR")` با **لاگِ** تست (`ERROR    telabzar.dl:tasks_download.py:201 …`) — که سه اجرای کاملاً **سالم** را «هدف اجرا نشد» خواند. حالا فقط بخشِ `short test summary info` خوانده می‌شود، یعنی گرامرِ خودِ pytest؛ قاعده‌اش در §۶ ثبت شد. **(۹ و یک درسِ عملیاتی که گران‌تر بود)** اولین اجرای کاملِ دفترچه با تایم‌اوتِ ۱۰ دقیقه‌ایِ ابزار **کشته شد**، پس `finally` اجرا نشد و `app/admin_web.py` با متنِ سابوتاژ روی دیسک ماند؛ اجرای بعدی ۱۲۵ مورد را روی همان درختِ خراب سنجید و نتیجه‌اش باید دور ریخته می‌شد. تنها نشانه‌اش «الگو رُت کرده» روی موردی بود که کسی لمسش نکرده بود. دفترچه باید **detached** اجرا شود، و هر اجرای نیمه‌کاره یک `git diff` می‌خواهد پیش از باور کردنِ هر عددی. **اعمال: `telabzar update` روی مستر، و `node/update.sh` اگر نودِ پردازش وصل شد** (`tasks.py` روی نودِ پردازش هم می‌دود). **بدونِ migration، بدونِ کلیدِ تنظیماتِ تازه**؛ یک رشتهٔ locale در دو زبان. **سه یافتهٔ جانبی فقط ثبت شدند و دست نخوردند** (تصمیمِ اپراتور): بی‌سقف بودنِ ورودیِ zip/merge/img_pdf، خاموش‌شدنِ گاردِ دانلود با `dl_max_size_mb=0`، و نیمهٔ گمشدهٔ won't-fixِ rename.
- 2026-08-17 — **خوشهٔ شکستِ خاموشِ پنل: B-1، B-3، B-4، B-5 — و یک مسیرِ خطای مشترک زیرِ هر چهارتا.** الگو یکی بود: ورودیِ نامعتبر با یک `continue`/`elif` بی‌صدا دور ریخته می‌شد و صفحه بی‌قیدوشرط بنرِ سبز می‌داد. **(۰ مسیرِ مشترک)** فقط `texts_save` راهِ برگرداندنِ خطا داشت و `buttons_save` نداشت — یعنی ناسازگاریِ دو صفحه، نه محدودیتِ طراحی، و همان چیزی که B-1 را ساخت. `_result()` تنها راهِ ساختنِ `ok=`/`err=` شد و **هر** محلِ فراخوانی در همان کامیت تبدیل شد، تا گاردِ ASTی بتواند قاعدهٔ صاف بدهد بدونِ فهرستِ استثنا (که همان `_KNOWN_UNREACHABLE`ی است که پوسید). **صداقتِ اندازه‌گیری:** هندلرهای کوکی متنِ فارسی را بدونِ انکود به کوئری می‌چسباندند، ولی yarl سرِ سیم انکودش می‌کند — پس **باگِ زنده نبود** و تبدیلشان یکنواختی و گارد می‌خرد، نه یک رفع. **(۱ B-1)** `buttons_save` در یک حلقه هم می‌سنجید هم می‌نوشت، و شاخهٔ `elif` هر متنِ ردشده را به «حذفِ override» ترجمه می‌کرد: یک تایپ در placeholder برچسبِ سالم را پاک می‌کرد و بنرِ سبز می‌آمد. حالا اول کلِ فرم سنجیده می‌شود بعد نوشته، و **اتمیک** — چون فرم کلِ منو را یک‌جا می‌فرستد و «۱۱ از ۱۲ ذخیره شد» خودش یک شکستِ نیمه‌خاموشِ دیگر است. **(۲ B-3+B-4)** `/save` مقدارِ خارج از `ENUM_VALUES` و عددِ نامعتبر را `continue` می‌کرد و هیچ کرانی هم نبود (`max_file_mb = -1`، `safety_threshold = 9999` پذیرفته و ذخیره می‌شدند). اعتبارسنجی به `settings_store` منتقل شد چون `/admin`ِ تلگرام کپیِ دست‌نویسِ خودش را داشت با همان کرانِ غایب. **معیارِ عددی `int()` شد نه `isdigit()`**، چون `get_int()` بعداً همان را می‌زند — و دقتِ ادعا مهم است: `--5` ردیف را **می‌نوشت** ولی `_effective()` هم همان `except ValueError` را دارد، پس صفحه پیش‌فرض نشان می‌داد؛ ردیفی که نه اثری داشت نه دیده می‌شد. (نسخهٔ اولِ همین ادعا در پیامِ کامیت و داکس‌استرینگ نوشته بود «صفحه `--5` نشان می‌داد» — غلط بود و با اجرا روی `f0a3cfe` تصحیح شد.) **کران‌ها مشتق‌اند نه سلیقه:** ۲۰۰۰ از سقفِ **آپلودِ** Bot APIِ محلی، ۱۰۰ برای دو کلیدِ درصدی و برای `match_min` که بازه‌اش در `config.py` نوشته شده، و کفِ ۰ برای بقیه **بدونِ سقف** — `safety_video_frames = 9999` هنوز مجاز است چون کرانِ قابلِ‌دفاعی ندارم و ساختنِ یکی بدتر از نداشتنش است. **و بزرگ‌ترین اشتباهِ همین کار همین‌جا بود:** نسخهٔ اول ۲۰۰۰ را روی **هر پنج** کلیدِ مگابایتی گذاشت، در حالی که `--local` دو محدودیتِ متفاوت دارد — «دانلود بدونِ محدودیتِ حجم، آپلود تا ۲۰۰۰ مگابایت» — و `max_file_mb` سمتِ **دریافت** است. شاهدِ اپراتور از تولید ردش کرد: جدولِ `files` ۴۴ ردیفِ بالای ۲۰۰۰ مگ دارد و بزرگ‌ترین ۳۹۱۲ مگ، یعنی آن سقف مسیری را می‌بست که امروز کار می‌کند. ریشه در **سند** بود نه در کد: `docs/telegram-api.md` می‌گفت local mode «محدودیتِ ۵۰/۲۰ مگ را به ~۲۰۰۰ می‌برد» — یک عدد برای دو جهت، دقیقاً همان ثابتی که §۶ می‌گوید می‌پوسد — و تستِ پین هم فقط همان عدد را می‌سنجید، پس **تأییدش می‌کرد**. حالا سند دو جهت را جدا می‌گوید، تست جهت را هم پین می‌کند، و طبقه‌بندیِ هر پنج کلید با **ردیابیِ محلِ خواندن** انجام شده (جدول در §۷). یک نتیجه برخلافِ شهود بود و با اجرا معلوم شد: `dl_direct_max_mb` **سمتِ آپلود است**، چون موتورِ direct هم از `_spawn`/`_deliver_single` رد می‌شود و `_media_arg(f, path)` مقدارِ `FSInputFile` می‌دهد. **(۳ B-5)** فیلدِ «نامِ نود» از روزِ اول خوانده نمی‌شد؛ نام از `hostname -s`ِ خودِ نود می‌آمد و راهِ تغییرِ نام هم نیست. حالا نامِ ادمین داخلِ همان payloadِ **امضاشدهٔ** join می‌رود (پس نود نمی‌تواند جایش چیزی بگذارد و حالتِ Redisِ اضافه لازم نیست) و فیلدِ خالی به رفتارِ امروز برمی‌گردد. نقشِ نامعتبر هم که بی‌صدا ریدایرکت می‌شد حالا دلیل می‌دهد. **(۴ رقمِ فارسی — ساخته نشد، با دلیل)** فرضِ «۲۰۰۰ فارسی رد می‌شود» غلط بود: از قبل پذیرفته می‌شد، `int()` درست پارسش می‌کند، و `_effective()` هم برای نمایش `int()` می‌زند — پس مقدارِ مؤثر و نمایش هر دو درست بودند. تنها ردِ باقی‌مانده رشتهٔ غیرASCII در DB است و **صفر مصرف‌کننده** می‌بیندش (سرشماری‌شده: هیچ‌کدام از ۳۴ کلیدِ `int` با `get_str`/`get_bool` خوانده نمی‌شوند). نرمال‌سازی یعنی تغییرِ رفتار بدونِ سودِ اندازه‌گیری‌شده، روی پنلی که کاملاً فارسی است. **تست‌ها (۷۵۷ → ۸۱۹ در jobِ اصلی، ۲۷ → ۵۶ در jobِ پنل):** رفتاری روی سرورِ واقعی، نه AST. **کنترلِ منفی به‌ازای هر بخش** با برگرداندنِ سورس: B-1 چهار ادعا می‌افتد و سه کنترل سبز می‌ماند؛ B-3/B-4 یازده ادعا می‌افتد و سیزده کنترل سبز. **و دو تستِ خودم توخالی درآمدند و هر دو را همان کنترلِ منفی گرفت** — «نامِ دکمه در پیام هست» روی کلِ صفحه assert می‌کرد در حالی که برچسب به‌هرحال داخلِ فرم رندر می‌شود، و «نقشِ نامعتبر خطا می‌دهد» صرفاً وجودِ یک errbox را می‌سنجید در حالی که صفحهٔ نودها وقتی WGِ مستر پیکربندی نشده **همیشه** یکی دارد؛ هر دو حالا محتوای بنر را می‌خوانند. **یک باگِ هارنس هم پیدا شد:** `textstore` سه دیکشنریِ سطحِ ماژول دارد که بینِ تست‌ها زنده می‌مانند در حالی که DB هر تست تازه است، پس پیش‌شرطِ یک تست را همسایه‌اش تعیین می‌کرد؛ fixture حالا خالیشان می‌کند. **۱۱ موردِ سابوتاژِ تازه (۲ کنترلِ معکوس)، همه طبقِ ثبت.** **اعمال: `telabzar update` روی مستر. بدونِ migration، بدونِ کلیدِ تنظیماتِ تازه، بدونِ رشتهٔ locale.** فقط `admin_web`/`settings_store`/`nodes`/`routers/admin` عوض شده‌اند؛ `settings_store` و `routers/admin` روی نودها هم می‌دوند ولی هیچ مسیرِ نودی این کد را صدا نمی‌زند، پس `node/update.sh` لازم نیست. **مقادیرِ خارج از کرانِ از-قبل-ذخیره‌شده دست‌نخورده می‌مانند، و این یک پیامدِ استقرارِ دیدنی دارد که باید گفته شود** (اندازه‌گیری‌شده، و تست دارد): کران فقط سرِ **نوشتن** اعمال می‌شود، پس ردیفِ موجود سرِ جایش می‌ماند و صفحه همان را رندر می‌کند — ولی اولین ذخیرهٔ بعدی، حتی اگر ادمین آن فیلد را لمس نکرده باشد، به‌خاطرِ اتمیک‌بودنِ فرم **رد می‌شود**. از بیرون شبیهِ «پنل خراب شد» است؛ پیام نامِ همان کلید را می‌برد، پس راهِ خروج یک ویرایش است نه یک دیباگ. اگر روی مستر مقدارِ خارج از کرانی نشسته باشد، اولین ذخیره بعد از این استقرار همان را نشان می‌دهد. **و یک flakeِ مشاهده‌شده که مالِ این کار نیست:** `test_settings_rename.py::test_concurrent_writes_of_a_new_key_do_not_crash[16]` یک‌بار در اجرای کاملِ سوییت افتاد و بعدش ۳ از ۳ اجرای کامل و ۳ از ۳ اجرای منفرد سبز بود — روی `origin/main`ِ دست‌نخورده هم ۳ از ۳ سبز است، و `settings_store.set()` در این برنچ لمس نشده. ۱۶ نویسندهٔ هم‌زمان روی SQLite است؛ ثبت شد، دنبال نشد.
- 2026-08-17 — **فاز ۲: زنجیرهٔ راز بسته شد — A-1 (نیمهٔ کد + نصب‌کننده)، A-2، C-2، A-3.** **(A-1)** `_fernet` روی `ADMIN_SECRET`ِ خالی به `BOT_TOKEN` برمی‌گشت و `install.sh` **اصلاً `ADMIN_SECRET` نمی‌نوشت** — یعنی هر استقرارِ ساخته‌شده با مسیرِ مستندِ نصب، کلیدِ نشستش را از توکنی می‌گرفت که عمداً به هر نود داده می‌شود. حالا fallback حذف شده، `main()` پیش از `run_app` **متوقف می‌شود**، و نصب‌کننده مثلِ `PG_PASS` تولید/حفظ می‌کند. **refuse-to-start با سه اندازه‌گیری توجیه شد نه با سلیقه:** هیچ ماژولِ دیگری `admin_web` را import نمی‌کند (شعاع = یک کانتینر)، `/admin`ِ تلگرام به `admin_secret` دست نمی‌زند (اپراتور کنترلِ ربات را از دست نمی‌دهد)، و «`.env` گم شد» از قبل هم کشنده بود چون `BOT_TOKEN` پیش‌فرض ندارد. مسیرِ درخواست **بسته** برمی‌گردد نه ۵۰۰. `NODE_SECRET` هم آمد چون fallbackِ یکسان دارد و گاردی که یکی را بگیرد و دیگری را نه، استثنای دستی می‌خواهد. **(A-2 + C-2)** توکنِ join در query string می‌رفت و لاگرِ aiohttp با `%r` مسیر را **با کوئری** می‌نویسد، پس مستقیم در `docker compose logs admin` می‌نشست؛ لاگِ تولید نیمهٔ دوم را نشان داد — از ۹ خطِ `tok=`، هشت‌تا `Referer` داشتند. حالا توکن در Redis زیرِ کلیدِ **بسته‌به‌ادمین** می‌نشیند، redirect بی‌کوئری است و نمایش **یک‌بارمصرف** (`getdel`). `Referrer-Policy` در همین کامیت است نه در سخت‌سازی، چون referer همان مسیرِ انتشار بود؛ middleware است تا ریدایرکت‌ها و خطاها را هم بگیرد — و جریانِ نودها **از ریدایرکت ساخته شده**. ادعای اصلی با **لاگِ واقعی** اثبات شد نه استدلال، با کنترلِ منفیِ داخلی («اول ثابت کن لاگ اصلاً چیزی گرفته»). **(A-3)** مصرفِ توکن به **بعد از** اعتبارسنجی رفت؛ هر دو شاخهٔ `if` جدا تست دارند چون تستِ تک‌شاخه‌ای با نصفه‌رفع سبز می‌ماند. **(هدرها، کامیتِ جدا)** X-Frame-Options/CSP/nosniff/HSTS. CSP سخت‌گیر است چون پنل **صفر منبعِ خارجی** دارد (اندازه‌گیری‌شده)، و HSTS **مشروط به اسکیمِ واقعی** است وگرنه نصبِ بدونِ دامنه مرورگر را به HTTPSِ ناموجود قفل می‌کند. **دو یافتهٔ روشی که از خودِ رفع مهم‌ترند.** (۱) **گاردِ نصب‌کننده در نسخهٔ اول خودتخریب بود:** فهرستش را از الگوی `settings.X or settings.bot_token` **کشف** می‌کرد، و رفعِ A-1 همان الگو را برداشت — پس گارد دیگر `ADMIN_SECRET` را نمی‌خواست و حذفِ خطِ نصب‌کننده هیچ‌چیز را قرمز نمی‌کرد. سابوتاژ گرفتش. معیاری که با رفعِ باگ ناپدید شود از فردای رفع محافظت نمی‌کند؛ حالا فهرست صریح است و کشف در جهتِ **معکوس** نگه‌داری‌اش می‌کند. (۲) **هارنس خودش روی همان آسیب‌پذیری می‌دوید:** فیکسچرِ پنل هرگز `admin_secret` را ست نمی‌کرد، پس هر تستِ پنل بی‌سروصدا مسیرِ fallback را تمرین می‌کرد. **تست‌ها: ۷۵۳ → ۷۵۶ در jobِ اصلی، ۱۳ → ۲۷ در jobِ پنل؛ ۱۶ موردِ سابوتاژِ تازه، همه طبقِ ثبت.** **اعمال: `telabzar update`؛ بدونِ migration و بدونِ snapshot.**
- 2026-08-17 — **مسیرِ تستِ رفتاریِ پنل باز شد (فاز ۳). صفر تغییر در `app/`.** تا امروز `test_no_test_imports_a_module_the_ci_runner_does_not_have` هر importِ `app.admin_web` را رد می‌کرد و نتیجه‌اش **صفر پوششِ رفتاری روی ۳۱ مسیرِ پنل** بود؛ یعنی رفعِ فاز ۲ هم بدونِ تستِ رگرسیون می‌رفت. گارد **حذف نشد** — دلیلش واقعی است — بلکه یک مسیرِ **مجاز** ساخته شد. **سه فورک سنجیده شد و دوتا با اجرا رد شدند.** مارکر (+jobِ جدا) کار نمی‌کند چون مارکر جلوی import را نمی‌گیرد: `-m "not panel"` باز هم ماژول را import می‌کند تا مارکرش را بخواند و کلِ ران با `Interrupted: 1 error during collection` می‌میرد، نه فقط آن تست — پس به فورکِ مسیر **فرو می‌ریزد**. و importِ hookِ ثبت‌شده در Open Questions **REFUTED** شد: `packages_distributions()` فقط چیزهای **نصب‌شده** را می‌شناسد، و در محیطِ CI هر ۱۳ توزیعِ خارج از dev مقدارِ `UNRESOLVABLE` می‌دهند — یعنی برای denyکردنِ یک ماژول باید نصب باشد، و اگر نصب باشد چیزی برای deny نیست. نگاشت روی نصب‌شده‌ها درست کار می‌کند (کنترل: `Pillow→PIL`, `PyYAML→['_yaml','yaml']`, `yt-dlp→yt_dlp`)، و همین است که غلط‌بودنش را روی کاغذ نامرئی می‌کند. **فورکِ انتخابی مسیر است:** `tests/panel/` + `addopts = --ignore=tests/panel` + jobِ **موازیِ** `panel` (بدونِ `needs:`، وگرنه قرمزیِ jobِ اصلی نتیجهٔ پنل را پنهان می‌کند). **دلتای دقیقِ وابستگی‌ها اندازه‌گیری شد: ۵ توزیع** — `cryptography`+`jinja2`ِ اعلام‌شده به‌علاوهٔ `MarkupSafe`/`cffi`/`pycparser`ِ وابسته؛ و بس. **هارنس مستقیم قابلِ انتقال نبود و دو قید این را تعیین کرد:** `POSTGRES_DSN` از env هدایت‌شدنی نیست (`tests/conftest.py:17` زودتر ستش می‌کند و `app/db.py:53` موتور را سرِ import می‌سازد)، پس الگوی جاافتادهٔ ریپو (`test_settings_rename.py:36-40`) نامِ `Sessionmaker` را در **چهار** ماژولِ اندازه‌گیری‌شده وصله می‌کند — و فهرست با یک تست کشف‌محور نگه‌داری می‌شود تا ماژولِ پنجم بی‌صدا به Postgres وصل نشود؛ و `settings.admin_id_set` propertyِ فقط‌خواندنی است پس `admin_ids` ست می‌شود. SQLite فایل‌محور روی `tmp_path`، نه `:memory:`. **دو شکافِ واقعی در خودِ گارد پیدا و بسته شد** (و معافیتِ مسیر در همان کامیت، وگرنه سوییت بینِ دو کامیت قرمز می‌شد): فقط `test_*.py` را می‌خواند، پس هر `conftest.py` — یعنی دقیقاً جایی که هارنس می‌نشیند — کاملاً از کنارش رد می‌شد؛ و `import app.admin_web` را می‌گرفت ولی `from app import admin_web` را **نه** (اندازه‌گیری‌شده روی فرمِ قبلی)، که همان فرمی است که آدم طبیعی می‌نویسد. **تست‌های characterization** رفتارِ **امروزِ** A-1/A-2/A-3 را pin می‌کنند با برچسبِ صریح که سبزبودنشان یعنی «هنوز رفع نشده»؛ سابوتاژشان **معکوس** است — پچِ اعمال‌شده همان رفعِ فاز ۲ است و ادعا این است که دقیقاً همان تستِ `TODAY` قرمز می‌شود. یک بازآراییِ باربر: نسخهٔ اول توکن را از redirect بیرون می‌کشید، پس یک رفع چهار تست را می‌انداخت و معلوم نمی‌شد کدام ادعا شکسته؛ حالا توکن از fixture می‌آید و فقط تستی که دربارهٔ URL است به URL گره خورده. **تصحیحِ یک واقعیتِ ثبت‌شده در §۶:** «deselectِ همه کدِ صفر می‌دهد» روی **pytest 9.1.1** دیگر درست نیست — کدِ ۵ می‌دهد؛ تصمیمِ آن روز (نگهبان یک تست باشد نه گامِ CI) سرِ جایش است ولی مقدمه‌اش عوض شده، و همین باعث شد گیتِ «تعدادِ جمع‌شده» در jobِ پنل با دلیلِ **درست** توضیح داده شود: کفِ فرسایش + بیمه در برابرِ عوض‌شدنِ همین معناشناسی، نه «صفر تست سبز می‌شود» که روی این نسخه اثباتاً قرمز است. **تست‌ها: ۷۲۶ → ۷۳۸ در jobِ اصلی + ۱۳ در jobِ پنل؛ دفترچهٔ سابوتاژ ۷۸/۷۸.** **اعمال: هیچ deployای لازم نیست — هیچ فایلی زیرِ `app/` عوض نشده.**
- 2026-08-17 — **دو کارِ کوچکِ بازمانده: ctxِ هارنسِ انتخابگر، و دو زیرفرایندِ یتیم.** **(۱ هارنس — بدونِ کدِ اجرایی)** `tests/test_soundcloud_path._picked` ctxِ انتخابگر را هاردکد می‌کرد و **هر دو فلگش غلط بود**: `incomplete_formats` را `False` می‌گفت (درستش `True`) و `has_merged_format` را اصلاً نمی‌داد (درستش `False`). **نتیجهٔ #۱۱۵ عوض نشد** و این‌بار به‌جای حافظه یک **کنترلِ معکوسِ اجرایی** پشتش هست. ولی هر دو فلگ روی همین فیکسچر پیامدِ سنجش‌پذیر دارند و **نیمهٔ دومش در پرامپت نبود**: `b` و `bv*+ba/b` با ctxِ هاردکد `None` می‌دهند و با ctxِ درست `hls_aac_96k` (همان false failِ کست‌باکس)، **و `mp4` با ctxِ هاردکد `KeyError` می‌دهد** — چون `build_format_selector` مقدارِ `ctx['has_merged_format']` را با `[]` می‌خواند نه `.get()`، یعنی کلیدِ **غایب** بی‌صدا falsy نیست. رفع: `_picked` حالا `ydl._select_formats(...)` را صدا می‌زند، همان متدی که `process_video_result` در `YoutubeDL.py:2885` صدا می‌زند. **سه ادعا در سه سطح** (حقیقتِ زمینیِ ctx · کنترلِ منفی به‌ازای هر فلگ · تست‌های #۱۱۵ به‌عنوان کنترلِ معکوس)، چون یک تستِ انتها‌به‌انتها نمی‌تواند دو فلگ را جدا اثبات کند. **و یک چیزِ خارج از دامنه که با اجرا پیدا شد:** هارنسِ کست‌باکس همان دو عبارت را **دستی بازنویسی** کرده بود — باگ نبود چون درست محاسبه می‌کرد، ولی کپیِ دومِ دست‌نویس از قاعده‌ای است که صاحبش yt-dlp است و کپیِ دوم واگرا می‌شود؛ آن هم حالا از yt-dlp می‌پرسد. **(۲ یتیم‌ها)** `_run`/`_run_dl` از قبل روی `CancelledError` فرزندشان را می‌کشتند، `probe` و `_yt_search_candidates` نه — هر دو فقط `asyncio.TimeoutError` می‌گرفتند. محرک `job_timeout` نیست، **خاموشیِ ورکر** است، یعنی هر `telabzar update`؛ و چون `dl_ux_youtube = probe` در تولید ست است، مسیرِ اول **هر** لینکِ یوتیوب است. هر دو `--cookies` می‌فرستند، پس یتیمشان سهمیهٔ یک اکانتِ سشن را می‌سوزاند بی‌آنکه ثبت شود (جاب مرده). قاعده به `processing.kill_orphan` منتقل شد و هر چهار مسیر از آن رد می‌شوند — **چهار کپیِ دست‌نویس که از قبل واگرا شده بودند، دو تا با رفع و دو تا بی‌رفع**، یعنی همان چیزی که یک کپیِ پنجم را دعوت می‌کند. **`cancel` عمداً اضافه نشد و دلیلش اندازه‌گیری است نه سلیقه:** رفعِ یتیم به آن نیازی ندارد، و افزودنش دکمهٔ لغو را حینِ «در حالِ تطبیق» درست نمی‌کند چون هزینهٔ غالبِ `_gather_candidates` مالِ `_ytmusic_search` است که در `asyncio.to_thread` می‌دود و **اصلاً لغوشدنی نیست** (اجراشده: بعد از `task.cancel()` خودِ thread تا آخر رفت). **هارنس** یک yt-dlpِ جعلیِ **تمام‌نشدنی** است تا «رفت» فقط بتواند یعنی «کشته شد» (درسِ ۳الف)، PID از فایلی که خودِ فرایند می‌نویسد خوانده می‌شود نه `pgrep` (که خطِ فرمانِ خودِ تست را هم می‌شمارد)، و یک **کنترلِ مثبت** روی `_run_dl`ِ از-قبل-رفع‌شده ثابت می‌کند هارنس اصلاً می‌تواند یک kill را ببیند. دو تست هم assert می‌کنند یتیم `--cookies` در دست داشته، تا ادعای «هزینه‌اش سهمیهٔ سشن است» اجرایی باشد نه نثر. **تست‌ها (۷۲۶ → ۷۴۱)، سابوتاژ (۶۶ → ۷۳، همه سبز)** — از جمله دو کنترلِ معکوس: خرابکاریِ probe نباید ادعای جست‌وجو را بیندازد (دو مسیر جدا اثبات شده‌اند)، و خنثی‌کردنِ هلپرِ مشترک باید کنترلِ مثبت را بیندازد (یعنی `_run_dl` واقعاً از آن رد می‌شود). **(۳ شناساییِ هزینهٔ فازِ probe — فقط ثبت، بدونِ کد)** با `run_download`ِ واقعی و yt-dlpِ جعلیِ **موفق** اندازه گرفته شد که یک probeِ موفقِ یوتیوب چه می‌خرد و چه ردی می‌گذارد: کوکی **برداشته و مصرف می‌شود**، ولی `ckuse:` (سطلِ ساعتی) دست‌نخورده می‌ماند چون `note_spend` صدا زده نمی‌شود؛ `dl_active.count` صفر است و `dlq:cnt`/`dlq:cd`/`dlq:mb` هر سه ست نمی‌شوند؛ و تنها ردِ باقی‌مانده `probe:{ref}` با TTL ۱۸۰۰ است. **دو یافته که در صورتِ مسئله نبودند:** probeِ **موفق** هیچ `dlstat`ی نمی‌نویسد (`_metric` در آن شاخه فقط روی شکست است)، پس حتی «چند probe انجام شد» هم شمرده نمی‌شود؛ و `DownloadCache` اصلاً ستونِ `url` **ندارد** — فقط هشِ `(url, selector)` — پس «آیا این لینک کش دارد؟» بدونِ selector سؤالِ **پرس‌ناشدنی** است نه صرفاً مبهم (هرچند فضای selector بسته و ۸تایی است: `best`/`audio` + `_TARGET_HEIGHTS`، پس یک `WHERE key IN (…)` ممکن است). تصحیحِ تصویرِ مسئله: `on_dl_pick` کش را **چک می‌کند** (`routers/download.py:290`)، پس لینکِ تکراریِ زیرِ probe امروز یک **کوکی** خرج می‌کند نه یک دانلود. حفرهٔ `_charge` به‌عنوان **تنها موردِ امنیتیِ** فهرست جدا ثبت شد (§۷). **هیچ‌کدام رفع نشد** — ترتیبِ توافق‌شده: اول شمارنده، بعد تصمیم. **اعمال:** کارِ ۱ فقط `tests/` است و هیچ استقراری نمی‌خواهد؛ کارِ ۲ `downloader.py`/`processing.py` را عوض می‌کند که روی نودِ دانلود و نودِ پردازش هم می‌دوند → `telabzar update` روی مستر و `node/update.sh` اگر نودی وصل شد. بدونِ مهاجرت، بدونِ کلیدِ تازه، بدونِ رشتهٔ locale، بدونِ تغییرِ رفتار در مسیرِ سالم.
- 2026-08-17 — **کاورِ صوتی جاسازی می‌شود — یک فلگ، گیت‌خورده به مسیرِ صوت.** علامت: کاربر MP3 را ذخیره می‌کرد و در پخش‌کننده تصویری نمی‌دید. علت از قبل معلوم بود: خطِ فرمان `--write-thumbnail --convert-thumbnails jpg` داشت (کاور دانلود و روی دیسک می‌نشست) و `--embed-metadata` داشت، ولی `--embed-thumbnail` نداشت — و `--embed-metadata` فقط تگِ **متنی** می‌نویسد. **رفع یک خط است؛ کارِ واقعی تعیینِ دامنه بود.** **گیتِ `audio_only` قیدِ سخت است نه احتیاط (اجراشده از سورسِ yt-dlp):** `EmbedThumbnailPP` برای `ogg/opus/flac`ِ بی‌mutagen و برای هر پسوندِ ناشناخته `PostProcessingError` می‌دهد، و چون `--ignore-errors` نمی‌فرستیم `YoutubeDL.run_pp` دوباره raise می‌کند و **کلِ دانلود می‌شکند**؛ مسیرِ ویدیو روی منبعِ فقط‌صوتی دقیقاً همان پسوندها را می‌دهد (کد خودش برایش fallback دارد). مسیرِ صوت امن است چون خروجی **اثباتاً همیشه mp3** است و برای mp3 خودِ PP مستقیم ffmpeg با `-c copy` می‌زند. **دو ادعای اپراتور تصحیح شد و هر دو ثبت شدند:** (الف) نبودِ **AtomicParsley** برای این دامنه بی‌ربط است — برای mp3 اصلاً صدا زده نمی‌شود، و حتی برای m4a لایهٔ **دوم از سه** است (mutagen → AtomicParsley → ffmpeg) و `mutagen` در تولید هست چون `requirements-worker-dl.txt` از `yt-dlp[default]` استفاده می‌کند؛ (ب) شکستش **خاموش نیست، پرصداست** — دانلود را می‌شکند، و همین است که دامنه را لازم می‌کند. **کوچک‌کردنِ کاور بررسی و رد شد، با عدد:** آن `+۱۸٪` آرتیفکتِ یک نمونهٔ **۴٫۵ دقیقه‌ای** بود؛ کاور حجمِ ثابت است و روی پادکستِ واقعیِ ۱ تا ۳ ساعته `۱٫۳٪` تا `۰٫۴۴٪` می‌شود (جدول در §۷). و مکانیزمی هم نیست: yt-dlp گزینهٔ resize ندارد و `--ppa ThumbnailsConvertor:…` وقتی تامبنیل از قبل jpg باشد **اصلاً اجرا نمی‌شود** (اجراشده: `resolve_mapping` مقدارِ skip می‌دهد)، پس هر روشِ قابلِ‌اتکا یعنی re-embed یعنی یک پاسِ کاملِ صوت یعنی خوردنِ بردِ #۱۱۵. **فایلِ jpg بعد از جاسازی می‌ماند** (`already_have_thumbnail = opts.writethumbnail`، با کامنتِ خودِ yt-dlp) و چیزی را نمی‌شکند: `_newest` با پسوند فیلتر می‌کند و مسیرِ ytdlp `paths`ِ تک‌عضوی می‌سازد — و **لازم** است، چون کارت از همان فایل می‌خواند. **یافتهٔ جانبی که در پرامپت نبود:** کارتِ صوتی **هرگز** از ما تامبنیل نمی‌گیرد، روی هیچ پلتفرمی — شاخهٔ `audio` در `_send_typed` پارامترِ `thumb` را نادیده می‌گیرد و گیتِ `kind == "video"` اصلاً آماده‌اش نمی‌کند؛ پس کاوری که روی کارتِ ساندکلاود دیده شده از کدِ ما نیامده بود. عمداً **در این کار ساخته نشد**: تلگرام کاورِ ID3 را می‌خواند، پس اول جاسازی مستقر شود و بعد اندازه گرفته شود (§۷). **تست‌ها (۷۱۴ → ۷۲۶):** هارنس خودِ `FFmpegExtractAudioPP`ِ yt-dlp را اجرا می‌کند و فقط **ffprobe** را جعل می‌کند (نه تصمیم را). **کنترلِ منفی پیش از اتکا زده شد و شرطِ اعتبارِ بقیه است:** ورودیِ `aac` باید `libmp3lame` بدهد و می‌دهد، در حالی که ورودیِ `mp3` **هیچ فراخوانیِ ffmpegی** نمی‌سازد — یعنی بردِ بدونِ ترنسکدِ #۱۱۵ سرِ جایش است. روی سورسِ پیش از رفع **دقیقاً ۱ تست می‌افتد** (خودِ ادعای جاسازی) و ۱۱ تای دیگر عمداً هر دو طرف سبزند چون کنترل‌اند؛ غیرِتوخالی‌بودنشان از **۴ سابوتاژ (۴/۴، شاملِ یک کنترلِ معکوس)** می‌آید نه از اجرای pre-fix. **اعمال:** `downloader.py` روی نودِ دانلود هم می‌دود → `telabzar update` روی مستر و `node/update.sh` اگر نودی وصل شد. بدونِ مهاجرت، بدونِ کلیدِ تازه، بدونِ رشتهٔ locale. ردیف‌های کشِ موجود **بازنویسی نمی‌شوند** (کلید عوض نشده)، پس فایل‌های قبلاً تحویل‌شده همچنان بی‌کاورند و فقط دانلودهای تازه کاور می‌گیرند.
- 2026-08-17 — **تگ‌های خامِ HTML در کپشن — و اینکه چرا رفعِ بی‌قید بدتر از خودِ باگ بود.** علامت (تستِ پذیرشِ کست‌باکس روی تولید): توضیحاتِ اپیزود با `<strong>`/`</p>`/`<p>`ِ خام به کاربر می‌رسید. توضیحاتِ پادکست HTML است و اکسترکتورِ `html5` خام برمی‌داردش؛ `cards.post_view` هم escapeش می‌کند که **درست است** — گامِ غایب **پاک‌کردن** بود نه escape. **مهم‌ترین یافته این بود که فرضِ اولیه («مسئله عام است پس رفع هم عام») نصفش غلط بود:** `clean_caption` مشترک است (شش فراخوان، **چهار** مسیرِ رندر: کارت · آلبوم · Rich · کش) و کپشنِ **سادهٔ** اینستاگرام هم از آن رد می‌شود. پاک‌سازیِ بی‌قید اندازه‌گیری شد و روی ۱۰ متنِ سادهٔ واقعی **۳ تا را خراب کرد**، بدترینش `کد: if (a<b) return;` → **`کد: if (a`** (چون `<b>` نامِ تگِ واقعی است و پارسر تا انتهای رشته را می‌بلعد). یعنی رفعِ بی‌قید یک زشتیِ کوچک را با یک **باگِ واقعی در پرترافیک‌ترین مسیر** عوض می‌کرد. پس رفع در جای عام نشست ولی به `_HTML_GATE` گیت خورد — فهرستِ **صریح و بستهٔ** تگ‌ها با شرطِ پایانِ تگ (`>`/`/`/فاصله)، همان اصلِ `safety.STRONG_TOKENS`؛ اندازه‌گیری‌شده **۱۲ از ۱۲** متنِ ساده ساکت و **۸ از ۸** متنِ HTMLدار شلیک. **پیاده‌سازی با `html.parser` است نه رجکس**، چون `<[^>]+>` روی «اگر x < 5 باشد و y > 2» متن را می‌خورد (اجراشده: «اگر x  2»). سه تلهٔ دیگر: ترتیب باید **strip قبل از unescape** باشد وگرنه متنی که مبدأ عمداً escape کرده خورده می‌شود (`&lt;script&gt;…` → `alert(1)`)، تگِ **بلوکی** باید `\n` بدهد نه حذف شود وگرنه پاراگراف‌ها می‌چسبند، و `&nbsp;`→`\xa0` و فاصلهٔ ابتدای خط باید در `strip_html` جمع شوند نه در مسیرِ مشترک (آن‌جا `ln.rstrip()` است و `strip()`کردنش تورفتگیِ عمدیِ کاربر را می‌خورد). **تصمیمِ لینک (اپراتور): متن + آدرس** وقتی http(s) است و در متن نیست، و لنگرِ **خالی** خودِ آدرس را می‌دهد — «فقط متنِ لنگر» همان تحویلِ ناقصِ بی‌نشانه بود؛ `mailto:`/`javascript:` هرگز وارد متن نمی‌شوند. **سقفِ ۱۰۲۴ خاموش نیست** (`…` می‌گذارد) و آخر اعمال می‌شود، پس یک آدرس می‌تواند وسط بریده شود — پذیرفته‌شده و علامت‌دار؛ خودِ سقف عمداً دست‌نخورده ماند چون مسیرِ مشترک است. **امنیت:** `parse_mode=HTML` سراسری است و سه مسیر از چهار مسیر escape می‌کنند؛ مسیرِ چهارم (`InputRichBlockParagraph.text`) بررسی شد و نوعش `RichTextUnion` است که `str` را شامل می‌شود و قالب‌بندی‌اش با **اشیای ساختاری** بیان می‌شود نه مارک‌آپ، پس unescape سطحِ تزریق نمی‌سازد. **تست‌ها (۶۶۸ → ۷۱۴):** فیکسچر **خروجیِ عینیِ `yt-dlp --dump-json`** است (سه `<p>`، `<strong>`ِ تودرتو کنارِ ایموجی، و یک `<p>`ِ فاصله‌دار) و چون خودِ کست‌باکس بریده‌اش، سقف با فیکسچرِ دست‌سازِ بلندِ جدا تست می‌شود. **۶ از ۱۰ ادعای رفتاری روی سورسِ پیش از رفع می‌افتند** و **کنترلِ متنِ ساده روی هر دو طرف ۱۲/۱۲** است — که دقیقاً همان چیزی است که باید. کپشنِ نمونهٔ اینستاگرام صادقانه «نماینده، نه ضبطِ واقعی» علامت خورده چون هیچ کپشنی در فیکسچرهای ضبط‌شدهٔ ریپو نبود. **۶ سابوتاژِ تازه، ۶/۶** — از جمله «گیت را بردار» که کنترلِ متنِ ساده را می‌اندازد. **اعمال:** `downloader.py` روی نودِ دانلود هم می‌دود → `telabzar update` روی مستر و `node/update.sh` اگر نودی وصل شد. بدونِ مهاجرت، بدونِ کلیدِ تازه، بدونِ رشتهٔ locale. ردیف‌های کشِ موجود دست‌نخورده‌اند (کپشن جزءِ کلید نیست) ولی `post_caption`ِ ذخیره‌شدهٔ قبلی همچنان تگ دارد — با دانلودِ بعدیِ همان لینک بازنویسی می‌شود.
- 2026-08-17 — **پشتیبانیِ کست‌باکس: بازنویسیِ لینکِ کوتاه، گاردِ SSRF، کلیدِ کش، و ردِ کانال.** انگیزه: کست‌باکس پلتفرمِ پادکست است و لینکی که کاربر می‌فرستد کار نمی‌کرد. **اولین یافته این بود که کارِ کمتری لازم است تا آنچه به‌نظر می‌رسید:** yt-dlp ۲۰۲۶.۰۷.۰۴ صفحهٔ اپیزود را با اکسترکتورِ `html5` از قبل می‌خواند (اندازه‌گیریِ اپراتور: `/ep/798014224` → عنوانِ فارسیِ درست، دانلودِ ۴٫۱۶MB)، پس **ماژولِ اختصاصی لازم نبود**؛ فقط فرمِ کوتاهِ `/vb/` — یعنی خروجیِ دکمهٔ Shareِ اپ — روی صفحهٔ واسطهٔ `d.castbox.fm/dynamic-link/redirect?link=…` می‌ایستاد. **رفع رشته‌ای و بی‌شبکه است:** هر فرمِ اپیزود به `/ep/<eid>` بازنویسی می‌شود (همان فرمی که اندازه‌گیری‌شده کار می‌کند) و `link=` هم در رشته‌ای است که از قبل در دست داریم، پس هیچ ریدایرکتی دنبال نمی‌شود — نه درخواستی به مسیرِ داغ اضافه می‌شود، نه رفتارِ ریدایرکت‌دنبال‌کن که خودش سطحِ SSRF است. محدودیتش صریح ثبت شد: فرمِ کوتاهِ تازهٔ کست‌باکس یک خطِ الگو می‌خواهد، ولی شکستش **پرصداست** (`dl_bad_link`) نه خاموش. **SSRF بخشِ اصلیِ کار بود، نه پاورقی‌اش.** چون `d.castbox.fm` **واقعاً** castbox.fm است، کاربر می‌تواند خودش `…?link=http://169.254.169.254/` را بسازد و درِ ورودی — که فقط هاستِ بیرونی را می‌سنجد — عبورش می‌دهد (اجراشده روی هر چهار payload: متادیتای ابری، لوپ‌بک، WGِ داخلی، و IPِ عددی). **پس گیت‌کردن به دامنهٔ castbox.fm جواب نبود.** دو دفاعِ مستقل: `castbox_target` URL را **بازمی‌سازد** و هرگز مقداری را عبور نمی‌دهد (دفاعِ اول و اصلی)، و `resolve_castbox` خروجی را از `is_safe_url_resolved` رد می‌کند — که ساختاراً زائد است ولی تنها لایه‌ای است که «خودِ castbox.fm داخلی شود» را می‌گیرد، و یک نقطهٔ خروج با یک قرارداد می‌سازد تا مسیرِ الگویی و مسیرِ `link=` دو سطحِ ایمنی نداشته باشند. **و اینکه این دو باید تستِ جدا داشته باشند با اجرا معلوم شد نه با استدلال:** اولین اجرای دفترچهٔ سابوتاژ نشان داد برداشتنِ دفاعِ اول تستِ انتها‌به‌انتها را **نمی‌اندازد**، چون گارد payload را می‌گیرد و «هیچ جابی ساخته نشد» همچنان صادق است — یعنی یک سابوتاژِ موفق «نگرفت» گزارش می‌شد. حالا سه تست در سه سطح است و سابوتاژِ ادعای انتها‌به‌انتها **هر دو** لایه را برمی‌دارد. **تلهٔ دو-شناسه‌ای، بهترین کَچِ این کار:** `webpage_url`ِ واقعی `…-id5174947-id798014224` است (اول کانال، بعد اپیزود) و الگوی طبیعیِ `id(\d+)` شناسهٔ **کانال** را برمی‌دارد — رفعی که ظاهراً درست و عملاً غلط است، هم‌خانوادهٔ `acodec`ِ ساندکلاود و `srcset`ِ اینستاگرام، و کنترلِ معکوسش نگه داشته شد. **کانال رد می‌شود با پیامِ روشن** (رشتهٔ تازهٔ `dl_castbox_channel` در دو زبان)، چون اندازه‌گیری نشان داد yt-dlp روی `/va/` هم به همان صفحهٔ واسطه می‌خورد و اصلاً به صفحهٔ کانال نمی‌رسد — و آن صفحه هم تگِ `<audio>` ندارد، پس «آخرین اپیزود» یعنی پارسِ دستیِ صفحه و مسموم‌کردنِ کش (کلیدِ کانال به یک اپیزودِ مشخص می‌چسبد و فردا باید جوابِ دیگری بدهد). **کش:** `cb:ep:`/`cb:ch:` — **هشت** شکل به **دو** کلید (اجراشده)، شاملِ اسلاگِ فارسیِ URL-encoded که واردِ کلید نمی‌شود و صفحهٔ واسطه که مجانی جمع می‌شود؛ نیمهٔ دومِ کش (`_canonical_url` از `webpage_url`) از قبل آماده بود چون فقط به `_MATCH_PLATFORMS` گیت خورده و کست‌باکس عمداً آن‌جا **نیست**. **دو چیزی که بررسی شد و لازم نبود:** انتخابگرِ فرمت (`bv*+ba/b` و `ba/b` روی منبعِ فقط‌صوتی همان تک‌فرمت را می‌دهند — تستش به‌عنوان سند نگه داشته شد و روی سورسِ پیش از رفع هم سبز است)، و سقفِ مدت (`dl_max_duration_min` پیش‌فرضش `0` است، پس پادکستِ ۱–۳ ساعته رد نمی‌شود؛ نمونهٔ واقعی ۴٫۵ دقیقه و ۴٫۱۶MB بود). **تست‌ها (۶۳۵ → ۶۶۸):** ۳۳ تست، ۲۹ تای‌شان روی سورسِ پیش از رفع می‌افتند و **۳ تای باقی‌مانده عمداً هر دو طرف سبزند** — یکی‌شان تستِ انتخابگر است که دقیقاً ثابت می‌کند آن‌جا چیزی خراب نبود. **۱۰ موردِ سابوتاژِ تازه، ۱۰/۱۰.** **یک نقصِ هارنس که خودِ این کار ساخت و گرفت:** نسخهٔ اولِ سنجشِ انتخابگر `incomplete_formats` را `False` هاردکد کرده بود و یک نقصِ تولیدیِ **خیالی** اختراع کرد که نزدیک بود واردِ نقشه شود؛ yt-dlp آن فلگ را خودش می‌سازد. در §۶ به‌عنوان نیمهٔ **false fail**ِ درسِ هارنس ثبت شد (همهٔ نمونه‌های قبلی false pass بودند) و گاردش یک تست است نه یادداشت. همان نقص به‌شکلِ **نهفته** در `tests/test_soundcloud_path.py` هم هست — **باگ نیست و نتیجهٔ #۱۱۵ عوض نمی‌شود** (اجراشده)، ولی برای هر انتخابگرِ حاویِ `b` روی منبعِ تک‌نوع غلط می‌دهد؛ در §۷ ثبت شد، رفعش PRِ جدا. **و یک تصحیحِ فرض که ثبت شد تا نفرِ بعد رویش تصمیم نگیرد:** `dl_allow_unknown` پیش‌فرضش **`True`** است، پس این کار «رفعِ سکوت» نبود — لینکِ کست‌باکس امروز هم به yt-dlp می‌رسد و کاربر خطای خام می‌گیرد؛ سکوت فقط وقتی است که ادمین خودش آن کلید را خاموش کند. **اعمال:** `downloader.py`/`dl_cache.py` روی نودِ دانلود هم می‌دوند → `telabzar update` روی مستر و `node/update.sh` اگر نودی وصل شد. بدونِ مهاجرت، بدونِ کلیدِ تنظیماتِ تازه، یک رشتهٔ locale در دو زبان. ردیف‌های کشِ قبلیِ `/ep/` زیرِ selectorِ `best` یتیم می‌مانند — **`DELETE` نمی‌خواهند** چون کلید عوض می‌شود و هرگز خوانده نمی‌شوند (برخلافِ اسپاتیفای که ردیفِ کهنه **سرو** می‌شد).
- 2026-08-17 — **مسیرِ ساندکلاود، سه کار در یک PR: انتخابگرِ فرمت، کلیدِ کش، و سه پیامِ بن‌بست.** **(۱ انتخابگر)** `ba/b`ِ عمومی `hls_aac_96k` را برمی‌داشت — ۹۶k، ۲۶ فرگمنتِ HLS، به‌علاوهٔ ترنسکدِ کاملِ AAC→MP3 — در حالی که `http_mp3_0_0` یک GETِ ساده و ۱۲۸k است (اندازه‌گیریِ اپراتور روی همان ترک: ۱٫۳۹MB/۶ث در برابرِ ۴٫۰۲MB/۲ث). حجمِ ~سه‌برابر **تصمیمِ آگاهانه** است، نه عارضه: ساندکلاود سرویسِ موسیقی است و m4a نمی‌خواهیم. **و مهم‌ترین یافته این بود که `-x --audio-format mp3` اصلاً لازم نیست دست بخورد:** `FFmpegExtractAudioPP.run` وقتی `target_format == filecodec` باشد `acodec='copy'` می‌گذارد و «Not converting audio» می‌دهد (از سورسِ نصب‌شده خوانده شد)، پس با انتخابِ mp3 ترنسکد **خودبه‌خود** حذف می‌شود — یک خط عوض شد نه دو تا. زنجیره `ba[ext=mp3][protocol^=http]/ba[ext=mp3]/ba/b` است: دُمِ `ba/b` دست‌نخوردهٔ امروز می‌ماند تا وقتی ساندکلاود MP3 را حذف کند خودش به AAC برگردد، بدونِ تغییرِ کد. **دو دامِ خاموش که فقط با اجرا دیده شدند:** `[acodec^=mp3]` — طبیعی‌ترین شرطی که آدم می‌نویسد — **هیچ تطبیقی ندارد**، چون `acodec` از `codecs="…"`ِ mime-type می‌آید و mp3ِ ساندکلاود `audio/mpeg` است که آن attribute را ندارد؛ و فرمِ بدونِ `[protocol^=http]` به **ترتیبِ ورودی** وابسته است و با جابه‌جاییِ فهرست به `hls_mp3_0_0` می‌افتد — همان درسِ لنگرِ `regexp`، این‌بار پیش از merge گرفته شد. شعاع فقط ساندکلاود است: `_selector_to_format` یک فراخوان دارد و پلتفرم را از `platform_of(url)` می‌گیرد، پس `tasks_download.py` برای این تغییر اصلاً لمس نشد و بقیهٔ `AUDIO_PLATFORMS` بیت‌به‌بیت همان `ba/b` را می‌گیرند (تستِ پارامتری). **(۲ کش)** سه فرمِ یک ترک سه کلید می‌ساختند. `sc:<user>/<slug>` فرم‌های `www.`/`m.`/کوئری‌دار را جمع می‌کند، ولی `on.soundcloud.com/<code>` — یعنی همان چیزی که دکمهٔ Shareِ اپ **همیشه** می‌دهد — شناسهٔ محتوا نیست و هیچ الگویی جمعش نمی‌کند. سه گزینه سنجیده شد و ارزان‌ترین برنده شد: yt-dlp خودش ریدایرکت را دنبال می‌کند و `webpage_url` فرمِ کانونیک را می‌دهد، پس `put_cached` یک ردیفِ **دوم** می‌نویسد — صفر درخواستِ شبکه و صفر سطحِ SSRF، در برابرِ resolve-پیش-از-enqueue که هر دو را می‌خرید. دو قیدِ باربر: کلیدِ دوم از همان `cache_key` رد می‌شود نه از URLِ خام (به‌تصریحِ اپراتور — وگرنه ردیفِ دوم زیرِ یک شکلِ خاص می‌نشیند و شکلِ دیگر باز miss می‌خورد)، و نوشتنِ دوم به `platform not in _MATCH_PLATFORMS` گیت خورده چون برای اسپاتیفای/اپل `webpage_url` **یوتیوب** است و آن ردیف `_MATCH_VERSION` نمی‌گیرد. شورت‌کدِ **متفاوتِ** همان ترک همچنان miss می‌خورد — حدِ روش، صریح ثبت شد. **(۳ پیام‌ها)** هر سه دربارهٔ «سشن» حرف می‌زدند برای سطلی که سشن ندارد: «اکانتِ دیگری را امتحان می‌کنم» با `cookie_name`ِ تهی، و در پایان «ادمین باید کوکی تنظیم کند» یا «سشن دیگر معتبر نیست». مرز همان تفکیکِ سه‌حالتهٔ `_alert_if_low` است و **کنترل‌ها از خودِ رفع مهم‌ترند**. یک رشتهٔ locale تازه (`dl_login_unsupported`، fa+en). **تست‌ها (۶۰۱ → ۶۳۵):** ۳۴ تست. `yt-dlp` به `requirements-dev.txt` اضافه شد تا انتخاب با **موتورِ خودِ yt-dlp** سنجیده شود نه با assert روی رشتهٔ انتخابگر — بدونش دامِ `acodec` گرفته نمی‌شد، و `_ADMIN_ONLY` هم فهرستِ دستی است پس یک `import yt_dlp` بی‌آنکه گارد بگیردش روی رانر قرمز می‌شد. **۱۱ سابوتاژِ تازه (۳ معکوس)، و سه‌تایشان تستِ خودم را رد کردند — که مهم‌ترین بخشِ این کار بود:** فیکسچرِ فرمت‌ها AAC را **اول** گذاشته بود و چون `ba` آخرین را برمی‌دارد، تستِ اصلی روی سورسِ پیش از رفع هم سبز می‌ماند (توخالی، با ظاهرِ سالم) — حالا یک کنترلِ منفی صریح پین می‌کند که هارنس `ba/b` → `hls_aac_96k` را بازتولید کند؛ تستِ «کلیدِ دوم از نرمال‌ساز رد می‌شود» فرمِ `www.` را می‌داد که شاخهٔ عمومی از قبل جمعش می‌کند، پس به فرمِ `m.` عوض شد؛ و «استخرِ سوخته» یک اکانتِ **سالم** می‌ساخت پس گاردِ غلط (`not usable`) از آن رد می‌شد — حالا اکانت واقعاً فریز می‌شود و پیش‌شرطِ `(1, 0)` با assert پین شده. **و یک نقصِ خودِ رفع را هم تست گرفت:** `_no_account_possible` یک `ping` لازم داشت نه فقط `try`، چون `pool_counts`/`was_stocked` خطای Redis را می‌بلعند و «سطل خالی» را از «Redis خواب» جدا نمی‌کنند. **اعمال:** `telabzar update` روی مستر (و `node/update.sh` اگر نودی وصل شد). بدونِ مهاجرت، بدونِ کلیدِ تنظیماتِ تازه. ردیف‌های کشِ ساندکلاودِ قبلی زیرِ کلیدِ قدیمی یتیم می‌مانند (جدول eviction ندارد)؛ `DELETE` تک‌باره‌اش نوشته شد ولی **اجرا نشد** — تصمیمش با اپراتور است.
- 2026-08-16 — **درِ ورودیِ لینک لنگر خورده بود: `magic_filter.regexp` پیش‌فرضش `match` است نه `search`.** یک خط کد، و بزرگ‌ترین چیزی که ممیزیِ ساندکلاود پیدا کرد — ولی **ربطی به ساندکلاود ندارد**، هر پلتفرمی را می‌گیرد. `app/routers/download.py` هندلرِ لینک را با `F.text.regexp(r"https?://")` ثبت می‌کرد و شاخهٔ `if mode is None` در `magic_filter/magic.py` مقدارِ `RegexpMode.MATCH` می‌گذارد، یعنی `pattern.match` که به موقعیتِ صفر لنگر می‌خورد؛ پس متن باید **با** `http` شروع می‌شد. اندازه‌گیری‌شده روی شیءِ **واقعیِ** فیلتر: متنِ دوخطیِ دکمهٔ Shareِ اپِ ساندکلاود، اشتراکِ دوخطیِ یوتیوب، «اینو بگیر <لینک>» و حتی **یک فاصلهٔ** پیش از لینک همه رد می‌شدند و — چون ترتیبِ روترها `start → admin → ops → download → files` است — به catch-allِ `files.py` می‌افتادند، یعنی کاربر در جوابِ یک لینکِ **معتبر** «یک فایل بفرست» می‌گرفت. جوابِ فعالانه گمراه‌کننده، نه سکوت. **چرا ماه‌ها زنده ماند، و این درسِ اصلی است:** لینکِ خامِ تک‌خطی (کپیِ آدرس‌بار، مسیرِ دسکتاپ) کار می‌کرد، **و هیچ شمارنده‌ای این را نمی‌دید** — `_metric`/`dlstat:*`/`dlctx:`/`ckuse:` همه داخلِ `run_download`اند و وقتی فیلترِ روتر رد شود جابی ساخته نمی‌شود که چیزی بشمارد. یعنی این کاربران در **مخرج** هم نبودند: پنل سالم به‌نظر می‌رسید. تله‌متری فقط چیزی را می‌بیند که وارد شده باشد؛ برای درِ ورودی تنها سنجهٔ امروزی شکایتِ کاربر است. **نسخه‌محور نیست** — magic-filter ۱.۰.۹ تا ۱.۰.۱۲ هر چهار پیش‌فرضشان `match` است (اجراشده، از خودِ ویل‌ها) و aiogram 3.30 هم overrideاش نمی‌کند (`aiogram/utils/magic_filter.py` فقط `as_` اضافه می‌کند) و `magic-filter>=1.0.12,<1.1` را پین می‌کند پس `mode=` در دسترس است. **اثرِ جانبی پیش از رفع سنجیده شد، نه بعدش:** پنج ورودی `miss → HIT` می‌شوند و دوتایشان ترسناک به‌نظر می‌رسند — `/start …` و `/admin …`ِ حاوی لینک — ولی هرگز به download نمی‌رسند چون روترِ دستورها قبل‌تر ثبت شده و `admin_cmd` برای غیرِادمین `return` می‌کند نه `SkipHandler`؛ و شمارشِ کلِ ریپو نشان داد **تنها هندلری که `SkipHandler` می‌زند `cookie_paste` است**، یعنی تنها درزِ ممکن، که رفتارش هم درست است. **تست‌ها (۵۸۶ → ۶۰۱):** ۱۵ تست، و طراحی‌شان دو قیدِ سخت دارد. **(۱)** تست در سطحِ **خودِ فیلتر** است نه `find_url` — چون `find_url` از روزِ اول سالم بود (روی همان متنِ دوخطی لینک را درست درمی‌آورد)، پس تستی که آن را صدا بزند **از قبل سبز است** و هیچ‌چیز ثابت نمی‌کند؛ باگ یک لایه بالاتر بود. **(۲)** فیلتر از **ثبتِ زندهٔ روتر** بیرون کشیده می‌شود (`FilterObject.magic`)، نه با بازنویسیِ الگو در تست — الگوی دست‌نویس یک کپیِ دوم است و روزی که سورس عوض شود ساکت می‌ماند، همان «دو کپیِ دست‌نویس واگرا می‌شوند» که §۷ برای `remove_cookie_file` ثبت کرده. و **عمداً هیچ fallbackِ ASTی ندارد**: اگر `app.routers.download` روی رانر import نشود تست باید **بیفتد** نه اینکه بی‌صدا چیزِ دیگری بسنجد — همان ردهٔ «سندباکس در برابر CI» که §۶ سه نمونه‌اش را دارد. ورودی `aiogram.types.Message`ِ واقعی است نه داکل (درسِ `aiogram_double`). **۴ سابوتاژِ تازه (۲ تای معکوس)، هر چهار همان‌طور که ثبت شده رفتار کردند:** برگرداندنِ پیش‌فرض ۵ شکلِ رفتاری + گاردِ AST را می‌اندازد و ۸ کنترل را سبز می‌گذارد؛ شکلِ **هم‌ارزِ** `search=True` هیچ‌چیز را نمی‌اندازد (اثبات اینکه تست رفتار را می‌سنجد نه رشتهٔ `mode="search"` را)؛ و برداشتنِ کلِ فیلتر همه را می‌اندازد (اثبات اینکه استخراج واقعاً زنده است). **گاردِ کشف‌محور** اضافه شد چون این دام **پیش‌فرضِ کتابخانه** است نه اشتباهِ یک‌بارهٔ ما: هر `regexp(` زیرِ `app/` باید `mode`/`search` صریح داشته باشد. امروز فقط **یک** استفاده از `regexp` در کلِ `app/` هست، پس کپیِ واگرایی وجود نداشت. **تغییرِ رفتاری که آگاهانه پذیرفته شد:** لینکِ هاستِ ناشناخته با `dl_allow_unknown`ِ خاموش حالا **سکوت** می‌گیرد به‌جای «یک فایل بفرست»؛ پیامِ تازه یعنی رشتهٔ locale و شعاعِ بزرگ‌تر برای یک رفعِ فوری، و مسیر نادر است — در §۷ به‌عنوان کارِ بعدیِ ممکن ثبت شد. **اعمال:** `routers/download.py` فقط در پروسهٔ ربات اجرا می‌شود → `telabzar update` روی مستر. بدونِ مهاجرت، بدونِ کلیدِ تازه، بدونِ رشتهٔ locale.
- 2026-08-16 — **حلقهٔ probe به اندازهٔ حلقهٔ fetch ایمن شد: کلاسِ خطا، خطِ لاگ، سقفِ تلاش.** سه تغییرِ کوچک در یک تابع و یک هدفِ واحد؛ همه در `run_download`، شاخهٔ `phase == "probe"`. **(۱ کلاسِ خطا)** `ck.mark_fail(redis, cname)` بی‌کلاس صدا زده می‌شد، پس از هر شاخهٔ دسته‌بندیِ `cookies.mark_fail` رد می‌شد و به سخت‌ترینشان می‌افتاد؛ حالا `error_class=cls, message=msg` می‌گیرد، دقیقاً مثلِ مسیرِ fetch که همین را از `_resolve_blame` می‌گیرد. **واحدِ سود «استخر» است نه «اکانت»** — اندازه‌گیری‌شده روی استخرِ ۵تایی، یک استورمِ `transient`: ۰ از ۵ قابلِ‌استفاده → ۵ از ۵؛ و برای `bot_check` هر دو حالت ۰ از ۵، یعنی رفع تقصیرِ درست را نرم نکرده. `needs_human` هم حالا `_alert_checkpoint` را صدا می‌زند، که probe اصلاً نداشت و اکانتِ چک‌پوینتی بی‌صدا کنار می‌رفت. **(۲ خطِ لاگ)** تنها چیزی که توزیعِ خطای probe را قابلِ اندازه‌گیری می‌کند: تا امروز این شاخه فقط نامِ اکانت را لاگ می‌کرد و متنِ خطا را هرگز، پس هر سرشماریِ لاگ عملاً آمارِ fetch بود — همان اشتباهی که در کامیتِ `2b7c34f` تصحیح شد. شکل عمداً هم‌ریختِ خطِ `attempt %d failed (%s)`ِ حلقهٔ fetch است تا یک گرپ هر دو فاز را کنارِ هم بیاورد، و **تصمیمِ بعدی (`dl_ux_youtube`) روی همین عدد بنا می‌شود**. **(۳ سقفِ تلاش)** `dl_max_cookie_tries` فقط در fetch خوانده می‌شد، پس یک شکستِ کوکی‌محور کلِ استخر را می‌پیمود و هیچ کلیدِ پنلی محدودش نمی‌کرد. **گزینهٔ «بردنِ probe به `_resolve_blame`» عمداً ساخته نشد** — دلیلش در §۷ است (برچسبِ کلاس را با `transient` بازنویسی می‌کند، مرزِ `>=2` تست‌نشده، و با کرانِ «حداکثر ۷ شکستِ probe در روز» توجیه ندارد). **تست‌ها (۵۶۹ → ۵۸۶):** ۱۷ تستِ تازه، **۱۱ تای رفتاری روی سورسِ پیش از رفع می‌افتند** (با revertِ واقعیِ فایل سنجیده شد، نه استدلال) و ۶ تا کنترل‌اند که باید هر دو طرف سبز بمانند — از جمله کنترلِ معکوسِ اصلی: bot-check که فرمِ غالبِ تولید است و **باید** اکانت را بسوزاند. هارنس یک `yt-dlp`ِ **اجراییِ واقعی** روی PATH است نه `D.probe`ِ ماک‌شده، چون پیامی که `classify_error` می‌بیند خروجیِ `_stderr_summary` است نه رشتهٔ خامی که تست دوست دارد. **سه تلهٔ توخالی‌شدن که با اجرا پیدا شدند و طراحی دورشان می‌زند:** `assert fail_streak == 0` روی متنِ رایجِ ۴۲۹ **امروز هم سبز است** (چون `_is_cookie_error` آن را نمی‌گیرد و اصلاً به `mark_fail` نمی‌رسد)، پس تست‌ها روی متنی نوشته شدند که واقعاً از گارد رد می‌شود و پیش‌شرطش با assert پین شده؛ `assert bot.messages` هم سبز است چون `_alert_if_low` یک DMِ 🔴 می‌فرستد، پس ادعا روی نشانهٔ 🛑 و کلیدِ `ckcheck:` است؛ و `last_error != ""` با فراموشیِ `message=` سبز می‌ماند (`'transient'`ِ خالی)، پس تکه‌ای از متنِ خودِ موتور هم خواسته می‌شود — و همین سابوتاژِ اختصاصی دارد. **۸ سابوتاژِ تازه (۳ تای معکوس)؛ کلِ دفترچه ۳۱/۳۱.** الگوی سقف عمداً بلند است چون `if max_tries and attempts >= max_tries:` حالا **دو بار** در فایل است (fetch و probe) و فرمِ کوتاهش `SabotageError` می‌دهد — همان تله‌ای که یک‌بار `trim_audio` را به‌جای `trim_video` خراب کرد. **و اولین اجرای دفترچه یک نقصِ گزارشی در تستِ خودم پیدا کرد:** idهای خودکارِ `parametrize` از متنِ پیام ساخته می‌شدند و **فاصله** داشتند، و چون دفترچه نامِ تستِ افتاده را با شکستن روی فاصله برمی‌دارد، یک سابوتاژِ کاملاً **موفق** به‌شکلِ «نگرفت» گزارش شد؛ با `ids`ِ صریحِ بی‌فاصله رفع شد. **اعمال:** `tasks_download.py` روی نودِ دانلود هم می‌دود → `telabzar update` روی مستر و `node/update.sh` روی نود اگر روزی وصل شد. بدونِ مهاجرت، بدونِ کلیدِ تازه، بدونِ رشتهٔ locale.
- 2026-08-16 — **کیفیتِ شواهدِ مسیرِ یوتیوب: پنج تصحیح، جدا از هر پیاده‌سازی. بدونِ کدِ اجرایی.** این ورودی عمداً از PRِ رفع جداست، چون دربارهٔ **درستیِ استدلال** است نه دربارهٔ کد، و نباید به سرنوشتِ آن گره بخورد. **(۱ واحدِ آسیب استخر است نه اکانت)** جدولِ per-accountی که اول کشیدم گمراه‌کننده بود: حلقهٔ probe سقفِ `dl_max_cookie_tries` ندارد (آن کلید فقط در حلقهٔ fetch خوانده می‌شود)، پس یک خطای واحد تا تهِ استخر می‌رود و چون `mark_fail` بی‌کلاس صدا زده می‌شود هر اکانتِ لمس‌شده ضربه می‌گیرد. اندازه‌گیری‌شده روی استخرِ ۵تایی با `run_download`ِ واقعی: `transient` امروز **۰ از ۵** قابلِ‌استفاده می‌گذارد و با پاس‌دادنِ کلاس **۵ از ۵**؛ `bot_check` هر دو حالت ۰ از ۵. یعنی یک `JSONDecodeError` کلِ استخر را می‌خواباند، و برخلافِ جدولِ تک‌اکانتی این نتیجه به توزیعِ نسنجیدهٔ خطای probe **وابسته نیست** — اکیداً بدتر نمی‌شود. **(۲ کرانِ بالا، از اپراتور)** `dlstat:youtube:fail` در دو روز ۷ و ۶ بوده، پس شکستِ probe حداکثر ۷ در روز است؛ و کران شل‌تر هم هست چون آن شمارنده **شش** محل دارد نه دو تا (probe، fetch، و سه ردِ سیاستیِ `AgeRestricted`/حجم/محتوا). نتیجه‌ای که تصمیم را ساخت: بنچِ کلِ استخر **ممکن ولی محدود** است، پس بیمهٔ ارزان توجیه دارد و بازآراییِ بزرگ نه. **(۳ واگراییِ سوم)** `_is_cookie_error` عبارتِ `429`/`too many requests` را ندارد ولی `classify_error` دارد، پس یک ۴۲۹ با متنِ رایج اصلاً به `mark_fail` **نمی‌رسد**؛ همین‌طور `connection reset` و `read timed out`. و صریح نوشته شد که «نرسیدن» برای خودِ اکانت **درست** است (محدودیتِ نرخ نباید اکانت بسوزاند) و آنچه ممکن است غلط باشد **نچرخیدن به اکانتِ بعدی** است — تغییرِ جدا، ثبت شد و ساخته نشد. **(۴ گزینهٔ «ب» رد شد)** بردنِ probe به `_resolve_blame` اندازه‌گیری شد و کار می‌کند (استورمِ سه‌اکانتی: «هر سه ضربه» → «هیچ ضربه + کول‌داونِ خروجی»)، ولی شاخهٔ exit-blame عمداً `error_class=ck.TRANSIENT` می‌دهد، پس در موردِ غالب پنل `transient` نشان می‌دهد نه `bot_check` — سودِ تشخیصی‌اش تا حدی معکوس است. به‌علاوهٔ سه ایرادِ ردیه: مرزِ `>=2` اکانت تست‌نشده، بی‌اثر روی مسیرِ برد، و `_alert_if_low` که جابه‌جا کردنش برای `n>=2` جواب نمی‌دهد چون `UNPROVEN` عضوِ `USABLE` است. با کرانِ ۷، توجیه ندارد. **(۵ `dl_ux_youtube = quick` معلق شد)** حذفِ کاملِ مصرفِ کوکیِ probe با یک کلید، ولی هزینهٔ محصولیِ واقعی دارد (منوی کیفیت) و عددی که تصمیم را می‌سازد هنوز وجود ندارد؛ به‌عنوان **تصمیمِ معلق با هزینه‌اش** ثبت شد نه به‌عنوان توصیه. **روشِ این ورودی هم ثبت‌کردنی است:** هر پنج مورد از یک پاسِ **ردیه‌ای** درآمدند که تنها کارش رد کردنِ ادعاهای پاسِ قبلی بود، و مهم‌ترین‌شان (انتساب ۲۹/۳۲ به probe، که در کامیتِ قبلی تصحیح شد) ادعای «تأییدشده»ی خودم بود — یعنی برچسبِ VERIFIED روی یک عدد، از تعمیمِ اشتباهِ **دامنهٔ** آن عدد محافظت نمی‌کند.
- 2026-08-16 — **شناساییِ مسیرِ یوتیوب: چهار اندازه‌گیریِ تولید ثبت شد و اولویت‌ها را بازچید. بدونِ کدِ اجرایی.** **(۱ PO token بی‌اثر است — و چهار حالت لازم بود نه دو تا)** یک ویدیو، چهار آرم: ناشناس+pot → bot-check · ناشناس بی‌pot → bot-check · کوکی+pot → OK (۵۹۱۴۵۶ بایت) · کوکی بی‌pot → OK (۵۹۱۶۲۱ بایت). ۱۶۵ بایت اختلاف = نویزِ متادیتا. **کنترلِ سلامت بخشِ تصمیم‌کننده بود:** pot-provider همان لحظه زنده بود (ping → `1.3.1`، آپ‌تایم ~۶ روز)، پس این «سرویس خراب است» نیست. طراحیِ چهارخانه‌ای عمدی است و در §۷ با همان جدول ثبت شد: بدونِ خانهٔ «ناشناس بی‌pot» می‌شد خواند «pot کار نمی‌کند»، بدونِ «کوکی+pot» می‌شد خواند «pot مضر است» — هر دو غلط. پیامدِ مستقیم: retryِ بدونِ pot یک اجرای دومِ کاملِ yt-dlp می‌خرد که اثباتاً هیچ نمی‌دهد، و هزینه‌اش زمانِ ورکر نیست بلکه یک **برخوردِ اضافه با یوتیوب** است. دامنهٔ شاهد صریح نوشته شد (یک ویدیو، یک IP): برای «pot هرگز به‌درد نمی‌خورد» کافی نیست، برای «امروز این‌جا چیزی نمی‌خرد» کافی است. **(۲ نرخِ ناشناس ~۳۲٪)** دو اندازه‌گیریِ مستقل هم‌گرا: ۳۲ خطِ `anonymous attempt failed (bot_check)` در برابرِ ۴۷ جابِ یوتیوب (۴۱ ok + ۶ fail)، و ۱ از ۳ در تستِ مستقیم. **قیدِ پنجره بخشی از عدد است:** لاگ فقط از ۰۸:۱۸ همان روز است (ری‌استارتِ ورکر)، نه ۷ روز. این ادعای «~۳۰۰ ویدیو در ساعتِ» بولتِ `_ANON_FIRST` را تصحیح می‌کند — آن عددِ ویکیِ yt-dlp بود نه عددِ ما، و روی IPِ دیتاسنترِ ما یک‌سوم است؛ قاعده عوض نمی‌شود ولی هر طراحی‌ای که فرض کند anon-first کوکی را **حذف** می‌کند غلط است (اینستاگرام ~۸۷٪، یوتیوب هرگز آن نمی‌شود). **(۳ فرم‌های خطای نگران‌کننده وجود ندارند)** سرشماریِ کلِ پنجرهٔ لاگ: صفر «members-only»، صفر «Music Premium»، صفر «not available on this app»؛ تنها فرم، bot-checkِ استاندارد، ۲۹ بار. ریزه‌کاریِ شمارش هم ثبت شد وگرنه عدد سه‌برابر خوانده می‌شود: سه گرپِ `not a bot`/`cookies-from-browser`/`Sign in to confirm` **یک پیامِ واحد** را می‌شمارند. نتیجه: واگراییِ `_YT_BOTCHECK_HINTS` با `_CLASS_HINTS[BOT_CHECK]` — که گیتِ ارتقای anon→کوکی رویش سوار است — **واقعی ولی امروز بی‌هزینه**؛ درستیِ نهفته، بدونِ فوریت، و شرطِ فوری‌شدنش نوشته شد. **(۴ پیکربندی)** تنها کلیدِ غیرپیش‌فرض `dl_ux_youtube = probe`؛ `COBALT_URL` خالی یعنی شاخهٔ کوبالت **هرگز اجرا نمی‌شود** و نباید در هیچ تحلیلی حساب شود؛ `PROXY_URL` خالی؛ بدونِ نود. و چون همین یک کلید فازِ probe را روشن می‌کند، سه یافتهٔ شناسایی کنارش ثبت شد: probe **بی‌قیدوشرط** کوکی برمی‌دارد (متغیرِ `anon` ده‌ها خط پایین‌تر و فقط برای fetch است، پس قاعدهٔ anon-first برای دانلود سالم است ولی probe یک **درِ دومِ بی‌گارد** جلوی آن است)؛ یک دانلودِ **کاملاً موفق** یک درخواستِ احرازشده در probe می‌زند و بعد fetch را ناشناس می‌کند؛ و probe از **همهٔ** سقف‌ها بیرون است — پنج لینکِ پشتِ‌هم سه سشن را لمس کردند در حالی که `ckuse:*` خالی، `dl:active:z` صفر و `dlq:cnt`/`dlq:cd`/`dlq:mb` ست‌نشده ماندند (چون `note_spend` فقط در fetch است و `dl_active.enter` بعد از `return`ِ probe). سنجهٔ در دسترس برای حجمِ probe هم ثبت شد (`probe:{ref}` در برابرِ `dlctx:{ref}`، هر دو TTL ۱۸۰۰)، چون شمارندهٔ اختصاصی وجود ندارد. **اعمال:** هیچ‌چیز — فقط `CLAUDE.md`. دو اهرمِ بعدی (کلاسِ خطای probe، و retryِ بی‌pot) نقشه دارند و هنوز پیاده نشده‌اند.
- 2026-08-15 — **روزِ اولِ تولیدِ مسیرِ ناشناس: یک رده رسماً رد شد، یک ادعای من رد شد، و یک ردهٔ شکستِ تازه نام گرفت. بدونِ کدِ اجرایی.** **(۱ GraphQL — REFUTED، نه «هنوز نساخته‌ایم»)** §۷ تا امروز می‌گفت این رده را «فقط اگر تک‌عکسی‌ها در تولید افتادند» بساز — یعنی یک نامزدِ باز. نسخهٔ کاهش‌یافته اجرا شد (POST به `www.instagram.com/graphql/query`، `doc_id=8845758582119845`، هدرهای `X-IG-App-ID` + `X-FB-Friendly-Name: PolarisPostActionLoadPostQueryQuery`) روی چهار شورت‌کدِ واقعی: هر چهار `HTTP 403` با صفحهٔ `not-logged-in` و هر چهار **دقیقاً ۲۰۹۵۲ بایت**. **کنترلِ منفی بخشِ تصمیم‌کننده بود:** `DYiEBENOlT1` که از مسیرِ embed **موفق** دانلود می‌شود همان ۴۰۳ را گرفت — پس گیت خاصیتِ **اندپوینت برای درخواستِ ناشناس از این IP** است نه خاصیتِ آن چهار پست. بدونِ آن کنترل، چهار ۴۰۳ می‌توانست «آن پست‌ها خاص‌اند» خوانده شود و رده باز می‌ماند. **نسخهٔ کاملِ توکن‌کِشی هم صریحاً از میز برداشته شد**، چون همان درخواست را می‌سازد و به همان گیت می‌خورد؛ تفاوتش در به‌دست‌آوردنِ توکن است نه در پاسخِ اندپوینت به یک درخواستِ بی‌سشن. **(۲ ادعای خودم رد شد)** نوشته بودم «`is_video` بدونِ `video_url`» در تولید **تورِ ایمنیِ drift** است نه مسیرِ رایج، و اگر دیده شد یعنی اینستاگرام عوض شده. دادهٔ تولید ردش کرد: `Dbew2QJNYQx` یک `GraphVideo` با `is_video=True` و بدونِ `video_url` است در حالی که `display_url` و تگِ `EmbeddedMediaImage` **هر دو** در همان صفحه‌اند — یعنی بدترین شکل، پوستر دمِ دست بود و ماژول درست برنداشت و کلِ رده را به کوکی انداخت. پس حالتِ **عادیِ** اینستاگرام است نه خبرِ drift، و تفاوتِ عمدی با cobalt (`instagram.js:307-316`) دقیقاً برای همین ساخته شده بود. خطای استدلالیِ من هم قابلِ نام‌گذاری است: `Daq3IWJGIPG` (هر ۶ فرزندِ ویدیویی با `video_url`) فقط ثابت می‌کرد این حالت **همیشگی** نیست، و من از آن «نادر است» خواندم. **(۳ ردهٔ شکستِ تازه: «قالبِ خالی»)** `DajmNS3lMrK` و `Dbgyn2xyG_v` هر دو `contextJSON=null` **و** بدونِ `EmbeddedMediaImage`، با حجمِ **۲۰۹۸۵۸** و **۲۰۹۸۵۹** بایت — یک بایت اختلاف، یعنی یک قالبِ یکسانِ بی‌محتوا. اینستاگرام صفحه را ۲۰۰ می‌دهد و هیچ رسانه‌ای داخلش نمی‌گذارد؛ هر دو **بعدش با کوکی موفق دانلود شدند**، پس محتوا هست و فقط ناشناس سرو نمی‌شود. این `no_media`ِ **درست** است و رفع‌شدنی نیست. تفکیکش از ردهٔ (۲) لازم است چون آن یکی «داده هست، ما ردش کردیم» است و این یکی «داده نیست» — و اگر یکی خوانده شوند، تله‌متری بی‌معنا می‌شود. **(۴ عددِ برد، با قیدش)** ۱۵ آگوست `iganon:ok = 5` و **صفر** در هر چهار سطلِ دیگر — هر ۵ دانلودِ اینستاگرامِ آن روز بدونِ لمسِ هیچ اکانتی. ۱۴ آگوست (بعد از روشن‌کردنِ فلگ) ۵ `ok` و ۳ `unsupported` از ۸ لینک. جمعاً **۱۰ از ۱۳ ≈ ۷۷٪**؛ مبنای پیش از فلگ ۲۱ تا `instagram:ok` در ۱۴ آگوست، **همه با کوکی**. قید بخشی از عدد است نه پاورقیِ آن: نمونه کوچک است و آن سه شکست همه در یک نشستِ **تستِ دستی** افتادند نه در توزیعِ طبیعیِ ترافیک، در حالی که ۱۵ آگوست با ترافیکِ عادی‌تر ۵ از ۵ داد — پس ۷۷٪ کفِ محتاطانه است و ۱۰۰٪ سقفِ خوش‌بینانه، و نرخِ پایدار چند روز داده می‌خواهد. **(۵ ریسکِ اصلی رد شد)** نگرانیِ روشن‌کردن این بود که حجمِ درخواست به صفحهٔ embed اعتبارِ IPِ سرور را خراب کند و کلِ استخر را به دردسر بیندازد؛ ۱۵ آگوست `dlstat:instagram:fail = 0` به‌علاوهٔ صفر `blocked` و صفر `network` — نه محدودیتی خوردیم و نه دانلودی شکست خورد. دامنه‌اش هم نوشته شد تا بیش از آنچه هست خوانده نشود: این شاهد برای **حجمِ سنجیده‌شده** است، نه برای مقیاسی چند برابر؛ اگر ترافیک جهید، `blocked`/`network` اولین دو سطلی‌اند که تکان می‌خورند. **اعمال:** هیچ‌چیز — فقط `CLAUDE.md` و یک داکس‌استرینگ (که تا امروز می‌گفت رده «عمداً در فاز ۱ ساخته نشد»، یعنی همچنان نامزد).
- 2026-08-14 — **مسیرِ ناشناسِ اینستاگرام، فاز ۲: وصل شد، پشتِ فلگی که پیش‌فرض خاموش است.** ماژولِ فاز ۱ نیمهٔ **fetch** گرفت (`download_anonymous`) و `run_download` بینِ محاسبهٔ `anon` و حلقهٔ تلاش صدایش می‌زند. **نقطهٔ اتصال قبل از `_next_cookie` است و «قبل» معنیِ دقیقی دارد:** تا رسیدن به `download_gallerydl`، `pick` اکانت را از چرخه درآورده، `materialize` روی دیسکِ نود نوشته و `note_use` مهرِ فاصلهٔ حداقلی زده — هر سه بی‌بازگشت، حتی اگر آن کوکی هیچ‌وقت به موتور نرسد. پس ادعای این کار «کوکی استفاده نشد» نیست («انتخاب نشد» است) و تستِ اصلی با تریپ‌وایر روی `pick`/`materialize`/`note_use`/`mark_ok`/`mark_fail`/`note_spend` همان را می‌سنجد، روی استخری که عمداً **پر** است. **بایت‌ها را `download_direct` می‌کشد نه یک لوپِ دست‌نویس** — ارثِ `_direct_connector` (همان رزولورِ ضدِTOCTOU)، `_follow` (هر پرشِ ریدایرکت دوباره `is_safe_url`)، سقفِ دولایه با حذفِ فایلِ نیمه‌کاره، و قراردادِ progress/cancel؛ و مهم‌تر، آن تابع `opts["cookies"]` را **اصلاً نمی‌خواند** پس قاعدهٔ بنیادیِ ماژول رایگان حفظ می‌شود. لوپِ جدا یعنی چکِ per-hopِ `_follow` بازنویسی شود — همان واگراییِ `remove_cookie_file`. **`engine` عمداً `gallerydl` می‌ماند**، پس شاخه‌های تحویل (کاروسل → Rich/آلبوم، تک‌آیتم → کارت) و کش بدونِ یک خطِ تغییر کار می‌کنند؛ `dl_cache.cache_key` فقط `(url, selector)` را می‌بیند و موتور در آن نیست، پس روشن/خاموش‌کردنِ فلگ ردیف‌های کش را باطل نمی‌کند. **گیت روی شورت‌کد است نه پلتفرم:** `platform_of` برای استوری و پروفایل هم `instagram` می‌دهد ولی آن‌ها مسیرِ ناشناس ندارند، پس بدونِ هیچ درخواستِ شبکه‌ای مستقیم به کوکی می‌روند (سطلِ `skipped`). **`while not anon_won:` و نه `while paths is None:`** — `anon_won` داخلِ حلقه هرگز نوشته نمی‌شود پس از داخل بایت‌به‌بایت همان `while True:` است؛ فرمِ دیگر بی‌ضرر به‌نظر می‌رسد ولی یک رفتار را عوض می‌کند، چون `cookies.mark_ok` `get_meta`/`set_meta` را بدونِ `try` صدا می‌زند و یک خرابیِ Redis **بعد از** دانلودِ موفق با `paths`ِ ست‌شده به `except` می‌افتد. **تصمیمِ «هیچ شکستی پای اکانت نوشته نمی‌شود» ساختاری اثبات شد نه استدلالی:** `failures` فقط زیرِ `if cookie_name:` پر می‌شود و گامِ ناشناس هیچ `ck.*`ی را صدا نمی‌زند، پس `_resolve_blame` روی فهرستِ تهی برمی‌گردد — و تست با تریپ‌وایر و مقایسهٔ `fail_streak`/`last_error` قبل و بعد می‌سنجدش. **تله‌متری شش سطل دارد نه پنج (تصحیحِ اپراتور، و درست بود):** پنج سطلِ اولیه همه از `verdict` می‌آمدند، ولی fetch می‌تواند **بعد از** `verdict=ok` بیفتد (URLِ امضاشدهٔ منقضی، سقفِ تجمعی وسطِ کاروسل، قطعیِ شبکه) و نشستنِ آن حالت در سطلِ `ok` ادعای «تعدادِ دانلودی که کوکی لمس نکرده = عددِ ok» را دروغ می‌کرد — چون آن‌جا به مسیرِ کوکی افتاده‌ایم و کوکی سوخته. `fetch_failed` سطلِ خودش را دارد و از صورتِ آن نسبت بیرون است؛ retryش عمداً ساخته نشد و در Open Questions ثبت شد (اول باید معلوم شود کدام‌یک از چهار علت است — retry فقط برای انقضای URL معنا دارد). **کرانِ زمانی اضافه شد چون سنجیده شد که وجود ندارد:** `download_direct` با `ClientTimeout(total=None, …)` کار می‌کند، یعنی کاروسلِ ۱۱تایی فقط با `job_timeout`ِ ۵۴۰۰ ثانیه‌ای محدود بود؛ این پاس **گمانه‌زنی** است و باید سریع کنار برود، پس هر آیتم با `asyncio.wait_for` روی بودجهٔ **باقی‌مانده** اجرا می‌شود (`ANON_FETCH_BUDGET` = ۳۰۰ ثانیه). **جداسازیِ فایل شرطِ درستی است:** `<workdir>/igan/<NN>/` و `rmtree` در `finally` روی هر خروجی‌ای جز موفقیتِ کامل، وگرنه شکستِ ۶-از-۱۱ یک workdirِ آلوده تحویلِ مسیرِ کوکی می‌دهد. **دو تستِ خودم که همین‌جا خراب درآمدند و ارزشِ ثبت دارند.** (۱) تستِ جداسازی **توخالی** بود: بعد از `run_download` نگاه می‌کرد، در حالی که `finally`ِ خودِ آن تابع کلِ workdir را پاک می‌کند — پس «چیزی نمانده» بی‌قیدوشرط صادق بود و با خرابکاری هم سبز می‌ماند؛ حالا workdir را **در لحظهٔ فراخوانیِ `download_gallerydl`** می‌سنجد، که دقیقاً همان چیزی است که قید می‌گوید. (۲) تستِ سقفِ تجمعی ۱۱ آیتمِ ۴۰ کیلوبایتی را زیرِ سقفِ ۱ مگابایتی می‌گذاشت، پس پاسِ ناشناس **موفق** می‌شد و تست چیزی را که ادعا می‌کرد نمی‌سنجید. **و یک اشتباهِ هارنس که تست‌ها را قرمز کرد و آموزنده بود:** فیکسچرِ واقعی URLها را در `contextJSON` **دو بار** escape می‌کند (`https:\\\/\\\/…`)، پس `str.replace`ِ ساده فقط فرمِ `<img srcset>` را می‌گرفت و رسانه‌ها به CDNِ واقعی روی پورتِ ۴۴۳ می‌رفتند. **تست‌ها (۵۴۹ → ۵۶۹):** ۲۰ تست روی **سرورِ واقعیِ aiohttp** با **فیکسچرهای واقعیِ فاز ۱** (فقط هاستِ CDN چرخانده) و **DNSِ جعلی** — تنها چیزی که §۶ جعلش را مجاز می‌داند — تا `download_direct`ِ واقعی با کانکتور و `_follow`ِ خودش اجرا شود؛ ماک‌کردنش یعنی همان چیزی که تصمیمِ «الف» ادعا می‌کند نسنجیده بماند. لایهٔ تحویل ضبط می‌شود نه اجرا (اجرایش Postgres و ffprobe می‌خواهد، نویزی که هیچ ادعایی به آن بند نیست). **۹ سابوتاژِ تازه، یکی به‌ازای هر قیدِ سخت و هر تصمیم؛ کلِ دفترچه ۲۳/۲۳ سبز.** یک سابوتاژ عمداً ثبت **نشد** و دلیلش در تست نوشته شد: «`sorted()` به‌جای ترتیبِ ساخت» گرفتنی نیست، چون زیرشاخهٔ صفرپرشده باعث می‌شود مرتب‌سازی عیناً با ترتیبِ ساخت یکی دربیاید — یعنی طراحی **دو** تضمینِ مستقل دارد، نه یک شکافِ تست. **تستِ ایمنی (پیشنهادِ اپراتور) تنها ویژگیِ کاربر-محورِ ایمنیِ این تغییر را می‌سنجد:** رسانه‌ای که لایهٔ سوم رد می‌کند از مسیرِ ناشناس هم تحویل نمی‌شود — منطقاً بدیهی است (چک‌ها بعد از حلقه‌اند) ولی «منطقاً بدیهی» چیزی است که تست برای اثباتش هست، و سابوتاژش (`if pol.enabled and not anon_won`) می‌گیردش. **اعمال:** `telabzar update` روی مستر — هیچ نودی وصل نیست. **بدونِ مهاجرت و بدونِ تغییرِ رفتار**: با فلگِ خاموش مسیر بایت‌به‌بایت همان امروز است (تستِ کنترل). روشن‌کردن از پنل، بدونِ ری‌استارت.
- 2026-08-14 — **مسیرِ ناشناسِ اینستاگرام، فاز ۱: ماژول + ابزار + تست. به مسیرِ دانلود وصل نیست.** انگیزه: اینستاگرام امروز ۱۰۰٪ کوکی‌محور است (`engine_for` هر لینکش را به gallery-dl می‌دهد و extractorِ آن به `sessionid` بند است — در حالتِ ناشناس هر سه لینکِ آزمایشی `HTTP redirect to login page` دادند) و سشن‌ها چند بار در روز می‌میرند. `app/instagram_anon.py` یک مسیرِ **دوم** است که هیچ اکانتی خرج نمی‌کند؛ `tasks_download.py`/`download_gallerydl`/`_ANON_FIRST` **دست‌نخورده‌اند** و اتصال فاز ۲ است. **نردبون دو رده دارد، نه سه.** رده mobile API (`api/v1/media/<id>/info/`) عمداً ساخته نشد چون از IPِ ما `HTTP 403 login_required` می‌دهد (اندازه‌گیریِ زندهٔ اپراتور روی مستر)، و **ردهٔ GraphQL هم حذف شد** — تحلیلِ فیکسچرهای واقعی نشان داد هر سه نوعِ محتوا از خودِ HTMLِ embed درمی‌آیند، پس ساختنش کدِ نسنجیده بود. **رده B دو زیرشاخهٔ ترتیبی دارد** (نه موازی): اول `contextJSON.gql_data` و **فقط اگر تهی بود** `<img class="EmbeddedMediaImage" srcset>`؛ یک تریپ‌وایر به‌عنوان کنترلِ معکوس ثابت می‌کند روی ریل و کاروسل زیرشاخهٔ دوم **صفر** بار صدا می‌شود. **فیکسچرها ضبطِ واقعی‌اند نه ساختگی** (۸۳۶ KB، سه فایلِ `-p`، دست‌نخورده) و همان‌ها چهار تله را لو دادند که سه‌تایش در نقشهٔ اولیه نبود — همه در §۷ ثبت شد. **تلهٔ چهارم را خودِ فیکسچر نشان داد و در نقشه نبود:** `srcset` داخلِ HTML است پس `&` در آن `&amp;` نوشته شده و بدونِ `html.unescape` پارامترهای امضا خراب به CDN می‌رفتند، در حالی که مسیرِ `gql_data` (که از `json.loads` آمده) اصلاً entity ندارد و نباید unescape شود. **یک تفاوتِ عمدی با cobalt:** فرزندی که `is_video` را ادعا کند ولی `video_url` نداشته باشد، آن‌جا بی‌صدا با `display_url` — یعنی **فریمِ پوستر** — جواب داده می‌شود (`instagram.js:307-316`)؛ این‌جا کلِ رده با `no_media` می‌افتد و کار به کوکی می‌رود، چون «فایلِ غلط» از «فایل نداریم» بدتر است، و `detail` علتِ **مشخص** را می‌برد (کدام فرزند) نه یک `no_media`ِ ژنریک تا تله‌متریِ فاز ۲ بتواند drift را جدا کند. **تفکیکِ «شکست» از «خطای شبکه»** با `verdict` (`ok`/`unsupported`/`blocked`/`network`) انجام می‌شود و معنیِ عملیاتی دارد: یک ۵xx یا قطعیِ شبکه نباید در فاز ۲ به `mark_fail` روی اکانتِ **سالم** تبدیل شود — همان درسِ `_resolve_blame`. سشن و سیاستِ SSRF از `downloader._direct_connector` می‌آید نه کپیِ تازه. **دو چیزی که سرِ کار درآمد و از خودِ رفع مهم‌تر است.** (۱) **تستِ خودم غلط بود نه کد:** انتظار داشتم صفحهٔ بی‌مغز `no_media` بدهد، ولی چون بلاکِ `init` ندارد علتِ دقیق‌ترِ `parse_failed` می‌گیرد؛ حالا هر دو حالت **جدا** تست می‌شوند، که خودش تفکیکی است که فاز ۲ لازم دارد. (۲) **یک سابوتاژ ادعای خودش را رد کرد:** خراب‌کردنِ چکِ `if cj` هیچ تستی را نینداخت، چون آن خط و `isinstance(cj, str)` **دو دفاعِ مستقل**اند و هرکدام به‌تنهایی جلوی `json.loads(None)` را می‌گیرد — یعنی سابوتاژِ تک‌گارده ذاتاً گرفتنی نیست و «نگرفت»ش شبیهِ تستِ ضعیف به‌نظر می‌رسد بی‌آنکه باشد. ورودی به شکلِ **پیاده‌سازیِ ساده‌لوحانهٔ واقعی** (هر دو گارد با هم) بازنویسی شد و افتاد؛ توضیحش هم در سورس ماند. **تست‌ها (۵۱۱ → ۵۴۷):** ۳۶ تست — هشت‌تا روی فیکسچرِ واقعی، شش‌تا با ورودیِ **دست‌سازِ خصمانه** (شاخهٔ فرزندِ ویدیویی، آیکون، `xdt_shortcode_media`، صفحهٔ خراب) که عمداً دست‌ساز است چون فیکسچرِ واقعی این حالت‌ها را ندارد و تست رویش توخالی می‌شد، و ده‌تای دیگر روی **سرورِ `aiohttp.web` واقعی** روی لوپ‌بک (نه ماک، طبقِ درسِ `FakeBot` در §۶) برای verdictها، تکـهشدارِ گذار، سکوتِ مسیرِ سالم، و «هیچ کوکی‌ای نمی‌رود» که `opts` را **با** کوکی می‌دهد و هدرها را روی سرورِ واقعی می‌سنجد. **۵ سابوتاژِ تازه** در `tests/sabotage.CASES` (کلِ دفترچه ۱۴/۱۴ سبز). `tools/ig_anon_probe.py` روی هر آیتم یک range-GET می‌زند، چون «پارس شد» با «دانلود می‌شود» یکی نیست. **اعتبارسنجیِ زنده روی مستر، هر چهار شکل `verdict=ok` و `via=embed`، و هر ۱۹ آیتم با `HTTP 206` و Content-Typeِ رسانه‌ای و حجمِ واقعی:** ریل (۱ ویدیو، ۱٫۴MB) · کاروسلِ ۱۱عکسی (۷۸۰KB تا ۳٫۵MB) · تک‌عکسی از مسیرِ img با همان کاندیدِ ۳۰۷۲w (۱٫۲MB — تلهٔ `&amp;` زنده تأیید شد) · و یک کاروسلِ **ترکیبی** با **۶ فرزندِ ویدیویی** که همه `video/mp4` دادند. آن آخری تنها اندازه‌گیریِ بازِ فاز ۱ بود و **بسته شد**: فرزندِ ویدیویی از IPِ ما `video_url` می‌دهد، پس تصمیمِ «بدونِ `video_url` کلِ رده بیفتد» تورِ ایمنیِ drift است نه مسیرِ رایج (به §۷ منتقل شد). **کپشنِ تک‌عکسی** تنها سؤالِ بازِ باقی‌مانده است. **تصحیحِ ادعای «اعمال: هیچ‌چیز» — ناقص بود.** برای **ماژول** درست است (کسی import نمی‌کندش)، ولی برای **ابزار** نه: `tools/ig_anon_probe.py` به `app.instagram_anon` وابسته است و آن ماژول در ایمیجِ build‌شده نیست، پس الگوی جاافتادهٔ stdin با `ImportError` می‌افتد و یک گامِ تزریقِ صریح لازم دارد (در §۷ و در داکس‌استرینگِ خودِ ابزار نوشته شد؛ خودکفا‌کردنِ ابزار عمداً رد شد چون آن‌وقت یک کپیِ منطق را می‌سنجید نه تولید را). **و یک بی‌دقتیِ گزارشیِ خودِ ابزار که همان اجرا لو داد:** `await content.read(n)` «تا سقفِ n» می‌دهد نه «دقیقاً n»، پس روی پاسخِ چندتکه‌ای `got=1B` چاپ می‌شد در حالی که status/Content-Type/total درست بودند — تشخیصی که می‌تواند گمراه کند، همان ردهٔ رتبهٔ کاذبِ `spotify_query_probe`. با `_read_capped` (انباشت تا سقف) رفع شد؛ سقف عمداً ماند چون `read(-1)` روی سروری که Range را نادیده بگیرد کلِ ویدیو را می‌کشد. **و نسخهٔ اولِ تستش کنترلش را رد کرد:** روی لوپ‌بک کلِ بدنه پیش از اولین `read` در بافر می‌نشیند، پس هارنس اصلاً مکانیزم را مدل نمی‌کرد و یک `read` هم همه‌اش را می‌گرفت؛ حالا سرور بعد از تکهٔ اول روی یک `Event` می‌ایستد و درهم‌آمیزی **مجبور** می‌شود — قاعدهٔ §۶، نه انتظار برای رقابت. **تست‌ها ۵۴۷ → ۵۴۹.** **اعمال:** برای ماژول هیچ‌چیز؛ برای اجرای ابزار پیش از merge، همان یک خطِ تزریق.
- 2026-08-14 — **هشدارِ «کوکیِ سالم نمانده» برای سطلی که هرگز پر نشده، و اینکه چرا گاردِ بدیهی همان زنگ را خفه می‌کند.** علامتی که گزارش شد: لینکِ اپل روی کدِ قدیم «other» می‌شد و شکست می‌خورد، و ادمین DMِ قرمزِ «هیچ کوکیِ سالمی برای عمومی/سایر نمانده» می‌گرفت. **اول ادعای «استخر سوخت» با اجرا رد شد** — `run_download`ِ واقعی + yt-dlpِ جعلی + استخرِ خالی، در **هر دو** حالتِ `dl_cookie_when_needed`: صفر فراخوانیِ `mark_fail`/`mark_ok`/`note_spend`/`cool_exit`، دقیقاً **یک** DM، و پیامِ درستِ `dl_failed` برای کاربر. دلیلش ساختاری است نه اتفاقی: `failures.append` زیرِ `if cookie_name:` است و با استخرِ خالی `cookie_name` همیشه `None` است، پس `_resolve_blame` روی `failures`ِ تهی همان اول برمی‌گردد. یعنی استخر نمی‌سوخت و تنها اثرِ آن شکست همان DM بود. **و شمارش نشان داد این یک موردِ خاص نیست:** `_cookie_platform` می‌تواند **۱۴** سطل بخواهد ولی `COOKIE_PLATFORMS` فقط **۶** تا می‌سازد (و `guess_platform` هم همان ۶ را می‌دهد — باگ نیست، مو‌به‌مو یکی‌اند)، پس هشت پلتفرمِ **پشتیبانی‌شده** (ساندکلاود، آپارات، ویمئو، توییچ، دیلی‌موشن، بندکمپ، ردیت، استریمبل) سطلی می‌خواهند که از هیچ راهی پر نمی‌شود. هر ۱۴ سطلِ خالی شلیک می‌کردند؛ کنترلِ منفی (یوتیوب با یک اکانتِ سالم) ساکت بود، پس هارنس ساکت‌شدنی است و آن اعداد سیگنالِ واقعی بودند. **رفع:** `cookies.pool_counts()` هر دو عدد را با **یک** پیمایش می‌دهد و `_alert_if_low` روی `total` گارد می‌گیرد نه روی `left`. **این تفکیک تمامِ کار است، و نیمهٔ خطرناکش گاردِ بدیهی است:** `if not left: return` هشدارِ استخرِ **واقعاً سوخته** («۰ قابلِ‌استفاده از ۳») را هم خفه می‌کند، یعنی دقیقاً همان چیزی که این تابع برایش وجود دارد. پس `test_a_burned_pool_still_screams` از تستِ خودِ رفع مهم‌تر است — و سابوتاژ تأییدش کرد: برداشتنِ کلِ گارد ۱۰ تست را می‌اندازد و **آن سه کنترل را سبز می‌گذارد**، در حالی که نوشتنِ گارد روی `healthy_count` دقیقاً **همان یک** تست را می‌اندازد. **و سؤالی که اپراتور پرسید از خودِ رفع مهم‌تر بود و چارچوبِ گزینهٔ بعدی را عوض کرد:** آن هشت پلتفرمِ non-anon با سطلِ صفر، اصلاً تلاش می‌کنند یا زودتر برمی‌گردند؟ اندازه‌گیریِ قبلی جوابش را نمی‌داد چون موتورِ جعلی شکست می‌خورد؛ با موتورِ **موفق** جواب قطعی شد: yt-dlp **صدا زده می‌شود**، **بدونِ `--cookies`**، فایل تولید می‌شود و جریان تا «📤 در حالِ ارسال به تو…» می‌رود (فقط روی Postgresِ غایبِ سندباکس می‌ایستد). پس آن هشت‌تا **شکسته نبودند**، فقط نویز می‌ساختند. **و مقایسهٔ چهارحالته نشان داد گزینهٔ «آن‌ها را `_ANON_FIRST` کن» روی سطلِ خالی هیچ رفتاری عوض نمی‌کند:** فراخوانیِ موتور، نبودِ کوکی، ضربه‌ها، DMها و پیامِ کاربر در هر چهار حالت یکسان‌اند و تنها تفاوتِ سنجیده‌شده یک خطِ `log.error("cookieless attempt on …")` است. یعنی نه `_ANON_FIRST` و نه گسترشِ `COOKIE_PLATFORMS` جایگزینِ این گارد نبودند. **دو نکتهٔ ریز که سرِ راه سنجیده شد:** `mark_ok`/`note_spend` روی نامِ `None` هر دو `if not name: return` دارند، پس فراخوانی‌شان در مسیرِ بی‌کوکی no-opِ بی‌ضرر است — تریپ‌وایرِ من فراخوانی را می‌شمرد نه اثر را، و این تفاوت باید گفته شود؛ و `_warn_cookieless` خطِ `log.error` را **پیش از** گاردِ `if not usable` می‌زند، پس هر دانلودِ آپارات/ویمئو/… امروز یک ERROR در لاگ می‌گذارد که سرنخِ قابلِ‌جست‌وجویی روی مستر است. **و اپراتور یک ته‌ماندهٔ همان رده را گرفت که من «فقط یک چیز» خوانده بودمش:** `_warn_cookieless` آن `log.error` را **قبل از** گاردِ خروجش می‌زند، پس بعد از رفعِ DM هنوز هر دانلود از آن هشت پلتفرم یک ERRORِ دائمی برای مسیری می‌گذاشت که سالم است — DM ساکت می‌شد، لاگ نه، و خطای واقعی لای آن گم می‌شود. همان تفکیکِ `total == 0` یک خط بالاتر هم اعمال شد: سطلِ بی‌اکانت `info` می‌گیرد، سطلِ **سوخته** (اکانت دارد، هیچ‌کدام قابلِ‌استفاده نیست) همچنان `error`. سابوتاژ روی این هم دوطرفه است و هرکدام **دقیقاً یک** تست را می‌اندازد: فرمِ قبلی (ERROR قبل از گارد) `test_an_unstocked_bucket_does_not_log_an_error` را، و گاردِ نوشته‌شده روی `usable` `test_a_burned_pool_still_logs_an_error` را. **و اپراتور نقطهٔ کورِ خودِ رفع را هم گرفت — که از هر دو تای قبلی مهم‌تر بود:** «هرگز پر نشده» و «پر بوده و خالی شده» هر دو `total == 0` می‌خوانند، پس گاردِ دوحالتی نویزِ نُه سطل را می‌بندد و هم‌زمان سیگنالِ واقعیِ اینستاگرام را خاموش می‌کند: بینِ پاک‌کردنِ سشن‌های مرده و چسباندنِ تازه‌ها، دانلود کار نمی‌کند و **هیچ هشداری نمی‌آید**، جایی که کدِ قبلی داد می‌زد. `ckseen:<platform>` ردِ ماندگار است — `set_meta` می‌نویسدش و `del_meta` **عمداً** پاک نمی‌کند — و شرط سه‌حالتی شد. **دو تصمیمِ طراحی که با اجرا گرفته شد نه با سلیقه:** سیگنالِ **مشتق** بررسی و رد شد، چون `ckrot:<platform>` فقط وقتی `incr` می‌شود که **دو یا چند** نامزدِ هم‌رتبه باشند، یعنی سطلی که همیشه یک اکانت داشت هرگز آن را بالا نمی‌برد؛ و رد در `set_meta` نوشته می‌شود نه در `_save_cookie`/مسیرِ پنل، چون نامِ فایل قابلِ‌اتکا نیست (اکانتِ «other» با برچسبِ `youtube-backup` سطلِ **یوتیوب** را علامت می‌زد) و `admin_web` هم در محیطِ تست قابلِ import نیست. **و کمکیِ تستِ خودم اولش غلط بود:** حذف سه گام است (فایل + `_unmirror_cookie` + `del_meta`) و من دو تا نوشتم، پس `list_names` از آینهٔ Redis اکانت‌های «حذف‌شده» را می‌دید و تست شکست — بررسی شد که هر دو مسیرِ حذفِ تولید هر سه گام را دارند، پس **باگ نیست**. **و یک سابوتاژ که ادعای خودش را رد کرد:** نسخهٔ اولِ «del_meta ردِ ماندگار را پاک کند» اصلاً اعمال نشد (رشتهٔ هدف عوض شده بود) و «۲۰ passed» بی‌معنا بود — همان درسِ ۲۰۲۶-۰۸-۱۰، سابوتاژ هم باید اعمال‌شدنش را assert کند؛ با اعمالِ درست ۳ تست افتاد. **حفرهٔ راه‌اندازیِ سرد که اپراتور گرفت:** رد را `set_meta` می‌نویسد، ولی اکانت‌های موجود پیش از این کد ساخته شده‌اند و ردی ندارند. نویسنده‌های `set_meta` با AST شمرده شدند — `mark_ok`/`mark_fail` (هر تلاشِ دانلود)، `unfreeze` و سه مسیرِ پنل/ربات — پس پنجره از استقرار تا **اولین دانلودِ** آن پلتفرم باز است، و ادمین دقیقاً در همان پنجره سشن‌های مرده را پاک می‌کند. «احتمالاً به‌زودی» جواب نبود: `cookies.backfill_seen()` سرِ استارتِ هر ورکر یک پیمایش می‌کند و هر سطلِ پر را علامت می‌زند. تستِ کنترل، **خودِ حفره** را ثبت می‌کند (بدونِ backfill سکوت رخ می‌دهد) وگرنه تستِ رفع چیزی اثبات نمی‌کند؛ و چون «هلپر هست ولی کسی صدایش نمی‌زند» رگرسیونِ محتمل‌تر است، یک گاردِ ASTی روی `worker.startup` هم هست. **سه ته‌ماندهٔ پیش‌از‌مرج، به‌پیشنهادِ اپراتور:** (۱) نبودِ TTLِ رد با یک تست پین شد — `TTL` روی کلیدِ بی‌انقضا `-1` و روی کلیدِ نبوده `-2` می‌دهد، پس یک assert هم انقضای صریح را می‌گیرد هم انقضای به‌ارث‌رسیده؛ (۲) درسِ «سابوتاژ باید اعمال‌شدنش را assert کند» از انضباط به ساختار رفت (`tests/sabotage.py` + تستِ خودش)، چون دو بار فراموش شده بود؛ (۳) دو مسیرِ حذف در `cookies.delete_account()` یکی شدند با گاردِ ASTی که ترکیبِ ≥۲ گام را می‌گیرد. **و همان یکی‌سازی یک تستِ قدیمی را انداخت که درست بود:** `test_both_delete_paths_share_one_implementation` دنبالِ `remove_cookie_file` می‌گشت، یعنی نامِ نقطهٔ اشتراکِ **قبلی** — ادعایش عوض نشد، فقط به‌روز شد. **و ابهامی که گزارشِ خودم لو داد، با اجرا بسته شد:** ادعا کرده بودم خطِ فرمانِ `trim_video` و `trim_audio` «یکسان» شده — نادقیق بود و تصحیح شد؛ فقط **قطعهٔ سیک** دو بار در فایل است و `trim_audio` جلوتر است. هیچ ادعای زنده‌ای رویش بنا نشده: اثباتِ ۲-۳ یک تستِ **ساختاری** است که با `inspect.getsource(P.trim_video)` سورسِ همان تابع را می‌خواند، و با سابوتاژِ جدا روی هر دو تابع اجرا شد — خراب‌کردنِ `trim_video` می‌اندازدش و خراب‌کردنِ `trim_audio` نه. هر دو در دفترچه ثبت شدند، دومی به‌عنوان کنترلِ معکوس. **دفترچهٔ سابوتاژ (پیشنهادِ اپراتور، ساخته شد):** ۹ مورد به‌صورتِ داده در `tests/sabotage.CASES` + `python -m tests.sabotage`؛ هر ۹ تا همان‌طور که ثبت شده رفتار کردند. **تست‌ها (۴۹۵ → ۵۲۴):** ۲۵ تستِ هشدار/backfill + ۳ تستِ ابزارِ سابوتاژ + ۱ گاردِ حذف، از جمله انتها‌به‌انتها از همان مسیری که علامت گزارش شد. **درسِ §۶:** سه سبزِ محلیِ گمراه‌کننده در یک روز (`:memory:` که هم‌زمانی را مدل نمی‌کرد، `7z` که فرضش غلط بود، `cryptography` که سندباکس تصادفاً داشت) یک رده‌اند — سندباکس و رانر دو ماشین‌اند و هیچ‌چیز دلتا را گزارش نمی‌کند؛ نوشته شد، به‌همراه شکافِ **importِ گذرا** در Open Questions (گاردِ AST فقط importِ مستقیم را می‌بیند). **اعمال:** `cookies.py`/`tasks_download.py` روی نودِ دانلود هم می‌دوند → `telabzar update` روی مستر (و `node/update.sh` اگر روزی نودی برگشت). بدونِ مهاجرت و بدونِ تغییرِ رفتار برای سطل‌های پر.
- 2026-08-13 — **CIِ #۱۰۸ قرمز شد و علتش هیچ‌کدام از دو حدسِ ما نبود — تستی بود که خودم در همین PR نوشتم.** لاگِ خامِ ران: `1 failed, 493 passed` و تنها شکست `test_every_panel_row_is_a_real_runtime_key` با `ModuleNotFoundError: No module named 'cryptography'` از `app/admin_web.py:28`. حدسِ اپراتور (مسیرِ ورکری و تست‌های ffmpeg/7z) غلط بود و حدسِ ضمنیِ من هم؛ **لاگ جواب داد، نه استدلال**. فلیک نبود: خطای ماژولِ غایب قطعی است و محلی هم با مسدودکردنِ `cryptography` در `meta_path` عیناً بازتولید شد. (`rerun_failed_jobs` با ۴۰۳ رد شد — این integration اجازه‌اش را ندارد، پس تکرارِ ران روی GitHub انجام نشد و اثبات از بازتولیدِ محلی آمد.) **چرا محلی سبز بود:** `requirements-dev.txt` عمداً استکِ پنل را ندارد (`jinja2`/`cryptography` در `requirements-admin.txt`اند)، پس `app/admin_web.py` در محیطِ تست **قابلِ import نیست** — ولی سندباکسِ من `cryptography` نصب داشت، چون **اولِ همین سشن خودم نصبش کردم** تا `cryptography`ِ شکستهٔ دبیان را دور بزنم. یعنی سندباکس دقیقاً به‌خاطرِ رفعِ یک مشکلِ محیطی از رانر واگرا شد و هیچ‌چیز هشدار نداد. **رفع:** `GROUPS` با AST از سورس خوانده می‌شود، بدونِ import — همان قاعده‌ای که از قبل در `tests/test_phase2a._func_src` مستند بود و داکس‌استرینگش صریحاً می‌گفت این ماژول روی رانر نصب نیست. `GROUPS` لیترالِ خالص است پس `literal_eval` کافی است. **و بستنِ خودِ ردهٔ کور:** `test_no_test_imports_a_module_the_ci_runner_does_not_have` در `test_repo_hygiene` با **کشفِ AST** روی کلِ `tests/` هر importی از `app.admin_web`/`cryptography`/`jinja2` را می‌گیرد و فایل:خط را نام می‌برد؛ سابوتاژ تأیید کرد (`test_settings_rename.py:155 → app.admin_web`). به‌علاوه کلِ سوییت یک‌بار با `cryptography`ِ **غایب‌شده** اجرا شد (sitecustomize روی PYTHONPATH) و سبز ماند — نزدیک‌ترین تقریبِ محلیِ رانر. **درسِ عام در §۶ ثبت شد:** سندباکسِ توسعه همان لحظه‌ای که چیزی نصب می‌کنی تا گیر باز شود از رانر واگرا می‌شود، و گارد باید **تست** باشد نه عادت — همان شکلِ مارکرِ `7z` و هارنسِ `:memory:`: **سبزیِ محلی شاهدی دربارهٔ محیطِ محلی است، نه دربارهٔ کد.** **تست‌ها (۴۹۴ → ۴۹۵).** فینگرپرینت دست‌نخورده. **اعمال:** بدونِ تغییر — فقط تست.
- 2026-08-13 — **فیکسچرهای واقعیِ اپل جای ردیف‌های دست‌ساز را گرفتند، و همان‌طور که امید می‌رفت یک تستِ سبز را انداختند.** هفت دامپِ واقعیِ `itunes.apple.com/lookup` از مستر در `tests/fixtures/apple_lookup.json` نشستند، دست‌نخورده، هرکدام با `_note`ِ خودش (مبدأ، چه چیزی را اثبات می‌کند و چه چیزی را **نه**)؛ هشدارِ «از فیلدهای گزارش‌شده ساخته شده» از بالای فایلِ تست برداشته شد چون دیگر صادق نیست. **و بلافاصله یک حدسِ من افتاد:** مدتِ واقعیِ «Faryaad» **۴۲۰۰۴۹ms** است نه ۳۱۱۰۰۰ — عددی که خودم از ترکِ دیگری برداشته بودم. با مرجعِ ۴۲۰ ثانیه‌ای، نامزدهای ۳۱۱ثانیه‌ایِ تست‌های رتبه‌بندی از `_duration_reject` رد می‌شوند (اختلاف ۱۰۹ ثانیه، ۲۶٪)، پس آن تست‌ها روی دادهٔ واقعی قرمز شدند. حالا مدت **از خودِ دامپ خوانده می‌شود** نه هاردکد، و وارونگیِ رتبه با عددِ واقعی عیناً بازتولید می‌شود (غلط ۹۶٫۹ در برابرِ درست ۹۶٫۰؛ با استخراج، درست ۱۰۶٫۰ و غلط رد). سالِ F2 هم ۱۹۷۰ است نه ۱۹۹۶. **چهار چیز که F7 و F8 لو دادند** (هر دو از `lookup` گرفته شدند چون عنوان‌هایشان قبلاً رشتهٔ دست‌نویس بودند): در F7 `collectionName` **عیناً برابرِ** `trackName` است و فقط بعد از پاک‌سازیِ عنوان واگرا می‌شوند — پس اشتباه‌گرفتنِ یکی به‌جای دیگری تا آن لحظه نامرئی است (آلبوم عمداً پاک نمی‌شود: نامِ محصول است نه عنوانِ ترک)؛ F7 `artistName` تک‌نامی دارد و هر دو مهمان در عنوان‌اند، که استخراج درست درشان می‌آورد؛ در F8 `collectionExplicitness` **explicit** ولی `trackExplicitness` **notExplicit** است — **باگ نیست چون resolver هیچ‌کدام را نمی‌خواند** (گیتِ محتوا روی خودِ دانلودِ یوتیوب است) و تست هم واگرایی را پین می‌کند هم نبودِ کلید در خروجی؛ و F8 آشکارسازِ گلچین را با خودش آورد (`collectionArtistName = "Various Artists"` به‌علاوهٔ `collectionArtistId` که هیچ ردیفِ دیگری ندارد) که به یادداشتِ جریمهٔ کاذبِ آلبوم در Open Questions اضافه شد — **ثبت شد، ساخته نشد**. **خانوادهٔ سه‌تاییِ نسخه** رایگان درآمد: ۳۷۰/۶۳۳/۲۴۸ ثانیه روی یک عنوان، با سه شکلِ متفاوتِ artistName/collectionName؛ نام جدایشان نمی‌کند و گیتِ مدت هر جفت را رد می‌کند. **و سابوتاژ یک تستِ vacuous پیدا کرد که فیکسچر پیدایش نکرد:** گاردِ `wrapperType`/`kind` از هیچ تستی رد نمی‌شد، چون تستِ لینکِ آلبوم پیش از lookup و روی **شکلِ URL** رد می‌شود؛ برداشتنِ کاملِ گارد ۵۳ تست را سبز می‌گذاشت. تستِ `/song/<albumid>` اضافه شد و حالا هر ۱۱ سابوتاژ دقیقاً تستِ خودش را می‌اندازد. **تست‌ها (۴۸۴ → ۴۹۴).** فینگرپرینت **دست‌نخورده** (`7d38598886db25f5`) پس `_MATCH_VERSION` تکان نخورد. **اعمال:** بدونِ تغییر — master-only، بدونِ `DELETE`.
- 2026-08-13 — **سه سؤالِ پیش‌از‌مرج، و اندازه‌گیری دو بار ادعای خودم را رد کرد.** **(۱ شمارِ retry)** سؤال درست بود و جوابش از آنچه فکر می‌کردم بدتر: تکرارِ **همان** عملیاتِ racy ذاتاً احتمالی است. حالا روی تعارض یک `UPDATE`ِ مستقیم می‌رود — تعارض خودش ثابت می‌کند ردیف هست و `UPDATE` روی کلیدِ یکتا نمی‌تواند تعارض بدهد، پس تلاشِ دوم **قطعی** است. فقط `IntegrityError` گرفته می‌شود و مسیرِ دوم چیزی نمی‌گیرد. **ولی دو ادعای خودم غلط بود و هر دو با اجرا افتاد:** اولی اینکه «۲ کافی است ولی ۴ می‌شکند» — آن روی `sqlite+aiosqlite:///:memory:` سنجیده شده بود که **اصلاً رقابت مدل نمی‌کند** (SQLAlchemy یک اتصالِ مشترک نگه می‌دارد و session‌های هم‌زمان روی همان تراکنش multiplex می‌شوند)؛ روی DBِ فایل‌محور نتیجه کاملاً فرق کرد. دومی اینکه در داکس‌استرینگ نوشتم «۳ تلاش تا ۸ پروسه سالم می‌ماند» — بی‌آنکه سنجیده باشم، و سنجش ردش کرد. عددِ صادق، ۲۰ اجرا به‌ازای هر حالت روی فایل: **بی‌محافظت ۱/۲۰ در n=2 و ۰/۲۰ در n=8**، و «یک retry» و «UPDATEِ مستقیم» هر دو ۲۰/۲۰. پس خودِ **باگ** اثبات‌شده است ولی تفاوتِ دو رفع در این مقیاس سنجیده‌نشدنی؛ انتخابِ `UPDATE` بر پایهٔ ساختار است نه عدد، و داکس‌استرینگ دقیقاً همین را می‌گوید. فیکسچرِ تست هم به DBِ فایل‌محور منتقل شد و تستِ هم‌زمانی روی ۲/۴/۸/۱۶ نویسنده پارامتری شد. **و یک رگرسیونِ خودم که همان تست گرفت:** موقعِ بازنویسیِ `set()` نوشتنِ کشِ Redis از انتهای تابع افتاد؛ تستِ clobber بلافاصله قرمز شد و سابوتاژ تأیید کرد که واقعاً می‌گیردش. **(۲ ممیزیِ الگو، و برچسبِ یک‌کاسهٔ خودم غلط بود)** بارِ اول هر سه نقطهٔ نوشتنِ `textstore` را زیرِ یک «IntegrityError» گذاشتم — روی همان هارنسِ `:memory:`. اپراتور پرسید چرا `set_menu_layout` که کلِ kind را قبل از درج حذف می‌کند شدتِ یکسانی داشته باشد، و اندازه‌گیریِ به‌تفکیک (۲۰ اجرا، ۴ نویسنده، DBِ فایل‌محور) نشان داد **ندارد**: `set_text` ۱۸/۲۰ و `set_button_styles` ۱۹/۲۰ خطا دادند، ولی `set_menu_layout` **۰/۲۰** — و هر بار یک چیدمانِ **کامل** از یک نویسنده، نه ترکیبی و نه نیمه‌کاره، چون delete+insertش داخلِ **یک تراکنش** است یعنی اتمی و last-writer-wins، که دقیقاً همان معنیِ «کلِ چیدمان را جایگزین کن» است. و آن ۰/۲۰ فقط به این دلیل معنا دارد که همان هارنس روی دو خواهرش ۱۸ و ۱۹ داد — همان کنترلِ منفی. `settings_store.reset` هم سالم است. پیش‌موجود و بی‌ربط به اپل → **ثبت شد، بسته نشد**. **(۳ پیامِ فینگرپرینت)** روالی که خودم اجرا کردم داخلِ پیام نوشته شد — «کیس‌های تازه را بردار، هش را دوباره بگیر، با پینِ **قبلی** مقایسه کن» — با تأکیدِ صریح بر اینکه «کیس اضافه کردم» به‌تنهایی هیچ چیزی ثابت نمی‌کند، چون یک کامیت می‌تواند هم کیس اضافه کند هم رفتار را عوض کند و هش به دو دلیلِ از-بیرون-یکسان تکان بخورد. **(۴ کنترلِ منفی، قاعدهٔ تازه در §۶)** درسِ زیرینِ هر دو تصحیح یکی بود و به §۶ رفت: هر اندازه‌گیریِ هم‌زمانی/زمان‌بندی قبل از اینکه عددِ سبزش معنا داشته باشد به **کنترلِ منفی** نیاز دارد — یعنی نشان‌دادنِ اینکه نسخهٔ بی‌محافظت روی **همان** هارنس واقعاً می‌افتد. **سابوتاژ این رده را نمی‌گیرد**، چون وقتی نقص در هارنس است سابوتاژ فقط می‌گوید «نگرفت» و شبیهِ ادعای ضعیف به‌نظر می‌رسد نه بنچِ مرده. و علتِ ریشه‌ای عام است: بکندی که مکانیزمِ موردِ سنجش را مدل نمی‌کند **هم** false pass می‌دهد **هم** false fail — این‌جا هر دو را داد. **تست‌ها (۴۸۱ → ۴۸۴).** **اعمال:** بدونِ تغییر — master-only، بدونِ `DELETE`.
- 2026-08-13 — **دو سؤالِ پیش‌از‌مرج، و هر دو یک باگِ واقعی بیرون داد.** **(۱ فینگرپرینت)** سؤال درست بود: «سبز ماند» فقط وقتی معنا دارد که استخراجِ feat در کدِ **مشترک** نباشد یا فیکسچر ورودیِ feat‌دار داشته باشد. با **اجرا** جواب داده شد نه grep: یک tripwire روی `_split_feat_title` و بعد اجرای پارسر روی هر دو دامپِ واقعی + کلِ زنجیرهٔ ماچر با عنوانی که feat دارد → **صفر فراخوانی** از مسیرِ اسپاتیفای (تنها محلِ فراخوانی `apple_resolve` است). و مستقلاً، فینگرپرینت روی `app/`ِ **پیش از** کارِ اپل و روی برنچ محاسبه شد: هر دو `943a6186749d76ab` — پس سبزی معنادار است. **ولی نکتهٔ زیرینِ سؤال درست بود:** فیکسچر هیچ عنوانِ feat‌داری نداشت، یعنی اگر روزی استخراج به کدِ مشترک منتقل شود این تست ساکت می‌ماند. کیسِ `feat_in_title` اضافه شد (مرجعِ feat‌دار + نامزدِ feat‌دار + براکتِ نشانه کنارِ براکتِ feat) و با سابوتاژ تأیید شد که انتقالِ استخراج به `_track_artists` را **می‌گیرد**. عدد شد `7d38598886db25f5`، و **`_MATCH_VERSION` بالا نرفت** چون با برداشتنِ موقتِ کیسِ تازه عدد دقیقاً به پینِ قبلی برمی‌گردد — یعنی رشدِ پوشش است نه تغییرِ رفتار. همین تفکیک به **پیامِ شکستِ خودِ تست** هم اضافه شد، چون فرمِ قبلی بی‌قیدوشرط می‌گفت «نسخه را ببر بالا» و آن برای رشدِ فیکسچر توصیهٔ غلط است (ردیف‌های سالمِ کش را برای مشکلی که ندارند دور می‌ریزد). **(۲ رقابتِ مهاجرت)** سؤالِ «کِی خاموش می‌شود» به باگی رسید که خودم ندیده بودم. مهاجرت کلیدِ تازه را **می‌نویسد** و قدیمی را پاک می‌کند، پس هشدار یک‌بار می‌آید و تمام — ولی وقتی پرسیده شد «اگر bot و download-worker هم‌زمان بزنند چه؟» و **اجرا شد**، جواب «بی‌صدا خراب می‌شود» نبود: **می‌ترکید**. `set()` یک check-then-actِ کلاسیک بود (اول SELECT بعد INSERT) و دو پروسه هر دو `row is None` می‌دیدند → `UNIQUE constraint failed: settings.key`. تا امروز بی‌خطر بود چون تنها نویسنده پنل بود؛ مهاجرت آن را به مسیرِ **هر** پروسه سرِ اولین خواندن برد، و `get()` در مسیرِ داغِ `_dl_opts` است یعنی شکستِ دانلود. `set()` حالا یک‌بار retry می‌کند. **و رقابتِ دومِ ظریف‌تر:** شاخهٔ «چیزی برای مهاجرت نبود» negative-cache می‌نوشت، پس پروسه‌ای که دیر می‌رسید می‌توانست `_MISSING` را روی مقدارِ تازه‌مهاجرت‌کرده بنویسد و — چون کلیدِ منفی TTL ندارد — تنظیمِ ادمین را **ماندگار** دفن کند. حالا آن‌جا هیچ کشی نوشته نمی‌شود. **و تستش اولش vacuous بود:** دو خواندنِ عادی هرگز به آن شاخه نمی‌رسند (بعد از مهاجرت ردیفِ DB هست و مسیرِ عادی جواب می‌دهد) و سابوتاژ نشانش داد؛ حالا طبقِ قاعدهٔ §۶ درهم‌آمیزی **مجبور** می‌شود نه اینکه منتظرش بمانیم. **تست‌ها (۴۷۸ → ۴۸۱).** **اعمال:** بدونِ تغییر — master-only، بدونِ `DELETE`.
- 2026-08-13 — **اپل‌موزیک، فازِ A: فقط لینکِ ترک — و یک عددِ اندازه‌گیری‌شده که یکی از رفع‌های خودم را لغو کرد.** متادیتا از `itunes.apple.com/lookup` (رایگان، بی‌احراز)، بعد همان ماچرِ مشترک روی یوتیوب. **درِ ورودی:** `apple_id()` با تقدمِ `?i=` — تلهٔ اصلیِ این پلتفرم، چون دکمهٔ Share **همیشه** فرمِ آلبوم می‌دهد و شناسهٔ داخلِ مسیر آلبوم است؛ پارسرِ «آخرین بخشِ مسیر» ردیفِ `collection` می‌گیرد و برای یک لینکِ کاملاً معمولیِ ترک می‌گوید «پشتیبانی نمی‌شود». storefront از **کلیدِ کش** بیرون است (شناسه سراسری است) ولی به‌عنوان `&country=` به lookup می‌رود. اپل از روزِ اول در `_MATCH_PLATFORMS` است، پس کلید نسخه می‌گیرد **و** fallbackِ legacy رد می‌شود — یعنی برخلافِ استقرارِ اسپاتیفای **هیچ `DELETE`ی لازم نیست**. **استخراجِ feat، و چرا فقط آراستگی نیست:** اپل مهمان را در **عنوان** می‌گذارد و اسپاتیفای در فهرستِ هنرمند. با مهمانِ پنهان، `_artist_contradiction` خلعِ‌سلاح می‌شود (آن قاعده «جاافتاده **و** اضافه» می‌خواهد و مرجعِ تک‌هنرمنده هرگز «جاافتاده» نمی‌شود)، پس اندازه‌گیری‌شده روی نامزدهای واقعی: خوانندهٔ **غلط** ۹۶٫۹۴ و Art Trackِ **درست** ۹۶٫۰۴ — رتبه وارونه. با استخراج، درست ۱۰۶٫۰۰ می‌شود و غلط **کاملاً رد** می‌شود. دو سودِ دیگر هم سنجیده شد: `_search_queries` دوباره **دو** شکل می‌سازد (شکلِ دوم همان است که برای موسیقیِ ایرانی خواننده را پیدا می‌کند) و کانالِ جریمهٔ کاذبِ «(feat. Session Band)» بسته می‌شود. **پاک‌سازی جراحی است نه «پرانتزها را بردار»** — `[Daft Punk Remix]`, `(Radio Edit)`, `(Live)`, `[Extended Mix]` می‌مانند و `_version_markers` هنوز می‌بیندشان؛ و **`with` عمداً نشانهٔ feat نیست** چون `(With Strings)` را می‌خورد و «Strings» را هنرمند می‌کند. **کلیدهای `match_*`:** پنج کلیدِ ماچر از `spotify_*` تغییرِ نام دادند چون آن نام دیگر صادق نیست؛ مقدارِ ذخیره‌شدهٔ قدیمی روی اولین خواندن **مهاجرت** می‌کند (نه صرفاً fallback — fallbackِ خالص یعنی پنل پیش‌فرض را نشان بدهد و ذخیره از آن نمای غلط دادهٔ واقعی را پاک کند، همان کاری که `/buttons` یک‌بار کرد)، با `log.warning` و با **نقطهٔ حذفِ نوشته‌شده** در §۶. **`download_spotify` → `download_matched`** به همان دلیل. **و مهم‌ترین نتیجهٔ این کار یک چیزی است که ساخته نشد:** `_ALBUM_UNKNOWN` طراحی و سنجیده شد (با مرجعِ آلبوم‌دار، نامزدِ بی‌آلبوم ۱۰۶٫۰۰ و نامزدِ آلبومِ‌مخالف ۹۹٫۹۴ — همان باگِ `_TIME_UNKNOWN`) ولی probe روی مستر **۰ از ۲۲** بازماندهٔ بی‌آلبوم داد و هر ۲۱۰ نامزد از کاتالوگِ `songs` بودند. آرتیفکتِ نمونه‌برداری نیست و این با **اجرا** تفکیک شد نه استدلال: `videos` فقط وقتی شلیک می‌شود که استخرِ ادغام‌شدهٔ `songs` زیرِ ۳ باشد و `ytsearch` شرطی **سخت‌گیرتر** دارد، و گیتِ خودِ probe اندازه‌گیری شد که از گیتِ تولید **سست‌تر** است. پس ثابتی که نمی‌شود کالیبره‌اش کرد برای حالتی که ندیده‌ایم ساخته نشد — همان پوسیدگیِ ثابتِ دستی که کلِ کار برای بستنش بود. **و probe سه نقص در خودش داشت که اجرای خشک پیدا کرد** (پوشش به‌ازای هر فراخوانیِ سرچ شمرده می‌شد → ۴۴ برای ۴ نامزد؛ توزیعِ آلبوم روی کلِ استخر بود نه بازماندگان؛ و `with` در الگوی feat)، **و یک نقصِ چهارم که اپراتور با خواندنِ خروجی گرفت:** معیارِ «هدف» عضویتِ **دقیقِ** `_norm` بود، پس `Mohammad Noori` ↔ `Mohammad Nouri` (شباهت ۹۲٫۹) رد می‌شد — ضبطِ درست با املای دیگر (رتبهٔ ۱) کنار می‌رفت و یک ضبطِ ضعیف‌ترِ دقیق‌املا (رتبهٔ ۴) «هدف» می‌شد. همان چیز «مرغ سحر پیدا نشد» را هم توضیح می‌دهد: نه باگِ ماچر و نه غیبتِ ترک، بلکه `Mohammad Reza Shajarian` ↔ `Mohammadreza Shajarian` (۹۷٫۸) که دقیق نمی‌خورد. حالا از `_ARTIST_SAME_MIN`ِ خودِ تولید استفاده می‌کند. **و ستونِ رتبه هم اصلاح شد** (تصحیحِ اپراتور): میانگینِ رتبهٔ **استخر** به سؤال جواب نمی‌دهد، چون پاک‌سازی استخر را بزرگ‌تر می‌کند و موقعیتِ خام طبعاً عقب می‌رود؛ رتبهٔ **نهایی** در هر ۷ ترک دست‌نخورده ماند، پس خوانشِ درست «پرانتز بی‌ضرر است و شکلِ دومِ کوئری مجانی است». **باگِ یکپارچگی که سرِ راه گرفته شد:** `AppleUnsupported` به `except Exception` می‌افتاد و کلِ استخرِ کوکیِ **یوتیوب** را برای لینکِ آلبوم می‌چرخاند (اپل فایل را از یوتیوب می‌گیرد)؛ حالا مثلِ `AgeRestricted` شاخهٔ خودش را **قبل از** چرخش دارد. **تست‌ها (۴۲۲ → ۴۷۸):** ۱۱ سابوتاژِ مستقل، هرکدام دقیقاً تستِ خودش را می‌اندازد. **و یازدهمی اولش نیفتاد** — تستِ `collectionArtistName` vacuous بود چون فیکسچرم feat را در عنوانِ «Get Lucky» هم گذاشته بود (حدسِ من، نه دادهٔ گزارش‌شده) و استخراج هنرمندانِ گم‌شده را برمی‌گرداند؛ با عنوانِ تمیز — شکلِ واقعی — سابوتاژ می‌افتد. **یک تستِ خودم هم غلط بود:** `caplog.records` از قبل از بلاکِ `with` هم پر است، پس «بارِ دوم هشدار نباشد» به دلیلِ غلط افتاد؛ جایش شمارشِ کلِ مهاجرت‌ها نشست. `test_spotify_match_fingerprint` سبز ماند و **همان اثباتِ دست‌نخوردگیِ رفتارِ اسپاتیفاست**، پس `_MATCH_VERSION` بالا نرفت. **مرزِ صداقتِ فیکسچرها در خودِ فایل نوشته شده:** `itunes.apple.com` از سندباکس ۴۰۳ است، پس ردیف‌ها از فیلدهای **گزارش‌شدهٔ اپراتور** ساخته شده‌اند نه دامپِ ضبط‌شده — نامِ فیلدها واقعی است ولی این فایل اسکیمای اپل را پین نمی‌کند. **اعمال:** master-only (`telabzar update`)؛ نودی وجود ندارد. بدونِ `DELETE`.
- 2026-08-13 — **اسموکِ تولید قبول شد، و همان اجرا یک دستورِ مستنداتیِ ما را از «لازم» به «مضر» تبدیل کرد.** روی مستر: یک `DELETE` دقیقاً **۱** ردیفِ یتیم برداشت (کلِ جمعیتِ پیش‌از‌نسخه — پس دورهٔ «۳۴ ردیف دستی» هم رسماً بسته شد)، و بعد سه فرمِ **واقعی** — `intl-fa`، ساده، و لینکِ خامِ Copy-link با چهار پارامتر — همه روی **یک** ردیف نشستند: کلیدِ `f66192b3`، `hits = 2`. **و این‌جا ادعای اولم را اپراتور تصحیح کرد:** آن اجرا **نرمال‌ساز** را مستقیماً تأیید می‌کند (سه فرمِ واقعاً متفاوت → یک ردیف با hitsِ بالارونده، چیزی که هیچ تستِ واحدی دربارهٔ لینکِ **واقعی** نشان نمی‌دهد) ولی دو تکهٔ دیگر را **نه** — چون `DELETE` جدول را قبلش خالی کرد، پس هیچ ردیفِ legacyِ کهنه‌ای در میدان نبود: ردِ fallback چیزی برای رد کردن نداشت و نسخه هیچ ردیفی را باطل نکرد. برای آن دو، اجرا فقط نشان می‌دهد مسیرِ خوشحال را نشکسته‌اند. پس باطل‌سازیِ نسخه و ردِ fallback روی **تست‌های واحد** سوارند (`test_a_stale_legacy_spotify_row_is_not_resurrected`، `test_a_row_from_an_older_version_is_ignored`، `test_bumping_the_version_moves_only_the_spotify_key`، و کنترلِ `test_a_legacy_youtube_row_is_still_migrated`)، نه روی این اسموک — و صراحت دربارهٔ آنچه پوشش داده **نمی‌شود** خودش بخشی از روال است. **(۱) قاعدهٔ «قبل از اسموک کشِ اسپاتیفای را دستی پاک کن» اصلاح شد** — آن حرف وقتی کلید نسخه نداشت درست بود، ولی حالا **مضر** است: پاک‌کردن دقیقاً همان مدرکی را از بین می‌برد که اسموک باید بسازد (اینکه منطقِ **تازه** فرم‌ها را یکی می‌کند و hit می‌دهد). جایش روالِ درست در §۷ نوشته شد — همان ترک را در **دو فرمِ متفاوت** بفرست، بعد ردیف‌ها را بشمار و `hits` را بخوان: یک ردیف با hitsِ بالارونده یعنی سالم، دو ردیف یعنی فرمی از نرمال‌سازی فرار کرده. سه ارجاعِ باقی‌مانده در changelogِ همان روز هم صریح باطل شد تا کسی از تاریخ دستور نگیرد. `DELETE` فقط مالِ همان استقرار بود، نه بخشی از روالِ اسموک. **(۲) قاعدهٔ ارجاع‌دهی، که همین سشن با هزینه یادش گرفت:** در گزارش و بازبینی شمارهٔ خط بده — همان چیزی است که خوانندهٔ diff لازم دارد — ولی در مستنداتِ **کامیت‌شده** به نامِ سمبل ارجاع بده، چون خط با اولین ویرایشِ بالادست کهنه می‌شود. مصداقِ زنده: افزودنِ یک کامنتِ توضیحی بالای `_MATCH_PLATFORMS` آن را از خطِ ۴۶ به ۵۳ برد و **سه** ارجاعِ نوشته‌شدهٔ چند دقیقه قبل را باطل کرد (کامنتِ import در `dl_cache`، یک گاردِ §۷، و یک ردیفِ changelog) — هیچ‌کدام هم ربطی به آن ویرایش نداشتند. و همان اتفاق برای `si` در `_DROP_PARAMS` افتاد: یک واقعیتِ ثابت، هم «:۴۶» درست بود هم «:۵۱»، بسته به اینکه کدام revision را باز کنی. **(۳) شکافِ `7z` ثبت شد** — دقیقاً همان تلهٔ مارکرِ ffmpeg، این‌بار زنده: `needs_7z` یک تست را گیت می‌کند (همان تستی که رفتارِ path-traversalِ خودِ 7-Zip را پین می‌کند، یعنی چیزی که گاردِ `archive_extract` رویش حساب می‌کند)، CI **فقط** ffmpeg نصب می‌کند، و برخلافِ ffmpeg **گاردِ ضدِ مرگ ندارد**. آنچه **تأیید نشده** و تمامِ سؤال همان است: آیا ایمیجِ `ubuntu-latest` خودش `7z` دارد؟ اگر نه، آن تست **هیچ‌جا** اجرا نمی‌شود. عمداً حدس زده نشد — جوابش یک گامِ `7z --version` است، همان شکلی که نصبِ ffmpeg برای اثباتِ حضور استفاده می‌کند. **(۴) و شکافِ `7z` بسته شد — با جوابی که فرضِ خودم را رد کرد:** ایمیجِ `ubuntu-latest` **`7z` دارد**، پس آن تست از اول در CI می‌دویده و مارکر هرگز مرده نبود؛ نگرانی مالِ من بود و یک اجرای CI در یک دقیقه ردش کرد. **و همان اجرا الگوی خودم را هم تصحیح کرد:** `7z --version` نحوِ درستی نیست — خودِ 7-Zip `Unknown switch: --version` می‌دهد و با کدِ **۷** بیرون می‌آید، یعنی گامی که این‌طور نوشته شود وقتی باینری **هست** هم «نیست» گزارش می‌کند. (`7zz` واقعاً نیست؛ `7z` و `7za` هستند.) حالا `7z i` است، بی‌pipe تا کدِ خروج مالِ خودِ 7z بماند. قاعدهٔ عام: پروبِ حضور که می‌تواند به دلیلِ **دومی** بیفتد (سوئیچِ غلط، نامِ غلط، pipe که کدِ خروج را می‌خورد) پروبِ حضور نیست، و افتادنش شاهدِ غیبت نیست. **نیمهٔ پایدار سرِ جایش ماند** چون از خرابیِ دیگری محافظت می‌کند — حذف‌شدنِ خودِ تستِ گیت‌خورده: (پیشنهادِ اپراتور، و درست بود): گامِ `prove 7z is present` عمداً **بدونِ نصبِ صریح** اضافه شد تا خودِ اجرا جواب بدهد — اگر رانر `7z` دارد سؤال بسته است، اگر ندارد CI بلند می‌شکند و جوابش همان است. و نیمهٔ پایدارش یک تست است: `test_the_7z_gate_is_not_dead_weight` تعدادِ توابعِ دکوراتورخوردهٔ `needs_7z` را **با AST** می‌شمارد. **و نسخهٔ اولِ همان تست vacuous بود** — با regex نوشتم و `@needs_7z`ِ داخلِ **داکس‌استرینگِ خودش** را می‌شمرد، پس با برداشتنِ دکوراتور هم سبز می‌ماند؛ سومین بارِ همین تله در یک سشن، و با سابوتاژ گرفته شد. **اعمال:** هیچ — مستندات و CI.
- 2026-08-13 — **نسخهٔ کلیدِ کش برای پلتفرم‌هایی که هدف را خودمان انتخاب می‌کنیم — و نیمهٔ باربر، fallbackِ legacy بود.** `_MATCH_VERSION` فقط وقتی واردِ کلید می‌شود که `platform_of(url) in downloader._MATCH_PLATFORMS`، و آن مجموعه از `downloader.py:53` خوانده می‌شود نه فهرستِ دستِ‌دومی. **چرا سراسری نه:** کش `file_id` نگه می‌دارد نه بایت، پس ردیفِ کهنه پهنای‌باند خرج نمی‌کند بلکه فایلِ **غلط** می‌دهد؛ و برای لینکِ یوتیوب چیزی برای غلط بودن نیست، پس نسخهٔ سراسری ردیف‌های سالم را برای مشکلی که هرگز نداشتند دور می‌ریخت (تستِ منفی روی **هر دو** کلید، `cache_key` و `_legacy_key`). **و نیمه‌ای که بدونش کلِ کار بی‌اثر بود:** `get_cached` روی miss به `_legacy_key` می‌افتد و ردیف را **جلو می‌آورد**، و برای URLِ اسپاتیفای این دو کلید **از قبل** متفاوت‌اند (چون `_cache_url` اسکیم را می‌ریزد) — پس مسیر این بود: کلیدِ نسخه‌دار → miss → اصابت روی ردیفِ خامِ کهنه → مهاجرت به کلیدِ نو → همان جوابِ غلط، این‌بار «تازه». تستی ردیفِ کهنه را می‌کارد و ثابت می‌کند نه سرو می‌شود نه مهاجرت. **رتِ ثابتِ دستی با تست بسته شد نه با نظم:** فینگرپرینتِ رفتاری خروجیِ زنجیره را هش و پین می‌کند و روی شکست، مقدارِ تازه را **آمادهٔ پیست** چاپ می‌کند. **دو نیمه، و نیمهٔ دوم همان‌جایی است که کور بودیم** (تصحیحِ اپراتور): کلید `(url, options, version)` است و URL با تغییرِ **پارسر** تکان نمی‌خورد، پس رفعِ `_parse_spotify_embed` همهٔ مرجع‌ها و در نتیجه همهٔ هدف‌ها را عوض می‌کند در حالی که فینگرپرینتِ فقط-ماچر (که مرجعش فیکسچرِ ثابت است) ساکن می‌ماند — همان پارسری که هفته‌ها بی‌صدا مرده بود. پس نیمهٔ دو، دو دامپِ **واقعیِ** `__NEXT_DATA__` را از پارسر می‌گذراند و مرجعِ حاصل را هش می‌کند. فلوت‌ها `round(_, 3)` می‌شوند وگرنه هش بینِ محیط‌ها پایدار نیست. **دوطرفه سنجیده شد:** جابه‌جاییِ یک وزن به‌اندازهٔ ۰٫۰۱ یا جریمه به‌اندازهٔ ۱ می‌شکندش، ولی افزودنِ کامنت و تغییرِ نامِ متغیرِ محلی **نمی‌شکندش**. **دامنه، با اجرا نه با فرض (سؤال‌های اپراتور):** `get_cached` تنها مسیرِ خواندنِ کلید-محور است — پنل فقط aggregate می‌گیرد (`admin_web.py:1403-1407`) و گیت‌وی اصلاً به جدول دست نمی‌زند (`/dl` روی `File.dl_token`، `gateway.py:33`). و **پلی‌لیستِ چندترکیِ اسپاتیفای هیچ ردیفِ کشی نمی‌سازد**: `url=url if len(paths) == 1 else None` (`tasks_download.py:1113`) و `_spawn` فقط `if url and f.file_id` می‌نویسد (`:544`)، پس سؤالِ نسخه آن‌جا مطرح نمی‌شود؛ و `put_album_cached` پشتِ `engine == "gallerydl"` است (`:1072`) یعنی فقط کاروسلِ اینستاگرام/پینترست، که درست هم همین است چون gallery-dl هدف را انتخاب نمی‌کند. **و یک فرضیه که با اجرا رد شد:** فرض بود `?si=` (که اپِ اسپاتیفای موقعِ Copy link می‌گذارد) هر بار کلیدِ یکتا می‌سازد و کشِ اسپاتیفای هرگز hit نمی‌خورد — ولی `si` **اولین عضوِ `_DROP_PARAMS`** است (`dl_cache.py:51`)، پس `?si=AbC` و `?si=XyZ` و فرمِ ساده از قبل به یک کلید می‌رسیدند. **نرمال‌سازیِ `sp:<kind>:<id>`** (کامیتِ جدا) پس توجیهِ دیگری دارد: `intl-fa/track/X` و `intl-de/track/X` کلیدِ **متفاوتی** می‌گرفتند و اسپاتیفای همین مسیرِ زبانی را به کاربرِ غیرِانگلیسی می‌دهد، و پارامترهای ناشناختهٔ اشتراک مثلِ `?go=1&nd=1` هم کلید را جدا می‌کردند — سه کلید → یک کلید، با حفظِ تفکیکِ track از playlist. از `spotify_id` استفاده می‌کند نه الگوی تازه. **دو تستِ خودم که همین‌جا افتادند:** تستِ حلقهٔ import را زیررشته‌ای نوشته بودم و **کامنتِ خودم** در `downloader.py:53` را می‌گرفت (همان تلهٔ ثبت‌شدهٔ ۲۰۲۶-۰۸-۱۰) — با AST بازنویسی شد و با افزودنِ یک importِ واقعی ثابت شد vacuous نیست. **تست‌ها (۴۰۵ → ۴۲۱):** ۱۲ تستِ کلید (شاملِ رفت‌وبرگشتِ DBِ واقعیِ SQLite برای ردِ fallback و کنترلِ مهاجرتِ یوتیوب) + ۴ تستِ فینگرپرینت. فیکسچرِ فینگرپرینت از کیس‌های **واقعیِ اندازه‌گیری‌شده** است: Faryad، Jane Maryam، Hallelujah، نامزدِ تماماً فارسی‌نویس، مسیرِ اسکریپتِ مخلوط، `Ebi ↔ Ebrahim Hamedi`، ریمیکس، `art_track` در هر دو حالت، و **هر دو شاخهٔ مدت** (نامزدِ بی‌مدت = مسیرِ `_TIME_UNKNOWN`، و ترکِ بی‌مدت = مسیرِ حذفِ مؤلفه) — یک تست پوششِ همین‌ها را می‌سنجد تا فیکسچر بی‌صدا لاغر نشود. **اعمال (استقرارِ master-only؛ نودی وجود ندارد):** `telabzar update` روی مستر، و **یک‌بار** `DELETE FROM download_cache WHERE platform = 'spotify';` چون جدول eviction ندارد (`created_at` هست ولی هیچ TTLی پیاده نشده) و ردیف‌های قبلی برای همیشه یتیم می‌مانند. از این پس پاک‌کردنِ دستی لازم نیست.
- 2026-08-13 — **تطبیقِ هنرمند: قاعدهٔ تناقض، وزنِ آهنگساز، و معافیتِ گیتِ نام برای خطِ متفاوت — و سابوتاژ یک نقصِ طراحی پیدا کرد نه فقط شکافِ تست.** سه چیز روی یک تابع، با هم. **(۲ وزنِ آهنگساز)** `_artist_match` برای هر هنرمندِ **مرجع** بهترین شباهت را می‌گرفت و اولی را ۰٫۶ وزن می‌داد؛ اسپاتیفای برای موسیقیِ کلاسیکِ ایرانی آهنگساز را اول می‌گذارد، پس «اولی» آهنگساز است نه خواننده. اندازه‌گیری‌شده: وقتی یوتیوب فقط خواننده را فهرست می‌کند (**حالتِ رایج**) ضبطِ درست `[16.7, 100]` می‌گرفت یعنی ۵۰٫۰ و ضبطِ غلط ۶۸٫۰ — یعنی این مؤلفه فعالانه غلط را **۱۸ نمره ترجیح می‌داد**. فرمول با **اندازه‌گیریِ پنج گزینه روی شش سناریو** انتخاب شد نه با سلیقه: امروز ۵۰ در برابرِ ۶۸ (معکوس)، `max(ref)` ۱۰۰/۱۰۰ (بی‌تفکیک)، `mean(ref)` ۵۸٫۳/۶۰٫۰ (هم معکوس و هم Art Trackِ درستِ Get Lucky را به ۳۹٫۱ می‌انداخت)، و تنها `mean(cand-side)` (**۱۰۰ در برابرِ ۵۳٫۵**، حاشیهٔ ۴۶٫۵) و یک ترکیبِ ملایم‌تر (حاشیهٔ ۲۳٫۲) قبول شدند؛ اولی به‌خاطرِ حاشیه و هم‌خوانیِ مفهومی با نیمهٔ «اضافه»ی قاعدهٔ تناقض. هزینهٔ پذیرفته‌شده: مهمانِ اضافه ۱۰۰ → ۷۲٫۷، همچنان خیلی بالاتر از ۵۳٫۵. **(۱ تناقض)** «جاافتاده **و** اضافه» با آستانهٔ ۴۵، به‌عنوان گیت، و کفِ عددی به‌عنوان لایهٔ دومِ ارزان. **دو تصحیح روی انتظارِ ثبت‌شده:** روی هشت سناریو گیتِ قدیم **۷ از ۸** بود نه ۳ از ۵، و آن یک شکست دقیقاً جایگزینیِ خواننده است — یعنی بُردِ قاعده باریک‌تر از یادداشتِ قبلی ولی همان باگِ گزارش‌شده؛ و **Hallelujah/باکلی امروز هم رد می‌شود** (am=۱۶)، پس **کنترل** است نه شکست. **(۳ معافیتِ خط، و اندازه‌گیریِ اولم موردِ غلط را سنجیده بود)** روی نامزدِ **کاملاً** فارسی‌نویس هم نام و هم هنرمند صفر می‌شوند (۳۵٫۳ در برابرِ ۱۰۶)، پس معافیت no-op است و فقط نویز وارد می‌کند — و خنثی‌کردنِ نام هم فقط به ۷۰٫۷ می‌رسد. ولی حالتِ **مخلوط** واقعی است و **اپراتور از دادهٔ خودمان بیرونش کشید**: نامزدِ ۱۳ با عنوانِ `'قطعه فریاد'` و هنرمندِ `'Anushiravan Ruhani'`، که هنرمندش سالم است (۶۰٫۰ قبل، **۸۸٫۹** با فرمولِ تازه) و **تنها** گیتِ نام می‌کشدش. پس `_name_gate_exempt` وقتی **عنوان‌ها** دو خط دارند و امتیازِ هنرمند از ۴۵ رد می‌شود گیت را برمی‌دارد: انتها به انتها به **۶۱٫۶** می‌رسد، از آستانهٔ ۵۵ رد می‌شود، و پس از ردِ رقیبِ غلط توسطِ قاعدهٔ تناقض می‌برد — در حالی که ضبطِ رومی‌شدهٔ درست، وقتی حاضر باشد، با ۱۰۳٫۲ همچنان اول است. **و امتیازِ نام عمداً با خنثی جایگزین نمی‌شود** (درسِ `_TIME_UNKNOWN` در جهتِ مخالف): جایگزینی هدف و طعمه را به یک اندازه بالا می‌برد پس تفکیکی نمی‌خرد و فقط آستانه را ضعیف می‌کند — طعمهٔ همان‌آهنگساز در +۵/+۱۰/+۲۰/+۳۵ ثانیه با مقدارِ واقعی ۵۰٫۰/۴۳٫۰/۳۶٫۲/۳۳٫۱ می‌ماند (همه زیرِ ۵۵) و با خنثیِ ۵۰، طعمهٔ +۲۰ به ۵۵٫۹ می‌رسد و رد می‌شود. `_dominant_script` حرف می‌شمارد (لاتین در برابرِ غیرِلاتین) نه بازهٔ هاردکدِ عربی، پس سیریلیک و CJK هم پوشش دارند و رقم خطِ متفاوت شمرده نمی‌شود. سیگنالِ اطمینان بی‌صدا نیست: `match_confidence_note()` برای برنده لاگِ هشدار می‌گیرد، همان الگوی `reference_is_blind`. **و مهم‌ترین چیزِ این گام: سابوتاژ دو چیز پیدا کرد که خودم ندیده بودم.** (الف) نسخهٔ اول **خطِ نامِ هنرمند** را هم چک می‌کرد؛ برداشتنش هیچ تستی را نینداخت — چون شرطِ **امتیازِ** هنرمند از قبل همان را می‌سنجد — و در تنها حالتی که واقعاً به آن می‌رسید **غلط** بود: فهرستِ دوزبانهٔ `'هایده Haydeh'` در برابرِ مرجعِ فارسی شباهتِ ۵۸٫۸ دارد یعنی هنرمند واقعاً می‌خواند، ولی آن چک خط را «متفاوت» می‌دید و ردش می‌کرد. هم زیادی بود هم مضر، حذف شد. (ب) قاعدهٔ تناقض فقط به‌صورتِ **تابع** تست شده بود، پس حذفِ گیت از `_rank_candidates` هیچ تستی را نمی‌انداخت — و کفِ عددی هم نمی‌تواند جایش را بگیرد، چون امتیازِ همان نامزد ۵۳٫۵ است یعنی بالای کفِ ۴۰. تستِ اتصال اضافه شد. **تست‌ها (۳۸۱ → ۴۰۰):** ۴ شکستِ **رفتاری** روی سورسِ پیش از رفع (از جمله `درست 50.0 در برابرِ غلط 68.0` و افتادنِ زیرمجموعهٔ Get Lucky به ۶۳٫۴) و بقیه قفلِ توابعِ تازه. چهار سابوتاژِ مستقل، هر کدام دقیقاً تستِ خودش را می‌اندازد. `Ebi ↔ Ebrahim Hamedi` (۳۵٫۳) به‌عنوان محدودیتِ شناخته‌شده تست دارد: نامِ مستعار است نه رومی‌سازی. **اعمال:** `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود؛ ردیف‌های `platform='spotify'`ِ کش آن روز دستی پاک شدند — **این کار دیگر نباید تکرار شود**، ببین §۷.
- 2026-08-13 — **باگِ پرانتز: دو نرمال‌ساز، مرزِ کلمه، و فهرستِ صریحِ صورت‌ها — که طراحیِ اولِ خودم را باطل کرد.** `_norm` پنج کار می‌کند و یکی‌شان `_PAREN_RE` است، و `_match_score` همان را برای جست‌وجوی `_BAD_KW` به کار می‌برد — پس **۵ از ۶** عنوانِ واقعی جریمه‌شان صفر می‌شد. اثرِ دومش بدتر بود: حذفِ براکت `_name_match` را هم به **۱۰۰** می‌رساند، یعنی ریمیکس هم‌زمان تطبیقِ کاملِ عنوان می‌گرفت **و** جریمه نمی‌خورد. اندازه‌گیری‌شده: ضبطِ اصلی و ریمیکس **هر دو دقیقاً ۱۰۶٫۰**؛ حالا **۱۰۶٫۰ در برابرِ ۹۴٫۰**، و `(Live …)`/`(Radio Edit)`/`[Official Live Video]` هم ۹۴٫۰، `(Slowed + Reverb)` ۸۲٫۰ (دو نشانه روی هم، مثلِ قبل)، و کنترل‌های `(Remastered)`/`(Official Video)` دست‌نخورده روی ۱۰۶٫۰. رتبه‌بندی هم دیگر اصلی را بالای ریمیکس می‌گذارد. **`_norm` دست‌نخورده ماند** — حذفِ براکت برای مقایسهٔ fuzzy درست است، وگرنه «Faryad (Official Video)» دیگر با «Faryad» تطبیق نمی‌خورد؛ نامِ ریمیکس عمداً ۱۰۰ می‌ماند و چیزی که جدایش می‌کند **جریمه** است. **`_penalty_text` سه کار را عمداً نمی‌کند**، هر سه سنجیده: براکت را نگه می‌دارد؛ `_FEAT_RE` را اعمال نمی‌کند چون `.*$` دارد و «Faryad (Live) feat. Haydeh» را به `'faryad'` فرو می‌ریخت و نشانه را کامل گم می‌کرد؛ و `_NOISE_RE` را اعمال نمی‌کند. بده‌بستانِ پذیرفته‌شده در داکس‌استرینگ ثبت شد (گروهی به‌نامِ «Live Band» در اعتبارِ feat حالا −۱۲ می‌گیرد؛ ۱۲ نمره است نه رد شدن). **و تقارن، که خودش یک باگِ نساخته بود:** شرطِ `kw in ct and kw not in tt` زیرِ `_norm` متقارن بود (هر دو براکت را می‌ریختند)، پس عوض‌کردنِ **فقط** سمتِ نامزد باگِ تازه می‌ساخت — مرجعی که خودش لایو است `tt='faryad'` می‌داد در برابرِ `ct='faryad live in tehran'` و ناحق `live` را جریمه می‌کرد؛ پیش از پیاده‌سازی اندازه گرفته و بسته شد. **و مهم‌ترین چیزِ این کار: اپراتور طراحیِ اولم را متوقف کرد و اندازه‌گیری ردش کرد.** من قاعدهٔ عامِ `(?:s|es|ed|ing)?` را پیشنهاد داده بودم تا `remixes`/`covers`/`sessions` از مرزِ کلمه نجات پیدا کنند، و فقط زیررشته‌های **تصادفی** (`oliver`/`recovery`/`delivery`) را سنجیده بودم. ردهٔ نسنجیده چیزِ دیگری بود: **صرفِ خودِ کلیدواژه که کلمهٔ عادیِ انگلیسی است** — `lives` (zipf ۵٫۱)، `covered` (۴٫۸)، `covers` (۴٫۵)، `covering` (۴٫۵)، `performances` (۴٫۳)، `reactions` (۴٫۲). روی ۲۰ عنوانِ واقعی: قاعدهٔ عام **۱۰ مثبتِ کاذب**، یعنی **دقیقاً همان‌قدر که تطبیقِ زیررشته‌ای** — «Nine Lives» و «Covered in Rain» هر دو −۱۲؛ صرفِ per-keyword ۲ خطا (`covered`)؛ **فهرستِ صریحِ `remixes/remixed/covers/sessions/mashups` صفر خطا**. `_BAD_BASE` هر صورت را به کلیدواژهٔ پایه نگاشت می‌کند تا «۱۲− به‌ازای هر کلیدواژه» معنیِ قبلی‌اش را نگه دارد. همان شکلِ `safety.STRONG_TOKENS`/`WORD_TOKENS`: فهرستِ صریح + تستِ رگرسیون، نه قاعده‌ای که خودش را گسترش بدهد. **و مرزِ کلمه یک باگِ موجود را هم برمی‌دارد:** تطبیقِ زیررشته‌ای همین حالا هر ده عنوانِ گروهِ کنترل را جریمه می‌کند، پس «Nine Lives» امروز در تولید ۱۲ نمره می‌بازد — آن مثبت‌های کاذب ریسکِ این تغییر نبودند، وضعِ فعلی بودند. یک ابهام می‌ماند و **تازه نیست**: `session` از قبل در `_BAD_KW` بود پس «Session of Love» امروز هم جریمه می‌خورد و جمعش رفتار را هم‌شکل می‌کند. **ابزار هم به همان قاعده وصل شد** — `version_markers`ِ probe الگوی دست‌نویسِ خودش را داشت و حالا `D._version_markers` را صدا می‌زند، وگرنه دو کپی واگرا می‌شدند (درسِ `remove_cookie_file`)؛ و یک تست همین اشتراک را می‌سنجد. **تست‌ها (۳۶۵ → ۳۸۱):** ۸ شکستِ **رفتاری** روی سورسِ پیش از رفع، از جمله `اصلی 106.0 در برابرِ ریمیکس 106.0` و تقارنِ مرجعِ لایو. جریمه عمداً **از مسیرِ خودِ `_match_score`** سنجیده می‌شود نه با صداکردنِ تابعِ تازه — وگرنه `AttributeError` می‌داد که «نبودِ صفت» را نشان می‌دهد نه شکافِ رفتاری (درسِ فاز ۳پ)؛ تفاضل با عنوانِ بی‌نشانه تمیز است چون `_norm` براکت را می‌ریزد پس نام/هنرمند/مدت یکسان می‌مانند. **دو تستِ خودم غلط بود و همین‌جا گرفته شد:** «Faryad - Remix» را `== -12` خواسته بودم در حالی که بی‌براکت است و مؤلفهٔ نام هم **واقعاً** می‌افتد (−۲۶)، پس `<= -12` شد؛ و «Nine Lives» را با تفاضل سنجیده بودم که `-35` داد چون عنوانِ کاملاً دیگری است و نام عوض می‌شود — به دو تستِ جدا شکسته شد (براکتی با تفاضل، خام روی `_version_markers`). **و یک تستِ گامِ ۰ عوض شد چون طراحیِ آن لحظه را قفل کرده بود:** «Sessions of Love» را «نباید نشانه» گفته بودم زیرِ فرضِ مرزِ خالی؛ اندازه‌گیری آن فرض را رد کرد و حالا `sessions` صورتِ صریح است. دو سابوتاژِ مستقل (برداشتنِ `\b`، و قاعدهٔ عام به‌جای فهرست) هر کدام دقیقاً همان تست‌ها را انداختند. **اعمال:** `downloader.py` روی نودِ دانلود اجرا می‌شود → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود؛ ردیف‌های `platform='spotify'`ِ کش آن روز باید دستی پاک می‌شدند — **دیگر نه**، ببین بولتِ «پاک‌نکردنِ کشِ اسپاتیفای» در §۷.
- 2026-08-13 — **کوئریِ اسپاتیفای: «هنرمندِ اول + عنوان» و «هنرمندِ آخر + عنوان» — و اول ابزارِ اندازه‌گیری تعمیر شد.** ترتیبِ کار عمدی بود: **ابزار قبل از رفع**، چون ابهامِ «برندهٔ ۱۰۳٫۲» بدونِ ابزارِ سالم قابلِ تأیید نبود. **(۰ ابزار)** `hits()` اصابت‌ها را به ترتیبِ **استخر** برمی‌گرداند و هر دو صداکننده `[0]` را هدف می‌گیرند، پس یک مثبتِ کاذبِ «فقط مدت» که جلوتر بیفتد اصابتِ واقعیِ «نام+مدت» را می‌پوشاند — بازتولید شد: `[(0,'فقط مدت'),(2,'نام+مدت')]`، ابزار «رتبهٔ ۱» را برای ضبطِ **غلط** چاپ می‌کرد و مسیرِ ادغام همان ویدیوی غلط را «هدف» می‌گرفت. **این منشأِ «رتبهٔ ۳»ی است که در گزارشِ قبلی مثبتِ کاذب بود.** حالا دو **رده** (نام+مدت، بعد فقط-مدت) با حفظِ ترتیبِ استخر داخلِ هر رده؛ معیارِ «فقط مدت» **حذف نشد** چون همان چیزی است که ضبطِ درست را وقتی با نامِ **فارسی** فهرست شده پیدا می‌کند. به‌علاوه `mark_of` (اصابتِ ضعیف دیگر «✓» نمی‌گیرد) و `describe` (شناسه + عنوانِ کامل + **همهٔ** هنرمندان + مدت، **بی‌برش** — خطِ قبلی نه شناسه داشت نه مدت و هنرمند را روی ۲۴ کاراکتر می‌بُرید، که دقیقاً علتِ بی‌جواب‌ماندنِ «۱۰۳٫۲» بود). **و اجرای خشکِ `main()` نقصی در رفعِ خودم پیدا کرد نه در کدِ قدیم:** ریمیکسِ همان هنرمند با همان طول هر دو نیمهٔ شرطِ قوی را دارد، پس هدف شمرده می‌شد و ابزار می‌گفت «همان ضبطِ درست است»؛ حکم حالا فقط چیزی را که سنجیده ادعا می‌کند و نشانهٔ نسخه `⚠` می‌خورد — روی عنوانِ **خام** و با **مرزِ کلمه**، چون `_BAD_KW` در تولید زیررشته‌ای است و برخورد دارد (`Delivery`→`live`، `Recovery`→`cover`، `Sessions`→`session`). **و `import re` جا افتاده بود، یعنی ابزار روی مستر سرِ import می‌مرد.** **(۱ کوئری)** اپراتور probeِ تعمیرشده را روی مستر زد: **Faryad** — شکلِ کامایی فقط مثبتِ کاذب، **هنرمندِ اول رتبهٔ ۱** و **هنرمندِ آخر رتبهٔ ۲** (هر دو نام+مدت)، ادغامِ ۶۱ نامزد → برندهٔ `WUxurPJmKXI` («Faryad» — Anoushirvan Rohani, Haydeh — ۳۱۲ ثانیه — ۱۰۳٫۲)، **با چشم تأیید شد ضبطِ درست است**؛ **Jane Maryam** — برندهٔ `OB8caWDe4mI`، محمد نوری، ۳۱۱ ثانیه، ۱۰۶٫۰، درست. پس **ادغام به‌تنهایی هر دو شکایتِ گزارش‌شده را می‌بندد**، و به‌همین‌دلیل این گام **جدا و زودتر** merge می‌شود و موارد ۲ و ۳ در PRهای بعدی می‌آیند. `_search_queries()` تنها منبعِ شکل‌هاست. **سه شکل روی اندازه‌گیری حذف شد نه سلیقه:** کامایی و بدونِ‌ویرگول هدف را نیاوردند، و «فقط عنوان» آورد ولی رتبهٔ ۱۶ (Faryad) و ۱۰ (Jane Maryam) و در هر دو **بعد از** اینکه شکلِ دیگری از قبل آورده بود. **چرا هر دو سر:** اسپاتیفای برای موسیقیِ کلاسیکِ ایرانی آهنگساز را اول می‌گذارد پس «آخر» خواننده است، و انتشارِ غربی هنرمندِ اصلی را اول می‌گذارد. **هزینه:** تک‌هنرمند **یک** کوئری (بی‌تغییر) — روی فیکسچرِ واقعیِ پلی‌لیست هر چهار ترک تک‌هنرمندند، یعنی صفر هزینهٔ اضافه؛ گیتِ fallback روی استخرِ **ادغام‌شده** است نه به‌ازای هر شکل و به‌محضِ رسیدن به ۳ می‌ایستد. **ترتیبی، چون ۴۲۹ بی‌صدا `[]` می‌دهد.** **و تلهٔ اصلی:** `download_spotify` همان کوئری را **بارِ دوم و مستقل** می‌ساخت و آخرین‌چارهٔ `ytsearch1:` رویش سوار بود — پس رفعِ `_gather_candidates` به‌تنهایی، آخرین‌چاره را روی همان شکلی می‌گذاشت که اثباتاً هدف را نمی‌آورد؛ هر دو حالا یک منبع دارند و تست هدفِ آخرین‌چاره را می‌سنجد. dedup روی `_cand_url` **اولی را نگه می‌دارد**، که باربر است: `songs` قبل از `videos` می‌آید پس `art_track=True` و بونوسِ +۶ حفظ می‌شود. **تست‌ها (۳۳۹ → ۳۶۵):** ۹ تستِ ابزار (۲ تا روی سورسِ پیش از رفع **رفتاری** می‌افتند؛ سابوتاژِ ترتیب دقیقاً همان دو را می‌اندازد؛ ۳ کنترل هر دو طرف سبز) + ۱۷ تستِ کوئری (**۷ شکستِ رفتاری** روی سورسِ قبل — از جمله `ytsearch1:` با شکلِ کامایی و افتادنِ dedup به `[]` — و ۷ تای دیگر `AttributeError`ِ تابعِ تازه‌اند که در داکس‌استرینگ صریح گفته شده **اثباتِ رفتاری نیست**). دو سابوتاژِ مستقل روی تولید (برگرداندنِ شکلِ کوئری، و گیتِ per-shape) هر کدام دقیقاً تست‌های مربوطِ خودشان را انداختند. یکپارچگی با فیکسچرهای **واقعی** از خودِ `_parse_spotify_embed` سنجیده شد نه دیکشنریِ دست‌ساز. **دو تصحیح در یافته‌های ثبت‌شده (کد حقیقت است):** موردِ ۳ می‌گفت «ضبطِ درست ۱۰۰ می‌گیرد» — این فقط وقتی درست است که نامزد **هر دو** هنرمند را فهرست کند؛ وقتی یوتیوب فقط خواننده را می‌آورد (حالتِ رایج) امتیازش **۵۰٫۰** است و ضبطِ **غلط** ۶۸٫۰، یعنی مؤلفهٔ هنرمند فعالانه غلط را **۱۸ نمره ترجیح می‌دهد** — پس باگ است نه نکتهٔ وزنی و باید در گامِ ۳ هم‌وزنِ قاعدهٔ تناقض دیده شود. و در موردِ ۵، `جان مریم` **۱۰٫۵** است نه ۵٫۰ (دو عددِ دیگر بازتولید شدند؛ نتیجه عوض نمی‌شود). **و ریسکِ «نسنجیده»ی موردِ ۴ سنجیده شد:** ۱۴ از ۱۵ جفتِ رومی‌سازیِ یک هنرمند از آستانهٔ ۴۵ رد می‌شوند (۵۷٫۱–۹۷٫۸)، پس آن ریسک عمدتاً بسته است؛ تنها شکست `Ebi`↔`Ebrahim Hamedi` (۳۵٫۳) است که رومی‌سازی نیست بلکه **نامِ هنری در برابرِ شناسنامه‌ای** است. **اعمال:** `downloader.py` روی نودِ دانلود اجرا می‌شود → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود. کشِ دانلود آن روز نسخه نداشت، پس ردیف‌های `platform='spotify'` جوابِ قدیمی را می‌دادند و باید دستی پاک می‌شدند. **این دستور دیگر معتبر نیست** — از وقتی `_MATCH_VERSION` واردِ کلید شد، پاک‌کردنِ دستی هم لازم نیست و هم مضر است (مدرکِ اسموک را از بین می‌برد)؛ روالِ درست در §۷ است.
- 2026-08-12 — **ممیزیِ matcherِ اسپاتیفای: شش یافتهٔ اندازه‌گیری‌شده، هیچ‌کدام پیاده نشد.** اسموکِ بعد از رفعِ پارسر نشان داد «Jane Maryam» درست شد ولی «Faryad» هنوز خواننده را اشتباه می‌دهد — و کالبدشکافی با `spotify_explain.py` روی مستر ثابت کرد **این شاخهٔ ب است**: ضبطِ درست اصلاً در بیستِ نامزد نیست، پس امتیازدهی بی‌تقصیر است و مسئله **کوئری** است. **(۱ کوئری)** پروبِ زنده روی مستر: کوئریِ فعلی (`"همهٔ هنرمندان با ویرگول + عنوان"`) ضبطِ درست را **اصلاً برنمی‌گرداند** — آن «رتبهٔ ۳»ی که دیده شد **مثبتِ کاذب** بود، یک `Faryaad`ِ ۳۱۲ثانیه‌ای که فقط مدتش نزدیک بود. «هنرمندِ اول + عنوان» **رتبهٔ ۱** (نام+مدت) و «هنرمندِ آخر + عنوان» **رتبهٔ ۳** (نام+مدت). «فقط عنوان» و «فارسی» هر دو رتبهٔ ۱۹ و فقط با مدت. ادغامِ شش شکل: **۷۱ نامزدِ یکتا، برندهٔ ۱۰۳٫۲**. **و کوئریِ فارسی در تولید ساختنی نیست** — آن را اپراتور دستی با `--fa` داد؛ اسپاتیفای فقط نامِ رومی‌شده می‌دهد، پس پیش‌نیازش نویسه‌گردانی است. **هزینه اندازه‌گیری شد:** امروز هر ترک **۱** فراخوانی وقتی کاتالوگ پر است و **۳** وقتی کم‌مایه (`songs`→`videos`→`ytsearch`)؛ دو شکلِ کوئری یعنی ۲، و برای ترکِ **تک‌هنرمندی هر دو یکی می‌شوند** پس هزینهٔ اضافه صفر است. `spotify_max_tracks` پیش‌فرض **۲۰** است نه ۱۰۰. موازی‌سازی ممکن است (`_ytmusic_search` از قبل `to_thread` است) ولی نرخِ لحظه‌ای را دو برابر می‌کند و روی ۴۲۹ این تابع خطا را می‌بلعد و `[]` می‌دهد — **شکستِ بی‌صدا**. **(۲ باگِ پرانتز)** `_norm` محتوای پرانتز را **پیش از** جست‌وجوی `_BAD_KW` حذف می‌کند، و نشانگرِ نسخه تقریباً همیشه همان‌جاست: **۵ از ۶ عنوانِ واقعی** جریمه‌شان کاملاً می‌رود. و اثرِ دوم بدتر است — با حذفِ پرانتز `_name_match("Faryad (DJ Fere Remix)")` برابرِ **۱۰۰** می‌شود، یعنی ریمیکس هم‌زمان تطبیقِ کامل می‌گیرد و جریمه نمی‌خورد؛ همان ۸۰٫۲ که در فهرست دیده شد. یک نرمال‌ساز برای دو کارِ متضاد. **و این در خروجیِ گزارشِ شش‌سؤالیِ خودم بود و ندیدمش** (`Get Lucky (Live)` → `[]` را با «—» علامت زدم انگار درست است). **(۳ `_artist_match`)** بیشینهٔ per-artist است نه پوشش، با وزنِ **۰٫۶ روی هنرمندِ اول** — که اسپاتیفای برای موسیقیِ ایرانی آهنگساز می‌گذارد نه خواننده. پس `100×۰٫۶ + 20×۰٫۴ = ۶۸٫۰` برای نامزدِ اشتباه، و هنرمندِ اضافه در نامزد **هیچ هزینه‌ای ندارد**. **(۴ قاعدهٔ تناقض)** «جاافتاده **و** اضافه = جایگزینی» با آستانهٔ فازیِ ۴۵ — **۷ از ۷** سناریو درست، در حالی که فعلی ۳/۵، min ۳/۵، میانگین ۲/۵، جریمه‌دار ۳/۵. **و هر قاعدهٔ پوشش‌محور نامزدِ درستِ Get Lucky را رد می‌کند** وقتی یوتیوب فقط `Daft Punk` را فهرست کرده (min ۷٫۷، میانگین ۳۹٫۱، جریمه‌دار ۱۳٫۴). ریسکِ نسنجیده: تفاوتِ رومی‌سازی (`Hayedeh`/`Haydeh`) ممکن است «اضافه» خوانده شود. **(۵ خطِ فارسی)** `قطعه فریاد` → **۴٫۸**، `فریاد` → **۰٫۰**، `جان مریم` → **۵٫۰** — همه زیرِ گیتِ ۴۵، پس کلِ کاتالوگِ فارسی‌نویس حذف می‌شود. سه گزینه با هزینه‌شان ثبت شد؛ نویسه‌گردانی **ذاتاً مبهم** است چون فارسی مصوتِ کوتاه نمی‌نویسد. **(۶ گیتِ ۴۰)** **۳ از ۹** جفتِ نامِ بی‌ربط از آن رد می‌شوند (`Mohammad Nouri`↔`Sara Naeini` و `Shajarian`↔`Nazeri` هر دو دقیقاً **۴۰٫۰**، و گیت `< 40` است)، پس امروز عملاً گیتِ **مدت** کار می‌کند نه گیتِ هنرمند. **(۷ کلیدِ کش)** نسخه ندارد؛ تصمیمِ اپراتور: نسخه فقط برای پلتفرم‌هایی که **ما هدف را انتخاب می‌کنیم**، چون ردیفِ یوتیوب دقیقاً همان چیزی است که URL می‌گوید و نسخهٔ سراسری ردیف‌های سالم را دور می‌ریزد. **ابزارها:** `tools/spotify_query_probe.py` اضافه شد. **و یک باگ در ابزارِ خودم که همین‌جا لو رفت:** `hits()` اصابت‌ها را به ترتیبِ استخر برمی‌گرداند و `midx[0]` اولی را هدف می‌گیرد، پس یک اصابتِ «فقط مدت» می‌تواند جلوی «نام+مدت» بیفتد و رتبهٔ اشتباه گزارش شود — دقیقاً همان مثبتِ کاذبی که خودم هشدارش را داده بودم. **ترتیبِ توافق‌شده برای سشنِ بعد: (۱) کوئری، (۲) باگِ پرانتز، (۳) تناقض + معافیتِ خط.** **اعمال:** هیچ — فقط مستندات و یک ابزار.
- 2026-08-12 — **فاز ۳ح: پارسرِ embedِ اسپاتیفای هفته‌ها مرده بود و هیچ‌کس نفهمید — چون fallback بی‌صدا موفق می‌شد.** گزارشِ کاربر: «Jane Maryam» درخواست شد، **سارا نایینی** تحویل شد به‌جای **محمد نوری**. با ابزارِ `spotify_explain.py` روی مستر، علت در سه خطِ اولِ خروجی بود نه در رتبه‌بندی: `artist=''` و `duration=None`. **زنجیرهٔ کامل، که هر سه استنتاجِ قبلیِ من را باطل کرد:** اسپاتیفای اسکیمای embed را عوض کرده و `coverArt` را کلاً حذف کرده؛ شرطِ `_find_spotify_entity` (`trackList` **یا** `title`+`coverArt`) دیگر هیچ‌وقت برقرار نمی‌شد، پس `_parse_spotify_embed` **همیشه `None`** می‌داد و `_spotify_scrape` بی‌صدا به **oEmbed** می‌افتاد که فقط عنوان و کاور دارد. آن `title`ی که در خروجی می‌دیدیم اصلاً از پارسر نیامده بود. **و مرجعِ بی‌هنرمند و بی‌مدت هر دو گیت را هم‌زمان خاموش می‌کند** (`_artist_match` روی مرجعِ بی‌هنرمند `None` می‌دهد و شرطِ گیت `am is not None` است؛ `_duration_reject` هر دو مدت را لازم دارد)، پس **یازده نامزد دقیقاً ۱۰۶٫۰** گرفتند و برنده صرفاً اولین نفرِ فهرست بود — ضبطِ درستِ محمد نوری نفرِ **نهم** بود با همان امتیاز. **نگاشتِ تأییدشده** (همه زیرِ `props.pageProps.state.data.entity`): `title`/`name` · `artists[].name` (**آرایه**، نه رشته) · `duration` **میلی‌ثانیه** · `releaseDate.isoString` · `visualIdentity.image[].url`؛ `album` وجود ندارد. **`_find_spotify_entity` دیگر به کلیدِ منفرد بند نیست:** نامزدها امتیاز می‌گیرند (تعدادِ فیلدهای معنی‌دار + پاداشِ `type`) و **کامل‌ترین** برنده می‌شود نه اولین — چون شرطِ قبلی «اولین تطبیق» بود و یک زیرآبجکتِ عنوان‌دار می‌توانست entityِ واقعی را بزند. **سه چیزِ ناخواسته که همین کار بیرون کشید:** (۱) الگوی استخراج `>(\{.*?\})</script>` بود، یعنی `}` را **بلافاصله** پیش از تگ می‌خواست و یک newline کلِ پارس را ساکت می‌شکست — حالا `>(.*?)</script>` با `.strip()`؛ (۲) `int(ms/1000)` هر مدتی را تا یک ثانیه **کم** می‌کرد (۳۱۰۹۷۳ → ۳۱۰ به‌جای ۳۱۱) و آن یک ثانیه روی `_time_match` ~۱۰ واحد می‌ارزد، پس `round` شد — در **هر دو** مسیرِ embed و API؛ (۳) `year` حالا **در دسترس است** (`releaseDate.isoString`)، پس ادعای قبلیِ من در §۷ که «مسیرِ embed سال نمی‌دهد» تصحیح شد — هرچند `year` در امتیازدهی استفاده نمی‌شود و فقط برای تگ‌گذاری است. **گاردِ کوری:** `reference_is_blind()` مرجعِ بی‌هنرمند و بی‌مدت را علامت می‌زند و `_spotify_scrape` روی سقوط به oEmbed **`log.warning`** می‌دهد نه `log.info` — همان چیزی که اگر بود این باگ هفتهٔ اول پیدا می‌شد. مصرف‌کنندهٔ کاربری‌اش رفعِ آستانه/هشدار است که هنوز ساخته نشده. **تست‌ها (۳۲۲ → ۳۲۹):** فیکسچرِ اصلی حالا **پاسخِ واقعیِ ضبط‌شده از مستر** است (`tests/fixtures/spotify_embed_track.json`)، نه ساختگی — و این دقیقاً همان شکافی بود که خودم در همان فایل علامت زده بودم («عمداً چیزی دربارهٔ نامِ فیلدهای اسپاتیفای ثابت نمی‌کند») و همین باگ را پنهان کرد. تست‌های شکلِ قدیمی حذف نشدند ولی صریحاً به `_legacy_entity` تغییرِ نام دادند و می‌گویند دربارهٔ **fallback**اند نه رفتارِ امروز. روی سورسِ مستقر **۱۰ تست** می‌افتد. **دو تستِ خودم که غلط بودند و روی سورسِ سالم افتادند:** ادعای «امتیازها باید متفاوت باشند» — در حالی که با مرجعِ سالم فقط **یک** نامزد از گیت رد می‌شود و مجموعهٔ تک‌عضوی طبعاً یک مقدار دارد (ادعای درست: بقیه باید **گیت بخورند**، که قوی‌تر است)؛ و انتظارِ `duration == 311` که باگِ `int` را بیرون کشید. **دو ابزار:** `tools/spotify_explain.py` (کلِ فهرستِ نامزدها با تصمیمِ هر گیت) و `tools/spotify_embed_dump.py` (ساختارِ خام + ذخیرهٔ فیکسچر). **و باگِ خودم در ابزار:** نسخهٔ اول `open.spotify.com/track/<id>` را می‌گرفت که پوستهٔ وب‌پلیر است؛ حالا مثلِ `_spotify_scrape` به `/embed/<kind>/<id>` تبدیل می‌کند. **دامپِ پلی‌لیست (۱۰۰ عضو) هم گرفته شد و یک تصحیحِ مهم داد:** شاخهٔ `trackList` **هیچ‌وقت نشکسته بود** — فقط لینکِ تک‌ترک خراب بود، و هر دو موردِ شکایت هم `/track/` بودند. مهم‌تر: **`subtitle` کدِ کهنه نیست.** دو مسیر دو شکلِ **هم‌زمان‌زندهٔ** هنرمند دارند — تک‌ترک `artists[].name` (آرایه) و ترکِ داخلِ `trackList` یک `subtitle`ِ **رشته‌ای**. برچسبِ «قدیمی» که اول رویش گذاشته بودم خطرناک بود: هر پاکسازیِ کدِ کهنه که `subtitle` را بردارد، **همهٔ پلی‌لیست‌ها** را می‌شکند. حالا کد، فیکسچر و `test_both_live_artist_shapes_are_supported` هر سه صریح می‌گویند؛ تابعِ کمکیِ تست هم از `_legacy_entity` به `_entity_with_cover_art` تغییرِ نام داد چون فقط `coverArt`ش کهنه بود نه `subtitle`ش. فیکسچرِ پلی‌لیست هم از همان پاسخِ واقعی اضافه شد (مدت آن‌جا هم میلی‌ثانیه است، پس رفعِ `round` هر دو مسیر را می‌گیرد؛ آیتم‌ها کاورِ اختصاصی ندارند؛ `playabilityReason` می‌تواند `COUNTRY_RESTRICTED` باشد که برای ما بی‌اثر است چون فایل از یوتیوب می‌آید). **و یک تستِ خودم حذف شد چون شکلی را قفل می‌کرد که هیچ دامپی نشان نداده:** `subtitle`ِ **لیستی** — همان تلهٔ فیکسچرِ ساختگی، این‌بار کوچک‌تر. **و دامپِ اول یک باگِ زندهٔ دیگر را لو داد:** `subtitle` روی خودِ entityِ پلی‌لیست **مالک** است («Spotify»)، نه هنرمند — یعنی سه معنا بسته به جایش. و چون شاخهٔ تک‌ترک روی `not tl` می‌افتاد نه روی `kind`، پلی‌لیستِ خالی یا هر پلی‌لیستی که فهرستش خوانده نشود **یک ترکِ ساختگی** می‌ساخت: `('Persian Essentials', 'Spotify', None)`. `reference_is_blind` هم نمی‌گرفتش چون «Spotify» هنرمندِ ناتهی است، پس ربات دنبالِ «Spotify Persian Essentials» در یوتیوب می‌گشت و هرچه برمی‌گشت تحویل می‌داد — بی‌صدا. **با اجرا پیدا شد نه با استدلال** (به‌درخواستِ اپراتور)، و حالا مجموعه‌ای که فهرستش خوانده نشود **شکستِ پارس** است نه یک ترک. کاور و سالِ سطحِ پلی‌لیست در هیچ دامپی نبودند، پس نه حدس زده شدند نه ادعایی رویشان هست. `isExplicit`/`isNineteenPlus` فقط ثبت شدند. **اعمال:** `downloader.py` روی نودِ دانلود اجرا می‌شود → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود.
- 2026-08-12 — **فاز ۳ج: سه رفع در matcherِ اسپاتیفای + اولین پوششِ پارسرِ embed.** این‌ها از گزارشِ کیفیتِ matcher درآمدند، و **قیدِ تازه‌ای طراحی را عوض کرد**: اپراتور تعیین کرد که Web APIِ اسپاتیفای برای ما بسته است (تغییراتِ فوریهٔ ۲۰۲۶ — نیازِ اکانتِ پرمیومِ مالکِ اپ، حالتِ Development محدود به یک Client ID و پنج کاربر، فاصله‌گرفتنِ اسپاتیفای از Client Credentials برای متادیتا، و سهمیهٔ گسترده فقط برای ۲۵۰ هزار کاربرِ ماهانه). پس **ISRC هرگز در دسترس نخواهد بود** و matcher روی سه سیگنال می‌ماند: نام ۰٫۴۰، هنرمند ۰٫۲۵، مدت ۰٫۲۷ (که چون آلبوم هم همیشه `None` است روی ۰٫۹۲ نرمال می‌شوند). **(۱ باگِ `ft`)** `_ARTIST_SPLIT_RE` سه شاخهٔ `feat`/`ft`/`featuring` را **بدونِ مرزِ کلمه** داشت در حالی که سه شاخهٔ همسایه‌اش (`\bx\b`/`\bvs\b`/`\band\b`) داشتند — همین ناهماهنگی باعث می‌شد به چشم نیاید. **۱۴ از ۴۰ نامِ واقعی خرد می‌شدند**، هر چهارده‌تا از شاخهٔ `ft`: «Daft Punk» → `['Da','Punk']`، و همین‌طور Taylor Swift و Kraftwerk و Deftones و Soft Cell و Shaft و… . **و شدتِ واقعی دو چیز است، نه آنچه اول گفتم:** روی ترکِ **چندهنرمندی** گیتِ `am<40` نامزدِ **درست** را پیش از امتیازدهی می‌انداخت (۳۲٫۳)، و روی همه فاصلهٔ «ضبطِ درست» تا «کاور» از ~۲۶ به ۱۵٫۴ می‌افتاد یعنی ~۴۰٪ از قدرتِ تفکیک. ادعای اولیه‌ام که روی تک‌هنرمند هم نتیجه را برمی‌گرداند **غلط بود و اپراتور پذیرفت که فرضیه‌اش بیش‌ازحد بوده**؛ نتوانستم چنین موردی بسازم چون وقتی همهٔ نامزدها یک هنرمند دارند خرابی هم‌مود است. **مرزِ یک‌طرفه کافی نبود** (`\bfeat` هنوز «Feature Films» را می‌شکند) پس دوطرفه شد. **و یک باگِ سومِ ناگفته از دلِ همین خط درآمد:** با الگوی قدیمی شاخهٔ `feat` روی `featuring` **سایه می‌انداخت**، پس `Drake featuring Rihanna` می‌شد `['Drake','uring Rihanna']` — آن جداکننده هیچ‌وقت کار نکرده بود. **(۳ مدتِ نامعلوم)** `_match_score` مؤلفهٔ غایب را از میانگین حذف و بقیه را دوباره نرمال می‌کرد، یعنی «نمی‌دانم» **دقیقاً** نمرهٔ «مدتِ کامل» را می‌گرفت (هر دو ۱۰۶٫۰۰) و از نامزدِ ۳ ثانیه‌ای (۹۹٫۰۰) جلو می‌زد. طبقِ تصمیمِ اپراتور **مقدارِ خنثی، نه جریمه** — جریمه ادعای «نبودِ مدت مشکوک است» را دارد که شاهدی برایش نداریم. `_TIME_UNKNOWN=50` وسطِ بازهٔ خروجیِ `_time_match` است و روی آن منحنی معادلِ **۶٫۹ ثانیه** اختلاف، یعنی جایی بینِ «همان ضبط با مسترِ متفاوت» و «نسخهٔ دیگر». **یک استثنا عمدی است:** اگر مدتِ **خودِ ترک** نامعلوم باشد مؤلفه مثلِ قبل حذف می‌شود، چون آن‌وقت هیچ نامزدی قابلِ مقایسه نیست و دادنِ ۵۰ به همه فقط امتیازها را فشرده می‌کند (رتبه‌بندی اثباتاً عوض نمی‌شود، چون تبدیل یکنواست). **(۴ کدِ مرده)** `_pick_best_match` هیچ فراخوانی نداشت و `download_spotify` همان منطق را درجا نوشته بود — حذف شد، مثلِ `zip` و `thumb`. **(کدِ مردهٔ ISRC نگه داشته شد + کامنت)** شاخهٔ جست‌وجوی ISRC و بونوسِ `isrc_hit`ِ +۲۰ در تولید هرگز شلیک نمی‌کنند ولی هزینه‌شان صفر است و اگر کسی credential داشت کار می‌کنند؛ کامنت می‌گوید هیچ طراحی‌ای نباید رویشان حساب کند. **تست‌ها (۲۶۱ → ۳۲۲):** ۳۶ تست روی سورسِ پیش از رفع می‌افتد. **پوششِ `_parse_spotify_embed` برای اولین بار** — که تا دیروز صفر بود در حالی که از امروز **تنها** مسیرِ متادیتاست. **و مرزِ صداقتش در خودِ فایل نوشته شده:** `open.spotify.com` از سندباکسِ تست در دسترس نیست (پروکسی `CONNECT` را ۴۰۳ می‌کند — با `__agentproxy/status` تأیید شد)، پس فیکسچرها از روی **انتظارِ خودِ پارسر** ساخته شده‌اند نه از صفحهٔ ضبط‌شده؛ رفتارِ ما را قفل می‌کنند و عمداً چیزی دربارهٔ نامِ فیلدهای اسپاتیفای ثابت نمی‌کنند. **یک تستِ خودم که غلط بود و همین‌جا افتاد:** «فاصلهٔ تا کاور» را بینِ **دو هنرمندِ متفاوت** برابر خواسته بودم، در حالی که آن فاصله به شباهتِ فازیِ همان نام با «The Cover Band» بستگی دارد و بی‌ربط به این باگ فرق می‌کند — روی سورسِ **سالم** افتاد، یعنی تست خراب بود نه کد؛ جایش ادعای مستقیمِ «هنرمندِ دقیقاً درست باید ۱۰۰ بگیرد» و کفِ سنجیده‌شدهٔ ۲۳ نشست. **(رفع ۲ عمداً انجام نشد)** بی‌اثربودنِ `spotify_match_min` سرِ جایش است؛ اپراتور گزینهٔ چهارمی داد که از هر سهٔ من بهتر است — **آستانه به‌جای رد کردن، هشدار بدهد** — ولی تصمیمش به دادهٔ واقعی گره خورد: اول توزیعِ امتیازِ برنده روی چند ده ترکِ متنوع اندازه گرفته می‌شود، بعد هم رفع ۲ و هم بازوزنیِ `art_track` تصمیم‌پذیر می‌شوند. **اعمال:** `downloader.py` روی نودِ دانلود اجرا می‌شود → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود.
- 2026-08-12 — **فاز ۳ث (موارد ۴، ۵، ۱۰): سه موردِ باقی‌مانده — و با این، ممیزیِ فاز ۳ تمام است.** **(۴ رفت‌وبرگشتِ Redis در `pick()`)** تنظیمات از قبل یک‌بار خوانده می‌شد (`Limits`)، ولی بقیهٔ چیزها هنوز **به‌ازای هر اکانت** بود: یک `GET` متا، یک `EXISTS` کول‌داون، و داخلِ `_over_budget` دو `GET` دیگر (شمارندهٔ ساعتی و مهرِ آخرین‌استفاده) — یعنی **۴N+۲** فرمان. روی مستر بی‌اهمیت است؛ روی نودِ دانلود هرکدام یک رفت‌وبرگشتِ WireGuard است و `pick()` **داخلِ حلقهٔ چرخشِ کوکی** صدا زده می‌شود، پس ضرب می‌شد. حالا `get_metas`/`cooldowns`/`_mget` دسته‌ای می‌خوانند و `over_budget` نسخهٔ **همگامِ** `_over_budget` است که مقادیرِ ازپیش‌خوانده را می‌گیرد — همان الگویی که `Limits` بنا گذاشت. **اندازه‌گیری‌شده: ۸ اکانت ۳۳ فرمان → ۹ فرمان، و ۲ و ۸ اکانت هر دو ۹ (مستقل از N).** چهار ریزه‌کاریِ باربر: `TTL` جای **هر دو**ی `EXISTS` و `TTL` را می‌گیرد چون روی کلیدِ نبوده `-2` می‌دهد، پس ثانیهٔ باقی‌ماندهٔ پنل مجانی درمی‌آید؛ نامزدها **قبل از** خواندنِ سهمیه فیلتر می‌شوند پس اکانتِ فریز/کول‌داون هزینه‌ای ندارد؛ زیرِ `ignore_budget` آن دو `MGET` اصلاً اجرا نمی‌شوند؛ و مقدارِ برگشتی باید از `_int` رد شود، چون `usage` کلِ خواندن را در `try` داشت و یک `int()`ِ لخت در مسیرِ دسته‌ای یک کلیدِ خراب را به `pick()`ی تبدیل می‌کند که **می‌ترکد** — این یکی سرِ بازخوانیِ diff پیدا شد، نه سرِ طراحی. **(۵ کشِ مدلِ whisper)** ایمیج فقط `base` را پیش‌کش می‌کند ولی پنل پنج مدل می‌دهد، پس هر انتخابِ دیگری در **لایهٔ نوشتنیِ کانتینر** می‌نشست و `telabzar update` دورش می‌ریخت: `large-v3` ≈ ۳ گیگابایت، **با هر آپدیت دوباره**، وسطِ جابِ کاربر و با اشغالِ یکی از چهار اسلات. ولومِ نام‌دارِ `model-cache:/opt/models/hf` اضافه شد. **و محدودیتش صریح ثبت شد به‌جای اینکه رفعِ کامل جا زده شود:** `node/install.sh` کانتینرِ نقش را **بدونِ هیچ ولومی** اجرا می‌کند (بررسی شد — حتی یک `-v` ندارد)، پس نودِ پردازش هنوز بعد از هر `node/update.sh` دوباره دانلود می‌کند؛ عمداً دست‌نخورده چون امروز نودی وصل نیست. **(۱۰ پیامِ غلطِ اسپاتیفای)** وقتی گیتِ سنی **همهٔ** ترک‌ها را می‌انداخت، کاربر «no YouTube match» می‌گرفت یعنی علتِ اشتباه. حالا ترک‌های افتاده و سهمِ `AgeRestricted` شمرده می‌شوند و اگر برابر بودند خودِ `AgeRestricted` بالا می‌رود (که `run_download` به `nsfw_blocked` نگاشتش می‌کند). شرط عمداً «همهٔ **افتاده‌ها**» است نه «همهٔ ترک‌ها» — اگر یکی سنی بود و یکی نامزد نداشت، پیامِ عمومی درست‌تر است. **و retryِ pot باید استثنا می‌شد:** حلقه روی هر خطا یک‌بار بدونِ pot دوباره تلاش می‌کند، ولی ردِ سنی کرشِ pot نیست — تلاشِ دوم هم یک اجرای اضافیِ yt-dlp خرج می‌کرد هم می‌توانست `AgeRestricted` را زیرِ خطای دیگری دفن کند، یعنی دقیقاً همان سیگنالی که رفع رویش سوار است. **(الحاقیه) پیش‌فرضِ `cookies_dir` از `""` به `/cookies` — و دو باگِ واقعی که همین الحاقیه بیرون کشید.** با رشتهٔ خالی `os.path.join("", name)` مسیرِ **نسبی** می‌داد و کوکی در CWDِ پروسه نوشته می‌شد؛ خودم همین سشن با یک اسکریپتِ اندازه‌گیری هشت فایلِ کوکی در ریشهٔ ریپو ریختم. فرضم این بود که «در تولید رخ نمی‌دهد چون compose ستش می‌کند» — و **غلط بود، در هر دو جهت.** **(الف) ربات هم کوکی می‌نویسد:** پیستِ کوکی از داخلِ تلگرام (`routers/admin.py:224`) در پروسهٔ **ربات** اجرا می‌شود، ولی سرویسِ `bot` نه `COOKIES_DIR` داشت نه ولومِ `./cookies` — یعنی آن کوکی در CWDِ کانتینر می‌افتاد و هیچ‌جا دیده نمی‌شد. آینهٔ Redis هم نجاتش نمی‌داد، چون `list_names` هر وقت روی دیسک `*.txt` پیدا کند شاخهٔ دیسک را برنده می‌کند و روی مستر همیشه پیدا می‌کند: پس نه پنل آن اکانت را فهرست می‌کرد و نه ورکرِ دانلودِ مستر استفاده‌اش می‌کرد. **و رفعِ پیش‌فرض به‌تنهایی کافی نبود** — با `/cookies` و بدونِ ولوم، `open()` می‌ترکید و پیست «ذخیره نشد.» می‌داد؛ بهتر از سکوت، ولی هنوز خراب. هر دو خط (env + ولومِ نوشتنی) به سرویسِ `bot` اضافه شد. **(ب) `.env.example` مین را دوباره مسلح می‌کرد:** خطِ `COOKIES_DIR=` با مقدارِ **خالی** آن‌جا بود، و مقدارِ خالی با کلیدِ غایب یکی نیست — pydantic همان `""` را می‌گیرد و پیش‌فرضِ تازه را باطل می‌کند. سنجیده شد، حذف شد، و گاردش اضافه. **یک نکتهٔ روشِ تست هم این‌جا بود:** گاردِ compose باید **به تفکیکِ سرویس** بخواند — تطبیقِ رشته‌ایِ `COOKIES_DIR: /cookies` صرفاً به‌خاطرِ نسخهٔ `admin` سبز می‌شد و دربارهٔ `bot` هیچ نمی‌گفت، پس `PyYAML` به `requirements-dev.txt` اضافه شد تا YAML با پارسر خوانده شود نه regex. **تست‌ها (۲۴۲ → ۲۶۱):** شمارش با `CountingRedis` (زیرکلاسِ `FakeRedis` که `execute_command` را می‌شمارد) روی Redisِ واقعیِ درون‌حافظه‌ای، نه ماک. **شش تست از هفت تستِ رفتاری عمداً دربارهٔ *تعداد* نیستند** بلکه دربارهٔ این‌اند که بهینه‌سازی **انتخاب** را عوض نکرده باشد (کول‌داون، سقفِ ساعتی، disabled/frozen، پینِ خروجی، ثانیهٔ باقی‌ماندهٔ پنل) — بهینه‌سازی‌ای که اکانتِ دیگری برگرداند از خودِ مشکل بدتر است. روی سورسِ پیش از رفع **۷ تست** می‌افتد. **و یک تستِ خودم که vacuous بود و همین‌جا گرفته شد:** `test_the_round_trips_do_not_grow_with_the_pool` هر دو بار ۸ اکانت می‌ساخت، یعنی ۸ را با ۸ مقایسه می‌کرد و روی سورسِ پیش از رفع **هم سبز بود**؛ حالا ۲ در برابر ۸ است و پیش از رفع `9 → 33` می‌دهد. **یک سابوتاژ هم ادعای خودش را رد کرد** (شمارشِ رشته‌ایِ غلط، پس فایل اصلاً عوض نشده بود و «۱ passed» بی‌معنا بود) — همان درسِ ۲۰۲۶-۰۸-۱۰: سابوتاژ هم مثلِ تست باید ادعایش را چک کند. **اعمال:** `cookies.py`/`downloader.py` روی نودِ دانلود اجرا می‌شوند → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود؛ ولومِ `model-cache` با `telabzar update` ساخته می‌شود (بارِ اول `base`ِ ایمیج داخلش کپی می‌شود، چیزی از دست نمی‌رود).
- 2026-08-12 — **فاز ۳ت (موردِ ۱۱ + PySocks): موتورِ `direct` بالاخره از پروکسیِ socks می‌رود.** تا امروز `_http_proxy` هر پروکسیِ غیرِhttp را دور می‌ریخت، پس با `socks5h://` — همان چیزی که **مستندِ خودمان توصیه می‌کرد** — یوتیوب و اینستاگرام از خروجی می‌رفتند و دانلودِ فایلِ مستقیم **بی‌صدا** از IPِ خودِ مستر. `_proxy_kind()` حالا http/socks را تفکیک می‌کند و `_direct_connector` مسیرِ socks را به `aiohttp_socks.ProxyConnector` می‌دهد، با کلیدِ زمانِ‌اجرای `dl_direct_proxy` (پیش‌فرض **روشن**، به استدلالِ اپراتور: با پروکسیِ http این موتور همیشه از پروکسی می‌رفته، پس روشن‌بودن هم‌شکل‌کردن است نه رفتارِ تازه؛ خاموش‌بودن یعنی نگه‌داشتنِ باگ). **سه یافته که همه روی ۰.۱۲.۰ دوباره سنجیده شدند نه ارثی از یادداشتِ ۰.۱۱.۰:** (الف) `ProxyConnector` بی‌قیدوشرط `NoResolver()` می‌گذارد، پس وتوی ضدِTOCTOU آن‌جا **قابلِ وصل نیست** و بی‌صدا ناپدید می‌شود؛ (ب) جایگزینش — پین‌کردنِ IPِ تأییدشده — بررسی و **رد شد**، چون python_socks `server_hostname` را از `dest_host` می‌سازد (`_stream.start_tls(hostname=…)`) و یک IP اعتبارسنجیِ سرتیفیکیتِ هر هاستِ HTTPS را می‌شکند؛ پس دفاع **درِ ورودی** است — که رگرسیون نیست، چون با پروکسیِ http هم از قبل همین بود؛ (پ) `socks5h://` را python_socks نمی‌شناسد و به `socks5://` بازنویسی می‌شود، که **بازنویسیِ خالصِ اسکیم** است چون `rdns` همان‌جا پیش‌فرض True است — برخلافِ curl. **شکستِ DNS برای هر دو نوعِ پروکسی fail-closed شد** (پیشنهادِ اپراتور، و درست: استدلالِ قدیمی فقط برای DNSِ افقِ‌تقسیم‌شده صادق بود، در حالی که نامی که برای ما NXDOMAIN است و پروکسی حلش می‌کند از درِ ورودی رد می‌شد — همان دری که در حالتِ پروکسی **تنها** دفاع است). **PySocks هم در همین استقرار آمد:** yt-dlp socksِ خودش را دارد ولی gallery-dl روی `requests` است و بدونِ PySocks خطای «Missing dependencies for SOCKS support» می‌دهد — و gallery-dl همان چیزی است که **اینستاگرام** را می‌کشد، یعنی دقیقاً هدفِ خروجیِ موبایل. **تست‌ها (۲۲۸ → ۲۴۲):** مسیرِ socks با یک **سرورِ SOCKS5ِ واقعیِ درون‌پروسه‌ای** سنجیده می‌شود که خودش پروتکل را حرف می‌زند و مقصدِ خواسته‌شده را ثبت می‌کند — همان ثبت اثبات می‌کند ترافیک واقعاً از پروکسی رد شده، نه اینکه صرفاً دانلود موفق بوده. **عمداً ماکِ کانکتور نه**، چون درسِ همین هفته این بود که ماک شکلِ کتابخانهٔ بیرونی را پنهان می‌کند. تنها چیزی که ماک می‌شود `_addr_is_internal` است (الگوی موجودِ `test_ssrf`) تا سرورِ ۱۲۷٫۰٫۰٫۱ قابلِ تست باشد. روی سورسِ پیش از رفع ۶ از ۱۱ تست fail می‌شود. **دو تستِ قدیمی عمداً عوض شدند** چون رفتارِ پین‌شده‌شان همان باگ بود: «socks رزولور را نگه می‌دارد» و «شکستِ DNS با پروکسی مجاز است». **اعمال:** `downloader.py` روی نودِ دانلود و `requirements-worker-dl.txt` عوض شده → `telabzar update` روی مستر **و** `node/update.sh` روی نودِ دانلود (rebuildِ ایمیج لازم است).
- 2026-08-12 — **دو باگِ کاربر-محور از یک علتِ ریشه‌ای: ترتیبِ آرگومانِ `edit_message_text`.** اسموکِ ۳پ روی سرور نشان داد ویدیوی ۱٫۵ گیگی یک دقیقه روی «در حالِ بررسی…» می‌ماند و متن **هیچ‌وقت** عوض نمی‌شود. علت با اثباتِ محلی پیدا شد نه حدس: پارامترِ **دومِ** `Bot.edit_message_text` در aiogram `business_connection_id` است نه `chat_id`، پس فرمِ موضعیِ `(text, chat_id, mid)` مقدارِ `chat_id` را در `business_connection_id` می‌گذارد و **پیش از هر I/O شبکه‌ای** `ValidationError` می‌دهد — که هر دو محلِ فراخوانی داخلِ `except Exception` می‌بلعیدند. **باگِ مهم‌ترْ مالِ من نبود و ~۳ هفته زنده بود** (`22bd5c7`): پیامِ «محتوای غیرمجاز» هم با همین فرم فرستاده می‌شد، پس ویرایش می‌ترکید، `except` یادداشت را پاک می‌کرد، و شاخهٔ `else` هم اجرا نمی‌شد چون `note_mid` وجود دارد — یعنی **هر آپلودی که فیلتر ردش می‌کرد بی‌صدا ناپدید می‌شد و کاربر هیچ توضیحی نمی‌گرفت**. حالا ویرایش fallback به `send_message` دارد. **چرا فقط این دو متد:** `edit_message_text` و `edit_message_caption` تنها متدهایی‌اند که `business_connection_id` را قبل از `chat_id` دارند؛ `send_message`/`delete_message`/`send_*` همه شهودی‌اند و همین ناهماهنگی چشم را رد می‌کند. **چرا CI سبز بود — و درسِ اصلیِ این کار:** `FakeBot` امضای **خودش** را تعریف کرده بود و فراخوانیِ موضعی را می‌پذیرفت، یعنی ماک شکلِ API را پنهان کرد. جنسِ تازه‌ای از vacuous شدن که در دو موردِ قبلی ندیده بودیم. `tests/aiogram_double.py` حالا آرگومان‌ها را با امضای خودِ `aiogram.Bot` bind و همان مدلی را می‌سازد که aiogram می‌ساخت، پس pydantic واقعاً اعتبارسنجی می‌کند؛ **هر سه** `FakeBot`ِ ریپو رویش رفتند (دوتای دیگر هم همان امضای غلط را می‌پذیرفتند، هرچند مسیرشان با kwarg صدا زده می‌شد). به‌علاوهٔ گاردِ ASTی که متدهای تله‌دار را از امضای خودِ `Bot` **کشف** می‌کند نه از فهرستِ دستی. **تست‌ها (۲۲۳ → ۲۲۸):** روی کدِ مستقر، ۴ تستِ فازِ غربالگری + ۲ تستِ تازهٔ پیامِ رد + گاردِ AST fail می‌شوند — و آن ۴ تا **قبلاً روی همین کد سبز بودند**، که خودش اثباتِ رفعِ ماک است. **اعمال:** `tasks.py` روی مستر و نودِ پردازش → `telabzar update` + `node/update.sh`.
- 2026-08-11 — **فاز ۳پ: دو نیمه از سقفِ ظرفیتِ غربالگری — بارگذاریِ مدل و سکوتِ انتظار.** **(۱۲ warm-upِ NudeNet)** بارگذاری ~۸۱ مگابایت و چند ثانیه است و تا امروز روی **اولین** فایلی که کاربر می‌فرستد اتفاق می‌افتاد، یعنی بدترین لحظهٔ ممکن: درست بعد از هر `telabzar update`. حالا `worker._warm_safety_model` سرِ استارت در پس‌زمینه بارش می‌کند. **یک کشفِ ساختاری کار را ساده کرد:** هم `startup_dl` هم `startup_master` خودشان `await startup(ctx)` می‌زنند، پس یک تغییر در `startup` هر چهار نوع ورکر را می‌گیرد. **سه قید، هرکدام با دلیل:** گیت روی `safety_enabled` + `safety_scan_pixels` (وگرنه ۸۱ مگابایت برای قابلیتِ خاموش)؛ **داخلِ `asyncio.to_thread`** چون `_get_detector` **همگام** است و صداکردنش روی حلقهٔ رویداد یعنی startup را مسدود نکرده‌ایم ولی کلِ ورکر را تا پایانِ بارگذاری کر کرده‌ایم — قیدی که در پلن نبود و سرِ طراحی اضافه شد؛ و **ردشدن روی نودِ پردازش** چون آن‌جا اثباتاً اسکن نمی‌شود (`run_screen` بدونِ `_queue_name` صف می‌شود پس به `arq:queue:proc` نمی‌رسد، و `run_op` هیچ مسیری به safety ندارد). **قفلِ #۸۹ پیش‌نیازِ این کار است نه جانبیِ آن:** warm-upِ پس‌زمینه‌ای احتمالِ ساختِ هم‌زمان را **بیشتر** می‌کند، و تست همین را می‌سنجد (warm-up + دو جابِ هم‌زمان → دقیقاً یک ساخت). **(۱۳الف برچسبِ فاز)** یادداشتِ «در حالِ بررسی» یک‌بار فرستاده می‌شد و تا پایان دست‌نخورده می‌ماند — روی ویدیوی بزرگ تا ~۹۴ ثانیه سکوت. حالا ticker فازِ جاری (دریافت/بررسی) + ثانیهٔ سپری‌شده را می‌نویسد. **درصد و شمارندهٔ فریم عمداً ساخته نشد،** چون تقسیمِ زمان (۱۰٫۳ / ۱٫۱ / ۰٫۳) می‌گوید کار یک انتظارِ شبکه است و درصدِ ساختگی چیزی نمی‌گوید. **و ticker با تأخیر شروع می‌شود (`_SCREEN_NOTE_DELAY=4`)، که تصمیمِ اپراتور بود و درست بود:** غربالگریِ فایلِ کوچک ~۱٫۴ ثانیه است، پس شروعِ بی‌تأخیر یعنی اکثریتِ مطلقِ آپلودها یک ویرایشِ بی‌فایده می‌گیرند و رگبارِ آلبوم به سقفِ نرخِ تلگرام نزدیک می‌شود. بستنِ ticker با `P.stop_task` است (درسِ ۲-۷) و `rmtree` **قبل** از آن، چون `stop_task` می‌تواند لغوِ خودِ جاب را بالا بدهد. **تصحیحِ یک کامنتِ جامانده:** `routers/files.py` هنوز می‌گفت کارت یعنی «آپلودِ دوباره» — همان جمله‌ای که ۲۰۲۶-۰۸-۱۰ در `tasks.py` و §۷ تصحیح شد ولی این نسخه‌اش جا مانده بود. **تست‌ها (۲۰۴ → ۲۲۳):** ۹ تستِ warm-up + ۱۰ تستِ برچسبِ فاز. روی سورسِ پیش از رفع ۹ + ۵ تا fail می‌شوند. **یک تصحیحِ روشِ خودم:** نسخهٔ اولِ فیکسچر با `monkeypatch.setattr` روی ثابت‌هایی که پیش از رفع وجود ندارند، باعث می‌شد تست‌ها با `AttributeError` سرِ **setup** بیفتند — یعنی «نبودِ صفت» را نشان می‌داد نه شکافِ رفتاری را؛ با `raising=False` نسخهٔ قدیمی واقعاً اجرا می‌شود و روی ادعای درست می‌افتد («کارِ کند هیچ بازخوردی نمی‌دهد»). پنج تستی که هر دو طرف سبزند کنترل‌اند، از جمله «سریع = صفر ویرایش» که گاردِ **ضدِ پرحرفیِ کدِ جدید** است نه اثباتِ قابلیت. **۱۳ب (گیتِ صف) عمداً انجام نشد** — تصمیمِ ظرفیت است و در Open Questions با تداخلش با ۱۲ (ورکرِ اختصاصی = نسخهٔ دومِ ۸۱ مگابایتیِ مدل) ثبت شد. **اعمال:** `worker.py`/`safety.py` روی مستر و نودِ دانلود، `tasks.py` روی نودِ پردازش → `telabzar update` + `node/update.sh` روی هر دو نوع نود.
- 2026-08-11 — **حذفِ opِ مردهٔ `thumb`** (کارِ جدا، بعد از فاز ۳ب). گاردِ موردِ ۸ پیدایش کرده بود و تصمیمِ محصولی می‌خواست. **مقایسه‌ای که تصمیم را ساخت و حدسِ اولیه را رد کرد:** `thumb` تکرارِ دکمهٔ **کاور** نبود — جهتشان عکسِ هم است (`cover` عکسی را که کاربر می‌فرستد می‌گیرد و `file.cover_id` را ست می‌کند، کاملاً در روتر و بدونِ جاب؛ `thumb` یک JPG از **دلِ** ویدیو بیرون می‌داد). همپوشانیِ واقعی با **`screenshot`** بود که دقیقاً همان `{"send_media": {"as": "photo"}}` را برمی‌گرداند و تنها تفاوتش انتخابِ فریم بود: زمانِ انتخابیِ کاربر در برابرِ فریمِ نمایندهٔ خودکارِ فیلترِ `thumbnail`. با منوی ویدیو که از قبل ۱۱ دکمه دارد، صرفه‌جوییِ دو تپ ارزشِ دکمهٔ دوازدهم را نداشت. **حذف‌شده‌ها:** شاخهٔ `_do_op`، ورودیِ `OFFLOAD_OPS`، `btn_thumb`/`cl_thumb` در دو زبان، و `processing.video_thumbnail` که تنها فراخوانش همان شاخه بود (مثلِ `make_zip` در ۳الف). نیازِ داخلی دست‌نخورده می‌ماند چون `video_poster` همان فیلترِ `thumbnail` را در ≤۳۲۰px دارد. `_KNOWN_UNREACHABLE` تهی شد و **در همان کامیت**، چون گارد دوطرفه است. تعدادِ تست ثابت (۲۰۴) — چیزی اضافه نشد، ولی با سابوتاژ (افزودنِ دوبارهٔ یک هندلرِ بی‌دکمه) تأیید شد که گارد با فهرستِ تهی هنوز می‌گیرد. پاریتیِ locale سنجیده شد: ۲۱۰ → ۲۰۸ کلید، صفر اختلاف. **اعمال:** `tasks.py`/`processing.py`/`nodes.py` روی نودِ پردازش هم می‌دوند → `telabzar update` + `node/update.sh`؛ رفتارِ کاربر عوض نمی‌شود چون این مسیر از ابتدا در دسترس نبود.
- 2026-08-11 — **فاز ۳ب: تنها باگِ درستیِ فاز ۳، و سه یافته در یک تابعِ دانلود.** **(۱ رقابت در `collect_recv`)** چکِ سقفِ حجم روی `data`ی بالای تابع کار می‌کرد ولی افزودنِ عضو داخلِ قفل بود، و بینشان `await _vjoin_cap_mb()` — یک نقطهٔ yieldِ واقعی — قرار داشت. پس دو آپلودِ هم‌زمانِ یک آلبوم (که aiogram موازی هندل می‌کند) هر دو از چک رد می‌شدند و سقف به‌اندازهٔ «تعدادِ آپلودِ هم‌زمان منهای یک» می‌شکست. ناحیهٔ بحرانی کامل شد: خواندنِ اعضا → چک → افزودن → نوشتن → ویرایشِ کارت، همه داخلِ قفل. **خواندنِ خودِ عددِ سقف عمداً بیرون ماند** — خواندنِ تنظیمات است نه حالتِ مشترک، و بردنش به داخل یک رفت‌وبرگشتِ Redis را وسطِ ناحیهٔ بحرانی می‌گذاشت؛ کهنه‌بودنِ یک‌لحظه‌ایِ عدد بی‌ضرر است، آنچه باید اتمی باشد مقایسه‌اش با فهرستِ اعضاست. **باگِ دومِ هم‌ریشه** هم بسته شد: ویرایشِ کپشن بیرونِ قفل بود، پس دو هندلر می‌توانستند جابه‌جا تمام شوند و کارتْ کمتر از آنچه ثبت شده نشان دهد. **(۳ طوفانِ EXISTS)** `_run_dl` روی هر خطِ stdout یک `redis.exists` می‌زد و yt-dlp با `--newline` و `--concurrent-fragments 4` ده‌ها خط در ثانیه می‌دهد — روی نودِ دانلود هرکدام یک رفت‌وبرگشتِ WireGuard. طبقِ تصمیمِ اپراتور مکانیزمِ دوم ساخته نشد: ناظرِ `_CANCEL_POLL`ِ `processing` به `start_cancel_watcher`/`CancelWatch` استخراج شد و **هر دو** زیرفرایند از همان استفاده می‌کنند؛ importِ `downloader` عمداً تنبل ماند (مثلِ `_ffprobe_video`). **دو یافتهٔ دیگر در همان تابع، که همان بازآرایی هر دو را بست:** دانلودِ **گیرکرده** اصلاً لغو نمی‌شد (بدونِ خطِ خروجی، `async for` بلاک است و چک هرگز اجرا نمی‌شد — دکمهٔ لغو تا تایم‌اوتِ ۳۰۰۰ ثانیه‌ای بی‌اثر بود)، و `_run_dl` باگِ یتیمِ ۲-۲ را داشت و رفع نشده بود. **یتیمِ yt-dlp از نسخهٔ ffmpegش بدتر است و صریح ثبت شد:** به دانلود **ادامه می‌دهد**، یعنی سهمیهٔ همان اکانتِ کوکی را می‌سوزاند و سشن را در معرض می‌گذارد — و چون جابِ صاحبش مرده، `mark_ok`/`mark_fail`/`note_spend` هیچ‌کدام صدا زده نمی‌شوند و **هیچ‌جا ثبت نمی‌شود**. **تست‌ها (۱۹۳ → ۲۰۴):** ۵ تستِ رقابت + ۶ تستِ لغو. **قطعی‌اند نه زمان‌محور:** تستِ رقابت یک `asyncio.Barrier` دقیقاً روی همان `await`ی می‌گذارد که باگ پشتش زندگی می‌کند، و تستِ ترتیبِ کپشن با تأخیر روی **اولین** ویرایش کار می‌کند (بیرونِ قفل، بعدی‌ها از اولی جلو می‌زنند و کپشنِ کهنه آخر می‌نشیند؛ داخلِ قفل این ترتیب ممکن نیست). روی سورسِ پیش از رفع: ۳ از ۵ تستِ رقابت و ۳ از ۶ تستِ لغو fail می‌شوند؛ بقیه کنترل‌اند و باید هر دو طرف سبز باشند. **درسِ vacuousِ ۳الف این‌جا هم اعمال شد:** تستِ یتیم فرایندی می‌سازد که خودش تمام‌شدنی نیست و روی دیسک می‌نویسد، پس «کارِ ادامه‌دار» مستقیم دیده می‌شود. **اعمال:** `routers/ops.py` روی ربات → `telabzar update` روی مستر؛ `downloader.py` روی نودِ دانلود و `processing.py` روی نودِ پردازش → `node/update.sh` روی هر دو نوع نود.
- 2026-08-11 — **فاز ۳الف: چهار موردِ بهداشتی + رفعِ یک تستِ flaky — و دو یافته که خودِ همین کار بیرون داد.** **(۶ `x.db`)** از PR #41 tracked بود؛ بررسی شد که خالی است (`users/files/jobs/download_cache` صفر ردیف، `settings` یک ردیفِ `downloader_enabled=on`)، **نه رازی نه دادهٔ کاربری**، و هیچ کدی ارجاعش نمی‌دهد → `git rm --cached` + الگوی `*.db` در `.gitignore`. بازنویسیِ تاریخچه عمداً نه (بی‌تناسب، چون رازی در کار نیست). **(۷ `.env.example`)** در **هر دو** جهت کهنه بود: یازده کلید داشت در برابرِ ۹۵ فیلدِ `Settings`. جهتِ رفت — `WEBHOOK_SECRET` صفر ارجاع در کلِ ریپو (بازماندهٔ طرحِ webhook؛ خودِ `install.sh:126` می‌گوید ربات long-polling است) و `DOMAIN` هم از `.env` خوانده نمی‌شود. **تفکیکی که مهم بود و اول از قلم افتاده بود:** `DOMAIN` در خودِ `install.sh` **زنده** است (`:81,84,87,127` → ساختِ `PUBLIC_BASE` و مسیرِ سرتیفیکیت)، پس فقط نوشتنش در `.env` حذف شد نه پرسیدنش — حذفِ کورکورانه نصب را می‌شکست. جهتِ برگشت — همان سه‌تایی که اپراتور گفت (`PROXY_URL`/`ADMIN_SECRET`/`NODE_SECRET`) به‌علاوهٔ `PUBLIC_BASE`/`TLS_*`/`GATEWAY_HTTPS_PORT` و بلوکِ WG/NODE با برچسبِ «دستی ننویس». **(۸ شاخهٔ مردهٔ `zip`)** مجموعهٔ کاملِ opهای صف‌شدنی شمرده شد: `zip` فقط به `op_zip_start` می‌رود که فلوِ FSM است، و `op_collect_go` (`ops.py:687-688`) همیشه `zip_many` را صف می‌کند → `tasks.py:261-264` و تنها فراخوانش `processing.make_zip` هر دو حذف شدند (+ رشتهٔ یتیمِ `cl_zip` از دو زبان). **(۹ نحوِ Postgres-only)** طبقِ توافق فقط مستندسازی: SQLite روی `ALTER … ADD COLUMN IF NOT EXISTS` خطای نحوی می‌دهد (سنجیده شد) ولی `init_models()` فقط از دو نقطهٔ تولیدی صدا زده می‌شود، پس **باگِ فعال نیست**. **یافتهٔ الف (جدی‌تر از خودِ موردِ ۹، در Open Questions):** هیچ تستی `init_models()` را صدا نمی‌زند، پس یک غلطِ تایپی در مهاجرتِ بعدی تا لحظهٔ استقرار پنهان می‌ماند — گزینه‌اش سرویسِ Postgres در CI است؛ فقط ثبت شد. **یافتهٔ ب:** گاردِ تازه یک opِ مردهٔ **دوم** پیدا کرد — `thumb` هندلر دارد و در `OFFLOAD_OPS` هست و هر دو زبان رشته‌اش را دارند، ولی در `keyboards` دکمه‌ای ندارد؛ چون شکلِ **قابلیتِ نیمه‌تمام** را دارد نه بازمانده، حذف نشد و به‌عنوان تنها ورودیِ مستندِ `_KNOWN_UNREACHABLE` ثبت شد تا تصمیمِ محصولی گرفته شود. **(تستِ flaky)** `test_orphan_process` این‌جا ۴ از ۵ اجرا می‌افتاد. علت اندازه‌گیری شد نه حدس: `pgrep -x` **زامبی** را هم می‌شمارد و بلافاصله بعد از لغو حالتِ فرایند `Zl` است (۱۵۰ms بعد صفر) — یعنی رفعِ ۲-۲ درست است و ادعای «zombieِ لحظه‌ای مهم نیست» تجربی تأیید شد. هر دو نیمه رفع شد: شمارش زامبی را کنار می‌گذارد، **و** `test_cancellation_still_propagates` مثلِ همسایه‌هایش منتظرِ فرایندِ خودش می‌ماند (وگرنه بعدِ خودش را تمیز نمی‌کرد و جای دیگر می‌زد). **و یک تستِ خودم که vacuous شد و سابوتاژ گرفتش:** وقتی مهلتِ انتظار را از ۲ به ۵ ثانیه بردم، تست‌ها با سورسِ **سابوتاژشده** هم سبز ماندند — چون انکودِ ۳۰ثانیه‌ای ۵٫۵ ثانیه طول می‌کشد و حدودِ ۴ ثانیه بعد از لغو **خودش** تمام می‌شد، پس «صفر شد» را می‌دیدم بی‌آنکه کشتنی رخ داده باشد. آن مرزِ ۲ ثانیه‌ای شانسی بود، نه طراحی. حالا ورودیِ lavfi **بدونِ `duration`** است، یعنی فرایند خودبه‌خود تمام‌شدنی نیست و «صفر شد» فقط می‌تواند یعنی کشته شد؛ ضمناً ساختِ منبع حذف شد و این ماژول از ۱۱٫۶ به ۳٫۵ ثانیه رسید. **تست‌ها (۱۸۴ → ۱۹۳):** نُه گاردِ تازه، و **هر نُه‌تا با خراب‌کردنِ عمدیِ حالت راستی‌آزمایی شدند** (x.db به index برگردانده شد، `*.db` از gitignore، `DOMAIN` به نمونه و به heredocِ installer، `BOT_TOKEN`/`PROXY_URL` از نمونه، شاخهٔ `zip` و `make_zip` برگردانده شدند، و `thumb` قابلِ‌دسترس شد) — همه طبقِ انتظار fail شدند. گاردها کشف‌محورند نه فهرست‌دستی، و تحلیلگرِ AST خودش ضدِ vacuous چک دارد. **موردِ ۲ won't-fix ثبت شد** با اثباتِ سیمِ پروتکل. **اعمال:** موارد ۶ و ۷ فقط ریپو/نصبِ تازه‌اند؛ ۹ و موردِ ۲ فقط مستنداتند؛ موردِ ۸ کدِ مرده است پس رفتاری عوض نمی‌شود ولی `tasks.py`/`processing.py` روی نودِ پردازش هم می‌دوند و با `telabzar update` + `node/update.sh`ِ بعدیِ عادی می‌آیند — استقرارِ فوری لازم نیست.
- 2026-08-10 — **فاز ۲پ (بخشِ اول): دو باگِ لغو.** **(۲-۲ پروسهٔ یتیم)** `_run` روی دکمهٔ لغو و روی تایم‌اوت ffmpeg را می‌کشت، ولی روی `CancelledError` — یعنی `job_timeout`ِ ARQ یا خاموشیِ ورکر — فقط ناظر را می‌بست و فرایند زنده می‌ماند. بازتولید شد: بعد از `task.cancel()` یک ffmpeg باقی می‌ماند (`assert 1 == 0` روی سورسِ پیش از رفع، در **هر دو** شاخهٔ `_run`). شاخهٔ `except BaseException` می‌کُشد و دوباره raise می‌کند؛ عمداً `await proc.wait()` نمی‌زند چون در مسیرِ لغو خودِ آن await می‌تواند دوباره `CancelledError` بگیرد و رفع را بی‌اثر کند. **(۲-۷ بلعیدنِ لغو)** `await ticker` بعد از `ticker.cancel()` دو دلیلِ تفکیک‌ناپذیر دارد و هر دو محل هر دو را می‌بلعیدند. **اندازه‌گیری خوانشِ اولم را تصحیح کرد:** در حالتِ رایج (لغو وسطِ خودِ کار) فرمِ قبلی هم درست propagate می‌کرد؛ گم‌شدن فقط وقتی است که لغو **حین انتظار برای ticker** برسد — پنجره‌ای واقعی، چون ticker هر چند ثانیه یک فراخوانیِ HTTP می‌زند و سرِ خاموشی همهٔ جاب‌ها هم‌زمان داخلِ آن‌اند. `processing.stop_task()` با `Task.cancelling()` تفکیک می‌کند؛ `gather(return_exceptions=True)` و «cancel بدونِ await» هر دو امتحان و رد شدند (هر دو می‌بلعند). **یک تستِ خودم که مثبتِ کاذب داد:** نسخهٔ اولِ تستِ ساختاری با تطبیقِ رشته **کامنتِ خودم** را که عبارتِ `except BaseException` داشت می‌گرفت؛ حالا با AST هندلرها خوانده می‌شوند. **تست‌ها (۱۷۴ → ۱۸۴):** ۲-۲ چهار تست (دو تا pre-fix fail)، ۲-۷ شش تست (دو تا pre-fix fail). **۲-۶ عمداً انجام نشد** — دلیلش در Open Questions. **اعمال:** `processing`/`tasks` روی نودِ پردازش و `tasks_download` روی نودِ دانلود اجرا می‌شوند → `telabzar update` روی مستر و `node/update.sh` روی هر نود.
- 2026-08-10 — **تثبیتِ «غربالگری سرِ آپلود می‌ماند» + تصحیحِ مکانیزمِ ریسک + دو یافتهٔ ثبت‌شده.** تصمیمِ اپراتور: غربالگری **موکول نمی‌شود**؛ استدلال، انتساب است — در مقیاسِ بزرگ کسی چیزی آپلود می‌کند که نباید، و ربات پیش از دانستنِ محتوا آن را زیرِ نامِ خودش بازفرستاده. **تصحیحِ متن (مهم چون آیندگان روی آن تصمیم می‌گیرند):** هم `tasks.py` هم §۷ می‌گفتند کارت یعنی «آپلودِ دوباره» — غلط است: کارت با **`file_id`** می‌رود (`cards.py:188`)، تلگرام سمتِ خودش کپی می‌کند و هیچ بایتی آپلود نمی‌شود. ریسک از بین نمی‌رود ولی شکلش عوض می‌شود (انتساب، نه پهنای‌باند) و دو پیامد دارد: هزینهٔ غربالگری **دانلود** است نه آپلود (چرا I/O-bound است)، و ریسک در چتِ خصوصی بسیار کمتر از گروه است — تفکیکی که نه کد می‌کرد نه مستند. **یافتهٔ ۱ — `op_link`:** تنها مسیرِ واقعیِ بازتوزیع به شخصِ ثالث و تنها opی که **بایت لازم ندارد** (`ops.py:913-916`: توکن می‌سازد و commit می‌کند، بدونِ `_localize` و بدونِ جاب). هر قاعدهٔ آینده به شکلِ «وقتی بایت لازم شد غربال کن» از کنارش کور رد می‌شود. **یافتهٔ ۲ — چتِ خصوصی:** هیچ فیلترِ نوعِ چتی در کلِ `app/` نیست؛ کد فرضش را دارد ولی اعمالش نمی‌کند (`files.py:82-84` و `ops.py:532,603,757,773` با کامنتِ «در چتِ خصوصی مجاز است»). محافظت **کاملاً بیرونِ ریپو** است: privacy modeِ ربات روشن است (تأییدِ اپراتور با BotFather)، ولی **با ادمین‌شدنِ ربات در گروه دور زده می‌شود** — آن‌وقت آپلودِ گروه به ربات می‌رسد و آن `message.delete()` هم موفق می‌شود، پس نسخهٔ ربات تنها نسخهٔ دیدنی می‌ماند. **اعمال:** فقط مستندات و یک داکس‌استرینگ — هیچ رفتارِ اجرایی عوض نشده.
- 2026-08-10 — **قفلِ بارگذاریِ مدلِ NudeNet + ثبتِ سقفِ ظرفیتِ غربالگری.** ریشهٔ «در حال بررسی»‌ماندنِ طولانی پیدا شد و **باگ نیست**: `run_screen` است و اندازه‌گیری روی ویدیوی ۱۹۸ مگابایتی نشان داد **`get_file` ۱۰٫۳ ثانیه، استخراجِ فریم ۱٫۱، استنتاج ۰٫۳** — یعنی ~۸۸٪ یک واکشیِ شبکه است و خودِ اسکن ~۱٫۴ ثانیه و تقریباً ثابت. **پس هزینه I/O است نه CPU** و این تفاوت درمان را عوض می‌کند: ورکر منتظرِ شبکه است ولی یکی از چهار اسلاتِ `max_jobs` را گرفته، و آن‌ها **همان** اسلات‌های `run_op`اند. **باگی که سرِ همین بررسی پیدا شد و رفع شد:** `_get_detector()` قفل نداشت و از **thread** صدا زده می‌شود (`_detect_sync` داخلِ `asyncio.to_thread`)، پس روی ورکرِ تازه‌ری‌استارت‌شده تا چهار جابِ هم‌زمان می‌توانستند چهار `NudeDetector` بسازند — هرکدام **~۸۱ مگابایت** (اندازه‌گیری‌شده: ۱۱→۹۲) که سه‌تایش بلافاصله زباله می‌شد؛ و این دقیقاً بعد از هر `telabzar update` محتمل‌ترین است. حالا double-checked locking: مسیرِ داغ بعد از بارگذاری اصلاً قفل نمی‌گیرد. **تأییدِ «آیا فایل دوبار دانلود می‌شود؟» — نه.** `_localize` روی مستر مسیرِ دیسکِ مشترک را برمی‌گرداند (`tasks.py:122`، حجمِ `tg-bot-api-data` با `:ro` روی ورکر سوار است)، پس نه کپی می‌شود نه دوباره منتقل؛ آن ۱۰٫۳ ثانیه واکشیِ **سرورِ Bot APIِ محلی** از DCِ تلگرام است و بارِ دوم از دیسکِ خودش می‌آید. معماری روی همین بنا شده: گیت‌وی هم `get_file` می‌زند و بعد همان مسیر را با `os.path.exists` می‌خواند و کشِ ۱۲۰ ثانیه‌ای دارد (`gateway.py:41-49`) — اگر هر `getFile` دوباره ۱۹۸ مگابایت می‌کشید، جلو-عقب‌بردنِ ویدیو غیرقابلِ‌استفاده بود. **تست‌ها (۱۷۰ → ۱۷۴):** روی سورسِ پیش از رفع ۳ از ۴ تست fail می‌شود (چهارمی مسیرِ شکستِ تک‌threadی است که از قبل درست بود). `nudenet` در محیطِ تست نصب نیست، پس سازنده وصله می‌خورد — چیزی که سنجیده می‌شود قاعدهٔ «یک‌بار» است نه خودِ مدل. **اعمال:** `safety` روی ورکرِ اصلی **و** ورکرِ دانلود اجرا می‌شود → `telabzar update` روی مستر و `node/update.sh` روی نودِ دانلود.
- 2026-08-10 — **فاز ۲ب: سه باگِ مسیرِ رسانه + اولین تست‌های واقعیِ ffmpeg.** **(۲-۳ سیکِ برش)** `trim_video` سیکِ خروجی داشت و `trim_audio` ورودی. اندازه‌گیریِ واقعی روی منبعِ ۱۸۰ثانیه‌ای، برشِ [۱۷۰،۱۷۴]: **۱٫۴۷ → ۰٫۳۰ ثانیه**، و فریمِ اولِ خروجی **بیت‌به‌بیت یکی** (PSNR = `inf`) — پس دقت از دست نمی‌رود، چون ffmpeg از کی‌فریمِ پیش از `start` دیکود می‌کند و اضافه‌ها را دور می‌ریزد. **تلهٔ اصلی:** جابه‌جاکردنِ فقط `-ss` از نکردنِ رفع بدتر است — با سیکِ ورودی تایم‌استمپ‌ها صفر می‌شوند و `-to`ی که بعدِ `-i` مانده گزینهٔ **خروجی** می‌شود، پس برشِ [۳،۷] به‌جای ۴ ثانیه **۷ ثانیه** می‌دهد؛ تجربی سنجیده شد. **(۲-۴ لغو)** چکِ لغو داخلِ خوانندهٔ `-progress` بود و `use_prog` هر دو `progress` و `duration` را می‌خواهد، پس هر فراخوانیِ بدونشان تا آخر می‌رفت — از جمله حلقهٔ نرمال‌سازیِ `concat_videos` که طولانی‌ترین بخشِ کار است. حالا ناظرِ جدا در **هر دو** شاخه و کنسل در `finally`. رفعِ `_run` به‌تنهایی کافی نبود: `mute_video` و `write_audio_metadata` اصلاً `cancel` نمی‌گرفتند. **(۲-۵ fallback)** `except RuntimeError` تایم‌اوت را هم می‌گرفت، پس nvencِ تایم‌اوت‌شده یک انکودِ **کاملِ** دیگر با x264 راه می‌انداخت و مجموع از `job_timeout` رد می‌شد؛ `ProcessingTimeout` (زیرکلاسِ RuntimeError تا هیچ `except`ِ دیگری عوض نشود) قبل از شاخهٔ fallback دوباره raise می‌شود — در **دو** تابع، نه یکی. **CI:** `ubuntu-latest` ffmpeg **ندارد** (در فهرستِ رسمیِ runner-images نیست، بررسی شد)، پس صریح نصب می‌شود + گامِ `ffmpeg -version` تا خودِ اجرا حضورش را ثابت کند نه READMEی رانر. **تست‌ها (۱۵۵ → ۱۷۰):** مارکر **per-test** است نه سطحِ ماژول، چون تست‌های ۲-۵ با `_run`ِ وصله‌خورده کار می‌کنند و نباید با نبودِ ffmpeg بی‌صدا skip شوند. اثباتِ pre-fix **جدا برای هر مورد** گرفته شد (نه یک revertِ کلی): ۲-۴ دو تست، ۲-۵ دو تست، ۲-۳ تستِ ساختاری. **دو اشتباهِ خودم که همین‌جا گرفته شد و ارزشِ ثبت دارد:** (۱) اولین اثباتِ pre-fixِ ۲-۳ **بی‌اعتبار** بود — چون بعد از رفع، **قطعهٔ سیکِ** هر دو تابع یکی شد (`"-ss", f"{start}", "-to", f"{end}", "-i", inp`، دو بار در فایل؛ خطِ فرمانِ کاملشان همچنان فرق دارد — تصحیحِ ۲۰۲۶-۰۸-۱۴، کد حقیقت است) و `trim_audio` جلوتر از `trim_video` است، پس `replace(..., 1)`ِ من سراغِ آن رفت؛ افزودنِ `assert count==1` گرفتش، و درسش این است که سابوتاژ هم مثلِ تست باید ادعایش را چک کند. (۲) گامِ CIی که برای «مارکر بی‌اثر نشود» نوشتم کار نمی‌کرد: با صفر تستِ نشان‌دار `pytest -m ffmpeg` همه را deselect می‌کند و با کدِ **صفر** خارج می‌شود (کدِ ۵ فقط برای «هیچ‌چیز جمع نشد» است)؛ نگهبان به یک **تست** تبدیل شد که با حذفِ مارکرها واقعاً fail می‌شود. **اعمال:** `processing`/`tasks` روی نودِ پردازش هم اجرا می‌شوند → `telabzar update` روی مستر و `node/update.sh` روی نود.
- 2026-08-10 — **فاز ۲الف: پنج موردِ ممیزی — سه‌تا باگ بودند، یکی نبود، یکی نه به آن شکل.** **(۲-۱ مالکیت، باگِ واقعی)** هیچ‌جای `routers/ops.py` `owner_id` سنجیده نمی‌شد؛ ۴۱ فراخوانیِ `get_file_by_ref` فقط به `ref` اعتماد می‌کردند. قاعده به **داخلِ خودِ lookup** رفت (`crud.get_file_by_ref(session, ref, user)`) نه به ۴۱ هندلر، و دو چیز باعث شد این کار تمیز دربیاید: هر هندلر از قبل `file is None` را مدیریت می‌کرد، پس **مسیرِ ردِ درخواست در همه‌جا از قبل درست بود** و صفر شاخهٔ تازه لازم شد؛ و `user` پارامترِ **اجباری** است که `None`اش یعنی **رد** نه «بدونِ بررسی» — پیش‌فرضِ `None` یک آرگومانِ فراموش‌شده را به دور زدنِ خاموشِ مجوز تبدیل می‌کرد، یعنی دقیقاً همان چیزی که این فاز برای بستنش بود (تستِ جدا همین را قفل می‌کند). **حدس‌ناپذیریِ `ref` هیچ‌وقت دفاع نبود:** ۸ کاراکترِ تصادفی است، ولی هر نشتی (لاگ/فوروارد/گروه) کلِ عملیاتِ فایل را باز می‌کرد از جمله `op_link` که لینکِ عمومی می‌سازد. **و یک مسیر اصلاً حدس نمی‌خواست:** `op_cancel_job` شناسهٔ **ترتیبیِ** `Job.id` را می‌گرفت — شمردنِ ۱،۲،۳… جابِ دیگران را لغو می‌کرد؛ حالا از `Job.file_id → File.owner_id` می‌سنجد. **(۲-۸ zip-slip — باگ نیست)** با همان دستورِ دقیقِ `processing.py` چهار بردار روی 7-Zip 23.01 **واقعاً اجرا شد**: `../../x` داخل ماند، مسیرِ مطلق بازپایه شد، و symlinkِ داخلِ zip و tar هر دو به **دایرکتوریِ ساده** تبدیل شدند و فایلِ هدف دست‌نخورده ماند. ضمناً گارد **بعد از** استخراج است پس اصلاً نمی‌تواند از نوشتن جلوگیری کند — فقط فهرست را فیلتر می‌کند. پس امنیتِ واقعی به خودِ 7z بند است و تست حالا همان رفتار را **پین** می‌کند تا تعویضِ باینری/رفتن به `zipfile` بی‌صدا نماند. **ولی یک ایرادِ واقعی در گارد بود:** `startswith(real_ex)` پیشوندِ **رشته‌ای** است و `<outdir>/exfil` را داخلِ `<outdir>/ex` می‌شمرد؛ حالا با `real_ex + os.sep` مرزِ مسیر سنجیده می‌شود. **(۲-۹ راز در query string)** `/node/peers` دیگر `?key=` را نمی‌پذیرد و فقط `X-Node-Key` را می‌خواند (که از قبل پشتیبانی می‌شد). **تصحیحِ مقدمه:** `node/install.sh` این کلید را **نمی‌فرستد** و اصلاً این endpoint را صدا نمی‌زند — فقط توکنِ یک‌بارمصرف را در **بدنهٔ** `POST /node/join` می‌گذارد؛ تنها کلاینت `node/wg-sync.sh` است. هر دو طرف در یک کامیت عوض شدند، چون بستنِ فقط سمتِ سرور یعنی دفعهٔ بعد که نودی اضافه شود peerها **بی‌صدا** نمی‌آیند؛ یک تستِ سراسری هم اگر `node/peers?key=` جایی برگردد fail می‌شود. **(۲-۱۰ نشتِ قفل)** `_collect_locks` برای هر chat_id یک `asyncio.Lock` می‌ساخت و هرگز پاک نمی‌کرد؛ حالا `WeakValueDictionary` است. استدلالِ درستی مهم‌تر از خودِ تغییر است: دو کارِ واقعاً هم‌زمان به‌ضرورت هم‌پوشانی دارند و آن‌که داخلِ `async with` است ارجاعِ قوی نگه می‌دارد، پس رقیب همیشه **همان** شیء را می‌گیرد؛ و اگر ورودی جمع شده باشد یعنی هیچ‌کس قفل را نداشته. **(۲-۱۱ `os.remove` — نفوذی نیست، ولی واگرایی واقعی است)** پنل نام را اعتبارسنجی و نگه‌داشتِ مسیر را چک می‌کرد و دوقلوی رباتی‌اش (`routers/admin.py`) **هیچ‌کدام** را؛ `name` از کلیدِ سیستمیِ `cktok:` می‌آمد و هندلر ادمین-گیت بود پس بهره‌برداری‌پذیر نبود، ولی دو نسخهٔ دست‌نویس دوباره واگرا می‌شوند. هر دو حالا `cookies.remove_cookie_file()` را صدا می‌زنند — که در `cookies.py` است نه در پنل، چون **`routers/admin.py` نمی‌تواند `admin_web` را import کند** (ایمیجِ ربات jinja2/cryptography ندارد). **تست‌ها (۱۳۰ → ۱۵۴):** روی سورسِ پیش از رفع **۲۳ از ۲۴** تستِ تازه fail می‌شود؛ تنها استثنا تستِ پینِ 7z است که عمداً باید هر دو طرف سبز باشد چون رفتارِ بیرونی را قفل می‌کند نه کدِ ما را. DBِ واقعی (SQLite در حافظه) نه ماک، پس `aiosqlite` به `requirements-dev.txt` اضافه شد — وگرنه CI روی رانرِ تمیز می‌شکست. **پاک‌سازیِ جانبی:** حذفِ `os.remove` از `routers/admin.py` باعث شد `import os` و `from ..config import settings` بی‌مصرف شوند؛ هر دو برداشته شدند. **اعمال:** `processing`/`cookies`/`crud`/`ops` روی نودها هم اجرا می‌شوند → `telabzar update` روی مستر و `node/update.sh` روی هر نود؛ `node/wg-sync.sh` روی **هاستِ مستر** است و با `telabzar update` می‌آید ولی تایمر باید یک‌بار اجرا شود تا فرمِ تازه اثر کند.
- 2026-08-10 — **CI: `.github/workflows/tests.yml`** — روی هر PR و هر push به `main`، رانرِ تمیزِ `ubuntu-latest` کارِ `pip install -r requirements-dev.txt && pytest -q` را می‌کند. **پایتون ۳.۱۲، نه ۳.۱۱** — چون همهٔ ایمیج‌های اجرایی `python:3.12-slim`اند (`docker/*.Dockerfile`)؛ اینکه من محلی روی ۳.۱۱ تست می‌کردم اختلافِ خاموشی بود که سرِ نوشتنِ workflow پیدا شد و رفع شد. بدونِ ماتریسِ چندنسخه‌ای (هدف: محیطِ تولید، نه پوششِ نسخه). **دو چیزی که از تجربهٔ همین سشن آمد و در YAML کامنت شد:** (۱) تنها شکستِ بازتولیدپذیرِ محیطی، `cryptography`ِ **بستهٔ دبیان** بود که `_cffi_backend` نداشت و کلِ collect را با `pyo3_runtime.PanicException` می‌شکست؛ در venvِ تمیز `cryptography` **اصلاً نصب نمی‌شود** و PyJWT با `has_crypto=False` درست کار می‌کند — پس رانرِ تمیز این را بازتولید نمی‌کند. این حدس نبود: در یک venvِ خالیِ ۳.۱۲ دقیقاً همان دو دستورِ CI اجرا شد → **۱۳۰ سبز**. (۲) **ffmpeg عمداً نصب نمی‌شود**، چون هیچ تستی مارکرش را ندارد؛ نصبش فقط زمانِ build می‌خورد و پوششی که وجود ندارد را واقعی جلوه می‌دهد — تکلیفش با فاز ۲ب است. یک ریزِ مهم هم در §۶ ثبت شد: `'3.12'` باید کوت‌دار بماند وگرنه `3.10` به floatِ `3.1` تبدیل می‌شود. **Open Questions:** ردیفِ «Lint / CI» به «CI حل شد، **lint هنوز باز است**» تغییر کرد (هیچ ruff/flake8ای نیست، پس این جاب فقط پاس‌بودنِ تست‌ها را ثابت می‌کند نه چیزِ دیگر). **و محدودیتِ reaper ثبت شد:** `role_online` یعنی «heartbeat می‌زند»، نه «کار می‌کند» (`nodes.py:210-211` + `167-170`) — با تفکیکِ دو حالت که موقعِ نوشتن راستی‌آزمایی شد و ادعای اولیه‌ام را تصحیح کرد: اگر **حلقهٔ رویداد** بلاک شود، `_node_heartbeat` هم که تسکی روی همان حلقه است (`worker.py:40`) می‌ایستد، TTLِ ۴۵ ثانیه تمام می‌شود و سیستم **خودش را ترمیم می‌کند**؛ حالتِ نگران‌کننده وقتی است که حلقه زنده باشد ولی همهٔ اسلات‌های `max_jobs` گیر کرده باشند — آن‌وقت heartbeat می‌آید و مصرفی نیست، هرچند `job_timeout` (۲۰۰۰ ثانیه پردازش / ۵۴۰۰ دانلود) سرانجام اسلات‌ها را آزاد می‌کند، پس توقفِ تکرارشونده است نه گمشدنِ دائمی. باید **قبل از برگرداندنِ نودها** تعیینِ تکلیف شود. **اعمال:** فقط CI و مستندات — هیچ کدِ اجرایی عوض نشده، نه روی مستر نه روی نود.
- 2026-08-10 — **ورکرِ دانلودِ مستر اصلاً بالا نمی‌آمد: ساب‌کلاسِ تنظیماتِ ARQ کار نمی‌کند.** `arq.worker.get_kwargs` فقط `settings_cls.__dict__` را می‌خواند (`arq/worker.py:889` در ۰.۲۸) و `__dict__` صفاتِ ارث‌بری‌شده را **ندارد**؛ پس `MasterDownloadWorkerSettings(DownloadWorkerSettings)` دقیقاً **یک** کلید به arq می‌داد (`queue_name`) و ورکر با «at least one function or cron_job must be registered» (`arq/worker.py:236`) در حلقهٔ کرش می‌افتاد — یعنی هیچ دانلودی انجام نمی‌شد. با `create_worker`ِ واقعی بازتولید شد، نه استدلالِ روی کاغذ. **دو چیز که در گزارشِ اولیه نبود و بررسی بیرون کشید:** (۱) **دو کلاس خراب بودند نه یکی** — `ProcessingWorkerSettings` (`worker.py:122`، از `c445c63`/فاز N2) همین باگ را داشت، پس **نقشِ نودِ پردازش از روزِ اول هرگز کار نکرده**؛ مصرف‌کننده‌هایش `nodes.py:40` و `node/update.sh:35` هستند. (۲) **فقط `functions` گم نمی‌شود** — `redis_settings` هم می‌افتد، و آن بی‌صداتر و بدتر است: وصلهٔ دستیِ `functions` ورکری می‌دهد که خوش‌وخرم بالا می‌آید و به `localhost:6379` وصل می‌شود نه به Redisِ ما. باگِ دانلود از `c3dd2b0` آمد و تا وقتی نودها بودند پنهان ماند (جاب‌ها به صفِ نود می‌رفتند)؛ با حذفِ نودها مسیر به `arq:queue:dl:master` افتاد که مصرف‌کننده نداشت. **رفع:** دکوراتورِ `_flatten_settings` در `app/worker.py` صفاتِ ارث‌بری‌شده را در `__dict__`ِ خودِ کلاس کپی می‌کند (مقدارِ خودِ کلاس برنده می‌ماند — `max_jobs=2`ِ نودِ پردازش سرِ جایش است)، روی هر دو ساب‌کلاس. **یک شکافِ پوششی که سرِ راه ثبت شد:** امروز **هیچ تستی مارکرِ `ffmpeg` ندارد** (`pytest -m ffmpeg` → `130 deselected`)؛ تست‌های ffmpegیِ توصیف‌شده در changelogِ ۲۰۲۶-۰۷-۲۴ هرگز کامیت نشدند (آن ورودی از خودِ `tests/` قدیمی‌تر است، که در `4add1cd` آمد) و هیچ فایلِ تستی هم حذف نشده. یعنی قلابِ skip درست است ولی فعلاً از چیزی محافظت نمی‌کند — برای PRِ CI و فاز ۲ب در §۶ ثبت شد. **تست‌ها (۱۱۱ → ۱۳۰):** `tests/test_worker_settings.py` هر کلاسِ `*WorkerSettings` را **خودکار** کشف می‌کند (کلاسِ پنجمِ آینده هم پوشش می‌گیرد)، و علاوه بر `functions` کلِ مجموعهٔ arq را می‌سنجد تا افتادنِ بی‌صدای `redis_settings` هم گرفته شود؛ کنترلِ ضدِ vacuous یک ساب‌کلاسِ بدونِ دکوراتور می‌سازد و ثابت می‌کند **همان خطای تولیدی** را می‌دهد. روی سورسِ پیش از رفع، ۷ تست fail می‌شود (هر سه assert برای هر دو کلاسِ خراب). **یک تستِ خودم را همین‌جا دور انداختم:** نسخهٔ اولِ `test_the_subclasses_actually_inherit_something` تاتولوژی بود — بعد از اجرای دکوراتور آن مجموعه به‌ضرورت خالی است، پس تست با خودِ رفع در تضاد بود؛ جایش چیزی نشست که واقعاً صادق است (پدر خودش کامل باشد و در MRO بنشیند). **تستِ کانکتور هم عمومی شد:** `test_both_direct_engine_sessions_use_the_guarded_connector` دو تابع را هاردکد کرده بود — همان جنسِ شکافی که این باگ را ساخت (فهرستی که خودش را به‌روز نمی‌کند). حالا با AST کشف می‌شود (نه تطبیقِ رشته، چون `connector=` روی خطِ بعدیِ `ClientSession(` است) و معیارِ «موتورِ direct» یا نامِ تابع است یا صدازدنِ `_follow`. **اثباتِ ارزشِ این تغییر گرفته شد:** یک سشنِ سومِ محافظت‌نشده به `downloader.py` اضافه شد → تستِ نو می‌گیردش، تستِ هاردکدِ قبلی **کور از کنارش رد می‌شد**. **دو gotchaی جدید:** ناممکن‌بودنِ ساب‌کلاسِ تنظیماتِ ARQ، و اینکه `telabzar update` قبل از build دستورِ `git checkout -f -B main origin/main` می‌زند (`install.sh:185`) و هر تغییرِ محلیِ فایلِ tracked را دور می‌ریزد — امروز یک رفعِ فوری را سه بار بی‌صدا پاک کرد و تشخیص را گمراه کرد؛ برای build از کدِ محلی `telabzar up` (`install.sh:180`، بدونِ هیچ عملیاتِ گیت). **دو سؤالِ بازبینی که جواب گرفتند و ثبت شدند:** (الف) *جابِ یتیم روی `arq:queue:proc`؟* — arq **داخلِ `Worker.__init__`** خطا می‌دهد (`arq/worker.py:236`)، یعنی **قبل از** `on_startup`؛ و `on_startup` همان جایی است که heartbeatِ نود را می‌سازد (`worker.py:39-40`). بدونِ heartbeat، `role_online("processing")` غلط است — و این **همان گیتی** است که `ops._op_queue` (`routers/ops.py:150-157`) قبل از فرستادن به `arq:queue:proc` می‌پرسد. پس ورکری که بالا نمی‌آید اصلاً کار هم جذب نمی‌کند و opها تمامِ این مدت روی `arq:queue`ِ مستر ماندند. (ب) *reaper صفِ proc را پوشش می‌دهد؟* — بله، `_REAP_MAP` (`nodes.py:181-184`) هر دو صف را دارد؛ **باگِ جدا نیست**. ضمناً arq با عضوی که payloadش منقضی شده مهربان است (`job … expired` + شکستِ تمیز، `arq/worker.py:514-516`)، پس برگرداندنِ ورودی‌های کهنه بی‌خطر است. **Open Questionِ جدید:** «`wg0` هست ولی آی‌پی ندارد» توضیح‌ناپذیر است و پیش‌نیازِ برگرداندنِ نودهاست؛ کنارش این تأییدِ ریپویی ثبت شد که `.nodes-enabled` فقط **ساخته** می‌شود (`node/master-setup.sh:125`) و هیچ‌جای ریپو حذفش نمی‌کند، در حالی که CLI صرفاً با وجودِ فایل overlay را اعمال می‌کند (`install.sh:176`). **اعمال:** `worker.py` روی مستر **و** روی نودِ دانلود/پردازش اجرا می‌شود → `telabzar update` روی مستر و `node/update.sh` روی هر نود. تا merge شدن، استقرار فقط با `telabzar up`.
- 2026-07-26 — تأییدِ روی سرور، پیش از merge فازِ ۱. **`PROXY_URL` روی مستر خالی است** (egressِ مستقیم) — یعنی سخت‌گیرترین ردیفِ جدولِ تصمیم: رزولورِ وتوکننده وصل است و شکستِ DNS fail-closed، پس شکافی وجود ندارد و برعکس‌کردنِ fail-open لازم نشد. این مقدار در gotchaها ثبت شد تا دفعهٔ بعد از صفر بررسی نشود؛ هر تغییری در `proxy_url` (به‌ویژه به یک پروکسیِ **داخلی**) باید همان بولت را دوباره بخواند. **اسموکِ دستیِ چهار لینکِ واقعی روی مستر سالم بود** (یوتیوب، ریلزِ اینستاگرام، لینکِ مستقیمِ گیت‌هاب، و یک shortener با ریدایرکت) — پس درِ ورودیِ تازه رگرسیونی روی مسیرِ عادیِ دانلود نساخت. **دو تستِ محافظ برای `probe_direct`** هم اضافه شد (چون قبل از `download_direct` اجرا می‌شود و سشنِ سادهٔ آن‌جا یعنی یک چکِ محافظت‌نشده جلوی چکِ محافظت‌شده): یکی سورسِ هر دو تابع را می‌خواند، دیگری رفتاری است. **نسخهٔ اولِ تستِ رفتاری vacuous بود و همین‌جا گرفته شد** — وصله روی `socket.getaddrinfo` به رزولورِ aiohttp نمی‌رسد، پس نام NXDOMAIN می‌ماند و تست به دلیلِ غلط سبز می‌شد (با کانکتورِ ساده هم پاس می‌شد)؛ حالا روی `aiohttp.DefaultResolver.resolve` وصله می‌خورد و یک کنترل دارد که مسیرِ باز را اثبات کند. **یافتهٔ socks به فهرستِ فاز ۳ رفت** (نه پاورقی): `docs/ADMIN_PANEL.md:74` خودش `socks5h://` را توصیه می‌کند ولی `_http_proxy` فقط http(s) را به aiohttp می‌دهد، پس موتورِ `direct` از IPِ خودِ مستر بیرون می‌رود — که مانعِ برنامهٔ پروکسیِ موبایل/۴G است. `aiohttp_socks 0.11.0` سنجیده شد: در `connector.py:107` رزولور را با `NoResolver()` **بازنویسی** می‌کند (وتوی ما بی‌صدا ناپدید می‌شود) و اسکیمِ `socks5h` را هم اصلاً نمی‌پذیرد.
- 2026-07-26 — بازبینیِ پیش از merge برای فازِ ۱، و **یک رگرسیونِ واقعی که همان بازبینی گرفت**. سؤال این بود: حالا که IPِ خصوصی رد می‌شود، آیا مسیرِ داخلیِ خودمان (لایهٔ نود روی `10.51.0.0/24`) از این فیلترها رد می‌شود؟ فهرست‌برداری شد و جواب برای همه «نه» بود — `is_safe_url*` فقط دو فراخوان دارد (درِ ورودیِ لینک و `_follow`) و `gateway_node`/پنل/`download_cobalt`/aiogram/Redis/Postgres هرکدام سشن یا درایورِ خودشان را دارند، و `node/wg-sync.sh` با `curl` از روی هاست به `/node/peers` می‌زند و اصلاً به پایتون نمی‌رسد. **ولی یک مسیر واقعاً می‌شکست:** رزولورِ ضدِ TOCTOU روی کانکتور، هاستِ **پروکسی** را هم وتو می‌کرد. aiohttp در حالتِ پروکسی نامِ پروکسی را حل می‌کند نه مقصد را، پس آن رزولور آن‌جا هیچ حفاظتی نمی‌داد و فقط می‌توانست خودِ پروکسی را بشکند: `PROXY_URL=http://squid:3128` (نامِ سرویسِ داکر → ۱۷۲٫x) «داخلی» شمرده می‌شد و هر دانلود با `ClientConnectorDNSError` می‌مرد. با پروکسیِ **IPِ لفظی** اتفاق نمی‌افتاد، که همین باعث می‌شد تستِ واحد پیدایش نکند. `_direct_connector(opts)` حالا وقتی پروکسیِ http(s) در کار است رزولور را وصل نمی‌کند (پروکسیِ socks که aiohttp نمی‌فهمدش و اتصال مستقیم است، رزولور را نگه می‌دارد). سه تستِ تازه: پروکسیِ نام‌دارِ روی IPِ خصوصی + وصل‌بودنِ رزولور بدونِ پروکسی + مسیرِ socks. **مسیرِ ردِ گیتِ سنی هم تا آخرِ خط تست شد** (نه فقط تا `download_ytdlp`): `run_download`ِ واقعی با yt-dlpِ جعلی که مثلِ خودِ yt-dlp با کدِ **صفر** و بدونِ فایل خارج می‌شود → کاربر `nsfw_blocked` می‌گیرد نه `dl_failed` و نه «produced no file»، اسلاتِ هم‌زمانی آزاد می‌شود، و هیچ اکانتِ کوکی‌ای ضربه نمی‌خورد. **`--match-filter` روی اسپاتیفای هم اعمال می‌شود** — ترکِ دارای محدودیتِ سنی بی‌صدا از پلی‌لیست حذف می‌شود (در gotchaها ثبت شد؛ اگر *همهٔ* ترک‌ها رد شوند پیامِ `no YouTube match` علت را اشتباه نام می‌برد، که عمداً برای بعد ماند). **اسموکِ لینکِ واقعی:** خروجیِ HTTPِ این محیط با سیاستِ پروکسی مسدود است (`403 CONNECT`)، پس دانلودِ واقعی اجراشدنی نبود؛ ولی DNS کار می‌کند و درِ ورودی — تنها چیزی که عوض شده — روی ۱۰ هاستِ واقعی سنجیده شد (یوتیوب، `youtu.be`، ریلزِ اینستاگرام، ریلیزِ گیت‌هاب، CDNِ گیت‌هاب، `bit.ly`، `t.co`، X، تیک‌تاک، آپارات): همه از هر دو لایه رد شدند و `platform_of`/`engine_for` دست‌نخورده ماند. نکتهٔ ارزشمندش `t.co` بود که روی `172.66.0.227` می‌نشیند — یک چکِ سرانگشتیِ «۱۷۲٫x یعنی خصوصی» آن را می‌شکست، ولی `172.16.0.0/12` شاملش نیست. دانلودِ واقعیِ چهار لینک روی مستر قبل از merge لازم است (فهرستش به کاربر داده شد). یادداشتِ بی‌اقدام: `is_safe_url_resolved` روی executorِ پیش‌فرضِ `to_thread` است و در مقیاسِ بالا نقطهٔ اشباع دارد.
- 2026-07-26 — **فازِ ۱ِ ممیزیِ باگ: چهار موردِ بحرانی** + اولین `tests/`ِ کامیت‌شدهٔ ریپو. **(۱-۱) SSRF.** `is_safe_url` روی `ValueError`ِ `ipaddress.ip_address` نتیجه می‌گرفت «پس نامِ دامنه است → مجاز»، ولی `2130706433` و `0x7f000001` و `127.1` و `017700000001` **همه** ValueError می‌دهند و **همه** به `127.0.0.1` وصل می‌شوند — `ipaddress` فقط dotted-quad را می‌پذیرد در حالی که `getaddrinfo` (که خودِ اتصال از آن استفاده می‌کند) هر شکلِ `inet_aton` را می‌فهمد. تشخیصِ لفظی حالا با `AI_NUMERICHOST` است: معناشناسیِ libc، بدونِ DNS. دو سوراخِ دیگر هم بسته شد: `::ffff:127.0.0.1` که `is_loopback` برایش False است (باز کردنِ `ipv4_mapped`)، و `is_multicast`/`is_unspecified`/CGNATِ `100.64.0.0/10` که اصلاً چک نمی‌شدند. **و مهم‌تر از همه:** هیچ resolveی انجام نمی‌شد، پس `evil.example` با A-recordِ `169.254.169.254` از فیلتر رد می‌شد — `is_safe_url_resolved()` (ناهمگام، `getaddrinfo` در thread، کشِ ۶۰ ثانیه، مهلتِ ۲ ثانیه) حالا درِ ورودیِ لینک است. شکستِ DNS **مشروط** است نه fail-open: با `proxy_url` نام را پروکسی حل می‌کند → اجازه؛ بدونِ پروکسی (پیش‌فرضِ ما) درخواست از همین ماشین می‌رود پس شکستِ DNS بهانه‌ای ندارد → رد + لاگ. پنجرهٔ TOCTOU (DNS rebinding) هم برای موتورِ `direct` با `TCPConnector(resolver=_safe_resolver())` بسته شد: aiohttp همان آدرسی را وتو می‌کند که واقعاً به آن وصل می‌شود، پس هر پرشِ ریدایرکت خودکار پوشش دارد. yt-dlp زیرفرایند است و رزولور نمی‌گیرد؛ آن‌جا درِ ورودی کلِ دفاع است. یک کانالِ باقی‌مانده **آگاهانه پذیرفته و در کد علامت‌گذاری شد**: پیامِ `dl_failed` مقدارِ `msg[:280]`ِ stderrِ موتور را نشان می‌دهد. **(۱-۲) شمارندهٔ هم‌زمانی.** `INCR dl:active` با `DECR` در `finally` — که روی OOM/kill اجرا نمی‌شود و کلید TTL نداشت، پس سه مرگِ ناگهانی شمارنده را برای همیشه بالای `dl_concurrency` می‌برد و **هر** دانلودِ بعدی «شلوغ است» می‌گرفت. ماژولِ تازهٔ `app/dl_active.py` جایش را می‌گیرد: ZSET با مهرِ زمانِ **سرورِ Redis** (نه ساعتِ محلی — مستر و نود دو ماشین‌اند)، تسکِ keepalive برای کلِ طولِ جاب (شاملِ آپلود) که در `finally` کنسل می‌شود، و شمارشِ «اول هرس بعد ZCARD». دو تلهٔ ظریف: عضوِ ZSET باید **per-job یکتا** باشد نه `ref` (که بینِ probe/fetch مشترک است و `on_dl_pick` می‌تواند چند کیفیت از یک منو بفرستد → دو جاب همدیگر را بازنویسی/حذف می‌کردند)؛ و ماژول عمداً وابستگیِ سنگین ندارد چون **پنل هم از آن می‌خواند** و ایمیجِ پنل Pillow ندارد (importِ `tasks_download` آن‌جا پروسه را می‌شکست). **(۱-۳) حلقهٔ بی‌نهایتِ `_atempo_chain`.** `Spd.rate` رشتهٔ آزادِ callback است و `while r < 0.5: r /= 0.5` روی نرخِ منفی و روی `inf` هرگز تمام نمی‌شود. نکتهٔ کشنده: تابع **همگام** است و قبل از هر `await` اجرا می‌شود، پس `job_timeout`ِ asyncioی ARQ نمی‌تواند شلیک کند — یک callbackِ ساخته‌شده کلِ پروسهٔ ورکر (یا **نودِ پردازش**، چون `speed` در `OFFLOAD_OPS` است) را می‌خواباند و لیست را تا OOM بزرگ می‌کرد. دو گارد در دو سطح: `_do_op` فقط ضریب‌هایی را می‌پذیرد که خودِ ربات پیشنهاد داده (`keyboards.AUDIO_SPEEDS`)، و `_atempo_chain` مقدارِ غیرمتناهی و بیرونِ `SPEED_MIN..SPEED_MAX` را رد می‌کند. `op_speed_pick` هم گاردِ `kind != "audio"` را گرفت که خواهرش `op_speed` از قبل داشت؛ **فقدانِ سیستماتیکِ اعتبارسنجی/مالکیت در `ops.py` عمداً دست‌نخورده ماند** و به فازِ ۲ سپرده شد. **(۱-۴) لایهٔ ۲ فیلترِ بزرگسال.** `normalize_probe` فقط `{title, duration, kind, thumbnail, options}` می‌داد، پس `check_meta` روی نتیجهٔ probe نه `age_limit` می‌دید نه `description`/`tags`/`categories`/`uploader`/`channel` — یعنی قوی‌ترین و ارزان‌ترین سیگنالِ ما **هرگز قبل از دانلود** شلیک نمی‌کرد. (بعد از دانلود کار می‌کرد، چون مسیرِ fetch همان `.info.json`ِ خامِ yt-dlp را می‌دهد.) حالا این فیلدها با سقفِ اندازه حمل می‌شوند. برای مسیرِ **quick** — که پیش‌فرض است و اصلاً probe نمی‌کند — گیت روی خودِ فراخوانیِ دانلود سوار شد با `--match-filter`: صفر رفت‌وبرگشتِ اضافه و صفر مصرفِ اضافه از سهمیهٔ اکانتِ کوکی (گران‌ترین منبعِ ما؛ گزینهٔ «یک `-J`ِ جداگانه قبل از هر دانلود» به همین دلیل رد شد). **مقایسه باید `age_limit<?18` باشد نه `age_limit<18`:** در yt-dlp مقایسهٔ عددیِ ساده روی فیلدِ **غایب** False می‌دهد و اکثرِ extractorها `age_limit` ست نمی‌کنند، پس فرمِ سخت‌گیرانه تقریباً هر ویدیویی را رد می‌کرد. ردِ yt-dlp به‌صورتِ `does not pass filter` در stdout می‌آید و بسته به نسخه با هر دو کدِ خروجی، پس هر دو مسیر بررسی می‌شود و به `AgeRestricted` تبدیل می‌شود که `run_download` **قبل از** شاخهٔ چرخشِ کوکی می‌گیردش (اکانتِ دیگر نتیجهٔ متفاوتی نمی‌دهد و هیچ‌کدام مستحقِ ضربه نیست). **تست‌ها — اولین `tests/`ِ ریپو (۱۰۰ تست، `requirements-dev.txt` + `pytest.ini`):** واقعی نه ماک — سرورِ واقعیِ aiohttp که نقشِ سرویسِ داخلی را بازی می‌کند و قبل از رفع واقعاً بدنه‌اش تحویل می‌شد، `yt-dlp`ِ جعلیِ **اجرایی** روی PATH که رفتارِ واقعیِ `--match-filter` را تقلید می‌کند، `fakeredis` با ZSET/TIMEِ واقعی، و اجرای `_atempo_chain` در زیرفرایندِ مهلت‌دار تا نبودِ گارد به‌جای هنگ‌کردنِ suite یک failِ تمیز بدهد. تنها چیزی که جعل می‌شود رکوردِ DNS است، چون A-recordِ مهاجم در تست ساختنی نیست. اثباتِ pre-fix گرفته شد: ۲۱ تستِ SSRF، ۱۲ تستِ سرعت (پنج‌تا با تایم‌اوتِ حلقهٔ بی‌نهایت) و ۵ تستِ فیلتر روی سورسِ قبل از رفع fail می‌شوند. تستِ نیازمندِ ffmpeg با `@pytest.mark.ffmpeg` علامت می‌خورد و در نبودش skip می‌شود. **باگی که خودِ تست‌ها گرفتند:** درجِ `AgeRestricted` کنارِ `DirectTooLarge` سازندهٔ آن را دزدیده بود و پیامِ «حجم زیاد است» را می‌شکست — یک تستِ محافظ برایش اضافه شد. **اعمال:** `telabzar update` روی مستر **و** `node/update.sh` روی **هر دو** نوع نود — `downloader`/`tasks_download`/`dl_active` روی نودِ دانلود و `processing`/`tasks` روی نودِ پردازش اجرا می‌شوند.
- 2026-07-25 — «۲ کوکیِ خراب + ۱ سالم → بارِ اول ارور، بارِ دوم دانلود» + «کوکی‌ها سالم‌اند ولی می‌گوید کوکی ست کن». هر دو از **یک** عادتِ غلط می‌آمدند: تصمیم‌گیری از روی **رشتهٔ خطا**. **(A) چرخش:** `tried.add` و `continue` داخلِ شرطِ `_is_cookie_error` بودند، پس هر خطایی که در فهرستِ کلیدواژه‌ها نبود کلِ درخواست را با **یک** تلاش تمام می‌کرد — با اینکه اکانت‌های دست‌نخورده کنارش بودند. (بارِ دوم کار می‌کرد چون اکانتِ افتاده `UNPROVEN` شده و رتبه‌اش پایین آمده بود.) حالا پیش‌فرض می‌چرخد و فقط خطاهای **محتوایی** (`_CONTENT_HINTS`: ۴۰۴/خصوصی/حذف‌شده) متوقفش می‌کنند؛ سقفِ `dl_max_cookie_tries` جلوی راه‌رفتنِ کلِ استخر روی یک لینکِ خراب را می‌گیرد؛ نگهبانِ تکراریِ `pick()` حذف شد (که `node_id` را هم پاس نمی‌داد و با `_next_cookie` اختلاف داشت). **(B) تقصیر:** وقتی اینستاگرام یک **IP** را رد می‌کند همان `redirect to login page`ی را می‌دهد که برای سشنِ مرده — پس با یک پیام نمی‌شود قضاوت کرد، ولی با **الگو** می‌شود. `_resolve_blame` در پایانِ درخواست تصمیم می‌گیرد: موفق شد → اکانت‌های افتاده واقعاً خراب‌اند؛ شکست خورد و ≥۲ اکانتِ متفاوت امتحان شد → **مقصر خروجی است** → هیچ ضربه‌ای به هیچ اکانتی، خروجی کول‌داون می‌گیرد، `_dl_queue` از آن عبور می‌کند، و پیامِ کاربر به‌جای «کوکی ست کن» می‌شود «مشکل از خروجیِ شبکه است». **چرا مهم بود:** `burns_account(login_required)` صادق است، پس یک IPِ مسدود به هر تلاش یک ضربه به یک اکانتِ **سالم** می‌زد و با `ck_invalid_at=3` سشن‌های سالم را «باطل» می‌کرد — یعنی سیستم خودش ادمین را وادار می‌کرد سشن‌های سالم را دوباره استخراج کند. **دو نکتهٔ ریز:** `note_use` دیگر سطلِ ساعتی را پر نمی‌کند (با `note_spend` بعد از نتیجه)، وگرنه یک خروجیِ مسدود سهمیهٔ کلِ استخر را می‌خورد؛ و `pick` هم‌رتبه‌ها را چرخشی برمی‌دارد وگرنه روی استخرِ تازه مرتب‌سازی به **نام** می‌افتد و همیشه یک اکانتِ ثابت اولین قربانی است (`_CK_ROT` برای همین بود و استفاده نمی‌شد). تست: سناریوی دقیقِ کاربر (۲ خراب + ۱ سالم → همان بارِ اول موفق، هر سه امتحان شدند)، شکستِ همگانی → صفر ضربه + کول‌داونِ خروجی + پیامِ درست + DMِ «کوکی‌ها را عوض نکن»، ۴۰۴ با **یک** تلاش و بدونِ سوزاندنِ استخر، سقفِ تلاش، چرخشی‌بودنِ ترتیبِ اولیه، و عبورِ مسیریابی از خروجیِ کول‌داون‌شده (فقط برای همان پلتفرم). **اعمال:** `telabzar update` + `node/update.sh`.
- 2026-07-25 — «پنل سالم نشان می‌دهد ولی هیچ دانلودی کار نمی‌کند» — ریشه پیدا و بسته شد. **علت:** وضعیتِ اکانت فقط از `fail_streak` ساخته می‌شد و `mark_fail` **تنها** وقتی صدا زده می‌شد که خطا «کوکی‌محور» شناخته شود (`tasks_download.py`، شرطِ `_is_cookie_error`). خطای ناشناخته هیچ‌وقت به استخر نمی‌رسید، و دسته‌های بی‌ضربه (`transient`) هم عمداً شمارنده بالا نمی‌برند — پس بج برای همیشه سبز می‌ماند. پنل دروغ نمی‌گفت؛ داشت می‌گفت «چیزی ثبت نشده»، که ادمین آن را «سالم است» می‌خواند. **رفع:** (۱) هر شکستی روی اکانت ثبت می‌شود، (۲) وضعیتِ تازهٔ `UNPROVEN` («آخرین تلاش ناموفق») وقتی آخرین رویداد خطا بوده نه موفقیت — اکانت همچنان قابلِ استفاده است و فقط بعد از اکانت‌های واقعاً موفق انتخاب می‌شود، (۳) متنِ `last_error` روی ردیفِ اکانت نمایش داده می‌شود (تا امروز ذخیره می‌شد و هیچ‌جا دیده نمی‌شد). **و مسئلهٔ اصلی‌تر:** آمارِ per-account اصلاً نمی‌تواند بگوید «سشن مرده یا IP مسدود؟» — وقتی همهٔ اکانت‌ها می‌افتند مقصر معمولاً خروجی است. `note_exit`/`exit_stats` موفقیت/شکست را به تفکیکِ **خروجی** می‌شمارند و کارتِ «🌐 خروجی‌ها» وقتی یک خروجی صفر موفقیت و ≥۳ شکست دارد صریح می‌نویسد «IPِ این خروجی مسدود است، نه کوکی‌ها — تعویضِ سشن کمکی نمی‌کند». فقط شکستِ واقعیِ شبکه‌ای شمرده می‌شود نه ردِ سیاستی (حجم/مدت/فیلتر)، وگرنه سیگنال آلوده می‌شد. **هشدارِ ناهمخوانیِ آینه** هم اضافه شد (تعدادِ فایلِ دیسک در برابرِ Redis) + دکمهٔ همگام‌سازی، چون نودِ دانلود فقط آینهٔ Redis را می‌بیند و نبودنِ یک کوکی در آن بی‌سروصدا بود. **دو تلهٔ حین کار که تست‌ها گرفتند:** `healthy_count` (که هشدارِ «کوکیِ سالم کم است» را می‌زند) باید `UNPROVEN` را هم بشمارد وگرنه یک شکستِ بی‌تقصیر هشدارِ الکی می‌فرستد؛ و `unfreeze` باید `last_error` را پاک کند وگرنه پس از «رسیدگی شد» اکانت با خطای منقضی سبز نمی‌شود. **آنچه بررسی و رد شد:** «شاید فقط `sessionid` کافی نیست» — سورسِ gallery-dl 1.32.8 خوانده شد: `cookies_names = ("sessionid",)` و `csrftoken` را خودش می‌سازد، پس اعتبارسنجیِ ما درست است.
- 2026-07-25 — رفعِ خطای `JSONDecodeError`ِ اینستاگرام + تشخیصِ «سشن مرده یا موتورِ عقب‌افتاده؟». gallery-dl وقتی بدنهٔ پاسخ خالی/غیرJSON باشد `An unexpected error occurred: JSONDecodeError - Expecting value: line 1 column 1` می‌دهد؛ اینستاگرام وقتی سشن یا IP را بی‌سروصدا رد می‌کند همین را برمی‌گرداند — **ولی** دقیقاً همین خطا وقتی هم می‌آید که خودِ extractor با تغییرِ سایت عقب افتاده باشد. همین ابهام کلِ نحوهٔ برخورد را تعیین می‌کند: دستهٔ تازهٔ `cookies.TRANSIENT` باعث می‌شود `_is_cookie_error` **به اکانتِ بعدی بچرخد** (چون حالتِ رایج همان سشنِ مرده است) ولی `mark_fail` **نه شمارنده بالا ببرد نه کول‌داون بدهد** — فقط `last_error` را برای پنل ثبت می‌کند. اگر کول‌داون می‌دادیم، یک مشکلِ سمتِ سایت کلِ استخر را از سرویس خارج می‌کرد. قبل از این، هیچ‌کدام از این پیام‌ها با `_BAN_HINTS`/`_LOGIN_HINTS` جور نمی‌شد، پس نه چرخشی بود و نه پیامِ معناداری: کاربر تریس‌بکِ خامِ gallery-dl می‌گرفت در حالی که شاید اکانتِ سالمِ بعدی جواب می‌داد. حالا پیامِ `dl_bad_response` هر دو احتمال را می‌گوید. **و چون ادمین با چشم نمی‌تواند این دو را تفکیک کند:** هر ورکرِ دانلود سرِ استارت نسخهٔ `gallery-dl`/`yt-dlp` خودش را در Redis می‌نویسد (`worker.startup_dl` → `dlver:<who>`) و صفحهٔ سلامت نشانشان می‌دهد — موتورِ قدیمی یعنی `telabzar update` (و روی نود `node/update.sh`)، موتورِ به‌روز یعنی سشن باید عوض شود. دو باگِ bidi سرِ همین کارت پیدا و رفع شد: جفتِ نسخه در پاراگرافِ RTL برعکس چیده می‌شد (`.mono` ایزوله می‌کند ولی `direction` را ست نمی‌کند → کلِ سلولِ لاتینِ خالص باید `.ltr` بگیرد) و پرانتزِ دورِ متنِ ترکیبی در راهنما آواره می‌شد. تست: پیامِ **دقیقِ** گزارش‌شدهٔ کاربر، پنج شکلِ خویشاوندِ آن، دست‌نخوردن‌ِ دسته‌های قبلی (چک‌پوینت/محدودیتِ نرخ/۴۰۴ که نباید بچرخد)، سالم‌ماندنِ اکانت پس از ۵ خطا، چرخشِ واقعی روی هر سه اکانت در `run_download` و سالم‌ماندنِ کلِ استخر پس از آن.
- 2026-07-25 — **فیلترِ محتوای بزرگسال** (`app/safety.py`)، برای لینک و فایلِ آپلودی هر دو. انگیزه عملیاتی است نه سلیقه‌ای: ربات هر فایلی را **دوباره آپلود** می‌کند، پس خودش توزیع‌کننده است و همین مسیرِ بن‌شدنِ اکانتِ ربات است. **سه لایه، از ارزان به گران:** (۱) **دامنه** سرِ ورودِ لینک، قبل از دانلودِ حتی یک بایت — فهرستِ پایه + TLDهای بزرگسال + کلیدواژه در هاست/مسیر؛ (۲) **متادیتا** — `age_limit`ی که خودِ yt-dlp می‌دهد به‌علاوهٔ عنوان/توضیحات/تگ/نامِ فایل، باز هم قبل از دانلود؛ (۳) **پیکسل** — NudeNet روی onnxruntime (که برای rembg از قبل داشتیم)، ویدیو با نمونه‌برداریِ چند فریمِ پخش‌شده در طولِ کلیپ. **جایی که گیت می‌خورد مهم است:** فایلِ آپلودی **قبل از ساختنِ کارت** بررسی می‌شود نه بعدش، چون کارت یعنی ربات همان محتوا را دوباره فرستاده؛ اسکن در ورکر (`tasks.run_screen`) است نه در ربات، چون اجرای مدل کارِ CPU است و نباید long-polling را بگیرد. **دو قاعدهٔ سفت:** فیلتر **fail-open** است (مدل نبود/خطا داد → مجاز)، چون فیلتری که سرویس را بخورد از فیلترِ ناقص بدتر است؛ و فقط برچسب‌های **صریحِ** NudeNet مسدود می‌کنند — `BELLY/FEET/ARMPITS/FACE`، هر `*_COVERED` و `MALE_BREAST_EXPOSED` هرگز، وگرنه عکسِ ساحل و باشگاه هم رد می‌شد. **درسِ اصلیِ این کار از تست بیرون آمد:** تطبیقِ زیررشته‌ای روی `sex` واژه‌های Sussex/Essex/Middlesex و در فارسی سوسکس/اسکس را می‌گیرد، روی `anal` واژهٔ analysis، روی `pussy` گروهِ Pussycat Dolls، روی `cum` واژهٔ Cumbria و روی `hardcore` سایتِ hardcoregaming101 — ولی تطبیقِ «توکنِ کامل» هم `freeporn-tube` را از دست می‌دهد چون دامنه‌های بزرگسال کلمه‌ها را می‌چسبانند. پس سه ردهٔ کلیدواژه ساخته شد: `STRONG` (زیررشته‌ای، فقط ریشه‌های بی‌ابهام)، `WORD` (فقط توکنِ کامل) و `HOST` (فقط داخلِ نامِ دامنه — «Ford Escorts» و «adult education» در متن مبهم‌اند ولی در هاست نه). هر کدام از این برخوردها حالا یک تستِ رگرسیون دارد. **ادمین:** گروهِ «🔞 فیلترِ محتوای بزرگسال» با کلید روشن/خاموش، خاموش‌کردنِ جداگانهٔ لایهٔ پیکسل، آستانهٔ درصدی، تعدادِ فریم، فهرستِ دامنهٔ اضافی و **فهرستِ استثنا** (برای رفعِ مسدودیِ اشتباه)، گزارشِ ادمین، و مسدودیِ خودکارِ کاربر پس از N تخلف (۰=خاموش). دو فیلدِ فهرست به‌جای inputِ ۱۶۰ پیکسلی textarea گرفتند (`LONGTEXT_KEYS` + کلاسِ `.ta-inline` در `_CSS`). **اعمال:** `safety` هم روی ورکرِ اصلی و هم روی نودِ دانلود اجرا می‌شود؛ `requirements-worker-dl.txt` برای اولین بار `onnxruntime` می‌گیرد (ایمیجِ لاغرِ دانلود سنگین‌تر می‌شود، ولی جایگزینش جابه‌جاکردنِ بایت‌ها بینِ ماشین‌هاست) و مدل سرِ build آماده می‌شود تا نودِ با egressِ محدود بی‌سروصدا فیلتر را خاموش نکند → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — دو مسئلهٔ گزارش‌شدهٔ کاربر: **سشنِ مردهٔ اینستاگرام** و **لینکِ فایلِ مستقیم**. **(۱)** `HTTP redirect to home page (https://www.instagram.com/)` جوابِ gallery-dl است وقتی کوکیِ اینستاگرام دیگر معتبر نیست؛ ولی چون هیچ‌کدام از کلیدواژه‌های `_BAN_HINTS`/`_LOGIN_HINTS` را ندارد، «بی‌ربط» حساب می‌شد — یعنی نه اکانتِ بعدی امتحان می‌شد، نه اکانتِ مرده علامت می‌خورد، و کاربر با وجودِ اکانت‌های سالمِ دیگر خطا می‌گرفت. حالا در `_LOGIN_HINTS` و در `cookies._CLASS_HINTS[LOGIN_REQUIRED]` هست، پس هم چرخش می‌کند هم شمارنده بالا می‌رود (محدودیتِ نرخ نیست؛ سشن واقعاً باید عوض شود). درسِ کلی که در gotchaها ثبت شد: سرِ افزودنِ موتور، **پیامِ شکستِ خاموشِ احراز هویت** را چک کن، نه فقط خطاهای پرسروصدا. **(۲)** لینکِ دانلودِ مستقیم (ریلیزِ گیت‌هاب، APK، PDF…) به yt-dlp می‌رفت و می‌شکست — روی یک لینکِ امضاشدهٔ blob با مسیرِ GUIDدار و کوئریِ بلند حتی سرِ نوشتنِ فایلِ متادیتای خودش کرش کرد. حالا هاستِ ناشناخته اول یک **HEADِ ارزان** می‌خورد (`downloader.probe_direct`) و هرچه صفحه نیست با `download_direct` استریم می‌شود؛ `text/html`, `application/json/xml` و **مانیفستِ HLS/DASH** دستِ yt-dlp می‌مانند. چهار نکتهٔ طراحی: نامِ فایل از **Content-Disposition** (هم `filename*`ِ RFC 5987 هم ساده) گرفته می‌شود نه از مسیرِ URL که اغلب GUID است؛ سقف **دو لایه** اعمال می‌شود (`Content-Length` قبل از شروع + شمارشِ واقعیِ بایت‌ها حین دانلود، چون سرور ممکن است ندهد یا دروغ بگوید) و فایلِ نیمه‌کاره پاک می‌شود؛ **هر پرشِ ریدایرکت** دوباره از `is_safe_url` رد می‌شود (ریدایرکتِ خودکارِ aiohttp یک پرش به `169.254.169.254` را پنهان می‌کرد)؛ و `info` عمداً `title` ندارد تا کارت نمای فنی بدهد نه کپشنِ ساختگیِ پست. کلیدهای زمانِ‌اجرا: `dl_direct_enabled` و `dl_direct_max_mb` (پیش‌فرض ۵۰۰ مگابایت، و `dl_max_size_mb` همچنان حاکم است چون سقفِ آپلودِ تلگرام قابلِ‌مذاکره نیست). فایلِ مستقیم هیچ‌وقت کوکی نمی‌گیرد و هیچ اکانتی را نمی‌سوزاند. تست با **سرورِ واقعیِ aiohttp** (نه ماک): بلابِ امضاشده با نامِ GUIDدار، صفحهٔ HTML و مانیفستِ m3u8 که باید دستِ yt-dlp بمانند، سروری که HEAD را ۴۰۵ می‌دهد، ریدایرکتِ سالم و ریدایرکتِ SSRF، هر دو لایهٔ سقف، لغوِ وسطِ دانلود، و مسیرِ کاملِ `run_download` تا ساختِ کارتِ `kind=app`. **اعمال:** `downloader`/`tasks_download`/`cookies` روی نودِ دانلود اجرا می‌شوند → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — سهمیهٔ استخرِ سشن از **ثابت** به **تنظیم‌شدنی از پنل** تبدیل شد. تا دیروز همهٔ اعدادِ سرعت‌گیر ثابتِ کد بودند (`_HOURLY_CAP`, `_MIN_GAP_SEC`, `_WARMUP_DAYS`, `_WARMUP_FLOOR`, `_COOLDOWN_SEC`, `_RATE_COOLDOWN`, `_INVALID_AT`)، یعنی ادمین برای عوض‌کردنِ سقفِ اینستاگرام باید کد را دست می‌زد و ری‌استارت می‌کرد — در حالی که همین عدد است که تعادلِ «سرعت در برابر عمرِ اکانت» را می‌سازد و از استقرار تا استقرار فرق می‌کند. حالا هر یازده عدد کلیدِ زمانِ‌اجرا است (`ck_cap_instagram/youtube/twitter/tiktok/default`, `ck_min_gap_sec`, `ck_warmup_days`, `ck_warmup_pct`, `ck_cooldown_min`, `ck_rate_cooldown_min`, `ck_invalid_at`) با گروهِ «🧬 سهمیهٔ استخرِ سشن» در پنل و پیش‌فرضِ env در `config`. **تصمیمِ طراحی که مسئله بود:** `settings_store.get_int` ناهمگام است ولی `hourly_cap`/`warmup_factor`/`budget_of` ریاضیِ خالص و همگام‌اند؛ ناهمگام‌کردنشان هم تست را به Redis گره می‌زد و هم `pick()` را وادار می‌کرد برای *هر* اکانت تنظیمات بخواند. به‌جایش `Limits` ساخته شد — یک عکسِ فوریِ تغییرناپذیر که فقط `load_limits()` ناهمگام است و **یک‌بار سرِ هر عملیات** خوانده و به پایین پاس داده می‌شود (`pick`, `accounts`, `mark_fail`, صفحهٔ کوکی‌ها)؛ ریاضی همگام ماند و بارِ Redis از N به ۱ رسید. هر تابع اگر `lim` نگیرد به `default_limits()` (مقادیرِ env) برمی‌گردد، پس هیچ مسیرِ قدیمی و هیچ پروسه‌ای که store ندارد نمی‌شکند. **معنیِ صفر:** سقفِ ۰ = **بی‌سقف** (سرعت‌گیر خاموش)، نه «صفر دانلود» — `budget_of` صفر می‌دهد، `_over_budget` از سقف صرف‌نظر می‌کند و ردیفِ پنل «بی‌سقف» می‌نویسد؛ `ck_warmup_days=0` هم یعنی بدونِ گرم‌کردن. واحدها به زبانِ ادمین‌اند (کول‌داون به **دقیقه**، کفِ گرم‌شدن به **درصد**) چون `RUNTIME_KEYS` فقط bool/int/str دارد و کسری‌نویسی در فرم خطاخیز است. تست: پیش‌فرض بدونِ store، اثرِ هر کلید روی `Limits`، توقفِ اکانت روی سقفِ **پنل** (نه ۳۰ِ قدیمی)، «باطل» شدن با ۲ خطا وقتی پنل ۲ گفته، TTLِ واقعیِ کول‌داونِ محدودیتِ نرخ + بی‌ضربه‌ماندنِ اکانت، حالتِ بی‌سقف (۲۰۰ استفاده و همچنان سرویس)، و ثبتِ هر کلید در `RUNTIME_KEYS` + یک صفحهٔ پنل + پیش‌فرضِ `config`. **اعمال:** `cookies` روی نودِ دانلود اجرا می‌شود → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — استخرِ سشن V3 (لایه‌های ۲ و ۳): **هویتِ سشن** + **سرعت‌گیر و گرم‌کردن**. **(۱) هویت:** اکانت دیگر «یک فایلِ کوکی» نیست؛ سه‌تاییِ کوکی + خروجی + User-Agent است که همیشه با هم می‌روند. متادیتای هر اکانت `node_id`/`proxy`/`user_agent` گرفت؛ `pick(node_id=…)` اکانتِ پین‌شده به خروجیِ **دیگر** را اصلاً برنمی‌دارد و اکانتِ پین‌شده به خروجیِ **فعلی** را مقدم می‌داند، و `_opts(identity=…)` پروکسی/UAِ خودِ اکانت را جای مقادیرِ عمومی می‌گذارد (`--user-agent` به yt-dlp و gallery-dl می‌رسد). دلیل: اینستاگرام IP را هویت می‌داند و جابه‌جاییِ IPِ یک سشن سریع‌ترین راهِ چک‌پوینت است. معماریِ نودِ موجود دقیقاً همین را رایگان می‌دهد. **(۲) سرعت‌گیر:** سطلِ توکنِ ساعتی برای هر اکانت (`hourly_cap` — اینستاگرام عمداً سخت‌گیرترین) + حداقلِ فاصلهٔ `_MIN_GAP_SEC` بین دو استفاده از **یک** اکانت، هر دو در Redis. طبقِ تحقیق، فشارِ ۲× یعنی سوختنِ ۴×. **(۳) گرم‌کردن:** اکانتِ تازه با ۲۵٪ ظرفیت شروع و طیِ `_WARMUP_DAYS` روز به ۱۰۰٪ می‌رسد — اکانتِ نویی که ناگهان پرمصرف شود، خودش الگویی است که تشخیص داده می‌شود. **درستی:** اگر سهمیهٔ کلِ استخر تمام شود `pick` یک‌بار با `ignore_budget=True` تلاش می‌کند، پس سرعت‌گیر هرگز به خطای کاربر تبدیل نمی‌شود. **پنل:** هر ردیفِ اکانت سهمیهٔ ساعتی و نشانِ «در حالِ گرم‌شدن» را نشان می‌دهد و فرمِ «🧬 هویت» خروجی/پروکسی/UA را ست می‌کند. تست: ضریبِ گرم‌شدن، سقفِ هر پلتفرم، توقفِ اکانتِ پرمصرف، آخرین‌چارهٔ استخرِ پر، فاصلهٔ حداقلی، پینِ خروجی در هر دو جهت، رسیدنِ proxy/UA به موتور، ثبتِ مصرف در دانلودِ واقعی، و دست‌نخوردنِ قواعدِ فریز. **اعمال:** `cookies`/`tasks_download`/`downloader` روی نودِ دانلود اجرا می‌شوند → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — استخرِ سشن V3: واکنشِ **هوشمند** به خطا + کوکی فقط وقتی لازم است + ورودِ انسان از داخلِ تلگرام. **(۰) بزرگ‌ترین بُرد صفر خطِ منطق داشت:** طبقِ ویکیِ yt-dlp، یوتیوب کوکی را روی سشنی که هنوز باز است **می‌چرخاند**؛ پس export از پنجرهٔ عادی همیشه زود می‌میرد. روالِ درست (ناشناس → لاگین → همان تب → `robots.txt` → export → بستنِ پنجره **بدونِ لاگ‌اوت**) حالا روی صفحهٔ کوکی‌ها چاپ می‌شود. **(۱) کوکی فقط وقتی لازم است:** یوتیوب ناشناس ~۳۰۰ ویدیو/ساعت می‌دهد (با لاگین ~۲۰۰۰)، ولی ما به **هر** دانلود کوکی می‌چسباندیم و بی‌دلیل اکانت می‌سوزاندیم. پلتفرم‌های `_ANON_FIRST` اول ناشناس تلاش می‌کنند و فقط روی خطای کوکی‌محور به کوکی ارتقا می‌دهند (`dl_cookie_when_needed`). اینستاگرام دسترسیِ ناشناس ندارد و همیشه کوکی می‌گیرد. **(۲) دسته‌بندیِ خطا به‌جای شمارندهٔ واحد:** `classify_error()` → `rate_limit` / `checkpoint` / `login_required` / `bot_check` / `unrelated`. محدودیتِ نرخ **هیچ ضربه‌ای** نمی‌زند (یعنی *ما* تند رفته‌ایم؛ ضربه‌زدن یعنی دورانداختنِ اکانتِ سالم)، چک‌پوینت اکانت را **فریز** می‌کند (وضعیتِ جدیدِ `FROZEN` هرگز انتخاب نمی‌شود) و فقط لاگین/بات‌چک شمارنده را بالا می‌برد. **(۳) ورودِ انسان:** روی چک‌پوینت، ربات به ادمین DM می‌دهد با سه دکمه، و ادمین می‌تواند کوکیِ تازه را **همان‌جا در تلگرام** بچسباند — هندلرِ پیست در روترِ ادمین است و وقتی انتظاری ثبت نشده `SkipHandler` می‌دهد تا مسیرهای بعدی دست‌نخورده بمانند؛ callback به‌جای نامِ فایل یک توکنِ کوتاهِ Redis می‌برد (سقفِ ۶۴ بایت). صفِ «نیازمندِ رسیدگی» در پنل + دکمهٔ «رسیدگی شد» (`unfreeze`). **بازآرایی:** توابعِ پذیرشِ کوکی از `admin_web` به `cookies.py` منتقل شدند چون رباتْ هم به آن‌ها نیاز دارد و نباید به فرآیندِ پنل (aiohttp/jinja) وابسته شود. **آنچه عمداً نساختیم:** لاگینِ خودکار با یوزر/پسورد — از IPِ دیتاسنتر سریع‌ترین راهِ بن است، ۲FA می‌خواهد و پسورد را وارد سیستم می‌کند. تست: ده دستهٔ خطا، بی‌اثربودنِ ۵ محدودیتِ نرخ، فریز/عدمِ‌انتخاب/آزادسازی، تک‌تلاشِ ناشناسِ یوتیوب، ارتقا به کوکی روی بات‌چک، کوکیِ همیشگیِ اینستاگرام، DMِ سه‌دکمه‌ای با توکنِ کوتاه، اعتبارسنجیِ پیست، و وجودِ راهنما در صفحه. **اعمال:** `tasks_download`/`cookies` روی نودِ دانلود اجرا می‌شوند → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — کشِ دانلود برای **همهٔ فایل‌ها**: چهار سوراخ که بیشترِ بُردِ کش را می‌گرفتند بسته شد. **(۱) فقط ویدیو/صوت کش می‌شد** (`kind not in ("video","audio") → return`) — حالا هر نوعی: عکس، سند، PDF، آرشیو. **(۲) اینستاگرام/توییتر اصلاً کش نمی‌شد**، چون `put_cached` تنها در `_deliver_single` صدا زده می‌شد و آن شاخه پشتِ `engine != "gallerydl"` بود؛ حالا `_spawn` هم `url`/`selector` می‌گیرد و تک‌فایلِ گالری (ریلز/عکسِ تکی) را کش می‌کند. **(۳) کلید URLِ خام بود**، پس `youtu.be/X`، `watch?v=X`، `shorts/X` و `watch?v=X&si=…` چهار ردیفِ جدا می‌ساختند و لینکِ فورواردشده از تلگرام (که تقریباً همیشه `si=` دارد) هیچ‌وقت اصابت نمی‌کرد — `_cache_url()` حالا شناسهٔ محتوایی می‌سازد (`yt:`/`ig:`/`x:`/`tt:`) و برای بقیه فقط پارامترهای ترکینگِ **فهرست‌شده** را حذف می‌کند (پارامترِ ناشناخته حفظ می‌شود: بدترین حالتش یک miss است، ولی حذفِ اشتباه یعنی تحویلِ فایلِ **غلط**). کشِ موجود بی‌ارزش نمی‌شود: `get_cached` کلیدِ قدیمی را هم می‌زند و ردیف را زیرِ کلیدِ نو کپی می‌کند. **(۴) کاروسل/آلبوم کش نمی‌شد** — ستونِ `DownloadCache.items` (JSON) فهرستِ مرتبِ `file_id`ها را نگه می‌دارد، `_deliver_album` حالا پاسخِ `send_media_group` را (که تا امروز دور ریخته می‌شد) جمع می‌کند، و بارِ بعد آلبوم مستقیم از `file_id`ها بازپخش می‌شود. **درستی:** `deliver_from_cache` دیگر `None` برنمی‌گرداند بلکه bool است — روی `TelegramBadRequest` (file_idِ باطل) ردیف را پاک می‌کند و `False` می‌دهد؛ `routers/download.py` همان پیامِ وضعیتِ ارسال‌شده را لنگرگاهِ دانلودِ عادی می‌کند. پس یک `file_id`ی مرده دیگر دانلود را نمی‌شکند. **کنترل:** کلیدِ زمانِ‌اجرای `dl_cache_enabled` (`config` + `RUNTIME_KEYS` + ردیفِ پنل) برای دیباگ. دو تلهٔ aiogram که سرِ راه خوردیم و در gotchaها ثبت شد: مدل‌های `InputMedia*` **frozen**‌اند (کپشن باید سرِ ساخت داده شود) و `post_caption` خام ذخیره می‌شود پس سرِ ارسالِ آلبوم باید escape شود. تست: نرمال‌سازی (۶ شکلِ یوتیوب → یک کلید، پارامترِ ناشناخته حفظ، ترکینگ حذف)، کش‌شدنِ هر شش نوعِ فایل، غنی‌ماندنِ کارتِ کش‌شده، رفت‌وبرگشتِ کاروسل با ترتیب/کپشن/نوع، شکستنِ >۱۰ آیتم به چند گروه، file_idِ باطل → حذفِ ردیف + False، و مهاجرتِ کلیدِ قدیمی. **اعمال:** `dl_cache`/`tasks_download` روی نودِ دانلود اجرا می‌شوند → هم `telabzar update` هم `node/update.sh`.
- 2026-07-25 — صفحهٔ آمار بازنویسی و غنی شد + ستونِ `File.platform`. **دیتایی که داشتیم و دور ریخته می‌شد** حالا نمایش داده می‌شود: `Job.finished_at − created_at` (میانگین و p95ِ زمانِ هر عملیات — تا امروز هیچ‌جا استفاده نمی‌شد)، `Job.error` (پرتکرارترین خطاها)، نرخِ موفقیت **به تفکیکِ op** (کدام عملیات می‌شکند)، `File.owner_id` (کاربرانِ برتر)، `File.duration` (مجموعِ مدتِ رسانه)، `File.width/height` (توزیعِ کیفیت)، `File.size` (توزیعِ حجم)، `File.name` (توزیعِ فرمت)، `User.lang`، و `DownloadCache` (تعداد، تحویلِ آنی، حجمِ صرفه‌جویی‌شده). **نوارِ بازهٔ زمانی** (۲۴ ساعت/۷ روز/۳۰ روز/کل) اضافه شد و همهٔ اعداد به آن پاسخ می‌دهند. **ستونِ جدیدِ `File.platform`** (+ `ALTER … IF NOT EXISTS`): شمارنده‌های `dlstat:` در Redis فقط ۲ روز عمر دارند، پس بدونِ این ستون آمارِ تاریخیِ «یوتیوب در برابر اینستاگرام» ساخته نمی‌شد — از این پس پر می‌شود (برای دادهٔ گذشته خالی می‌ماند). **باگی که سرِ راه پیدا شد:** `deliver_from_cache` ستونِ تازهٔ `post_caption` را حمل نمی‌کرد، یعنی تحویلِ آنی از کش کارتِ فقیرتری از دانلودِ واقعی می‌ساخت (بدونِ کپشنِ پست) — `DownloadCache` حالا `post_caption`/`platform` را هم نگه می‌دارد و `hits` را می‌شمارد تا سودِ کش قابلِ‌سنجش باشد. **کارایی:** پنج ایندکسِ جدید روی `files.created_at/platform`, `jobs.created_at/status`, `users.created_at` + کشِ ۶۰ ثانیه‌ایِ Redis برای کلِ payload. **قابلیتِ حمل:** باکت‌بندیِ روز و p95 در پایتون انجام می‌شوند چون `date_trunc`/`percentile_cont` فقط Postgres‌اند و تست‌ها روی SQLite می‌دوند. **باگِ نمودار:** نسخهٔ اول هر سری را جدا نرمال می‌کرد، پس روزی با ۱ ثبت‌نام و روزی با ۳۰ فایل هم‌اندازه درمی‌آمدند؛ حالا نمودارِ انباشته با **مقیاسِ مشترک** است و اوجِ روزانه در سربرگ نوشته می‌شود. تست: هر چهار بازه، پاسخ‌دهیِ اعداد به بازه، مقیاسِ مشترکِ نمودار، و استخراجِ همهٔ داده‌های تازه. **اعمال:** فقط مستر (`telabzar update`) — `admin_web`/`models`/`db` روی نود اجرا نمی‌شوند، ولی `dl_cache`/`tasks_download` روی نودِ دانلود اجرا می‌شوند، پس برای پرشدنِ `platform` روی نود هم `node/update.sh` لازم است.
- 2026-07-24 — رفعِ باگ: کپشنِ پستِ اینستاگرام روی **نودِ دانلود** نمی‌آمد (یوتیوب سالم بود). ریشه ربطی به استخراجِ کپشن نداشت — `_gallery_caption` درست کار می‌کرد. `download_gallerydl` خروجی را در **خودِ workdir** می‌نوشت و بعد کلِ درخت را پیمایش می‌کرد؛ روی نود، `cookies.materialize()` کوکی را در `workdir/ck/<name>` می‌نویسد (نود `COOKIES_DIR` ندارد)، پس آن `.txt` هم به‌عنوان فایلِ دانلودشده شمرده می‌شد → یک ریلزِ **تکی** دو فایل به‌نظر می‌رسید، به شاخهٔ **آلبوم** می‌رفت و اصلاً کارت/کپشنِ پست نمی‌ساخت. بی‌سروصدا بود چون `_deliver_album` بر اساسِ پسوند فیلتر می‌کند و `.txt` را دور می‌ریخت، پس کاربر فقط ویدیو را می‌دید. روی مستر رخ نمی‌داد (مسیرِ کوکی بیرونِ workdir است) — یعنی فقط با نود بازتولید می‌شد. رفع: موتور در زیرشاخهٔ اختصاصیِ `workdir/gl/` می‌نویسد و فایل‌ها **فقط** از همان‌جا جمع می‌شوند (`_gallery_caption` هم روی همان دایرکتوری). تست: نودِ با کوکی داخلِ workdir → ریلزِ تکی یک فایل می‌ماند و کپشن می‌آید، کاروسلِ واقعی همچنان به آلبوم می‌رود، و مسیرِ مستر بدونِ تغییر. **اعمال:** `downloader.py` روی نودِ دانلود اجرا می‌شود → `node/update.sh` روی نود لازم است.
- 2026-07-24 — کارت دو حالتِ کپشن گرفت (کپشنِ اصلیِ پست vs کپشنِ فنی). بلاک‌کوتی که در تغییرِ قبلی دورِ **کلِ** کپشن پیچیده شده بود برداشته شد؛ حالا کپشن از حالتِ کیبورد پیروی می‌کند: **جمع‌شده** (پیش‌فرضِ فایلِ لینک و همان چیزی که دکمهٔ «بازگشت» برمی‌گرداند) = فقط متنِ اصلیِ پستِ مبدأ در یک `<blockquote expandable>`ِ بسته؛ **باز** (منوی کاملِ عملیات) = همان کپشنِ سادهٔ قدیمی، `🎬 نام` + `📦 حجم · 🎞 کیفیت · ⏱ مدت · فرمت`، **بدونِ هیچ کوتِ دورِ کل** (فقط لاگِ تغییرات کوتِ کوچکِ خودش را دارد). ستونِ جدیدِ `File.post_caption` (+ یک `ALTER … IF NOT EXISTS` در `db.py:_MIGRATIONS`) متنِ **خامِ بدونِ HTML** را نگه می‌دارد؛ `tasks_download._post_text()` آن را می‌سازد — اینستاگرام/توییتر از همان `gallery_caption` که تا امروز محاسبه می‌شد ولی برای **تک‌فایل دور ریخته می‌شد** (فقط آلبوم مصرفش می‌کرد)، و یوتیوب از عنوان + کانال + توضیحات — و هر دو از `clean_caption()`ِ موجود رد می‌شوند (حذفِ هشتگ، جمعِ خطوط، سقفِ ۱۰۲۴ کاراکترِ تلگرام). `cards.post_view()` سرِ رندر escape می‌کند، چون یک `<` در کپشنِ واقعیِ پست کلِ پیام را برای تلگرام خراب می‌کند. سوییچ یک‌جا است: `view_caption(collapsed=…)`؛ `set_card_note(collapsed=True)` را **فقط** `op_collapse` می‌دهد، پس پیشرفت/خطا/محدودیت همیشه فنی می‌مانند. پستِ بی‌کپشن به نمای فنی برمی‌گردد تا کارت هرگز خالی نماند، و فایل‌های آپلودیِ کاربر (بدونِ `post_caption`) دقیقاً مثلِ قبل رفتار می‌کنند. یک تغییرِ رفتار: بعد از اتمامِ عملیات کارت **باز** می‌ماند (`update_card`/`move_card_below` با `collapsed=False`) تا حجم/کیفیتِ تازه دیده شود؛ قبلاً جمع می‌شد که با قاعدهٔ جدید یعنی نتیجه پنهان می‌ماند. آلبوم/پستِ گروهیِ اینستاگرام طبقِ درخواست دست‌نخورده. تست: رندرِ دقیقِ هر دو حالت، سوییچِ دو دکمه، fallbackِ پستِ بی‌کپشن، امن‌بودنِ HTMLِ خام، سقفِ ۱۰۲۴ کاراکتر، دست‌نخوردنِ فایلِ آپلودی، و ساختِ متنِ یوتیوب/اینستاگرام. **اعمال:** `tasks_download` روی نودِ دانلود و `tasks`/`cards` روی نودِ پردازش اجرا می‌شوند → علاوه بر `telabzar update` روی مستر، `node/update.sh` روی هر نود.
- 2026-07-24 — ویدیوی سالم: کانتینرِ همیشه‌MP4، زمان/ابعاد/کاورِ درست، و کپشنِ بلاک‌کوتِ بسته. چهار ریشهٔ مستقل پیدا و رفع شد. **(۱) فرمتِ غیرmp4 از یوتیوب:** `--merge-output-format mp4` فقط وقتی اثر دارد که yt-dlp دو استریم را merge کند؛ اگر سلکتور به فایلِ **از پیش mux‌شده** برسد (شاخهٔ `/b` — یوتیوب اغلب webm/VP9 می‌دهد) merge‌ای نیست پس remuxی هم نیست، و اگر کدک‌ها با mp4 سازگار نباشند yt-dlp خودش به **mkv** برمی‌گردد و فقط warn می‌دهد. هیچ `-S`ای هم نبود، پس VP9/Opus انتخابِ اول بود. حالا `_FORMAT_SORT = res,vcodec:h264,acodec:aac,ext:mp4:m4a` (رزولوشنِ انتخابیِ کاربر اول، بعد کدکِ سازگار) + `downloader._ensure_mp4()` که هر خروجیِ غیرmp4 را **فقط کانتینر** remux می‌کند (`-c copy`، بدونِ انکودِ مجدد، با faststart) و اگر شکست خورد فایلِ اصلی را نگه می‌دارد. **(۲) کاور/زمانِ لینک‌های gallery-dl:** `paths = [(p, {}, None)]` یعنی info و تامبنیلِ خالی؛ فقط عکس‌ها با PIL جبران می‌شدند و ویدیوها (ریلزِ اینستاگرام/توییتر) بدونِ ابعاد، بدونِ مدت و بدونِ کاور به تلگرام می‌رفتند. **(۳) بزرگ‌ترین باگ — متادیتا بعد از پردازش به‌روز نمی‌شد:** شاخهٔ «عملیاتِ رسانه‌ساز» در `run_op` فقط `name/size/kind/changelog` را عوض می‌کرد و `width/height/duration` **هرگز** از خروجی خوانده نمی‌شد؛ تلگرام هم هرچه بفرستیم باور می‌کند، پس ویدیوی ۳۰ثانیه‌ایِ برش‌خورده با زمانِ ۱۰:۰۰ اصل و ویدیوی ۴۸۰p با قابِ ۱۰۸۰p نمایش داده می‌شد (کارتِ spawn مثلِ استخراجِ صدا هم اصلاً duration نداشت). **(۴) سقوطِ بی‌صدا به سند:** `send_card` روی هر `TelegramBadRequest` مستقیم `send_document` می‌کرد، پس یک تامبنیلِ نامعتبر ویدیو را بی‌سروصدا به سند تبدیل می‌کرد. رفع: `processing.probe_media()` منبعِ یکتای ffprobe شد (`downloader._ffprobe_video` به آن واگذار می‌کند)؛ `tasks._refresh_media_meta()` بعد از **هر** عملیاتِ رسانه‌ساز و روی کارتِ spawn اجرا می‌شود (و در rollbackِ خطا برمی‌گردد)؛ `tasks_download._media_meta()` درِ ورودیِ **همهٔ** موتورها شد و سه تضمین می‌دهد (mp4 + ابعاد/مدت از فایل + پوسترِ ≤۳۲۰px وقتی موتور تامبنیل نداده)؛ `send_card` قبل از سقوط به سند یک‌بار **بدونِ تامبنیل** دوباره تلاش و خطا را لاگ می‌کند. **کپشن:** `card_caption()` حالا یک `<blockquote expandable>`ِ **بسته** است (نام + خطِ اطلاعات + لاگِ تغییرات)؛ چون تلگرام بلاک‌کوتِ تودرتو را نمی‌پذیرد، لاگِ تغییرات از بلاک‌کوتِ جدا به خطِ ساده داخلِ همان بلاک تبدیل شد، و `note` (نوارِ پیشرفت/ویرایشگرِ متادیتا) عمداً بیرونِ بلاک ماند تا وقتی کوت بسته است هم دیده شود. آلبومِ گروهیِ تلگرام طبقِ درخواست دست‌نخورده. تست‌ها با ffmpegِ واقعی (نه ماک): remuxِ webm→mp4 بدونِ انکودِ مجدد، برش→زمانِ تازه، کاهشِ ابعاد→ابعادِ تازه، صوت→پاک‌شدنِ ابعادِ کهنه، پرشدنِ متادیتای gallery-dl، تک‌بلاک‌کوت‌بودنِ کپشن، و retryِ بدونِ تامبنیل. **اعمال:** چون `tasks_download`/`downloader` روی **نودِ دانلود** و `tasks`/`processing` روی **نودِ پردازش** اجرا می‌شوند، علاوه بر `telabzar update` روی مستر، روی هر نود هم `sudo bash node/update.sh` لازم است.
- 2026-07-24 — Panel UI/UX audit: pixel review of all 9 pages → fixed real layout bugs, the RTL bidi bugs, and unified the grid/spacing. **Root cause of the layout bugs: four classes were used in templates but never defined in `_CSS`** — `.pad` (×6 on cookies/buttons/nodes), `.hint`, `.tabs`/`.tab` — so those blocks rendered with **zero padding, edge-to-edge against the card border**, and the buttons page's file-kind tabs were bare run-together links. Defined all of them (+ `.tag` promoted from the `.card h3`-scoped rule so standalone chips like the `/texts` counter render as chips). **RTL bidi (wrong data on screen, not just ugly):** Latin/numeric runs inside the `dir=rtl` page were reordered by the bidi algorithm — users showed `22:12 2026-07-24` instead of `2026-07-24 22:12`, stats showed `MB 975.0`, and the cookie textarea rendered the Netscape header backwards. Added `.mono/.num/.ltr` isolation utilities + `<bdi>` at the mixed-content sites, `dir=ltr` on the cookie/`.cmd` code boxes. Note `.num` forces `direction:ltr`, so the health cookie-pool line (mixed Persian+numbers) was moved off it to `<bdi>`-per-number. **Grid/spacing:** one 16px vertical rhythm (`.grid2`/`.col` gap, `.body>.card+.card`, and `form>.card+.card` — settings cards live inside a `<form>`, so the flex gap never applied to them and they sat 8px apart); 18px horizontal card padding everywhere; `.inp` 150→160px to match `.sel`; messages that are direct children of a card (`.saved/.errbox/.note/.empty`) get the same inset. **Texts page** was ~183px per item × 205 items: the save button now sits inline beside the textarea (~134px/item) and the textarea switched from a dark code box to the panel's light style (it edits UI copy, not code). **Responsive** (there was none): under 860px the sidebar becomes a horizontal top nav, under 560px paddings/table cells tighten, and the users table scrolls in a `.tbl-wrap` instead of wrapping dates. **Dead CSS** removed: the `.up` upload-form grid (V2 replaced the file upload with paste). **Bug found while re-testing:** a pasted cookie with a BOM/zero-width char failed JSON parsing (`str.strip()` doesn't strip U+FEFF) — `_normalize_cookie_text` now strips them. Verified by rendering every real page with seeded data and screenshotting at 1440/820/500px before and after each fix; full scratchpad suite green (stale cookie-V1 assertions in `admin_d2`/`cookie_json`/`spotify` retargeted to the V2 paste/pool API). Reason: the panel is the only admin surface — undefined classes and bidi-scrambled dates make it look broken and misread real values.
- 2026-07-22 — Initial CLAUDE.md as repo source-of-truth: overview, architecture + module map, verified role hierarchy (admin/user only), dependency versions from the four requirements files, conventions + add-an-op steps, env/deploy, known gotchas; added `docs/telegram-api.md`. Reason: establish a durable, code-backed reference and the mandatory update workflow.
- 2026-07-22 — Runtime-editable texts (Phase A): new `TextOverride` model + `app/textstore.py` (in-process overrides reloaded via Redis `txtver`); `i18n.t()` prefers overrides with format-fallback; panel `/texts` editor (search/edit/reset, placeholder+HTML validation); refresh wired into `DataMiddleware` + both workers. Reason: stop hardcoding user-facing strings — admin can edit any text/label (HTML + premium emoji) with no restart.
- 2026-07-22 — Button styling (Phase B): new `ButtonStyle` model + button funcs in `textstore` (shared `txtver` reload); `file_card_kb` applies per-op `style` (primary/success/danger) + `icon_custom_emoji_id`; panel `/buttons` page (per-op color + premium-emoji id, one-save batch, `clean_button` validation). Reason: admin sets card-button color + premium-emoji icon with no restart.
- 2026-07-22 — `/texts` page redesign: now shows **all** ~204 strings grouped into collapsible prefix-based categories (`_texts_groups`/`_TEXT_CATS`) instead of an empty search-only box; search filters and auto-opens matches; first category open by default. Reason: the previous page looked empty (only overridden shown) — admin needs to browse/edit every string, categorized.
- 2026-07-22 — Card menu layout editor (buttons Phase 2): new `MenuButton` model + `textstore.get/set/reset_menu_layout` (shared `txtver` reload); `file_card_kb` now resolves order + hidden + per-button width (full/half/third → row sizes) with zero-change default that reproduces the old layout. `/buttons` page rebuilt (V3): per-kind tabs, a live simulated-Telegram preview (JS `rebuildPreview`), and a drag-reorder list editing text (per-lang) + color + premium-emoji + width + show/hide in one save. Reason: admin can fully arrange each file-kind's card menu (reorder, hide, row widths) + text/color/emoji, no restart.
- 2026-07-24 — Cookie account pool V2 (retry-next-cookie + paste-based panel). **Reliability (the point):** a cookie that
fails no longer fails the user's download — `run_download` retries with the **next** account (`app/cookies.py:pick` with an
`exclude` set) in both probe and fetch, marking the bad account with an escalating cooldown; the user only gets an error
when no usable account is left. Non-cookie errors (404/too-large) neither roll over nor penalise the pool. **New
`app/cookies.py`** is the single pool authority (status machine healthy/suspect/invalid/cooldown/disabled, LRU-fair
selection, `mark_ok`/`mark_fail`, Redis-mirror materialisation for nodes) — replaces the ad-hoc `_pick_cookies` in
`tasks_download`. **Panel:** the cookies page is now account-centric (V2) — add by **pasting** cookie text (no file
upload; Netscape or Cookie-Editor JSON), per-platform groups with live status/last-success/fail-streak, and in-place
"paste a fresh cookie" that keeps the account's label and history. Validation at add time (required cookie per platform;
YouTube's `LOGIN_INFO` check is free). **Alerts:** admin gets a Telegram DM when a platform's usable accounts fall below
`cookie_alert_min` (new runtime key), throttled to once per 6 h. **Panel bugfixes:** `/texts` items used the page-level
`.save` class (a full-width 44px bar per item across 204 texts) → new compact `.save-sm`; categories no longer auto-open
just because they contain an edited string. Pool logic, rollover end-to-end (incl. "all fail → error only then"), and
mirror/reconcile unit-tested. Reason: with several accounts, one dead cookie should be invisible to users.
- 2026-07-23 — `node/update.sh` — in-place node code update (no re-join). `telabzar update` on the master doesn't touch a node's separately-built image, so node-side fixes (the cookie mirror in `_pick_cookies`, any `run_download`/`run_op` change) never reached a running node — the cookie fix looked broken because the node kept running old code. New `node/update.sh` (run on the node host) reads the running container's env/image/command via `docker inspect`, `git pull`s, rebuilds the role's Dockerfile, and recreates the container preserving env + WG identity. Documented that node-code fixes require it (vs master-only changes). Reason: nodes need their own update path; a master update alone silently leaves them on stale code.
- 2026-07-23 — Cookies invisible on the download node → Instagram "admin must set cookies" (bugfix). The panel stores cookie files on the **master's** disk, but a download node has no cookies dir, so `_pick_cookies` returned `None` on the node and IG/YT-with-cookies ran cookieless there → login-required error even with a fresh cookie uploaded. Fix: the panel **mirrors cookies into Redis** (`ckfiles` + `ckfile:<name>`) on upload/delete and reconciles on startup; `tasks_download._pick_cookies` now takes `workdir` and reads local disk on the master, else the Redis mirror on the node (materialising a temp cookie into the workdir). Rotation/cooldown unchanged (shared Redis). The cookies page shows a node-sync note when a download node is online. Master behaviour is unchanged (still local files). Redis-mirror + node/materialise + reconcile logic unit-tested. Reason: cookies are master-local state a remote node can't see; sharing them via Redis makes IG/YT-with-cookies work on the clean-IP node.
- 2026-07-23 — Downloads split master/node → YouTube "every-other-download fails" (bugfix). Both the master's download-worker and a download node consumed the **same** `arq:queue:dl`, so ARQ round-robined jobs — half ran on the master's flagged datacenter IP (bot-check → fail), half on the node's clean IP (ok), i.e. alternating failures. Fix: the master download-worker now runs `MasterDownloadWorkerSettings` on `arq:queue:dl:master` (compose `command:`); the node still runs `DownloadWorkerSettings` on `arq:queue:dl` (**unchanged → no node re-install**); `download._dl_queue` routes `run_download` to `arq:queue:dl` when a download node is live (all downloads on the clean IP), else `arq:queue:dl:master`. Reaper (`_REAP_MAP`) now also drains `arq:queue:dl`→`arq:queue:dl:master` when no download node is live. Apply: `telabzar update` on the master (rebuilds download-worker); the existing node needs nothing. Pure logic (routing gate, reaper move, worker/compose shape) unit-tested. Reason: with a clean-IP download node, **every** download must run on the node, not half on the master's blocked IP.
- 2026-07-23 — `GET /node/install.sh` returned 404 on the server (bugfix). The panel serves the node installer by reading `node/install.sh` off disk (`admin_web.node_install` → `/srv/node/install.sh`), but `docker/admin.Dockerfile` only `COPY app ./app` — the `node/` dir was never in the admin image, so the handler always hit its "install script not found" 404 (the panel test passed only because it runs from the repo root). Added `COPY node ./node` to the admin image. Any file the panel serves off disk must be copied into the admin image. Rebuild admin (`telabzar update`) to pick it up.
- 2026-07-23 — `telabzar update` self-refreshes the CLI (bugfix). The `telabzar` helper (`/usr/local/bin/telabzar`) was written once by `install.sh:install_cli` and **never regenerated on update**, so new subcommands (`nodes-enable`/`wg-sync`) and the `.nodes-enabled` overlay logic never reached disk — `telabzar nodes-enable` printed the old usage. Now: `install.sh` gains a headless `refresh-cli` mode (`bash install.sh refresh-cli` = re-write the CLI, no prompts), the generated `update` command calls it after `compose up`, and `install_cli` writes atomically (temp + `mv -f`) so overwriting the CLI mid-`update` is safe. One-time bootstrap on an already-updated server: `cd <repo> && sudo bash install.sh refresh-cli` (the old on-disk CLI can't self-refresh until replaced once). Reason: shipped CLI subcommands were invisible after `telabzar update`.
- 2026-07-23 — Master infra auto-provisioning (Phase N5) + panel text-reset fix. **N5-A (host auto-setup):** `node/master-setup.sh` (`telabzar nodes-enable` / installer prompt) sets up WireGuard on the master host, autodetects the public IP, writes all `WG_*`/`NODE_*` vars into `.env`, applies `docker-compose.nodes.yml` (publishes redis/postgres/local-bot-api/pot/gateway on `${WG_MASTER_IP}` — WG-only), and installs a `telabzar-wg-sync` systemd timer. **Declarative WG peers:** the panel only writes `Node` rows; the host `node/wg-sync.sh` fetches them from the new `/node/peers` endpoint (gated by `NODE_SECRET`) and rebuilds `wg0.conf` = `[Interface]` + `nodes.render_peers()` + `wg syncconf` (self-healing, admin container stays unprivileged). CLI auto-adds the overlay when `.nodes-enabled` exists (so `telabzar update` keeps WG exposure); standalone unchanged. **N5-B (no-node → master):** `ops._link_base()` uses `stream_base` only when a `gateway` node is live (`role_online`), else `public_base` — a dead stream node auto-falls-back; downloads (master `download-worker`) and processing (routing + reaper) already fall back. **Panel text-reset fix:** the panel never reloaded `textstore`, so after `telabzar update` it showed defaults and a `/buttons` batch-save overwrote real overrides with defaults (silent loss) — `admin_web._on_startup` now `textstore.load()`s and `texts_page`/`buttons_page` `refresh_if_stale()` per request. Pure/host logic (`render_peers`, `/node/peers` auth, overlay YAML, `_link_base` gating, panel refresh, all `bash -n`) unit-tested; real WG/multi-machine verified on the master server. Reason: make the master's WG/infra one-command-auto, guarantee master-only fallback, and stop panel-set texts resetting on update.
- 2026-07-23 — Distributed nodes (Phase N4, resilience & observability): closed the N2 caveat — new `nodes.reap_orphan_jobs(redis)` moves jobs stranded on `arq:queue:proc` back to the master's `arq:queue` **only when no processing node is live** (claims each with `zrem` before re-adding → no double-run; preserves scores). The main worker runs it every 30 s via a new `worker.startup_master` (master-only, `not node_role`); `WorkerSettings.on_startup` switched to it, download/processing workers keep plain `startup`. Observability: a per-node **jobs-done** counter (`nodes.note_job_done()` in `run_op`/`run_download` finally when `NODE_ROLE` set) rides the heartbeat (`done`) and shows per node in the panel; a **reaped** counter (`nodes:reaped`) shows on the nodes page. Pure logic (reaper move/guard/counter, worker wiring) unit-tested with a fake Redis. Reason: offloaded jobs must never hang if a node blips, and the admin needs to see each node actually doing work.
- 2026-07-23 — Distributed nodes (Phase N3, gateway/stream role): new `app/gateway_node.py` — a public reverse proxy that forwards `/dl` + `/s` to the master's gateway over WireGuard, streaming the body while preserving Range/Content-Range/status (206/HEAD/404 all pass through). Gives a **clean/dedicated public streaming IP** off the master (grey-cloudable) with no DB/Bot API on the node — the token resolves on the master; the node needs only HTTP to the master gateway (`NODE_GATEWAY_URL`) + Redis for its own heartbeat (role `gateway`). New `gateway` role in `nodes.ROLES` (a **service** role: carries `command` = `python -m app.gateway_node`, not `queue`/`worker`), and `node_config()` now emits `queue`+`settings` for worker roles vs `command` for service roles; `node/install.sh` branches accordingly (`arq <settings>` vs the command) and passes `NODE_GATEWAY_URL`. New runtime `stream_base` setting (`config` + `settings_store.RUNTIME_KEYS` + panel `GROUPS`) read via `ops._link_base()` — when set, `/dl` `/s` links point at the gateway node's public domain, else `public_base` (zero change when unset). Health page shows the proc queue from N2; the gateway role auto-appears in the add-node dropdown. Real reverse-proxy path (Range/HEAD/404/502) integration-tested against a live upstream in-process; real multi-machine + public TLS verified on the master server. Reason: offload public link/stream serving to a clean-IP node, the third node type from the master/node plan.
- 2026-07-23 — Distributed nodes (Phase N2, processing/offload role): remote `run_op` on nodes. New `tasks._localize(bot, fid, workdir)` — the single input seam: returns the shared-disk path on the master, else `bot.download_file()`s into the workdir (remote node); all ~8 `get_file().file_path` sites in `_do_op`/`run_op` now go through it (output was already node-safe via `FSInputFile` multipart). New `processing` role in `nodes.ROLES` (queue `arq:queue:proc`, image `worker`) + `ProcessingWorkerSettings(WorkerSettings)` (that queue). Enqueue-time routing: `ops._op_queue` sends an op to `arq:queue:proc` only when it is in `nodes.OFFLOAD_OPS` **and** a processing node is live (`nodes.role_online`), else the master's default queue (zero regression when no node). `node/install.sh` now builds the role's Dockerfile (`docker/${IMAGE}.Dockerfile`, e.g. the full `worker` image) instead of hardcoding download-worker; health page shows the `arq:queue:proc` depth; processing role auto-appears in the panel's add-node dropdown. Pure logic (localize disk/remote branches, routing gate, roles/worker shape) unit-tested; real multi-machine offload verified on the master server. Reason: offload heavy CPU ops (compress/convert/transcribe/…) to a dedicated processing node, proving the remote download-input/upload-output path N1 flagged.
- 2026-07-23 — Distributed nodes (Phase N1, download/clean-IP role): new `app/nodes.py` master-side layer (roles, HMAC-signed **one-time** WireGuard join token in Redis, WG-IP allocation, live registry via `node:{id}` heartbeat, WG peer add/remove through the config file + `wg syncconf`, `node_config()` join reply) + `Node` model (`nodes` table, auto-created). `bot.py` uses `is_local=False` when `NODE_ROLE` is set (remote HTTP download / multipart upload); `worker.py` startup spawns a 20 s heartbeat for node processes. Panel gains a **🖧 Nodes** page (add → one-time install command, live online/offline list with load, remove → strips WG peer) + public `/node/join` API and `/node/install.sh` serving (master base injected). New `node/install.sh` (curl-piped, root): installs WireGuard+Docker, generates a WG keypair, joins with the one-time token, brings up the tunnel, and runs the role's ARQ worker against the master's Redis over WG. README + config node/WG env vars added. Pure logic (token/IP/peer/config) unit-tested; real `wg` + multi-machine join must be verified on the master server. Reason: begin the Master/Node distributed architecture — offload downloads to a clean-IP node, admin-provisioned entirely from the panel.
