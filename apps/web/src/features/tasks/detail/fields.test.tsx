import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { NOW, due } from "@/test/tasks";
import type { Task } from "../model/types";
import { seedTasks } from "../services/seed";
import type { TaskPatch } from "../services/types";
import { AUTOSAVE_DELAY_MS } from "./useAutosaveField";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

/** Rejects every update until `heal()`, to drive the failure and retry paths. */
class FlakyTaskService extends FakeTaskService {
  private broken = true;
  heal() {
    this.broken = false;
  }
  override async update(id: string, patch: TaskPatch, note?: string) {
    if (this.broken) {
      this.calls.push(["update:rejected", id, patch]);
      throw new Error("offline");
    }
    return super.update(id, patch, note);
  }
}

/** Holds every update open, so a test can interleave two saves and settle them in any order. */
function deferUpdates(service: FakeTaskService) {
  const original = service.update.bind(service);
  const requests: { patch: TaskPatch; settle: (ok: boolean) => void }[] = [];
  service.update = (id, patch, note) =>
    new Promise<Task>((resolve, reject) => {
      requests.push({
        patch,
        settle: (ok) => {
          if (ok) void original(id, patch, note).then(resolve, reject);
          else reject(new Error("offline"));
        },
      });
    });
  return requests;
}

const updates = (service: FakeTaskService) => service.calls.filter((c) => c[0] === "update");
const title = () => screen.getByRole("textbox", { name: "Task name" });
const description = () => screen.getByRole("textbox", { name: "Description" });
const properties = () => within(screen.getByRole("complementary", { name: "Properties" }));
const saveState = () => screen.getByTestId("save-state");

/** Only the debounce is faked; Testing Library's own polling keeps its real interval. */
function fakeDebounce() {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
}
async function elapse(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => vi.useRealTimers());

