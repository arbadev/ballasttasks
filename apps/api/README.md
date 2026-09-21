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
| `app.seed_demo` | `python -m app.seed_demo`: the explicit local demo seed (below) | `bootstrap`, `application` |
| `app.worker` | `celery_app`: settings -> bootstrap -> the worker's Celery app | `bootstrap` |

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

## Local demo data (explicit, optional)

After migrations, seed **only a local development/demo database**. With the local compose
API running, invoke from the repo root:

```sh
docker compose exec api python -m app.seed_demo --confirm-demo-accounts
```

Or, from `apps/api`, with your local `DATABASE__URL`, `REDIS__URL`, `AUTH__JWT_SECRET`
and other settings loaded: `uv run python -m app.seed_demo --confirm-demo-accounts`.
No seed runs on startup; there is no seed HTTP route or startup flag. The command does
not run migrations and requires no AI/provider calls.

Two refusals guard it, both before any database connection is opened:

- `APP__ENV=production` is refused, with or without the flag. Do not override that
  setting to seed a deployed database.
- Without `--confirm-demo-accounts` nothing is written at all.

The flag records your intent; it is not a safety check. It says you accept that this
database will hold accounts whose password is published in this repository. Nothing in
the command can tell whether `DATABASE__URL` points at a local database you own — a
shared development or staging database is not production-labelled and would be seeded —
so read that variable yourself before passing the flag.

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
The web app's default HTTP mode reads this same persisted data after sign-in. The seed
command does not change the explicit in-memory web demo; see [web integration](../web/README.md#authentication-and-http-integration).

The self-contained fixture is `src/app/application/demo_data.py`, corresponding to the
web's `src/features/tasks/services/seed.ts`: **16 tasks, 13 open** (8 todo, 3 in progress,
2 testing, 3 done), 14 in Ballast Tasks (`BT`) and 2 in the existing Inbox (`IN`). It also
adds Assistant (`system`, no password sign-in), so all four design people are visible.
Role labels grant no permissions. API initials are derived: Assistant is `AS`, not the
design's manually supplied `AI`. Design `progress` becomes API `in_progress`; completed
tasks use their last update time as `completed_at`, creators come from the design's
creation activity, and empty descriptions become `null`. This seed covers task metadata
and each task's required `Created the task` event through `ActivityRecorder` (ADR 0007),
attributed to its creator at the original creation time. It does not insert the design's
historical steps, comments, status-change history or attachments. Descriptions are
historical design sample copy, not a claim that those features are implemented.

Dates are relative to the injected UTC clock at first invocation: 1 overdue, 2 P0 at risk,
4 due soon, 2 needing an owner, and 7 open tasks assigned to Andres. Existing Inbox
metadata and tasks stay intact; every new key is allocated through the project repository
(`BT-01`–`BT-14` on a fresh demo project; Inbox numbering continues after existing tasks).

