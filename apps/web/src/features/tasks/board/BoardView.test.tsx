import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, onTestFinished, vi } from "vitest";
import { FakeTaskService } from "@/test/fakeServices";
import { renderWithServices } from "@/test/renderWithServices";
import { NOW, due, makeTask } from "@/test/tasks";
import type { Task, TaskStatus } from "../model/types";
import { seedTasks } from "../services/seed";
import { TasksApp } from "../shell/TasksApp";

const PRD = "Write PRD.md: overview, user stories, scope";
const JWT = "JWT authentication";
const COMPOSE = "Docker compose: five services from .env.example";

async function renderBoard(options?: Parameters<typeof renderWithServices>[1]) {
  const view = renderWithServices(<TasksApp />, options);
  fireEvent.click(screen.getByText("Board", { exact: true }));
  await screen.findByRole("region", { name: "To Do" });
  return view;
}

const column = (name: string) => screen.getByRole("region", { name });
const cardsIn = (name: string) => within(column(name)).queryAllByRole("article");
const titlesIn = (name: string) => cardsIn(name).map((c) => within(c).getAllByRole("button")[0].textContent);
const card = (title: string) => screen.getByRole("article", { name: title });
const openButton = (title: string) => within(card(title)).getByRole("button", { name: title });
const moveCalls = (service: FakeTaskService) => service.calls.filter((c) => c[0] === "move");

function dataTransfer() {
  const data = new Map<string, string>();
  return { setData: (k: string, v: string) => data.set(k, v), getData: (k: string) => data.get(k) ?? "", effectAllowed: "none", dropEffect: "none" };
}

function drag(title: string, to: string) {
  const transfer = dataTransfer();
  fireEvent.dragStart(card(title), { dataTransfer: transfer });
  fireEvent.dragOver(column(to), { dataTransfer: transfer });
  return {
    drop: () => {
      fireEvent.drop(column(to), { dataTransfer: transfer });
      fireEvent.dragEnd(card(title), { dataTransfer: transfer });
    },
  };
}

/** A service whose next move can be made to fail, or held until the test releases it. */
class ControlledTaskService extends FakeTaskService {
  failNextMove = false;
  hold: Promise<void> | null = null;
  override async move(id: string, status: TaskStatus) {
    if (this.hold) await this.hold;
    if (this.failNextMove) {
      this.failNextMove = false;
      this.calls.push(["move", id, status]);
      throw new Error("The server said no.");
    }
    return super.move(id, status);
  }
}

