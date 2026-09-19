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
uv run mypy .                             # the whole project, migrations included (what `make lint` runs)
uv run lint-imports

uv run alembic upgrade head               # migrations are an explicit step, never run by the app
uv run alembic revision --autogenerate -m "message"   # new revision from the ORM models; review it by hand
uv run uvicorn app.main:create_app --factory --reload --no-proxy-headers
uv run celery -A app.worker worker --loglevel=INFO
```

Configuration is environment-only; every variable is documented in the repo-root `.env.example`.
For local runs load the repo-root file with `uv run --env-file ../../.env <command>`.

## Draft step jobs

Run the API and `uv run celery -A app.worker worker --loglevel=INFO` with the same
`DATABASE__URL`, `REDIS__URL` and AI settings. The old
`app.infrastructure.jobs.celery_app` entrypoint was replaced so both processes compose
providers through `bootstrap.py`. No additional service or environment variable is needed.

Authenticated `POST /tasks/{id_or_key}/step-generations` (no body) returns `202` with
`{id, task_id, state: "pending", titles: [], error: null}` without calling the model in
HTTP. Poll `GET /tasks/{id_or_key}/step-generations/{id}` (normally once per second).
A success has `state: "success"` and 1–20 `titles`; a failure has `state: "failure"` and a
safe error code. Retry/regenerate by POSTing again. Keep each handle with its task when
changing selection. Unknown/deleted tasks, wrong-task jobs and expired jobs return `404`.
A Redis/queue outage returns a safe `503`, not a false pending or empty success.

Proposals expire one hour after enqueue. Unfinished jobs time out after five minutes.
Generation never creates steps: send the chosen titles to the existing
`POST /tasks/{id_or_key}/steps/bulk` to accept them (atomic, 100-step total ceiling).
See [the HTTP/lifetime contract](../../docs/architecture.md#queued-step-generation).

`AI__PROVIDER=fake` (default) produces three deterministic draft titles offline;
`openrouter` and `gemini` use the existing provider-neutral `AI__MODEL`, `AI__API_KEY`,
`AI__BASE_URL` and `AI__TIMEOUT_SECONDS` settings. The worker caps model time at 240
seconds and its hard execution limit is 250 seconds; use Celery's default prefork pool
in deployment. Never use eager mode in the API process.

Offline real-worker proof (against your own PostgreSQL/Redis):

```sh
uv run pytest -m integration tests/integration/test_step_generation_served.py -s
uv run pytest -m integration tests/integration/test_step_generation_results.py
```

The first test starts and reaps private HTTP/worker processes, uses a deterministic model
(no paid calls), and prints only task-feature requests/responses, never login credentials.

## Docker

One image (build context `apps/api`) serves three commands:

| Service | Command |
| --- | --- |
| api (default) | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers` |
| worker | `celery -A app.worker worker --loglevel=INFO` |
| migrate | `alembic upgrade head` (run before the api starts) |
