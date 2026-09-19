# ADR 0005: Task keys from a per-project counter, and one urgency model in two languages

- Status: Accepted
- Date: 2026-09-19

## Context

The web design shows things the API did not have: projects, task keys such as `BT-04`, a fourth status, priority and importance, an Urgency sort and an Attention strip, all over a task list that is filtered, sorted and paged by the server.
The design is the authority where it differs from the API; its script (`Component.dueInfo`, `urgency`, `filtered`, and the signals in `renderVals`) holds the exact rules.

Two of those need a decision that is easy to get subtly wrong:

1. A key is `<PROJECT PREFIX>-<NN>`, sequential per project. Two people creating tasks in one project at the same moment must not get the same number, and a number must not be skipped.
2. Urgency depends on today's date, so it cannot be a stored column, and the list must still be sorted and paged in SQL. That puts the same formula in two places (the domain, for the `attention` object of every response; SQL, for `ORDER BY`), and two copies of a rule drift.

## Decision

### Keys: a counter on the project row, taken inside the unit of work

`projects.next_task_number` is incremented by `ProjectRepository.allocate_task_key` with one statement:

```sql
UPDATE projects SET next_task_number = next_task_number + 1
WHERE id = :project_id
RETURNING key, next_task_number - 1
```

- The `UPDATE` takes the row lock and holds it until the request's transaction ends (`Container.request_scope()` is the unit of work, so no code here commits). A second creator in the same project waits, then reads the number the first one left: **no duplicates, no race**. Creators in other projects lock other rows and do not wait.
- When the request fails after taking a number, the rollback undoes the increment: **no gaps**. This is why `CreateTask` can take the key first and check everything else afterwards.
- `uq_tasks_key` is the backstop should anything ever bypass the repository.

Rejected: **a PostgreSQL sequence per project.** Sequences are deliberately non-transactional, so a rolled-back creation leaves a hole, which is exactly what "without gaps" forbids; and a sequence per project means DDL at runtime (`CREATE SEQUENCE` when a project is created) outside Alembic, against the rule that schema arrives only through revisions.
Rejected: **`SELECT max(number) + 1`.** Two transactions read the same maximum; it needs the same lock to be correct and scans more to get it.

Cost accepted: task creation is serialised per project for the length of one short transaction. For a team tool that is irrelevant; a project with sustained concurrent creation would be the moment to revisit.

"No gaps" is about allocation. Deleting `BT-03` leaves `BT-03` unused forever: a key that has been shown to people is never handed to another task.

### A key is immutable, and so is a project's prefix

- The design lets a task move to another project. The task keeps its key (`BT-02` stays `BT-02` in the Inbox): it is what people have written in commits and chats. Consequently `tasks.key` is unique on its own, not per project, and the key is stored as text rather than derived from `(project, number)`.
- `PATCH /projects/{id}` changes the name and the colour, never the key: every key the project handed out carries it.
- Format: the number is padded to two digits (`BT-04`, `BT-12`, `BT-100`), as the design draws it. Lookups accept any case and padding (`bt-4`).

### Urgency: the design's function, ported twice, held together by tests

- `app.domain.attention.assess(task, today=...)` is the port of `dueInfo` + `urgency`, with the design line cited wherever a rule is not obvious. It produces the `attention` object of every task response.
- `infrastructure/db/repositories/task_queries.py` is the same formula as a SQLAlchemy expression, used for `ORDER BY`, for the `signal` filter and for the summary's counts. `today` is a bound parameter, never `CURRENT_DATE`: the clock belongs to the application and tests pin it.
- Neither copy is trusted. `tests/urgency_cases.py` holds a third, deliberately literal line-by-line port of the design's JavaScript, plus a table of 736 cases covering every boundary (the 30-day cap, each priority's window, the 40-day point where distance stops counting, no date, done tasks). Three tests compare against it:
  - `tests/unit/test_attention.py`: the domain, value by value;
  - `tests/integration/test_urgency_sql.py`: the SQL expression and the four signals, value by value, in real PostgreSQL;
  - `tests/contract/test_task_repository_contract.py`: the resulting order, for the in-memory fake and the PostgreSQL adapter alike.
- The score is `numeric` in SQL so equal scores are exactly equal, and every sort ends with `created_at DESC, id DESC`, so pages never overlap or skip.

Rejected: **a stored or generated urgency column.** It would be wrong the day after it was written, because it depends on today; refreshing it nightly makes the list lie for up to a day and adds a job.
Rejected: **sorting in Python.** Paging needs the whole ordered set, so every request would load every task.

### Indexing

No index can serve an order that changes with the date, so the urgency sort always sorts what the filters leave. What can be indexed is what the default view reads: open tasks. `ix_tasks_open_project_id_due_date` is partial (`WHERE status <> 'done'`), so it stays the size of the open work however many done tasks accumulate; with 5,000 tasks of which 50 are open, `EXPLAIN` shows an index scan feeding a 50-row sort, and no sequential scan. The open-task condition is written as a literal in SQL, because the planner only matches a partial index against a predicate it can read.
`q` is an unindexed `ILIKE` over title and description. A trigram index needs the `pg_trgm` extension, which was not worth adding for a workspace of this size.

### Smaller calls made along the way

- **Defaults of `GET /tasks`** are the design's: open tasks, by urgency, 50 per page (max 200). `status=all` lists everything. The previous default (everything, newest first) is `?status=all&sort=updated`-like but not identical; the change is deliberate.
- **`status` on create.** The design adds a task straight into a board column (`create(title, open, status)`), so `POST /tasks` accepts a `status`; `done` completes the task at once. The earlier API refused it, and one API test case that pinned the refusal now pins that a status outside the vocabulary is refused.
- **`is_due_soon`** follows the design's "due soon" chip: not overdue, and due today or within the window, where the window is 2 days, widened to 3 for `P1` and 4 for `P0` (design line 524).
- **The Attention strip** (`GET /tasks/summary`, `signals`) follows every filter except `status` and `signal`: it describes open work even while the list shows done tasks, and choosing one chip must not blank the others. Sent only `project_id`, it is exactly the design's strip (design line 726). The sidebar counts ignore filters, as in the design (line 743).
- **The people list is its own port**, `PeopleDirectory`, not a method on `UserDirectory`: the task use cases need a yes or no about one id, the picker needs names, and a test double of one should not have to implement the other. `Person` has no email field, so none can leak.
- **`PATCH` and `DELETE` also accept a key.** OpenAPI does not allow two templated paths that differ only in the parameter name, so all three task routes are `/tasks/{id_or_key}`.
- **Priority is stored as its rank** (0 for `P0`), so the SQL computes with it as the design does; the API and the domain speak `P0` to `P3`.

## Consequences

Positive:

- Keys are correct by construction under concurrency, proven by `tests/integration/test_task_key_allocation.py` (12 concurrent creators, a rolled-back creation, two projects at once).
- A change to the urgency rules that touches only one of the two implementations fails a test.
- The list issues a fixed number of statements whatever it returns (list 3, summary 4, projects 2, the first being authentication), asserted in `tests/integration/test_design_api.py`.

Negative, accepted:

- The formula exists in Python and in SQL. The tests make the duplication safe, not absent.
- "Today" is the UTC date for everybody (see "Time" in [architecture.md](../architecture.md)).
- One shared workspace: any signed-in user sees and changes every task and project. Membership and permissions are out of scope, and `created_by` plus the foreign keys are what a later ownership model would build on.
