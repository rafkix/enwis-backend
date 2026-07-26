import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import (
    PlanTier,
    can_use_csv_import,
    can_use_excel_import,
    get_user_plan_tier,
)
from app.modules.auth.models import User
from app.modules.questions.constants import MAX_BULK_QUESTIONS
from app.modules.questions.exceptions import (
    BulkOperationLimitException,
    ImportFeatureNotAvailable,
    ImportValidationError,
    NotBankOwnerException,
    NotQuestionOwnerException,
    QuestionBankNotFoundException,
    QuestionCategoryNotFoundException,
    QuestionNotFoundException,
    QuestionReferencedByPublishedExams,
)
from app.modules.questions.models import (
    Question,
    QuestionBank,
    QuestionCategory,
    QuestionStatus,
    QuestionTag,
    Visibility,
)
from app.modules.tests.question_repository import (
    QuestionBankRepository,
    QuestionCategoryRepository,
    QuestionRepository,
    QuestionTagRepository,
    QuestionTypeRepository,
)


class QuestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.category_repo = QuestionCategoryRepository(db)
        self.tag_repo = QuestionTagRepository(db)
        self.bank_repo = QuestionBankRepository(db)
        self.question_repo = QuestionRepository(db)
        self.type_repo = QuestionTypeRepository(db)

    def _now(self) -> datetime:
        from datetime import UTC
        return datetime.now(UTC)

    async def _get_user_tier(self, owner_id: uuid.UUID) -> PlanTier:
        result = await self.db.execute(
            select(User.subscription_tier).where(User.id == owner_id)
        )
        tier_str = result.scalar_one_or_none()
        return get_user_plan_tier(tier_str)

    @staticmethod
    def _assert_question_owner(
        question: Question, requester_id: uuid.UUID, is_admin: bool = False
    ) -> None:
        if is_admin:
            return
        if question.owner_id != requester_id:
            raise NotQuestionOwnerException()

    @staticmethod
    def _assert_can_view_question(
        question: Question, requester_id: uuid.UUID, is_admin: bool = False
    ) -> None:
        if is_admin or question.owner_id == requester_id:
            return
        visibility = (
            question.visibility.value
            if hasattr(question.visibility, "value")
            else question.visibility
        )
        if visibility in (Visibility.PUBLIC.value, Visibility.ORGANIZATION.value):
            return
        raise NotQuestionOwnerException()

    @staticmethod
    def _assert_bank_owner(
        bank: QuestionBank, requester_id: uuid.UUID, is_admin: bool = False
    ) -> None:
        if is_admin:
            return
        if bank.owner_id != requester_id:
            raise NotBankOwnerException()

    # ── Categories ─────────────────────────────────────────────────

    async def create_category(
        self, name: str, parent_id: uuid.UUID | None = None,
    ) -> QuestionCategory:
        return await self.category_repo.create(name, parent_id)

    async def get_category_tree(self) -> list[QuestionCategory]:
        return await self.category_repo.get_tree()

    async def update_category(self, cat_id: uuid.UUID, name: str | None = None,
                              parent_id: uuid.UUID | None = ...) -> QuestionCategory:
        cat = await self.category_repo.get_by_id(cat_id)
        if not cat:
            raise QuestionCategoryNotFoundException()
        return await self.category_repo.update(cat_id, name, parent_id)

    async def delete_category(self, cat_id: uuid.UUID) -> None:
        cat = await self.category_repo.get_by_id(cat_id)
        if not cat:
            raise QuestionCategoryNotFoundException()
        await self.category_repo.delete(cat_id)

    # ── Tags ───────────────────────────────────────────────────────

    async def list_tags(self) -> list[QuestionTag]:
        return await self.tag_repo.list_all()

    # ── Question Banks ─────────────────────────────────────────────

    async def create_bank(self, name: str, owner_id: uuid.UUID,
                          description: str | None = None,
                          visibility: str = "private") -> QuestionBank:
        return await self.bank_repo.create(name, owner_id, description, visibility)

    async def list_banks(self, owner_id: uuid.UUID, page: int = 1, per_page: int = 20) -> dict:
        return await self.bank_repo.list_by_owner(owner_id, page, per_page)

    async def get_bank(
        self, bank_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> QuestionBank:
        bank = await self.bank_repo.get_by_id(bank_id)
        if not bank:
            raise QuestionBankNotFoundException()
        if not is_admin and bank.owner_id != requester_id and bank.visibility == "private":
            raise NotBankOwnerException()
        return bank

    async def update_bank(
        self, bank_id: uuid.UUID, data: dict,
        requester_id: uuid.UUID, is_admin: bool = False,
    ) -> QuestionBank:
        bank = await self.bank_repo.get_by_id(bank_id)
        if not bank:
            raise QuestionBankNotFoundException()
        self._assert_bank_owner(bank, requester_id, is_admin)
        return await self.bank_repo.update(bank_id, data)

    async def delete_bank(
        self, bank_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> None:
        bank = await self.bank_repo.get_by_id(bank_id)
        if not bank:
            raise QuestionBankNotFoundException()
        self._assert_bank_owner(bank, requester_id, is_admin)
        await self.bank_repo.delete(bank_id)

    # ── Questions ──────────────────────────────────────────────────

    async def create_question(self, data: dict, owner_id: uuid.UUID) -> Question:
        return await self.question_repo.create(data, owner_id)

    async def get_question(
        self, question_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> Question:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_can_view_question(q, requester_id, is_admin)
        return q

    async def update_question(
        self, question_id: uuid.UUID, data: dict,
        requester_id: uuid.UUID, is_admin: bool = False,
    ) -> Question:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_question_owner(q, requester_id, is_admin)
        return await self.question_repo.update(question_id, data)

    async def delete_question(
        self, question_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> None:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_question_owner(q, requester_id, is_admin)

        from app.modules.tests.models import Test, TestQuestion

        pub_refs = await self.db.execute(
            select(TestQuestion)
            .join(Test, TestQuestion.test_id == Test.id)
            .where(TestQuestion.question_id == question_id,
                   Test.status == "active")
        )
        if pub_refs.scalar_one_or_none():
            raise QuestionReferencedByPublishedExams()

        await self.question_repo.delete(question_id)

    async def duplicate_question(
        self, question_id: uuid.UUID, owner_id: uuid.UUID, is_admin: bool = False
    ) -> Question:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_can_view_question(q, owner_id, is_admin)
        return await self.question_repo.duplicate(question_id, owner_id)

    async def archive_question(
        self, question_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> Question:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_question_owner(q, requester_id, is_admin)
        return await self.question_repo.set_status(question_id, QuestionStatus.ARCHIVED)

    async def restore_question(
        self, question_id: uuid.UUID, requester_id: uuid.UUID, is_admin: bool = False
    ) -> Question:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()
        self._assert_question_owner(q, requester_id, is_admin)
        return await self.question_repo.set_status(question_id, QuestionStatus.DRAFT)

    async def search_questions(self, filters: dict, page: int = 1,
                               per_page: int = 20,
                               requester_id: uuid.UUID | None = None,
                               is_admin: bool = False) -> dict:
        if not is_admin and requester_id is not None:
            requested_owner = filters.get("owner_id")
            if requested_owner is not None and requested_owner != requester_id:
                raise NotQuestionOwnerException()
            filters["owner_id"] = requester_id
        return await self.question_repo.search(filters, page, per_page)

    # ── Bulk ───────────────────────────────────────────────────────

    async def bulk_create_questions(self, questions_data: list[dict],
                                    owner_id: uuid.UUID) -> list[Question]:
        if len(questions_data) > MAX_BULK_QUESTIONS:
            raise BulkOperationLimitException(MAX_BULK_QUESTIONS)
        return await self.question_repo.bulk_create(questions_data, owner_id)

    async def _assert_bulk_owner(
        self, question_ids: list[uuid.UUID], requester_id: uuid.UUID, is_admin: bool
    ) -> None:
        if is_admin:
            return
        for qid in question_ids:
            q = await self.question_repo.get_by_id(qid)
            if q and q.owner_id != requester_id:
                raise NotQuestionOwnerException()

    async def bulk_delete_questions(
        self, question_ids: list[uuid.UUID],
        requester_id: uuid.UUID, is_admin: bool = False,
    ) -> int:
        await self._assert_bulk_owner(question_ids, requester_id, is_admin)
        return await self.question_repo.bulk_delete(question_ids)

    async def bulk_move_questions(self, question_ids: list[uuid.UUID],
                                  target_bank_id: uuid.UUID,
                                  requester_id: uuid.UUID, is_admin: bool = False) -> int:
        bank = await self.bank_repo.get_by_id(target_bank_id)
        if not bank:
            raise QuestionBankNotFoundException()
        self._assert_bank_owner(bank, requester_id, is_admin)
        await self._assert_bulk_owner(question_ids, requester_id, is_admin)
        return await self.question_repo.bulk_move(question_ids, target_bank_id)

    async def bulk_copy_questions(self, question_ids: list[uuid.UUID],
                                  target_bank_id: uuid.UUID,
                                  owner_id: uuid.UUID, is_admin: bool = False) -> list[Question]:
        bank = await self.bank_repo.get_by_id(target_bank_id)
        if not bank:
            raise QuestionBankNotFoundException()
        self._assert_bank_owner(bank, owner_id, is_admin)
        return await self.question_repo.bulk_copy(question_ids, target_bank_id, owner_id)

    # ── Import / Export ────────────────────────────────────────────

    async def export_json(self, question_ids: list[uuid.UUID] | None = None) -> str:
        if question_ids:
            questions: list[Question] = []
            for qid in question_ids:
                q = await self.question_repo.get_by_id(qid)
                if q:
                    questions.append(q)
        else:
            result = await self.db.execute(select(Question))
            questions = list(result.scalars().all())

        data = []
        for q in questions:
            qt = (
                q.question_type.value
                if hasattr(q.question_type, "value")
                else q.question_type
            )
            diff = (
                q.difficulty.value
                if hasattr(q.difficulty, "value")
                else q.difficulty
            )
            vis = (
                q.visibility.value
                if hasattr(q.visibility, "value")
                else q.visibility
            )
            data.append({
                "title": q.title,
                "description": q.description,
                "question_type": qt,
                "difficulty": diff,
                "score": q.score,
                "explanation": q.explanation,
                "visibility": vis,
                "choices": [
                    {"content": c.content, "is_correct": c.is_correct, "order": c.order}
                    for c in q.choices
                ],
                "tags": [t.name for t in q.tags],
            })

        return json.dumps(data, ensure_ascii=False, indent=2)

    async def import_json(self, json_str: str, owner_id: uuid.UUID,
                          bank_id: uuid.UUID | None = None) -> list[Question]:
        if bank_id:
            bank = await self.bank_repo.get_by_id(bank_id)
            if not bank:
                raise QuestionBankNotFoundException()

        raw = json.loads(json_str)
        questions_data = []
        for item in raw:
            qd = {
                "title": item["title"],
                "description": item.get("description"),
                "question_type": item.get("question_type", "single_choice"),
                "difficulty": item.get("difficulty", "medium"),
                "score": item.get("score", 1),
                "explanation": item.get("explanation"),
                "visibility": item.get("visibility", "private"),
                "question_bank_id": bank_id,
                "choices": item.get("choices", []),
            }
            tag_names = item.get("tags", [])
            if tag_names:
                tag_ids = []
                for name in tag_names:
                    tag = await self.tag_repo.get_or_create(name)
                    tag_ids.append(tag.id)
                qd["tag_ids"] = tag_ids
            questions_data.append(qd)

        return await self.question_repo.bulk_create(questions_data, owner_id)

    async def import_excel(
        self,
        file_bytes: bytes,
        owner_id: uuid.UUID,
        bank_id: uuid.UUID | None = None,
    ) -> list[Question]:
        tier = await self._get_user_tier(owner_id)
        if not can_use_excel_import(tier):
            raise ImportFeatureNotAvailable("Excel")

        from app.modules.questions.import_utils import parse_excel

        questions_data, errors = parse_excel(file_bytes)
        if errors and not questions_data:
            raise ImportValidationError(errors)

        if bank_id:
            bank = await self.bank_repo.get_by_id(bank_id)
            if not bank:
                raise QuestionBankNotFoundException()
            for q in questions_data:
                q["question_bank_id"] = bank_id

        return await self.bulk_create_questions(questions_data, owner_id)

    async def import_csv(
        self,
        file_bytes: bytes,
        owner_id: uuid.UUID,
        bank_id: uuid.UUID | None = None,
    ) -> list[Question]:
        tier = await self._get_user_tier(owner_id)
        if not can_use_csv_import(tier):
            raise ImportFeatureNotAvailable("CSV")

        from app.modules.questions.import_utils import parse_csv

        questions_data, errors = parse_csv(file_bytes)
        if errors and not questions_data:
            raise ImportValidationError(errors)

        if bank_id:
            bank = await self.bank_repo.get_by_id(bank_id)
            if not bank:
                raise QuestionBankNotFoundException()
            for q in questions_data:
                q["question_bank_id"] = bank_id

        return await self.bulk_create_questions(questions_data, owner_id)

    async def get_statistics(self, question_id: uuid.UUID) -> dict:
        q = await self.question_repo.get_by_id(question_id)
        if not q:
            raise QuestionNotFoundException()

        from app.modules.tests.models import Test, TestQuestion

        exam_count_result = await self.db.execute(
            select(TestQuestion)
            .join(Test, TestQuestion.test_id == Test.id)
            .where(TestQuestion.question_id == question_id,
                   Test.status == "active")
        )
        used_in_exams = len(list(exam_count_result.scalars().all()))

        return {
            "total_attempts": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "accuracy": 0.0,
            "avg_time_seconds": None,
            "used_in_exams": used_in_exams,
        }

    # ── Question Type Metadata ────────────────────────────────────

    async def list_question_types(self, active_only: bool = False) -> list:
        return await self.type_repo.list_all(active_only)

    async def list_question_types_paginated(
        self, page: int = 1, per_page: int = 20, active_only: bool = False
    ) -> dict:
        return await self.type_repo.list_paginated(page, per_page, active_only)

    async def get_question_type(self, type_id: uuid.UUID) -> object:
        qt = await self.type_repo.get_by_id(type_id)
        if not qt:
            from app.modules.questions.exceptions import QuestionNotFoundException
            raise QuestionNotFoundException()
        return qt

    async def create_question_type(self, data: dict) -> object:
        existing = await self.type_repo.get_by_name(data["name"])
        if existing:
            from fastapi import HTTPException
            raise HTTPException(409, "Question type with this name already exists")
        return await self.type_repo.create(data)

    async def update_question_type(self, type_id: uuid.UUID, data: dict) -> object:
        qt = await self.type_repo.update(type_id, data)
        if not qt:
            from app.modules.questions.exceptions import QuestionNotFoundException
            raise QuestionNotFoundException()
        return qt

    async def delete_question_type(self, type_id: uuid.UUID) -> None:
        deleted = await self.type_repo.delete(type_id)
        if not deleted:
            from app.modules.questions.exceptions import QuestionNotFoundException
            raise QuestionNotFoundException()

    async def seed_question_types(self) -> None:
        defaults = [
            {"name": "single_choice", "display_name": "Single Choice",
             "has_options": True, "has_correct_answer": True,
             "max_options": 6, "min_options": 2, "sort_order": 1},
            {"name": "short_answer", "display_name": "Short Answer",
             "has_options": False, "has_correct_answer": True,
             "max_options": 0, "min_options": 0, "sort_order": 2},
            {"name": "image", "display_name": "Image-Based",
             "has_options": True, "has_correct_answer": True,
             "has_image": True, "max_options": 6, "min_options": 2,
             "sort_order": 3},
        ]
        for d in defaults:
            existing = await self.type_repo.get_by_name(d["name"])
            if not existing:
                await self.type_repo.create(d)
