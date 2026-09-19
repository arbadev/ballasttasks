# ADR 0004: Rate limiting behind a port, fixed windows in Redis, failing open

- Status: Accepted
- Date: 2026-09-18

## Context

The exercise asks to "add rate limiting to prevent API abuse".
Two kinds of abuse matter for this API: guessing passwords on `POST /auth/login` (and mass account creation on `POST /auth/register`), and one client taking more than its share of everything else.
The API runs as several processes (compose today, more behind a proxy tomorrow), so a count kept in one process limits nothing: the count has to be shared, and Redis is already in the stack.
Redis is also one more thing that can be down, and a limiter must not take the API down with it.
Like every other outside dependency (ADR 0002), it has to be replaceable in tests and swappable without touching the HTTP layer.

## Decision

**A port.** `RateLimiter` (`application/ports/rate_limiter.py`) has one method: `hit(key, policy) -> RateLimitDecision`. A `RateLimitPolicy` is a name, a limit and a window in seconds; a decision is `allowed`, `limit`, `remaining`, `reset_after_seconds`. No framework type crosses it. A hit that is refused is not counted and does not extend the window, so hammering a closed window never pushes its reset back.

**Algorithm: a fixed window that opens at the key's first hit.** One small Redis hash per key holds the hit count and the window's end.

- It is O(1) in memory and in Redis commands whatever the limit is.
- Its state maps exactly onto the headers a client reads: `remaining` is a subtraction, and `reset` is the real moment the whole budget comes back. A sliding log (one sorted-set entry per hit) or GCRA has no single such moment, so `X-RateLimit-Reset` becomes an approximation.
- Opening the window at the first hit, not on the wall-clock minute, spreads resets out instead of releasing every client at the same second.
- The known price: a client can spend one budget at the end of a window and the next at the start of the following one, up to twice the limit in a short burst. For brute-force protection what counts is the sustained rate (with the defaults, 10 attempts a minute per address, about 14,000 a day), and that holds. If the burst ever matters, a sliding-window adapter is a new class behind the same port and the same contract suite, minus the cases that pin the fixed-window reset.

**Atomicity.** Read, decide, count and set the expiry are one Lua script. Redis runs a script to completion before anything else, so concurrent requests from any number of processes cannot both take the last slot; `INCR` followed by a separate `EXPIRE` could also strand a counter with no expiry if the process died between the two. The script reads Redis's own clock (`TIME`), the one clock all processes share; tests inject a clock instead and never sleep. Every key expires at the end of its window, so abandoned keys clean themselves up.

**Three policies, two kinds of key** (the `rate_limit` settings group, defaults in `.env.example`):

| Policy | Routes | Key | Default |
| --- | --- | --- | --- |
| `auth` | `POST /auth/login`, `POST /auth/register` (one shared budget) | client IP | 10 / 60 s |
| `authenticated` | every other limited route, when the bearer token resolves to an active user | user id | 120 / 60 s |
| `anonymous` | the same routes, when it does not (the route then answers `401`) | client IP | 60 / 60 s |

- Keyed by user where there is one: a user keeps one budget across devices and addresses, and users who share an address (an office, a carrier NAT) do not spend each other's. Keyed by address only where nobody is identified yet.
- The strict check runs before the body is read, a unit of work is opened or a password is hashed; the `429` is cheap to produce.
- `GET /health` and `GET /health/ready` are exempt: probes must never be refused, and they cost almost nothing. Exempt means the route simply has no limiter dependency; nothing matches on paths.
- Redis keys are `<RATE_LIMIT__KEY_PREFIX>:<policy>:ip:<address>` or `...:user:<uuid>`; they hold no credentials and live for one window at most.

**Client address.** The peer of the TCP connection, which a client cannot choose. `X-Forwarded-For` is honoured only when `RATE_LIMIT__TRUST_PROXY=true`, and then only its last entry, the one the trusted proxy appended; anything to its left came from the client. Off by default: trusting the header from anyone would let every request claim a fresh address and a fresh budget.

