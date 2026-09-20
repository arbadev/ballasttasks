import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { FakeDirectoryService, FakeTaskService } from "@/test/fakeServices";
import { makeTask } from "@/test/tasks";
import type { Project } from "../model/types";
import { WorkspaceProvider, useDirectory, useWorkspace } from "./WorkspaceProvider";

function setup(directoryService = new FakeDirectoryService()) {
  const taskService = new FakeTaskService([makeTask()]);
  const wrapper = ({ children }: { children: ReactNode }) => <Providers directoryService={directoryService} taskService={taskService}><WorkspaceProvider>{children}</WorkspaceProvider></Providers>;
  return { directoryService, ...renderHook(() => ({ ...useWorkspace(), directory: useDirectory() }), { wrapper }) };
}

describe("project directory synchronization", () => {
  it("keeps canonical saved metadata over an older directory refresh, leaving tasks and selection intact", async () => {
    const { result, directoryService } = setup();
    await waitFor(() => expect(result.current.directory.projects).toHaveLength(2));
    const original = result.current.directory.projects[0];
    let finish!: (projects: Project[]) => void;
    vi.spyOn(directoryService, "projects").mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    act(() => { result.current.actions.toggleProject(original.id); result.current.actions.reload(); });
    const tasks = result.current.state.tasks;
    await act(() => result.current.actions.updateProject(original.id, { name: "Canonical", tone: "info" }));
    await act(async () => finish([original]));
    expect(result.current.directory.projects[0]).toMatchObject({ name: "Canonical", tone: "info", key: original.key });
    expect(result.current.state.query.project).toBe(original.id);
    expect(result.current.state.tasks).toEqual(tasks);
    act(() => result.current.actions.reload());
    await waitFor(() => expect(result.current.state.load.status).toBe("ready"));
    expect(result.current.directory.projects[0].name).toBe("Canonical");
  });
  it("keeps only the edited project local, listing the projects the late refresh brings with it", async () => {
    const { result, directoryService } = setup();
    await waitFor(() => expect(result.current.directory.projects).toHaveLength(2));
    const [original, other] = result.current.directory.projects;
    const elsewhere: Project = { id: "elsewhere", name: "Made elsewhere", key: "ME", tone: "ok" };
    let finish!: (projects: Project[]) => void;
    vi.spyOn(directoryService, "projects").mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    act(() => { result.current.actions.reload(); });
    await act(() => result.current.actions.updateProject(original.id, { name: "Canonical", tone: "info" }));
    await act(async () => finish([original, other, elsewhere]));
    expect(result.current.directory.projects.map((project) => project.name)).toEqual(["Canonical", other.name, "Made elsewhere"]);
    expect(result.current.directory.projects[0].key).toBe(original.key);
    act(() => result.current.actions.reload());
    await waitFor(() => expect(result.current.state.load.status).toBe("ready"));
    expect(result.current.directory.projects.map((project) => project.name)).toEqual(["Canonical", other.name]);
  });
  it("ignores a save completing after the directory session changes", async () => {
    const oldDirectory = new FakeDirectoryService();
    let service = oldDirectory;
    const taskService = new FakeTaskService([]);
    const wrapper = ({ children }: { children: ReactNode }) => <Providers directoryService={service} taskService={taskService}><WorkspaceProvider>{children}</WorkspaceProvider></Providers>;
    const { result, rerender } = renderHook(() => ({ ...useWorkspace(), directory: useDirectory() }), { wrapper });
    await waitFor(() => expect(result.current.directory.projects).toHaveLength(2));
    const project = result.current.directory.projects[0];
    const gate = oldDirectory.holdNextCreate();
    let saving!: Promise<void>;
    act(() => { saving = result.current.actions.updateProject(project.id, { name: "Obsolete", tone: "warn" }); });
    service = new FakeDirectoryService({ projects: [{ ...project, name: "New session" }] });
    rerender();
    await waitFor(() => expect(result.current.directory.projects[0].name).toBe("New session"));
    await act(async () => { gate.release(); await saving; });
    expect(result.current.directory.projects[0].name).toBe("New session");
  });
  it("does not allow an older edit response to replace a newer saved edit", async () => {
    const { result, directoryService } = setup();
    await waitFor(() => expect(result.current.directory.projects).toHaveLength(2));
    const project = result.current.directory.projects[0];
    let finish!: (project: Project) => void;
    vi.spyOn(directoryService, "updateProject").mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    let old!: Promise<void>;
    act(() => { old = result.current.actions.updateProject(project.id, { name: "Older", tone: "warn" }); });
    await act(() => result.current.actions.updateProject(project.id, { name: "Newer", tone: "info" }));
    await act(async () => { finish({ ...project, name: "Older", tone: "warn" }); await old; });
    expect(result.current.directory.projects[0].name).toBe("Newer");
  });
});
