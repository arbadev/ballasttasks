# ADR 0001: One repository for docs, backend, frontend and infrastructure

- Status: Accepted
- Date: 2026-09-18

## Context

The deliverable is a task management REST API with a frontend, judged on Clean Architecture, test coverage, code quality and a working end-to-end system.
The frontend's types are generated from the backend's OpenAPI schema, so the two applications change together whenever the HTTP contract changes.
A reviewer must be able to clone one thing and run the whole system with no manual steps.

## Decision

Everything lives in one repository:

- `docs/`: product docs, architecture and decision records.
- `apps/api/`: FastAPI service and Celery worker, with its own `pyproject.toml` and `uv.lock`.
- `apps/web/`: Next.js frontend, with its own `package.json` and `package-lock.json`.
- Repo root: one `docker-compose.yml`, one `.pre-commit-config.yaml`, one `Makefile`, one `.env.example`.

Each app keeps its own toolchain, lockfile and `.gitignore`. There is no shared workspace manager and no cross-app build tool.
Nothing in the repo creates, references or depends on anything outside the repo root.

## Consequences

Positive:

- One source of truth: the API contract, the generated frontend types and the docs are versioned together.
- A contract change and the frontend type fix land in the same commit, so `main` is never in a half-migrated state.
- One `docker compose up --build` runs the system; one pre-commit configuration guards the whole repo.
- A reviewer sees the full history of a feature (docs, API, UI, infra) in one log.

Negative:

- Two toolchains (uv and npm) live side by side; the root `Makefile` exists to hide that behind `make test` and `make lint`.
- CI and pre-commit run checks for both apps even when only one changed. Acceptable at this size.
- The apps cannot be versioned or released independently. Not needed for this deliverable.

## Alternatives considered

- **Two repositories (api, web).** Rejected: a contract change becomes two coordinated commits with a window where the generated types are stale, and the reviewer has to clone and wire two things.
- **Monorepo with a workspace/build tool (Nx, Turborepo, Pants).** Rejected: two apps in two languages do not justify the extra dependency and configuration; a `Makefile` with four targets covers the need.
- **A shared published types package.** Rejected: generating `schema.d.ts` straight from the API's OpenAPI schema gives the same guarantee without a publish step.
