import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TasksApp } from "../shell/TasksApp";
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
