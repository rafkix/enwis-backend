"""'Test is also Playable' — ungated practice attempts.

No registration, no Exam, no time-window gating: a user just plays a
published Test directly. This is what powers test.enwis.uz. Exam
attempts (registration, scheduling, leaderboards, certificates) are a
completely separate flow in app.modules.exams and are unaffected.
"""

import random
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tests.models import Test, TestPracticeAnswer, TestPracticeAttempt


class PracticeAttemptNotFound(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Attempt not found")


class NotPracticeAttemptOwner(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, "You do not own this attempt")


class DuplicateActivePracticeAttempt(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "You already have an active practice attempt for this Test",
        )


class PracticeAttemptAlreadyCompleted(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, "Attempt already completed")


class TestNotPlayable(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "Only published Tests can be played",
        )


class TestPracticeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    async def _get_playable_test(self, test_id: uuid.UUID) -> Test:
        result = await self.db.execute(select(Test).where(Test.id == test_id))
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
        if test.status != "active":
            raise TestNotPlayable()
        return test

    def _grade(self, question, points: int, answer: dict) -> tuple[bool | None, int]:
        qtype = question.question_type
        selected = answer.get("selected_option_id")
        text = answer.get("text_answer")

        if qtype in ("single_choice", "image"):
            if not selected:
                return None, 0
            for c in question.choices:
                if c.id == selected and c.is_correct:
                    return True, points
            return False, 0

        if qtype == "short_answer":
            user_text = (text or "").strip().lower()
            correct_text = (question.correct_answer or "").strip().lower()
            if not user_text:
                return None, 0
            return (True, points) if user_text == correct_text else (False, 0)

        return None, 0

    # ── Question serialization ──────────────────────────────────────

    def _serialize_attempt_questions(self, test: Test) -> list[dict]:
        """Serialize a Test's questions for a player, WITHOUT is_correct.

        Grading happens exclusively in submit() against the DB copy of
        each Choice — nothing here is trusted back from the client.

        NOTE: if test.shuffle_questions / shuffle_answers is on, this
        produces a *fresh* random order every time it's called. That's
        fine for the initial start(), but it means resuming an
        in-progress attempt (or viewing /result) currently reshuffles
        the order again rather than reusing what the player originally
        saw. Answers still grade correctly either way (they're keyed by
        question_id / choice_id, not position), but the reshuffle-on-
        reload is a real UX rough edge. Fixing it properly means
        persisting the shown order (e.g. a JSON column on
        TestPracticeAttempt) — that's a follow-up, not done here.
        """
        test_questions = sorted(test.test_questions, key=lambda tq: tq.order)
        if test.shuffle_questions:
            test_questions = test_questions[:]
            random.shuffle(test_questions)

        serialized = []
        for tq in test_questions:
            question = tq.question
            choices = list(question.choices)
            if test.shuffle_answers:
                choices = choices[:]
                random.shuffle(choices)

            serialized.append({
                "id": question.id,
                "title": question.title,
                "question_type": question.question_type,
                "points": tq.points,
                "order": tq.order,
                "choices": [
                    {"id": c.id, "content": c.content, "order": c.order}
                    for c in choices
                ],
                "attachments": [
                    {
                        "id": a.id,
                        "file_type": a.file_type,
                        "file_url": a.file_url,
                        "file_name": a.file_name,
                    }
                    for a in question.attachments
                ],
            })
        return serialized

    # ── Start ────────────────────────────────────────────────────────

    async def start(
        self, test_id: uuid.UUID, user_id: uuid.UUID, group_quiz_id: uuid.UUID | None = None
    ) -> dict:
        test = await self._get_playable_test(test_id)

        existing = await self.db.execute(
            select(TestPracticeAttempt).where(
                TestPracticeAttempt.test_id == test_id,
                TestPracticeAttempt.user_id == user_id,
                TestPracticeAttempt.status == "in_progress",
            )
        )
        active_attempt = existing.scalar_one_or_none()
        if active_attempt:
            # start() is idempotent: re-hitting it (e.g. page reload)
            # resumes the existing in-progress attempt instead of 400ing.
            return {
                "id": active_attempt.id,
                "test_id": test_id,
                "status": "in_progress",
                "questions_count": len(test.test_questions),
                "max_score": active_attempt.max_score,
                "started_at": active_attempt.started_at,
                "expires_at": None,
                "questions": self._serialize_attempt_questions(test),
            }

        max_score = sum(tq.points for tq in test.test_questions)
        attempt = TestPracticeAttempt(
            test_id=test_id, user_id=user_id,
            status="in_progress", max_score=max_score,
            group_quiz_id=group_quiz_id,
        )
        self.db.add(attempt)
        await self.db.flush()
        await self.db.refresh(attempt)
        await self.db.commit()

        return {
            "id": attempt.id,
            "test_id": test_id,
            "status": "in_progress",
            "questions_count": len(test.test_questions),
            "max_score": max_score,
            "started_at": attempt.started_at,
            # No time-limit field exists on Test or TestSettings (checked
            # both models — negative_marking/auto_submit/result_visibility/
            # certificate_enabled is the whole set, no duration/minutes
            # column anywhere). There's nothing to compute expires_at
            # FROM, so it's returned as null rather than invented. If the
            # frontend Timer component requires a real deadline, that
            # needs a schema migration (e.g. Test.time_limit_minutes)
            # before this can be filled in honestly.
            "expires_at": None,
            "questions": self._serialize_attempt_questions(test),
        }

    async def _get_owned_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> TestPracticeAttempt:
        result = await self.db.execute(
            select(TestPracticeAttempt).where(TestPracticeAttempt.id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise PracticeAttemptNotFound()
        if attempt.user_id != user_id:
            raise NotPracticeAttemptOwner()
        return attempt

    # ── Save (draft) ────────────────────────────────────────────────

    async def save(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, answers_data: list[dict]
    ) -> dict:
        attempt = await self._get_owned_attempt(attempt_id, user_id)
        if attempt.status != "in_progress":
            raise PracticeAttemptAlreadyCompleted()

        for a in answers_data:
            qid = a.get("question_id")
            if not qid:
                continue
            existing = await self.db.execute(
                select(TestPracticeAnswer).where(
                    TestPracticeAnswer.attempt_id == attempt_id,
                    TestPracticeAnswer.question_id == qid,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.selected_option_id = a.get("selected_option_id")
                row.text_answer = a.get("text_answer")
            else:
                self.db.add(TestPracticeAnswer(
                    attempt_id=attempt_id, question_id=qid,
                    selected_option_id=a.get("selected_option_id"),
                    text_answer=a.get("text_answer"),
                ))
        await self.db.flush()
        await self.db.commit()
        return {"success": True, "saved_count": len(answers_data)}

    # ── Submit ───────────────────────────────────────────────────────

    async def submit(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, answers_data: list[dict]
    ) -> dict:
        attempt = await self._get_owned_attempt(attempt_id, user_id)
        if attempt.status != "in_progress":
            raise PracticeAttemptAlreadyCompleted()

        if answers_data:
            await self.save(attempt_id, user_id, answers_data)
            await self.db.refresh(attempt)

        test_result = await self.db.execute(select(Test).where(Test.id == attempt.test_id))
        test = test_result.scalar_one()

        questions_by_id = {tq.question_id: tq.question for tq in test.test_questions}
        points_by_id = {tq.question_id: tq.points for tq in test.test_questions}

        saved_answers = await self.db.execute(
            select(TestPracticeAnswer).where(TestPracticeAnswer.attempt_id == attempt_id)
        )
        total_score = 0
        for ans in saved_answers.scalars().all():
            question = questions_by_id.get(ans.question_id)
            if not question:
                continue
            is_correct, points = self._grade(
                question,
                points_by_id.get(ans.question_id, 0),
                {
                    "selected_option_id": ans.selected_option_id,
                    "text_answer": ans.text_answer,
                },
            )
            ans.is_correct = is_correct
            ans.points_earned = points
            total_score += points

        attempt.score = total_score
        attempt.percentage = (
            round(total_score / attempt.max_score * 100, 2) if attempt.max_score else 0.0
        )
        attempt.status = "completed"
        attempt.completed_at = self._now()
        await self.db.flush()
        await self.db.commit()

        return {
            "id": attempt.id,
            "status": "completed",
            "score": attempt.score,
            "max_score": attempt.max_score,
            "percentage": attempt.percentage,
        }

    # ── Result ───────────────────────────────────────────────────────

    async def get_result(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        attempt = await self._get_owned_attempt(attempt_id, user_id)
        test_result = await self.db.execute(select(Test).where(Test.id == attempt.test_id))
        test = test_result.scalar_one()
        return {
            "id": attempt.id,
            "test_id": attempt.test_id,
            "status": attempt.status,
            "score": attempt.score,
            "max_score": attempt.max_score,
            "percentage": attempt.percentage,
            "started_at": attempt.started_at,
            "completed_at": attempt.completed_at,
            "questions": self._serialize_attempt_questions(test),
            "answers": [
                {
                    "question_id": a.question_id,
                    "selected_option_id": a.selected_option_id,
                    "text_answer": a.text_answer,
                    "is_correct": a.is_correct,
                    "points_earned": a.points_earned,
                }
                for a in attempt.answers
            ],
        }

    # ── My results (across ALL tests — the simple-user "profile history") ──

    async def list_my_results(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        base_query = (
            select(TestPracticeAttempt, Test.title, Test.test_type)
            .join(Test, Test.id == TestPracticeAttempt.test_id)
            .where(TestPracticeAttempt.user_id == user_id)
            .order_by(TestPracticeAttempt.started_at.desc())
        )

        count_result = await self.db.execute(
            select(TestPracticeAttempt.id).where(TestPracticeAttempt.user_id == user_id)
        )
        total = len(count_result.all())

        offset = (page - 1) * per_page
        result = await self.db.execute(base_query.offset(offset).limit(per_page))
        rows = result.all()

        items = [
            {
                "attempt_id": attempt.id,
                "test_id": attempt.test_id,
                "test_title": title,
                "test_type": test_type,
                "status": attempt.status,
                "score": attempt.score,
                "max_score": attempt.max_score,
                "percentage": attempt.percentage,
                "started_at": attempt.started_at,
                "completed_at": attempt.completed_at,
            }
            for attempt, title, test_type in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page else 0,
        }

    async def list_attempts(self, test_id: uuid.UUID, user_id: uuid.UUID) -> list[dict]:
        result = await self.db.execute(
            select(TestPracticeAttempt)
            .where(
                TestPracticeAttempt.test_id == test_id,
                TestPracticeAttempt.user_id == user_id,
            )
            .order_by(TestPracticeAttempt.started_at.desc())
        )
        return [
            {
                "id": a.id,
                "status": a.status,
                "score": a.score,
                "max_score": a.max_score,
                "percentage": a.percentage,
                "started_at": a.started_at,
                "completed_at": a.completed_at,
            }
            for a in result.scalars().all()
        ]
