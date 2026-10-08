from fastapi import HTTPException, status


class QuestionNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Question not found")


class QuestionBankNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Question bank not found")


class QuestionCategoryNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Question category not found")


class BulkOperationLimitException(HTTPException):
    def __init__(self, max_items: int) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            f"Bulk operations are limited to {max_items} items at a time",
        )


class ImportFeatureNotAvailable(HTTPException):
    def __init__(self, detail: str = "Import feature is not available on your plan") -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class ImportValidationError(HTTPException):
    def __init__(self, detail: str = "Invalid import data") -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


class NotQuestionOwnerException(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "You do not have permission to modify this question",
        )


class NotBankOwnerException(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "You do not have permission to modify this question bank",
        )


class QuestionReferencedByPublishedExams(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "This question is used by one or more published/active exams "
            "and cannot be deleted",
        )
