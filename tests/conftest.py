"""Shared async fixtures for integration tests.

NOTE: The `active_exam` / `draft_exam` / `exam_questions` fixtures that used
to live here were removed — they referenced `Exam.exam_type`,
`LegacyQuestion`, and `Option`, none of which exist in the current schema
(Exam now references a Test via `test_id`; questions live in the
`questions` module as `Question`/`Choice`). See tests/legacy_disabled/
for the original (now-quarantined) test files that depended on them, and
tests/README.md for what a from-scratch rewrite against the current
Test -> Exam -> Registration -> Attempt -> Result -> Certificate pipeline
needs to cover.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.modules.auth.models import Role, User, UserStatus

# Import every module's models so SQLAlchemy's mapper configuration step
# (triggered lazily on first use) can resolve string-based relationship()
# targets like User.notifications -> "Notification" across modules. In
# the real app this happens naturally because app.main imports every
# router; test collection must do the same or mapper configuration blows
# up with "failed to locate a name" for any model not yet imported.
import app.modules.exams.apply_models  # noqa: F401
import app.modules.exams.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.questions.models  # noqa: F401
import app.modules.subscriptions.models  # noqa: F401
import app.modules.tests.models  # noqa: F401

ASYNC_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(ASYNC_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


@pytest_asyncio.fixture
async def role_user(session: AsyncSession) -> Role:
    r = await session.execute(text("SELECT * FROM roles WHERE name = 'USER'"))
    role = r.fetchone()
    if not role:
        role = Role(name="USER", description="Default user")
        session.add(role)
        await session.commit()
        await session.refresh(role)
    else:
        role = Role(id=role[0], name=role[1], description=role[2])
    return role


@pytest_asyncio.fixture
async def test_user(session: AsyncSession, role_user: Role) -> User:
    user = User(
        id=uuid.uuid4(),
        username="testuser",
        phone="+998901234567",
        full_name="Test User",
        is_active=True,
        is_verified=True,
        status=UserStatus.ACTIVE,
    )
    user.roles.append(role_user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def second_user(session: AsyncSession, role_user: Role) -> User:
    user = User(
        id=uuid.uuid4(),
        username="seconduser",
        phone="+998907654321",
        full_name="Second User",
        is_active=True,
        is_verified=True,
        status=UserStatus.ACTIVE,
    )
    user.roles.append(role_user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

