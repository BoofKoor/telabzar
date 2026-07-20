"""پیکربندی از محیط (env / .env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    bot_token: str
    default_lang: str = "fa"
    admin_ids: str = ""
    max_file_mb: int = 2000

    # سرورِ محلیِ Bot API (ربات با long-polling به آن وصل می‌شود)
    local_api_base: str = "http://local-bot-api:8081"

    # داده
    redis_url: str = "redis://redis:6379/0"
    postgres_dsn: str = (
        "postgresql+asyncpg://telabzar:telabzar@postgres:5432/telabzar"
    )

    # پردازش (ورکر)
    work_dir: str = "/work"

    # امنیت
    clamav_host: str = "clamav"
    clamav_port: int = 3310

    # آرشیو (محدودیتِ استخراج — دفاعِ پایه در برابرِ bomb)
    max_extract_files: int = 40
    max_extract_mb: int = 500

    # کنترلِ سوءاستفاده (بات عمومی) — ۰ = نامحدود (خاموش).
    # فعلاً خاموش؛ بعداً از پنلِ ادمین (M5) مقداردهی می‌شود.
    daily_op_quota: int = 0
    rate_per_min: int = 0

    # لینک دانلود/استریم (سرویسِ gateway؛ فایل از دیسکِ local-bot-api سرو می‌شود)
    public_base: str = ""          # پایهٔ عمومی، مثل https://files.example.com
    gateway_port: int = 8080       # پورتِ داخلِ کانتینر (بدونِ نیاز به cap)
    tls_cert: str = ""             # مسیرِ سرتیفیکیتِ Origin کلودفلر (PEM)
    tls_key: str = ""              # مسیرِ کلیدِ خصوصیِ Origin (PEM)

    @property
    def admin_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_ids.replace(" ", "").split(","):
            if part.isdigit():
                out.add(int(part))
        return out


settings = Settings()  # type: ignore[call-arg]
