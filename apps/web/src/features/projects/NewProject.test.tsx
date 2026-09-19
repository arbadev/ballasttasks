import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TasksApp } from "@/features/tasks/shell/TasksApp";
import { ProjectRejectedError } from "@/features/tasks/services/types";
import { FakeDirectoryService } from "@/test/fakeServices";
import { renderWithServices } from "@/test/renderWithServices";

async function renderApp(directoryService = new FakeDirectoryService()) {
  const view = renderWithServices(<TasksApp />, { directoryService });
  await screen.findByText("13 tasks");
  return view;
}

const sidebar = () => within(screen.getByRole("complementary", { name: "Workspace" }));
const control = () => sidebar().getByRole("button", { name: "New project" });
const dialog = () => screen.getByRole("dialog", { name: "New project" });
const field = (name: string) => within(dialog()).getByRole("textbox", { name });
const submit = () => fireEvent.submit(within(dialog()).getByRole("form", { name: "New project" }));
const type = (name: string, value: string) => fireEvent.change(field(name), { target: { value } });
const backdrop = () => screen.getByTestId("new-project-backdrop");

function clickBackdrop() {
  fireEvent.mouseDown(backdrop());
  fireEvent.mouseUp(backdrop());
  fireEvent.click(backdrop());
}

function open() {
  fireEvent.click(control());
  return dialog();
}

