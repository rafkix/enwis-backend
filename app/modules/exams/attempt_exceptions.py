from fastapi import HTTPException, status


class AttemptNotFound(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Attempt not found")


class ExamNotActive(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, "Exam is not active")


class MaxAttemptsReached(HTTPException):
    def __init__(self, max_attempts: int) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            f"Maximum attempts ({max_attempts}) reached",
        )


class DuplicateActiveAttempt(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "You already have an active attempt for this exam",
        )


class AttemptAlreadyCompleted(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, "Attempt already completed")


class ExamTimeExpired(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, "Exam time has expired")


class InvalidAnswerData(HTTPException):
    def __init__(self, detail: str = "Invalid answer data") -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


class EssayNotAutoGraded(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "Essay questions require manual grading",
        )


class NotAttemptOwner(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, "You do not own this attempt")


class NotExamOwner(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, "You do not own this exam")
