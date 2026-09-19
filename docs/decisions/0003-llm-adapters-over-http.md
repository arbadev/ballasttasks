# ADR 0003: LLM adapters over plain HTTP, with a free health check and typed failures

- Status: Accepted
- Date: 2026-09-18

## Context

The AI features need a real model, and the provider must be replaceable by configuration alone: OpenRouter is the recommended one, Google's Gemini API the alternative, and `fake` stays the default so the stack and every test run with no key.
The port already existed (`LanguageModel`: `provider`, `model`, `generate`, `check`), with a registry and a contract suite ([ADR 0002](0002-ports-and-adapters.md)).
Three questions were open: how an adapter talks to its provider, what `check()` may cost, and what the application sees when a provider fails.

## Decision

### Plain HTTP on `httpx`, no vendor SDK

Each adapter is one module under `infrastructure/ai/` that calls the provider's documented HTTP API through a shared `httpx.AsyncClient`.

- The port needs one request per method. An SDK would bring its own client, retry policy, exception tree and transitive dependencies for that.
- With the transport in our hands, the contract suite and every failure case run against `httpx.MockTransport` with bodies copied from the official references: offline, deterministic, no key.
- The client's lifetime is explicit: `build_container` creates it with `AI__TIMEOUT_SECONDS`, the adapter borrows it, `Container.aclose` closes it.
- `httpx` moved from the dev group to the runtime dependencies (it was already locked; the production image installs without dev packages). No package was added.

The APIs were read at implementation time, not recalled, and two findings changed the code:

- Gemini's documentation now leads with the Interactions API, which is in beta with announced breaking changes; the same documentation recommends `generateContent` for stable deployments. The adapter uses `generateContent`.
- Gemini answers a rejected key with `400 INVALID_ARGUMENT`, not `401`; only `error.details[].reason == "API_KEY_INVALID"` tells it from a bad request. This was observed with a dummy key against the models endpoint. The adapter reads that field.

### `check()` must be free

`GET /health/ready` calls `check()` on every request, and the page polls it. A check that generated text would turn monitoring into spend and into rate-limit pressure. Each adapter therefore calls a metadata endpoint that produces no generation:

- OpenRouter: `GET /key`. The models listing is public and answers `200` to any key, so it would report a broken configuration as healthy. The reference does not state a price for `/key`; it returns key metadata and generates nothing.
- Gemini: `GET /models/{id}`, which proves the key and the model id in one call.

`check()` uses a 2 second timeout and returns `False` on any failure; it never raises.

### Failures are typed at the port

`generate` raises only `LanguageModelError` subclasses, defined next to the port: unavailable, rate limited, authentication failed, invalid response, timeout. The mapping lives in `infrastructure/ai/http.py`:

| Provider signal | Error |
| --- | --- |
| `401`, `403`; Gemini `400` with `API_KEY_INVALID` | `LanguageModelAuthenticationError` |
| `429` | `LanguageModelRateLimitedError` |
| `408`, `504`, `524`; any `httpx` timeout | `LanguageModelTimeoutError` |
| `402` (OpenRouter: out of credits), `5xx`; connection and other transport errors | `LanguageModelUnavailableError` |
| Any other status; a body that is not a JSON object; no, empty or blank completion; a blocked prompt | `LanguageModelInvalidResponseError` |

OpenRouter documents that an error can arrive with HTTP `200` and the status in `error.code`; the adapter maps that code through the same table.

One retry, and only after `httpx.ConnectError`: the request never reached the provider, so it cannot be billed twice. A read timeout is not retried, because the generation may have completed.

An error message carries a status code or a fixed phrase, never a header, a URL query or a response body, so a provider that echoed the key could not leak it. Gemini gets the key in the `x-goog-api-key` header rather than the documented `?key=` query, which would put it in every logged URL.

## Consequences

Positive:

- Switching provider is an edit to `.env`. A third HTTP provider is one module, one registry line and one contract-suite line.
- Use cases can react to a category (retry later, report a configuration fault) without importing `httpx` or knowing a vendor. import-linter forbids `httpx` in `domain`, `application` and `api`.
- No test in the default or integration suites needs the network or a key.

Negative, accepted:

- We own the request and response shapes. When a provider changes its API, the stubbed tests keep passing; only the opt-in live tests (`uv run pytest -m live`) notice. They need a real key and have not been run in this change.
- Readiness makes one outbound call per request when a real provider is configured. It is bounded by the 2 second timeout; caching the result is left for when it is needed.
- The five categories are coarse: an unknown model id and a malformed body are both `LanguageModelInvalidResponseError`. The `reason` text distinguishes them for a log reader; a new category is added when a use case needs to branch on it.
- The OpenRouter `401` fixture is the documented example body. A well-formed but revoked key was not observed, since no key was available; the mapping depends only on the status.
