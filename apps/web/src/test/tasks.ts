import type { Task } from "@/features/tasks/model/types";

/** Friday 18 September 2026, 10:00 local time: the fixed "now" of the task tests. */
export const NOW = new Date(2026, 8, 18, 10, 0, 0, 0).getTime();

const DAY_MS = 864e5;

/** The calendar day `offset` days from NOW, as the model's YYYY-MM-DD due date. */
export function due(offset: number): string {
  const d = new Date(NOW);
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A minimal open, assigned, undated task; tests override only what they are about. */
export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "A task",
    description: "",
    status: "todo",
    project: "ballast",
    assignee: "ab",
    due: null,
    prio: 2,
    importance: 50,
    steps: [],
    attachments: [],
    activity: [],
    createdAt: NOW - 3 * DAY_MS,
    updatedAt: NOW - DAY_MS,
    ...overrides,
  };
}
