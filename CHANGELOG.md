# CHANGELOG

All notable changes to the Enwis backend are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/)
(`MAJOR.MINOR.PATCH`) starting from this entry. `Settings.APP_VERSION`
in `app/core/config.py` and `FastAPI(version=...)` in `app/main.py`
track this number; bump both together with every release.

---

## [1.1.0] - 2026-07-29

Production refactor: removed the IELTS/CEFR user-profile fields,
rewrote billing as a manual card-transfer + admin-review flow with a
provider abstraction for future payment gateways, added a full admin
panel, and introduced `/api/v1` / `/api/v2`-ready URL versioning.

### Removed

- **IELTS/CEFR user-profile fields.** `CEFRLevel`, `IELTSGoal`,
  `CEFRGoal`, `IELTSMeta`, `CEFRMeta` and the `UserMeta.ielts` /
  `UserMeta.cefr` fields (`app/modules/users/schemas.py`). This was the
  only place IELTS/CEFR existed in the codebase — no models, routers,
  services, or migrations referenced it elsewhere. `main.py`'s API
  description text updated accordingly. Existing user rows with
  `meta.ielts` / `meta.cefr` JSON keys are unaffected (Pydantic ignores
  unknown keys by default) but those keys are no longer read or written
  going forward.
- **`PaymentLog` model / `payment_logs` table** — superseded by
  `Payment` + `PaymentEvent` (see below). The old table is left in
  place on existing databases (no destructive auto-migration); it can
  be dropped manually once you've confirmed nothing else reads it.
- **Unauthenticated plan-mutation endpoints** on `/subscriptions/*`
  (`create_plan` / `update_plan` / `delete_plan` / `seed` used to be
  reachable by *any* logged-in user — a real security bug). Moved to
  `/admin/plans/*`, gated by the `ADMIN` role.

### Added

