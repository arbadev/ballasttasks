import { dueInfo } from "./due";
import type { Task, TaskStatus } from "./types";
import { urgency } from "./urgency";

export type Scope = "all" | "mine" | "overdue";
/** "all" or a project id. */
export type ProjectFilter = string;
/** "open" is every status but Done; "all" is Everything. */
export type StatusFilter = "open" | "all" | TaskStatus;
export type DueFilter = "any" | "overdue" | "today" | "week" | "none";
export type PriorityFilter = "any" | "0" | "1" | "2" | "3";
export type SortBy = "urgency" | "importance" | "due" | "updated";
export type SignalId = "overdue" | "critical" | "soon" | "unassigned";

export interface TaskQuery {
  scope: Scope;
  project: ProjectFilter;
  status: StatusFilter;
  due: DueFilter;
  priority: PriorityFilter;
  search: string;
  /** The active Attention chip, if any. */
  signal: SignalId | null;
}

export const DEFAULT_QUERY: TaskQuery = {
  scope: "all",
  project: "all",
  status: "open",
  due: "any",
  priority: "any",
  search: "",
  signal: null,
};

export const DEFAULT_SORT: SortBy = "urgency";

export interface FilterContext {
  now: number;
  currentUserId: string;
  /** The board shows every status as a column, so it passes false. Defaults to true. */
  applyStatus?: boolean;
}

export function filterTasks(tasks: readonly Task[], query: TaskQuery, context: FilterContext): Task[] {
  const { now, currentUserId, applyStatus = true } = context;
  const q = query.search.trim().toLowerCase();

  return tasks.filter((t) => {
    const di = dueInfo(t.due, now);
    const open = t.status !== "done";
    if (query.project !== "all" && t.project !== query.project) return false;
    if (query.scope === "mine" && t.assignee !== currentUserId) return false;
    if (query.scope === "overdue" && !(di.overdue && open)) return false;
    if (applyStatus) {
      if (query.status === "open" && !open) return false;
      if (query.status !== "open" && query.status !== "all" && t.status !== query.status) return false;
    }
    if (query.due === "overdue" && !(di.overdue && open)) return false;
    if (query.due === "today" && !di.isToday) return false;
    if (query.due === "week" && !di.inWeek) return false;
    if (query.due === "none" && t.due) return false;
    if (query.priority !== "any" && String(t.prio) !== query.priority) return false;
    if (q && !(t.title.toLowerCase().includes(q) || t.description.toLowerCase().includes(q))) return false;
    if (query.signal) {
      const u = urgency(t, now);
      if (query.signal === "overdue" && !u.overdue) return false;
      if (query.signal === "critical" && !u.critical) return false;
      if (query.signal === "soon" && !(!u.overdue && (u.today || u.soon))) return false;
      if (query.signal === "unassigned" && !u.unassigned) return false;
    }
    return true;
  });
}

const dueTime = (t: Task) => (t.due ? Date.parse(`${t.due}T12:00:00`) : Infinity);

/** Returns a sorted copy; ties keep their input order. */
export function sortTasks(tasks: readonly Task[], sortBy: SortBy, now: number): Task[] {
  const comparators: Record<SortBy, (a: Task, b: Task) => number> = {
    urgency: (a, b) => urgency(b, now).score - urgency(a, now).score,
    importance: (a, b) => b.importance - a.importance,
    due: (a, b) => {
      const byDate = dueTime(a) - dueTime(b);
      // Infinity - Infinity is NaN: two undated tasks fall through to importance.
      return byDate || b.importance - a.importance;
    },
    updated: (a, b) => b.updatedAt - a.updatedAt,
  };
  return [...tasks].sort(comparators[sortBy]);
}

export function selectTasks(tasks: readonly Task[], query: TaskQuery, sortBy: SortBy, context: FilterContext): Task[] {
  return sortTasks(filterTasks(tasks, query, context), sortBy, context.now);
}
