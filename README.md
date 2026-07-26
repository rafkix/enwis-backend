# Enwis Backend — Models Phase

This archive contains only the database model layer, as scoped so far:

```
app/
├── shared/
│   └── base_model.py     # Base declarative class + BaseModel (UUID PK, created_at, updated_at)
└── modules/
    ├── users/
    │   └── models.py      # User, Subscription models + UserRole, SubscriptionPlan, SubscriptionStatus enums
    └── auth/               # placeholder — auth models to be added next phase
```

No API, repository, service, schema, or authentication logic is included yet — by design, per current project scope.

## Requirements to run migrations later
- PostgreSQL with the `pgcrypto` extension enabled:
  ```sql
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  ```
- SQLAlchemy 2.0 (async), Alembic, Python 3.13.

## Next phases (not yet implemented)
- `core/` (config, database, security, jwt, redis, logging, middleware, lifespan)
- `modules/auth/` full implementation (api, service, repository, schemas, providers)
- `modules/users/` full implementation (api, service, repository, schemas)
- Alembic migration environment
