"""Subscriptions & billing module constants."""

# Where uploaded payment-receipt screenshots are stored. Deliberately
# NOT under a publicly served static path — app/main.py's
# PublicStaticFiles blocks direct access to "payment-proofs/" so these
# can only ever be read back through the authenticated
# /billing/payments/{id}/receipt (owner) or /admin/payments/{id}/receipt
# (admin) endpoints.
RECEIPT_UPLOAD_DIR = "static/payment-proofs"
MAX_RECEIPT_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_RECEIPT_MIMES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

# How long a user has to upload a receipt after creating a PENDING
# payment before it is auto-expired by the background sweeper.
RECEIPT_UPLOAD_TIMEOUT_MINUTES = 60

# How long a WAITING_FOR_REVIEW payment can sit unreviewed before it is
# auto-expired by the background sweeper.
REVIEW_TIMEOUT_HOURS = 72
