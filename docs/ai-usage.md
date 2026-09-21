# AI usage

This assessment grew through conversation, implementation and correction, not a single
prompt followed by an unchecked code dump. I used GenAI to help turn a deliberately
small scaffold into the application in this repository. I remained responsible for
what to build, which architectural choices to accept and whether the interface met
the intended behavior. This account separates **assistance during development** from
**AI drafting inside the product**, and separates remembered instructions from retained
evidence.

## Tools used

**Preferred coding tool for the proposed scaffold: Claude Code.** Give it the prompt
below alongside this repository's `CLAUDE.md`/`AGENTS.md` and architecture. This names
a usable tool choice for the submission, not a claim that every historical change
came from that tool or a particular model/version.

GenAI-assisted implementation used bounded task instructions, repository inspection,
code edits and test feedback. Retained implementation briefs and validation reports
support the examples below; they are not a complete conversation archive. The precise
coding model/version and first unedited model drafts are not retained in the evidence
used for this account, so neither is asserted here. The samples are **accepted resulting
repository code**, not claimed verbatim first responses.

**Firstmate was my development companion.** It coordinated bounded workers with
specific instructions, brought review findings and test results back into the work,
and kept source delivery tied to the evidence for the changed code. That coordination
helped keep implementation, validation and unresolved issues visible across iterations;
it did not replace my product direction, interface feedback, scope/architecture
acceptance or final decisions. Firstmate is development tooling, not a runtime
dependency of Ballast Tasks, and coordination is not a guarantee of correctness.

The practical loop was to define a small change and its constraints, inspect existing
code, ask for a testable implementation, examine failures and review findings, then
accept or correct the result. Tests and source inspection were the checks on the
assistant's answer, not supporting decoration added after declaring it done. The
examples below include corrections and limits precisely because an apparently
plausible answer was not enough.

The workflow used pytest, Vitest/MSW, Playwright, native Chrome checks, Ruff, mypy,
TypeScript, import-linter and pre-commit. The repository's
[working rules](../AGENTS.md) require tests-first changes and inward dependencies;
that policy alone is not proof that every change followed TDD.
The application's configurable language-model adapters are a separate feature, not
identification of the coding assistant: see [ADR 0003](decisions/0003-llm-adapters-over-http.md).

## Prompts used

### Starting point: recalled scaffold request

The following is an excerpt from **my recalled starting prompt, reconstructed by me**;
it is not an independently preserved verbatim conversation transcript:

> I am aiming to have a mono repo containing:
>
> the frontend application, which is going to be a Next.js app
> the backend application, which is going to be a FastAPI application
> probably some shared documentation in that repo that is going to work as some kind of PRD, definitions, and changes that are going to be added to the product that I'm going to be creating for this Claude Design
>
> Help me to build this thing. Please give me the instructions so I can start working on that front.

