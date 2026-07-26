from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import (
    AuthLog,
    PasswordResetToken,
    PhoneRegistrationTicket,
    PhoneVerification,
    Role,
    Session,
    User,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).options(selectinload(User.roles)).where(User.id == user_id)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return await self._session.scalar(stmt)

    async def get_by_phone(self, phone: str) -> User | None:
        stmt = select(User).where(User.phone == phone)
        return await self._session.scalar(stmt)

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username.lower())
        return await self._session.scalar(stmt)

    async def exists_by_any_identifier(self, username=None, email=None, phone=None) -> bool:
        conditions = []
        if username:
            conditions.append(User.username == username.lower())
        if email:
            conditions.append(User.email == email.lower())
        if phone:
            conditions.append(User.phone == phone)
        if not conditions:
            return False
        stmt = select(User).where(or_(*conditions)).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def create(self, **kwargs) -> User:
        user = User(**kwargs)
        self._session.add(user)
        await self._session.flush()
        return user

    async def update(self, user: User, **kwargs) -> User:
        for field, value in kwargs.items():
            if value is not None:
                setattr(user, field, value)
        await self._session.flush()
        return user

    async def delete(self, user: User) -> None:
        await self._session.delete(user)
        await self._session.flush()


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> Session:
        sess = Session(**kwargs)
        self._session.add(sess)
        await self._session.flush()
        return sess

    async def get_by_jti(self, jti: str) -> Session | None:
        from datetime import UTC
        now = datetime.now(UTC)
        stmt = select(Session).where(
            Session.refresh_token_jti == jti,
            Session.is_revoked.is_(False),
            Session.expires_at > now,
        )
        return await self._session.scalar(stmt)

    async def revoke(self, session_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Session).where(Session.id == session_id).values(is_revoked=True)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Session).where(Session.user_id == user_id).values(is_revoked=True)
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[Session]:
        stmt = (
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        return await self._session.scalar(stmt)

    async def get_or_create(self, name: str, description: str = "") -> Role:
        role = await self.get_by_name(name)
        if not role:
            role = Role(name=name, description=description)
            self._session.add(role)
            await self._session.flush()
        return role


class PhoneVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_for_user(self, user_id: uuid.UUID, phone: str) -> PhoneVerification | None:
        stmt = (
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user_id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used.is_(False),
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(PhoneVerification)
            .where(PhoneVerification.user_id == user_id, PhoneVerification.is_used.is_(False))
            .values(is_used=True)
        )

    async def create(self, **kwargs) -> PhoneVerification:
        pv = PhoneVerification(**kwargs)
        self._session.add(pv)
        await self._session.flush()
        return pv


class PhoneRegistrationTicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self, phone: str) -> PhoneRegistrationTicket | None:
        stmt = (
            select(PhoneRegistrationTicket)
            .where(
                PhoneRegistrationTicket.phone == phone,
                PhoneRegistrationTicket.is_used.is_(False),
            )
            .order_by(PhoneRegistrationTicket.created_at.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def create(self, **kwargs) -> PhoneRegistrationTicket:
        t = PhoneRegistrationTicket(**kwargs)
        self._session.add(t)
        await self._session.flush()
        return t

    async def revoke_all_for_phone(self, phone: str) -> None:
        await self._session.execute(
            update(PhoneRegistrationTicket)
            .where(
                PhoneRegistrationTicket.phone == phone,
                PhoneRegistrationTicket.is_used.is_(False),
            )
            .values(is_used=True)
        )


class AuthLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> AuthLog:
        entry = AuthLog(**kwargs)
        self._session.add(entry)
        await self._session.flush()
        return entry


class PasswordTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token(self, token: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.is_used.is_(False),
        )
        return await self._session.scalar(stmt)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )

    async def create(self, **kwargs) -> PasswordResetToken:
        pwt = PasswordResetToken(**kwargs)
        self._session.add(pwt)
        await self._session.flush()
        return pwt