describe("title and description autosave", () => {
  it("shows the saved text, under the design's placeholders", async () => {
    await renderDetail();
    openTask("t4");
    expect(title()).toHaveValue("JWT authentication");
    expect(title()).toHaveAttribute("placeholder", "Task name");
    expect((description() as HTMLTextAreaElement).value).toContain("Register and login");
    expect(description()).toHaveAttribute("placeholder", "What does done look like?");
  });

  it("debounces typing into one save of the final text, with no Save button anywhere", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fakeDebounce();

    fireEvent.change(title(), { target: { value: "JWT a" } });
    fireEvent.change(title(), { target: { value: "JWT auth, v2" } });
    await elapse(AUTOSAVE_DELAY_MS - 1);
    expect(updates(taskService)).toEqual([]);
    expect(title()).toHaveValue("JWT auth, v2");

    await elapse(1);
    expect(updates(taskService)).toEqual([["update", "t4", { title: "JWT auth, v2" }]]);
    expect(screen.getByRole("dialog")).toHaveAccessibleName("JWT auth, v2");
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
  });

  it("saves at once on blur", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.change(description(), { target: { value: "Short-lived access token, refresh in a cookie." } });
    fireEvent.blur(description());
    await settle();
    expect(updates(taskService)).toEqual([["update", "t4", { description: "Short-lived access token, refresh in a cookie." }]]);
  });

  it("does not save text that was typed and then put back", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.change(title(), { target: { value: "JWT" } });
    fireEvent.change(title(), { target: { value: "JWT authentication" } });
    fireEvent.blur(title());
    await settle();
    expect(updates(taskService)).toEqual([]);
  });

  it("never loses text typed just before the panel closes", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.change(title(), { target: { value: "JWT, typed then Escape" } });
    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    expect(updates(taskService)).toEqual([["update", "t4", { title: "JWT, typed then Escape" }]]);

    openTask("t4");
    expect(title()).toHaveValue("JWT, typed then Escape");
  });

  it("saves text typed mid-edit to its own task when another task is opened", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.change(title(), { target: { value: "Edited, then switched" } });
    openTask("t6");
    await settle();
    expect(updates(taskService)).toEqual([["update", "t4", { title: "Edited, then switched" }]]);
    expect(title()).toHaveValue("Seed data and demo credentials");
  });

  it("walks the indicator through saving to saved", async () => {
    const { taskService } = await renderDetail();
    let release = () => {};
    const original = taskService.update.bind(taskService);
    taskService.update = async (...args) => {
      await new Promise<void>((resolve) => (release = resolve));
      return original(...args);
    };
    openTask("t4");
    fireEvent.change(title(), { target: { value: "Slow save" } });
    fireEvent.blur(title());
    await settle();
    expect(saveState()).toHaveTextContent("saving…");
    expect(title()).toHaveValue("Slow save");

    release();
    await settle();
    expect(saveState()).toHaveTextContent(/^saved · /);
  });

  it("saves an edit made while an earlier save is still in flight, even one that restores the saved text", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    const requests = deferUpdates(taskService);

    fireEvent.change(title(), { target: { value: "Typed while offline" } });
    fireEvent.blur(title());
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ title: "Typed while offline" }]);

    // Back to the text the task already holds, while the first save is still open.
    fireEvent.change(title(), { target: { value: "JWT authentication" } });
    fireEvent.blur(title());
    await settle();
    expect(title()).toHaveValue("JWT authentication");

    // Queued behind the save in flight, never skipped, so the service is written to in order.
    requests[0].settle(true);
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ title: "Typed while offline" }, { title: "JWT authentication" }]);
    expect(title()).toHaveValue("JWT authentication");

    requests[1].settle(true);
    await settle();
    expect(title()).toHaveValue("JWT authentication");
    expect(screen.getByRole("dialog")).toHaveAccessibleName("JWT authentication");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("never shows stale confirmed text while an edit of its own is still on the way", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    const requests = deferUpdates(taskService);

    fireEvent.change(title(), { target: { value: "First" } });
    fireEvent.blur(title());
    await settle();
    fireEvent.change(title(), { target: { value: "Second" } });
    fireEvent.blur(title());
    await settle();

    requests[0].settle(true);
    await settle();
    // The task now holds "First", but the user's own newer text is what the field keeps showing.
    expect(taskService.calls).toContainEqual(["update", "t4", { title: "First" }]);
    expect(title()).toHaveValue("Second");

    requests[1].settle(true);
    await settle();
    expect(title()).toHaveValue("Second");
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Second");
  });

  it("keeps showing an edit that the save in flight is already carrying", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    const requests = deferUpdates(taskService);

    fireEvent.change(title(), { target: { value: "JWT auth" } });
    fireEvent.blur(title());
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ title: "JWT auth" }]);

    // Typed and undone again while that save is still open: the field must not revert meanwhile.
    fireEvent.change(title(), { target: { value: "JWT auth!" } });
    fireEvent.change(title(), { target: { value: "JWT auth" } });
    fireEvent.blur(title());
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ title: "JWT auth" }]);
    expect(title()).toHaveValue("JWT auth");

    requests[0].settle(true);
    await settle();
    expect(title()).toHaveValue("JWT auth");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    requests[1]?.settle(true);
    await settle();
    expect(title()).toHaveValue("JWT auth");
  });

  it("drops the failure of a save that a later, successful one has overtaken", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    const requests = deferUpdates(taskService);

    fireEvent.change(title(), { target: { value: "JWT auth" } });
    fireEvent.blur(title());
    await settle();
    fireEvent.change(title(), { target: { value: "JWT auth, v2" } });
    fireEvent.blur(title());
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ title: "JWT auth" }]);

    requests[0].settle(false);
    await settle();
    // The newer edit was queued behind it, so the failure is not the last word: no alert, no rollback.
    expect(requests.map((r) => r.patch)).toEqual([{ title: "JWT auth" }, { title: "JWT auth, v2" }]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(title()).toHaveValue("JWT auth, v2");

    requests[1].settle(true);
    await settle();
    expect(title()).toHaveValue("JWT auth, v2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(saveState()).toHaveTextContent(/^saved · /);
  });

  it("rolls a failed save back, says so inline, and Retry saves the same text", async () => {
    const taskService = new FlakyTaskService(seedTasks(NOW));
    await renderDetail({ taskService });
    openTask("t4");
    fireEvent.change(title(), { target: { value: "Will not stick" } });
    fireEvent.blur(title());
    await settle();

    expect(title()).toHaveValue("JWT authentication");
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save the title. Your change was undone.");
    expect(saveState()).toHaveTextContent("not saved");

    taskService.heal();
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(updates(taskService)).toEqual([["update", "t4", { title: "Will not stick" }]]);
    expect(title()).toHaveValue("Will not stick");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(saveState()).toHaveTextContent(/^saved · /);
  });
});

