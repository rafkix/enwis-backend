import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tests.models import (
    Test,
    TestFavorite,
    TestPracticeAttempt,
    TestQuestion,
    TestSettings,
)

# Tests that are safe to expose on the public/anonymous surfaces
# (test.enwis.uz listing, trending/popular/etc.) — must be published
# and explicitly marked public.
_PUBLIC_FILTERS = (Test.status == "active", Test.visibility == "public")


class TestRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, test_id: uuid.UUID) -> Test | None:
        result = await self.db.execute(
            select(Test)
            .options(
                selectinload(Test.test_questions),
            )
            .where(Test.id == test_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_owner(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test | None:
        result = await self.db.execute(
            select(Test)
            .options(
                selectinload(Test.test_questions),
            )
            .where(Test.id == test_id, Test.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Test.id)).where(Test.owner_id == owner_id)
        )
        return result.scalar_one() or 0

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> dict:
        q = select(Test).where(Test.owner_id == owner_id)
        count_q = select(func.count(Test.id)).where(Test.owner_id == owner_id)

        if status_filter:
            q = q.where(Test.status == status_filter)
            count_q = count_q.where(Test.status == status_filter)
        if search:
            q = q.where(Test.title.ilike(f"%{search}%"))
            count_q = count_q.where(Test.title.ilike(f"%{search}%"))

        total = (await self.db.execute(count_q)).scalar_one()

        result = await self.db.execute(
            q.order_by(Test.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        tests = list(result.scalars().all())

        items = []
        for test in tests:
            tq_count = await self.db.execute(
                select(func.count()).select_from(TestQuestion)
                .where(TestQuestion.test_id == test.id)
            )
            q_total = tq_count.scalar_one()

            items.append({
                "id": test.id,
                "title": test.title,
                "description": test.description,
                "instructions": test.instructions,
                "cover_image": test.cover_image,
                "test_type": test.test_type,
                "status": test.status,
                "visibility": test.visibility,
                "shuffle_questions": test.shuffle_questions,
                "shuffle_answers": test.shuffle_answers,
                "show_result": test.show_result,
                "allow_review": test.allow_review,
                "negative_marking": test.negative_marking,
                "auto_submit": test.auto_submit,
                "publish_at": test.publish_at,
                "expire_at": test.expire_at,
                "owner_id": test.owner_id,
                "questions_count": q_total,
                "attempts_count": 0,
                "avg_score": 0.0,
                "created_at": test.created_at,
                "updated_at": test.updated_at,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    async def create(self, data: dict, owner_id: uuid.UUID) -> Test:
        test = Test(owner_id=owner_id, **data)
        self.db.add(test)
        await self.db.flush()
        await self.db.refresh(test)
        return test

    async def update(self, test_id: uuid.UUID, data: dict) -> Test:
        test = await self.get_by_id(test_id)
        if not test:
            raise ValueError("Test not found")
        for key, value in data.items():
            if value is not None and hasattr(test, key):
                setattr(test, key, value)
        await self.db.flush()
        await self.db.refresh(test)
        return test

    async def delete(self, test_id: uuid.UUID) -> None:
        test = await self.get_by_id(test_id)
        if test:
            await self.db.delete(test)
            await self.db.flush()

    # ── Public / anonymous browsing (test.enwis.uz) ─────────────────────
    #
    # NOTE: Test has no dedicated `category` / `subject` / `difficulty` /
    # `language` columns (only `test_type`, per the existing, unchanged
    # schema). Per the "do not change database schema" constraint, the
    # `category`/`subject` filters below match against `test_type` (the
    # closest existing field), and `difficulty`/`language` are accepted
    # for forward API compatibility but are currently no-ops — there is
    # no column to filter them against without an additive migration.

    async def _attempts_count_subquery(self):
        return (
            select(
                TestPracticeAttempt.test_id,
                func.count(TestPracticeAttempt.id).label("attempts_count"),
            )
            .group_by(TestPracticeAttempt.test_id)
            .subquery()
        )

    async def list_public(
        self,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        category: str | None = None,
        sort: str = "newest",
    ) -> dict:
        q = select(Test).where(*_PUBLIC_FILTERS)
        count_q = select(func.count(Test.id)).where(*_PUBLIC_FILTERS)

        if search:
            q = q.where(Test.title.ilike(f"%{search}%"))
            count_q = count_q.where(Test.title.ilike(f"%{search}%"))
        if category:
            q = q.where(Test.test_type == category)
            count_q = count_q.where(Test.test_type == category)

        total = (await self.db.execute(count_q)).scalar_one()

        if sort == "popular":
            sub = await self._attempts_count_subquery()
            q = (
                q.outerjoin(sub, sub.c.test_id == Test.id)
                .order_by(func.coalesce(sub.c.attempts_count, 0).desc())
            )
        elif sort == "oldest":
            q = q.order_by(Test.created_at.asc())
        else:  # "newest" (default)
            q = q.order_by(Test.created_at.desc())

        result = await self.db.execute(q.offset((page - 1) * per_page).limit(per_page))
        tests = list(result.scalars().all())

        items = []
        for test in tests:
            tq_count = await self.db.execute(
                select(func.count()).select_from(TestQuestion)
                .where(TestQuestion.test_id == test.id)
            )
            items.append({"test": test, "questions_count": tq_count.scalar_one()})

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    async def get_public_by_id_or_slug(self, id_or_slug: str) -> Test | None:
        """Public tests have no dedicated `slug` column, so the Test's
        UUID doubles as its slug (`/tests/public/{test.id}`)."""
        try:
            test_uuid = uuid.UUID(id_or_slug)
        except ValueError:
            return None
        result = await self.db.execute(
            select(Test)
            .options(selectinload(Test.test_questions))
            .where(Test.id == test_uuid, *_PUBLIC_FILTERS)
        )
        return result.scalar_one_or_none()

    async def list_trending(self, limit: int = 10, days: int = 7) -> list[Test]:
        since = datetime.now(UTC) - timedelta(days=days)
        sub = (
            select(
                TestPracticeAttempt.test_id,
                func.count(TestPracticeAttempt.id).label("recent_attempts"),
            )
            .where(TestPracticeAttempt.started_at >= since)
            .group_by(TestPracticeAttempt.test_id)
            .subquery()
        )
        result = await self.db.execute(
            select(Test)
            .join(sub, sub.c.test_id == Test.id)
            .where(*_PUBLIC_FILTERS)
            .order_by(sub.c.recent_attempts.desc())
            .limit(limit)
        )
        tests = list(result.scalars().all())
        if tests:
            return tests
        # fallback: nothing attempted recently yet, surface newest instead
        return await self._newest_public(limit)

    async def list_popular(self, limit: int = 10) -> list[Test]:
        sub = await self._attempts_count_subquery()
        result = await self.db.execute(
            select(Test)
            .outerjoin(sub, sub.c.test_id == Test.id)
            .where(*_PUBLIC_FILTERS)
            .order_by(func.coalesce(sub.c.attempts_count, 0).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 10) -> list[Test]:
        return await self._newest_public(limit)

    async def _newest_public(self, limit: int) -> list[Test]:
        result = await self.db.execute(
            select(Test).where(*_PUBLIC_FILTERS).order_by(Test.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_recommended(self, limit: int = 10) -> list[Test]:
        # NOTE: no personalization data (interests, history) exists on the
        # current schema, so recommendations best-effort fall back to the
        # most popular public tests. Revisit once a signals table exists.
        return await self.list_popular(limit)

    async def list_categories(self) -> list[dict]:
        result = await self.db.execute(
            select(Test.test_type, func.count(Test.id))
            .where(*_PUBLIC_FILTERS)
            .group_by(Test.test_type)
            .order_by(func.count(Test.id).desc())
        )
        return [{"name": name, "count": count} for name, count in result.all()]


class TestFavoriteRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def is_favorited(self, test_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(TestFavorite.id).where(
                TestFavorite.test_id == test_id, TestFavorite.user_id == user_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def add(self, test_id: uuid.UUID, user_id: uuid.UUID) -> TestFavorite:
        existing = await self.db.execute(
            select(TestFavorite).where(
                TestFavorite.test_id == test_id, TestFavorite.user_id == user_id
            )
        )
        fav = existing.scalar_one_or_none()
        if fav:
            return fav
        fav = TestFavorite(test_id=test_id, user_id=user_id)
        self.db.add(fav)
        await self.db.flush()
        await self.db.refresh(fav)
        return fav

    async def remove(self, test_id: uuid.UUID, user_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(TestFavorite).where(
                TestFavorite.test_id == test_id, TestFavorite.user_id == user_id
            )
        )
        fav = result.scalar_one_or_none()
        if fav:
            await self.db.delete(fav)
            await self.db.flush()

    async def list_for_user(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[Test], int]:
        count_result = await self.db.execute(
            select(func.count(TestFavorite.id)).where(TestFavorite.user_id == user_id)
        )
        total = count_result.scalar_one()

        offset = (page - 1) * per_page
        result = await self.db.execute(
            select(Test)
            .join(TestFavorite, TestFavorite.test_id == Test.id)
            .options(selectinload(Test.test_questions))
            .where(TestFavorite.user_id == user_id)
            .order_by(TestFavorite.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        return list(result.scalars().all()), total


class TestQuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_question(
        self, test_id: uuid.UUID, question_id: uuid.UUID,
        order: int | None = None, points: int = 1, required: bool = True,
    ) -> TestQuestion:
        if order is None:
            result = await self.db.execute(
                select(func.count(TestQuestion.id)).where(TestQuestion.test_id == test_id)
            )
            order = result.scalar_one() + 1

        tq = TestQuestion(
            test_id=test_id, question_id=question_id,
            order=order, points=points, required=required,
        )
        self.db.add(tq)
        await self.db.flush()
        await self.db.refresh(tq)
        return tq

    async def remove_question(self, test_id: uuid.UUID, tq_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(TestQuestion).where(
                TestQuestion.id == tq_id, TestQuestion.test_id == test_id
            )
        )
        tq = result.scalar_one_or_none()
        if tq:
            await self.db.delete(tq)
            await self.db.flush()

    async def get_by_test_and_question(
        self, test_id: uuid.UUID, question_id: uuid.UUID
    ) -> TestQuestion | None:
        result = await self.db.execute(
            select(TestQuestion).where(
                TestQuestion.test_id == test_id,
                TestQuestion.question_id == question_id,
            )
        )
        return result.scalar_one_or_none()

    async def remove_by_question(
        self, test_id: uuid.UUID, question_id: uuid.UUID
    ) -> None:
        tq = await self.get_by_test_and_question(test_id, question_id)
        if tq:
            await self.db.delete(tq)
            await self.db.flush()

    async def count_links_for_question(self, question_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(TestQuestion.id)).where(
                TestQuestion.question_id == question_id
            )
        )
        return result.scalar_one()

    async def update_question(
        self, tq_id: uuid.UUID, data: dict
    ) -> TestQuestion:
        result = await self.db.execute(
            select(TestQuestion).where(TestQuestion.id == tq_id)
        )
        tq = result.scalar_one_or_none()
        if not tq:
            raise ValueError("Test question not found")
        for key, value in data.items():
            if value is not None and hasattr(tq, key):
                setattr(tq, key, value)
        await self.db.flush()
        await self.db.refresh(tq)
        return tq

    async def reorder(
        self, test_id: uuid.UUID, question_ids: list[uuid.UUID],
    ) -> list[TestQuestion]:
        test_questions = []
        for i, qid in enumerate(question_ids):
            result = await self.db.execute(
                select(TestQuestion).where(
                    TestQuestion.test_id == test_id,
                    TestQuestion.id == qid,
                )
            )
            tq = result.scalar_one_or_none()
            if tq:
                tq.order = i + 1
                test_questions.append(tq)
        await self.db.flush()
        return test_questions

    async def reorder_by_question_ids(
        self, test_id: uuid.UUID, question_ids: list[uuid.UUID],
    ) -> list[TestQuestion]:
        test_questions = []
        for i, qid in enumerate(question_ids):
            result = await self.db.execute(
                select(TestQuestion).where(
                    TestQuestion.test_id == test_id,
                    TestQuestion.question_id == qid,
                )
            )
            tq = result.scalar_one_or_none()
            if tq:
                tq.order = i + 1
                test_questions.append(tq)
        await self.db.flush()
        return test_questions

    async def list_by_test(self, test_id: uuid.UUID) -> list[TestQuestion]:
        result = await self.db.execute(
            select(TestQuestion)
            .options(selectinload(TestQuestion.test))
            .where(TestQuestion.test_id == test_id)
            .order_by(TestQuestion.order)
        )
        return list(result.scalars().all())


class TestSettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_test(self, test_id: uuid.UUID) -> TestSettings | None:
        result = await self.db.execute(
            select(TestSettings).where(TestSettings.test_id == test_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, test_id: uuid.UUID, data: dict) -> TestSettings:
        existing = await self.get_by_test(test_id)
        if existing:
            for key, value in data.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        settings = TestSettings(test_id=test_id, **data)
        self.db.add(settings)
        await self.db.flush()
        await self.db.refresh(settings)
        return settings




# NOTE: TestParticipantRepository was removed — participants/registration
# are handled exclusively by app.modules.exams (ExamParticipant / apply
# flow) per the product spec: "Registration belongs to the Exam module".
# NOTE: TestAttemptRepository was removed — attempts are handled by
# app.modules.exams.attempt_repository per the product spec.
