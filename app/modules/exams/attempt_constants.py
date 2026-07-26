

ATTEMPT_STATUS_IN_PROGRESS = "in_progress"
ATTEMPT_STATUS_SUBMITTED = "submitted"

GRADE_A = "A"
GRADE_B = "B"
GRADE_C = "C"
GRADE_D = "D"
GRADE_F = "F"

GRADE_THRESHOLDS: dict[str, float] = {
    GRADE_A: 90.0,
    GRADE_B: 80.0,
    GRADE_C: 70.0,
    GRADE_D: 60.0,
}

AUTO_GRACE_SECONDS = 30
