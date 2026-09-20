import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { makeTask } from "@/test/tasks";
import { TasksApp } from "../shell/TasksApp";
import type { Task } from "../model/types";

const alpha = makeTask({ id: "alpha", title: "Alpha", importance: 90 });
const beta = makeTask({ id: "beta", title: "Beta", importance: 50 });
const board = () => screen.getByRole("region", { name: "Board", exact: true });
const card = (name: string) => within(board()).getByRole("button", { name, exact: true });
const heading = (name: string) => within(board()).getByRole("heading", { name, exact: true });
const panel = () => screen.getByRole("dialog");
const close = () => fireEvent.keyDown(window, { key: "Escape" });

async function setup(tasks: Task[] = [alpha, beta]) {
  const services = renderWithServices(<TasksApp />, { tasks });
  fireEvent.click(screen.getByText("Board", { exact: true }));
  await screen.findByRole("region", { name: "To Do", exact: true });
  return services;
}

function open(name = "Alpha") {
  act(() => card(name).focus());
  fireEvent.click(card(name));
  expect(panel()).toContainElement(document.activeElement as HTMLElement);
}

async function moveOpenTask() {
  fireEvent.change(within(panel()).getByRole("combobox", { name: "Status", exact: true }), { target: { value: "progress" } });
  await waitFor(() => expect(within(panel()).getByTestId("detail-status")).toHaveTextContent("In Progress"));
}

async function removeOpenTask() {
  fireEvent.click(within(panel()).getByRole("button", { name: "Delete", exact: true }));
  fireEvent.click(within(panel()).getByRole("button", { name: "Delete task", exact: true }));
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
    fireEvent.change(screen.getByRole("combobox", { name: "Priority", exact: true }), { target: { value: "0" } });
    open();
    fireEvent.change(within(panel()).getByRole("combobox", { name: "Priority", exact: true }), { target: { value: "3" } });
    await waitFor(() => expect(within(board()).queryByRole("button", { name: "Alpha", exact: true })).not.toBeInTheDocument());
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
