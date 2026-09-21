# ADR 0003: LLM adapters over plain HTTP, with a free health check and typed failures

- Status: Accepted
- Date: 2026-09-18

## Context

The AI features need a real model, and the provider must be replaceable by configuration alone. Initially `fake` was the offline default, with OpenRouter recommended and Google's Gemini API the alternative. The 2026-09-21 default update below makes OpenRouter the normal provider while keeping all ordinary tests keyless.
The port already existed (`LanguageModel`: `provider`, `model`, `generate`, `check`), with a registry and a contract suite ([ADR 0002](0002-ports-and-adapters.md)).
Three questions were open: how an adapter talks to its provider, what `check()` may cost, and what the application sees when a provider fails.

## Decision

### Plain HTTP on `httpx`, no vendor SDK

Each adapter is one module under `infrastructure/ai/` that calls the provider's documented HTTP API through a shared `httpx.AsyncClient`.

- The port needs one request per method. An SDK would bring its own client, retry policy, exception tree and transitive dependencies for that.
- With the transport in our hands, the contract suite and every failure case run against `httpx.MockTransport` with bodies copied from the official references: offline, deterministic, no key.
- The client's lifetime is explicit: `build_container` creates it with `AI__TIMEOUT_SECONDS`, the adapter borrows it, `Container.aclose` closes it.
- `AI__TIMEOUT_SECONDS` is a total deadline for one generation. `httpx` bounds each phase (connect, write, every read) separately, so a response that trickles in could outlive it; `send` therefore wraps the whole exchange, the connection retry and the body included, in `asyncio.timeout` and reports its expiry as `LanguageModelTimeoutError`. The per-phase timeouts are the same value, so none is larger than the total.
- `httpx` moved from the dev group to the runtime dependencies (it was already locked; the production image installs without dev packages). No package was added.

The APIs were read at implementation time, not recalled, and two findings changed the code:

- Gemini's documentation now leads with the Interactions API, which is in beta with announced breaking changes; the same documentation recommends `generateContent` for stable deployments. The adapter uses `generateContent`.
- Gemini answers a rejected key with `400 INVALID_ARGUMENT`, not `401`; only `error.details[].reason == "API_KEY_INVALID"` tells it from a bad request. This was observed with a dummy key against the models endpoint. The adapter reads that field.

### `check()` must be free

`GET /health/ready` calls `check()` on every request, and the page polls it. A check that generated text would turn monitoring into spend and into rate-limit pressure. Each adapter therefore calls a metadata endpoint that produces no generation:

- OpenRouter: `GET /key`. The models listing is public and answers `200` to any key, so it would report a broken configuration as healthy. The reference does not state a price for `/key`; it returns key metadata and generates nothing.
- Gemini: `GET /models/{id}`, which proves the key and the model id in one call.

`check()` has 2 seconds in total and returns `False` on any failure; it never raises.

Free is not enough: `GET /health/ready` is public and unauthenticated, and each `check()` is an outbound call carrying the API key, so anyone could drive rate-limit pressure on the key. `LanguageModelHealthCheck` therefore keeps the last result in memory for `AI__CHECK_CACHE_SECONDS` (default 30, `0` turns it off) and serialises concurrent checks, so the provider is asked at most once per window however often readiness is hit. A failure is cached for the same window: a recovered provider shows as `failed` for up to 30 seconds, which is the price of not letting a failing provider be hammered. The clock is injected, so the tests do not sleep.

### Failures are typed at the port

`generate` raises only `LanguageModelError` subclasses, defined next to the port: unavailable, rate limited, authentication failed, invalid response, timeout. The mapping lives in `infrastructure/ai/http.py`:

| Provider signal | Error |
| --- | --- |
| `401`; `403` (for OpenRouter only without moderation or guardrail metadata); Gemini `400` with `API_KEY_INVALID` | `LanguageModelAuthenticationError` |
| `429` | `LanguageModelRateLimitedError` |
| `408`, `504`, `524`; any `httpx` timeout | `LanguageModelTimeoutError` |
| `402` (OpenRouter: out of credits), `5xx`; connection and other transport errors | `LanguageModelUnavailableError` |
| Any other status; a body that is not a JSON object; no, empty or blank completion; a blocked prompt (Gemini: `200` with no candidates, only `promptFeedback`; OpenRouter: `403` whose `error.metadata` carries `reasons`, `flagged_input` or `patterns`) | `LanguageModelInvalidResponseError` |

