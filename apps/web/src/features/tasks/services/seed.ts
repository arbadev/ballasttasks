import { dayFrom } from "../model/due";
import type { ActivityEntry, Attachment, Person, Project, Step, Task } from "../model/types";

export const CURRENT_USER_ID = "ab";

export const SEED_PEOPLE: readonly Person[] = [
  { id: "ab", name: "Andres Barradas", initials: "AB", role: "owner" },
  { id: "lm", name: "Lucía Marín", initials: "LM", role: "backend" },
  { id: "tr", name: "Tomás Rey", initials: "TR", role: "frontend" },
  { id: "ai", name: "Assistant", initials: "AI", role: "system" },
];

export const SEED_PROJECTS: readonly Project[] = [
  { id: "ballast", name: "Ballast Tasks", key: "BT", tone: "accent" },
  { id: "inbox", name: "Inbox", key: "IN", tone: "muted" },
];

type SeedTask = Omit<Partial<Task>, "createdAt" | "updatedAt"> &
  Pick<Task, "id" | "title" | "status" | "project" | "prio" | "importance"> & { created?: number; updated?: number };

/**
 * The design's sixteen seed tasks, dated relative to `now`. The entries below are the
 * design's own `mk({...})` literals, copied verbatim (hence the single quotes) so the data
 * cannot drift from the reference; the helpers around them carry the same names.
 */
