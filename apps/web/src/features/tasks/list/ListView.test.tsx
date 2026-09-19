import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { renderWithServices } from "@/test/renderWithServices";
import { due, makeTask } from "@/test/tasks";
import type { Task } from "../model/types";
import type { NewTask } from "../services/types";
import { TasksApp } from "../shell/TasksApp";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { ListView } from "./ListView";

/** Shows what the list did to the workspace, without depending on the detail panel. */
function Probe() {
  const { state, actions } = useWorkspace();
  return (
    <div>
      <output data-testid="selected">{state.selectedId ?? "none"}</output>
      <button type="button" onClick={() => actions.setStatusFilter("all")}>
        probe: all statuses
      </button>
      <button type="button" onClick={() => actions.toggleProject("ballast")}>
        probe: ballast project
      </button>
    </div>
  );
}

async function renderList(tasks: Task[], taskService?: FakeTaskService) {
  const view = renderWithServices(
    <WorkspaceProvider>
      <ListView />
      <Probe />
    </WorkspaceProvider>,
    { tasks, taskService },
  );
  await screen.findByRole("textbox", { name: "Add a task" });
  return view;
}

const rows = () => within(screen.getByRole("list", { name: "Tasks" })).getAllByRole("listitem");
const row = (title: string) => {
  const found = rows().find((li) => within(li).queryByRole("button", { name: title }));
  if (!found) throw new Error(`no row titled ${title}`);
  return found;
};
const titleButton = (title: string) => screen.getByRole("button", { name: title });
const toggle = (title: string) => screen.getByRole("checkbox", { name: `Complete: ${title}` });
const quickAdd = () => screen.getByRole("textbox", { name: "Add a task" });
const selected = () => screen.getByTestId("selected").textContent;

const steps = [
  { id: "s1", text: "one", done: true },
  { id: "s2", text: "two", done: false },
  { id: "s3", text: "three", done: false },
];
const attachments = [
  { kind: "pdf" as const, name: "brief.pdf", meta: "PDF · 1 MB" },
  { kind: "link" as const, name: "example.com", meta: "link", url: "https://example.com/" },
];

describe("task rows", () => {
  it("shows the title, project, due label, steps, attachments, importance, priority and assignee", async () => {
    await renderList([makeTask({ id: "a", title: "Ship the list", project: "ballast", due: due(-2), prio: 1, importance: 75, steps, attachments, assignee: "lm" })]);
    const r = within(row("Ship the list"));
    expect(r.getByText("Ballast Tasks")).toBeInTheDocument();
    expect(r.getByText("Overdue · 2d")).toBeInTheDocument();
    expect(r.getByText("1/3")).toBeInTheDocument();
    expect(r.getByText("2")).toBeInTheDocument();
    expect(r.getByText("75")).toBeInTheDocument();
    expect(r.getByText("P1")).toBeInTheDocument();
    expect(r.getByRole("img", { name: "Lucía Marín" })).toHaveTextContent("LM");
  });

  it("omits the steps and attachment marks when the task has none", async () => {
    await renderList([makeTask({ id: "a", title: "Bare" })]);
    const r = within(row("Bare"));
    expect(r.queryByText(/^\d+\/\d+$/)).not.toBeInTheDocument();
    expect(r.queryByTestId("attachment-count")).not.toBeInTheDocument();
  });

  it("marks an open task without an assignee as needing an owner", async () => {
    await renderList([makeTask({ id: "a", title: "Orphan", assignee: null })]);
    const r = within(row("Orphan"));
    expect(r.getByText("needs owner")).toBeInTheDocument();
    expect(r.getByRole("img", { name: "Needs an owner" })).toHaveTextContent("?");
  });

  it("colours the due label by urgency: overdue, today, soon, later", async () => {
    await renderList([
      makeTask({ id: "a", title: "Late", due: due(-1) }),
      makeTask({ id: "b", title: "Now", due: due(0) }),
      makeTask({ id: "c", title: "Near", due: due(2) }),
      makeTask({ id: "d", title: "Far", due: due(20) }),
    ]);
    const tone = (title: string) => within(row(title)).getByTestId("due").getAttribute("data-tone");
    expect([tone("Late"), tone("Now"), tone("Near"), tone("Far")]).toEqual(["danger", "warn", "warn", "later"]);
    expect(within(row("Late")).getByTestId("due")).toHaveClass("bg-danger-soft", "text-danger");
    expect(within(row("Now")).getByTestId("due")).toHaveClass("bg-warn-soft", "text-warn");
    expect(within(row("Far")).getByTestId("due")).toHaveClass("text-fg-3");
  });

  it("gives an urgent row its rail, and pulses it only for a P0 at risk", async () => {
    await renderList([makeTask({ id: "a", title: "Late", due: due(-1), prio: 2 }), makeTask({ id: "b", title: "Risky", due: due(1), prio: 0 }), makeTask({ id: "c", title: "Calm" })]);
    expect(within(row("Late")).getByTestId("rail")).toHaveClass("bg-danger");
    expect(within(row("Late")).getByTestId("rail")).not.toHaveClass("animate-bt-blink");
    expect(within(row("Risky")).getByTestId("rail")).toHaveClass("bg-danger", "animate-bt-blink");
    expect(within(row("Calm")).getByTestId("rail")).toHaveClass("bg-transparent");
  });

  it("shows a done task checked, struck through and quiet", async () => {
    await renderList([makeTask({ id: "a", title: "Finished", status: "done", due: "2026-09-10" })]);
    fireEvent.click(screen.getByRole("button", { name: "probe: all statuses" }));
    expect(toggle("Finished")).toBeChecked();
    expect(titleButton("Finished")).toHaveClass("line-through", "text-fg-3");
    expect(within(row("Finished")).getByText("Sep 10")).toBeInTheDocument();
    expect(within(toggle("Finished")).getByTestId("check")).toHaveClass("animate-bt-pop");
  });

  it("enters with the design's stagger", async () => {
    await renderList([makeTask({ id: "a", title: "First" }), makeTask({ id: "b", title: "Second" })]);
    const [first, second] = rows();
    expect(first).toHaveClass("animate-bt-in");
    expect(first.style.animationDelay).toBe("0ms");
    expect(second.style.animationDelay).toBe("24ms");
  });
});

