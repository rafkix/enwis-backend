"""Tests module constants."""

COVER_UPLOAD_DIR = "static/test_covers"
MAX_COVER_SIZE = 5 * 1024 * 1024  # 5MB — covers can reasonably be a bit
# bigger than an avatar since they're wide banner-style images, not a
# small square thumbnail.
ALLOWED_COVER_MIMES = {"image/jpeg", "image/png", "image/webp"}