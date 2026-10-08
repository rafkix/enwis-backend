"""Constants for the questions module."""

QUESTION_TYPE_CHOICES = (
    "single_choice",
    "short_answer",
    "image",
)

DIFFICULTY_LEVELS = ("easy", "medium", "hard")

VISIBILITY_CHOICES = ("private", "public", "organization")

STATUS_CHOICES = ("draft", "published", "archived")

ATTACHMENT_TYPES = ("image", "audio", "video", "pdf", "other")

MAX_BULK_QUESTIONS = 500
MAX_IMPORT_FILE_SIZE_MB = 10
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100