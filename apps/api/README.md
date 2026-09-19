# apps/api

FastAPI backend, Clean Architecture. Python 3.14, uv, SQLAlchemy (async, psycopg), Alembic,
Celery + Redis. PostgreSQL everywhere, including tests.

## Layers (enforced by import-linter, see `pyproject.toml`)

| Package | Role | May import |
| --- | --- | --- |
| `app.domain` | entities and their rules (`Task`) | nothing |
| `app.application` | ports (`typing.Protocol`) and use cases | `domain` |
| `app.infrastructure` | adapters + `config/settings.py` (the only env reader) | `application`, `domain` |
| `app.api` | routes, Pydantic schemas (the HTTP contract), dependencies | `application` |
| `app.bootstrap` | composition root: the only importer of concrete adapters | everything |
| `app.main` | `create_app()`: settings -> bootstrap -> routes | `bootstrap`, `api` |

Swapping or adding an adapter = a new adapter file, one registration line, one line in the
port's contract suite (`tests/contract/`), and an env change. Where each kind of adapter is
registered: "How to add an adapter" in [`docs/architecture.md`](../../docs/architecture.md#how-to-add-an-adapter).

## Commands (run from `apps/api`)

```sh
uv sync                                   # install (locked)
uv run pytest --cov                       # default suite: needs NO PostgreSQL/Redis, coverage >= 80%
uv run pytest -m integration              # needs DATABASE__URL, REDIS__URL (live services) and AUTH__JWT_SECRET
uv run pytest -m live                     # opt-in: calls real third parties (AI provider, Google sign-in), skipped without their credentials
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run lint-imports

uv run alembic upgrade head               # migrations are an explicit step, never run by the app
uv run alembic revision --autogenerate -m "message"   # new revision from the ORM models; review it by hand
uv run uvicorn app.main:create_app --factory --reload --no-proxy-headers
uv run celery -A app.infrastructure.jobs.celery_app worker --loglevel=INFO
```

Configuration is environment-only; every variable is documented in the repo-root `.env.example`.
For local runs load the repo-root file with `uv run --env-file ../../.env <command>`.

## Local demo data (explicit, optional)

After migrations, seed **only a local development/demo database**. With the local compose
API running, invoke from the repo root:

```sh
docker compose exec api python -m app.seed_demo
```

Or, from `apps/api`, with your local `DATABASE__URL`, `REDIS__URL`, `AUTH__JWT_SECRET`
and other settings loaded: `uv run python -m app.seed_demo`. No seed runs on startup;
there is no seed HTTP route or startup flag. `APP__ENV=production` is refused before
opening any database connection. Do not override that setting to seed a deployed database.
The command does not run migrations and requires no AI/provider calls.

Intentional **public, demo-only** password: `ballast-local-demo-only` for these accounts:

| Email | Person | Role label |
| --- | --- | --- |
| `demo@ballast.example` | Andres Barradas | owner |
| `lucia@ballast.example` | Lucía Marín | backend |
| `tomas@ballast.example` | Tomás Rey | frontend |

These reserved example addresses are not real accounts. Never reuse this password or
expose this database publicly. Use `/docs` → **Authorize** with an email as the username,
or `POST /auth/login` (form fields `username`, `password`), then explore `/auth/me`,
`/users`, `/projects`, `/tasks?status=all` and `/tasks/summary` through the real API.
Frontend authentication and HTTP-backed task services are separate work; this command
does not connect the in-memory web demo to the API.

The self-contained fixture is `src/app/application/demo_data.py`, corresponding to the
web's `src/features/tasks/services/seed.ts`: **16 tasks, 13 open** (8 todo, 3 in progress,
2 testing, 3 done), 14 in Ballast Tasks (`BT`) and 2 in the existing Inbox (`IN`). It also
adds Assistant (`system`, no password sign-in), so all four design people are visible.
Role labels grant no permissions. API initials are derived: Assistant is `AS`, not the
design's manually supplied `AI`. Design `progress` becomes API `in_progress`; completed
tasks use their last update time as `completed_at`, creators come from the design's
creation activity, and empty descriptions become `null`. Only current API fields are
seeded: not steps, attachments or activity. Descriptions are historical design sample
copy, not a claim that the features they describe are implemented.

Dates are relative to the injected UTC clock at first invocation: 1 overdue, 2 P0 at risk,
4 due soon, 2 needing an owner, and 7 open tasks assigned to Andres. Existing Inbox
metadata and tasks stay intact; every new key is allocated through the project repository
(`BT-01`–`BT-14` on a fresh demo project; Inbox numbering continues after existing tasks).

**Safe reruns:** one request-scope transaction owns every insert and key allocation.
Concurrent invocations serialise on the existing Inbox row. Stable demo IDs and the demo
project's creation timestamp identify and date the seed. An intact rerun says `Demo
unchanged` without rewriting hashes, dates or rows. A conflicting email, ID or project
key, edited demo record/password, or partial/deleted seed is refused, not repaired; all
in-flight inserts and counters roll back. Unrelated records are never deleted or reset.
Use a separate fresh local database if you need the original scenarios again after edits
or as dates age. Failure returns a nonzero exit status without printing credentials.

## Docker

One image (build context `apps/api`) serves three commands:

| Service | Command |
| --- | --- |
| api (default) | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers` |
| worker | `celery -A app.infrastructure.jobs.celery_app worker --loglevel=INFO` |
| migrate | `alembic upgrade head` (run before the api starts) |
