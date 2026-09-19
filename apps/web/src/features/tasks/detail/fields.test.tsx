import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { NOW, due } from "@/test/tasks";
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

  it("due date saves the day, and clearing it saves null", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    const input = properties().getByLabelText("Due date");
    fireEvent.change(input, { target: { value: due(9) } });
    await settle();
    fireEvent.change(input, { target: { value: "" } });
    await settle();
    expect(updates(taskService)).toEqual([
      ["update", "t1", { due: due(9) }],
      ["update", "t1", { due: null }],
    ]);
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
