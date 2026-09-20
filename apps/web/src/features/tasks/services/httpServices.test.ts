// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiPerson, apiProject, apiTask, apiTaskPage } from "@/test/httpFixtures";
import { HttpTaskService } from "./httpTaskService";
import { HttpDirectoryService } from "./httpDirectoryService";
import { ProjectRejectedError, TaskNotFoundError } from "./types";
import { DEFAULT_QUERY } from "../model/filter";

const base = "http://tasks.test";
const client = () => new ApiClient(base, { token: () => "test-token" });
const detail = (task = apiTask()) => server.use(
  http.get(`${base}/tasks/task-id`, () => HttpResponse.json(task)),
  http.get(`${base}/tasks/task-id/activity`, () => HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 })),
);

describe("HTTP task adapter", () => {
  it("sends filters, sort, search and offsets to the API and uses full-workspace summary counts", async () => {
    server.use(
      http.get(`${base}/tasks`, ({ request }) => {
        expect(Object.fromEntries(new URL(request.url).searchParams)).toEqual({ scope: "mine", project_id: "project-id", status: "in_progress", due: "week", priority: "P0", q: "hello %_", signal: "needs_owner", sort: "due_date", limit: "50", offset: "50" });
        return HttpResponse.json(apiTaskPage([apiTask()], { total: 123, offset: 50, statusTotals: { in_progress: 123 } }));
      }),
      http.get(`${base}/tasks/summary`, ({ request }) => {
        expect(Object.fromEntries(new URL(request.url).searchParams)).toEqual({ project_id: "project-id" });
        return HttpResponse.json({ counts: { all: 300, mine: 200, overdue: 10 }, projects: [apiProject], signals: { overdue: 5, p0_at_risk: 3, due_soon: 4, needs_owner: 6 } });
      }),
    );
    const page = await new HttpTaskService(client()).query({ query: { ...DEFAULT_QUERY, scope: "mine", project: "project-id", status: "progress", due: "week", priority: "0", search: " hello %_ ", signal: "unassigned" }, sort: "due", board: false, offset: 50 });
    expect(page).toMatchObject({ total: 123, headerTotal: 123, offset: 50, limit: 50, projectHasTasks: true, sidebar: { all: 300, mine: 200, overdue: 10, byProject: { "project-id": 1 } }, signals: { overdue: 5, critical: 3, soon: 4, unassigned: 6 } });
    expect(page.tasks).toHaveLength(1);
  });

  it("ignores only status on the board, takes column/header totals from the list and detects done-only projects", async () => {
    const statusTotals = { todo: 6, in_progress: 4, testing: 3, done: 8 };
    server.use(
      http.get(`${base}/tasks`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        if (!params.has("q")) {
          expect(params.get("status")).toBe("all");
          return HttpResponse.json(apiTaskPage([apiTask({ status: "done" })], { total: 8, limit: 1, statusTotals: { done: 8 } }));
        }
        expect(params.get("q")).toBe("needle");
        expect(params.get("status")).toBe("all");
        return HttpResponse.json(apiTaskPage([], { total: 21, limit: Number(params.get("limit")), statusTotals }));
      }),
      http.get(`${base}/tasks/summary`, () => HttpResponse.json({ counts: { all: 0, mine: 0, overdue: 0 }, projects: [{ ...apiProject, open_tasks: 0 }], signals: { overdue: 0, p0_at_risk: 0, due_soon: 0, needs_owner: 0 } })),
    );
    const page = await new HttpTaskService(client()).query({ query: { ...DEFAULT_QUERY, project: "project-id", search: "needle" }, sort: "importance", board: true, offset: 0 });
    expect(page).toMatchObject({ total: 21, headerTotal: 13, columns: { todo: 6, progress: 4, testing: 3, done: 8 }, projectHasTasks: true });
  });

  it("reads full board column totals from one list request, on a page that holds them all and on a paginated one", async () => {
    const listed: string[] = [];
    const rows = Array.from({ length: 60 }, (_, index) => apiTask({ id: `t${index}`, status: index % 3 === 0 ? "testing" : "todo" }));
    const statusTotals = { todo: 40, in_progress: 0, testing: 20, done: 0 };
    server.use(
      http.get(`${base}/tasks`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        listed.push(`status=${params.get("status")}&limit=${params.get("limit")}`);
        const limit = Number(params.get("limit"));
        const offset = Number(params.get("offset"));
        return HttpResponse.json(apiTaskPage(rows.slice(offset, offset + limit), { total: rows.length, limit, offset, statusTotals }));
      }),
      http.get(`${base}/tasks/summary`, () => HttpResponse.json({ counts: { all: 60, mine: 0, overdue: 0 }, projects: [apiProject], signals: { overdue: 0, p0_at_risk: 0, due_soon: 0, needs_owner: 0 } })),
    );
    const service = new HttpTaskService(client());
    const request = { query: DEFAULT_QUERY, sort: "importance", board: true, offset: 0 } as const;

    // 60 matching rows do not fit the 50-row page the workspace asks for.
    const paginated = await service.query(request);
    expect(paginated.tasks).toHaveLength(50);
    expect(paginated.total).toBe(60);
    expect(paginated.columns).toEqual({ todo: 40, progress: 0, testing: 20, done: 0 });
    expect(paginated.headerTotal).toBe(60);
    expect(listed).toEqual(["status=all&limit=50"]);

    listed.length = 0;
    const whole = await service.query({ ...request, limit: 200 });
    expect(whole.columns).toEqual({ todo: 40, progress: 0, testing: 20, done: 0 });
    expect(listed).toEqual(["status=all&limit=200"]);
  });

  it("spends five requests on a board save and its canonical refresh", async () => {
    const requests: string[] = [];
    const row = apiTask({ status: "todo" });
    server.use(
      http.patch(`${base}/tasks/task-id`, () => { requests.push("PATCH /tasks/task-id"); return HttpResponse.json(row); }),
      http.get(`${base}/tasks/task-id`, () => { requests.push("GET /tasks/task-id"); return HttpResponse.json(row); }),
      http.get(`${base}/tasks/task-id/activity`, () => { requests.push("GET /tasks/task-id/activity"); return HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }); }),
      http.get(`${base}/tasks`, ({ request }) => {
        requests.push(`GET /tasks?status=${new URL(request.url).searchParams.get("status")}`);
        return HttpResponse.json(apiTaskPage([row]));
      }),
      http.get(`${base}/tasks/summary`, () => { requests.push("GET /tasks/summary"); return HttpResponse.json({ counts: { all: 1, mine: 0, overdue: 0 }, projects: [apiProject], signals: { overdue: 0, p0_at_risk: 0, due_soon: 0, needs_owner: 0 } }); }),
    );
    const service = new HttpTaskService(client());
    const saved = await service.update("task-id", { title: "Edited" });
    expect(saved.detailLoaded).toBe(true);
    const page = await service.query({ query: DEFAULT_QUERY, sort: "importance", board: true, offset: 0 });
    expect(page.columns).toEqual({ todo: 1, progress: 0, testing: 0, done: 0 });
    expect(requests).toHaveLength(5);
    expect(requests.filter((call) => call.startsWith("GET /tasks?"))).toEqual(["GET /tasks?status=all"]);
  });

  it("orders read-only recovery after another outstanding write to the same task", async () => {
    let release!: () => void;
    let started!: () => void;
    const wait = new Promise<void>((resolve) => { release = resolve; });
    const ready = new Promise<void>((resolve) => { started = resolve; });
    let title = "Before";
    const reads: string[] = [];
    server.use(
      http.patch(`${base}/tasks/task-id`, async () => {
        started();
        await wait;
        title = "Saved newest title";
        return HttpResponse.json(apiTask({ title }));
      }),
      http.get(`${base}/tasks/task-id`, () => {
        reads.push(title);
        return HttpResponse.json(apiTask({ title }));
      }),
      http.get(`${base}/tasks/task-id/activity`, () => HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 })),
    );
    const service = new HttpTaskService(client());
    const writing = service.update("task-id", { title: "Saved newest title" });
    await ready;
    const recovering = service.refresh("task-id");
    await Promise.resolve();
    expect(reads).toEqual([]);
    release();
    await writing;
    expect(await recovering).toMatchObject({ title: "Saved newest title" });
    expect(reads).toEqual(["Saved newest title", "Saved newest title"]);
  });

  it("loads every list page with all statuses and preserves keys/tallies without fake children", async () => {
    const pages: number[] = [];
    server.use(http.get(`${base}/tasks`, ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("status")).toBe("all");
      expect(url.searchParams.get("limit")).toBe("200");
      const offset = Number(url.searchParams.get("offset"));
      pages.push(offset);
      return HttpResponse.json(apiTaskPage([apiTask({ id: `t${offset}`, key: `IN-0${offset + 1}`, steps_total: 3, steps_done: 1, attachments_count: 2, status: "in_progress" })], { total: 2, limit: 200, offset, statusTotals: { in_progress: 2 } }));
    }));
    const tasks = await new HttpTaskService(client()).list();
    expect(pages).toEqual([0, 1]);
    expect(tasks).toHaveLength(2);
    expect(tasks[0]).toMatchObject({ key: "IN-01", status: "progress", steps: [], attachments: [], detailLoaded: false, tally: { steps: 3, done: 1, attachments: 2, comments: 0 } });
  });

  it("gets detail and every activity page in chronological UI order", async () => {
    detail(apiTask({ steps: [{ id: "s1", task_id: "task-id", title: "Do this", done: false, position: 0, created_at: "2026-09-19T00:00:00Z" }] }));
    server.use(http.get(`${base}/tasks/task-id/activity`, ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      return HttpResponse.json({ items: [{ id: `a${offset}`, task_id: "task-id", kind: "comment", actor: apiPerson, text: offset ? "older" : "newer", created_at: "2026-09-19T00:00:00Z" }], total: 2, limit: 200, offset });
    }));
    const task = await new HttpTaskService(client()).get("task-id");
    expect(task?.detailLoaded).toBe(true);
    expect(task?.steps).toEqual([{ id: "s1", text: "Do this", done: false }]);
    expect(task?.activity.map((a) => a.text)).toEqual(["older", "newer"]);
  });

  it("omits the Inbox sentinel on create and maps dates/assignment/priority on patch", async () => {
    detail();
    server.use(
      http.post(`${base}/tasks`, async ({ request }) => {
        expect(await request.json()).toEqual({ title: "Created", status: "in_progress" });
        return HttpResponse.json(apiTask(), { status: 201 });
      }),
      http.patch(`${base}/tasks/task-id`, async ({ request }) => {
        expect(await request.json()).toEqual({ due_date: null, assignee_id: "user-id", priority: "P0", description: "Description" });
        return HttpResponse.json(apiTask({ due_date: null, assignee_id: "user-id", priority: "P0", description: "Description" }));
      }),
    );
    const service = new HttpTaskService(client());
    expect((await service.create({ title: "Created", status: "progress", project: "inbox" })).id).toBe("task-id");
    await service.update("task-id", { due: null, assignee: "user-id", prio: 0, description: "Description" }, "legacy note must not be sent");
  });

  it("maps missing tasks consistently and does not swallow network/server failures", async () => {
    const service = new HttpTaskService(client());
    server.use(http.get(`${base}/tasks/missing`, () => new HttpResponse(null, { status: 404 })));
    expect(await service.get("missing")).toBeNull();
    server.use(http.patch(`${base}/tasks/missing`, () => new HttpResponse(null, { status: 404 })));
    await expect(service.move("missing", "done")).rejects.toBeInstanceOf(TaskNotFoundError);
    server.use(http.get(`${base}/tasks/missing`, () => new HttpResponse(null, { status: 503 })));
    await expect(service.get("missing")).rejects.toMatchObject({ status: 503 });
  });

  it("uses one atomic bulk request and does not retry a refused batch", async () => {
    const handler = vi.fn(async ({ request }: { request: Request }) => {
      expect(await request.json()).toEqual({ titles: ["one", "two"] });
      return HttpResponse.json({ detail: "step limit" }, { status: 422 });
    });
    server.use(http.post(`${base}/tasks/task-id/steps/bulk`, handler));
    await expect(new HttpTaskService(client()).acceptSteps("task-id", ["one", "two"])).rejects.toMatchObject({ status: 422 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("uploads original bytes passed by the delivered panel's addAttachment contract", async () => {
    detail();
    const upload = vi.fn(async ({ request }: { request: Request }) => {
      const file = (await request.formData()).get("file") as File;
      expect(file.name).toBe("panel.pdf");
      expect(await file.text()).toBe("%PDF-panel");
      return HttpResponse.json({}, { status: 201 });
    });
    server.use(http.post(`${base}/tasks/task-id/attachments/files`, upload));
    await new HttpTaskService(client()).addAttachment("task-id", { kind: "pdf", name: "panel.pdf", meta: "PDF" }, new File(["%PDF-panel"], "panel.pdf", { type: "application/pdf" }));
    expect(upload).toHaveBeenCalledOnce();
  });

  it("sends actual link URLs, uploads files, and retrieves authenticated bytes", async () => {
    detail();
    server.use(
      http.post(`${base}/tasks/task-id/attachments/links`, async ({ request }) => {
        expect(await request.json()).toEqual({ name: "Docs", url: "https://example.test/docs" });
        return HttpResponse.json({}, { status: 201 });
      }),
      http.post(`${base}/tasks/task-id/attachments/files`, async ({ request }) => {
        const file = (await request.formData()).get("file") as File;
        expect(file.name).toBe("test.pdf");
        expect(await file.text()).toBe("%PDF-test");
        return HttpResponse.json({}, { status: 201 });
      }),
      http.get(`${base}/tasks/task-id/attachments/file-id/content`, ({ request }) => {
        expect(request.headers.get("Authorization")).toBe("Bearer test-token");
        return new HttpResponse("%PDF-test");
      }),
    );
    const service = new HttpTaskService(client());
    await service.addAttachment("task-id", { kind: "link", name: "Docs", meta: "example.test", url: "https://example.test/docs" });
    await service.uploadAttachment("task-id", new File(["%PDF-test"], "test.pdf"));
    expect(await (await service.downloadAttachment("task-id", "file-id")).text()).toBe("%PDF-test");
  });
});

describe("HTTP directory adapter", () => {
  it("maps people/current caller/projects and creates using API color tokens", async () => {
    server.use(
      http.get(`${base}/users`, () => HttpResponse.json({ items: [apiPerson] })),
      http.get(`${base}/auth/me`, () => HttpResponse.json(apiPerson)),
      http.get(`${base}/projects`, () => HttpResponse.json({ items: [apiProject] })),
      http.post(`${base}/projects`, async ({ request }) => {
        expect(await request.json()).toEqual({ name: "Inbox", key: "IN", color: "acc" });
        return HttpResponse.json(apiProject, { status: 201 });
      }),
    );
    const service = new HttpDirectoryService(client());
    expect(await service.people()).toEqual([{ id: "user-id", name: "Test Person", initials: "TP", role: "" }]);
    expect(await service.currentUser()).toEqual((await service.people())[0]);
    expect(await service.createProject({ name: "Inbox", key: "IN", tone: "accent" })).toEqual((await service.projects())[0]);
  });

  it("translates duplicate keys to the existing field error seam", async () => {
    server.use(http.post(`${base}/projects`, () => HttpResponse.json({}, { status: 409 })));
    const pending = new HttpDirectoryService(client()).createProject({ name: "Inbox", key: "IN", tone: "accent" });
    await expect(pending).rejects.toBeInstanceOf(ProjectRejectedError);
    await expect(pending).rejects.toMatchObject({ errors: { key: expect.any(String) } });
  });
});