**Condensed history, not a quotation:** I wanted clean configuration, dependency
inversion and replaceable database/AI components. The initial assignment was setup
only: a Next.js/FastAPI monorepo, PostgreSQL, Redis, Celery, health/readiness checks,
Docker Compose, tests and linting. Most documentation was initially headings only.
Work was staged—implement, check, commit and report—with tests first on the backend,
explicit checkpoints, and a stop rather than guessing after repeated errors. Auth,
tasks and other product features were outside that first stage; later accepted work
intentionally added them. Historical version choices were starting assumptions, not
today's installation instructions; use the locked dependencies and
[current setup](../README.md#quick-start).

My starting wording contrasted “dependency inversion” with “dependency injection”.
The implemented distinction is more precise: use cases depend on inward-facing
`Protocol` ports, and explicit constructor calls in the composition root inject their
adapters. We avoided a DI **framework**, not dependency injection itself. That made
the original replacement goal concrete and testable; see
[ADR 0002](decisions/0002-ports-and-adapters.md).

### A usable prompt for the expanded API

**Proposed API scaffold prompt (written for this submission, not a historical
invocation):**

> Build a FastAPI task-management API using PostgreSQL and Clean Architecture:
> domain rules, application use cases with small Protocol ports, infrastructure
> adapters and one composition root. Support JWT registration/login, authenticated
> task CRUD, assignment and completion, with status/due-date filtering and pagination.
> Preserve the browser-session/CSRF and bearer contracts in ADR 0009; never store
> readable browser credentials. Validate inputs and return safe errors. Use migrations, a request-scoped unit of
> work, Redis-backed rate limiting and Celery background processing. Read the existing
> architecture and decisions before editing. Write failing domain, contract and route
> tests first; exercise real PostgreSQL/Redis integrations, document setup and Swagger,
> and run tests, coverage, type checks and import-boundary checks. Do not use real
> external keys or claim tests passed unless they ran.

This proposed prompt did **not** produce the samples below. It describes the later,
expanded API scope, not the initial no-features scaffold.

### Retained instructions for one bounded feature

Historical evidence is narrower: these are exact, representative excerpts from retained implementation instructions,
not newly reconstructed prompts or the entire development conversation:

> Implement only the queued asynchronous step-generation API.

> Validate model output as bounded nonempty step titles consistent with the merged step domain/bulk contract. Malformed/empty/oversized output and provider failure must yield a useful failed job, not partially created task steps. Do not trust free-form model text as executable input. Read task data using short request scopes; do not hold a database transaction while waiting for a model response.

> Keep generated proposals separate from stored steps. Human acceptance uses the existing atomic bulk-step use case/endpoint and its 100-step ceiling; do not invent another acceptance or activity mechanism.

Summary, **not a quotation**: these instructions constrained implementation to the
existing Celery/Redis infrastructure and provider-neutral ports, authenticated
request/poll routes, bounded safe failure responses and offline tests. They did not
ask the assistant to invent a new job framework or automatically accept generated steps.
The implemented scope is [FR-24–26](PRD.md).

## GenAI inside the product

Development assistance and the shipped model integration solve different problems.
In the app, a person requests draft step titles for a task. The API queues work,
Celery reads task context without keeping a transaction open during the model wait,
and polling returns validated proposals. Only explicit acceptance writes steps.
This puts the model on the suggestion side of the boundary, not in charge of task data.

The current default is **OpenRouter**, with the exact alias
`~openai/gpt-luna-latest` and reasoning enabled. The provider-neutral `LanguageModel`
port returns only final content; opaque reasoning details are not stored, logged or
reused. Gemini is an alternative. Offline use explicitly selects **both**
`AI__PROVIDER=fake` and `AI__MODEL=fake-1`; missing or rejected real-provider credentials
never trigger a silent fake fallback. See [AI configuration](../apps/api/README.md#ai-configuration)
and [ADR 0003](decisions/0003-llm-adapters-over-http.md).

Using plain HTTP rather than a vendor SDK keeps the small port, timeout policy and
error mapping under our control. The tradeoff is that we own those request/response
shapes: a stub test can pass while a vendor API changes. Likewise, valid JSON is not
the same as useful advice. Human acceptance and bounded validation remain necessary.

## Representative output

Accepted resulting code at baseline `80c2c29aa71a8f5ac54cdbd0ca6885e9c8e52573`:
[`generate_step_titles.py`](../apps/api/src/app/application/use_cases/generate_step_titles.py)
(exact excerpt; surrounding code omitted):

```python
def parse_titles(text: str) -> tuple[str, ...]:
    """Never execute or repair free-form output. The size bound is on raw model output."""
    if len(text) > MAX_COMPLETION_CHARACTERS:
        raise ValueError("completion too large")
    return valid_titles(json.loads(text))
```

The called validator enforces 1–20 strings, domain title rules and UTF-8 encodability.
The model wait has a deadline; provider exceptions become safe error categories.
Generation returns proposals, not database writes. Acceptance separately uses
[`AddSteps.execute`](../apps/api/src/app/application/use_cases/add_steps.py)
(exact excerpt):

```python
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        first_free = len(await self._steps.list_for_task(task_id))
        check_room_for(first_free, adding=len(titles))
```

The rest of that method constructs and validates every step before storing any,
then records activity within the request unit of work. This illustrates accepted
separation of model output, domain validation and transactional persistence, not
proof that the first generated draft was correct.

## How suggestions were validated

Retained consolidated validation at `f5f50b950a785d3acfac5ff246229285662d6c40`
reported **2,600 API tests, 375 integration tests, 670 web tests and 106 visual tests**
passing, plus lint, pre-commit and an HTTP-mode production build. API coverage was
90.95%; web statement coverage was 96.18%. Baseline `80c2c29` has the same source
tree as that validated head. These are historical results, not a claim of newly
running those journeys for this document or of remote CI; no CI workflow is claimed.

A later source-bound checkpoint is `7c43cbfc1161f958e0972ccfc4465293d94dbf6a`,
whose tree matches landed `2f4397aa0e7bed4e859302beb9de4835ffb3b694`. It reported
**2,625 API tests (91.05% coverage), 380 integration tests and 804 web tests** passing,
plus lint/types/import checks, pre-commit and an HTTP-mode production build. These
final suites used fake providers or mock transports with no real credentials. This
documentation-only follow-up reuses those results for unchanged executable inputs;
it does not relabel them as fresh test runs or a new browser campaign. Remote CI was
not run and no configured CI checks are claimed.

**Current limitation:** later session/routing work exposed an unresolved React185
(maximum update depth) failure in Next development-mode browser testing. Five bounded
production attempts passed, but those attempts neither resolve the development failure
nor establish production capacity or an all-browser-tests-green result. The commands
below are a reproduction guide, not a statement that every suite currently passes.

Evidence types matter:

- Unit/contract tests inject ports; web HTTP-adapter tests use MSW. They test specified
  behavior, not a live vendor or a real browser deployment.
- [Served generation integration](../apps/api/tests/integration/test_step_generation_served.py)
  exercises real HTTP, PostgreSQL, Redis and a consuming worker with a deterministic
  fake model. [File integration](../apps/api/tests/integration/test_file_attachments.py)
  covers real storage/transaction behavior.
- Retained native browser acceptance covered sign-in, persisted edits, steps,
  attachments and explicit proposal acceptance. A subsequent main-equivalent
  deployment smoke confirmed a saved fixture after a fresh sign-in, then deleted it.
  Existing screenshots/journeys retain their original tested-head labels.
- Those historical browser/integration results used **fake AI and SSO providers**.
  Separately, one bounded real OpenRouter generation at source `1323d10304622360828cc295065e967eb0daf12f`
  traversed API → Redis → Linux prefork Celery → the exact configured alias, then
  polling and explicit acceptance. No steps or activity changed before acceptance.
  The later provider delivery changed only a fake-provider docstring in API production
  source. This supports one real queued success, not a live-model evaluation campaign,
  a forced worker-timeout test, capacity, or continued provider availability. Its
  native browser attempt stopped on stale-reference tooling failures; HTTP success
  is not a native-browser pass. No real Google SSO flow is claimed.
- One inherited httpx cookie deprecation warning and two jsdom navigation notices were
  retained in validation history. Earlier native console/Chrome Issues checks were
  clean within their own journeys, not a blanket warning-free claim for later source.
  A bounded vendor check found no verified applicable fix for the development React185
  path; successful production attempts do not erase that failure.

Reproduce the repository checks after the [setup](../README.md#tests-and-linters),
using a dedicated test stack, never a retained demo database:

```sh
make test
make lint
pre-commit run --all-files
make test-integration
(cd apps/web && npm run test:visual)
(cd apps/web && npm run build)
```

Visual design comparisons additionally need the design snapshot via `BT_DESIGN_DIR`;
without it those comparisons skip. See the [web guide](../apps/web/README.md) for
isolated visual ports and real-HTTP test configuration, and the
[testing strategy](architecture.md#testing-strategy) for opt-in live-provider tests.

## Corrections and improvements made

- **Unicode output:** JSON decoding accepts lone surrogate escapes which cannot be
  represented by HTTP/PostgreSQL. A retained red/green regression led to explicit
  UTF-8 encoding validation, rejecting the whole invalid proposal batch rather than
  silently repairing it. See [generation tests](../apps/api/tests/unit/test_generate_step_titles.py).
- **Silent worker failures:** fixed diagnostic events with allowlisted categories
  replaced an unobservable failure path, without exposing exception text, provider
  output or secrets. Retained replay of the earlier implementation failed three
  diagnostic tests; the corrected version passed them. See
  [worker configuration tests](../apps/api/tests/config/test_generation_worker_app.py).
- **Keyboard focus:** native testing found focus falling to BODY when a board Retry
  disappeared after authoritative query settlement. A failing served regression and
  a fix were followed by native two-client confirmation of focus on the moved card.
  See [board tests](../apps/web/src/features/tasks/board/BoardView.test.tsx).
- **Provider configuration:** the real-provider default was checked against the exact
  model alias, with failing default/startup and reasoning-request tests before the
  change. The API base URL must be the provider root, not a completion endpoint;
  type-valid configuration alone cannot prove that an endpoint is usable. Offline
  tests remain explicitly fake/keyless. See
  [default tests](../apps/api/tests/config/test_ai_default.py) and
  [adapter tests](../apps/api/tests/unit/test_openrouter_language_model.py).
- **Test ordering:** a component test failed because its intended passive-effect
  ordering had not been established. The fixture was changed to await the actual
  loaded-effect witness, keeping both ordering assertions and the final focus checks.
  That correction is test evidence, not a claim to fix every browser focus issue.
  See [detail tests](../apps/web/src/features/tasks/detail/TaskDetail.test.tsx).
- **Validation setup was fallible too:** an HTTP run failed when its worker was absent;
  a recovered owned worker and a later scheduled run passed. Credential-limit failures
  were retained and groups spaced by the real limit window, not “fixed” by weakening
  authentication limits. A production-mode seed test also failed with an inherited
  HTTP CORS origin; valid synthetic HTTPS CORS corrected the test environment without
  weakening its assertion. Those failed attempts are not included as passes.

## Edge cases, authentication and validation handling

[Generation unit tests](../apps/api/tests/unit/test_generate_step_titles.py) cover
malformed, empty and oversized output, Unicode, provider errors and timeouts;
[route tests](../apps/api/tests/api/test_step_generations.py) cover authentication,
rate limits and task/job association. Unknown, expired, wrong-task and deleted-task
handles are not successful empty results. Generation does not add steps; explicit
acceptance is atomic and subject to the 100-step ceiling.

[Authentication tests](../apps/api/tests/api/test_auth.py) exercise the JWT boundary;
the product is deliberately a **shared workspace**, not per-user task isolation.
Browser sessions now use server-set HttpOnly cookies, verified against the active
user on reload/new tab, with the existing JWT expiry and no refresh/sliding renewal.
Cookie-authenticated writes require an exact allowed Origin and CSRF header; bearer
clients remain supported. Logout clears the browser cookie, not copied JWTs or other
devices. See [ADR 0009](decisions/0009-browser-sessions-and-routes.md),
[browser-session route tests](../apps/api/tests/api/test_browser_session.py) and
[PostgreSQL/JWT integration tests](../apps/api/tests/integration/test_browser_session.py).
File content
sniffing, streaming size limits, rollback cleanup and their residual failure windows
are documented in [ADR 0008](decisions/0008-file-storage.md) and tested in
[file route tests](../apps/api/tests/api/test_file_attachments.py). These are concrete
checks, not a claim of a complete security audit or malware scanning.

## Performance and idiomatic-quality assessment

The design uses database filtering/pagination, page-wide tallies instead of a count
query per task, short transactions outside model waits, and injected clocks for
repeatable time rules. Import-linter checks dependency direction; small Protocol
ports, shared contract suites and a composition root make adapters replaceable.
Ruff/mypy/TypeScript and tests provide stronger evidence than generated code looking
plausible. See [architecture](architecture.md) and
[query tests](../apps/api/tests/unit/test_task_queries.py).

A retained native bounded editing probe recorded **14 real title saves in 40.16 s,
72 API requests**, no 429 and no blank sidebar counts in a 52-row scope with a
50-row page. This is a responsiveness/request-budget observation, **not** a load
benchmark or a measured before/after speedup. There is no demonstrated production
capacity, latency percentile or live-model quality benchmark here.

Important limits remain: database and domain urgency rules are implemented twice
and need parity tests; file storage cannot make disk and SQL perfectly atomic;
model output can be syntactically valid yet unhelpful; and shared request throttling
is **not** a separate generation spending cap. Human proposal acceptance, explicit
failure contracts and documented limitations matter more than treating assistant
suggestions or coverage percentages as guarantees.

## What I would carry forward

The useful part of this process was not asking for more code at once. It was making
the next question small enough to check: what may this layer know, what happens when
a provider fails, what persists after reload, and who decides that a suggestion
becomes task data? Firstmate helped coordinate those questions and their evidence;
the answers still needed human acceptance and executable checks.

The strongest lesson is to preserve the difference between intent, output and proof.
A prompt states what I wanted. Accepted source shows what we built. A passing test
supports a particular behavior on particular inputs—not the whole product, every
browser or every future provider response. Keeping the original failures and known
limits beside the successes makes this account more useful than calling the project
finished because the code and documentation exist.
