import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeTask } from "@/test/tasks";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const task = makeTask({ id: "edit", steps: [
  { id: "a", text: "First", done: true },
  { id: "b", text: "Second", done: false },
  { id: "c", text: "Third", done: false },
] });
const elsewhere = makeTask({ id: "elsewhere", title: "Another task" });
const section = () => within(screen.getByRole("region", { name: "Steps" }));
const names = () => section().getAllByRole("checkbox").map((s) => s.getAttribute("aria-label"));
const edit = (name: string) => fireEvent.click(section().getByRole("button", { name: `Rename step: ${name}` }));
const input = () => section().getByRole("textbox", { name: "Step title" });
/** Chrome drops the focus to <body> when the activated control disables or its row moves; jsdom keeps it. */
const dropFocusAsTheBrowserDoes = () => {
  const spare = section().getByRole("textbox", { name: "Add a step" });
  spare.focus();
  spare.blur();
};

describe("ordinary panel step editing through workspace commands", () => {
  it("renames inline on Enter without ticking/removing; persists identity, completion and order after reopening", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit"); edit("First");
    expect(input()).toHaveFocus();
    fireEvent.change(input(), { target: { value: "  Revised  " } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();
    expect(taskService.calls).toContainEqual(["renameStep", "edit", "a", "Revised"]);
    expect(section().getByRole("checkbox", { name: "Revised" })).toBeChecked();
    expect(taskService.calls.filter((c) => ["toggleStep", "removeStep"].includes(String(c[0])))).toEqual([]);
    fireEvent.keyDown(window, { key: "Escape" }); openTask("edit");
    expect(names()).toEqual(["Revised", "Second", "Third"]);
    expect((await taskService.get("edit"))!.steps[0]).toEqual({ id: "a", text: "Revised", done: true });
  });

  it("cancels with Escape without closing the panel and refuses invalid titles without writing", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "discard" } });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(section().getByRole("button", { name: "Rename step: First" })).toHaveFocus();
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
    edit("First");
    for (const value of ["  ", "x".repeat(201), "bad\0title"]) {
      fireEvent.change(input(), { target: { value } });
      fireEvent.keyDown(input(), { key: "Enter" });
      expect(section().getByRole("button", { name: "Save step title" })).toBeDisabled();
    }
    fireEvent.click(section().getByRole("button", { name: "Cancel step rename" }));
    expect(taskService.calls.filter((c) => c[0] === "renameStep")).toEqual([]);
  });

  it("lets pending Escape close the panel and keeps an open empty newer draft through settlement", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Saved via Escape" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "" } });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    openTask("edit");
    expect(input()).toHaveValue("");
    expect(input()).toHaveAttribute("aria-busy", "true");
    // Reopening intentionally focuses the panel; the reader chooses the retained draft again.
    input().focus();
    release(); await settle();
    expect(input()).toHaveValue("");
    expect(input()).toHaveFocus();
    expect((await taskService.get("edit"))!.steps[0].text).toBe("Saved via Escape");
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
  });

  it("keeps a refused rename and an independent newer draft through close/reopen", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let reject!: () => void;
    taskService.renameStep = () => new Promise((_resolve, no) => { reject = () => no(new Error("refused")); });
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Rejected" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "Newer draft" } });
    fireEvent.change(section().getByRole("textbox", { name: "Add a step" }), { target: { value: "Independent add" } });
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    reject(); await settle(); openTask("edit");
    expect(input()).toHaveValue("Newer draft");
    expect(section().getByRole("textbox", { name: "Add a step" })).toHaveValue("Independent add");
    taskService.renameStep = original;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(input()).toHaveValue("Newer draft");
    expect((await taskService.get("edit"))!.steps[0]).toEqual({ id: "a", text: "Rejected", done: true });
  });

  it("keeps an explicitly empty newer rename draft on refusal and a held-title retry", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let reject!: () => void;
    taskService.renameStep = () => new Promise((_yes, no) => { reject = () => no(new Error("refused")); });
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Held title" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    reject(); await settle(); openTask("edit");
    expect(input()).toHaveValue("");
    taskService.renameStep = original;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(input()).toHaveValue("");
    expect((await taskService.get("edit"))!.steps[0].text).toBe("Held title");
  });

  it("moves with accessible buttons, disables boundaries, sends all IDs and keeps completion", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit");
    expect(section().getByRole("button", { name: "Move step up: First" })).toBeDisabled();
    expect(section().getByRole("button", { name: "Move step down: Third" })).toBeDisabled();
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    expect(taskService.calls).toContainEqual(["reorderSteps", "edit", ["b", "a", "c"]]);
    expect(names()).toEqual(["Second", "First", "Third"]);
    expect(section().getByRole("checkbox", { name: "First" })).toBeChecked();
    fireEvent.keyDown(window, { key: "Escape" }); openTask("edit");
    expect(names()).toEqual(["Second", "First", "Third"]);
  });

  it("keeps a newer rename draft after a successful pending save and prevents duplicate submission", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Saved" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "Newer" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    release(); await settle(); openTask("edit");
    expect(input()).toHaveValue("Newer");
    expect(taskService.calls.filter((c) => c[0] === "renameStep")).toEqual([["renameStep", "edit", "a", "Saved"]]);
    expect(section().getByRole("checkbox", { name: "Saved" })).toBeChecked();
  });

  it("holds a concurrent-deletion refusal through a failed reload and only recovers after canonical read", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const read = taskService.get.bind(taskService);
    openTask("edit");
    await taskService.removeStep("edit", "c");
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    taskService.get = async () => { throw new Error("read unavailable"); };
    fireEvent.click(section().getByRole("button", { name: "Reload steps" }));
    await settle();
    expect(section().getByRole("alert")).toBeInTheDocument();
    expect(names()).toEqual(["First", "Second", "Third"]);
    taskService.get = read;
    fireEvent.click(section().getByRole("button", { name: "Reload steps" }));
    await settle();
    expect(names()).toEqual(["First", "Second"]);
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
    expect(taskService.calls.filter((c) => c[0] === "reorderSteps")).toHaveLength(1);
  });

  it("a concurrent addition refuses the stale order; reload reads without resubmitting or losing drafts", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Unsent rename" } });
    await taskService.addStep("edit", "Concurrent");
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    expect(section().getByRole("alert")).toHaveTextContent("Reload steps");
    expect(section().getByRole("button", { name: "Move step down: First" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" }); openTask("edit");
    fireEvent.click(section().getByRole("button", { name: "Reload steps" }));
    await settle();
    expect(names()).toEqual(["First", "Second", "Third", "Concurrent"]);
    expect(input()).toHaveValue("Unsent rename");
    expect(taskService.calls.filter((c) => c[0] === "reorderSteps")).toHaveLength(1);
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    expect(names()).toEqual(["Second", "First", "Third", "Concurrent"]);
    expect(taskService.calls).toContainEqual(["reorderSteps", "edit", ["b", "a", "c", "step1"]]);
  });
  it("hands the keyboard to recovery when a move is refused, and back to the row after the reload", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit");
    await taskService.removeStep("edit", "c");
    const up = section().getByRole("button", { name: "Move step up: Second" });
    up.focus();
    fireEvent.click(up);
    dropFocusAsTheBrowserDoes();
    await settle();
    const reload = section().getByRole("button", { name: "Reload steps" });
    expect(reload).toHaveFocus();
    fireEvent.click(reload);
    dropFocusAsTheBrowserDoes();
    await settle();
    expect(names()).toEqual(["First", "Second"]);
    expect(section().getByRole("button", { name: "Move step up: Second" })).toHaveFocus();
  });

  it("leaves a focus the reader chose during a move alone", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.reorderSteps.bind(taskService);
    let release!: () => void;
    taskService.reorderSteps = (id, ids) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, ids));
    openTask("edit");
    const up = section().getByRole("button", { name: "Move step up: Second" });
    up.focus();
    fireEvent.click(up);
    dropFocusAsTheBrowserDoes();
    const add = section().getByRole("textbox", { name: "Add a step" });
    add.focus();
    release();
    await settle();
    expect(add).toHaveFocus();
    expect(names()).toEqual(["Second", "First", "Third"]);
  });

  it("speaks about the refused move: a later canonical read updates the list and still holds moving", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    openTask("edit");
    await taskService.removeStep("edit", "c");
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    expect(section().getByRole("alert")).toHaveTextContent("The last step move was not confirmed.");
    fireEvent.click(section().getByRole("checkbox", { name: "First" }));
    await settle();
    expect(names()).toEqual(["First", "Second"]);
    expect(section().getByRole("alert")).toHaveTextContent("The last step move was not confirmed.");
    expect(section().getByRole("button", { name: "Move step down: First" })).toBeDisabled();
    fireEvent.click(section().getByRole("button", { name: "Reload steps" }));
    await settle();
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
    expect(section().getByRole("button", { name: "Move step down: First" })).toBeEnabled();
    expect(taskService.calls.filter((c) => c[0] === "reorderSteps")).toHaveLength(1);
  });

  it("reloads as a read: the section says so and the footer neither invents nor clears a save", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const read = taskService.get.bind(taskService);
    taskService.update = async () => { throw new Error("offline"); };
    openTask("edit");
    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Refused elsewhere" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Task name" }));
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");
    await taskService.removeStep("edit", "c");
    fireEvent.click(section().getByRole("button", { name: "Move step up: Second" }));
    await settle();
    expect(section().getByRole("alert")).toBeInTheDocument();
    let finish!: () => void;
    taskService.get = (id) => new Promise((resolve) => { finish = () => resolve(read(id)); });
    fireEvent.click(section().getByRole("button", { name: "Reload steps" }));
    await settle();
    expect(section().getByRole("status")).toHaveTextContent("Updating steps…");
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");
    finish();
    await settle();
    expect(names()).toEqual(["First", "Second"]);
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");
  });
  it("keeps the submitted title in the field while it saves, and takes a newer draft over it", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Revised" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(input()).toHaveValue("Revised");
    expect(input()).toHaveAttribute("aria-invalid", "false");
    expect(input()).toHaveAttribute("aria-busy", "true");
    expect(section().getByRole("status")).toHaveTextContent("Saving step title…");
    fireEvent.change(input(), { target: { value: "" } });
    expect(input()).toHaveValue("");
    expect(input()).toHaveAttribute("aria-invalid", "true");
    expect(section().getByRole("button", { name: "Save step title" })).toBeDisabled();
    fireEvent.change(input(), { target: { value: "Newer" } });
    release(); await settle();
    expect(input()).toHaveValue("Newer");
    expect(section().getByRole("checkbox", { name: "Revised" })).toBeChecked();
    expect(taskService.calls.filter((c) => c[0] === "renameStep")).toEqual([["renameStep", "edit", "a", "Revised"]]);
  });

  it("puts a refused title back in its own field and collapses the editor when the save lands", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let settleSend!: (ok: boolean) => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes, no) => {
      settleSend = (ok) => (ok ? yes() : no(new Error("refused")));
    }).then(() => original(id, stepId, text));
    openTask("edit"); edit("Second");
    fireEvent.change(input(), { target: { value: "Held" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(input()).toHaveValue("Held");
    settleSend(false); await settle();
    expect(input()).toHaveValue("Held");
    expect(input()).toHaveAttribute("aria-invalid", "false");
    expect(section().queryByRole("checkbox", { name: "Held" })).not.toBeInTheDocument();
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    expect(input()).toHaveValue("Held");
    settleSend(true); await settle();
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
    expect(names()).toEqual(["First", "Held", "Third"]);
  });
  it("holds the title being saved in its own field through a close and reopen", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Revised" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    openTask("edit");
    expect(input()).toHaveValue("Revised");
    expect(input()).toHaveAttribute("aria-invalid", "false");
    expect(input()).toHaveAttribute("aria-busy", "true");
    expect(section().getByRole("button", { name: "Save step title" })).toBeDisabled();
    release(); await settle();
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
    expect(section().getByRole("checkbox", { name: "Revised" })).toBeChecked();
    expect(taskService.calls.filter((c) => c[0] === "renameStep")).toEqual([["renameStep", "edit", "a", "Revised"]]);
  });

  it("keeps a draft emptied on purpose empty across another task, and saves what was sent", async () => {
    const { taskService } = await renderDetail({ tasks: [task, elsewhere] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("Second");
    fireEvent.change(input(), { target: { value: "Sent" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "" } });
    openTask("elsewhere");
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
    openTask("edit");
    expect(input()).toHaveValue("");
    expect(input()).toHaveAttribute("aria-invalid", "true");
    release(); await settle();
    expect(names()).toEqual(["First", "Sent", "Third"]);
    expect(input()).toHaveValue("");
    fireEvent.click(section().getByRole("button", { name: "Cancel step rename" }));
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
    expect(names()).toEqual(["First", "Sent", "Third"]);
  });

  it("leaves a draft emptied on purpose open, focused and editable when the save it replaced lands", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let release!: () => void;
    taskService.renameStep = (id, stepId, text) => new Promise<void>((yes) => { release = yes; }).then(() => original(id, stepId, text));
    openTask("edit"); edit("Second");
    fireEvent.change(input(), { target: { value: "Sent" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.change(input(), { target: { value: "" } });
    expect(input()).toHaveFocus();
    release(); await settle();
    expect(names()).toEqual(["First", "Sent", "Third"]);
    expect(input()).toHaveValue("");
    expect(input()).toHaveFocus();
    expect(section().getByRole("button", { name: "Save step title" })).toBeDisabled();
    taskService.renameStep = original;
    fireEvent.change(input(), { target: { value: "Typed after the save" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();
    expect(names()).toEqual(["First", "Typed after the save", "Third"]);
    expect(section().queryByRole("textbox", { name: "Step title" })).not.toBeInTheDocument();
  });

  it("says why a refused rename takes no further save, and takes none until it is resolved", async () => {
    const { taskService } = await renderDetail({ tasks: [task] });
    const original = taskService.renameStep.bind(taskService);
    let sends = 0;
    let refuse = true;
    taskService.renameStep = (id, stepId, text) => {
      sends += 1;
      return refuse ? Promise.reject(new Error("refused")) : original(id, stepId, text);
    };
    openTask("edit"); edit("First");
    fireEvent.change(input(), { target: { value: "Refused" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();
    expect(section().getByRole("alert")).toHaveTextContent(
      "Could not rename the step. Retry or dismiss the failed save before saving another edit.",
    );
    fireEvent.change(input(), { target: { value: "Corrected" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();
    expect(sends).toBe(1);
    expect(names()).toEqual(["First", "Second", "Third"]);
    refuse = false;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Dismiss" }));
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();
    expect(sends).toBe(2);
    expect(names()).toEqual(["Corrected", "Second", "Third"]);
  });
});
