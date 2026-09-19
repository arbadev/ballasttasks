import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { FakeTaskService } from "@/test/fakeServices";
import { makeTask } from "@/test/tasks";
import { WorkspaceProvider, useTaskCommands, useWorkspace } from "./WorkspaceProvider";

const task = makeTask({ id: "storage", attachments: [] });
const uploaded = { ...task, attachments: [{ id: "file", name: "proof.pdf", kind: "pdf" as const, meta: "3 B" }] };
const file = new File(["pdf"], "proof.pdf", { type: "application/pdf" });

function Probe({ downloaded }: { downloaded: (blob: Blob) => void }) {
  const commands = useTaskCommands();
  const { state } = useWorkspace();
  return <>
    <output>{state.tasks.find((t) => t.id === task.id)?.attachments.length ?? "loading"}</output>
    <button disabled={!commands.uploadAttachment} onClick={() => void commands.uploadAttachment?.(task.id, file)}>Upload</button>
    <button disabled={!commands.downloadAttachment} onClick={() => void commands.downloadAttachment?.(task.id, "file").then(downloaded)}>Download</button>
    <button disabled={!commands.removeAttachment} onClick={() => void commands.removeAttachment?.(task.id, "file")}>Remove</button>
  </>;
}

describe("workspace storage capabilities", () => {
  it("synchronizes upload and removal results and delegates authenticated download", async () => {
    const blob = new Blob(["content"]);
    const service = Object.assign(new FakeTaskService([task]), {
      uploadAttachment: vi.fn().mockResolvedValue(uploaded),
      downloadAttachment: vi.fn().mockResolvedValue(blob),
      removeAttachment: vi.fn().mockResolvedValue(task),
    });
    const downloaded = vi.fn();
    renderWithServices(<WorkspaceProvider><Probe downloaded={downloaded} /></WorkspaceProvider>, { taskService: service });
    await screen.findByText("0");
    fireEvent.click(screen.getByText("Upload"));
    await screen.findByText("1");
    expect(service.uploadAttachment).toHaveBeenCalledExactlyOnceWith(task.id, file);
    fireEvent.click(screen.getByText("Download"));
    await waitFor(() => expect(downloaded).toHaveBeenCalledWith(blob));
    expect(service.downloadAttachment).toHaveBeenCalledExactlyOnceWith(task.id, "file");
    fireEvent.click(screen.getByText("Remove"));
    await screen.findByText("0");
    expect(service.removeAttachment).toHaveBeenCalledExactlyOnceWith(task.id, "file");
  });

  it("does not advertise unavailable file capabilities in older explicit demo doubles", async () => {
    renderWithServices(<WorkspaceProvider><Probe downloaded={vi.fn()} /></WorkspaceProvider>, { taskService: new FakeTaskService([task]) });
    await screen.findByText("0");
    for (const name of ["Upload", "Download", "Remove"]) expect(screen.getByText(name)).toBeDisabled();
  });
});
