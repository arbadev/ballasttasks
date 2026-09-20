import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { TasksApp } from "../shell/TasksApp";
import { BoardView } from "../board/BoardView";
import { ListView } from "../list/ListView";
import { EmptyProject, useEmptyProject } from "@/features/projects/EmptyProject";
import { describe, expect, it, vi } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { FakeTaskService } from "@/test/fakeServices";
import { makeTask } from "@/test/tasks";
import type { TaskPage, TaskPageRequest } from "../services/query";
import { WorkspaceProvider, useTaskCommands, useVisibleTasks, useWorkspace } from "./WorkspaceProvider";
const page = (name: string, offset = 0): TaskPage => ({ tasks: [makeTask({ id: name, title: name })], total: 101, headerTotal: 101, limit: 50, offset, sidebar: { all: 200, mine: 40, overdue: 3, byProject: {} }, signals: { overdue: 3, critical: 1, soon: 2, unassigned: 4 } });
class QueryService extends FakeTaskService {
  query = vi.fn<(request: TaskPageRequest) => Promise<TaskPage>>().mockImplementation(async (request) => page(`page-${request.offset}`, request.offset));
}
function Probe() {
  const { state, actions } = useWorkspace();
  const commands = useTaskCommands();
  const tasks = useVisibleTasks();
  return <>
    <p data-testid="titles">{tasks.map((task) => task.title).join(",")}</p>
    <p data-testid="total">{state.page?.total}</p>
    <button onClick={() => actions.setPage(50)}>Next page</button>
    <button onClick={() => actions.setStatusFilter("testing")}>Testing only</button>
    <button onClick={() => actions.setView("board")}>Board</button>
    <button onClick={() => void commands.create({ title: "created" })}>Create</button>
  </>;
}
function InvitationProbe() {
  const project = useEmptyProject();
  const { actions } = useWorkspace();
  return <>
    <button onClick={() => actions.toggleProject("ballast")}>Project</button>
    <button onClick={actions.reload}>Refresh</button>
    {project && <EmptyProject project={project} />}
  </>;
}

