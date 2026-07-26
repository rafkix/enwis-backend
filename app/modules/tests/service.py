import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.plans import (
    PlanTier,
    can_use_ai,
    check_test_limit,
    get_plan_limits,
    get_user_plan_tier,
)
from app.modules.auth.models import User
from app.modules.exams.ai import build_ai_prompt, call_ai_api
from app.modules.questions.models import Choice
from app.modules.questions.models import Question as QBQuestion
from app.modules.tests.models import (
    Test,
    TestQuestion,
    TestSettings,
)
from app.modules.tests.repository import (
    TestFavoriteRepository,
    TestQuestionRepository,
    TestRepository,
    TestSettingsRepository,
)


class TestLimitExceededException(HTTPException):
    def __init__(self, limit: int, tier: str) -> None:
        super().__init__(
            403,
            f"Your {tier} plan allows a maximum of {limit} tests. Please upgrade your plan.",
        )


class TestNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(404, "Test not found")


class TestNotEditableException(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            409,
            "Test is published and cannot be modified. Duplicate it first.",
        )


class AIFeatureNotAvailable(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            403,
            "AI question generation is not available on your current plan. "
            "Upgrade to PRO or PREMIUM.",
        )


class TestQuestionNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(404, "Test question not found")


class TestSettingsNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(404, "Test settings not found")


