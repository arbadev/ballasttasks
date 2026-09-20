import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ListView } from "../list/ListView";
import type { Task } from "../model/types";
import { TasksApp } from "../shell/TasksApp";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { TaskDetail } from "./TaskDetail";
import { FakeTaskService } from "@/test/fakeServices";
import { renderWithServices } from "@/test/renderWithServices";
import { NOW, due, makeTask } from "@/test/tasks";
import { seedTasks } from "../services/seed";
import { openTask, opener, renderDetail, settle } from "./testing/renderDetail";

describe("opening and closing", () => {
  it("renders nothing until a task is selected", async () => {
    await renderDetail();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a modal dialog named after the task, with its key, project and status", async () => {
    await renderDetail();
    const dialog = openTask("t4");
    expect(dialog).toHaveAccessibleName("JWT authentication");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByText("BT-04")).toBeInTheDocument();
    expect(within(dialog).getByTestId("detail-project")).toHaveTextContent("Ballast Tasks");
    expect(within(dialog).getByTestId("detail-status")).toHaveTextContent("To Do");
  });

  it("closes from the Close button, from Escape and from the backdrop, but not from a click inside", async () => {
    await renderDetail();

    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openTask("t4");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const dialog = openTask("t4");
    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("detail-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("has a back control for the full-screen layout that closes the panel", async () => {
    await renderDetail();
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Back to tasks" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("focus management", () => {
  it("moves focus into the panel on open and back to the opener on close", async () => {
    await renderDetail();
    const dialog = openTask("t4");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(opener("t4")).toHaveFocus();
  });

  it("keeps Tab inside the panel, wrapping at both ends", async () => {
    await renderDetail();
    const dialog = openTask("t4");
    const focusable = [...dialog.querySelectorAll<HTMLElement>("button, input, select, textarea")].filter((el) => !el.hasAttribute("disabled") && el.tabIndex >= 0);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });
});

describe("attention banner", () => {
  it("states why the task needs attention", async () => {
    await renderDetail();
    openTask("t4");
    expect(screen.getByTestId("detail-banner")).toHaveTextContent("P0 due in 4 days · needs an owner");
  });

  it("is absent for a calm task", async () => {
    await renderDetail();
    openTask("t9");
    expect(screen.queryByTestId("detail-banner")).not.toBeInTheDocument();
  });

  it("Assign to me assigns the current user and the banner drops the owner warning", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));
    await settle();
    expect(taskService.calls).toContainEqual(["update", "t4", { assignee: "ab" }]);
    expect(within(screen.getByTestId("detail-banner")).getByText("P0 due in 4 days")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign to me" })).not.toBeInTheDocument();
  });

  it("Due tomorrow and +1 week reschedule with the design's activity notes", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1", due: due(-2) }), makeTask({ id: "t2", due: due(1) })] });
    openTask("t1");
    fireEvent.click(screen.getByRole("button", { name: "Due tomorrow" }));
    await settle();
    expect(taskService.calls).toContainEqual(["update", "t1", { due: due(1) }, "Due date moved to tomorrow"]);

    // An overdue task moves a week out from today; a future one from its own date.
    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t2");
    fireEvent.click(screen.getByRole("button", { name: "+1 week" }));
    await settle();
    expect(taskService.calls).toContainEqual(["update", "t2", { due: due(8) }, "Due date moved a week out"]);
  });

  it("+1 week counts from today when the task is already late", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1", due: due(-5) })] });
    openTask("t1");
    fireEvent.click(screen.getByRole("button", { name: "+1 week" }));
    await settle();
    expect(taskService.calls).toContainEqual(["update", "t1", { due: due(7) }, "Due date moved a week out"]);
  });

  it("Break it into steps starts a generation and then leaves the banner", async () => {
    const { generation } = await renderDetail();
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Break it into steps" }));
    await settle();
    expect(generation.calls).toEqual([["start", "t4"]]);
    expect(screen.queryByRole("button", { name: "Break it into steps" })).not.toBeInTheDocument();
  });
});

