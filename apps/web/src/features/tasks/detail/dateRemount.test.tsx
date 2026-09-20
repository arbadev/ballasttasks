import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { NOW, due } from "@/test/tasks";
import type { Task } from "../model/types";
import { seedTasks } from "../services/seed";
import type { TaskPatch } from "../services/types";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

/** Controlled latency/refusal only: successful releases mutate the fake's actual saved task. */
class DeferredUpdates extends FakeTaskService {
  readonly requests: { id: string; patch: TaskPatch; note?: string; done: boolean; finish(ok: boolean): void }[] = [];
  maxConcurrent = 0;

  override update(id: string, patch: TaskPatch, note?: string): Promise<Task> {
    return new Promise((resolve, reject) => {
      const request = {
        id, patch, note, done: false,
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
  it.each(["Clear date", "Keep"])("returns focus to the date after %s removes its prompt", async (action) => {
    const service = await setup();
    fireEvent.change(dateInput(), { target: { value: "" } });
    const button = properties().getByRole("button", { name: action });
    button.focus();
    fireEvent.click(button);
    expect(dateInput()).toHaveFocus();
    if (action === "Clear date") await service.finish(0, true);
    else expect(service.requests).toHaveLength(0);
  });

  it("returns focus to the date when Retry removes the failure", async () => {
    const service = await setup();
    clearDate();
    await service.finish(0, false);
    const retry = within(properties().getByRole("alert")).getByRole("button", { name: "Retry" });
    retry.focus();
    fireEvent.click(retry);
    expect(dateInput()).toHaveFocus();
    await service.finish(1, true);
    expect(dateInput()).toHaveFocus();
  });

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

  async function refuseADateWrite() {
    const service = await setup();
    fireEvent.change(dateInput(), { target: { value: due(9) } });
    fireEvent.blur(dateInput());
    await service.finish(0, false);
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");
    expect(dateInput()).toHaveValue(due(3));
    return service;
  }

  it("retires the date recovery once the banner reschedules the task", async () => {
    const service = await refuseADateWrite();
    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    await service.finish(1, true);
    expect(dateInput()).toHaveValue(due(1));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();

    // The obsolete Retry is gone for good, so it cannot put the older date back.
    close();
    openTask("t1");
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    expect(dateInput()).toHaveValue(due(1));
    expect((await service.get("t1"))?.due).toBe(due(1));
    expect(service.requests.map((r) => r.patch)).toEqual([{ due: due(9) }, { due: due(1) }]);
  });

  it("hands the date recovery to the newest thing asked of the field", async () => {
    const service = await refuseADateWrite();
    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    await service.finish(1, false);
    expect(dateInput()).toHaveValue(due(3));

    // One field, one story about failure: the reader has asked for tomorrow since, so Retry
    // sends that and its note rather than the date they left behind.
    retryClear();
    await service.finish(2, true);
    expect(written(service)).toEqual([
      [{ due: due(9) }, undefined],
      [{ due: due(1) }, "Due date moved to tomorrow"],
      [{ due: due(1) }, "Due date moved to tomorrow"],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(1));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["Keep", "blur"])("keeps a refused reschedule while the box is emptied mid-retype, settled by %s", async (settleBy) => {
    const service = await setup();
    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    await service.finish(0, false);
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");

    // Backspacing a segment makes the box report itself empty: a value the task can never
    // hold, so it never reaches the queue and has nothing to say about the refusal.
    fireEvent.change(dateInput(), { target: { value: "" } });
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");
    if (settleBy === "Keep") fireEvent.click(properties().getByRole("button", { name: "Keep" }));
    else fireEvent.blur(dateInput());
    expect(dateInput()).toHaveValue(due(3));

    retryClear();
    await service.finish(1, true);
    expect(written(service)).toEqual([
      [{ due: due(1) }, "Due date moved to tomorrow"],
      [{ due: due(1) }, "Due date moved to tomorrow"],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(1));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retires the date recovery once a date the field can write is on its way", async () => {
    const service = await refuseADateWrite();
    fireEvent.change(dateInput(), { target: { value: due(12) } });
    // Typing is not sending: until the replacement is enqueued the refusal still stands.
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");
    fireEvent.blur(dateInput());
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    await service.finish(1, true);
    expect(written(service)).toEqual([
      [{ due: due(9) }, undefined],
      [{ due: due(12) }, undefined],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(12));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["Keep", "blur"])("keeps a refused reschedule when a typed replacement is emptied before it is sent, settled by %s", async (settleBy) => {
    const service = await setup();
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
      await service.finish(0, false);
      expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");

      fireEvent.change(dateInput(), { target: { value: due(12) } });
      expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");
      // Backspacing a segment before the debounce expires: the replacement is never sent, so
      // it never had anything to say about the refusal.
      await act(async () => { vi.advanceTimersByTime(200); });
      fireEvent.change(dateInput(), { target: { value: "" } });
      await act(async () => { vi.advanceTimersByTime(400); });
      expect(service.requests).toHaveLength(1);

      if (settleBy === "Keep") fireEvent.click(properties().getByRole("button", { name: "Keep" }));
      else fireEvent.blur(dateInput());
      expect(dateInput()).toHaveValue(due(3));

      retryClear();
      await service.finish(1, true);
      expect(written(service)).toEqual([
        [{ due: due(1) }, "Due date moved to tomorrow"],
        [{ due: due(1) }, "Due date moved to tomorrow"],
      ]);
      expect((await service.get("t1"))?.due).toBe(due(1));
      expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports a refusal that arrives while a typed replacement is still being retyped", async () => {
    const service = await setup();
    vi.useFakeTimers();
    try {
      fireEvent.change(dateInput(), { target: { value: due(9) } });
      await act(async () => { vi.advanceTimersByTime(400); });
      expect(service.requests.map((r) => r.patch)).toEqual([{ due: due(9) }]);

      // A newer date is typed but not yet sent when the refusal comes back.
      fireEvent.change(dateInput(), { target: { value: due(12) } });
      await service.finish(0, false);
      expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");

      fireEvent.change(dateInput(), { target: { value: "" } });
      await act(async () => { vi.advanceTimersByTime(400); });
      expect(service.requests).toHaveLength(1);
      expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");

      fireEvent.blur(dateInput());
      expect(dateInput()).toHaveValue(due(3));
      retryClear();
      await service.finish(1, true);
      expect(written(service)).toEqual([
        [{ due: due(9) }, undefined],
        [{ due: due(9) }, undefined],
      ]);
      expect((await service.get("t1"))?.due).toBe(due(9));
      expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves the date recovery alone when an unrelated property is refused", async () => {
    const service = await refuseADateWrite();
    fireEvent.change(properties().getByRole("combobox", { name: "Priority" }), { target: { value: "2" } });
    await service.finish(1, false);

    const dueAlert = properties().getAllByRole("alert").find((a) => a.textContent?.includes("due date"));
    expect(dueAlert).toBeDefined();
    fireEvent.click(within(dueAlert as HTMLElement).getByRole("button", { name: "Retry" }));
    await service.finish(2, true);
    expect(written(service)).toEqual([
      [{ due: due(9) }, undefined],
      [{ prio: 2 }, undefined],
      [{ due: due(9) }, undefined],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(9));
  });

  const written = (service: DeferredUpdates) => service.requests.map((r) => [r.patch, r.note]);

  it("keeps a reschedule refused while the panel was shut, behind the date its own write stored", async () => {
    const service = await setup();
    fireEvent.change(dateInput(), { target: { value: due(9) } });
    fireEvent.blur(dateInput());
    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    close();

    // Nothing is mounted to watch, but the queue runs on: the typed date lands, the reschedule
    // behind it is refused.
    await service.finish(0, true);
    await service.finish(1, false);
    expect((await service.get("t1"))?.due).toBe(due(9));

    openTask("t1");
    expect(dateInput()).toHaveValue(due(9));
    retryClear();
    await service.finish(2, true);
    expect(written(service)).toEqual([
      [{ due: due(9) }, undefined],
      [{ due: due(1) }, "Due date moved to tomorrow"],
      [{ due: due(1) }, "Due date moved to tomorrow"],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(1));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("makes a banner reschedule wait for a typed date already in flight, so it cannot be undone", async () => {
    const service = await setup();
    fireEvent.change(dateInput(), { target: { value: due(9) } });
    fireEvent.blur(dateInput());
    expect(service.requests).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    // The banner writes the date the box owns, so it queues behind it instead of racing it.
    expect(service.requests).toHaveLength(1);
    expect(dateInput()).toHaveValue(due(1));

    await service.finish(0, true);
    expect(service.requests).toHaveLength(2);
    await service.finish(1, true);
    expect(written(service)).toEqual([
      [{ due: due(9) }, undefined],
      [{ due: due(1) }, "Due date moved to tomorrow"],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(1));
    expect(dateInput()).toHaveValue(due(1));
    expect(service.maxConcurrent).toBe(1);
  });

  it("reports a refused banner reschedule under the date box, and retries that date and note", async () => {
    const service = await setup();
    fireEvent.click(screen.getByRole("button", { name: "+1 week" }));
    expect(dateInput()).toHaveValue(due(10));

    await service.finish(0, false);
    expect(dateInput()).toHaveValue(due(3));
    retryClear();
    await service.finish(1, true);
    expect(written(service)).toEqual([
      [{ due: due(10) }, "Due date moved a week out"],
      [{ due: due(10) }, "Due date moved a week out"],
    ]);
    expect((await service.get("t1"))?.due).toBe(due(10));
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("leaves a date being retyped in the box when the clear it follows is refused", async () => {
    const service = await setup();
    clearDate();
    fireEvent.change(dateInput(), { target: { value: due(9) } });
    // Retyping a segment makes the native box report itself empty again: the same value the
    // clear sent, but a newer edit all the same, and the clear's answer is not about it.
    fireEvent.change(dateInput(), { target: { value: "" } });

    await service.finish(0, false);
    expect(dateInput()).toHaveValue("");
    expect(service.requests).toHaveLength(1);
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");

    // Leaving the field is what settles it: an empty box is not a date the task can hold.
    fireEvent.blur(dateInput());
    expect(dateInput()).toHaveValue(due(3));
  });

  it("does not let a queued date success release a newer focused incomplete draft", async () => {
    const service = await setup();
    vi.useFakeTimers();
    try {
      clearDate(); // A is the explicit null write, held at the service.
      fireEvent.change(dateInput(), { target: { value: due(9) } });
      // Unlike the preceding control, B's debounce really expires before C is typed.
      await act(async () => { vi.advanceTimersByTime(400); });
      expect(service.requests.map((r) => r.patch)).toEqual([{ due: null }]);
      expect(dateInput()).toHaveFocus();
      fireEvent.change(dateInput(), { target: { value: "" } }); // C: an unfinished segment.

      await service.finish(0, false);
      expect(service.requests.map((r) => r.patch)).toEqual([{ due: null }, { due: due(9) }]);
      expect(service.requests[1].done).toBe(false);
      expect(dateInput()).toHaveValue("");
      expect(dateInput()).toHaveFocus();
      expect((await service.get("t1"))?.due).toBe(due(3));

      await service.finish(1, true);
      expect((await service.get("t1"))?.due).toBe(due(9));
      expect(dateInput()).toHaveValue("");
      expect(dateInput()).toHaveFocus();
      expect(properties().queryByRole("alert")).not.toBeInTheDocument();
      expect(service.maxConcurrent).toBe(1);

      // Only normal settling releases C; it never authorizes another null write.
      fireEvent.blur(dateInput());
      expect(dateInput()).toHaveValue(due(9));
      close();
      openTask("t1");
      expect(dateInput()).toHaveValue(due(9));
      expect(service.requests.map((r) => r.patch)).toEqual([{ due: null }, { due: due(9) }]);
    } finally {
      vi.useRealTimers();
    }
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
