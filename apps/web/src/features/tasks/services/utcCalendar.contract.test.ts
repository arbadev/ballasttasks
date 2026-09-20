// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiTask } from "@/test/httpFixtures";
import { makeTask } from "@/test/tasks";
import { DEFAULT_QUERY, selectTasks } from "../model/filter";
import { rowView } from "../list/rowView";
import { cardView } from "../board/cardView";
import { dayFrom } from "../model/due";
import { urgency } from "../model/urgency";
import { HttpTaskService } from "./httpTaskService";
import { InMemoryTaskService } from "./inMemoryTaskService";
import { InMemoryTaskStore } from "./inMemoryTaskStore";

const now = Date.parse("2026-09-19T19:56:08-05:00");
const base = "http://utc-calendar.test";

const modes = [
  { name: "explicit demo", setup: () => ({ service: new InMemoryTaskService(new InMemoryTaskStore(() => now)), id: "t4" }) },
  { name: "HTTP adapter", setup: () => {
    let row = apiTask({ due_date: "2026-09-24", priority: "P0", importance: 90, assignee_id: null });
    server.use(
      http.get(`${base}/tasks/task-id`, () => HttpResponse.json(row)),
      http.get(`${base}/tasks/task-id/activity`, () => HttpResponse.json({ items: [], total: 0, offset: 0, limit: 200 })),
      http.patch(`${base}/tasks/task-id`, async ({ request }) => {
        const body = await request.json() as { due_date: string | null };
        expect(body.due_date === null || typeof body.due_date === "string").toBe(true);
        row = { ...row, due_date: body.due_date };
        return HttpResponse.json(row);
      }),
    );
    return { service: new HttpTaskService(new ApiClient(base)), id: "task-id" };
  } },
];

for (const mode of modes) describe(`UTC calendar in ${mode.name}`, () => {
  it("uses the API UTC day for stored dates, list/board labels and urgency", async () => {
    const { service, id } = mode.setup();
    const task = (await service.get(id))!;
    expect(task.due).toBe("2026-09-24");
    expect(rowView(task, now, 0)).toMatchObject({ dueLabel: "Due Thu · 4d", prioTone: "hot", rail: "danger" });
    expect(cardView(task, now)).toMatchObject({ dueLabel: "Due Thu · 4d", prioTone: "hot", rail: "danger" });
    expect(urgency(task, now)).toMatchObject({ diff: 4, critical: true, soon: true, score: 858 });
  });

  it("changes urgency and its ordering at UTC midnight, not browser midnight", async () => {
    const { service, id } = mode.setup();
    const risk = (await service.get(id))!;
    const peer = makeTask({ id: "peer", due: "2026-09-20", prio: 2, importance: 50 });
    const before = Date.parse("2026-09-19T23:59:59.999Z");
    const after = before + 1;
    expect(urgency(risk, before)).toMatchObject({ diff: 5, critical: false, score: 233 });
    expect(urgency(risk, after)).toMatchObject({ diff: 4, critical: true, score: 858 });
    expect(selectTasks([risk, peer], DEFAULT_QUERY, "urgency", { now: before, currentUserId: "ab" }).map((task) => task.id)).toEqual(["peer", id]);
    expect(selectTasks([risk, peer], DEFAULT_QUERY, "urgency", { now: after, currentUserId: "ab" }).map((task) => task.id)).toEqual([id, "peer"]);
  });

  it("saves UTC quick-action dates and unchanged date-only values, and clears with exact null", async () => {
    const { service, id } = mode.setup();
    let task = await service.update(id, { due: dayFrom(1, now) });
    expect(task.due).toBe("2026-09-21");
    expect(rowView(task, now, 0).dueLabel).toBe("Due tomorrow");
    task = await service.update(id, { due: dayFrom(7, now, "2026-09-24") });
    expect(task.due).toBe("2026-10-01");
    for (const entered of ["2026-03-08", "2026-11-01", "2028-02-29"]) {
      await service.update(id, { due: entered });
      expect((await service.get(id))?.due).toBe(entered);
    }
    task = await service.update(id, { due: null });
    expect(task.due).toBeNull();
    expect(rowView(task, now, 0).dueLabel).toBe("No date");
    expect(cardView(task, now).dueLabel).toBe("No date");
    expect(urgency(task, now)).toMatchObject({ overdue: false, soon: false, critical: false, diff: Infinity });
  });
});
