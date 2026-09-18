# ADR 0002: Ports and adapters with hand-wired composition roots

- Status: Accepted
- Date: 2026-09-18

## Context

The exercise is judged first on Clean Architecture: separation of concerns and independence of components.
Later phases add task CRUD, JWT auth, pagination, filtering, rate limiting, Celery background processing and AI features, each of which brings an external dependency (PostgreSQL, Redis, a broker, a model provider).
Those dependencies must be replaceable in tests and extensible without editing working code, and the rule must be checkable by a machine, not just described.

## Decision

Backend (`apps/api`):

- Layers `domain`, `application`, `infrastructure`, `presentation`, with dependencies pointing inward only.
- Ports are small `typing.Protocol` classes in `application/ports/` (`HealthCheck`, `JobQueue`, `LanguageModel`). Use cases depend on ports, never on adapters.
- Adapters live in `infrastructure` and conform structurally; they do not inherit from the port.
- `bootstrap.py` is the only composition root. It holds the registries (for example `AI__PROVIDER` value -> factory), so a new provider is a new adapter plus one registry line.
- `settings.py` is the only module that reads the environment.
- No DI framework or container library. Wiring is plain constructor calls.
- The dependency rule is enforced by import-linter contracts; substitutability is enforced by one contract test suite per port that every adapter must pass before it is registered.

Frontend (`apps/web`):

- Components depend on service interfaces obtained from React context.
- `providers.tsx` is the only composition root, `client.ts` the only `fetch` caller, `config.ts` the only `process.env` reader.
- Response types come from the generated `schema.d.ts`, never from hand-written duplicates.

Details and diagrams: [architecture.md](../architecture.md).

## Consequences

Positive:

- Use cases are unit-tested with in-memory fakes: fast, deterministic, no containers.
- Adding a provider or backend touches no existing module (open/closed), and the contract suite proves it behaves like its siblings (Liskov).
- Architecture violations fail `make lint` instead of surviving until review.
- Both composition roots are short, explicit files a reviewer can read top to bottom.

Negative:

- More files and some indirection for what is, in this setup, only a health endpoint. The structure pays off from the first real feature.
- Hand wiring grows with the app. If `bootstrap.py` becomes hard to read it is split into builder functions, still without a container.
- `Protocol` conformance is structural, so a missing method is caught by `mypy` and the contract suite rather than at class definition time.

## Alternatives considered

- **Framework-centric layout (routes call the ORM directly).** Rejected: fastest to start, but business rules become untestable without a database and every external service leaks into the routes.
- **Abstract base classes for ports.** Rejected: forces adapters to import and inherit from the application layer's classes; `Protocol` keeps adapters independent and fakes trivial.
- **A DI container (dependency-injector, punq, FastAPI `Depends` as the wiring mechanism everywhere).** Rejected: hides the object graph behind configuration and adds a dependency; explicit constructor calls in one file are easier to review. FastAPI `Depends` may appear inside `presentation` only, to hand routes what `bootstrap.py` built.
- **Frontend components calling `fetch` directly or through a data-fetching hook library.** Rejected: couples components to the network and forces tests to mock HTTP; a service interface is injected instead.
