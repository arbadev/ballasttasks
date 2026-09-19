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

/** A service whose next move or create can be made to fail, or held until the test releases it. */
class ControlledTaskService extends FakeTaskService {
  failNextMove = false;
  failNextCreate = false;
  /** Every move to this status fails, whatever order the moves are answered in. */
  refuses: TaskStatus | null = null;
  hold: Promise<void> | null = null;
  holdCreate: Promise<void> | null = null;
  /** The first move to this status waits for its promise; later ones are answered at once. */
  readonly holds = new Map<TaskStatus, Promise<void>>();
  override async move(id: string, status: TaskStatus) {
    const held = this.holds.get(status);
    if (held) {
      this.holds.delete(status);
      await held;
    }
    if (this.hold) await this.hold;
    if (this.failNextMove || this.refuses === status) {
      this.failNextMove = false;
      this.calls.push(["move", id, status]);
      throw new Error("The server said no.");
    }
    return super.move(id, status);
  }
  override async create(input: Parameters<FakeTaskService["create"]>[0]) {
    if (this.holdCreate) await this.holdCreate;
    if (this.failNextCreate) {
      this.failNextCreate = false;
      throw new Error("The server said no.");
    }
    return super.create(input);
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
    expect(alert).toHaveTextContent(`Could not move "${PRD}". It is back in To Do.`);
    expect(titlesIn("To Do")).toContain(PRD);
    expect(titlesIn("Testing")).not.toContain(PRD);

    fireEvent.click(within(alert).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(moveCalls(service)).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("moves the task on Retry even when the filters have since hidden its card", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    drag(PRD, "Testing").drop();
    const alert = await screen.findByRole("alert");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "docker" } });
    expect(screen.queryByRole("article", { name: PRD })).not.toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(moveCalls(service)).toEqual([
      ["move", "t5", "testing"],
      ["move", "t5", "testing"],
    ]);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "" } });
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
  });

  it("lets the error be dismissed", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    drag(PRD, "Testing").drop();
    fireEvent.click(within(await screen.findByRole("alert")).getByRole("button", { name: /^Dismiss/ }));
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

  it("names the column the card is really back in when the second of two chained moves fails", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.refuses = "testing";
    let release = () => {};
    service.hold = new Promise<void>((resolve) => (release = resolve));
    await renderBoard({ taskService: service });

    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    expect(titlesIn("In Progress")).toContain(PRD);
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    expect(titlesIn("Testing")).toContain(PRD);

    await act(async () => release());
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(titlesIn("In Progress")).toContain(PRD));
    expect(alert).toHaveTextContent(`Could not move "${PRD}". It is back in In Progress.`);
  });

  it("puts focus back on the card when a Shift+Arrow move is refused and the card returns to its column", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await screen.findByRole("alert");

    expect(titlesIn("To Do")).toContain(PRD);
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());
  });

  it("puts focus back on the card when a move button's move is refused", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    const button = within(card(COMPOSE)).getByRole("button", { name: `Move "${COMPOSE}" to Done` });
    button.focus();
    fireEvent.click(button);
    await screen.findByRole("alert");

    expect(titlesIn("Testing")).toContain(COMPOSE);
    await waitFor(() => expect(openButton(COMPOSE)).toHaveFocus());
  });

  it("keeps focus off the body when Retry is refused again", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    const retry = within(await screen.findByRole("alert")).getByRole("button", { name: /^Retry/ });
    retry.focus();
    fireEvent.click(retry);

    await waitFor(() => expect(moveCalls(service)).toHaveLength(2));
    await screen.findByRole("alert");
    expect(titlesIn("To Do")).toContain(PRD);
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());
  });

  it("leaves focus where the user has put it while the refused move was pending", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    let release = () => {};
    service.hold = new Promise<void>((resolve) => (release = resolve));
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());
    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    search.focus();

    await act(async () => release());
    await screen.findByRole("alert");
    expect(search).toHaveFocus();
  });

  it("does not take focus when a dragged move is refused, even for a card the keyboard moved before", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(moveCalls(service)).toHaveLength(1));
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());

    service.failNextMove = true;
    drag(PRD, "Testing").drop();
    await screen.findByRole("alert");
    expect(titlesIn("In Progress")).toContain(PRD);
    expect(openButton(PRD)).not.toHaveFocus();
  });

  it("sends focus to the column the card left when a successful move takes it off the board", async () => {
    await renderBoard();
    fireEvent.click(within(screen.getByRole("complementary", { name: "Workspace" })).getByRole("button", { name: /^Overdue/ }));
    expect(titlesIn("To Do")).toEqual([PRD]);

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(titlesIn("In Progress")).toEqual([PRD]));
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(titlesIn("Testing")).toEqual([PRD]));

    // Done is not overdue-and-open, so this move drops the card out of the Overdue scope.
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(screen.queryByRole("article", { name: PRD })).not.toBeInTheDocument());
    await waitFor(() => expect(within(column("Testing")).getByRole("heading", { level: 2 })).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
  });

  it("sends focus to the card that took its place when the column it left still has cards", async () => {
    const overdue = (id: string, title: string) => makeTask({ id, title, status: "testing", due: due(-2) });
    await renderBoard({ tasks: [overdue("o1", "First overdue"), overdue("o2", "Second overdue"), overdue("o3", "Third overdue")] });
    fireEvent.click(within(screen.getByRole("complementary", { name: "Workspace" })).getByRole("button", { name: /^Overdue/ }));
    expect(titlesIn("Testing")).toEqual(["First overdue", "Second overdue", "Third overdue"]);

    openButton("Second overdue").focus();
    fireEvent.keyDown(openButton("Second overdue"), { key: "ArrowRight", shiftKey: true });

    await waitFor(() => expect(titlesIn("Testing")).toEqual(["First overdue", "Third overdue"]));
    await waitFor(() => expect(openButton("Third overdue")).toHaveFocus());
  });

  it("serializes two rapid moves of the same card and keeps the newer target", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const calls = vi.spyOn(service, "move");
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });

    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    expect(titlesIn("Testing")).toContain(PRD);
    // The second service call cannot start while the first is still held.
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);

    await act(async () => release());
    await waitFor(() => expect(moveCalls(service)).toEqual([["move", "t5", "progress"], ["move", "t5", "testing"]]));
    expect(calls.mock.calls).toEqual([["t5", "progress"], ["t5", "testing"]]);
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(titlesIn("In Progress")).not.toContain(PRD);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("supersedes an intermediate queued target without sending it to the service", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const calls = vi.spyOn(service, "move");
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });

    for (let i = 0; i < 3; i++) fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    expect(titlesIn("Done")).toContain(PRD);
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);

    await act(async () => release());
    await waitFor(() => expect(moveCalls(service)).toEqual([["move", "t5", "progress"], ["move", "t5", "done"]]));
    expect(calls.mock.calls).toEqual([["t5", "progress"], ["t5", "done"]]);
    expect(titlesIn("Done")).toContain(PRD);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("returns to the starting column with no net status change after rapid forward and back moves", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const calls = vi.spyOn(service, "move");
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });

    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowLeft", shiftKey: true });
    expect(titlesIn("To Do")).toContain(PRD);
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);

    await act(async () => release());
    await waitFor(() => expect(moveCalls(service)).toEqual([["move", "t5", "progress"], ["move", "t5", "todo"]]));
    expect(calls.mock.calls).toEqual([["t5", "progress"], ["t5", "todo"]]);
    expect((await service.get("t5"))?.status).toBe("todo");
    expect(titlesIn("To Do")).toContain(PRD);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says nothing when the refused move was on the way back to the column the card is in", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const calls = vi.spyOn(service, "move");
    service.refuses = "progress";
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowLeft", shiftKey: true });
    expect(titlesIn("To Do")).toContain(PRD);

    await act(async () => release());
    await waitFor(() => expect(moveCalls(service)).toEqual([["move", "t5", "progress"]]));
    // The queued target was the card's own status, so nothing the user asked for is missing.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);
    expect((await service.get("t5"))?.status).toBe("todo");
    expect(titlesIn("To Do")).toContain(PRD);
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());

    // The card is not stuck: the next move still goes through.
    service.refuses = null;
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(titlesIn("In Progress")).toContain(PRD));
  });

  it("cancels queued moves when the in-flight move fails and rolls back to its true starting status", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const calls = vi.spyOn(service, "move");
    service.refuses = "progress";
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });

    openButton(PRD).focus();
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(openButton(PRD), { key: "ArrowRight", shiftKey: true });
    expect(titlesIn("Testing")).toContain(PRD);
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);

    await act(async () => release());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Could not move "${PRD}". It is back in To Do.`);
    expect(titlesIn("To Do")).toContain(PRD);
    expect(titlesIn("In Progress")).not.toContain(PRD);
    expect(titlesIn("Testing")).not.toContain(PRD);
    expect((await service.get("t5"))?.status).toBe("todo");
    expect(calls.mock.calls).toEqual([["t5", "progress"]]);
    await waitFor(() => expect(openButton(PRD)).toHaveFocus());

    service.refuses = null;
    fireEvent.click(within(alert).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(calls.mock.calls).toEqual([["t5", "progress"], ["t5", "testing"]]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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

describe("concurrent board attempts", () => {
  it("keeps a move error the user has not acted on when an add is started, and reports both", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    drag(PRD, "Testing").drop();
    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${PRD}".`);

    service.failNextCreate = true;
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
      expect.stringContaining(`Could not move "${PRD}". It is back in To Do.`),
      expect.stringContaining("Could not add a task to Testing."),
    ]);

    for (const alert of screen.getAllByRole("alert")) fireEvent.click(within(alert).getByRole("button", { name: /^Dismiss/ }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps a move error on screen when an add in another column succeeds", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    drag(PRD, "Testing").drop();
    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${PRD}".`);

    fireEvent.click(within(column("Done")).getByRole("button", { name: "Add a task" }));
    await screen.findByRole("dialog", { name: "Untitled task" });
    expect(screen.getByRole("alert")).toHaveTextContent(`Could not move "${PRD}". It is back in To Do.`);
  });

  it("reports a refused add that was in flight while a move succeeded", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    drag(PRD, "In Progress").drop();
    await waitFor(() => expect(titlesIn("In Progress")).toContain(PRD));
    await act(async () => release());

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add a task to Testing.");
  });

  it("reports a refused add and a refused move that overlapped, side by side", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    service.failNextMove = true;
    drag(PRD, "In Progress").drop();
    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${PRD}".`);
    await act(async () => release());

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
      expect.stringContaining(`Could not move "${PRD}". It is back in To Do.`),
      expect.stringContaining("Could not add a task to Testing."),
    ]);
  });

  it("reports a refused add when no move happens at all", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await act(async () => release());

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add a task to Testing.");
  });

  it("still reports a refused move that was in flight while an unrelated add succeeded", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    drag(PRD, "In Progress").drop();
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await screen.findByRole("dialog", { name: "Untitled task" });
    await act(async () => release());

    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${PRD}". It is back in To Do.`);
    expect(titlesIn("To Do")).toContain(PRD);
  });

  it("still reports a refused move after a newer move on another card has succeeded", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    drag(PRD, "In Progress").drop();
    drag(JWT, "Testing").drop();
    await waitFor(() => expect(titlesIn("Testing")).toContain(JWT));
    await act(async () => release());

    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${PRD}". It is back in To Do.`);
    expect(titlesIn("To Do")).toContain(PRD);
    // The successful card keeps its own announcement; the refusal takes back only its own.
    expect(screen.getByTestId("board-live")).toHaveTextContent(`Moved "${JWT}" to Testing.`);
  });

  it("keeps the newest move error and reports the older task's refusal when it arrives later", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holds.set("progress", new Promise<void>((resolve) => (release = resolve)));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    drag(PRD, "In Progress").drop();
    drag(JWT, "In Progress").drop();
    expect(await screen.findByRole("alert")).toHaveTextContent(`Could not move "${JWT}".`);
    await act(async () => release());

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual([
      expect.stringContaining(`Could not move "${PRD}". It is back in To Do.`),
      expect.stringContaining(`Could not move "${JWT}". It is back in To Do.`),
    ]);
  });

  it("dismisses and retries each refusal on its own card", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    drag(PRD, "In Progress").drop();
    drag(JWT, "In Progress").drop();
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));

    const [prdAlert] = screen.getAllByRole("alert");
    fireEvent.click(within(prdAlert).getByRole("button", { name: /^Dismiss/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(`Could not move "${JWT}".`);

    service.refuses = null;
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(titlesIn("In Progress")).toContain(JWT));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps a keyboard task's settlement when another task answers in the same batch", async () => {
    const service = new ControlledTaskService([
      makeTask({ id: "a", title: "Keyboard task", status: "testing", due: due(-1) }),
      makeTask({ id: "b", title: "Dragged task", status: "todo", due: due(-1) }),
    ]);
    let release = () => {};
    service.hold = new Promise<void>((resolve) => (release = resolve));
    await renderBoard({ taskService: service });
    fireEvent.click(within(screen.getByRole("complementary", { name: "Workspace" })).getByRole("button", { name: /^Overdue/ }));

    openButton("Keyboard task").focus();
    fireEvent.keyDown(openButton("Keyboard task"), { key: "ArrowRight", shiftKey: true });
    drag("Dragged task", "In Progress").drop();
    await act(async () => release());

    expect(screen.queryByRole("article", { name: "Keyboard task" })).not.toBeInTheDocument();
    expect(titlesIn("In Progress")).toContain("Dragged task");
    await waitFor(() => expect(within(column("Testing")).getByRole("heading")).toHaveFocus());
  });

  it("does not consume a pending keyboard move's focus when a different task settles earlier", async () => {
    const service = new ControlledTaskService([
      makeTask({ id: "a", title: "Keyboard task", status: "testing", due: due(-1) }),
      makeTask({ id: "b", title: "Dragged task", status: "todo", due: due(-1) }),
    ]);
    let release = () => {};
    service.holds.set("done", new Promise<void>((resolve) => (release = resolve)));
    await renderBoard({ taskService: service });
    fireEvent.click(within(screen.getByRole("complementary", { name: "Workspace" })).getByRole("button", { name: /^Overdue/ }));

    openButton("Keyboard task").focus();
    fireEvent.keyDown(openButton("Keyboard task"), { key: "ArrowRight", shiftKey: true });
    drag("Dragged task", "In Progress").drop();
    await waitFor(() => expect(moveCalls(service)).toEqual([["move", "b", "progress"]]));
    expect(openButton("Keyboard task")).toHaveFocus();
    await act(async () => release());
    await waitFor(() => expect(within(column("Testing")).getByRole("heading")).toHaveFocus());
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

  it("says so when the task cannot be added, and Retry adds it", async () => {
    class FailsFirstCreate extends FakeTaskService {
      private failed = false;
      override async create(input: Parameters<FakeTaskService["create"]>[0]) {
        if (!this.failed) {
          this.failed = true;
          throw new Error("The server said no.");
        }
        return super.create(input);
      }
    }
    await renderBoard({ taskService: new FailsFirstCreate(seedTasks(NOW)) });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not add a task to Testing.");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: /^Retry/ }));
    await screen.findByRole("dialog", { name: "Untitled task" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(titlesIn("Testing")).toContain("Untitled task");
  });

  it("keeps the add-a-task failure on screen while a move failure comes and goes beside it", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add a task to Testing.");

    service.failNextMove = true;
    drag(PRD, "Testing").drop();
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));

    fireEvent.click(within(screen.getAllByRole("alert")[0]).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(titlesIn("Testing")).toContain(PRD));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not add a task to Testing.");
  });

  it("reports a refused add even though another column started one before it answered", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("To Do")).getByRole("button", { name: "Add a task" }));
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await act(async () => release());

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add a task to To Do.");
    await waitFor(() => expect(titlesIn("Testing")).toContain("Untitled task"));
    expect(titlesIn("To Do")).not.toContain("Untitled task");
  });

  it("asks for one task at a time in a column, and for both when two columns add at once", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    fireEvent.click(within(column("Done")).getByRole("button", { name: "Add a task" }));
    await act(async () => release());

    await waitFor(() => expect(titlesIn("Done")).toContain("Untitled task"));
    expect(service.calls.filter((c) => c[0] === "create")).toEqual([
      ["create", { title: "Untitled task", status: "testing", project: "inbox" }],
      ["create", { title: "Untitled task", status: "done", project: "inbox" }],
    ]);
  });

  it("holds the column until a refused add is retried or dismissed", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    const creates = vi.spyOn(service, "create");
    service.failNextCreate = true;
    await renderBoard({ taskService: service });
    const addIn = (name: string) => within(column(name)).getByRole("button", { name: "Add a task" });

    fireEvent.click(addIn("Testing"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not add a task to Testing.");

    fireEvent.click(addIn("Testing"));
    expect(creates).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not add a task to Testing.");

    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: /^Dismiss/ }));
    fireEvent.click(addIn("Testing"));
    await screen.findByRole("dialog", { name: "Untitled task" });
    expect(creates).toHaveBeenCalledTimes(2);
  });

  it("puts focus back on the Add a task when its alert is retried", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    const retry = within(await screen.findByRole("alert")).getByRole("button", { name: /^Retry/ });
    retry.focus();
    fireEvent.click(retry);

    expect(within(column("Testing")).getByRole("button", { name: "Add a task" })).toHaveFocus();
    await screen.findByRole("dialog", { name: "Untitled task" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says the column's Add a task is unavailable while it is busy, and keeps it focusable", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    let release = () => {};
    service.holdCreate = new Promise<void>((resolve) => (release = resolve));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });
    const addIn = (name: string) => within(column(name)).getByRole("button", { name: "Add a task" });

    addIn("Testing").focus();
    fireEvent.click(addIn("Testing"));
    expect(addIn("Testing")).toHaveAttribute("aria-disabled", "true");
    expect(addIn("Testing")).toHaveAttribute("aria-busy", "true");
    expect(addIn("Testing")).toHaveFocus();
    expect(addIn("Done")).not.toHaveAttribute("aria-disabled");

    await act(async () => release());
    await screen.findByRole("alert");
    expect(addIn("Testing")).toHaveAttribute("aria-disabled", "true");
    expect(addIn("Testing")).not.toHaveAttribute("aria-busy");

    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: /^Dismiss/ }));
    expect(addIn("Testing")).not.toHaveAttribute("aria-disabled");
    expect(addIn("Testing")).toHaveFocus();
  });

  it("names each alert's buttons after what it is about, keeping the visible labels", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });
    drag(PRD, "Testing").drop();
    await screen.findByRole("alert");

    service.failNextCreate = true;
    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));

    expect(screen.getByRole("button", { name: `Retry moving "${PRD}"` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Dismiss: could not move "${PRD}"` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry adding a task to Testing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss: could not add a task to Testing" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Retry/ }).map((b) => b.textContent)).toEqual(["Retry", "Retry"]);
  });
});

describe("dismissing an alert", () => {
  it("puts focus back on the card a move failure is about", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    drag(PRD, "Testing").drop();
    const dismiss = within(await screen.findByRole("alert")).getByRole("button", { name: /^Dismiss/ });
    dismiss.focus();
    fireEvent.click(dismiss);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(openButton(PRD)).toHaveFocus();
  });

  it("falls back to the column heading when the card is no longer on the board", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextMove = true;
    await renderBoard({ taskService: service });

    drag(PRD, "Testing").drop();
    const alert = await screen.findByRole("alert");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "docker" } });
    expect(screen.queryByRole("article", { name: PRD })).not.toBeInTheDocument();

    const dismiss = within(alert).getByRole("button", { name: /^Dismiss/ });
    dismiss.focus();
    fireEvent.click(dismiss);

    expect(within(column("To Do")).getByRole("heading", { level: 2 })).toHaveFocus();
  });

  it("keeps the other alert and stays off the body when one of two is dismissed", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.refuses = "progress";
    await renderBoard({ taskService: service });

    drag(PRD, "In Progress").drop();
    drag(JWT, "In Progress").drop();
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));

    const dismiss = within(screen.getAllByRole("alert")[0]).getByRole("button", { name: /^Dismiss/ });
    dismiss.focus();
    fireEvent.click(dismiss);

    expect(screen.getByRole("alert")).toHaveTextContent(`Could not move "${JWT}".`);
    expect(openButton(PRD)).toHaveFocus();
  });

  it("puts focus back on the Add a task the failure is about", async () => {
    const service = new ControlledTaskService(seedTasks(NOW));
    service.failNextCreate = true;
    await renderBoard({ taskService: service });

    fireEvent.click(within(column("Testing")).getByRole("button", { name: "Add a task" }));
    const dismiss = within(await screen.findByRole("alert")).getByRole("button", { name: /^Dismiss/ });
    dismiss.focus();
    fireEvent.click(dismiss);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(column("Testing")).getByRole("button", { name: "Add a task" })).toHaveFocus();
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

    fireEvent.click(within(alert).getByRole("button", { name: /^Retry/ }));
    expect(await screen.findByRole("article", { name: "Only task" })).toBeInTheDocument();
  });
});
