import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NOW } from "@/test/tasks";
import { InMemoryStepGenerationService } from "./inMemoryStepGenerationService";
import { InMemoryTaskService } from "./inMemoryTaskService";
import { InMemoryTaskStore } from "./inMemoryTaskStore";
import { TaskNotFoundError, type Generation } from "./types";

let now: number;
let tasks: InMemoryTaskService;
let service: InMemoryStepGenerationService;
let seen: (Generation | null)[];

beforeEach(() => {
  vi.useFakeTimers();
  now = NOW;
  const store = new InMemoryTaskStore(() => now);
  tasks = new InMemoryTaskService(store);
  service = new InMemoryStepGenerationService(store);
  seen = [];
  service.subscribe((g) => seen.push(g));
});

afterEach(() => vi.useRealTimers());

const last = <T,>(items: T[]) => items[items.length - 1];

describe("InMemoryStepGenerationService", () => {
  it("runs, then proposes the task's drafted steps", async () => {
    await service.start("t4");
    expect(service.current()).toEqual({ taskId: "t4", phase: "running" });

    vi.advanceTimersByTime(2199);
    expect(service.current()?.phase).toBe("running");
    vi.advanceTimersByTime(1);

    const proposed = service.current();
    expect(proposed).toMatchObject({ taskId: "t4", phase: "proposed" });
    expect(proposed?.phase === "proposed" && proposed.steps.map((s) => s.text)).toEqual([
      "users table + Alembic migration (email, password_hash)",
      "Ports: PasswordHasher and TokenIssuer; adapters: argon2 and PyJWT",
      "Use cases: register, login → access + refresh tokens",
      "current_user dependency on every /tasks route (401 on missing or expired)",
      "Contract tests for both token adapters; API tests for the 401 paths",
      "Frontend: token storage in client.ts, login form, redirect on 401",
    ]);
    expect(seen.map((g) => g?.phase)).toEqual(["running", "proposed"]);
  });

  it("falls back to the generic draft for a task without a tailored one", async () => {
    const created = await tasks.create({ title: "Something new" });
    await service.start(created.id);
    vi.advanceTimersByTime(2200);
    const g = service.current();
    expect(g?.phase === "proposed" && g.steps).toHaveLength(5);
  });

  it("ignores a second start for the task already running", async () => {
    await service.start("t4");
    vi.advanceTimersByTime(2000);
    await service.start("t4");
    vi.advanceTimersByTime(200);
    expect(service.current()?.phase).toBe("proposed");
  });

  it("replaces a running generation when another task starts", async () => {
    await service.start("t4");
    vi.advanceTimersByTime(1000);
    await service.start("t7");
    vi.advanceTimersByTime(2200);
    expect(service.current()).toMatchObject({ taskId: "t7", phase: "proposed" });
  });

  it("lets a proposed step be dropped before accepting", async () => {
    await service.start("t16");
    vi.advanceTimersByTime(2200);
    const g = service.current();
    if (g?.phase !== "proposed") throw new Error("expected a proposal");
    service.removeProposed(g.steps[0].id);
    const after = service.current();
    expect(after?.phase === "proposed" && after.steps.map((s) => s.text)).toEqual([
      "Ask who sits on the panel and how long the review is",
      "Block the calendar and add the Meet link to this task",
    ]);
  });

  it("accepts: appends the steps undone, logs as the assistant and clears", async () => {
    await service.start("t16");
    vi.advanceTimersByTime(2200);
    now += 5000;
    const task = await service.accept();
    expect(task?.steps.map((s) => s.done)).toEqual([false, false, false]);
    expect(task?.updatedAt).toBe(now);
    expect(last(task!.activity)).toEqual({ type: "log", who: "ai", text: "Drafted 3 steps · added by Andres", at: now });
    expect(service.current()).toBeNull();
    expect((await tasks.get("t16"))?.steps).toHaveLength(3);
  });

  it("uses the singular when one step is accepted", async () => {
    await service.start("t16");
    vi.advanceTimersByTime(2200);
    const g = service.current();
    if (g?.phase !== "proposed") throw new Error("expected a proposal");
    g.steps.slice(1).forEach((s) => service.removeProposed(s.id));
    expect(last((await service.accept())!.activity).text).toBe("Drafted 1 step · added by Andres");
  });

  it("does not accept while still running, or with nothing in flight", async () => {
    expect(await service.accept()).toBeNull();
    await service.start("t4");
    expect(await service.accept()).toBeNull();
    expect(service.current()?.phase).toBe("running");
  });

  it("discards: cancels the run, logs it and leaves the steps alone", async () => {
    await service.start("t4");
    await service.discard();
    vi.advanceTimersByTime(5000);
    expect(service.current()).toBeNull();
    const task = (await tasks.get("t4"))!;
    expect(task.steps).toEqual([]);
    expect(last(task.activity)).toMatchObject({ type: "log", who: "ai", text: "Draft discarded by Andres" });
    expect(seen).toEqual([{ taskId: "t4", phase: "running" }, null]);
  });

  it("discards a run whose task was deleted, and never proposes for it", async () => {
    await service.start("t4");
    await tasks.remove("t4");
    await expect(service.discard()).resolves.toBeUndefined();
    vi.advanceTimersByTime(5000);
    expect(service.current()).toBeNull();
    expect(seen).toEqual([{ taskId: "t4", phase: "running" }, null]);
  });

  it("clears a run on its own when the task is deleted before the proposal", async () => {
    await service.start("t4");
    await tasks.remove("t4");
    vi.advanceTimersByTime(2200);
    expect(service.current()).toBeNull();
    expect(seen.map((g) => g?.phase)).toEqual(["running", undefined]);
  });

  it("clears a proposal whose task was deleted instead of accepting it", async () => {
    await service.start("t16");
    vi.advanceTimersByTime(2200);
    await tasks.remove("t16");
    expect(await service.accept()).toBeNull();
    expect(service.current()).toBeNull();
  });

  it("discards a proposal whose task was deleted", async () => {
    await service.start("t16");
    vi.advanceTimersByTime(2200);
    await tasks.remove("t16");
    await service.discard();
    expect(service.current()).toBeNull();
  });

  it("discarding nothing is a no-op", async () => {
    await service.discard();
    expect(seen).toEqual([]);
  });

  it("stops notifying after unsubscribe", async () => {
    const calls: unknown[] = [];
    const unsubscribe = service.subscribe((g) => calls.push(g));
    unsubscribe();
    await service.start("t4");
    expect(calls).toEqual([]);
  });

  it("rejects an unknown task", async () => {
    await expect(service.start("nope")).rejects.toBeInstanceOf(TaskNotFoundError);
  });
});