describe("footer", () => {
  it("Mark complete completes the task, and the button becomes Reopen", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();
    expect(taskService.calls).toContainEqual(["toggleDone", "t4"]);
    expect(screen.getByTestId("detail-status")).toHaveTextContent("Done");
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });

  it("Delete asks once before removing the task, and Keep backs out", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(taskService.calls).not.toContainEqual(["remove", "t4"]);
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete task" }));
    await settle();
    expect(taskService.calls).toContainEqual(["remove", "t4"]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("open t4")).not.toBeInTheDocument();
  });

  it("keeps the task and says so when the delete fails", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    taskService.remove = async (id: string) => {
      taskService.calls.push(["remove", id]);
      throw new Error("offline");
    };
    await renderDetail({ taskService });
    openTask("t4");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete task" }));
    await settle();

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Could not delete the task. Try again.");
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    // The prompt took the focus when it opened; it must hand it back, not drop it out of the modal.
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);

    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });

  it("keeps the focus inside the modal when the delete prompt is dismissed", async () => {
    await renderDetail();
    openTask("t4");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("button", { name: "Delete task" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const confirm = screen.getByRole("button", { name: "Delete task" });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(confirm, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
  });

  it("says not saved about the task that failed, and nothing about any other", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    const broken = new Set(["t4"]);
    const original = taskService.update.bind(taskService);
    taskService.update = async (id, patch, note) => {
      if (broken.has(id)) throw new Error("offline");
      return original(id, patch, note);
    };
    await renderDetail({ taskService });

    openTask("t4");
    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Will not stick" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Task name" }));
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");

    // Another task carries none of it, and its own successful save cannot clear t4's failure.
    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t6");
    expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);
    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Seeded twice" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Task name" }));
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);

    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t4");
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");

    broken.clear();
    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Sticks now" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Task name" }));
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);
  });

  it("attributes a save still in flight to its own task", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    let release!: () => void;
    const original = taskService.update.bind(taskService);
    taskService.update = async (id, patch, note) => {
      await new Promise<void>((resolve) => (release = resolve));
      return original(id, patch, note);
    };
    await renderDetail({ taskService });

    openTask("t4");
    fireEvent.change(screen.getByRole("textbox", { name: "Task name" }), { target: { value: "Slow save" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Task name" }));
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent("saving…");

    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t6");
    expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);

    release();
    await settle();
    expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);
  });

  it("shows when the task was last saved, and when it was created and updated", async () => {
    await renderDetail();
    openTask("t4");
    expect(screen.getByTestId("save-state")).toHaveTextContent("saved · 4 days ago");
    const properties = within(screen.getByRole("complementary", { name: "Properties" }));
    expect(properties.getByText("created 4 days ago")).toBeInTheDocument();
    expect(properties.getByText("updated 4 days ago")).toBeInTheDocument();
  });
});

const threeTasks = [makeTask({ id: "t1", title: "Alpha" }), makeTask({ id: "t2", title: "Beta" }), makeTask({ id: "t3", title: "Gamma" })];

const rowTitles = () =>
  within(screen.getByRole("list", { name: "Tasks" }))
    .getAllByRole("listitem")
    .map((row) => row.querySelector<HTMLElement>("[data-row-title]")!);

/** Renders the list beside the panel and opens the first row the way a user does. */
async function openFirstRow(tasks: Task[]) {
  renderWithServices(
    <WorkspaceProvider>
      <ListView />
      <TaskDetail />
    </WorkspaceProvider>,
    { tasks },
  );
  await screen.findByRole("textbox", { name: "Add a task" });
  const row = rowTitles()[0];
  row.focus();
  fireEvent.click(row);
  await settle();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
}

async function deleteOpenTask() {
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete task" }));
  await settle();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
}

