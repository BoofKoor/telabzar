"""پنلِ ادمینِ سبک (admin-lite): تنظیماتِ زمانِ‌اجرا + هلث، از طریقِ /admin.

دسترسی فقط برای ادمین‌ها (ADMIN_IDS در env). برای غیرِادمین، دستور بی‌پاسخ می‌ماند
تا وجودش لو نرود. تنظیمات از settings_store خوانده/نوشته می‌شوند؛ تغییر بلافاصله و
بین‌پروسه‌ای اثر می‌کند (bot و worker هر دو read-through از Redis می‌خوانند).
"""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cookies as ck
from .. import settings_store
from ..callbacks import Ck
from ..settings_store import RUNTIME_KEYS

router = Router(name="admin")

_HELP = (
    "🛠 <b>پنلِ ادمین</b>\n"
    "<code>/admin list</code> — تنظیماتِ فعلی\n"
    "<code>/admin get &lt;key&gt;</code>\n"
    "<code>/admin set &lt;key&gt; &lt;value&gt;</code>\n"
    "<code>/admin reset &lt;key&gt;</code> — بازگشت به پیش‌فرضِ env\n"
    "<code>/admin health</code> — وضعیتِ سرویس‌ها\n\n"
    "کلیدها: " + ", ".join(f"<code>{k}</code>" for k in RUNTIME_KEYS)
)


def _validate(key: str, value: str) -> str | None:
    """پیامِ خطا در صورتِ نامعتبر بودن؛ None اگر معتبر.

    منطق در `settings_store.validate_value` است تا این مسیر و پنلِ وب **یک**
    قاعده داشته باشند: تا امروز هر دو جدا نوشته شده بودند و هر دو کرانِ عددی
    نداشتند، پس `/admin set max_file_mb -1` هم مثلِ فرمِ پنل قبول می‌شد. این‌جا
    فقط خروجی برای تلگرام escape می‌شود (پیام با parse_mode=HTML می‌رود).
    """
    return escape(settings_store.validate_value(key, value) or "") or None


async def _effective(key: str) -> str:
    """مقدارِ مؤثر: override اگر باشد، وگرنه پیش‌فرضِ env."""
    kind, default = RUNTIME_KEYS[key]
    override = await settings_store.get_str(key, "\x00")
    if override == "\x00":
        return f"{default}  <i>(پیش‌فرض)</i>"
    return f"{escape(override)}  <i>(تنظیم‌شده)</i>"


@router.message(Command("panel"))
async def panel_cmd(message: Message, is_admin: bool) -> None:
    """لینکِ پنلِ ادمینِ وب را می‌دهد (ورود با کدِ تلگرام)."""
    if not is_admin:
        return
    from ..config import settings as _s
    if _s.admin_base:
        await message.answer(f"🖥 پنلِ مدیریت:\n{_s.admin_base}\n\nشناسهٔ عددی‌ات را وارد کن؛ کد همین‌جا برایت می‌آید.")
    else:
        await message.answer("پنلِ وب هنوز پیکربندی نشده (ADMIN_BASE در نصب تنظیم نشده). فعلاً از /admin استفاده کن.")


@router.message(Command("admin"))
async def admin_cmd(message: Message, command: CommandObject, is_admin: bool,
                    arq_pool: ArqRedis, session: AsyncSession) -> None:
    if not is_admin:
        return  # بی‌پاسخ برای غیرِادمین
    args = (command.args or "").split()
    sub = args[0].lower() if args else "help"

    if sub in ("help", ""):
        await message.answer(_HELP)
        return

    if sub == "list":
        lines = ["🛠 <b>تنظیماتِ فعلی</b>:"]
        for k in RUNTIME_KEYS:
            lines.append(f"• <code>{k}</code> = {await _effective(k)}")
        await message.answer("\n".join(lines))
        return

    if sub == "get":
        if len(args) < 2 or args[1] not in RUNTIME_KEYS:
            await message.answer("استفاده: <code>/admin get &lt;key&gt;</code>")
            return
        await message.answer(f"<code>{args[1]}</code> = {await _effective(args[1])}")
        return

    if sub == "set":
        if len(args) < 3:
            await message.answer("استفاده: <code>/admin set &lt;key&gt; &lt;value&gt;</code>")
            return
        key, value = args[1], " ".join(args[2:])
        err = _validate(key, value)
        if err:
            await message.answer("⚠️ " + err)
            return
        await settings_store.get_store().set(key, value)
        await message.answer(f"✅ <code>{key}</code> = <code>{escape(value)}</code> تنظیم شد.")
        return

    if sub == "reset":
        if len(args) < 2 or args[1] not in RUNTIME_KEYS:
            await message.answer("استفاده: <code>/admin reset &lt;key&gt;</code>")
            return
        await settings_store.get_store().reset(args[1])
        await message.answer(f"✅ <code>{args[1]}</code> به پیش‌فرضِ env برگشت.")
        return

    if sub == "health":
        await message.answer(await _health(arq_pool, session))
        return

    await message.answer(_HELP)