export function seedTasks(now: number): Task[] {
  let seq = 100;
  const day = (n: number) => dayFrom(n, now);
  const ago = (d: number, h = 0) => now - d * 864e5 - h * 36e5;
  const st = (text: string, done = false): Step => ({ id: `s${++seq}`, text, done });
  const log = (who: string, text: string, d: number, h?: number): ActivityEntry => ({ type: "log", who, text, at: ago(d, h) });
  const say = (who: string, text: string, d: number, h?: number): ActivityEntry => ({ type: "comment", who, text, at: ago(d, h) });
  const pdf: Attachment = { kind: "pdf", name: "Python - BLA - Technical Interview Exercise - V2.pdf", meta: "PDF · 3 pages · 84 KB" };
  const mk = ({ created = 3, updated = 1, ...o }: SeedTask): Task => ({
    description: "",
    assignee: null,
    due: null,
    steps: [],
    attachments: [],
    activity: [],
    ...o,
    createdAt: ago(created),
    updatedAt: ago(updated),
  });

  // prettier-ignore
  return [
    mk({ id: 't1', title: 'Task CRUD endpoints with pagination and filters', status: 'progress', project: 'ballast', assignee: 'ab', due: day(3), prio: 0, importance: 95, created: 4, updated: 0.8,
      description: 'FastAPI routes under /tasks. Filter by status and due date, paginate with limit/offset. The Pydantic models own the contract — run npm run gen:api after every change.',
      steps: [st('Task entity and TaskStatus enum in domain', true), st('TaskRepository port + in-memory fake, contract suite', true), st('Use cases: create, list (limit/offset), update, delete', true), st('Routes under /tasks with status, due_before, due_after filters'), st('Alembic migration for the tasks table'), st('npm run gen:api and fix the frontend types in the same commit')],
      attachments: [pdf, { kind: 'link', name: 'Swagger UI', meta: 'localhost:8000/docs' }],
      activity: [log('ab', 'Created the task', 4), log('ab', 'Moved To Do → In Progress', 2), say('lm', 'The exercise says "filter by due date" — I would accept due_before and due_after so the panel cannot ask for a range we do not have.', 1, 3), log('ai', 'Drafted 6 steps · added by Andres', 1), say('ab', 'Agreed. Pagination stays limit/offset; cursor pagination is a non-goal for this scope.', 0, 20)] }),
    mk({ id: 't2', title: 'Next.js task list and board', status: 'progress', project: 'ballast', assignee: 'ab', due: day(7), prio: 0, importance: 85, created: 3, updated: 1,
      description: 'List and Kanban views over the same query. Components read TaskService from providers.tsx; nothing outside client.ts calls fetch.',
      steps: [st('TaskService interface + HttpTaskService over client.ts', true), st('List view with due-date and priority filters'), st('Board view with drag between statuses'), st('Task detail panel with steps and attachments'), st('Vitest: render with a fake TaskService')],
      attachments: [{ kind: 'image', name: 'vectal-board-reference.png', meta: 'PNG · 1514×856' }, { kind: 'image', name: 'vectal-list-reference.png', meta: 'PNG · 2562×1456' }],
      activity: [log('ab', 'Created the task', 3), say('tr', 'Board columns should come from the API TaskStatus enum so the frontend never invents a state.', 1)] }),
    mk({ id: 't3', title: 'Generate-steps job: Celery worker + LanguageModel port', status: 'progress', project: 'ballast', assignee: 'tr', due: day(5), prio: 1, importance: 70, created: 2, updated: 1,
      description: 'POST /tasks/{id}/steps:generate enqueues a job; the worker calls LanguageModel.generate and stores proposed steps. The UI polls until the job settles.',
      steps: [st('Job payload and result schema'), st('Prompt template from title, description and attachments'), st('GET /jobs/{id} to poll'), st('Fake provider returns deterministic steps for tests')],
      attachments: [{ kind: 'link', name: 'docs/architecture.md#ports', meta: 'github.com/arbadev/ballasttasks' }],
      activity: [log('tr', 'Created the task', 2)] }),
    mk({ id: 't4', title: 'JWT authentication', status: 'todo', project: 'ballast', due: day(4), prio: 0, importance: 90, created: 4, updated: 4,
      description: 'Register and login, access + refresh tokens, and a current_user dependency on every /tasks route. The panel will ask about expiry and where the token lives in the browser.',
      activity: [log('ab', 'Created the task', 4)] }),
    mk({ id: 't5', title: 'Write PRD.md: overview, user stories, scope', status: 'todo', project: 'ballast', assignee: 'ab', due: day(-2), prio: 1, importance: 75, created: 6, updated: 3,
      description: 'docs/PRD.md is headings only. Fill overview, user stories and in-scope / non-goals before the CRUD slice lands, so the demo story matches the code.',
      steps: [st('Overview and the one-line user story'), st('In scope vs non-goals (no teams, no recurring tasks)'), st('Functional requirements mapped to endpoints')],
      attachments: [pdf],
      activity: [log('ab', 'Created the task', 6)] }),
    mk({ id: 't6', title: 'Seed data and demo credentials', status: 'todo', project: 'ballast', assignee: 'lm', due: day(8), prio: 1, importance: 70, created: 3, updated: 3,
      description: 'Demo credentials and a dozen tasks across every status, so the panel sees a populated board on first run.',
      activity: [log('lm', 'Created the task', 3)] }),
    mk({ id: 't7', title: 'Rate limiting on the API', status: 'todo', project: 'ballast', prio: 2, importance: 55, created: 3, updated: 3,
      description: 'Behind a RateLimiter port, so the Redis token bucket is swappable for an in-memory fake in tests.',
      activity: [log('ab', 'Created the task', 3)] }),
    mk({ id: 't8', title: 'GenAI write-up: prompt, validation, corrections', status: 'todo', project: 'ballast', assignee: 'ab', due: day(10), prio: 1, importance: 75, created: 2, updated: 2,
      description: 'docs/ai-usage.md: the scaffold prompt, a representative sample of the output, how it was validated and what was corrected.',
      steps: [st('Paste the scaffold prompt'), st('Pick a representative sample of generated code'), st('List the corrections and why'), st('Edge cases: auth, validation, performance')],
      attachments: [{ kind: 'link', name: 'docs/ai-usage.md', meta: 'github.com/arbadev/ballasttasks' }],
      activity: [log('ab', 'Created the task', 2)] }),
    mk({ id: 't9', title: 'Presentation and code-review walkthrough', status: 'todo', project: 'ballast', assignee: 'ab', due: day(13), prio: 1, importance: 80, created: 2, updated: 2,
      description: 'Twelve minutes: user story, architecture, live demo, GenAI usage. Then the code review — have bootstrap.py, the ports and TaskService ready to open.',
      activity: [log('ab', 'Created the task', 2)] }),
    mk({ id: 't10', title: 'Unit tests at 80% coverage or more', status: 'testing', project: 'ballast', assignee: 'lm', due: day(4), prio: 1, importance: 65, created: 5, updated: 0.5,
      description: 'pytest --cov on the API, vitest --coverage on the web. Contract suites parametrised over every adapter of a port.',
      steps: [st('Contract suite for TaskRepository (fake + PostgreSQL)', true), st('API tests for 200 / 404 / 422 on /tasks', true), st('Frontend: StatusCard and TaskList with fake services')],
      activity: [log('lm', 'Created the task', 5), log('lm', 'Moved In Progress → Testing', 0, 12)] }),
    mk({ id: 't11', title: 'Docker compose: five services from .env.example', status: 'testing', project: 'ballast', assignee: 'tr', due: day(1), prio: 2, importance: 50, created: 5, updated: 1,
      description: 'cp .env.example .env && docker compose up --build must be the whole setup.',
      steps: [st('Healthchecks on db and redis before api starts', true), st('Web image takes NEXT_PUBLIC_API_URL as a build arg')],
      activity: [log('tr', 'Created the task', 5), log('tr', 'Moved In Progress → Testing', 1)] }),
    mk({ id: 't12', title: 'Monorepo foundation and health endpoints', status: 'done', project: 'ballast', assignee: 'ab', due: day(-6), prio: 0, importance: 90, created: 12, updated: 6,
      steps: [st('/health and /health/ready with the pinned contract', true), st('Celery worker wired through the JobQueue port', true), st('StatusCard reads HealthService from providers.tsx', true)],
      activity: [log('ab', 'Created the task', 12), log('ab', 'Moved Testing → Done', 6)] }),
    mk({ id: 't13', title: 'ADR 0002: ports and adapters', status: 'done', project: 'ballast', assignee: 'ab', due: day(-8), prio: 2, importance: 60, created: 11, updated: 8,
      activity: [log('ab', 'Created the task', 11), log('ab', 'Moved In Progress → Done', 8)] }),
    mk({ id: 't14', title: 'Pre-commit: ruff, mypy, import-linter', status: 'done', project: 'ballast', assignee: 'tr', due: day(-7), prio: 3, importance: 40, created: 10, updated: 7,
      activity: [log('tr', 'Created the task', 10), log('tr', 'Moved In Progress → Done', 7)] }),
    mk({ id: 't15', title: 'Review Vectal task detail for assistant patterns', status: 'todo', project: 'inbox', assignee: 'ab', prio: 3, importance: 30, created: 1, updated: 1,
      attachments: [{ kind: 'image', name: 'vectal-task-detail.png', meta: 'PNG · 2560×1456' }, { kind: 'link', name: 'vectal.ai', meta: 'Generate Steps, AI Toolkit' }],
      activity: [log('ab', 'Created the task', 1)] }),
    mk({ id: 't16', title: 'Confirm the panel slot with the recruiter', status: 'todo', project: 'inbox', assignee: 'ab', due: day(0), prio: 1, importance: 70, created: 1, updated: 1,
      activity: [log('ab', 'Created the task', 1)] }),
  ];
}
