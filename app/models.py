"""مدل‌های داده (M1: User, File)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: عرضِ ستونِ کدِ زبان، در **هر سه** جایی که کدِ زبان ذخیره می‌شود
#: (`User.lang`, `TextOverride.lang`, `Language.code`). یک ثابت، نه سه عدد —
#: چون واگراییِ این سه یعنی زبانی که import می‌شود ولی به کاربر بسته نمی‌شود.
LANG_LEN = 16


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    #: کدِ زبان — **BCP 47**، نه دو حرف. `String(16)` جا برای `pt-BR` و
    #: `zh-Hant-TW` باز می‌گذارد؛ کرانِ واقعی در `langpack.normalize_code` است
    #: (فرمت، نه طول). عرضِ ستون باید با `TextOverride.lang` و `Language.code`
    #: یکی بماند، وگرنه زبانی که در متن‌ها جا می‌شود روی کاربر رد می‌شود.
    lang: Mapped[str | None] = mapped_column(String(LANG_LEN), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_unique_id: Mapped[str] = mapped_column(String(64))
    file_id: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16))
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    duration: Mapped[int | None] = mapped_column(nullable=True)
    changelog: Mapped[list | None] = mapped_column(JSON, default=list)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # متادیتای فعلیِ صوت
    dl_token: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    cover_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # کاورِ ویدیو
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # None/tg=آپلود · dl=دانلودی
    # متنِ اصلیِ پستِ مبدأ (کپشنِ اینستاگرام، عنوان/توضیحِ یوتیوب) — خامِ **بدونِ HTML**؛
    # حالتِ جمع‌شدهٔ کارت آن را در بلاک‌کوتِ بسته نشان می‌دهد (سرِ رندر escape می‌شود).
    post_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # پلتفرمِ مبدأ برای فایلِ دانلودی (youtube/instagram/…). شمارنده‌های Redis فقط ۲ روز
    # عمر دارند، پس بدونِ این ستون آمارِ تاریخیِ «کدام پلتفرم» ساخته نمی‌شود.
    platform: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Setting(Base):
    """تنظیماتِ زمانِ‌اجرا (admin-lite). Postgres = منبعِ ماندگار؛ Redis = منبعِ زنده.
    نبودِ کلید یعنی «از پیش‌فرضِ env (config.Settings) استفاده کن»."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TextOverride(Base):
    """بازنویسیِ زمانِ‌اجرا برای متن‌ها/لیبل‌ها (به‌جای هاردکد در locales).
    نبودِ ردیف یعنی «از پیش‌فرضِ locale استفاده کن». کلید = (زبان, کلیدِ متن)."""

    __tablename__ = "text_overrides"

    lang: Mapped[str] = mapped_column(String(LANG_LEN), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Language(Base):
    """زبانِ **افزوده‌شده** — آن‌هایی که کاتالوگِ کد ندارند و از پنل import شده‌اند.

    `fa`/`en` این‌جا ردیف **ندارند**: آن‌ها از `i18n.CATALOG` می‌آیند و نامشان در
    `i18n.BUILTIN_NAMES` است. دو منبعِ حقیقت برای یک مفهوم، همان واگرایی‌ای است
    که §۷ بارها ثبتش کرده، پس مرز صریح است: «زبانِ داخلی = کاتالوگ دارد» و
    «زبانِ افزوده = ردیفِ این جدول».

    تنها چیزی که این‌جا هست و از `text_overrides` **مشتق‌شدنی نیست** نامِ نمایشی
    است؛ بقیه (پوشش، تعدادِ ترجمه) از همان ردیف‌ها حساب می‌شود. عمداً ستونِ
    `enabled` ندارد — امروز هیچ مسیری خاموشش نمی‌کند، و حالتی که هیچ کدی
    نمی‌سازدش دقیقاً همان `DISABLED`ِ مردهٔ استخرِ کوکی است.
    """

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(LANG_LEN), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ButtonStyle(Base):
    """استایلِ زمانِ‌اجرا برای کلیدهای منوی کارت (به‌ازای هر op).
    style ∈ primary/success/danger (رنگِ کلید)؛ icon_emoji_id = آیدیِ ایموجیِ
    پرمیوم روی کلید. نبودِ ردیف = کلیدِ ساده (بی‌رنگ/بی‌آیکون)."""

    __tablename__ = "button_styles"

    op: Mapped[str] = mapped_column(String(24), primary_key=True)
    style: Mapped[str | None] = mapped_column(String(12), nullable=True)
    icon_emoji_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MenuButton(Base):
    """چیدمانِ زمانِ‌اجرا برای منوی کارتِ هر نوع (kind): ترتیب + نمایش + عرضِ کلید.
    نبودِ ردیف برای یک kind = از چیدمانِ پیش‌فرضِ کد (`OPS_BY_KIND`) استفاده کن.
    width ∈ full/half/third (تلگرام کلیدها را به‌ترتیب تا پرشدنِ ردیف کنارِ هم می‌چیند)."""

    __tablename__ = "menu_buttons"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    op: Mapped[str] = mapped_column(String(24), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[str] = mapped_column(String(8), default="third")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Node(Base):
    """نودِ توزیع‌شده (ماشینِ راه‌دورِ متصل با WireGuard). هویتِ ماندگار؛ وضعیتِ زنده
    در Redis (heartbeat) نگه‌داری می‌شود. role ∈ کلیدهای `nodes.ROLES`."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # کوتاه، تصادفی
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    wg_ip: Mapped[str] = mapped_column(String(45))
    wg_pubkey: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DownloadCache(Base):
    """کشِ file_id برای دانلودِ آنی: کلید = هشِ (لینک + کیفیت) → فایلِ ارسال‌شده.
    دفعهٔ بعد که همان لینک+کیفیت خواسته شود، مستقیم با file_id فرستاده می‌شود
    (بدونِ دانلودِ دوباره)."""

    __tablename__ = "download_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(256))
    file_unique_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    duration: Mapped[int | None] = mapped_column(nullable=True)
    # کپشنِ پست و پلتفرم هم کش می‌شوند، وگرنه تحویلِ آنی کارتِ فقیرتری از دانلودِ واقعی می‌دهد
    post_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # کاروسل/آلبوم: فهرستِ مرتبِ آیتم‌ها ([{file_id, kind, size}, …]). None = تک‌فایل.
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hits: Mapped[int] = mapped_column(default=0)  # چندبار از کش تحویل شد (سنجشِ سودِ کش)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), index=True)
    op: Mapped[str] = mapped_column(String(24))
    args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
