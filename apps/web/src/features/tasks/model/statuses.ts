import type { TaskStatus } from "./types";

export interface StatusDefinition {
  id: TaskStatus;
  name: string;
  /** Which token colours the status dot and badge. */
  tone: "muted" | "accent" | "warn" | "ok";
}

/** The four statuses in workflow (and board column) order. */
export const STATUSES: readonly StatusDefinition[] = [
  { id: "todo", name: "To Do", tone: "muted" },
  { id: "progress", name: "In Progress", tone: "accent" },
  { id: "testing", name: "Testing", tone: "warn" },
  { id: "done", name: "Done", tone: "ok" },
];

export function statusName(id: TaskStatus): string {
  return STATUSES.find((s) => s.id === id)?.name ?? id;
}