class TestService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TestRepository(db)
        self.tq_repo = TestQuestionRepository(db)
        self.settings_repo = TestSettingsRepository(db)
        self.favorite_repo = TestFavoriteRepository(db)

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def _get_user_tier(self, user_id: uuid.UUID) -> PlanTier:
        result = await self.db.execute(
            select(User.subscription_tier).where(User.id == user_id)
        )
        tier_str = result.scalar_one_or_none()
        return get_user_plan_tier(tier_str)

    async def _check_test_quota(self, owner_id: uuid.UUID) -> None:
        tier = await self._get_user_tier(owner_id)
        limits = get_plan_limits(tier)
        if limits.max_tests is None or limits.max_tests == -1:
            return
        current_count = await self.repo.count_by_owner(owner_id)
        if not check_test_limit(current_count, tier):
            raise TestLimitExceededException(limits.max_tests, tier.value)

    # ── Test CRUD ─────────────────────────────────────────────────────

    async def list_tests(
        self,
        owner_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> dict:
        return await self.repo.list_by_owner(owner_id, page, per_page, status_filter, search)

    async def get_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        test = await self.repo.get_by_id_owner(test_id, owner_id)
        if not test:
            raise TestNotFoundException()
        return test

    async def create_test(self, data: dict, owner_id: uuid.UUID) -> Test:
        await self._check_test_quota(owner_id)

        test = Test(
            title=data["title"],
            description=data.get("description"),
            instructions=data.get("instructions"),
            cover_image=data.get("cover_image"),
            test_type=data["test_type"],
            visibility=data.get("visibility", "private"),
            shuffle_questions=data.get("shuffle_questions", False),
            shuffle_answers=data.get("shuffle_answers", False),
            show_result=data.get("show_result", True),
            allow_review=data.get("allow_review", True),
            negative_marking=data.get("negative_marking", False),
            auto_submit=data.get("auto_submit", True),
            publish_at=data.get("publish_at"),
            expire_at=data.get("expire_at"),
            owner_id=owner_id,
            status="draft",
        )
        self.db.add(test)
        test.settings = TestSettings()
        await self.db.flush()
        await self.db.refresh(test)
        await self.db.commit()

        return test

    async def update_test(
        self, test_id: uuid.UUID, data: dict, owner_id: uuid.UUID
    ) -> Test:
        test = await self.get_test(test_id, owner_id)

        for key, value in data.items():
            if value is not None and hasattr(test, key):
                setattr(test, key, value)
        await self.db.flush()
        await self.db.refresh(test)
        await self.db.commit()
        return test

    async def delete_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        test = await self.get_test(test_id, owner_id)

        from app.modules.exams.models import Exam

        existing_exam = await self.db.execute(
            select(Exam.id).where(Exam.test_id == test_id).limit(1)
        )
        if existing_exam.scalar_one_or_none():
            raise HTTPException(
                409,
                "Cannot delete a test that has Exams referencing it. "
                "Archive the test instead, or delete the dependent Exams first.",
            )

        await self.db.delete(test)
        await self.db.flush()
        await self.db.commit()

    # ── Test publishing ───────────────────────────────────────────────

    async def publish_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        test = await self.get_test(test_id, owner_id)
        if test.status != "draft":
            raise HTTPException(400, "Only draft tests can be published")
        test.status = "active"
        await self.db.flush()
        await self.db.refresh(test)
        await self.db.commit()
        return test

    async def archive_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        test = await self.get_test(test_id, owner_id)
        test.status = "archived"
        await self.db.flush()
        await self.db.refresh(test)
        await self.db.commit()
        return test

    async def unpublish_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        test = await self.get_test(test_id, owner_id)
        if test.status != "active":
            raise HTTPException(400, "Only published (active) tests can be unpublished")
        test.status = "draft"
        await self.db.flush()
        await self.db.refresh(test)
        await self.db.commit()
        return test

    async def share_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> dict:
        test = await self.get_test(test_id, owner_id)
        if test.visibility != "public":
            test.visibility = "public"
            await self.db.flush()
            await self.db.refresh(test)
            await self.db.commit()
        # NOTE: no dedicated `slug` column exists (schema left unchanged),
        # so the Test's id doubles as its public slug.
        slug = str(test.id)
        return {
            "slug": slug,
            "public_url": f"https://test.enwis.uz/t/{slug}",
        }

    # ── Public browsing (test.enwis.uz — anonymous) ─────────────────────

    async def list_public_tests(
        self,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        category: str | None = None,
        difficulty: str | None = None,
        subject: str | None = None,
        language: str | None = None,
        sort: str = "newest",
    ) -> dict:
        return await self.repo.list_public(
            page=page, per_page=per_page, search=search, category=category, sort=sort,
        )

    async def get_public_test(self, id_or_slug: str) -> Test:
        test = await self.repo.get_public_by_id_or_slug(id_or_slug)
        if not test:
            raise TestNotFoundException()
        return test

    async def get_public_test_statistics(self, id_or_slug: str) -> dict:
        test = await self.get_public_test(id_or_slug)
        return await self._compute_statistics(test)

    async def list_trending_tests(self, limit: int = 10) -> list[Test]:
        return await self.repo.list_trending(limit)

    async def list_popular_tests(self, limit: int = 10) -> list[Test]:
        return await self.repo.list_popular(limit)

    async def list_recent_tests(self, limit: int = 10) -> list[Test]:
        return await self.repo.list_recent(limit)

    async def list_recommended_tests(self, limit: int = 10) -> list[Test]:
        return await self.repo.list_recommended(limit)

    async def list_categories(self) -> list[dict]:
        return await self.repo.list_categories()

    # ── Favorites ────────────────────────────────────────────────────────

    async def favorite_test(self, test_id: uuid.UUID, user_id: uuid.UUID) -> None:
        # Any published+public test can be favorited, whether or not the
        # user owns it — so we look it up as a public test, not by owner.
        test = await self.repo.get_by_id(test_id)
        if not test or test.status != "active" or test.visibility != "public":
            raise TestNotFoundException()
        await self.favorite_repo.add(test_id, user_id)
        await self.db.commit()

    async def unfavorite_test(self, test_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self.favorite_repo.remove(test_id, user_id)
        await self.db.commit()

    async def list_favorites(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        tests, total = await self.favorite_repo.list_for_user(user_id, page, per_page)
        return {
            "items": tests,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page else 0,
        }

    # ── Import previews (parse without persisting) ──────────────────────

    async def preview_import_json(
        self, test_id: uuid.UUID, questions_data: list[dict], owner_id: uuid.UUID,
    ) -> dict:
        await self.get_test(test_id, owner_id)
        return {"items": questions_data, "count": len(questions_data), "errors": []}

    async def preview_import_excel(
        self, test_id: uuid.UUID, file_bytes: bytes, owner_id: uuid.UUID,
    ) -> dict:
        from app.modules.questions.import_utils import parse_excel

        await self.get_test(test_id, owner_id)
        questions_data, errors = parse_excel(file_bytes)
        return {"items": questions_data, "count": len(questions_data), "errors": errors}

    async def preview_import_csv(
        self, test_id: uuid.UUID, file_bytes: bytes, owner_id: uuid.UUID,
    ) -> dict:
        from app.modules.questions.import_utils import parse_csv

        await self.get_test(test_id, owner_id)
        questions_data, errors = parse_csv(file_bytes)
        return {"items": questions_data, "count": len(questions_data), "errors": errors}

    async def duplicate_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> Test:
        await self._check_test_quota(owner_id)

        original = await self.repo.get_by_id_owner(test_id, owner_id)
        if not original:
            raise TestNotFoundException()

        new_test = Test(
            title=f"{original.title} (Copy)",
            description=original.description,
            instructions=original.instructions,
            cover_image=original.cover_image,
            test_type=original.test_type,
            status="draft",
            visibility="private",
            shuffle_questions=original.shuffle_questions,
            shuffle_answers=original.shuffle_answers,
            show_result=original.show_result,
            allow_review=original.allow_review,
            negative_marking=original.negative_marking,
            auto_submit=original.auto_submit,
            owner_id=owner_id,
        )
        self.db.add(new_test)
        await self.db.flush()

        for tq in original.test_questions:
            new_tq = TestQuestion(
                test_id=new_test.id,
                question_id=tq.question_id,
                order=tq.order,
                points=tq.points,
                required=tq.required,
            )
            self.db.add(new_tq)

        original_settings = original.settings
        settings = TestSettings(
            test_id=new_test.id,
            negative_marking=(
                original_settings.negative_marking if original_settings else False
            ),
            auto_submit=(
                original_settings.auto_submit if original_settings else True
            ),
            result_visibility=(
                original_settings.result_visibility if original_settings else "immediate"
            ),
            certificate_enabled=(
                original_settings.certificate_enabled if original_settings else False
            ),
        )
        self.db.add(settings)

        await self.db.flush()
        await self.db.refresh(new_test)
        await self.db.commit()
        return new_test

    # ── Questions (Bank) ─────────────────────────────────────────────

    async def add_question(
        self, test_id: uuid.UUID, question_id: uuid.UUID,
        owner_id: uuid.UUID, order: int | None = None,
        points: int = 1, required: bool = True,
    ) -> TestQuestion:
        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()
        return await self.tq_repo.add_question(test_id, question_id, order, points, required)

    async def update_question(
        self, tq_id: uuid.UUID, data: dict, owner_id: uuid.UUID
    ) -> TestQuestion:
        result = await self.db.execute(
            select(TestQuestion).options(selectinload(TestQuestion.test))
            .where(TestQuestion.id == tq_id)
        )
        tq = result.scalar_one_or_none()
        if not tq:
            raise TestQuestionNotFoundException()
        if tq.test.owner_id != owner_id:
            raise HTTPException(403, "Not authorized")
        if tq.test.status == "active":
            raise TestNotEditableException()
        return await self.tq_repo.update_question(tq_id, data)

    async def delete_question(
        self, test_id: uuid.UUID, tq_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()
        await self.tq_repo.remove_question(test_id, tq_id)

    async def add_bank_questions(
        self, test_id: uuid.UUID, question_ids: list[uuid.UUID],
        owner_id: uuid.UUID,
    ) -> list[TestQuestion]:
        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        created: list[TestQuestion] = []
        for qid in question_ids:
            tq = await self.tq_repo.add_question(test_id, qid)
            created.append(tq)
        return created

    async def reorder_questions(
        self, test_id: uuid.UUID, question_ids: list[uuid.UUID], owner_id: uuid.UUID
    ) -> list[TestQuestion]:
        await self.get_test(test_id, owner_id)
        return await self.tq_repo.reorder_by_question_ids(test_id, question_ids)

    # ── Questions (full content — Question now lives entirely inside Test) ──

    async def list_questions_full(
        self, test_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[QBQuestion]:
        await self.get_test(test_id, owner_id)
        tqs = await self.tq_repo.list_by_test(test_id)

        if not tqs:
            return []
        q_ids = [tq.question_id for tq in tqs]
        result = await self.db.execute(
            select(QBQuestion)
            .options(selectinload(QBQuestion.choices))
            .where(QBQuestion.id.in_(q_ids))
        )
        by_id = {q.id: q for q in result.scalars().all()}
        # preserve Test-defined order
        return [by_id[tq.question_id] for tq in tqs if tq.question_id in by_id]

    async def create_question_in_test(
        self, test_id: uuid.UUID, data: dict, owner_id: uuid.UUID,
    ) -> QBQuestion:
        from app.modules.tests.question_service import QuestionService

        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        question = await QuestionService(self.db).create_question(data, owner_id)
        await self.tq_repo.add_question(
            test_id, question.id, points=data.get("score", 1),
        )
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def update_question_in_test(
        self, test_id: uuid.UUID, question_id: uuid.UUID, data: dict,
        owner_id: uuid.UUID,
    ) -> QBQuestion:
        from app.modules.tests.question_service import QuestionService

        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        link = await self.tq_repo.get_by_test_and_question(test_id, question_id)
        if not link:
            raise TestQuestionNotFoundException()

        question = await QuestionService(self.db).update_question(
            question_id, data, owner_id,
        )
        if "score" in data and data["score"] is not None:
            await self.tq_repo.update_question(link.id, {"points": data["score"]})
        await self.db.commit()
        return question

    async def delete_question_from_test(
        self, test_id: uuid.UUID, question_id: uuid.UUID, owner_id: uuid.UUID,
    ) -> None:
        from app.modules.tests.question_service import QuestionService

        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        link = await self.tq_repo.get_by_test_and_question(test_id, question_id)
        if not link:
            raise TestQuestionNotFoundException()

        await self.tq_repo.remove_by_question(test_id, question_id)

        # Question is no longer independently addressable — if no other
        # Test references it anymore, delete the underlying entity too.
        remaining = await self.tq_repo.count_links_for_question(question_id)
        if remaining == 0:
            await QuestionService(self.db).delete_question(question_id, owner_id)
        await self.db.commit()

    # ── Import ────────────────────────────────────────────────────────

    async def import_questions_json(
        self, test_id: uuid.UUID, questions_data: list[dict], owner_id: uuid.UUID,
    ) -> list[QBQuestion]:
        from app.modules.tests.question_service import QuestionService

        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        questions = await QuestionService(self.db).bulk_create_questions(
            questions_data, owner_id,
        )
        for q, data in zip(questions, questions_data, strict=False):
            await self.tq_repo.add_question(
                test_id, q.id, points=data.get("score", 1),
            )
        await self.db.commit()
        return questions

    async def import_questions_excel(
        self, test_id: uuid.UUID, file_bytes: bytes, owner_id: uuid.UUID,
    ) -> dict:
        from app.modules.questions.import_utils import parse_excel

        questions_data, errors = parse_excel(file_bytes)
        created = await self.import_questions_json(test_id, questions_data, owner_id)
        return {"created": len(created), "errors": errors}

    async def import_questions_csv(
        self, test_id: uuid.UUID, file_bytes: bytes, owner_id: uuid.UUID,
    ) -> dict:
        from app.modules.questions.import_utils import parse_csv

        questions_data, errors = parse_csv(file_bytes)
        created = await self.import_questions_json(test_id, questions_data, owner_id)
        return {"created": len(created), "errors": errors}

    # ── Export ────────────────────────────────────────────────────────

    async def export_questions_json(
        self, test_id: uuid.UUID, owner_id: uuid.UUID,
    ) -> list[dict]:
        questions = await self.list_questions_full(test_id, owner_id)
        return [
            {
                "title": q.title,
                "question_type": q.question_type,
                "difficulty": q.difficulty,
                "score": q.score,
                "explanation": q.explanation,
                "correct_answer": q.correct_answer,
                "choices": [
                    {"content": c.content, "is_correct": c.is_correct}
                    for c in q.choices
                ],
            }
            for q in questions
        ]

    async def export_questions_excel(self, test_id: uuid.UUID, owner_id: uuid.UUID):
        from io import BytesIO

        from openpyxl import Workbook

        from app.modules.questions.import_utils import TEMPLATE_HEADERS

        questions = await self.list_questions_full(test_id, owner_id)
        wb = Workbook()
        ws = wb.active
        ws.title = "Questions"
        ws.append(TEMPLATE_HEADERS)
        for q in questions:
            row = [q.title, q.question_type, q.score, q.explanation or ""]
            choices = list(q.choices)[:4]
            for i in range(4):
                if i < len(choices):
                    row += [choices[i].content, choices[i].is_correct]
                else:
                    row += ["", ""]
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    async def export_questions_csv(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> str:
        import csv
        import io

        from app.modules.questions.import_utils import TEMPLATE_HEADERS

        questions = await self.list_questions_full(test_id, owner_id)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(TEMPLATE_HEADERS)
        for q in questions:
            row = [q.title, q.question_type, q.score, q.explanation or ""]
            choices = list(q.choices)[:4]
            for i in range(4):
                if i < len(choices):
                    row += [choices[i].content, choices[i].is_correct]
                else:
                    row += ["", ""]
            writer.writerow(row)
        return buf.getvalue()

    # ── Preview ───────────────────────────────────────────────────────

    async def preview_test(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> dict:
        test = await self.get_test(test_id, owner_id)
        questions = await self.list_questions_full(test_id, owner_id)
        return {
            "id": test.id,
            "title": test.title,
            "description": test.description,
            "instructions": test.instructions,
            "shuffle_questions": test.shuffle_questions,
            "shuffle_answers": test.shuffle_answers,
            "questions_count": len(questions),
            "total_points": sum(q.score for q in questions),
            "questions": [
                {
                    "id": q.id,
                    "title": q.title,
                    "question_type": q.question_type,
                    "score": q.score,
                    "choices": [
                        {"id": c.id, "content": c.content} for c in q.choices
                    ],
                }
                for q in questions
            ],
        }

    # ── Statistics ────────────────────────────────────────────────────

    async def get_statistics(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> dict:
        test = await self.get_test(test_id, owner_id)
        return await self._compute_statistics(test)

    async def _compute_statistics(self, test: Test) -> dict:
        from app.modules.exams.models import Exam, ExamAttempt

        test_id = test.id
        tqs = await self.tq_repo.list_by_test(test_id)
        questions_count = len(tqs)

        exam_ids_result = await self.db.execute(
            select(Exam.id).where(Exam.test_id == test_id)
        )
        exam_ids = [row[0] for row in exam_ids_result.all()]

        attempts_count = 0
        avg_score = 0.0
        avg_time_seconds = 0.0
        if exam_ids:
            attempts_result = await self.db.execute(
                select(ExamAttempt).where(
                    ExamAttempt.exam_id.in_(exam_ids),
                    ExamAttempt.is_completed.is_(True),
                )
            )
            attempts = list(attempts_result.scalars().all())
            attempts_count = len(attempts)
            if attempts_count:
                avg_score = sum(a.score or 0 for a in attempts) / attempts_count
                durations = [
                    (a.completed_at - a.started_at).total_seconds()
                    for a in attempts
                    if a.completed_at and a.started_at
                ]
                if durations:
                    avg_time_seconds = sum(durations) / len(durations)

        return {
            "test_id": test.id,
            "questions_count": questions_count,
            "exams_count": len(exam_ids),
            "times_used": attempts_count,
            "average_score": round(avg_score, 2),
            "average_time_seconds": round(avg_time_seconds, 1),
            "last_updated": test.updated_at,
        }

    # ── Settings ──────────────────────────────────────────────────────

    async def get_settings(self, test_id: uuid.UUID, owner_id: uuid.UUID) -> TestSettings | None:
        test = await self.repo.get_by_id_owner(test_id, owner_id)
        if not test:
            raise TestNotFoundException()
        return await self.settings_repo.get_by_test(test_id)

    async def update_settings(
        self, test_id: uuid.UUID, data: dict, owner_id: uuid.UUID
    ) -> TestSettings:
        test = await self.repo.get_by_id_owner(test_id, owner_id)
        if not test:
            raise TestNotFoundException()
        return await self.settings_repo.upsert(test_id, data)

    # ── AI ────────────────────────────────────────────────────────────

    async def generate_questions(
        self,
        test_id: uuid.UUID,
        topic: str,
        owner_id: uuid.UUID,
        count: int = 5,
        question_types: list[str] | None = None,
        language: str = "en",
    ) -> list[TestQuestion]:
        test = await self.get_test(test_id, owner_id)
        if test.status == "active":
            raise TestNotEditableException()

        tier = await self._get_user_tier(owner_id)
        if not can_use_ai(tier):
            raise AIFeatureNotAvailable()

        count = max(1, min(count, 20))

        prompt = build_ai_prompt(topic, count, question_types, language)
        questions_data = await call_ai_api(prompt)

        if isinstance(questions_data, dict):
            questions_data = [questions_data]

        created: list[TestQuestion] = []
        for data in questions_data:
            qb_question = QBQuestion(
                title=data.get("text", ""),
                question_type=data.get("question_type", "single_choice"),
                score=data.get("points", 1),
                explanation=data.get("explanation"),
                correct_answer=data.get("correct_answer"),
                owner_id=owner_id,
            )
            self.db.add(qb_question)
            await self.db.flush()

            for opt_data in data.get("options", []):
                choice = Choice(
                    question_id=qb_question.id,
                    content=opt_data.get("text", ""),
                    is_correct=opt_data.get("is_correct", False),
                )
                self.db.add(choice)

            await self.db.flush()

            tq = await self.tq_repo.add_question(
                test_id, qb_question.id,
                points=data.get("points", 1),
            )
            created.append(tq)

        await self.db.commit()
        return created
