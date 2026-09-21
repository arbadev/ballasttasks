import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { FakeQueryTaskService, type FakeTaskService } from "@/test/fakeServices";
import { makeTask } from "@/test/tasks";
import { TasksApp } from "../shell/TasksApp";
import type { Task } from "../model/types";

const alpha = makeTask({ id: "alpha", title: "Alpha", importance: 90 });
const beta = makeTask({ id: "beta", title: "Beta", importance: 50 });
const board = () => screen.getByRole("region", { name: "Board" });
const card = (name: string) => within(board()).getByRole("button", { name });
const heading = (name: string) => within(board()).getByRole("heading", { name });
const panel = () => screen.getByRole("dialog");
const close = () => fireEvent.keyDown(window, { key: "Escape" });
const firstTaskField = () => screen.getByRole("textbox", { name: "Name the first task" });
const settled = () => waitFor(() => expect(board()).toHaveAttribute("aria-busy", "false"));
/** The sidebar's project filter, once the directory this shell loaded it from has answered. */
const project = () => within(screen.getByRole("complementary", { name: "Workspace" })).findByRole("button", { name: /^Ballast Tasks/ });

async function setup(tasks: Task[] = [alpha, beta], taskService?: FakeTaskService) {
  const services = renderWithServices(<TasksApp />, taskService ? { taskService } : { tasks });
  fireEvent.click(screen.getByText("Board", { exact: true }));
  await screen.findByRole("region", { name: "To Do" });
  await settled();
  return services;
}

/** The same board, with only the selected project's tasks on it, as the design's project filter leaves it. */
async function setupProject(tasks: Task[] = [alpha], taskService?: FakeTaskService) {
  const services = renderWithServices(<TasksApp />, taskService ? { taskService } : { tasks });
  fireEvent.click(await project());
  fireEvent.click(screen.getByText("Board", { exact: true }));
  await screen.findByRole("region", { name: "To Do" });
  await settled();
  return services;
}

function open(name = "Alpha") {
  act(() => card(name).focus());
  fireEvent.click(card(name));
  expect(panel()).toContainElement(document.activeElement as HTMLElement);
}

async function moveOpenTask() {
  fireEvent.change(within(panel()).getByRole("combobox", { name: "Status" }), { target: { value: "progress" } });
  await waitFor(() => expect(within(panel()).getByTestId("detail-status")).toHaveTextContent("In Progress"));
}

