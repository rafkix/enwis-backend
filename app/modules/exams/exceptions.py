from fastapi import HTTPException, status


class ExamNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Exam not found")


class ExamNotEditableException(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "Exam is published and cannot be modified.",
        )


class ExamParticipantNotFoundException(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_404_NOT_FOUND, "Participant not found"
        )


class ExamLimitExceededException(HTTPException):
    def __init__(self, limit: int, tier: str) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            f"Your {tier} plan allows a maximum of {limit} exams. "
            f"Please upgrade your plan.",
        )


class ParticipantLimitExceededException(HTTPException):
    def __init__(self, limit: int, tier: str) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            f"Your {tier} plan allows a maximum of {limit} participants "
            f"per exam. Please upgrade your plan.",
        )
