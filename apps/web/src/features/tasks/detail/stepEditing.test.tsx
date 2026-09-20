import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeTask } from "@/test/tasks";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const task = makeTask({ id: "edit", steps: [
  { id: "a", text: "First", done: true },
  { id: "b", text: "Second", done: false },
  { id: "c", text: "Third", done: false },
] });
const section = () => within(screen.getByRole("region", { name: "Steps" }));
const names = () => section().getAllByRole("checkbox").map((s) => s.getAttribute("aria-label"));
const edit = (name: string) => fireEvent.click(section().getByRole("button", { name: `Rename step: ${name}` }));
const input = () => section().getByRole("textbox", { name: "Step title" });

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
});
