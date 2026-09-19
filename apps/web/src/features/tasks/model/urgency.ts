import { dueInfo } from "./due";
import type { Task } from "./types";

/** Days ahead that count as "due soon" before priority widens the window. */
export const DEFAULT_SOON_WINDOW = 2;

export interface Urgency {
  open: boolean;
  overdue: boolean;
  today: boolean;
  soon: boolean;
  /** An open P0 due inside its window: the "P0 at risk" signal. */
  critical: boolean;
  unassigned: boolean;
  score: number;
  diff: number;
  /** The rail and banner pulse only for a P0 that is overdue or at risk. */
  blink: boolean;
}

/**
 * One urgency model for every surface: rows, cards, the Attention strip, the detail banner
 * and the default sort. P0 widens the soon window by two days and P1 by one.
 */
export function urgency(task: Task, now: number, soonWindow: number = DEFAULT_SOON_WINDOW): Urgency {
  const open = task.status !== "done";
  const has = task.due !== null;
  const diff = dueInfo(task.due, now).diff;
  const win = Math.max(0, soonWindow) + (task.prio === 0 ? 2 : task.prio === 1 ? 1 : 0);
  const overdue = open && has && diff < 0;
  const today = open && has && diff === 0;
  const soon = open && has && diff > 0 && diff <= win;
  const critical = open && has && task.prio === 0 && diff >= 0 && diff <= win;
  const unassigned = open && !task.assignee;

  let score = 0;
  if (overdue) score = 1000 + Math.min(-diff, 30) * 10;
  else if (critical) score = 800 + (win - diff) * 10;
  else if (today) score = 600;
  else if (soon) score = 400 + (win - diff) * 10;
  else if (open && has) score = Math.max(0, 200 - diff * 5);
  score += (unassigned ? 40 : 0) + task.importance / 10 + (3 - task.prio) * 3;

  return { open, overdue, today, soon, critical, unassigned, score, diff, blink: task.prio === 0 && (overdue || critical) };
}
