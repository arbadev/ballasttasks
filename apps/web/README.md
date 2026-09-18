# apps/web

Next.js (App Router, TypeScript, Tailwind) frontend. For now the home page renders a single
`StatusCard` showing API, Database, Redis and AI (provider and model) status.

## Architecture

Dependencies point inwards; components never touch HTTP or the environment.

| Path | Responsibility |
| --- | --- |
| `src/lib/config.ts` | The only module that reads `process.env`. Validates on load. |
| `src/lib/api/client.ts` | The only module that calls `fetch`. Throws a typed `ApiError`. |
| `src/lib/api/schema.d.ts` | Generated from the API's OpenAPI document. Never edited by hand. |
| `src/features/health/service.ts` | `HealthService` interface, `HttpHealthService`, and the view model. |
| `src/features/health/StatusCard.tsx` | UI. Depends on `HealthService` only. |
| `src/app/providers.tsx` | Composition root: the only place `HttpHealthService` is constructed. |

The two "only module" rules are enforced by ESLint (`eslint.config.mjs`), not by convention.
Readiness checks are a list keyed by name, so a new backend check appears on the page with no
frontend change; unknown names fall back to the raw name as their label.

## Commands

```sh
npm run dev                  # needs NEXT_PUBLIC_API_URL
npm run test -- --coverage   # vitest + msw; fails under 80% coverage
npm run lint
npm run typecheck
npm run build                # needs NEXT_PUBLIC_API_URL (inlined at build time)
npm run gen:api              # regenerate schema.d.ts from http://localhost:8000/openapi.json
```

Any change to an API response model is followed by `npm run gen:api` in the same commit.

## Docker

`NEXT_PUBLIC_API_URL` is inlined into the client bundle, so it is a build argument:

```sh
docker build --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t web .
```

## Version notes

Dependencies are resolved to latest stable at install time. Two sit below the registry's
latest because required tooling does not accept it yet: `eslint` stays on 9.x
(`eslint-config-next` bundles plugins whose peer range ends at `^9`) and `typescript` on 5.x
(`openapi-typescript` and `typescript-eslint` exclude 7.x). Revisit when those peers move.
