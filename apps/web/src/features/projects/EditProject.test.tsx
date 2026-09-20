import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { ProjectRejectedError } from "@/features/tasks/services/types";
import { TasksApp } from "@/features/tasks/shell/TasksApp";
import { FakeDirectoryService } from "@/test/fakeServices";

describe("project editing", () => {
  it("saves name and colour without changing the selected project or its key", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    expect(screen.getByLabelText("Key")).toHaveValue(project.key);
    expect(screen.getByLabelText("Key")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Key")).toHaveAttribute("id");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed project" } });
    fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit project" })).not.toBeInTheDocument());
    expect(directoryService.calls).toContainEqual(["updateProject", project.id, { name: "Renamed project", tone: "info" }]);
    expect(screen.getByTestId("crumb")).toHaveTextContent("Renamed project");
    expect((await directoryService.projects())[0]).toMatchObject({ key: project.key, name: "Renamed project", tone: "info" });
  });
  it("validates, locks pending controls, retains refused input and retries without false success", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Give the project a name.")).toBeVisible();
    expect(directoryService.calls).toEqual([]);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Try again" } });
    const gate = directoryService.holdNextCreate();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Blue" })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeVisible();
    await act(async () => gate.fail(new Error("Refused")));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save the project");
    expect(screen.getByLabelText("Name")).toHaveValue("Try again");
    expect(screen.getByTestId("crumb")).toHaveTextContent(project.name);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("crumb")).toHaveTextContent("Try again");
    expect(directoryService.calls).toHaveLength(2);
  });
  it("shows a refused name on the field alone, then saves the corrected name", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Taken elsewhere" } });
    const gate = directoryService.holdNextCreate();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    // The directory refuses the field, as it does when another session took the name first.
    await act(async () => gate.fail(new ProjectRejectedError({ name: "That name is already used." })));
    expect(screen.getByText("That name is already used.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Taken elsewhere");
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("crumb")).toHaveTextContent(project.name);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Free name" } });
    expect(screen.queryByText("That name is already used.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("crumb")).toHaveTextContent("Free name");
  });
  it("moves the keyboard to what must change and drops a banner the next refusal supersedes", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "" } });
    screen.getByRole("button", { name: "Save changes" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByLabelText("Name")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Try again" } });
    const gate = directoryService.holdNextCreate();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await act(async () => gate.fail(new Error("Offline")));
    expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Give the project a name.")).toBeVisible();
    expect(screen.getByLabelText("Name")).toHaveFocus();
  });
  it("sends only the field that changed, leaving the other as it is stored", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toEqual([["updateProject", project.id, { tone: "info" }]]);
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed only" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls[1]).toEqual(["updateProject", project.id, { name: "Renamed only" }]);
    expect((await directoryService.projects())[0]).toMatchObject({ name: "Renamed only", tone: "info", key: project.key });
  });
  it("recolours a project whose stored name only the API could have given it", async () => {
    const stored = "A project the API named with a title far longer than the form allows";
    const directoryService = new FakeDirectoryService({ projects: [
      { id: "ballast", name: stored, key: "BT", tone: "muted" },
      { id: "twin", name: stored, key: "TW", tone: "muted" },
      { id: "inbox", name: "Inbox", key: "IN", tone: "muted" },
    ] });
    renderWithServices(<TasksApp />, { directoryService });
    fireEvent.click((await screen.findAllByRole("button", { name: new RegExp(stored) }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    expect(screen.getByLabelText("Name")).toHaveValue(stored);
    fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toEqual([["updateProject", "ballast", { tone: "info" }]]);
  });
  it("recolours a stored name that keeps its own inner spacing, and still renames when asked to", async () => {
    const spaced = "Design  System";
    const longSpaced = "A project the API named  with two spaces and more than forty characters";
    const directoryService = new FakeDirectoryService({ projects: [
      { id: "ballast", name: spaced, key: "BT", tone: "muted" },
      { id: "long", name: longSpaced, key: "LO", tone: "muted" },
      { id: "inbox", name: "Inbox", key: "IN", tone: "muted" },
    ] });
    renderWithServices(<TasksApp />, { directoryService });
    fireEvent.click(await screen.findByRole("button", { name: /Design/ }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    expect(screen.getByLabelText("Name")).toHaveValue(spaced);
    fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toEqual([["updateProject", "ballast", { tone: "info" }]]);
    fireEvent.click(screen.getByRole("button", { name: /A project the API named/ }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.click(screen.getByRole("radio", { name: "Green" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls[1]).toEqual(["updateProject", "long", { tone: "ok" }]);
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Renamed  at  last  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls[2]).toEqual(["updateProject", "long", { name: "Renamed at last" }]);
  });
  it("cancels and closes unchanged forms without a write", async () => {
    const { directoryService } = renderWithServices(<TasksApp />);
    const [project] = await directoryService.projects();
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(project.name) }));
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Discard me" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(directoryService.calls).toEqual([]);
  });
});
