import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.exams.attempt_constants import (
    GRADE_F,
    GRADE_THRESHOLDS,
)
from app.modules.exams.attempt_exceptions import (
    AttemptNotFound,
    NotAttemptOwner,
)
from app.modules.exams.models import Exam

if TYPE_CHECKING:
    from app.modules.exams.attempt_repository import AttemptRepository


class AttemptReviewService:
    """Handles attempt review with detailed answer breakdown."""

    def __init__(self, db: AsyncSession, repo: "AttemptRepository"):
        self.db = db
        self.repo = repo

    @staticmethod
    def _compute_grade(percentage: float) -> str:
        for grade, threshold in sorted(
            GRADE_THRESHOLDS.items(), key=lambda x: x[1], reverse=True
        ):
            if percentage >= threshold:
                return grade
        return GRADE_F

    @staticmethod
    def _compute_time_spent(started_at: datetime, completed_at: datetime | None) -> int:
        end = completed_at or datetime.now(UTC)
        return max(0, int((end - started_at).total_seconds()))

    @staticmethod
    def _normalize_options(question) -> list[dict]:
        if hasattr(question, "options") and question.options:
            return [
                {"id": o.id, "text": o.text, "is_correct": o.is_correct}
                for o in question.options
            ]
        if hasattr(question, "choices") and question.choices:
            return [
                {"id": c.id, "text": c.content, "is_correct": c.is_correct}
                for c in question.choices
            ]
        return []

    def _normalize_question(self, question, order: int = 0) -> dict:
        is_legacy = hasattr(question, "options")
        return {
            "id": question.id,
            "question_type": (
                question.question_type.value
                if hasattr(question.question_type, "value")
                else str(question.question_type)
            ),
            "points": question.points if is_legacy else question.score,
            "text": question.text if is_legacy else question.title,
            "explanation": getattr(question, "explanation", None),
            "correct_answer": getattr(question, "correct_answer", None),
            "options": self._normalize_options(question),
            "order": order,
        }

    def _get_all_exam_questions(self, exam) -> list[dict]:
        questions = []
        if exam.test and hasattr(exam.test, "test_questions"):
            for tq in exam.test.test_questions:
                q = tq.question if hasattr(tq, "question") else None
                if q:
                    questions.append(self._normalize_question(q, tq.order or 0))
        questions.sort(key=lambda x: x["order"])
        return questions

    async def review_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        attempt = await self.repo.get_attempt_with_relations(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if not attempt.is_completed:
            from fastapi import HTTPException
            raise HTTPException(400, "Cannot review an incomplete attempt")

        exam = attempt.exam
        passing_score = await self._get_exam_passing_score(attempt.exam_id)

        answers_map: dict[uuid.UUID, list] = {}
        for a in attempt.answers:
            answers_map.setdefault(a.question_id, []).append(a)

        all_questions = self._get_all_exam_questions(exam)

        answer_details = []
        for q in all_questions:
            user_answers = answers_map.get(q["id"], [])
            qtype = q["question_type"]
            options = q["options"]

            selected_text = None
            text_answer = None
            is_correct = None
            points_earned = 0

            if qtype in ("single_choice", "image"):
                if user_answers:
                    sid = user_answers[0].selected_option_id
                    for opt in options:
                        if opt["id"] == sid:
                            selected_text = opt["text"]
                            break
                    is_correct = user_answers[0].is_correct
                    points_earned = user_answers[0].points_earned
            elif qtype == "short_answer":
                if user_answers:
                    text_answer = user_answers[0].text_answer
                    is_correct = user_answers[0].is_correct
                    points_earned = user_answers[0].points_earned

            correct_text = None
            correct_answer_val = None
            if qtype in ("single_choice", "image"):
                for opt in options:
                    if opt["is_correct"]:
                        correct_text = opt["text"]
                        break
            else:
                correct_answer_val = q["correct_answer"]

            answer_details.append({
                "question_id": q["id"],
                "question_text": q["text"],
                "question_type": qtype,
                "points": q["points"],
                "selected_option_text": selected_text,
                "text_answer": text_answer,
                "correct_answer": correct_answer_val,
                "correct_option_text": correct_text,
                "is_correct": is_correct,
                "points_earned": points_earned,
                "order": q["order"],
                "explanation": q["explanation"],
            })

        time_spent = self._compute_time_spent(attempt.started_at, attempt.completed_at)
        total_points = attempt.total_points or 1
        score = attempt.score or 0
        percentage = round((score / total_points * 100), 2)
        passed = percentage >= passing_score
        grade = self._compute_grade(percentage)

        r = await self.db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one_or_none()
        username = user.username or user.full_name if user else None

        return {
            "id": attempt.id,
            "exam_id": attempt.exam_id,
            "exam_title": exam.title if exam else "",
            "user_id": attempt.user_id,
            "username": username,
            "status": "submitted",
            "score": score,
            "total_points": total_points,
            "percentage": percentage,
            "grade": grade,
            "passed": passed,
            "started_at": attempt.started_at,
            "completed_at": attempt.completed_at,
            "time_spent_seconds": time_spent,
            "answers": answer_details,
        }

    async def _get_exam_passing_score(self, exam_id: uuid.UUID) -> int:
        result = await self.db.execute(select(Exam.passing_score).where(Exam.id == exam_id))
        return result.scalar_one_or_none() or 60