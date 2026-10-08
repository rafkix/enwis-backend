import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.exams.attempt_constants import (
    AUTO_GRACE_SECONDS,
    GRADE_F,
    GRADE_THRESHOLDS,
)
from app.modules.exams.attempt_exceptions import (
    AttemptAlreadyCompleted,
    AttemptNotFound,
    DuplicateActiveAttempt,
    ExamNotActive,
    ExamTimeExpired,
    InvalidAnswerData,
    MaxAttemptsReached,
    NotAttemptOwner,
    NotExamOwner,
)
from app.modules.exams.attempt_leaderboard_service import AttemptLeaderboardService
from app.modules.exams.attempt_repository import AttemptRepository
from app.modules.exams.attempt_review_service import AttemptReviewService
from app.modules.exams.attempt_stats_service import AttemptStatsService
from app.modules.exams.models import Exam, ExamAttempt, QuestionAnswer, Result

if TYPE_CHECKING:
    pass


class AttemptService:
    """Main orchestrator for exam attempt lifecycle.
    Delegates to specialized services for grading, leaderboard, stats, and review.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AttemptRepository(db)

        # Composed services
        self._leaderboard = AttemptLeaderboardService(db, self.repo)
        self._stats = AttemptStatsService(db, self.repo)
        self._review = AttemptReviewService(db, self.repo)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

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
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        return max(0, int((end - started_at).total_seconds()))

    @staticmethod
    def _get_status(attempt: ExamAttempt) -> str:
        return "submitted" if attempt.is_completed else "in_progress"

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

    async def _get_exam_passing_score(self, exam_id: uuid.UUID) -> int:
        from sqlalchemy import select as sel

        result = await self.db.execute(sel(Exam.passing_score).where(Exam.id == exam_id))
        return result.scalar_one_or_none() or 60

    # ── Start Attempt ────────────────────────────────────────────────

    async def start_attempt(self, exam_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        exam = await self.repo.get_active_exam(exam_id)
        if not exam:
            raise ExamNotActive()

        attempt_count = await self.repo.count_user_attempts(exam_id, user_id)
        if attempt_count >= exam.max_attempts:
            raise MaxAttemptsReached(exam.max_attempts)

        existing = await self.repo.get_active_attempt(exam_id, user_id)
        if existing:
            raise DuplicateActiveAttempt()

        all_questions = self._get_all_exam_questions(exam)
        total_points = sum(q["points"] for q in all_questions)
        attempt = await self.repo.create_attempt(exam_id, user_id, total_points)

        time_limit = exam.duration_minutes
        time_remaining = time_limit * 60 if time_limit else None

        return {
            "id": attempt.id,
            "exam_id": attempt.exam_id,
            "user_id": attempt.user_id,
            "status": "in_progress",
            "score": attempt.score,
            "total_points": attempt.total_points,
            "started_at": attempt.started_at,
            "completed_at": attempt.completed_at,
            "time_limit_minutes": time_limit,
            "time_remaining_seconds": time_remaining,
        }

    # ── Resume Attempt ───────────────────────────────────────────────

    # ── Get Questions During Active Attempt ────────────────────────────

    async def get_attempt_questions(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        """Student-facing question list for an in-progress attempt.

        Strips correct_answer / is_correct so a student can never read
        the answer key while the exam is still open.
        """
        attempt = await self.repo.get_attempt_with_relations(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if attempt.is_completed:
            raise AttemptAlreadyCompleted()

        exam = attempt.exam
        if not exam:
            raise ExamNotActive()

        time_remaining = None
        if exam.duration_minutes:
            elapsed = self._compute_time_spent(attempt.started_at, None)
            time_remaining = max(0, exam.duration_minutes * 60 - elapsed)
            if time_remaining <= 0:
                raise ExamTimeExpired()

        saved = {a.question_id: a for a in (attempt.answers or [])}

        questions = []
        for q in self._get_all_exam_questions(exam):
            saved_answer = saved.get(q["id"])
            questions.append({
                "id": q["id"],
                "question_type": q["question_type"],
                "points": q["points"],
                "text": q["text"],
                "order": q["order"],
                "options": [
                    {"id": o["id"], "text": o["text"]} for o in q["options"]
                ],
                "saved_answer": (
                    {
                        "selected_option_id": saved_answer.selected_option_id,
                        "text_answer": saved_answer.text_answer,
                    }
                    if saved_answer else None
                ),
            })

        return {
            "attempt_id": attempt.id,
            "exam_id": exam.id,
            "time_remaining_seconds": time_remaining,
            "questions": questions,
        }

    async def resume_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        attempt = await self.repo.get_attempt_with_relations(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if attempt.is_completed:
            raise AttemptAlreadyCompleted()

        exam = attempt.exam
        if not exam:
            raise ExamNotActive()

        elapsed = self._compute_time_spent(attempt.started_at, None)
        time_limit = exam.duration_minutes
        time_remaining = None
        if time_limit:
            time_remaining = max(0, time_limit * 60 - elapsed + AUTO_GRACE_SECONDS)
            if time_remaining <= 0:
                raise ExamTimeExpired()

        saved = []
        for ans in attempt.answers:
            item: dict = {"question_id": ans.question_id}
            if ans.selected_option_id:
                item["selected_option_id"] = ans.selected_option_id
            if ans.text_answer:
                item["text_answer"] = ans.text_answer
            saved.append(item)

        all_questions = self._get_all_exam_questions(exam)

        return {
            "attempt_id": attempt.id,
            "exam_id": exam.id,
            "status": "in_progress",
            "score": attempt.score,
            "total_points": attempt.total_points,
            "started_at": attempt.started_at,
            "time_limit_minutes": time_limit,
            "time_remaining_seconds": time_remaining,
            "saved_answers": saved,
            "questions_count": len(all_questions),
        }

    # ── Save Answers (in-progress) ───────────────────────────────────

    async def save_answers(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, answers_data: list[dict]
    ) -> dict:
        attempt = await self.repo.get_attempt_by_id(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if attempt.is_completed:
            raise AttemptAlreadyCompleted()

        qids = [ans["question_id"] for ans in answers_data if ans.get("question_id")]
        await self.repo.delete_answers_for_questions(attempt_id, qids)

        new_rows = []
        for ans in answers_data:
            qid = ans.get("question_id")
            if not qid:
                continue

            selected_ids = ans.get("selected_option_ids")
            selected_id = ans.get("selected_option_id")

            if selected_ids and len(selected_ids) > 0:
                for sid in selected_ids:
                    new_rows.append(
                        QuestionAnswer(
                            attempt_id=attempt_id,
                            question_id=qid,
                            selected_option_id=sid,
                            text_answer=ans.get("text_answer"),
                        )
                    )
            else:
                new_rows.append(
                    QuestionAnswer(
                        attempt_id=attempt_id,
                        question_id=qid,
                        selected_option_id=selected_id,
                        text_answer=ans.get("text_answer"),
                    )
                )

        self.db.add_all(new_rows)
        await self.db.flush()
        return {"success": True, "message": "Answers saved", "saved_count": len(answers_data)}

    # ── Submit Attempt ───────────────────────────────────────────────

    async def submit_attempt(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, answers_data: list[dict]
    ) -> dict:
        attempt = await self.repo.get_attempt_with_relations(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if attempt.is_completed:
            raise AttemptAlreadyCompleted()

        exam = attempt.exam
        if not exam:
            raise ExamNotActive()

        elapsed = self._compute_time_spent(attempt.started_at, None)
        time_limit = exam.duration_minutes
        if time_limit:
            time_remaining = time_limit * 60 - elapsed + AUTO_GRACE_SECONDS
            if time_remaining <= 0:
                raise ExamTimeExpired()

        all_questions = self._get_all_exam_questions(exam)
        questions_map = {q["id"]: q for q in all_questions}

        existing_answers = await self.repo.get_answers_for_attempt(attempt_id)
        for ea in existing_answers:
            await self.db.delete(ea)
        await self.db.flush()

        # Delegate grading to grading service
        total_score = 0
        correct_count = 0
        wrong_count = 0
        unanswered_count = 0

        for ans_data in answers_data:
            qid = ans_data.get("question_id")
            if not qid:
                unanswered_count += 1
                continue

            question = questions_map.get(qid)
            if not question:
                unanswered_count += 1
                continue

            is_correct, points_earned = self._grade_question(question, ans_data)
            total_score += points_earned

            if is_correct is True:
                correct_count += 1
            elif is_correct is False:
                wrong_count += 1
            else:
                unanswered_count += 1

            selected_ids = ans_data.get("selected_option_ids")
            selected_id = ans_data.get("selected_option_id")

            if selected_ids and len(selected_ids) > 0:
                for sid in selected_ids:
                    self.db.add(
                        QuestionAnswer(
                            attempt_id=attempt_id,
                            question_id=qid,
                            selected_option_id=sid,
                            text_answer=ans_data.get("text_answer"),
                            is_correct=is_correct,
                            points_earned=points_earned,
                        )
                    )
            else:
                self.db.add(
                    QuestionAnswer(
                        attempt_id=attempt_id,
                        question_id=qid,
                        selected_option_id=selected_id,
                        text_answer=ans_data.get("text_answer"),
                        is_correct=is_correct,
                        points_earned=points_earned,
                    )
                )

        submitted = await self.repo.complete_attempt(attempt_id, total_score)
        total_points = submitted.total_points or 1

        time_spent = self._compute_time_spent(attempt.started_at, submitted.completed_at)
        percentage = round((total_score / total_points * 100), 2) if total_points else 0.0
        passed = percentage >= (exam.passing_score or 60)
        grade = self._compute_grade(percentage)

        result = Result(
            attempt_id=attempt_id,
            total_score=total_score,
            max_score=total_points,
            percentage=percentage,
            grade=grade,
            correct_count=correct_count,
            wrong_count=wrong_count,
            unanswered_count=unanswered_count,
            time_spent_seconds=time_spent,
            passed=passed,
            graded_by="auto",
            graded_at=self._now(),
        )
        self.db.add(result)
        await self.db.flush()

        from app.modules.notifications.events import notify_result_ready

        await notify_result_ready(
            self.db,
            user_id=attempt.user_id,
            test_title=exam.title,
            score=percentage,
        )

        if passed:
            from app.modules.exams.certificate_service import CertificateService

            await CertificateService(self.db).issue_for_attempt(attempt)

        return {
            "attempt_id": attempt_id,
            "status": "submitted",
            "score": total_score,
            "total_points": total_points,
            "percentage": percentage,
            "grade": grade,
            "passed": passed,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "unanswered_count": unanswered_count,
            "time_spent_seconds": time_spent,
            "message": (
                "Exam submitted successfully" if passed else "Exam submitted but you did not pass"
            ),
        }

    # ── Auto-grading Engine ──────────────────────────────────────────

    def _grade_question(self, question: dict, answer: dict) -> tuple[bool | None, int]:
        qtype = question["question_type"]
        points = question["points"]
        options = question["options"]
        correct_answer = question["correct_answer"]

        if qtype in ("single_choice", "image"):
            selected = answer.get("selected_option_id")
            if not selected:
                return None, 0
            for opt in options:
                if opt["id"] == selected and opt["is_correct"]:
                    return True, points
            return False, 0

        if qtype == "short_answer":
            user_text = (answer.get("text_answer") or "").strip().lower()
            correct_text = (correct_answer or "").strip().lower()
            if not user_text:
                return None, 0
            return (True, points) if user_text == correct_text else (False, 0)

        return None, 0

    # ── Manual Grade (Essay) ─────────────────────────────────────────

    async def manual_grade(
        self,
        attempt_id: uuid.UUID,
        question_id: uuid.UUID,
        grader_user_id: uuid.UUID,
        points_earned: int,
        feedback: str | None = None,
    ) -> dict:
        attempt = await self.repo.get_attempt_by_id(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if not attempt.is_completed:
            from fastapi import HTTPException
            raise HTTPException(400, "Cannot grade an incomplete attempt")

        exam = await self.repo.get_exam_by_id(attempt.exam_id)
        if not exam:
            raise ExamNotActive()
        if exam.owner_id != grader_user_id:
            raise NotExamOwner()

        answers = await self.repo.get_answers_for_attempt(attempt_id)
        target = next((a for a in answers if a.question_id == question_id), None)
        if not target:
            raise InvalidAnswerData("Answer not found for this question")

        if points_earned < 0:
            raise InvalidAnswerData("points_earned cannot be negative")

        from app.modules.questions.models import Question

        q_result = await self.db.execute(
            select(Question.score).where(Question.id == question_id)
        )
        max_points = q_result.scalar_one_or_none()
        if max_points is not None and points_earned > max_points:
            raise InvalidAnswerData(
                f"points_earned cannot exceed the question's max score ({max_points})"
            )

        diff = points_earned - (target.points_earned or 0)
        target.is_correct = points_earned > 0
        target.points_earned = points_earned

        attempt.score = (attempt.score or 0) + diff
        await self.db.flush()

        r = await self.db.execute(select(Result).where(Result.attempt_id == attempt_id))
        result_record = r.scalar_one_or_none()
        if not result_record:
            result_record = Result(attempt_id=attempt_id)
            self.db.add(result_record)
            await self.db.flush()

        total_points = result_record.max_score or 1
        passing_score = await self._get_exam_passing_score(attempt.exam_id)
        result_record.total_score = attempt.score or 0
        result_record.percentage = round((result_record.total_score / total_points * 100), 2)
        result_record.grade = self._compute_grade(result_record.percentage)
        result_record.passed = result_record.percentage >= passing_score
        result_record.graded_by = str(grader_user_id)
        result_record.graded_at = self._now()
        await self.db.flush()

        from app.modules.notifications.events import notify_result_ready

        await notify_result_ready(
            self.db,
            user_id=attempt.user_id,
            test_title=exam.title,
            score=result_record.percentage,
        )

        if result_record.passed:
            from app.modules.exams.certificate_service import CertificateService

            full_attempt = await self.repo.get_attempt_with_relations(attempt_id)
            if full_attempt:
                await CertificateService(self.db).issue_for_attempt(full_attempt)

        return {
            "success": True,
            "message": "Question graded manually",
            "points_earned": points_earned,
            "feedback": feedback,
        }

    # ── Result ───────────────────────────────────────────────────────

    async def get_result(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        attempt = await self.repo.get_attempt_by_id(attempt_id)
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != user_id:
            raise NotAttemptOwner()
        if not attempt.is_completed:
            from fastapi import HTTPException
            raise HTTPException(400, "Attempt not yet completed")

        passing_score = await self._get_exam_passing_score(attempt.exam_id)

        r = await self.db.execute(select(Result).where(Result.attempt_id == attempt_id))
        result_record = r.scalar_one_or_none()

        time_spent = self._compute_time_spent(attempt.started_at, attempt.completed_at)
        total_points = attempt.total_points or 1

        if result_record:
            return {
                "attempt_id": attempt_id,
                "total_score": result_record.total_score,
                "max_score": result_record.max_score,
                "percentage": result_record.percentage,
                "grade": result_record.grade,
                "correct_count": result_record.correct_count,
                "wrong_count": result_record.wrong_count,
                "unanswered_count": result_record.unanswered_count,
                "time_spent_seconds": result_record.time_spent_seconds,
                "passed": result_record.passed,
                "graded_by": result_record.graded_by,
                "graded_at": result_record.graded_at,
            }

        total_score = attempt.score or 0
        percentage = round((total_score / total_points * 100), 2)
        passed = percentage >= passing_score
        grade = self._compute_grade(percentage)

        return {
            "attempt_id": attempt_id,
            "total_score": total_score,
            "max_score": total_points,
            "percentage": percentage,
            "grade": grade,
            "correct_count": 0,
            "wrong_count": 0,
            "unanswered_count": 0,
            "time_spent_seconds": time_spent,
            "passed": passed,
            "graded_by": "auto",
            "graded_at": attempt.completed_at,
        }

    # ── Review ───────────────────────────────────────────────────────

    async def review_attempt(self, attempt_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        return await self._review.review_attempt(attempt_id, user_id)

    # ── Leaderboard ──────────────────────────────────────────────────

    async def get_leaderboard(self, exam_id: uuid.UUID, limit: int = 50) -> dict:
        return await self._leaderboard.get_leaderboard(exam_id, limit)

    # ── Stats ─────────────────────────────────────────────────────────

    async def get_exam_stats(self, exam_id: uuid.UUID) -> dict:
        return await self._stats.get_exam_stats(exam_id)

    # ── List Attempts ─────────────────────────────────────────────────

    async def list_user_attempts(
        self, user_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        data = await self.repo.get_attempts_for_user(user_id, page, per_page)
        items = []
        exam_passing_scores: dict[uuid.UUID, int] = {}
        for a in data["items"]:
            exam_title = a.exam.title if a.exam else ""
            total_points = a.total_points or 1
            score = a.score or 0
            percentage = (
                round((score / total_points * 100), 2) if a.is_completed else None
            )
            time_spent = self._compute_time_spent(a.started_at, a.completed_at)
            passed = None
            grade = None
            if a.is_completed:
                if a.exam_id not in exam_passing_scores:
                    exam_passing_scores[a.exam_id] = await self._get_exam_passing_score(a.exam_id)
                passing = exam_passing_scores[a.exam_id]
                passed = (percentage or 0) >= passing
                grade = self._compute_grade(percentage or 0)

            items.append({
                "id": a.id,
                "exam_id": a.exam_id,
                "exam_title": exam_title,
                "status": self._get_status(a),
                "score": a.score,
                "total_points": a.total_points,
                "percentage": percentage,
                "grade": grade,
                "passed": passed,
                "started_at": a.started_at,
                "completed_at": a.completed_at,
                "time_spent_seconds": time_spent,
            })

        return {**data, "items": items}

    async def list_exam_attempts(
        self, exam_id: uuid.UUID, page: int = 1, per_page: int = 20,
        owner_id: uuid.UUID | None = None,
    ) -> dict:
        if owner_id:
            exam = await self.repo.get_exam_by_id(exam_id)
            if not exam or exam.owner_id != owner_id:
                raise NotExamOwner()

        passing_score = await self._get_exam_passing_score(exam_id)
        data = await self.repo.get_attempts_for_exam(exam_id, page, per_page)

        user_ids = [a.user_id for a in data["items"]]
        users_result = await self.db.execute(
            select(User).where(User.id.in_(user_ids)) if user_ids else select(User).where(False)
        )
        users_map = {u.id: u for u in users_result.scalars().all()}

        items = []
        for a in data["items"]:
            user = users_map.get(a.user_id)
            total_points = a.total_points or 1
            score = a.score or 0
            percentage = (
                round((score / total_points * 100), 2) if a.is_completed else None
            )
            passed = None
            grade = None
            if a.is_completed:
                passed = (percentage or 0) >= passing_score
                grade = self._compute_grade(percentage or 0)

            items.append({
                "id": a.id,
                "exam_id": a.exam_id,
                "user_id": a.user_id,
                "username": user.username if user else None,
                "status": self._get_status(a),
                "score": a.score,
                "total_points": a.total_points,
                "percentage": percentage,
                "grade": grade,
                "passed": passed,
                "started_at": a.started_at,
                "completed_at": a.completed_at,
                "time_spent_seconds": self._compute_time_spent(
                    a.started_at, a.completed_at
                ),
            })

        return {**data, "items": items}
