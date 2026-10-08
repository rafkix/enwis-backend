"""API versioning package.

Each sub-package (`v1`, `v2`, ...) exposes a single aggregate
`APIRouter` for that URL-routing generation. `app/main.py` mounts the
currently-active generation(s) under their prefix (e.g. `/api/v1`).

Why this exists: previously every module router was included directly
in `app/main.py` under a hardcoded "/api/v1" string. That made it
impossible to introduce a `/api/v2` without either duplicating that
whole block or entangling v1 and v2 routing decisions in the same
place. Now each version is its own aggregator module, so `main.py`
only ever deals with "which version(s) are currently mounted", not
"which endpoints exist in that version".
"""
