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
- **Download worker** (`arq app.worker.DownloadWorkerSettings`) — queue `arq:queue:dl`, runs `run_download`.
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
| `app/models.py` | ORM: `User`, `File`, `Setting`, `DownloadCache`, `Job`, `TextOverride`, `ButtonStyle`, `MenuButton`, `Node` |
| `app/middlewares.py` | `DataMiddleware`: per-update DB session, get/create user, inject `lang`+`is_admin`, block-gate |
| `app/routers/start.py` | `/start`, language pick |
| `app/routers/admin.py` | `/admin` (list/get/set/reset/health) + `/panel`, admin-only |
| `app/routers/files.py` | `on_file` intake → `File` row → card; text fallback |
| `app/routers/ops.py` | All op button/FSM handlers; `_enqueue`; `_op_queue` (routes heavy ops to a live processing node's `arq:queue:proc`); limits; collection (zip/merge/img_pdf/vjoin) flow |
| `app/routers/download.py` | URL intake, platform UX (probe/quick), dl limits, `Dl` menu |
| `app/keyboards.py` | `OPS_BY_KIND` menus, card/collection/download keyboards; `file_card_kb` applies the admin menu layout (order + hidden + per-button width→rows via `_rows_from_widths`) |
| `app/callbacks.py` | Typed `CallbackData` factories (<64 B): `Act,Conv,Meta,Cmp,Wm,Rsz,Rot,Spd,Tr,Dl,Lang` |
| `app/states.py` | FSM states (rename, meta edit, watermark, trim, screenshot, collect, …) |
| `app/cards.py` | Send/update the card (file + keyboard), spawn new cards, progress note |
| `app/tasks.py` | `run_op` (ARQ) + `_do_op` op dispatch; live status ticker; `_localize()` resolves every input to a local path — disk path on the master, HTTP download on a remote node (the only remote-input seam) |
| `app/tasks_download.py` | `run_download` (ARQ): probe→menu / fetch→size-check→spawn; rich-post/album delivery |
| `app/processing.py` | ffmpeg/Pillow ops; `_run` subprocess contract (progress/cancel/`ProcessingCancelled`) |
| `app/downloader.py` | Engine routing (`platform_of`/`engine_for`), yt-dlp/gallery-dl/cobalt/Spotify, YT-match scorer |
| `app/settings_store.py` | Runtime config: Postgres (durable) + Redis (live, read-through); `RUNTIME_KEYS`/`ENUM_VALUES` |
| `app/textstore.py` | Runtime UI overrides: bot texts/labels, per-op button `style`+`icon_emoji_id`, **and per-kind card menu layout** (`TextOverride`/`ButtonStyle`/`MenuButton`, Postgres) via one in-process dict reloaded on the Redis `txtver` counter; `validate()`, `clean_button()`, `get_menu_layout()` |
| `app/admin_web.py` | Web panel: settings/texts/buttons/health/users/stats/cookies/**nodes**; `GROUPS` = panel rows; node join API (`/node/join`) + install-script serving (`/node/install.sh`) |
| `app/nodes.py` | Distributed **master-side** node layer: `ROLES` (download, processing, gateway), `OFFLOAD_OPS`, `role_online()`, `reap_orphan_jobs()` (proc→master when no proc node) + `note_job_done()`/`reaped_count()` counters, signed one-time WireGuard join token, WG-IP allocation, live registry (Redis `node:{id}` heartbeat, 45 s TTL), WG peer add/remove (config-file + `wg syncconf`), `node_config()` (join reply — worker roles carry `queue`+`settings`, service roles carry `command`) |
| `app/gateway.py` | `/dl` + `/s` file serving (Range, faststart-friendly, token→path cache) |
| `app/gateway_node.py` | **Gateway-node** (Phase N3): a public reverse proxy that forwards `/dl` + `/s` to the master's gateway over WG (streams body + Range/Content-Range/status), giving a clean streaming IP off the master. Needs no DB/bot (token resolves on master); own heartbeat (role `gateway`) |
| `app/security.py` | ClamAV INSTREAM scan |
| `app/filetypes.py` | `detect()` message→`FileInfo`; kind = image/video/audio/document/pdf/archive/app |
| `app/i18n.py` + `app/locales/{fa,en}.py` | `t(lang, key, **kw)` + message tables (keys must stay in parity) |
| `app/dl_cache.py` | `DownloadCache` helpers (link+quality → prior `file_id`, skip re-download) |
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
  3. `tasks.py:_do_op` → add the `if op == "…":` branch; return `{"path","filename","label","kind"}`. Resolve **every** input file_id via `_localize(bot, fid, workdir)` (never `get_file().file_path` directly) so the op runs on a remote node too.
  4. `processing.py` → implement the work via the `_run` contract (`progress`, `cancel`, `ProcessingCancelled`).
  5. If tunable → `config.py` default + `settings_store.RUNTIME_KEYS` (+`ENUM_VALUES`) + `admin_web.GROUPS` row; read via `settings_store`.
  6. If it is CPU-heavy → add the op to `nodes.OFFLOAD_OPS` so it offloads to a live processing node (skip for light ops and anything needing a master-only service, e.g. `scan`/ClamAV).
- **Schema changes:** add the column to `models.py` **and** an idempotent `ALTER … IF NOT EXISTS` to `db.py:_MIGRATIONS` (no Alembic). A brand-new **table** needs no migration line — `create_all` creates it.
- **User-facing strings are runtime-editable:** every string lives in `locales/{fa,en}.py` as the default and is overridable per-(lang,key) from the panel `/texts` page (`textstore`). Keep placeholders (`{n}`, …) stable when adding/renaming a string — the override validator rejects unknown placeholders, and `t()` silently falls back to the default if an override fails to format.

## 6. Environment & Deployment
**Env vars** (names only; source of truth = fields of `app/config.py:Settings`, env name = UPPER_SNAKE of each field):
- Required: `BOT_TOKEN`. Common: `ADMIN_IDS`, `DEFAULT_LANG`, `MAX_FILE_MB`, `LOCAL_API_BASE`, `REDIS_URL`, `POSTGRES_DSN`, `WORK_DIR`.
- Processing: `VIDEO_ENCODER`, `COMPRESS_SPEED`, `COMPRESS_TINY_TARGET_MB`, `COMPRESS_TINY_HEIGHT`, `VJOIN_MAX_MB`, `WHISPER_MODEL`.
- Security/limits: `CLAMAV_HOST`, `CLAMAV_PORT`, `MAX_EXTRACT_FILES`, `MAX_EXTRACT_MB`, `DAILY_OP_QUOTA`, `RATE_PER_MIN`.
- Gateway: `PUBLIC_BASE`, `GATEWAY_PORT`, `TLS_CERT`, `TLS_KEY`, `STREAM_BASE` (runtime-tunable — when set, `/dl` `/s` links point at a gateway node instead of `PUBLIC_BASE`).
- Downloader: `DOWNLOADER_ENABLED`, `DL_ALLOW_UNKNOWN`, `DL_RICH_POSTS`, `PROXY_URL`, `COOKIES_DIR`, `POT_PROVIDER_URL`, `DL_POT_ENABLED`, `DL_DEFAULT_UX`, `DL_MAX_SIZE_MB`, `DL_MAX_DURATION_MIN`, `DL_DAILY_COUNT`, `DL_DAILY_MB`, `DL_CONCURRENCY`, `DL_COOLDOWN_SEC`, `DL_OP_DAILY_MIN`, `DL_MIN_FREE_GB`, `DL_SPONSORBLOCK`, `DL_SUBS`, `COBALT_URL`, `COBALT_API_KEY`.
- Spotify: `SPOTIFY_ENABLED`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_META`, `SPOTIFY_MAX_TRACKS`, `SPOTIFY_SOURCE`, `SPOTIFY_MATCH_MIN`, `SPOTIFY_YT_FALLBACK`.
- Panel: `ADMIN_PORT`, `ADMIN_BASE`, `ADMIN_SECRET`.
- Nodes — master side (one-time WG setup): `NODE_SECRET` (HMAC key for join tokens; falls back to `BOT_TOKEN`), `WG_INTERFACE` (`wg0`), `WG_SUBNET` (`10.51.0.0/24`), `WG_MASTER_IP` (`10.51.0.1`), `WG_MASTER_PUBKEY`, `WG_ENDPOINT` (`host:51820`), `WG_CONFIG_PATH` (`/etc/wireguard/wg0.conf`), and the internal addresses handed to nodes (`NODE_REDIS_URL`, `NODE_POSTGRES_DSN`, `NODE_API_BASE`, `NODE_POT_PROVIDER_URL`, `NODE_GATEWAY_URL` — all on the master's WG IP; the last is the master gateway a gateway node reverse-proxies to).
- Nodes — node side (set by `node/install.sh`, not by humans): `NODE_ROLE` (presence = "I am a node" → `is_local=False` + heartbeat), `NODE_ID`, `NODE_NAME`.
- The runtime-tunable subset (editable live via `/admin` or the web panel, no restart) = keys in `settings_store.RUNTIME_KEYS`.

**Run:** `docker compose up -d` (services: `local-bot-api`, `postgres`, `redis`, `clamav`, `bot`, `worker`,
`download-worker`, `gateway`, `admin`, `bgutil-pot-provider`; volumes: `tg-bot-api-data`, `pg-data`,
`redis-data`, `work-data`, `clamav-data`). Dockerfiles in `docker/`. Adding a Python dep to the download path
requires rebuilding **`download-worker`** (`docker compose build download-worker && docker compose up -d download-worker`).

**Tests / lint / CI:** none committed — no `tests/` dir, no CI workflow, no lint config in the repo.
Verification is currently done with ad-hoc scratchpad scripts outside the repo (see Open Questions).

## 7. Known Gotchas
- **Local Bot API server**: files are on its disk; `bot.get_file(file_id)` can trigger a full download from Telegram DC on first call (slow) — workers/gateway use long `request_timeout` (600 s). Upload ceiling ≈ `MAX_FILE_MB` (2000); larger files can't be carded/served.
- **Read-only `/cookies` mount**: yt-dlp/gallery-dl must copy the cookie to a writable temp first (`downloader._writable_cookie`), else `OSError: read-only file system`.
- **Cross-process settings staleness**: `settings_store` is read-through Redis (durable copy in Postgres), NOT an in-process TTL cache — so a panel change is seen instantly by bot **and** worker. Reading `settings.X` directly bypasses this and silently ignores the panel.
- **yt-dlp deps**: needs Deno (JS runtime) + `bgutil-pot-provider` for YouTube PO tokens. The pot plugin can crash yt-dlp → toggle `DL_POT_ENABLED` off and there is a retry-without-pot path. Datacenter IPs get blocked → route via `PROXY_URL` (your own clean exit).
- **Spotify/Apple are DRM**: never downloaded directly — metadata is resolved then matched to a YouTube recording. Accurate matching needs `ytmusicapi` **installed in the download-worker image** and a proxy that can reach `music.youtube.com`; otherwise it falls back to raw `ytsearch` (less accurate). `SPOTIFY_SOURCE=youtube` forces the fallback.
- **Streaming**: browser playback needs the MP4 `moov` atom up front (`-movflags +faststart`) — applied to downloaded/processed videos, not to raw user uploads. Gateway caches token→path (120 s) so seek/Range requests don't re-hit DB+getFile each time. Keep the streaming subdomain **grey-cloud on Cloudflare** (CF ToS §2.8 restricts proxying video; also adds buffering).
- **Callback 64-byte cap**: never pack large data into `CallbackData`; store in Redis, pass a token.
- **No Alembic**: schema evolves via idempotent `ALTER … IF NOT EXISTS` in `db.py:_MIGRATIONS`.
- **Locale parity**: every key must exist in both `locales/fa.py` and `locales/en.py`.
- **`t()` is sync & hot**: text overrides live in an in-process dict, refreshed only when the Redis `txtver` counter changes (bumped on panel edit) — checked per-update in `DataMiddleware` and per-job in the workers. Do NOT make `t()` async or read the DB on every call. Button styles (`file_card_kb`, per-op via `textstore.get_button_style`) share the same dict + `txtver` reload.
- **Premium/custom emoji**: `<tg-emoji emoji-id=…>` in text and `icon_custom_emoji_id` on buttons require the **bot owner's account to have Telegram Premium**; button `style` (`primary`/`success`/`danger`, the only 3 colors Telegram allows) does not. Only the card op-menu (`OPS_BY_KIND` ops) is styled today. A wrong `icon_emoji_id` can make Telegram reject the whole keyboard — the panel validates it is numeric, but existence isn't checked.
- **Nodes need `is_local=False`**: co-located workers read input straight off the shared Bot API disk (`bot.get_file().file_path`), which does **not** exist on a remote machine. `bot.py` therefore flips to `is_local=False` whenever `NODE_ROLE` is set, so aiogram downloads inputs over HTTP from the (WG-reachable) Bot API and uploads outputs by multipart. A node reaches Redis/Postgres/Bot API only over the WireGuard tunnel (`NODE_*` addresses = master's WG IP); those services must listen on the tunnel. The **input seam is `tasks._localize()`** (Phase N2): it returns the disk path when it exists (master) and otherwise `bot.download_file()`s into the workdir (node) — every `run_op` input now goes through it, so `run_op` is node-safe. Output was already node-safe (all delivery is `FSInputFile` multipart). Heavy ops (`nodes.OFFLOAD_OPS`) route to `arq:queue:proc` only when a **processing** node is live; `scan` stays on the master (it needs the master-side ClamAV service), and the whisper model downloads on the node's first transcribe. If a processing node dies with jobs still queued on `arq:queue:proc`, the master's **reaper** (`nodes.reap_orphan_jobs`, run every 30 s by the main worker via `startup_master`) moves them back to `arq:queue` so they never hang — it only fires when no processing node is live, and claims each job with `zrem` before re-adding (no double-run).
- **Gateway node is a reverse proxy, not a file host**: `gateway_node.py` forwards `/dl` `/s` to the master's gateway over WG and streams the response back (Range preserved) — the file bytes still traverse master→node→client, so the master's **uplink is unchanged**; what you gain is a clean/dedicated public streaming IP (grey-cloud it on Cloudflare, keep it off the master's IP) and TLS/DDoS surface off the master. Token resolution stays on the master, so the node needs **no** DB/Bot API — only HTTP to the master gateway (`NODE_GATEWAY_URL`) + Redis for its heartbeat. Point links at it with the runtime `stream_base` setting (empty → master `public_base`). The master gateway must listen on the WG IP. Public TLS on the node (streaming subdomain cert, or CF in front) is the admin's job — inherent to running a public service. A future download-once/serve-many local cache (cut repeat WG traffic + latency) is out of scope (N4).
- **WireGuard peer automation is best-effort & needs real-server testing**: `nodes.add_peer/remove_peer` append/strip a `[Peer]` block in `WG_CONFIG_PATH` then `wg syncconf` (no tunnel drop). All shell-outs are guarded (`# noqa: BLE001`), so join still returns a valid config even where `wg` is absent (e.g. the sandbox logs `wg config append failed` — expected). The pure logic (token sign/verify/one-time, IP allocation, peer block add/strip, `node_config`) is unit-tested; the actual `wg`/multi-machine join must be verified **on the master server**. Join token is HMAC-signed + **one-time** (Redis `njoin:{jti}`, GETDEL) + 30-min TTL; the reply includes `BOT_TOKEN` (nodes are admin-provisioned & trusted, gated by the one-time token + WG).

## 8. Reference Docs
- `docs/telegram-api.md` — recent Telegram Bot API changelog (10.0→10.2), project-relevant, with sources.
- `docs/ADMIN_PANEL.md` — admin panel / runtime settings notes (pre-existing).

## Open Questions
- **Roles:** the plan hypothesized `owner`/`reseller` tiers; **code has none** — only admin (env) vs user, plus `is_blocked`, and `User.role` is unused. Is a multi-tier/reseller hierarchy intended-but-unbuilt (should this file track it as a gap), or is the two-tier model final?
- **Tests/lint:** no committed test suite, CI, or lint config. Set up `tests/` + a linter (ruff) + CI as a follow-up, or keep verification ad-hoc?
- **Contribution/git conventions** (branch naming, commit trailers) are session-injected, not repo facts — document them here or leave out?

## Changelog
- 2026-07-22 — Initial CLAUDE.md as repo source-of-truth: overview, architecture + module map, verified role hierarchy (admin/user only), dependency versions from the four requirements files, conventions + add-an-op steps, env/deploy, known gotchas; added `docs/telegram-api.md`. Reason: establish a durable, code-backed reference and the mandatory update workflow.
- 2026-07-22 — Runtime-editable texts (Phase A): new `TextOverride` model + `app/textstore.py` (in-process overrides reloaded via Redis `txtver`); `i18n.t()` prefers overrides with format-fallback; panel `/texts` editor (search/edit/reset, placeholder+HTML validation); refresh wired into `DataMiddleware` + both workers. Reason: stop hardcoding user-facing strings — admin can edit any text/label (HTML + premium emoji) with no restart.
- 2026-07-22 — Button styling (Phase B): new `ButtonStyle` model + button funcs in `textstore` (shared `txtver` reload); `file_card_kb` applies per-op `style` (primary/success/danger) + `icon_custom_emoji_id`; panel `/buttons` page (per-op color + premium-emoji id, one-save batch, `clean_button` validation). Reason: admin sets card-button color + premium-emoji icon with no restart.
- 2026-07-22 — `/texts` page redesign: now shows **all** ~204 strings grouped into collapsible prefix-based categories (`_texts_groups`/`_TEXT_CATS`) instead of an empty search-only box; search filters and auto-opens matches; first category open by default. Reason: the previous page looked empty (only overridden shown) — admin needs to browse/edit every string, categorized.
- 2026-07-22 — Card menu layout editor (buttons Phase 2): new `MenuButton` model + `textstore.get/set/reset_menu_layout` (shared `txtver` reload); `file_card_kb` now resolves order + hidden + per-button width (full/half/third → row sizes) with zero-change default that reproduces the old layout. `/buttons` page rebuilt (V3): per-kind tabs, a live simulated-Telegram preview (JS `rebuildPreview`), and a drag-reorder list editing text (per-lang) + color + premium-emoji + width + show/hide in one save. Reason: admin can fully arrange each file-kind's card menu (reorder, hide, row widths) + text/color/emoji, no restart.
- 2026-07-23 — Distributed nodes (Phase N4, resilience & observability): closed the N2 caveat — new `nodes.reap_orphan_jobs(redis)` moves jobs stranded on `arq:queue:proc` back to the master's `arq:queue` **only when no processing node is live** (claims each with `zrem` before re-adding → no double-run; preserves scores). The main worker runs it every 30 s via a new `worker.startup_master` (master-only, `not node_role`); `WorkerSettings.on_startup` switched to it, download/processing workers keep plain `startup`. Observability: a per-node **jobs-done** counter (`nodes.note_job_done()` in `run_op`/`run_download` finally when `NODE_ROLE` set) rides the heartbeat (`done`) and shows per node in the panel; a **reaped** counter (`nodes:reaped`) shows on the nodes page. Pure logic (reaper move/guard/counter, worker wiring) unit-tested with a fake Redis. Reason: offloaded jobs must never hang if a node blips, and the admin needs to see each node actually doing work.
- 2026-07-23 — Distributed nodes (Phase N3, gateway/stream role): new `app/gateway_node.py` — a public reverse proxy that forwards `/dl` + `/s` to the master's gateway over WireGuard, streaming the body while preserving Range/Content-Range/status (206/HEAD/404 all pass through). Gives a **clean/dedicated public streaming IP** off the master (grey-cloudable) with no DB/Bot API on the node — the token resolves on the master; the node needs only HTTP to the master gateway (`NODE_GATEWAY_URL`) + Redis for its own heartbeat (role `gateway`). New `gateway` role in `nodes.ROLES` (a **service** role: carries `command` = `python -m app.gateway_node`, not `queue`/`worker`), and `node_config()` now emits `queue`+`settings` for worker roles vs `command` for service roles; `node/install.sh` branches accordingly (`arq <settings>` vs the command) and passes `NODE_GATEWAY_URL`. New runtime `stream_base` setting (`config` + `settings_store.RUNTIME_KEYS` + panel `GROUPS`) read via `ops._link_base()` — when set, `/dl` `/s` links point at the gateway node's public domain, else `public_base` (zero change when unset). Health page shows the proc queue from N2; the gateway role auto-appears in the add-node dropdown. Real reverse-proxy path (Range/HEAD/404/502) integration-tested against a live upstream in-process; real multi-machine + public TLS verified on the master server. Reason: offload public link/stream serving to a clean-IP node, the third node type from the master/node plan.
- 2026-07-23 — Distributed nodes (Phase N2, processing/offload role): remote `run_op` on nodes. New `tasks._localize(bot, fid, workdir)` — the single input seam: returns the shared-disk path on the master, else `bot.download_file()`s into the workdir (remote node); all ~8 `get_file().file_path` sites in `_do_op`/`run_op` now go through it (output was already node-safe via `FSInputFile` multipart). New `processing` role in `nodes.ROLES` (queue `arq:queue:proc`, image `worker`) + `ProcessingWorkerSettings(WorkerSettings)` (that queue). Enqueue-time routing: `ops._op_queue` sends an op to `arq:queue:proc` only when it is in `nodes.OFFLOAD_OPS` **and** a processing node is live (`nodes.role_online`), else the master's default queue (zero regression when no node). `node/install.sh` now builds the role's Dockerfile (`docker/${IMAGE}.Dockerfile`, e.g. the full `worker` image) instead of hardcoding download-worker; health page shows the `arq:queue:proc` depth; processing role auto-appears in the panel's add-node dropdown. Pure logic (localize disk/remote branches, routing gate, roles/worker shape) unit-tested; real multi-machine offload verified on the master server. Reason: offload heavy CPU ops (compress/convert/transcribe/…) to a dedicated processing node, proving the remote download-input/upload-output path N1 flagged.
- 2026-07-23 — Distributed nodes (Phase N1, download/clean-IP role): new `app/nodes.py` master-side layer (roles, HMAC-signed **one-time** WireGuard join token in Redis, WG-IP allocation, live registry via `node:{id}` heartbeat, WG peer add/remove through the config file + `wg syncconf`, `node_config()` join reply) + `Node` model (`nodes` table, auto-created). `bot.py` uses `is_local=False` when `NODE_ROLE` is set (remote HTTP download / multipart upload); `worker.py` startup spawns a 20 s heartbeat for node processes. Panel gains a **🖧 Nodes** page (add → one-time install command, live online/offline list with load, remove → strips WG peer) + public `/node/join` API and `/node/install.sh` serving (master base injected). New `node/install.sh` (curl-piped, root): installs WireGuard+Docker, generates a WG keypair, joins with the one-time token, brings up the tunnel, and runs the role's ARQ worker against the master's Redis over WG. README + config node/WG env vars added. Pure logic (token/IP/peer/config) unit-tested; real `wg` + multi-machine join must be verified on the master server. Reason: begin the Master/Node distributed architecture — offload downloads to a clean-IP node, admin-provisioned entirely from the panel.
