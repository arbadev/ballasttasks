import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { NOW, makeTask } from "@/test/tasks";
import { seedTasks } from "../services/seed";
import { TasksApp } from "./TasksApp";
import { renderWithServices } from "@/test/renderWithServices";

async function renderApp(options?: Parameters<typeof renderWithServices>[1]) {
  const view = renderWithServices(<TasksApp />, options);
  await screen.findByText("13 tasks", undefined, { timeout: 2000 }).catch(() => {});
  return view;
}

const sidebar = () => within(screen.getByRole("complementary", { name: "Workspace" }));
const titles = () => within(screen.getByRole("list", { name: "Tasks" })).getAllByRole("listitem").map((li) => li.textContent);
const navButton = (name: RegExp) => sidebar().getByRole("button", { name });

describe("sidebar", () => {
  it("shows the brand, live counts, projects, people and the current user", async () => {
    await renderApp();
    expect(sidebar().getByText("Ballast")).toBeInTheDocument();
    expect(navButton(/^All tasks/)).toHaveTextContent("13");
    expect(navButton(/^My tasks/)).toHaveTextContent("7");
    expect(navButton(/^Overdue/)).toHaveTextContent("1");
    expect(navButton(/^Ballast Tasks/)).toHaveTextContent("11");
    expect(navButton(/^Inbox/)).toHaveTextContent("2");

    const people = within(sidebar().getByRole("list", { name: "People" })).getAllByRole("listitem");
    expect(people.map((p) => p.textContent)).toEqual(["ABAndres Barradasowner", "LMLucía Marínbackend", "TRTomás Reyfrontend"]);

    const footer = within(sidebar().getByTestId("current-user"));
    expect(footer.getByText("Andres Barradas")).toBeInTheDocument();
    expect(footer.getByText("owner")).toBeInTheDocument();
  });

  it("links to the system status page from the footer", async () => {
    await renderApp();
    expect(sidebar().getByRole("link", { name: "System status" })).toHaveAttribute("href", "/status");
  });

  it("marks the active scope and switches the header, count and list with it", async () => {
    await renderApp();
    expect(navButton(/^All tasks/)).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(navButton(/^My tasks/));
    expect(navButton(/^My tasks/)).toHaveAttribute("aria-pressed", "true");
    expect(navButton(/^All tasks/)).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("My tasks");
    expect(screen.getByText("7 tasks")).toBeInTheDocument();
    expect(titles()).toHaveLength(7);
  });

  it("Overdue shows the late open task and resets the status filter to All open", async () => {
    await renderApp();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "done" } });
    fireEvent.click(navButton(/^Overdue/));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Overdue");
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("open");
    expect(screen.getByText("1 task")).toBeInTheDocument();
    expect(titles()).toEqual(["Write PRD.md: overview, user stories, scope"]);
  });

  it("toggles a project: the breadcrumb follows, and a second click goes back to all", async () => {
    await renderApp();
    expect(screen.getByTestId("crumb")).toHaveTextContent("Ballast");

    fireEvent.click(navButton(/^Inbox/));
    expect(navButton(/^Inbox/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("crumb")).toHaveTextContent("Inbox");
    expect(titles()).toEqual(["Confirm the panel slot with the recruiter", "Review Vectal task detail for assistant patterns"]);

    fireEvent.click(navButton(/^Inbox/));
    expect(screen.getByTestId("crumb")).toHaveTextContent("Ballast");
    expect(screen.getByText("13 tasks")).toBeInTheDocument();
  });

  it("keeps its counts while the main view is filtered", async () => {
    await renderApp();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "jwt" } });
    expect(screen.getByText("1 task")).toBeInTheDocument();
    expect(navButton(/^All tasks/)).toHaveTextContent("13");
  });
});

