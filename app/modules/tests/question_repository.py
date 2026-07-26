import math
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.questions.models import (
    Choice,
    Question,
    QuestionBank,
    QuestionCategory,
    QuestionStatus,
    QuestionTag,
    QuestionTypeMeta,
    Visibility,
)


class QuestionCategoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, name: str, parent_id: uuid.UUID | None = None) -> QuestionCategory:
        cat = QuestionCategory(name=name, parent_id=parent_id)
        self.db.add(cat)
        await self.db.flush()
        await self.db.refresh(cat)
        return cat

    async def get_tree(self) -> list[QuestionCategory]:
        result = await self.db.execute(
            select(QuestionCategory).options(selectinload(QuestionCategory.children))
            .where(QuestionCategory.parent_id.is_(None))
            .order_by(QuestionCategory.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, cat_id: uuid.UUID) -> QuestionCategory | None:
        result = await self.db.execute(
            select(QuestionCategory).where(QuestionCategory.id == cat_id)
        )
        return result.scalar_one_or_none()

    async def update(self, cat_id: uuid.UUID, name: str | None = None,
                     parent_id: uuid.UUID | None = ...) -> QuestionCategory:
        cat = await self.get_by_id(cat_id)
        if not cat:
            raise ValueError("Category not found")
        if name is not None:
            cat.name = name
        if parent_id is not ...:
            cat.parent_id = parent_id
        await self.db.flush()
        await self.db.refresh(cat)
        return cat

    async def delete(self, cat_id: uuid.UUID) -> None:
        cat = await self.get_by_id(cat_id)
        if cat:
            await self.db.delete(cat)
            await self.db.flush()


class QuestionTagRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, name: str) -> QuestionTag:
        result = await self.db.execute(
            select(QuestionTag).where(QuestionTag.name == name)
        )
        tag = result.scalar_one_or_none()
        if tag:
            return tag
        tag = QuestionTag(name=name)
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag)
        return tag

    async def list_all(self) -> list[QuestionTag]:
        result = await self.db.execute(
            select(QuestionTag).order_by(QuestionTag.name)
        )
        return list(result.scalars().all())


class QuestionBankRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, name: str, owner_id: uuid.UUID,
                     description: str | None = None,
                     visibility: str = "private") -> QuestionBank:
        bank = QuestionBank(
            name=name, description=description,
            owner_id=owner_id, visibility=visibility,
        )
        self.db.add(bank)
        await self.db.flush()
        await self.db.refresh(bank)
        return bank

    async def list_by_owner(self, owner_id: uuid.UUID, page: int = 1,
                            per_page: int = 20) -> dict:
        q = select(QuestionBank).where(
            (QuestionBank.owner_id == owner_id) |
            (QuestionBank.visibility == Visibility.PUBLIC)
        )
        count_q = select(func.count(QuestionBank.id)).where(
            (QuestionBank.owner_id == owner_id) |
            (QuestionBank.visibility == Visibility.PUBLIC)
        )
        total = (await self.db.execute(count_q)).scalar_one()

        result = await self.db.execute(
            q.order_by(QuestionBank.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page)
        )
        banks = list(result.scalars().all())

        items = []
        for bank in banks:
            qc = await self.db.execute(
                select(func.count(Question.id)).where(Question.question_bank_id == bank.id)
            )
            items.append({
                "id": bank.id,
                "name": bank.name,
                "description": bank.description,
                "owner_id": bank.owner_id,
                "visibility": (
                    bank.visibility.value
                    if hasattr(bank.visibility, "value")
                    else bank.visibility
                ),
                "questions_count": qc.scalar_one(),
                "created_at": bank.created_at,
                "updated_at": bank.updated_at,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    async def get_by_id(self, bank_id: uuid.UUID) -> QuestionBank | None:
        result = await self.db.execute(
            select(QuestionBank).where(QuestionBank.id == bank_id)
        )
        return result.scalar_one_or_none()

    async def update(self, bank_id: uuid.UUID, data: dict) -> QuestionBank:
        bank = await self.get_by_id(bank_id)
        if not bank:
            raise ValueError("Question bank not found")
        for key, value in data.items():
            if value is not None and hasattr(bank, key):
                setattr(bank, key, value)
        await self.db.flush()
        await self.db.refresh(bank)
        return bank

    async def delete(self, bank_id: uuid.UUID) -> None:
        bank = await self.get_by_id(bank_id)
        if bank:
            await self.db.delete(bank)
            await self.db.flush()


class QuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count_by_bank(self, bank_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Question.id)).where(Question.question_bank_id == bank_id)
        )
        return result.scalar_one()

    async def create(self, data: dict, owner_id: uuid.UUID) -> Question:
        tag_ids = data.pop("tag_ids", [])
        choices_data = data.pop("choices", [])

        question = Question(owner_id=owner_id, **data)
        self.db.add(question)
        await self.db.flush()

        if tag_ids:
            result = await self.db.execute(
                select(QuestionTag).where(QuestionTag.id.in_(tag_ids))
            )
            question.tags = list(result.scalars().all())

        for c in choices_data:
            choice = Choice(
                question_id=question.id,
                content=c["content"],
                is_correct=c.get("is_correct", False),
                order=c.get("order", 0),
            )
            self.db.add(choice)

        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        result = await self.db.execute(
            select(Question)
            .options(
                selectinload(Question.choices),
                selectinload(Question.tags),
                selectinload(Question.attachments),
                selectinload(Question.category),
            )
            .where(Question.id == question_id)
        )
        return result.scalar_one_or_none()

    async def update(self, question_id: uuid.UUID, data: dict) -> Question:
        question = await self.get_by_id(question_id)
        if not question:
            raise ValueError("Question not found")

        tag_ids = data.pop("tag_ids", None)
        choices_data = data.pop("choices", None)

        for key, value in data.items():
            if value is not None and hasattr(question, key):
                setattr(question, key, value)

        if tag_ids is not None:
            result = await self.db.execute(
                select(QuestionTag).where(QuestionTag.id.in_(tag_ids))
            )
            question.tags = list(result.scalars().all())

        if choices_data is not None:
            await self.db.execute(
                delete(Choice).where(Choice.question_id == question_id)
            )
            for c in choices_data:
                choice = Choice(
                    question_id=question_id,
                    content=c["content"],
                    is_correct=c.get("is_correct", False),
                    order=c.get("order", 0),
                )
                self.db.add(choice)

        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def delete(self, question_id: uuid.UUID) -> None:
        q = await self.get_by_id(question_id)
        if q:
            await self.db.delete(q)
            await self.db.flush()

    async def duplicate(self, question_id: uuid.UUID, owner_id: uuid.UUID) -> Question:
        original = await self.get_by_id(question_id)
        if not original:
            raise ValueError("Question not found")

        data = {
            "title": f"{original.title} (Copy)",
            "description": original.description,
            "question_type": original.question_type,
            "difficulty": original.difficulty,
            "score": original.score,
            "explanation": original.explanation,
            "visibility": original.visibility,
            "category_id": original.category_id,
            "question_bank_id": original.question_bank_id,
        }
        question = Question(owner_id=owner_id, status=QuestionStatus.DRAFT, **data)
        self.db.add(question)
        await self.db.flush()

        if original.tags:
            question.tags = original.tags

        for ch in original.choices:
            choice = Choice(
                question_id=question.id,
                content=ch.content,
                is_correct=ch.is_correct,
                order=ch.order,
            )
            self.db.add(choice)

        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def set_status(self, question_id: uuid.UUID, status: QuestionStatus) -> Question:
        await self.db.execute(
            update(Question).where(Question.id == question_id).values(status=status)
        )
        await self.db.flush()
        result = await self.db.execute(
            select(Question).where(Question.id == question_id)
        )
        return result.scalar_one()

    async def search(self, filters: dict, page: int = 1, per_page: int = 20) -> dict:
        q = select(Question)
        count_q = select(func.count(Question.id))

        conditions = []
        for field, value in filters.items():
            if value is not None and hasattr(Question, field):
                col = getattr(Question, field)
                if field == "search":
                    continue
                conditions.append(col == value)

        search_text = filters.get("search")
        if search_text:
            pattern = f"%{search_text}%"
            conditions.append(Question.title.ilike(pattern))

        if conditions:
            q = q.where(*conditions)
            count_q = count_q.where(*conditions)

        total = (await self.db.execute(count_q)).scalar_one()

        result = await self.db.execute(
            q.order_by(Question.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page)
        )
        questions = list(result.scalars().all())

        return {
            "items": questions,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    async def bulk_create(self, questions_data: list[dict],
                          owner_id: uuid.UUID) -> list[Question]:
        created: list[Question] = []
        for data in questions_data:
            q = await self.create(data, owner_id)
            created.append(q)
        return created

    async def bulk_delete(self, question_ids: list[uuid.UUID]) -> int:
        result = await self.db.execute(
            delete(Question).where(Question.id.in_(question_ids))
        )
        await self.db.flush()
        return result.rowcount

    async def bulk_move(self, question_ids: list[uuid.UUID],
                        target_bank_id: uuid.UUID) -> int:
        result = await self.db.execute(
            update(Question)
            .where(Question.id.in_(question_ids))
            .values(question_bank_id=target_bank_id)
        )
        await self.db.flush()
        return result.rowcount

    async def bulk_copy(self, question_ids: list[uuid.UUID],
                        target_bank_id: uuid.UUID,
                        owner_id: uuid.UUID) -> list[Question]:
        copied: list[Question] = []
        for qid in question_ids:
            original = await self.get_by_id(qid)
            if original:
                dup = await self.duplicate(qid, owner_id)
                dup.question_bank_id = target_bank_id
                self.db.add(dup)
                copied.append(dup)
        await self.db.flush()
        return copied


class QuestionTypeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self, active_only: bool = False) -> list[QuestionTypeMeta]:
        q = select(QuestionTypeMeta).order_by(QuestionTypeMeta.sort_order)
        if active_only:
            q = q.where(QuestionTypeMeta.is_active.is_(True))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_paginated(
        self, page: int = 1, per_page: int = 20, active_only: bool = False
    ) -> dict:
        q = select(QuestionTypeMeta)
        count_q = select(func.count(QuestionTypeMeta.id))
        if active_only:
            q = q.where(QuestionTypeMeta.is_active.is_(True))
            count_q = count_q.where(QuestionTypeMeta.is_active.is_(True))

        total = (await self.db.execute(count_q)).scalar_one() or 0
        result = await self.db.execute(
            q.order_by(QuestionTypeMeta.sort_order)
            .offset((page - 1) * per_page).limit(per_page)
        )
        return {
            "items": list(result.scalars().all()),
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total > 0 else 1,
        }

    async def get_by_id(self, type_id: uuid.UUID) -> QuestionTypeMeta | None:
        result = await self.db.execute(
            select(QuestionTypeMeta).where(QuestionTypeMeta.id == type_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> QuestionTypeMeta | None:
        result = await self.db.execute(
            select(QuestionTypeMeta).where(QuestionTypeMeta.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> QuestionTypeMeta:
        qt = QuestionTypeMeta(**data)
        self.db.add(qt)
        await self.db.flush()
        await self.db.refresh(qt)
        return qt

    async def update(self, type_id: uuid.UUID, data: dict) -> QuestionTypeMeta | None:
        qt = await self.get_by_id(type_id)
        if not qt:
            return None
        for key, value in data.items():
            if value is not None and hasattr(qt, key):
                setattr(qt, key, value)
        await self.db.flush()
        await self.db.refresh(qt)
        return qt

    async def delete(self, type_id: uuid.UUID) -> bool:
        qt = await self.get_by_id(type_id)
        if not qt:
            return False
        await self.db.delete(qt)
        await self.db.flush()
        return True
