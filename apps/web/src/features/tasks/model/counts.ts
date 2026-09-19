import { dueInfo } from "./due";
import type { Task } from "./types";

export interface SidebarCounts {
  all: number;
  mine: number;
  overdue: number;
  /** Open tasks per project id; a project with none is absent. */
  byProject: Record<string, number>;
}

/** The sidebar counts open work only, whatever filters are applied to the main view. */
export function sidebarCounts(tasks: readonly Task[], context: { now: number; currentUserId: string }): SidebarCounts {
  const open = tasks.filter((t) => t.status !== "done");
  const byProject: Record<string, number> = {};
  for (const t of open) byProject[t.project] = (byProject[t.project] ?? 0) + 1;
  return {
    all: open.length,
    mine: open.filter((t) => t.assignee === context.currentUserId).length,
    overdue: open.filter((t) => dueInfo(t.due, context.now).overdue).length,
    byProject,
  };
}