describe("header", () => {
  it("switches between the list and the board", async () => {
    await renderApp();
    expect(screen.getByRole("radio", { name: "List" })).toBeChecked();
    expect(screen.getByRole("list", { name: "Tasks" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Board" }));
    expect(screen.getByRole("region", { name: "Board" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Tasks" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "List" }));
    expect(screen.getByRole("list", { name: "Tasks" })).toBeInTheDocument();
  });

  it("New task creates an untitled task in the Inbox, counts it and opens it", async () => {
    const { taskService } = await renderApp();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));

    const detail = await screen.findByRole("dialog", { name: "Untitled task" });
    expect(taskService.calls).toContainEqual(["create", { title: "Untitled task", project: "inbox" }]);
    expect(screen.getByText("14 tasks")).toBeInTheDocument();
    expect(navButton(/^All tasks/)).toHaveTextContent("14");
    expect(navButton(/^Inbox/)).toHaveTextContent("3");
    expect(detail).toBeInTheDocument();
  });

  it("New task goes into the selected project", async () => {
    const { taskService } = await renderApp();
    fireEvent.click(navButton(/^Ballast Tasks/));
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    await screen.findByRole("dialog");
    expect(taskService.calls).toContainEqual(["create", { title: "Untitled task", project: "ballast" }]);
  });

  it("opens a task from the list and closes it with Escape or the close button", async () => {
    await renderApp();
    fireEvent.click(screen.getByRole("button", { name: "JWT authentication" }));
    expect(screen.getByRole("dialog", { name: "JWT authentication" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "JWT authentication" }));
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("filter toolbar", () => {
  it("offers the design's options", async () => {
    await renderApp();
    const options = (name: string) => within(screen.getByRole("combobox", { name })).getAllByRole("option").map((o) => o.textContent);
    expect(options("Status")).toEqual(["All open", "To Do", "In Progress", "Testing", "Done", "Everything"]);
    expect(options("Due")).toEqual(["Any date", "Overdue", "Today", "Next 7 days", "No date"]);
    expect(options("Priority")).toEqual(["Any", "P0", "P1", "P2", "P3"]);
    expect(options("Sort")).toEqual(["Urgency", "Importance", "Due date", "Recently updated"]);
  });

  it("filters by status, including Done and Everything", async () => {
    await renderApp();
    const status = screen.getByRole("combobox", { name: "Status" });
    fireEvent.change(status, { target: { value: "testing" } });
    expect(screen.getByText("2 tasks")).toBeInTheDocument();
    fireEvent.change(status, { target: { value: "done" } });
    expect(screen.getByText("3 tasks")).toBeInTheDocument();
    fireEvent.change(status, { target: { value: "all" } });
    expect(screen.getByText("16 tasks")).toBeInTheDocument();
  });

  it("filters by due date", async () => {
    await renderApp();
    const dueSelect = screen.getByRole("combobox", { name: "Due" });
    fireEvent.change(dueSelect, { target: { value: "today" } });
    expect(titles()).toEqual(["Confirm the panel slot with the recruiter"]);
    fireEvent.change(dueSelect, { target: { value: "none" } });
    expect(titles()).toEqual(["Rate limiting on the API", "Review Vectal task detail for assistant patterns"]);
    fireEvent.change(dueSelect, { target: { value: "week" } });
    expect(screen.getByText("6 tasks")).toBeInTheDocument();
  });

  it("filters by priority", async () => {
    await renderApp();
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    expect(titles()).toEqual(["JWT authentication", "Task CRUD endpoints with pagination and filters", "Next.js task list and board"]);
  });

  it("sorts", async () => {
    await renderApp();
    expect(titles()[0]).toBe("Write PRD.md: overview, user stories, scope");
    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), { target: { value: "importance" } });
    expect(titles().slice(0, 3)).toEqual(["Task CRUD endpoints with pagination and filters", "JWT authentication", "Next.js task list and board"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), { target: { value: "updated" } });
    expect(titles()[0]).toBe("Unit tests at 80% coverage or more");
  });

  it("searches titles and descriptions, and says so when nothing matches", async () => {
    await renderApp();
    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    fireEvent.change(search, { target: { value: "token bucket" } });
    expect(titles()).toEqual(["Rate limiting on the API"]);

    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText("0 tasks")).toBeInTheDocument();
    expect(screen.getByText("No tasks match these filters.")).toBeInTheDocument();
  });
});

describe("Attention strip", () => {
  const strip = () => within(screen.getByRole("region", { name: "Attention" }));

  it("shows the design's four signals with counts", async () => {
    await renderApp();
    expect(strip().getAllByRole("button").map((b) => b.textContent)).toEqual(["1overdue", "2P0 at risk", "4due soon", "2need an owner"]);
  });

  it("applies a signal as a filter, shows Show all, and clears from either control", async () => {
    await renderApp();
    const chip = strip().getByRole("button", { name: /need an owner/ });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(strip().queryByRole("button", { name: "Show all" })).not.toBeInTheDocument();

    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(titles()).toEqual(["JWT authentication", "Rate limiting on the API"]);

    fireEvent.click(strip().getByRole("button", { name: "Show all" }));
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("13 tasks")).toBeInTheDocument();

    fireEvent.click(chip);
    fireEvent.click(chip);
    expect(screen.getByText("13 tasks")).toBeInTheDocument();
  });

  it("switching chips replaces the signal", async () => {
    await renderApp();
    fireEvent.click(strip().getByRole("button", { name: /overdue/ }));
    fireEvent.click(strip().getByRole("button", { name: /P0 at risk/ }));
    expect(strip().getByRole("button", { name: /overdue/ })).toHaveAttribute("aria-pressed", "false");
    expect(titles()).toEqual(["JWT authentication", "Task CRUD endpoints with pagination and filters"]);
  });

  it("follows the selected project", async () => {
    await renderApp();
    fireEvent.click(navButton(/^Inbox/));
    expect(strip().getAllByRole("button").map((b) => b.textContent)).toEqual(["1due soon"]);
  });

  it("says all clear when nothing needs attention", async () => {
    await renderApp({ tasks: [makeTask()] });
    await screen.findByText("1 task");
    expect(strip().getByText("All clear — nothing overdue, at risk or unowned")).toBeInTheDocument();
    expect(strip().queryAllByRole("button")).toEqual([]);
  });
});

describe("loading and failure", () => {
  it("says it is loading, then shows the tasks", async () => {
    renderWithServices(<TasksApp />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading tasks");
    expect(await screen.findByText("13 tasks")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reports a failure and recovers on Retry", async () => {
    const taskService = new FakeTaskService(seedTasks(NOW));
    taskService.list = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(seedTasks(NOW));
    renderWithServices(<TasksApp />, { taskService });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the tasks");
    expect(alert).toHaveTextContent("offline");

    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("13 tasks")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("narrow screens", () => {
  it("opens the sidebar as a drawer and closes it with Escape, the backdrop or a choice", async () => {
    await renderApp();
    const aside = screen.getByRole("complementary", { name: "Workspace" });
    const open = screen.getByRole("button", { name: "Open navigation" });
    expect(aside).toHaveAttribute("data-open", "false");
    expect(open).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(open);
    expect(aside).toHaveAttribute("data-open", "true");
    expect(open).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(aside).toHaveAttribute("data-open", "false");

    fireEvent.click(open);
    fireEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(aside).toHaveAttribute("data-open", "false");

    fireEvent.click(open);
    fireEvent.click(navButton(/^My tasks/));
    await waitFor(() => expect(aside).toHaveAttribute("data-open", "false"));
  });
});
