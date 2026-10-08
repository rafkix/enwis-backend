"""Create default teacher package + grant ADMIN role to a Telegram user."""
import asyncio, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import all models to resolve relationship strings
from app.core.database import AsyncSessionLocal
from app.modules.notifications.models import Notification  # noqa: F401 (User relationship)
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.auth.models import Role, User
from sqlalchemy import select

TELEGRAM_ID = "7281495879"  # admin bot user


async def main():
    from app.modules.billing.models import TeacherPackage
    from app.modules.billing.service import BillingService

    async with AsyncSessionLocal() as db:
        billing = BillingService(db)

        # 1. Create teacher package
        pkg = await billing.get_teacher_package_admin()
        if not pkg:
            pkg = await billing.create_default_teacher_package()
            print(f"✅ Teacher package created: {pkg.id}")
        else:
            print(f"ℹ️  Teacher package already exists: {pkg.id}")

        # 2. Grant ADMIN role to the telegram user
        result = await db.execute(
            select(User).where(User.telegram_id == TELEGRAM_ID)
        )
        user = result.scalar_one_or_none()
        if user:
            has_admin = any(r.name.upper() == "ADMIN" for r in (user.roles or []))
            if not has_admin:
                result = await db.execute(select(Role).where(Role.name == "ADMIN"))
                admin_role = result.scalar_one_or_none()
                if not admin_role:
                    admin_role = Role(name="ADMIN", description="Admin role")
                    db.add(admin_role)
                    await db.flush()
                user.roles.append(admin_role)
                await db.commit()
                print(f"✅ ADMIN role granted to user {user.id} (telegram_id={TELEGRAM_ID})")
            else:
                print(f"ℹ️  User already has ADMIN role")
        else:
            print(f"⚠️  User with telegram_id={TELEGRAM_ID} not found")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
