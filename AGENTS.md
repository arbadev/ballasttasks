# Ballast Tasks: agent instructions

Task management REST API (FastAPI + Celery) with a Next.js frontend, in one monorepo.
Authority for everything below: [docs/architecture.md](docs/architecture.md). Decisions: [docs/decisions/](docs/decisions/).

## Rules that must never be broken

- **Layers** (`apps/api`): `domain` <- `application` <- `infrastructure` / `api` (the presentation package). Imports point inward only; `infrastructure` and `api` never import each other. Enforced by `uv run lint-imports`.
- **Ports** are `typing.Protocol` classes in `apps/api/src/app/application/ports/`. Keep them small; every adapter must pass its port's contract suite before it is registered.
- **Composition roots**: only `apps/api/src/app/bootstrap.py` and `apps/web/src/app/providers.tsx` name concrete classes. No DI framework. A new provider = new adapter + one registry line (`infrastructure/ai/registry.py`), no edits to existing code.
- **Env readers**: only `infrastructure/config/settings.py` (API) and `src/lib/config.ts` (web) read the environment. Variable names are in `.env.example`; a new variable is added there in the same commit.
- **Network**: `client.ts` is the only `fetch` caller. Components depend on service interfaces from context, never on the client.
- **Generated files** (`schema.d.ts`, lockfiles) are never edited by hand.
- **Contract change in one commit**: update the Pydantic model, run `npm run gen:api`, fix frontend types, commit together.
- **PostgreSQL only**, including tests. No SQLite. A table = an ORM model in `infrastructure/db/models/` plus one Alembic revision (`--autogenerate`, then reviewed by hand).
- **Transactions**: repositories never commit. `Container.request_scope()` is the unit of work (one session, commit or rollback in one place); see "Unit of work" in `docs/architecture.md`.
- **Auth seam**: routes get the caller only through `CurrentUserId` (`api/security.py`); API tests set it with `app.dependency_overrides[get_current_user_id]`. No other module touches JWTs, and no response, log line or error ever carries a password, a hash or a token.
- **Rate limiting**: a new router outside `/health` opts in with `Depends(limit_requests)` (credential routes: `limit_auth_attempts`) and `responses={**TOO_MANY_REQUESTS}` from `api/rate_limit.py`; see "Rate limiting" in `docs/architecture.md`. API tests swap `Container.rate_limiting.limiter`, never Redis.
- **Versions**: latest stable, verified from the official source at install time. Let `uv add` / `npm install` resolve; never type versions from memory.
- **TDD order**: write the test, see it fail, implement, run all checks, commit (`chore(scope): ...`, conventional commits). Never weaken or delete a test to get green.
- **No AI attribution**: commits, PR titles and PR descriptions never carry an AI or agent attribution (no `Co-Authored-By: Claude ...` trailer, no "Generated with ..." line).
- Do not add dependencies, services or top-level folders without asking. Do not touch `.claude/skills/`. Nothing may reference anything outside the repo root.
- If the same error repeats twice, or something is unclear: stop and report instead of guessing.

## Commands

| Command | Where | What |
| --- | --- | --- |
| `make up` / `make down` | root | Start / stop all five services with docker compose |
| `make test` | root | Both test suites with coverage |
| `make test-integration` | root | API integration tests (`pytest -m integration`) against the running compose stack |
| `pre-commit run --all-files` | root | ruff, ruff-format, lint-imports, web lint, web typecheck |
| `make lint` | root | ruff, ruff format, mypy, lint-imports, web lint, `tsc --noEmit` |
| `uv run pytest --cov` | `apps/api` | API tests |
| `uv run lint-imports` | `apps/api` | Layer import contracts |
| `npm run test` | `apps/web` | Web tests |
| `npm run gen:api` | `apps/web` | Regenerate `schema.d.ts` from the API's OpenAPI schema |

## Repo map

- `apps/api/`: FastAPI service and Celery worker (`src/app/`: `domain`, `application`, `infrastructure`, `api`, `bootstrap.py`, `main.py`).
- `apps/web/`: Next.js frontend (`src/app/providers.tsx` is the composition root). Before using a Next.js API, read the version-matched docs in `apps/web/node_modules/next/dist/docs/`.
- `docs/`: `PRD.md`, `architecture.md`, `ai-usage.md`, `decisions/` (ADRs).
- Root: `docker-compose.yml`, `.pre-commit-config.yaml`, `Makefile`, `.env.example`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
