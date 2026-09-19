import { dueInfo, formatDueDate } from "../model/due";
import type { Task } from "../model/types";
import { urgency } from "../model/urgency";

export type CardTone = "danger" | "warn";

/** What a board card shows, derived once so the component holds no rules of its own. */
export interface CardView {
  done: boolean;
  dueLabel: string;
  /** The due chip's colour; null is the quiet, untinted chip. */
  dueTone: CardTone | null;
  /** Which mark leads the due chip: alert, clock or calendar. */
  dueMark: "overdue" | "soon" | "later";
  /** The strip down the card's left edge. */
  rail: CardTone | null;
  /** The rail pulses only for a P0 that is overdue or at risk. */
  blink: boolean;
  prioLabel: string;
  /** `hot` is the solid danger mark of a P0 at risk or overdue. */
  prioTone: "hot" | "p0" | "p1" | "p2" | "p3";
  stepsLabel: string | null;
  attachmentsLabel: string | null;
  unassigned: boolean;
}

export function cardView(task: Task, now: number): CardView {
  const u = urgency(task, now);
  const done = task.status === "done";
  const timed = u.overdue || u.today || u.soon;
  const hot = u.critical || (u.overdue && task.prio === 0);
  const stepsDone = task.steps.filter((s) => s.done).length;

  return {
    done,
    dueLabel: done && task.due ? formatDueDate(task.due) : dueInfo(task.due, now).label,
    dueTone: u.overdue ? "danger" : timed ? "warn" : null,
    dueMark: u.overdue ? "overdue" : timed ? "soon" : "later",
    rail: u.overdue || u.critical ? "danger" : timed ? "warn" : null,
    blink: u.blink,
    prioLabel: `P${task.prio}`,
    prioTone: hot ? "hot" : (`p${task.prio}` as CardView["prioTone"]),
    stepsLabel: task.steps.length > 0 ? `${stepsDone}/${task.steps.length}` : null,
    attachmentsLabel: task.attachments.length > 0 ? String(task.attachments.length) : null,
    unassigned: u.unassigned,
  };
}

/** Milliseconds between one card's entrance and the next one's, down a column. */
export const ENTRANCE_STEP_MS = 24;

const ENTRANCE_MAX_STEPS = 14;

export function entranceDelay(index: number): string {
  return `${Math.min(index, ENTRANCE_MAX_STEPS) * ENTRANCE_STEP_MS}ms`;
}
