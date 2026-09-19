# apps/web

Next.js (App Router, TypeScript, Tailwind) frontend. `/` is the Ballast Tasks application;
`/status` shows API, Database, Redis and AI (provider and model) health, and is linked from
the sidebar footer.

## Architecture

Dependencies point inwards; components never touch HTTP, the environment or a concrete service.

| Path | Responsibility |
| --- | --- |
| `src/app/providers.tsx` | Composition root: the only place a concrete service is constructed. Exports the hooks `useTaskService`, `useDirectoryService`, `useStepGenerationService`, `useClock`, `useHealthService`. |
| `src/app/globals.css` | The design tokens, once: the skin's CSS variables, mapped into the Tailwind theme (`bg-card`, `text-fg-3`, `rounded-bt`, `shadow-glow`, `animate-bt-in`, ...), plus base rules and the `bt-*` keyframes. Components use token names, never raw hex. |
| `src/lib/config.ts` | The only application module that reads `process.env` (the Playwright tooling reads its own variables: see "Visual tests"). Validates on load. |
| `src/lib/api/client.ts` | The only module that calls `fetch`. Throws a typed `ApiError`. |
| `src/lib/api/schema.d.ts` | Generated from the API's OpenAPI document. Never edited by hand. |
| `src/components/ui/` | Shared primitives: `Button`, `IconButton`, `Select`, `SegmentedControl`, `TextInput`, `Avatar`, `Pill`. No feature knowledge. |
| `src/features/tasks/model/` | Types and pure logic: due info, relative time, urgency, filtering, sorting, sidebar counts, Attention signals. Every function takes `now`; nothing reads the clock. |
| `src/features/tasks/services/` | `types.ts` holds the interfaces the UI depends on (`TaskService`, `DirectoryService`, `StepGenerationService`, `Clock`). The `inMemory*` files implement them over one shared store seeded from the design. |
| `src/features/tasks/workspace/` | One reducer plus its provider: scope, project, filters, Attention signal, sort, search, view, selected task, loaded tasks, load state. |
| `src/features/tasks/shell/` | Sidebar, header, filter toolbar, Attention strip, and `TasksApp`, which mounts the three views below. |
| `src/features/tasks/list/` | The list view. `rowView.ts` is the pure row model (due tone, rail, priority tone, stagger: every decision the design's `taskView` makes); `TaskRow`, `QuickAdd`, `ListSkeleton` and `ListLoadError` draw it; `ListView` wires them to the workspace and owns keyboard focus. |
| `src/features/tasks/board/` | The board view: the four status columns, the card, and the moves between them. See "The board" below. |
| `src/features/projects/` | Project creation: the rules for a name and key (`model/rules.ts`, pure), the "New project" control the sidebar mounts, its dialog, and the empty-project state the shell shows for a project with no tasks. Creates through `DirectoryService.createProject`, then `actions.addProject`. |
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
Saved tasks/projects are PostgreSQL data, independent of login persistence: sign in again
to retrieve them. No refresh tokens, cookie session or browser token storage is introduced.
Next development request logs exclude `/auth/callback`; deployment proxy/access logs must
also omit callback query strings. Real-vendor OAuth setup and primary-stack activation are
separate operator actions, not performed by the local fake-provider tests.

The HTTP workspace uses the API's filters, sorting, search and limit/offset pages (50 rows),
not client filtering over the first page. Page/filter changes discard stale requests;
mutations reload canonical query results and counts. Sidebar counts describe the whole
workspace; Attention counts describe open work in the selected project, as in the design.
Board queries ignore only the status filter, with per-column totals fetched from the API;
the header still describes the list's status filter. Pagination is across all columns.
Already-loaded views stay mounted during refresh (marked busy), preserving pending gestures
and focus. Full-scope column totals do not hide optimistic cards or imply every card is on
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

Due dates are calendar days, `YYYY-MM-DD` strings, not `Date` objects: the same arithmetic
and labels as the design, but serialisable and the shape an API date column has.

## Building on the shell

The shell mounts three views. Each is owned by one slice, which keeps whatever it needs
**inside its own folder**. The list and board are built (see "The board" below); the
detail panel is still a placeholder, replaced by its slice:

| Folder (owner) | Mounted as | Contents |
| --- | --- | --- |
| `src/features/tasks/list/` | `<ListView />` when the view is `list`, in every load state: it draws its own skeleton and load error | Built: the task rows and the quick-add input. |
| `src/features/tasks/board/` | `<BoardView />` when the view is `board`, in every load state; it shows its own loading skeleton and load error | Built: the four status columns, with drag, keyboard and touch moves. |
| `src/features/tasks/detail/` | `<TaskDetail />`, always mounted; renders when a task is selected | The side panel: fields, steps, generated steps, attachments, activity. |

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
| `addStep`, `toggleStep`, `removeStep` | same names | Detail steps. |
| `addComment(id, text)` | `addComment` | Detail activity. |
| `addAttachment(id, attachment)` | `addAttachment` | Link attachment with an absolute URL. |
| `uploadAttachment`, `downloadAttachment`, `removeAttachment` | same names | Optional capabilities for older demo doubles; HTTP implements all three. Upload/removal synchronize workspace state; download returns an authenticated blob, never a credential-bearing URL. |
| `remove(id)` | `remove` | Detail delete. Clears the selection if it was the selected task, and discards a step generation in flight for it. |
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
satisfaction removes a focused alert, focus returns to its card or column heading; unrelated
focus is left alone. "Add a task" belongs to its column
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

Any change to an API response model is followed by `npm run gen:api` in the same commit.

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

Both servers are reused when already running. When two checkouts run the suite at once, give
each its own pair with `BT_VISUAL_APP_PORT` and `BT_VISUAL_DESIGN_PORT`, or they screenshot each
other's app.

Screenshots, diffs and each suite's measured percentages (the report file named in its entry
above) land in the git-ignored `visual-results/`. Run `npx playwright install chromium` once beforehand.

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
