# Product Requirements: Ballast Tasks

## Overview

## User stories

## Scope

### In scope

### Non-goals

## Functional requirements

What exists today. The HTTP contract, with every status code and error body, is in [architecture.md](architecture.md) and in Swagger (`/docs`).

Accounts

- FR-1. A person registers with an email, a full name and a password, logs in, and receives a JWT bearer token; every other feature requires it.
- FR-2. A user reads their own account and changes their own full name and role label (a free-text label such as "backend"; it grants nothing).
- FR-3. A signed-in user lists the active users (id, full name, initials, role label) to pick an assignee. Nobody sees another user's email address.

Projects

- FR-4. A user creates a project with a name, a unique key of 2 to 5 upper-case letters (such as `BT`) and an optional colour token, lists the projects with their open-task counts, reads one, and renames or recolours it. A project's key never changes and projects are not deleted.
- FR-5. Every workspace has an "Inbox" project; a task created without a project belongs to it.

Tasks

- FR-6. A user creates, reads, changes and deletes tasks. A task has a title, an optional description, a status (To Do, In Progress, Testing, Done), an optional due date, a creator, an optional assignee, a project, a priority (`P0` to `P3`, default `P2`) and an importance (0 to 100, default 50).
- FR-7. Every task has a human key, `<PROJECT KEY>-<NN>` (such as `BT-04`), sequential per project without duplicates or gaps even when tasks are created at the same moment. The key never changes, also when the task moves to another project, and a task can be addressed by its key as well as by its id.
- FR-8. A task is assigned to an active user, reassigned, or unassigned. An assignee who is later deactivated keeps the task, which can still be edited, completed or handed on.
- FR-9. A task is marked completed by moving it to Done, which records when; moving it out of Done reopens it.
- FR-10. The task list is filtered by view (all, mine, overdue), project, status (one or more, all open, everything), due date (overdue, today, next 7 days, no date, on or before a date, on or after a date), priority, assignee (or unassigned), attention signal and a case-insensitive search of title and description; sorted by urgency, importance, due date or most recently updated; and paged with `limit` (default 50, maximum 200) and `offset`, reporting the total. The default is the open tasks, most urgent first.
- FR-11. Every task in a response says what about it asks for attention today (overdue, due soon, P0 at risk, needs an owner, days until due, an urgency score and the reasons), by the rules of the web design, so the client does not re-implement them.
- FR-12. A summary gives the sidebar counts (all, mine, overdue, per project) and the four Attention signals (overdue, P0 at risk, due soon, need an owner) for the current filters.
- FR-13. One shared workspace: any signed-in user sees and changes every task and project. Dates are evaluated on the UTC calendar day.

Steps, comments and activity

- FR-14. A signed-in user adds, renames, ticks, unticks, reorders and deletes steps on any task. Titles are trimmed, 1–200 characters and contain no NUL. A task holds at most 100 steps; the add that would cross that ceiling is rejected and adds nothing, and deleting a step makes room again. Steps remain densely ordered under concurrent changes; a reorder must name every current step exactly once. Deleting a task deletes its steps.
- FR-15. A user accepts an ordered list of 1–20 step titles in one atomic request. All are appended in that order or none are added, including when the batch would take the task past its 100 steps; this endpoint does not generate proposals.
- FR-16. Every task representation carries `steps_total`, `steps_done` and `comments_count`; reading one task also returns its ordered steps. Listing computes counts without a query per task.
- FR-17. Task creation, status moves (including completion/reopening), assignment/clearing, due-date changes, priority changes, step addition/completion and bulk acceptance append automatic activity in the same transaction. No-op changes log nothing. Wording follows the design where it logs the event; the required design-styled extensions are listed in [ADR 0007](decisions/0007-steps-and-activity.md).
- FR-18. A signed-in user posts an immutable comment of 1–2000 trimmed characters, rejecting NUL. A task's timeline combines comments and logs, newest first, paginated with `items`, `total`, `limit` (default 50, max 200) and `offset`; every entry identifies its actor by id, full name and initials, never email. Deleting a task deletes its timeline.
- FR-19. Existing tasks retain all their data and receive only a creation entry attributed to the original creator at creation time; earlier unrecorded changes are not invented. Comment editing/deletion, mentions, notifications and real-time updates are outside this piece.

Attachments

- FR-20. A signed-in user attaches an absolute http(s) link to a task, with an optional name defaulting to the host. URLs over 2000 characters, credentials, relative references and other schemes are rejected.
- FR-21. A signed-in user uploads a PDF, PNG, JPEG, GIF or WebP file. Leading bytes determine type, not the filename or supplied MIME type. Empty, unsupported and oversized files are refused without leaving a stored file. The size limit is checked while streaming, defaults to 10 MiB, and is configurable.
- FR-22. Every task representation reports its attachment count; task detail includes its attachments. A signed-in user downloads stored files with their detected content type and sanitised display name, removes attachments, or deletes a task and all its attachments/files. Attaching and removing record caller-attributed `Attached <name>` / `Removed <name>` activity through the existing recorder in the same transaction; refusals record nothing.
- FR-23. File storage is replaceable through a small port and provider registry. Local-disk storage ships now with a persistent named API volume; cloud providers, virus scanning, previews and per-user permissions are out of scope. Storage failure windows and security limits are explicit in [ADR 0008](decisions/0008-file-storage.md).

Draft step generation

- FR-24. A signed-in user asks a task for draft step titles. The request queues background work and answers at once with a job handle in a `pending` state; the request itself creates no step and neither calls nor awaits the model, though a worker may start the job before the response is delivered. Polling that handle reports `pending`, `running`, `success` with 1–20 proposed titles, or `failure` with a safe reason (`invalid_output`, `provider_unavailable`, `timeout`, `worker_failed`) that never carries a provider response or credential.
- FR-25. A handle belongs to its task and stays readable for up to an hour after it is queued, as long as its task still exists and the ephemeral result store still holds the handle, so it survives selecting another task and returning; another task's handle, an unknown one, one whose task was deleted and an expired one are all unknown. A generation that does not finish within five minutes is reported as a timed-out failure. Asking again is how a user retries or regenerates; nothing cancels a running generation.
- FR-26. Generating proposes nothing into the task: the user accepts the chosen titles through FR-15, which is where the 100-step ceiling is checked. Removing or discarding proposals before accepting them changes nothing on the server.

## Non-functional requirements

## Milestones