- **Billing rewrite** (`app/modules/subscriptions/`):
  - `PaymentStatus`: `PENDING`, `WAITING_FOR_REVIEW`, `APPROVED`,
    `REJECTED`, `EXPIRED`, `CANCELLED`.
  - `Payment` model — plan price/currency snapshotted at creation time
    (so a later price change can't retroactively alter an in-flight or
    historical payment), receipt image path, reviewer, rejection
    reason, review deadline.
  - `PaymentEvent` model — an immutable transaction-history row written
    on every status transition, independent of the mutable `Payment`
    row (full audit trail for "transaction history").
  - `PaymentCard` model — admin-managed receiving cards shown to users
    at checkout.
  - Flow: `POST /billing/payments` (select plan, get card to pay to) ->
    `POST /billing/payments/{id}/receipt` (upload screenshot, JPEG/PNG/
    WebP/PDF, 5&nbsp;MB max) -> `POST /admin/payments/{id}/approve` or
    `/reject` -> subscription is activated/renewed automatically on
    approval, user notified either way.
  - `GET /billing/payments`, `/billing/payments/{id}` — a user's own
    transaction history. `POST /billing/payments/{id}/cancel` to back
    out before review.
  - Background sweeper (`app/main.py`'s lifespan task, every 15 min)
    auto-expires payments that sit in `PENDING` >60 min without a
    receipt, or `WAITING_FOR_REVIEW` >72 h without an admin decision.
  - **Payment-provider abstraction** (`app/modules/subscriptions/providers/`)
    so a real gateway (Payme/Click/Uzcard) can be added later without
    touching `BillingService`, routers, or schemas: `BasePaymentProvider`
    interface, `ManualCardProvider` (today's only implementation),
    `PaymentMethod` enum reserving `payme` / `click` / `uzcard`, a
    provider registry, and `POST /billing/webhooks/{provider}` as the
    single landing point for future gateway callbacks (currently
    returns `501` for unregistered providers). See the docstring in
    `providers/__init__.py` for the exact steps to plug in a new one.
- **Admin panel** (`app/modules/admin/`, all endpoints under `/admin`,
  `ADMIN` role required):
  - `GET /admin/dashboard` — user/payment/subscription/content stats.
  - `GET/PATCH/DELETE /admin/users*` — search & paginate, change
    status (pending/active/blocked), change roles, soft-delete.
  - `GET/POST /admin/payments*`, `/approve`, `/reject`, `/receipt` —
    payment moderation and receipt-image viewing.
  - `GET/POST/PUT/DELETE /admin/plans*`, `/admin/plans/seed` — plan
    management (moved here from the public subscriptions router).
  - `GET/POST/PUT/DELETE /admin/cards*` — manage which receiving
    card(s) are shown to users, edit numbers/holder/bank/active state.
  - `GET /admin/logs` — `AdminAuditLog`: every admin mutation
    (status/role changes, payment decisions, plan/card CRUD) is written
    to an immutable audit table alongside the mutation itself, inside
    the same DB transaction.
- **API versioning architecture** (`app/api/`):
  - `app/api/v1/__init__.py` aggregates every module router into one
    `v1_router`; `app/main.py` mounts it under `settings.API_PREFIX`
    (`/api/v1`) instead of looping over a hardcoded router list.
  - `app/api/v2/__init__.py` is a working placeholder (mounted at
    `/api/v2`, responds, documented) showing exactly how to build a
    real v2 later by reusing unchanged v1 routers and swapping out only
    the ones that changed — see its module docstring.
  - `Settings.APP_VERSION` (SemVer, this file) added alongside the
    existing `Settings.API_VERSION` / `API_PREFIX` (URL-routing
    generation) — they're independent and both now flow into
    `FastAPI(version=...)`, `/`, and the docs endpoints instead of
    being hardcoded in three places.
- Test coverage: `tests/test_billing_admin.py` (8 tests covering the
  free-vs-paid-plan split, the full approve/reject lifecycle, provider
  extensibility, and dashboard stats).

### Fixed

- `SubscriptionRepository.get_active_by_user` crashed with
  `TypeError: can't compare offset-naive and offset-aware datetimes`
  whenever a subscription's `expires_at` came back from SQLite without
  tzinfo (which SQLite always does) — normalized both sides before
  comparing so it works on SQLite (dev) and Postgres (prod) alike.

### Security

- Plan CRUD and payment moderation now require the `ADMIN` role (see
  "Removed" above) — previously reachable by any authenticated user.
- Receipt screenshots are stored under `static/payment-proofs/`, which
  `app/main.py`'s `PublicStaticFiles` already blocked from direct
  public access; they're only ever served through the authenticated
  `/billing/payments/{id}/receipt` (owner) or `/admin/payments/{id}/receipt`
  (admin) endpoints.
- Payment amount is always taken from the `Plan` server-side at
  initiation time — never accepted from the client — preventing price
  tampering.

### Migration notes

Idempotent `ALTER TABLE` migrations were added to
`app/core/database.py::init_db` for the new `payments.method` and
`payments.provider_ref` columns, following this codebase's existing
lightweight SQLite migration pattern (no Alembic environment exists in
this project yet — `alembic` is declared in `requirements.txt` but
unused; consider wiring up a real migration environment before this
table set grows much further). All other new tables (`payments`,
`payment_cards`, `payment_events`, `admin_audit_logs`) are created
automatically by `Base.metadata.create_all` since they're new tables,
not new columns on existing ones.

---

# CHANGELOG — Backend audit & fixes

This pass focused on the exact complaint in the brief: Tests, Questions
and Exams "looked" wired together but the flow was broken in practice.
Every item below was found by actually running the code (unit tests +
a live `uvicorn` instance hit over real HTTP), not by inspection alone.
The full `Test -> Question -> Exam -> Attempt -> Result` flow is now
verified working end-to-end (see `tests/test_full_pipeline.py`, and the
HTTP trace reproduced at the bottom of this file).

## Critical bugs (silently broke core functionality)

1. **`TestQuestion` had no `question` relationship** — the single most
   important bug, matching "Eng muhim muammo" in the brief. The model
   only had `question_id` (a bare FK column), with no ORM
   `relationship()` to `Question`. As a result:
   - `app/modules/exams/attempt_repository.py`'s eager-load queries
     (`selectinload(TestQuestion.question)`) crashed outright with
     `AttributeError` the moment a student tried to start an exam.
   - `attempt_service.py` was defensively written around this
     (`tq.question if hasattr(tq, "question") else None`), which
     avoided the crash in some code paths but meant every exam
     silently resolved to **zero questions** — attempts were created
     with `total_points = 0` and grading was meaningless.
   - Fix: added `question: Mapped["Question"] = relationship(lazy="selectin")`
     to `TestQuestion` in `app/modules/tests/models.py`.

2. **No transaction commit anywhere in the Questions module or the
   entire Exams/Attempts subsystem** — `app/core/database.py`'s `get_db`
   dependency only closed the session on success; it never committed.
   Individual services were expected to call `session.commit()`
   themselves. The `Tests` module did this correctly, but:
   - `QuestionRepository` (used by every Questions endpoint: create,
     update, delete, bulk ops, categories, tags, banks, imports) never
     called `commit()` — every "successful" write was silently rolled
     back when the session closed. This is exactly the "Hozir savollar
     yaratish ishlamayapti" (question creation doesn't work) symptom:
     the API returned 200/201 with a valid-looking object, but nothing
     was actually in the database.
   - `AttemptService` and its composed grading/leaderboard/stats/review
     services never committed either — attempts, saved answers, and
     computed results all vanished the same way.
   - Fix (defense in depth, two layers):
     - `app/core/database.py`: `get_db` now commits on success
       (no-op if a service already committed itself).
     - `app/modules/questions/service.py`: `get_statistics` restored
       as its own method (see #3) as part of the same file cleanup.

3. **`QuestionService.get_statistics` didn't exist** — a bad merge had
   glued the method's *body* onto the end of `import_csv()`, after its
   `return` statement (so it was unreachable dead code), with no `def`
   for `get_statistics` at all. `GET /questions/{id}/statistics`
   crashed with `AttributeError: 'QuestionService' object has no
   attribute 'get_statistics'`. Fixed by restoring the method
   signature in `app/modules/questions/service.py`.

4. **`bcrypt`/`passlib` version mismatch crashed every register/login
   call.** `pyproject.toml` pinned `bcrypt>=4.2,<5`, but `passlib==1.7.4`
   (the current release, unmaintained since 2020) is incompatible with
   bcrypt's 4.1+ stricter 72-byte handling — its internal backend
   self-test raises `ValueError: password cannot be longer than 72
   bytes...` on the *first* password hash, i.e. on every registration.
   Fixed by pinning `bcrypt>=4.0,<4.1` (verified working against
   passlib 1.7.4).

5. **App couldn't even boot from a clean `pip install`** — several
   modules imported packages that were never declared in
   `pyproject.toml`, so a fresh install crashed with
   `ModuleNotFoundError` before the server could start:
   - `from jose import ...` (auth) → added `python-jose[cryptography]`
   - `pydantic.EmailStr` (auth schemas) → switched to `pydantic[email]`
   - `google.auth` / `google.oauth2` (Google OAuth login) → added
     `google-auth`, and its transitive need for `requests` → added
     `requests`
   - `import resend` (transactional email) → added `resend`
   - `UploadFile`/`File(...)` (Excel/CSV import endpoints) → added
     `python-multipart`
   - `starlette.middleware.sessions.SessionMiddleware` (OAuth session
     state) → added `itsdangerous`

6. **Naive/aware datetime crash on every exam submission.** SQLite
   (an explicitly supported `DATABASE_URL` in `app/core/database.py`,
   not just a test detail) returns naive `datetime` objects even for
   `DateTime(timezone=True)` columns. `AttemptService._compute_time_spent`
   subtracted a timezone-aware "now" from the naive `started_at` read
   back from the DB, raising `TypeError: can't subtract offset-naive
   and offset-aware datetimes` on `submit_attempt`/`resume_attempt`.
   Fixed by normalizing both operands to UTC-aware before subtracting.

## Test-infrastructure fixes

- `tests/conftest.py` didn't import the Notifications/Exams/Questions/
  Subscriptions/Tests model modules, so SQLAlchemy's mapper
  configuration blew up the first time a cross-module string
  relationship (e.g. `User.notifications -> "Notification"`) needed
  resolving. In production this "worked" only because `app/main.py`
  happens to import every router (and therefore every model) before
  the first request. Test collection now imports all of them
  explicitly, matching production behavior.
- Removed `tests/legacy_disabled/*.stale` — genuinely dead files that
  referenced models/methods removed in a prior refactor
  (`Exam.exam_type`, `LegacyQuestion`, `Option`,
  `app.modules.attempts.service.AttemptService`). They were already
  quarantined and unused; deleted per the "remove dead code" ask.
- Added `tests/test_full_pipeline.py`: a real integration test that
  exercises Test → Question → attach → publish → Exam → publish →
  Attempt → submit → Result, re-reading through a **fresh DB session**
  after every write so it can't be fooled by a service that "looks"
  successful without actually persisting (exactly how bug #2 above was
  caught).

## Minor cleanup

- Removed an unused `CertificateService` import in
  `app/modules/exams/attempt_grading_service.py`.
- Added a `TYPE_CHECKING` import for `Question` in
  `app/modules/tests/models.py` so the new relationship's string
  annotation is statically resolvable (was previously an undefined
  name from a linter's point of view, even though SQLAlchemy resolved
  it fine at runtime via its mapper registry).
- Deleted stray `__pycache__`/`*.pyc` files and the local `enwis.db`
  dev database from the archive.

## Verification performed

- `pytest tests/ -v` — all tests pass, including the new full-pipeline
  integration test.
- `ruff check app --select F821,F401,F811,F841` — no undefined names,
  unused imports, redefinitions, or unused locals.
- Booted the real app with `uvicorn app.main:app` against a clean
  SQLite DB and drove the **entire spec workflow over real HTTP**:
  register → login → create Test → create Question → confirm it
  persisted via a fresh `GET` → attach Question to Test → publish Test
  → create Exam → publish Exam → start Attempt → submit the correct
  answer → confirm a graded Result (100%, grade A, passed) was
  computed and persisted. No manual data seeding, no mocked services —
  this is the exact `Test(1) -> Questions(N)` and `Test(1) -> Exam(N)`
  business flow described in the brief, running against real code.

## Architecture notes (confirmed correct, no change needed)

- `Exam` never stores questions directly — it only holds `test_id`,
  matching "Exam hech qachon savollarni o'zida saqlamasligi kerak."
- Registration/OTP/apply-review lives entirely inside the Exams module
  (`apply_service.py`, `apply_router.py`), not inside Tests.
- `Question` is modeled as a reusable bank item (optionally inside a
  `QuestionBank`) that gets attached to one or more Tests via the
  `TestQuestion` join table, with points/order/required overridable per
  Test. This supports the same question being reused across Tests
  while still requiring an explicit attach step per Test — the
  attach step already existed as `POST /tests/{id}/questions`; the bug
  was that the attached question could never actually be *read back*
  by the exam-taking flow (see bug #1).
