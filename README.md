# Ballast Tasks

A task management app: a Python REST API with a web frontend, built as a Clean Architecture exercise.

The implemented app includes authenticated task CRUD, a list and board, projects,
assignment, completion, database-backed filtering/search/pagination, and computed
attention signals. Task keys such as `BT-04` stay stable when a task moves projects.
The web frontend uses the real API by default, with password registration/sign-in,
steps, comments, activity, file/link attachments and queued draft-step proposals.
It is a **shared workspace**: every signed-in user can read and change every task
and project; role labels are not permissions.

Browser sessions use server-validated HttpOnly cookies. Reload/new tab restores a
valid session until its existing JWT expiry; URL-owned filters, view and pagination
survive navigation. Saved data stays in PostgreSQL. Bearer clients and Swagger
remain supported, and optional Google single sign-on is disabled until configured.
See [ADR 0009](docs/decisions/0009-browser-sessions-and-routes.md) for CSRF and the
exact expiry/logout limits, and [web integration](apps/web/README.md#authentication-and-http-integration).
`NEXT_PUBLIC_SERVICE_MODE=demo` selects a separate in-memory design demo, not the
persisted API seed described below.

A task also carries **steps** (`/tasks/{id_or_key}/steps`, added singly or in an atomic batch of up to 20, reordered, ticked and deleted), immutable **comments** (`/comments`) and an **activity timeline** (`/activity`) that also records attaching and removing. Every task representation carries its step, comment and attachment tallies, counted for a whole page in one query; the fields are listed in the [task contract](docs/architecture.md#task-contract). See [steps and activity](docs/architecture.md#steps-and-activity) and [ADR 0007](docs/decisions/0007-steps-and-activity.md).

Step titles can also be **drafted by the language model** in the background: `POST /tasks/{id_or_key}/step-generations` queues the work and answers immediately with a job handle, `GET /tasks/{id_or_key}/step-generations/{job_id}` polls it, and the chosen titles become steps only through the bulk-add endpoint above; see [queued step generation](docs/architecture.md#queued-step-generation).

Every route except the health endpoints is **rate limited** (strict per-IP limits on login and registration, per-user and per-IP limits elsewhere; `429` with `Retry-After` and `X-RateLimit-*` headers; counted in Redis, and the API keeps serving when Redis is down): see [rate limiting](docs/architecture.md#rate-limiting) and [ADR 0004](docs/decisions/0004-rate-limiting.md).

## Submission guide

| Requirement | Where to look |
| --- | --- |
| Setup, configuration, service URLs and checks | [Quick start](#quick-start), [tests and linters](#tests-and-linters), [API guide](apps/api/README.md), [web guide](apps/web/README.md) |
| Seeded data and public demo credentials | [Demo walkthrough](#demo-walkthrough), [seed safety and exact fixture](apps/api/README.md#local-demo-data-explicit-optional) |
| Key implementation decisions | [Architecture at a glance](#architecture-at-a-glance) and linked ADRs |
| Coding tool and usable scaffold prompt | [Tools](docs/ai-usage.md#tools-used), [proposed and retained prompts](docs/ai-usage.md#prompts-used) |
| Representative resulting code | [Exact source excerpts](docs/ai-usage.md#representative-output) |
| Validation and corrections | [Validation evidence](docs/ai-usage.md#how-suggestions-were-validated), [improvements](docs/ai-usage.md#corrections-and-improvements-made) |
| Edge cases, authentication and validation | [Handling and tests](docs/ai-usage.md#edge-cases-authentication-and-validation-handling) |
| Performance and idiomatic quality | [Assessment and limits](docs/ai-usage.md#performance-and-idiomatic-quality-assessment) |

## Architecture at a glance

- **`apps/api`**: FastAPI + Celery, organised as ports and adapters. Use cases depend on small `typing.Protocol` ports; adapters are wired in one composition root, `bootstrap.py`. Layer rules are enforced by import-linter.
- **`apps/web`**: Next.js. Components depend on service interfaces provided by one composition root, `providers.tsx`; only `client.ts` talks to the network.
- **One HTTP contract**: Pydantic models -> OpenAPI -> generated TypeScript types.
- **PostgreSQL** everywhere (local, Docker, integration tests) and **Redis** as the Celery broker and result backend, and the shared rate limit counters.

Full description with diagrams: [docs/architecture.md](docs/architecture.md). Decisions: [ADR 0001: monorepo](docs/decisions/0001-monorepo.md), [ADR 0002: ports and adapters](docs/decisions/0002-ports-and-adapters.md), [ADR 0003: LLM adapters over HTTP](docs/decisions/0003-llm-adapters-over-http.md), [ADR 0004: rate limiting](docs/decisions/0004-rate-limiting.md), [ADR 0006: single sign-on](docs/decisions/0006-single-sign-on.md), [ADR 0007: steps and activity](docs/decisions/0007-steps-and-activity.md), [ADR 0008: file storage](docs/decisions/0008-file-storage.md), [ADR 0009: browser sessions and routes](docs/decisions/0009-browser-sessions-and-routes.md).

## Prerequisites

To run the system:

- A Docker-compatible container runtime with Docker Compose v2 (`docker compose`).

To run tests and linters on the host:

- [uv](https://docs.astral.sh/uv/) (it installs the Python version the API asks for).
- [Node.js](https://nodejs.org/) 24 with npm (the web Dockerfile uses Node 24).
- `make`, and optionally [pre-commit](https://pre-commit.com/).

## Quick start

From a fresh clone, in the repository root, on a local machine you control:

```sh
# Preserve existing configuration; create a private local file only when absent.
if [ ! -e .env ]; then (umask 077; cp .env.example .env); fi
docker compose up --build
```

Review [`.env.example`](.env.example) before starting. Its database credentials and
JWT signing secret are **local-only examples**, not deployment secrets. Do not commit
`.env` or overwrite an existing one. The default ports 3000 and 8000 must be free;
these Compose bindings are not restricted to loopback, so do not expose this local
demo on an untrusted network.

Compose starts all five services (`db`, `redis`, `api`, `worker`, `web`). It waits for
PostgreSQL/Redis health, runs `alembic upgrade head` in the API command before starting
Uvicorn, then starts the worker/web after API liveness. The application itself never
runs migrations; native setup uses the [API commands](apps/api/README.md#commands-run-from-appsapi).
No startup seeds accounts or tasks. The example configuration works offline. The AI provider that ships active is the offline `fake`; to use a real one (OpenRouter is the recommended one, Gemini the alternative), edit the `AI__*` lines in `.env` as their comments in `.env.example` describe. Single sign-on ships disabled, so password login works with no credentials; the `SSO__*` comments in `.env.example` describe how to enable Google or the credential-free `fake` provider.

| What | URL |
| --- | --- |
| Web app | <http://localhost:3000> |
| API | <http://localhost:8000> |
| Swagger UI | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness (database, redis, ai) | <http://localhost:8000/health/ready> |

To try authentication, open Swagger UI, call `POST /auth/register`, then press **Authorize** and enter the same email (as `username`) and password: Swagger logs in through `POST /auth/login` and sends the bearer token on every later call, such as `GET /auth/me`. Details: [docs/architecture.md](docs/architecture.md#authentication).

Check `docker compose ps` and `/health/ready` before exploring. Liveness only proves
the API process answers; readiness reports database, Redis and AI checks (`200` when
all pass, `503` otherwise), not that a worker can consume jobs. If startup fails, inspect
`docker compose logs api worker`; do not delete data or reseed to fix configuration.

### Demo walkthrough

Only after confirming the configured database is your **local demo database**, run:

```sh
docker compose exec api python -m app.seed_demo --confirm-demo-accounts
```

Open <http://localhost:3000/login> and use **`demo@ballast.example`** with password
**`ballast-local-demo-only`**. These are intentionally public, demo-only credentials
from [the fixture](apps/api/src/app/application/demo_data.py), never suitable for a
public deployment. Additional demo users and full safety rules are in the
[API seed guide](apps/api/README.md#local-demo-data-explicit-optional).

The seed adds 16 tasks (13 open), the Ballast Tasks project alongside Inbox, and four
people (three password accounts plus Assistant, which cannot sign in). Inspect All/My
tasks, project filters and the board; open a task, edit it, add a step/comment or file,
and reload to see persisted changes. Drafting queues proposals; only **accepting**
chosen proposals stores steps. The seed itself does not call a model or include
historical steps, comments or attachments.

Seeding is opt-in, not a reset command. Production mode and missing confirmation are
refused before adapters are built. An intact rerun reports `Demo unchanged`; conflicts,
edited records/passwords and partial seeds are refused, not overwritten. Unrelated
records are preserved. Do not change production mode just to bypass the refusal.

### Stop and rebuild without losing saved work

Stop foreground services with `Ctrl+C`; normal teardown and subsequent rebuild are:

```sh
docker compose down
docker compose up --build -d
```

Keep the same Compose project/configuration to reuse the named PostgreSQL and attachment
volumes. **Do not add `-v`**, prune volumes or reset the database as routine troubleshooting.
Changing `POSTGRES_*` in an env file does not change credentials in an initialized volume.
Redis proposals/queued jobs are ephemeral; accepted steps are persisted in PostgreSQL.

Only the web app (3000) and the API (8000) are published to the host. PostgreSQL and
Redis stay inside the Compose network, reached as `db` and `redis`. The browser API
origin (`NEXT_PUBLIC_API_URL`) and service mode are baked into the web image: changing
them requires a rebuild, not just a restart. Keep `CORS__ALLOWED_ORIGINS` equal to the
web origin and use the same hostname spelling for web/API (`localhost`, not mixed with
`127.0.0.1`). Local HTTP uses `APP__ENV=development` even with a production Next build;
production API mode requires HTTPS origins and Secure cookies. Configuration details
and SSO redirects are in [`.env.example`](.env.example) and [ADR 0009](docs/decisions/0009-browser-sessions-and-routes.md).

## Tests and linters

Install the locked dependencies once (Python 3.14 is selected by the API project):

```sh
(cd apps/api && uv sync --frozen)
(cd apps/web && npm ci)
```

Then, from the repo root:

```sh
make test   # api: uv run pytest --cov    web: npm run test -- --coverage
make lint   # ruff check, ruff format --check, mypy, lint-imports, web lint, tsc --noEmit
make help   # list every target
```

Default API tests and web unit tests need no external services. Integration tests need
PostgreSQL and Redis: use a **dedicated disposable test stack**, not a retained demo
or shared deployment. Against that owned running Compose stack:

```sh
make test-integration   # pytest -m integration in a one-off container on the compose network
```

The integration harness creates temporary PostgreSQL databases; tests also exercise
Redis and real workers. See the [testing strategy](docs/architecture.md#testing-strategy).
For production-build and visual/real-HTTP browser commands, required explicit endpoints
and test isolation, see the [web guide](apps/web/README.md#commands).
Historical passes are not an all-tests-green claim for current source: the known
Next development React185 failure remains unresolved; see [validation limits](docs/ai-usage.md#how-suggestions-were-validated).

To run the same checks on every commit: `pre-commit install` (or once, by hand: `pre-commit run --all-files`). The hooks use each app's installed dependencies, so do the two installs above first.

## How the API contract reaches the frontend

```text
Pydantic response model -> OpenAPI schema -> npm run gen:api -- <your-api-url>/openapi.json (openapi-typescript) -> schema.d.ts -> service -> component
```

1. Change the Pydantic response model in `apps/api`.
2. Run `npm run gen:api -- <your-api-url>/openapi.json` in `apps/web` to regenerate `schema.d.ts`.
   The schema source is always given explicitly. Never edit that file by hand.
3. Fix whatever the TypeScript compiler now reports.
4. Commit the API change, the regenerated types and the frontend fix **together**.

## Repo map

```text
.
├── apps/
│   ├── api/                  FastAPI service and Celery worker (uv, pytest, ruff, mypy, import-linter)
│   │   └── src/app/          domain, application (ports, use cases), infrastructure (adapters and
│   │                         config/settings.py, the only env reader), api (presentation),
│   │                         bootstrap.py (composition root)
│   └── web/                  Next.js frontend (npm)
│       └── src/app/          providers.tsx (composition root)
├── docs/
│   ├── PRD.md                product requirements
│   ├── architecture.md       layers, ports, composition roots, HTTP contract, SOLID mapping
│   ├── ai-usage.md           how GenAI tools were used and checked
│   └── decisions/            architecture decision records
├── docker-compose.yml        the whole system
├── .pre-commit-config.yaml   one guard for the whole repo
├── .env.example              local-only defaults; preserve an existing .env
├── Makefile                  up, down, test, test-integration, lint
├── AGENTS.md                 rules for coding agents (CLAUDE.md imports it)
└── README.md
```
