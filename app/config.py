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

    # سرورِ محلیِ Bot API
    local_api_base: str = "http://local-bot-api:8081"

    # وبهوک (داخلی — local-bot-api آپدیت‌ها را به این آدرس می‌فرستد)
    webhook_host: str = "http://bot:8080"
    webhook_path: str = "/webhook"
    webhook_secret: str = "dev-secret"
    web_port: int = 8080

    # داده
    redis_url: str = "redis://redis:6379/0"
    postgres_dsn: str = (
        "postgresql+asyncpg://telabzar:telabzar@postgres:5432/telabzar"
    )

    # پردازش (ورکر)
    work_dir: str = "/work"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_host}{self.webhook_path}"

    @property
    def admin_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_ids.replace(" ", "").split(","):
            if part.isdigit():
                out.add(int(part))
        return out


settings = Settings()  # type: ignore[call-arg]