describe("property controls", () => {
  it("shows the task's values in the design's controls", async () => {
    await renderDetail();
    openTask("t1");
    const p = properties();
    expect(p.getByRole("combobox", { name: "Status" })).toHaveValue("progress");
    expect(p.getByRole("combobox", { name: "Assignee" })).toHaveValue("ab");
    expect(p.getByLabelText("Due date")).toHaveValue(due(3));
    expect(p.getByRole("combobox", { name: "Priority" })).toHaveValue("0");
    expect(p.getByRole("spinbutton", { name: "Importance" })).toHaveValue(95);
    expect(p.getByRole("combobox", { name: "Project" })).toHaveValue("ballast");

    const options = (name: string) => within(p.getByRole("combobox", { name })).getAllByRole("option").map((o) => o.textContent);
    expect(options("Status")).toEqual(["To Do", "In Progress", "Testing", "Done"]);
    expect(options("Assignee")).toEqual(["Unassigned", "Andres Barradas", "Lucía Marín", "Tomás Rey"]);
    expect(options("Priority")).toEqual(["P0", "P1", "P2", "P3"]);
    expect(options("Project")).toEqual(["Ballast Tasks", "Inbox"]);
  });

  it("status moves the task", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.change(properties().getByRole("combobox", { name: "Status" }), { target: { value: "testing" } });
    await settle();
    expect(taskService.calls).toContainEqual(["move", "t4", "testing"]);
    expect(screen.getByTestId("detail-status")).toHaveTextContent("Testing");
  });

  it("assignee saves a person, and Unassigned saves null", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const assignee = properties().getByRole("combobox", { name: "Assignee" });
    fireEvent.change(assignee, { target: { value: "lm" } });
    await settle();
    fireEvent.change(assignee, { target: { value: "" } });
    await settle();
    expect(updates(taskService)).toEqual([
      ["update", "t1", { assignee: "lm" }],
      ["update", "t1", { assignee: null }],
    ]);
    expect(assignee).toHaveValue("");
  });

  it("due date saves the day, and Clear date saves null", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");
    fireEvent.change(input, { target: { value: due(9) } });
    fireEvent.blur(input);
    await settle();
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(properties().getByRole("button", { name: "Clear date" }));
    await settle();
    expect(updates(taskService)).toEqual([
      ["update", "t1", { due: due(9) }],
      ["update", "t1", { due: null }],
    ]);
    expect(input).toHaveValue("");
  });

  it("saves one complete date when a segment is retyped, and never the empty value in between", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");
    fakeDebounce();

    // A date input reports an empty value while one of its segments is being retyped.
    fireEvent.change(input, { target: { value: "" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(taskService.calls.filter((c) => c[0] === "update")).toEqual([]);

    fireEvent.change(input, { target: { value: due(9) } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(taskService.calls.filter((c) => c[0] === "update")).toEqual([["update", "t1", { due: due(9) }]]);
    expect(input).toHaveValue(due(9));
  });

  it("puts the stored date back when the emptied box is left, and only Clear date removes it", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");
    fakeDebounce();

    fireEvent.change(input, { target: { value: "" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(updates(taskService)).toEqual([]);
    expect(input).toHaveValue("");

    // Leaving the field is not the user's word for "no due date": the stored one comes back.
    fireEvent.blur(input);
    await elapse(0);
    expect(updates(taskService)).toEqual([]);
    expect(input).toHaveValue(due(3));

    fireEvent.click(properties().getByRole("button", { name: "Clear date" }));
    await elapse(0);
    expect(updates(taskService)).toEqual([["update", "t1", { due: null }]]);
    expect(input).toHaveValue("");
    expect(properties().queryByRole("group", { name: "Remove the date?" })).not.toBeInTheDocument();
  });

  it("keeps the stored date when the panel closes on an emptied box", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    expect(updates(taskService)).toEqual([]);

    openTask("t1");
    expect(properties().getByLabelText("Due date")).toHaveValue(due(3));
  });

  it("says so inline when Clear date is refused, and Retry sends the same null", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    const original = taskService.update.bind(taskService);
    taskService.update = async () => {
      throw new Error("offline");
    };
    await renderDetail({ taskService });
    openTask("t1");
    const input = properties().getByLabelText("Due date");

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(properties().getByRole("button", { name: "Clear date" }));
    await settle();
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the due date.");
    expect(input).toHaveValue(due(3));

    taskService.update = original;
    fireEvent.click(within(properties().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(updates(taskService)).toEqual([["update", "t1", { due: null }]]);
    expect(input).toHaveValue("");
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps an explicit clear last, behind a date save that is still open", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");
    const requests = deferUpdates(taskService);

    fireEvent.change(input, { target: { value: due(9) } });
    fireEvent.blur(input);
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ due: due(9) }]);

    // Cleared while that save is still open: the null is sent after it, never under it.
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(properties().getByRole("button", { name: "Clear date" }));
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ due: due(9) }]);

    requests[0].settle(true);
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ due: due(9) }, { due: null }]);

    requests[1].settle(true);
    await settle();
    expect(input).toHaveValue("");
  });

  it("Keep leaves the stored date alone and takes the prompt away", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(properties().getByRole("button", { name: "Keep" }));
    await settle();
    expect(updates(taskService)).toEqual([]);
    expect(input).toHaveValue(due(3));
    expect(properties().queryByRole("group", { name: "Remove the date?" })).not.toBeInTheDocument();
  });

  it("priority and project save on change", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    fireEvent.change(properties().getByRole("combobox", { name: "Priority" }), { target: { value: "3" } });
    await settle();
    fireEvent.change(properties().getByRole("combobox", { name: "Project" }), { target: { value: "inbox" } });
    await settle();
    expect(updates(taskService)).toEqual([
      ["update", "t1", { prio: 3 }],
      ["update", "t1", { project: "inbox" }],
    ]);
    expect(screen.getByTestId("detail-project")).toHaveTextContent("Inbox");
  });

  it("importance is clamped to 0-100 and drives its meter", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByRole("spinbutton", { name: "Importance" });
    fireEvent.change(input, { target: { value: "250" } });
    fireEvent.blur(input);
    await settle();
    expect(updates(taskService)).toEqual([["update", "t1", { importance: 100 }]]);
    expect(input).toHaveValue(100);
    expect(properties().getByRole("meter", { name: "Importance" })).toHaveAttribute("aria-valuenow", "100");
  });

  it("an emptied importance is not saved and comes back on blur", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByRole("spinbutton", { name: "Importance" });
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    await settle();
    expect(updates(taskService)).toEqual([]);
    expect(input).toHaveValue(95);
  });

  it("keeps an emptied importance box empty while the debounce passes, so the next digits are the value", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByRole("spinbutton", { name: "Importance" });
    fakeDebounce();

    fireEvent.change(input, { target: { value: "" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(input).toHaveValue(null);
    expect(updates(taskService)).toEqual([]);

    fireEvent.change(input, { target: { value: "45" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(updates(taskService)).toEqual([["update", "t1", { importance: 45 }]]);
    expect(input).toHaveValue(45);
    expect(properties().getByRole("meter", { name: "Importance" })).toHaveAttribute("aria-valuenow", "45");
  });

  it("reports a refused importance save that an emptied box is waiting behind", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    const requests = deferUpdates(taskService);
    await renderDetail({ taskService });
    openTask("t1");
    const input = properties().getByRole("spinbutton", { name: "Importance" });
    fakeDebounce();

    fireEvent.change(input, { target: { value: "45" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(requests.map((r) => r.patch)).toEqual([{ importance: 45 }]);

    // Mid-retype the box is empty, which is not a number the task can hold: it never reaches
    // the service, so it cannot stand in for the newer edit that would supersede the refusal.
    fireEvent.change(input, { target: { value: "" } });
    await elapse(AUTOSAVE_DELAY_MS);
    expect(requests).toHaveLength(1);

    await act(async () => requests[0].settle(false));
    await settle();
    expect(properties().getByRole("alert")).toHaveTextContent("Could not save the importance. Your change was undone.");

    fireEvent.blur(input);
    await settle();
    expect(input).toHaveValue(95);
    fireEvent.click(within(properties().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ importance: 45 }, { importance: 45 }]);
  });

  it("still supersedes a refusal with a newer number the box did type", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    const requests = deferUpdates(taskService);
    await renderDetail({ taskService });
    openTask("t1");
    const input = properties().getByRole("spinbutton", { name: "Importance" });
    fakeDebounce();

    fireEvent.change(input, { target: { value: "45" } });
    await elapse(AUTOSAVE_DELAY_MS);
    fireEvent.change(input, { target: { value: "60" } });
    await act(async () => requests[0].settle(false));
    await settle();
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
    expect(input).toHaveValue(60);

    await elapse(AUTOSAVE_DELAY_MS);
    await act(async () => requests[1].settle(true));
    await settle();
    expect(requests.map((r) => r.patch)).toEqual([{ importance: 45 }, { importance: 60 }]);
    expect(properties().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a failed property save snaps the control back and explains", async () => {
    const taskService = new FlakyTaskService(seedTasks(NOW));
    await renderDetail({ taskService });
    openTask("t1");
    const priority = properties().getByRole("combobox", { name: "Priority" });
    fireEvent.change(priority, { target: { value: "2" } });
    await settle();
    expect(priority).toHaveValue("0");
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save the priority. Your change was undone.");
  });
});
