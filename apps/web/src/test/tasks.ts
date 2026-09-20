import type { Task } from "@/features/tasks/model/types";

/** Friday 18 September 2026, 15:00 UTC: the fixed injected instant of the task tests. */
export const NOW = Date.parse("2026-09-18T15:00:00Z");

const DAY_MS = 864e5;

/** The calendar day `offset` days from NOW, as the model's YYYY-MM-DD due date. */
export function due(offset: number): string {
  return new Date(NOW + offset * DAY_MS).toISOString().slice(0, 10);
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
