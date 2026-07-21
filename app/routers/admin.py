"""پنلِ ادمینِ سبک (admin-lite): تنظیماتِ زمانِ‌اجرا + هلث، از طریقِ /admin.

دسترسی فقط برای ادمین‌ها (ADMIN_IDS در env). برای غیرِادمین، دستور بی‌پاسخ می‌ماند
تا وجودش لو نرود. تنظیمات از settings_store خوانده/نوشته می‌شوند؛ تغییر بلافاصله و
بین‌پروسه‌ای اثر می‌کند (bot و worker هر دو read-through از Redis می‌خوانند).
"""
from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from arq import ArqRedis
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_store
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
    """پیامِ خطا در صورتِ نامعتبر بودن؛ None اگر معتبر."""
    if key not in RUNTIME_KEYS:
        return f"کلیدِ ناشناخته: <code>{escape(key)}</code>"
    kind = RUNTIME_KEYS[key][0]
    if kind == "int":
        try:
            int(value)
        except ValueError:
            return f"مقدارِ «{escape(key)}» باید عدد باشد."
    return None


async def _effective(key: str) -> str:
    """مقدارِ مؤثر: override اگر باشد، وگرنه پیش‌فرضِ env."""
    kind, default = RUNTIME_KEYS[key]
    override = await settings_store.get_str(key, "\x00")
    if override == "\x00":
        return f"{default}  <i>(پیش‌فرض)</i>"
    return f"{escape(override)}  <i>(تنظیم‌شده)</i>"


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
