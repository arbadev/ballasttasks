import { beforeEach, describe, expect, it } from "vitest";
import { NOW, due } from "@/test/tasks";
import { InMemoryTaskService } from "./inMemoryTaskService";
import { InMemoryTaskStore } from "./inMemoryTaskStore";
import { TaskNotFoundError } from "./types";

let now: number;
let service: InMemoryTaskService;

beforeEach(() => {
  now = NOW;
  service = new InMemoryTaskService(new InMemoryTaskStore(() => now));
});

const tick = (ms = 60_000) => (now += ms);
const last = <T,>(items: T[]) => items[items.length - 1];

describe("InMemoryTaskService", () => {
  it("lists the seeded tasks and gets one by id", async () => {
    expect(await service.list()).toHaveLength(16);
    expect((await service.get("t4"))?.title).toBe("JWT authentication");
    expect(await service.get("nope")).toBeNull();
  });

  it("returns a fresh array, so callers cannot reorder the store", async () => {
    (await service.list()).reverse();
    expect((await service.list())[0].id).toBe("t1");
  });

  it("creates a task at the top with the design's defaults and a creation log", async () => {
    tick();
    const created = await service.create({ title: "Untitled task" });
    expect(created).toMatchObject({
      title: "Untitled task", description: "", status: "todo", project: "inbox", assignee: null, due: null,
      prio: 2, importance: 50, steps: [], attachments: [], createdAt: now, updatedAt: now,
    });
    expect(created.activity).toEqual([{ type: "log", who: "ab", text: "Created the task", at: now }]);
    expect((await service.list())[0].id).toBe(created.id);
  });

  it("creates into a given status and project, with ids that never collide", async () => {
    const a = await service.create({ title: "A", status: "testing", project: "ballast" });
    const b = await service.create({ title: "B" });
    expect(a).toMatchObject({ status: "testing", project: "ballast" });
    const ids = (await service.list()).flatMap((t) => [t.id, ...t.steps.map((s) => s.id)]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(a.id).not.toBe(b.id);
  });

  it("updates plain fields silently, bumping updatedAt", async () => {
    tick();
    const before = (await service.get("t4"))!;
    const after = await service.update("t4", { title: "JWT auth", prio: 1, importance: 40, due: due(9) });
    expect(after).toMatchObject({ title: "JWT auth", prio: 1, importance: 40, due: due(9), updatedAt: now });
    expect(after.activity).toEqual(before.activity);
  });

  it("clamps importance to 0..100", async () => {
    expect((await service.update("t4", { importance: 140 })).importance).toBe(100);
    expect((await service.update("t4", { importance: -5 })).importance).toBe(0);
  });

  it("logs an assignment and an unassignment", async () => {
    tick();
    const assigned = await service.update("t4", { assignee: "lm" });
    expect(last(assigned.activity)).toEqual({ type: "log", who: "ab", text: "Assigned to Lucía Marín", at: now });
    const cleared = await service.update("t4", { assignee: null });
    expect(last(cleared.activity).text).toBe("Unassigned");
  });

  it("logs the caller's note instead, for the design's quick actions", async () => {
    const moved = await service.update("t5", { due: due(1) }, "Due date moved to tomorrow");
    expect(last(moved.activity)).toMatchObject({ type: "log", who: "ab", text: "Due date moved to tomorrow" });
  });

  it("moves a task and logs both status names", async () => {
    tick();
    const moved = await service.move("t4", "progress");
    expect(moved).toMatchObject({ status: "progress", updatedAt: now });
    expect(last(moved.activity)).toEqual({ type: "log", who: "ab", text: "Moved To Do → In Progress", at: now });
  });

  it("does nothing when moved to the status it already has", async () => {
    const before = (await service.get("t4"))!;
    tick();
    expect(await service.move("t4", "todo")).toEqual(before);
  });

  it("toggles done: completes an open task and reopens a done one to To Do", async () => {
    expect(last((await service.toggleDone("t10")).activity).text).toBe("Moved Testing → Done");
    const reopened = await service.toggleDone("t12");
    expect(reopened.status).toBe("todo");
    expect(last(reopened.activity).text).toBe("Moved Done → To Do");
  });

  it("adds a trimmed step without logging, and ignores a blank one", async () => {
    tick();
    const before = (await service.get("t4"))!;
    const after = await service.addStep("t4", "  users table  ");
    expect(after.steps).toEqual([{ id: expect.any(String), text: "users table", done: false }]);
    expect(after.updatedAt).toBe(now);
    expect(after.activity).toEqual(before.activity);
    expect(await service.addStep("t4", "   ")).toEqual(after);
  });

  it("toggles and removes a step", async () => {
    const [first] = (await service.get("t3"))!.steps;
    expect((await service.toggleStep("t3", first.id)).steps[0].done).toBe(true);
    expect((await service.toggleStep("t3", first.id)).steps[0].done).toBe(false);
    const after = await service.removeStep("t3", first.id);
    expect(after.steps.map((s) => s.id)).not.toContain(first.id);
    expect(after.steps).toHaveLength(3);
  });

  it("adds a comment from the current user and ignores a blank one", async () => {
    tick();
    const after = await service.addComment("t4", " Where does the token live? ");
    expect(last(after.activity)).toEqual({ type: "comment", who: "ab", text: "Where does the token live?", at: now });
    expect(after.updatedAt).toBe(now);
    expect(await service.addComment("t4", "")).toEqual(after);
  });

  it("adds an attachment and logs its name", async () => {
    const after = await service.addAttachment("t4", { kind: "link", name: "jwt.io", meta: "pasted link", url: "https://jwt.io/" });
    expect(after.attachments).toEqual([{ kind: "link", name: "jwt.io", meta: "pasted link", url: "https://jwt.io/" }]);
    expect(last(after.activity).text).toBe("Attached jwt.io");
  });

  it("removes a task", async () => {
    await service.remove("t4");
    expect(await service.get("t4")).toBeNull();
    expect(await service.list()).toHaveLength(15);
  });

  it("never mutates a task it has already handed out", async () => {
    const before = (await service.get("t4"))!;
    const snapshot = structuredClone(before);
    await service.addStep("t4", "x");
    await service.move("t4", "done");
    expect(before).toEqual(snapshot);
  });

  it.each([
    ["update", () => service.update("nope", { title: "x" })],
    ["move", () => service.move("nope", "done")],
    ["toggleDone", () => service.toggleDone("nope")],
    ["addStep", () => service.addStep("nope", "x")],
    ["toggleStep", () => service.toggleStep("nope", "s1")],
    ["removeStep", () => service.removeStep("nope", "s1")],
    ["addComment", () => service.addComment("nope", "x")],
    ["addAttachment", () => service.addAttachment("nope", { kind: "link", name: "x", meta: "", url: "https://example.com/" })],
    ["remove", () => service.remove("nope")],
  ])("rejects %s on an unknown task", async (_name, call) => {
    await expect(call()).rejects.toBeInstanceOf(TaskNotFoundError);
  });
});