async function removeOpenTask() {
  fireEvent.click(within(panel()).getByRole("button", { name: "Delete" }));
  fireEvent.click(within(panel()).getByRole("button", { name: "Delete task" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

describe("board-opened panel return", () => {
  it("returns to the connected card after a detail status move, without leaving the modal early", async () => {
    const { taskService } = await setup();
    const original = card("Alpha");
    open();
    await moveOpenTask();
    expect(original.isConnected).toBe(false);
    expect(panel()).toContainElement(document.activeElement as HTMLElement);
    expect((await taskService.get("alpha"))?.status).toBe("progress");
    close();
    expect(card("Alpha")).toHaveFocus();
  });

  it.each([true, false])("returns after deletion to a surviving neighbour, or the empty column heading (neighbour=%s)", async (neighbour) => {
    const { taskService } = await setup(neighbour ? [alpha, beta] : [alpha]);
    open();
    await removeOpenTask();
    expect(await taskService.get("alpha")).toBeNull();
    expect(neighbour ? card("Beta") : heading("To Do")).toHaveFocus();
  });

  it("uses the origin column when an edit filters the task away", async () => {
    await setup([{ ...alpha, prio: 0 }]);
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    open();
    fireEvent.change(within(panel()).getByRole("combobox", { name: "Priority" }), { target: { value: "3" } });
    await waitFor(() => expect(within(board()).queryByRole("button", { name: "Alpha" })).not.toBeInTheDocument());
    expect(panel()).toContainElement(document.activeElement as HTMLElement);
    close();
    expect(heading("To Do")).toHaveFocus();
  });

  it("keeps the existing unchanged-close and direct keyboard-move controls", async () => {
    await setup();
    const original = card("Alpha");
    open();
    close();
    expect(original).toHaveFocus();
    fireEvent.keyDown(original, { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(card("Alpha").closest("[data-column]")).toHaveAttribute("data-column", "progress"));
    expect(card("Alpha")).toHaveFocus();
  });

  it("does not reclaim unrelated deliberately placed focus when a disconnected opener closes", async () => {
    await setup();
    open();
    await moveOpenTask();
    const search = screen.getByRole("searchbox", { name: "Search tasks" });
    act(() => search.focus());
    close();
    expect(search).toHaveFocus();
  });

  it("uses the newest board selection, never the obsolete panel's return location", async () => {
    await setup();
    open();
    await moveOpenTask();
    open("Beta"); // Simulates an explicit selection command, not a native click through a modal.
    await moveOpenTask();
    close();
    expect(card("Beta")).toHaveFocus();
    expect(card("Alpha")).not.toHaveFocus();
  });

  it("does not revive an old return after unchanged close and a later unrelated render", async () => {
    await setup();
    open();
    close();
    act(() => card("Alpha").blur());
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tasks" }), { target: { value: "Beta" } });
    expect(document.body).toHaveFocus();
  });
});

/**
 * The same board over a served page, as the HTTP adapter leaves it: the workspace holds a page,
 * and a save is answered twice — by the save itself, then by the canonical query it triggers.
 */
describe("board-opened panel return over a served page", () => {
  const p0 = (task: Task) => ({ ...task, prio: 0 as const });

  it("returns to the replacement card when the save that moved it lands after the close", async () => {
    const service = new FakeQueryTaskService([alpha, beta]);
    await setup([], service);
    open();
    const save = service.holdNext("move");
    fireEvent.change(within(panel()).getByRole("combobox", { name: "Status" }), { target: { value: "progress" } });
    await waitFor(() => expect(service.calls).toContainEqual(["move", "alpha", "progress"]));
    close(); // The old card is still on the board: the server has taken the change but not answered.
    expect(card("Alpha")).toHaveFocus();
    expect(card("Alpha").closest("[data-column]")).toHaveAttribute("data-column", "todo");

    await act(async () => save.release());
    await settled();
    expect(card("Alpha").closest("[data-column]")).toHaveAttribute("data-column", "progress");
    expect(card("Alpha")).toHaveFocus();
    expect((await service.get("alpha"))?.status).toBe("progress");
  });

  it("keeps the return through the canonical query that filters the task away", async () => {
    const service = new FakeQueryTaskService([p0(alpha), p0(beta)]);
    await setup([], service);
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    await settled();
    open();
    const refresh = service.holdNext("query");
    fireEvent.change(within(panel()).getByRole("combobox", { name: "Priority" }), { target: { value: "3" } });
    await waitFor(() => expect(service.calls).toContainEqual(["update", "alpha", { prio: 3 }]));
    // The call log precedes the acknowledgement and its query. Close only once
    // the deliberately held canonical query is actually pending.
    await waitFor(() => expect(board()).toHaveAttribute("aria-busy", "true"));
    close(); // The saved card is still on the old page, so the board returns to it first.
    expect(card("Alpha")).toHaveFocus();

    await act(async () => refresh.release());
    await settled();
    expect(within(board()).queryByRole("button", { name: "Alpha" })).not.toBeInTheDocument();
    expect(card("Beta")).toHaveFocus();
  });

  it("stops owing the return once the user parks the focus while that query is still out", async () => {
    const service = new FakeQueryTaskService([p0(alpha), p0(beta)]);
    await setup([], service);
    fireEvent.change(screen.getByRole("combobox", { name: "Priority" }), { target: { value: "0" } });
    await settled();
    open();
    const refresh = service.holdNext("query");
    fireEvent.change(within(panel()).getByRole("combobox", { name: "Priority" }), { target: { value: "3" } });
    await waitFor(() => expect(service.calls).toContainEqual(["update", "alpha", { prio: 3 }]));
    await waitFor(() => expect(board()).toHaveAttribute("aria-busy", "true"));
    close();
    expect(card("Alpha")).toHaveFocus();
    act(() => card("Alpha").blur()); // A click on board chrome that takes no focus of its own.

    await act(async () => refresh.release());
    await settled();
    expect(within(board()).queryByRole("button", { name: "Alpha" })).not.toBeInTheDocument();
    expect(document.body).toHaveFocus();
  });
});

describe("the last task of a project", () => {
  it("retires an unfinished board move's handoff when leaving for the list", async () => {
    const service = new FakeQueryTaskService([alpha]);
    await setupProject([], service);
    const save = service.holdNext("move");
    act(() => card("Alpha").focus());
    fireEvent.keyDown(card("Alpha"), { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(service.calls).toContainEqual(["move", "alpha", "progress"]));

    const list = screen.getByRole("radio", { name: "List" });
    act(() => list.focus());
    fireEvent.click(list);
    expect(screen.queryByRole("region", { name: "Board" })).not.toBeInTheDocument();
    await act(async () => save.release());
    await waitFor(() => expect(screen.getByRole("list", { name: "Tasks" }).parentElement).toHaveAttribute("aria-busy", "false"));
    expect(list).toHaveFocus();

    // A later, unrelated list-panel deletion must not spend that abandoned board claim.
    const row = screen.getByRole("button", { name: "Alpha" });
    act(() => row.focus());
    fireEvent.click(row);
    await removeOpenTask();
    expect(await service.get("alpha")).toBeNull();
    expect(await screen.findByRole("textbox", { name: "Name the first task" })).not.toHaveFocus();
  });

  it("does not carry a consumed empty-project handoff into a later project visit", async () => {
    await setupProject();
    open();
    await removeOpenTask();
    expect(firstTaskField()).toHaveFocus();

    const projectFilter = await project();
    act(() => projectFilter.focus());
    fireEvent.click(projectFilter); // Toggle this project off, showing all projects.
    expect(screen.queryByRole("textbox", { name: "Name the first task" })).not.toBeInTheDocument();
    act(() => projectFilter.blur());
    fireEvent.click(await project());
    expect(await screen.findByRole("textbox", { name: "Name the first task" })).not.toHaveFocus();
  });

  it("hands the keyboard to the first-task field when deleting it takes the board away", async () => {
    const { taskService } = await setupProject();
    open();
    await removeOpenTask();
    expect(await taskService.get("alpha")).toBeNull();
    expect(firstTaskField()).toHaveFocus();
  });

  it("stands on the emptied column until the served page agrees the project is empty", async () => {
    const service = new FakeQueryTaskService([alpha]);
    await setupProject([], service);
    open();
    const refresh = service.holdNext("query");
    await removeOpenTask();
    expect(heading("To Do")).toHaveFocus();

    await act(async () => refresh.release());
    await waitFor(() => expect(firstTaskField()).toHaveFocus());
  });

  it("leaves the first-task field alone when the project was empty all along", async () => {
    renderWithServices(<TasksApp />, { tasks: [{ ...beta, project: "inbox" }] });
    fireEvent.click(await project()); // Nothing was removed, so nothing is owed: the field waits to be reached.
    expect(await screen.findByRole("textbox", { name: "Name the first task" })).not.toHaveFocus();
  });
});
