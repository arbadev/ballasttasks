# Ballast Tasks

A task management app: a Python REST API with a web frontend, built as a Clean Architecture exercise.

The repository currently contains the foundation (the monorepo, the architecture, health endpoints, the background worker and the tooling that guards them) and the first product feature: the task CRUD API under `/tasks` (create, read, update, delete, assign, mark as completed; see the [task contract](docs/architecture.md#task-contract) and Swagger UI). It sits behind **JWT authentication** (`/auth/register`, `/auth/login`, `/auth/me`; see [authentication](docs/architecture.md#authentication)): a `/tasks` request without a valid bearer or browser-cookie credential is answered `401`. The API also carries the model the web design shows: projects (`/projects`), task keys such as `BT-04`, four statuses, priority and importance, a people list (`/users`), a task list that is filtered, sorted, searched and paged by the database, and the computed attention data (`attention` on every task, `GET /tasks/summary`); see [projects and task keys](docs/architecture.md#projects-and-task-keys) and [ADR 0005](docs/decisions/0005-task-keys-and-urgency.md). **Single sign-on** (Google first, off by default) is a second way in under `/auth/sso/*` that ends in the same access token; see [single sign-on](docs/architecture.md#single-sign-on). The web callback at `/auth/callback` exchanges the one-time code through the API; real-vendor setup remains an operator action. Tasks also carry **attachments** under `/tasks/{id_or_key}/attachments`: http(s) links and uploaded files (PDF, PNG, JPEG, GIF, WebP), streamed in and out through a `FileStorage` port whose local-disk adapter is replaced by a cloud one with a single registry line; see [task attachments](docs/architecture.md#task-attachments) and [ADR 0008](docs/decisions/0008-file-storage.md). The web app uses HTTP-backed services by default: password sign-in/registration, list/board/detail editing, projects (creating, renaming and recolouring), steps/comments/activity, file/link attachments and queued step proposals with explicit acceptance. Set `NEXT_PUBLIC_SERVICE_MODE=demo` only for the explicit in-memory design demo. Browser sessions use server-validated HttpOnly cookies: reload/new tab restores a session until its configured JWT expiry or browser logout. Anonymous `/login` and `/register` and protected task/project routes preserve validated filters, view and pagination in the URL; saved work remains in PostgreSQL. See [ADR 0009](docs/decisions/0009-browser-sessions-and-routes.md) for CSRF, origin and exact persistence/logout limits. See [web integration](apps/web/README.md#authentication-and-http-integration). The API's own demo data — the design's people, projects and tasks, with credentials to log in and explore them — is an explicit opt-in local command, never run on startup: see [local demo data](apps/api/README.md#local-demo-data-explicit-optional).

A task also carries **steps** (`/tasks/{id_or_key}/steps`, added singly or in an atomic batch of up to 20, reordered, ticked and deleted), immutable **comments** (`/comments`) and an **activity timeline** (`/activity`) that also records attaching and removing. Every task representation carries its step, comment and attachment tallies, counted for a whole page in one query; the fields are listed in the [task contract](docs/architecture.md#task-contract). See [steps and activity](docs/architecture.md#steps-and-activity) and [ADR 0007](docs/decisions/0007-steps-and-activity.md).

Step titles can also be **drafted by the language model** in the background: `POST /tasks/{id_or_key}/step-generations` queues the work and answers immediately with a job handle, `GET /tasks/{id_or_key}/step-generations/{job_id}` polls it, and the chosen titles become steps only through the bulk-add endpoint above; see [queued step generation](docs/architecture.md#queued-step-generation).

Every route except the health endpoints is **rate limited** (strict per-IP limits on login and registration, per-user and per-IP limits elsewhere; `429` with `Retry-After` and `X-RateLimit-*` headers; counted in Redis, and the API keeps serving when Redis is down): see [rate limiting](docs/architecture.md#rate-limiting) and [ADR 0004](docs/decisions/0004-rate-limiting.md).

## Architecture at a glance

- **`apps/api`**: FastAPI + Celery, organised as ports and adapters. Use cases depend on small `typing.Protocol` ports; adapters are wired in one composition root, `bootstrap.py`. Layer rules are enforced by import-linter.
- **`apps/web`**: Next.js. Components depend on service interfaces provided by one composition root, `providers.tsx`; only `client.ts` talks to the network.
- **One HTTP contract**: Pydantic models -> OpenAPI -> generated TypeScript types.
- **PostgreSQL** everywhere (local, Docker, integration tests) and **Redis** as the Celery broker and result backend, and the shared rate limit counters.

Full description with diagrams: [docs/architecture.md](docs/architecture.md). Decisions: [ADR 0001: monorepo](docs/decisions/0001-monorepo.md), [ADR 0002: ports and adapters](docs/decisions/0002-ports-and-adapters.md), [ADR 0003: LLM adapters over HTTP](docs/decisions/0003-llm-adapters-over-http.md), [ADR 0004: rate limiting](docs/decisions/0004-rate-limiting.md), [ADR 0006: single sign-on](docs/decisions/0006-single-sign-on.md), [ADR 0007: steps and activity](docs/decisions/0007-steps-and-activity.md), [ADR 0008: file storage](docs/decisions/0008-file-storage.md).

## Prerequisites

To run the system:

- A Docker-compatible container runtime with Docker Compose v2 (`docker compose`).

To run tests and linters on the host:

- [uv](https://docs.astral.sh/uv/) (it installs the Python version the API asks for).
- [Node.js](https://nodejs.org/) (current LTS) with npm.
- `make`, and optionally [pre-commit](https://pre-commit.com/).

## Quick start

```sh
cp .env.example .env && docker compose up --build
```

That starts all five services (`db`, `redis`, `api`, `worker`, `web`) with no other step. `.env.example` holds working local values; nothing needs editing. The AI provider that ships active is the offline `fake`; to use a real one (OpenRouter is the recommended one, Gemini the alternative), edit the `AI__*` lines in `.env` as their comments in `.env.example` describe. Single sign-on ships disabled, so password login works with no credentials; the `SSO__*` comments in `.env.example` describe how to enable Google or the credential-free `fake` provider.

| What | URL |
| --- | --- |
| Web app | <http://localhost:3000> |
| API | <http://localhost:8000> |
| Swagger UI | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness (database, redis, ai) | <http://localhost:8000/health/ready> |

To try authentication, open Swagger UI, call `POST /auth/register`, then press **Authorize** and enter the same email (as `username`) and password: Swagger logs in through `POST /auth/login` and sends the bearer token on every later call, such as `GET /auth/me`. Details: [docs/architecture.md](docs/architecture.md#authentication).

To explore the design's tasks and people instead of an empty database, seed a **local** database once with the explicit demo command described in [local demo data](apps/api/README.md#local-demo-data-explicit-optional).

Stop with `Ctrl+C`, then `make down` (`docker compose down`; add `-v` to also drop the database and attachment volumes).

Only the web app (3000) and the API (8000) are published to the host, so those two ports must be free. PostgreSQL and Redis stay inside the compose network, where the services reach them as `db` and `redis`; the browser reaches the API at `NEXT_PUBLIC_API_URL`, which is baked into the web image at build time.

## Tests and linters

Install each app's dependencies once:

```sh
(cd apps/api && uv sync)
(cd apps/web && npm install)
```

Then, from the repo root:

```sh
make test   # api: uv run pytest --cov    web: npm run test -- --coverage
make lint   # ruff check, ruff format --check, mypy, lint-imports, web lint, tsc --noEmit
make help   # list every target
```

API integration tests need PostgreSQL and Redis. With the system running (`make up`), run them against that stack:

```sh
make test-integration   # pytest -m integration in a one-off container on the compose network
```

See [docs/architecture.md](docs/architecture.md#testing-strategy).

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
├── .env.example              copy to .env; works as is
├── Makefile                  up, down, test, test-integration, lint
├── AGENTS.md                 rules for coding agents (CLAUDE.md imports it)
└── README.md
```
