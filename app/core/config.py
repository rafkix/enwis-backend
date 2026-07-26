import json

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # =========================
    # ENV
    # =========================
    ENV: str = "local"
    DEBUG: bool = False
    IS_TESTING: bool = False
    LOG_DIR: str = "logs"
    PROJECT_NAME: str = "Enwis Backend"

    # =========================
    # DATABASE
    # =========================
    DATABASE_URL: str = "sqlite+aiosqlite:///./enwis.db"

    # =========================
    # JWT
    # =========================
    JWT_SECRET: str = "change-me-to-a-very-long-secret-key-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 7

    # =========================
    # GOOGLE
    # =========================
    GOOGLE_CLIENT_ID: str = ""

    # =========================
    # TELEGRAM
    # =========================
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""

    # =========================
    # MAIL
    # =========================
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "noreply@enwis.uz"
    MAIL_SERVER: str = "smtp.gmail.com"
    RESEND_API_KEY: str = ""

    # =========================
    # CORS
    # =========================
    ALLOWED_ORIGINS: list[str] = []

    # =========================
    # SMS
    # =========================
    SMS_GATEWAY_URL: str = ""
    ESKIZ_EMAIL: str = ""
    ESKIZ_PASSWORD: str = ""
    SMS_FROM: str = "4546"

    # =========================
    # REDIS
    # =========================
    REDIS_URL: str = "redis://localhost:6379/0"

    # =========================
    # AI
    # =========================
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # =========================
    # COOKIES
    # =========================
    # =========================
    # COOKIES
    # =========================
    COOKIE_DOMAIN: str = "localhost"
    COOKIE_SECURE: bool = False
    COOKIE_HTTPONLY: bool = True
    COOKIE_SAMESITE: str = "lax"

    @field_validator("COOKIE_DOMAIN", mode="before")
    @classmethod
    def clean_cookie_domain(cls, v):
        if not v:
            return v
        # Vergul bilan bir nechta qiymat yozib qo'yilgan bo'lsa — birinchisini olamiz,
        # qo'shtirnoq/bo'shliqlarni tozalaymiz. "localhost" ni domenga aylantirmaslik
        # uchun uni butunlay bo'sh qilib qaytaramiz (localhost'da domain kerak emas).
        first = v.split(",")[0].strip().strip('"').strip("'")
        if first.lower() == "localhost":
            return ""
        return first

    # =========================
    # FRONTEND
    # =========================
    FRONTEND_URL: str = "http://localhost:3000"

    # =========================
    # INTERNAL API
    # =========================
    INTERNAL_API_TOKEN: str = "internal-token"

    # =========================
    # API
    # =========================
    API_VERSION: str = "v1"
    API_PREFIX: str = "/api/v1"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================
    # VALIDATORS
    # =========================
    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [i.strip() for i in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET kamida 32 ta belgi bo'lishi kerak")
        if self.is_production:
            insecure_values = {
                "change-me-to-a-very-long-secret-key-min-32-chars",
                "internal-token",
                "internal-secret",
            }
            if self.DEBUG:
                raise ValueError("Production muhitida DEBUG=false bo'lishi kerak")
            if self.JWT_SECRET in insecure_values:
                raise ValueError("Production uchun xavfsiz JWT_SECRET kiriting")
            if self.INTERNAL_API_TOKEN in insecure_values or len(self.INTERNAL_API_TOKEN) < 32:
                raise ValueError("Production uchun kuchli INTERNAL_API_TOKEN kiriting")
            if not self.COOKIE_SECURE:
                raise ValueError("Production muhitida COOKIE_SECURE=true bo'lishi kerak")
        return self

    # =========================
    # PROPERTIES
    # =========================
    @property
    def jwt_secret(self) -> str:
        return self.JWT_SECRET

    @property
    def telegram_token(self) -> str:
        return self.TELEGRAM_BOT_TOKEN

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


settings = Settings()
