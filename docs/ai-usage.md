# AI usage

I wanted to turn a task-management design into a working product: somewhere to
organise projects, identify the next piece of work and carry a task through to
completion. My first request was deliberately smaller than that goal. I asked for
a Next.js/FastAPI monorepo with a runnable foundation, clean configuration and
replaceable components. Product features would follow once that foundation could
be checked.

**Firstmate is my development companion and coordination point.** Together we worked
through a product-definition loop: clarify the behavior, constrain the implementation,
review the result, exercise it and use the findings to refine the next change. I
supplied product direction and interface feedback and accepted scope and architecture
decisions. Firstmate contributed suggestions, coordinated bounded workers and brought
implementation, review and test evidence back together. I did not hand-design every
detail or personally execute every check; my responsibility was to make informed
acceptance decisions rather than treat generated code as the finished product.

That loop led to the delivered **Ballast Tasks**: an authenticated shared workspace
with projects, list and board views, assignment, priorities, attention signals,
steps, comments, activity, attachments and AI-assisted step drafting. The final
Docker application was exercised on representative persisted workflows, including
title editing, session restoration, navigation and a real queued generation with
explicit acceptance. This is a completed bounded task-manager delivery, with known
follow-ups—not a claim that every edge case is solved.

## From product questions to architectural decisions

The architecture became useful when it answered concrete product questions. The
following groups explain that reasoning; they are not a claim that I anticipated
every requirement at the start. The [PRD](PRD.md) records implemented behavior, and
the [architecture](architecture.md) and ADRs record the constraints we accepted.

### Keep the API and interface in agreement

I wanted one deliverable that could be cloned and run, with the design and API
evolving together. We kept the docs, FastAPI backend, Next.js frontend and Compose
setup in one repository. The API owns the HTTP contract: Pydantic models produce
OpenAPI, which generates the frontend types. A contract change and its frontend fix
land together instead of relying on two hand-maintained definitions.

