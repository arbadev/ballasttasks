// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiPerson, apiProject, apiTask } from "@/test/httpFixtures";
import { HttpTaskService } from "./httpTaskService";
import { HttpDirectoryService } from "./httpDirectoryService";
import { ProjectRejectedError, TaskNotFoundError } from "./types";

const base = "http://tasks.test";
const client = () => new ApiClient(base, { token: () => "test-token" });
const detail = (task = apiTask()) => server.use(
  http.get(`${base}/tasks/task-id`, () => HttpResponse.json(task)),
  http.get(`${base}/tasks/task-id/activity`, () => HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 })),
);

describe("HTTP task adapter", () => {
  it("loads every list page with all statuses and preserves keys/tallies without fake children", async () => {
    const pages: number[] = [];
    server.use(http.get(`${base}/tasks`, ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("status")).toBe("all");
      expect(url.searchParams.get("limit")).toBe("200");
      const offset = Number(url.searchParams.get("offset"));
      pages.push(offset);
      return HttpResponse.json({ items: [apiTask({ id: `t${offset}`, key: `IN-0${offset + 1}`, steps_total: 3, steps_done: 1, attachments_count: 2, status: "in_progress" })], total: 2, limit: 200, offset });
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
