import logging
import uuid

from sqlalchemy import event, text
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    ),
)

if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

from app.shared.base_model import Base  # noqa: E402


class UUIDType(TypeDecorator):
    impl = CHAR(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value.hex
        return uuid.UUID(str(value)).hex

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return uuid.UUID(value)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Commit-on-success safety net: several service methods
            # (notably the Questions module) never call session.commit()
            # themselves and only flush(). Without an explicit or
            # implicit commit, AsyncSession.close() discards the pending
            # transaction and every "successful" write silently vanishes
            # (e.g. creating a Question appeared to work but nothing was
            # persisted). Committing here if nothing failed is a no-op
            # when a service already committed, and guarantees writes are
            # durable when it didn't.
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _table_exists(conn, table_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name=:name"
        ),
        {"name": table_name},
    )
    return result.fetchone() is not None


async def add_column_if_not_exists(
    conn,
    table_name: str,
    column_name: str,
    ddl: str,
):
    if not await _table_exists(conn, table_name):
        return
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = {row[1] for row in result.fetchall()}
    if column_name not in columns:
        await conn.execute(text(ddl))


async def init_db() -> None:
    # Create the schema first and commit it on its own, so that a
    # later failure while altering columns cannot roll back the tables.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if "sqlite" in settings.DATABASE_URL:
        async with engine.begin() as conn:
            await add_column_if_not_exists(
                conn,
                "users",
                "xp",
                "ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "level",
                "ALTER TABLE users ADD COLUMN level INTEGER NOT NULL DEFAULT 1",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "streak",
                "ALTER TABLE users ADD COLUMN streak INTEGER NOT NULL DEFAULT 0",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "referral_code",
                "ALTER TABLE users ADD COLUMN referral_code VARCHAR(32)",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "referred_by_id",
                "ALTER TABLE users ADD COLUMN referred_by_id CHAR(32)",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "deleted_at",
                "ALTER TABLE users ADD COLUMN deleted_at DATETIME",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "is_google_verified",
                "ALTER TABLE users ADD COLUMN is_google_verified BOOLEAN NOT NULL DEFAULT 0",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "is_telegram_verified",
                "ALTER TABLE users ADD COLUMN is_telegram_verified BOOLEAN NOT NULL DEFAULT 0",
            )
            await add_column_if_not_exists(
                conn,
                "users",
                "teacher_verified_at",
                "ALTER TABLE users ADD COLUMN teacher_verified_at DATETIME",
            )
            await add_column_if_not_exists(
                conn,
                "phone_registration_tickets",
                "password_hash",
                "ALTER TABLE phone_registration_tickets ADD COLUMN password_hash VARCHAR(255)",
            )
            await add_column_if_not_exists(
                conn,
                "test_practice_attempts",
                "group_quiz_id",
                "ALTER TABLE test_practice_attempts ADD COLUMN group_quiz_id CHAR(32)",
            )
            # Billing (added when the manual-card-transfer payment review
            # flow replaced the old payment_logs table; safe no-op if the
            # payments table doesn't exist yet, since create_all above
            # would have already created it with these columns).
            await add_column_if_not_exists(
                conn,
                "payments",
                "method",
                "ALTER TABLE payments ADD COLUMN method VARCHAR(20) NOT NULL DEFAULT 'manual_card'",
            )
            await add_column_if_not_exists(
                conn,
                "payments",
                "provider_ref",
                "ALTER TABLE payments ADD COLUMN provider_ref VARCHAR(255)",
            )

            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    ix_users_referral_code
                    ON users (referral_code)
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS
                    ix_users_referred_by_id
                    ON users (referred_by_id)
                    """
                )
            )