async def _health(arq_pool: ArqRedis, session: AsyncSession) -> str:
    lines = ["🩺 <b>وضعیتِ سرویس‌ها</b>:"]
    # Postgres
    try:
        await session.execute(sql_text("SELECT 1"))
        lines.append("• Postgres: ✅")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"• Postgres: ❌ <code>{escape(str(exc)[:80])}</code>")
    # Redis (از طریقِ کلاینتِ فروشگاهِ تنظیمات)
    store = settings_store.get_store()
    try:
        await store.r.ping()
        lines.append("• Redis: ✅")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"• Redis: ❌ <code>{escape(str(exc)[:80])}</code>")
    # عمقِ صفِ ARQ (بهترین‌تلاش)
    try:
        depth = await arq_pool.zcard("arq:queue")
        lines.append(f"• صفِ ARQ: <code>{depth}</code> جابِ در انتظار")
    except Exception:  # noqa: BLE001
        lines.append("• صفِ ARQ: —")
    # تعدادِ overrideها
    try:
        overrides = await store.all_overrides()
        lines.append(f"• تنظیماتِ override‌شده: <code>{len(overrides)}</code>")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


# ── صفِ رسیدگیِ کوکی: ادمین از داخلِ تلگرام اکانتِ فریزشده را درست می‌کند ────────
# چک‌پوینت/۲FA با تلاشِ خودکار حل نمی‌شود. ربات هشدار می‌دهد و ادمین یا کوکیِ تازه
# می‌چسباند (همین‌جا، بدونِ بازکردنِ پنل) یا اکانت را کنار می‌گذارد/حذف می‌کند.
_CK_TOK = "cktok:"      # cktok:<token> → نامِ فایلِ کوکی
_CK_WAIT = "ckwait:"    # ckwait:<admin_id> → نامِ فایلی که منتظرِ متنِ تازه است


@router.callback_query(Ck.filter())
async def cookie_action(cq: CallbackQuery, callback_data: Ck, is_admin: bool,
                        arq_pool: ArqRedis) -> None:
    if not is_admin:
        return
    name = await arq_pool.get(_CK_TOK + callback_data.tok)
    name = name if isinstance(name, str) else (name.decode() if name else None)
    if not name:
        await cq.answer("این هشدار منقضی شده — از پنل رسیدگی کن.", show_alert=True)
        return
    meta = await ck.get_meta(arq_pool, name)
    label = escape(str(meta.get("label") or name))

    if callback_data.act == "paste":
        await arq_pool.set(_CK_WAIT + str(cq.from_user.id), name, ex=1800)
        await cq.message.answer(
            f"📋 متنِ کوکیِ تازهٔ «{label}» را همین‌جا بفرست.\n"
            f"<i>Netscape یا JSONِ Cookie-Editor — هر دو قبول است. ۳۰ دقیقه وقت داری.</i>")
        await cq.answer()
        return

    if callback_data.act == "off":
        meta["disabled"] = True
        await ck.set_meta(arq_pool, name, meta)
        await cq.answer("کنار گذاشته شد.")
    else:                                    # del
        await ck.delete_account(arq_pool, name)   # همان سه گامِ مسیرِ پنل، از یک جا
        await cq.answer("حذف شد.")
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


@router.message(F.text.len() > 60)
async def cookie_paste(message: Message, is_admin: bool, arq_pool: ArqRedis) -> None:
    """متنِ بلندی که ادمین بعد از زدنِ «کوکیِ تازه می‌فرستم» می‌فرستد = همان کوکی.

    فیلترِ طولِ ۶۰ کاراکتر جلوی گرفتنِ پیام‌های عادی را می‌گیرد، و اگر انتظاری ثبت
    نشده باشد این هندلر عبور می‌کند تا مسیرهای بعدی (لینک/فایل) کارِ خودشان را بکنند.
    """
    waiting = await arq_pool.get(_CK_WAIT + str(message.from_user.id)) if is_admin else None
    name = waiting if isinstance(waiting, str) else (waiting.decode() if waiting else None)
    if not name:
        raise SkipHandler
    text, err = ck._normalize_cookie_text(message.text)
    if err:
        await message.reply(f"⚠️ {err}")
        return
    meta = await ck.get_meta(arq_pool, name)
    err = ck._check_required(text, str(meta.get("platform") or ""))
    if err:
        await message.reply(f"⚠️ {err}")
        return
    err = await ck._save_cookie(arq_pool, name, text)
    if err:
        await message.reply(f"⚠️ {err}")
        return
    await ck.unfreeze(arq_pool, name)                    # از صفِ رسیدگی خارج
    await arq_pool.delete(_CK_WAIT + str(message.from_user.id))
    await arq_pool.delete(f"ckcheck:{name}")             # هشدارِ بعدی دوباره مجاز
    await message.reply(f"✅ کوکیِ «{escape(str(meta.get('label') or name))}» به‌روز شد "
                        f"و اکانت دوباره واردِ چرخش شد.")
