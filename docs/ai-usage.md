# AI usage

## Tools used

GenAI-assisted implementation used bounded task instructions, repository inspection,
code edits and test feedback. Retained implementation briefs and validation reports
support the examples below; they are not a complete conversation archive. The precise
coding model/version and first unedited model drafts are not retained in the evidence
used for this account, so neither is asserted here. The samples are **accepted resulting
repository code**, not claimed verbatim first responses.

The workflow used pytest, Vitest/MSW, Playwright, native Chrome checks, Ruff, mypy,
TypeScript, import-linter and pre-commit. The repository's
[working rules](../AGENTS.md) require tests-first changes and inward dependencies;
that policy alone is not proof that every change followed TDD.
The application's configurable language-model adapters are a separate feature, not
identification of the coding assistant: see [ADR 0003](decisions/0003-llm-adapters-over-http.md).

## Prompts used

These are exact, representative excerpts from retained implementation instructions,
not newly reconstructed prompts or the entire development conversation:

> Implement only the queued asynchronous step-generation API.

> Validate model output as bounded nonempty step titles consistent with the merged step domain/bulk contract. Malformed/empty/oversized output and provider failure must yield a useful failed job, not partially created task steps. Do not trust free-form model text as executable input. Read task data using short request scopes; do not hold a database transaction while waiting for a model response.

> Keep generated proposals separate from stored steps. Human acceptance uses the existing atomic bulk-step use case/endpoint and its 100-step ceiling; do not invent another acceptance or activity mechanism.

Summary, **not a quotation**: these instructions constrained implementation to the
existing Celery/Redis infrastructure and provider-neutral ports, authenticated
request/poll routes, bounded safe failure responses and offline tests. They did not
ask the assistant to invent a new job framework or automatically accept generated steps.
The implemented scope is [FR-24–26](PRD.md#draft-step-generation).

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
- AI and SSO providers remained **fake**. These results do not verify paid-provider
  availability, model usefulness or a real Google account flow. One inherited httpx
  cookie warning was disclosed; normal native console and Chrome Issues checks were clean.

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
- **Validation setup was fallible too:** an HTTP run failed when its worker was absent;
  a recovered owned worker and a later scheduled run passed. Credential-limit failures
  were retained and groups spaced by the real limit window, not “fixed” by weakening
  authentication limits. Those failed attempts are not included as passes.

## Edge cases, authentication and validation handling

[Generation unit tests](../apps/api/tests/unit/test_generate_step_titles.py) cover
malformed, empty and oversized output, Unicode, provider errors and timeouts;
[route tests](../apps/api/tests/api/test_step_generations.py) cover authentication,
rate limits and task/job association. Unknown, expired, wrong-task and deleted-task
handles are not successful empty results. Generation does not add steps; explicit
acceptance is atomic and subject to the 100-step ceiling.

[Authentication tests](../apps/api/tests/api/test_auth.py) exercise the JWT boundary;
the product is deliberately a **shared workspace**, not per-user task isolation.
Browser sessions are memory-only, so a reload requires sign-in again. File content
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