**Safe reruns:** one request-scope transaction owns every insert and key allocation.
Concurrent invocations serialise on the existing Inbox row. Stable demo IDs and the demo
project's creation timestamp identify and date the seed. An intact rerun says `Demo
unchanged` without rewriting hashes, dates or rows. A conflicting email, ID or project
key, edited demo record/password, or partial/deleted seed (including creation events) is
refused, not repaired; all in-flight inserts and counters roll back. Unrelated records are
never deleted or reset. Use a separate fresh local database if you need the original
scenarios again after edits or as dates age. Failure returns a nonzero exit status
without printing credentials.

## Draft step jobs

Run the API and `uv run celery -A app.worker worker --loglevel=INFO` with the same
`DATABASE__URL`, `REDIS__URL` and AI settings. The old
`app.infrastructure.jobs.celery_app` entrypoint was replaced so both processes compose
providers through `bootstrap.py`. No additional service or environment variable is needed.

Authenticated `POST /tasks/{id_or_key}/step-generations` (no body) returns `202` with
`{id, task_id, state: "pending", titles: [], error: null}` without calling the model in
HTTP. Poll `GET /tasks/{id_or_key}/step-generations/{id}` with a bounded backoff: 2s, 4s,
8s, then every 10s, stopping on a terminal state and staying at the 10s bound while the
task is not the selected one. Two concurrent generations then fit inside the shipped
authenticated budget (120 per 60s); on `429`, wait `Retry-After` before polling again.
A success has `state: "success"` and 1–20 `titles`; a failure has `state: "failure"` and a
safe error code (`invalid_output`, `provider_unavailable`, `timeout` or `worker_failed`).
Retry/regenerate by POSTing again. Keep each handle with its task when changing selection;
handles survive the change. Unknown/deleted tasks, wrong-task jobs and expired jobs return
`404`, including a task deleted while its generation was running.
A Redis/queue outage returns a safe `503`, not a false pending or empty success.

Proposals expire one hour after enqueue. Unfinished jobs time out after five minutes.
Neither is a spending cap: enqueue is bounded only by the shared authenticated request
allowance, so a paid provider has no generation-specific cost protection here. A job that
fails before or outside the model call logs one warning with the task id and a fixed
category (`configuration`, `database`, `cache`, `unexpected`) and nothing from the cause.
Generation never creates steps: send the chosen titles to the existing
`POST /tasks/{id_or_key}/steps/bulk` to accept them (atomic, 100-step total ceiling).
See [the HTTP/lifetime contract](../../docs/architecture.md#queued-step-generation).

`AI__PROVIDER=fake` (explicit offline choice, with `AI__MODEL=fake-1`) produces three deterministic draft titles offline;
`openrouter` and `gemini` use the existing provider-neutral `AI__MODEL`, `AI__API_KEY`,
`AI__BASE_URL` and `AI__TIMEOUT_SECONDS` settings. The worker waits
`min(AI__TIMEOUT_SECONDS, 240)` seconds for the model and its hard execution limit is 250
seconds; use Celery's default prefork pool in deployment. Never use eager mode in the API
process.

Offline real-worker proof (against your own PostgreSQL/Redis):

```sh
uv run pytest -m integration tests/integration/test_step_generation_served.py -s
uv run pytest -m integration tests/integration/test_step_generation_results.py
```

The first test starts and reaps private HTTP/worker processes, uses a deterministic model
(no paid calls), and prints only task-feature requests/responses, never login credentials.

## AI configuration

The normal default is `AI__PROVIDER=openrouter`, `AI__MODEL=~openai/gpt-luna-latest`.
Supply `AI__API_KEY` to both API and worker; the API refuses to start without it.
The worker builds its model per job: a missing worker key becomes a safe `worker_failed`
result with the fixed `configuration` log category, never an offline fallback. Leave
`AI__BASE_URL` blank to use `https://openrouter.ai/api/v1`. Do not put a model-page URL
or the `/chat/completions` suffix there: the adapter appends its own endpoint paths.
Editing `.env` does not change an already-running service's environment.

The exact `~openai/gpt-luna-latest` identifier is a public model alias, not an
`@preset/...` workspace preset. OpenRouter's public and authenticated model listings
reported it on 2026-09-21, targeting `openai/gpt-5.6-luna`; that target may change.
Public listing alone is not proof your account can use it. Readiness only checks
`GET /key` (cached, no generation); model availability, routing and credits can still
prevent a job. No missing/rejected-key fallback exists.

OpenRouter sends `reasoning: {enabled: true}` and returns **only final message content**
through the unchanged single-prompt port. Returned `reasoning_details` are opaque and
are neither saved as steps nor logged. There is no conversation store or multi-turn UI.
If writing a separate continuation example, pass the assistant's `reasoning_details`
unmodified, authenticate **both** requests, and check HTTP/API errors before reading
`choices`. Reasoning tokens are billed and count toward the completion budget.

Offline: explicitly set `AI__PROVIDER=fake` and `AI__MODEL=fake-1`; no key is needed.
Gemini alternative: `AI__PROVIDER=gemini`, `AI__MODEL=gemini-3.8-flash`, its own
`AI__API_KEY`, and blank `AI__BASE_URL` (or its documented Google API root).
Default and integration tests select fakes/stub transports and never need a provider key.
Opt-in `uv run pytest -m live` uses the selected real provider and **spends tokens**;
run it only intentionally, separately from offline validation.

The queue remains API → Redis broker → Celery → selected model → Redis result → poll;
only explicit bulk acceptance writes steps. Redis proposals are ephemeral, not durable
job rows. The normal HTTP budgets are not model-spend or per-job quotas.

## Docker

One image (build context `apps/api`) serves three commands:

| Service | Command |
| --- | --- |
| api (default) | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers` |
| worker | `celery -A app.worker worker --loglevel=INFO` |
| migrate | `alembic upgrade head` (run before the api starts) |
