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

## Docker

One image (build context `apps/api`) serves three commands:

| Service | Command |
| --- | --- |
| api (default) | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers` |
| worker | `celery -A app.infrastructure.jobs.celery_app worker --loglevel=INFO` |
| migrate | `alembic upgrade head` (run before the api starts) |
