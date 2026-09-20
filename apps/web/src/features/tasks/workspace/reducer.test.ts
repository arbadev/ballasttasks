import { describe, expect, it } from "vitest";
import { makeTask } from "@/test/tasks";
import { DEFAULT_QUERY } from "../model/filter";
import { initialWorkspaceState, workspaceReducer, type WorkspaceAction, type WorkspaceState } from "./reducer";

const apply = (actions: WorkspaceAction[], from: WorkspaceState = initialWorkspaceState) => actions.reduce(workspaceReducer, from);

describe("workspaceReducer", () => {
  it("starts loading, on the list, with the design's default filters and nothing selected", () => {
    expect(initialWorkspaceState).toEqual({
      load: { status: "loading" },
      tasks: [],
      query: DEFAULT_QUERY,
      sort: "urgency",
      view: "list",
      selectedId: null,
    });
  });

  it("stores the loaded tasks and becomes ready", () => {
    const tasks = [makeTask()];
    expect(apply([{ type: "tasksLoaded", tasks }])).toMatchObject({ load: { status: "ready" }, tasks });
  });

  it("records a load failure, and goes back to loading on retry", () => {
    const failed = apply([{ type: "loadFailed", message: "offline" }]);
    expect(failed.load).toEqual({ status: "error", message: "offline" });
    expect(apply([{ type: "loadStarted" }], failed).load).toEqual({ status: "loading" });
  });

  it("selects a scope", () => {
    expect(apply([{ type: "scopeSelected", scope: "mine" }]).query.scope).toBe("mine");
  });

  it("resets the status filter to All open when Overdue is selected, as the design does", () => {
    const state = apply([{ type: "statusFilterChanged", status: "done" }, { type: "scopeSelected", scope: "overdue" }]);
    expect(state.query).toMatchObject({ scope: "overdue", status: "open" });
  });

  it("leaves the status filter alone for the other scopes", () => {
    const state = apply([{ type: "statusFilterChanged", status: "done" }, { type: "scopeSelected", scope: "mine" }]);
    expect(state.query.status).toBe("done");
  });

  it("toggles a project: selecting the active one goes back to all", () => {
    const on = apply([{ type: "projectToggled", project: "inbox" }]);
    expect(on.query.project).toBe("inbox");
    expect(apply([{ type: "projectToggled", project: "inbox" }], on).query.project).toBe("all");
    expect(apply([{ type: "projectToggled", project: "ballast" }], on).query.project).toBe("ballast");
  });

  it("changes each toolbar filter, the sort and the search independently", () => {
    const state = apply([
      { type: "statusFilterChanged", status: "testing" },
      { type: "dueFilterChanged", due: "week" },
      { type: "priorityFilterChanged", priority: "0" },
      { type: "sortChanged", sort: "due" },
      { type: "searchChanged", search: "jwt" },
    ]);
    expect(state.query).toEqual({ ...DEFAULT_QUERY, status: "testing", due: "week", priority: "0", search: "jwt" });
    expect(state.sort).toBe("due");
  });

  it("toggles an Attention signal on, over to another, and off", () => {
    const on = apply([{ type: "signalToggled", signal: "overdue" }]);
    expect(on.query.signal).toBe("overdue");
    expect(apply([{ type: "signalToggled", signal: "soon" }], on).query.signal).toBe("soon");
    expect(apply([{ type: "signalToggled", signal: "overdue" }], on).query.signal).toBeNull();
    expect(apply([{ type: "signalCleared" }], on).query.signal).toBeNull();
  });

  it("switches view without touching the filters", () => {
    const state = apply([{ type: "searchChanged", search: "x" }, { type: "viewChanged", view: "board" }]);
    expect(state).toMatchObject({ view: "board", query: { search: "x" } });
  });

  it("selects and clears a task", () => {
    const selected = apply([{ type: "taskSelected", id: "t4" }]);
    expect(selected.selectedId).toBe("t4");
    expect(apply([{ type: "selectionCleared" }], selected).selectedId).toBeNull();
  });

  it("replaces a changed task in place", () => {
    const tasks = [makeTask({ id: "a" }), makeTask({ id: "b" })];
    const state = apply([{ type: "tasksLoaded", tasks }, { type: "taskSaved", task: makeTask({ id: "b", title: "Renamed" }) }]);
    expect(state.tasks.map((t) => t.title)).toEqual(["A task", "Renamed"]);
  });

  it("puts a new task first", () => {
    const state = apply([{ type: "tasksLoaded", tasks: [makeTask({ id: "a" })] }, { type: "taskSaved", task: makeTask({ id: "new" }) }]);
    expect(state.tasks.map((t) => t.id)).toEqual(["new", "a"]);
  });

  it("removes a task and clears the selection if it was the one selected", () => {
    const loaded = apply([{ type: "tasksLoaded", tasks: [makeTask({ id: "a" }), makeTask({ id: "b" })] }]);
    const gone = apply([{ type: "taskSelected", id: "a" }, { type: "taskRemoved", id: "a" }], loaded);
    expect(gone).toMatchObject({ selectedId: null, tasks: [{ id: "b" }] });
    const other = apply([{ type: "taskSelected", id: "b" }, { type: "taskRemoved", id: "a" }], loaded);
    expect(other.selectedId).toBe("b");
  });

  it("does not let a late list response overwrite saved tasks or resurrect deletions", () => {
    const old = makeTask({ id: "a", title: "old" });
    const saved = makeTask({ id: "a", title: "saved" });
    const result = apply([
      { type: "tasksLoaded", tasks: [old, makeTask({ id: "b" })] },
      { type: "loadStarted" },
      { type: "taskSaved", task: saved },
      { type: "taskRemoved", id: "b" },
      { type: "tasksLoaded", tasks: [old, makeTask({ id: "b" })] },
    ]);
    expect(result.tasks).toEqual([saved]);
  });

  it("ignores detail fetched before a mutation or deletion", () => {
    const summary = makeTask({ id: "a", detailLoaded: false });
    const saved = makeTask({ id: "a", title: "saved" });
    const loaded = apply([{ type: "tasksLoaded", tasks: [summary] }, { type: "taskSelected", id: "a" }]);
    const changed = apply([{ type: "taskSaved", task: saved }, { type: "detailLoaded", task: { ...summary, detailLoaded: true }, expected: summary }], loaded);
    expect(changed.tasks).toEqual([saved]);
    const removed = apply([{ type: "taskRemoved", id: "a" }, { type: "detailLoaded", task: { ...summary, detailLoaded: true }, expected: summary }], loaded);
    expect(removed.tasks).toEqual([]);
  });

  it("returns the same state for a no-op, so nothing re-renders", () => {
    expect(workspaceReducer(initialWorkspaceState, { type: "viewChanged", view: "list" })).toBe(initialWorkspaceState);
    expect(workspaceReducer(initialWorkspaceState, { type: "signalCleared" })).toBe(initialWorkspaceState);
  });
});
