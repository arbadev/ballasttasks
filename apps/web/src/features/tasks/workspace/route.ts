import { DEFAULT_QUERY, type TaskQuery } from "../model/filter";
import { initialWorkspaceState, workspaceReducer, type View, type WorkspaceAction, type WorkspaceState } from "./reducer";

export const MAX_SEARCH_LENGTH = 200;
/** A search the route accepts, or "" for one it refuses. */
export function routeSearch(search: string): string { return search.length <= MAX_SEARCH_LENGTH && !/\p{Cc}/u.test(search) ? search : ""; }
export interface TaskRoute { query: TaskQuery; sort: WorkspaceState["sort"]; view: View; pageOffset: number }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function projectId(value: string, demo: boolean) { return UUID.test(value) || (demo && /^[a-z0-9-]{1,100}$/i.test(value)); }
function one(params: URLSearchParams, key: string): string | null { return params.getAll(key).length === 1 ? params.get(key) : null; }
function choice<T extends string>(value: string | null, choices: readonly T[], fallback: T): T { return choices.includes(value as T) ? value as T : fallback; }
export function isTaskPath(path: string, demo = false): boolean {
  return ["/tasks", "/tasks/mine", "/tasks/overdue"].includes(path) || (path.startsWith("/projects/") && projectId(path.slice(10), demo));
}
export function parseTaskRoute(href: string, demo = false): TaskRoute {
  const [path, query = ""] = href.split("?");
  const params = new URLSearchParams(query);
  const project = path.startsWith("/projects/") && projectId(path.slice(10), demo) ? path.slice(10) : "all";
  const scope = project === "all" ? (path === "/tasks/mine" ? "mine" : path === "/tasks/overdue" ? "overdue" : "all") : choice(one(params, "scope"), ["all", "mine", "overdue"], "all");
  const offset = one(params, "offset") ?? "0";
  return {
    query: { ...DEFAULT_QUERY, project, scope,
      status: choice(one(params, "status"), ["open", "all", "todo", "progress", "testing", "done"], "open"),
      due: choice(one(params, "due"), ["any", "overdue", "today", "week", "none"], "any"),
      priority: choice(one(params, "priority"), ["any", "0", "1", "2", "3"], "any"),
      search: routeSearch(one(params, "q") ?? ""),
      signal: choice(one(params, "signal"), ["", "overdue", "critical", "soon", "unassigned"] as const, "") || null,
    },
    sort: choice(one(params, "sort"), ["urgency", "importance", "due", "updated"], "urgency"),
    view: choice(one(params, "view"), ["list", "board"], "list"),
    pageOffset: /^\d+$/.test(offset) && Number(offset) <= 1_000_000 ? Math.floor(Number(offset) / 50) * 50 : 0,
  };
}
export function taskHref(route: TaskRoute): string {
  const { query, sort, view, pageOffset } = route;
  const path = query.project === "all" ? `/tasks${query.scope === "all" ? "" : `/${query.scope}`}` : `/projects/${encodeURIComponent(query.project)}`;
  const params = new URLSearchParams();
  if (query.project !== "all" && query.scope !== "all") params.set("scope", query.scope);
  if (query.status !== "open") params.set("status", query.status);
  if (query.due !== "any") params.set("due", query.due);
  if (query.priority !== "any") params.set("priority", query.priority);
  if (query.search) params.set("q", query.search);
  if (query.signal) params.set("signal", query.signal);
  if (sort !== "urgency") params.set("sort", sort);
  if (view !== "list") params.set("view", view);
  if (pageOffset) params.set("offset", String(pageOffset));
  return `${path}${params.size ? `?${params}` : ""}`;
}
export function returnDestination(value: string | null): string {
  if (!value || /[\\#]|\p{Cc}/u.test(value) || !isTaskPath(value.split("?")[0])) return "/tasks";
  return taskHref(parseTaskRoute(value));
}
const QUERY_ACTIONS = new Set(["scopeSelected", "projectToggled", "statusFilterChanged", "dueFilterChanged", "priorityFilterChanged", "searchChanged", "signalToggled", "signalCleared", "sortChanged", "viewChanged", "pageChanged"]);
export function changeTaskRoute(route: TaskRoute, action: WorkspaceAction): TaskRoute | null {
  if (!QUERY_ACTIONS.has(action.type)) return null;
  const current = { ...initialWorkspaceState, ...route };
  const next = workspaceReducer(current, action);
  const leavesProject = action.type === "scopeSelected" && route.query.project !== "all";
  return { query: leavesProject ? { ...next.query, project: "all" } : next.query, sort: next.sort, view: next.view, pageOffset: leavesProject ? 0 : next.pageOffset ?? 0 };
}
