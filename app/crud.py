"""عملیاتِ سادهٔ پایگاه‌داده."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import File, Job, User


async def get_file_by_ref(session: AsyncSession, ref: str,
                          user: User | None) -> File | None:
    """فایلِ این `ref` را بده — **فقط اگر** `user` مالکش باشد، وگرنه `None`.

    گاردِ مالکیت عمداً این‌جاست و نه در ۴۱ هندلرِ `routers/ops.py`: قاعده باید یک
    جا باشد وگرنه هندلرِ بعدی که اضافه شود بی‌صدا از قلم می‌افتد. و چون هر هندلر از
    قبل حالتِ «فایل پیدا نشد» را مدیریت می‌کند (`if file is None: … return`)، ردِ
    درخواستِ غیرمجاز از همان مسیرِ موجود می‌رود و هیچ شاخهٔ تازه‌ای لازم ندارد.

    `ref` هشت کاراکترِ تصادفی است (`routers/files.py:_new_ref`) پس حدس‌زدنی نیست؛
    ولی مخفی‌بودنِ شناسه مجوز نیست — هرجا یک `ref` نشت کند (لاگ، فوروارد، گروه)
    بدونِ این گارد همهٔ عملیاتِ آن فایل باز می‌شود، از جمله `op_link` که لینکِ
    عمومیِ دانلود می‌سازد.

    `user` **اجباری** است و `None` یعنی **رد**، نه «بدونِ بررسی». این جهتِ خطا
    عمدی است: اگر روزی میدل‌ور کاربر را تزریق نکند، بدترین حالت «کار نمی‌کند»
    باشد نه «برای همه باز است». در عمل `user` فقط وقتی `None` است که فرستنده ربات
    باشد یا اصلاً `event_from_user` نداشته باشد (`middlewares.py:46-50`) — که برای
    کال‌بکِ یک کاربرِ واقعی رخ نمی‌دهد.
    """
    if user is None:
        return None
    result = await session.execute(
        select(File).where(File.ref == ref, File.owner_id == user.id))
    return result.scalar_one_or_none()


async def get_owned_job(session: AsyncSession, job_id: int,
                        user: User | None) -> Job | None:
    """جابی با این شناسه که فایلش متعلق به همین کاربر باشد، وگرنه `None`.

    `Job.id` یک عددِ **ترتیبی** است، پس برخلافِ `ref` اصلاً حدس لازم ندارد —
    شمردنِ ۱،۲،۳… کافی بود تا کاربری جابِ کاربرِ دیگری را لغو کند.
    """
    if user is None:
        return None
    result = await session.execute(
        select(Job).join(File, Job.file_id == File.id)
        .where(Job.id == job_id, File.owner_id == user.id))
    return result.scalar_one_or_none()
