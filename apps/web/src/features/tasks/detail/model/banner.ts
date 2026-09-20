import type { Task } from "../../model/types";
import { urgency } from "../../model/urgency";

export interface Banner {
  text: string;
  tone: "danger" | "warn" | "info";
  /** The dot pulses for a P0 that is overdue or at risk, like the row's rail. */
  blink: boolean;
  canAssign: boolean;
  canReschedule: boolean;
  /** Offered only while there is nothing to lose: no steps yet and no generation around. */
  canDraft: boolean;
}

const days = (n: number) => `${n} day${n === 1 ? "" : "s"}`;

/** Why the open task needs attention, in the design's words; null when it does not. */
export function bannerFor(task: Task, now: number, hasGeneration: boolean): Banner | null {
  const u = urgency(task, now);
  const parts: string[] = [];
  let tone: Banner["tone"] | null = null;

  if (u.overdue) {
    parts.push(`Overdue by ${days(-u.diff)}`);
    tone = "danger";
  } else if (u.critical) {
    parts.push(u.today ? "P0 due today" : `P0 due in ${days(u.diff)}`);
    tone = "danger";
  } else if (u.today) {
    parts.push("Due today");
    tone = "warn";
  } else if (u.soon) {
    parts.push(`Due in ${days(u.diff)}`);
    tone = "warn";
  }
  if (u.unassigned) {
    parts.push(parts.length ? "needs an owner" : "Needs an owner");
    tone ??= "info";
  }
  if (!tone) return null;

  return {
    text: parts.join(" · "),
    tone,
    blink: u.blink,
    canAssign: u.unassigned,
    canReschedule: u.overdue || u.today || u.soon,
    canDraft: (u.critical || u.overdue) && task.steps.length === 0 && !hasGeneration,
  };
}
