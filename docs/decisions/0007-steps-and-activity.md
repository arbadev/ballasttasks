# ADR 0007: Task steps and application-recorded activity

Status: accepted

## Context

The detail panel shows ordered steps and an activity timeline containing log lines and comments. The design's script is the wording authority. Changes must be atomic with their log entries, also when initiated outside an HTTP route. Attachments and future step generation need the same recording seam without depending on this feature's persistence adapter.

## Decision

Application use cases depend on the small `ActivityRecorder` Protocol: `async record(entry: ActivityEntry) -> None`. `RequestScope.activity` supplies the adapter bound to the same session as the task repository. The use case decides whether anything changed, constructs the entry using its injected clock and actor, then records it. The unit of work alone commits or rolls back. `ActivityFeed` is a separate read port; neither exposes update or delete. Comments are immutable `comment` entries, not a comment plus an extra log line.

Database triggers were rejected: they lack the calling user's application context, cannot distinguish a bulk acceptance from independent inserts, and would place product wording in SQL rather than the tested domain. Route-level logging was rejected because non-HTTP callers would miss entries and controllers would own business behavior. No-op changes record nothing.

### Wording and events

`app/domain/activity_log.py` is the sole source of log sentences. Tests in `tests/unit/test_activity.py` pin the text. Completing/reopening a task is a status move, not a second event.

| Event | Text | Authority |
| --- | --- | --- |
| Create task | `Created the task` | Design `create` |
| Change status, complete or reopen | `Moved To Do → In Progress` (column names vary) | Design `move` / `toggleDone` |
| Assign | `Assigned to Lucía Marín` | Design assignee picker |
| Clear assignee | `Unassigned` | Design assignee picker |
| Due tomorrow | `Due date moved to tomorrow` | Design `dueTomorrow` |
| Due one week out | `Due date moved a week out` | Design `dueNextWeek`: a week after a future due date, otherwise after today |
| Other due date | `Due date moved to Sep 4` (include year when different from today) | Design-styled extension for the required event |
| Clear due date | `Due date cleared` | Design-styled extension |
| Priority | `Priority P2 → P0` | Design-styled extension; design silently changes priority |
| Add step | `Added step “Task entity”` | Design-styled extension; design `addStep` is silent |
| Complete step | `Completed step “Task entity”` | Design-styled extension; design checkbox is silent |
| Accept bulk steps | `Drafted 3 steps · added by Lucía` (singular `step` for one) | Design `accept`, actor's first name |

Title, description, importance and project changes, step renames, unticking, reordering and deletion are silent, as in the design. Their real changes still update the task's `updated_at`. Comment text is trimmed, 1–2000 characters, and NUL is rejected. Step titles are trimmed, 1–200 characters, and reject NUL.

### Step ordering

Steps have zero-based dense integer positions, unique per task. Every writer first locks the owning task (`SELECT ... FOR UPDATE`) inside the unit of work. Appends use the list length; deletion renumbers successors; reorder requires an exact permutation of current ids. Stale, duplicate, missing or foreign ids reject the entire request. Bulk insertion validates all 1–20 titles first and appends them atomically in request order.

The `(task_id, position)` unique constraint is `DEFERRABLE INITIALLY DEFERRED`: intermediate swaps may collide, but the committed result cannot. The task lock serializes appends, deletions and reorders together without locking unrelated tasks. This is simpler than fractional positions for small detail-panel lists; it costs O(n) writes for a reorder. PostgreSQL concurrency tests prove both density and task-local locking.

### Reading and migration

Activity is ordered by `created_at DESC, seq DESC`; a private identity sequence breaks equal timestamp ties in recording order without relying on random UUID order. The feed joins only actor id and full name; initials come from the domain and email is never exposed. Pagination uses the task-list envelope, default limit 50, maximum 200.

`TaskTallies.for_tasks(ids)` computes step totals, completed totals and comment counts for a whole task page in one SQL statement, avoiding an N+1. A nonempty authenticated list costs four statements: caller, page, total, tallies; an empty page costs three.

One revision creates `task_steps` and `task_activity`. Both cascade on task deletion; activity actors reference users with `RESTRICT`. Existing tasks are unchanged and acquire exactly one creation entry, attributed to the existing creator (including inactive users) at the original creation timestamp. No historical changes are invented and no steps are backfilled. Downgrade drops the two tables and all their contents, leaving tasks intact. Upgrade from empty, upgrade with existing rows, downgrade/re-upgrade and constraints are exercised by `tests/integration/test_steps_activity_migration.py`.

## Consequences

The API gains steps and immutable comments; no attachment storage, AI generation, comment editing/deletion, mentions, notifications or real-time delivery is included. All signed-in users share the workspace and may operate on any task. The generated web API schema changes, but frontend behavior is outside this decision.
