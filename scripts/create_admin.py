"""
Bir martalik script: birinchi ADMIN hisobini yaratish.

Ishlatish (loyiha ildizidan, masalan enwis_v2/ papkasidan):

    python -m scripts.create_admin --username admin --password KuchliParol123 --phone 998901234567
    python -m scripts.create_admin --telegram-id 7281495879

1-usul (--username/--password): to'g'ridan-to'g'ri login+parol bilan yangi
    ADMIN hisobini yaratadi (agar shunday username/phone/telegram_id band
    bo'lmasa).
2-usul (--telegram-id): Telegram orqali AVVAL ro'yxatdan o'tgan (ya'ni
    bot/sayt orqali kamida bir marta kirgan) foydalanuvchini topib, unga
    ADMIN rolini biriktiradi. Agar bunday user topilmasa, xato chiqaradi —
    avval shu telegram_id bilan botga/saytga kirib ro'yxatdan o'tish kerak.

Ikkala holatda ham ADMIN roli mavjud bo'lmasa, avtomatik yaratiladi.
"""

import argparse
import asyncio

from sqlalchemy import select

# Import the full API router graph first. This pulls in every module's
# models (e.g. Notification) so SQLAlchemy's mapper registry is complete
# before we run any query — without this, importing just
# app.modules.auth.models triggers "failed to locate a name" errors for
# relationships that point at models from other modules.
import app.api.v1  # noqa: F401

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User, UserStatus


async def _get_or_create_admin_role(db) -> Role:
    result = await db.execute(select(Role).where(Role.name == "ADMIN"))
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="ADMIN", description="Administrator")
        db.add(role)
        await db.flush()
        print("ADMIN roli topilmadi — yangi yaratildi.")
    return role


async def create_by_credentials(username: str, password: str, phone: str | None) -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(User).where(User.username == username.lower())
        )
        if existing.scalar_one_or_none():
            print(f"Xato: '{username}' login allaqachon band.")
            return

        role = await _get_or_create_admin_role(db)

        user = User(
            username=username.lower(),
            password_hash=hash_password(password),
            phone=phone,
            full_name="Administrator",
            status=UserStatus.ACTIVE,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user, attribute_names=["roles"])
        user.roles.append(role)
        await db.commit()
        print(f"✅ Admin yaratildi. username={username}  id={user.id}")


async def promote_telegram_user(
    telegram_id: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == str(telegram_id))
        )
        user = result.scalar_one_or_none()
        if not user:
            print(
                f"Xato: telegram_id={telegram_id} bilan hech qanday user topilmadi. "
                "Avval shu odam botga/saytga Telegram orqali kirib ro'yxatdan o'tishi kerak."
            )
            return

        role = await _get_or_create_admin_role(db)
        await db.refresh(user, attribute_names=["roles"])
        if role not in user.roles:
            user.roles.append(role)
            print(f"'{user.username}' ADMIN qilindi.")
        else:
            print(f"'{user.username}' allaqachon ADMIN.")

        if username or password:
            if not (username and password):
                print(
                    "Diqqat: login+parol o'rnatish uchun --username VA --password "
                    "ikkalasi ham berilishi kerak. Parol o'rnatilmadi."
                )
            else:
                existing = await db.execute(
                    select(User).where(
                        User.username == username.lower(), User.id != user.id
                    )
                )
                if existing.scalar_one_or_none():
                    print(f"Xato: '{username}' login boshqa userda band — parol o'rnatilmadi.")
                else:
                    user.username = username.lower()
                    user.password_hash = hash_password(password)
                    print(f"Login+parol o'rnatildi: username={username}")

        await db.commit()
        print(f"✅ Tayyor. id={user.id}  telegram_id={telegram_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Birinchi admin hisobini yaratish")
    parser.add_argument("--username", help="Yangi admin uchun login")
    parser.add_argument("--password", help="Yangi admin uchun parol")
    parser.add_argument("--phone", help="Ixtiyoriy: telefon raqami", default=None)
    parser.add_argument(
        "--telegram-id",
        help="Mavjud Telegram foydalanuvchisini ADMIN qilish uchun uning telegram_id'si",
    )
    args = parser.parse_args()

    if args.telegram_id:
        asyncio.run(
            promote_telegram_user(args.telegram_id, args.username, args.password)
        )
    elif args.username and args.password:
        asyncio.run(create_by_credentials(args.username, args.password, args.phone))
    else:
        parser.error(
            "Yo --telegram-id, yoki --username va --password birga berilishi kerak."
        )


if __name__ == "__main__":
    main()