describe("columns", () => {
  it("shows the four statuses in workflow order with live counts", async () => {
    await renderBoard();
    const names = within(screen.getByRole("region", { name: "Board" })).getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["To Do", "In Progress", "Testing", "Done"]);
    expect(within(column("To Do")).getByTestId("column-count")).toHaveTextContent("8");
    expect(within(column("In Progress")).getByTestId("column-count")).toHaveTextContent("3");
    expect(within(column("Testing")).getByTestId("column-count")).toHaveTextContent("2");
    expect(within(column("Done")).getByTestId("column-count")).toHaveTextContent("3");
    expect(cardsIn("To Do")).toHaveLength(8);
  });

  it("shows every status even though the Status filter says All open, and the header keeps the list's count", async () => {
    await renderBoard();
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("open");
    expect(cardsIn("Done")).toHaveLength(3);
    expect(screen.getByText("13 tasks")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "done" } });
    expect(cardsIn("To Do")).toHaveLength(8);
    expect(screen.getByText("3 tasks")).toBeInTheDocument();
  });

  it("honours scope, project, priority, due and search", async () => {
    await renderBoard();
    const sidebar = within(screen.getByRole("complementary", { name: "Workspace" }));

    fireEvent.click(sidebar.getByRole("button", { name: /^Inbox/ }));
    expect(titlesIn("To Do")).toEqual(["Confirm the panel slot with the recruiter", "Review Vectal task detail for assistant patterns"]);
    expect(cardsIn("In Progress")).toHaveLength(0);
    fireEvent.click(sidebar.getByRole("button", { name: /^Inbox/ }));

    fireEvent.click(sidebar.getByRole("button", { name: /^Overdue/ }));
    expect(titlesIn("To Do")).toEqual([PRD]);
    fireEvent.click(sidebar.getByRole("button", { name: /^All tasks/ }));

    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    expect(titlesIn("To Do")).toEqual([JWT]);
    expect(cardsIn("In Progress")).toHaveLength(2);
    expect(cardsIn("Done")).toHaveLength(1);
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "any" } });

    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "today" } });
    expect(titlesIn("To Do")).toEqual(["Confirm the panel slot with the recruiter"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "any" } });

    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "docker" } });
    expect(titlesIn("Testing")).toEqual([COMPOSE]);
    expect(cardsIn("To Do")).toHaveLength(0);
  });

  it("orders each column by the chosen sort", async () => {
    await renderBoard();
    expect(titlesIn("To Do")[0]).toBe(PRD);
    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), { target: { value: "importance" } });
    const importanceOf = new Map(seedTasks(NOW).map((t) => [t.title, t.importance]));
    const importances = titlesIn("To Do").map((title) => importanceOf.get(title ?? "") ?? -1);
    expect(importances).toHaveLength(8);
    expect(importances).toEqual([...importances].sort((a, b) => b - a));
  });

  it("says Drop tasks here in a column the filters leave empty", async () => {
    await renderBoard();
    expect(screen.queryByText("Drop tasks here")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "docker" } });
    expect(within(column("To Do")).getByText("Drop tasks here")).toBeInTheDocument();
    expect(within(column("Testing")).queryByText("Drop tasks here")).not.toBeInTheDocument();
    expect(within(column("To Do")).getByTestId("column-count")).toHaveTextContent("0");
  });
});

describe("card", () => {
  it("shows project, priority, title, due label, step progress, attachments and the assignee", async () => {
    await renderBoard();
    const crud = within(card("Task CRUD endpoints with pagination and filters"));
    expect(crud.getByText("Ballast Tasks")).toBeInTheDocument();
    expect(crud.getByText("P0")).toBeInTheDocument();
    expect(crud.getByText("Due Mon · 3d")).toBeInTheDocument();
    expect(crud.getByTitle("3 of 6 steps done")).toHaveTextContent("3/6");
    expect(crud.getByTitle("2 attachments")).toHaveTextContent("2");
    expect(crud.getByRole("img", { name: "Andres Barradas" })).toHaveTextContent("AB");
  });

  it("marks a task that needs an owner", async () => {
    await renderBoard();
    const jwt = within(card(JWT));
    expect(jwt.getByText("needs owner")).toBeInTheDocument();
    expect(jwt.getByRole("img", { name: "Needs an owner" })).toHaveTextContent("?");
  });

  it("strikes a done task and shows its plain date", async () => {
    await renderBoard();
    const done = card("Monorepo foundation and health endpoints");
    expect(within(done).getByText("Sep 12")).toBeInTheDocument();
    expect(within(done).getByRole("button", { name: "Monorepo foundation and health endpoints" })).toHaveClass("line-through");
  });

  it("enters with a stagger down the column", async () => {
    await renderBoard();
    const [first, second] = cardsIn("To Do");
    expect(first).toHaveClass("animate-bt-in");
    expect(first.style.animationDelay).toBe("0ms");
    expect(second.style.animationDelay).toBe("24ms");
  });

  it("opens the task when clicked or activated from the keyboard, and marks it as the current one", async () => {
    await renderBoard();
    fireEvent.click(card(PRD));
    expect(screen.getByRole("dialog", { name: PRD })).toBeInTheDocument();
    expect(card(PRD)).toHaveAttribute("aria-current", "true");
    expect(card(JWT)).not.toHaveAttribute("aria-current");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(openButton(JWT));
    expect(screen.getByRole("dialog", { name: JWT })).toBeInTheDocument();
  });
});

