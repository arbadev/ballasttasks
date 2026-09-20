// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiTask } from "@/test/httpFixtures";
import { HttpTaskService } from "./httpTaskService";
import { InMemoryTaskService } from "./inMemoryTaskService";
import { InMemoryTaskStore } from "./inMemoryTaskStore";
import { NOW } from "@/test/tasks";

const base = "http://step-edit.test";
const httpService = () => new HttpTaskService(new ApiClient(base, { token: () => "test-token" }));

describe("step editing adapters", () => {
  it("PATCHes only the trimmed title then returns canonical identity/completion; PUTs the exact permutation", async () => {
    let steps = [
      { id: "a", title: "First", done: true, position: 0, task_id: "task-id", created_at: "2026-09-19T00:00:00Z" },
      { id: "b", title: "Second", done: false, position: 1, task_id: "task-id", created_at: "2026-09-19T00:00:00Z" },
    ];
    const writes: unknown[] = [];
    server.use(
      http.patch(`${base}/tasks/task-id/steps/a`, async ({ request }) => {
        const body = await request.json(); writes.push(body);
        expect(body).toEqual({ title: "Renamed" });
        steps = steps.map((s) => s.id === "a" ? { ...s, title: "Renamed" } : s);
        return HttpResponse.json(steps[0]);
      }),
      http.put(`${base}/tasks/task-id/steps/order`, async ({ request }) => {
        const body = await request.json(); writes.push(body);
        expect(body).toEqual({ step_ids: ["b", "a"] });
        steps = [steps[1], steps[0]].map((s, position) => ({ ...s, position }));
        return HttpResponse.json({ items: steps });
      }),
      http.get(`${base}/tasks/task-id`, () => HttpResponse.json(apiTask({ steps }))),
      http.get(`${base}/tasks/task-id/activity`, () => HttpResponse.json({ items: [], total: 0, offset: 0, limit: 200 })),
    );
    const service = httpService();
    expect((await service.renameStep("task-id", "a", "  Renamed  ")).steps).toEqual([
      { id: "a", text: "Renamed", done: true }, { id: "b", text: "Second", done: false },
    ]);
    const saved = await service.reorderSteps("task-id", ["b", "a"]);
    expect(saved.steps.map((s) => s.id)).toEqual(["b", "a"]);
    expect(saved.steps[1]).toEqual({ id: "a", text: "Renamed", done: true });
    expect(saved.activity).toEqual([]);
    expect(writes).toHaveLength(2);
  });

  it("propagates a stale permutation refusal once, without filtering, retrying or reporting success", async () => {
    const put = vi.fn(() => HttpResponse.json({ detail: "exact permutation required" }, { status: 422 }));
    server.use(http.put(`${base}/tasks/task-id/steps/order`, put));
    await expect(httpService().reorderSteps("task-id", ["a", "b"])).rejects.toMatchObject({ status: 422 });
    expect(put).toHaveBeenCalledOnce();
  });

  it("propagates a title refusal without retrying or inventing a saved task", async () => {
    const patch = vi.fn(() => HttpResponse.json({ detail: "title refused" }, { status: 422 }));
    server.use(http.patch(`${base}/tasks/task-id/steps/a`, patch));
    await expect(httpService().renameStep("task-id", "a", "Refused")).rejects.toMatchObject({ status: 422 });
    expect(patch).toHaveBeenCalledOnce();
  });

  it("fences a queued rename and reorder after the client session ends", async () => {
    let version = 1;
    const client = new ApiClient(base, { token: () => "test-token", version: () => version, expectedVersion: 1 });
    const service = new HttpTaskService(client);
    version++;
    await expect(service.renameStep("task-id", "a", "Renamed")).rejects.toThrow();
    await expect(service.reorderSteps("task-id", ["b", "a"])).rejects.toThrow();
  });

  it("demo trims valid names, preserves IDs/done/activity and accepts only exact current permutations", async () => {
    let now = NOW;
    const service = new InMemoryTaskService(new InMemoryTaskStore(() => now));
    const before = (await service.get("t1"))!;
    const first = before.steps[0];
    now += 1000;
    const renamed = await service.renameStep("t1", first.id, "  Revised  ");
    expect(renamed.steps[0]).toEqual({ ...first, text: "Revised" });
    expect(renamed.activity).toEqual(before.activity);
    expect(renamed.updatedAt).toBe(now);
    const ids = renamed.steps.map((s) => s.id).reverse();
    const reordered = await service.reorderSteps("t1", ids);
    expect(reordered.steps).toEqual([...renamed.steps].reverse());
    expect(reordered.activity).toEqual(before.activity);
    for (const invalid of [ids.slice(1), [...ids, "foreign"], ids.map(() => ids[0])]) {
      await expect(service.reorderSteps("t1", invalid)).rejects.toThrow();
      expect(await service.get("t1")).toEqual(reordered);
    }
    for (const invalid of [" ", "x".repeat(201), "bad\0title"]) {
      await expect(service.renameStep("t1", first.id, invalid)).rejects.toThrow();
      expect(await service.get("t1")).toEqual(reordered);
    }
    await expect(service.renameStep("t1", "missing", "valid")).rejects.toThrow();
    now += 1000;
    expect(await service.renameStep("t1", first.id, "Revised")).toEqual(reordered);
    expect(await service.reorderSteps("t1", ids)).toEqual(reordered);
  });
});