The tradeoff is two toolchains and coordinated releases, without an additional
monorepo build framework. At this size, explicit `make` commands are enough. See
[ADR 0001](decisions/0001-monorepo.md) and the
[contract flow](architecture.md#http-contract-flow).

### Make replacement a boundary, not a promise

My initial request for replaceable database and AI components needed a precise
implementation rule. We put small `Protocol` ports in the application layer and
kept framework and provider adapters outside it. `bootstrap.py` and `providers.tsx`
choose and inject implementations; components receive services rather than calling
the network themselves.

This is **dependency inversion using explicit dependency injection**. We avoided a
DI framework, not injection. The cost is more interfaces, files and hand wiring;
the benefit is that a use case can be tested without its external services and an
adapter can be checked against a shared contract. Import-linter checks the dependency
direction. PostgreSQL is still the only supported database: an interface is not
proof that another database already works. See [ADR 0002](decisions/0002-ports-and-adapters.md)
and the [adapter contracts](architecture.md#ports).

### Translate the design into durable task rules

The design introduced projects, stable task keys, a Testing column and urgency-based
attention. Those are product rules, not just new fields on a screen. A task keeps
its key when moved to another project; a transactional counter on the project row
allocates keys safely under concurrent creation. That serialises creation within
one project, in exchange for rollback-safe allocation.

Urgency created a different tension: it depends on today's date, but filtering,
sorting and pagination belong in SQL. We accepted a domain implementation and a SQL
implementation, both checked against literal design cases with an injected date.
That preserves server-side paging but creates an ongoing parity-testing obligation;
“today” remains UTC for everyone. [ADR 0005](decisions/0005-task-keys-and-urgency.md)
explains the decisions and links the concurrency and urgency tests.

### Give a change and its consequences one transaction owner

Steps and activity made “save the task” insufficient: a change and its timeline entry
must succeed or fail together, including outside an HTTP route. We used PostgreSQL
through a request-scoped unit of work; repositories never commit. Use cases record
activity through `ActivityRecorder` in the same transaction. Task-row locking keeps
step positions and the 100-step limit coherent under concurrent writers.

Attachments exposed the boundary of that guarantee. SQL and a filesystem cannot
share an atomic commit, so `FileChanges` compensates new writes on rollback and
defers removal until after commit. Uploads stream between short transactions rather
than occupy a database connection while waiting for a client. This costs cleanup
logic and leaves documented crash/orphan windows. The
[unit of work](architecture.md#unit-of-work-one-transaction-per-request),
[ADR 0007](decisions/0007-steps-and-activity.md) and
[ADR 0008](decisions/0008-file-storage.md) connect those choices to rollback,
concurrency and real-storage tests.

### Treat reload and navigation as product behavior

Real browser use revealed a distinction between persisted records and a remembered
session or filter: PostgreSQL could retain the data while a reload lost the context
needed to use it. We adopted server-validated HttpOnly cookie sessions and URL-owned
filters, view and pagination. The existing workspace remains the data/draft owner;
the URL owns navigation, including Back/Forward.

The decision preserved bearer clients and the existing JWT expiry rather than adding
refresh credentials or readable browser tokens. Cookie writes require Origin and
CSRF checks; logout clears this browser's cookie, not every copied token or device.
Optional SSO stays behind its own port and single-use exchange flow, with no live
SSO claim here. See [ADR 0009](decisions/0009-browser-sessions-and-routes.md), which
supersedes the earlier memory-only browser approach in
[ADR 0006](decisions/0006-single-sign-on.md).

### Let AI propose work, not silently create it

For step drafting, I wanted help breaking down a task while keeping acceptance with
the person. We reused Celery/Redis and the provider-neutral `LanguageModel` port:
queue the request, wait outside a database transaction, validate the returned titles
and present proposals. Only the existing atomic bulk-step operation persists the
selected titles. The same domain limits apply to manual and generated steps.

Plain HTTP adapters keep timeout and error policies explicit, at the cost of owning
vendor request/response compatibility. Ephemeral proposals avoid treating Redis as
the task store. Shared request throttling limits request rates, **not model spending**;
there is no separate generation quota. [ADR 0003](decisions/0003-llm-adapters-over-http.md),
[ADR 0004](decisions/0004-rate-limiting.md) and
[queued generation](architecture.md#queued-step-generation) document these boundaries.

## Tools used

Firstmate gave me one coordination point for bounded implementation and validation
work. The practical cycle was:

1. **Define the next observable result.** For example, generating titles must leave
   the task unchanged until acceptance; reloading must restore a valid session and
   the chosen navigation state.
2. **Constrain the change.** Use existing ports and transaction ownership, specify
   non-goals, and stop on uncertainty rather than introduce an unreviewed framework.
3. **Implement and challenge the result.** Workers inspected the source, wrote code
   and tests, and returned review findings and failures—not just a completion message.
4. **Use real flows to refine acceptance.** A title save that trims a paused space
   can pass a simple persistence check yet still break typing. That finding led to
   a focused correction and natural-typing plus in-flight-response regressions.
5. **Separate source delivery from usable delivery.** Merged code and passing suites
   were followed by checks against the actual Docker application, then bounded
   acceptance with the remaining findings recorded.

The workflow used pytest, Vitest/MSW, Playwright, native Chrome checks, Ruff, mypy,
TypeScript, import-linter and pre-commit. The [working rules](../AGENTS.md) require
tests-first executable changes; documented red/green examples appear below. Firstmate
is development tooling, not a runtime dependency or a correctness guarantee.

**Claude Code is my preferred coding-tool choice for the reusable prompt below.**
That recommendation does not identify every historical coding session or model.
The app's OpenRouter/Gemini integration is a separate use of GenAI, described under
[GenAI inside the product](#genai-inside-the-product).

## Prompts used

### Starting point: a bounded scaffold

**Edited reconstruction of my recalled initial request**, not a verbatim transcript;
the dependency-inversion wording is clarified to match the distinction above:

> Set up the initial monorepo for a task-management product based on the interface
> design: Next.js and TypeScript for the frontend, FastAPI for the backend, and
> shared product requirements, architecture and decision records. This stage is
> setup only; do not implement authentication or task features yet.
>
> Establish Clean Architecture and typed configuration. Keep application behavior
> separate from database and AI adapters so those boundaries can be replaced and
> tested. Use dependency inversion with explicit injection, without a DI framework.
>
> Provide PostgreSQL, Redis and Celery, health/readiness checks, a frontend status
> page and a five-service Docker Compose setup. Add backend tests, coverage, lint,
> type checks and pre-commit tooling. Start most product documentation as headings;
> fill in the initial architecture decision and give me reproducible setup instructions.
>
> Work one task at a time: implement, check, commit and report. Write backend tests
> first, pause at the backend and Compose checkpoints, and stop rather than guess
> after repeated errors or uncertainty. Completion means the services and checks
> actually work—not that their files merely exist.

That first boundary let us validate the foundation before expanding it. Auth, task
CRUD and the later capabilities were deliberate subsequent work, not violations of
the scaffold scope. For installation today, use the locked dependencies and
[current setup](../README.md#quick-start), not historical version assumptions.

### A usable prompt for the expanded API

**Proposed API scaffold prompt (written for this submission, not a historical
invocation):**

> Build a FastAPI task-management API using PostgreSQL and Clean Architecture:
> domain rules, application use cases with small Protocol ports, infrastructure
> adapters and one composition root. Support JWT registration/login, authenticated
> task CRUD, assignment and completion, with status/due-date filtering and pagination.
> Preserve the browser-session/CSRF and bearer contracts in ADR 0009; never store
> readable browser credentials. Validate inputs and return safe errors. Use migrations,
> a request-scoped unit of work, Redis-backed rate limiting and Celery background
> processing. Read the existing
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

I treated validation as several kinds of evidence, not a single green status.
Unit and contract tests check rules and adapter behavior; HTTP integrations check
real infrastructure; browser journeys check whether the interface is usable. A
successful build or a merged branch cannot substitute for that last step.

### Source-bound suites and build

The final executable source is `d6568fe952434763919734dea5d680ec1e5ceac6`.
It differs from validated `1ffc78382eaf11d58620b2fc13ceb6263c5ee942` only in
README and assessment prose. The retained results for those executable inputs are:

| Evidence | Result and scope |
| --- | --- |
| API at `7c43cbfc1161f958e0972ccfc4465293d94dbf6a` | 2,625 tests passed; 91.05% coverage. API/config/build-test inputs match the final validated title source. |
| PostgreSQL/Redis integration at the same API checkpoint | 380 passed; one inherited httpx cookie deprecation warning. |
| Web at `1ffc78382eaf11d58620b2fc13ceb6263c5ee942` | 807 tests passed; 95.74% statement coverage, including the title correction. |
| Static checks at that title checkpoint | Ruff, formatting, mypy, import contracts, ESLint, TypeScript and pre-commit passed. |
| Production build | Successful HTTP-mode build reused against identical web product/build inputs; the final Docker build was separately exercised below. |

Ordinary suites used fake providers or mock transports, not real credentials.
[Served generation integration](../apps/api/tests/integration/test_step_generation_served.py)
adds real HTTP, PostgreSQL, Redis and a consuming worker with deterministic fake AI;
[file integration](../apps/api/tests/integration/test_file_attachments.py) checks
storage and transaction behavior. Neither establishes live-provider quality.

### Acceptance against the delivered Docker app

At the final source above, bounded checks exercised password login, reload/new-tab
session restoration, protected navigation, list/board and Back/Forward, search,
project/task operations, title editing, steps, comments, activity and file round trips.
The title journeys checked a paused Space followed by more typing, caret preservation,
reload persistence and genuine blank-title refusal/retry. Controlled delivery of
real PATCH responses separately checked that an older acknowledgement preserves a
newer draft. These core/title journeys used Playwright, not native gestures.

One real queued OpenRouter job traversed the API, Redis and Linux prefork Celery and
returned **10 proposals**. The full task response was unchanged before acceptance,
including after removing one proposal locally. Explicit acceptance stored **9 steps**;
reload and database readback agreed on the selected titles and order. That demonstrated
the product boundary I wanted: assistance first, a deliberate user decision before
persistent change. It was one final-app success, not a provider evaluation campaign.

The final API report recorded 74 expected statuses and 116 passing assertions,
retaining an earlier header-helper false failure and a separate failed 403 rate-header
audit. The primary browser run retained 14 passed
and 3 failed compound cases; nine corrected navigation checkpoints subsequently
passed. Invalid URL expectations, a wrong board selector and an assertion made before
an asynchronous step acknowledgement were distinguished from product defects, not
silently removed from the record. Native stale-reference failures stopped that path.
An auxiliary generation observer started after acceptance and failed its launcher
assertion; preacceptance evidence comes from the captured task responses, not that
late observer.

A 375×812 viewport check covered dialog keyboard traversal and document overflow,
not touch or full accessibility. The primary browser console contained two expected
422 resource errors; no page errors or Chrome Issues were recorded in that bounded
run. The corrected navigation run was clean. These observations do not erase the
historical jsdom notices or establish a universal warning-free result.

### Known follow-ups and evidence provenance

The delivery was accepted with these limits visible:

- **Development React185 remains unresolved.** Production search passes do not fix
  the Next development-mode maximum-update-depth failure.
- **Cookie-CSRF 403 refusals lack the documented rate headers.** They safely refused
  writes, but source ordering skips the ordinary limiter decision on that path.
  Accounting was not directly measured in Redis; no auth bypass or exhaustion exploit
  was demonstrated.
- **Long project names overlap sidebar rows.** The final check measured 9.75 px of
  overlap; this is a usability follow-up, not observed data loss.
- **The project-key hint says 2–4 letters while the contract permits 2–5.** Five-letter
  keys succeeded through the API; five-letter UI acceptance was not tested.

Retained instructions, source and validation reports underpin this account, not a
complete conversation archive. The starting prompt is edited recollection; the
reusable prompt is newly proposed; the feature quotations are retained instructions;
the code samples are accepted output, not invented first model responses. The exact
development model/version is not established by the app's provider settings. The
TDD policy alone is not proof that every historical change followed it.

This prose-only revision reuses source-bound suite/build/browser evidence; it does
not report new executions of those campaigns. CI was intentionally **skipped, not
green**. No live Google SSO, exhaustive browser/security audit, production capacity,
forced worker-kill proof or live-model usefulness benchmark is claimed. Fresh final
acceptance did not repeat natural session expiry, all filter permutations, step-limit
concurrency or crash/rollback testing. Earlier failures retain their original scope.

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

These examples show where feedback changed the implementation or the way we checked
it. The useful output was the corrected behavior and its evidence, not the assistant's
initial confidence.

- **Title autosave:** a natural paused Space was saved, trimmed by the server and
  applied back to the focused input, joining the next word to the previous one.
  The correction retains the title's local draft until blur/close while still saving
  it; tests cover natural typing, newer drafts during acknowledgement and refusal/retry.
  This accepts a focused-draft-versus-canonical-value tradeoff rather than changing
  autosave for every field. See [autosave](../apps/web/src/features/tasks/detail/autosaveMachine.ts)
  and [title-typing tests](../apps/web/src/features/tasks/detail/titleTyping.test.tsx).
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
File content sniffing, streaming size limits, rollback cleanup and their residual failure windows
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

I would keep the same division of responsibility: I set product direction and make
acceptance decisions; Firstmate helps turn those decisions into bounded work, brings
back suggestions and evidence, and keeps the feedback loop moving. The most useful
questions were concrete: what may this layer know, what happens when a provider
fails, what persists after reload, and who decides that a suggestion becomes task data?

We reached a working task manager by answering those questions through successive
implementation and validation, not by making the initial prompt sound omniscient.
My reusable lesson is to define observable behavior, preserve failures and distinguish
intent, accepted source and demonstrated behavior. That is how I can explain both
what was delivered and what I would improve next.