async function createMarketing() {
  open();
  type("Name", "Marketing");
  submit();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

describe("the New project control", () => {
  it("sits in the sidebar's Projects section and opens a modal dialog with the name focused", async () => {
    await renderApp();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(control()).toHaveAttribute("aria-haspopup", "dialog");

    const box = open();
    expect(box).toHaveAttribute("aria-modal", "true");
    expect(field("Name")).toHaveFocus();
    expect(within(box).getByRole("button", { name: "Create project" })).toBeEnabled();
    expect(within(box).getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("closes on Escape, on Cancel and on the backdrop, returning focus to the control without creating anything", async () => {
    const { directoryService } = await renderApp();

    open();
    fireEvent.keyDown(field("Name"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(control()).toHaveFocus();

    open();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(control()).toHaveFocus();

    open();
    fireEvent.click(within(dialog()).getByRole("textbox", { name: "Name" }));
    expect(dialog()).toBeInTheDocument();
    clickBackdrop();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    expect(directoryService.calls).toEqual([]);
  });

  it("stays open when a drag that started inside the dialog ends on the backdrop", async () => {
    await renderApp();
    open();
    type("Name", "Marketing");

    // Selecting text in the name and releasing outside: the click lands on the common ancestor.
    fireEvent.mouseDown(field("Name"));
    fireEvent.mouseUp(backdrop());
    fireEvent.click(backdrop());
    expect(field("Name")).toHaveValue("Marketing");

    clickBackdrop();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("forgets an abandoned draft", async () => {
    await renderApp();
    open();
    type("Name", "Marketing");
    fireEvent.keyDown(field("Name"), { key: "Escape" });
    open();
    expect(field("Name")).toHaveValue("");
    expect(field("Key")).toHaveValue("");
  });

  it("keeps Tab inside the dialog", async () => {
    await renderApp();
    const box = open();
    const cancel = within(box).getByRole("button", { name: "Cancel" });
    const create = within(box).getByRole("button", { name: "Create project" });

    create.focus();
    fireEvent.keyDown(create, { key: "Tab" });
    expect(field("Name")).toHaveFocus();

    fireEvent.keyDown(field("Name"), { key: "Tab", shiftKey: true });
    expect(create).toHaveFocus();

    // Inside the dialog Tab is left to the browser.
    cancel.focus();
    expect(fireEvent.keyDown(cancel, { key: "Tab" })).toBe(true);
  });
});

describe("the New project form", () => {
  it("suggests the key from the name until the key is edited by hand", async () => {
    await renderApp();
    open();
    type("Name", "Release notes");
    expect(field("Key")).toHaveValue("RN");
    type("Name", "Big Thing");
    expect(field("Key")).toHaveValue("BIG"); // BT belongs to Ballast Tasks

    type("Key", "x-y9z");
    expect(field("Key")).toHaveValue("XYZ");
    type("Name", "Marketing");
    expect(field("Key")).toHaveValue("XYZ");
  });

  it("offers the token colours as a radio group, preselecting one no project uses yet", async () => {
    await renderApp();
    const colours = within(within(open()).getByRole("radiogroup", { name: "Colour" }));
    expect(colours.getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual(["Lime", "Blue", "Green", "Amber", "Grey"]);
    expect(colours.getByRole("radio", { name: "Blue" })).toBeChecked();

    fireEvent.click(colours.getByRole("radio", { name: "Amber" }));
    expect(colours.getByRole("radio", { name: "Amber" })).toBeChecked();
    expect(colours.getByRole("radio", { name: "Blue" })).not.toBeChecked();
  });

  it("shows inline messages and creates nothing while the draft is invalid", async () => {
    const { directoryService } = await renderApp();
    open();
    submit();

    expect(field("Name")).toHaveAttribute("aria-invalid", "true");
    expect(field("Name")).toHaveAccessibleDescription("Give the project a name.");
    expect(field("Key")).toHaveAccessibleDescription(/Use 2 to 4 letters\./);
    expect(field("Name")).toHaveFocus();
    expect(directoryService.calls).toEqual([]);

    // A message clears as soon as its field is corrected.
    type("Name", "ballast tasks");
    expect(field("Name")).toHaveAttribute("aria-invalid", "false");
    submit();
    expect(field("Name")).toHaveAccessibleDescription('A project named "Ballast Tasks" already exists.');

    type("Name", "Marketing");
    type("Key", "BT");
    submit();
    expect(field("Key")).toHaveAccessibleDescription(/The key BT is already used by Ballast Tasks\./);
    expect(field("Key")).toHaveFocus();
    expect(directoryService.calls).toEqual([]);
  });

  it("creates the project through the directory service with the trimmed name, the key and the colour", async () => {
    const { directoryService } = await renderApp();
    open();
    type("Name", "  Marketing  ");
    fireEvent.click(within(dialog()).getByRole("radio", { name: "Green" }));
    submit();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toEqual([["createProject", { name: "Marketing", key: "MAR", tone: "ok" }]]);
  });

  it("shows a pending state that cannot be submitted twice or dismissed", async () => {
    const directoryService = new FakeDirectoryService();
    await renderApp(directoryService);
    const held = directoryService.holdNextCreate();
    open();
    type("Name", "Marketing");
    submit();

    const busy = await within(dialog()).findByRole("button", { name: "Creating…" });
    expect(busy).toBeDisabled();
    expect(within(dialog()).getByRole("form")).toHaveAttribute("aria-busy", "true");
    expect(field("Name")).toBeDisabled();
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toBeDisabled();

    submit();
    fireEvent.keyDown(dialog(), { key: "Escape" });
    clickBackdrop();
    expect(dialog()).toBeInTheDocument();
    expect(directoryService.calls).toHaveLength(1);

    await act(async () => held.release());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows an error with a retry, keeps the draft, and succeeds on the second attempt", async () => {
    const directoryService = new FakeDirectoryService();
    await renderApp(directoryService);
    const held = directoryService.holdNextCreate();
    open();
    type("Name", "Marketing");
    submit();
    await act(async () => held.fail(new Error("The connection dropped.")));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert).toHaveTextContent("Could not create the project. The connection dropped.");
    expect(field("Name")).toHaveValue("Marketing");
    expect(field("Name")).toBeEnabled();

    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(directoryService.calls).toHaveLength(2);
    expect(sidebar().getByRole("button", { name: /^Marketing/ })).toBeInTheDocument();
  });

  it("leaves the focus in a field that is edited after a failure, and on the field a later validation rejects", async () => {
    const directoryService = new FakeDirectoryService();
    await renderApp(directoryService);
    const held = directoryService.holdNextCreate();
    open();
    type("Name", "Marketing");
    submit();
    await act(async () => held.fail(new Error("The connection dropped.")));

    const retry = await within(dialog()).findByRole("button", { name: "Retry" });
    expect(retry).toHaveFocus();

    act(() => field("Name").focus());
    type("Name", "Marketing 2");
    expect(field("Name")).toHaveFocus();

    act(() => field("Key").focus());
    type("Key", "MK");
    expect(field("Key")).toHaveFocus();

    type("Key", "BT");
    act(() => retry.focus());
    submit();
    expect(field("Key")).toHaveAccessibleDescription(/The key BT is already used by Ballast Tasks\./);
    expect(field("Key")).toHaveFocus();
    expect(directoryService.calls).toHaveLength(1);
  });

  it("shows a rejection from the service next to the field it is about", async () => {
    const directoryService = new FakeDirectoryService();
    await renderApp(directoryService);
    const held = directoryService.holdNextCreate();
    open();
    type("Name", "Marketing");
    submit();
    await act(async () => held.fail(new ProjectRejectedError({ key: "The key MAR is already used by Margins." })));

    await waitFor(() => expect(field("Key")).toHaveAccessibleDescription(/The key MAR is already used by Margins\./));
    expect(within(dialog()).queryByRole("alert")).not.toBeInTheDocument();
    expect(field("Key")).toHaveFocus();
  });
});

describe("a created project", () => {
  it("appears in the sidebar with a zero count, selected, and gives focus back to the control", async () => {
    await renderApp();
    await createMarketing();

    const item = sidebar().getByRole("button", { name: /^Marketing/ });
    expect(item).toHaveTextContent("Marketing0");
    expect(item).toHaveAttribute("aria-pressed", "true");
    expect(within(sidebar().getByRole("navigation", { name: "Projects" })).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Ballast Tasks11",
      "Inbox2",
      "Marketing0",
    ]);
    expect(screen.getByTestId("crumb")).toHaveTextContent("Marketing");
    expect(screen.getByText("0 tasks")).toBeInTheDocument();
    await waitFor(() => expect(control()).toHaveFocus());
  });

  it("shows an empty state that invites the first task, and adds it to the project", async () => {
    const { taskService } = await renderApp();
    await createMarketing();

    const empty = within(screen.getByRole("region", { name: "Marketing has no tasks yet" }));
    expect(empty.getByText("MAR")).toBeInTheDocument();
    const input = empty.getByRole("textbox", { name: "Name the first task" });

    // Blank input is ignored.
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(taskService.calls.filter(([name]) => name === "create")).toEqual([]);

    fireEvent.change(input, { target: { value: " Draft the launch post " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Marketing has no tasks yet" })).not.toBeInTheDocument());

    expect(taskService.calls).toContainEqual(["create", { title: "Draft the launch post", project: "p1" }]);
    expect(within(screen.getByRole("list", { name: "Tasks" })).getByText("Draft the launch post")).toBeInTheDocument();
    expect(sidebar().getByRole("button", { name: /^Marketing/ })).toHaveTextContent("Marketing1");
  });

  it("opens over clean filters, so leftover ones cannot hide its first task", async () => {
    await renderApp();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "done" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "overdue" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), { target: { value: "importance" } });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "jwt" } });
    await createMarketing();

    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("open");
    expect(screen.getByRole("combobox", { name: "Due" })).toHaveValue("any");
    expect(screen.getByRole("combobox", { name: "Priority" })).toHaveValue("any");
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Sort" })).toHaveValue("importance");

    const input = within(screen.getByRole("region", { name: "Marketing has no tasks yet" })).getByRole("textbox", { name: "Name the first task" });
    fireEvent.change(input, { target: { value: "Draft the launch post" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await within(await screen.findByRole("list", { name: "Tasks" })).findByText("Draft the launch post")).toBeInTheDocument();
  });

  it("is where New task creates its tasks", async () => {
    const { taskService } = await renderApp();
    await createMarketing();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    await waitFor(() => expect(taskService.calls).toContainEqual(["create", { title: "Untitled task", project: "p1" }]));
  });

  it("keeps the ordinary views for projects that have tasks, and for no project at all", async () => {
    await renderApp();
    expect(screen.queryByRole("region", { name: /has no tasks yet/ })).not.toBeInTheDocument();
    fireEvent.click(sidebar().getByRole("button", { name: /^Inbox/ }));
    expect(screen.queryByRole("region", { name: /has no tasks yet/ })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Tasks" })).toBeInTheDocument();
  });

  it("can be followed by another, whose key avoids the first one's", async () => {
    await renderApp();
    await createMarketing();
    open();
    type("Name", "Margins");
    expect(field("Key")).toHaveValue("MAG");
  });
});
