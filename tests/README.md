# Tests

- `test_smoke.py` — sanity check that fixtures/DB wiring work.
- `test_full_pipeline.py` — full integration test of the core business
  flow described in the product spec:

  ```
  Test (create) -> Question (create) -> attach Question to Test
    -> publish Test -> create Exam (linked to Test) -> publish Exam
    -> start Attempt -> submit answers -> auto-graded Result
  ```

  It deliberately re-reads data with a **fresh session** after every
  write (the same way a new HTTP request would), so it catches the
  "response looked fine but nothing was actually saved" class of bug —
  this is exactly how the missing-commit bug in the Questions/Exams
  modules and the missing `TestQuestion.question` relationship were
  found and verified fixed. See `CHANGELOG.md` at the project root for
  details on both.

Run with:

```bash
pytest tests/ -v
```

Useful entry points to test against directly:

- `app.modules.tests.service.TestService` — test CRUD, publish,
  duplicate, settings, AI generation (`generate_questions`).
- `app.modules.questions.service.QuestionService` — question CRUD,
  bulk create, JSON/Excel/CSV import.
- `app.modules.exams.service.ExamService` — exam CRUD, publish,
  duplicate, participants.
- `app.modules.exams.apply_service.ApplyService` — apply-link
  registration flow (apply -> review -> participant).
- `app.modules.exams.attempt_service.AttemptService` — start, save,
  submit, manual grade, leaderboard, review.
- `app.modules.exams.certificate_service.CertificateService` —
  certificate issuance and verification.
