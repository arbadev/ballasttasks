import type { DueDate } from "./types";

const DAY_MS = 864e5;

export interface DueInfo {
  label: string;
  overdue: boolean;
  isToday: boolean;
  /** Due today or within the next six days. */
  inWeek: boolean;
  /** Whole calendar days from today; negative when late, Infinity without a date. */
  diff: number;
}

/** Local noon of a calendar day: far enough from midnight that DST never shifts the day. */
function noon(date: Date): Date {
  const d = new Date(date);
  d.setHours(12, 0, 0, 0);
  return d;
}

function parse(due: DueDate): Date {
  const [y, m, d] = due.split("-").map(Number);
  return new Date(y, m - 1, d, 12, 0, 0, 0);
}

export function toDueDate(date: Date): DueDate {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The day `offset` days after `base` (today when omitted). */
export function dayFrom(offset: number, now: number, base?: DueDate): DueDate {
  const d = base ? parse(base) : noon(new Date(now));
  d.setDate(d.getDate() + offset);
  return toDueDate(d);
}

/** "Sep 25" */
export function formatDueDate(due: DueDate): string {
  return parse(due).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function dueInfo(due: DueDate | null, now: number): DueInfo {
  if (!due) return { label: "No date", overdue: false, isToday: false, inWeek: false, diff: Infinity };
  const date = parse(due);
  const diff = Math.round((date.getTime() - noon(new Date(now)).getTime()) / DAY_MS);
  if (diff < 0) return { label: `Overdue · ${-diff}d`, overdue: true, isToday: false, inWeek: false, diff };
  if (diff === 0) return { label: "Due today", overdue: false, isToday: true, inWeek: true, diff };
  if (diff === 1) return { label: "Due tomorrow", overdue: false, isToday: false, inWeek: true, diff };
  if (diff < 7) {
    const weekday = date.toLocaleDateString("en-US", { weekday: "short" });
    return { label: `Due ${weekday} · ${diff}d`, overdue: false, isToday: false, inWeek: true, diff };
  }
  return { label: `Due ${formatDueDate(due)}`, overdue: false, isToday: false, inWeek: false, diff };
}
