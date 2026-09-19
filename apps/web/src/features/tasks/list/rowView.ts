import { dueInfo, formatDueDate } from "../model/due";
import type { Task } from "../model/types";
import { urgency } from "../model/urgency";

export type DueTone = "danger" | "warn" | "later";
export type DueIcon = "overdue" | "soon" | "later";
export type Rail = "danger" | "warn" | "none";
/** `hot` is a P0 that is overdue or at risk: the one solid pill in the row. */
export type PriorityTone = "hot" | "danger" | "accent" | "neutral" | "muted";

export interface RowView {
  done: boolean;
  dueLabel: string;
  dueTone: DueTone;
  dueIcon: DueIcon;
  rail: Rail;
  blink: boolean;
  prioLabel: string;
  prioTone: PriorityTone;
  importance: number;
  /** The design accents the importance bar from 85 up. */
  importanceAccent: boolean;
  /** "1/3", or null for a task without steps. */
  stepsLabel: string | null;
  attachmentCount: number;
  needsOwner: boolean;
  /** Entrance stagger: 24ms per row, capped so a long list never waits. */
  delayMs: number;
}

const PRIORITY_TONES: PriorityTone[] = ["danger", "accent", "neutral", "muted"];
const STAGGER_MS = 24;
const STAGGER_CAP = 14;
const IMPORTANCE_ACCENT_FROM = 85;

/** What a list row shows for a task: every decision the design's `taskView` makes, and no markup. */
export function rowView(task: Task, now: number, index: number): RowView {
  const u = urgency(task, now);
  const done = task.status === "done";
  const timed = u.overdue || u.today || u.soon;
  const hot = u.critical || (u.overdue && task.prio === 0);

  return {
    done,
    dueLabel: done && task.due ? formatDueDate(task.due) : dueInfo(task.due, now).label,
    dueTone: u.overdue ? "danger" : timed ? "warn" : "later",
    dueIcon: u.overdue ? "overdue" : timed ? "soon" : "later",
    rail: u.overdue || u.critical ? "danger" : timed ? "warn" : "none",
    blink: u.blink,
    prioLabel: `P${task.prio}`,
    prioTone: hot ? "hot" : PRIORITY_TONES[task.prio],
    importance: task.importance,
    importanceAccent: task.importance >= IMPORTANCE_ACCENT_FROM,
    stepsLabel: task.steps.length > 0 ? `${task.steps.filter((s) => s.done).length}/${task.steps.length}` : null,
    attachmentCount: task.attachments.length,
    needsOwner: u.unassigned,
    delayMs: Math.min(index, STAGGER_CAP) * STAGGER_MS,
  };
}
