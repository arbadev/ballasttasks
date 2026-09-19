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
| `src/lib/config.ts` | The only application module that reads `process.env` (the Playwright tooling reads its own `BT_DESIGN_DIR`). Validates on load. |
| `src/lib/api/client.ts` | The only module that calls `fetch`. Throws a typed `ApiError`. |
| `src/lib/api/schema.d.ts` | Generated from the API's OpenAPI document. Never edited by hand. |
| `src/components/ui/` | Shared primitives: `Button`, `IconButton`, `Select`, `SegmentedControl`, `TextInput`, `Avatar`, `Pill`. No feature knowledge. |
| `src/features/tasks/model/` | Types and pure logic: due info, relative time, urgency, filtering, sorting, sidebar counts, Attention signals. Every function takes `now`; nothing reads the clock. |
| `src/features/tasks/services/` | `types.ts` holds the interfaces the UI depends on (`TaskService`, `DirectoryService`, `StepGenerationService`, `Clock`). The `inMemory*` files implement them over one shared store seeded from the design. |
| `src/features/tasks/workspace/` | One reducer plus its provider: scope, project, filters, Attention signal, sort, search, view, selected task, loaded tasks, load state. |
| `src/features/tasks/shell/` | Sidebar, header, filter toolbar, Attention strip, and `TasksApp`, which mounts the three views below. |
| `src/features/health/` | `HealthService` and the `StatusCard` behind `/status`. |
| `src/test/` | Test infrastructure: `makeTask`/`due`/`NOW`, fake services that record calls, `renderWithServices`. |

The two "only module" rules are enforced by ESLint (`eslint.config.mjs`), not by convention.
Icons come from `lucide-react`, the design system's icon set.

The task services are in-memory for now. An HTTP-backed `TaskService` is a new class plus one
line in `providers.tsx`; no component changes, because none of them knows which one it has.

Due dates are calendar days, `YYYY-MM-DD` strings, not `Date` objects: the same arithmetic
and labels as the design, but serialisable and the shape an API date column has.

## Building on the shell

The shell already mounts three placeholders. Each is owned by one follow-up slice, which
replaces the file's contents and adds whatever else it needs **inside its own folder**:

| Folder (owner) | Mounted as | Replace the placeholder with |
| --- | --- | --- |
| `src/features/tasks/list/` | `<ListView />` when the view is `list` | The task rows and the quick-add input. |
| `src/features/tasks/board/` | `<BoardView />` when the view is `board` | The four status columns with drag between them. |
| `src/features/tasks/detail/` | `<TaskDetail />`, always mounted; renders when a task is selected | The side panel: fields, steps, generated steps, attachments, activity. |

Everything else (`model/`, `services/`, `workspace/`, `shell/`, `components/ui/`) is shared.
If a slice needs a change there, keep it additive (a new export, a new prop with a default)
so the other two slices are unaffected.

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
| `selectScope`, `toggleProject`, `setStatusFilter`, `setDueFilter`, `setPriorityFilter`, `setSort`, `setSearch`, `toggleSignal`, `clearSignal`, `setView`, `reload` | The shell. Available to the views, rarely needed. |

**Task commands** (`useTaskCommands()`): each calls `TaskService` and then puts the saved task
back into the workspace, so counts, signals and every view update together. Call these rather
than `useTaskService()` directly.

| Command | Service method | Used by |
| --- | --- | --- |
| `create({ title, status? }, { open? })` | `create` | List quick-add (`open` false); board column "add" (`status`, `open` true). Goes into the selected project, or the Inbox. |
| `toggleDone(id)` | `toggleDone` | List and board checkboxes; detail "Mark complete" / "Reopen". |
| `move(id, status)` | `move` | Board drop; detail status select. |
| `update(id, patch, note?)` | `update` | Detail fields. An assignee change logs itself; pass `note` for the quick actions ("Due date moved to tomorrow"). |
| `addStep`, `toggleStep`, `removeStep` | same names | Detail steps. |
| `addComment(id, text)` | `addComment` | Detail activity. |
| `addAttachment(id, attachment)` | `addAttachment` | Detail attachments. |
| `remove(id)` | `remove` | Detail delete. Clears the selection if it was the selected task, and discards a step generation in flight for it. |
| `sync(task)` | none | Detail, after `StepGenerationService.accept()` resolves with the updated task. |

**Step generation** (`useStepGenerationService()` from `@/app/providers`): `start(taskId)`,
`subscribe(listener)` and `current()` to observe `running` then `proposed`, `removeProposed(stepId)`,
`accept()` (then `commands.sync(task)`), `discard()`.

**Testing a view**: `renderWithServices(<YourView />, { tasks })` from `src/test/` gives fake
services, the design's seed and a fixed clock (`NOW`, Friday 18 September 2026); wrap the view in
`WorkspaceProvider`, or render `<TasksApp />` to drive it through the real shell.
`FakeTaskService.calls` records what the UI asked for.

## The board

`src/features/tasks/board/` is the board view, built from the design's markup and `taskView` rules.

| File | Responsibility |
| --- | --- |
| `BoardView.tsx` | The view: its own loading skeleton and load error, then the four columns. Holds the drag state and puts focus back on a card moved from the keyboard. |
| `useBoardMoves.ts` | Optimistic moves over `useTaskCommands().move`: the card changes column at once, a rejected move puts it back and is reported with a retry, and an older answer never undoes a newer move. |
| `cardView.ts` | Pure: everything a card shows (due chip tone and mark, rail, priority tone, step and attachment labels), from `urgency` and `dueInfo`. |
| `TaskCard.tsx`, `BoardColumn.tsx`, `BoardSkeleton.tsx`, `BoardAlert.tsx` | Presentation only. `layout.ts` is the grid the board and its skeleton share. |

The board passes `applyStatus: false`, so every status is a column whatever the Status filter
says; the header count keeps describing the list's filters. Both are the design's behaviour.

The design can only be dragged. Two additions make the same move reachable without a pointer
drag: Shift+Left / Shift+Right on a focused card, announced through a polite live region, and
a row of move buttons that appears while the keyboard is inside a card and is always present
on a coarse pointer. At rest on a desktop the card is pixel-identical to the design.

## Commands

```sh
npm run dev                  # needs NEXT_PUBLIC_API_URL
npm run test -- --coverage   # vitest + msw; fails under 80% coverage
npm run test:visual          # Playwright (Chromium): see below
npm run lint
npm run typecheck
npm run build                # needs NEXT_PUBLIC_API_URL (inlined at build time)
npm run gen:api              # regenerate schema.d.ts from http://localhost:8000/openapi.json
```

Any change to an API response model is followed by `npm run gen:api` in the same commit.

## Visual tests

`npm run test:visual` starts the app on port 47812 and runs the suites in `visual/`:

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
  target with the dragged card (a real mouse drag, held), and the empty column. Same limits as
  the shell suite; needs `BT_DESIGN_DIR`. Measurements go to `board-report.json`.
- `board-behaviour.visual.ts` needs nothing else: a real mouse drag moves a card, Shift+Arrow
  moves the focused card and focus follows it, at 375px the columns scroll and snap inside the
  board with touch-sized move buttons and no page overflow, reduced motion stills the card,
  and the console stays silent.

Screenshots, diffs and `report.json` (the measured percentages) land in the git-ignored
`visual-results/`. Run `npx playwright install chromium` once beforehand.

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