OpenRouter documents that an error can arrive with HTTP `200` and the status in `error.code`; the adapter maps that code through the same table.

The same event gets the same category on every provider. OpenRouter documents `403` on inference as insufficient permissions, a guardrail block or a moderation flag, so the status alone would label a refused prompt as a refused key. The adapter reads `error.metadata` (in a `403` body or in a `200` body with `error.code: 403`): moderation fields (`reasons`, `flagged_input`) or guardrail fields (`patterns`) make it `LanguageModelInvalidResponseError`, as Gemini's blocked prompt already was; a bare `403` stays an authentication failure. The contract suite holds one blocked-prompt case per provider and asserts the same error type from all of them.

Which providers need `AI__API_KEY` is not a settings rule. The `_over_http` factory in the registry raises a `ConfigurationError` naming the variable, and `build_container` runs it at startup, so a missing key still stops the process before the first request while a keyless provider stays one registry line with no edit to `settings.py`.

One retry, and only after `httpx.ConnectError`: the request never reached the provider, so it cannot be billed twice. A read timeout is not retried, because the generation may have completed.

An error message carries a status code or a fixed phrase, never a header, a URL query or a response body, so a provider that echoed the key could not leak it. Gemini gets the key in the `x-goog-api-key` header rather than the documented `?key=` query, which would put it in every logged URL.

### Default update (2026-09-21)

Normal settings and `.env.example` now select OpenRouter with the exact requested
`~openai/gpt-luna-latest` identifier, including its leading `~`. The official public
`GET /models` and authenticated `GET /models/user` listings identified it as a model
alias targeting `openai/gpt-5.6-luna`, not an `@preset/...` workspace preset. An isolated
API → Redis → prefork Celery → OpenRouter job succeeded with that exact alias, followed
by polling and explicit acceptance; this is account-specific evidence, not a promise
of continued availability. The human model-page URL returned HTTP 403 to the validation
client; the API metadata and actual generation, not that page, establish support.

The adapter adds only `reasoning: {enabled: true}`. Its single-prompt port still returns
final message content only. Opaque `reasoning_details` are not task content and are not
logged, persisted or reused between independent requests. No multi-turn feature is
introduced. A separate continuation must preserve those details unmodified and send
authentication on both calls. Reasoning tokens count against output budgets and billing.

A nonblank key is required at normal startup; rejection fails health/generation rather
than falling back. Explicit offline configuration sets `AI__PROVIDER=fake` **and**
`AI__MODEL=fake-1`. Ordinary test fixtures select that mode or HTTP stubs, and integration
fixtures discard inherited AI credentials. Gemini remains available unchanged. The API
base URL is a root (`https://openrouter.ai/api/v1`), never a model page or completion URL.

Official references: [models](https://openrouter.ai/api/v1/models),
[reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens),
[presets](https://openrouter.ai/docs/guides/features/presets).

## Consequences

Positive:

- Switching provider is an edit to `.env`. A third HTTP provider is one module, one registry line and one contract-suite line.
- Use cases can react to a category (retry later, report a configuration fault) without importing `httpx` or knowing a vendor. import-linter forbids `httpx` in `domain`, `application` and `api`.
- No test in the default or integration suites needs the network or a key.

Negative, accepted:

- We own the request and response shapes. When a provider changes its API, the stubbed tests keep passing; only the opt-in live tests (`uv run pytest -m live`) notice. They need a real key. They were not run for the original adapter change; the later default update above used one bounded real queued generation, separately from the test suite.
- Readiness reports the AI provider's state as of up to `AI__CHECK_CACHE_SECONDS` ago, not as of now. The cache is per process: each API worker asks once per window.
- The five categories are coarse: an unknown model id and a malformed body are both `LanguageModelInvalidResponseError`. The `reason` text distinguishes them for a log reader; a new category is added when a use case needs to branch on it.
- The OpenRouter `401` test fixture is the documented example body. With a key-shaped dummy, `401` was observed on both `GET /key` and `POST /chat/completions`, but the body was not inspected and no real or revoked key was available; the mapping depends only on the status.
