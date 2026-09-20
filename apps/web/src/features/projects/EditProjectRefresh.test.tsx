import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import type { Project } from "@/features/tasks/model/types";
import { WorkspaceProvider, useDirectory, useWorkspace } from "@/features/tasks/workspace/WorkspaceProvider";
import { EditProjectControl } from "./EditProjectControl";

function EditorWithRefresh() {
  const { projects } = useDirectory();
  const { actions } = useWorkspace();
  return <>
    <button onClick={actions.reload}>Refresh directory</button>
    <output data-testid="canonical">{JSON.stringify(projects[0])}</output>
    {projects[0] && <EditProjectControl project={projects[0]} />}
  </>;
}

describe("open project editor across authoritative directory refresh", () => {
  for (const field of ["name", "tone"] as const) {
    for (const timing of ["during edit", "before edit", "unchanged"] as const) {
      it(`${field}-only save preserves untouched fields when refresh is ${timing}`, async () => {
        const { directoryService } = renderWithServices(<WorkspaceProvider><EditorWithRefresh /></WorkspaceProvider>);
        await screen.findByRole("button", { name: "Edit project" });
        const [original] = await directoryService.projects();
        let finish!: (projects: Project[]) => void;
        vi.spyOn(directoryService, "projects").mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
        fireEvent.click(screen.getByRole("button", { name: "Refresh directory" }));
        if (timing !== "before edit") fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
        // Explicit second-client simulation: change the adapter's saved row while GET is held.
        if (timing !== "unchanged") await directoryService.updateProject(original.id, field === "name" ? { tone: "warn" } : { name: "New server name" });
        const fetched = await directoryService.projects();
        await act(async () => finish(fetched));
        expect(screen.getByTestId("canonical")).toHaveTextContent(JSON.stringify(fetched[0]));
        if (timing === "before edit") fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
        const before = directoryService.calls.length;
        const patch = field === "name" ? { name: "Local renamed project" } : { tone: "info" };
        if (field === "name") fireEvent.change(screen.getByLabelText("Name"), { target: { value: patch.name } });
        else fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
        expect(directoryService.calls.slice(before)).toEqual([["updateProject", original.id, patch]]);
        expect((await directoryService.projects())[0]).toEqual({ ...fetched[0], ...patch });
        expect(screen.getByTestId("canonical")).toHaveTextContent(JSON.stringify({ ...fetched[0], ...patch }));
      });
    }
  }
  it("closing an untouched draft after a refresh is still a no-op", async () => {
    const { directoryService } = renderWithServices(<WorkspaceProvider><EditorWithRefresh /></WorkspaceProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Edit project" }));
    const [original] = await directoryService.projects();
    await directoryService.updateProject(original.id, { name: "Other reader", tone: "warn" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh directory" }));
    await waitFor(() => expect(screen.getByTestId("canonical")).toHaveTextContent("Other reader"));
    const before = directoryService.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toHaveLength(before);
    expect((await directoryService.projects())[0]).toMatchObject({ name: "Other reader", tone: "warn" });
  });
});
