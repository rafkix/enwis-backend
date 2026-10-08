"""migrate_ai_limits.py

PostgreSQL uchun migratsiya skripti:
  1. users jadvaliga ai_questions_used va ai_questions_reset_at qo'shish
  2. Mavjud TEACHER roliga ega foydalanuvchilarning subscription_tier ni
     'TEACHER' ga yangilash (agar hali 'FREE' bo'lsa)

Ishlatish:
    python scripts/migrate_ai_limits.py

.env dagi DATABASE_URL ga qarab ishlaydi.
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

# sqlite uchun add_column_if_not_exists database.py da bor — bu skript
# faqat PostgreSQL uchun
IS_POSTGRES = "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL


async def run():
    engine = create_async_engine(DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        if IS_POSTGRES:
            # 1. ai_questions_used
            await conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS ai_questions_used INTEGER NOT NULL DEFAULT 0;
            """))
            print("✓ ai_questions_used kolonnasi qo'shildi (yoki allaqachon bor)")

            # 2. ai_questions_reset_at
            await conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS ai_questions_reset_at TIMESTAMPTZ;
            """))
            print("✓ ai_questions_reset_at kolonnasi qo'shildi (yoki allaqachon bor)")

            # 3. subscription_tier = 'TEACHER' — TEACHER roliga ega
            #    foydalanuvchilar uchun (agar hali 'FREE' bo'lsa)
            result = await conn.execute(text("""
                UPDATE users u
                SET subscription_tier = 'TEACHER'
                FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = u.id
                  AND r.name = 'TEACHER'
                  AND u.subscription_tier IN ('FREE', 'free')
                RETURNING u.id, u.username;
            """))
            rows = result.fetchall()
            print(f"✓ {len(rows)} foydalanuvchining subscription_tier = TEACHER ga yangilandi:")
            for row in rows:
                print(f"   - {row[1]} ({row[0]})")

        else:
            print("SQLite: database.py init_db() da add_column_if_not_exists ishlatiladi.")
            print("Bu skript faqat PostgreSQL uchun.")

    await engine.dispose()
    print("\nMigratsiya muvaffaqiyatli yakunlandi.")


if __name__ == "__main__":
    asyncio.run(run())
