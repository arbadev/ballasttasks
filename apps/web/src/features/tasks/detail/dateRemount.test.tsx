import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { NOW, due } from "@/test/tasks";
import type { Task } from "../model/types";
import { seedTasks } from "../services/seed";
import type { TaskPatch } from "../services/types";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

/** Controlled latency/refusal only: successful releases mutate the fake's actual saved task. */
class DeferredUpdates extends FakeTaskService {
  readonly requests: { id: string; patch: TaskPatch; done: boolean; finish(ok: boolean): void }[] = [];
  maxConcurrent = 0;

  override update(id: string, patch: TaskPatch, note?: string): Promise<Task> {
    return new Promise((resolve, reject) => {
      const request = {
        id, patch, done: false,
        finish: (ok: boolean) => {
          request.done = true;
          if (ok) void super.update(id, patch, note).then(resolve, reject);
          else reject(new Error("Controlled refusal"));
        },
      };
      this.requests.push(request);
      this.maxConcurrent = Math.max(this.maxConcurrent, this.requests.filter((r) => !r.done).length);
    });
  }

  async finish(index: number, ok: boolean) {
    await act(async () => this.requests[index].finish(ok));
    await settle();
  }
}

const properties = () => within(screen.getByRole("complementary", { name: "Properties" }));
const dateInput = () => properties().getByLabelText("Due date");
function clearDate() {
  fireEvent.change(dateInput(), { target: { value: "" } });
  // A pointer activation leaves the date field before clicking Clear.
  fireEvent.blur(dateInput());
  fireEvent.click(properties().getByRole("button", { name: "Clear date" }));
}
const close = () => fireEvent.click(screen.getByRole("button", { name: "Close task" }));
const exits = ["same mount", "close", "switch"] as const;
function leave(mode: typeof exits[number]) {
  if (mode === "close") close();
  if (mode === "switch") openTask("t4");
}
function returnToTask(mode: typeof exits[number]) {
  if (mode !== "same mount") openTask("t1");
}
async function setup() {
  const service = new DeferredUpdates(seedTasks(NOW));
  await renderDetail({ taskService: service });
  openTask("t1");
  return service;
}
function retryClear() {
  const alert = properties().getByRole("alert");
  expect(alert).toHaveTextContent("Could not save the due date.");
  fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
}

describe("date save ownership across panel mounts", () => {
  it.each(exits)("retains exact-null recovery after a refusal: %s", async (mode) => {
    const service = await setup();
    clearDate();
    expect(service.requests.map((r) => [r.id, r.patch])).toEqual([["t1", { due: null }]]);
    leave(mode);
    await service.finish(0, false);
    if (mode === "switch") expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    returnToTask(mode);
    expect(dateInput()).toHaveValue(due(3));
    retryClear();
    expect(service.requests.map((r) => [r.id, r.patch])).toEqual([
      ["t1", { due: null }], ["t1", { due: null }],
    ]);
    await service.finish(1, true);
    expect((await service.get("t1"))?.due).toBeNull();
    expect(dateInput()).toHaveValue("");
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    expect(service.maxConcurrent).toBe(1);
  });

  it.each(exits)("observes refusal without another reopen when remounted before settlement: %s", async (mode) => {
    const service = await setup();
    clearDate();
    leave(mode);
    returnToTask(mode);
    await service.finish(0, false);
    retryClear();
    await service.finish(1, true);
    expect((await service.get("t1"))?.due).toBeNull();
    expect(dateInput()).toHaveValue("");
    expect(service.requests.map((r) => r.patch)).toEqual([{ due: null }, { due: null }]);
  });

  it.each(exits)("an old date write cannot resurrect a later explicit clear: %s", async (mode) => {
    const service = await setup();
    fireEvent.change(dateInput(), { target: { value: due(9) } });
    fireEvent.blur(dateInput());
    leave(mode);
    returnToTask(mode);
    clearDate();
    // Disconfirming same-mount control: the correct machine has not sent the clear yet.
    // If two writes overlap, make the older one apply last, exposing actual saved corruption.
    if (service.requests.length === 2) {
      await service.finish(1, true);
      await service.finish(0, true);
    } else {
      await service.finish(0, true);
      await service.finish(1, true);
    }
    expect((await service.get("t1"))?.due).toBeNull();
    expect(dateInput()).toHaveValue("");
    expect(service.requests.map((r) => r.patch)).toEqual([{ due: due(9) }, { due: null }]);
    expect(service.maxConcurrent).toBe(1);
  });

  it("preserves a newer complete date after reopening during a clear, and flushes text to its own task", async () => {
    const service = await setup();
    clearDate();
    close();
    openTask("t1");
    fireEvent.change(dateInput(), { target: { value: due(12) } });
    fireEvent.blur(dateInput());
    expect(service.requests.map((r) => r.patch)).toEqual([{ due: null }]);
    await service.finish(0, false);
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    await service.finish(1, true);
    expect((await service.get("t1"))?.due).toBe(due(12));
    expect(dateInput()).toHaveValue(due(12));

    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Task one renamed" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "Keep this description" } });
    openTask("t4");
    await service.finish(2, true);
    await service.finish(3, true);
    expect(await service.get("t1")).toMatchObject({ title: "Task one renamed", description: "Keep this description", due: due(12) });
    expect((await service.get("t4"))?.title).toBe("JWT authentication");
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });
});
