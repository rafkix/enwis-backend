"""migrate_ai_quota_override.py

PostgreSQL uchun migratsiya skripti:
  users jadvaliga ai_questions_quota_override (nullable INTEGER) qo'shadi.

  NULL -> foydalanuvchi hali ham o'z tarifining standart oylik AI
          limitidan foydalanadi (PlanLimits.ai_questions_per_month).
  -1   -> admin shu foydalanuvchiga cheksiz AI savol generatsiyasi bergan.
  N>=0 -> admin shu foydalanuvchi uchun tarifdan mustaqil aniq oylik son
          belgilagan.

Ishlatish:
    python scripts/migrate_ai_quota_override.py

.env dagi DATABASE_URL ga qarab ishlaydi. SQLite uchun bu ustun
app/core/database.py ichidagi add_column_if_not_exists orqali init_db()
paytida avtomatik qo'shiladi — bu skript faqat PostgreSQL uchun.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL .env faylda topilmadi.")
    sys.exit(1)

IS_POSTGRES = "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL


async def run():
    engine = create_async_engine(DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        if IS_POSTGRES:
            await conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS ai_questions_quota_override INTEGER;
            """))
            print("✓ ai_questions_quota_override kolonnasi qo'shildi (yoki allaqachon bor)")
        else:
            print("SQLite: database.py init_db() da add_column_if_not_exists ishlatiladi.")
            print("Bu skript faqat PostgreSQL uchun.")

    await engine.dispose()
    print("\nMigratsiya muvaffaqiyatli yakunlandi.")


if __name__ == "__main__":
    asyncio.run(run())