describe("drag and drop", () => {
  it("moves a card through the service, which writes the activity entry", async () => {
    const { taskService } = await renderBoard();
    drag(PRD, "Testing").drop();

    expect(moveCalls(taskService)).toEqual([["move", "t5", "testing"]]);
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(titlesIn("To Do")).not.toContain(PRD);
    expect(within(column("To Do")).getByTestId("column-count")).toHaveTextContent("7");
    expect(within(column("Testing")).getByTestId("column-count")).toHaveTextContent("3");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("dims the dragged card and highlights the column under it until the drag ends", async () => {
    await renderBoard();
    const dragging = drag(PRD, "Testing");
    expect(card(PRD)).toHaveAttribute("data-dragging", "true");
    expect(column("Testing")).toHaveAttribute("data-drop-target", "true");
    expect(column("To Do")).not.toHaveAttribute("data-drop-target");

    fireEvent.dragOver(column("Done"), { dataTransfer: dataTransfer() });
    expect(column("Done")).toHaveAttribute("data-drop-target", "true");
    expect(column("Testing")).not.toHaveAttribute("data-drop-target");

    dragging.drop();
    await waitFor(() => expect(card(PRD)).not.toHaveAttribute("data-dragging"));
    expect(screen.queryAllByRole("region").some((r) => r.hasAttribute("data-drop-target"))).toBe(false);
  });

  it("moves the card at once, before the service answers", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.hold = new Promise<void>((resolve) => (release = resolve));
    await renderBoard({ taskService: service });

    drag(PRD, "Testing").drop();
    expect(titlesIn("Testing")).toContain(PRD);

    await act(async () => release());
    await waitFor(() => expect(moveCalls(service)).toHaveLength(1));
    expect(titlesIn("Testing")).toContain(PRD);
  });

  it("does nothing when a card is dropped on its own column", async () => {
    const { taskService } = await renderBoard();
    drag(PRD, "To Do").drop();
    expect(moveCalls(taskService)).toEqual([]);
    expect(titlesIn("To Do")).toContain(PRD);
    expect(screen.getByTestId("board-live")).toBeEmptyDOMElement();
  });

  it("rolls the card back and says so when the move fails, and Retry moves it", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    drag(PRD, "Testing").drop();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Could not move "${PRD}" to Testing. It is back in To Do.`);
    expect(titlesIn("To Do")).toContain(PRD);
    expect(titlesIn("Testing")).not.toContain(PRD);

    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(moveCalls(service)).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lets the error be dismissed", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    drag(PRD, "Testing").drop();
    fireEvent.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("moving without a drag", () => {
  it("moves the focused card to the next or previous status with Shift+Arrow, announces it and keeps focus on the card", async () => {
    const { taskService } = await renderBoard();
    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });

    expect(moveCalls(taskService)).toEqual([["move", "t5", "progress"]]);
    await waitFor(() => expect(titlesIn("In Progress")).toContain(PRD));
    expect(screen.getByTestId("board-live")).toHaveTextContent(`Moved "${PRD}" to In Progress.`);
    expect(screen.getByTestId("board-live")).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());

    fireEvent.keyDown(openButton(PRD), { key: "ArrowLeft", shiftKey: true });
    await waitFor(() => expect(titlesIn("To Do")).toContain(PRD));
    expect(screen.getByTestId("board-live")).toHaveTextContent(`Moved "${PRD}" to To Do.`);
  });

  it("ignores plain arrows and the ends of the workflow", async () => {
    const { taskService } = await renderBoard();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight" });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(openButton("ADR 0002: ports and adapters"), { key: "ArrowRight", shiftKey: true });
    expect(moveCalls(taskService)).toEqual([]);
  });

  it("tells assistive tech about the shortcut", async () => {
    await renderBoard();
    expect(openButton(PRD)).toHaveAttribute("aria-keyshortcuts", "Shift+ArrowLeft Shift+ArrowRight");
    expect(openButton(PRD)).toHaveAccessibleDescription(/Shift and the left or right arrow/);
  });

  it("offers the same move as buttons, which do not open the task", async () => {
    const { taskService } = await renderBoard();
    const compose = within(card(COMPOSE));
    expect(compose.getByRole("button", { name: `Move "${COMPOSE}" to In Progress` })).toBeInTheDocument();
    fireEvent.click(compose.getByRole("button", { name: `Move "${COMPOSE}" to Done` }));

    expect(moveCalls(taskService)).toEqual([["move", "t11", "done"]]);
    await waitFor(() => expect(titlesIn("Done")).toContain(COMPOSE));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("board-live")).toHaveTextContent(`Moved "${COMPOSE}" to Done.`);
  });

  it("keeps the move buttons on show while keyboard focus stays inside the card, and hides them when it leaves", async () => {
    // jsdom does not track input modality, so every focus here counts as the keyboard's.
    const matches = Element.prototype.matches;
    const spy = vi.spyOn(Element.prototype, "matches").mockImplementation(function (this: Element, selector: string) {
      return selector === ":focus-visible" ? this === document.activeElement : matches.call(this, selector);
    });
    onTestFinished(() => spy.mockRestore());

    await renderBoard();
    const controls = () => card(COMPOSE).querySelector("[data-move-controls]");
    expect(controls()).toBeNull();

    act(() => openButton(COMPOSE).focus());
    expect(controls()).not.toBeNull();

    // Focus travelling from one of the card's buttons to another must not hide the row.
    act(() => within(card(COMPOSE)).getByRole("button", { name: `Move "${COMPOSE}" to Done` }).focus());
    expect(controls()).not.toBeNull();

    act(() => openButton(PRD).focus());
    expect(controls()).toBeNull();
  });

  it("has no backward button in the first column and no forward button in the last", async () => {
    await renderBoard();
    expect(within(card(PRD)).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([PRD, `Move "${PRD}" to In Progress`]);
    const done = "ADR 0002: ports and adapters";
    expect(within(card(done)).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([done, `Move "${done}" to Testing`]);
  });

  it("leaves a failed move to the alert, with nothing in the polite region", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await screen.findByRole("alert");
    expect(screen.getByTestId("board-live")).toBeEmptyDOMElement();
  });
});

describe("add a task", () => {
  it("creates an untitled task in that column and opens it", async () => {
    const { taskService } = await renderBoard();
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await screen.findByRole("dialog", { name: "Untitled task" });
    expect(taskService.calls).toContainEqual(["create", { title: "Untitled task", status: "testing", project: "inbox" }]);
    expect(titlesIn("Testing")).toContain("Untitled task");
  });
});

describe("load states", () => {
  class NeverLoads extends FakeTaskService {
    override list(): Promise<Task[]> {
      return new Promise(() => {});
    }
  }

  class FailsOnce extends FakeTaskService {
    private failed = false;
    override async list() {
      if (!this.failed) {
        this.failed = true;
        throw new Error("The API is down.");
      }
      return super.list();
    }
  }

  it("shows a skeleton shaped like the board while the tasks load", () => {
    renderWithServices(<TasksApp />, { taskService: new NeverLoads() });
    fireEvent.click(screen.getByText("Board", { exact: true }));
    expect(screen.getByRole("status", { name: "Loading the board" })).toBeInTheDocument();
    expect(screen.getAllByTestId("skeleton-column")).toHaveLength(4);
    expect(screen.queryByText("Loading tasks…")).not.toBeInTheDocument();
  });

  it("shows the load error with a retry that brings the board back", async () => {
    renderWithServices(<TasksApp />, { taskService: new FailsOnce([makeTask({ id: "x1", title: "Only task", due: due(9) })]) });
    fireEvent.click(screen.getByText("Board", { exact: true }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the board.");
    expect(alert).toHaveTextContent("The API is down.");
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("article", { name: "Only task" })).toBeInTheDocument();
  });
});