**HTTP.** Over the limit is `429` with the standard `ErrorResponse` body and `Retry-After`. Every response of a limited route, errors included, carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`; `Reset` is seconds from now, like `Retry-After`, so a client needs no synchronised clock. The headers are exposed through CORS, and the `429` is declared in OpenAPI on each limited route.

**Failure mode: fail open, to a per-process count.** `FailOpenRateLimiter` wraps the Redis adapter. When Redis raises, or does not answer within 0.5 s, the request is decided by the in-memory adapter instead and the API keeps serving; never a `500`. It logs one warning when an outage starts and one info line when it ends, not a line per request. During an outage Redis is probed by one request every 5 s while the others skip it, so a blackholed Redis costs one timeout per interval, not one per request. The log line carries the error's type, never its message, which can quote a connection URL.

Failing open was chosen over failing closed because the limiter exists to keep the API available; refusing every login because a cache is down would do the attacker's work for them. The cost is that for the length of an outage the limit is per process (N processes allow N times the limit), and an attacker who can take Redis down loosens the limits. Readiness already reports Redis, so the outage is visible.

**No third-party library.** `slowapi` and `fastapi-limiter` tie the limiter to FastAPI decorators and to their own storage layer, which is exactly the coupling the port exists to avoid, and neither offers the fail-open stand-in. The Redis adapter is about 25 lines of Python and 25 of Lua.

## What this does not protect against

- **Distributed attacks.** A botnet, or a password-spraying run that tries a few passwords on many accounts from many addresses, stays under every per-address limit. There is no per-account lockout: that is a different trade-off (it lets anyone lock a victim out) and was left out of scope.
- **Volumetric denial of service.** A refused request still costs a connection, a Redis round trip and a response. Flood protection belongs in front of the API (proxy, CDN, firewall).
- **Address rotation.** An attacker with an IPv6 /64 has 2^64 addresses; keys are whole addresses, not prefixes. Conversely, many legitimate users behind one address share the `auth` and `anonymous` budgets.
- **A misconfigured proxy.** `TRUST_PROXY=true` without a proxy that really sets the header lets clients forge their address; more than one proxy hop makes the last entry the inner proxy, not the client. Only the single-hop case is handled.
- **Expensive requests.** Every request costs one unit, whatever work it triggers. There are no per-route weights, per-plan quotas, allow/deny lists or admin overrides (out of scope).
- **Swagger UI and `/openapi.json`.** FastAPI serves them outside the routers; they are static and cheap, and are not limited.

## Consequences

Positive:

- The HTTP layer and the tests never see Redis: API tests swap in the in-memory adapter with a clock they move, and the default suite needs no service.
- Both adapters and the fail-open wrapper pass one contract suite (`tests/contract/test_rate_limiter_contract.py`); the Redis run, a 100-hit race over ten connections and a 40-login burst through the whole app are under the `integration` marker.
- A new policy is one settings field and one line in `bootstrap.py`; a new route opts in with one dependency.

Negative:

- Every limited request pays one Redis round trip, and an authenticated one resolves its user before it is counted (the limiter cannot key by user otherwise), so a flood of valid-token requests still reaches the users table.
- The fixed window's 2x burst, and the looser per-process limit during a Redis outage, described above.
- Two sources of time exist (Redis in production, an injected clock in tests); the integration suite covers the Redis one with a real one-second window.

## Alternatives considered

- **Sliding-window log or GCRA.** Smoother, no boundary burst. Rejected for now: more state or less obvious arithmetic, and no exact reset to report, for a benefit this API does not need yet. The port makes it a later, local change.
- **Fail closed.** Rejected: turns a cache outage into a full outage of login and of every other route.
- **Fail open with no limit at all during an outage.** Rejected: the in-memory adapter already exists for the tests, and a per-process count still stops a simple brute force while Redis is away.
- **A middleware that matches on paths.** Rejected: it would duplicate the routing table and could not key by user without re-implementing authentication. A dependency gets the caller from the existing auth seam; a small ASGI middleware is kept only to copy the decision onto error responses, which a dependency cannot reach.
- **Limiting in the reverse proxy only.** Complementary, not a substitute: a proxy does not know the user id, and the exercise asks for it in the API.
