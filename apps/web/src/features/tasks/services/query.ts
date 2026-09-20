import type { SidebarCounts } from "../model/counts";
import type { SignalId, SortBy, TaskQuery } from "../model/filter";
import type { Task, TaskStatus } from "../model/types";

export interface TaskPageRequest {
  query: TaskQuery;
  sort: SortBy;
  board: boolean;
  offset: number;
  limit?: number;
}
export interface TaskPage {
  tasks: Task[];
  total: number;
  /** The header intentionally counts the list's status filter even on the board. */
  headerTotal: number;
  offset: number;
  limit: number;
  sidebar: SidebarCounts;
  signals: Record<SignalId, number>;
  columns?: Record<TaskStatus, number>;
  /** Across all statuses and filters, for the empty-project invitation. */
  projectHasTasks?: boolean;
}
export type TaskPageInfo = Omit<TaskPage, "tasks"> & { ids: string[]; project: string };