describe("ordering and counts", () => {
  it("lists the design's 13 open tasks in urgency order and follows the filters", async () => {
    renderWithServices(<TasksApp />);
    await screen.findByText("13 tasks");
    expect(rows()).toHaveLength(13);
    expect(within(rows()[0]).getByRole("button", { name: "Write PRD.md: overview, user stories, scope" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "done" } });
    expect(screen.getByText("3 tasks")).toBeInTheDocument();
    expect(rows()).toHaveLength(3);
    rows().forEach((li) => expect(within(li).getByRole("checkbox")).toBeChecked());
  });

  it("keeps the header count right after a quick-add and after completing a task", async () => {
    renderWithServices(<TasksApp />);
    await screen.findByText("13 tasks");
    fireEvent.change(quickAdd(), { target: { value: "One more" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(await screen.findByText("14 tasks")).toBeInTheDocument();
    expect(rows()).toHaveLength(14);
    expect(titleButton("One more")).toBeInTheDocument();

    fireEvent.click(toggle("One more"));
    expect(await screen.findByText("13 tasks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "One more" })).not.toBeInTheDocument();
  });
});

describe("selecting a row", () => {
  it("opens the task on click and marks the row selected", async () => {
    await renderList([makeTask({ id: "a", title: "Alpha" }), makeTask({ id: "b", title: "Beta" })]);
    expect(selected()).toBe("none");
    fireEvent.click(within(row("Beta")).getByText("P2"));
    expect(selected()).toBe("b");
    expect(row("Beta")).toHaveAttribute("aria-current", "true");
    expect(row("Beta")).toHaveClass("bg-acc-soft");
    expect(row("Alpha")).not.toHaveAttribute("aria-current");
  });

  it("keeps the task open when the selected row is clicked again, as the design does", async () => {
    await renderList([makeTask({ id: "a", title: "Alpha" })]);
    fireEvent.click(titleButton("Alpha"));
    fireEvent.click(titleButton("Alpha"));
    expect(selected()).toBe("a");
  });

  it("completes through the service without opening the row", async () => {
    const { taskService } = await renderList([makeTask({ id: "a", title: "Alpha" })]);
    fireEvent.click(screen.getByRole("button", { name: "probe: all statuses" }));
    fireEvent.click(toggle("Alpha"));
    await waitFor(() => expect(toggle("Alpha")).toBeChecked());
    expect(taskService.calls).toContainEqual(["toggleDone", "a"]);
    expect(selected()).toBe("none");

    fireEvent.click(toggle("Alpha"));
    await waitFor(() => expect(toggle("Alpha")).not.toBeChecked());
  });
});

describe("keyboard", () => {
  const three = [makeTask({ id: "a", title: "Alpha", importance: 90 }), makeTask({ id: "b", title: "Beta", importance: 60 }), makeTask({ id: "c", title: "Gamma", importance: 30 })];

  it("Enter opens the focused row", async () => {
    await renderList(three);
    titleButton("Beta").focus();
    fireEvent.keyDown(titleButton("Beta"), { key: "Enter" });
    expect(selected()).toBe("b");
  });

  it("Space completes the focused row without opening it", async () => {
    const { taskService } = await renderList(three);
    titleButton("Beta").focus();
    fireEvent.keyDown(titleButton("Beta"), { key: " " });
    await waitFor(() => expect(taskService.calls).toContainEqual(["toggleDone", "b"]));
    expect(selected()).toBe("none");
  });

  it("the arrow keys, Home and End move between rows and stop at the last one", async () => {
    await renderList(three);
    titleButton("Alpha").focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(titleButton("Beta")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(titleButton("Gamma")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(titleButton("Gamma")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(titleButton("Beta")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(titleButton("Alpha")).toHaveFocus();
  });

  it("ArrowDown from the quick-add reaches the first row, and ArrowUp from it goes back", async () => {
    await renderList(three);
    quickAdd().focus();
    fireEvent.keyDown(quickAdd(), { key: "ArrowDown" });
    expect(titleButton("Alpha")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(quickAdd()).toHaveFocus();
  });

  it("moves focus to the next row when the completed row leaves the list", async () => {
    await renderList(three);
    titleButton("Beta").focus();
    fireEvent.keyDown(titleButton("Beta"), { key: " " });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Beta" })).not.toBeInTheDocument());
    expect(titleButton("Gamma")).toHaveFocus();
  });

  it("falls back to the quick-add when the last row is completed", async () => {
    await renderList([three[0]]);
    titleButton("Alpha").focus();
    fireEvent.keyDown(titleButton("Alpha"), { key: " " });
    await screen.findByText("No tasks match these filters.");
    expect(quickAdd()).toHaveFocus();
  });

  it("does not pull the focus back later when the completed row stayed in the list", async () => {
    await renderList(three);
    fireEvent.click(screen.getByRole("button", { name: "probe: all statuses" }));
    titleButton("Beta").focus();
    fireEvent.keyDown(titleButton("Beta"), { key: " " });
    await waitFor(() => expect(toggle("Beta")).toBeChecked());
    expect(titleButton("Beta")).toHaveFocus();

    act(() => titleButton("Beta").blur());
    fireEvent.change(quickAdd(), { target: { value: "Later on" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    await screen.findByRole("button", { name: "Later on" });
    expect(document.body).toHaveFocus();
  });
});

describe("quick-add", () => {
  it("creates in the Inbox on Enter, clears the field, keeps focus and does not open the task", async () => {
    const { taskService } = await renderList([]);
    quickAdd().focus();
    fireEvent.change(quickAdd(), { target: { value: "  Book the room  " } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Book the room" })).toBeInTheDocument();
    expect(taskService.calls).toContainEqual(["create", { title: "Book the room", project: "inbox" }]);
    expect(quickAdd()).toHaveValue("");
    expect(quickAdd()).toHaveFocus();
    expect(selected()).toBe("none");
  });

  it("creates in the selected project", async () => {
    const { taskService } = await renderList([]);
    fireEvent.click(screen.getByRole("button", { name: "probe: ballast project" }));
    fireEvent.change(quickAdd(), { target: { value: "In the project" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    await screen.findByRole("button", { name: "In the project" });
    expect(taskService.calls).toContainEqual(["create", { title: "In the project", project: "ballast" }]);
  });

  it("does nothing for an empty or blank title", async () => {
    const { taskService } = await renderList([]);
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    fireEvent.change(quickAdd(), { target: { value: "   " } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    await act(async () => {});
    expect(taskService.calls.filter(([name]) => name === "create")).toEqual([]);
  });

  it("ignores a second Enter while the same title is still saving, but not a different title", async () => {
    class Slow extends FakeTaskService {
      private held: (() => void)[] = [];
      override create(input: NewTask) {
        const saved = super.create(input);
        return new Promise<Task>((resolve) => this.held.push(() => resolve(saved)));
      }
      release() {
        this.held.splice(0).forEach((go) => go());
      }
    }
    const service = new Slow();
    await renderList([], service);
    const creates = () => service.calls.filter(([name]) => name === "create");

    fireEvent.change(quickAdd(), { target: { value: "Only once" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(creates()).toHaveLength(1);

    fireEvent.change(quickAdd(), { target: { value: "The next one" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(creates()).toHaveLength(2);

    await act(async () => service.release());
    expect(await screen.findByRole("button", { name: "The next one" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Only once" })).toHaveLength(1);
    expect(quickAdd()).toHaveValue("");

    fireEvent.change(quickAdd(), { target: { value: "Only once" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(creates()).toHaveLength(3);
  });

  it("names its field, so the browser raises no form-field issue", async () => {
    await renderList([]);
    expect(quickAdd()).toHaveAttribute("name", "title");
  });

  it("Escape clears the field", async () => {
    await renderList([]);
    fireEvent.change(quickAdd(), { target: { value: "Never mind" } });
    fireEvent.keyDown(quickAdd(), { key: "Escape" });
    expect(quickAdd()).toHaveValue("");
  });

  it("ignores the Enter that confirms an input-method composition", async () => {
    const { taskService } = await renderList([]);
    fireEvent.change(quickAdd(), { target: { value: "にほん" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter", isComposing: true });
    await act(async () => {});
    expect(taskService.calls.filter(([name]) => name === "create")).toEqual([]);
    expect(quickAdd()).toHaveValue("にほん");
  });
});

describe("states", () => {
  it("says so when no task matches", async () => {
    await renderList([]);
    expect(screen.getByText("No tasks match these filters.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Tasks" })).not.toBeInTheDocument();
  });

  it("shows a skeleton while the tasks load", async () => {
    class Slow extends FakeTaskService {
      release: () => void = () => {};
      override list() {
        return new Promise<Task[]>((resolve) => {
          this.release = () => resolve([makeTask({ id: "a", title: "Arrived" })]);
        });
      }
    }
    const service = new Slow();
    renderWithServices(
      <WorkspaceProvider>
        <ListView />
      </WorkspaceProvider>,
      { taskService: service },
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading tasks");
    expect(screen.getAllByTestId("skeleton-row").length).toBeGreaterThanOrEqual(5);
    expect(screen.queryByText("No tasks match these filters.")).not.toBeInTheDocument();

    await act(async () => service.release());
    expect(await screen.findByRole("button", { name: "Arrived" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reports a load failure and recovers on Retry", async () => {
    class Flaky extends FakeTaskService {
      failures = 1;
      override async list() {
        if (this.failures-- > 0) throw new Error("The network is down.");
        return super.list();
      }
    }
    renderWithServices(
      <WorkspaceProvider>
        <ListView />
      </WorkspaceProvider>,
      { taskService: new Flaky([makeTask({ id: "a", title: "Recovered" })]) },
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the tasks.");
    expect(alert).toHaveTextContent("The network is down.");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Recovered" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says so when completing fails, and leaves the row as it was", async () => {
    class Broken extends FakeTaskService {
      override async toggleDone(): Promise<Task> {
        throw new Error("offline");
      }
    }
    await renderList([], new Broken([makeTask({ id: "a", title: "Alpha" })]));
    fireEvent.click(toggle("Alpha"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not update “Alpha”. Try again.");
    expect(toggle("Alpha")).not.toBeChecked();
  });

  it("keeps the typed title when creating fails, and clears the message on the next edit", async () => {
    class Broken extends FakeTaskService {
      override async create(): Promise<Task> {
        throw new Error("offline");
      }
    }
    await renderList([], new Broken());
    fireEvent.change(quickAdd(), { target: { value: "Keep me" } });
    fireEvent.keyDown(quickAdd(), { key: "Enter" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add the task. Press Enter to try again.");
    expect(quickAdd()).toHaveValue("Keep me");
    fireEvent.change(quickAdd(), { target: { value: "Keep me!" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