describe("delete, from a list row", () => {
  it("hands focus to the row that took the deleted row's place", async () => {
    await openFirstRow(threeTasks);
    await deleteOpenTask();
    expect(rowTitles()).toHaveLength(2);
    expect(rowTitles()[0]).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it("falls back to the quick-add when the deleted row was the only one", async () => {
    await openFirstRow([threeTasks[0]]);
    await deleteOpenTask();
    await screen.findByText("No tasks match these filters.");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Add a task" })).toHaveFocus());
  });

  it("still hands focus on after the task was edited in the panel first", async () => {
    await openFirstRow(threeTasks);
    const properties = within(screen.getByRole("complementary", { name: "Properties" }));
    fireEvent.change(properties.getByRole("combobox", { name: "Status" }), { target: { value: "progress" } });
    await settle();
    expect(screen.getByTestId("detail-status")).toHaveTextContent("In Progress");

    await deleteOpenTask();
    expect(rowTitles()).toHaveLength(2);
    expect(rowTitles()[0]).toHaveFocus();
  });

  it("still hands focus on after the row left the list on Mark complete", async () => {
    await openFirstRow(threeTasks);
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();
    // The default filter hides done tasks, so the row is already gone before the delete.
    expect(rowTitles()).toHaveLength(2);

    await deleteOpenTask();
    expect(rowTitles()).toHaveLength(2);
    expect(rowTitles()[0]).toHaveFocus();
  });
});

describe("closing the panel, from a list row", () => {
  const CLOSERS: [string, () => void][] = [
    ["Escape", () => fireEvent.keyDown(window, { key: "Escape" })],
    ["the Close control", () => fireEvent.click(screen.getByRole("button", { name: "Close task" }))],
    ["the Back control", () => fireEvent.click(screen.getByRole("button", { name: "Back to tasks" }))],
    ["the backdrop", () => fireEvent.click(screen.getByTestId("detail-backdrop"))],
  ];

  it.each(CLOSERS)("hands focus on when %s closes a panel whose row has left the list", async (_name, close) => {
    await openFirstRow(threeTasks);
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();
    // Done tasks are hidden by the default filter, so there is no row left to go back to.
    expect(rowTitles()).toHaveLength(2);

    close();
    await settle();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(rowTitles()[0]).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it("falls back to the quick-add when completing the only row empties the list", async () => {
    await openFirstRow([threeTasks[0]]);
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();

    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    await screen.findByText("No tasks match these filters.");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Add a task" })).toHaveFocus());
  });

  it("leaves the focus on the row it was opened from when that row is still there", async () => {
    await openFirstRow(threeTasks);
    const opened = rowTitles()[0];

    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    expect(opened).toHaveFocus();
    expect(rowTitles()).toHaveLength(3);
  });

  it("finds the row again when it left the list and came back before the panel closed", async () => {
    await openFirstRow(threeTasks);
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await settle();
    expect(rowTitles()).toHaveLength(2);

    // Reopening mounts a new row node, so the button the panel remembered is gone for good.
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));
    await settle();
    expect(rowTitles()).toHaveLength(3);

    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    expect(document.body).not.toHaveFocus();
    expect(document.activeElement).toHaveAccessibleName("Alpha");
  });

  it("does not pull the focus into the list later, once the panel has come and gone", async () => {
    renderWithServices(<TasksApp />);
    await screen.findByText("13 tasks");
    const row = rowTitles()[0];
    row.focus();
    fireEvent.click(row);
    await settle();
    fireEvent.keyDown(window, { key: "Escape" });
    await settle();
    expect(row).toHaveFocus();

    act(() => row.blur());
    expect(document.body).toHaveFocus();

    // Searching the row away asks for no focus move: the panel is long gone.
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "no task says this" } });
    await settle();
    await screen.findByText("No tasks match these filters.");
    expect(document.body).toHaveFocus();
  });
});

describe("New task, through the shell", () => {
  it("creates an untitled task, opens it and puts the caret in the selected title", async () => {
    renderWithServices(<TasksApp />);
    await screen.findByText("13 tasks");
    fireEvent.click(screen.getByRole("button", { name: "New task" }));

    const dialog = await screen.findByRole("dialog", { name: "Untitled task" });
    const title = within(dialog).getByRole("textbox", { name: "Task name" }) as HTMLInputElement;
    await waitFor(() => expect(title).toHaveFocus());
    expect(title.selectionStart).toBe(0);
    expect(title.selectionEnd).toBe("Untitled task".length);
    expect(within(dialog).getByTestId("detail-project")).toHaveTextContent("Inbox");
  });

  it("keeps an untouched new task when the panel closes, as the design does", async () => {
    const { taskService } = renderWithServices(<TasksApp />);
    await screen.findByText("13 tasks");
    screen.getByRole("button", { name: "New task" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    const dialog = await screen.findByRole("dialog", { name: "Untitled task" });
    // The panel is only open once its effects have run: they take focus and listen for Escape.
    await waitFor(() => expect(within(dialog).getByRole("textbox", { name: "Task name" })).toHaveFocus());

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("14 tasks")).toBeInTheDocument();
    expect(taskService.calls.some((c) => c[0] === "remove")).toBe(false);
    expect(screen.getByRole("button", { name: "New task" })).toHaveFocus();
  });
});
