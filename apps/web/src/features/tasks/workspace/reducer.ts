import {
  DEFAULT_QUERY,
  DEFAULT_SORT,
  type DueFilter,
  type PriorityFilter,
  type ProjectFilter,
  type Scope,
  type SignalId,
  type SortBy,
  type StatusFilter,
  type TaskQuery,
} from "../model/filter";
import type { Task } from "../model/types";
import type { TaskPage, TaskPageInfo, TaskPageRequest } from "../services/query";

export type View = "list" | "board";

export type LoadState = { status: "loading" } | { status: "ready" } | { status: "error"; message: string };

export interface WorkspaceState {
  load: LoadState;
  tasks: Task[];
  /** Scope, project, toolbar filters, search and the active Attention signal. */
  query: TaskQuery;
  sort: SortBy;
  view: View;
  selectedId: string | null;
  /** Changes made while a list reload is in flight win over that older response. */
  duringLoad?: Record<string, Task | null>;
  detailLoad?: LoadState;
  page?: TaskPageInfo;
  pageOffset?: number;
  revision?: number;
}

export type WorkspaceAction =
  | { type: "loadStarted" }
  | { type: "tasksLoaded"; tasks: Task[] }
  | { type: "loadFailed"; message: string }
  | { type: "pageChanged"; offset: number }
  | { type: "queryLoaded"; page: TaskPage; request: TaskPageRequest; revision: number }
  | { type: "taskSaved"; task: Task }
  | { type: "detailStarted" }
  | { type: "detailLoaded"; task: Task; expected: Task }
  | { type: "detailFailed"; id: string; message: string }
  | { type: "taskRemoved"; id: string }
  | { type: "scopeSelected"; scope: Scope }
  | { type: "projectToggled"; project: ProjectFilter }
  | { type: "statusFilterChanged"; status: StatusFilter }
  | { type: "dueFilterChanged"; due: DueFilter }
  | { type: "priorityFilterChanged"; priority: PriorityFilter }
  | { type: "sortChanged"; sort: SortBy }
  | { type: "searchChanged"; search: string }
  | { type: "signalToggled"; signal: SignalId }
  | { type: "signalCleared" }
  | { type: "viewChanged"; view: View }
  | { type: "taskSelected"; id: string }
  | { type: "selectionCleared" };

export const initialWorkspaceState: WorkspaceState = {
  load: { status: "loading" },
  tasks: [],
  query: DEFAULT_QUERY,
  sort: DEFAULT_SORT,
  view: "list",
  selectedId: null,
};

/** Returns `state` itself when the patch changes nothing, so no-ops never re-render. */
function withQuery(state: WorkspaceState, patch: Partial<TaskQuery>): WorkspaceState {
  const keys = Object.keys(patch) as (keyof TaskQuery)[];
  if (keys.every((k) => state.query[k] === patch[k])) return state;
  return { ...state, query: { ...state.query, ...patch }, pageOffset: 0, load: state.page ? { status: "loading" } : state.load };
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case "loadStarted":
      return { ...state, load: { status: "loading" }, duringLoad: {} };
    case "tasksLoaded": {
      const tasks = new Map(action.tasks.map((task) => [task.id, task]));
      for (const [id, task] of Object.entries(state.duringLoad ?? {})) {
        if (task) tasks.set(id, task);
        else tasks.delete(id);
      }
      return { ...state, load: { status: "ready" }, tasks: [...tasks.values()], duringLoad: undefined };
    }
    case "pageChanged":
      return { ...state, pageOffset: Math.max(0, action.offset), load: { status: "loading" } };
    case "queryLoaded": {
      const request = action.request;
      if (request.query !== state.query || request.sort !== state.sort || request.board !== (state.view === "board") || request.offset !== (state.pageOffset ?? 0) || action.revision !== (state.revision ?? 0)) return state;
      const { tasks: rows, ...info } = action.page;
      const selected = state.tasks.find((task) => task.id === state.selectedId);
      const tasks = rows.map((row) => selected?.id === row.id && selected.detailLoaded && selected.updatedAt === row.updatedAt ? selected : row);
      if (selected && !rows.some((row) => row.id === selected.id)) tasks.push(selected);
      return { ...state, tasks, page: { ...info, ids: rows.map((row) => row.id), project: request.query.project }, load: { status: "ready" }, duringLoad: undefined };
    }
    case "detailStarted":
      return { ...state, detailLoad: { status: "loading" } };
    case "detailFailed":
      return state.selectedId === action.id ? { ...state, detailLoad: { status: "error", message: action.message } } : state;
    case "detailLoaded":
      if (state.selectedId !== action.task.id || state.tasks.find((task) => task.id === action.task.id) !== action.expected) return state;
      return { ...state, tasks: state.tasks.map((task) => task.id === action.task.id ? action.task : task), detailLoad: { status: "ready" } };
    case "loadFailed":
      return { ...state, load: { status: "error", message: action.message } };
    case "taskSaved": {
      const known = state.tasks.some((t) => t.id === action.task.id);
      const tasks = known ? state.tasks.map((t) => (t.id === action.task.id ? action.task : t)) : [action.task, ...state.tasks];
      return { ...state, tasks, revision: (state.revision ?? 0) + 1, duringLoad: state.load.status === "loading" ? { ...state.duringLoad, [action.task.id]: action.task } : state.duringLoad };
    }
    case "taskRemoved":
      return {
        ...state,
        tasks: state.tasks.filter((t) => t.id !== action.id),
        revision: (state.revision ?? 0) + 1,
        duringLoad: state.load.status === "loading" ? { ...state.duringLoad, [action.id]: null } : state.duringLoad,
        selectedId: state.selectedId === action.id ? null : state.selectedId,
      };
    case "scopeSelected":
      // Overdue only makes sense over open work, so the design resets the status filter with it.
      return withQuery(state, action.scope === "overdue" ? { scope: "overdue", status: "open" } : { scope: action.scope });
    case "projectToggled":
      return withQuery(state, { project: state.query.project === action.project ? "all" : action.project });
    case "statusFilterChanged":
      return withQuery(state, { status: action.status });
    case "dueFilterChanged":
      return withQuery(state, { due: action.due });
    case "priorityFilterChanged":
      return withQuery(state, { priority: action.priority });
    case "sortChanged":
      return state.sort === action.sort ? state : { ...state, sort: action.sort, pageOffset: 0, load: state.page ? { status: "loading" } : state.load };
    case "searchChanged":
      return withQuery(state, { search: action.search });
    case "signalToggled":
      return withQuery(state, { signal: state.query.signal === action.signal ? null : action.signal });
    case "signalCleared":
      return withQuery(state, { signal: null });
    case "viewChanged":
      return state.view === action.view ? state : { ...state, view: action.view, pageOffset: 0, load: state.page ? { status: "loading" } : state.load };
    case "taskSelected":
      return state.selectedId === action.id ? state : { ...state, selectedId: action.id, detailLoad: undefined };
    case "selectionCleared":
      return state.selectedId === null ? state : { ...state, selectedId: null };
  }
}
