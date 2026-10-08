"""Application modules — each sub-package is a bounded context.

Modules follow a consistent internal structure:
  models.py       — SQLAlchemy ORM models
  schemas.py      — Pydantic request/response schemas
  repository.py   — Data-access layer (SQLAlchemy sessions)
  service.py      — Business-logic layer
  router.py       — FastAPI router with HTTP endpoints
  dependencies.py — FastAPI dependencies
  constants.py    — Module-level constants
  exceptions.py   — Domain exceptions
"""