describe("server-query workspace", () => {
  it("preserves the first-task draft while its project's authoritative page refreshes", async () => {
    const service = new QueryService();
    const empty = { ...page("empty"), tasks: [], total: 0, headerTotal: 0, projectHasTasks: false };
    service.query.mockResolvedValue(empty);
    renderWithServices(<WorkspaceProvider><InvitationProbe /></WorkspaceProvider>, { taskService: service });
    fireEvent.click(screen.getByText("Project"));
    const input = await screen.findByRole("textbox", { name: "Name the first task" });
    fireEvent.change(input, { target: { value: "Unsubmitted work" } });
    let answer!: (value: TaskPage) => void;
    service.query.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
    const count = service.query.mock.calls.length;
    fireEvent.click(screen.getByText("Refresh"));
    await waitFor(() => expect(service.query.mock.calls.length).toBeGreaterThan(count));
    await act(async () => answer(empty));
    expect(screen.getByRole("textbox", { name: "Name the first task" })).toHaveValue("Unsubmitted work");
    service.query.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByText("Refresh"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your first-task draft is kept");
    expect(screen.getByRole("textbox", { name: "Name the first task" })).toHaveValue("Unsubmitted work");
    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "Name the first task" })).toHaveValue("Unsubmitted work");
  });
  it("keeps the moved card focused across an asynchronous authoritative page refresh", async () => {
    const task = makeTask({ id: "focus", title: "Query-backed move", status: "todo" });
    const service = new QueryService([task]);
    let answer!: (value: TaskPage) => void;
    service.query.mockResolvedValueOnce({ ...page("initial"), tasks: [task] });
    service.query.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
    renderWithServices(<WorkspaceProvider><BoardView /></WorkspaceProvider>, { taskService: service });
    const card = await screen.findByRole("button", { name: "Query-backed move" });
    card.focus();
    fireEvent.keyDown(card, { key: "ArrowRight", shiftKey: true });
    await waitFor(() => expect(service.query).toHaveBeenCalledTimes(2));
    await act(async () => answer({ ...page("refreshed"), tasks: [(await service.get(task.id))!] }));
    expect(within(await screen.findByRole("region", { name: "In Progress" })).getByRole("button", { name: task.title })).toHaveFocus();
  });

  it("shows an optimistic card in a column whose last server count is zero", async () => {
    const task = makeTask({ id: "optimistic", title: "Pending move", status: "todo" });
    const service = new QueryService([task]);
    let complete!: () => void;
    const move = service.move.bind(service);
    vi.spyOn(service, "move").mockImplementation(async (id, status) => {
      await new Promise<void>((resolve) => { complete = resolve; });
      return move(id, status);
    });
    service.query.mockResolvedValue({ ...page("initial"), tasks: [task], columns: { todo: 1, progress: 0, testing: 0, done: 0 } });
    renderWithServices(<WorkspaceProvider><BoardView /></WorkspaceProvider>, { taskService: service });
    const card = await screen.findByRole("button", { name: task.title });
    card.focus();
    fireEvent.keyDown(card, { key: "ArrowRight", shiftKey: true });
    expect(within(screen.getByRole("region", { name: "In Progress" })).getByRole("button", { name: task.title })).toHaveFocus();
    await act(async () => complete());
  });
  it("hands list focus to the next row only after the authoritative page removes a completed task", async () => {
    const first = makeTask({ id: "first", title: "Finish first", status: "todo" });
    const next = makeTask({ id: "next", title: "Keep next", status: "todo" });
    const service = new QueryService([first, next]);
    let answer!: (value: TaskPage) => void;
    service.query.mockResolvedValueOnce({ ...page("initial"), tasks: [first, next] });
    service.query.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
    renderWithServices(<WorkspaceProvider><ListView /></WorkspaceProvider>, { taskService: service });
    const title = await screen.findByRole("button", { name: first.title });
    title.focus();
    fireEvent.keyDown(title, { key: " " });
    await waitFor(() => expect(service.query).toHaveBeenCalledTimes(2));
    await act(async () => answer({ ...page("refreshed"), tasks: [next] }));
    expect(await screen.findByRole("button", { name: next.title })).toHaveFocus();
  });

  it("renders server totals and global/project counts, with working page controls", async () => {
    const service = new QueryService();
    renderWithServices(<TasksApp />, { taskService: service });
    expect(await screen.findByText("101 tasks")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Views" })).getByRole("button", { name: /All tasks/ })).toHaveTextContent("200");
    expect(screen.getByRole("button", { name: /4\s*need an owner/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(service.query).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })));
    await waitFor(() => expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled());
  });
  it("pages server results, resets page on filter/view changes, and never calls the full-list port", async () => {
    const service = new QueryService();
    renderWithServices(<WorkspaceProvider><Probe /></WorkspaceProvider>, { taskService: service });
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("page-0"));
    expect(screen.getByTestId("total")).toHaveTextContent("101");
    fireEvent.click(screen.getByText("Next page"));
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("page-50"));
    expect(screen.getByTestId("titles")).not.toHaveTextContent("page-0");
    fireEvent.click(screen.getByText("Testing only"));
    await waitFor(() => expect(service.query).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, query: expect.objectContaining({ status: "testing" }), board: false })));
    fireEvent.click(screen.getByText("Board"));
    await waitFor(() => expect(service.query).toHaveBeenLastCalledWith(expect.objectContaining({ board: true, offset: 0 })));
    expect(service.calls).not.toContainEqual(["list"]);
  });

  it("ignores late page/filter responses and reloads totals after successful mutations", async () => {
    const service = new QueryService();
    let old!: (value: TaskPage) => void;
    service.query.mockImplementationOnce(() => new Promise((resolve) => { old = resolve; }));
    renderWithServices(<WorkspaceProvider><Probe /></WorkspaceProvider>, { taskService: service });
    await waitFor(() => expect(service.query).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("Testing only"));
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("page-0"));
    await act(async () => { old(page("obsolete")); });
    expect(screen.getByTestId("titles")).not.toHaveTextContent("obsolete");
    const count = service.query.mock.calls.length;
    fireEvent.click(screen.getByText("Create"));
    await waitFor(() => expect(service.query.mock.calls.length).toBeGreaterThan(count));
  });
});
