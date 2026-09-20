# apps/web

Next.js (App Router, TypeScript, Tailwind) frontend. `/` is the Ballast Tasks application;
`/status` shows API, Database, Redis and AI (provider and model) health, and is linked from
the sidebar footer.

## Architecture

Dependencies point inwards; components never touch HTTP, the environment or a concrete service.

| Path | Responsibility |
| --- | --- |
| `src/app/providers.tsx` | Composition root: the only place a concrete service is constructed. Exports the hooks `useAuthService`, `useSession`, `useTaskService`, `useDirectoryService`, `useStepGenerationService`, `useClock`, `useHealthService`. |
| `src/app/globals.css` | The design tokens, once: the skin's CSS variables, mapped into the Tailwind theme (`bg-card`, `text-fg-3`, `rounded-bt`, `shadow-glow`, `animate-bt-in`, ...), plus base rules and the `bt-*` keyframes. Components use token names, never raw hex. |
| `src/lib/config.ts` | The only application module that reads `process.env` (the Playwright tooling reads its own variables: see "Visual tests"). Validates on load. |
| `src/lib/api/client.ts` | The only module that calls `fetch`. Throws a typed `ApiError`. |
| `src/lib/api/schema.d.ts` | Generated from the API's OpenAPI document. Never edited by hand. |
| `src/components/ui/` | Shared primitives: `Button`, `IconButton`, `Select`, `SegmentedControl`, `TextInput`, `Avatar`, `Pill`. No feature knowledge. |
| `src/features/tasks/model/` | Types and pure logic: due info, relative time, urgency, filtering, sorting, sidebar counts, Attention signals. Every function takes `now`; nothing reads the clock. |
| `src/features/tasks/services/` | `types.ts` holds the interfaces the UI depends on (`TaskService`, `DirectoryService`, `StepGenerationService`, `Clock`). The `http*` files implement them over `client.ts` (the default); the `inMemory*` files implement the same interfaces over one shared store seeded from the design. |
| `src/features/tasks/workspace/` | One reducer plus its provider: scope, project, filters, Attention signal, sort, search, view, selected task, loaded tasks, load state. |
| `src/features/tasks/shell/` | Sidebar, header, filter toolbar, Attention strip, the page controls (`TaskPagination`), and `TasksApp`, which mounts the three views below. |
| `src/features/tasks/detail/` | The task side panel: `TaskDetail` (dialog, focus, Escape) around one component per section. `useAutosaveField` is the autosave rule for every field, `DetailSession` holds what must outlive the open panel (saves in flight, unsent drafts, failed generations), `model/` the pure parts (banner text, task key, link parsing). |
| `src/features/tasks/list/` | The list view. `rowView.ts` is the pure row model (due tone, rail, priority tone, stagger: every decision the design's `taskView` makes); `TaskRow`, `QuickAdd`, `ListSkeleton` and `ListLoadError` draw it; `ListView` wires them to the workspace and owns keyboard focus. |
| `src/features/tasks/board/` | The board view: the four status columns, the card, and the moves between them. See "The board" below. |
| `src/features/projects/` | Project creation: the rules for a name and key (`model/rules.ts`, pure), the "New project" control the sidebar mounts, its dialog, and the empty-project state the shell shows for a project with no tasks. Creates through `DirectoryService.createProject`, then `actions.addProject`. |
| `src/features/auth/` | Sign-in: the `AuthService` over `client.ts`, the `AuthBoundary` that gates the workspace on a session, and the `/auth/callback` code exchange. See "Authentication and HTTP integration" below. |
| `src/features/health/` | `HealthService` and the `StatusCard` behind `/status`. |
| `src/test/` | Test infrastructure: `makeTask`/`due`/`NOW`, fake services that record calls, `renderWithServices`. |

The two "only module" rules are enforced by ESLint (`eslint.config.mjs`), not by convention.
Icons come from `lucide-react`, the design system's icon set.

The default services are HTTP-backed. `NEXT_PUBLIC_SERVICE_MODE=demo` explicitly selects
in-memory design fixtures; visual comparison tooling opts into that mode, never silently
falls back to it after an API error. Unit tests can still inject individual services.

## Authentication and HTTP integration

`/` presents password sign-in/registration; `/auth/callback` exchanges an SSO one-time code
in a POST body after clearing it from the browser URL. Enabled providers come from the API.
The bearer credential lives **only in memory**. Full reloads and new tabs require sign-in
again; logout/401 clears the session and unmounts the workspace. This is not XSS protection.
Unsaved per-session drafts are cleared by that teardown: within-session close/reopen
retention does not promise draft survival across sign-out or expiry.
Saved tasks/projects are PostgreSQL data, independent of login persistence: sign in again
to retrieve them. No refresh tokens, cookie session or browser token storage is introduced.
Next development request logs exclude `/auth/callback`; deployment proxy/access logs must
also omit callback query strings. Real-vendor OAuth setup and primary-stack activation are
separate operator actions, not performed by the local fake-provider tests.

The HTTP workspace uses the API's filters, sorting, search and limit/offset pages (50 rows),
not client filtering over the first page. Page/filter changes discard stale requests;
mutations reload canonical query results and counts. Sidebar counts describe the whole
workspace; Attention counts describe open work in the selected project, as in the design.
Board queries ignore only the status filter; the header still describes the list's status
filter, and pagination is across all columns. The four column totals are the list response's
own `status_totals`, which counts every matching task by status whatever the page holds, so
a board query is two requests (list and summary) however many pages of tasks match.
Already-loaded views stay mounted during refresh (marked busy), preserving pending gestures
and focus, and sidebar counts keep their last server values rather than blanking. Full-scope column totals do not hide optimistic cards or imply every card is on
this page; columns with off-page rows say so.
Selected-task detail/activity is loaded separately, not once per list row. The complete
`TaskService.list()` remains a legacy/demo capability, not the HTTP workspace's data path.

`client.ts` attaches bearer headers, carries Retry-After, uploads multipart files and returns
authenticated download blobs (never bearer URLs). It fences both late responses and queued
work from an obsolete session. Client disposal does not undo an already accepted mutation.
Generation handles belong to tasks; observation pauses when not selected/visible/subscribed,
uses 2/4/8/10-second delays, respects Retry-After and stops at terminal results. Proposals
are accepted through one atomic bulk endpoint; an ambiguous acceptance must be checked by
reloading the task, not blindly retried. The API's 100-step ceiling remains authoritative;
a single bulk request accepts at most 20 titles. The explicit demo follows per-task proposal,
local-only discard and accepting-user activity semantics too. The shared 120 requests/60s
allowance is unchanged; it is not a generation quota or paid-provider cost budget.

SWR was evaluated via Context7's `/vercel/swr` and `/vercel/swr-site` official sources,
with the 2.5.1 tag checked against React 19. It is not added: the existing workspace and
service seams own data, and a second cache would duplicate mutation/auth coordination.
References: [cache](https://swr.vercel.app/docs/advanced/cache),
[revalidation](https://swr.vercel.app/docs/revalidation),
[mutation](https://swr.vercel.app/docs/mutation),
[error handling](https://swr.vercel.app/docs/error-handling).

Task dates are **UTC calendar days** in both HTTP and explicit demo modes. “Today” changes
at UTC midnight, independent of the browser's timezone; due labels, quick actions, urgency
and date-based ordering use the injected `useNow()`/Clock instant with that same basis.
Entered `YYYY-MM-DD` values stay unchanged (not converted through local instants), and Clear
sends exactly `null`. Absolute activity-timestamp presentation is unchanged. Date and service
contract tests cover UTC midnight, both offset directions and DST boundaries.

## Building on the shell

The shell mounts three views. Each is owned by one slice, which keeps whatever it needs
**inside its own folder**. The list, board and detail panel are built (see "The board" and
"The task panel" below):

| Folder (owner) | Mounted as | Contents |
| --- | --- | --- |
| `src/features/tasks/list/` | `<ListView />` when the view is `list`, in every load state: it draws its own skeleton and load error | Built: the task rows and the quick-add input. |
| `src/features/tasks/board/` | `<BoardView />` when the view is `board`, in every load state; it shows its own loading skeleton and load error | Built: the four status columns, with drag, keyboard and touch moves. |
| `src/features/tasks/detail/` | `<TaskDetail />`, always mounted; renders when a task is selected | Built: see "The task panel" below. |

Everything else (`model/`, `services/`, `workspace/`, `shell/`, `components/ui/`) is shared.
If a slice needs a change there, keep it additive (a new export, a new prop with a default)
so the other two slices are unaffected.

A view that replaces another hands the focus on: when the empty-project state saves its first
task, its `onFirstTask` makes the shell set `ListView`'s `focusQuickAdd`, so the caret lands in
the quick-add without the page scrolling. The list is the only view that claims it: the board
has no quick-add, so a first task saved while the board is showing takes no focus of its own.

All hooks come from `workspace/WorkspaceProvider.tsx` unless noted.

**Reading**

| Hook | Gives you |
| --- | --- |
| `useVisibleTasks()` | The tasks to show: filtered by scope, project, toolbar filters, search and Attention signal, then sorted. **List.** |
| `useVisibleTasks({ applyStatus: false })` | The same without the Status filter, because the board shows every status as a column. **Board.** |
| `useWorkspace().state` | `selectedId`, `tasks`, `query`, `sort`, `view`, `load`. **Detail** finds its task with `state.tasks.find(t => t.id === state.selectedId)`. |
| `useDirectory()` | `people`, `projects`, `currentUser` for avatars, assignee and project pickers. |
| `useNow()` | The current time, sampled from the injected clock. Pass it to `dueInfo(due, now)`, `urgency(task, now)`, `relativeTime(at, now)`. Never call `Date.now()`. |

**Workspace actions** (`useWorkspace().actions`)

| Action | Used by |
| --- | --- |
| `selectTask(id)` | List rows and board cards, to open the detail panel. |
| `clearSelection()` | Detail: close button, backdrop, Escape. |
| `addProject(project)` | Project creation, after `DirectoryService.createProject` resolves: lists the project in the sidebar and selects it in a clean view (scope All tasks; Attention signal, filters and search reset; sort and view kept). |
| `selectScope`, `toggleProject`, `setStatusFilter`, `setDueFilter`, `setPriorityFilter`, `setSort`, `setSearch`, `toggleSignal`, `clearSignal`, `setView`, `reload` | The shell. Available to the views, rarely needed. |

**Task commands** (`useTaskCommands()`): each calls `TaskService` and then puts the saved task
back into the workspace, so counts, signals and every view update together. Call these rather
than `useTaskService()` directly.

| Command | Service method | Used by |
| --- | --- | --- |
| `create({ title, status? }, { open? })` | `create` | List quick-add and the empty project's first task (`open` false); board column "add" (`status`, `open` true). Goes into the selected project, or the Inbox. |
| `toggleDone(id)` | `toggleDone` | List checkbox; detail "Mark complete" / "Reopen". |
| `move(id, status)` | `move` | Board moves (through `useBoardMoves`); detail status select. |
| `update(id, patch, note?)` | `update` | Detail fields. The API owns assignment/due-date/priority event wording; legacy `note` is ignored, never posted as a comment or invented event. |
| `addStep`, `toggleStep`, `removeStep`, `renameStep`, `reorderSteps` | same names | Detail steps; rename keeps identity/completion, order sends every current ID exactly once. |
| `refreshTask(id)` | `get` | Read-only recovery after a refused/stale step order; syncs canonical children or forgets a missing task. |
| `addComment(id, text)` | `addComment` | Detail activity. |
| `addAttachment(id, attachment, file?)` | `addAttachment` | Link with its full absolute URL, or file metadata and original bytes for upload-capable adapters. Demo retains metadata only. |
| `uploadAttachment`, `downloadAttachment`, `removeAttachment` | same names | Optional capabilities for older demo doubles; HTTP implements all three. Upload/removal synchronize workspace state; download returns an authenticated blob, never a credential-bearing URL. |
| `remove(id)` | `remove` | Detail delete. Clears the selection if it was the selected task, and discards a step generation in flight for it. |
| `forget(id)` | none | A task the server no longer has: drops it from the workspace with its step generation, deleting nothing. The generation panel's "Reload task" uses it when the reload finds the task gone. |
| `sync(task)` | none | Detail, after `StepGenerationService.accept()` resolves with the updated task. |

**Step generation** (`useStepGenerationService()` from `@/app/providers`): `start(taskId)`,
`subscribe(listener)` and `current()` to observe `running`, `proposed` or `error`, `removeProposed(stepId)`,
`accept()` (then `commands.sync(task)`), `discard()`. The workspace coordinates optional
`select`, `setVisible` and `forget`; the composition root disposes obsolete session services.
Discard writes no activity and does not cancel a server job. The selected task's `detailLoad`
and `actions.reloadDetail()` distinguish a summary from complete children/activity.

**Testing a view**: `renderWithServices(<YourView />, { tasks })` from `src/test/` gives fake
services, the design's seed and a fixed clock (`NOW`, Friday 18 September 2026); wrap the view in
`WorkspaceProvider`, or render `<TasksApp />` to drive it through the real shell.
`FakeTaskService.calls` records what the UI asked for.

## The task panel

`<TaskDetail />` opens for `state.selectedId`. HTTP list summaries first show loading/retry instead of fabricated editable children. Previously loaded detail remains mounted during authoritative refresh, preserving drafts and focus in the existing workspace. Rows and cards only call `actions.selectTask(id)`;
the panel moves focus inside on open and hands it back to whatever was focused (the row, the
card, the New task button) on close, so an opener needs nothing more than being focusable. An
opener that is gone by then — the task deleted or filtered away from inside the panel — takes
no focus back, and the view it belonged to places it instead: the list remembers the control a
row was opened from until that panel closes, and gives the focus to the row's own control if it
is back, else the row that took its place, else the quick-add, the same as for a row it
completes. While it is open the panel keeps the keyboard. A control that disables or unmounts
itself under the reader's hands (a send button once its box is busy, a step's own Remove)
leaves the focus on the document, but the browser keeps its navigation starting point where
that control stood, so the next Tab carries on from there — usually still inside the panel.
The dialog leaves that key alone and watches only where it lands: a landing outside is wrapped
back to the panel's first stop, or its last when the key was Shift+Tab, the same edges
`keepTabInside` wraps at from within. Nothing else moves the focus, so an opener, another
dialog and the hand-back on close are all untouched.

- **Task fields autosave, no Save button.** Each task field is a `useAutosaveField`: the edit shows at once, text
  saves 400 ms after typing stops, on blur, and when the field unmounts (the panel closing,
  another task opening), so typed text is never dropped. A failed save says so inline, with a Retry
  that carries the rejected value. The control goes back to the stored value only when the refused
  write is still what it shows; a newer edit typed since stays on screen and settles the usual way,
  on commit or blur. That recovery is retired when the field sends a replacement of its own — when
  that value is actually on its way, not while it is still being typed and could yet be emptied —
  or once the stored value moves without the field asking (something else wrote the task while no
  control was mounted), so its Retry cannot undo the newer value; a value the field stored itself
  never counts as such a move. The footer reports `saving…`, `saved · <when>` or `not saved`.
- **A value the field cannot hold is never written by leaving it.** A field may declare which
  values are `savable`: an emptied number box and an emptied date box are not, and a date
  reports itself empty while a segment is being retyped. Such a value is kept as typed and never
  sent — so it never retires a reported failure — and `flush` (blur, unmount) puts the stored
  value back instead of saving it. Removing a due date is its own action — emptying the box asks,
  with "Clear date" beside a "Keep" that restores it. Focus moves within that date editor do
  not settle the input before its controls activate; leaving the editor still flushes normally.
  "Clear date" calls `field.store`, the
  one path that writes a value the control is not typing. The prompt asks about one stored date:
  it stands while the box is empty or back on that date, and another writer (the banner, a Retry)
  making a different date visible dismisses it, without a write from the prompt itself.
  Explicit "Clear date" saves null through the existing date owner, including when a queued
  write changed the saved date underneath an empty visible draft. `store` drops any
  half-typed edit as it goes, so an abandoned one cannot land on top of it, and its failure uses
  the field's own inline message and Retry. The date's machine is owned by `DetailSession`, not
  its mounted input: its draft, serialized writes and exact-null recovery survive close/switch,
  and a reopened input subscribes to the same owner. Other fields are owned by their mount.
- **Everything that writes the due date shares one owner**, `useDueField(task)`: the date box,
  "Clear date" and the urgency banner's "Due tomorrow"/"+1 week". The banner passes its activity
  note to `store`, which carries it through the same queue, so a quick reschedule cannot be
  undone by an older typed date that was still in flight, and a refused one says so under the
  date box with a Retry that re-sends that date and that note. A write releases only the draft
  it was made from, so an answer arriving while the reader is mid-retype leaves the box alone.
- **The step and comment boxes send one thing at a time.** `useComposer` holds what is typed and
  the send it is waiting on in one record per task and box, so both survive the panel closing
  mid-send and the box that opens again sees how that send ended. While a send runs the box says
  so and takes no second one; the next draft can be typed and is kept. A refused send is held
  with its exact text until Retry or Dismiss — the send controls stay unavailable and say so
  meanwhile, and nothing dismisses it implicitly. It is put back in the box only if the box is
  empty, and it keeps that text as its own however many refusals it takes, so a newer draft is
  never overwritten and a Retry that lands clears only text the failure itself put there.
- **Rename and reorder steps.** Activate a step's title to edit inline; Enter/Save submits a
  trimmed 1–200-character title, and Escape/Cancel abandons the draft without ticking or
  removing the step. The session's composer holds pending/refused renames and independent
  newer drafts across close/reopen, and the title being saved stays in the field, valid, until
  the reader types over it. Move up/down buttons have a reserved slot of their own between the
  title and Remove — they appear on row hover/keyboard focus without ever covering or reflowing
  the title, and take their own line with 44px targets on coarse pointers. First/last
  boundaries are disabled.
  Reordering sends the exact current-ID permutation, preserving completion and identity;
  neither operation invents activity. If membership changed concurrently or order cannot be
  confirmed, moving stops and **Reload steps** performs a canonical read, never resubmits
  the stale permutation. A failed reload retains recovery and drafts. The alert speaks about
  that refused move, not about what is on screen: a later canonical read (ticking a step, say)
  can bring the list up to date, and the message and the block on moving still stand until the
  reader reloads deliberately. The reload is a read, so it never reports itself as a save and
  never clears another field's "not saved". Keyboard order survives a move: the control that
  was activated takes the focus back when the move settles, the opposite arrow takes it at a
  boundary, **Reload steps** takes it when the move was refused and the row's control takes it
  again after the reload — unless the reader moved the focus somewhere themselves.
- **A new task** (one the workspace had not seen before it was selected) opens with its title
  focused and selected. Closing an untouched "Untitled task" keeps it, as the design does.
- **Step generation** belongs to its task: the service holds the run, the session holds a failed
  start, and both are still there after another task has been opened and closed. HTTP terminal failures and polling notices are visible; proposal controls lock during atomic acceptance. A rejected limit retains the proposal, while an uncertain acceptance requires canonical readback before generating again. Discard is local and creates no activity.
- **Attachments**: links retain their full validated URL and open in a new tab (URL plus optional
  title, validated by `model/linkAttachment.ts`). "Attach file" opens a labelled native picker;
  dropping a file works too. PDF, PNG, JPG, GIF and WEBP files up to 10 MB show uploading metadata
  until the service settles; invalid files or failed saves show an inline error. The in-memory
  adapter keeps metadata only, never file bytes. HTTP uploads the original file and reloads canonical metadata/activity; stored files offer authenticated blob downloads and confirmed removal, without credential-bearing URLs.
- **Escape** closes the innermost thing: the link form or the delete prompt first, then the panel.

## The board

`src/features/tasks/board/` is the board view, built from the design's markup and `taskView` rules.

| File | Responsibility |
| --- | --- |
| `BoardView.tsx` | The view: its own loading skeleton and load error, then the four columns. Holds the drag state, reports a refused "Add a task", and keeps focus after a move made without a drag: on the card until the move settles, then on whatever took its place in the column it left (that column's heading if it is empty) if the move took the card off the board. |
| `useBoardMoves.ts` | Optimistic moves over `useTaskCommands().move`: the card changes column at once; a rejected move cancels queued moves, restores the last saved status and offers a retry of the newest target. |
| `cardView.ts` | Pure: everything a card shows (due chip tone and mark, rail, priority tone, step and attachment labels), from `urgency` and `dueInfo`. |
| `TaskCard.tsx`, `BoardColumn.tsx`, `BoardSkeleton.tsx`, `BoardAlert.tsx`, `BoardLoadError.tsx` | Presentation only. `layout.ts` is the grid the board and its skeleton share. |

Calls for the same task never overlap. The newest queued target wins, so intermediate queued
targets are never sent; serialization prevents stale answers without a shared workspace guard.
A refused move is therefore carried on the user's newest target and not on the one the service
refused, because the intermediate hops were never sent, which is why the alert states only that
the card did not move and which column it is back in. A retry consequently records a single
status change rather than one per hop; that follows from coalescing and is intended.
Feedback is kept against the card it belongs to, never against one latest attempt: an unsatisfied
refused move raises its own alert, whatever any other card did. Only that card's next attempt,
a dismissal, or reaching its target takes it away, so two unsatisfied refused cards show two alerts. A refusal is a failure only when
the card is not already in the user's newest target: a hop refused on the way back to where the
card started asked for nothing that did not happen, so it raises no alert and leaves no Retry
with nothing to do. The same rule holds afterwards: a failure is dropped for good, not hidden,
as soon as the workspace says the card reached that target, whatever moved it there, so no alert
can outlive its target or come back if the card moves away again. A fulfilled command updates the
saved-status snapshot immediately, so a queued refusal in the same microtask chain sees that save
even before React renders it. Settlement tickets are kept per task as well, so answers batched
with another task cannot erase the signal that restores keyboard focus. If authoritative target
satisfaction removes a focused alert, focus returns to its card or column heading in the
same layout commit, before the canonical query is observable as settled; a later passive
effect would leave focus on the document in between. Unrelated focus is left alone. "Add a task" belongs to its column
rather than to a card, and a column adds one task at a time: while its call is out, and once that
call has been refused, the column's "Add a task" reads as unavailable (`aria-disabled`, and
`aria-busy` while the call is out) and does nothing, so the refusal keeps its place until the
user retries or dismisses it. Columns are independent of each other, and no add or move ever
clears another's alert, so several refusals can be on screen at once, each with its own Retry.
Retrying or dismissing an alert hands focus to what it was about — the card, its column's heading
once the card is off the board, or that column's "Add a task" — so the keyboard is never left on
the body, which is why that button is never `disabled` and can still take focus while it is
unavailable. Each alert names its own buttons (`Retry moving "…"`, `Dismiss: could not add a task
to Testing`) so that stacked alerts do not all read "Retry"; the visible labels, the Dismiss
tooltip included, stay as the design has them (`IconButton` takes a `title` of its own for that).

A failed load is built from the same parts in both views — the danger badge, the heading, the
detail line and a Retry carrying the design's refresh mark — each naming its own subject and
keeping its own content gutter. The board states the failure once: a rejection that carried no
message of its own is reported as `LOAD_FAILED_WITHOUT_DETAIL`, which says nothing the heading has
not already said, so the board leaves the detail line out rather than doubling it; the list's own
doubling is left as it was.

The board's own controls name the properties they animate rather than using `transition-colors`,
which in Tailwind v4 covers `outline-color` as well: the focus ring is `outline: 2px solid
var(--acc)`, so transitioning it would tween the ring up from the element's text colour instead
of showing the accent at once.

The board passes `applyStatus: false`, so every status is a column whatever the Status filter
says; the header count keeps describing the list's filters. Both are the design's behaviour.

The design can only be dragged. Two additions make the same move reachable without a pointer
drag: Shift+Left / Shift+Right on a focused card, announced through a polite live region, and
a row of move buttons that appears while the keyboard is inside a card and is always present
on a coarse pointer. At rest on a desktop the card is pixel-identical to the design, apart from
the hot P0 mark's colour (the sanctioned contrast fix under "Visual tests").

## Commands

```sh
npm run dev                  # needs NEXT_PUBLIC_API_URL
npm run test -- --coverage   # vitest + msw; fails under 80% coverage
npm run test:visual          # Playwright (Chromium): see below
npm run lint
npm run typecheck
npm run build                # needs NEXT_PUBLIC_API_URL (inlined at build time)
npm run gen:api -- http://localhost:8000/openapi.json  # use your OWN API URL; source is explicit
```

Real HTTP adapter contracts use `BT_HTTP_API_URL=<owned-api-url> npm run test:http`.
Optionally set `BT_HTTP_WEB_URL=<owned-http-web-url>` as well to execute the served-browser
query/focus regressions against that same stack. Neither suite starts a stack or selects an
endpoint by default. Use only an owned disposable database and the fake model provider:
these tests register example accounts and write ordinary authenticated test data. The
browser regression observes the canonical query's settled DOM boundary independently of
focus; it does not wait for a later render to make a lost-focus assertion pass.

With the unchanged default auth policy (10 attempts per IP per 60 seconds), all five checks
in one command overbook credential setup: the three adapter checks need eight attempts,
and the two served-browser checks need six. Select the groups separately with
`-- --grep-invert 'served query-backed board focus'` and
`-- --grep 'served query-backed board focus'`, respectively. Let the configured auth window
elapse after the first group finishes before starting the second, without concurrent
credential-heavy jobs on that API/IP. Honor any longer advertised `Retry-After` boundary.
Keep a 429 setup failure as a failure; do not count its unexecuted assertions, disable
throttling, or blanket-retry the suite. No test or application request retries automatically.

Any change to an API response model is followed by `npm run gen:api -- <your-api-url>/openapi.json`
in the same commit; the schema source is always given, the command has no default.

## Visual tests

`npm run test:visual` starts the app (port 47812 unless overridden, see below) and runs these suites from `visual/`:

- `responsive.visual.ts` needs nothing else: no horizontal page scroll from 375px to 1440px,
  the sidebar drawer and full-screen task panel at 375px, keyboard operation of the view
  switch, and no console error or warning across the shell's states.
- `shell.visual.ts` compares the app with the design, region by region (sidebar, header, filter
  toolbar, Attention strip) at 1440x900 and 1024x768, in two states reached by the same clicks
  on both sides. A region fails above 1% differing pixels, at a channel tolerance of 2/255.
  The design is not in this repository; point `BT_DESIGN_DIR` at the folder that holds
  `Ballast Tasks v2.dc.html` and `support.js`, or the suite skips itself:

  ```sh
  BT_DESIGN_DIR=/path/to/design-v2 npm run test:visual
  ```
- `tokens.visual.ts` checks the design tokens where they take effect, as computed styles. Without
  the design: the `rounded-bt*` utilities follow `--r` / `--r-sm` on all four corners, and the
  search placeholder is set in `--fg-3`. With `BT_DESIGN_DIR`: the skin's custom properties on
  the root element, the resolved colours, radii, shadows and type of shell elements, and the
  keyboard focus ring all equal the design's.
- `board.visual.ts` compares the board with the design at both desktop sizes: the whole
  board, one column, a card at rest, hovered and selected, a column highlighted as the drop
  target with the dragged card (a real mouse drag, held), the empty column, and a card with
  the hot P0 mark (its text is `--acc-fg`, not the design's white, for contrast). Same limits as
  the shell suite; needs `BT_DESIGN_DIR`. Measurements go to `board-report.json`.
- `board-behaviour.visual.ts` needs nothing else: a real mouse drag moves a card, Shift+Arrow
  moves the focused card and focus follows it, at 375px the columns scroll and snap inside the
  board with touch-sized move buttons and no page overflow, reduced motion stills the card,
  the hot P0 mark computes to `--acc-fg` on `--danger` at 4.5:1 or better, the board's move
  and "Add a task" controls transition neither `outline-color` nor `all`, and the console
  stays silent.
- `list.visual.ts` compares the list view with the design the same way (1% limit, 2/255
  tolerance): a default, hovered, selected, done, overdue and hot (P0 at risk) row, the quick-add,
  the empty state and the whole list region, at both sizes. For the selected row the task panel
  is hidden on both sides, because its backdrop covers the list. There are two sanctioned
  exceptions, both text colours where the design fails AA; for each, the untouched region is
  measured and reported while the app's colour and its contrast (at least 4.5:1) are asserted
  instead:
  - The quick-add placeholder: the design leaves it at the browser default (3.90:1) and the app
    sets it in `--fg-3` (5.29:1). The quick-add is compared twice, so its structure is still held
    to the limit with the placeholder made transparent on both sides.
  - The hot P0 pill: the design sets white on `--danger` (3.01:1) and the app sets `--acc-fg`
    (6.13:1). The row is still held to the limit; the pill alone is measured untouched.
- `projects.visual.ts` covers project creation, which the design has no reference for. At
  1440x900, 1024x768 and 375x812 it walks every state (closed, open, validation error, pending,
  created, empty project) and compares the regions the feature owns with the baselines committed
  in `visual/__screenshots__/`; a region fails above 1% differing pixels. It also drives the flow
  from the keyboard, checks the focus trap, reduced motion and the console, and audits computed
  styles so every colour, font, radius and shadow in the dialog and the empty state is a design
  token. After a deliberate visual change, re-record the baselines and the full-page screenshots
  next to them with `npx playwright test projects --update-snapshots`.
- `filters.visual.ts` needs no design: it measures each filter control's focus-ring geometry
  (the ring encloses the whole `Select`, label included) at 1440px and 375px, immediately under
  normal and reduced motion. It drives pointer focus, Tab, native type-ahead and Enter, plus
  `selectOption` for the application-level change contract, and asserts values, filtered rows
  and accessible names. It does not claim to automate the operating system's native popup:
  macOS popup arrows/Escape may not receive browser-automation input.
- `list.responsive.visual.ts` needs no design: at 375px every row reflows inside the viewport,
  and a keyboard pass over the list's states raises no console error or warning.
- `detail.visual.ts` compares the task panel with the design, region by region (header, banner,
  title, description, steps, attachments, activity, properties, footer), at both sizes, for a
  task with steps, attachments and comments, an empty new task, the drafting state, the proposed
  steps, and each property control open. Regions are clipped to what the panel's scroll area
  shows. A region holding a placeholder is compared twice: for structure with the placeholder
  glyphs transparent on both sides (1% limit), and untouched (reported, not limited), because
  placeholders are `--fg-3` here and the browser default in the design. Deliberate differences
  are listed in the suite's `DEVIATIONS`, each with its reason and its own measured ceiling (it
  is empty today). Needs `BT_DESIGN_DIR`; measurements go to `detail/report.json`.
- `step-editing.visual.ts` checks keyboard rename/cancel/save and exact move boundaries,
  that a hovered row's move controls neither cover nor reflow the title (including the wrapped
  one at 768px, where a click at the end of a line opens the rename editor and moves nothing),
  real browser touch taps with 44px non-overlapping targets at 375px, completion preservation,
  close/reopen, overflow and console silence. Screenshots go to `visual-results/step-editing/`;
  the existing `detail.visual.ts` still holds the untouched resting panel to its 1% limit.
- `detail-behaviour.visual.ts` needs no design: the panel is full-screen at 375px with a back
  control, nothing scrolls sideways from 375px to 1440px with every surface open, the keyboard
  path (Enter opens, Tab stays inside, Escape peels one layer, focus returns), placeholder
  colour and contrast, `prefers-reduced-motion`, and no console error or warning across every
  state of the panel. Two behaviours are checked with real gestures rather than assertions on
  the markup, because both turn on what the browser itself does: "Clear date" and "Keep" are
  activated by pointer and by native Tab traversal of the date's segments, and each must leave
  the focus back on the date box; and at 375px and 768px, with all four quick actions offered,
  every banner action is measured against the panel's own box and hit-tested at its centre,
  because the panel clips rather than scrolls, so an action past its edge draws nothing and
  takes no click while the page still reports no overflow.

Both servers are reused when already running. When two checkouts run the suite at once, give
each its own pair with `BT_VISUAL_APP_PORT` and `BT_VISUAL_DESIGN_PORT`, or they screenshot each
other's app.

Screenshots, diffs and each suite's measured percentages (the report file named in its entry
above) land in the git-ignored `visual-results/` (the panel's under `visual-results/detail/`).
Run `npx playwright install chromium` once beforehand.

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
