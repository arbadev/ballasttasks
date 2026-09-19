import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { NOW, due, makeTask } from "@/test/tasks";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "@/test/fakeServices";
import { WorkspaceProvider, useDirectory, useNow, useTaskCommands, useVisibleTasks, useWorkspace } from "./WorkspaceProvider";

const tasks = [
  makeTask({ id: "late", title: "Late", due: due(-2), importance: 10 }),
  makeTask({ id: "theirs", title: "Theirs", assignee: "lm", importance: 90 }),
  makeTask({ id: "shipped", title: "Shipped", status: "done" }),
];

function setup(taskService = new FakeTaskService(tasks), stepGeneration = new FakeStepGenerationService()) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Providers taskService={taskService} directoryService={new FakeDirectoryService()} stepGenerationService={stepGeneration} clock={() => NOW}>
      <WorkspaceProvider>{children}</WorkspaceProvider>
    </Providers>
  );
  const hook = renderHook(
    () => ({ workspace: useWorkspace(), visible: useVisibleTasks(), board: useVisibleTasks({ applyStatus: false }), directory: useDirectory(), commands: useTaskCommands(), now: useNow() }),
    { wrapper },
  );
  return { ...hook, taskService, stepGeneration };
}

const ready = async (result: ReturnType<typeof setup>["result"]) => waitFor(() => expect(result.current.workspace.state.load.status).toBe("ready"));

describe("WorkspaceProvider", () => {
  it("loads tasks and the directory through the services", async () => {
    const { result } = setup();
    expect(result.current.workspace.state.load.status).toBe("loading");
    await ready(result);
    expect(result.current.workspace.state.tasks).toHaveLength(3);
    expect(result.current.directory.currentUser?.id).toBe("ab");
    expect(result.current.directory.people.map((p) => p.id)).toEqual(["ab", "lm", "tr", "ai"]);
    expect(result.current.directory.projects.map((p) => p.id)).toEqual(["ballast", "inbox"]);
    expect(result.current.now).toBe(NOW);
  });

  it("derives the visible tasks: filtered and sorted, with the board ignoring the status filter", async () => {
    const { result } = setup();
    await ready(result);
    expect(result.current.visible.map((t) => t.id)).toEqual(["late", "theirs"]);
    expect(result.current.board).toHaveLength(3);

    act(() => result.current.workspace.actions.selectScope("mine"));
    expect(result.current.visible.map((t) => t.id)).toEqual(["late"]);

    act(() => {
      result.current.workspace.actions.selectScope("all");
      result.current.workspace.actions.setSort("importance");
    });
    expect(result.current.visible.map((t) => t.id)).toEqual(["theirs", "late"]);
  });

  it("exposes every action the views need", async () => {
    const { result } = setup();
    await ready(result);
    const { actions } = result.current.workspace;
    act(() => {
      actions.toggleProject("inbox");
      actions.setStatusFilter("all");
      actions.setDueFilter("none");
      actions.setPriorityFilter("2");
      actions.setSearch("x");
      actions.toggleSignal("soon");
      actions.setView("board");
      actions.selectTask("late");
    });
    expect(result.current.workspace.state).toMatchObject({
      query: { project: "inbox", status: "all", due: "none", priority: "2", search: "x", signal: "soon" },
      view: "board",
      selectedId: "late",
    });
    act(() => {
      actions.clearSignal();
      actions.clearSelection();
    });
    expect(result.current.workspace.state).toMatchObject({ query: { signal: null }, selectedId: null });
  });

  it("reports a load failure and recovers on retry", async () => {
    const service = new FakeTaskService(tasks);
    service.list = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(tasks);
    const { result } = setup(service);
    await waitFor(() => expect(result.current.workspace.state.load).toEqual({ status: "error", message: "offline" }));
    act(() => result.current.workspace.actions.reload());
    await ready(result);
    expect(result.current.workspace.state.tasks).toHaveLength(3);
  });

  it("commands call the service and sync the result into the state", async () => {
    const { result, taskService } = setup();
    await ready(result);

    await act(() => result.current.commands.toggleDone("late"));
    expect(taskService.calls).toContainEqual(["toggleDone", "late"]);
    expect(result.current.workspace.state.tasks.find((t) => t.id === "late")?.status).toBe("done");

    await act(() => result.current.commands.move("theirs", "testing"));
    await act(() => result.current.commands.update("theirs", { title: "Ours" }));
    await act(() => result.current.commands.addStep("theirs", "step"));
    expect(result.current.workspace.state.tasks.find((t) => t.id === "theirs")).toMatchObject({ status: "testing", title: "Ours", steps: [{ text: "step" }] });
  });

  it("creates into the selected project, or the Inbox, and can open the new task", async () => {
    const { result, taskService } = setup();
    await ready(result);

    await act(() => result.current.commands.create({ title: "Quick" }));
    expect(taskService.calls).toContainEqual(["create", { title: "Quick", project: "inbox" }]);
    expect(result.current.workspace.state.selectedId).toBeNull();

    act(() => result.current.workspace.actions.toggleProject("ballast"));
    await act(() => result.current.commands.create({ title: "Untitled task", status: "testing" }, { open: true }));
    expect(taskService.calls).toContainEqual(["create", { title: "Untitled task", status: "testing", project: "ballast" }]);
    const [first] = result.current.workspace.state.tasks;
    expect(first.title).toBe("Untitled task");
    expect(result.current.workspace.state.selectedId).toBe(first.id);
  });

  it("removes a task", async () => {
    const { result } = setup();
    await ready(result);
    await act(() => result.current.commands.remove("late"));
    expect(result.current.workspace.state.tasks.map((t) => t.id)).toEqual(["theirs", "shipped"]);
  });

  it("removing a task discards the step generation in flight for it", async () => {
    const { result, stepGeneration } = setup();
    await ready(result);
    await stepGeneration.start("late");
    await act(() => result.current.commands.remove("late"));
    expect(stepGeneration.current()).toBeNull();
  });

  it("removing a task leaves another task's step generation running", async () => {
    const { result, stepGeneration } = setup();
    await ready(result);
    await stepGeneration.start("theirs");
    await act(() => result.current.commands.remove("late"));
    expect(stepGeneration.current()).toEqual({ taskId: "theirs", phase: "running" });
  });

  it("refuses to run outside its provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => useWorkspace())).toThrow(/WorkspaceProvider/);
    spy.mockRestore();
  });
});
