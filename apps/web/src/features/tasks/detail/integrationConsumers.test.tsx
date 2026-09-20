import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "@/test/fakeServices";
import { NOW, makeTask as buildTask } from "@/test/tasks";
import type { TaskService } from "../services/types";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { TaskDetail } from "./TaskDetail";

function Opener() {
  const { actions } = useWorkspace();
  return <button onClick={() => actions.selectTask("t1")}>Open integration task</button>;
}

async function setup(service: TaskService = new FakeTaskService([buildTask({ id: "t1" })])) {
  const generation = new FakeStepGenerationService();
  render(<Providers taskService={service} directoryService={new FakeDirectoryService()} stepGenerationService={generation} clock={() => NOW}>
    <WorkspaceProvider><Opener /><TaskDetail /></WorkspaceProvider>
  </Providers>);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Open integration task" }));
  return { generation, service };
}

afterEach(() => vi.restoreAllMocks());

// Controlled port tests of the delivered UI; live persistence is verified separately.
describe("detail integration consumers", () => {
  it("shows the immutable server task key instead of synthesizing one from a UUID", async () => {
    await setup(new FakeTaskService([buildTask({ id: "t1", key: "UCI-01" })]));
    expect(within(screen.getByRole("dialog")).getByText("UCI-01")).toBeVisible();
    expect(within(screen.getByRole("dialog")).queryByText("BT-01")).not.toBeInTheDocument();
  });
  it("does not mount writable fabricated detail while only a list summary is loaded, and retries a refusal", async () => {
    const service = new FakeTaskService([buildTask({ id: "t1", detailLoaded: false, description: "summary" })]);
    let refuse!: (reason: Error) => void;
    const get = vi.spyOn(service, "get").mockImplementationOnce(() => new Promise((_, reject) => { refuse = reject; }))
      .mockResolvedValue(buildTask({ id: "t1", detailLoaded: true, description: "Authoritative description" }));
    await setup(service);
    expect(screen.getByRole("status", { name: "Loading task details" })).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Description" })).not.toBeInTheDocument();
    await act(async () => refuse(new Error("Detail unavailable")));
    expect(screen.getByRole("alert")).toHaveTextContent("Detail unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry task details" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("Authoritative description"));
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("shows terminal generation errors and status-check notices instead of silently hiding them", async () => {
    const { generation } = await setup();
    act(() => generation.emit({ taskId: "t1", phase: "error", message: "Generation timed out. Try again." }));
    expect(screen.getByRole("alert")).toHaveTextContent("Generation timed out. Try again.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(generation.calls).toContainEqual(["start", "t1"]);
    act(() => generation.emit({ taskId: "t1", phase: "running", notice: "Waiting to retry the status check…" }));
    expect(screen.getByRole("status", { name: "Drafting steps" })).toHaveTextContent("Waiting to retry the status check…");
  });

  it("keeps rejected proposals visible, locks all proposal mutations during acceptance and makes discard local", async () => {
    const service = new FakeTaskService([buildTask({ id: "t1" })]);
    const get = vi.spyOn(service, "get");
    const { generation } = await setup(service);
    const proposal = { taskId: "t1", phase: "proposed" as const, steps: [{ id: "p1", text: "One proposal" }] };
    act(() => generation.emit({ ...proposal, accepting: true }));
    for (const name of ["Add 1 step", "Regenerate", "Discard", "Remove proposed step: One proposal", "Generate steps"])
      expect(screen.getByRole("button", { name })).toBeDisabled();
    act(() => generation.emit({ ...proposal, notice: "No steps were added. Check the 100-step limit and selected proposals." }));
    expect(screen.getByRole("alert")).toHaveTextContent("100-step limit");
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    await act(async () => {});
    expect(generation.calls).toContainEqual(["discard"]);
    expect(get).not.toHaveBeenCalled();
  });

  it("requires canonical readback, not another acceptance or generation, after an uncertain response", async () => {
    const task = buildTask({ id: "t1" });
    const service = new FakeTaskService([task]);
    const get = vi.spyOn(service, "get").mockResolvedValue({ ...task, steps: [{ id: "accepted", text: "Already accepted", done: false }] });
    const { generation } = await setup(service);
    act(() => generation.emit({ taskId: "t1", phase: "error", recovery: "reload", message: "Acceptance could not be confirmed. Reload the task before generating again." }));
    expect(screen.getByRole("button", { name: "Generate steps" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload task" }));
    expect(await screen.findByText("Already accepted")).toBeVisible();
    expect(get).toHaveBeenCalledOnce();
    expect(generation.calls).toEqual([["discard"]]);
    expect(screen.getByRole("button", { name: "Generate steps" })).toBeEnabled();
  });

  it("closes the panel when the reload finds the task deleted, and deletes nothing itself", async () => {
    const service = new FakeTaskService([buildTask({ id: "t1" })]);
    const get = vi.spyOn(service, "get").mockResolvedValue(null);
    const remove = vi.spyOn(service, "remove");
    const { generation } = await setup(service);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => generation.emit({ taskId: "t1", phase: "error", recovery: "reload", message: "This generation expired or its task was deleted. Reload the task." }));
    fireEvent.click(screen.getByRole("button", { name: "Reload task" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(get).toHaveBeenCalledOnce();
    expect(remove).not.toHaveBeenCalled();
    expect(generation.calls).toEqual([["discard"]]);
  });

  it("downloads authenticated bytes via the command and removes only after the service confirms", async () => {
    const attachment = { id: "file-id", kind: "pdf" as const, name: "proof.pdf", meta: "PDF · 8 bytes" };
    const task = buildTask({ id: "t1", attachments: [attachment] });
    const service = Object.assign(new FakeTaskService([task]), {
      downloadAttachment: vi.fn(async () => new Blob(["%PDF-ok"])),
      removeAttachment: vi.fn(async () => ({ ...task, attachments: [] })),
    });
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-download");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("proof.pdf");
      expect(this.href).toBe("blob:test-download");
    });
    await setup(service);
    const section = within(screen.getByRole("region", { name: "Attachments" }));
    fireEvent.click(section.getByRole("button", { name: "Download proof.pdf" }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(service.downloadAttachment).toHaveBeenCalledWith("t1", "file-id");
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:test-download"));
    service.removeAttachment.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(section.getByRole("button", { name: "Remove attachment: proof.pdf" }));
    expect(await section.findByRole("alert")).toHaveTextContent("Could not remove");
    expect(section.getByText("proof.pdf")).toBeVisible();
    fireEvent.click(section.getByRole("button", { name: "Remove attachment: proof.pdf" }));
    await waitFor(() => expect(section.queryByText("proof.pdf")).not.toBeInTheDocument());
    expect(service.removeAttachment).toHaveBeenCalledWith("t1", "file-id");
  });
});
